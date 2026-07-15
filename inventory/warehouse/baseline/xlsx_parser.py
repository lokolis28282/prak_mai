"""Strict OOXML reader for ODE-FULL-INVENTORY v1.

Worksheet rows are processed with ``iterparse`` and are not retained as an XML
DOM. Shared strings, when present, are materialized because the OOXML format
uses integer references to that table; callers must account for that bounded
but non-streaming part in performance evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
import io
from pathlib import Path, PurePosixPath
import posixpath
import re
from typing import Iterator
from xml.etree import ElementTree
from xml.sax.saxutils import escape, quoteattr
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile, ZipInfo


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CELL_RE = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")

MAX_UPLOAD_BYTES = 512 * 1024 * 1024
MAX_ENTRIES = 10_000
MAX_EXPANDED_BYTES = 4 * 1024 * 1024 * 1024
MAX_ENTRY_BYTES = 4 * 1024 * 1024 * 1024
MAX_COMPRESSION_RATIO = 1_000
MAX_ROWS = 1_000_000

REQUIRED_SHEETS = {"Manifest", "Inventory"}
OPTIONAL_SHEETS = {"Instructions", "Lookups"}
MANIFEST_KEYS = (
    "TemplateId",
    "TemplateVersion",
    "InventoryExternalId",
    "WarehouseCode",
    "CountStartedAt",
    "CountFinishedAt",
    "CountedBy",
    "TimeZone",
    "ReferenceVersion",
    "Comment",
)
INVENTORY_COLUMNS = (
    "RowId",
    "ItemKind",
    "WarehouseCode",
    "LocationCode",
    "SerialNumber",
    "InventoryNumber",
    "PartNumber",
    "Vendor",
    "Model",
    "Description",
    "Quantity",
    "UOM",
    "Condition",
    "Lot",
    "CountedBy",
    "CountedAt",
    "Comment",
)
IDENTIFIER_COLUMNS = {"SerialNumber", "InventoryNumber", "PartNumber", "RowId"}
FORBIDDEN_PART_MARKERS = (
    "vbaproject",
    "macrosheet",
    "externallinks/",
    "embeddings/",
    "oleobjects/",
    "activex/",
    "connections.xml",
    "ddelink",
)


class FullInventoryXlsxError(ValueError):
    code = "FULL_INVENTORY_XLSX_INVALID"


@dataclass(frozen=True)
class Cell:
    coordinate: str
    column: str
    row_number: int
    cell_type: str
    number_format: str
    raw_value: str
    display_value: str
    has_formula: bool


@dataclass(frozen=True)
class SourceRow:
    row_number: int
    hidden: bool
    cells: dict[str, Cell]


@dataclass(frozen=True)
class WorkbookInfo:
    sheets: tuple[str, ...]
    manifest: dict[str, Cell]
    rows: tuple[SourceRow, ...]
    unknown_sheets: tuple[str, ...]
    merged_inventory_ranges: tuple[str, ...]


def _q(namespace: str, local: str) -> str:
    return f"{{{namespace}}}{local}"


def _safe_part_name(name: str) -> None:
    pure = PurePosixPath(name)
    if not name or pure.is_absolute() or ".." in pure.parts or "\\" in name:
        raise FullInventoryXlsxError("XLSX содержит небезопасный ZIP path")


def _scan_xml_security(archive: ZipFile, info: ZipInfo) -> None:
    tail = b""
    with archive.open(info) as stream:
        while chunk := stream.read(1024 * 1024):
            sample = (tail + chunk).upper()
            if b"<!DOCTYPE" in sample or b"<!ENTITY" in sample:
                raise FullInventoryXlsxError("DTD/entity в OOXML запрещены")
            tail = sample[-16:]


def _validate_archive(archive: ZipFile) -> None:
    infos = archive.infolist()
    if not infos or len(infos) > MAX_ENTRIES:
        raise FullInventoryXlsxError("Некорректное количество XLSX ZIP entries")
    expanded = 0
    names: set[str] = set()
    for info in infos:
        _safe_part_name(info.filename)
        lower = info.filename.casefold()
        if lower in names:
            raise FullInventoryXlsxError("XLSX содержит повторяющийся ZIP entry")
        names.add(lower)
        if any(marker in lower for marker in FORBIDDEN_PART_MARKERS):
            raise FullInventoryXlsxError("Макросы, external links и embedded objects запрещены")
        if info.file_size < 0 or info.file_size > MAX_ENTRY_BYTES:
            raise FullInventoryXlsxError("XLSX ZIP entry превышает лимит")
        if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
            raise FullInventoryXlsxError("Подозрительная степень сжатия XLSX")
        expanded += info.file_size
        if expanded > MAX_EXPANDED_BYTES:
            raise FullInventoryXlsxError("Распакованный XLSX превышает лимит")
        if lower.endswith((".xml", ".rels")):
            _scan_xml_security(archive, info)
    if "[content_types].xml" not in names or "xl/workbook.xml" not in names:
        raise FullInventoryXlsxError("Файл не является поддерживаемым XLSX/OOXML")
    for info in infos:
        if info.filename.casefold().endswith(".rels"):
            try:
                root = ElementTree.fromstring(archive.read(info))
            except ElementTree.ParseError as error:
                raise FullInventoryXlsxError("Повреждённый OOXML relationship") from error
            for relation in root:
                if relation.attrib.get("TargetMode", "").casefold() == "external":
                    raise FullInventoryXlsxError("External OOXML relationships запрещены")


def _relationships(archive: ZipFile, path: str) -> dict[str, str]:
    try:
        root = ElementTree.fromstring(archive.read(path))
    except (KeyError, ElementTree.ParseError) as error:
        raise FullInventoryXlsxError("Отсутствуют workbook relationships") from error
    return {
        relation.attrib["Id"]: relation.attrib["Target"]
        for relation in root.findall(_q(REL_NS, "Relationship"))
        if "Id" in relation.attrib and "Target" in relation.attrib
    }


def _workbook_parts(archive: ZipFile) -> tuple[list[tuple[str, str]], str | None, str | None]:
    try:
        root = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    except (KeyError, ElementTree.ParseError) as error:
        raise FullInventoryXlsxError("Повреждён workbook.xml") from error
    relationships = _relationships(archive, "xl/_rels/workbook.xml.rels")
    sheets: list[tuple[str, str]] = []
    for sheet in root.findall(f".//{_q(MAIN_NS, 'sheet')}"):
        name = sheet.attrib.get("name", "")
        relation_id = sheet.attrib.get(_q(DOC_REL_NS, "id"), "")
        target = relationships.get(relation_id, "")
        if not name or not target:
            raise FullInventoryXlsxError("Некорректное описание листа XLSX")
        path = posixpath.normpath(posixpath.join("xl", target))
        _safe_part_name(path)
        sheets.append((name, path))
    shared = next(
        (posixpath.normpath(posixpath.join("xl", target)) for target in relationships.values() if "sharedstrings" in target.casefold()),
        None,
    )
    styles = next(
        (posixpath.normpath(posixpath.join("xl", target)) for target in relationships.values() if target.casefold().endswith("styles.xml")),
        None,
    )
    return sheets, shared, styles


def _shared_strings(archive: ZipFile, path: str | None) -> list[str]:
    if not path:
        return []
    values: list[str] = []
    try:
        with archive.open(path) as stream:
            for _, element in ElementTree.iterparse(stream, events=("end",)):
                if element.tag == _q(MAIN_NS, "si"):
                    values.append("".join(node.text or "" for node in element.iter(_q(MAIN_NS, "t"))))
                    element.clear()
    except (KeyError, ElementTree.ParseError) as error:
        raise FullInventoryXlsxError("Повреждена таблица sharedStrings") from error
    return values


def _number_formats(archive: ZipFile, path: str | None) -> list[str]:
    if not path:
        return ["General"]
    try:
        root = ElementTree.fromstring(archive.read(path))
    except (KeyError, ElementTree.ParseError):
        return ["General"]
    custom = {
        int(node.attrib.get("numFmtId", "0")): node.attrib.get("formatCode", "General")
        for node in root.findall(f".//{_q(MAIN_NS, 'numFmt')}")
    }
    formats = ["General"]
    cell_xfs = root.find(_q(MAIN_NS, "cellXfs"))
    if cell_xfs is not None:
        formats = [custom.get(int(node.attrib.get("numFmtId", "0")), "@" if node.attrib.get("numFmtId") == "49" else "General") for node in cell_xfs]
    return formats or ["General"]


def _cell_value(element: ElementTree.Element, shared: list[str]) -> tuple[str, str]:
    cell_type = element.attrib.get("t", "n")
    value_element = element.find(_q(MAIN_NS, "v"))
    raw = value_element.text or "" if value_element is not None else ""
    if cell_type == "inlineStr":
        display = "".join(node.text or "" for node in element.iter(_q(MAIN_NS, "t")))
        return display, display
    if cell_type == "s":
        try:
            return raw, shared[int(raw)]
        except (ValueError, IndexError) as error:
            raise FullInventoryXlsxError("Некорректная ссылка sharedStrings") from error
    return raw, raw


def _iter_rows(
    archive: ZipFile,
    sheet_path: str,
    shared: list[str],
    formats: list[str],
) -> Iterator[SourceRow]:
    try:
        with archive.open(sheet_path) as stream:
            for _, element in ElementTree.iterparse(stream, events=("end",)):
                if element.tag != _q(MAIN_NS, "row"):
                    continue
                row_number = int(element.attrib.get("r", "0") or 0)
                if row_number <= 0:
                    raise FullInventoryXlsxError("Некорректный номер строки XLSX")
                cells: dict[str, Cell] = {}
                for cell_node in element.findall(_q(MAIN_NS, "c")):
                    coordinate = cell_node.attrib.get("r", "")
                    match = CELL_RE.fullmatch(coordinate)
                    if not match:
                        raise FullInventoryXlsxError("Некорректная координата XLSX")
                    column, coordinate_row = match.groups()
                    if int(coordinate_row) != row_number:
                        raise FullInventoryXlsxError("Координата XLSX не совпадает со строкой")
                    raw, display = _cell_value(cell_node, shared)
                    style = int(cell_node.attrib.get("s", "0") or 0)
                    number_format = formats[style] if 0 <= style < len(formats) else "General"
                    cells[column] = Cell(
                        coordinate=coordinate,
                        column=column,
                        row_number=row_number,
                        cell_type=cell_node.attrib.get("t", "n"),
                        number_format=number_format,
                        raw_value=raw,
                        display_value=display,
                        has_formula=cell_node.find(_q(MAIN_NS, "f")) is not None,
                    )
                yield SourceRow(
                    row_number=row_number,
                    hidden=element.attrib.get("hidden") in {"1", "true", "True"},
                    cells=cells,
                )
                element.clear()
    except (KeyError, ElementTree.ParseError) as error:
        raise FullInventoryXlsxError("Повреждён worksheet XML") from error


def _merged_ranges(archive: ZipFile, sheet_path: str) -> tuple[str, ...]:
    ranges: list[str] = []
    try:
        with archive.open(sheet_path) as stream:
            for _, element in ElementTree.iterparse(stream, events=("end",)):
                if element.tag == _q(MAIN_NS, "mergeCell"):
                    reference = element.attrib.get("ref", "")
                    if reference:
                        ranges.append(reference)
                element.clear()
    except (KeyError, ElementTree.ParseError) as error:
        raise FullInventoryXlsxError("Повреждены merged cells") from error
    return tuple(ranges)


def _column_number(letters: str) -> int:
    value = 0
    for letter in letters:
        value = value * 26 + ord(letter) - 64
    return value


def inspect_workbook(path: str | Path) -> WorkbookInfo:
    source = Path(path)
    if source.suffix.casefold() != ".xlsx" or not source.is_file():
        raise FullInventoryXlsxError("Разрешён только файл .xlsx")
    if source.stat().st_size <= 0 or source.stat().st_size > MAX_UPLOAD_BYTES:
        raise FullInventoryXlsxError("Размер XLSX вне допустимого диапазона")
    try:
        with ZipFile(source) as archive:
            _validate_archive(archive)
            sheets, shared_path, styles_path = _workbook_parts(archive)
            names = [name for name, _ in sheets]
            missing = REQUIRED_SHEETS.difference(names)
            if missing:
                raise FullInventoryXlsxError("Отсутствуют листы: " + ", ".join(sorted(missing)))
            if len(names) != len(set(names)):
                raise FullInventoryXlsxError("Повторяющиеся имена листов запрещены")
            shared = _shared_strings(archive, shared_path)
            formats = _number_formats(archive, styles_path)
            manifest_path = dict(sheets)["Manifest"]
            inventory_path = dict(sheets)["Inventory"]
            manifest: dict[str, Cell] = {}
            for row in _iter_rows(archive, manifest_path, shared, formats):
                key = row.cells.get("A")
                value = row.cells.get("B")
                if key and key.display_value.strip():
                    if key.display_value in manifest:
                        raise FullInventoryXlsxError("Manifest содержит повторяющийся key")
                    if value is None:
                        value = Cell(f"B{row.row_number}", "B", row.row_number, "inlineStr", "@", "", "", False)
                    manifest[key.display_value] = value
            row_iterator = _iter_rows(archive, inventory_path, shared, formats)
            header_row = next(row_iterator, None)
            if header_row is None or header_row.row_number != 1:
                raise FullInventoryXlsxError("Inventory header должен быть в строке 1")
            headers: dict[str, str] = {}
            for column, cell in header_row.cells.items():
                header = cell.display_value.strip()
                if header:
                    if header in headers.values():
                        raise FullInventoryXlsxError("Inventory header содержит дубликаты")
                    headers[column] = header
            missing_columns = set(INVENTORY_COLUMNS).difference(headers.values())
            if missing_columns:
                raise FullInventoryXlsxError(
                    "Отсутствуют колонки: " + ", ".join(sorted(missing_columns))
                )
            rows: list[SourceRow] = []
            for row in row_iterator:
                if row.row_number > MAX_ROWS + 1:
                    raise FullInventoryXlsxError("Inventory превышает 1 000 000 строк")
                mapped = {
                    headers[column]: cell
                    for column, cell in row.cells.items()
                    if column in headers
                }
                extra = {
                    f"__EXTRA__{_column_number(column)}": cell
                    for column, cell in row.cells.items()
                    if column not in headers
                }
                if mapped or extra or row.hidden:
                    rows.append(SourceRow(row.row_number, row.hidden, {**mapped, **extra}))
            merged = _merged_ranges(archive, inventory_path)
            unknown = tuple(name for name in names if name not in REQUIRED_SHEETS | OPTIONAL_SHEETS)
            return WorkbookInfo(tuple(names), manifest, tuple(rows), unknown, merged)
    except BadZipFile as error:
        raise FullInventoryXlsxError("Файл не является валидным XLSX") from error


def _column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _worksheet_xml(rows: list[list[str]]) -> str:
    body = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(row, start=1):
            coordinate = f"{_column_name(column_index)}{row_index}"
            cells.append(
                f'<c r="{coordinate}" s="1" t="inlineStr"><is><t xml:space="preserve">'
                f"{escape(value)}</t></is></c>"
            )
        body.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{MAIN_NS}"><sheetData>{"".join(body)}</sheetData></worksheet>'
    )


def template_bytes() -> bytes:
    manifest_rows = [["Key", "Value"]] + [[key, ""] for key in MANIFEST_KEYS]
    for row in manifest_rows:
        if row[0] == "TemplateId":
            row[1] = "ODE-FULL-INVENTORY"
        elif row[0] == "TemplateVersion":
            row[1] = "1.0"
    inventory_rows = [list(INVENTORY_COLUMNS)]
    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '</Types>',
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<Relationships xmlns="{REL_NS}"><Relationship Id="rId1" '
            f'Type="{DOC_REL_NS}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<workbook xmlns="{MAIN_NS}" xmlns:r="{DOC_REL_NS}"><sheets>'
            '<sheet name="Manifest" sheetId="1" r:id="rId1"/>'
            '<sheet name="Inventory" sheetId="2" r:id="rId2"/>'
            '</sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<Relationships xmlns="{REL_NS}">'
            f'<Relationship Id="rId1" Type="{DOC_REL_NS}/worksheet" Target="worksheets/sheet1.xml"/>'
            f'<Relationship Id="rId2" Type="{DOC_REL_NS}/worksheet" Target="worksheets/sheet2.xml"/>'
            f'<Relationship Id="rId3" Type="{DOC_REL_NS}/styles" Target="styles.xml"/>'
            '</Relationships>',
        )
        archive.writestr(
            "xl/styles.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<styleSheet xmlns="{MAIN_NS}"><fonts count="1"><font/></fonts>'
            '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
            '<borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs>'
            '<cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="49" applyNumberFormat="1"/></cellXfs>'
            '</styleSheet>',
        )
        archive.writestr("xl/worksheets/sheet1.xml", _worksheet_xml(manifest_rows))
        archive.writestr("xl/worksheets/sheet2.xml", _worksheet_xml(inventory_rows))
    return output.getvalue()
