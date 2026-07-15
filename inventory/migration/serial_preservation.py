"""Lossless S/N extraction and match-only normalization for migration staging."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
import re
import unicodedata
from typing import Iterable, Sequence

from .xlsx_cells import XlsxCell, iter_xlsx_cells


MATCH_NORMALIZATION_RULE = (
    "UNICODE_NFKC+REMOVE_EXTERNAL_WHITESPACE_OR_FORMAT_CONTROLS+CASEFOLD"
)
MAX_PROVABLE_EXCEL_NUMERIC_DIGITS = 15
PURE_ZERO_FORMAT_RE = re.compile(r"0+")
EXPONENT_TOKEN_RE = re.compile(r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)[Ee][+-]?[0-9]+$")


class PreservationStatus(str, Enum):
    EMPTY = "EMPTY"
    TEXT_EXACT = "TEXT_EXACT"
    NUMERIC_FORMAT_RECOVERED = "NUMERIC_FORMAT_RECOVERED"
    NUMERIC_FORMAT_UNPROVEN = "NUMERIC_FORMAT_UNPROVEN"
    FORMULA_UNSAFE = "FORMULA_UNSAFE"
    SOURCE_CORRUPTED = "SOURCE_CORRUPTED"
    UNSUPPORTED_CELL_TYPE = "UNSUPPORTED_CELL_TYPE"


@dataclass(frozen=True)
class SerialColumnSpec:
    """A worksheet column that contains S/N values for one operation role."""

    source_sheet: str
    source_column: str
    operation_kind: str
    first_row: int = 1
    last_row: int | None = None


@dataclass(frozen=True)
class SerialPreservationRecord:
    """Source-exact S/N plus a separate, non-authoritative match key."""

    source_file: str
    source_sheet: str
    source_row: int
    source_column: str
    excel_cell_coordinate: str
    excel_cell_type: str
    excel_number_format: str
    raw_xml_value: str
    source_display_value: str
    source_serial_value: str
    normalized_match_value: str
    preservation_status: str
    warning: str
    source_hash: str
    normalization_rule: str
    confidence: str
    requires_manual_review: bool
    operation_kind: str
    source_file_hash: str


def normalize_serial_match(value: str) -> str:
    """Build a match key without changing any internal S/N character.

    NFKC and casefold are intentionally the only transformations of retained
    characters.  Whitespace and Unicode format controls are removed only while
    they are at either outer edge.  Internal spaces, dashes, script and leading
    zeroes remain significant.
    """
    if not isinstance(value, str):
        raise TypeError("Serial number must be str")
    normalized = unicodedata.normalize("NFKC", value)
    start = 0
    end = len(normalized)
    while start < end and _is_external_ignorable(normalized[start]):
        start += 1
    while end > start and _is_external_ignorable(normalized[end - 1]):
        end -= 1
    return normalized[start:end].casefold()


def preserve_serial_cell(
    cell: XlsxCell,
    *,
    operation_kind: str = "",
) -> SerialPreservationRecord:
    """Classify one OOXML cell without using ``float`` or guessing digits."""
    if cell.has_formula:
        return _record(
            cell,
            operation_kind=operation_kind,
            source_display_value=cell.source_display_value,
            source_serial_value=cell.source_display_value,
            normalized_match_value="",
            status=PreservationStatus.FORMULA_UNSAFE,
            warnings=("FORMULA_CELL_NOT_AUTHORITATIVE",),
            rule="NONE_FORMULA_CELL",
            confidence="NONE",
            manual=True,
        )

    if cell.excel_cell_type in {"s", "inlineStr"}:
        return _preserve_text(cell, operation_kind)
    if cell.excel_cell_type == "n":
        return _preserve_numeric(cell, operation_kind)
    if not cell.raw_xml_value and not cell.source_display_value:
        return _record(
            cell,
            operation_kind=operation_kind,
            source_display_value="",
            source_serial_value="",
            normalized_match_value="",
            status=PreservationStatus.EMPTY,
            warnings=(),
            rule="NONE_EMPTY_CELL",
            confidence="NONE",
            manual=False,
        )
    return _record(
        cell,
        operation_kind=operation_kind,
        source_display_value=cell.source_display_value,
        source_serial_value=cell.source_display_value,
        normalized_match_value="",
        status=PreservationStatus.UNSUPPORTED_CELL_TYPE,
        warnings=(f"UNSUPPORTED_CELL_TYPE:{cell.excel_cell_type}",),
        rule="NONE_UNSUPPORTED_CELL_TYPE",
        confidence="NONE",
        manual=True,
    )


def extract_serial_cells(
    path: str | Path,
    specs: Iterable[
        SerialColumnSpec
        | tuple[str, str, str]
        | tuple[str, str, str, int]
        | tuple[str, str, str, int, int | None]
    ],
) -> list[SerialPreservationRecord]:
    """Extract selected serial columns and attach their operation kind."""
    normalized_specs = [_coerce_spec(spec) for spec in specs]
    if not normalized_specs:
        return []
    by_coordinate: dict[tuple[str, str], SerialColumnSpec] = {}
    for spec in normalized_specs:
        column = spec.source_column.strip().upper()
        key = (spec.source_sheet, column)
        if key in by_coordinate:
            raise ValueError(f"Duplicate serial column specification: {key}")
        if spec.first_row < 1:
            raise ValueError("first_row must be positive")
        if spec.last_row is not None and spec.last_row < spec.first_row:
            raise ValueError("last_row must not precede first_row")
        by_coordinate[key] = SerialColumnSpec(
            spec.source_sheet,
            column,
            spec.operation_kind,
            spec.first_row,
            spec.last_row,
        )

    columns: dict[str, set[str]] = {}
    for sheet_name, column in by_coordinate:
        columns.setdefault(sheet_name, set()).add(column)
    result: list[SerialPreservationRecord] = []
    for cell in iter_xlsx_cells(
        path,
        sheet_names=columns,
        columns=columns,
    ):
        spec = by_coordinate[(cell.source_sheet, cell.source_column)]
        if cell.source_row < spec.first_row:
            continue
        if spec.last_row is not None and cell.source_row > spec.last_row:
            continue
        result.append(
            preserve_serial_cell(cell, operation_kind=spec.operation_kind)
        )
    return result


def _preserve_text(
    cell: XlsxCell,
    operation_kind: str,
) -> SerialPreservationRecord:
    source = cell.source_display_value
    match_value = normalize_serial_match(source)
    warnings: list[str] = []
    nfkc = unicodedata.normalize("NFKC", source)
    if nfkc != source:
        warnings.append("UNICODE_NFKC_MATCH_ONLY")
    if _has_external_whitespace(source):
        warnings.append("EXTERNAL_WHITESPACE_REMOVED_FOR_MATCH_ONLY")
    if _has_external_format_control(nfkc):
        warnings.append("EXTERNAL_INVISIBLE_REMOVED_FOR_MATCH_ONLY")
    retained = _trim_external_ignorables(nfkc)
    if any(character.isspace() for character in retained):
        warnings.append("INTERNAL_WHITESPACE_PRESERVED")
    if _contains_latin_and_cyrillic(retained):
        warnings.append("MIXED_LATIN_CYRILLIC_PRESERVED")
    if EXPONENT_TOKEN_RE.fullmatch(retained):
        warnings.append("SCIENTIFIC_LOOKING_TEXT_PRESERVED_AS_TEXT")
    if not match_value:
        return _record(
            cell,
            operation_kind=operation_kind,
            source_display_value=source,
            source_serial_value=source,
            normalized_match_value="",
            status=PreservationStatus.EMPTY,
            warnings=tuple(warnings) + ("NO_MATCHABLE_CHARACTERS",),
            rule=MATCH_NORMALIZATION_RULE,
            confidence="NONE",
            manual=bool(source),
        )
    manual = any(
        warning in {
            "INTERNAL_WHITESPACE_PRESERVED",
            "MIXED_LATIN_CYRILLIC_PRESERVED",
            "SCIENTIFIC_LOOKING_TEXT_PRESERVED_AS_TEXT",
        }
        for warning in warnings
    )
    return _record(
        cell,
        operation_kind=operation_kind,
        source_display_value=source,
        source_serial_value=source,
        normalized_match_value=match_value,
        status=PreservationStatus.TEXT_EXACT,
        warnings=warnings,
        rule=MATCH_NORMALIZATION_RULE,
        confidence="HIGH",
        manual=manual,
    )


def _preserve_numeric(
    cell: XlsxCell,
    operation_kind: str,
) -> SerialPreservationRecord:
    raw = cell.raw_xml_value
    if not raw:
        return _record(
            cell,
            operation_kind=operation_kind,
            source_display_value="",
            source_serial_value="",
            normalized_match_value="",
            status=PreservationStatus.EMPTY,
            warnings=(),
            rule="NONE_EMPTY_CELL",
            confidence="NONE",
            manual=False,
        )
    try:
        numeric = Decimal(raw)
    except InvalidOperation:
        return _corrupted_numeric(
            cell,
            operation_kind,
            source_display_value=raw,
            warning="INVALID_NUMERIC_XML_TOKEN",
        )
    if not numeric.is_finite():
        return _corrupted_numeric(
            cell,
            operation_kind,
            source_display_value=raw,
            warning="NON_FINITE_NUMERIC_IDENTIFIER",
        )
    if numeric != numeric.to_integral_value():
        return _corrupted_numeric(
            cell,
            operation_kind,
            source_display_value=format(numeric, "f"),
            warning="FRACTIONAL_NUMERIC_IDENTIFIER",
        )

    plain = format(numeric, "f").split(".", 1)[0]
    signless = plain.lstrip("-")
    significant_digits = len(signless.lstrip("0") or "0")
    warnings = ["NUMERIC_SOURCE_CELL"]
    is_exponent_token = bool(EXPONENT_TOKEN_RE.fullmatch(raw))
    if is_exponent_token:
        warnings.append("SCIENTIFIC_XML_TOKEN_EXPANDED_WITH_DECIMAL")
    if plain.startswith("-"):
        return _corrupted_numeric(
            cell,
            operation_kind,
            source_display_value=plain,
            warning="NEGATIVE_NUMERIC_IDENTIFIER",
            extra_warnings=warnings,
        )
    if significant_digits > MAX_PROVABLE_EXCEL_NUMERIC_DIGITS:
        return _corrupted_numeric(
            cell,
            operation_kind,
            source_display_value=plain,
            warning="EXCEL_NUMERIC_PRECISION_NOT_PROVABLE",
            extra_warnings=warnings,
        )

    number_format = cell.excel_number_format
    formatted_display = plain
    if len(number_format) > 1 and PURE_ZERO_FORMAT_RE.fullmatch(number_format):
        formatted_display = signless.zfill(len(number_format))

    if is_exponent_token:
        warnings.extend((
            "RAW_EXPONENT_TOKEN_PRESERVED_WITHOUT_AUTOMATIC_MATCH",
            "PRIOR_IDENTIFIER_CHARACTERS_NOT_PROVABLE",
        ))
        return _record(
            cell,
            operation_kind=operation_kind,
            source_display_value=formatted_display,
            source_serial_value=raw,
            normalized_match_value="",
            status=PreservationStatus.NUMERIC_FORMAT_UNPROVEN,
            warnings=warnings,
            rule="PRESERVE_RAW_EXPONENT_TOKEN;DECIMAL_DISPLAY_FOR_REVIEW_ONLY;NO_MATCH",
            confidence="LOW",
            manual=True,
        )

    if len(number_format) > 1 and PURE_ZERO_FORMAT_RE.fullmatch(number_format):
        display = formatted_display
        warnings.append("CUSTOM_ZERO_FORMAT_APPLIED")
        if len(number_format) > len(signless):
            warnings.append("LEADING_ZEROS_RECOVERED_FROM_NUMBER_FORMAT")
        # Even an unambiguous format-based reconstruction is presented for
        # review; the source bytes and rule make the decision reproducible.
        return _record(
            cell,
            operation_kind=operation_kind,
            source_display_value=display,
            source_serial_value=display,
            normalized_match_value="",
            status=PreservationStatus.NUMERIC_FORMAT_RECOVERED,
            warnings=warnings,
            rule=f"DECIMAL_INTEGER+CUSTOM_ZERO_FORMAT:{number_format};NO_MATCH_BEFORE_APPROVAL",
            confidence="HIGH",
            manual=True,
        )

    if re.fullmatch(r"\+?0[0-9]+", raw):
        warnings.append("NUMERIC_XML_TOKEN_HAS_UNFORMATTED_LEADING_ZEROS")
        return _record(
            cell,
            operation_kind=operation_kind,
            source_display_value=plain,
            source_serial_value=raw.removeprefix("+"),
            normalized_match_value="",
            status=PreservationStatus.NUMERIC_FORMAT_UNPROVEN,
            warnings=warnings,
            rule="PRESERVE_RAW_TOKEN;NO_MATCH_WITHOUT_DISPLAY_FORMAT_PROOF",
            confidence="LOW",
            manual=True,
        )

    if number_format not in {"General", "0", "@"}:
        warnings.append(f"UNSUPPORTED_NUMERIC_FORMAT:{number_format}")
        return _record(
            cell,
            operation_kind=operation_kind,
            source_display_value=cell.source_display_value or plain,
            source_serial_value=raw,
            normalized_match_value="",
            status=PreservationStatus.NUMERIC_FORMAT_UNPROVEN,
            warnings=warnings,
            rule="DECIMAL_INTEGER_ONLY;NO_MATCH_UNPROVEN_DISPLAY_FORMAT",
            confidence="LOW",
            manual=True,
        )

    if number_format == "@":
        warnings.append("NUMERIC_CELL_WITH_TEXT_NUMBER_FORMAT")
    warnings.extend((
        "NUMERIC_IDENTIFIER_REQUIRES_APPROVAL",
        "PRIOR_LEADING_ZERO_HISTORY_NOT_PROVABLE",
    ))
    return _record(
        cell,
        operation_kind=operation_kind,
        source_display_value=plain,
        source_serial_value=raw,
        normalized_match_value="",
        status=PreservationStatus.NUMERIC_FORMAT_UNPROVEN,
        warnings=warnings,
        rule="PRESERVE_RAW_NUMERIC_TOKEN;DECIMAL_DISPLAY_FOR_REVIEW_ONLY;NO_MATCH",
        confidence="LOW",
        manual=True,
    )


def _corrupted_numeric(
    cell: XlsxCell,
    operation_kind: str,
    *,
    source_display_value: str,
    warning: str,
    extra_warnings: Sequence[str] = (),
) -> SerialPreservationRecord:
    return _record(
        cell,
        operation_kind=operation_kind,
        source_display_value=source_display_value,
        # Keep the exact storage token; it is not a claim about the identifier
        # before Excel altered or reformatted it.
        source_serial_value=cell.raw_xml_value or source_display_value,
        normalized_match_value="",
        status=PreservationStatus.SOURCE_CORRUPTED,
        warnings=tuple(extra_warnings) + (warning,),
        rule="NONE_SOURCE_PRECISION_OR_TYPE_NOT_PROVABLE",
        confidence="NONE",
        manual=True,
    )


def _record(
    cell: XlsxCell,
    *,
    operation_kind: str,
    source_display_value: str,
    source_serial_value: str,
    normalized_match_value: str,
    status: PreservationStatus,
    warnings: Sequence[str],
    rule: str,
    confidence: str,
    manual: bool,
) -> SerialPreservationRecord:
    return SerialPreservationRecord(
        source_file=cell.source_file,
        source_sheet=cell.source_sheet,
        source_row=cell.source_row,
        source_column=cell.source_column,
        excel_cell_coordinate=cell.excel_cell_coordinate,
        excel_cell_type=cell.excel_cell_type,
        excel_number_format=cell.excel_number_format,
        raw_xml_value=cell.raw_xml_value,
        source_display_value=source_display_value,
        source_serial_value=source_serial_value,
        normalized_match_value=normalized_match_value,
        preservation_status=status.value,
        warning=";".join(warnings),
        source_hash=cell.source_hash,
        normalization_rule=rule,
        confidence=confidence,
        requires_manual_review=manual,
        operation_kind=operation_kind,
        source_file_hash=cell.source_file_hash,
    )


def _coerce_spec(
    spec: SerialColumnSpec
    | tuple[str, str, str]
    | tuple[str, str, str, int]
    | tuple[str, str, str, int, int | None],
) -> SerialColumnSpec:
    if isinstance(spec, SerialColumnSpec):
        return spec
    if len(spec) == 3:
        return SerialColumnSpec(*spec)
    if len(spec) == 4:
        return SerialColumnSpec(*spec)
    if len(spec) == 5:
        return SerialColumnSpec(*spec)
    raise ValueError("Serial column spec must have 3, 4 or 5 values")


def _is_external_ignorable(character: str) -> bool:
    return character.isspace() or unicodedata.category(character) == "Cf"


def _trim_external_ignorables(value: str) -> str:
    start = 0
    end = len(value)
    while start < end and _is_external_ignorable(value[start]):
        start += 1
    while end > start and _is_external_ignorable(value[end - 1]):
        end -= 1
    return value[start:end]


def _has_external_whitespace(value: str) -> bool:
    return any(character.isspace() for character in _removed_external_characters(value))


def _has_external_format_control(value: str) -> bool:
    return any(
        unicodedata.category(character) == "Cf"
        for character in _removed_external_characters(value)
    )


def _removed_external_characters(value: str) -> str:
    start = 0
    end = len(value)
    while start < end and _is_external_ignorable(value[start]):
        start += 1
    while end > start and _is_external_ignorable(value[end - 1]):
        end -= 1
    return value[:start] + value[end:]


def _contains_latin_and_cyrillic(value: str) -> bool:
    has_latin = False
    has_cyrillic = False
    for character in value:
        name = unicodedata.name(character, "")
        has_latin = has_latin or "LATIN" in name
        has_cyrillic = has_cyrillic or "CYRILLIC" in name
    return has_latin and has_cyrillic
