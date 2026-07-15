"""Deterministic preservation-aware selector for the 200-row receipt pilot."""

from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Iterable, Mapping
from xml.etree import ElementTree
from zipfile import ZipFile

from .canonical_naming import build_component_name, build_equipment_name
from .pilot_models import (
    CONFLICT_HISTORY_ONLY,
    EXACT_DUPLICATE,
    IMPORT,
    MANUAL_REVIEW,
    PILOT_DECISIONS,
    PILOT_SELECTION_SEED,
    PILOT_SELECTION_SIZE,
    QUANTITY_POSITION_DEFERRED,
    QUARANTINE,
    SERIAL_REVIEW_SHA256,
    SOURCE_CORRUPTED_REJECTED,
    PilotSelection,
    PilotSelectionRow,
)
from .reference_data import normalize_reference_key
from .validation import connect_readonly, sha256_file, validate_candidate
from .xlsx_cells import MAIN_NS, XlsxCell, iter_xlsx_cells, read_text_xlsx


RECEIPT_SHEET = "ПРИХОД"
SERIAL_REVIEW_SHEET = "SERIAL_REVIEW"
SOURCE_WORKBOOK_NAME = "warehouse_accounting_source.xlsx"
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_FORMAT_TOKEN = re.compile(r"[dmy]", flags=re.IGNORECASE)


@dataclass(frozen=True)
class PreservedReceiptDate:
    iso_value: str
    raw_xml_value: str
    status: str
    excel_cell_type: str
    excel_number_format: str

    @property
    def proven(self) -> bool:
        return bool(self.iso_value)


@dataclass
class _Receipt:
    row: dict[str, Any]
    payload: dict[str, str]
    serial: dict[str, Any]
    receipt_date: PreservedReceiptDate
    review_status: str = ""
    review_flags: str = ""
    rank: str = ""
    resolved_vendor: str = ""
    resolved_model: str = ""
    resolved_supplier: str = ""
    resolved_canonical_name: str = ""
    reference_warnings: tuple[str, ...] = ()

    @property
    def id(self) -> int:
        return int(self.row["id"])

    @property
    def source_row(self) -> int:
        return int(self.row["source_row"])

    @property
    def match(self) -> str:
        return str(self.row["normalized_matching_serial"] or "")

    @property
    def serial_value(self) -> str:
        return str(self.row["source_serial_value"] or "")


def selection_rank(source_row_hash: str, *, seed: str = PILOT_SELECTION_SEED) -> str:
    return hashlib.sha256(f"{seed}\0{source_row_hash}".encode("utf-8")).hexdigest()


def _date_like_number_format(number_format: str) -> bool:
    # Remove quoted literals, escaped characters and bracketed conditions.
    cleaned = re.sub(r'"[^"]*"', "", str(number_format or ""))
    cleaned = re.sub(r"\\.", "", cleaned)
    cleaned = re.sub(r"\[[^]]*\]", "", cleaned)
    tokens = {token.casefold() for token in _DATE_FORMAT_TOKEN.findall(cleaned)}
    return "d" in tokens and ("m" in tokens or "y" in tokens)


def _workbook_uses_1904_epoch(path: Path) -> bool:
    with ZipFile(path, "r") as archive:
        root = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    properties = root.find(f"{{{MAIN_NS}}}workbookPr")
    if properties is None:
        return False
    return properties.attrib.get("date1904", "0").strip().casefold() in {
        "1", "true", "on",
    }


def parse_excel_receipt_date(
    cell: XlsxCell | None, *, uses_1904_epoch: bool = False
) -> PreservedReceiptDate:
    """Parse only dates whose raw OOXML representation proves the value."""
    if cell is None:
        return PreservedReceiptDate("", "", "MISSING_SOURCE_DATE_CELL", "", "")
    base = {
        "raw_xml_value": cell.raw_xml_value,
        "excel_cell_type": cell.excel_cell_type,
        "excel_number_format": cell.excel_number_format,
    }
    if cell.excel_cell_type == "n":
        if not _date_like_number_format(cell.excel_number_format):
            return PreservedReceiptDate(
                "", status="NUMERIC_NON_DATE_FORMAT", **base
            )
        try:
            serial = Decimal(cell.raw_xml_value)
        except InvalidOperation:
            return PreservedReceiptDate("", status="INVALID_NUMERIC_DATE_TOKEN", **base)
        if not serial.is_finite() or serial != serial.to_integral_value():
            return PreservedReceiptDate("", status="NUMERIC_DATE_NOT_WHOLE_DAY", **base)
        day = int(serial)
        if day < 1 or day > 100_000:
            return PreservedReceiptDate("", status="NUMERIC_DATE_OUT_OF_RANGE", **base)
        epoch = date(1904, 1, 1) if uses_1904_epoch else date(1899, 12, 30)
        parsed = epoch + timedelta(days=day)
        return PreservedReceiptDate(
            parsed.isoformat(),
            status=(
                "NUMERIC_DATE_EXACT_1904_EPOCH"
                if uses_1904_epoch
                else "NUMERIC_DATE_EXACT_1900_EPOCH"
            ),
            **base,
        )
    text = cell.source_display_value
    if _ISO_DATE.fullmatch(text):
        try:
            parsed = date.fromisoformat(text)
        except ValueError:
            pass
        else:
            return PreservedReceiptDate(
                parsed.isoformat(), status="TEXT_ISO_DATE_EXACT", **base
            )
    return PreservedReceiptDate("", status="SOURCE_DATE_UNPROVEN", **base)


def extract_receipt_dates(
    workbook: Path, source_rows: Iterable[int]
) -> dict[int, PreservedReceiptDate]:
    wanted = set(source_rows)
    dates: dict[int, PreservedReceiptDate] = {}
    uses_1904 = _workbook_uses_1904_epoch(workbook)
    for cell in iter_xlsx_cells(
        workbook,
        sheet_names={RECEIPT_SHEET},
        columns={RECEIPT_SHEET: {"A"}},
    ):
        if cell.source_row in wanted:
            dates[cell.source_row] = parse_excel_receipt_date(
                cell, uses_1904_epoch=uses_1904
            )
    for source_row in wanted.difference(dates):
        dates[source_row] = parse_excel_receipt_date(None)
    return dates


def _json_object(value: str) -> dict[str, str]:
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        raise RuntimeError("staging payload must be a JSON object")
    return {str(key): "" if item is None else str(item) for key, item in decoded.items()}


def _quantity_is_one(receipt: _Receipt) -> bool:
    try:
        return Decimal(receipt.payload.get("quantity", "")) == Decimal("1")
    except InvalidOperation:
        return False


def _safe_text(receipt: _Receipt) -> bool:
    return (
        receipt.row["serial_preservation_status"] == "TEXT_EXACT"
        and bool(receipt.match)
        and receipt.review_status != "NOT_A_SERIAL"
        and receipt.row["resolution_status"] != "MANUAL_REVIEW"
    )


def _import_eligible(receipt: _Receipt) -> bool:
    return (
        _safe_text(receipt)
        and _quantity_is_one(receipt)
        and not receipt.reference_warnings
        and bool(receipt.resolved_canonical_name)
        and receipt.receipt_date.proven
    )


def _value(receipt: _Receipt, field: str) -> str:
    if field == "vendor":
        return receipt.resolved_vendor or str(receipt.row["proposed_vendor"] or "")
    if field == "model":
        return receipt.resolved_model or str(receipt.row["proposed_model"] or "")
    return receipt.payload.get(field, "")


def _variants(group: Iterable[_Receipt], field: str) -> set[str]:
    return {
        normalize_reference_key(_value(receipt, field))
        for receipt in group
        if _value(receipt, field).strip()
    }


def _conflict_types(group: list[_Receipt]) -> tuple[str, ...]:
    result: list[str] = []
    for field, code in (
        ("vendor", "VENDOR_CONFLICT"),
        ("model", "MODEL_CONFLICT"),
        ("source_item_name", "ITEM_NAME_CONFLICT"),
    ):
        if len(_variants(group, field)) > 1:
            result.append(code)
    if len(_variants(group, "warehouse_location")) > 1:
        result.append("MULTIPLE_SHELVES_HISTORY")
    return tuple(result)


def _has_identity_conflict(group: list[_Receipt]) -> bool:
    return bool(
        set(_conflict_types(group)).intersection(
            {"VENDOR_CONFLICT", "MODEL_CONFLICT", "ITEM_NAME_CONFLICT"}
        )
    )


def _exact_duplicate_group(group: list[_Receipt]) -> bool:
    return (
        len({str(receipt.row["raw_payload"]) for receipt in group}) == 1
        and len({receipt.serial_value for receipt in group}) == 1
    )


def _history_variation_types(group: list[_Receipt]) -> tuple[str, ...]:
    result: list[str] = []
    for field, code in (
        ("receipt_date", "RECEIPT_DATE_VARIATION"),
        ("warehouse_location", "SHELF_VARIATION"),
        ("supplier", "SUPPLIER_VARIATION"),
        ("order_number", "ORDER_VARIATION"),
        ("request_number", "REQUEST_VARIATION"),
        ("plu", "PLU_VARIATION"),
        ("responsible", "RESPONSIBLE_VARIATION"),
        ("part_number", "PART_NUMBER_VARIATION"),
        ("quantity", "QUANTITY_VARIATION"),
    ):
        if len({receipt.payload.get(field, "") for receipt in group}) > 1:
            result.append(code)
    if len({str(receipt.row["raw_payload"]) for receipt in group}) > 1:
        result.append("RAW_PAYLOAD_VARIATION")
    return tuple(result)


def _ordinary(receipt: _Receipt, groups: Mapping[str, list[_Receipt]]) -> bool:
    return bool(
        _import_eligible(receipt)
        and receipt.row["warnings"] == "[]"
        and len(groups[receipt.match]) == 1
        and receipt.row["proposed_object_kind"]
        and receipt.resolved_canonical_name
    )


def _ranked(receipts: Iterable[_Receipt]) -> list[_Receipt]:
    return sorted(receipts, key=lambda item: (item.rank, item.source_row, item.id))


def _group_rank(group: list[_Receipt]) -> tuple[str, int]:
    return min(item.rank for item in group), group[0].source_row


def _load_receipts(
    source_candidate: Path,
    dates: Mapping[int, PreservedReceiptDate],
    review: Mapping[tuple[str, int], Mapping[str, str]],
) -> tuple[list[_Receipt], str]:
    with closing(connect_readonly(source_candidate)) as connection:
        batch = connection.execute(
            "SELECT id, source_manifest_sha256 FROM migration_batches "
            "WHERE stage='0.13.3A' AND status='REVIEW_REQUIRED'"
        ).fetchone()
        if batch is None:
            raise RuntimeError("source candidate is not Stage 0.13.3A REVIEW_REQUIRED")
        alias_maps: dict[str, dict[str, tuple[str, str]]] = {
            "vendor": {}, "supplier": {}, "model": {},
        }
        for alias in connection.execute(
            """SELECT d.domain_key, a.normalized_source_key,
                      v.display_name, v.scope_key
                 FROM reference_aliases_v2 a
                 JOIN reference_domains_v2 d ON d.id=a.domain_id
                 JOIN reference_values_v2 v ON v.id=a.canonical_id
                WHERE d.domain_key IN ('vendor', 'supplier', 'model')
                  AND a.resolution_status IN ('AUTO_APPROVED', 'APPROVED')
                ORDER BY d.domain_key, a.normalized_source_key, v.scope_key"""
        ):
            domain = str(alias["domain_key"])
            source_key = str(alias["normalized_source_key"])
            scope = str(alias["scope_key"] or "")
            map_key = f"{scope}\x1f{source_key}" if domain == "model" else source_key
            resolved = (str(alias["display_name"]), scope)
            existing = alias_maps[domain].get(map_key)
            if existing is not None and existing != resolved:
                raise RuntimeError(f"ambiguous approved {domain} alias: {source_key}")
            alias_maps[domain][map_key] = resolved
        cursor = connection.execute(
            """SELECT s.*, f.file_name,
                      c.excel_cell_type, c.excel_number_format,
                      c.raw_xml_value AS serial_raw_xml_value,
                      c.source_display_value AS serial_source_display_value,
                      c.source_hash AS serial_source_hash,
                      c.warning AS serial_warning
                 FROM migration_staging_rows s
                 JOIN migration_source_files f ON f.id=s.source_file_id
                 LEFT JOIN migration_serial_cells c
                   ON c.staging_row_id=s.id AND c.serial_role='SOURCE_SERIAL'
                WHERE s.operation_kind='RECEIPT'
                ORDER BY s.source_row, s.id"""
        )
        receipts: list[_Receipt] = []
        for sql_row in cursor:
            row = dict(sql_row)
            source_row = int(row["source_row"])
            review_row = review.get((str(row["source_sheet"]), source_row), {})
            payload = _json_object(str(row["normalized_payload"]))
            source_vendor = str(row["proposed_vendor"] or "")
            source_model = str(row["proposed_model"] or "")
            source_supplier = payload.get("supplier", "")
            reference_warnings: list[str] = []

            vendor_entry = alias_maps["vendor"].get(
                normalize_reference_key(source_vendor)
            )
            if vendor_entry is None:
                resolved_vendor = source_vendor
                reference_warnings.append(
                    "VENDOR_ALIAS_UNRESOLVED" if source_vendor else "VENDOR_NOT_PROVIDED"
                )
            else:
                resolved_vendor = vendor_entry[0]

            model_entry = alias_maps["model"].get(
                f"{normalize_reference_key(resolved_vendor)}\x1f"
                f"{normalize_reference_key(source_model)}"
            )
            if model_entry is None:
                resolved_model = source_model
                reference_warnings.append(
                    "MODEL_ALIAS_UNRESOLVED" if source_model else "MODEL_NOT_PROVIDED"
                )
            else:
                resolved_model = model_entry[0]

            supplier_entry = alias_maps["supplier"].get(
                normalize_reference_key(source_supplier)
            )
            if supplier_entry is None:
                resolved_supplier = source_supplier
                reference_warnings.append(
                    "SUPPLIER_ALIAS_UNRESOLVED"
                    if source_supplier else "SUPPLIER_NOT_PROVIDED"
                )
            else:
                resolved_supplier = supplier_entry[0]

            object_kind = str(row["proposed_object_kind"] or "")
            if object_kind == "equipment" and resolved_vendor and resolved_model:
                resolved_name = build_equipment_name(
                    str(row["proposed_equipment_type"] or "other"),
                    resolved_vendor,
                    resolved_model,
                )
            elif object_kind == "component" and resolved_vendor and (
                resolved_model or payload.get("part_number", "")
            ):
                resolved_name = build_component_name(
                    str(row["proposed_component_type"] or "other"),
                    resolved_vendor,
                    model=resolved_model,
                    part_number=payload.get("part_number", ""),
                )
            else:
                resolved_name = ""
                reference_warnings.append("CANONICAL_NAME_UNRESOLVED")
            receipts.append(
                _Receipt(
                    row=row,
                    payload=payload,
                    serial={
                        "excel_cell_type": str(row["excel_cell_type"] or ""),
                        "excel_number_format": str(row["excel_number_format"] or ""),
                        "raw_xml_value": str(row["serial_raw_xml_value"] or ""),
                        "source_display_value": str(
                            row["serial_source_display_value"] or ""
                        ),
                        "source_hash": str(row["serial_source_hash"] or ""),
                        "warning": str(row["serial_warning"] or ""),
                    },
                    receipt_date=dates[source_row],
                    review_status=str(review_row.get("status", "")),
                    review_flags=str(review_row.get("flags", "")),
                    rank=selection_rank(str(row["source_row_hash"])),
                    resolved_vendor=resolved_vendor,
                    resolved_model=resolved_model,
                    resolved_supplier=resolved_supplier,
                    resolved_canonical_name=resolved_name,
                    reference_warnings=tuple(sorted(set(reference_warnings))),
                )
            )
    return receipts, str(batch["source_manifest_sha256"])


def _review_map(path: Path, expected_sha256: str) -> tuple[dict[tuple[str, int], dict[str, str]], str]:
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise RuntimeError(
            f"serial_review.xlsx SHA mismatch: expected {expected_sha256}, got {actual}"
        )
    workbook = read_text_xlsx(path, sheet_names={SERIAL_REVIEW_SHEET})
    rows = workbook.get(SERIAL_REVIEW_SHEET)
    if rows is None:
        raise RuntimeError("serial review sheet is missing")
    result: dict[tuple[str, int], dict[str, str]] = {}
    for row in rows:
        try:
            source_row = int(row["source_row"])
        except (KeyError, ValueError) as error:
            raise RuntimeError("serial review contains an invalid source_row") from error
        key = (row.get("source_sheet", ""), source_row)
        if key in result:
            raise RuntimeError(f"duplicate serial review key: {key}")
        result[key] = row
    return result, actual


def _select(
    receipts: list[_Receipt], *, selection_size: int
) -> tuple[dict[int, _Receipt], dict[int, set[str]], dict[int, str], dict[str, list[_Receipt]]]:
    if selection_size != PILOT_SELECTION_SIZE:
        raise ValueError(f"Stage 0.13.3A.5 requires exactly {PILOT_SELECTION_SIZE} rows")
    groups: dict[str, list[_Receipt]] = defaultdict(list)
    for receipt in receipts:
        if receipt.match:
            groups[receipt.match].append(receipt)
    for group in groups.values():
        group.sort(key=lambda item: (item.source_row, item.id))

    conflict_groups = sorted(
        (
            group for group in groups.values()
            if len(group) > 1 and _has_identity_conflict(group)
            and _import_eligible(group[0])
        ),
        key=_group_rank,
    )
    exact_groups = sorted(
        (
            group for group in groups.values()
            if len(group) > 1 and _exact_duplicate_group(group)
            and any(_import_eligible(receipt) for receipt in group)
        ),
        key=_group_rank,
    )
    history_groups = sorted(
        (
            group for group in groups.values()
            if len(group) > 1
            and not _has_identity_conflict(group)
            and not _exact_duplicate_group(group)
            and _history_variation_types(group)
            and any(_import_eligible(receipt) for receipt in group)
        ),
        key=_group_rank,
    )
    if len(conflict_groups) < 26 or len(exact_groups) < 6 or len(history_groups) < 9:
        raise RuntimeError("source has insufficient eligible duplicate/conflict groups")

    selected: dict[int, _Receipt] = {}
    reasons: dict[int, set[str]] = defaultdict(set)
    decisions: dict[int, str] = {}

    def add(receipt: _Receipt, reason: str, decision: str) -> None:
        existing = decisions.get(receipt.id)
        if existing is not None and existing != decision:
            raise RuntimeError(
                f"selector assigned conflicting decisions to staging row {receipt.id}"
            )
        selected[receipt.id] = receipt
        reasons[receipt.id].add(reason)
        decisions[receipt.id] = decision

    corrupted = _ranked(
        receipt for receipt in receipts
        if receipt.row["serial_preservation_status"] == "SOURCE_CORRUPTED"
    )
    if len(corrupted) != 2:
        raise RuntimeError(f"expected 2 receipt SOURCE_CORRUPTED rows, got {len(corrupted)}")
    for receipt in corrupted:
        add(receipt, "ALL_RECEIPT_SOURCE_CORRUPTED", SOURCE_CORRUPTED_REJECTED)

    numeric = _ranked(
        receipt for receipt in receipts
        if receipt.row["serial_preservation_status"] == "NUMERIC_FORMAT_UNPROVEN"
    )[:10]
    quantity_positions = _ranked(
        receipt for receipt in receipts if receipt.review_status == "NOT_A_SERIAL"
    )[:10]
    if len(numeric) != 10 or len(quantity_positions) != 10:
        raise RuntimeError("source has insufficient numeric or quantity pilot rows")
    for receipt in numeric:
        add(receipt, "NUMERIC_MANUAL_REVIEW", QUARANTINE)
    for receipt in quantity_positions:
        add(receipt, "SERIAL_REVIEW_NOT_A_SERIAL", QUANTITY_POSITION_DEFERRED)

    r220_groups = [
        group for group in conflict_groups
        if "r220" in normalize_reference_key(group[0].resolved_model)
        and any(
            normalize_reference_key(item.resolved_vendor) in {"vegman", "yadro"}
            for item in group
        )
    ]
    multi_shelf_groups = [
        group for group in conflict_groups
        if "MULTIPLE_SHELVES_HISTORY" in _conflict_types(group)
    ]
    xfusion_groups = [
        group for group in conflict_groups
        if any(
            normalize_reference_key(item.resolved_vendor) == "xfusion"
            for item in group
        )
    ]
    if not r220_groups or not multi_shelf_groups or not xfusion_groups:
        raise RuntimeError(
            "source lacks required R220, multi-shelf or Huawei/xFusion conflict group"
        )
    chosen_conflicts: list[list[_Receipt]] = []
    for group in (
        r220_groups[0],
        multi_shelf_groups[0],
        xfusion_groups[0],
        *conflict_groups,
    ):
        if group not in chosen_conflicts:
            chosen_conflicts.append(group)
        if len(chosen_conflicts) == 26:
            break
    for group in chosen_conflicts:
        add(group[0], "CONFLICT_GROUP_PRIMARY", IMPORT)
        add(group[1], "CONFLICT_HISTORY_ROW", CONFLICT_HISTORY_ONLY)
    chosen_exact = exact_groups[:6]
    for group in chosen_exact:
        primary = next(receipt for receipt in group if _import_eligible(receipt))
        duplicate = next(receipt for receipt in group if receipt.id != primary.id)
        add(primary, "EXACT_DUPLICATE_PRIMARY", IMPORT)
        add(duplicate, "EXACT_DUPLICATE_ROW", EXACT_DUPLICATE)

    chosen_history = history_groups[:9]
    for group in chosen_history:
        primary = next(receipt for receipt in group if _import_eligible(receipt))
        history = next(receipt for receipt in group if receipt.id != primary.id)
        add(primary, "HISTORY_VARIATION_PRIMARY", IMPORT)
        add(history, "HISTORY_VARIATION_ROW", CONFLICT_HISTORY_ONLY)

    manual_candidates = _ranked(
        receipt for receipt in receipts
        if _safe_text(receipt)
        and len(groups[receipt.match]) == 1
        and (
            not receipt.row["proposed_object_kind"]
            or bool(receipt.reference_warnings)
            or not receipt.resolved_canonical_name
        )
    )[:7]
    if len(manual_candidates) != 7:
        raise RuntimeError("source lacks seven unknown-reference review rows")
    for receipt in manual_candidates:
        add(receipt, "UNKNOWN_REFERENCE_REVIEW", MANUAL_REVIEW)

    import_rows = {
        receipt.id: receipt
        for receipt in selected.values()
        if decisions[receipt.id] == IMPORT
    }

    def add_import(receipt: _Receipt, reason: str) -> None:
        if receipt.id not in selected:
            add(receipt, reason, IMPORT)
            import_rows[receipt.id] = receipt
        else:
            reasons[receipt.id].add(reason)

    unique_eligible = _ranked(
        receipt for receipt in receipts
        if _import_eligible(receipt) and len(groups[receipt.match]) == 1
    )

    named_predicates: tuple[tuple[str, Callable[[_Receipt], bool]], ...] = (
        (
            "DELL_SERVER",
            lambda receipt: normalize_reference_key(receipt.resolved_vendor)
            == "dell" and receipt.row["proposed_equipment_type"] == "server",
        ),
        (
            "HUAWEI_VENDOR",
            lambda receipt: normalize_reference_key(receipt.resolved_vendor)
            == "huawei",
        ),
        (
            "XFUSION_VENDOR",
            lambda receipt: normalize_reference_key(receipt.resolved_vendor)
            == "xfusion",
        ),
    )
    for reason, predicate in named_predicates:
        match = next(
            (receipt for receipt in selected.values() if predicate(receipt)),
            None,
        )
        if match is None:
            match = next(
                (receipt for receipt in unique_eligible if predicate(receipt)),
                None,
            )
        if match is None:
            raise RuntimeError(f"source lacks required pilot category: {reason}")
        if match.id in selected:
            reasons[match.id].add(reason)
        else:
            add_import(match, reason)

    best_by_vendor: dict[str, _Receipt] = {}
    for receipt in unique_eligible:
        vendor = normalize_reference_key(receipt.resolved_vendor)
        if vendor:
            best_by_vendor.setdefault(vendor, receipt)
    for _, receipt in sorted(
        best_by_vendor.items(), key=lambda item: (item[1].rank, item[0])
    )[:10]:
        add_import(receipt, "VENDOR_DIVERSITY")

    def fulfill(
        predicate: Callable[[_Receipt], bool],
        minimum: int,
        reason: str,
    ) -> None:
        identities = {item.match for item in import_rows.values() if predicate(item)}
        for receipt in unique_eligible:
            if len(identities) >= minimum:
                break
            if predicate(receipt) and receipt.match not in identities:
                add_import(receipt, reason)
                identities.add(receipt.match)
        if len(identities) < minimum:
            raise RuntimeError(f"pilot quota {reason} is not achievable")

    fulfill(lambda item: item.serial_value.startswith("0"), 20, "LEADING_ZERO")
    fulfill(lambda item: len(item.serial_value) > 15, 20, "LONG_TEXT_SERIAL")
    fulfill(
        lambda item: item.row["proposed_equipment_type"] == "server",
        20,
        "SERVER",
    )
    fulfill(
        lambda item: item.row["proposed_object_kind"] == "component",
        20,
        "COMPONENT",
    )
    fulfill(
        lambda item: not item.payload.get("warehouse_location", "").strip(),
        1,
        "NO_SHELF",
    )
    fulfill(lambda item: _ordinary(item, groups), 50, "ORDINARY_TEXT_EXACT")

    for receipt in unique_eligible:
        if len(import_rows) >= 130:
            break
        add_import(receipt, "DETERMINISTIC_IMPORT_FILL")
    if len(import_rows) != 130 or len(selected) != selection_size:
        raise RuntimeError(
            f"selector invariant failed: selected={len(selected)}, import={len(import_rows)}"
        )
    return selected, reasons, decisions, groups


def _warnings(receipt: _Receipt, conflict_types: tuple[str, ...]) -> tuple[str, ...]:
    result: set[str] = set()
    try:
        staged = json.loads(str(receipt.row["warnings"] or "[]"))
        if isinstance(staged, list):
            result.update(str(item) for item in staged if str(item))
    except json.JSONDecodeError:
        result.add("INVALID_STAGING_WARNING_JSON")
    result.update(
        item for item in receipt.serial.get("warning", "").split(";") if item
    )
    result.update(receipt.reference_warnings)
    result.update(conflict_types)
    if not receipt.receipt_date.proven:
        result.add("SOURCE_RECEIPT_DATE_UNPROVEN")
    if not receipt.payload.get("warehouse_location", "").strip():
        result.add("SHELF_NOT_PROVIDED")
    if (
        not receipt.row["proposed_object_kind"]
        or bool(receipt.reference_warnings)
        or not receipt.resolved_canonical_name
    ):
        result.add("REFERENCE_VALUE_UNRESOLVED")
    if receipt.review_status:
        result.add(f"SERIAL_REVIEW_{receipt.review_status}")
    return tuple(sorted(result))


def _quota_flags(
    receipt: _Receipt,
    decision: str,
    groups: Mapping[str, list[_Receipt]],
    conflict_types: tuple[str, ...],
) -> tuple[str, ...]:
    flags: set[str] = set()
    if receipt.row["serial_preservation_status"] == "TEXT_EXACT":
        flags.add("TEXT_EXACT")
    if receipt.serial_value.startswith("0"):
        flags.add("LEADING_ZERO")
    if len(receipt.serial_value) > 15:
        flags.add("LONG_TEXT_SERIAL")
    if receipt.row["proposed_equipment_type"] == "server":
        flags.add("SERVER")
    if receipt.row["proposed_object_kind"] == "component":
        flags.add("COMPONENT")
    vendor = normalize_reference_key(receipt.resolved_vendor)
    if vendor == "dell" and receipt.row["proposed_equipment_type"] == "server":
        flags.add("DELL_SERVER")
    if vendor == "huawei":
        flags.add("HUAWEI_VENDOR")
    if vendor == "xfusion":
        flags.add("XFUSION_VENDOR")
    if "r220" in normalize_reference_key(receipt.resolved_model):
        flags.add("R220_MODEL")
    if not receipt.payload.get("warehouse_location", "").strip():
        flags.add("NO_SHELF")
    if len(groups.get(receipt.match, ())) > 1:
        flags.add("DUPLICATE_SERIAL_GROUP")
    flags.update(conflict_types)
    if _ordinary(receipt, groups):
        flags.add("ORDINARY_TEXT_EXACT")
    if decision == QUARANTINE:
        flags.add("NUMERIC_MANUAL_REVIEW")
    if decision == QUANTITY_POSITION_DEFERRED:
        flags.add("QUANTITY_POSITION")
    if decision == SOURCE_CORRUPTED_REJECTED:
        flags.add("SOURCE_CORRUPTED")
    if decision == MANUAL_REVIEW:
        flags.add("UNKNOWN_REFERENCE")
    return tuple(sorted(flags))


def select_pilot_receipts(
    source_candidate: Path,
    source_workbook: Path,
    serial_review: Path,
    *,
    expected_serial_review_sha256: str = SERIAL_REVIEW_SHA256,
    selection_size: int = PILOT_SELECTION_SIZE,
) -> PilotSelection:
    """Select exactly 200 real receipt rows without writing any source file."""
    validation = validate_candidate(source_candidate)
    if validation["operational_rows"]["stock_receipts"] != 0:
        raise RuntimeError("Stage 0.13.3A source candidate already has receipts")
    review, review_sha = _review_map(
        serial_review, expected_serial_review_sha256
    )
    with closing(connect_readonly(source_candidate)) as connection:
        source_rows = [
            int(row[0])
            for row in connection.execute(
                "SELECT source_row FROM migration_staging_rows "
                "WHERE operation_kind='RECEIPT' ORDER BY source_row"
            )
        ]
        registered = connection.execute(
            "SELECT sha256 FROM migration_source_files WHERE file_name=?",
            (source_workbook.name,),
        ).fetchone()
    if registered is None or str(registered[0]) != sha256_file(source_workbook):
        raise RuntimeError("source workbook does not match candidate provenance")
    dates = extract_receipt_dates(source_workbook, source_rows)
    receipts, manifest_sha = _load_receipts(
        source_candidate, dates, review
    )
    selected, reasons, decisions, groups = _select(
        receipts, selection_size=selection_size
    )

    ordered_receipts = sorted(
        selected.values(), key=lambda item: (item.rank, item.source_row, item.id)
    )
    rows: list[PilotSelectionRow] = []
    for order, receipt in enumerate(ordered_receipts, start=1):
        group = groups.get(receipt.match, [])
        conflicts = (
            tuple(sorted(set(_conflict_types(group) + _history_variation_types(group))))
            if len(group) > 1 else ()
        )
        decision = decisions[receipt.id]
        row = PilotSelectionRow(
            selection_order=order,
            staging_row_id=receipt.id,
            migration_batch_id=int(receipt.row["batch_id"]),
            source_file=Path(str(receipt.row["file_name"])).name,
            source_sheet=str(receipt.row["source_sheet"]),
            source_row=receipt.source_row,
            source_row_hash=str(receipt.row["source_row_hash"]),
            source_serial_value=receipt.serial_value,
            normalized_match_value=receipt.match,
            serial_preservation_status=str(
                receipt.row["serial_preservation_status"]
            ),
            excel_cell_type=str(receipt.serial["excel_cell_type"]),
            excel_number_format=str(receipt.serial["excel_number_format"]),
            raw_xml_value=str(receipt.serial["raw_xml_value"]),
            source_display_value=str(receipt.serial["source_display_value"]),
            source_serial_hash=str(receipt.serial["source_hash"]),
            source_item_name=receipt.payload.get("source_item_name", ""),
            canonical_item_name=receipt.resolved_canonical_name,
            object_kind=str(receipt.row["proposed_object_kind"] or ""),
            equipment_category=str(
                receipt.row["proposed_equipment_category"] or ""
            ),
            equipment_type=str(receipt.row["proposed_equipment_type"] or ""),
            component_type=str(receipt.row["proposed_component_type"] or ""),
            vendor=receipt.resolved_vendor,
            model=receipt.resolved_model,
            part_number=receipt.payload.get("part_number", ""),
            supplier=receipt.resolved_supplier,
            # No source column is proven to be a datacenter at this stage.
            datacenter="",
            shelf=receipt.payload.get("warehouse_location", ""),
            quantity=receipt.payload.get("quantity", ""),
            source_receipt_date=receipt.receipt_date.iso_value,
            source_receipt_date_raw=receipt.receipt_date.raw_xml_value,
            source_receipt_date_status=receipt.receipt_date.status,
            source_receipt_date_cell_type=receipt.receipt_date.excel_cell_type,
            source_receipt_date_number_format=(
                receipt.receipt_date.excel_number_format
            ),
            migration_warnings=_warnings(receipt, conflicts),
            selection_reasons=tuple(sorted(reasons[receipt.id])),
            quota_flags=_quota_flags(receipt, decision, groups, conflicts),
            conflict_types=conflicts,
            duplicate_group_size=len(group),
            import_decision=decision,
            identity_key=receipt.match if decision in {
                IMPORT, EXACT_DUPLICATE, CONFLICT_HISTORY_ONLY
            } else "",
        )
        if row.import_decision == IMPORT and not row.source_receipt_date:
            raise RuntimeError("IMPORT row has no proven historical receipt date")
        rows.append(row)

    decision_counts = Counter(row.import_decision for row in rows)
    expected_decisions = {
        IMPORT: 130,
        QUARANTINE: 10,
        MANUAL_REVIEW: 7,
        EXACT_DUPLICATE: 6,
        CONFLICT_HISTORY_ONLY: 35,
        QUANTITY_POSITION_DEFERRED: 10,
        SOURCE_CORRUPTED_REJECTED: 2,
    }
    if dict(decision_counts) != expected_decisions:
        raise RuntimeError(
            "pilot decision distribution changed: "
            + json.dumps(dict(decision_counts), sort_keys=True)
        )
    quota_counts = Counter(flag for row in rows for flag in row.quota_flags)
    quota_counts["DISTINCT_VENDOR"] = len(
        {
            normalize_reference_key(row.vendor)
            for row in rows if row.vendor
        }
    )
    quota_counts["DUPLICATE_GROUP"] = len(
        {
            row.identity_key
            for row in rows
            if row.identity_key
            and "DUPLICATE_SERIAL_GROUP" in row.quota_flags
        }
    )
    quota_counts["CONFLICT_GROUP"] = len(
        {
            row.identity_key
            for row in rows
            if row.identity_key
            and set(row.conflict_types).intersection(
                {"VENDOR_CONFLICT", "MODEL_CONFLICT", "ITEM_NAME_CONFLICT"}
            )
        }
    )
    required_minimums = {
        "TEXT_EXACT": 50,
        "LEADING_ZERO": 20,
        "LONG_TEXT_SERIAL": 20,
        "SERVER": 20,
        "COMPONENT": 20,
        "DISTINCT_VENDOR": 10,
        "DUPLICATE_GROUP": 20,
        "CONFLICT_GROUP": 20,
        "NUMERIC_MANUAL_REVIEW": 10,
        "SOURCE_CORRUPTED": 2,
        "NO_SHELF": 1,
        "MULTIPLE_SHELVES_HISTORY": 2,
        "QUANTITY_POSITION": 10,
        "ORDINARY_TEXT_EXACT": 50,
        "R220_MODEL": 1,
        "DELL_SERVER": 1,
        "HUAWEI_VENDOR": 1,
        "XFUSION_VENDOR": 1,
    }
    shortfalls = {
        key: {"actual": quota_counts[key], "required": minimum}
        for key, minimum in required_minimums.items()
        if quota_counts[key] < minimum
    }
    if shortfalls:
        raise RuntimeError("pilot selection quota failure: " + json.dumps(shortfalls))

    serialized = json.dumps(
        [row.as_mapping() for row in rows],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    source_sha = sha256_file(source_candidate)
    return PilotSelection(
        rows=tuple(rows),
        decision_counts={decision: decision_counts[decision] for decision in PILOT_DECISIONS},
        quota_counts=dict(sorted(quota_counts.items())),
        selection_sha256=hashlib.sha256(serialized).hexdigest(),
        source_candidate_sha256=source_sha,
        source_manifest_sha256=manifest_sha,
        serial_review_sha256=review_sha,
        unavailable_requirements=("VEGMAN_R200_UNAVAILABLE_FROM_SOURCE",),
    )


__all__ = [
    "PreservedReceiptDate",
    "extract_receipt_dates",
    "parse_excel_receipt_date",
    "select_pilot_receipts",
    "selection_rank",
]
