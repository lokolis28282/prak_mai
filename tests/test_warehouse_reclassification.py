import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts.reclassify_warehouse_cards import (
    apply_plan,
    build_plan,
    readonly_connection,
    sha256_file,
)


class WarehouseReclassificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db_path = self.root / "warehouse.db"
        with closing(sqlite3.connect(self.db_path)) as db:
            db.executescript(
                """
                CREATE TABLE stock_receipts(
                    id INTEGER PRIMARY KEY,
                    item_name TEXT NOT NULL,
                    vendor TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    serial_number TEXT NOT NULL DEFAULT '',
                    equipment_type TEXT NOT NULL DEFAULT '',
                    component_type TEXT NOT NULL DEFAULT '',
                    cable_type TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE audit_log(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_date TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                    action TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL DEFAULT '',
                    details TEXT NOT NULL DEFAULT '',
                    author TEXT NOT NULL DEFAULT 'system'
                );
                CREATE TABLE reference_domains_v2(
                    id INTEGER PRIMARY KEY,
                    domain_key TEXT NOT NULL
                );
                CREATE TABLE reference_values_v2(
                    id INTEGER PRIMARY KEY,
                    domain_id INTEGER NOT NULL,
                    display_name TEXT NOT NULL,
                    active INTEGER NOT NULL,
                    approval_status TEXT NOT NULL,
                    FOREIGN KEY(domain_id) REFERENCES reference_domains_v2(id)
                );
                INSERT INTO reference_domains_v2 VALUES
                    (1,'equipment_type'),(2,'component_type'),(3,'cable_type');
                INSERT INTO reference_values_v2 VALUES
                    (1,1,'Система хранения данных',1,'APPROVED'),
                    (2,2,'SSD',1,'APPROVED'),
                    (3,2,'Прочий компонент',1,'APPROVED'),
                    (4,3,'DAC',1,'APPROVED'),
                    (5,3,'AOC',1,'APPROVED'),
                    (6,2,'Трансивер',1,'APPROVED');
                """
            )
            db.executemany(
                """INSERT INTO stock_receipts(
                       id,item_name,vendor,model,serial_number,
                       equipment_type,component_type,cable_type
                   ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    (1, "Полка JBOD 12x20TB HDD", "AIC", "JBOD", "JBOD-1", "", "HDD", ""),
                    (2, "Трансивер Huawei QSFP-DD-400G-CU1M", "Huawei", "QSFP-DD-400G-CU1M", "DAC-1", "", "Трансивер", ""),
                    (3, "Компонент MICRON 7500 PRO", "Micron", "7500 PRO", "SSD-1", "", "SSD", ""),
                    (4, "Историческая позиция — требуется классификация", "", "", "UNKNOWN-1", "", "Прочий компонент", ""),
                    (5, "Трансивер Modultech MT-QSFP-100G-AOC", "Modultech", "MT-QSFP-100G-AOC", "AOC-1", "", "Трансивер", ""),
                    (6, "Историческая позиция — требуется классификация", "", "", "PROVENANCE-1", "", "Прочий компонент", ""),
                    (7, "Историческая позиция — требуется классификация", "", "", "CONFLICT-1", "", "Прочий компонент", ""),
                ),
            )
            db.execute(
                """INSERT INTO audit_log(action,entity_type,entity_id,details,author)
                   VALUES('MIGRATION_SOURCE_ROW_LINKED','stock_receipt','2',?,'migration')""",
                (json.dumps({
                    "source_item_name": "DAC-кабель Huawei QSFP-DD-400G-CU1M p/n: 02314WUG"
                }, ensure_ascii=False),),
            )
            db.execute(
                """INSERT INTO audit_log(action,entity_type,entity_id,details,author)
                   VALUES('MIGRATION_SOURCE_ROW_LINKED','stock_receipt','5',?,'migration')""",
                (json.dumps({
                    "source_item_name": "AOC-кабель Modultech MT-QSFP-100G-AOC"
                }, ensure_ascii=False),),
            )
            db.execute(
                """INSERT INTO audit_log(action,entity_type,entity_id,details,author)
                   VALUES('MIGRATION_SOURCE_ROW_LINKED','stock_receipt','6',?,'migration')""",
                (json.dumps({
                    "source_item_name": "Трансивер Huawei SFP-25G-SR"
                }, ensure_ascii=False),),
            )
            db.executemany(
                """INSERT INTO audit_log(action,entity_type,entity_id,details,author)
                   VALUES('MIGRATION_SOURCE_ROW_LINKED','stock_receipt','7',?,'migration')""",
                (
                    (json.dumps({"source_item_name": "Трансивер Huawei SFP-25G-SR"}, ensure_ascii=False),),
                    (json.dumps({"source_item_name": "DAC-кабель Huawei CU1M"}, ensure_ascii=False),),
                ),
            )
            db.commit()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_plan_is_high_confidence_and_preserves_unresolved_rows(self) -> None:
        with closing(readonly_connection(self.db_path)) as db:
            plan = build_plan(db)
        self.assertEqual([change["receipt_id"] for change in plan], [1, 2, 5, 6])
        self.assertEqual(plan[0]["type_after"]["equipment_type"], "Система хранения данных")
        self.assertEqual(plan[1]["type_after"]["cable_type"], "DAC")
        self.assertEqual(
            plan[1]["item_name_after"], "DAC-кабель Huawei QSFP-DD-400G-CU1M"
        )
        self.assertEqual(plan[1]["model_after"], "QSFP-DD-400G-CU1M")
        self.assertEqual(plan[2]["type_after"]["cable_type"], "AOC")
        self.assertEqual(
            plan[2]["item_name_after"], "AOC-кабель Modultech MT-QSFP-100G-AOC"
        )
        self.assertEqual(plan[3]["type_after"]["component_type"], "Трансивер")
        self.assertEqual(plan[3]["rule"], "PROVENANCE_TRANSCEIVER")

    def test_apply_is_audited_atomic_and_idempotent(self) -> None:
        before_sha = sha256_file(self.db_path)
        report = apply_plan(
            self.db_path,
            expected_sha256=before_sha,
            manifest_path=self.root / "manifest.json",
            author="test",
        )
        self.assertEqual(report["changed_cards"], 4)
        self.assertNotEqual(report["before_sha256"], report["after_sha256"])
        with closing(sqlite3.connect(self.db_path)) as db:
            db.row_factory = sqlite3.Row
            rows = {row["id"]: row for row in db.execute(
                "SELECT * FROM stock_receipts ORDER BY id"
            )}
            self.assertEqual(rows[1]["equipment_type"], "Система хранения данных")
            self.assertEqual(rows[1]["component_type"], "")
            self.assertEqual(rows[2]["cable_type"], "DAC")
            self.assertEqual(rows[2]["item_name"], "DAC-кабель Huawei QSFP-DD-400G-CU1M")
            self.assertEqual(rows[2]["model"], "QSFP-DD-400G-CU1M")
            self.assertEqual(rows[2]["serial_number"], "DAC-1")
            self.assertEqual(rows[3]["component_type"], "SSD")
            self.assertEqual(rows[4]["component_type"], "Прочий компонент")
            self.assertEqual(rows[5]["cable_type"], "AOC")
            self.assertEqual(
                rows[5]["item_name"], "AOC-кабель Modultech MT-QSFP-100G-AOC"
            )
            self.assertEqual(rows[6]["component_type"], "Трансивер")
            self.assertEqual(rows[7]["component_type"], "Прочий компонент")
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM audit_log WHERE action='WAREHOUSE_CARD_RECLASSIFIED'"
                ).fetchone()[0],
                4,
            )
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM audit_log WHERE action='WAREHOUSE_RECLASSIFICATION_COMPLETED'"
                ).fetchone()[0],
                1,
            )
        self.assertTrue((self.root / "manifest.json").is_file())
        with closing(readonly_connection(self.db_path)) as db:
            self.assertEqual(build_plan(db), [])


if __name__ == "__main__":
    unittest.main()
