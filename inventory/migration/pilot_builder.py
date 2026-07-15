"""Build and validate the disposable Stage 0.13.3A.5 receipt pilot.

The module belongs to the offline migration context.  Runtime receipt/audit
functions are injected by ``scripts/migration_pilot.py`` so this package never
imports the warehouse runtime and can never initialize the production DB.
"""

from __future__ import annotations

from collections import Counter
from contextlib import closing
from dataclasses import dataclass, fields
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile
from time import perf_counter
from typing import Any, Callable, Mapping

from .pilot_models import (
    CONFLICT_HISTORY_ONLY,
    EXACT_DUPLICATE,
    IMPORT,
    MANUAL_REVIEW,
    PILOT_DECISIONS,
    PILOT_MARKER,
    PILOT_SELECTION_SEED,
    PILOT_SELECTION_SIZE,
    PILOT_STAGE,
    PILOT_STATUS,
    QUANTITY_POSITION_DEFERRED,
    QUARANTINE,
    SOURCE_CORRUPTED_REJECTED,
    PilotBuildResult,
    PilotPaths,
    PilotSelection,
    PilotSelectionRow,
)
from .pilot_schema import PILOT_TABLES, create_pilot_schema
from .pilot_selector import select_pilot_receipts
from .serial_preservation import normalize_serial_match
from .validation import (
    SQLITE_SIDECAR_SUFFIXES,
    assert_source_database_safe,
    candidate_sidecars,
    connect_readonly,
    sha256_file,
    source_content_state,
)
from .xlsx_cells import iter_xlsx_cells, read_text_xlsx, write_text_xlsx


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RAW_DIR = ROOT / "migration_inputs" / "raw"
DEFAULT_NORMALIZED_DIR = ROOT / "migration_inputs" / "normalized"
DEFAULT_SOURCE_CANDIDATE = (
    ROOT / "migration_inputs" / "workspace" / "warehouse_migration_candidate.db"
)
DEFAULT_PILOT_DB = (
    ROOT / "migration_inputs" / "workspace" / "warehouse_pilot_candidate.db"
)
DEFAULT_SERIAL_REVIEW = DEFAULT_NORMALIZED_DIR / "serial_review.xlsx"
DEFAULT_SELECTION_XLSX = (
    ROOT / "migration_inputs" / "reports" / "PILOT_RECEIPT_SELECTION.xlsx"
)
DEFAULT_SELECTION_MARKDOWN = (
    ROOT / "migration_inputs" / "reports" / "PILOT_RECEIPT_SELECTION.md"
)
DEFAULT_SOURCE_WORKBOOK = DEFAULT_RAW_DIR / "warehouse_accounting_source.xlsx"

LINKED_DECISIONS = frozenset({IMPORT, EXACT_DUPLICATE, CONFLICT_HISTORY_ONLY})
QUARANTINE_DECISIONS = frozenset(
    {
        QUARANTINE,
        MANUAL_REVIEW,
        QUANTITY_POSITION_DEFERRED,
        SOURCE_CORRUPTED_REJECTED,
    }
)
EXPECTED_DECISION_COUNTS = {
    IMPORT: 130,
    QUARANTINE: 10,
    MANUAL_REVIEW: 7,
    EXACT_DUPLICATE: 6,
    CONFLICT_HISTORY_ONLY: 35,
    QUANTITY_POSITION_DEFERRED: 10,
    SOURCE_CORRUPTED_REJECTED: 2,
}


@dataclass(frozen=True)
class PilotRuntimeHooks:
    """Warehouse-owned writes injected into the offline pilot builder."""

    write_receipt: Callable[..., int]
    write_source_row_linked: Callable[..., None]
    write_conflict_recorded: Callable[..., None]
    write_exact_duplicate_skipped: Callable[..., None]
    write_serial_quarantined: Callable[..., None]


def default_pilot_paths(*, production_db: Path) -> PilotPaths:
    return PilotPaths(
        source_candidate=DEFAULT_SOURCE_CANDIDATE,
        production_db=production_db,
        raw_dir=DEFAULT_RAW_DIR,
        normalized_dir=DEFAULT_NORMALIZED_DIR,
        serial_review=DEFAULT_SERIAL_REVIEW,
        pilot_db=DEFAULT_PILOT_DB,
        selection_xlsx=DEFAULT_SELECTION_XLSX,
        selection_markdown=DEFAULT_SELECTION_MARKDOWN,
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _portable(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


def _same_file_or_path(left: Path, right: Path) -> bool:
    if left.resolve() == right.resolve():
        return True
    if left.exists() and right.exists():
        try:
            return os.path.samefile(left, right)
        except OSError:
            return False
    return False


def _raw_hashes(raw_dir: Path) -> dict[str, str]:
    if not raw_dir.is_dir():
        raise FileNotFoundError(raw_dir)
    files = sorted(path for path in raw_dir.iterdir() if path.is_file())
    if not files:
        raise RuntimeError("raw migration directory is empty")
    return {path.name: sha256_file(path) for path in files}


def assert_safe_pilot_paths(paths: PilotPaths) -> None:
    """Reject output/source aliasing, hardlinks and production output paths."""

    sources = [
        paths.source_candidate,
        paths.production_db,
        paths.serial_review,
        *sorted(path for path in paths.raw_dir.glob("*") if path.is_file()),
    ]
    outputs = [paths.pilot_db, paths.selection_xlsx, paths.selection_markdown]
    if paths.pilot_db.name != "warehouse_pilot_candidate.db":
        raise ValueError("pilot DB must be named warehouse_pilot_candidate.db")
    for source in sources:
        if not source.is_file():
            raise FileNotFoundError(source)
    for output in outputs:
        for source in sources:
            if _same_file_or_path(output, source):
                raise RuntimeError(
                    f"pilot output {_portable(output)} aliases immutable source "
                    f"{_portable(source)}"
                )
    for index, left in enumerate(outputs):
        for right in outputs[index + 1 :]:
            if _same_file_or_path(left, right):
                raise RuntimeError("pilot output paths must be distinct")
    if any(Path(str(paths.pilot_db) + suffix).exists() for suffix in SQLITE_SIDECAR_SUFFIXES):
        raise RuntimeError("pilot output has SQLite sidecars; stop review before rebuild")


def _selection_serialized(rows: list[PilotSelectionRow] | tuple[PilotSelectionRow, ...]) -> bytes:
    return json.dumps(
        [row.as_mapping() for row in rows],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _row_for_writer(row: PilotSelectionRow) -> dict[str, Any]:
    result = row.as_mapping()
    result.update(
        {
            "decision": row.import_decision,
            "receipt_date": row.source_receipt_date,
            "category": row.equipment_category,
            "responsible": "Миграционный пилот",
            "object_name": "Исторический склад",
            "inventory_number": "",
            "project": "",
            "order_date": "",
            "request_number": "",
            "order_number": "",
            "plu": "",
        }
    )
    return result


_SELECTION_COLUMNS = (
    "selection_order",
    "staging_row_id",
    "migration_batch_id",
    "source_file",
    "source_sheet",
    "source_row",
    "source_row_hash",
    "source_serial_value",
    "normalized_match_value",
    "serial_preservation_status",
    "excel_cell_type",
    "excel_number_format",
    "raw_xml_value",
    "source_display_value",
    "source_serial_hash",
    "source_item_name",
    "canonical_item_name",
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
    "source_receipt_date",
    "source_receipt_date_raw",
    "source_receipt_date_status",
    "source_receipt_date_cell_type",
    "source_receipt_date_number_format",
    "migration_warnings",
    "selection_reasons",
    "quota_flags",
    "conflict_types",
    "duplicate_group_size",
    "import_decision",
    "identity_key",
    "target_receipt_id",
    "created_at",
)


def _selection_values(row: PilotSelectionRow, created_at: str) -> tuple[Any, ...]:
    source = row.as_mapping()
    source.update(
        {
            "migration_warnings": json.dumps(
                row.migration_warnings, ensure_ascii=False
            ),
            "selection_reasons": json.dumps(
                row.selection_reasons, ensure_ascii=False
            ),
            "quota_flags": json.dumps(row.quota_flags, ensure_ascii=False),
            "conflict_types": json.dumps(row.conflict_types, ensure_ascii=False),
            "created_at": created_at,
        }
    )
    return tuple(source[column] for column in _SELECTION_COLUMNS)


def _insert_selection(
    connection: sqlite3.Connection,
    selection: PilotSelection,
    *,
    created_at: str,
) -> None:
    columns = ", ".join(_SELECTION_COLUMNS)
    placeholders = ", ".join("?" for _ in _SELECTION_COLUMNS)
    connection.executemany(
        f"INSERT INTO migration_pilot_selection({columns}) VALUES ({placeholders})",
        (_selection_values(row, created_at) for row in selection.rows),
    )


def _insert_provenance(
    connection: sqlite3.Connection,
    row: PilotSelectionRow,
    *,
    selection_id: int,
    identity_id: int | None,
    target_receipt_id: int | None,
    created_at: str,
) -> None:
    connection.execute(
        """INSERT INTO migration_pilot_provenance(
               selection_id, identity_id, target_receipt_id,
               source_file, source_sheet, source_row, source_row_hash,
               source_serial_value, normalized_match_value,
               source_item_name, canonical_item_name,
               source_receipt_date, source_receipt_date_raw,
               source_receipt_date_status, shelf, import_decision,
               warnings, created_at
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            selection_id,
            identity_id,
            target_receipt_id,
            Path(row.source_file).name,
            row.source_sheet,
            row.source_row,
            row.source_row_hash,
            row.source_serial_value,
            row.normalized_match_value,
            row.source_item_name,
            row.canonical_item_name,
            row.source_receipt_date,
            row.source_receipt_date_raw,
            row.source_receipt_date_status,
            row.shelf,
            row.import_decision,
            json.dumps(row.migration_warnings, ensure_ascii=False),
            created_at,
        ),
    )


def _measure_query(
    connection: sqlite3.Connection, sql: str, parameters: tuple[Any, ...] = ()
) -> tuple[float, list[sqlite3.Row]]:
    started = perf_counter()
    rows = connection.execute(sql, parameters).fetchall()
    return (perf_counter() - started) * 1000, rows


def _create_pilot_file(
    destination: Path,
    source_candidate: Path,
    selection: PilotSelection,
    hooks: PilotRuntimeHooks,
    *,
    selection_ms: float,
    copy_started: float,
) -> dict[str, Any]:
    build_started_at = _utc_now()
    shutil.copy2(source_candidate, destination)
    if os.name == "posix":
        destination.chmod(0o600)
    copy_ms = (perf_counter() - copy_started) * 1000
    built_at = _utc_now()
    with closing(sqlite3.connect(destination)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        create_pilot_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        try:
            _insert_selection(connection, selection, created_at=built_at)
            selection_ids = {
                int(row["staging_row_id"]): int(row["id"])
                for row in connection.execute(
                    "SELECT id, staging_row_id FROM migration_pilot_selection"
                )
            }
            target_by_identity: dict[str, int] = {}
            identity_id_by_key: dict[str, int] = {}
            import_started = perf_counter()
            for row in selection.rows:
                if row.import_decision != IMPORT:
                    continue
                if row.identity_key in target_by_identity:
                    raise RuntimeError("selector produced two IMPORT rows for one identity")
                receipt_id = hooks.write_receipt(
                    connection,
                    _row_for_writer(row),
                    author="migration-pilot",
                )
                target_by_identity[row.identity_key] = receipt_id
                connection.execute(
                    "UPDATE migration_pilot_selection SET target_receipt_id=? "
                    "WHERE staging_row_id=?",
                    (receipt_id, row.staging_row_id),
                )

            linked_counts = Counter(
                row.identity_key
                for row in selection.rows
                if row.import_decision in LINKED_DECISIONS
            )
            for row in selection.rows:
                if row.import_decision != IMPORT:
                    continue
                receipt_id = target_by_identity[row.identity_key]
                cursor = connection.execute(
                    """INSERT INTO migration_pilot_identities(
                           normalized_match_value, preserved_serial_value,
                           primary_selection_id, target_receipt_id,
                           source_row_count, created_at
                       ) VALUES (?,?,?,?,?,?)""",
                    (
                        row.normalized_match_value,
                        row.source_serial_value,
                        selection_ids[row.staging_row_id],
                        receipt_id,
                        linked_counts[row.identity_key],
                        built_at,
                    ),
                )
                identity_id_by_key[row.identity_key] = int(cursor.lastrowid)

            for row in selection.rows:
                selection_id = selection_ids[row.staging_row_id]
                target_receipt_id: int | None = None
                identity_id: int | None = None
                source = _row_for_writer(row)
                if row.import_decision in LINKED_DECISIONS:
                    target_receipt_id = target_by_identity.get(row.identity_key)
                    identity_id = identity_id_by_key.get(row.identity_key)
                    if target_receipt_id is None or identity_id is None:
                        raise RuntimeError(
                            "linked provenance has no IMPORT primary identity"
                        )
                    connection.execute(
                        "UPDATE migration_pilot_selection SET target_receipt_id=? "
                        "WHERE id=?",
                        (target_receipt_id, selection_id),
                    )
                    if row.import_decision != IMPORT:
                        hooks.write_source_row_linked(
                            connection,
                            receipt_id=target_receipt_id,
                            source=source,
                            author="migration-pilot",
                        )
                    if row.import_decision == EXACT_DUPLICATE:
                        hooks.write_exact_duplicate_skipped(
                            connection,
                            receipt_id=target_receipt_id,
                            source=source,
                            author="migration-pilot",
                        )
                    elif row.import_decision == CONFLICT_HISTORY_ONLY:
                        hooks.write_conflict_recorded(
                            connection,
                            receipt_id=target_receipt_id,
                            source=source,
                            author="migration-pilot",
                        )
                else:
                    if row.import_decision not in QUARANTINE_DECISIONS:
                        raise RuntimeError(
                            f"unsupported pilot decision: {row.import_decision}"
                        )
                    connection.execute(
                        """INSERT INTO migration_pilot_quarantine(
                               selection_id, reason_code, created_at
                           ) VALUES (?,?,?)""",
                        (selection_id, row.import_decision, built_at),
                    )
                    hooks.write_serial_quarantined(
                        connection,
                        source=source,
                        author="migration-pilot",
                        staging_row_id=row.staging_row_id,
                    )
                _insert_provenance(
                    connection,
                    row,
                    selection_id=selection_id,
                    identity_id=identity_id,
                    target_receipt_id=target_receipt_id,
                    created_at=built_at,
                )
            import_ms = (perf_counter() - import_started) * 1000

            list_ms, list_rows = _measure_query(
                connection,
                "SELECT id FROM migration_pilot_selection "
                "ORDER BY import_decision, normalized_match_value, source_row",
            )
            leading = next(
                row
                for row in selection.rows
                if row.import_decision == IMPORT and row.source_serial_value.startswith("0")
            )
            search_ms, search_rows = _measure_query(
                connection,
                "SELECT id FROM stock_receipts WHERE serial_number=?",
                (leading.source_serial_value,),
            )
            receipt_id = target_by_identity[leading.identity_key]
            card_ms, card_rows = _measure_query(
                connection,
                "SELECT id, serial_number, item_name, vendor, model, shelf "
                "FROM stock_receipts WHERE id=?",
                (receipt_id,),
            )
            timeline_ms, timeline_rows = _measure_query(
                connection,
                "SELECT id, action, event_date FROM audit_log "
                "WHERE entity_type='stock_receipt' AND entity_id=? ORDER BY id",
                (str(receipt_id),),
            )
            if (
                len(list_rows) != PILOT_SELECTION_SIZE
                or len(search_rows) != 1
                or len(card_rows) != 1
                or not timeline_rows
            ):
                raise RuntimeError("pilot performance probes returned invalid results")
            metrics = {
                "selection": selection_ms,
                "candidate_copy_and_schema": copy_ms,
                "pilot_200_row_processing": import_ms,
                "review_list_query": list_ms,
                "exact_serial_search": search_ms,
                "equipment_card_query": card_ms,
                "timeline_query": timeline_ms,
                "pilot_database_build": (perf_counter() - copy_started) * 1000,
            }
            connection.executemany(
                """INSERT INTO migration_pilot_performance(
                       metric, duration_ms, measured_at, details
                   ) VALUES (?,?,?,?)""",
                (
                    (
                        metric,
                        f"{duration:.3f}",
                        built_at,
                        json.dumps({"scope": "database-side pilot probe"}),
                    )
                    for metric, duration in metrics.items()
                ),
            )
            decision_counts = {
                decision: int(selection.decision_counts.get(decision, 0))
                for decision in PILOT_DECISIONS
            }
            connection.execute(
                """INSERT INTO migration_pilot_marker(
                       id, marker, stage, pilot_only, review_read_only, status,
                       selection_seed, selection_sha256,
                       source_candidate_sha256, source_manifest_sha256,
                       serial_review_sha256, selected_count, imported_count,
                       quarantined_count, decision_counts, quota_counts,
                       unavailable_requirements, build_started_at, built_at
                   ) VALUES (1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    PILOT_MARKER,
                    PILOT_STAGE,
                    1,
                    1,
                    PILOT_STATUS,
                    PILOT_SELECTION_SEED,
                    selection.selection_sha256,
                    selection.source_candidate_sha256,
                    selection.source_manifest_sha256,
                    selection.serial_review_sha256,
                    len(selection.rows),
                    decision_counts[IMPORT],
                    sum(decision_counts[item] for item in QUARANTINE_DECISIONS),
                    json.dumps(decision_counts, sort_keys=True),
                    json.dumps(selection.quota_counts, sort_keys=True),
                    json.dumps(selection.unavailable_requirements),
                    build_started_at,
                    built_at,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    if os.name == "posix":
        destination.chmod(0o600)
    return {"performance_ms": {key: round(value, 3) for key, value in metrics.items()}}


def _selection_from_connection(connection: sqlite3.Connection) -> list[PilotSelectionRow]:
    result: list[PilotSelectionRow] = []
    field_names = tuple(field.name for field in fields(PilotSelectionRow))
    for sql_row in connection.execute(
        "SELECT * FROM migration_pilot_selection ORDER BY selection_order"
    ):
        row = dict(sql_row)
        result.append(
            PilotSelectionRow(
                **{
                    key: (
                        tuple(json.loads(str(row[key] or "[]")))
                        if key in {
                            "migration_warnings",
                            "selection_reasons",
                            "quota_flags",
                            "conflict_types",
                        }
                        else None
                        if key == "target_receipt_id"
                        else row[key]
                    )
                    for key in field_names
                }
            )
        )
    return result


def validate_pilot_database(path: Path) -> dict[str, Any]:
    """Validate pilot marker, preservation, events and card cardinality."""

    if not path.is_file():
        raise FileNotFoundError(path)
    sidecars = candidate_sidecars(path)
    if sidecars:
        raise RuntimeError("pilot DB has SQLite sidecars: " + ", ".join(sidecars))
    mode = stat.S_IMODE(path.stat().st_mode)
    if os.name == "posix" and mode != 0o600:
        raise RuntimeError(f"pilot DB mode must be 0600, got {mode:04o}")
    with closing(connect_readonly(path)) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing = sorted(set(PILOT_TABLES).difference(tables))
        if missing:
            raise RuntimeError("missing pilot tables: " + ", ".join(missing))
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = list(connection.execute("PRAGMA foreign_key_check"))
        marker_rows = list(connection.execute("SELECT * FROM migration_pilot_marker"))
        if integrity != "ok" or foreign_keys:
            raise RuntimeError(
                f"pilot SQLite health failed: integrity={integrity}, fk={len(foreign_keys)}"
            )
        if len(marker_rows) != 1:
            raise RuntimeError("pilot marker must contain exactly one row")
        marker = dict(marker_rows[0])
        marker_contract = {
            "marker": PILOT_MARKER,
            "stage": PILOT_STAGE,
            "status": PILOT_STATUS,
            "pilot_only": 1,
            "review_read_only": 1,
            "selection_seed": PILOT_SELECTION_SEED,
        }
        for key, expected in marker_contract.items():
            if marker.get(key) != expected:
                raise RuntimeError(f"invalid pilot marker {key}: {marker.get(key)!r}")
        selected_count = int(
            connection.execute("SELECT COUNT(*) FROM migration_pilot_selection").fetchone()[0]
        )
        identities = int(
            connection.execute("SELECT COUNT(*) FROM migration_pilot_identities").fetchone()[0]
        )
        provenance = int(
            connection.execute("SELECT COUNT(*) FROM migration_pilot_provenance").fetchone()[0]
        )
        quarantine = int(
            connection.execute("SELECT COUNT(*) FROM migration_pilot_quarantine").fetchone()[0]
        )
        receipts = int(connection.execute("SELECT COUNT(*) FROM stock_receipts").fetchone()[0])
        decision_counts = {
            str(row[0]): int(row[1])
            for row in connection.execute(
                "SELECT import_decision, COUNT(*) FROM migration_pilot_selection "
                "GROUP BY import_decision"
            )
        }
        if selected_count != PILOT_SELECTION_SIZE or decision_counts != EXPECTED_DECISION_COUNTS:
            raise RuntimeError(
                f"pilot selection counts changed: selected={selected_count}, "
                f"decisions={decision_counts}"
            )
        if identities != 130 or receipts != 130 or provenance != selected_count or quarantine != 29:
            raise RuntimeError(
                "pilot cardinality failed: "
                f"identities={identities}, receipts={receipts}, "
                f"provenance={provenance}, quarantine={quarantine}"
            )
        for key, actual in (
            ("selected_count", selected_count),
            ("imported_count", identities),
            ("quarantined_count", quarantine),
        ):
            if int(marker[key]) != actual:
                raise RuntimeError(f"pilot marker {key} does not match data")
        if json.loads(str(marker["decision_counts"])) != EXPECTED_DECISION_COUNTS:
            raise RuntimeError("pilot marker decision_counts mismatch")
        unsafe_links = int(
            connection.execute(
                """SELECT COUNT(*) FROM migration_pilot_selection
                   WHERE (import_decision IN ('IMPORT','EXACT_DUPLICATE','CONFLICT_HISTORY_ONLY')
                          AND target_receipt_id IS NULL)
                      OR (import_decision NOT IN ('IMPORT','EXACT_DUPLICATE','CONFLICT_HISTORY_ONLY')
                          AND target_receipt_id IS NOT NULL)"""
            ).fetchone()[0]
        )
        serial_mismatches = int(
            connection.execute(
                """SELECT COUNT(*)
                     FROM migration_pilot_identities i
                     JOIN stock_receipts r ON r.id=i.target_receipt_id
                    WHERE typeof(i.preserved_serial_value)<>'text'
                       OR typeof(r.serial_number)<>'text'
                       OR r.serial_number<>i.preserved_serial_value COLLATE BINARY
                       OR r.quantity<>1 OR r.is_opening_balance<>1
                       OR r.legacy_equipment_id IS NOT NULL"""
            ).fetchone()[0]
        )
        non_text_selection = int(
            connection.execute(
                """SELECT COUNT(*) FROM migration_pilot_selection
                   WHERE typeof(source_serial_value)<>'text'
                      OR typeof(normalized_match_value)<>'text'
                      OR typeof(part_number)<>'text'"""
            ).fetchone()[0]
        )
        unsafe_source_names = int(
            connection.execute(
                """SELECT COUNT(*) FROM migration_pilot_selection
                   WHERE instr(source_file, '/')>0 OR instr(source_file, char(92))>0"""
            ).fetchone()[0]
        )
        production_rows = {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "stock_issues",
                "stock_issue_allocations",
                "equipment",
                "deliveries",
                "delivery_lines",
            )
        }
        if unsafe_links or serial_mismatches or non_text_selection or unsafe_source_names:
            raise RuntimeError(
                "pilot preservation/link validation failed: "
                f"links={unsafe_links}, serials={serial_mismatches}, "
                f"text={non_text_selection}, paths={unsafe_source_names}"
            )
        if any(production_rows.values()):
            raise RuntimeError("pilot contains forbidden operational/legacy rows")
        audit_counts = {
            str(row[0]): int(row[1])
            for row in connection.execute(
                "SELECT action, COUNT(*) FROM audit_log "
                "WHERE action LIKE 'MIGRATION_%' GROUP BY action"
            )
        }
        expected_audits = {
            "MIGRATION_RECEIPT_IMPORTED": 130,
            "MIGRATION_SOURCE_ROW_LINKED": 171,
            "MIGRATION_CONFLICT_RECORDED": 35,
            "MIGRATION_EXACT_DUPLICATE_SKIPPED": 6,
            "MIGRATION_SERIAL_QUARANTINED": 29,
        }
        if audit_counts != expected_audits:
            raise RuntimeError(f"pilot audit counts changed: {audit_counts}")
        active_admins = int(
            connection.execute(
                "SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1"
            ).fetchone()[0]
        )
        if active_admins < 1:
            raise RuntimeError("pilot DB has no active administrator")
        reconstructed = _selection_from_connection(connection)
        selection_sha = hashlib.sha256(_selection_serialized(reconstructed)).hexdigest()
        if selection_sha != str(marker["selection_sha256"]):
            raise RuntimeError("pilot selection SHA does not match marker")
        normalization_mismatches = sum(
            1
            for row in reconstructed
            if (
                row.serial_preservation_status == "TEXT_EXACT"
                and (
                    row.normalized_match_value
                    != normalize_serial_match(row.source_serial_value)
                    or row.source_display_value != row.source_serial_value
                )
            )
            or (
                row.serial_preservation_status != "TEXT_EXACT"
                and bool(row.normalized_match_value)
            )
            or (
                row.import_decision in LINKED_DECISIONS
                and row.identity_key != row.normalized_match_value
            )
            or (
                row.import_decision not in LINKED_DECISIONS
                and bool(row.identity_key)
            )
        )
        if normalization_mismatches:
            raise RuntimeError(
                "pilot source/match separation failed: "
                f"{normalization_mismatches} row(s)"
            )
        leading_zero_examples = [
            str(row[0])
            for row in connection.execute(
                """SELECT source_serial_value FROM migration_pilot_selection
                   WHERE import_decision='IMPORT' AND source_serial_value GLOB '0*'
                   ORDER BY selection_order LIMIT 10"""
            )
        ]
        performance = {
            str(row[0]): float(row[1])
            for row in connection.execute(
                "SELECT metric, duration_ms FROM migration_pilot_performance"
            )
        }
    return {
        "stage": PILOT_STAGE,
        "status": PILOT_STATUS,
        "pilot_only": True,
        "database": path.name,
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "file_mode": f"{mode:04o}",
        "integrity_check": integrity,
        "foreign_key_errors": 0,
        "sidecars": sidecars,
        "selected_count": selected_count,
        "decision_counts": decision_counts,
        "imported_cards": receipts,
        "identity_rows": identities,
        "provenance_rows": provenance,
        "quarantine_rows": quarantine,
        "audit_counts": audit_counts,
        "active_admins": active_admins,
        "leading_zero_examples": leading_zero_examples,
        "selection_sha256": selection_sha,
        "source_match_mismatches": normalization_mismatches,
        "performance_ms": performance,
        "historical_issues_imported": 0,
        "balance_sheet_rows_imported": 0,
        "production_mutations": 0,
    }


def _report_rows(selection: PilotSelection) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in selection.rows:
        item = row.as_mapping()
        for key in (
            "migration_warnings",
            "selection_reasons",
            "quota_flags",
            "conflict_types",
        ):
            item[key] = json.dumps(item[key], ensure_ascii=False)
        item["target_receipt_id"] = ""
        rows.append(item)
    return rows


def write_selection_reports(
    selection: PilotSelection,
    xlsx_path: Path,
    markdown_path: Path,
    *,
    pilot_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write deterministic human review reports without local absolute paths."""

    summary = [
        {"metric": "stage", "value": PILOT_STAGE},
        {"metric": "selection_seed", "value": PILOT_SELECTION_SEED},
        {"metric": "selection_sha256", "value": selection.selection_sha256},
        {"metric": "selected_count", "value": str(len(selection.rows))},
        *(
            {
                "metric": f"decision_{decision}",
                "value": str(selection.decision_counts.get(decision, 0)),
            }
            for decision in PILOT_DECISIONS
        ),
        *(
            {"metric": f"quota_{key}", "value": str(value)}
            for key, value in sorted(selection.quota_counts.items())
        ),
        {
            "metric": "unavailable_requirements",
            "value": ", ".join(selection.unavailable_requirements),
        },
    ]
    if pilot_report:
        summary.extend(
            (
                {"metric": "pilot_db", "value": str(pilot_report["database"])},
                {"metric": "pilot_db_sha256", "value": str(pilot_report["sha256"])},
                {
                    "metric": "pilot_integrity_check",
                    "value": str(pilot_report["integrity_check"]),
                },
                {
                    "metric": "pilot_foreign_key_errors",
                    "value": str(pilot_report["foreign_key_errors"]),
                },
            )
        )
    report_rows = _report_rows(selection)
    headers = list(report_rows[0])
    write_text_xlsx(
        xlsx_path,
        {
            "SUMMARY": (["metric", "value"], summary),
            "PILOT_SELECTION": (headers, report_rows),
        },
        identifier_columns={
            "SUMMARY": {"value"},
            "PILOT_SELECTION": {
                "source_row_hash",
                "source_serial_value",
                "normalized_match_value",
                "raw_xml_value",
                "source_display_value",
                "source_serial_hash",
                "part_number",
                "identity_key",
            },
        },
    )
    reopened = read_text_xlsx(xlsx_path)
    if len(reopened.get("PILOT_SELECTION", [])) != len(selection.rows):
        raise RuntimeError("pilot selection XLSX round-trip row count failed")
    for expected, actual in zip(
        selection.rows, reopened["PILOT_SELECTION"], strict=True
    ):
        if actual["source_serial_value"] != expected.source_serial_value:
            raise RuntimeError("pilot selection XLSX changed source S/N")
        if actual["part_number"] != expected.part_number:
            raise RuntimeError("pilot selection XLSX changed Part Number")
    identifier_headers = {
        "source_serial_value",
        "normalized_match_value",
        "part_number",
        "raw_xml_value",
    }
    for cell in iter_xlsx_cells(
        xlsx_path,
        sheet_names={"PILOT_SELECTION"},
    ):
        if cell.source_row == 1:
            continue
        header = headers[ord(cell.source_column) - ord("A")] if len(cell.source_column) == 1 else ""
        if header in identifier_headers and cell.excel_number_format != "@":
            raise RuntimeError(f"identifier column {header} is not XLSX text")

    leading = [
        row
        for row in selection.rows
        if row.import_decision == IMPORT and row.source_serial_value.startswith("0")
    ][:10]
    manual = [
        row
        for row in selection.rows
        if row.import_decision in {
            QUARANTINE,
            MANUAL_REVIEW,
            SOURCE_CORRUPTED_REJECTED,
        }
    ][:15]
    canonical_examples: list[str] = []
    for row in selection.rows:
        if row.canonical_item_name and row.canonical_item_name not in canonical_examples:
            canonical_examples.append(row.canonical_item_name)
        if len(canonical_examples) == 10:
            break
    db_lines = ""
    if pilot_report:
        db_lines = (
            f"- Pilot DB: `{pilot_report['database']}`; SHA-256 "
            f"`{pilot_report['sha256']}`.\n"
            f"- SQLite: integrity `{pilot_report['integrity_check']}`, FK errors "
            f"`{pilot_report['foreign_key_errors']}`, imported cards "
            f"`{pilot_report['imported_cards']}`.\n"
        )
    markdown = f"""# ODE Stage 0.13.3A.5 — Pilot Receipt Selection

Дата: {datetime.now().date().isoformat()}.

**PILOT ONLY / NOT PRODUCTION.** Этот отчёт описывает детерминированную
выборку из реального receipt staging. Он не является файлом массового импорта,
не использует лист БАЛАНС и не меняет `data/warehouse.db`.

## Результат

- Seed: `{PILOT_SELECTION_SEED}`.
- Selection SHA-256: `{selection.selection_sha256}`.
- Выбрано: **{len(selection.rows)}** строк; создаётся **{selection.decision_counts[IMPORT]}** карточек.
{db_lines}- Vegman R200: **UNAVAILABLE_FROM_SOURCE**; синтетическая source row не создавалась.
- Literal raw-exact duplicate groups с безопасным primary: **{selection.decision_counts[EXACT_DUPLICATE]}**. Остальные повторные S/N классифицированы как conflict/history, а не объявлены exact.

## Решения

| Решение | Строк |
|---|---:|
"""
    markdown += "".join(
        f"| `{decision}` | {selection.decision_counts.get(decision, 0)} |\n"
        for decision in PILOT_DECISIONS
    )
    markdown += "\n## Coverage\n\n"
    markdown += "".join(
        f"- `{key}`: {value}\n"
        for key, value in sorted(selection.quota_counts.items())
    )
    markdown += "\n## Leading-zero cards for manual comparison\n\n"
    markdown += "".join(
        f"- selection `{row.selection_order}`, source row `{row.source_row}`: `{row.source_serial_value}`\n"
        for row in leading
    ) or "- Нет безопасных IMPORT-примеров.\n"
    markdown += "\n## Canonical-name examples\n\n"
    markdown += "".join(f"- {value}\n" for value in canonical_examples)
    markdown += "\n## Priority manual-review rows\n\n"
    markdown += "".join(
        f"- selection `{row.selection_order}`, source `{row.source_sheet}` row `{row.source_row}`: "
        f"`{row.import_decision}`, preservation `{row.serial_preservation_status}`.\n"
        for row in manual
    )
    markdown += """

## Ограничения и решение пользователя

- Numeric/unproven и `SOURCE_CORRUPTED` строки не создают карточки.
- `source_serial_value` хранится отдельно от match key и записывается символ в символ.
- Shelf остаётся optional provenance и не участвует в identity.
- Huawei/xFusion и разные модели не объединяются aliases автоматически.
- Переход к Stage 0.13.3B возможен только после отдельного ручного одобрения.
"""
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(markdown, encoding="utf-8")
    if os.name == "posix":
        xlsx_path.chmod(0o600)
        markdown_path.chmod(0o600)
    return {
        "xlsx": _portable(xlsx_path),
        "markdown": _portable(markdown_path),
        "xlsx_sha256": sha256_file(xlsx_path),
        "markdown_sha256": sha256_file(markdown_path),
        "rows": len(selection.rows),
    }


def select_and_report(paths: PilotPaths, *, overwrite: bool = False) -> dict[str, Any]:
    assert_safe_pilot_paths(paths)
    existing = [
        path
        for path in (paths.selection_xlsx, paths.selection_markdown)
        if path.exists()
    ]
    if existing and not overwrite:
        raise FileExistsError(
            "pilot selection report exists; use --overwrite: "
            + ", ".join(_portable(path) for path in existing)
        )
    raw_before = _raw_hashes(paths.raw_dir)
    production_before = source_content_state(paths.production_db)
    source_candidate_sha = sha256_file(paths.source_candidate)
    started = perf_counter()
    selection = select_pilot_receipts(
        paths.source_candidate,
        paths.raw_dir / "warehouse_accounting_source.xlsx",
        paths.serial_review,
    )
    selection_ms = (perf_counter() - started) * 1000
    paths.selection_xlsx.parent.mkdir(parents=True, exist_ok=True)
    paths.selection_markdown.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".ode-pilot-selection.", dir=paths.selection_xlsx.parent
    ) as directory:
        root = Path(directory)
        xlsx = root / paths.selection_xlsx.name
        markdown = root / paths.selection_markdown.name
        report = write_selection_reports(selection, xlsx, markdown)
        if _raw_hashes(paths.raw_dir) != raw_before:
            raise RuntimeError("raw migration sources changed during selection")
        if source_content_state(paths.production_db) != production_before:
            raise RuntimeError("production DB changed during selection")
        if sha256_file(paths.source_candidate) != source_candidate_sha:
            raise RuntimeError("Stage 0.13.3A candidate changed during selection")
        paths.selection_xlsx.parent.mkdir(parents=True, exist_ok=True)
        paths.selection_markdown.parent.mkdir(parents=True, exist_ok=True)
        os.replace(xlsx, paths.selection_xlsx)
        os.replace(markdown, paths.selection_markdown)
    return {
        **report,
        "selection_ms": round(selection_ms, 3),
        "selection_sha256": selection.selection_sha256,
        "decision_counts": dict(selection.decision_counts),
        "quota_counts": dict(selection.quota_counts),
        "unavailable_requirements": list(selection.unavailable_requirements),
        "raw_sha_unchanged": True,
        "production_db_unchanged": True,
        "source_candidate_unchanged": True,
    }


def build_pilot(
    paths: PilotPaths,
    hooks: PilotRuntimeHooks,
    *,
    overwrite: bool = False,
) -> PilotBuildResult:
    """Atomically publish reports and the marker-guarded pilot DB."""

    assert_safe_pilot_paths(paths)
    if paths.pilot_db.exists() and not overwrite:
        raise FileExistsError("pilot DB exists; use --overwrite")
    raw_before = _raw_hashes(paths.raw_dir)
    production_before = source_content_state(paths.production_db)
    assert_source_database_safe(paths.production_db)
    source_candidate_sha = sha256_file(paths.source_candidate)
    selection_started = perf_counter()
    selection = select_pilot_receipts(
        paths.source_candidate,
        paths.raw_dir / "warehouse_accounting_source.xlsx",
        paths.serial_review,
    )
    selection_ms = (perf_counter() - selection_started) * 1000
    paths.pilot_db.parent.mkdir(parents=True, exist_ok=True)
    paths.selection_xlsx.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".ode-migration-pilot.", dir=paths.pilot_db.parent
    ) as directory:
        root = Path(directory)
        temporary_db = root / paths.pilot_db.name
        temporary_xlsx = root / paths.selection_xlsx.name
        temporary_markdown = root / paths.selection_markdown.name
        copy_started = perf_counter()
        build_details = _create_pilot_file(
            temporary_db,
            paths.source_candidate,
            selection,
            hooks,
            selection_ms=selection_ms,
            copy_started=copy_started,
        )
        pilot_report = validate_pilot_database(temporary_db)
        report_files = write_selection_reports(
            selection,
            temporary_xlsx,
            temporary_markdown,
            pilot_report=pilot_report,
        )
        raw_after = _raw_hashes(paths.raw_dir)
        production_after = source_content_state(paths.production_db)
        if raw_after != raw_before:
            raise RuntimeError("raw migration sources changed during pilot build")
        if production_after != production_before:
            raise RuntimeError("production DB changed during pilot build")
        if sha256_file(paths.source_candidate) != source_candidate_sha:
            raise RuntimeError("Stage 0.13.3A candidate changed during pilot build")
        # Reports are derived/reviewable; the validated DB is the final marker.
        os.replace(temporary_xlsx, paths.selection_xlsx)
        os.replace(temporary_markdown, paths.selection_markdown)
        os.replace(temporary_db, paths.pilot_db)
        if os.name == "posix":
            paths.pilot_db.chmod(0o600)

    final_report = validate_pilot_database(paths.pilot_db)
    report_files = {
        "xlsx": _portable(paths.selection_xlsx),
        "markdown": _portable(paths.selection_markdown),
        "xlsx_sha256": sha256_file(paths.selection_xlsx),
        "markdown_sha256": sha256_file(paths.selection_markdown),
        "rows": len(selection.rows),
    }
    report = {
        **final_report,
        **build_details,
        "reports": report_files,
        "source_candidate": _portable(paths.source_candidate),
        "source_candidate_sha256": source_candidate_sha,
        "production_database": _portable(paths.production_db),
        "production_database_sha_before": str(production_before["database"]["sha256"]),
        "production_database_sha_after": str(production_after["database"]["sha256"]),
        "production_database_unchanged": True,
        "raw_sha_before": raw_before,
        "raw_sha_after": raw_after,
        "raw_sha_unchanged": True,
        "source_candidate_unchanged": True,
        "unavailable_requirements": list(selection.unavailable_requirements),
    }
    return PilotBuildResult(report=report, selection=selection)


__all__ = [
    "DEFAULT_PILOT_DB",
    "DEFAULT_SELECTION_MARKDOWN",
    "DEFAULT_SELECTION_XLSX",
    "DEFAULT_SOURCE_CANDIDATE",
    "EXPECTED_DECISION_COUNTS",
    "PilotRuntimeHooks",
    "assert_safe_pilot_paths",
    "build_pilot",
    "default_pilot_paths",
    "select_and_report",
    "validate_pilot_database",
    "write_selection_reports",
]
