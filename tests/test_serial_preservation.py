from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

from inventory.migration.serial_preservation import (
    PreservationStatus,
    SerialColumnSpec,
    extract_serial_cells,
    normalize_serial_match,
)
from inventory.migration.xlsx_cells import (
    iter_xlsx_cells,
    read_text_csv,
    read_text_xlsx,
    write_text_csv,
    write_text_xlsx,
)


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


TEXT_SERIALS = (
    "00012345",
    "001A020",
    "0000000000000001",
    "2102313CKX10LC000033",
    "СЕРИЯ-0001",
    "AС-001",  # Latin A, Cyrillic С.
    "AB  12",
)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_numeric_fixture(path: Path) -> None:
    """Create a small independent OOXML fixture with exact literal tokens."""
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '<Override PartName="/xl/sharedStrings.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        '</Types>'
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Relationships xmlns="{REL_NS}">'
        f'<Relationship Id="rId1" Type="{DOC_REL_NS}/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<workbook xmlns="{MAIN_NS}" xmlns:r="{DOC_REL_NS}">'
        '<sheets><sheet name="SERIALS" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Relationships xmlns="{REL_NS}">'
        f'<Relationship Id="rId1" Type="{DOC_REL_NS}/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        f'<Relationship Id="rId2" Type="{DOC_REL_NS}/styles" Target="styles.xml"/>'
        f'<Relationship Id="rId3" Type="{DOC_REL_NS}/sharedStrings" '
        'Target="sharedStrings.xml"/>'
        '</Relationships>'
    )
    styles = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<styleSheet xmlns="{MAIN_NS}">'
        '<numFmts count="1"><numFmt numFmtId="164" formatCode="00000000"/></numFmts>'
        '<fonts count="1"><font/></fonts><fills count="1"><fill/></fills>'
        '<borders count="1"><border/></borders>'
        '<cellXfs count="3">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>'
        '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" applyNumberFormat="1"/>'
        '<xf numFmtId="2" fontId="0" fillId="0" borderId="0" applyNumberFormat="1"/>'
        '</cellXfs></styleSheet>'
    )
    shared_strings = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<sst xmlns="{MAIN_NS}" count="1" uniqueCount="1">'
        '<si><t xml:space="preserve">  001A020  </t></si></sst>'
    )
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<worksheet xmlns="{MAIN_NS}"><sheetData>'
        '<row r="1"><c r="A1" t="inlineStr"><is><t>S/N</t></is></c></row>'
        '<row r="2"><c r="A2" s="1"><v>12345</v></c></row>'
        '<row r="3"><c r="A3"><v>1.2345E7</v></c></row>'
        '<row r="4"><c r="A4"><v>1.234567890123456E15</v></c></row>'
        '<row r="5"><c r="A5"><v>1234567890123456</v></c></row>'
        '<row r="6"><c r="A6"><v>1.25</v></c></row>'
        '<row r="7"><c r="A7" t="str"><f>"000123"</f><v>000123</v></c></row>'
        '<row r="8"><c r="A8" t="s"><v>0</v></c></row>'
        '<row r="9"><c r="A9" s="2"><v>12345</v></c></row>'
        '<row r="10"><c r="A10"><v>12345</v></c></row>'
        '</sheetData></worksheet>'
    )
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/styles.xml", styles)
        archive.writestr("xl/sharedStrings.xml", shared_strings)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)


class SerialNormalizationTest(unittest.TestCase):
    def test_match_normalization_does_not_change_internal_content(self) -> None:
        value = " \u200bＡB  12-СН\u2060 "

        self.assertEqual(normalize_serial_match(value), "ab  12-сн")
        self.assertNotEqual(normalize_serial_match("001234567"), "1234567")
        self.assertNotEqual(normalize_serial_match("AB-12"), "ab12")
        self.assertNotEqual(normalize_serial_match("AС-1"), "ac-1")

    def test_non_string_match_value_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            normalize_serial_match(12345)  # type: ignore[arg-type]


class XlsxSerialExtractionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "source.xlsx"
        write_numeric_fixture(self.path)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def records(self):
        return {
            record.source_row: record
            for record in extract_serial_cells(
                self.path,
                [SerialColumnSpec("SERIALS", "A", "receipt", first_row=2)],
            )
        }

    def test_custom_zero_format_recovers_leading_zeroes_for_review(self) -> None:
        record = self.records()[2]

        self.assertEqual(record.raw_xml_value, "12345")
        self.assertEqual(record.excel_number_format, "00000000")
        self.assertEqual(record.source_display_value, "00012345")
        self.assertEqual(record.source_serial_value, "00012345")
        self.assertEqual(record.normalized_match_value, "")
        self.assertEqual(
            record.preservation_status,
            PreservationStatus.NUMERIC_FORMAT_RECOVERED.value,
        )
        self.assertTrue(record.requires_manual_review)
        self.assertIn("CUSTOM_ZERO_FORMAT:00000000", record.normalization_rule)
        self.assertIn("LEADING_ZEROS_RECOVERED", record.warning)

    def test_scientific_token_is_preserved_and_requires_manual_decision(self) -> None:
        record = self.records()[3]

        self.assertEqual(record.raw_xml_value, "1.2345E7")
        self.assertEqual(record.source_display_value, "12345000")
        self.assertEqual(record.source_serial_value, "1.2345E7")
        self.assertEqual(record.normalized_match_value, "")
        self.assertEqual(
            record.preservation_status,
            PreservationStatus.NUMERIC_FORMAT_UNPROVEN.value,
        )
        self.assertTrue(record.requires_manual_review)
        self.assertIn("RAW_EXPONENT_TOKEN_PRESERVED", record.warning)

    def test_numeric_identifiers_over_fifteen_digits_are_corrupted(self) -> None:
        records = self.records()

        for row in (4, 5):
            with self.subTest(row=row):
                self.assertEqual(
                    records[row].preservation_status,
                    PreservationStatus.SOURCE_CORRUPTED.value,
                )
                self.assertEqual(records[row].normalized_match_value, "")
                self.assertTrue(records[row].requires_manual_review)
                self.assertIn("PRECISION_NOT_PROVABLE", records[row].warning)
        self.assertEqual(records[4].source_serial_value, "1.234567890123456E15")
        self.assertEqual(records[5].source_serial_value, "1234567890123456")

    def test_fraction_formula_and_unproven_format_never_get_match_keys(self) -> None:
        records = self.records()

        self.assertEqual(records[6].preservation_status, PreservationStatus.SOURCE_CORRUPTED.value)
        self.assertEqual(records[7].preservation_status, PreservationStatus.FORMULA_UNSAFE.value)
        self.assertEqual(
            records[9].preservation_status,
            PreservationStatus.NUMERIC_FORMAT_UNPROVEN.value,
        )
        for row in (6, 7, 9):
            self.assertEqual(records[row].normalized_match_value, "")
            self.assertTrue(records[row].requires_manual_review)

    def test_plain_numeric_identifier_is_never_auto_matched(self) -> None:
        record = self.records()[10]

        self.assertEqual(record.source_display_value, "12345")
        self.assertEqual(record.source_serial_value, "12345")
        self.assertEqual(record.normalized_match_value, "")
        self.assertEqual(
            record.preservation_status,
            PreservationStatus.NUMERIC_FORMAT_UNPROVEN.value,
        )
        self.assertTrue(record.requires_manual_review)
        self.assertIn("LEADING_ZERO_HISTORY_NOT_PROVABLE", record.warning)

    def test_shared_string_keeps_source_spaces_and_only_match_is_trimmed(self) -> None:
        record = self.records()[8]

        self.assertEqual(record.raw_xml_value, "0")
        self.assertEqual(record.source_display_value, "  001A020  ")
        self.assertEqual(record.source_serial_value, "  001A020  ")
        self.assertEqual(record.normalized_match_value, "001a020")
        self.assertEqual(record.preservation_status, PreservationStatus.TEXT_EXACT.value)
        self.assertIn("EXTERNAL_WHITESPACE", record.warning)

    def test_extraction_is_read_only_and_hashes_each_cell_provenance(self) -> None:
        before = file_hash(self.path)
        records = self.records()
        after = file_hash(self.path)

        self.assertEqual(before, after)
        self.assertTrue(all(record.source_file_hash == before for record in records.values()))
        self.assertEqual(len({record.source_hash for record in records.values()}), len(records))
        self.assertTrue(all(len(record.source_hash) == 64 for record in records.values()))


class IdentifierOutputRoundTripTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_xlsx_identifier_round_trip_is_inline_text_with_at_format(self) -> None:
        path = self.directory / "identifiers.xlsx"
        rows = [
            {"serial_number": serial, "inventory_number": f"INV-{index:04d}"}
            for index, serial in enumerate(TEXT_SERIALS, start=1)
        ]

        write_text_xlsx(
            path,
            {"SERIALS": (["serial_number", "inventory_number"], rows)},
            {"SERIALS": {"serial_number", "inventory_number"}},
        )

        round_trip = read_text_xlsx(path)["SERIALS"]
        self.assertEqual([row["serial_number"] for row in round_trip], list(TEXT_SERIALS))
        cells = [
            cell
            for cell in iter_xlsx_cells(path, sheet_names={"SERIALS"})
            if cell.source_row > 1
        ]
        self.assertTrue(cells)
        self.assertTrue(all(cell.excel_cell_type == "inlineStr" for cell in cells))
        self.assertTrue(all(cell.excel_number_format == "@" for cell in cells))
        self.assertEqual(
            [cell.source_display_value for cell in cells if cell.source_column == "A"],
            list(TEXT_SERIALS),
        )
        preserved = extract_serial_cells(
            path,
            [SerialColumnSpec("SERIALS", "A", "round_trip", first_row=2)],
        )
        self.assertEqual(
            [record.source_serial_value for record in preserved],
            list(TEXT_SERIALS),
        )
        self.assertTrue(
            all(
                record.preservation_status == PreservationStatus.TEXT_EXACT.value
                for record in preserved
            )
        )
        self.assertEqual(preserved[2].source_serial_value, "0000000000000001")
        self.assertNotEqual(preserved[5].normalized_match_value, "ac-001")
        self.assertEqual(preserved[6].normalized_match_value, "ab  12")

    def test_csv_machine_round_trip_keeps_exact_identifier_characters(self) -> None:
        path = self.directory / "identifiers.csv"
        rows = [{"serial_number": serial} for serial in TEXT_SERIALS]

        write_text_csv(path, ["serial_number"], rows)

        self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertEqual(
            [row["serial_number"] for row in read_text_csv(path)],
            list(TEXT_SERIALS),
        )

    def test_writers_reject_numeric_identifier_inputs(self) -> None:
        with self.assertRaises(TypeError):
            write_text_xlsx(
                self.directory / "bad.xlsx",
                {"SERIALS": (["serial_number"], [{"serial_number": 12345}])},
                {"serial_number"},
            )
        with self.assertRaises(TypeError):
            write_text_csv(
                self.directory / "bad.csv",
                ["serial_number"],
                [{"serial_number": 12345}],
                {"serial_number"},
            )


if __name__ == "__main__":
    unittest.main()
