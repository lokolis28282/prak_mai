from __future__ import annotations

from contextlib import closing
from decimal import Decimal
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile
import unittest
from xml.etree import ElementTree
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parent.parent
CANDIDATE = ROOT / "migration_inputs/workspace/warehouse_full_candidate.db"
PRODUCTION = ROOT / "data/warehouse.db"
REPORT = ROOT / "migration_inputs/reports/FULL_WAREHOUSE_MIGRATION_REPORT.xlsx"
CLEAN_REPORT = ROOT / "migration_inputs/reports/FULL_WAREHOUSE_OPERATIONAL_CLEANLINESS.xlsx"

# Import the application composition root first; inventory.warehouse's package
# exports intentionally depend on that established import order.
import inventory.core.application as _application_wiring  # noqa: E402,F401
from inventory.migration.full_builder import validate_full_database  # noqa: E402
from inventory.migration.xlsx_cells import iter_xlsx_cells, sha256_file  # noqa: E402
from inventory.service import WarehouseService  # noqa: E402
from inventory.shared.validators import WarehouseError  # noqa: E402
from inventory.webapp import make_handler  # noqa: E402
from inventory.warehouse.migration_full_review import (  # noqa: E402
    MigrationFullReviewService,
    assert_full_inventory_assignment_allowed,
    validate_full_migration_database,
)


EXPECTED_RECEIPT = {
    "CONFLICT_HISTORY_ONLY": 532,
    "EXACT_DUPLICATE": 611,
    "IMPORTED": 43_027,
    "LINKED_TO_EXISTING_IDENTITY": 65,
    "NUMERIC_PROVISIONAL_IMPORTED": 6_682,
    "QUANTITY_DEFERRED": 84,
    "SOURCE_CORRUPTED_REJECTED": 2,
}
EXPECTED_ISSUE = {
    "CONFLICT_HISTORY_ONLY": 283,
    "IMPORTED": 15_359,
    "NUMERIC_PROVISIONAL_LINKED": 3_155,
    "OPENING_STATE_CREATED": 284,
    "QUANTITY_DEFERRED": 1_274,
    "QUARANTINED": 2,
}
REQUIRED_SHEETS = {
    "SUMMARY",
    "SOURCE_ROW_RECONCILIATION",
    "RECEIPT_RESULTS",
    "ISSUE_RESULTS",
    "IDENTITIES",
    "PROVISIONAL_NUMERIC",
    "SOURCE_CORRUPTED",
    "EXACT_DUPLICATES",
    "CONFLICTS",
    "OPENING_STATES",
    "UNRESOLVED_ISSUES",
    "QUARANTINE",
    "DEFERRED_QUANTITY",
    "REFERENCES",
    "PERFORMANCE",
    "VALIDATION",
    "MANUAL_REVIEW_CHECKLIST",
}


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"{CANDIDATE.resolve().as_uri()}?mode=ro&immutable=1", uri=True
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _decimal_display(raw: str) -> str:
    value = Decimal(raw)
    integral = value.to_integral_exact()
    return format(integral, "f")


@unittest.skipUnless(CANDIDATE.is_file(), "full candidate is a local ignored artifact")
class FullMigrationCandidateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.production_sha = sha256_file(PRODUCTION)
        # After promotion, data/warehouse.db is the working descendant rather
        # than the frozen pre-build baseline. Candidate validation remains
        # self-contained; build-time baseline equality is still enforced by the
        # builder itself before it publishes this artifact.
        cls.validation = validate_full_database(CANDIDATE)
        cls.runtime_status = validate_full_migration_database(CANDIDATE, enabled=True)

    def test_marker_exact_reconciliation_and_sqlite_health(self) -> None:
        self.assertEqual(self.validation["marker"], "FULL_WAREHOUSE_CANDIDATE")
        self.assertEqual(self.validation["integrity_check"], "ok")
        self.assertEqual(self.validation["foreign_key_errors"], 0)
        self.assertEqual(self.validation["receipt_source_rows"], 51_003)
        self.assertEqual(self.validation["issue_source_rows"], 20_357)
        self.assertEqual(self.validation["reconciliation_rows"], 71_360)
        self.assertEqual(self.validation["receipt_status_counts"], EXPECTED_RECEIPT)
        self.assertEqual(self.validation["issue_status_counts"], EXPECTED_ISSUE)
        self.assertEqual(self.validation["identities"], 50_000)
        self.assertEqual(self.validation["receipts"], 50_000)
        self.assertEqual(self.validation["issues"], 18_798)
        self.assertEqual(self.validation["allocations"], 18_798)
        self.assertEqual(self.validation["opening_states"], 291)
        self.assertEqual(self.validation["provisional"], 6_689)
        self.assertEqual(self.validation["quarantine"], 4)
        self.assertEqual(self.runtime_status["status"], "READY_FOR_MANUAL_ACCEPTANCE")
        self.assertEqual(sha256_file(PRODUCTION), self.production_sha)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(CANDIDATE.stat().st_mode), 0o600)
        for suffix in ("-wal", "-shm", "-journal"):
            self.assertFalse(Path(str(CANDIDATE) + suffix).exists())

    def test_renamed_copy_runs_as_working_database_without_replaying_serial_index(self) -> None:
        source_sha = sha256_file(CANDIDATE)
        with tempfile.TemporaryDirectory(prefix="ode_promoted_full_") as directory:
            promoted = Path(directory) / "warehouse.db"
            shutil.copy2(CANDIDATE, promoted)
            status = validate_full_migration_database(promoted, enabled=False)
            self.assertTrue(status["working_database"])
            self.assertFalse(status["read_only"])
            service = WarehouseService(promoted)
            stats = service.dashboard_stats()
            self.assertEqual(stats["cards"], 50_000)
            self.assertEqual(stats["issues"], 18_798)
            self.assertGreater(len(service.references()), 800)
            initialized_sha = sha256_file(promoted)
            WarehouseService(promoted)
            self.assertEqual(sha256_file(promoted), initialized_sha)
            with closing(sqlite3.connect(promoted)) as connection:
                self.assertEqual(
                    connection.execute("PRAGMA integrity_check").fetchone()[0], "ok"
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM pragma_foreign_key_check").fetchone()[0],
                    0,
                )
        self.assertEqual(sha256_file(CANDIDATE), source_sha)

    def test_serial_preservation_identity_and_quarantine_rules(self) -> None:
        with closing(_connection()) as connection:
            leading = connection.execute(
                """SELECT i.display_serial_value, r.serial_number
                     FROM migration_full_identities i
                     JOIN stock_receipts r ON r.id=i.target_receipt_id
                    WHERE i.preservation_status='TEXT_EXACT'
                      AND i.display_serial_value GLOB '0*'
                    ORDER BY i.id LIMIT 1"""
            ).fetchone()
            self.assertIsNotNone(leading)
            self.assertTrue(str(leading["display_serial_value"]).startswith("0"))
            self.assertEqual(leading["display_serial_value"], leading["serial_number"])

            provisional = connection.execute(
                """SELECT i.display_serial_value, i.raw_xml_value,
                          i.identity_confidence, i.authoritative,
                          i.requires_manual_review, r.inventory_number
                     FROM migration_full_identities i
                     JOIN stock_receipts r ON r.id=i.target_receipt_id
                    WHERE i.preservation_status='NUMERIC_FORMAT_UNPROVEN'
                    ORDER BY i.id LIMIT 1"""
            ).fetchone()
            self.assertEqual(
                provisional["display_serial_value"],
                _decimal_display(str(provisional["raw_xml_value"])),
            )
            self.assertEqual(provisional["identity_confidence"], "PROVISIONAL")
            self.assertEqual(provisional["authoritative"], 0)
            self.assertEqual(provisional["requires_manual_review"], 1)
            self.assertEqual(provisional["inventory_number"], "")

            self.assertEqual(
                connection.execute(
                    """SELECT COUNT(*) FROM migration_full_reconciliation r
                         JOIN migration_full_identities i ON i.id=r.target_identity_id
                        WHERE r.preservation_status<>i.preservation_status"""
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute(
                    """SELECT COUNT(*) FROM migration_full_reconciliation
                        WHERE preservation_status='SOURCE_CORRUPTED'
                          AND (target_identity_id IS NOT NULL
                               OR target_receipt_id IS NOT NULL
                               OR target_issue_id IS NOT NULL)"""
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM migration_full_quarantine WHERE affects_balance<>0"
                ).fetchone()[0],
                0,
            )

        with self.assertRaisesRegex(WarehouseError, "provisional numeric identity"):
            assert_full_inventory_assignment_allowed(
                CANDIDATE, str(provisional["display_serial_value"])
            )

    def test_opening_states_clean_contour_and_operational_provenance(self) -> None:
        with closing(_connection()) as connection:
            opening = connection.execute(
                """SELECT COUNT(*) FROM migration_full_identities i
                     JOIN stock_receipts r ON r.id=i.target_receipt_id
                    WHERE i.opening_state=1 AND r.is_opening_balance=1
                      AND r.supplier='' AND r.order_number=''
                      AND r.request_number='' AND r.plu=''"""
            ).fetchone()[0]
            self.assertEqual(opening, 291)
            for table in (
                "deliveries", "delivery_lines", "equipment", "operations",
                "work_logs", "daily_report_uploads", "daily_report_rows",
            ):
                self.assertEqual(
                    connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
                    0,
                    table,
                )
            self.assertEqual(
                connection.execute(
                    """SELECT COUNT(*) FROM stock_receipts r
                         LEFT JOIN migration_full_identities i
                           ON i.target_receipt_id=r.id WHERE i.id IS NULL"""
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute(
                    """SELECT COUNT(*) FROM stock_issues i
                         LEFT JOIN migration_full_reconciliation r
                           ON r.target_issue_id=i.id WHERE r.id IS NULL"""
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute(
                    """SELECT COUNT(*) FROM stock_issue_allocations a
                         LEFT JOIN stock_receipts r ON r.id=a.receipt_id
                         LEFT JOIN stock_issues i ON i.id=a.issue_id
                        WHERE r.id IS NULL OR i.id IS NULL"""
                ).fetchone()[0],
                0,
            )
            cleanliness = connection.execute(
                """SELECT check_kind, COUNT(*) AS count
                     FROM migration_full_cleanliness
                    GROUP BY check_kind"""
            ).fetchall()
            clean_counts = {str(row[0]): int(row[1]) for row in cleanliness}
            self.assertEqual(clean_counts["OPERATIONAL_TABLE"], 11)
            self.assertGreaterEqual(clean_counts["EXCLUDED_TEST_SERIAL"], 1)
            self.assertEqual(
                connection.execute(
                    """SELECT COUNT(*) FROM migration_full_cleanliness
                        WHERE result NOT IN ('PASS','INFO')"""
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM stock_receipts WHERE id<=1000000"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM stock_issues WHERE id<=2000000"
                ).fetchone()[0],
                0,
            )

    def test_read_only_review_search_numeric_and_opening_timeline(self) -> None:
        with closing(_connection()) as connection:
            numeric = connection.execute(
                """SELECT r.id, r.display_serial_value, r.raw_xml_value
                     FROM migration_full_reconciliation r
                    WHERE r.final_status='NUMERIC_PROVISIONAL_IMPORTED'
                      AND r.target_identity_id IS NOT NULL
                    ORDER BY r.id LIMIT 1"""
            ).fetchone()
            opening = connection.execute(
                """SELECT r.id, r.display_serial_value
                     FROM migration_full_reconciliation r
                    WHERE r.final_status='OPENING_STATE_CREATED'
                      AND r.target_identity_id IS NOT NULL
                    ORDER BY r.id LIMIT 1"""
            ).fetchone()
        service = WarehouseService(CANDIDATE, initialize_database=False)
        review = MigrationFullReviewService(CANDIDATE, actor_provider=service)
        numeric_rows = review.list_rows(
            filter_name="NUMERIC_PROVISIONAL",
            query=str(numeric["display_serial_value"]),
            limit=50,
        )
        matching = next(
            row for row in numeric_rows["rows"]
            if row["reconciliation_id"] == int(numeric["id"])
        )
        self.assertEqual(matching["raw_xml_value"], numeric["raw_xml_value"])
        self.assertEqual(matching["identity_confidence"], "PROVISIONAL")
        self.assertNotIn("password_hash", json.dumps(numeric_rows))

        card = review.get_card(int(opening["id"]))
        self.assertEqual(card["position"]["serial_number"], opening["display_serial_value"])
        self.assertTrue(card["migration"]["opening_state"])
        message = (
            "Исходный приход отсутствует в доступной выгрузке; начальное состояние "
            "восстановлено для сохранения исторического расхода"
        )
        self.assertEqual(card["migration"]["opening_state_message"], message)
        self.assertTrue(any(message in str(row.get("comment", "")) for row in card["history"]))
        self.assertFalse(any("/Users/" in str(row) for row in card["migration"]["source_rows"]))

    def test_http_review_is_role_gated_and_all_mutations_are_denied(self) -> None:
        previous = os.environ.get("ODE_FULL_MIGRATION_CANDIDATE")
        os.environ["ODE_FULL_MIGRATION_CANDIDATE"] = "1"
        try:
            service = WarehouseService(CANDIDATE, initialize_database=False)
            handler_type = make_handler(service)
            handler = handler_type.__new__(handler_type)
            sent: list[tuple[int, dict[str, object]]] = []
            handler._send_json = lambda status, payload: sent.append((status, payload))
            handler.path = "/api/migration-full?filter=SOURCE_CORRUPTED&limit=10"
            with service.user_context("lokolis", role_override="engineer"):
                handler._do_GET()
            self.assertEqual(sent[-1][0], 200)
            self.assertEqual(len(sent[-1][1]["rows"]), 4)
            self.assertNotIn("password_hash", json.dumps(sent[-1][1]))

            review = MigrationFullReviewService(CANDIDATE, actor_provider=service)
            with service.user_context("lokolis", role_override="viewer"):
                with self.assertRaisesRegex(WarehouseError, "инженеру"):
                    review.list_rows(limit=1)

            handler.path = "/api/action"
            handler.headers = {}
            handler._session_email = lambda: "lokolis"
            handler.do_POST()
            self.assertEqual(sent[-1][0], 403)
            self.assertIn("только в режиме просмотра", sent[-1][1]["error"])
            self.assertEqual(sha256_file(PRODUCTION), self.production_sha)
        finally:
            if previous is None:
                os.environ.pop("ODE_FULL_MIGRATION_CANDIDATE", None)
            else:
                os.environ["ODE_FULL_MIGRATION_CANDIDATE"] = previous

    def test_reports_have_required_sheets_and_text_identifier_cells(self) -> None:
        self.assertTrue(REPORT.is_file())
        self.assertTrue(CLEAN_REPORT.is_file())
        namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        with ZipFile(REPORT) as archive:
            workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        sheet_names = {
            str(node.attrib["name"])
            for node in workbook.findall("m:sheets/m:sheet", namespace)
        }
        self.assertTrue(REQUIRED_SHEETS.issubset(sheet_names))

        identifier_columns = {"C", "D", "F", "G", "J", "K", "L"}
        cells = iter_xlsx_cells(
            REPORT,
            sheet_names={"SOURCE_ROW_RECONCILIATION"},
            columns=identifier_columns,
        )
        count = 0
        for cell in cells:
            count += 1
            self.assertEqual(cell.excel_cell_type, "inlineStr")
            self.assertEqual(cell.excel_number_format, "@")
        self.assertGreater(count, 400_000)


if __name__ == "__main__":
    unittest.main()
