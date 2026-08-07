"""Multi-sheet XLSX writer built on the standard library.

The project ships without third-party dependencies, so `openpyxl` is not
available for writing either. An XLSX file is a ZIP container of XML parts; this
module writes the parts needed for a workbook of flat sheets. Values are emitted
as inline-string text, which keeps identifiers such as task and serial numbers
intact for Excel.

Two levels of API are provided:

* :func:`build_workbook` — plain ``(sheet_name, rows)`` pairs, all cells as
  inline strings, no styling. Kept for callers that only need a raw grid.
* :func:`build_styled_workbook` — richly formatted sheets built from
  :class:`SheetSpec`: a centred merged title band, a highlighted header band,
  thin borders around the table, and per-column auto-width. This is what the
  Reports exports use so the downloaded file opens as a finished document.

The styling is deliberately small and self-contained: a fixed set of cell
formats declared once in ``styles.xml`` and referenced by index. It produces a
file that opens without repair in Microsoft Excel and LibreOffice Calc.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from xml.sax.saxutils import escape, quoteattr


# Style indexes into the cellXfs list declared in _STYLES_XML. Index 0 is the
# implicit default (no fill, no border) that Excel always reserves.
STYLE_DEFAULT = 0
STYLE_TITLE = 1     # light-green fill, bold, centred — merged title band
STYLE_HEADER = 2    # light-yellow fill, bold, bordered — column headers
STYLE_CELL = 3      # bordered data cell, top-aligned, wrapped


def _column_ref(index: int) -> str:
    """Zero-based column index to an A1-style column letter (0->A, 26->AA)."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _xml_text(value: object) -> str:
    """Return XML 1.0-safe text without losing visible user content.

    JSON and SQLite can contain control characters that XML 1.0 forbids. Excel
    otherwise opens the generated workbook with a repair warning (or refuses
    it), so invalid code points are replaced explicitly with U+FFFD.
    """
    text = "" if value is None else str(value)
    return "".join(
        char
        if (
            char in "\t\n\r"
            or 0x20 <= ord(char) <= 0xD7FF
            or 0xE000 <= ord(char) <= 0xFFFD
            or 0x10000 <= ord(char) <= 0x10FFFF
        )
        else "\uFFFD"
        for char in text
    )


def _cell(column: int, row: int, value: object, style: int = STYLE_DEFAULT) -> str:
    ref = f"{_column_ref(column)}{row}"
    text = _xml_text(value)
    style_attr = f' s="{style}"' if style else ""
    return (
        f'<c r="{ref}"{style_attr} t="inlineStr">'
        f'<is><t xml:space="preserve">{escape(text)}</t></is></c>'
    )


def _plain_sheet_xml(rows: list[list[object]]) -> str:
    body = []
    for row_index, row in enumerate(rows, start=1):
        cells = "".join(_cell(col, row_index, value) for col, value in enumerate(row))
        body.append(f'<row r="{row_index}">{cells}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(body)}</sheetData></worksheet>'
    )


def _safe_sheet_name(name: str, used: set[str]) -> str:
    # Excel forbids these characters and a 31-char limit in sheet names.
    cleaned = "".join(" " if char in r"[]:*?/\\" else char for char in str(name)).strip()
    cleaned = (cleaned or "Лист")[:31]
    candidate, suffix = cleaned, 2
    while candidate.casefold() in used:
        candidate = f"{cleaned[:28]} {suffix}"
        suffix += 1
    used.add(candidate.casefold())
    return candidate


# --- Styled workbook --------------------------------------------------------


@dataclass
class SheetSpec:
    """A single styled sheet.

    The table is laid out with a small top-left margin: the header band starts
    at ``start_row``/``start_col`` and the merged title band sits one row above
    it. With the defaults the title lands on row 7 and the headers on row 8,
    column C (``C8``), leaving rows 1–6 and columns A–B as breathing room, which
    matches the corporate report templates this export replaces.
    """

    name: str
    title: str
    header: list[str]
    rows: list[list[object]] = field(default_factory=list)
    start_row: int = 8          # header row (title goes on start_row - 1)
    start_col: int = 2          # 0-based → column C


def _auto_widths(spec: SheetSpec) -> list[float]:
    """Character width per column from the longest cell (header or data).

    Excel column width is measured in characters of the default font; we add a
    little padding and clamp so one long value cannot produce an unusable sheet.
    """
    columns = len(spec.header)
    widths = [len(str(h)) for h in spec.header]
    for row in spec.rows:
        for col in range(columns):
            value = row[col] if col < len(row) else ""
            # Multi-line cells (the PNR handover text) size to their widest line.
            longest_line = max((len(part) for part in str(value).split("\n")), default=0)
            if longest_line > widths[col]:
                widths[col] = longest_line
    return [min(max(width + 3, 10), 60) for width in widths]


def _styled_sheet_xml(spec: SheetSpec) -> str:
    columns = len(spec.header)
    header_row = spec.start_row
    title_row = header_row - 1
    first_col = spec.start_col
    last_col = first_col + columns - 1

    widths = _auto_widths(spec)
    cols_xml = "".join(
        f'<col min="{first_col + i + 1}" max="{first_col + i + 1}" '
        f'width="{widths[i]:.2f}" customWidth="1"/>'
        for i in range(columns)
    ) if columns else ""

    body: list[str] = []

    # Title band: one merged, centred cell across the table width. Only the
    # top-left cell carries the value; Excel needs the rest present but empty.
    title_cells = [_cell(first_col, title_row, spec.title, STYLE_TITLE)]
    title_cells += [
        _cell(col, title_row, "", STYLE_TITLE)
        for col in range(first_col + 1, last_col + 1)
    ]
    body.append(f'<row r="{title_row}">{"".join(title_cells)}</row>')

    # Header band.
    header_cells = "".join(
        _cell(first_col + i, header_row, spec.header[i], STYLE_HEADER)
        for i in range(columns)
    )
    body.append(f'<row r="{header_row}">{header_cells}</row>')

    # Data rows.
    for offset, row in enumerate(spec.rows, start=1):
        row_number = header_row + offset
        cells = "".join(
            _cell(
                first_col + i, row_number,
                row[i] if i < len(row) else "",
                STYLE_CELL,
            )
            for i in range(columns)
        )
        body.append(f'<row r="{row_number}">{cells}</row>')

    merge = ""
    if columns > 1:
        merge = (
            '<mergeCells count="1">'
            f'<mergeCell ref="{_column_ref(first_col)}{title_row}:'
            f'{_column_ref(last_col)}{title_row}"/>'
            '</mergeCells>'
        )
    elif columns == 1:
        # A single-column table still gets a proper title cell, just not merged.
        merge = ""

    cols_block = f"<cols>{cols_xml}</cols>" if cols_xml else ""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'{cols_block}'
        f'<sheetData>{"".join(body)}</sheetData>'
        f'{merge}'
        '</worksheet>'
    )


# Style table: fills, fonts, borders and the cellXfs records that combine them.
# Kept as a literal so the indexes above stay in lock-step with the records.
_STYLES_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="2">'
    '<font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font>'
    '</fonts>'
    '<fills count="4">'
    '<fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill>'
    # index 2: light green (title), index 3: light yellow (header)
    '<fill><patternFill patternType="solid"><fgColor rgb="FFD9EAD3"/><bgColor indexed="64"/></patternFill></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFFFF2CC"/><bgColor indexed="64"/></patternFill></fill>'
    '</fills>'
    '<borders count="2">'
    '<border><left/><right/><top/><bottom/><diagonal/></border>'
    '<border>'
    '<left style="thin"><color rgb="FF9CA3AF"/></left>'
    '<right style="thin"><color rgb="FF9CA3AF"/></right>'
    '<top style="thin"><color rgb="FF9CA3AF"/></top>'
    '<bottom style="thin"><color rgb="FF9CA3AF"/></bottom>'
    '<diagonal/></border>'
    '</borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="4">'
    # 0 default
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    # 1 title: bold, green fill, centred
    '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1">'
    '<alignment horizontal="center" vertical="center"/></xf>'
    # 2 header: bold, yellow fill, bordered, centred
    '<xf numFmtId="0" fontId="1" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1">'
    '<alignment horizontal="center" vertical="center" wrapText="1"/></xf>'
    # 3 data: bordered, top-aligned, wrapped
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1">'
    '<alignment vertical="top" wrapText="1"/></xf>'
    '</cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    '</styleSheet>'
)


def _package(
    named: list[tuple[str, str]],
    *,
    with_styles: bool,
) -> bytes:
    """Zip the shared workbook parts around already-rendered sheet XML.

    `named` is a list of `(sheet_name, sheet_xml)` pairs.
    """
    count = len(named)
    style_override = (
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        if with_styles else ""
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        + style_override
        + "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, count + 1)
        )
        + "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    sheet_tags = "".join(
        f'<sheet name={quoteattr(name)} sheetId="{i}" r:id="rId{i}"/>'
        for i, (name, _xml) in enumerate(named, start=1)
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets>{sheet_tags}</sheets></workbook>'
    )
    # Worksheet relationships are rId1..rIdN; the styles part (if any) takes the
    # next free id so it never collides with a worksheet id.
    style_rel = ""
    if with_styles:
        style_rel = (
            f'<Relationship Id="rId{count + 1}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
            'Target="styles.xml"/>'
        )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            f'<Relationship Id="rId{i}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, count + 1)
        )
        + style_rel
        + "</Relationships>"
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        if with_styles:
            archive.writestr("xl/styles.xml", _STYLES_XML)
        for i, (_name, sheet_xml) in enumerate(named, start=1):
            archive.writestr(f"xl/worksheets/sheet{i}.xml", sheet_xml)
    return buffer.getvalue()


def build_workbook(sheets: list[tuple[str, list[list[object]]]]) -> bytes:
    """Build a plain XLSX workbook from `(sheet_name, rows)` pairs.

    Each `rows` entry is a list of rows, and each row is a list of cell values.
    All cells are written as inline strings, with no styling.
    """
    if not sheets:
        sheets = [("Лист1", [])]
    used: set[str] = set()
    named = [
        (_safe_sheet_name(name, used), _plain_sheet_xml(rows))
        for name, rows in sheets
    ]
    return _package(named, with_styles=False)


def build_styled_workbook(sheets: list[SheetSpec]) -> bytes:
    """Build a formatted XLSX workbook from :class:`SheetSpec` sheets.

    Each sheet gets a merged, centred, light-green title band, a bold
    light-yellow header band, thin borders around the table and auto-sized
    columns.
    """
    if not sheets:
        sheets = [SheetSpec(name="Лист1", title="", header=[])]
    used: set[str] = set()
    named = [
        (_safe_sheet_name(spec.name, used), _styled_sheet_xml(spec))
        for spec in sheets
    ]
    return _package(named, with_styles=True)
