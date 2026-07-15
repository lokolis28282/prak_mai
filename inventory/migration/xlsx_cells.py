"""Small, read-only OOXML cell reader and text-only XLSX writer.

The migration path deliberately does not use a spreadsheet object model.  Those
libraries commonly coerce numeric cells through ``float`` before the caller can
inspect the OOXML token.  This module keeps the token, style and provenance and
uses only the Python standard library.
"""

from __future__ import annotations

from collections import defaultdict
import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import tempfile
from typing import Any, Iterable, Iterator, Mapping, Sequence
from xml.etree import ElementTree
from xml.sax.saxutils import escape, quoteattr
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile, ZipInfo


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CELL_REFERENCE_RE = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")
INVALID_SHEET_NAME_RE = re.compile(r"[\\/*?:\[\]]")
INVALID_XML_TEXT_RE = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]"
)

# The source workbook currently expands to about 88 MiB.  The limits leave
# headroom for the real migration while rejecting accidental zip bombs.
MAX_ZIP_ENTRIES = 10_000
MAX_ZIP_ENTRY_BYTES = 256 * 1024 * 1024
MAX_ZIP_TOTAL_BYTES = 768 * 1024 * 1024


BUILTIN_NUMBER_FORMATS: dict[int, str] = {
    0: "General",
    1: "0",
    2: "0.00",
    3: "#,##0",
    4: "#,##0.00",
    9: "0%",
    10: "0.00%",
    11: "0.00E+00",
    12: "# ?/?",
    13: "# ??/??",
    14: "mm-dd-yy",
    15: "d-mmm-yy",
    16: "d-mmm",
    17: "mmm-yy",
    18: "h:mm AM/PM",
    19: "h:mm:ss AM/PM",
    20: "h:mm",
    21: "h:mm:ss",
    22: "m/d/yy h:mm",
    37: "#,##0 ;(#,##0)",
    38: "#,##0 ;[Red](#,##0)",
    39: "#,##0.00;(#,##0.00)",
    40: "#,##0.00;[Red](#,##0.00)",
    45: "mm:ss",
    46: "[h]:mm:ss",
    47: "mmss.0",
    48: "##0.0E+0",
    49: "@",
}


class XlsxFormatError(ValueError):
    """The source is not a safe, supported OOXML workbook."""


class SourceChangedError(RuntimeError):
    """The source bytes changed while they were being inspected."""


@dataclass(frozen=True)
class XlsxCell:
    """One explicit worksheet cell with its immutable-source provenance."""

    source_file: str
    source_sheet: str
    source_row: int
    source_column: str
    excel_cell_coordinate: str
    excel_cell_type: str
    excel_number_format: str
    raw_xml_value: str
    source_display_value: str
    source_hash: str
    source_file_hash: str
    style_index: int = 0
    formula: str = ""
    has_formula: bool = False


@dataclass(frozen=True)
class _WorkbookParts:
    sheets: tuple[tuple[str, str], ...]
    shared_strings_path: str | None
    styles_path: str | None


def sha256_file(path: str | Path) -> str:
    """Hash a file without loading it into memory."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def iter_xlsx_cells(
    path: str | Path,
    sheet_names: Iterable[str] | None = None,
    columns: Iterable[str] | Mapping[str, Iterable[str]] | None = None,
) -> Iterator[XlsxCell]:
    """Yield explicit cells without mutating or numerically coercing the XLSX.

    ``columns`` may be a set applied to every selected sheet or a mapping from
    sheet name to a set of column letters.  The SHA is checked again after a
    fully consumed iteration; consumers that need the immutability assertion
    must exhaust the iterator.
    """
    source_path = Path(path)
    before_hash = sha256_file(source_path)
    selected_names = None if sheet_names is None else set(sheet_names)
    column_filter = _column_filter(columns)

    try:
        with ZipFile(source_path, "r") as archive:
            _validate_archive(archive)
            parts = _workbook_parts(archive)
            available = {name for name, _ in parts.sheets}
            if selected_names is not None:
                missing = selected_names - available
                if missing:
                    raise XlsxFormatError(
                        "Worksheet(s) not found: " + ", ".join(sorted(missing))
                    )
            shared_strings = _shared_strings(archive, parts.shared_strings_path)
            number_formats = _style_number_formats(archive, parts.styles_path)

            for sheet_name, sheet_path in parts.sheets:
                if selected_names is not None and sheet_name not in selected_names:
                    continue
                wanted_columns = column_filter.get(sheet_name, column_filter.get("*"))
                with archive.open(sheet_path, "r") as stream:
                    for _, element in ElementTree.iterparse(stream, events=("end",)):
                        if element.tag != _q(MAIN_NS, "c"):
                            continue
                        coordinate = element.attrib.get("r", "")
                        match = CELL_REFERENCE_RE.fullmatch(coordinate)
                        if match is None:
                            element.clear()
                            continue
                        column, row_text = match.groups()
                        if wanted_columns is not None and column not in wanted_columns:
                            element.clear()
                            continue
                        cell_type = element.attrib.get("t", "n")
                        style_index = _non_negative_int(element.attrib.get("s", "0"))
                        number_format = (
                            number_formats[style_index]
                            if style_index < len(number_formats)
                            else "General"
                        )
                        value_element = element.find(_q(MAIN_NS, "v"))
                        formula_element = element.find(_q(MAIN_NS, "f"))
                        raw_value = (
                            (value_element.text or "")
                            if value_element is not None
                            else ""
                        )
                        formula = (
                            (formula_element.text or "")
                            if formula_element is not None
                            else ""
                        )
                        display = _cell_display_value(
                            element,
                            cell_type,
                            raw_value,
                            number_format,
                            shared_strings,
                        )
                        if cell_type == "inlineStr" and value_element is None:
                            raw_value = display
                        source_hash = _cell_source_hash(
                            before_hash,
                            sheet_name,
                            coordinate,
                            raw_value,
                        )
                        yield XlsxCell(
                            source_file=source_path.name,
                            source_sheet=sheet_name,
                            source_row=int(row_text),
                            source_column=column,
                            excel_cell_coordinate=coordinate,
                            excel_cell_type=cell_type,
                            excel_number_format=number_format,
                            raw_xml_value=raw_value,
                            source_display_value=display,
                            source_hash=source_hash,
                            source_file_hash=before_hash,
                            style_index=style_index,
                            formula=formula,
                            has_formula=formula_element is not None,
                        )
                        element.clear()
    except BadZipFile as error:
        raise XlsxFormatError(f"Not a valid XLSX/ZIP file: {source_path.name}") from error

    after_hash = sha256_file(source_path)
    if after_hash != before_hash:
        raise SourceChangedError(
            f"Source changed during extraction: {source_path.name}"
        )


def write_text_xlsx(
    path: str | Path,
    sheets: Mapping[str, Any],
    identifier_columns: Iterable[str] | Mapping[str, Iterable[str]] | None = None,
) -> Path:
    """Write a simple XLSX whose cells are inline text with number format ``@``.

    Sheet payloads may be ``(headers, rows)`` tuples or mappings with
    ``headers`` and ``rows`` keys.  Rows may be mappings or positional
    sequences.  Identifier fields reject non-string values rather than using
    ``str(value)``, which could silently preserve an already-corrupted float.
    """
    output_path = Path(path)
    prepared = _prepare_sheets(sheets, identifier_columns)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)
    try:
        with ZipFile(temporary_path, "w", compression=ZIP_DEFLATED) as archive:
            _write_zip_text(archive, "[Content_Types].xml", _content_types(len(prepared)))
            _write_zip_text(archive, "_rels/.rels", _root_relationships())
            _write_zip_text(archive, "xl/workbook.xml", _workbook_xml(prepared))
            _write_zip_text(
                archive,
                "xl/_rels/workbook.xml.rels",
                _workbook_relationships(len(prepared)),
            )
            _write_zip_text(archive, "xl/styles.xml", _text_styles_xml())
            for index, (_, headers, rows) in enumerate(prepared, start=1):
                _write_zip_text(
                    archive,
                    f"xl/worksheets/sheet{index}.xml",
                    _worksheet_xml(headers, rows),
                )
        os.replace(temporary_path, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return output_path


def read_text_xlsx(
    path: str | Path,
    sheet_names: Iterable[str] | None = None,
) -> dict[str, list[dict[str, str]]]:
    """Read text tables written by :func:`write_text_xlsx`.

    The first row is interpreted as a unique header row.  This helper is a
    round-trip verifier, not a general Excel importer.
    """
    cells_by_sheet: dict[str, dict[int, dict[int, str]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for cell in iter_xlsx_cells(path, sheet_names=sheet_names):
        cells_by_sheet[cell.source_sheet][cell.source_row][
            column_index(cell.source_column)
        ] = cell.source_display_value

    result: dict[str, list[dict[str, str]]] = {}
    for sheet_name, rows_by_number in cells_by_sheet.items():
        if not rows_by_number:
            result[sheet_name] = []
            continue
        header_values = rows_by_number[min(rows_by_number)]
        max_column = max(header_values, default=0)
        headers = [header_values.get(index, "") for index in range(1, max_column + 1)]
        if any(not header for header in headers):
            raise XlsxFormatError(f"Sheet {sheet_name!r} has an empty header")
        if len(set(headers)) != len(headers):
            raise XlsxFormatError(f"Sheet {sheet_name!r} has duplicate headers")
        table_rows: list[dict[str, str]] = []
        first_row = min(rows_by_number)
        for row_number in sorted(number for number in rows_by_number if number > first_row):
            values = rows_by_number[row_number]
            table_rows.append(
                {
                    header: values.get(index, "")
                    for index, header in enumerate(headers, start=1)
                }
            )
        result[sheet_name] = table_rows
    return result


def write_text_csv(
    path: str | Path,
    headers: Sequence[str],
    rows: Iterable[Mapping[str, Any] | Sequence[Any]],
    identifier_columns: Iterable[str] | None = None,
    *,
    delimiter: str = ";",
) -> Path:
    """Write an exact UTF-8 machine CSV, rejecting non-text identifiers.

    CSV has no cell-type metadata.  This function guarantees character-level
    round trips through :mod:`csv`; it does not claim that opening the file in
    Excel is safe from Excel's automatic type conversion.  Human review files
    with identifiers must use :func:`write_text_xlsx`.
    """
    if len(delimiter) != 1:
        raise ValueError("CSV delimiter must be one character")
    # With no explicit schema this is a deliberately text-only CSV.  Callers
    # that also export quantities may narrow the strict columns explicitly.
    strict_columns = headers if identifier_columns is None else identifier_columns
    _, normalized_headers, normalized_rows = _prepare_sheets(
        {"CSV": (headers, rows)},
        {"CSV": strict_columns},
    )[0]
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)
    try:
        with temporary_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream, delimiter=delimiter, lineterminator="\r\n")
            writer.writerow(normalized_headers)
            writer.writerows(normalized_rows)
        os.replace(temporary_path, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return output_path


def read_text_csv(
    path: str | Path,
    *,
    delimiter: str = ";",
) -> list[dict[str, str]]:
    """Read a UTF-8 machine CSV without trimming or numeric coercion."""
    if len(delimiter) != 1:
        raise ValueError("CSV delimiter must be one character")
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=delimiter)
        if not reader.fieldnames:
            raise ValueError("CSV header is required")
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError("CSV headers must be unique")
        return [
            {str(key): value or "" for key, value in row.items() if key is not None}
            for row in reader
        ]


def column_name(index: int) -> str:
    if index < 1:
        raise ValueError("Column index must be positive")
    letters: list[str] = []
    while index:
        index, remainder = divmod(index - 1, 26)
        letters.append(chr(ord("A") + remainder))
    return "".join(reversed(letters))


def column_index(name: str) -> int:
    normalized = str(name).strip().upper()
    if not normalized or not normalized.isascii() or not normalized.isalpha():
        raise ValueError(f"Invalid Excel column: {name!r}")
    result = 0
    for character in normalized:
        result = result * 26 + ord(character) - ord("A") + 1
    return result


def _q(namespace: str, local_name: str) -> str:
    return f"{{{namespace}}}{local_name}"


def _non_negative_int(value: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise XlsxFormatError(f"Invalid non-negative integer: {value!r}") from error
    if result < 0:
        raise XlsxFormatError(f"Invalid non-negative integer: {value!r}")
    return result


def _validate_archive(archive: ZipFile) -> None:
    entries = archive.infolist()
    if len(entries) > MAX_ZIP_ENTRIES:
        raise XlsxFormatError("XLSX has too many ZIP entries")
    total = 0
    for entry in entries:
        path = PurePosixPath(entry.filename)
        if path.is_absolute() or ".." in path.parts:
            raise XlsxFormatError(f"Unsafe XLSX ZIP path: {entry.filename}")
        if entry.flag_bits & 0x1:
            raise XlsxFormatError("Encrypted XLSX entries are not supported")
        if entry.file_size > MAX_ZIP_ENTRY_BYTES:
            raise XlsxFormatError(f"XLSX entry is too large: {entry.filename}")
        total += entry.file_size
        if total > MAX_ZIP_TOTAL_BYTES:
            raise XlsxFormatError("XLSX uncompressed content is too large")
    required = {"xl/workbook.xml", "xl/_rels/workbook.xml.rels"}
    missing = required - set(archive.namelist())
    if missing:
        raise XlsxFormatError("XLSX is missing: " + ", ".join(sorted(missing)))


def _workbook_parts(archive: ZipFile) -> _WorkbookParts:
    workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    relationships = ElementTree.fromstring(
        archive.read("xl/_rels/workbook.xml.rels")
    )
    relationship_map: dict[str, tuple[str, str, str]] = {}
    for relationship in relationships.findall(_q(REL_NS, "Relationship")):
        relationship_map[relationship.attrib.get("Id", "")] = (
            relationship.attrib.get("Type", ""),
            relationship.attrib.get("Target", ""),
            relationship.attrib.get("TargetMode", ""),
        )

    sheets: list[tuple[str, str]] = []
    sheets_element = workbook.find(_q(MAIN_NS, "sheets"))
    if sheets_element is None:
        raise XlsxFormatError("Workbook has no worksheets")
    for sheet in sheets_element.findall(_q(MAIN_NS, "sheet")):
        name = sheet.attrib.get("name", "")
        relation_id = sheet.attrib.get(_q(DOC_REL_NS, "id"), "")
        relation_type, target, target_mode = relationship_map.get(
            relation_id, ("", "", "")
        )
        if target_mode.casefold() == "external":
            raise XlsxFormatError(f"External worksheet is not supported: {name}")
        if not relation_type.endswith("/worksheet") or not target:
            raise XlsxFormatError(f"Worksheet relationship is missing: {name}")
        sheet_path = _resolve_xl_target(target)
        if sheet_path not in archive.namelist():
            raise XlsxFormatError(f"Worksheet part is missing: {sheet_path}")
        sheets.append((name, sheet_path))

    shared_strings_path: str | None = None
    styles_path: str | None = None
    for relation_type, target, target_mode in relationship_map.values():
        if target_mode.casefold() == "external" or not target:
            continue
        if relation_type.endswith("/sharedStrings"):
            shared_strings_path = _resolve_xl_target(target)
        elif relation_type.endswith("/styles"):
            styles_path = _resolve_xl_target(target)
    return _WorkbookParts(tuple(sheets), shared_strings_path, styles_path)


def _resolve_xl_target(target: str) -> str:
    if target.startswith("/"):
        normalized = posixpath.normpath(target.lstrip("/"))
    else:
        normalized = posixpath.normpath(posixpath.join("xl", target))
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or not normalized.startswith("xl/"):
        raise XlsxFormatError(f"Unsafe OOXML relationship target: {target}")
    return normalized


def _shared_strings(archive: ZipFile, path: str | None) -> list[str]:
    if path is None:
        return []
    if path not in archive.namelist():
        raise XlsxFormatError(f"Shared strings part is missing: {path}")
    result: list[str] = []
    with archive.open(path, "r") as stream:
        for _, element in ElementTree.iterparse(stream, events=("end",)):
            if element.tag == _q(MAIN_NS, "si"):
                result.append(
                    "".join(
                        text.text or ""
                        for text in element.iter(_q(MAIN_NS, "t"))
                    )
                )
                element.clear()
    return result


def _style_number_formats(archive: ZipFile, path: str | None) -> list[str]:
    if path is None:
        return ["General"]
    if path not in archive.namelist():
        raise XlsxFormatError(f"Styles part is missing: {path}")
    root = ElementTree.fromstring(archive.read(path))
    custom: dict[int, str] = {}
    number_formats = root.find(_q(MAIN_NS, "numFmts"))
    if number_formats is not None:
        for item in number_formats.findall(_q(MAIN_NS, "numFmt")):
            format_id = _non_negative_int(item.attrib.get("numFmtId", "0"))
            custom[format_id] = item.attrib.get("formatCode", "")
    result: list[str] = []
    cell_formats = root.find(_q(MAIN_NS, "cellXfs"))
    if cell_formats is None:
        return ["General"]
    for item in cell_formats.findall(_q(MAIN_NS, "xf")):
        format_id = _non_negative_int(item.attrib.get("numFmtId", "0"))
        result.append(custom.get(format_id, BUILTIN_NUMBER_FORMATS.get(format_id, f"numFmtId:{format_id}")))
    return result or ["General"]


def _cell_display_value(
    element: ElementTree.Element,
    cell_type: str,
    raw_value: str,
    number_format: str,
    shared_strings: Sequence[str],
) -> str:
    if cell_type == "s":
        if raw_value == "":
            return ""
        index = _non_negative_int(raw_value)
        if index >= len(shared_strings):
            raise XlsxFormatError(f"Shared string index is out of range: {index}")
        return shared_strings[index]
    if cell_type == "inlineStr":
        return "".join(
            text.text or "" for text in element.iter(_q(MAIN_NS, "t"))
        )
    if cell_type == "b":
        return "TRUE" if raw_value == "1" else "FALSE" if raw_value == "0" else raw_value
    if cell_type == "n":
        return _numeric_display(raw_value, number_format)
    return raw_value


def _numeric_display(raw_value: str, number_format: str) -> str:
    if not raw_value:
        return ""
    try:
        value = Decimal(raw_value)
    except InvalidOperation:
        return raw_value
    if not value.is_finite():
        return raw_value
    if value == value.to_integral_value():
        plain = format(value, "f").split(".", 1)[0]
        if re.fullmatch(r"0+", number_format):
            sign = "-" if plain.startswith("-") else ""
            digits = plain.lstrip("-").zfill(len(number_format))
            return sign + digits
        return plain
    return format(value, "f")


def _cell_source_hash(
    file_hash: str, sheet_name: str, coordinate: str, raw_value: str
) -> str:
    digest = hashlib.sha256()
    for value in (file_hash, sheet_name, coordinate, raw_value):
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _column_filter(
    columns: Iterable[str] | Mapping[str, Iterable[str]] | None,
) -> dict[str, set[str] | None]:
    if columns is None:
        return {"*": None}
    if isinstance(columns, Mapping):
        return {
            str(sheet): {_normalize_column(column) for column in values}
            for sheet, values in columns.items()
        }
    return {"*": {_normalize_column(column) for column in columns}}


def _normalize_column(column: str) -> str:
    normalized = str(column).strip().upper()
    column_index(normalized)
    return normalized


def _prepare_sheets(
    sheets: Mapping[str, Any],
    identifier_columns: Iterable[str] | Mapping[str, Iterable[str]] | None,
) -> list[tuple[str, list[str], list[list[str]]]]:
    if not sheets:
        raise ValueError("At least one worksheet is required")
    identifier_map: dict[str, set[str]]
    if identifier_columns is None:
        identifier_map = {"*": set()}
    elif isinstance(identifier_columns, Mapping):
        identifier_map = {
            str(name): {str(column) for column in values}
            for name, values in identifier_columns.items()
        }
    else:
        identifier_map = {"*": {str(column) for column in identifier_columns}}

    prepared: list[tuple[str, list[str], list[list[str]]]] = []
    seen_names: set[str] = set()
    for sheet_name, payload in sheets.items():
        name = str(sheet_name)
        _validate_sheet_name(name)
        folded = name.casefold()
        if folded in seen_names:
            raise ValueError(f"Duplicate worksheet name: {name}")
        seen_names.add(folded)
        headers, source_rows = _sheet_payload(payload)
        if not headers or any(not header for header in headers):
            raise ValueError(f"Worksheet {name!r} must have non-empty headers")
        if len(set(headers)) != len(headers):
            raise ValueError(f"Worksheet {name!r} has duplicate headers")
        identifiers = identifier_map.get(name, identifier_map.get("*", set()))
        unknown_identifiers = identifiers - set(headers)
        if unknown_identifiers:
            raise ValueError(
                f"Unknown identifier column(s) in {name!r}: "
                + ", ".join(sorted(unknown_identifiers))
            )
        rows: list[list[str]] = []
        for row_number, row in enumerate(source_rows, start=2):
            if isinstance(row, Mapping):
                values = [row.get(header, "") for header in headers]
            else:
                values = list(row)
                if len(values) != len(headers):
                    raise ValueError(
                        f"Worksheet {name!r}, row {row_number}: expected "
                        f"{len(headers)} values, got {len(values)}"
                    )
            text_values: list[str] = []
            for header, value in zip(headers, values):
                if value is None:
                    text = ""
                elif header in identifiers:
                    if not isinstance(value, str):
                        raise TypeError(
                            f"Identifier {header!r} in {name!r}, row {row_number} "
                            "must be str or None"
                        )
                    text = value
                else:
                    text = value if isinstance(value, str) else str(value)
                text_values.append(text)
            rows.append(text_values)
        prepared.append((name, headers, rows))
    return prepared


def _sheet_payload(payload: Any) -> tuple[list[str], Iterable[Any]]:
    if isinstance(payload, Mapping):
        headers = payload.get("headers")
        rows = payload.get("rows")
    elif isinstance(payload, tuple) and len(payload) == 2:
        headers, rows = payload
    else:
        raise TypeError(
            "Sheet payload must be (headers, rows) or {'headers': ..., 'rows': ...}"
        )
    if headers is None or rows is None:
        raise ValueError("Sheet payload requires headers and rows")
    return [str(header) for header in headers], rows


def _validate_sheet_name(name: str) -> None:
    if not name or len(name) > 31 or INVALID_SHEET_NAME_RE.search(name):
        raise ValueError(f"Invalid worksheet name: {name!r}")
    if name.startswith("'") or name.endswith("'"):
        raise ValueError(f"Invalid worksheet name: {name!r}")


def _write_zip_text(archive: ZipFile, name: str, value: str) -> None:
    info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    archive.writestr(info, value.encode("utf-8"))


def _content_types(sheet_count: int) -> str:
    sheet_overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for index in range(1, sheet_count + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        f"{sheet_overrides}</Types>"
    )


def _root_relationships() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{REL_NS}">'
        '<Relationship Id="rId1" '
        f'Type="{DOC_REL_NS}/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )


def _workbook_xml(prepared: Sequence[tuple[str, list[str], list[list[str]]]]) -> str:
    sheet_elements = "".join(
        f'<sheet name={quoteattr(name)} sheetId="{index}" r:id="rId{index}"/>'
        for index, (name, _, _) in enumerate(prepared, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{MAIN_NS}" xmlns:r="{DOC_REL_NS}">'
        f"<sheets>{sheet_elements}</sheets></workbook>"
    )


def _workbook_relationships(sheet_count: int) -> str:
    worksheet_relationships = "".join(
        f'<Relationship Id="rId{index}" Type="{DOC_REL_NS}/worksheet" '
        f'Target="worksheets/sheet{index}.xml"/>'
        for index in range(1, sheet_count + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{REL_NS}">'
        f"{worksheet_relationships}"
        f'<Relationship Id="rId{sheet_count + 1}" Type="{DOC_REL_NS}/styles" '
        'Target="styles.xml"/>'
        '</Relationships>'
    )


def _text_styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<styleSheet xmlns="{MAIN_NS}">'
        '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        '</cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '<dxfs count="0"/>'
        '</styleSheet>'
    )


def _worksheet_xml(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    all_rows = [list(headers), *[list(row) for row in rows]]
    row_elements: list[str] = []
    for row_number, row in enumerate(all_rows, start=1):
        cells = "".join(
            _inline_text_cell(column_name(column_number), row_number, value)
            for column_number, value in enumerate(row, start=1)
        )
        row_elements.append(f'<row r="{row_number}">{cells}</row>')
    end_coordinate = f"{column_name(len(headers))}{len(all_rows)}"
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{MAIN_NS}">'
        f'<dimension ref="A1:{end_coordinate}"/>'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
        'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        '<sheetFormatPr defaultRowHeight="15"/>'
        f'<sheetData>{"".join(row_elements)}</sheetData>'
        f'<autoFilter ref="A1:{end_coordinate}"/>'
        '</worksheet>'
    )


def _inline_text_cell(column: str, row: int, value: str) -> str:
    # ``inlineStr`` is critical: strings beginning with '=' stay text and no
    # shared-string or numeric conversion can alter identifier characters.
    if INVALID_XML_TEXT_RE.search(value):
        raise ValueError(
            f"Cell {column}{row} contains a character forbidden by XML 1.0"
        )
    encoded = escape(value, {'"': "&quot;"})
    return (
        f'<c r="{column}{row}" s="1" t="inlineStr"><is>'
        f'<t xml:space="preserve">{encoded}</t></is></c>'
    )
