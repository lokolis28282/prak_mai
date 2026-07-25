from __future__ import annotations

import unittest

from inventory.importing import parse_csv_bytes


class InventoryNumberImportCsvUnitTest(unittest.TestCase):
    def test_utf8_bom_semicolon_and_comma_use_only_two_canonical_fields(self) -> None:
        cases = (
            (
                "semicolon",
                (
                    "Serial Number;Inventory Number;Ignored\n"
                    " sn-unit-1 ; inv-unit-1 ;value\n"
                ).encode("utf-8-sig"),
            ),
            (
                "comma",
                (
                    "S/N,\u0418\u043d\u0432\u0435\u043d\u0442\u0430\u0440\u043d\u044b\u0439 \u043d\u043e\u043c\u0435\u0440\n"
                    "SN-UNIT-2,INV-UNIT-2\n"
                ).encode("utf-8"),
            ),
        )

        for name, body in cases:
            with self.subTest(name=name):
                rows = parse_csv_bytes(body, "inventory_numbers")

                self.assertEqual(len(rows), 1)
                self.assertEqual(
                    set(rows[0]), {"serial_number", "inventory_number"}
                )
                self.assertEqual(
                    rows[0],
                    {
                        "serial_number": (
                            "sn-unit-1" if name == "semicolon" else "SN-UNIT-2"
                        ),
                        "inventory_number": (
                            "inv-unit-1" if name == "semicolon" else "INV-UNIT-2"
                        ),
                    },
                )

    def test_both_columns_are_required(self) -> None:
        cases = (
            ("Inventory Number\nINV-ONLY\n", "S/N"),
            ("Serial Number\nSN-ONLY\n", "\u0418\u043d\u0432\u0435\u043d\u0442\u0430\u0440\u043d\u044b\u0439 \u043d\u043e\u043c\u0435\u0440"),
        )

        for text, missing_label in cases:
            with self.subTest(missing_label=missing_label):
                with self.assertRaisesRegex(
                    ValueError, f"\u041d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d \u043e\u0431\u044f\u0437\u0430\u0442\u0435\u043b\u044c\u043d\u044b\u0439 \u0441\u0442\u043e\u043b\u0431\u0435\u0446: {missing_label}"
                ):
                    parse_csv_bytes(text.encode("utf-8"), "inventory_numbers")


if __name__ == "__main__":
    unittest.main()
