"""Minimal read-only XLSX parser built on the standard library.

The project ships without third-party dependencies, so `openpyxl` is not
available. An XLSX file is a ZIP container of XML parts; this module reads the
shared string table and worksheet cells directly. Only the subset needed to
import flat work-log sheets is implemented: shared/inline strings, numeric
cells and Excel serial dates.
"""

from __future__ import annotations

import datetime as _dt
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_PKG = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

# Excel stores dates as days since 1899-12-30 (the well known 1900 leap-year bug
# is absorbed by using 1899-12-30 as the epoch).
_EXCEL_EPOCH = _dt.date(1899, 12, 30)

MAX_XLSX_BYTES = 50 * 1024 * 1024


class XlsxError(ValueError):
    """Raised when an XLSX file cannot be read as a flat table."""


def column_index(cell_ref: str) -> int:
    """Convert an A1-style reference to a zero-based column index (A->0, AA->26)."""
    letters = re.match(r"[A-Za-z]+", cell_ref or "")
    index = 0
    for char in (letters.group(0).upper() if letters else ""):
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index - 1


def excel_serial_to_iso(value: str) -> str:
    """Convert an Excel serial day number to an ISO date, or return value as-is."""
    text = str(value or "").strip()
    if not re.fullmatch(r"\d+(\.0+)?", text):
        return text
    serial = int(float(text))
    # Plausible spreadsheet date range only; small integers are left untouched so
    # that genuine numeric task fragments are not mistaken for dates.
    if serial < 1 or serial > 60_000:
        return text
    return (_EXCEL_EPOCH + _dt.timedelta(days=serial)).isoformat()


def _load_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(node.text or "" for node in si.iter(f"{_MAIN}t")) for si in root]


def _sheet_targets(archive: zipfile.ZipFile) -> dict[str, str]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rid_to_target = {
        rel.get("Id"): "xl/" + rel.get("Target").lstrip("/")
        for rel in rels.findall(f"{_PKG}Relationship")
    }
    sheets: dict[str, str] = {}
    for sheet in workbook.find(f"{_MAIN}sheets"):
        target = rid_to_target.get(sheet.get(f"{_REL}id"))
        if target:
            sheets[str(sheet.get("name"))] = target
    return sheets


def _cell_value(cell: ET.Element, shared: list[str]) -> str:
    cell_type = cell.get("t", "")
    value = cell.find(f"{_MAIN}v")
    if cell_type == "s" and value is not None and value.text is not None:
        try:
            return shared[int(value.text)]
        except (ValueError, IndexError):
            return ""
    if cell_type == "inlineStr":
        inline = cell.find(f"{_MAIN}is")
        if inline is not None:
            return "".join(node.text or "" for node in inline.iter(f"{_MAIN}t"))
    return value.text if value is not None and value.text is not None else ""


def sheet_names(source: str | Path | bytes) -> list[str]:
    with _open(source) as archive:
        return list(_sheet_targets(archive))


def read_sheet(source: str | Path | bytes, sheet_name: str) -> list[list[str]]:
    """Return the worksheet as a dense list of string rows."""
    with _open(source) as archive:
        targets = _sheet_targets(archive)
        target = targets.get(sheet_name)
        if target is None:
            raise XlsxError(
                f"Лист «{sheet_name}» не найден. Доступные листы: "
                + ", ".join(targets) if targets else f"Лист «{sheet_name}» не найден"
            )
        shared = _load_shared_strings(archive)
        root = ET.fromstring(archive.read(target))
        sheet_data = root.find(f"{_MAIN}sheetData")
        rows: list[list[str]] = []
        for row in sheet_data.findall(f"{_MAIN}row") if sheet_data is not None else []:
            cells: dict[int, str] = {}
            for cell in row.findall(f"{_MAIN}c"):
                cells[column_index(cell.get("r", ""))] = _cell_value(cell, shared)
            width = (max(cells) + 1) if cells else 0
            rows.append([cells.get(i, "") for i in range(width)])
        return rows


def _open(source: str | Path | bytes) -> zipfile.ZipFile:
    try:
        if isinstance(source, (bytes, bytearray)):
            import io

            return zipfile.ZipFile(io.BytesIO(source))
        return zipfile.ZipFile(source)
    except zipfile.BadZipFile as error:
        raise XlsxError("Файл не является корректным XLSX-документом") from error
