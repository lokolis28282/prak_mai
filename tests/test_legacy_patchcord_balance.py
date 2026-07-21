from contextlib import closing
import hashlib
import sqlite3
from pathlib import Path
import tempfile
import unittest

from scripts.restore_legacy_patchcord_balance import apply_plan, build_plan, sha256_file


class LegacyPatchcordBalanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temporary.name) / "warehouse.db"
        with closing(sqlite3.connect(self.db_path)) as db:
            db.executescript("""
                CREATE TABLE migration_full_reconciliation(
                    id INTEGER PRIMARY KEY,operation_kind TEXT,source_item_name TEXT,
                    canonical_item_name TEXT,quantity TEXT,source_row_hash TEXT,
                    final_status TEXT
                );
                CREATE TABLE stock_receipts(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,receipt_date TEXT,responsible TEXT,
                    item_name TEXT,project TEXT,serial_number TEXT,inventory_number TEXT,
                    supplier TEXT,vendor TEXT,model TEXT,shelf TEXT,object_name TEXT,
                    datacenter TEXT,equipment_type TEXT,component_type TEXT,cable_type TEXT,
                    unit TEXT,quantity REAL,is_opening_balance INTEGER
                );
                CREATE TABLE audit_log(id INTEGER PRIMARY KEY,action TEXT,entity_type TEXT,
                    entity_id TEXT,details TEXT,author TEXT);
                CREATE TABLE reference_domains_v2(id INTEGER PRIMARY KEY,domain_key TEXT);
                CREATE TABLE reference_values_v2(id INTEGER PRIMARY KEY,domain_id INTEGER,
                    display_name TEXT,active INTEGER,approval_status TEXT);
                INSERT INTO reference_domains_v2 VALUES(1,'cable_type');
                INSERT INTO reference_values_v2 VALUES(1,1,'UTP',1,'APPROVED'),(2,1,'OM4',1,'APPROVED');
            """)
            rows = [
                (1,'RECEIPT','патч-корд UTP 2м','патч-корд UTP 2м','100','a'*64,'QUANTITY_DEFERRED'),
                (2,'ISSUE','патч-корд UTP 2м','патч-корд UTP 2м','30','b'*64,'QUANTITY_DEFERRED'),
                (3,'RECEIPT','патч-корд оптический ОМ4 3м','патч-корд оптический ОМ4 3м','50','c'*64,'QUANTITY_DEFERRED'),
                (4,'RECEIPT','MTP патч-корд OM4 3м','MTP патч-корд OM4 3м','999','d'*64,'QUANTITY_DEFERRED'),
            ]
            db.executemany("INSERT INTO migration_full_reconciliation VALUES(?,?,?,?,?,?,?)", rows)
            db.commit()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_plan_is_strict_and_net_of_issues(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as db:
            db.row_factory = sqlite3.Row
            plan = build_plan(db)
        self.assertEqual([(row['item_name'], row['quantity']) for row in plan], [
            ('Патчкорд UTP 2м', '70'), ('Патчкорд оптический OM4 3м', '50')
        ])

    def test_apply_is_audited_and_idempotent(self) -> None:
        report = apply_plan(
            self.db_path, expected_sha256=sha256_file(self.db_path),
            manifest_path=Path(self.temporary.name) / "manifest.json", author="test",
        )
        self.assertEqual(report['positions'], 2)
        self.assertEqual(report['quantity'], '120')
        with closing(sqlite3.connect(self.db_path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM stock_receipts").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM audit_log WHERE action='LEGACY_PATCHCORD_BASELINE_PUBLISHED'").fetchone()[0], 1)
        with self.assertRaisesRegex(RuntimeError, "уже опубликован"):
            apply_plan(self.db_path, expected_sha256=sha256_file(self.db_path),
                       manifest_path=Path(self.temporary.name) / "manifest-2.json", author="test")


if __name__ == "__main__":
    unittest.main()
