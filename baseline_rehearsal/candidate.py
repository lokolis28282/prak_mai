"""Build and verify an ODE target-schema initial-baseline rehearsal database."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import unicodedata
import uuid
from typing import Any

from ode.application.config import DatabaseConfig, Environment
from ode.infrastructure.database import compute_schema_hash
from ode.infrastructure.migrations import MigrationRunner
from ode.infrastructure.paths import DDL_ROOT

from inventory.shared.validators import WarehouseError
from inventory.warehouse.baseline.models import ActorSnapshot
from inventory.warehouse.baseline.workspace import WorkspaceStore


APPLICATION_ID = 0x4F444531
SCHEMA_VERSION = 8
_NAMESPACE = uuid.UUID("72d63b94-c21f-4cdb-9849-bc87d4258603")


def _public_id(session_id: str, kind: str, key: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{session_id}:{kind}:{key}"))


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: str | bytes) -> bytes:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).digest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _key(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _timestamp_us(value: str) -> int:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(candidate)
    if parsed.tzinfo is None:
        raise WarehouseError("Inventory timestamp не содержит timezone")
    return int(parsed.timestamp() * 1_000_000)


def _candidate_config(path: Path, *, read_only: bool) -> DatabaseConfig:
    return DatabaseConfig.create(
        path,
        environment=Environment.TEST,
        read_only=read_only,
        expected_schema_version=SCHEMA_VERSION,
        expected_application_id=APPLICATION_ID,
        allow_external_dev_path=True,
    )


def _active_resolutions(db: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    return [dict(row) for row in db.execute(
        """SELECT z.*,r.source_row_number,f.code AS finding_code,f.field_code
             FROM preview_resolutions z
             JOIN preview_runs p ON p.run_id=z.run_id
             LEFT JOIN preview_rows r ON r.row_id=z.row_id
             LEFT JOIN preview_findings f ON f.finding_id=z.finding_id
            WHERE p.session_id=?
              AND NOT EXISTS (
                  SELECT 1 FROM preview_resolutions n
                   WHERE n.supersedes_resolution_id=z.resolution_id
              )
            ORDER BY z.resolution_id""",
        (session_id,),
    )]


def _load_plan(
    workspace_path: Path, session: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    with closing(WorkspaceStore(workspace_path).connect(read_only=True)) as db:
        run_id = str(session["active_run_id"] or "")
        run = db.execute(
            "SELECT * FROM preview_runs WHERE run_id=? AND run_status='READY'",
            (run_id,),
        ).fetchone()
        if run is None or session["session_status"] != "READY_FOR_APPROVAL":
            raise WarehouseError("Candidate требует READY_FOR_APPROVAL Preview")
        if db.execute(
            "SELECT 1 FROM preview_findings WHERE run_id=? AND blocking=1 AND finding_status='OPEN' LIMIT 1",
            (run_id,),
        ).fetchone():
            raise WarehouseError("Candidate запрещён при unresolved BLOCKING findings")
        rows = [dict(row) for row in db.execute(
            "SELECT * FROM preview_rows WHERE run_id=? ORDER BY source_row_number,row_id",
            (run_id,),
        )]
        findings = [dict(row) for row in db.execute(
            "SELECT * FROM preview_findings WHERE run_id=? ORDER BY finding_id", (run_id,)
        )]
        resolutions = _active_resolutions(db, session["session_id"])
    for row in rows:
        row["raw"] = json.loads(row.pop("raw_payload_json"))
        row["normalized"] = json.loads(row.pop("normalized_payload_json"))
    return rows, findings, resolutions


def _seed_security(db: sqlite3.Connection, actor: ActorSnapshot, now: int) -> None:
    db.execute(
        "INSERT INTO roles(role_id,code,display_name,active,created_at_us) VALUES (1,'admin','Administrator',1,?)",
        (now,),
    )
    db.execute(
        "INSERT INTO permissions(permission_code,display_name,risk_level,active,created_at_us) VALUES ('INVENTORY_APPROVE','Approve inventory','SENSITIVE',1,?)",
        (now,),
    )
    db.execute(
        """INSERT INTO users(user_id,public_id,login_key,display_name,password_hash,status,
                  must_change_password,credential_version,created_at_us,updated_at_us)
           VALUES (1,?,'candidate.rehearsal',?,'$argon2id$candidate-rehearsal-not-a-credential',
                   'ACTIVE',1,1,?,?)""",
        (_public_id(actor.actor_id, "user", actor.actor_id), actor.display, now, now),
    )
    db.execute(
        "INSERT INTO user_roles(user_role_id,user_id,role_id,assigned_by_user_id,assigned_at_us) VALUES (1,1,1,1,?)",
        (now,),
    )
    db.execute(
        "INSERT INTO role_permissions(role_id,permission_code,granted_at_us,granted_by_user_id) VALUES (1,'INVENTORY_APPROVE',?,1)",
        (now,),
    )


def _effective(row: dict[str, Any]) -> dict[str, str]:
    result = dict(row["raw"])
    result.update(row["normalized"].get("resolution_overrides") or {})
    return {str(key): str(value) for key, value in result.items()}


def build_candidate(
    workspace_path: Path,
    session: dict[str, Any],
    output: Path,
    actor: ActorSnapshot,
    *,
    correlation_id: str,
) -> dict[str, Any]:
    """Create an absent disposable target DB; never publishes it as runtime."""

    rows, findings, resolutions = _load_plan(workspace_path, session)
    included = [
        row for row in rows
        if row["normalized"].get("resolution_disposition") not in {
            "EXCLUDE_ROW", "QUARANTINE_ROW", "MARK_DUPLICATE"
        }
    ]
    if not included:
        raise WarehouseError("Candidate не может содержать ноль baseline rows")
    choices: dict[int, set[str]] = {}
    for resolution in resolutions:
        choices.setdefault(int(resolution["source_row_number"]), set()).add(
            str(resolution["action_code"])
        )
    for row in included:
        actions = choices.get(int(row["source_row_number"]), set())
        if "DEFER_ROW" in actions:
            raise WarehouseError("Candidate запрещён при DEFER_ROW")
        if "CHOOSE_CATALOG_ITEM" not in actions:
            raise WarehouseError(
                f"Строка {row['source_row_number']}: требуется CHOOSE_CATALOG_ITEM"
            )
        if row["stock_subject_kind"] == "SERIALIZED" and not (
            {"CREATE_NEW_EQUIPMENT_CANDIDATE", "LINK_EXISTING_EQUIPMENT"} & actions
        ):
            raise WarehouseError(
                f"Строка {row['source_row_number']}: требуется equipment resolution"
            )
        if "LINK_EXISTING_EQUIPMENT" in actions:
            raise WarehouseError("LINK_EXISTING_EQUIPMENT требует future Equipment Query Port")
    output = Path(output)
    if output.is_symlink():
        raise WarehouseError("Candidate path не может быть symlink")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if output.parent.is_symlink() or not output.parent.is_dir():
        raise WarehouseError("Candidate directory должен быть реальным каталогом")
    output = output.parent.resolve(strict=True) / output.name
    output.parent.chmod(0o700)
    if output.exists():
        report = validate_candidate(output)
        expected = bytes(session["preview_digest"]).hex()
        if report["preview_digest"] != expected:
            raise WarehouseError("Существующий candidate относится к другому Preview")
        return report
    runner = MigrationRunner(_candidate_config(output, read_only=False))
    runner.create()
    now = max(time.time_ns() // 1_000, 1)
    try:
        with closing(sqlite3.connect(output)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            _seed_security(db, actor, now)

            domain_ids = {"STOCK_CONDITION": 1, "VENDOR": 2, "MODEL": 3}
            for code, domain_id in domain_ids.items():
                db.execute(
                    """INSERT INTO reference_domains(domain_id,code,display_name,
                              normalization_policy,scope_policy,status,created_at_us,updated_at_us)
                       VALUES (?,?,?,'CONSERVATIVE_TEXT','GLOBAL','ACTIVE',?,?)""",
                    (domain_id, code, code.replace("_", " ").title(), now, now),
                )
            conditions = sorted({_effective(row).get("Condition", "AVAILABLE").upper() for row in included})
            condition_ids: dict[str, int] = {}
            next_value = 1
            for condition in conditions:
                condition_ids[condition] = next_value
                db.execute(
                    """INSERT INTO reference_values(value_id,public_id,domain_id,code,display_name,
                              normalized_key,scope_key,status,source_type,source_ref,created_by_user_id,
                              created_at_us,updated_at_us)
                       VALUES (?,?,?,?,?,?,'GLOBAL','APPROVED','FULL_INVENTORY',?,1,?,?)""",
                    (next_value, _public_id(session["session_id"], "condition", condition), 1,
                     condition, condition, condition, session["public_id"], now, now),
                )
                next_value += 1

            vendor_ids: dict[str, int] = {}
            model_ids: dict[str, int] = {}
            for domain, values, bucket in (
                (2, sorted({_effective(row).get("Vendor", "UNSPECIFIED") or "UNSPECIFIED" for row in included}), vendor_ids),
                (3, sorted({_effective(row).get("Model", "UNSPECIFIED") or "UNSPECIFIED" for row in included}), model_ids),
            ):
                for value in values:
                    bucket[value] = next_value
                    db.execute(
                        """INSERT INTO reference_values(value_id,public_id,domain_id,code,display_name,
                                  normalized_key,scope_key,status,source_type,source_ref,created_by_user_id,
                                  created_at_us,updated_at_us)
                           VALUES (?,?,?,?,?,?,'GLOBAL','APPROVED','FULL_INVENTORY',?,1,?,?)""",
                        (next_value, _public_id(session["session_id"], f"reference-{domain}", value),
                         domain, f"V{next_value}", value, _key(value), session["public_id"], now, now),
                    )
                    next_value += 1

            uom_specs = {
                "шт": ("EA", "Each", "COUNT", 0),
                "м": ("M", "Metre", "LENGTH", 3),
            }
            uom_ids: dict[str, int] = {}
            for index, raw_uom in enumerate(sorted({_effective(row)["UOM"] for row in included}), 1):
                if raw_uom not in uom_specs:
                    raise WarehouseError(f"Candidate UOM не поддерживается: {raw_uom}")
                code, display, dimension, scale = uom_specs[raw_uom]
                uom_ids[raw_uom] = index
                db.execute(
                    "INSERT INTO uoms(uom_id,code,display_name,dimension,scale,status,created_at_us) VALUES (?,?,?,?,?,'ACTIVE',?)",
                    (index, code, display, dimension, scale, now),
                )

            warehouse_ids: dict[str, int] = {}
            location_ids: dict[tuple[str, str], int] = {}
            for index, warehouse in enumerate(sorted({_effective(row)["WarehouseCode"] for row in included}), 1):
                warehouse_ids[warehouse] = index
                db.execute(
                    "INSERT INTO warehouses(warehouse_id,public_id,code,display_name,status,created_at_us,updated_at_us) VALUES (?,?,?,?,'ACTIVE',?,?)",
                    (index, _public_id(session["session_id"], "warehouse", warehouse), warehouse, warehouse, now, now),
                )
            for index, pair in enumerate(sorted({(_effective(row)["WarehouseCode"], _effective(row)["LocationCode"]) for row in included}), 1):
                warehouse, location = pair
                location_ids[pair] = index
                db.execute(
                    """INSERT INTO warehouse_locations(location_id,public_id,warehouse_id,code,
                              display_name,location_kind,status,created_at_us,updated_at_us)
                       VALUES (?,?,?,?,?,'SHELF','ACTIVE',?,?)""",
                    (index, _public_id(session["session_id"], "location", f"{warehouse}:{location}"),
                     warehouse_ids[warehouse], location, location, now, now),
                )

            catalog_ids: dict[tuple[str, ...], int] = {}
            for row in included:
                value = _effective(row)
                catalog_key = (
                    value["ItemKind"].upper(), value.get("Vendor", ""), value.get("Model", ""),
                    value.get("PartNumber", ""), value.get("Description", ""), value["UOM"],
                )
                if catalog_key not in catalog_ids:
                    catalog_id = len(catalog_ids) + 1
                    catalog_ids[catalog_key] = catalog_id
                    vendor = value.get("Vendor", "") or "UNSPECIFIED"
                    model = value.get("Model", "") or "UNSPECIFIED"
                    db.execute(
                        """INSERT INTO catalog_items(catalog_item_id,public_id,item_kind,vendor_value_id,
                                  vendor_scope_key,model_value_id,part_number_raw,part_number_key,
                                  default_uom_id,display_name,status,source_ref,created_at_us,updated_at_us)
                           VALUES (?,?,?,?,?,?,?,?,?,?,'APPROVED',?,?,?)""",
                        (catalog_id, _public_id(session["session_id"], "catalog", _json(catalog_key)),
                         catalog_key[0], vendor_ids[vendor], f"VENDOR:{vendor_ids[vendor]}",
                         model_ids[model], value.get("PartNumber", ""), _key(value.get("PartNumber", "")),
                         uom_ids[value["UOM"]], value.get("Description", "") or value.get("PartNumber", "Unnamed"),
                         session["public_id"], now, now),
                    )

            source_sha = bytes(session["source_sha256"])
            preview_digest = bytes(session["preview_digest"])
            import_public = _public_id(session["session_id"], "import", preview_digest.hex())
            db.execute(
                """INSERT INTO import_commits(import_commit_id,public_id,import_kind,source_object_key,
                          source_file_name,source_sha256,source_size_bytes,template_version,parser_version,
                          schema_version,preview_digest,manifest_json,committed_by_user_id,actor_display_name,
                          committed_at_us,idempotency_key,correlation_id)
                   VALUES (1,?,'FULL_INVENTORY',?,?,?,?,?,?,?, ?,?,1,?,?,?,?)""",
                (import_public, str(session["source_opaque_key"]), str(session["source_original_filename"]),
                 source_sha, int(session["source_size_bytes"]), str(session["template_version"]),
                 "inventory-xlsx/1", str(SCHEMA_VERSION), preview_digest,
                 _json({"warehouse": session["warehouse_scope_raw"], "rehearsal": True}), actor.display,
                 now, f"candidate:{preview_digest.hex()}", correlation_id),
            )

            row_links: dict[int, int] = {}
            equipment_id = 0
            snapshot_specs: list[dict[str, Any]] = []
            seen_bulk: set[tuple[Any, ...]] = set()
            for link_id, row in enumerate(included, 1):
                value = _effective(row)
                row_links[int(row["source_row_number"])] = link_id
                catalog_key = (
                    value["ItemKind"].upper(), value.get("Vendor", ""), value.get("Model", ""),
                    value.get("PartNumber", ""), value.get("Description", ""), value["UOM"],
                )
                catalog_id = catalog_ids[catalog_key]
                target_type = "CATALOG_ITEM"
                target_public = _public_id(session["session_id"], "catalog", _json(catalog_key))
                equipment = None
                if value["ItemKind"].upper() == "SERIALIZED":
                    equipment_id += 1
                    equipment = equipment_id
                    target_type = "EQUIPMENT"
                    target_public = _public_id(session["session_id"], "equipment", str(row["source_row_number"]))
                    db.execute(
                        """INSERT INTO equipment(equipment_id,public_id,catalog_item_id,lifecycle_status,
                                  identity_status,created_at_us,updated_at_us)
                           VALUES (?, ?, ?, 'ACTIVE','VERIFIED',?,?)""",
                        (equipment, target_public, catalog_id, now, now),
                    )
                    serial = value.get("SerialNumber", "")
                    db.execute(
                        """INSERT INTO equipment_identities(equipment_id,kind,raw_value,normalized_key,
                                  scope_key,status,valid_from_us,source_type,source_ref,changed_by_user_id,reason)
                           VALUES (?,'SERIAL_NUMBER',?,?,'UNSCOPED','ACTIVE',?,'FULL_INVENTORY',?,1,'initial baseline')""",
                        (equipment, serial, _key(serial), now, session["public_id"]),
                    )
                    inventory_number = value.get("InventoryNumber", "")
                    if inventory_number:
                        db.execute(
                            """INSERT INTO equipment_identities(equipment_id,kind,raw_value,normalized_key,
                                      scope_key,status,valid_from_us,source_type,source_ref,changed_by_user_id,reason)
                               VALUES (?,'INVENTORY_NUMBER',?,?,'GLOBAL','ACTIVE',?,'FULL_INVENTORY',?,1,'initial baseline')""",
                            (equipment, inventory_number, _key(inventory_number), now, session["public_id"]),
                        )
                db.execute(
                    """INSERT INTO import_row_links(row_link_id,import_commit_id,source_sheet,
                              source_row_number,source_row_key,source_row_sha256,raw_payload_json,
                              target_type,target_public_id,transform_version)
                       VALUES (?,1,'Inventory',?,?,?,?,?,?,'full-inventory/0.14')""",
                    (link_id, int(row["source_row_number"]), str(row["source_row_id"]),
                     bytes(row["row_sha256"]), _json(row["raw"]), target_type, target_public),
                )
                scale = uom_specs[value["UOM"]][3]
                quantity = Decimal(value["Quantity"]) * (Decimal(10) ** scale)
                if quantity != quantity.to_integral_value():
                    raise WarehouseError(f"Строка {row['source_row_number']}: quantity не соответствует UOM scale")
                spec = {
                    "row_link_id": link_id, "equipment_id": equipment,
                    "catalog_item_id": None if equipment else catalog_id,
                    "warehouse_id": warehouse_ids[value["WarehouseCode"]],
                    "location_id": location_ids[(value["WarehouseCode"], value["LocationCode"])],
                    "condition_value_id": condition_ids[value["Condition"].upper()],
                    "uom_id": uom_ids[value["UOM"]], "quantity_minor": int(quantity),
                    "identity": {"serial_raw": value.get("SerialNumber", ""), "source_row": row["source_row_number"]},
                }
                if equipment is None:
                    bulk_key = tuple(spec[key] for key in (
                        "catalog_item_id", "warehouse_id", "location_id", "condition_value_id", "uom_id"
                    )) + (value.get("Lot", ""),)
                    if bulk_key in seen_bulk:
                        raise WarehouseError("Bulk rows требуют предварительной агрегации по stock key")
                    seen_bulk.add(bulk_key)
                snapshot_specs.append(spec)

            for finding in findings:
                checksum = bytes(finding["finding_checksum"])
                db.execute(
                    """INSERT OR IGNORE INTO import_findings(import_commit_id,row_link_id,code,severity,
                              was_blocking,evidence_json,finding_checksum)
                       VALUES (1,?,?,?,?,?,?)""",
                    (row_links.get(int(next((r["source_row_number"] for r in rows if r["row_id"] == finding["row_id"]), 0))),
                     str(finding["code"]), str(finding["severity"]), int(finding["blocking"]),
                     str(finding["evidence_json"]), checksum),
                )
            for resolution in resolutions:
                link_id = row_links.get(int(resolution["source_row_number"]))
                if link_id is None:
                    continue
                db.execute(
                    """INSERT INTO import_resolutions(import_commit_id,row_link_id,action_code,target_type,
                              target_public_id,reason,actor_user_id,actor_display_name,resolved_at_us,resolution_checksum)
                       VALUES (1,?,?,'PREVIEW_ROW',?,?,1,?,?,?)""",
                    (link_id, str(resolution["action_code"]), resolution["target_public_id"],
                     str(resolution["reason"]), str(resolution["actor_display_name"]),
                     int(resolution["created_at_us"]), bytes(resolution["resolution_checksum"])),
                )

            count_started = _timestamp_us(str(session["count_started_at"]))
            count_finished = _timestamp_us(str(session["count_finished_at"]))
            freeze = count_started
            approved_at = max(now, count_finished)
            db.execute(
                """INSERT INTO inventory_sessions(session_id,public_id,import_commit_id,scope_type,
                          scope_json,status,source_sha256,template_version,parser_version,schema_version,
                          preview_digest,freeze_ledger_cutoff,freeze_started_at_us,effective_at_us,
                          count_started_at_us,count_finished_at_us,approved_by_user_id,actor_display_name,
                          approved_at_us,approval_idempotency_key,created_at_us,updated_at_us)
                   VALUES (1,?,1,'FULL','{"boundary":"GLOBAL","rehearsal":true}','APPROVED',
                           ?,?,?,?, ?,0,?,?,?, ?,1,?,?,?, ?,?)""",
                (_public_id(session["session_id"], "inventory-session", preview_digest.hex()), source_sha,
                 str(session["template_version"]), "inventory-xlsx/1", str(SCHEMA_VERSION), preview_digest,
                 freeze, freeze, count_started, count_finished, actor.display, approved_at,
                 f"rehearsal:{preview_digest.hex()}", now, approved_at),
            )
            content = _sha(_json(snapshot_specs))
            totals: dict[str, int] = {}
            for spec in snapshot_specs:
                code = next(raw for raw, uid in uom_ids.items() if uid == spec["uom_id"])
                totals[code] = totals.get(code, 0) + int(spec["quantity_minor"])
            snapshot_public = _public_id(session["session_id"], "snapshot", preview_digest.hex())
            db.execute(
                """INSERT INTO inventory_snapshots(snapshot_id,public_id,session_id,ledger_cutoff,
                          effective_at_us,status,is_active,item_count,totals_json,content_checksum,
                          approved_by_user_id,actor_display_name,approved_at_us)
                   VALUES (1,?,1,0,?,'APPROVED',1,?,?,?,1,?,?)""",
                (snapshot_public, freeze, len(snapshot_specs), _json(totals), content, actor.display, approved_at),
            )
            row_checksums: list[bytes] = []
            for item_id, spec in enumerate(snapshot_specs, 1):
                row_checksum = _sha(_json(spec))
                row_checksums.append(row_checksum)
                db.execute(
                    """INSERT INTO inventory_snapshot_items(snapshot_item_id,snapshot_id,row_link_id,
                              equipment_id,catalog_item_id,warehouse_id,location_id,condition_value_id,
                              uom_id,quantity_minor,identity_evidence_json,row_checksum)
                       VALUES (?,1,?,?,?,?,?,?,?,?,?,?)""",
                    (item_id, spec["row_link_id"], spec["equipment_id"], spec["catalog_item_id"],
                     spec["warehouse_id"], spec["location_id"], spec["condition_value_id"],
                     spec["uom_id"], spec["quantity_minor"], _json(spec["identity"]), row_checksum),
                )
            projection_checksum = _sha(b"".join(row_checksums))
            db.execute(
                """INSERT INTO balance_projection_versions(projection_version_id,public_id,snapshot_id,
                          build_status,built_through_sequence,row_count,total_checksum,created_at_us,
                          ready_at_us,activated_at_us)
                   VALUES (1,?,1,'ACTIVE',0,?,?,?, ?,?)""",
                (_public_id(session["session_id"], "projection", preview_digest.hex()),
                 len(snapshot_specs), projection_checksum, approved_at, approved_at, approved_at),
            )
            for item_id, spec in enumerate(snapshot_specs, 1):
                db.execute(
                    """INSERT INTO balance_projection_rows(projection_row_id,projection_version_id,
                              equipment_id,catalog_item_id,warehouse_id,location_id,condition_value_id,
                              uom_id,quantity_minor,last_applied_sequence,row_checksum)
                       VALUES (?,1,?,?,?,?,?,?,?,0,?)""",
                    (item_id, spec["equipment_id"], spec["catalog_item_id"], spec["warehouse_id"],
                     spec["location_id"], spec["condition_value_id"], spec["uom_id"],
                     spec["quantity_minor"], row_checksums[item_id - 1]),
                )
            db.execute(
                """UPDATE app_state SET balance_state='ACTIVE',active_snapshot_id=1,
                          active_projection_version_id=1,state_version=state_version+1,updated_at_us=?
                     WHERE singleton_id=1 AND balance_state='NOT_INITIALIZED'""",
                (approved_at,),
            )
            event_hash = _sha(_json({"action": "INVENTORY_APPROVED_REHEARSAL", "snapshot": snapshot_public}))
            db.execute(
                """INSERT INTO audit_events(public_id,occurred_at_us,action_code,outcome,actor_user_id,
                          actor_display_name,actor_role_code,permission_code,correlation_id,subject_type,
                          subject_public_id,details_json,event_hash)
                   VALUES (?,?, 'INVENTORY_APPROVED_REHEARSAL','SUCCESS',1,?,'admin',
                           'INVENTORY_APPROVE',?,'INVENTORY_SNAPSHOT',?,'{"rehearsal":true}',?)""",
                (_public_id(session["session_id"], "audit", preview_digest.hex()), approved_at,
                 actor.display, correlation_id, snapshot_public, event_hash),
            )
            db.commit()
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        os.chmod(output, 0o600)
        return validate_candidate(output)
    except Exception:
        output.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm", "-journal"):
            Path(str(output) + suffix).unlink(missing_ok=True)
        raise


def validate_candidate(path: Path) -> dict[str, Any]:
    path = path.resolve(strict=True)
    for suffix in ("-wal", "-shm", "-journal"):
        if Path(str(path) + suffix).exists():
            raise WarehouseError("Candidate содержит SQLite sidecar")
    runner = MigrationRunner(_candidate_config(path, read_only=True))
    status = runner.migration_status()
    if not status.ready:
        raise WarehouseError("Candidate migration registry не готов")
    with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        integrity = str(db.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = len(db.execute("PRAGMA foreign_key_check").fetchall())
        schema_hash = compute_schema_hash(db)
        if integrity != "ok" or foreign_keys or schema_hash != runner.manifest.approved_schema_hash:
            raise WarehouseError("Candidate integrity/FK/schema verification failed")
        invariants = runner._execute_proof(db, DDL_ROOT / "verify_domain_invariants.sql")
        violations = {name: int(value) for name, value in invariants if int(value) != 0}
        if violations:
            raise WarehouseError("Candidate domain invariants failed: " + ", ".join(violations))
        state = db.execute(
            "SELECT balance_state,active_snapshot_id,active_projection_version_id FROM app_state WHERE singleton_id=1"
        ).fetchone()
        if state != ("ACTIVE", 1, 1):
            raise WarehouseError("Candidate baseline state не ACTIVE")
        difference = int(db.execute(
            """SELECT count(*) FROM (
                   SELECT equipment_id,catalog_item_id,warehouse_id,location_id,
                          condition_value_id,lot_key,uom_id,quantity_minor
                     FROM inventory_snapshot_items WHERE snapshot_id=1
                   EXCEPT
                   SELECT equipment_id,catalog_item_id,warehouse_id,location_id,
                          condition_value_id,lot_key,uom_id,quantity_minor
                     FROM balance_projection_rows WHERE projection_version_id=1
               )"""
        ).fetchone()[0])
        if difference:
            raise WarehouseError("Candidate projection не совпадает с snapshot")
        row_count = int(db.execute("SELECT count(*) FROM inventory_snapshot_items").fetchone()[0])
        preview_digest = bytes(db.execute("SELECT preview_digest FROM import_commits WHERE import_commit_id=1").fetchone()[0]).hex()
    digest = _file_sha256(path)
    return {
        "status": "REHEARSAL_READY",
        "path": str(path),
        "sha256": digest,
        "size_bytes": path.stat().st_size,
        "permissions": oct(path.stat().st_mode & 0o777),
        "preview_digest": preview_digest,
        "snapshot_item_count": row_count,
        "projection_difference_count": 0,
        "verification": {
            "schema_hash": schema_hash,
            "integrity_result": integrity,
            "foreign_key_violations": foreign_keys,
            "domain_invariants": {name: int(value) for name, value in invariants},
        },
        "publish_available": False,
    }
