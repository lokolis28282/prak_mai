"""Marker-guarded, read-only review of the full migration candidate."""

from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import stat
from typing import Any

from inventory.db import DEFAULT_DB_PATH
from inventory.shared.validators import WarehouseError


FULL_ENV = "ODE_FULL_MIGRATION_CANDIDATE"
FULL_FILENAME = "warehouse_full_candidate.db"
FULL_MARKER = "FULL_WAREHOUSE_CANDIDATE"
FULL_STAGE = "FULL_HISTORICAL_WAREHOUSE_CANDIDATE"
FULL_STATUS = "READY_FOR_MANUAL_ACCEPTANCE"
FULL_MARKER_TABLE = "migration_full_marker"
EXPECTED_RECEIPT_ROWS = 51_003
EXPECTED_ISSUE_ROWS = 20_357
EXPECTED_TOTAL_ROWS = EXPECTED_RECEIPT_ROWS + EXPECTED_ISSUE_ROWS

_REQUIRED_TABLES = {
    "migration_full_marker",
    "migration_full_identities",
    "migration_full_reconciliation",
    "migration_full_warnings",
    "migration_full_quarantine",
    "migration_full_relationships",
    "migration_full_performance",
    "migration_full_cleanliness",
    "stock_receipts",
    "stock_issues",
    "stock_issue_allocations",
    "audit_log",
    "users",
}
_SIDECARS = ("-wal", "-shm", "-journal")
_FILTERS = {
    "TEXT_EXACT": "r.preservation_status='TEXT_EXACT'",
    "NUMERIC_PROVISIONAL": "r.preservation_status='NUMERIC_FORMAT_UNPROVEN'",
    "SOURCE_CORRUPTED": "r.preservation_status='SOURCE_CORRUPTED'",
    "CONFLICT": "(r.final_status='CONFLICT_HISTORY_ONLY' OR r.conflicts<>'[]')",
    "OPENING_STATE": "COALESCE(i.opening_state,0)=1",
    "UNRESOLVED_ISSUE": "r.final_status IN ('UNRESOLVED_ISSUE','FAILED_WITH_REASON')",
    "QUARANTINE": "EXISTS(SELECT 1 FROM migration_full_quarantine q WHERE q.reconciliation_id=r.id)",
    "EQUIPMENT": "i.object_kind='equipment'",
    "COMPONENT": "i.object_kind='component'",
    "VENDOR": "trim(COALESCE(i.vendor,r.vendor,''))<>''",
    "MODEL": "trim(COALESCE(i.model,r.model,''))<>''",
}


def full_migration_requested() -> bool:
    return os.environ.get(FULL_ENV) == "1"


def _same_file(left: Path, right: Path) -> bool:
    if left.resolve() == right.resolve():
        return True
    if left.exists() and right.exists():
        try:
            return os.path.samefile(left, right)
        except OSError:
            return False
    return False


def _readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def validate_full_migration_database(
    path: str | Path,
    *,
    enabled: bool | None = None,
) -> dict[str, Any]:
    """Validate candidate review or a promoted full working database."""

    selected = Path(path)
    requested = full_migration_requested() if enabled is None else bool(enabled)
    if not selected.is_file():
        if requested:
            raise RuntimeError(f"Full candidate DB не найдена: {selected.name}")
        return {"enabled": False}
    with closing(_readonly(selected)) as connection:
        tables = _table_names(connection)
        has_marker = FULL_MARKER_TABLE in tables
    if not requested and not has_marker:
        return {"enabled": False}
    if not requested and selected.name == FULL_FILENAME:
        raise RuntimeError(
            f"{FULL_ENV}=1 обязателен для запуска full migration candidate"
        )
    if requested and not has_marker:
        raise RuntimeError("В выбранной DB отсутствует full candidate marker")
    if requested:
        if selected.name != FULL_FILENAME:
            raise RuntimeError(f"Full candidate DB должна называться {FULL_FILENAME}")
        if _same_file(selected, DEFAULT_DB_PATH):
            raise RuntimeError("Full candidate нельзя запускать на data/warehouse.db")
    sidecars = [suffix for suffix in _SIDECARS if Path(str(selected) + suffix).exists()]
    if sidecars:
        raise RuntimeError(
            "У full marker DB обнаружены SQLite sidecar-файлы: "
            + ", ".join(sidecars)
        )
    mode = stat.S_IMODE(selected.stat().st_mode)
    if requested and os.name == "posix" and mode != 0o600:
        raise RuntimeError(f"Full candidate mode должен быть 0600, получен {mode:04o}")

    with closing(_readonly(selected)) as connection:
        tables = _table_names(connection)
        missing = sorted(_REQUIRED_TABLES.difference(tables))
        if missing:
            raise RuntimeError("Full candidate schema неполна: " + ", ".join(missing))
        marker_rows = list(connection.execute("SELECT * FROM migration_full_marker"))
        if len(marker_rows) != 1:
            raise RuntimeError("Full candidate marker должен содержать ровно одну строку")
        marker = dict(marker_rows[0])
        for key, expected in {
            "marker": FULL_MARKER,
            "stage": FULL_STAGE,
            "status": FULL_STATUS,
            "review_read_only": 1,
            "receipt_source_rows": EXPECTED_RECEIPT_ROWS,
            "issue_source_rows": EXPECTED_ISSUE_ROWS,
            "reconciliation_rows": EXPECTED_TOTAL_ROWS,
        }.items():
            if marker.get(key) != expected:
                raise RuntimeError(f"Неверный full marker {key}: {marker.get(key)!r}")
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = list(connection.execute("PRAGMA foreign_key_check"))
        if integrity != "ok" or foreign_keys:
            raise RuntimeError(
                f"Full candidate SQLite health: integrity={integrity}, fk={len(foreign_keys)}"
            )
        reconciliation = int(connection.execute(
            "SELECT COUNT(*) FROM migration_full_reconciliation"
        ).fetchone()[0])
        identities = int(connection.execute(
            "SELECT COUNT(*) FROM migration_full_identities"
        ).fetchone()[0])
        receipts = int(connection.execute("SELECT COUNT(*) FROM stock_receipts").fetchone()[0])
        issues = int(connection.execute("SELECT COUNT(*) FROM stock_issues").fetchone()[0])
        active_admins = int(connection.execute(
            "SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1"
        ).fetchone()[0])
        if reconciliation != EXPECTED_TOTAL_ROWS:
            raise RuntimeError("Full candidate reconciliation count mismatch")
        if identities != receipts or identities != int(marker["identity_count"]):
            raise RuntimeError("Full candidate identity/receipt cardinality mismatch")
        if issues != int(marker["issue_count"]):
            raise RuntimeError("Full candidate issue cardinality mismatch")
        if active_admins < 1:
            raise RuntimeError("Full candidate не содержит активного администратора")
    return {
        "enabled": True,
        "mode": "full",
        "database": selected.name,
        "marker": FULL_MARKER,
        "status": FULL_STATUS,
        "read_only": requested,
        "working_database": not requested,
        "diagnostic_review": True,
        "database_fingerprint": f"full:{marker['build_key']}",
        "integrity_status": integrity,
        "foreign_key_errors": len(foreign_keys),
        "source_rows": EXPECTED_TOTAL_ROWS,
        "receipt_source_rows": EXPECTED_RECEIPT_ROWS,
        "issue_source_rows": EXPECTED_ISSUE_ROWS,
        "identities": identities,
        "receipts": receipts,
        "issues": issues,
        "opening_states": int(marker["opening_state_count"]),
        "provisional": int(marker["provisional_identity_count"]),
        "quarantine": int(marker["quarantine_count"]),
    }


def assert_full_inventory_assignment_allowed(
    path: str | Path,
    serial_number: str,
) -> None:
    """Backend guard: provisional numeric identities never receive Inventory No."""

    selected = Path(path)
    if not selected.is_file():
        return
    with closing(_readonly(selected)) as connection:
        tables = _table_names(connection)
        if FULL_MARKER_TABLE not in tables or "migration_full_identities" not in tables:
            return
        row = connection.execute(
            """SELECT id FROM migration_full_identities
                WHERE preservation_status='NUMERIC_FORMAT_UNPROVEN'
                  AND (display_serial_value=? COLLATE NOCASE
                       OR preserved_serial_value=? COLLATE BINARY)
                LIMIT 1""",
            (str(serial_number), str(serial_number)),
        ).fetchone()
    if row is not None:
        raise WarehouseError(
            "Inventory Number запрещён для provisional numeric identity; "
            "сначала требуется ручное подтверждение исходного формата S/N"
        )


def _json_list(value: Any) -> list[str]:
    try:
        decoded = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        decoded = [str(value)] if value else []
    if not isinstance(decoded, list):
        decoded = [decoded]
    return [str(item) for item in decoded]


def _public_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for key in ("warnings", "conflicts"):
        result[key] = _json_list(result.get(key))
    result["migration_warnings"] = result.get("warnings", [])
    result["import_decision"] = str(result.get("final_status") or "")
    result["serial_preservation_status"] = str(result.get("preservation_status") or "")
    result["source_file"] = Path(str(result.get("source_file") or "").replace("\\", "/")).name
    result["has_card"] = bool(int(result.get("target_identity_id") or 0))
    return result


class MigrationFullReviewService:
    """SQL-paginated full review projection; raw payloads and secrets stay hidden."""

    def __init__(self, db_path: str | Path, *, actor_provider: Any):
        self.db_path = Path(db_path)
        self.actor_provider = actor_provider

    def _require_role(self) -> None:
        user = self.actor_provider.current_user()
        if user.get("role") not in {"admin", "engineer"}:
            raise WarehouseError("Full migration review доступен инженеру или администратору")

    def _validated(self) -> dict[str, Any]:
        try:
            return validate_full_migration_database(
                self.db_path,
                enabled=True if self.db_path.name == FULL_FILENAME else False,
            )
        except RuntimeError as error:
            raise WarehouseError(str(error)) from error

    def list_rows(
        self,
        *,
        filter_name: str = "",
        query: str = "",
        vendor: str = "",
        model: str = "",
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        self._require_role()
        self._validated()
        requested_filter = filter_name.strip().upper()
        if requested_filter and requested_filter not in _FILTERS:
            raise WarehouseError("Неизвестный фильтр full migration review")
        where: list[str] = []
        parameters: list[Any] = []
        if requested_filter:
            where.append(_FILTERS[requested_filter])
        needle = query.strip()
        if needle:
            like = f"%{needle}%"
            where.append(
                "(" + " OR ".join(
                    f"{column} LIKE ? COLLATE NOCASE"
                    for column in (
                        "r.source_serial_value", "r.display_serial_value",
                        "r.source_item_name", "r.canonical_item_name",
                        "r.vendor", "r.model", "r.source_sheet",
                        "CAST(r.source_row AS TEXT)", "r.final_status",
                    )
                ) + ")"
            )
            parameters.extend([like] * 9)
        if vendor.strip():
            where.append("COALESCE(i.vendor,r.vendor)=? COLLATE NOCASE")
            parameters.append(vendor.strip())
        if model.strip():
            where.append("COALESCE(i.model,r.model)=? COLLATE NOCASE")
            parameters.append(model.strip())
        where_sql = " WHERE " + " AND ".join(where) if where else ""
        safe_limit = max(1, min(int(limit), 500))
        safe_offset = max(0, int(offset))
        with closing(_readonly(self.db_path)) as connection:
            total = int(connection.execute(
                """SELECT COUNT(*) FROM migration_full_reconciliation r
                    LEFT JOIN migration_full_identities i ON i.id=r.target_identity_id"""
                + where_sql,
                parameters,
            ).fetchone()[0])
            rows = connection.execute(
                """SELECT r.id AS selection_id, r.id AS reconciliation_id,
                          r.operation_kind, r.source_file, r.source_sheet,
                          r.source_row, r.source_row_hash, r.source_serial_value,
                          r.display_serial_value, r.normalized_match_value,
                          r.raw_xml_value, r.preservation_status,
                          r.identity_confidence, r.authoritative,
                          r.requires_manual_review, r.final_status,
                          r.target_identity_id, r.target_receipt_id,
                          r.target_issue_id, r.source_item_name,
                          r.canonical_item_name, r.object_kind, r.category,
                          r.equipment_type, r.component_type, r.vendor, r.model,
                          r.part_number, r.quantity, r.source_operation_date,
                          r.shelf, r.warnings, r.conflicts,
                          r.non_application_reason,
                          COALESCE(i.opening_state,0) AS opening_state
                     FROM migration_full_reconciliation r
                     LEFT JOIN migration_full_identities i ON i.id=r.target_identity_id"""
                + where_sql
                + " ORDER BY r.operation_kind, r.source_row, r.id LIMIT ? OFFSET ?",
                (*parameters, safe_limit, safe_offset),
            ).fetchall()
            summary = {
                "source_rows": int(connection.execute(
                    "SELECT COUNT(*) FROM migration_full_reconciliation"
                ).fetchone()[0]),
                "imported_cards": int(connection.execute(
                    "SELECT COUNT(*) FROM migration_full_identities"
                ).fetchone()[0]),
                "imported_receipts": int(connection.execute(
                    "SELECT COUNT(*) FROM migration_full_identities WHERE opening_state=0"
                ).fetchone()[0]),
                "imported_issues": int(connection.execute(
                    "SELECT COUNT(*) FROM stock_issues"
                ).fetchone()[0]),
                "provisional_numeric": int(connection.execute(
                    """SELECT COUNT(*) FROM migration_full_identities
                        WHERE preservation_status='NUMERIC_FORMAT_UNPROVEN'"""
                ).fetchone()[0]),
                "quarantine": int(connection.execute(
                    "SELECT COUNT(*) FROM migration_full_quarantine"
                ).fetchone()[0]),
                "source_corrupted": int(connection.execute(
                    """SELECT COUNT(*) FROM migration_full_reconciliation
                        WHERE preservation_status='SOURCE_CORRUPTED'"""
                ).fetchone()[0]),
                "exact_duplicates": int(connection.execute(
                    """SELECT COUNT(*) FROM migration_full_reconciliation
                        WHERE final_status='EXACT_DUPLICATE'"""
                ).fetchone()[0]),
                "conflicts": int(connection.execute(
                    """SELECT COUNT(*) FROM migration_full_reconciliation
                        WHERE final_status='CONFLICT_HISTORY_ONLY' OR conflicts<>'[]'"""
                ).fetchone()[0]),
                "opening_states": int(connection.execute(
                    "SELECT COUNT(*) FROM migration_full_identities WHERE opening_state=1"
                ).fetchone()[0]),
                "unresolved_issues": int(connection.execute(
                    """SELECT COUNT(*) FROM migration_full_reconciliation
                        WHERE operation_kind='ISSUE'
                          AND final_status IN ('UNRESOLVED_ISSUE','FAILED_WITH_REASON')"""
                ).fetchone()[0]),
                "deferred_quantity": int(connection.execute(
                    """SELECT COUNT(*) FROM migration_full_reconciliation
                        WHERE final_status='QUANTITY_DEFERRED'"""
                ).fetchone()[0]),
            }
            facets = {
                "vendors": [str(row[0]) for row in connection.execute(
                    """SELECT DISTINCT vendor FROM migration_full_identities
                        WHERE trim(vendor)<>'' ORDER BY vendor LIMIT 500"""
                )],
                "models": [str(row[0]) for row in connection.execute(
                    """SELECT DISTINCT model FROM migration_full_identities
                        WHERE trim(model)<>'' ORDER BY model LIMIT 2000"""
                )],
            }
        return {
            "rows": [_public_row(row) for row in rows],
            "total": total,
            "selected_count": summary["source_rows"],
            "limit": safe_limit,
            "offset": safe_offset,
            "counts": summary,
            "facets": facets,
        }

    def get_card(self, reconciliation_id: int) -> dict[str, Any]:
        self._require_role()
        self._validated()
        with closing(_readonly(self.db_path)) as connection:
            selected = connection.execute(
                """SELECT r.*, i.id AS identity_id, i.display_serial_value AS identity_display,
                          i.preserved_serial_value, i.raw_xml_value AS identity_raw_xml,
                          i.preservation_status AS identity_preservation,
                          i.identity_confidence, i.authoritative,
                          i.requires_manual_review, i.opening_state,
                          i.target_receipt_id AS identity_receipt_id,
                          i.normalization_rule, i.warnings AS identity_warnings,
                          i.conflicts AS identity_conflicts
                     FROM migration_full_reconciliation r
                     LEFT JOIN migration_full_identities i ON i.id=r.target_identity_id
                    WHERE r.id=?""",
                (int(reconciliation_id),),
            ).fetchone()
            if selected is None:
                raise WarehouseError("Строка full migration review не найдена")
            if selected["identity_id"] is None:
                raise WarehouseError("Для source row карточка не создавалась")
            identity_id = int(selected["identity_id"])
            receipt_id = int(selected["identity_receipt_id"])
            source_rows = [
                _public_row(row)
                for row in connection.execute(
                    """SELECT id AS reconciliation_id, operation_kind, source_file,
                              source_sheet, source_row, source_row_hash,
                              source_serial_value, display_serial_value,
                              raw_xml_value, preservation_status, final_status,
                              source_item_name, canonical_item_name,
                              source_operation_date, shelf, warnings, conflicts,
                              non_application_reason
                         FROM migration_full_reconciliation
                        WHERE target_identity_id=?
                        ORDER BY operation_kind, source_row, id""",
                    (identity_id,),
                )
            ]
            relationships = [dict(row) for row in connection.execute(
                """SELECT relationship_type, target_source_serial_value,
                          target_display_serial_value, target_preservation_status,
                          target_identity_id, warning
                     FROM migration_full_relationships
                    WHERE source_identity_id=? ORDER BY id""",
                (identity_id,),
            )]

        response = self.actor_provider.position_card(receipt_id=receipt_id)
        position = dict(response.get("position") or {})
        position["serial_number"] = str(selected["identity_display"] or "")
        position["migration_identity_id"] = identity_id
        history = [dict(row) for row in response.get("history") or []]
        opening_state = bool(int(selected["opening_state"] or 0))
        opening_message = (
            "Исходный приход отсутствует в доступной выгрузке; начальное состояние "
            "восстановлено для сохранения исторического расхода"
        )
        receipt_relabelled = False
        for event in history:
            if not receipt_relabelled and event.get("event_type") in {
                "Приход", "Начальный остаток"
            }:
                event["event_type"] = (
                    "Миграционное начальное состояние"
                    if opening_state else "Исторический приход (миграция)"
                )
                if opening_state:
                    event["comment"] = opening_message
                receipt_relabelled = True
            elif event.get("event_type") == "Расход":
                event["event_type"] = "Исторический расход (миграция)"
        migration = {
            "mode": "full",
            "reconciliation_id": int(selected["id"]),
            "identity_id": identity_id,
            "source_file": Path(str(selected["source_file"])).name,
            "source_sheet": str(selected["source_sheet"]),
            "source_row": int(selected["source_row"]),
            "operation_kind": str(selected["operation_kind"] or ""),
            "source_operation_date": str(selected["source_operation_date"] or ""),
            "source_serial_value": str(selected["source_serial_value"] or ""),
            "final_status": str(selected["final_status"] or ""),
            "source_item_name": str(selected["source_item_name"] or ""),
            "canonical_item_name": str(selected["canonical_item_name"] or ""),
            "object_kind": str(selected["object_kind"] or ""),
            "category": str(selected["category"] or ""),
            "equipment_type": str(selected["equipment_type"] or ""),
            "component_type": str(selected["component_type"] or ""),
            "vendor": str(selected["vendor"] or ""),
            "model": str(selected["model"] or ""),
            "part_number": str(selected["part_number"] or ""),
            "shelf": str(selected["shelf"] or ""),
            "display_serial_value": str(selected["identity_display"] or ""),
            "preserved_serial_value": str(selected["preserved_serial_value"] or ""),
            "raw_xml_value": str(selected["identity_raw_xml"] or ""),
            "preservation_status": str(selected["identity_preservation"] or ""),
            "identity_confidence": str(selected["identity_confidence"] or ""),
            "authoritative": bool(int(selected["authoritative"] or 0)),
            "requires_manual_review": bool(int(selected["requires_manual_review"] or 0)),
            "opening_state": opening_state,
            "opening_state_message": opening_message if opening_state else "",
            "normalization_rule": str(selected["normalization_rule"] or ""),
            "warnings": _json_list(selected["identity_warnings"]),
            "conflicts": _json_list(selected["identity_conflicts"]),
            "source_rows": source_rows,
            "relationships": relationships,
            "timeline_label": (
                "Миграционное начальное состояние"
                if opening_state else "Исторический приход (миграция)"
            ),
        }
        return {"position": position, "history": history, "migration": migration}


__all__ = [
    "FULL_ENV",
    "FULL_FILENAME",
    "FULL_MARKER",
    "MigrationFullReviewService",
    "assert_full_inventory_assignment_allowed",
    "full_migration_requested",
    "validate_full_migration_database",
]
