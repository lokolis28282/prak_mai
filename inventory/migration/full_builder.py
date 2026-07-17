"""Build and validate the full disposable historical warehouse candidate.

The builder consumes the already validated Stage 0.13.3A staging database.
It never imports operational rows from ``data/warehouse.db``: that database is
opened read-only only to preserve the security baseline proof and to enumerate
test operational records which must remain excluded.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile
from time import perf_counter
from typing import Any, Callable, Iterable, Mapping, Sequence

from .canonical_naming import build_component_name, build_equipment_name
from .candidate_db import (
    ISSUE_FIRST_ROW,
    ISSUE_LAST_ROW,
    RECEIPT_FIRST_ROW,
    RECEIPT_LAST_ROW,
)
from .full_schema import (
    FULL_MARKER,
    FULL_STAGE,
    FULL_STATUS,
    FULL_TABLES,
    ISSUE_STATUSES,
    RECEIPT_STATUSES,
    create_full_schema,
)
from .pilot_selector import (
    PreservedReceiptDate,
    _workbook_uses_1904_epoch,
    parse_excel_receipt_date,
)
from .reference_data import normalize_reference_key
from .validation import (
    PRODUCTION_OPERATIONAL_TABLES,
    SQLITE_SIDECAR_SUFFIXES,
    assert_source_database_safe,
    candidate_sidecars,
    connect_readonly,
    sha256_file,
    source_content_state,
    validate_candidate,
)
from .xlsx_cells import iter_xlsx_cells, read_text_xlsx, write_text_xlsx


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RAW_DIR = ROOT / "migration_inputs" / "raw"
DEFAULT_NORMALIZED_DIR = ROOT / "migration_inputs" / "normalized"
DEFAULT_SOURCE_CANDIDATE = (
    ROOT / "migration_inputs" / "workspace" / "warehouse_migration_candidate.db"
)
DEFAULT_FULL_DB = (
    ROOT / "migration_inputs" / "workspace" / "warehouse_full_candidate.db"
)
DEFAULT_SOURCE_WORKBOOK = DEFAULT_RAW_DIR / "warehouse_accounting_source.xlsx"
DEFAULT_SERIAL_REVIEW = DEFAULT_NORMALIZED_DIR / "serial_review.xlsx"
DEFAULT_REPORT_XLSX = (
    ROOT / "migration_inputs" / "reports" / "FULL_WAREHOUSE_MIGRATION_REPORT.xlsx"
)
DEFAULT_REPORT_MARKDOWN = (
    ROOT / "migration_inputs" / "reports" / "FULL_WAREHOUSE_MIGRATION_REPORT.md"
)
DEFAULT_CLEANLINESS_XLSX = (
    ROOT / "migration_inputs" / "reports" / "FULL_WAREHOUSE_OPERATIONAL_CLEANLINESS.xlsx"
)
DEFAULT_CLEANLINESS_MARKDOWN = (
    ROOT / "migration_inputs" / "reports" / "FULL_WAREHOUSE_OPERATIONAL_CLEANLINESS.md"
)

EXPECTED_RECEIPT_ROWS = 51_003
EXPECTED_ISSUE_ROWS = 20_357
EXPECTED_TOTAL_ROWS = EXPECTED_RECEIPT_ROWS + EXPECTED_ISSUE_ROWS
RECEIPT_ID_BASE = 1_000_000
ISSUE_ID_BASE = 2_000_000
ALLOCATION_ID_BASE = 3_000_000
BUILD_RULE_VERSION = "FULL-WAREHOUSE-CANDIDATE-v1"

RECEIPT_LINKED_STATUSES = frozenset({
    "IMPORTED",
    "LINKED_TO_EXISTING_IDENTITY",
    "EXACT_DUPLICATE",
    "CONFLICT_HISTORY_ONLY",
    "NUMERIC_PROVISIONAL_IMPORTED",
})
ISSUE_LINKED_STATUSES = frozenset({
    "IMPORTED",
    "LINKED_TO_IDENTITY",
    "EXACT_DUPLICATE",
    "CONFLICT_HISTORY_ONLY",
    "OPENING_STATE_CREATED",
    "NUMERIC_PROVISIONAL_LINKED",
})


@dataclass(frozen=True)
class FullPaths:
    source_candidate: Path
    production_db: Path
    raw_dir: Path
    normalized_dir: Path
    source_workbook: Path
    serial_review: Path
    full_db: Path
    report_xlsx: Path
    report_markdown: Path
    cleanliness_xlsx: Path
    cleanliness_markdown: Path


@dataclass(frozen=True)
class FullRuntimeHooks:
    write_receipt: Callable[..., int]
    write_issue: Callable[..., int]
    write_event: Callable[..., None]


@dataclass(frozen=True)
class FullBuildResult:
    report: Mapping[str, Any]


def default_full_paths(*, production_db: Path) -> FullPaths:
    return FullPaths(
        source_candidate=DEFAULT_SOURCE_CANDIDATE,
        production_db=production_db,
        raw_dir=DEFAULT_RAW_DIR,
        normalized_dir=DEFAULT_NORMALIZED_DIR,
        source_workbook=DEFAULT_SOURCE_WORKBOOK,
        serial_review=DEFAULT_SERIAL_REVIEW,
        full_db=DEFAULT_FULL_DB,
        report_xlsx=DEFAULT_REPORT_XLSX,
        report_markdown=DEFAULT_REPORT_MARKDOWN,
        cleanliness_xlsx=DEFAULT_CLEANLINESS_XLSX,
        cleanliness_markdown=DEFAULT_CLEANLINESS_MARKDOWN,
    )


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


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_object(value: str) -> dict[str, str]:
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        raise RuntimeError("migration staging payload must be an object")
    result: dict[str, str] = {}
    for key, item in decoded.items():
        if key == "_formulas":
            continue
        result[str(key)] = "" if item is None else str(item)
    return result


def _json_list(value: str | Sequence[Any] | None) -> list[str]:
    decoded: Any = value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            decoded = [value]
    if decoded in (None, ""):
        return []
    if not isinstance(decoded, (list, tuple, set)):
        decoded = [decoded]
    return sorted({str(item) for item in decoded if str(item or "").strip()})


def _raw_hashes(raw_dir: Path) -> dict[str, str]:
    if not raw_dir.is_dir():
        raise FileNotFoundError(raw_dir)
    files = sorted(path for path in raw_dir.iterdir() if path.is_file())
    if not files:
        raise RuntimeError("raw migration directory is empty")
    return {path.name: sha256_file(path) for path in files}


def assert_safe_full_paths(paths: FullPaths) -> None:
    sources = (
        paths.source_candidate,
        paths.production_db,
        paths.source_workbook,
        paths.serial_review,
        *sorted(path for path in paths.raw_dir.glob("*") if path.is_file()),
    )
    outputs = (
        paths.full_db,
        paths.report_xlsx,
        paths.report_markdown,
        paths.cleanliness_xlsx,
        paths.cleanliness_markdown,
    )
    if paths.full_db.name != "warehouse_full_candidate.db":
        raise ValueError("full candidate DB must be named warehouse_full_candidate.db")
    for source in sources:
        if not source.is_file():
            raise FileNotFoundError(source)
    for output in outputs:
        for source in sources:
            if _same_file_or_path(output, source):
                raise RuntimeError(
                    f"full output {_portable(output)} aliases immutable source "
                    f"{_portable(source)}"
                )
    for index, left in enumerate(outputs):
        for right in outputs[index + 1 :]:
            if _same_file_or_path(left, right):
                raise RuntimeError("full candidate output paths must be distinct")
    if _same_file_or_path(paths.full_db, paths.production_db):
        raise RuntimeError("full candidate output cannot be data/warehouse.db")
    if paths.full_db.resolve() == (ROOT / "data" / "warehouse.db").resolve():
        raise RuntimeError("full candidate output cannot use production DB path")
    sidecars = [
        suffix for suffix in SQLITE_SIDECAR_SUFFIXES
        if Path(str(paths.full_db) + suffix).exists()
    ]
    if sidecars:
        raise RuntimeError(
            "full candidate output has SQLite sidecars; stop review before rebuild: "
            + ", ".join(sidecars)
        )


def _date_map(workbook: Path) -> dict[tuple[str, int], PreservedReceiptDate]:
    dates: dict[tuple[str, int], PreservedReceiptDate] = {}
    uses_1904 = _workbook_uses_1904_epoch(workbook)
    columns = {"ПРИХОД": {"A"}, "РАСХОД": {"B"}}
    for cell in iter_xlsx_cells(
        workbook,
        sheet_names=set(columns),
        columns=columns,
    ):
        if cell.source_sheet == "ПРИХОД":
            if not RECEIPT_FIRST_ROW <= cell.source_row <= RECEIPT_LAST_ROW:
                continue
        elif not ISSUE_FIRST_ROW <= cell.source_row <= ISSUE_LAST_ROW:
            continue
        dates[(cell.source_sheet, cell.source_row)] = parse_excel_receipt_date(
            cell, uses_1904_epoch=uses_1904
        )
    for row in range(RECEIPT_FIRST_ROW, RECEIPT_LAST_ROW + 1):
        dates.setdefault(("ПРИХОД", row), parse_excel_receipt_date(None))
    for row in range(ISSUE_FIRST_ROW, ISSUE_LAST_ROW + 1):
        dates.setdefault(("РАСХОД", row), parse_excel_receipt_date(None))
    return dates


def _review_map(path: Path) -> dict[tuple[str, int, str], dict[str, str]]:
    workbook = read_text_xlsx(path, sheet_names={"SERIAL_REVIEW"})
    rows = workbook.get("SERIAL_REVIEW")
    if rows is None:
        raise RuntimeError("serial review sheet is missing")
    result: dict[tuple[str, int, str], dict[str, str]] = {}
    for row in rows:
        try:
            source_row = int(row.get("source_row", ""))
        except ValueError as error:
            raise RuntimeError("serial review has invalid source_row") from error
        key = (
            str(row.get("source_sheet", "")),
            source_row,
            str(row.get("serial_role", "")),
        )
        if key in result:
            raise RuntimeError(f"duplicate serial review key: {key}")
        result[key] = dict(row)
    return result


def _approved_alias_maps(
    connection: sqlite3.Connection,
) -> dict[str, dict[str, tuple[str, str]]]:
    result: dict[str, dict[str, tuple[str, str]]] = {
        "vendor": {}, "supplier": {}, "model": {},
    }
    rows = connection.execute(
        """SELECT d.domain_key, a.normalized_source_key,
                  v.display_name, v.scope_key
             FROM reference_aliases_v2 a
             JOIN reference_domains_v2 d ON d.id=a.domain_id
             JOIN reference_values_v2 v ON v.id=a.canonical_id
            WHERE d.domain_key IN ('vendor','supplier','model')
              AND a.resolution_status IN ('AUTO_APPROVED','APPROVED')
            ORDER BY d.domain_key, a.normalized_source_key, v.scope_key, v.id"""
    )
    for row in rows:
        domain = str(row["domain_key"])
        source_key = str(row["normalized_source_key"])
        scope = str(row["scope_key"] or "")
        key = f"{scope}\x1f{source_key}" if domain == "model" else source_key
        value = (str(row["display_name"]), scope)
        existing = result[domain].get(key)
        if existing is not None and existing != value:
            raise RuntimeError(f"ambiguous approved {domain} alias: {source_key}")
        result[domain][key] = value
    return result


def _decimal_display(raw_token: str) -> str:
    try:
        numeric = Decimal(raw_token)
    except InvalidOperation as error:
        raise RuntimeError(f"invalid provisional numeric token: {raw_token!r}") from error
    if not numeric.is_finite() or numeric != numeric.to_integral_value() or numeric < 0:
        raise RuntimeError(f"unsafe provisional numeric token: {raw_token!r}")
    return format(numeric, "f").split(".", 1)[0]


def _identity_key(row: Mapping[str, Any]) -> str:
    preservation = str(row.get("preservation_status") or "")
    if preservation == "TEXT_EXACT":
        match = str(row.get("normalized_match_value") or "")
        return f"TEXT_EXACT\x1f{match}" if match else ""
    if preservation == "NUMERIC_FORMAT_UNPROVEN":
        raw = str(row.get("raw_xml_value") or "")
        return f"NUMERIC_FORMAT_UNPROVEN\x1f{raw}" if raw else ""
    return ""


def _quantity(value: str, *, blank_is_one: bool) -> tuple[bool, str, list[str]]:
    text = str(value or "")
    if not text and blank_is_one:
        return True, "1", ["MISSING_QUANTITY_ASSUMED_SERIAL_UNIT"]
    try:
        numeric = Decimal(text)
    except InvalidOperation:
        return False, text, ["INVALID_QUANTITY_DEFERRED"]
    if not numeric.is_finite() or numeric != Decimal("1"):
        return False, text, ["NON_UNIT_SERIAL_QUANTITY_DEFERRED"]
    return True, "1", []


def _resolve_row(
    row: dict[str, Any],
    aliases: Mapping[str, Mapping[str, tuple[str, str]]],
) -> None:
    payload = row["payload"]
    warnings = row["warnings"]
    source_vendor = str(row.get("source_vendor") or "")
    source_model = str(row.get("source_model") or "")
    source_supplier = str(payload.get("supplier", ""))

    vendor_entry = aliases["vendor"].get(normalize_reference_key(source_vendor))
    if vendor_entry is None:
        row["vendor"] = source_vendor
        if source_vendor:
            warnings.append("VENDOR_ALIAS_PENDING")
    else:
        row["vendor"] = vendor_entry[0]

    model_key = (
        f"{normalize_reference_key(row['vendor'])}\x1f"
        f"{normalize_reference_key(source_model)}"
    )
    model_entry = aliases["model"].get(model_key)
    if model_entry is None:
        row["model"] = source_model
        if source_model:
            warnings.append("MODEL_ALIAS_PENDING")
    else:
        row["model"] = model_entry[0]

    supplier_entry = aliases["supplier"].get(
        normalize_reference_key(source_supplier)
    )
    if supplier_entry is None:
        row["supplier"] = source_supplier
        if source_supplier:
            warnings.append("SUPPLIER_ALIAS_PENDING")
    else:
        row["supplier"] = supplier_entry[0]

    object_kind = str(row.get("object_kind") or "")
    part_number = str(payload.get("part_number", ""))
    if object_kind == "equipment" and row["vendor"] and row["model"]:
        canonical = build_equipment_name(
            str(row.get("equipment_type") or "other"),
            row["vendor"],
            row["model"],
        )
        rule = "STAGE_0_13_3A_EQUIPMENT_CANONICAL_NAME"
    elif object_kind == "component" and row["vendor"] and (
        row["model"] or part_number
    ):
        canonical = build_component_name(
            str(row.get("component_type") or "other"),
            row["vendor"],
            model=row["model"],
            part_number=part_number,
        )
        rule = "STAGE_0_13_3A_COMPONENT_CANONICAL_NAME"
    else:
        canonical = (
            str(row.get("proposed_canonical_name") or "")
            or str(payload.get("source_item_name", ""))
            or "Историческая позиция — требуется классификация"
        )
        rule = "SOURCE_NAME_FALLBACK_PENDING_REFERENCE_REVIEW"
        warnings.append("CANONICAL_NAME_FALLBACK")
    row["canonical_item_name"] = canonical
    row["normalization_rule"] = rule
    row["part_number"] = part_number
    row["source_item_name"] = str(payload.get("source_item_name", ""))
    row["source_inventory_number"] = str(payload.get("inventory_number", ""))
    row["shelf"] = str(payload.get("warehouse_location", ""))
    row["warnings"] = sorted(set(warnings))


def _operation_rows(
    connection: sqlite3.Connection,
    operation_kind: str,
    dates: Mapping[tuple[str, int], PreservedReceiptDate],
    reviews: Mapping[tuple[str, int, str], Mapping[str, str]],
    aliases: Mapping[str, Mapping[str, tuple[str, str]]],
) -> list[dict[str, Any]]:
    cursor = connection.execute(
        """SELECT s.*, f.file_name,
                  c.raw_xml_value AS serial_raw_xml_value,
                  c.source_display_value AS serial_display_value,
                  c.normalized_match_value AS serial_match_value,
                  c.preservation_status AS cell_preservation_status,
                  c.excel_cell_type AS serial_cell_type,
                  c.excel_number_format AS serial_number_format,
                  c.warning AS serial_warning,
                  c.extraction_rule AS serial_extraction_rule,
                  c.confidence AS serial_confidence,
                  c.requires_manual_review AS serial_manual_review,
                  t.raw_xml_value AS target_raw_xml_value,
                  t.source_display_value AS target_display_value,
                  t.source_serial_value AS target_source_serial_value,
                  t.normalized_match_value AS target_match_value,
                  t.preservation_status AS target_preservation_status,
                  t.warning AS target_warning
             FROM migration_staging_rows s
             JOIN migration_source_files f ON f.id=s.source_file_id
             LEFT JOIN migration_serial_cells c
               ON c.staging_row_id=s.id AND c.serial_role='SOURCE_SERIAL'
             LEFT JOIN migration_serial_cells t
               ON t.staging_row_id=s.id AND t.serial_role='TARGET_EQUIPMENT_SERIAL'
            WHERE s.operation_kind=?
            ORDER BY s.source_row, s.id""",
        (operation_kind,),
    )
    role = "receipt_asset" if operation_kind == "RECEIPT" else "issue_source"
    result: list[dict[str, Any]] = []
    for sql_row in cursor:
        source = dict(sql_row)
        payload = _json_object(str(source["normalized_payload"]))
        preservation = str(
            source.get("cell_preservation_status")
            or source.get("serial_preservation_status")
            or "EMPTY"
        )
        raw_xml = str(source.get("serial_raw_xml_value") or "")
        source_serial = str(source.get("source_serial_value") or "")
        if preservation == "NUMERIC_FORMAT_UNPROVEN":
            display_serial = _decimal_display(raw_xml)
        else:
            display_serial = source_serial
        source_row = int(source["source_row"])
        date_value = dates[(str(source["source_sheet"]), source_row)]
        review = reviews.get((str(source["source_sheet"]), source_row, role), {})
        warnings = _json_list(str(source.get("warnings") or "[]"))
        warnings.extend(
            part for part in str(source.get("serial_warning") or "").split(";")
            if part
        )
        if not date_value.proven:
            warnings.append(date_value.status)
        row = {
            **source,
            "payload": payload,
            "preservation_status": preservation,
            "raw_xml_value": raw_xml,
            "source_serial_value": source_serial,
            "display_serial_value": display_serial,
            "normalized_match_value": str(source.get("serial_match_value") or source.get("normalized_matching_serial") or ""),
            "identity_confidence": (
                "PROVISIONAL" if preservation == "NUMERIC_FORMAT_UNPROVEN"
                else "AUTHORITATIVE" if preservation == "TEXT_EXACT" else "NONE"
            ),
            "authoritative": int(preservation == "TEXT_EXACT"),
            "requires_manual_review": int(
                preservation != "TEXT_EXACT"
                or bool(int(source.get("serial_manual_review") or 0))
            ),
            "review_status": str(review.get("status", "")),
            "review_flags": str(review.get("flags", "")),
            "operation_date": date_value.iso_value,
            "operation_date_raw": date_value.raw_xml_value,
            "operation_date_status": date_value.status,
            "source_vendor": str(source.get("proposed_vendor") or ""),
            "source_model": str(source.get("proposed_model") or ""),
            "object_kind": str(source.get("proposed_object_kind") or ""),
            "category": str(source.get("proposed_equipment_category") or ""),
            "equipment_type": str(source.get("proposed_equipment_type") or ""),
            "component_type": str(source.get("proposed_component_type") or ""),
            "proposed_canonical_name": str(source.get("proposed_canonical_name") or ""),
            "warnings": warnings,
            "conflicts": _json_list(str(source.get("conflicts") or "[]")),
            "target_source_serial_value": str(source.get("target_source_serial_value") or ""),
            "target_raw_xml_value": str(source.get("target_raw_xml_value") or ""),
            "target_display_value": str(source.get("target_display_value") or ""),
            "target_match_value": str(source.get("target_match_value") or ""),
            "target_preservation_status": str(source.get("target_preservation_status") or "EMPTY"),
            "target_warning": str(source.get("target_warning") or ""),
        }
        if operation_kind == "RECEIPT":
            _resolve_row(row, aliases)
        result.append(row)
    return result


def _variant_values(rows: Iterable[Mapping[str, Any]], field: str) -> set[str]:
    return {
        normalize_reference_key(str(row.get(field) or ""))
        for row in rows
        if str(row.get(field) or "").strip()
    }


def _identity_conflicts(rows: list[dict[str, Any]]) -> list[str]:
    conflicts: list[str] = []
    if len(_variant_values(rows, "vendor")) > 1:
        conflicts.append("VENDOR_CONFLICT")
    if len(_variant_values(rows, "model")) > 1:
        conflicts.append("MODEL_CONFLICT")
    if len(_variant_values(rows, "source_item_name")) > 1:
        conflicts.append("ITEM_NAME_CONFLICT")
    if len(_variant_values(rows, "object_kind")) > 1:
        conflicts.append("OBJECT_KIND_CONFLICT")
    if len(_variant_values(rows, "shelf")) > 1:
        conflicts.append("MULTIPLE_SHELVES_HISTORY")
    exact_serials = {str(row.get("source_serial_value") or "") for row in rows}
    if len(exact_serials) > 1:
        conflicts.append("SOURCE_SERIAL_VARIANT_SAME_MATCH_KEY")
    return sorted(conflicts)


def _current_identity_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Choose current attributes by latest proven date, then highest source row."""

    return max(
        rows,
        key=lambda row: (
            1 if row.get("operation_date") else 0,
            str(row.get("operation_date") or ""),
            int(row["source_row"]),
            int(row["id"]),
        ),
    )


def _attribute_signature(row: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(
        normalize_reference_key(str(row.get(field) or ""))
        for field in ("vendor", "model", "source_item_name", "object_kind")
    )


def _writer_source(
    row: Mapping[str, Any],
    *,
    final_status: str,
    created_at: str,
    opening_state: bool = False,
) -> dict[str, Any]:
    payload = row.get("payload") if isinstance(row.get("payload"), Mapping) else {}
    operation_date = str(row.get("operation_date") or "")
    warnings = list(row.get("warnings") or [])
    if str(row.get("source_inventory_number") or ""):
        warnings.append("SOURCE_INVENTORY_RETAINED_AS_PROVENANCE_ONLY")
    return {
        "source_file": Path(str(row.get("file_name") or "")).name,
        "source_sheet": str(row.get("source_sheet") or ""),
        "source_row": int(row.get("source_row") or 0),
        "source_row_hash": str(row.get("source_row_hash") or ""),
        "source_serial_value": str(row.get("source_serial_value") or ""),
        "display_serial_value": str(row.get("display_serial_value") or ""),
        "preservation_status": str(row.get("preservation_status") or ""),
        "final_status": final_status,
        "source_item_name": str(row.get("source_item_name") or ""),
        "canonical_item_name": str(row.get("canonical_item_name") or ""),
        "warnings": sorted(set(warnings)),
        "conflicts": sorted(set(row.get("conflicts") or [])),
        "operation_date": operation_date,
        "audit_event_date": operation_date or created_at,
        "created_at": created_at,
        "responsible": str(payload.get("responsible", "")) or "Историческая миграция",
        "order_date": str(payload.get("order_date", "")),
        "request_number": str(payload.get("request_number", "")),
        "order_number": str(payload.get("order_number", "")),
        "plu": str(payload.get("plu", "")),
        "project": str(payload.get("project", "")),
        "inventory_number": "",
        "supplier": str(row.get("supplier") or ""),
        "vendor": str(row.get("vendor") or ""),
        "model": str(row.get("model") or ""),
        "shelf": str(row.get("shelf") or ""),
        "object_name": str(payload.get("deployment_location", "")),
        "datacenter": str(payload.get("deployment_location", "")),
        "equipment_type": str(row.get("equipment_type") or ""),
        "component_type": str(row.get("component_type") or ""),
        "quantity": "1",
        "task_type": str(payload.get("issue_reason", "")),
        "task_number": str(payload.get("case_number", "")),
        "target_serial_number": str(row.get("target_display_value") or ""),
        "target_hostname": str(payload.get("hostname", "")),
        "comment": "; ".join(
            part for part in (
                str(payload.get("action_taken", "")),
                str(payload.get("comments", "")),
                "Исходный приход отсутствует в доступной выгрузке"
                if opening_state else "",
            ) if part
        ),
    }


def _insert_identity(
    connection: sqlite3.Connection,
    row: Mapping[str, Any],
    *,
    identity_id: int,
    identity_key: str,
    receipt_id: int,
    source_row_count: int,
    opening_state: bool,
    conflicts: Sequence[str],
    created_at: str,
) -> None:
    warnings = sorted(set(row.get("warnings") or []))
    if row.get("preservation_status") == "NUMERIC_FORMAT_UNPROVEN":
        warnings.extend((
            "POSSIBLE_LEADING_ZERO_LOSS",
            "RAW_NUMERIC_TOKEN_SHOWN_IN_PROVENANCE",
            "INVENTORY_NUMBER_ASSIGNMENT_FORBIDDEN",
        ))
    connection.execute(
        """INSERT INTO migration_full_identities(
               id, identity_key, normalized_match_value, preserved_serial_value,
               display_serial_value, raw_xml_value, preservation_status,
               identity_confidence, authoritative, requires_manual_review,
               opening_state, primary_staging_row_id, target_receipt_id,
               source_row_count, source_item_name, canonical_item_name,
               object_kind, category, equipment_type, component_type,
               vendor, model, part_number, normalization_rule,
               warnings, conflicts, created_at
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            identity_id,
            identity_key,
            str(row.get("normalized_match_value") or ""),
            str(row.get("source_serial_value") or ""),
            str(row.get("display_serial_value") or ""),
            str(row.get("raw_xml_value") or ""),
            str(row.get("preservation_status") or ""),
            str(row.get("identity_confidence") or ""),
            int(row.get("authoritative") or 0),
            int(row.get("requires_manual_review") or 0),
            int(opening_state),
            int(row["id"]),
            receipt_id,
            source_row_count,
            str(row.get("source_item_name") or ""),
            str(row.get("canonical_item_name") or ""),
            str(row.get("object_kind") or ""),
            str(row.get("category") or ""),
            str(row.get("equipment_type") or ""),
            str(row.get("component_type") or ""),
            str(row.get("vendor") or ""),
            str(row.get("model") or ""),
            str(row.get("part_number") or ""),
            str(row.get("normalization_rule") or ""),
            _json(sorted(set(warnings))),
            _json(sorted(set(conflicts))),
            created_at,
        ),
    )


def _insert_reconciliation(
    connection: sqlite3.Connection,
    row: Mapping[str, Any],
    *,
    final_status: str,
    identity_id: int | None,
    receipt_id: int | None,
    issue_id: int | None,
    reason: str,
    created_at: str,
) -> int:
    operation_kind = str(row["operation_kind"])
    allowed = RECEIPT_STATUSES if operation_kind == "RECEIPT" else ISSUE_STATUSES
    if final_status not in allowed:
        raise RuntimeError(f"invalid {operation_kind} final status: {final_status}")
    reconciliation_id = int(row["id"])
    warnings = sorted(set(row.get("warnings") or []))
    conflicts = sorted(set(row.get("conflicts") or []))
    connection.execute(
        """INSERT INTO migration_full_reconciliation(
               id, staging_row_id, operation_kind, source_file, source_sheet,
               source_row, source_row_hash, source_serial_value,
               display_serial_value, normalized_match_value, raw_xml_value,
               preservation_status, identity_confidence, authoritative,
               requires_manual_review, final_status, target_identity_id,
               target_receipt_id, target_issue_id, source_item_name,
               canonical_item_name, source_inventory_number, object_kind,
               category, equipment_type, component_type, vendor, model,
               part_number, quantity, source_operation_date,
               source_operation_date_raw, source_operation_date_status, shelf,
               target_equipment_source_serial, target_equipment_display_serial,
               target_equipment_preservation_status, warnings, conflicts,
               non_application_reason, raw_payload, normalized_payload, created_at
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            reconciliation_id,
            int(row["id"]),
            operation_kind,
            Path(str(row.get("file_name") or "")).name,
            str(row.get("source_sheet") or ""),
            int(row.get("source_row") or 0),
            str(row.get("source_row_hash") or ""),
            str(row.get("source_serial_value") or ""),
            str(row.get("display_serial_value") or ""),
            str(row.get("normalized_match_value") or ""),
            str(row.get("raw_xml_value") or ""),
            str(row.get("preservation_status") or ""),
            str(row.get("identity_confidence") or "NONE"),
            int(row.get("authoritative") or 0),
            int(row.get("requires_manual_review") or 0),
            final_status,
            identity_id,
            receipt_id,
            issue_id,
            str(row.get("source_item_name") or ""),
            str(row.get("canonical_item_name") or ""),
            str(row.get("source_inventory_number") or ""),
            str(row.get("object_kind") or ""),
            str(row.get("category") or ""),
            str(row.get("equipment_type") or ""),
            str(row.get("component_type") or ""),
            str(row.get("vendor") or ""),
            str(row.get("model") or ""),
            str(row.get("part_number") or ""),
            str(row.get("quantity") or row.get("payload", {}).get("quantity", "")),
            str(row.get("operation_date") or ""),
            str(row.get("operation_date_raw") or ""),
            str(row.get("operation_date_status") or ""),
            str(row.get("shelf") or ""),
            str(row.get("target_source_serial_value") or ""),
            str(row.get("target_display_value") or ""),
            str(row.get("target_preservation_status") or "EMPTY"),
            _json(warnings),
            _json(conflicts),
            reason,
            str(row.get("raw_payload") or "{}"),
            str(row.get("normalized_payload") or "{}"),
            created_at,
        ),
    )
    for kind, values in (("WARNING", warnings), ("CONFLICT", conflicts)):
        for code in values:
            connection.execute(
                """INSERT OR IGNORE INTO migration_full_warnings(
                       reconciliation_id, identity_id, warning_kind, code,
                       message, created_at
                   ) VALUES (?,?,?,?,?,?)""",
                (reconciliation_id, identity_id, kind, code, code, created_at),
            )
    return reconciliation_id


def _quarantine(
    connection: sqlite3.Connection,
    row: Mapping[str, Any],
    *,
    reason_code: str,
    created_at: str,
) -> None:
    connection.execute(
        """INSERT INTO migration_full_quarantine(
               id, reconciliation_id, reason_code, raw_token, source_file,
               source_sheet, source_row, created_at
           ) VALUES (?,?,?,?,?,?,?,?)""",
        (
            int(row["id"]),
            int(row["id"]),
            reason_code,
            str(row.get("raw_xml_value") or row.get("source_serial_value") or ""),
            Path(str(row.get("file_name") or "")).name,
            str(row.get("source_sheet") or ""),
            int(row.get("source_row") or 0),
            created_at,
        ),
    )


def _opening_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = row["payload"]
    source_item_name = str(payload.get("formula_item_name", ""))
    model = str(
        payload.get("formula_component_model", "")
        or payload.get("formula_model", "")
    )
    if model == "#N/A":
        model = ""
    target_present = bool(str(row.get("target_source_serial_value") or ""))
    row = dict(row)
    row.update({
        "source_item_name": source_item_name,
        "canonical_item_name": source_item_name
        or "Историческая позиция — исходный приход отсутствует",
        "source_inventory_number": str(payload.get("formula_inventory_number", "")),
        "object_kind": "component" if target_present else "equipment",
        "category": "",
        "equipment_type": "" if target_present else "other",
        "component_type": "other" if target_present else "",
        "vendor": "",
        "model": model,
        "part_number": "",
        "supplier": "",
        "shelf": str(payload.get("warehouse_location", "")),
        "normalization_rule": "OPENING_STATE_SOURCE_FORMULA_NAME_ONLY",
        "warnings": sorted(set([
            *row.get("warnings", []),
            "SOURCE_RECEIPT_ABSENT_OPENING_STATE_CREATED",
        ])),
    })
    return row


def _process_receipts(
    connection: sqlite3.Connection,
    rows: list[dict[str, Any]],
    hooks: FullRuntimeHooks,
    *,
    created_at: str,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[int, dict[str, Any]],
    Counter[str],
    int,
]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    deferred: list[tuple[dict[str, Any], str, str, bool]] = []
    for row in rows:
        preservation = str(row["preservation_status"])
        raw_quantity = str(row["payload"].get("quantity", ""))
        row["quantity"] = raw_quantity
        if preservation == "SOURCE_CORRUPTED":
            row["warnings"] = sorted(set([
                *row["warnings"], "SOURCE_CORRUPTED_NO_IDENTITY_CREATED",
            ]))
            deferred.append((
                row,
                "SOURCE_CORRUPTED_REJECTED",
                "Исходный numeric token повреждён; карточка и приход не создавались",
                True,
            ))
            continue
        if preservation == "EMPTY":
            deferred.append((
                row,
                "QUANTITY_DEFERRED",
                "S/N отсутствует; строка сохранена как quantity/deferred evidence",
                False,
            ))
            continue
        if preservation not in {"TEXT_EXACT", "NUMERIC_FORMAT_UNPROVEN"}:
            deferred.append((
                row,
                "QUARANTINED",
                f"Неподдерживаемый preservation status: {preservation}",
                True,
            ))
            continue
        unit_quantity, normalized_quantity, quantity_warnings = _quantity(
            raw_quantity, blank_is_one=False
        )
        row["warnings"] = sorted(set([*row["warnings"], *quantity_warnings]))
        row["quantity"] = normalized_quantity
        if (
            row.get("review_status") == "NOT_A_SERIAL"
            or row.get("object_kind") == "cable"
            or not unit_quantity
        ):
            deferred.append((
                row,
                "QUANTITY_DEFERRED",
                "Quantity/cable-like строка не является serialized equipment",
                False,
            ))
            continue
        key = _identity_key(row)
        if not key:
            deferred.append((
                row,
                "QUARANTINED",
                "Preservation-aware identity key не может быть построен",
                True,
            ))
            continue
        row["identity_key"] = key
        groups[key].append(row)

    identity_by_key: dict[str, dict[str, Any]] = {}
    identity_by_id: dict[int, dict[str, Any]] = {}
    counts: Counter[str] = Counter()
    ordered_groups = sorted(
        groups.items(),
        key=lambda item: (
            min(int(row["source_row"]) for row in item[1]),
            item[0],
        ),
    )
    for identity_id, (key, group) in enumerate(ordered_groups, start=1):
        group.sort(key=lambda row: (int(row["source_row"]), int(row["id"])))
        current = _current_identity_row(group)
        conflicts = _identity_conflicts(group)
        current["conflicts"] = sorted(set([*current["conflicts"], *conflicts]))
        receipt_id = RECEIPT_ID_BASE + identity_id
        primary_status = (
            "NUMERIC_PROVISIONAL_IMPORTED"
            if current["preservation_status"] == "NUMERIC_FORMAT_UNPROVEN"
            else "IMPORTED"
        )
        source = _writer_source(
            current,
            final_status=primary_status,
            created_at=created_at,
        )
        hooks.write_receipt(
            connection,
            source,
            receipt_id=receipt_id,
            opening_state=False,
            author="full-warehouse-migration",
        )
        _insert_identity(
            connection,
            current,
            identity_id=identity_id,
            identity_key=key,
            receipt_id=receipt_id,
            source_row_count=len(group),
            opening_state=False,
            conflicts=conflicts,
            created_at=created_at,
        )
        identity = {
            "id": identity_id,
            "identity_key": key,
            "receipt_id": receipt_id,
            "row": current,
            "opening_state": False,
            "preservation_status": current["preservation_status"],
        }
        identity_by_key[key] = identity
        identity_by_id[identity_id] = identity
        if current["preservation_status"] == "NUMERIC_FORMAT_UNPROVEN":
            hooks.write_event(
                connection,
                action="MIGRATION_NUMERIC_IDENTITY_PROVISIONAL",
                entity_type="stock_receipt",
                entity_id=receipt_id,
                source=source,
                author="full-warehouse-migration",
            )

        primary_signature = str(current["raw_payload"])
        primary_attributes = _attribute_signature(current)
        primary_serial = str(current["source_serial_value"])
        identity_conflict_codes = set(conflicts).intersection({
            "VENDOR_CONFLICT",
            "MODEL_CONFLICT",
            "ITEM_NAME_CONFLICT",
            "OBJECT_KIND_CONFLICT",
            "SOURCE_SERIAL_VARIANT_SAME_MATCH_KEY",
        })
        for row in group:
            row["conflicts"] = sorted(set([*row["conflicts"], *conflicts]))
            if int(row["id"]) == int(current["id"]):
                final_status = primary_status
            elif (
                str(row["raw_payload"]) == primary_signature
                and str(row["source_serial_value"]) == primary_serial
            ):
                final_status = "EXACT_DUPLICATE"
            elif identity_conflict_codes and (
                _attribute_signature(row) != primary_attributes
                or str(row["source_serial_value"]) != primary_serial
            ):
                final_status = "CONFLICT_HISTORY_ONLY"
            else:
                final_status = "LINKED_TO_EXISTING_IDENTITY"
            _insert_reconciliation(
                connection,
                row,
                final_status=final_status,
                identity_id=identity_id,
                receipt_id=receipt_id,
                issue_id=None,
                reason=(
                    "Повторный operational receipt не создан"
                    if final_status != primary_status else ""
                ),
                created_at=created_at,
            )
            counts[final_status] += 1
            event_source = _writer_source(
                row,
                final_status=final_status,
                created_at=created_at,
            )
            hooks.write_event(
                connection,
                action="MIGRATION_SOURCE_ROW_LINKED",
                entity_type="stock_receipt",
                entity_id=receipt_id,
                source=event_source,
                author="full-warehouse-migration",
            )
            if final_status == "EXACT_DUPLICATE":
                hooks.write_event(
                    connection,
                    action="MIGRATION_EXACT_DUPLICATE_SKIPPED",
                    entity_type="stock_receipt",
                    entity_id=receipt_id,
                    source=event_source,
                    author="full-warehouse-migration",
                )
            elif final_status == "CONFLICT_HISTORY_ONLY":
                hooks.write_event(
                    connection,
                    action="MIGRATION_CONFLICT_RECORDED",
                    entity_type="stock_receipt",
                    entity_id=receipt_id,
                    source=event_source,
                    author="full-warehouse-migration",
                )

    for row, final_status, reason, quarantine in sorted(
        deferred, key=lambda item: (int(item[0]["source_row"]), int(item[0]["id"]))
    ):
        _insert_reconciliation(
            connection,
            row,
            final_status=final_status,
            identity_id=None,
            receipt_id=None,
            issue_id=None,
            reason=reason,
            created_at=created_at,
        )
        counts[final_status] += 1
        if quarantine:
            _quarantine(
                connection,
                row,
                reason_code=final_status,
                created_at=created_at,
            )
            source = _writer_source(
                row,
                final_status=final_status,
                created_at=created_at,
            )
            hooks.write_event(
                connection,
                action="MIGRATION_SERIAL_QUARANTINED",
                entity_type="migration_staging_row",
                entity_id=int(row["id"]),
                source=source,
                author="full-warehouse-migration",
            )
    return identity_by_key, identity_by_id, counts, len(ordered_groups)


def _target_key(row: Mapping[str, Any]) -> str:
    preservation = str(row.get("target_preservation_status") or "")
    if preservation == "TEXT_EXACT":
        match = str(row.get("target_match_value") or "")
        return f"TEXT_EXACT\x1f{match}" if match else ""
    if preservation == "NUMERIC_FORMAT_UNPROVEN":
        raw = str(row.get("target_raw_xml_value") or "")
        return f"NUMERIC_FORMAT_UNPROVEN\x1f{raw}" if raw else ""
    return ""


def _process_issues(
    connection: sqlite3.Connection,
    rows: list[dict[str, Any]],
    hooks: FullRuntimeHooks,
    identity_by_key: dict[str, dict[str, Any]],
    identity_by_id: dict[int, dict[str, Any]],
    *,
    first_identity_id: int,
    created_at: str,
) -> tuple[Counter[str], int, int]:
    potential_keys = Counter(
        _identity_key(row)
        for row in rows
        if row["preservation_status"] in {"TEXT_EXACT", "NUMERIC_FORMAT_UNPROVEN"}
        and _identity_key(row)
    )
    counts: Counter[str] = Counter()
    issue_signatures: dict[int, set[str]] = defaultdict(set)
    consumed_identities: set[int] = set()
    next_identity_id = first_identity_id
    issue_sequence = 0
    opening_states = 0

    for row in rows:
        preservation = str(row["preservation_status"])
        raw_quantity = str(row["payload"].get("quantity", ""))
        row["quantity"] = raw_quantity
        row["source_item_name"] = str(row["payload"].get("formula_item_name", ""))
        row["source_inventory_number"] = str(
            row["payload"].get("formula_inventory_number", "")
        )
        row["canonical_item_name"] = row["source_item_name"]
        row.setdefault("vendor", "")
        row.setdefault("model", str(row["payload"].get("formula_component_model", "")))
        row.setdefault("part_number", "")
        row.setdefault("normalization_rule", "ISSUE_SOURCE_PROVENANCE")
        row.setdefault("shelf", str(row["payload"].get("warehouse_location", "")))

        if preservation == "SOURCE_CORRUPTED":
            row["warnings"] = sorted(set([
                *row["warnings"], "SOURCE_CORRUPTED_NO_IDENTITY_CREATED",
            ]))
            final_status = "QUARANTINED"
            reason = "Повреждённый source S/N расхода не восстанавливался предположением"
            _insert_reconciliation(
                connection, row, final_status=final_status, identity_id=None,
                receipt_id=None, issue_id=None, reason=reason, created_at=created_at,
            )
            _quarantine(connection, row, reason_code="SOURCE_CORRUPTED", created_at=created_at)
            source = _writer_source(row, final_status=final_status, created_at=created_at)
            hooks.write_event(
                connection, action="MIGRATION_SERIAL_QUARANTINED",
                entity_type="migration_staging_row", entity_id=int(row["id"]),
                source=source, author="full-warehouse-migration",
            )
            counts[final_status] += 1
            continue
        if preservation == "EMPTY":
            final_status = "QUANTITY_DEFERRED"
            reason = "S/N расходуемой serialized-позиции отсутствует"
            _insert_reconciliation(
                connection, row, final_status=final_status, identity_id=None,
                receipt_id=None, issue_id=None, reason=reason, created_at=created_at,
            )
            counts[final_status] += 1
            continue
        if preservation not in {"TEXT_EXACT", "NUMERIC_FORMAT_UNPROVEN"}:
            final_status = "UNRESOLVED_ISSUE"
            reason = f"Неподдерживаемый preservation status: {preservation}"
            _insert_reconciliation(
                connection, row, final_status=final_status, identity_id=None,
                receipt_id=None, issue_id=None, reason=reason, created_at=created_at,
            )
            counts[final_status] += 1
            continue

        unit_quantity, normalized_quantity, quantity_warnings = _quantity(
            raw_quantity, blank_is_one=True
        )
        row["quantity"] = normalized_quantity
        row["warnings"] = sorted(set([*row["warnings"], *quantity_warnings]))
        if row.get("review_status") == "NOT_A_SERIAL" or not unit_quantity:
            final_status = "QUANTITY_DEFERRED"
            reason = "Quantity/cable-like расход не импортирован как serialized issue"
            _insert_reconciliation(
                connection, row, final_status=final_status, identity_id=None,
                receipt_id=None, issue_id=None, reason=reason, created_at=created_at,
            )
            counts[final_status] += 1
            continue

        key = _identity_key(row)
        if not key:
            final_status = "UNRESOLVED_ISSUE"
            reason = "Preservation-aware identity key расхода не построен"
            _insert_reconciliation(
                connection, row, final_status=final_status, identity_id=None,
                receipt_id=None, issue_id=None, reason=reason, created_at=created_at,
            )
            counts[final_status] += 1
            continue

        identity = identity_by_key.get(key)
        created_opening = False
        if identity is None:
            opening = _opening_row(row)
            next_identity_id += 1
            identity_id = next_identity_id
            receipt_id = RECEIPT_ID_BASE + identity_id
            opening_status = (
                "NUMERIC_PROVISIONAL_LINKED"
                if preservation == "NUMERIC_FORMAT_UNPROVEN"
                else "OPENING_STATE_CREATED"
            )
            source = _writer_source(
                opening,
                final_status=opening_status,
                created_at=created_at,
                opening_state=True,
            )
            hooks.write_receipt(
                connection,
                source,
                receipt_id=receipt_id,
                opening_state=True,
                author="full-warehouse-migration",
            )
            _insert_identity(
                connection,
                opening,
                identity_id=identity_id,
                identity_key=key,
                receipt_id=receipt_id,
                source_row_count=potential_keys[key],
                opening_state=True,
                conflicts=(),
                created_at=created_at,
            )
            identity = {
                "id": identity_id,
                "identity_key": key,
                "receipt_id": receipt_id,
                "row": opening,
                "opening_state": True,
                "preservation_status": preservation,
            }
            identity_by_key[key] = identity
            identity_by_id[identity_id] = identity
            created_opening = True
            opening_states += 1
            if preservation == "NUMERIC_FORMAT_UNPROVEN":
                hooks.write_event(
                    connection,
                    action="MIGRATION_NUMERIC_IDENTITY_PROVISIONAL",
                    entity_type="stock_receipt",
                    entity_id=receipt_id,
                    source=source,
                    author="full-warehouse-migration",
                )

        identity_id = int(identity["id"])
        receipt_id = int(identity["receipt_id"])
        identity_row = identity["row"]
        row["canonical_item_name"] = str(identity_row.get("canonical_item_name") or "")
        row["object_kind"] = str(identity_row.get("object_kind") or "")
        row["category"] = str(identity_row.get("category") or "")
        row["equipment_type"] = str(identity_row.get("equipment_type") or "")
        row["component_type"] = str(identity_row.get("component_type") or "")
        row["vendor"] = str(identity_row.get("vendor") or "")
        row["model"] = str(identity_row.get("model") or "")
        row["part_number"] = str(identity_row.get("part_number") or "")
        row["normalization_rule"] = str(identity_row.get("normalization_rule") or "")
        signature = str(row["raw_payload"])
        if identity_id in consumed_identities:
            final_status = (
                "EXACT_DUPLICATE"
                if signature in issue_signatures[identity_id]
                else "CONFLICT_HISTORY_ONLY"
            )
            reason = "Повторный расход не создал отрицательный serialized balance"
            _insert_reconciliation(
                connection, row, final_status=final_status,
                identity_id=identity_id, receipt_id=receipt_id,
                issue_id=None, reason=reason, created_at=created_at,
            )
            counts[final_status] += 1
            event_source = _writer_source(
                row, final_status=final_status, created_at=created_at
            )
            hooks.write_event(
                connection,
                action=(
                    "MIGRATION_EXACT_DUPLICATE_SKIPPED"
                    if final_status == "EXACT_DUPLICATE"
                    else "MIGRATION_CONFLICT_RECORDED"
                ),
                entity_type="stock_receipt",
                entity_id=receipt_id,
                source=event_source,
                author="full-warehouse-migration",
            )
            issue_signatures[identity_id].add(signature)
            continue

        issue_sequence += 1
        issue_id = ISSUE_ID_BASE + issue_sequence
        allocation_id = ALLOCATION_ID_BASE + issue_sequence
        if preservation == "NUMERIC_FORMAT_UNPROVEN":
            final_status = "NUMERIC_PROVISIONAL_LINKED"
        elif created_opening:
            final_status = "OPENING_STATE_CREATED"
        else:
            final_status = "IMPORTED"
        source = _writer_source(
            row,
            final_status=final_status,
            created_at=created_at,
            opening_state=created_opening,
        )
        hooks.write_issue(
            connection,
            source,
            issue_id=issue_id,
            allocation_id=allocation_id,
            receipt_id=receipt_id,
            author="full-warehouse-migration",
        )
        _insert_reconciliation(
            connection,
            row,
            final_status=final_status,
            identity_id=identity_id,
            receipt_id=receipt_id,
            issue_id=issue_id,
            reason="",
            created_at=created_at,
        )
        hooks.write_event(
            connection,
            action="MIGRATION_SOURCE_ROW_LINKED",
            entity_type="stock_receipt",
            entity_id=receipt_id,
            source=source,
            author="full-warehouse-migration",
        )
        counts[final_status] += 1
        consumed_identities.add(identity_id)
        issue_signatures[identity_id].add(signature)

        target_source = str(row.get("target_source_serial_value") or "")
        if target_source:
            target_key = _target_key(row)
            target_identity = identity_by_key.get(target_key) if target_key else None
            warning = str(row.get("target_warning") or "")
            if target_identity is None:
                warning = ";".join(filter(None, (warning, "TARGET_IDENTITY_NOT_FOUND")))
            connection.execute(
                """INSERT INTO migration_full_relationships(
                       id, reconciliation_id, source_identity_id,
                       target_identity_id, relationship_type,
                       target_source_serial_value, target_display_serial_value,
                       target_preservation_status, warning, created_at
                   ) VALUES (?,?,?,?, 'INSTALLED_IN', ?,?,?,?,?)""",
                (
                    int(row["id"]),
                    int(row["id"]),
                    identity_id,
                    int(target_identity["id"]) if target_identity else None,
                    target_source,
                    str(row.get("target_display_value") or ""),
                    str(row.get("target_preservation_status") or ""),
                    warning,
                    created_at,
                ),
            )

    connection.execute(
        """UPDATE migration_full_identities
              SET source_row_count = (
                  SELECT COUNT(*) FROM migration_full_reconciliation r
                   WHERE r.target_identity_id=migration_full_identities.id
              )
            WHERE EXISTS (
                  SELECT 1 FROM migration_full_reconciliation r
                   WHERE r.target_identity_id=migration_full_identities.id
              )"""
    )
    return counts, next_identity_id, opening_states


def _operational_counts(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        for table in PRODUCTION_OPERATIONAL_TABLES
    }


def _table_counts(
    connection: sqlite3.Connection, tables: Iterable[str]
) -> dict[str, int]:
    return {
        table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        for table in tables
    }


def _production_snapshot(path: Path) -> dict[str, Any]:
    with closing(connect_readonly(path)) as connection:
        counts = _operational_counts(connection)
        test_serials: list[dict[str, str]] = []
        for table in ("stock_receipts", "equipment"):
            for row in connection.execute(
                f"SELECT id, serial_number FROM {table} "
                "WHERE trim(serial_number)<>'' ORDER BY id"
            ):
                test_serials.append({
                    "source_table": table,
                    "source_id": str(row["id"]),
                    "serial_number": str(row["serial_number"]),
                })
        ids: dict[str, list[str]] = {}
        for table in PRODUCTION_OPERATIONAL_TABLES:
            ids[table] = [
                str(row[0])
                for row in connection.execute(f"SELECT id FROM {table} ORDER BY id")
            ]
        users = int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        active_admins = int(connection.execute(
            "SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1"
        ).fetchone()[0])
    return {
        "counts": counts,
        "test_serials": test_serials,
        "ids": ids,
        "users": users,
        "active_admins": active_admins,
    }


def _insert_cleanliness_rows(
    connection: sqlite3.Connection,
    *,
    before: Mapping[str, int],
    after: Mapping[str, int],
    preserved_before: Mapping[str, int],
    preserved_after: Mapping[str, int],
    production: Mapping[str, Any],
    created_at: str,
) -> None:
    for table in PRODUCTION_OPERATIONAL_TABLES:
        connection.execute(
            """INSERT INTO migration_full_cleanliness(
                   check_kind, source_table, before_count, after_count,
                   result, details, created_at
               ) VALUES ('OPERATIONAL_TABLE',?,?,?,?,?,?)""",
            (
                table,
                int(before[table]),
                int(after[table]),
                "PASS",
                _json({
                    "source_candidate_before_import_empty": before[table] == 0,
                    "after_contains_only_full_migration_rows": True,
                }),
                created_at,
            ),
        )
    for table in sorted(preserved_before):
        connection.execute(
            """INSERT INTO migration_full_cleanliness(
                   check_kind, source_table, before_count, after_count,
                   result, details, created_at
               ) VALUES ('PRESERVED_SYSTEM_TABLE',?,?,?,?,?,?)""",
            (
                table,
                int(preserved_before[table]),
                int(preserved_after[table]),
                "INFO",
                _json({"classification": "security/reference/staging"}),
                created_at,
            ),
        )
    for row in production["test_serials"]:
        serial = str(row["serial_number"])
        found = int(connection.execute(
            """SELECT COUNT(*) FROM migration_full_identities
                WHERE display_serial_value=? COLLATE BINARY
                   OR preserved_serial_value=? COLLATE BINARY""",
            (serial, serial),
        ).fetchone()[0])
        if found:
            raise RuntimeError(f"production test S/N leaked into candidate: {serial}")
        connection.execute(
            """INSERT INTO migration_full_cleanliness(
                   check_kind, source_table, source_id, source_serial,
                   result, details, created_at
               ) VALUES ('EXCLUDED_TEST_SERIAL',?,?,?,?,?,?)""",
            (
                str(row["source_table"]),
                str(row["source_id"]),
                serial,
                "PASS",
                _json({"candidate_matches": 0}),
                created_at,
            ),
        )
    for table, ids in production["ids"].items():
        connection.execute(
            """INSERT INTO migration_full_cleanliness(
                   check_kind, source_table, source_id, result, details, created_at
               ) VALUES ('EXCLUDED_SOURCE_IDS',?,?, 'PASS', ?,?)""",
            (
                table,
                ",".join(ids),
                _json({
                    "source_ids": ids,
                    "meaning": "IDs regenerated; no source operational row copied",
                }),
                created_at,
            ),
        )


def _measure(
    connection: sqlite3.Connection, sql: str, parameters: tuple[Any, ...] = ()
) -> tuple[float, list[sqlite3.Row]]:
    started = perf_counter()
    rows = connection.execute(sql, parameters).fetchall()
    return (perf_counter() - started) * 1000, rows


def _create_full_file(
    destination: Path,
    paths: FullPaths,
    hooks: FullRuntimeHooks,
    production: Mapping[str, Any],
    *,
    source_candidate_sha: str,
    production_sha: str,
    raw_hashes: Mapping[str, str],
) -> dict[str, Any]:
    build_started = perf_counter()
    shutil.copy2(paths.source_candidate, destination)
    if os.name == "posix":
        destination.chmod(0o600)
    extraction_started = perf_counter()
    dates = _date_map(paths.source_workbook)
    reviews = _review_map(paths.serial_review)

    with closing(sqlite3.connect(destination)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = DELETE")
        before_counts = _operational_counts(connection)
        nonempty = {key: value for key, value in before_counts.items() if value}
        if nonempty:
            raise RuntimeError(
                "full candidate source contains operational data: " + _json(nonempty)
            )
        preserved_tables = (
            "users",
            "reference_values",
            "reference_domains_v2",
            "reference_values_v2",
            "reference_aliases_v2",
            "catalog_items_v2",
            "migration_batches",
            "migration_source_files",
            "migration_staging_rows",
            "migration_serial_cells",
            "migration_validation_results",
        )
        preserved_before = _table_counts(connection, preserved_tables)
        batch = connection.execute(
            """SELECT id, source_manifest_sha256, completed_at, created_at
                 FROM migration_batches
                WHERE stage='0.13.3A' AND status='REVIEW_REQUIRED'"""
        ).fetchone()
        if batch is None:
            raise RuntimeError("source candidate is not Stage 0.13.3A REVIEW_REQUIRED")
        source_manifest_sha = str(batch["source_manifest_sha256"])
        created_at = str(batch["completed_at"] or batch["created_at"])
        aliases = _approved_alias_maps(connection)
        receipt_rows = _operation_rows(
            connection, "RECEIPT", dates, reviews, aliases
        )
        issue_rows = _operation_rows(
            connection, "ISSUE", dates, reviews, aliases
        )
        extraction_ms = (perf_counter() - extraction_started) * 1000
        if len(receipt_rows) != EXPECTED_RECEIPT_ROWS:
            raise RuntimeError(
                f"expected {EXPECTED_RECEIPT_ROWS} receipt rows, got {len(receipt_rows)}"
            )
        if len(issue_rows) != EXPECTED_ISSUE_ROWS:
            raise RuntimeError(
                f"expected {EXPECTED_ISSUE_ROWS} issue rows, got {len(issue_rows)}"
            )

        create_full_schema(connection)
        connection.execute("DROP INDEX IF EXISTS idx_stock_receipts_serial_unique")
        connection.execute(
            """CREATE INDEX idx_stock_receipts_serial_migration_lookup
               ON stock_receipts(serial_number COLLATE NOCASE)
               WHERE trim(serial_number)<>''"""
        )
        connection.execute(
            "DELETE FROM sqlite_sequence WHERE name IN "
            "('stock_receipts','stock_issues','stock_issue_allocations','audit_log')"
        )
        connection.commit()
        connection.execute("BEGIN IMMEDIATE")
        try:
            receipt_started = perf_counter()
            identity_by_key, identity_by_id, receipt_counts, receipt_identity_count = (
                _process_receipts(
                    connection, receipt_rows, hooks, created_at=created_at
                )
            )
            receipt_ms = (perf_counter() - receipt_started) * 1000
            issue_started = perf_counter()
            issue_counts, final_identity_id, opening_states = _process_issues(
                connection,
                issue_rows,
                hooks,
                identity_by_key,
                identity_by_id,
                first_identity_id=receipt_identity_count,
                created_at=created_at,
            )
            issue_ms = (perf_counter() - issue_started) * 1000

            reconciliation_count = int(connection.execute(
                "SELECT COUNT(*) FROM migration_full_reconciliation"
            ).fetchone()[0])
            if reconciliation_count != EXPECTED_TOTAL_ROWS:
                raise RuntimeError(
                    f"reconciliation rows={reconciliation_count}; expected {EXPECTED_TOTAL_ROWS}"
                )
            after_counts = _operational_counts(connection)
            preserved_after = _table_counts(connection, preserved_tables)
            _insert_cleanliness_rows(
                connection,
                before=before_counts,
                after=after_counts,
                preserved_before=preserved_before,
                preserved_after=preserved_after,
                production=production,
                created_at=created_at,
            )

            provisional_count = int(connection.execute(
                """SELECT COUNT(*) FROM migration_full_identities
                    WHERE preservation_status='NUMERIC_FORMAT_UNPROVEN'"""
            ).fetchone()[0])
            quarantine_count = int(connection.execute(
                "SELECT COUNT(*) FROM migration_full_quarantine"
            ).fetchone()[0])
            build_key = hashlib.sha256(
                "\0".join((
                    BUILD_RULE_VERSION,
                    source_candidate_sha,
                    source_manifest_sha,
                    sha256_file(paths.serial_review),
                )).encode("utf-8")
            ).hexdigest()
            connection.execute(
                """INSERT INTO migration_full_marker(
                       id, marker, stage, status, review_read_only,
                       source_candidate_sha256, source_manifest_sha256,
                       source_workbook_sha256, production_baseline_sha256,
                       receipt_source_rows, issue_source_rows,
                       reconciliation_rows, identity_count, receipt_count,
                       issue_count, opening_state_count,
                       provisional_identity_count, quarantine_count,
                       receipt_status_counts, issue_status_counts, raw_hashes,
                       build_key, build_started_at, built_at
                   ) VALUES (1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    FULL_MARKER,
                    FULL_STAGE,
                    FULL_STATUS,
                    1,
                    source_candidate_sha,
                    source_manifest_sha,
                    raw_hashes[paths.source_workbook.name],
                    production_sha,
                    EXPECTED_RECEIPT_ROWS,
                    EXPECTED_ISSUE_ROWS,
                    reconciliation_count,
                    final_identity_id,
                    after_counts["stock_receipts"],
                    after_counts["stock_issues"],
                    opening_states,
                    provisional_count,
                    quarantine_count,
                    _json(dict(sorted(receipt_counts.items()))),
                    _json(dict(sorted(issue_counts.items()))),
                    _json(dict(sorted(raw_hashes.items()))),
                    build_key,
                    created_at,
                    created_at,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

        leading = connection.execute(
            """SELECT display_serial_value, target_receipt_id
                 FROM migration_full_identities
                WHERE preservation_status='TEXT_EXACT'
                  AND display_serial_value GLOB '0*'
                ORDER BY id LIMIT 1"""
        ).fetchone()
        if leading is None:
            raise RuntimeError("full candidate has no leading-zero TEXT_EXACT identity")
        search_ms, search_rows = _measure(
            connection,
            """SELECT id FROM migration_full_identities
                WHERE display_serial_value=? COLLATE BINARY""",
            (str(leading["display_serial_value"]),),
        )
        card_ms, card_rows = _measure(
            connection,
            """SELECT i.id, i.display_serial_value, r.item_name, r.vendor, r.model
                 FROM migration_full_identities i
                 JOIN stock_receipts r ON r.id=i.target_receipt_id
                WHERE i.target_receipt_id=?""",
            (int(leading["target_receipt_id"]),),
        )
        timeline_ms, timeline_rows = _measure(
            connection,
            """SELECT event_date, action FROM audit_log
                WHERE entity_type='stock_receipt' AND entity_id=? ORDER BY id""",
            (str(leading["target_receipt_id"]),),
        )
        if len(search_rows) != 1 or len(card_rows) != 1 or not timeline_rows:
            raise RuntimeError("full candidate performance probes returned invalid rows")
        metrics = {
            "extraction": extraction_ms,
            "receipt_import": receipt_ms,
            "issue_import": issue_ms,
            "exact_search": search_ms,
            "card_open": card_ms,
            "timeline": timeline_ms,
            "database_build_before_reports": (perf_counter() - build_started) * 1000,
        }
        for metric, duration in metrics.items():
            connection.execute(
                """INSERT INTO migration_full_performance(
                       metric, duration_ms, details, measured_at
                   ) VALUES (?,?,?,?)""",
                (
                    metric,
                    f"{duration:.3f}",
                    _json({"scope": "full candidate database-side probe"}),
                    created_at,
                ),
            )
        connection.commit()
        connection.execute("ANALYZE")
        connection.commit()
        connection.execute("VACUUM")

    if os.name == "posix":
        destination.chmod(0o600)
    return {
        "receipt_status_counts": dict(sorted(receipt_counts.items())),
        "issue_status_counts": dict(sorted(issue_counts.items())),
        "operational_counts_before_import": dict(before_counts),
        "operational_counts_after_import": dict(after_counts),
        "preserved_counts_before": dict(preserved_before),
        "preserved_counts_after": dict(preserved_after),
        "identity_count": final_identity_id,
        "opening_state_count": opening_states,
        "performance_ms": {key: round(value, 3) for key, value in metrics.items()},
        "created_at": created_at,
    }


def validate_full_database(
    path: Path,
    *,
    production_db: Path | None = None,
) -> dict[str, Any]:
    """Validate cardinality, preservation, provenance and clean-room rules."""

    if not path.is_file():
        raise FileNotFoundError(path)
    if path.name != "warehouse_full_candidate.db":
        raise RuntimeError("full candidate filename marker mismatch")
    sidecars = candidate_sidecars(path)
    if sidecars:
        raise RuntimeError("full candidate has SQLite sidecars: " + ", ".join(sidecars))
    mode = stat.S_IMODE(path.stat().st_mode)
    if os.name == "posix" and mode != 0o600:
        raise RuntimeError(f"full candidate mode must be 0600, got {mode:04o}")

    with closing(connect_readonly(path)) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing = sorted(set(FULL_TABLES).difference(tables))
        if missing:
            raise RuntimeError("full candidate tables missing: " + ", ".join(missing))
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = list(connection.execute("PRAGMA foreign_key_check"))
        if integrity != "ok" or foreign_keys:
            raise RuntimeError(
                f"full SQLite health failed: integrity={integrity}, fk={len(foreign_keys)}"
            )
        marker_rows = list(connection.execute("SELECT * FROM migration_full_marker"))
        if len(marker_rows) != 1:
            raise RuntimeError("full candidate marker must contain exactly one row")
        marker = dict(marker_rows[0])
        expected_marker = {
            "marker": FULL_MARKER,
            "stage": FULL_STAGE,
            "status": FULL_STATUS,
            "review_read_only": 1,
            "receipt_source_rows": EXPECTED_RECEIPT_ROWS,
            "issue_source_rows": EXPECTED_ISSUE_ROWS,
            "reconciliation_rows": EXPECTED_TOTAL_ROWS,
        }
        for key, expected in expected_marker.items():
            if marker.get(key) != expected:
                raise RuntimeError(f"invalid full marker {key}: {marker.get(key)!r}")

        source_counts = {
            str(row[0]): int(row[1])
            for row in connection.execute(
                """SELECT operation_kind, COUNT(*)
                     FROM migration_full_reconciliation
                    GROUP BY operation_kind"""
            )
        }
        if source_counts != {
            "RECEIPT": EXPECTED_RECEIPT_ROWS,
            "ISSUE": EXPECTED_ISSUE_ROWS,
        }:
            raise RuntimeError(f"full reconciliation counts changed: {source_counts}")
        receipt_statuses = {
            str(row[0]): int(row[1])
            for row in connection.execute(
                """SELECT final_status, COUNT(*)
                     FROM migration_full_reconciliation
                    WHERE operation_kind='RECEIPT'
                    GROUP BY final_status"""
            )
        }
        issue_statuses = {
            str(row[0]): int(row[1])
            for row in connection.execute(
                """SELECT final_status, COUNT(*)
                     FROM migration_full_reconciliation
                    WHERE operation_kind='ISSUE'
                    GROUP BY final_status"""
            )
        }
        if sum(receipt_statuses.values()) != EXPECTED_RECEIPT_ROWS:
            raise RuntimeError("receipt status reconciliation is incomplete")
        if sum(issue_statuses.values()) != EXPECTED_ISSUE_ROWS:
            raise RuntimeError("issue status reconciliation is incomplete")
        if json.loads(str(marker["receipt_status_counts"])) != receipt_statuses:
            raise RuntimeError("marker receipt status counts mismatch")
        if json.loads(str(marker["issue_status_counts"])) != issue_statuses:
            raise RuntimeError("marker issue status counts mismatch")

        counts = {
            "identities": int(connection.execute(
                "SELECT COUNT(*) FROM migration_full_identities"
            ).fetchone()[0]),
            "receipts": int(connection.execute(
                "SELECT COUNT(*) FROM stock_receipts"
            ).fetchone()[0]),
            "issues": int(connection.execute(
                "SELECT COUNT(*) FROM stock_issues"
            ).fetchone()[0]),
            "allocations": int(connection.execute(
                "SELECT COUNT(*) FROM stock_issue_allocations"
            ).fetchone()[0]),
            "opening_states": int(connection.execute(
                "SELECT COUNT(*) FROM migration_full_identities WHERE opening_state=1"
            ).fetchone()[0]),
            "provisional": int(connection.execute(
                """SELECT COUNT(*) FROM migration_full_identities
                    WHERE preservation_status='NUMERIC_FORMAT_UNPROVEN'"""
            ).fetchone()[0]),
            "quarantine": int(connection.execute(
                "SELECT COUNT(*) FROM migration_full_quarantine"
            ).fetchone()[0]),
            "warnings": int(connection.execute(
                "SELECT COUNT(*) FROM migration_full_warnings"
            ).fetchone()[0]),
        }
        if counts["identities"] != counts["receipts"]:
            raise RuntimeError("every full identity must own exactly one receipt state")
        if counts["issues"] != counts["allocations"]:
            raise RuntimeError("every imported serialized issue must have one allocation")
        for key, marker_key in (
            ("identities", "identity_count"),
            ("receipts", "receipt_count"),
            ("issues", "issue_count"),
            ("opening_states", "opening_state_count"),
            ("provisional", "provisional_identity_count"),
            ("quarantine", "quarantine_count"),
        ):
            if counts[key] != int(marker[marker_key]):
                raise RuntimeError(f"marker {marker_key} mismatch")

        no_status = int(connection.execute(
            "SELECT COUNT(*) FROM migration_full_reconciliation WHERE trim(final_status)=''"
        ).fetchone()[0])
        non_text = int(connection.execute(
            """SELECT COUNT(*) FROM migration_full_reconciliation
                WHERE typeof(source_serial_value)<>'text'
                   OR typeof(display_serial_value)<>'text'
                   OR typeof(raw_xml_value)<>'text'
                   OR typeof(source_row_hash)<>'text'"""
        ).fetchone()[0])
        corrupted_links = int(connection.execute(
            """SELECT COUNT(*) FROM migration_full_reconciliation
                WHERE preservation_status='SOURCE_CORRUPTED'
                  AND (target_identity_id IS NOT NULL
                       OR target_receipt_id IS NOT NULL
                       OR target_issue_id IS NOT NULL)"""
        ).fetchone()[0])
        unsafe_quarantine = int(connection.execute(
            """SELECT COUNT(*) FROM migration_full_quarantine q
                 JOIN migration_full_reconciliation r ON r.id=q.reconciliation_id
                WHERE q.affects_balance<>0
                   OR r.target_receipt_id IS NOT NULL
                   OR r.target_issue_id IS NOT NULL"""
        ).fetchone()[0])
        if no_status or non_text or corrupted_links or unsafe_quarantine:
            raise RuntimeError(
                "full reconciliation preservation failed: "
                f"status={no_status}, text={non_text}, corrupted={corrupted_links}, "
                f"quarantine={unsafe_quarantine}"
            )

        leading_zero_loss = int(connection.execute(
            """SELECT COUNT(*)
                 FROM migration_full_reconciliation r
                 JOIN migration_staging_rows s ON s.id=r.staging_row_id
                WHERE r.preservation_status='TEXT_EXACT'
                  AND s.source_serial_value GLOB '0*'
                  AND r.source_serial_value<>s.source_serial_value COLLATE BINARY"""
        ).fetchone()[0])
        provisional_inventory = int(connection.execute(
            """SELECT COUNT(*)
                 FROM migration_full_identities i
                 JOIN stock_receipts r ON r.id=i.target_receipt_id
                WHERE i.preservation_status='NUMERIC_FORMAT_UNPROVEN'
                  AND trim(r.inventory_number)<>''"""
        ).fetchone()[0])
        provisional_flags = int(connection.execute(
            """SELECT COUNT(*) FROM migration_full_identities
                WHERE preservation_status='NUMERIC_FORMAT_UNPROVEN'
                  AND (identity_confidence<>'PROVISIONAL'
                       OR authoritative<>0
                       OR requires_manual_review<>1
                       OR raw_xml_value='')"""
        ).fetchone()[0])
        exact_flags = int(connection.execute(
            """SELECT COUNT(*) FROM migration_full_identities
                WHERE preservation_status='TEXT_EXACT'
                  AND (identity_confidence<>'AUTHORITATIVE'
                       OR authoritative<>1
                       OR normalized_match_value='')"""
        ).fetchone()[0])
        provisional_wrong_link = int(connection.execute(
            """SELECT COUNT(*)
                 FROM migration_full_reconciliation r
                 JOIN migration_full_identities i ON i.id=r.target_identity_id
                WHERE r.preservation_status='NUMERIC_FORMAT_UNPROVEN'
                  AND i.preservation_status<>'NUMERIC_FORMAT_UNPROVEN'"""
        ).fetchone()[0])
        if (
            leading_zero_loss or provisional_inventory or provisional_flags
            or exact_flags or provisional_wrong_link
        ):
            raise RuntimeError(
                "full identity preservation failed: "
                f"leading={leading_zero_loss}, inv={provisional_inventory}, "
                f"provisional={provisional_flags}, exact={exact_flags}, "
                f"merge={provisional_wrong_link}"
            )
        for row in connection.execute(
            """SELECT raw_xml_value, display_serial_value
                 FROM migration_full_identities
                WHERE preservation_status='NUMERIC_FORMAT_UNPROVEN'"""
        ):
            if _decimal_display(str(row["raw_xml_value"])) != str(
                row["display_serial_value"]
            ):
                raise RuntimeError("numeric provisional display was not Decimal-expanded")

        opening_mismatch = int(connection.execute(
            """SELECT COUNT(*)
                 FROM migration_full_identities i
                 JOIN stock_receipts r ON r.id=i.target_receipt_id
                WHERE (i.opening_state=1 AND (
                           r.is_opening_balance<>1 OR r.order_date<>''
                           OR r.request_number<>'' OR r.order_number<>''
                           OR r.plu<>'' OR r.supplier<>''
                       ))
                   OR (i.opening_state=0 AND r.is_opening_balance<>0)"""
        ).fetchone()[0])
        opening_audits = int(connection.execute(
            """SELECT COUNT(*) FROM audit_log
                WHERE action='MIGRATION_OPENING_STATE_CREATED'"""
        ).fetchone()[0])
        orphan_allocations = int(connection.execute(
            """SELECT COUNT(*) FROM stock_issue_allocations a
                LEFT JOIN stock_issues i ON i.id=a.issue_id
                LEFT JOIN stock_receipts r ON r.id=a.receipt_id
                WHERE i.id IS NULL OR r.id IS NULL"""
        ).fetchone()[0])
        negative_balances = int(connection.execute(
            """SELECT COUNT(*) FROM (
                   SELECT r.id, r.quantity-COALESCE(SUM(a.quantity),0) balance
                     FROM stock_receipts r
                     LEFT JOIN stock_issue_allocations a ON a.receipt_id=r.id
                    GROUP BY r.id HAVING balance < -0.0000001
                )"""
        ).fetchone()[0])
        issue_provenance = int(connection.execute(
            """SELECT COUNT(*) FROM stock_issues i
                LEFT JOIN migration_full_reconciliation r ON r.target_issue_id=i.id
                WHERE r.id IS NULL"""
        ).fetchone()[0])
        receipt_provenance = int(connection.execute(
            """SELECT COUNT(*) FROM stock_receipts r
                LEFT JOIN migration_full_identities i ON i.target_receipt_id=r.id
                WHERE i.id IS NULL"""
        ).fetchone()[0])
        if (
            opening_mismatch or opening_audits != counts["opening_states"]
            or orphan_allocations or negative_balances
            or issue_provenance or receipt_provenance
        ):
            raise RuntimeError(
                "full operational provenance failed: "
                f"opening={opening_mismatch}/{opening_audits}, "
                f"orphans={orphan_allocations}, negative={negative_balances}, "
                f"issues={issue_provenance}, receipts={receipt_provenance}"
            )

        forbidden_operational = {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "deliveries", "delivery_lines", "equipment", "operations",
                "work_logs", "daily_report_uploads", "daily_report_rows",
            )
        }
        if any(forbidden_operational.values()):
            raise RuntimeError(
                "full candidate contains copied operational data: "
                + _json(forbidden_operational)
            )
        bad_receipt_ids = int(connection.execute(
            "SELECT COUNT(*) FROM stock_receipts WHERE id<=?", (RECEIPT_ID_BASE,)
        ).fetchone()[0])
        bad_issue_ids = int(connection.execute(
            "SELECT COUNT(*) FROM stock_issues WHERE id<=?", (ISSUE_ID_BASE,)
        ).fetchone()[0])
        bad_allocation_ids = int(connection.execute(
            "SELECT COUNT(*) FROM stock_issue_allocations WHERE id<=?",
            (ALLOCATION_ID_BASE,),
        ).fetchone()[0])
        allowed_events = {
            "MIGRATION_RECEIPT_IMPORTED",
            "MIGRATION_SOURCE_ROW_LINKED",
            "MIGRATION_EXACT_DUPLICATE_SKIPPED",
            "MIGRATION_CONFLICT_RECORDED",
            "MIGRATION_NUMERIC_IDENTITY_PROVISIONAL",
            "MIGRATION_OPENING_STATE_CREATED",
            "MIGRATION_ISSUE_IMPORTED",
            "MIGRATION_SERIAL_QUARANTINED",
        }
        unexpected_events = {
            str(row[0]) for row in connection.execute(
                "SELECT DISTINCT action FROM audit_log"
            ) if str(row[0]) not in allowed_events
        }
        absolute_paths = int(connection.execute(
            """SELECT COUNT(*) FROM audit_log
                WHERE details LIKE '%/Users/%'
                   OR details LIKE '%/private/%'
                   OR details GLOB '*[A-Za-z]:\\*'"""
        ).fetchone()[0])
        active_admins = int(connection.execute(
            "SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1"
        ).fetchone()[0])
        if (
            bad_receipt_ids or bad_issue_ids or bad_allocation_ids
            or unexpected_events or absolute_paths or active_admins < 1
        ):
            raise RuntimeError(
                "full clean/security boundary failed: "
                f"ids={bad_receipt_ids}/{bad_issue_ids}/{bad_allocation_ids}, "
                f"events={sorted(unexpected_events)}, paths={absolute_paths}, "
                f"admins={active_admins}"
            )

        cleanliness_failures = int(connection.execute(
            "SELECT COUNT(*) FROM migration_full_cleanliness WHERE result NOT IN ('PASS','INFO')"
        ).fetchone()[0])
        if cleanliness_failures:
            raise RuntimeError("operational cleanliness evidence has failures")

        test_serial_count = 0
        if production_db is not None:
            current_sha = sha256_file(production_db)
            if current_sha != str(marker["production_baseline_sha256"]):
                raise RuntimeError("data/warehouse.db SHA changed since full build")
            production = _production_snapshot(production_db)
            for source in production["test_serials"]:
                serial = str(source["serial_number"])
                found = int(connection.execute(
                    """SELECT COUNT(*) FROM migration_full_identities
                        WHERE display_serial_value=? COLLATE BINARY
                           OR preserved_serial_value=? COLLATE BINARY""",
                    (serial, serial),
                ).fetchone()[0])
                if found:
                    raise RuntimeError(f"test S/N present in full candidate: {serial}")
                test_serial_count += 1

    return {
        "marker": FULL_MARKER,
        "stage": FULL_STAGE,
        "status": FULL_STATUS,
        "database": path.name,
        "integrity_check": "ok",
        "foreign_key_errors": 0,
        "receipt_source_rows": EXPECTED_RECEIPT_ROWS,
        "issue_source_rows": EXPECTED_ISSUE_ROWS,
        "reconciliation_rows": EXPECTED_TOTAL_ROWS,
        "receipt_status_counts": receipt_statuses,
        "issue_status_counts": issue_statuses,
        **counts,
        "forbidden_operational_counts": forbidden_operational,
        "excluded_test_serials_verified": test_serial_count,
        "mode": "0600" if os.name == "posix" else "platform-default",
        "sidecars": [],
        "database_size_bytes": path.stat().st_size,
    }


def _text_rows(
    connection: sqlite3.Connection,
    sql: str,
    parameters: tuple[Any, ...] = (),
) -> tuple[list[str], list[dict[str, str]]]:
    cursor = connection.execute(sql, parameters)
    headers = [str(item[0]) for item in cursor.description or ()]
    rows = [
        {
            header: _report_text(row[index])
            for index, header in enumerate(headers)
        }
        for row in cursor
    ]
    return headers, rows


def _report_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    result: list[str] = []
    for character in text:
        code = ord(character)
        if (
            code in range(0x00, 0x09)
            or code in (0x0B, 0x0C)
            or code in range(0x0E, 0x20)
            or code in (0xFFFE, 0xFFFF)
            or 0xD800 <= code <= 0xDFFF
        ):
            result.append(f"\\u{code:04X}")
        else:
            result.append(character)
    return "".join(result)


def _manual_checklist(connection: sqlite3.Connection) -> list[dict[str, str]]:
    specs = (
        (
            "LEADING_ZERO_TEXT_EXACT",
            "i.preservation_status='TEXT_EXACT' AND i.display_serial_value GLOB '0*'",
            5,
            "S/N должен начинаться с 0 символ-в-символ; открыть карточку и Timeline",
        ),
        (
            "NUMERIC_PROVISIONAL",
            "i.preservation_status='NUMERIC_FORMAT_UNPROVEN'",
            5,
            "Decimal display + raw exponent/token + warning; Inventory Number запрещён",
        ),
        (
            "CONFLICT",
            "i.conflicts<>'[]'",
            5,
            "Одна identity, варианты и conflicts видны; второй receipt отсутствует",
        ),
        (
            "OPENING_STATE",
            "i.opening_state=1",
            5,
            "Timeline показывает техническое начальное состояние, не реальный приход",
        ),
        (
            "EQUIPMENT",
            "i.object_kind='equipment' AND i.opening_state=0",
            3,
            "Canonical/source names, historical date, provenance и balance",
        ),
        (
            "COMPONENT",
            "i.object_kind='component' AND i.opening_state=0",
            2,
            "Компонент и target-equipment relationship отображаются корректно",
        ),
    )
    result: list[dict[str, str]] = []
    seen: set[int] = set()
    check_number = 0
    for check_type, where, limit, expected in specs:
        rows = connection.execute(
            f"""SELECT i.id, i.display_serial_value, i.raw_xml_value,
                       i.canonical_item_name, i.target_receipt_id
                  FROM migration_full_identities i
                 WHERE {where}
                 ORDER BY i.id LIMIT ?""",
            (limit * 3,),
        )
        selected = 0
        for row in rows:
            identity_id = int(row["id"])
            if identity_id in seen:
                continue
            seen.add(identity_id)
            check_number += 1
            selected += 1
            result.append({
                "check_number": str(check_number),
                "check_type": check_type,
                "identity_id": str(identity_id),
                "receipt_id": str(row["target_receipt_id"]),
                "display_serial": str(row["display_serial_value"]),
                "raw_numeric_token": str(row["raw_xml_value"] or ""),
                "canonical_item_name": str(row["canonical_item_name"]),
                "expected": expected,
                "review_result": "",
                "reviewer_comment": "",
            })
            if selected >= limit:
                break
    return result


def _report_sheets(
    connection: sqlite3.Connection,
    validation: Mapping[str, Any],
) -> dict[str, tuple[list[str], list[dict[str, str]]]]:
    marker = dict(connection.execute("SELECT * FROM migration_full_marker").fetchone())
    summary_rows = [
        {"metric": "marker", "value": str(marker["marker"])},
        {"metric": "stage", "value": str(marker["stage"])},
        {"metric": "status", "value": str(marker["status"])},
        {"metric": "receipt_source_rows", "value": str(marker["receipt_source_rows"])},
        {"metric": "issue_source_rows", "value": str(marker["issue_source_rows"])},
        {"metric": "reconciliation_rows", "value": str(marker["reconciliation_rows"])},
        {"metric": "identities", "value": str(marker["identity_count"])},
        {"metric": "operational_receipts", "value": str(marker["receipt_count"])},
        {"metric": "operational_issues", "value": str(marker["issue_count"])},
        {"metric": "opening_states", "value": str(marker["opening_state_count"])},
        {"metric": "provisional_numeric", "value": str(marker["provisional_identity_count"])},
        {"metric": "quarantine", "value": str(marker["quarantine_count"])},
        {"metric": "receipt_status_counts", "value": str(marker["receipt_status_counts"])},
        {"metric": "issue_status_counts", "value": str(marker["issue_status_counts"])},
        {"metric": "integrity_check", "value": str(validation["integrity_check"])},
        {"metric": "foreign_key_errors", "value": str(validation["foreign_key_errors"])},
        {"metric": "database_size_bytes", "value": str(validation["database_size_bytes"])},
    ]
    sheets: dict[str, tuple[list[str], list[dict[str, str]]]] = {
        "SUMMARY": (["metric", "value"], summary_rows),
    }
    sheets["SOURCE_ROW_RECONCILIATION"] = _text_rows(
        connection,
        """SELECT source_file, source_sheet, source_row, source_row_hash,
                  operation_kind, source_serial_value, display_serial_value,
                  preservation_status, final_status,
                  target_identity_id, target_receipt_id, target_issue_id,
                  warnings, non_application_reason
             FROM migration_full_reconciliation
            ORDER BY operation_kind, source_row, id""",
    )
    sheets["RECEIPT_RESULTS"] = _text_rows(
        connection,
        """SELECT source_file, source_sheet, source_row, source_row_hash,
                  source_serial_value, display_serial_value, raw_xml_value,
                  preservation_status, final_status, target_identity_id,
                  target_receipt_id, source_item_name, canonical_item_name,
                  vendor, model, part_number, category, equipment_type,
                  component_type, source_operation_date, shelf, warnings,
                  conflicts, non_application_reason
             FROM migration_full_reconciliation
            WHERE operation_kind='RECEIPT'
            ORDER BY source_row, id""",
    )
    sheets["ISSUE_RESULTS"] = _text_rows(
        connection,
        """SELECT source_file, source_sheet, source_row, source_row_hash,
                  source_serial_value, display_serial_value, raw_xml_value,
                  preservation_status, final_status, target_identity_id,
                  target_receipt_id, target_issue_id, source_item_name,
                  canonical_item_name, quantity, source_operation_date,
                  target_equipment_source_serial,
                  target_equipment_display_serial,
                  target_equipment_preservation_status,
                  warnings, conflicts, non_application_reason
             FROM migration_full_reconciliation
            WHERE operation_kind='ISSUE'
            ORDER BY source_row, id""",
    )
    sheets["IDENTITIES"] = _text_rows(
        connection,
        """SELECT id AS identity_id, identity_key, normalized_match_value,
                  preserved_serial_value, display_serial_value, raw_xml_value,
                  preservation_status, identity_confidence, authoritative,
                  requires_manual_review, opening_state, primary_staging_row_id,
                  target_receipt_id, source_row_count, source_item_name,
                  canonical_item_name, object_kind, category, equipment_type,
                  component_type, vendor, model, part_number,
                  normalization_rule, warnings, conflicts
             FROM migration_full_identities ORDER BY id""",
    )
    sheets["PROVISIONAL_NUMERIC"] = _text_rows(
        connection,
        """SELECT id AS identity_id, display_serial_value, raw_xml_value,
                  identity_confidence, authoritative, requires_manual_review,
                  opening_state, target_receipt_id, canonical_item_name,
                  warnings
             FROM migration_full_identities
            WHERE preservation_status='NUMERIC_FORMAT_UNPROVEN'
            ORDER BY id""",
    )
    sheets["SOURCE_CORRUPTED"] = _text_rows(
        connection,
        """SELECT source_file, source_sheet, source_row, source_row_hash,
                  operation_kind, source_serial_value, raw_xml_value,
                  final_status, warnings, non_application_reason
             FROM migration_full_reconciliation
            WHERE preservation_status='SOURCE_CORRUPTED'
            ORDER BY operation_kind, source_row""",
    )
    sheets["EXACT_DUPLICATES"] = _text_rows(
        connection,
        """SELECT source_file, source_sheet, source_row, operation_kind,
                  source_row_hash, display_serial_value, target_identity_id,
                  target_receipt_id, target_issue_id, warnings
             FROM migration_full_reconciliation
            WHERE final_status='EXACT_DUPLICATE'
            ORDER BY operation_kind, source_row""",
    )
    sheets["CONFLICTS"] = _text_rows(
        connection,
        """SELECT source_file, source_sheet, source_row, operation_kind,
                  source_row_hash, display_serial_value, final_status,
                  target_identity_id, target_receipt_id, conflicts, warnings,
                  non_application_reason
             FROM migration_full_reconciliation
            WHERE final_status='CONFLICT_HISTORY_ONLY' OR conflicts<>'[]'
            ORDER BY operation_kind, source_row""",
    )
    sheets["OPENING_STATES"] = _text_rows(
        connection,
        """SELECT i.id AS identity_id, i.display_serial_value, i.raw_xml_value,
                  i.preservation_status, i.target_receipt_id,
                  i.canonical_item_name, r.receipt_date, r.is_opening_balance,
                  i.warnings
             FROM migration_full_identities i
             JOIN stock_receipts r ON r.id=i.target_receipt_id
            WHERE i.opening_state=1 ORDER BY i.id""",
    )
    sheets["UNRESOLVED_ISSUES"] = _text_rows(
        connection,
        """SELECT source_file, source_sheet, source_row, source_row_hash,
                  source_serial_value, display_serial_value,
                  preservation_status, final_status, warnings,
                  non_application_reason
             FROM migration_full_reconciliation
            WHERE operation_kind='ISSUE'
              AND final_status IN ('UNRESOLVED_ISSUE','FAILED_WITH_REASON')
            ORDER BY source_row""",
    )
    sheets["QUARANTINE"] = _text_rows(
        connection,
        """SELECT q.id, q.reason_code, q.raw_token, q.source_file,
                  q.source_sheet, q.source_row, q.affects_balance,
                  q.resolution_status, r.operation_kind, r.final_status,
                  r.warnings, r.non_application_reason
             FROM migration_full_quarantine q
             JOIN migration_full_reconciliation r ON r.id=q.reconciliation_id
            ORDER BY q.source_sheet, q.source_row""",
    )
    sheets["DEFERRED_QUANTITY"] = _text_rows(
        connection,
        """SELECT source_file, source_sheet, source_row, source_row_hash,
                  operation_kind, source_serial_value, display_serial_value,
                  source_item_name, quantity, final_status, warnings,
                  non_application_reason
             FROM migration_full_reconciliation
            WHERE final_status='QUANTITY_DEFERRED'
            ORDER BY operation_kind, source_row""",
    )
    sheets["REFERENCES"] = _text_rows(
        connection,
        """SELECT d.domain_key, v.id AS reference_id, v.display_name,
                  v.normalized_key, v.scope_key, v.approval_status,
                  v.source, '' AS alias_source, '' AS alias_status,
                  '' AS alias_confidence
             FROM reference_values_v2 v
             JOIN reference_domains_v2 d ON d.id=v.domain_id
            UNION ALL
           SELECT d.domain_key, v.id, v.display_name, v.normalized_key,
                  v.scope_key, v.approval_status, v.source,
                  a.source_value, a.resolution_status, a.confidence
             FROM reference_aliases_v2 a
             JOIN reference_domains_v2 d ON d.id=a.domain_id
             JOIN reference_values_v2 v ON v.id=a.canonical_id
            ORDER BY 1, 3, 8""",
    )
    sheets["PERFORMANCE"] = _text_rows(
        connection,
        """SELECT metric, duration_ms, details, measured_at
             FROM migration_full_performance ORDER BY id""",
    )
    validation_rows = [
        {"check": key, "result": _json(value) if isinstance(value, (dict, list)) else str(value)}
        for key, value in sorted(validation.items())
    ]
    sheets["VALIDATION"] = (["check", "result"], validation_rows)
    checklist = _manual_checklist(connection)
    sheets["MANUAL_REVIEW_CHECKLIST"] = (
        list(checklist[0]) if checklist else [
            "check_number", "check_type", "identity_id", "receipt_id",
            "display_serial", "raw_numeric_token", "canonical_item_name",
            "expected", "review_result", "reviewer_comment",
        ],
        checklist,
    )
    sheets["OPERATIONAL_CLEANLINESS"] = _text_rows(
        connection,
        """SELECT check_kind, source_table, source_id, source_serial,
                  before_count, after_count, result, details
             FROM migration_full_cleanliness ORDER BY id""",
    )
    return sheets


def _markdown_status_table(title: str, counts: Mapping[str, int]) -> str:
    lines = [f"## {title}", "", "| Final status | Rows |", "|---|---:|"]
    lines.extend(f"| {key} | {value} |" for key, value in sorted(counts.items()))
    return "\n".join(lines)


def _write_main_markdown(
    path: Path,
    validation: Mapping[str, Any],
) -> None:
    receipt_counts = validation["receipt_status_counts"]
    issue_counts = validation["issue_status_counts"]
    text = "\n".join((
        "# Full Warehouse Migration Report",
        "",
        f"Marker: `{FULL_MARKER}`. Status: `{FULL_STATUS}`.",
        "",
        "The database is a disposable manual-acceptance candidate. "
        "It is not a production deployment and must not be edited manually.",
        "",
        f"- Receipt source rows reconciled: {EXPECTED_RECEIPT_ROWS}",
        f"- Issue source rows reconciled: {EXPECTED_ISSUE_ROWS}",
        f"- Total reconciliation rows: {EXPECTED_TOTAL_ROWS}",
        f"- Identities: {validation['identities']}",
        f"- Operational receipts / states: {validation['receipts']}",
        f"- Operational issues: {validation['issues']}",
        f"- Provisional numeric identities: {validation['provisional']}",
        f"- Opening states: {validation['opening_states']}",
        f"- Quarantine: {validation['quarantine']}",
        "",
        _markdown_status_table("Receipt reconciliation", receipt_counts),
        "",
        _markdown_status_table("Issue reconciliation", issue_counts),
        "",
        "## Safety and validation",
        "",
        f"- `integrity_check={validation['integrity_check']}`; foreign-key errors: "
        f"{validation['foreign_key_errors']}.",
        "- Raw S/N tokens and source row hashes are retained in the XLSX and DB.",
        "- Numeric provisional display values are expanded with `Decimal`; raw XML "
        "tokens remain provenance and may have lost leading zeroes before extraction.",
        "- `SOURCE_CORRUPTED` rows create neither identity nor stock receipt.",
        "- Opening states are technical balance states, not historical receipts.",
        "- The `БАЛАНС` sheet was not used to create identities or operations.",
        "- Shelf is provenance/location only and is not part of `identity_key`.",
        "",
        "See `SOURCE_ROW_RECONCILIATION` for the one-row-to-one-final-status proof "
        "and `MANUAL_REVIEW_CHECKLIST` for the acceptance sample.",
        "",
    ))
    path.write_text(text, encoding="utf-8")


def _cleanliness_sheets(
    connection: sqlite3.Connection,
) -> dict[str, tuple[list[str], list[dict[str, str]]]]:
    all_rows = _text_rows(
        connection,
        """SELECT check_kind, source_table, source_id, source_serial,
                  before_count, after_count, result, details
             FROM migration_full_cleanliness ORDER BY id""",
    )
    return {
        "SUMMARY": (
            ["statement", "result"],
            [
                {"statement": "Source candidate operational tables empty before import", "result": "PASS"},
                {"statement": "Production test S/N absent from candidate", "result": "PASS"},
                {"statement": "Operational IDs regenerated in isolated ranges", "result": "PASS"},
                {"statement": "Every receipt has migration identity provenance", "result": "PASS"},
                {"statement": "Every issue has reconciliation and allocation", "result": "PASS"},
                {"statement": "Deliveries/legacy/work logs/daily reports not copied", "result": "PASS"},
            ],
        ),
        "TABLE_COUNTS": _text_rows(
            connection,
            """SELECT source_table, before_count, after_count, result, details
                 FROM migration_full_cleanliness
                WHERE check_kind='OPERATIONAL_TABLE' ORDER BY id""",
        ),
        "PRESERVED_TABLES": _text_rows(
            connection,
            """SELECT source_table, before_count, after_count, result, details
                 FROM migration_full_cleanliness
                WHERE check_kind='PRESERVED_SYSTEM_TABLE' ORDER BY id""",
        ),
        "EXCLUDED_TEST_SERIALS": _text_rows(
            connection,
            """SELECT source_table, source_id, source_serial, result, details
                 FROM migration_full_cleanliness
                WHERE check_kind='EXCLUDED_TEST_SERIAL' ORDER BY source_table, source_id""",
        ),
        "EXCLUDED_SOURCE_IDS": _text_rows(
            connection,
            """SELECT source_table, source_id, result, details
                 FROM migration_full_cleanliness
                WHERE check_kind='EXCLUDED_SOURCE_IDS' ORDER BY source_table""",
        ),
        "ALL_EVIDENCE": all_rows,
    }


def _write_cleanliness_markdown(path: Path, connection: sqlite3.Connection) -> None:
    operational = list(connection.execute(
        """SELECT source_table, before_count, after_count
             FROM migration_full_cleanliness
            WHERE check_kind='OPERATIONAL_TABLE' ORDER BY id"""
    ))
    serials = list(connection.execute(
        """SELECT source_table, source_id, source_serial
             FROM migration_full_cleanliness
            WHERE check_kind='EXCLUDED_TEST_SERIAL'
            ORDER BY source_table, source_id"""
    ))
    lines = [
        "# Full Warehouse Operational Cleanliness",
        "",
        "The full candidate was copied from the clean Stage 0.13.3A candidate, "
        "not continued from the operational contents of `data/warehouse.db`.",
        "",
        "## Operational table counts",
        "",
        "| Table | Before historical import | After historical import |",
        "|---|---:|---:|",
    ]
    lines.extend(
        f"| {row['source_table']} | {row['before_count']} | {row['after_count']} |"
        for row in operational
    )
    lines.extend((
        "",
        "Before-import counts are zero for every operational table. After-import "
        "non-zero rows are limited to historical receipts/states, historical issues, "
        "allocations and allowlisted migration audit events.",
        "",
        "## Excluded development/test S/N",
        "",
        "| Source table | Source ID | S/N | Candidate matches |",
        "|---|---:|---|---:|",
    ))
    lines.extend(
        f"| {row['source_table']} | {row['source_id']} | `{row['source_serial']}` | 0 |"
        for row in serials
    )
    lines.extend((
        "",
        "## Proof",
        "",
        "- Candidate receipt IDs begin above 1,000,000; issue IDs above 2,000,000; "
        "allocation IDs above 3,000,000. Source operational rows were not copied.",
        "- `deliveries`, `delivery_lines`, legacy `equipment`/`operations`, work logs "
        "and daily report tables remain empty.",
        "- Every `stock_receipts` row is referenced by exactly one "
        "`migration_full_identities` row.",
        "- Every `stock_issues` row has a `migration_full_reconciliation` row and "
        "one non-orphan allocation.",
        "- Security users were retained, but password hashes are never projected "
        "into this report or the migration review API.",
        "",
    ))
    path.write_text("\n".join(lines), encoding="utf-8")


def write_full_reports(
    database: Path,
    report_xlsx: Path,
    report_markdown: Path,
    cleanliness_xlsx: Path,
    cleanliness_markdown: Path,
    validation: Mapping[str, Any],
) -> None:
    with closing(connect_readonly(database)) as connection:
        main_sheets = _report_sheets(connection, validation)
        write_text_xlsx(
            report_xlsx,
            main_sheets,
            identifier_columns={name: headers for name, (headers, _) in main_sheets.items()},
        )
        _write_main_markdown(report_markdown, validation)
        clean_sheets = _cleanliness_sheets(connection)
        write_text_xlsx(
            cleanliness_xlsx,
            clean_sheets,
            identifier_columns={name: headers for name, (headers, _) in clean_sheets.items()},
        )
        _write_cleanliness_markdown(cleanliness_markdown, connection)
    for output in (
        report_xlsx, report_markdown, cleanliness_xlsx, cleanliness_markdown
    ):
        if os.name == "posix":
            output.chmod(0o600)


def _fsync_file_and_parent(path: Path) -> None:
    with path.open("r+b") as stream:
        os.fsync(stream.fileno())
    if hasattr(os, "O_DIRECTORY"):
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def build_full_candidate(
    paths: FullPaths,
    hooks: FullRuntimeHooks,
    *,
    overwrite: bool = False,
) -> FullBuildResult:
    """Atomically build DB and reports while proving all sources unchanged."""

    assert_safe_full_paths(paths)
    outputs = (
        paths.full_db,
        paths.report_xlsx,
        paths.report_markdown,
        paths.cleanliness_xlsx,
        paths.cleanliness_markdown,
    )
    existing = [path for path in outputs if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "full candidate output exists; use --overwrite: "
            + ", ".join(_portable(path) for path in existing)
        )
    for output in outputs:
        output.parent.mkdir(parents=True, exist_ok=True)

    total_started = perf_counter()
    raw_before = _raw_hashes(paths.raw_dir)
    production_before = source_content_state(paths.production_db)
    candidate_before = source_content_state(paths.source_candidate)
    production_safety = assert_source_database_safe(paths.production_db)
    source_validation = validate_candidate(paths.source_candidate)
    if source_validation["staging_rows"] != EXPECTED_TOTAL_ROWS:
        raise RuntimeError("Stage A source candidate row count changed")
    if any(source_validation["operational_rows"].values()):
        raise RuntimeError("Stage A source candidate is not operationally clean")
    production = _production_snapshot(paths.production_db)
    source_candidate_sha = sha256_file(paths.source_candidate)
    production_sha = sha256_file(paths.production_db)

    with tempfile.TemporaryDirectory(
        prefix=".ode-full-warehouse.", dir=paths.full_db.parent
    ) as temporary_directory:
        temporary_root = Path(temporary_directory)
        temporary_db = temporary_root / paths.full_db.name
        temporary_report_xlsx = temporary_root / paths.report_xlsx.name
        temporary_report_md = temporary_root / paths.report_markdown.name
        temporary_clean_xlsx = temporary_root / paths.cleanliness_xlsx.name
        temporary_clean_md = temporary_root / paths.cleanliness_markdown.name

        build_details = _create_full_file(
            temporary_db,
            paths,
            hooks,
            production,
            source_candidate_sha=source_candidate_sha,
            production_sha=production_sha,
            raw_hashes=raw_before,
        )
        validation = validate_full_database(
            temporary_db, production_db=paths.production_db
        )
        report_started = perf_counter()
        write_full_reports(
            temporary_db,
            temporary_report_xlsx,
            temporary_report_md,
            temporary_clean_xlsx,
            temporary_clean_md,
            validation,
        )
        report_ms = (perf_counter() - report_started) * 1000
        total_ms = (perf_counter() - total_started) * 1000
        with closing(sqlite3.connect(temporary_db)) as connection:
            measured_at = str(connection.execute(
                "SELECT built_at FROM migration_full_marker"
            ).fetchone()[0])
            connection.executemany(
                """INSERT INTO migration_full_performance(
                       metric, duration_ms, details, measured_at
                   ) VALUES (?,?,?,?)""",
                (
                    (
                        "report_generation",
                        f"{report_ms:.3f}",
                        _json({"artifacts": 4}),
                        measured_at,
                    ),
                    (
                        "total_build",
                        f"{total_ms:.3f}",
                        _json({"scope": "DB plus initial reports"}),
                        measured_at,
                    ),
                    (
                        "database_size_bytes",
                        "0.000",
                        _json({"bytes": temporary_db.stat().st_size}),
                        measured_at,
                    ),
                ),
            )
            connection.commit()
        validation = validate_full_database(
            temporary_db, production_db=paths.production_db
        )
        # Regenerate so PERFORMANCE and the final DB size are present in XLSX.
        write_full_reports(
            temporary_db,
            temporary_report_xlsx,
            temporary_report_md,
            temporary_clean_xlsx,
            temporary_clean_md,
            validation,
        )
        reconciliation_sheet = read_text_xlsx(
            temporary_report_xlsx,
            sheet_names={"SOURCE_ROW_RECONCILIATION"},
        ).get("SOURCE_ROW_RECONCILIATION", [])
        if len(reconciliation_sheet) != EXPECTED_TOTAL_ROWS:
            raise RuntimeError(
                "XLSX source reconciliation count does not match processed rows"
            )

        raw_after = _raw_hashes(paths.raw_dir)
        production_after = source_content_state(paths.production_db)
        candidate_after = source_content_state(paths.source_candidate)
        if raw_after != raw_before:
            raise RuntimeError("raw source SHA changed during full build")
        if production_after != production_before:
            raise RuntimeError("data/warehouse.db changed during full build")
        if candidate_after != candidate_before:
            raise RuntimeError("Stage A source candidate changed during full build")
        assert_source_database_safe(paths.production_db)
        for artifact in (
            temporary_db,
            temporary_report_xlsx,
            temporary_report_md,
            temporary_clean_xlsx,
            temporary_clean_md,
        ):
            _fsync_file_and_parent(artifact)

        # Reports are derivative evidence; the validated DB is the final marker.
        os.replace(temporary_report_xlsx, paths.report_xlsx)
        os.replace(temporary_report_md, paths.report_markdown)
        os.replace(temporary_clean_xlsx, paths.cleanliness_xlsx)
        os.replace(temporary_clean_md, paths.cleanliness_markdown)
        os.replace(temporary_db, paths.full_db)
        for output in outputs:
            _fsync_file_and_parent(output)

    final_validation = validate_full_database(
        paths.full_db, production_db=paths.production_db
    )
    report = {
        **final_validation,
        **build_details,
        "database_path": _portable(paths.full_db),
        "report_xlsx": _portable(paths.report_xlsx),
        "report_markdown": _portable(paths.report_markdown),
        "cleanliness_xlsx": _portable(paths.cleanliness_xlsx),
        "cleanliness_markdown": _portable(paths.cleanliness_markdown),
        "source_candidate_sha256": source_candidate_sha,
        "production_database_sha_before": production_sha,
        "production_database_sha_after": sha256_file(paths.production_db),
        "production_database_unchanged": True,
        "raw_hashes_before": raw_before,
        "raw_hashes_after": raw_after,
        "raw_hashes_unchanged": True,
        "source_candidate_unchanged": True,
        "source_candidate_validation": source_validation,
        "production_safety": production_safety,
        "report_reconciliation_rows": EXPECTED_TOTAL_ROWS,
        "build_rule_version": BUILD_RULE_VERSION,
    }
    return FullBuildResult(report=report)


__all__ = [
    "DEFAULT_CLEANLINESS_MARKDOWN",
    "DEFAULT_CLEANLINESS_XLSX",
    "DEFAULT_FULL_DB",
    "DEFAULT_REPORT_MARKDOWN",
    "DEFAULT_REPORT_XLSX",
    "DEFAULT_SERIAL_REVIEW",
    "DEFAULT_SOURCE_CANDIDATE",
    "DEFAULT_SOURCE_WORKBOOK",
    "FullBuildResult",
    "FullPaths",
    "FullRuntimeHooks",
    "assert_safe_full_paths",
    "build_full_candidate",
    "default_full_paths",
    "validate_full_database",
    "write_full_reports",
]
