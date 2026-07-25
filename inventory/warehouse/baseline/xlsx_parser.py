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
OPTIONAL_SHEETS = {
    "Instructions", "Lookups", "Инструкция", "Справочник", "Номенклатура",
}
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
TEMPLATE_INVENTORY_COLUMNS = (
    "SerialNumber",
    "RowId",
    "ItemKind",
    "Description",
    "LocationCode",
    "WarehouseCode",
    "InventoryNumber",
    "PartNumber",
    "Vendor",
    "Model",
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
    rows: "InventoryRowStream"
    unknown_sheets: tuple[str, ...]
    merged_inventory_ranges: tuple[str, ...]


@dataclass(frozen=True)
class TemplateContext:
    """Read-only operator hints embedded into a downloaded inventory template."""

    reference_version: str = ""
    warehouse_codes: tuple[str, ...] = ()
    location_codes: tuple[str, ...] = ()
    uom_codes: tuple[str, ...] = ()
    vendors: tuple[str, ...] = ()
    type_rows: tuple[tuple[str, ...], ...] = ()
    nomenclature_rows: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class InventoryRowStream:
    source: Path
    sheet_path: str
    shared: tuple[str, ...]
    formats: tuple[str, ...]
    headers: tuple[tuple[str, str], ...]

    def __iter__(self) -> Iterator[SourceRow]:
        headers = dict(self.headers)
        try:
            with ZipFile(self.source) as archive:
                row_iterator = _iter_rows(
                    archive, self.sheet_path, list(self.shared), list(self.formats)
                )
                next(row_iterator, None)  # Header was validated by inspect_workbook.
                for row in row_iterator:
                    if row.row_number > MAX_ROWS + 1:
                        raise FullInventoryXlsxError(
                            "Inventory превышает 1 000 000 строк"
                        )
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
                        yield SourceRow(
                            row.row_number, row.hidden, {**mapped, **extra}
                        )
        except BadZipFile as error:
            raise FullInventoryXlsxError("Файл не является валидным XLSX") from error


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
            row_iterator.close()
            rows = InventoryRowStream(
                source=source.resolve(),
                sheet_path=inventory_path,
                shared=tuple(shared),
                formats=tuple(formats),
                headers=tuple(headers.items()),
            )
            merged = _merged_ranges(archive, inventory_path)
            unknown = tuple(name for name in names if name not in REQUIRED_SHEETS | OPTIONAL_SHEETS)
            return WorkbookInfo(tuple(names), manifest, rows, unknown, merged)
    except BadZipFile as error:
        raise FullInventoryXlsxError("Файл не является валидным XLSX") from error


def _column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _worksheet_xml(
    rows: list[list[str]],
    *,
    widths: tuple[float, ...] = (),
    freeze_rows: int = 0,
    freeze_columns: int = 0,
    header_rows: frozenset[int] = frozenset(),
    title_rows: frozenset[int] = frozenset(),
    note_rows: frozenset[int] = frozenset(),
    wrapped_rows: frozenset[int] = frozenset(),
    merged_ranges: tuple[str, ...] = (),
    auto_filter: str = "",
    validations: tuple[tuple[str, str, str, str], ...] = (),
) -> str:
    body = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(row, start=1):
            coordinate = f"{_column_name(column_index)}{row_index}"
            style = 2 if row_index in header_rows else 3 if row_index in title_rows else 4 if row_index in note_rows else 5 if row_index in wrapped_rows else 1
            cells.append(
                f'<c r="{coordinate}" s="{style}" t="inlineStr"><is><t xml:space="preserve">'
                f"{escape(str(value))}</t></is></c>"
            )
        height = ' ht="30" customHeight="1"' if row_index in title_rows else ' ht="24" customHeight="1"' if row_index in header_rows else ' ht="38" customHeight="1"' if row_index in note_rows or row_index in wrapped_rows else ""
        body.append(f'<row r="{row_index}"{height}>{"".join(cells)}</row>')
    columns = ""
    if widths:
        columns = "<cols>" + "".join(
            f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>'
            for index, width in enumerate(widths, start=1)
        ) + "</cols>"
    pane = ""
    if freeze_rows or freeze_columns:
        top_left = f"{_column_name(freeze_columns + 1)}{freeze_rows + 1}"
        attributes = [f'topLeftCell="{top_left}"', 'state="frozen"']
        if freeze_rows:
            attributes.append(f'ySplit="{freeze_rows}"')
        if freeze_columns:
            attributes.append(f'xSplit="{freeze_columns}"')
        attributes.append('activePane="bottomRight"' if freeze_rows and freeze_columns else 'activePane="bottomLeft"' if freeze_rows else 'activePane="topRight"')
        pane = f'<pane {" ".join(attributes)}/>'
    merges = ""
    if merged_ranges:
        merges = f'<mergeCells count="{len(merged_ranges)}">' + "".join(
            f'<mergeCell ref={quoteattr(value)}/>' for value in merged_ranges
        ) + "</mergeCells>"
    filter_xml = f'<autoFilter ref={quoteattr(auto_filter)}/>' if auto_filter else ""
    validation_xml = ""
    if validations:
        validation_xml = f'<dataValidations count="{len(validations)}">' + "".join(
            '<dataValidation type="list" allowBlank="1" showErrorMessage="1" '
            f'errorStyle="stop" errorTitle={quoteattr(title)} error={quoteattr(message)} '
            f'sqref={quoteattr(cell_range)}><formula1>{escape(name)}</formula1></dataValidation>'
            for cell_range, name, title, message in validations
        ) + "</dataValidations>"
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{MAIN_NS}"><sheetViews><sheetView workbookViewId="0" showGridLines="0">{pane}</sheetView></sheetViews>'
        f'<sheetFormatPr defaultRowHeight="18"/>{columns}<sheetData>{"".join(body)}</sheetData>{filter_xml}{merges}{validation_xml}</worksheet>'
    )


def _styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<styleSheet xmlns="{MAIN_NS}">'
        '<fonts count="3"><font><sz val="11"/><name val="Aptos"/></font>'
        '<font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Aptos"/></font>'
        '<font><b/><color rgb="FF17365D"/><sz val="14"/><name val="Aptos Display"/></font></fonts>'
        '<fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF2F64D6"/><bgColor indexed="64"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFEAF1FF"/><bgColor indexed="64"/></patternFill></fill></fills>'
        '<borders count="2"><border/><border><bottom style="thin"><color rgb="FFD7DFEE"/></bottom></border></borders>'
        '<cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="6">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>'
        '<xf numFmtId="49" fontId="0" fillId="0" borderId="1" applyNumberFormat="1"><alignment vertical="center"/></xf>'
        '<xf numFmtId="49" fontId="1" fillId="2" borderId="0" applyNumberFormat="1"><alignment vertical="center" wrapText="1"/></xf>'
        '<xf numFmtId="49" fontId="2" fillId="3" borderId="0" applyNumberFormat="1"><alignment vertical="center"/></xf>'
        '<xf numFmtId="49" fontId="0" fillId="3" borderId="0" applyNumberFormat="1"><alignment vertical="center" wrapText="1"/></xf>'
        '<xf numFmtId="49" fontId="0" fillId="0" borderId="1" applyNumberFormat="1"><alignment vertical="center" wrapText="1"/></xf>'
        '</cellXfs></styleSheet>'
    )


def _fallback_type_rows() -> tuple[tuple[str, ...], ...]:
    return (
        ("Оборудование", "Тип оборудования", "Сервер", "SERIALIZED", "SERIALIZED", "шт", "Точное наименование из листа «Номенклатура»", "S/N обязателен, Quantity = 1"),
        ("Трансиверы", "Тип компонента", "Трансивер", "SERIALIZED", "SERIALIZED", "шт", "Трансивер + модель", "SFP/QSFP — это трансиверы"),
        ("Память", "Тип компонента", "Оперативная память", "SERIALIZED", "SERIALIZED", "шт", "Оперативная память + модель/объём", "Скан S/N, Quantity = 1"),
        ("Кабели", "Тип кабеля", "UTP / OM4 / MTP", "CABLE", "SERIALIZED", "шт или м", "Точное наименование кабеля", "Без S/N — CABLE; с S/N — SERIALIZED"),
        ("Кабельные сборки", "Тип кабеля", "AOC / DAC", "CABLE", "SERIALIZED", "шт", "AOC/DAC + скорость/длина", "Без S/N — CABLE; с S/N — SERIALIZED"),
    )


def template_bytes(context: TemplateContext | None = None) -> bytes:
    context = context or TemplateContext(type_rows=_fallback_type_rows())
    manifest_rows = [["Key", "Value"]] + [[key, ""] for key in MANIFEST_KEYS]
    for row in manifest_rows:
        if row[0] == "TemplateId":
            row[1] = "ODE-FULL-INVENTORY"
        elif row[0] == "TemplateVersion":
            row[1] = "1.0"
        elif row[0] == "ReferenceVersion":
            row[1] = context.reference_version
        elif row[0] == "WarehouseCode" and context.warehouse_codes:
            row[1] = context.warehouse_codes[0]
        elif row[0] == "TimeZone":
            row[1] = "Europe/Moscow"

    inventory_rows = [list(TEMPLATE_INVENTORY_COLUMNS)]
    instructions_rows = [
        ["Как заполнять FULL Inventory", "", ""],
        ["Главное правило", "Одна физическая позиция с S/N = одна строка, ItemKind = SERIALIZED, Quantity = 1.", ""],
        ["Шаг", "Что делать", "Что копировать/вводить"],
        ["1", "Заполните Manifest", "Номер инвентаризации, время начала/окончания и ФИО."],
        ["2", "Откройте Inventory и сканируйте S/N в колонку A", "Не меняйте S/N: он сохраняется как текст."],
        ["3", "Для RowId у штучной позиции можно использовать тот же S/N", "Скопируйте A в B. RowId должен быть уникальным."],
        ["4", "Выберите ItemKind и точное наименование", "Берите их из «Справочника» и «Номенклатуры». Если точной позиции нет — введите новое точное Description, не выбирайте похожую модель."],
        ["5", "Укажите фактическую новую полку", "Скопируйте точный LocationCode из «Справочника». Если полки нет — добавьте её в ODE и скачайте шаблон заново."],
        ["6", "Заполните Quantity, UOM, Condition и CountedBy", "Обычно: 1 / шт / AVAILABLE / ФИО инженера."],
        ["7", "Загрузите XLSX в ODE", "Сначала будет Preview; рабочая БД на этом этапе не меняется."],
        ["", "", ""],
        ["Пример: оперативная память", "ItemKind = SERIALIZED; Description = точное наименование памяти; Quantity = 1; UOM = шт", "LocationCode = новая фактическая полка."],
    ]

    type_rows = context.type_rows or _fallback_type_rows()
    item_kinds = ("SERIALIZED", "BULK", "CABLE", "CONSUMABLE")
    conditions = ("AVAILABLE", "QUARANTINED", "DAMAGED")
    reference_height = max(
        len(type_rows) + 4,
        len(item_kinds) + 1,
        len(conditions) + 1,
        len(context.warehouse_codes) + 1,
        len(context.location_codes) + 1,
        len(context.uom_codes) + 1,
        len(context.vendors) + 1,
    )
    reference_rows = [["" for _ in range(16)] for _ in range(reference_height)]
    reference_rows[0][0] = "ODE — категории и точные значения для Inventory"
    reference_rows[1][0] = "Копируйте значения без изменений. Полки взяты из активного справочника, а номенклатура — из всей истории Warehouse."
    reference_rows[3][:8] = ["Категория", "Поле типа в ODE", "Точное значение типа", "ItemKind обычно", "ItemKind если есть S/N", "UOM", "Что писать в Description", "Правило"]
    for index, values in enumerate(type_rows, start=4):
        reference_rows[index][:8] = list(values[:8])
    lists = (
        (9, "ItemKind", item_kinds),
        (10, "Condition", conditions),
        (11, "WarehouseCode", context.warehouse_codes),
        (12, "LocationCode (полка)", context.location_codes),
        (13, "UOM", context.uom_codes),
        (14, "Vendor", context.vendors),
    )
    for column, header, values in lists:
        reference_rows[0][column] = header
        for row_index, value in enumerate(values, start=1):
            reference_rows[row_index][column] = value

    nomenclature_rows = [["Категория", "Тип ODE", "ItemKind", "Точное Description", "Vendor", "Model", "UOM", "Карточек в истории", "Предварительный остаток"]]
    nomenclature_rows.extend([list(row[:9]) for row in context.nomenclature_rows])
    if len(nomenclature_rows) == 1:
        nomenclature_rows.append(["Данных истории склада нет", "", "", "", "", "", "", "", ""])

    defined_names: list[tuple[str, str]] = [
        ("ItemKinds", f"'Справочник'!$J$2:$J${len(item_kinds) + 1}"),
        ("Conditions", f"'Справочник'!$K$2:$K${len(conditions) + 1}"),
    ]
    if context.warehouse_codes:
        defined_names.append(("WarehouseCodes", f"'Справочник'!$L$2:$L${len(context.warehouse_codes) + 1}"))
    if context.location_codes:
        defined_names.append(("LocationCodes", f"'Справочник'!$M$2:$M${len(context.location_codes) + 1}"))
    if context.uom_codes:
        defined_names.append(("UOMCodes", f"'Справочник'!$N$2:$N${len(context.uom_codes) + 1}"))
    validations: list[tuple[str, str, str, str]] = [
        ("C2:C1048576", "ItemKinds", "Неверный ItemKind", "Выберите значение из списка."),
        ("M2:M1048576", "Conditions", "Неверное состояние", "Выберите AVAILABLE, QUARANTINED или DAMAGED."),
    ]
    if context.location_codes:
        validations.append(("E2:E1048576", "LocationCodes", "Полка не найдена", "Добавьте полку в справочник ODE и скачайте шаблон заново."))
    if context.warehouse_codes:
        validations.append(("F2:F1048576", "WarehouseCodes", "ЦОД не найден", "Выберите ЦОД из списка."))
    if context.uom_codes:
        validations.append(("L2:L1048576", "UOMCodes", "Единица не найдена", "Выберите единицу из списка."))

    sheets = (
        ("Manifest", _worksheet_xml(manifest_rows, widths=(26, 76), freeze_rows=1, header_rows=frozenset({1}), auto_filter=f"A1:B{len(manifest_rows)}")),
        ("Inventory", _worksheet_xml(inventory_rows, widths=(24, 24, 16, 42, 20, 20, 22, 22, 20, 28, 12, 12, 18, 18, 24, 26, 38), freeze_rows=1, freeze_columns=1, header_rows=frozenset({1}), auto_filter="A1:Q1", validations=tuple(validations))),
        ("Инструкция", _worksheet_xml(instructions_rows, widths=(25, 58, 76), freeze_rows=3, header_rows=frozenset({3}), title_rows=frozenset({1}), note_rows=frozenset({2, 12}), wrapped_rows=frozenset({4, 5, 6, 7, 8, 9, 10}), merged_ranges=("A1:C1",))),
        ("Справочник", _worksheet_xml(reference_rows, widths=(24, 24, 30, 20, 22, 16, 44, 48, 3, 18, 20, 24, 26, 16, 24, 3), freeze_rows=4, header_rows=frozenset({4}), title_rows=frozenset({1}), note_rows=frozenset({2}), merged_ranges=("A1:H1", "A2:H2"), auto_filter=f"A4:H{len(type_rows) + 4}")),
        ("Номенклатура", _worksheet_xml(nomenclature_rows, widths=(24, 26, 16, 62, 22, 48, 12, 18, 18), freeze_rows=1, header_rows=frozenset({1}), wrapped_rows=frozenset(range(2, len(nomenclature_rows) + 1)), auto_filter=f"A1:I{len(nomenclature_rows)}")),
    )
    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        overrides = "".join(
            f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for index in range(1, len(sheets) + 1)
        )
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            f'{overrides}</Types>',
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
            + "".join(
                f'<sheet name={quoteattr(name)} sheetId="{index}" r:id="rId{index}"/>'
                for index, (name, _) in enumerate(sheets, start=1)
            )
            + '</sheets><definedNames>'
            + "".join(
                f'<definedName name={quoteattr(name)}>{escape(formula)}</definedName>'
                for name, formula in defined_names
            )
            + '</definedNames></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<Relationships xmlns="{REL_NS}">'
            + "".join(
                f'<Relationship Id="rId{index}" Type="{DOC_REL_NS}/worksheet" Target="worksheets/sheet{index}.xml"/>'
                for index in range(1, len(sheets) + 1)
            )
            + f'<Relationship Id="rId{len(sheets) + 1}" Type="{DOC_REL_NS}/styles" Target="styles.xml"/>'
            '</Relationships>',
        )
        archive.writestr("xl/styles.xml", _styles_xml())
        for index, (_, payload) in enumerate(sheets, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", payload)
    return output.getvalue()
