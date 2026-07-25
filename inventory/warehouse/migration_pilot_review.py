"""Read-only review boundary for the Stage 0.13.3A.5 migration pilot.

The offline pilot builder owns the ``migration_pilot_*`` tables.  Runtime code
only reads a deliberately small, allow-listed projection from those tables and
never exposes raw XML, raw payloads, password hashes, or local absolute paths.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable

from inventory.db import DEFAULT_DB_PATH
from inventory.shared.validators import WarehouseError


PILOT_ENV = "ODE_MIGRATION_PILOT"
PILOT_STAGE = "0.13.3A.5"
PILOT_FILENAME = "warehouse_pilot_candidate.db"
PILOT_MARKER_TABLE = "migration_pilot_marker"

_PILOT_TABLES = {
    PILOT_MARKER_TABLE,
    "migration_pilot_selection",
    "migration_pilot_identities",
    "migration_pilot_provenance",
    "migration_pilot_quarantine",
    "migration_pilot_performance",
}
_REQUIRED_REVIEW_TABLES = {
    PILOT_MARKER_TABLE,
    "migration_pilot_selection",
    "migration_pilot_identities",
    "migration_pilot_provenance",
    "migration_pilot_quarantine",
}

# Selection/provenance schemas are owned by the offline migration package.  A
# runtime projection is intentionally schema-adaptive within this strict list.
_SAFE_COLUMNS = {
    "id",
    "selection_id",
    "primary_selection_id",
    "selection_order",
    "staging_row_id",
    "migration_batch_id",
    "source_file",
    "source_sheet",
    "source_row",
    "source_column",
    "excel_cell_coordinate",
    "source_row_hash",
    "source_serial_value",
    "normalized_match_value",
    "serial_preservation_status",
    "preservation_status",
    "excel_cell_type",
    "excel_number_format",
    "source_display_value",
    "preserved_serial_value",
    "canonical_item_name",
    "source_item_name",
    "object_kind",
    "equipment_category",
    "category",
    "equipment_type",
    "component_type",
    "vendor",
    "model",
    "part_number",
    "supplier",
    "datacenter",
    "shelf",
    "quantity",
    "migration_warnings",
    "warnings",
    "warnings_json",
    "conflicts",
    "conflicts_json",
    "conflict_types",
    "selection_reason",
    "selection_reasons",
    "selection_reasons_json",
    "quota_flags",
    "import_decision",
    "decision",
    "resolution_status",
    "receipt_id",
    "target_entity_id",
    "target_receipt_id",
    "source_receipt_date",
    "source_receipt_date_raw",
    "source_receipt_date_cell_type",
    "source_receipt_date_number_format",
    "receipt_date",
    "source_date_status",
    "date_status",
    "source_receipt_date_status",
    "imported_at",
    "created_at",
}

_ALIASES = {
    "selection_id": ("selection_id", "primary_selection_id", "id"),
    "staging_row_id": ("staging_row_id",),
    "source_file": ("source_file",),
    "source_sheet": ("source_sheet",),
    "source_row": ("source_row",),
    "source_row_hash": ("source_row_hash",),
    "source_serial_value": ("source_serial_value",),
    "normalized_match_value": ("normalized_match_value",),
    "serial_preservation_status": (
        "serial_preservation_status",
        "preservation_status",
    ),
    "canonical_item_name": ("canonical_item_name",),
    "source_item_name": ("source_item_name",),
    "equipment_category": ("equipment_category", "category"),
    "migration_warnings": ("migration_warnings", "warnings", "warnings_json"),
    "conflicts": ("conflicts", "conflicts_json", "conflict_types"),
    "selection_reasons": (
        "selection_reasons",
        "selection_reasons_json",
        "selection_reason",
    ),
    "import_decision": ("import_decision", "decision", "resolution_status"),
    "receipt_id": ("receipt_id", "target_receipt_id", "target_entity_id"),
    "source_receipt_date": ("source_receipt_date", "receipt_date"),
    "source_date_status": (
        "source_date_status",
        "source_receipt_date_status",
        "date_status",
    ),
    "imported_at": ("imported_at", "created_at"),
}

_PUBLIC_KEYS = {
    "selection_id",
    "selection_order",
    "staging_row_id",
    "source_file",
    "source_sheet",
    "source_row",
    "source_row_hash",
    "source_serial_value",
    "normalized_match_value",
    "serial_preservation_status",
    "excel_cell_type",
    "excel_number_format",
    "source_display_value",
    "canonical_item_name",
    "source_item_name",
    "object_kind",
    "equipment_category",
    "equipment_type",
    "component_type",
    "vendor",
    "model",
    "part_number",
    "supplier",
    "datacenter",
    "shelf",
    "quantity",
    "migration_warnings",
    "conflicts",
    "selection_reasons",
    "quota_flags",
    "import_decision",
    "source_receipt_date",
    "source_receipt_date_raw",
    "source_receipt_date_cell_type",
    "source_receipt_date_number_format",
    "source_date_status",
    "imported_at",
}

_REQUIRED_SELECTION_COLUMNS = {
    "id",
    "selection_order",
    "staging_row_id",
    "source_file",
    "source_sheet",
    "source_row",
    "source_row_hash",
    "source_serial_value",
    "normalized_match_value",
    "serial_preservation_status",
    "source_item_name",
    "canonical_item_name",
    "migration_warnings",
    "selection_reasons",
    "conflict_types",
    "import_decision",
    "target_receipt_id",
}

_LOCAL_PATH = re.compile(
    r"(?<![\w:])(?:[A-Za-z]:[\\/][^\s;,]+|"
    r"/(?:Users|home|private|tmp|var|opt|etc)/[^\s;,]+)"
)
_PATH_REDACTED_FIELDS = {
    "source_sheet",
    "canonical_item_name",
    "source_item_name",
    "object_kind",
    "equipment_category",
    "equipment_type",
    "component_type",
    "vendor",
    "model",
    "supplier",
    "datacenter",
    "shelf",
}


def migration_pilot_requested() -> bool:
    """Return whether the process was explicitly launched as a pilot."""
    return os.environ.get(PILOT_ENV) == "1"


def _readonly_connection(path: Path) -> sqlite3.Connection:
    # mode=ro prevents accidental creation. immutable=1 prevents SQLite from
    # creating sidecars; the guard rejects pre-existing sidecars separately.
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _same_file(left: Path, right: Path) -> bool:
    if left.resolve() == right.resolve():
        return True
    if left.exists() and right.exists():
        try:
            return os.path.samefile(left, right)
        except OSError:
            return False
    return False


def _sidecars(path: Path) -> list[str]:
    found: list[str] = []
    for suffix in ("-wal", "-shm", "-journal"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            found.append(candidate.name)
    return found


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }


def _marker_value(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row:
            return row[name]
    return None


def validate_migration_pilot_database(
    db_path: str | Path,
    *,
    enabled: bool | None = None,
) -> dict[str, Any]:
    """Validate the opt-in marker contract before ODE initializes a service.

    A marked database without the environment flag and a flag without a valid
    marker both fail closed.  A normal ODE database returns ``enabled=False``.
    The returned path is a browser-safe logical label, never an absolute path.
    """
    requested = migration_pilot_requested() if enabled is None else bool(enabled)
    selected = Path(db_path).expanduser()
    if not selected.exists():
        if requested:
            raise RuntimeError(f"Миграционная pilot DB не найдена: {selected.name}")
        return {"enabled": False}

    marker_present = False
    marker_rows: list[dict[str, Any]] = []
    tables: set[str] = set()
    try:
        with closing(_readonly_connection(selected)) as connection:
            tables = _table_names(connection)
            marker_present = PILOT_MARKER_TABLE in tables
            if marker_present:
                marker_rows = [
                    dict(row)
                    for row in connection.execute(
                        f'SELECT * FROM "{PILOT_MARKER_TABLE}"'
                    )
                ]
    except sqlite3.Error as error:
        if requested:
            raise RuntimeError("Pilot DB не читается как SQLite") from error
        return {"enabled": False}

    if marker_present and not requested:
        raise RuntimeError(
            f"{PILOT_ENV}=1 обязателен для запуска помеченной migration pilot DB"
        )
    if not requested:
        return {"enabled": False}
    if not marker_present:
        raise RuntimeError("В выбранной DB отсутствует migration pilot marker")
    if selected.name != PILOT_FILENAME:
        raise RuntimeError(f"Pilot DB должна называться {PILOT_FILENAME}")
    if _same_file(selected, DEFAULT_DB_PATH):
        raise RuntimeError("Migration pilot нельзя запускать на data/warehouse.db")
    if os.name == "posix" and stat.S_IMODE(selected.stat().st_mode) != 0o600:
        raise RuntimeError("Pilot DB должна иметь приватный POSIX mode 0600")
    if len(marker_rows) != 1:
        raise RuntimeError("Migration pilot marker должен содержать ровно одну строку")
    missing_tables = sorted(_REQUIRED_REVIEW_TABLES - tables)
    if missing_tables:
        raise RuntimeError(
            "Pilot DB не содержит обязательные review-таблицы: "
            + ", ".join(missing_tables)
        )
    unexpected_pilot_tables = sorted(
        name for name in tables if name.startswith("migration_pilot_") and name not in _PILOT_TABLES
    )
    if unexpected_pilot_tables:
        raise RuntimeError(
            "Pilot DB содержит неизвестные migration_pilot_* таблицы: "
            + ", ".join(unexpected_pilot_tables)
        )

    marker = marker_rows[0]
    marker_name = str(_marker_value(marker, "marker") or "")
    stage = str(_marker_value(marker, "stage", "stage_version") or "")
    status = str(_marker_value(marker, "status", "build_status") or "")
    pilot_only = _marker_value(marker, "pilot_only", "is_pilot")
    review_read_only = _marker_value(marker, "review_read_only", "read_only")
    if marker_name != "ODE_MIGRATION_PILOT":
        raise RuntimeError("Неверное значение migration pilot marker")
    if stage != PILOT_STAGE:
        raise RuntimeError(f"Неверный pilot stage marker: {stage or 'пусто'}")
    if str(status).upper() != "READY_FOR_REVIEW":
        raise RuntimeError(f"Pilot DB не готова к review: {status or 'пусто'}")
    try:
        marker_flags = (int(pilot_only or 0), int(review_read_only or 0))
    except (TypeError, ValueError) as error:
        raise RuntimeError("Pilot marker содержит некорректные safety flags") from error
    if marker_flags != (1, 1):
        raise RuntimeError("Pilot marker не подтверждает pilot-only read-only режим")
    sidecars = _sidecars(selected)
    if sidecars:
        raise RuntimeError("У pilot DB обнаружены SQLite sidecar-файлы: " + ", ".join(sidecars))

    with closing(_readonly_connection(selected)) as connection:
        integrity = [str(row[0]) for row in connection.execute("PRAGMA integrity_check")]
        foreign_keys = list(connection.execute("PRAGMA foreign_key_check"))
        selected_count = int(connection.execute(
            "SELECT COUNT(*) FROM migration_pilot_selection"
        ).fetchone()[0])
        imported_count = int(connection.execute(
            "SELECT COUNT(*) FROM migration_pilot_identities"
        ).fetchone()[0])
        quarantined_count = int(connection.execute(
            "SELECT COUNT(*) FROM migration_pilot_quarantine"
        ).fetchone()[0])
    if integrity != ["ok"]:
        raise RuntimeError("integrity_check pilot DB завершился ошибкой")
    if foreign_keys:
        raise RuntimeError("foreign_key_check pilot DB обнаружил нарушения")
    expected_counts = {
        "selected_count": selected_count,
        "imported_count": imported_count,
        "quarantined_count": quarantined_count,
    }
    for column, actual in expected_counts.items():
        try:
            expected = int(marker[column])
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError(f"Pilot marker не содержит корректный {column}") from error
        if expected != actual:
            raise RuntimeError(
                f"Pilot marker {column}={expected}, фактическое значение={actual}"
            )
    return {
        "enabled": True,
        "stage": PILOT_STAGE,
        "status": "READY_FOR_REVIEW",
        "pilot_only": True,
        "review_read_only": True,
        "database": _logical_database_path(selected),
    }


def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [
        str(row[1])
        for row in connection.execute(f'PRAGMA table_info("{table}")')
        if str(row[1]) in _SAFE_COLUMNS
    ]


def _rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    columns = _columns(connection, table)
    if not columns:
        return []
    projection = ", ".join(f'"{column}"' for column in columns)
    return [dict(row) for row in connection.execute(f'SELECT {projection} FROM "{table}"')]


def _first(source: dict[str, Any], names: Iterable[str]) -> Any:
    for name in names:
        value = source.get(name)
        if value is not None and value != "":
            return value
    return ""


def _basename(value: Any) -> str:
    return str(value or "").replace("\\", "/").rsplit("/", 1)[-1]


def _logical_database_path(path: Path) -> str:
    project_root = DEFAULT_DB_PATH.resolve().parent.parent
    try:
        return path.resolve().relative_to(project_root).as_posix()
    except ValueError:
        return path.name


def _jsonish(value: Any) -> Any:
    if value is None or value == "":
        return []
    if isinstance(value, (list, dict)):
        return _redact_paths(value)
    text = str(value)
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return [_redact_paths(text)]
    if isinstance(parsed, (list, dict)):
        return _redact_paths(parsed)
    return [_redact_paths(str(parsed))]


def _redact_paths(value: Any) -> Any:
    if isinstance(value, list):
        return [_redact_paths(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _redact_paths(item) for key, item in value.items()}
    return _LOCAL_PATH.sub("[local-path-redacted]", str(value or ""))


def _canonical_row(row: dict[str, Any]) -> dict[str, Any]:
    result = {key: row.get(key, "") for key in _PUBLIC_KEYS if key in row}
    for key, aliases in _ALIASES.items():
        result[key] = _first(row, aliases)
    result["source_file"] = _basename(result.get("source_file"))
    for key in _PATH_REDACTED_FIELDS:
        if key in result:
            result[key] = _redact_paths(result[key])
    result["selection_id"] = int(result.get("selection_id") or 0)
    result["source_row"] = int(result.get("source_row") or 0)
    for key in ("migration_warnings", "conflicts", "selection_reasons"):
        result[key] = _jsonish(result.get(key))
    # Internal link is kept only until get_card() has resolved the position.
    result["_receipt_id"] = int(_first(row, _ALIASES["receipt_id"]) or 0)
    return result


def _join_key(row: dict[str, Any]) -> tuple[str, str]:
    if row.get("selection_id"):
        return ("selection", str(row["selection_id"]))
    if row.get("staging_row_id"):
        return ("staging", str(row["staging_row_id"]))
    return (
        "source",
        "|".join(
            str(row.get(key) or "")
            for key in ("source_file", "source_sheet", "source_row", "source_row_hash")
        ),
    )


class MigrationPilotReviewService:
    """Role-gated, read-only projection of a validated pilot database."""

    def __init__(self, db_path: str | Path, *, actor_provider: Any):
        self.db_path = Path(db_path)
        self.actor_provider = actor_provider

    def _require_role(self) -> dict[str, Any]:
        user = self.actor_provider.current_user()
        if user.get("role") not in {"admin", "engineer"}:
            raise WarehouseError("Pilot review доступен только инженеру или администратору")
        return user

    def _validated(self) -> dict[str, Any]:
        try:
            return validate_migration_pilot_database(self.db_path, enabled=True)
        except RuntimeError as error:
            raise WarehouseError(str(error)) from error

    def _all_rows(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        self._validated()
        with closing(_readonly_connection(self.db_path)) as connection:
            selection_columns = set(_columns(connection, "migration_pilot_selection"))
            missing = sorted(_REQUIRED_SELECTION_COLUMNS - selection_columns)
            if missing:
                raise WarehouseError(
                    "Pilot selection schema несовместима с runtime review: "
                    + ", ".join(missing)
                )
            selection = [_canonical_row(row) for row in _rows(connection, "migration_pilot_selection")]
            identities = [_canonical_row(row) for row in _rows(connection, "migration_pilot_identities")]
            provenance = [_canonical_row(row) for row in _rows(connection, "migration_pilot_provenance")]
            quarantine = [_canonical_row(row) for row in _rows(connection, "migration_pilot_quarantine")]

        supplements: dict[tuple[str, str], dict[str, Any]] = {}
        for row in identities + quarantine:
            supplements.setdefault(_join_key(row), {}).update(
                {key: value for key, value in row.items() if value not in (None, "", [], {})}
            )
        for row in selection:
            extra = supplements.get(_join_key(row), {})
            for key, value in extra.items():
                if row.get(key) in (None, "", [], {}):
                    row[key] = value
        return selection, provenance

    @staticmethod
    def _filter_bucket(decision: str, preservation: str) -> str:
        decision = decision.upper()
        preservation = preservation.upper()
        if decision == "IMPORT":
            return "IMPORT"
        if decision in {"QUARANTINE", "MANUAL_REVIEW"}:
            return "QUARANTINE"
        if decision in {"CONFLICT_HISTORY_ONLY", "EXACT_DUPLICATE"}:
            return "CONFLICT"
        if decision == "SOURCE_CORRUPTED_REJECTED" or "SOURCE_CORRUPTED" in preservation:
            return "CORRUPTED"
        return decision

    def list_rows(
        self,
        *,
        filter_name: str = "",
        query: str = "",
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        self._require_role()
        rows, _ = self._all_rows()
        buckets = {"IMPORT", "QUARANTINE", "CONFLICT", "CORRUPTED"}
        requested_filter = filter_name.strip().upper()
        if requested_filter and requested_filter not in buckets:
            raise WarehouseError("Неизвестный фильтр migration pilot")
        needle = query.strip().casefold()
        matched: list[dict[str, Any]] = []
        counts = {key: 0 for key in buckets}
        decisions: dict[str, int] = {}
        for row in rows:
            decision = str(row.get("import_decision") or "UNKNOWN").upper()
            bucket = self._filter_bucket(
                decision, str(row.get("serial_preservation_status") or "")
            )
            row["filter_bucket"] = bucket
            decisions[decision] = decisions.get(decision, 0) + 1
            if bucket in counts:
                counts[bucket] += 1
            if requested_filter and bucket != requested_filter:
                continue
            if needle and needle not in " ".join(
                str(row.get(key) or "")
                for key in (
                    "source_serial_value",
                    "canonical_item_name",
                    "source_item_name",
                    "vendor",
                    "model",
                    "source_sheet",
                    "source_row",
                    "import_decision",
                )
            ).casefold():
                continue
            matched.append(row)
        matched.sort(
            key=lambda row: (
                str(row.get("import_decision") or ""),
                str(row.get("normalized_match_value") or ""),
                int(row.get("source_row") or 0),
                int(row.get("selection_id") or 0),
            )
        )
        safe_limit = max(1, min(int(limit), 300))
        safe_offset = max(0, int(offset))
        page = matched[safe_offset : safe_offset + safe_limit]
        for row in page:
            row["has_card"] = int(row.get("_receipt_id") or 0) > 0
            row.pop("_receipt_id", None)
        return {
            "rows": page,
            "total": len(matched),
            "selected_count": len(rows),
            "limit": safe_limit,
            "offset": safe_offset,
            "counts": counts,
            "decisions": decisions,
        }

    def get_card(self, selection_id: int) -> dict[str, Any]:
        self._require_role()
        rows, provenance = self._all_rows()
        selected = next(
            (row for row in rows if int(row.get("selection_id") or 0) == int(selection_id)),
            None,
        )
        if selected is None:
            raise WarehouseError("Строка migration pilot не найдена")
        decision = str(selected.get("import_decision") or "").upper()
        if decision not in {"IMPORT", "EXACT_DUPLICATE", "CONFLICT_HISTORY_ONLY"}:
            raise WarehouseError("Pilot-строка не связана с Equipment Card")
        source_serial = str(selected.get("source_serial_value") or "")
        if not source_serial:
            raise WarehouseError("У pilot-строки отсутствует сохранный source S/N")
        receipt_id = int(selected.get("_receipt_id") or 0)
        if receipt_id <= 0:
            raise WarehouseError("Pilot-строка не связана с pilot receipt")
        with closing(_readonly_connection(self.db_path)) as connection:
            identity = connection.execute(
                """SELECT preserved_serial_value
                     FROM migration_pilot_identities
                    WHERE target_receipt_id = ? AND normalized_match_value = ?""",
                (receipt_id, str(selected.get("normalized_match_value") or "")),
            ).fetchone()
        if identity is None:
            raise WarehouseError("Pilot identity mapping для карточки не найден")
        preserved_identity_serial = str(identity["preserved_serial_value"] or "")
        response = self.actor_provider.position_card(receipt_id=receipt_id)
        position = dict(response.get("position") or {})
        if str(position.get("serial_number") or "") != preserved_identity_serial:
            raise WarehouseError(
                "Exact S/N pilot-карточки не совпал с preserved identity S/N"
            )
        history = [dict(row) for row in response.get("history") or []]
        receipt_relabelled = False
        for event in history:
            if not receipt_relabelled and event.get("event_type") in {
                "Приход", "Начальный остаток"
            }:
                event["event_type"] = "Исторический приход (миграция)"
                receipt_relabelled = True

        selected_match_key = str(selected.get("normalized_match_value") or "")
        source_rows: list[dict[str, Any]] = []
        for source in provenance:
            if str(source.get("normalized_match_value") or "") != selected_match_key:
                continue
            public = {key: value for key, value in source.items() if key in _PUBLIC_KEYS}
            public["source_file"] = _basename(public.get("source_file"))
            source_rows.append(public)
        if not source_rows:
            source_rows.append({
                key: value for key, value in selected.items() if key in _PUBLIC_KEYS
            })
        migration = {key: value for key, value in selected.items() if key in _PUBLIC_KEYS}
        migration["preserved_identity_serial"] = preserved_identity_serial
        migration["source_rows"] = source_rows
        migration["timeline_label"] = "Исторический приход (миграция)"
        return {"position": position, "history": history, "migration": migration}
