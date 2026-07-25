"""Build the disposable Stage 0.13.3A reference/staging candidate.

The builder never initializes or writes the working ODE database.  It reads
security rows through a SQLite-enforced read-only connection, creates a fresh
current production schema in a temporary file and then adds the candidate-only
schema from :mod:`inventory.migration.staging_schema`.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any, Iterable, Iterator, Mapping

from inventory.db import DEFAULT_DB_PATH, SCHEMA as PRODUCTION_SCHEMA

from .canonical_naming import build_component_name, build_equipment_name
from .reference_data import (
    DOMAIN_KEYS,
    clean_reference_display,
    iter_domain_definitions,
    iter_seed_values,
    normalize_reference_key,
    resolve_alias_safety,
    vendor_scoped_model_key,
)
from .serial_preservation import SerialPreservationRecord, preserve_serial_cell
from .staging_schema import create_staging_schema
from .validation import (
    assert_source_database_safe,
    candidate_sidecars,
    connect_readonly,
    sha256_file,
    source_content_state,
    validate_candidate,
)
from .xlsx_cells import (
    XlsxCell,
    iter_xlsx_cells,
    read_text_xlsx,
    write_text_csv,
    write_text_xlsx,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RAW_DIR = ROOT / "migration_inputs" / "raw"
DEFAULT_NORMALIZED_DIR = ROOT / "migration_inputs" / "normalized"
DEFAULT_WORKSPACE_DIR = ROOT / "migration_inputs" / "workspace"
DEFAULT_CANDIDATE_PATH = DEFAULT_WORKSPACE_DIR / "warehouse_migration_candidate.db"
DEFAULT_REFERENCE_PACKAGE_PATH = DEFAULT_WORKSPACE_DIR / "reference_candidate_package.xlsx"
DEFAULT_SERIAL_EXPORT_PATH = DEFAULT_WORKSPACE_DIR / "serial_preservation.csv"
DEFAULT_REPORT_PATH = DEFAULT_WORKSPACE_DIR / "candidate_validation.json"
WAREHOUSE_SOURCE_NAME = "warehouse_accounting_source.xlsx"
MANIFEST_NAME = "SHA256SUMS.local"
REFERENCE_REVIEW_NAME = "reference_candidates.xlsx"

RECEIPT_FIRST_ROW = 3
RECEIPT_LAST_ROW = 51_005
ISSUE_FIRST_ROW = 2
ISSUE_LAST_ROW = 20_358

RECEIPT_COLUMNS: dict[str, str] = {
    "A": "receipt_date",
    "B": "responsible",
    "C": "order_date",
    "D": "request_number",
    "E": "order_number",
    "F": "plu",
    "G": "source_item_name",
    "H": "quantity",
    "J": "project",
    "L": "source_serial_number",
    "M": "inventory_number",
    "N": "supplier",
    "O": "comments",
    "P": "capex_opex",
    "Q": "vendor",
    "R": "model",
    "S": "part_number",
    "T": "warehouse_location",
    "U": "deployment_location",
    "V": "object_kind",
    "W": "equipment_category",
    "X": "component_type",
    "Y": "cable_type",
}
ISSUE_COLUMNS: dict[str, str] = {
    "B": "issue_date",
    "C": "case_number",
    "D": "target_equipment_serial",
    "E": "hostname",
    "F": "formula_model",
    "G": "formula_item_name",
    "H": "formula_component_model",
    "I": "quantity",
    "J": "source_serial_number",
    "K": "formula_inventory_number",
    "L": "warehouse_location",
    "M": "issue_reason",
    "N": "action_taken",
    "O": "responsible",
    "P": "comments",
}

REVIEW_COLUMNS = {
    "A": "source_value",
    "B": "proposed_value",
    "C": "rule",
    "D": "confidence",
    "E": "requires_manual_review",
    "F": "source_sheet",
    "G": "source_row",
    "H": "domain",
    "I": "usage_count",
    "J": "all_source_sheets",
    "K": "aliases_in_group",
    "L": "conflict",
    "M": "recommendation",
}

DOMAIN_TRANSLATIONS = {"warehouse_shelf": "warehouse_location"}

SEMANTIC_REFERENCE_MAP: dict[str, dict[str, str]] = {
    "object_kind": {
        "оборудование": "equipment",
        "компонент": "component",
        "кабель": "cable",
        "объект": "unknown",
    },
    "equipment_category": {
        "серверное оборудование": "server equipment",
        "сетевое оборудование": "network equipment",
        "системы хранения данных": "storage",
        "другое оборудование": "other",
        "оперативная память": "other",
    },
    "component_type": {
        "cpu": "CPU",
        "memory": "memory",
        "ram": "memory",
        "оперативная память": "memory",
        "ssd": "SSD",
        "hdd": "HDD",
        "nic": "NIC",
        "lan card": "NIC",
        "hba": "HBA",
        "raid controller": "RAID controller",
        "psu": "PSU",
        "fan": "fan",
        "sfp": "transceiver",
        "transceiver": "transceiver",
        "motherboard": "motherboard",
        "storage": "other",
        "server": "other",
        "om4": "other",
    },
    "cable_type": {
        "utp": "UTP",
        "om4": "OM4",
        "mtp": "MTP",
    },
}


@dataclass(frozen=True)
class CandidatePaths:
    source_db: Path = DEFAULT_DB_PATH
    raw_dir: Path = DEFAULT_RAW_DIR
    normalized_dir: Path = DEFAULT_NORMALIZED_DIR
    candidate_db: Path = DEFAULT_CANDIDATE_PATH
    reference_package: Path = DEFAULT_REFERENCE_PACKAGE_PATH
    serial_export: Path = DEFAULT_SERIAL_EXPORT_PATH
    report: Path = DEFAULT_REPORT_PATH


@dataclass
class CatalogAggregate:
    canonical_name: str
    object_kind: str
    equipment_category: str
    equipment_type: str
    component_type: str
    vendor: str
    model: str
    part_number: str
    confidence: str
    source_names: Counter[str] = field(default_factory=Counter)


@dataclass(frozen=True)
class BuildResult:
    report: dict[str, Any]
    raw_sha_before: dict[str, str]
    raw_sha_after: dict[str, str]
    working_db_before: dict[str, dict[str, Any] | None]
    working_db_after: dict[str, dict[str, Any] | None]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _portable_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


def _same_file_or_path(left: Path, right: Path) -> bool:
    if left.exists() and right.exists():
        try:
            if os.path.samefile(left, right):
                return True
        except OSError:
            pass
    return left.resolve(strict=False) == right.resolve(strict=False)


def _is_within(path: Path, directory: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(directory.resolve(strict=False))
        return True
    except ValueError:
        return False


def assert_safe_candidate_paths(paths: CandidatePaths) -> None:
    """Reject aliases to the working DB, raw inputs and other outputs."""
    outputs = (
        paths.candidate_db,
        paths.reference_package,
        paths.serial_export,
        paths.report,
    )
    protected = [
        paths.source_db,
        *(Path(str(paths.source_db) + suffix) for suffix in ("-wal", "-shm", "-journal")),
    ]
    if paths.raw_dir.is_dir():
        protected.extend(path for path in paths.raw_dir.iterdir() if path.is_file())
    reference_review = paths.normalized_dir / REFERENCE_REVIEW_NAME
    if reference_review.exists():
        protected.append(reference_review)
    for output in outputs:
        if any(_same_file_or_path(output, source) for source in protected):
            raise ValueError(
                "source inputs and candidate outputs must be different files"
            )
        if _is_within(output, paths.raw_dir):
            raise ValueError("candidate outputs must not be written inside immutable raw/")
        if _is_within(output, paths.normalized_dir):
            raise ValueError(
                "candidate outputs must not overwrite normalized review inputs"
            )
    for index, left in enumerate(outputs):
        for right in outputs[index + 1 :]:
            if _same_file_or_path(left, right):
                raise ValueError("candidate output paths must be distinct")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def raw_file_hashes(raw_dir: Path) -> dict[str, str]:
    if not raw_dir.is_dir():
        raise FileNotFoundError(raw_dir)
    return {
        path.name: sha256_file(path)
        for path in sorted(raw_dir.iterdir())
        if path.is_file()
    }


def verify_raw_manifest(raw_dir: Path) -> dict[str, str]:
    manifest = raw_dir / MANIFEST_NAME
    if not manifest.is_file():
        raise FileNotFoundError(manifest)
    expected: dict[str, str] = {}
    for line_number, line in enumerate(
        manifest.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or len(parts[0]) != 64:
            raise ValueError(f"invalid SHA256 manifest line {line_number}")
        expected[Path(parts[1].strip()).name] = parts[0].lower()
    if not expected:
        raise ValueError("SHA256 manifest is empty")
    actual = raw_file_hashes(raw_dir)
    unexpected = sorted(set(actual).difference(set(expected) | {MANIFEST_NAME}))
    missing_files = sorted(set(expected).difference(actual))
    if unexpected or missing_files:
        raise RuntimeError(
            "raw source set differs from manifest: "
            + _json({"unexpected": unexpected, "missing": missing_files})
        )
    failures = {
        name: {"expected": digest, "actual": actual.get(name, "MISSING")}
        for name, digest in expected.items()
        if actual.get(name) != digest
    }
    if failures:
        raise RuntimeError("raw source SHA mismatch: " + _json(failures))
    return expected


def inspect_sources(paths: CandidatePaths) -> dict[str, Any]:
    manifest_entries = verify_raw_manifest(paths.raw_dir)
    raw_hashes = raw_file_hashes(paths.raw_dir)
    database = assert_source_database_safe(paths.source_db)
    forbidden_sidecars = [
        suffix
        for suffix in ("-wal", "-journal")
        if Path(str(paths.source_db) + suffix).exists()
    ]
    if forbidden_sidecars:
        raise RuntimeError(
            "working database has durable sidecars: " + ", ".join(forbidden_sidecars)
        )
    source_xlsx = paths.raw_dir / WAREHOUSE_SOURCE_NAME
    reference_review = paths.normalized_dir / REFERENCE_REVIEW_NAME
    if not source_xlsx.is_file():
        raise FileNotFoundError(source_xlsx)
    if not reference_review.is_file():
        raise FileNotFoundError(reference_review)
    return {
        "raw_files": raw_hashes,
        "manifest_entries_verified": len(manifest_entries),
        "working_database": database,
        "working_database_wal": False,
        "working_database_journal": False,
        "reference_review_sha256": sha256_file(reference_review),
        "operational_bounds": {
            "ПРИХОД": [RECEIPT_FIRST_ROW, RECEIPT_LAST_ROW],
            "РАСХОД": [ISSUE_FIRST_ROW, ISSUE_LAST_ROW],
        },
    }


def verify_candidate_source_files(
    candidate: Path, paths: CandidatePaths
) -> dict[str, dict[str, Any]]:
    """Match every candidate provenance row to the current immutable input."""
    with closing(connect_readonly(candidate)) as connection:
        rows = connection.execute(
            """SELECT file_name, sha256, size_bytes, immutable
               FROM migration_source_files ORDER BY file_name"""
        ).fetchall()
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = str(row[0])
        raw_path = paths.raw_dir / name
        normalized_path = paths.normalized_dir / name
        source = raw_path if raw_path.is_file() else normalized_path
        if not source.is_file():
            raise RuntimeError(f"registered candidate source is missing: {name}")
        actual_sha = sha256_file(source)
        actual_size = source.stat().st_size
        if actual_sha != str(row[1]) or actual_size != int(row[2]):
            raise RuntimeError(f"registered candidate source changed: {name}")
        if int(row[3]) != 1:
            raise RuntimeError(f"candidate source is not marked immutable: {name}")
        result[name] = {
            "sha256": actual_sha,
            "size_bytes": actual_size,
            "immutable": True,
        }
    if not result:
        raise RuntimeError("candidate has no registered source files")
    return result


def _iter_sheet_rows(
    path: Path,
    sheet: str,
    columns: Mapping[str, str],
    first_row: int,
    last_row: int,
) -> Iterator[tuple[int, dict[str, XlsxCell]]]:
    current_row: int | None = None
    current: dict[str, XlsxCell] = {}
    for cell in iter_xlsx_cells(
        path,
        sheet_names={sheet},
        columns={sheet: set(columns)},
    ):
        if cell.source_row < first_row or cell.source_row > last_row:
            continue
        if current_row is None:
            current_row = cell.source_row
        if cell.source_row != current_row:
            yield current_row, current
            current_row = cell.source_row
            current = {}
        current[columns[cell.source_column]] = cell
    if current_row is not None:
        yield current_row, current


def _review_rows(path: Path) -> Iterator[dict[str, str]]:
    for _, cells in _iter_sheet_rows(
        path,
        "REFERENCE_CANDIDATES",
        REVIEW_COLUMNS,
        2,
        1_048_576,
    ):
        yield {
            field: cells[field].source_display_value if field in cells else ""
            for field in REVIEW_COLUMNS.values()
        }


def _source_file_id(
    connection: sqlite3.Connection,
    batch_id: int,
    path: Path,
    now: str,
) -> int:
    cursor = connection.execute(
        """INSERT INTO migration_source_files(
               batch_id, source_path, file_name, sha256, size_bytes, immutable, created_at
           ) VALUES (?, ?, ?, ?, ?, 1, ?)""",
        (
            batch_id,
            _portable_path(path),
            path.name,
            sha256_file(path),
            path.stat().st_size,
            now,
        ),
    )
    return int(cursor.lastrowid)


def _insert_reference_value(
    connection: sqlite3.Connection,
    domain_ids: Mapping[str, int],
    *,
    domain: str,
    canonical_value: str,
    display_name: str,
    normalized_key: str,
    scope_key: str = "",
    active: bool,
    approval_status: str,
    source: str,
    now: str,
) -> int:
    connection.execute(
        """INSERT OR IGNORE INTO reference_values_v2(
               domain_id, canonical_value, display_name, normalized_key, scope_key,
               active, approval_status, source, created_at, updated_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            domain_ids[domain],
            canonical_value,
            display_name,
            normalized_key,
            scope_key,
            int(active),
            approval_status,
            source,
            now,
            now,
        ),
    )
    row = connection.execute(
        """SELECT id FROM reference_values_v2
           WHERE domain_id=? AND scope_key=? AND normalized_key=?""",
        (domain_ids[domain], scope_key, normalized_key),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"failed to resolve candidate reference {domain}:{canonical_value}")
    return int(row[0])


def _confidence_label(value: float | str) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        text = str(value).strip().casefold()
        return {"high": "HIGH", "medium": "MEDIUM", "low": "LOW"}.get(text, "LOW")
    if number >= 0.9:
        return "HIGH"
    if number >= 0.5:
        return "MEDIUM"
    return "LOW"


def _int_text(value: str) -> int:
    try:
        return max(0, int(Decimal(value or "0")))
    except (InvalidOperation, ValueError):
        return 0


def _insert_alias(
    connection: sqlite3.Connection,
    domain_ids: Mapping[str, int],
    *,
    domain: str,
    source_value: str,
    canonical_id: int,
    canonical_value: str,
    source_file: str,
    source_sheet: str,
    usage_count: int,
    now: str,
    notes: str = "",
    source_vendor: str = "",
    canonical_vendor: str = "",
    force_manual: bool = False,
) -> None:
    resolution = resolve_alias_safety(
        domain,
        source_value,
        canonical_value,
        source_vendor=source_vendor,
        canonical_vendor=canonical_vendor,
    )
    auto = resolution.auto_approved and not force_manual
    connection.execute(
        """INSERT INTO reference_aliases_v2(
               domain_id, source_value, normalized_source_key, canonical_id,
               source_file, source_sheet, usage_count, confidence,
               resolution_status, approved_by, approved_at, notes
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(domain_id, source_value, canonical_id, source_file, source_sheet)
           DO UPDATE SET usage_count=excluded.usage_count,
                         confidence=excluded.confidence,
                         resolution_status=excluded.resolution_status,
                         approved_by=excluded.approved_by,
                         approved_at=excluded.approved_at,
                         notes=excluded.notes""",
        (
            domain_ids[domain],
            source_value,
            resolution.normalized_source_key,
            canonical_id,
            source_file,
            source_sheet,
            usage_count,
            _confidence_label(resolution.confidence if not force_manual else 0.0),
            "AUTO_APPROVED" if auto else "PENDING",
            "ODE_SAFE_RULE_V1" if auto else "",
            now if auto else "",
            notes or resolution.reason,
        ),
    )


def _seed_reference_foundation(
    connection: sqlite3.Connection,
    review_path: Path,
    now: str,
) -> tuple[dict[str, int], dict[tuple[str, str, str], int], list[dict[str, str]]]:
    domain_ids: dict[str, int] = {}
    for definition in iter_domain_definitions():
        cursor = connection.execute(
            """INSERT INTO reference_domains_v2(
                   domain_key, display_name, description, active, source, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                definition.key,
                definition.display_name,
                definition.description,
                int(definition.active),
                definition.source,
                now,
                now,
            ),
        )
        domain_ids[definition.key] = int(cursor.lastrowid)

    value_ids: dict[tuple[str, str, str], int] = {}
    for value in iter_seed_values():
        reference_id = _insert_reference_value(
            connection,
            domain_ids,
            domain=value.domain,
            canonical_value=value.canonical_value,
            display_name=value.display_name,
            normalized_key=value.normalized_key,
            active=True,
            approval_status="APPROVED",
            source=value.source,
            now=now,
        )
        value_ids[(value.domain, "", value.normalized_key)] = reference_id

    unresolved: list[dict[str, str]] = []
    for row in _review_rows(review_path):
        source_domain = row["domain"]
        domain = DOMAIN_TRANSLATIONS.get(source_domain, source_domain)
        source_value = row["source_value"]
        proposed_value = row["proposed_value"] or source_value
        recommendation = row["recommendation"]
        conflict = row["conflict"]
        if recommendation == "SOURCE_CORRUPTED":
            unresolved.append({**row, "stage_decision": "BLOCKED_SOURCE_CORRUPTED"})
            continue
        if domain not in DOMAIN_KEYS:
            unresolved.append({**row, "stage_decision": "OUTSIDE_0_13_3A_DOMAIN"})
            continue
        if domain in {"model", "catalog_item"}:
            unresolved.append({**row, "stage_decision": "REQUIRES_STRUCTURED_VENDOR_MODEL_CONTEXT"})
            continue

        normalized_source = normalize_reference_key(source_value)
        canonical_value = SEMANTIC_REFERENCE_MAP.get(domain, {}).get(normalized_source)
        force_manual = False
        if canonical_value is not None:
            normalized_canonical = normalize_reference_key(canonical_value)
            canonical_id = value_ids.get((domain, "", normalized_canonical))
            if canonical_id is None:
                raise RuntimeError(
                    f"semantic mapping has no seed: {domain}:{canonical_value}"
                )
            force_manual = normalized_source != normalized_canonical
        else:
            canonical_value = clean_reference_display(proposed_value)
            if not canonical_value:
                unresolved.append({**row, "stage_decision": "EMPTY_CANDIDATE"})
                continue
            normalized_canonical = normalize_reference_key(canonical_value)
            canonical_id = _insert_reference_value(
                connection,
                domain_ids,
                domain=domain,
                canonical_value=canonical_value,
                display_name=canonical_value,
                normalized_key=normalized_canonical,
                active=False,
                approval_status="CANDIDATE",
                source="Stage 0.13.3A analytical review",
                now=now,
            )
            value_ids[(domain, "", normalized_canonical)] = canonical_id

        if (
            conflict
            and conflict.casefold() not in {"", "none"}
            and normalize_reference_key(source_value)
            != normalize_reference_key(canonical_value)
        ):
            force_manual = True
        _insert_alias(
            connection,
            domain_ids,
            domain=domain,
            source_value=source_value,
            canonical_id=canonical_id,
            canonical_value=canonical_value,
            source_file=WAREHOUSE_SOURCE_NAME,
            source_sheet=row["source_sheet"] or "ANALYTICAL_REVIEW",
            usage_count=_int_text(row["usage_count"]),
            now=now,
            notes=(
                f"review_rule={row['rule']}; recommendation={recommendation}; "
                f"conflict={conflict or 'none'}"
            ),
            force_manual=force_manual,
        )
    return domain_ids, value_ids, unresolved


def _seed_value(
    value_ids: Mapping[tuple[str, str, str], int], domain: str, canonical: str
) -> int | None:
    return value_ids.get((domain, "", normalize_reference_key(canonical)))


def _semantic_value(domain: str, raw: str) -> str:
    key = normalize_reference_key(raw)
    return SEMANTIC_REFERENCE_MAP.get(domain, {}).get(key, "")


def _infer_equipment_type(category: str, item_name: str, model: str) -> str:
    haystack = normalize_reference_key(" ".join((item_name, model)))
    if "server" in normalize_reference_key(category) or "сервер" in haystack:
        return "server"
    if category == "storage" or any(word in haystack for word in ("storage", "oceanstor", "схд")):
        return "storage system"
    if any(word in haystack for word in ("san", "fibre channel", "fc switch")):
        return "SAN switch"
    if category == "network equipment" or any(
        word in haystack for word in ("switch", "коммутатор")
    ):
        return "switch"
    if "load balancer" in haystack or "балансировщик" in haystack:
        return "load balancer"
    if "pdu" in haystack:
        return "PDU"
    if "ups" in haystack or "ибп" in haystack:
        return "UPS"
    return "other"


def _catalog_proposal(values: Mapping[str, str]) -> CatalogAggregate | None:
    object_kind = _semantic_value("object_kind", values.get("object_kind", ""))
    category = _semantic_value(
        "equipment_category", values.get("equipment_category", "")
    )
    component_type = _semantic_value(
        "component_type", values.get("component_type", "")
    )
    vendor = clean_reference_display(values.get("vendor", ""))
    model = clean_reference_display(values.get("model", ""))
    part_number = values.get("part_number", "")
    item_name = values.get("source_item_name", "")
    if not vendor or not (model or part_number):
        return None
    if object_kind == "equipment":
        equipment_type = _infer_equipment_type(category, item_name, model)
        canonical = build_equipment_name(equipment_type, vendor, model or part_number)
        return CatalogAggregate(
            canonical, object_kind, category, equipment_type, "", vendor, model,
            part_number, "MEDIUM" if equipment_type != "other" else "LOW",
        )
    if object_kind == "component":
        canonical_component = component_type or "other"
        canonical = build_component_name(
            canonical_component, vendor, model=model, part_number=part_number
        )
        return CatalogAggregate(
            canonical, object_kind, category, "", canonical_component, vendor, model,
            part_number, "MEDIUM" if canonical_component != "other" else "LOW",
        )
    return None


def _serial_record(
    cells: Mapping[str, XlsxCell], field_name: str, operation_kind: str
) -> SerialPreservationRecord | None:
    cell = cells.get(field_name)
    return preserve_serial_cell(cell, operation_kind=operation_kind) if cell else None


def _serial_warnings(record: SerialPreservationRecord | None) -> list[str]:
    return [part for part in (record.warning.split(";") if record else []) if part]


def _row_payloads(
    cells: Mapping[str, XlsxCell],
) -> tuple[dict[str, Any], dict[str, str]]:
    raw: dict[str, Any] = {}
    display: dict[str, str] = {}
    formulas: dict[str, str] = {}
    for field_name, cell in cells.items():
        raw[field_name] = cell.raw_xml_value
        display[field_name] = cell.source_display_value
        if cell.formula:
            formulas[field_name] = cell.formula
    if formulas:
        raw["_formulas"] = formulas
    return raw, display


def _row_hash(
    file_hash: str, sheet: str, source_row: int, raw_payload: Mapping[str, Any]
) -> str:
    digest = hashlib.sha256()
    for value in (file_hash, sheet, str(source_row), _json(raw_payload)):
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _insert_serial_cell(
    connection: sqlite3.Connection,
    staging_row_id: int,
    role: str,
    record: SerialPreservationRecord,
) -> None:
    connection.execute(
        """INSERT INTO migration_serial_cells(
               staging_row_id, serial_role, source_file, source_file_hash,
               source_sheet, source_row, source_column, excel_cell_coordinate,
               excel_cell_type, excel_number_format, raw_xml_value,
               source_display_value, source_serial_value, normalized_match_value,
               preservation_status, warning, source_hash, extraction_rule,
               confidence, requires_manual_review
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            staging_row_id,
            role,
            record.source_file,
            record.source_file_hash,
            record.source_sheet,
            record.source_row,
            record.source_column,
            record.excel_cell_coordinate,
            record.excel_cell_type,
            record.excel_number_format,
            record.raw_xml_value,
            record.source_display_value,
            record.source_serial_value,
            record.normalized_match_value,
            record.preservation_status,
            record.warning,
            record.source_hash,
            record.normalization_rule,
            record.confidence,
            int(record.requires_manual_review),
        ),
    )


def _stage_operations(
    connection: sqlite3.Connection,
    *,
    source_path: Path,
    source_file_id: int,
    batch_id: int,
    now: str,
) -> tuple[Counter[tuple[str, str]], dict[str, CatalogAggregate], dict[str, int]]:
    model_usage: Counter[tuple[str, str]] = Counter()
    catalogs: dict[str, CatalogAggregate] = {}
    counts: dict[str, int] = defaultdict(int)
    source_hash = sha256_file(source_path)
    specs = (
        ("ПРИХОД", RECEIPT_COLUMNS, RECEIPT_FIRST_ROW, RECEIPT_LAST_ROW, "RECEIPT"),
        ("РАСХОД", ISSUE_COLUMNS, ISSUE_FIRST_ROW, ISSUE_LAST_ROW, "ISSUE"),
    )
    for sheet, columns, first_row, last_row, operation_kind in specs:
        for source_row, cells in _iter_sheet_rows(
            source_path, sheet, columns, first_row, last_row
        ):
            raw_payload, display = _row_payloads(cells)
            source_serial = _serial_record(
                cells,
                "source_serial_number",
                f"{operation_kind}_SOURCE_SERIAL",
            )
            target_serial = (
                _serial_record(cells, "target_equipment_serial", "ISSUE_TARGET_SERIAL")
                if operation_kind == "ISSUE"
                else None
            )
            warnings = _serial_warnings(source_serial) + _serial_warnings(target_serial)
            if "part_number" in cells and cells["part_number"].excel_cell_type == "n":
                warnings.append("NUMERIC_PART_NUMBER_REQUIRES_MANUAL_REVIEW")
                display["part_number"] = ""

            proposed_object = _semantic_value("object_kind", display.get("object_kind", ""))
            proposed_category = _semantic_value(
                "equipment_category", display.get("equipment_category", "")
            )
            proposed_component = _semantic_value(
                "component_type", display.get("component_type", "")
            )
            proposed_equipment = (
                _infer_equipment_type(
                    proposed_category,
                    display.get("source_item_name", ""),
                    display.get("model", ""),
                )
                if proposed_object == "equipment"
                else ""
            )
            proposed_vendor = clean_reference_display(display.get("vendor", ""))
            proposed_model = clean_reference_display(display.get("model", ""))
            catalog = _catalog_proposal(display) if operation_kind == "RECEIPT" else None
            proposed_catalog_name = catalog.canonical_name if catalog else ""
            catalog_key = ""
            if catalog:
                catalog_key = "\x1f".join(
                    (
                        normalize_reference_key(catalog.canonical_name),
                        normalize_reference_key(catalog.vendor),
                        normalize_reference_key(catalog.model),
                        catalog.part_number,
                    )
                )
                existing = catalogs.setdefault(catalog_key, catalog)
                existing.source_names[display.get("source_item_name", "")] += 1
            if operation_kind == "RECEIPT" and proposed_vendor and proposed_model:
                model_usage[(proposed_vendor, proposed_model)] += 1

            primary_status = source_serial.preservation_status if source_serial else "EMPTY"
            if primary_status == "SOURCE_CORRUPTED":
                resolution_status = "BLOCKED"
            elif (source_serial and source_serial.requires_manual_review) or (
                target_serial and target_serial.requires_manual_review
            ):
                resolution_status = "MANUAL_REVIEW"
            elif source_serial and source_serial.source_serial_value:
                resolution_status = "AUTO_REVIEWED"
            else:
                resolution_status = "UNREVIEWED"
            normalized_payload = {
                **display,
                "source_serial_match_only": (
                    source_serial.normalized_match_value if source_serial else ""
                ),
                "target_serial_match_only": (
                    target_serial.normalized_match_value if target_serial else ""
                ),
            }
            cursor = connection.execute(
                """INSERT INTO migration_staging_rows(
                       batch_id, source_file_id, source_sheet, source_row,
                       source_row_hash, operation_kind, raw_payload, normalized_payload,
                       source_serial_value, normalized_matching_serial,
                       serial_preservation_status, proposed_object_kind,
                       proposed_equipment_category, proposed_equipment_type,
                       proposed_component_type, proposed_vendor, proposed_model,
                       proposed_catalog_item, proposed_catalog_key,
                       proposed_canonical_name, warnings,
                       conflicts, resolution_status, decision, target_entity_id,
                       created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                             '[]', ?, '', '', ?)""",
                (
                    batch_id,
                    source_file_id,
                    sheet,
                    source_row,
                    _row_hash(source_hash, sheet, source_row, raw_payload),
                    operation_kind,
                    _json(raw_payload),
                    _json(normalized_payload),
                    source_serial.source_serial_value if source_serial else "",
                    source_serial.normalized_match_value if source_serial else "",
                    primary_status,
                    proposed_object,
                    proposed_category,
                    proposed_equipment,
                    proposed_component,
                    proposed_vendor,
                    proposed_model,
                    proposed_catalog_name,
                    catalog_key,
                    proposed_catalog_name,
                    _json(sorted(set(warnings))),
                    resolution_status,
                    now,
                ),
            )
            staging_id = int(cursor.lastrowid)
            if source_serial:
                _insert_serial_cell(connection, staging_id, "SOURCE_SERIAL", source_serial)
            if target_serial:
                _insert_serial_cell(
                    connection, staging_id, "TARGET_EQUIPMENT_SERIAL", target_serial
                )
            counts[operation_kind] += 1
    return model_usage, catalogs, dict(counts)


def _ensure_vendor(
    connection: sqlite3.Connection,
    domain_ids: Mapping[str, int],
    value_ids: dict[tuple[str, str, str], int],
    vendor: str,
    now: str,
) -> int:
    key = normalize_reference_key(vendor)
    existing = value_ids.get(("vendor", "", key))
    if existing:
        return existing
    reference_id = _insert_reference_value(
        connection,
        domain_ids,
        domain="vendor",
        canonical_value=clean_reference_display(vendor),
        display_name=clean_reference_display(vendor),
        normalized_key=key,
        active=False,
        approval_status="CANDIDATE",
        source="Stage 0.13.3A receipt profile",
        now=now,
    )
    value_ids[("vendor", "", key)] = reference_id
    return reference_id


def _insert_models(
    connection: sqlite3.Connection,
    domain_ids: Mapping[str, int],
    value_ids: dict[tuple[str, str, str], int],
    model_usage: Counter[tuple[str, str]],
    now: str,
) -> dict[tuple[str, str], int]:
    result: dict[tuple[str, str], int] = {}
    for (vendor, model), usage_count in sorted(model_usage.items()):
        vendor_clean = clean_reference_display(vendor)
        model_clean = clean_reference_display(model)
        _ensure_vendor(connection, domain_ids, value_ids, vendor_clean, now)
        scope_key = normalize_reference_key(vendor_clean)
        model_key = normalize_reference_key(model_clean)
        reference_id = _insert_reference_value(
            connection,
            domain_ids,
            domain="model",
            canonical_value=model_clean,
            display_name=model_clean,
            normalized_key=model_key,
            scope_key=scope_key,
            active=False,
            approval_status="CANDIDATE",
            source="Stage 0.13.3A vendor-scoped receipt profile",
            now=now,
        )
        value_ids[("model", scope_key, model_key)] = reference_id
        result[(scope_key, model_key)] = reference_id
        _insert_alias(
            connection,
            domain_ids,
            domain="model",
            source_value=model,
            canonical_id=reference_id,
            canonical_value=model_clean,
            source_file=WAREHOUSE_SOURCE_NAME,
            source_sheet="ПРИХОД",
            usage_count=usage_count,
            now=now,
            source_vendor=vendor,
            canonical_vendor=vendor_clean,
        )
    return result


def _insert_catalogs(
    connection: sqlite3.Connection,
    domain_ids: Mapping[str, int],
    value_ids: dict[tuple[str, str, str], int],
    model_ids: Mapping[tuple[str, str], int],
    catalogs: Mapping[str, CatalogAggregate],
    now: str,
) -> int:
    count = 0
    for scope, catalog in sorted(catalogs.items()):
        normalized_name = normalize_reference_key(catalog.canonical_name)
        ref_id = _insert_reference_value(
            connection,
            domain_ids,
            domain="catalog_item",
            canonical_value=catalog.canonical_name,
            display_name=catalog.canonical_name,
            normalized_key=normalized_name,
            scope_key=scope,
            active=False,
            approval_status="CANDIDATE",
            source="Stage 0.13.3A structured naming proposal",
            now=now,
        )
        vendor_key = normalize_reference_key(catalog.vendor)
        model_key = normalize_reference_key(catalog.model)
        vendor_id = _ensure_vendor(
            connection, domain_ids, value_ids, catalog.vendor, now
        )
        model_id = model_ids.get((vendor_key, model_key)) if model_key else None
        cursor = connection.execute(
            """INSERT INTO catalog_items_v2(
                   reference_value_id, canonical_item_name, object_kind_id,
                   equipment_category_id, equipment_type_id, component_type_id,
                   vendor_id, model_id, part_number, primary_characteristic,
                   normalization_rule, confidence, requires_manual_review,
                   resolution_status, source, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, 1, 'PENDING', ?, ?, ?)""",
            (
                ref_id,
                catalog.canonical_name,
                _seed_value(value_ids, "object_kind", catalog.object_kind),
                _seed_value(
                    value_ids, "equipment_category", catalog.equipment_category
                ),
                _seed_value(value_ids, "equipment_type", catalog.equipment_type),
                _seed_value(value_ids, "component_type", catalog.component_type),
                vendor_id,
                model_id,
                catalog.part_number,
                "STRUCTURED_CANONICAL_NAME_V1",
                catalog.confidence,
                "Stage 0.13.3A receipt profile",
                now,
                now,
            ),
        )
        catalog_id = int(cursor.lastrowid)
        connection.execute(
            """UPDATE migration_staging_rows
               SET proposed_catalog_item_id=?
               WHERE proposed_catalog_key=?""",
            (catalog_id, scope),
        )
        for source_name, usage_count in catalog.source_names.items():
            if not source_name:
                continue
            _insert_alias(
                connection,
                domain_ids,
                domain="catalog_item",
                source_value=source_name,
                canonical_id=ref_id,
                canonical_value=catalog.canonical_name,
                source_file=WAREHOUSE_SOURCE_NAME,
                source_sheet="ПРИХОД",
                usage_count=usage_count,
                now=now,
                force_manual=True,
                notes="Structured catalog proposal; source name remains preserved.",
            )
        count += 1
    return count


def _copy_security_rows(source_db: Path, destination: sqlite3.Connection) -> int:
    columns = (
        "id", "first_name", "last_name", "position", "email", "password_hash",
        "role", "must_change_password", "is_active", "created_at",
    )
    with closing(connect_readonly(source_db)) as source:
        available = {
            str(row[1]) for row in source.execute("PRAGMA table_info(users)")
        }
        missing = set(columns).difference(available)
        if missing:
            raise RuntimeError("source users schema missing: " + ", ".join(sorted(missing)))
        rows = source.execute(
            "SELECT " + ", ".join(columns) + " FROM users ORDER BY id"
        ).fetchall()
    if not rows:
        raise RuntimeError("source database has no users to preserve")
    destination.executemany(
        "INSERT INTO users(" + ", ".join(columns) + ") VALUES (?,?,?,?,?,?,?,?,?,?)",
        [tuple(row) for row in rows],
    )
    active_admins = int(
        destination.execute(
            "SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1"
        ).fetchone()[0]
    )
    if active_admins < 1:
        raise RuntimeError("source security state has no active administrator")
    return len(rows)


def _validation_result(
    connection: sqlite3.Connection,
    batch_id: int,
    severity: str,
    code: str,
    message: str,
    now: str,
    *,
    entity_type: str = "batch",
    entity_id: str = "",
    details: Mapping[str, Any] | None = None,
) -> None:
    connection.execute(
        """INSERT INTO migration_validation_results(
               batch_id, severity, code, entity_type, entity_id, message, details, created_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            batch_id,
            severity,
            code,
            entity_type,
            entity_id,
            message,
            _json(details or {}),
            now,
        ),
    )


def _create_candidate_file(
    temporary_path: Path,
    paths: CandidatePaths,
) -> dict[str, Any]:
    now = _utc_now()
    source_xlsx = paths.raw_dir / WAREHOUSE_SOURCE_NAME
    reference_review = paths.normalized_dir / REFERENCE_REVIEW_NAME
    with closing(sqlite3.connect(temporary_path)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("PRAGMA synchronous = FULL")
        connection.executescript(PRODUCTION_SCHEMA)
        create_staging_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        try:
            users_copied = _copy_security_rows(paths.source_db, connection)
            manifest_sha = sha256_file(paths.raw_dir / MANIFEST_NAME)
            cursor = connection.execute(
                """INSERT INTO migration_batches(
                       batch_key, stage, status, source_manifest_sha256,
                       created_at, notes
                   ) VALUES (?, '0.13.3A', 'BUILDING', ?, ?, ?)""",
                (
                    f"ODE-0.13.3A-{manifest_sha[:16]}",
                    manifest_sha,
                    now,
                    "Reference/staging candidate only; no historical confirm.",
                ),
            )
            batch_id = int(cursor.lastrowid)
            registered: dict[str, int] = {}
            for source in sorted(paths.raw_dir.iterdir()):
                if source.is_file():
                    registered[source.name] = _source_file_id(
                        connection, batch_id, source, now
                    )
            registered[reference_review.name] = _source_file_id(
                connection, batch_id, reference_review, now
            )
            domain_ids, value_ids, unresolved = _seed_reference_foundation(
                connection, reference_review, now
            )
            model_usage, catalogs, staging_counts = _stage_operations(
                connection,
                source_path=source_xlsx,
                source_file_id=registered[source_xlsx.name],
                batch_id=batch_id,
                now=now,
            )
            model_ids = _insert_models(
                connection, domain_ids, value_ids, model_usage, now
            )
            catalog_count = _insert_catalogs(
                connection, domain_ids, value_ids, model_ids, catalogs, now
            )
            for item in unresolved:
                _validation_result(
                    connection,
                    batch_id,
                    "WARNING",
                    item["stage_decision"],
                    "Analytical reference row was not activated as a candidate reference.",
                    now,
                    entity_type="reference_review_row",
                    entity_id=f"{item.get('source_sheet', '')}:{item.get('source_row', '')}",
                    details={
                        "domain": item.get("domain", ""),
                        "source_value": item.get("source_value", ""),
                        "recommendation": item.get("recommendation", ""),
                    },
                )
            corrupted = int(
                connection.execute(
                    "SELECT COUNT(*) FROM migration_serial_cells "
                    "WHERE preservation_status='SOURCE_CORRUPTED'"
                ).fetchone()[0]
            )
            _validation_result(
                connection,
                batch_id,
                "WARNING" if corrupted else "INFO",
                "SOURCE_CORRUPTED_SERIALS",
                f"{corrupted} source serial cell(s) have no safe matching value.",
                now,
                details={"count": corrupted},
            )
            connection.execute(
                """UPDATE migration_batches
                   SET status='REVIEW_REQUIRED', completed_at=? WHERE id=?""",
                (now, batch_id),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or foreign_keys:
            raise RuntimeError(
                f"candidate validation failed before publish: integrity={integrity}, "
                f"foreign_keys={len(foreign_keys)}"
            )
        connection.execute("PRAGMA optimize")
        connection.commit()
    if os.name != "nt":
        os.chmod(temporary_path, 0o600)
    if candidate_sidecars(temporary_path):
        raise RuntimeError("temporary candidate has SQLite sidecars")
    return {
        "users_copied": users_copied,
        "staging_counts": staging_counts,
        "catalog_items": catalog_count,
        "unresolved_reference_rows": len(unresolved),
    }


def _fsync_file_and_parent(path: Path) -> None:
    with path.open("r+b") as handle:
        os.fsync(handle.fileno())
    if hasattr(os, "O_DIRECTORY"):
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


def _query_text_rows(
    connection: sqlite3.Connection, sql: str
) -> tuple[list[str], list[dict[str, str]]]:
    cursor = connection.execute(sql)
    headers = [str(item[0]) for item in cursor.description or ()]
    rows = [
        {header: "" if value is None else str(value) for header, value in zip(headers, row)}
        for row in cursor.fetchall()
    ]
    return headers, rows


def export_reference_package(candidate: Path, output: Path) -> dict[str, int]:
    with closing(connect_readonly(candidate)) as connection:
        queries = {
            "DOMAINS": """SELECT domain_key, display_name, description, active, source,
                                  created_at, updated_at
                           FROM reference_domains_v2 ORDER BY domain_key""",
            "VALUES": """SELECT d.domain_key AS domain, v.canonical_value,
                                 v.display_name, v.normalized_key,
                                 replace(v.scope_key, char(31), ' / ') AS scope_key,
                                 v.active, v.approval_status, v.source,
                                 v.created_at, v.updated_at
                          FROM reference_values_v2 v
                          JOIN reference_domains_v2 d ON d.id=v.domain_id
                          ORDER BY d.domain_key, v.scope_key, v.display_name""",
            "ALIASES": """SELECT d.domain_key AS domain, a.source_value,
                                  a.normalized_source_key, v.canonical_value,
                                  a.source_file, a.source_sheet, a.usage_count,
                                  a.confidence, a.resolution_status, a.approved_by,
                                  a.approved_at, a.notes
                           FROM reference_aliases_v2 a
                           JOIN reference_domains_v2 d ON d.id=a.domain_id
                           JOIN reference_values_v2 v ON v.id=a.canonical_id
                           ORDER BY d.domain_key, a.normalized_source_key, a.source_value""",
            "CATALOG_ITEMS": """SELECT c.canonical_item_name, c.part_number,
                                        c.primary_characteristic, c.normalization_rule,
                                        c.confidence, c.requires_manual_review,
                                        c.resolution_status, c.source
                                 FROM catalog_items_v2 c
                                 ORDER BY c.canonical_item_name, c.part_number""",
            "UNRESOLVED": """SELECT severity, code, entity_type, entity_id, message,
                                    details, created_at
                             FROM migration_validation_results
                             ORDER BY severity DESC, code, entity_id""",
        }
        sheets: dict[str, tuple[list[str], list[dict[str, str]]]] = {}
        counts: dict[str, int] = {}
        for name, sql in queries.items():
            headers, rows = _query_text_rows(connection, sql)
            sheets[name] = (headers, rows)
            counts[name] = len(rows)
    write_text_xlsx(
        output,
        sheets,
        identifier_columns={"CATALOG_ITEMS": {"part_number"}},
    )
    round_trip = read_text_xlsx(output)
    if {name: len(rows) for name, rows in round_trip.items()} != counts:
        raise RuntimeError("reference package XLSX round-trip count mismatch")
    for cell in iter_xlsx_cells(output):
        if cell.excel_number_format != "@":
            raise RuntimeError(
                f"reference package cell is not text formatted: {cell.excel_cell_coordinate}"
            )
    return counts


def export_serial_csv(candidate: Path, output: Path) -> int:
    headers = [
        "source_file", "source_sheet", "source_row", "source_column",
        "excel_cell_coordinate", "excel_cell_type", "excel_number_format",
        "raw_xml_value", "source_display_value", "source_serial_value",
        "normalized_match_value", "preservation_status", "warning",
        "source_hash", "source_file_hash", "extraction_rule", "confidence",
        "requires_manual_review", "serial_role",
    ]
    with closing(connect_readonly(candidate)) as connection:
        cursor = connection.execute(
            "SELECT " + ", ".join(headers) + " FROM migration_serial_cells ORDER BY id"
        )
        rows = [
            {header: "" if value is None else str(value) for header, value in zip(headers, row)}
            for row in cursor.fetchall()
        ]
    write_text_csv(
        output,
        headers,
        rows,
        identifier_columns={
            "raw_xml_value", "source_display_value", "source_serial_value",
            "normalized_match_value", "source_hash", "source_file_hash",
        },
    )
    return len(rows)


def write_json_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def candidate_report_details(
    candidate: Path, paths: CandidatePaths
) -> dict[str, Any]:
    """Recompute non-secret build details without trusting an old report."""
    with closing(connect_readonly(candidate)) as connection:
        staging_counts = {
            str(row[0]): int(row[1])
            for row in connection.execute(
                "SELECT operation_kind, COUNT(*) FROM migration_staging_rows "
                "GROUP BY operation_kind ORDER BY operation_kind"
            )
        }
        batch = connection.execute(
            "SELECT stage, status FROM migration_batches ORDER BY id"
        ).fetchone()
        if batch is None:
            raise RuntimeError("candidate has no migration batch")
        counts = {
            "DOMAINS": int(
                connection.execute("SELECT COUNT(*) FROM reference_domains_v2").fetchone()[0]
            ),
            "VALUES": int(
                connection.execute("SELECT COUNT(*) FROM reference_values_v2").fetchone()[0]
            ),
            "ALIASES": int(
                connection.execute("SELECT COUNT(*) FROM reference_aliases_v2").fetchone()[0]
            ),
            "CATALOG_ITEMS": int(
                connection.execute("SELECT COUNT(*) FROM catalog_items_v2").fetchone()[0]
            ),
            "UNRESOLVED": int(
                connection.execute(
                    "SELECT COUNT(*) FROM migration_validation_results"
                ).fetchone()[0]
            ),
        }
        unresolved_reference_rows = int(
            connection.execute(
                "SELECT COUNT(*) FROM migration_validation_results "
                "WHERE entity_type='reference_review_row'"
            ).fetchone()[0]
        )
        serial_rows = int(
            connection.execute("SELECT COUNT(*) FROM migration_serial_cells").fetchone()[0]
        )
    return {
        "stage": str(batch[0]),
        "status": str(batch[1]),
        "staging_counts": staging_counts,
        "catalog_items": counts["CATALOG_ITEMS"],
        "unresolved_reference_rows": unresolved_reference_rows,
        "reference_package": _portable_path(paths.reference_package),
        "reference_package_counts": counts,
        "serial_export": _portable_path(paths.serial_export),
        "serial_export_rows": serial_rows,
        "historical_receipts_imported_to_production": 0,
        "historical_issues_imported_to_production": 0,
    }


def build_candidate(paths: CandidatePaths, *, overwrite: bool = False) -> BuildResult:
    assert_safe_candidate_paths(paths)
    outputs = (
        paths.candidate_db,
        paths.reference_package,
        paths.serial_export,
        paths.report,
    )
    existing = [path for path in outputs if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "candidate output exists; use --overwrite: "
            + ", ".join(_portable_path(path) for path in existing)
        )
    source_inspection = inspect_sources(paths)
    raw_before = raw_file_hashes(paths.raw_dir)
    db_before = source_content_state(paths.source_db)
    for output in outputs:
        output.parent.mkdir(parents=True, exist_ok=True)

    # The final candidate is the publication marker.  Build and validate the
    # entire bundle first; export failures must not replace a valid candidate.
    with tempfile.TemporaryDirectory(
        prefix=".ode-migration-candidate.", dir=paths.candidate_db.parent
    ) as temporary_directory:
        temporary_root = Path(temporary_directory)
        temporary_candidate = temporary_root / paths.candidate_db.name
        temporary_package = temporary_root / paths.reference_package.name
        temporary_serial = temporary_root / paths.serial_export.name
        temporary_report = temporary_root / paths.report.name

        build_details = _create_candidate_file(temporary_candidate, paths)
        validation = validate_candidate(temporary_candidate)
        registered_sources = verify_candidate_source_files(temporary_candidate, paths)
        package_counts = export_reference_package(
            temporary_candidate, temporary_package
        )
        serial_export_count = export_serial_csv(
            temporary_candidate, temporary_serial
        )
        raw_after = raw_file_hashes(paths.raw_dir)
        db_after = source_content_state(paths.source_db)
        if raw_after != raw_before:
            raise RuntimeError("raw migration sources changed during candidate build")
        if db_after != db_before:
            raise RuntimeError("working database changed during candidate build")
        assert_source_database_safe(paths.source_db)
        validation["candidate_path"] = _portable_path(paths.candidate_db)
        report = {
            **validation,
            **build_details,
            "stage": "0.13.3A",
            "status": "REVIEW_REQUIRED",
            "source_inspection": source_inspection,
            "registered_sources": registered_sources,
            "raw_sha_unchanged": True,
            "working_database_sha_before": str(db_before["database"]["sha256"]),
            "working_database_sha_after": str(db_after["database"]["sha256"]),
            "working_database_unchanged": True,
            "reference_package": _portable_path(paths.reference_package),
            "reference_package_counts": package_counts,
            "serial_export": _portable_path(paths.serial_export),
            "serial_export_rows": serial_export_count,
            "historical_receipts_imported_to_production": 0,
            "historical_issues_imported_to_production": 0,
        }
        write_json_report(temporary_report, report)
        for artifact in (
            temporary_candidate,
            temporary_package,
            temporary_serial,
            temporary_report,
        ):
            _fsync_file_and_parent(artifact)

        # Ancillary review files are published first and the validated DB last.
        # A failure before the last replace leaves the previous candidate DB in
        # place; all artifacts are ignored, disposable and regenerable.
        os.replace(temporary_package, paths.reference_package)
        os.replace(temporary_serial, paths.serial_export)
        os.replace(temporary_report, paths.report)
        os.replace(temporary_candidate, paths.candidate_db)
        for output in outputs:
            _fsync_file_and_parent(output)

    return BuildResult(report, raw_before, raw_after, db_before, db_after)
