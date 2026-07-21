from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from inventory.core.application import create_application_context
from inventory.db import connect
from inventory.service import WarehouseError, WarehouseService


class DeliveryBulkSelectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "warehouse.db"
        self.service = WarehouseService(self.db_path)
        self.context = create_application_context(
            self.db_path, service=self.service, warehouse_contour="demo"
        )
        with connect(self.db_path) as db:
            delivery_id = db.execute(
                """INSERT INTO deliveries(
                       source_filename,delivery_number,supplier,status,uploaded_by
                   ) VALUES ('bulk.csv','BULK-1','Supplier','Ожидается','Test')"""
            ).lastrowid
            db.execute("PRAGMA ignore_check_constraints=ON")
            for row_number, state in enumerate(
                ("Ожидается", "Принято", "Уже на складе", " ожидается ", "ОЖИДАЕТСЯ"),
                start=1,
            ):
                db.execute(
                    """INSERT INTO delivery_lines(
                           delivery_id,row_number,serial_number,item_name,state
                       ) VALUES (?,?,?,?,?)""",
                    (delivery_id, row_number, f"SEL-{row_number}", "Server", state),
                )
            self.delivery_id = int(delivery_id)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_selection_returns_every_id_and_normalized_waiting_ids(self) -> None:
        result = self.context.warehouse.get_delivery_selection(self.delivery_id)
        self.assertEqual(result["delivery_id"], self.delivery_id)
        self.assertEqual(len(result["all_ids"]), 5)
        self.assertEqual(result["waiting_ids"], [
            result["all_ids"][0], result["all_ids"][3], result["all_ids"][4]
        ])

    def test_empty_delivery_and_unknown_delivery_are_safe(self) -> None:
        with connect(self.db_path) as db:
            empty_id = db.execute(
                """INSERT INTO deliveries(
                       source_filename,delivery_number,supplier,status,uploaded_by
                   ) VALUES ('empty.csv','EMPTY','Supplier','Ожидается','Test')"""
            ).lastrowid
        self.assertEqual(
            self.context.warehouse.get_delivery_selection(int(empty_id)),
            {"delivery_id": int(empty_id), "all_ids": [], "waiting_ids": []},
        )
        with self.assertRaises(WarehouseError):
            self.context.warehouse.get_delivery_selection(999999)

    def test_selection_is_not_limited_to_the_visible_page(self) -> None:
        with connect(self.db_path) as db:
            waiting_state, accepted_state = [
                row[0]
                for row in db.execute(
                    "SELECT state FROM delivery_lines WHERE delivery_id=? ORDER BY row_number LIMIT 2",
                    (self.delivery_id,),
                ).fetchall()
            ]
            delivery_status = db.execute(
                "SELECT status FROM deliveries WHERE id=?", (self.delivery_id,)
            ).fetchone()[0]
            large_delivery_id = db.execute(
                """INSERT INTO deliveries(
                       source_filename,delivery_number,supplier,status,uploaded_by
                   ) VALUES ('large.csv','LARGE','Supplier',?,'Test')""",
                (delivery_status,),
            ).lastrowid
            db.executemany(
                """INSERT INTO delivery_lines(
                       delivery_id,row_number,serial_number,item_name,state
                   ) VALUES (?,?,?,?,?)""",
                [
                    (
                        large_delivery_id,
                        row_number,
                        f"LARGE-{row_number}",
                        "Server",
                        waiting_state if row_number % 2 else accepted_state,
                    )
                    for row_number in range(1, 621)
                ],
            )

        result = self.context.warehouse.get_delivery_selection(int(large_delivery_id))
        self.assertEqual(len(result["all_ids"]), 620)
        self.assertEqual(len(result["waiting_ids"]), 310)
        self.assertTrue(set(result["waiting_ids"]).issubset(result["all_ids"]))


if __name__ == "__main__":
    unittest.main()
