"""Tests for PNR checklist logic, shift handover and two-sheet XLSX export."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from inventory.core.application import create_application_context
from inventory.reports.validators import PNR_CHECKLIST_KEYS
from inventory.service import WarehouseError, WarehouseService
from inventory.shared.xlsx import read_sheet, sheet_names


class ReportsHandoverTest(unittest.TestCase):
    def setUp(self) -> None:
        # ignore_cleanup_errors keeps Windows file-locking on the SQLite handle
        # from failing the run, matching the project's other DB-backed tests.
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.tmp.name) / "warehouse.db"
        self.service = WarehouseService(self.db_path)
        self.context = create_application_context(self.db_path, service=self.service)
        self.reports = self.context.reports
        self.today = "2026-08-04"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def pnr(self, number: str, checklist: list[str], **overrides) -> dict:
        base = {
            "work_date": self.today, "task_source": "PNR", "task_type": "ПНР",
            "task_number": number, "section": "Solar", "pnr_checklist": checklist,
            "due_date": self.today, "comment": "",
        }
        base.update(overrides)
        return base

    def plain(self, number: str, status: str, **overrides) -> dict:
        base = {
            "work_date": self.today, "task_source": "DCIM", "task_type": "Работа",
            "task_number": number, "section": "Linux", "description": "Работа",
            "status": status, "due_date": self.today, "comment": "",
        }
        base.update(overrides)
        return base

    # --- schema ---

    def test_new_columns_present(self) -> None:
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(self.db_path)) as db:
            cols = {r[1] for r in db.execute("PRAGMA table_info(work_logs)")}
        self.assertIn("due_date", cols)
        self.assertIn("pnr_checklist", cols)

    # --- PNR auto description + status ---

    def test_pnr_full_checklist_is_done(self) -> None:
        with self.service.user_context("lokolis", author_name="Тест"):
            self.reports.create_work_log(self.pnr("100", list(PNR_CHECKLIST_KEYS)))
            row = self.reports.list_work_logs({"date_from": self.today, "date_to": self.today})[0]
        self.assertEqual(row["status"], "Выполнено")
        self.assertIn("PNR выполнены работы", row["description"])
        self.assertEqual(len(row["pnr_checklist"].split(",")), len(PNR_CHECKLIST_KEYS))

    def test_pnr_partial_checklist_is_in_progress(self) -> None:
        with self.service.user_context("lokolis", author_name="Тест"):
            self.reports.create_work_log(self.pnr("101", ["servers", "power"]))
            row = self.reports.list_work_logs({"date_from": self.today, "date_to": self.today})[0]
        self.assertEqual(row["status"], "В работе")
        self.assertEqual(row["pnr_checklist"], "servers,power")
        self.assertIn("установлено оборудование в стойки", row["description"])
        self.assertIn("подключено питание", row["description"])

    def test_pnr_empty_checklist_is_in_progress(self) -> None:
        with self.service.user_context("lokolis", author_name="Тест"):
            self.reports.create_work_log(self.pnr("102", []))
            row = self.reports.list_work_logs({"date_from": self.today, "date_to": self.today})[0]
        self.assertEqual(row["status"], "В работе")
        self.assertEqual(row["pnr_checklist"], "")

    def test_pnr_description_ignores_manual_text(self) -> None:
        # A description sent for a PNR source is overridden by the generated one.
        with self.service.user_context("lokolis", author_name="Тест"):
            self.reports.create_work_log(
                self.pnr("103", ["servers"], description="произвольный текст")
            )
            row = self.reports.list_work_logs({"date_from": self.today, "date_to": self.today})[0]
        self.assertNotIn("произвольный", row["description"])
        self.assertIn("установлено оборудование в стойки", row["description"])

    def test_pnr_keeps_comment_separate(self) -> None:
        with self.service.user_context("lokolis", author_name="Тест"):
            self.reports.create_work_log(self.pnr("104", ["servers"], comment="стойка А"))
            row = self.reports.list_work_logs({"date_from": self.today, "date_to": self.today})[0]
        self.assertEqual(row["comment"], "стойка А")
        self.assertNotIn("стойка", row["description"])

    # --- due_date ---

    def test_due_date_is_stored(self) -> None:
        with self.service.user_context("lokolis", author_name="Тест"):
            self.reports.create_work_log(self.plain("5", "В работе", due_date="2026-08-10"))
            row = self.reports.list_work_logs({"date_from": self.today, "date_to": self.today})[0]
        self.assertEqual(row["due_date"], "2026-08-10")

    def test_invalid_due_date_rejected(self) -> None:
        from inventory.service import WarehouseError
        with self.service.user_context("lokolis", author_name="Тест"):
            with self.assertRaises(WarehouseError):
                self.reports.create_work_log(self.plain("6", "В работе", due_date="не дата"))

    def test_due_date_required_for_interactive_entry(self) -> None:
        from inventory.service import WarehouseError
        with self.service.user_context("lokolis", author_name="Тест"):
            with self.assertRaises(WarehouseError):
                self.reports.create_work_log(
                    self.plain("7", "В работе", due_date=""), require_due_date=True
                )

    def test_due_date_optional_for_legacy_and_import(self) -> None:
        # Without the interactive flag the deadline may be omitted (legacy/import).
        with self.service.user_context("lokolis", author_name="Тест"):
            log_id = self.reports.create_work_log(self.plain("7b", "В работе", due_date=""))
        self.assertGreater(log_id, 0)

    # --- section optional ---

    def test_section_is_optional(self) -> None:
        with self.service.user_context("lokolis", author_name="Тест"):
            log_id = self.reports.create_work_log(self.plain("8", "В работе", section=""))
        self.assertGreater(log_id, 0)

    # --- PNR dependencies and percent ---

    def test_pnr_dependency_drops_step_without_prerequisite(self) -> None:
        # «switching» requires «laying»; without it the step is not accepted.
        with self.service.user_context("lokolis", author_name="Тест"):
            self.reports.create_work_log(self.pnr("dep", ["servers", "switching"]))
            row = self.reports.list_work_logs({"date_from": self.today, "date_to": self.today})[0]
        self.assertEqual(row["pnr_checklist"], "servers")

    def test_pnr_full_chain_is_accepted(self) -> None:
        with self.service.user_context("lokolis", author_name="Тест"):
            self.reports.create_work_log(self.pnr("chain", ["marking", "laying", "switching"]))
            row = self.reports.list_work_logs({"date_from": self.today, "date_to": self.today})[0]
        self.assertEqual(row["pnr_checklist"], "marking,laying,switching")

    def test_pnr_progress_percent(self) -> None:
        from inventory.reports.validators import pnr_progress_percent, PNR_CHECKLIST_KEYS
        self.assertEqual(pnr_progress_percent([]), 0)
        self.assertEqual(pnr_progress_percent(["servers", "power", "transceivers"]), 50)
        self.assertEqual(pnr_progress_percent(list(PNR_CHECKLIST_KEYS)), 100)

    def test_inc_is_a_valid_source(self) -> None:
        refs = self.service.references()
        sources = [r["name"] for r in refs if r["kind"] == "task_source"]
        self.assertIn("ИНЦ", sources)

    # --- handover filter ---

    def test_handover_excludes_completed(self) -> None:
        with self.service.user_context("lokolis", author_name="Тест"):
            self.reports.create_work_log(self.plain("done", "Выполнено"))
            self.reports.create_work_log(self.plain("wip", "В работе"))
            self.reports.create_work_log(self.pnr("pnr-full", list(PNR_CHECKLIST_KEYS)))
            self.reports.create_work_log(self.pnr("pnr-part", ["servers"]))
            handover = self.reports.handover_logs({"date_from": self.today, "date_to": self.today})
        numbers = {row["task_number"] for row in handover}
        self.assertIn("wip", numbers)
        self.assertIn("pnr-part", numbers)
        self.assertNotIn("done", numbers)
        self.assertNotIn("pnr-full", numbers)

    def test_handover_empty_when_all_done(self) -> None:
        with self.service.user_context("lokolis", author_name="Тест"):
            self.reports.create_work_log(self.plain("a", "Выполнено"))
            self.reports.create_work_log(self.pnr("b", list(PNR_CHECKLIST_KEYS)))
            handover = self.reports.handover_logs({"date_from": self.today, "date_to": self.today})
        self.assertEqual(handover, [])

    # --- handover text: remaining PNR steps ---

    def test_pnr_handover_text_single_remaining_step(self) -> None:
        from inventory.reports.validators import pnr_handover_text
        # Everything done except «Коммутация…» → one imperative sentence.
        checked = [k for k in PNR_CHECKLIST_KEYS if k != "switching"]
        text = pnr_handover_text(checked)
        self.assertEqual(text, "Необходимо выполнить: выполнить коммутацию кабельных систем.")

    def test_pnr_handover_text_lists_all_remaining_steps(self) -> None:
        from inventory.reports.validators import pnr_handover_text
        # Only «servers» done → the rest are listed as bullet points, in order.
        text = pnr_handover_text(["servers"])
        self.assertTrue(text.startswith("Необходимо выполнить:\n"))
        self.assertIn("- подключить питание;", text)
        self.assertIn("- выполнить коммутацию кабельных систем;", text)
        self.assertNotIn("установить оборудование в стойки", text)

    def test_handover_description_shows_remaining_pnr_actions(self) -> None:
        with self.service.user_context("lokolis", author_name="Тест"):
            checked = [k for k in PNR_CHECKLIST_KEYS if k != "switching"]
            self.reports.create_work_log(self.pnr("pnr-x", checked))
            handover = self.reports.handover_logs({"date_from": self.today, "date_to": self.today})
        row = next(r for r in handover if r["task_number"] == "pnr-x")
        self.assertEqual(row["description"], "Необходимо выполнить: выполнить коммутацию кабельных систем.")

    # --- registry pagination / search / needs_review (R7, R8) ---

    def test_work_logs_page_returns_total_and_limit(self) -> None:
        with self.service.user_context("lokolis", author_name="Тест"):
            for i in range(3):
                self.reports.create_work_log(self.plain(f"p{i}", "В работе"))
            page = self.reports.work_logs_page({})
        self.assertEqual(page["total"], 3)
        self.assertEqual(len(page["logs"]), 3)
        self.assertFalse(page["truncated"])
        self.assertIn("limit", page)

    def test_work_logs_page_search(self) -> None:
        with self.service.user_context("lokolis", author_name="Тест"):
            self.reports.create_work_log(self.plain("s1", "В работе", description="Замена диска"))
            self.reports.create_work_log(self.plain("s2", "В работе", description="Настройка сети"))
            page = self.reports.work_logs_page({"search": "диск"})
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["logs"][0]["task_number"], "s1")

    def test_work_logs_page_applies_status_and_section_on_server(self) -> None:
        with self.service.user_context("lokolis", author_name="Тест"):
            self.reports.create_work_log(self.plain("linux-wip", "В работе"))
            self.reports.create_work_log(
                self.plain("solar-wip", "В работе", section="Solar")
            )
            self.reports.create_work_log(self.plain("linux-done", "Выполнено"))
            page = self.reports.work_logs_page({
                "status": "В работе",
                "section": "Linux",
            })
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["logs"][0]["task_number"], "linux-wip")

    def test_work_logs_search_covers_full_name_and_due_date(self) -> None:
        with self.service.user_context("lokolis", author_name="Тест"):
            self.reports.create_work_log(
                self.plain("SEARCH-42", "В работе", due_date="2026-08-19")
            )
            by_name = self.reports.work_logs_page({"search": "DCIM-SEARCH-42"})
            by_due_date = self.reports.work_logs_page({"search": "2026-08-19"})
        self.assertEqual(by_name["total"], 1)
        self.assertEqual(by_due_date["total"], 1)

    def test_work_logs_page_needs_review_filter(self) -> None:
        # Import a legacy row (soft) which gets needs_review, plus a normal one.
        with self.service.user_context("lokolis", author_name="Тест"):
            self.reports.create_work_log(self.plain("normal", "В работе"))
            self.reports.import_work_logs([{
                "work_date": self.today, "task_source": "Неизвестный источник",
                "task_type": "Работа", "task_number": "leg", "description": "старое",
                "status": "Выполнено", "section": "Поддержка оборудования",
            }], soft=True)
            page = self.reports.work_logs_page({"needs_review": "1"})
        self.assertTrue(all(row["needs_review"] for row in page["logs"]))

    def test_shift_stats(self) -> None:
        with self.service.user_context("lokolis", author_name="Тест"):
            self.reports.create_work_log(self.plain("d1", "Выполнено"))
            self.reports.create_work_log(self.plain("d2", "В работе"))
            stats = self.reports.shift_stats(self.today)
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["done"], 1)
        self.assertEqual(stats["unfinished"], 1)
        self.assertEqual(stats["done_percent"], 50)
        self.assertTrue(stats["by_section"])

    def test_assign_section_bulk_clears_review(self) -> None:
        with self.service.user_context("lokolis", author_name="Тест"):
            self.reports.import_work_logs([{
                "work_date": self.today, "task_source": "Неизвестный",
                "task_type": "Работа", "task_number": f"b{i}", "description": "x",
                "status": "Выполнено", "section": "Странный раздел",
                "needs_review": 1,
            } for i in range(2)], soft=True)
            page = self.reports.work_logs_page({"needs_review": "1"})
            ids = [row["id"] for row in page["logs"]]
            updated = self.reports.assign_section(ids, "Linux")
            after = self.reports.work_logs_page({"needs_review": "1"})
        self.assertEqual(updated, len(ids))
        self.assertEqual(after["total"], 0)

    def test_assign_section_rejects_unknown_reference(self) -> None:
        with self.service.user_context("lokolis", author_name="Тест"):
            self.reports.import_work_logs([{
                "work_date": self.today, "task_source": "Неизвестный",
                "task_type": "Работа", "task_number": "unsafe",
                "description": "x", "status": "Выполнено",
                "section": "Требует разбора",
                "needs_review": 1,
            }], soft=True)
            row = self.reports.work_logs_page({"needs_review": "1"})["logs"][0]
            with self.assertRaises(WarehouseError):
                self.reports.assign_section([row["id"]], "Несуществующий раздел")
            after = self.reports.work_logs_page({"needs_review": "1"})
        self.assertEqual(after["total"], 1)
        self.assertEqual(after["logs"][0]["section"], "Требует разбора")

    def test_assign_section_handles_full_registry_window(self) -> None:
        rows = [
            self.plain(
                f"bulk-{index}",
                "В работе",
                needs_review=1,
                due_date="",
            )
            for index in range(self.reports.WORK_LOG_PAGE_LIMIT)
        ]
        with self.service.user_context("lokolis", author_name="Тест"):
            self.reports.import_work_logs(rows)
            review = self.reports.work_logs_page({"needs_review": "1"})
            updated = self.reports.assign_section(
                [row["id"] for row in review["logs"]],
                "Solar",
            )
            after = self.reports.work_logs_page({"needs_review": "1"})
        self.assertEqual(updated, self.reports.WORK_LOG_PAGE_LIMIT)
        self.assertEqual(after["total"], 0)

    # --- two-sheet XLSX export ---

    def test_shift_report_xlsx_has_two_sheets(self) -> None:
        with self.service.user_context("lokolis", author_name="Тест"):
            self.reports.create_work_log(self.plain("done", "Выполнено"))
            self.reports.create_work_log(self.plain("wip", "В работе"))
            self.reports.create_work_log(
                self.plain("old-wip", "В ожидании", work_date="2026-08-03")
            )
            self.reports.create_work_log(
                self.plain("future-wip", "В работе", work_date="2026-08-05")
            )
            data = self.reports.shift_report_xlsx(self.today)
        self.assertEqual(sheet_names(data), ["Выполненные работы", "Передача по смене"])
        done = read_sheet(data, "Выполненные работы")
        handover = read_sheet(data, "Передача по смене")
        # Styled layout: row 0 is the merged green title band (starts at column
        # C, so two leading empty cells), row 1 is the header band, then data.
        self.assertEqual(done[0][2], "Выполненные работы")
        self.assertEqual(handover[0][2], "Передача по смене")
        done_header = [cell for cell in done[1] if cell]
        handover_header = [cell for cell in handover[1] if cell]
        self.assertEqual(done_header[0], "Дата")
        # «Выполненные работы» has no «Срок» column; «Передача по смене» keeps it.
        self.assertNotIn("Срок", done_header)
        self.assertIn("Срок", handover_header)
        # Only completed work belongs to the first sheet. Handover carries the
        # current and older backlog, but not future-dated tasks.
        self.assertEqual(len(done), 3)  # title + header + 1 completed row
        self.assertEqual(len(handover), 4)  # title + header + 2 pending rows
        done_text = "\n".join(cell for row in done for cell in row)
        handover_text = "\n".join(cell for row in handover for cell in row)
        self.assertIn("done", done_text)
        self.assertNotIn("wip", done_text)
        self.assertIn("old-wip", handover_text)
        self.assertIn("wip", handover_text)
        self.assertNotIn("future-wip", handover_text)

    def test_handover_xlsx_contains_only_filtered_pending_rows(self) -> None:
        with self.service.user_context("lokolis", author_name="Тест"):
            self.reports.create_work_log(self.plain("done", "Выполнено"))
            self.reports.create_work_log(self.plain("wait", "В ожидании"))
            self.reports.create_work_log(self.plain("work", "В работе"))
            data = self.reports.handover_xlsx({"status": "В ожидании"})
        rows = read_sheet(data, "Передача по смене")
        text = "\n".join(cell for row in rows for cell in row)
        self.assertIn("wait", text)
        self.assertNotIn("done", text)
        self.assertNotIn("work", text)

    def test_xlsx_writer_replaces_invalid_xml_control_characters(self) -> None:
        from inventory.shared.xlsx_writer import SheetSpec, build_styled_workbook

        data = build_styled_workbook([
            SheetSpec(
                name="Проверка",
                title="Проверка",
                header=["Текст"],
                rows=[["a\x01b"]],
            )
        ])
        rows = read_sheet(data, "Проверка")
        self.assertIn("a\uFFFDb", [cell for row in rows for cell in row])


if __name__ == "__main__":
    unittest.main()
