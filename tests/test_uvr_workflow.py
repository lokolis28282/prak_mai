"""Tests for the УВР (work-log) feature: section column, CRUD, XLSX import,
narrative reports and standalone task handling."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
import zipfile
import io
from contextlib import closing
from pathlib import Path

from inventory.core.application import create_application_context
from inventory.service import WarehouseError, WarehouseService


def _make_xlsx(sheet_name: str, rows: list[list[str]]) -> bytes:
    """Build a minimal XLSX (inline strings) for import tests, stdlib only."""
    def col(index: int) -> str:
        letters = ""
        index += 1
        while index:
            index, rem = divmod(index - 1, 26)
            letters = chr(65 + rem) + letters
        return letters

    sheet_rows = []
    for r, row in enumerate(rows, start=1):
        cells = "".join(
            f'<c r="{col(c)}{r}" t="inlineStr"><is><t xml:space="preserve">{value}</t></is></c>'
            for c, value in enumerate(row)
        )
        sheet_rows.append(f'<row r="{r}">{cells}</row>')
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{sheet_name}" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '</Relationships>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '</Types>'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buffer.getvalue()


class UvrWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "warehouse.db"
        self.service = WarehouseService(self.db_path)
        self.context = create_application_context(self.db_path, service=self.service)
        self.reports = self.context.reports
        self.today = "2026-07-14"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def row(self, number: str = "9001", **overrides) -> dict[str, str]:
        base = {
            "work_date": self.today, "task_source": "PNR", "task_type": "ПНР",
            "task_number": number, "description": "Настройка сервера",
            "status": "Выполнено", "section": "Linux", "comment": "",
        }
        base.update(overrides)
        return base

    # --- schema / migration ---

    def test_work_logs_has_section_and_needs_review_columns(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as db:
            cols = {r[1] for r in db.execute("PRAGMA table_info(work_logs)")}
        self.assertIn("section", cols)
        self.assertIn("needs_review", cols)

    def test_work_log_section_reference_seeded(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as db:
            count = db.execute(
                "SELECT count(*) FROM reference_values WHERE kind = 'work_log_section'"
            ).fetchone()[0]
        self.assertGreater(count, 0)

    # --- create / section persistence ---

    def test_create_stores_section(self) -> None:
        with self.service.user_context("lokolis", author_name="Иван Тестов"):
            self.reports.create_work_log(self.row(section="Виртуализация"))
            logs = self.reports.list_work_logs({})
        self.assertEqual(logs[0]["section"], "Виртуализация")
        self.assertEqual(logs[0]["needs_review"], 0)

    # --- update ---

    def test_update_changes_row_and_audits(self) -> None:
        with self.service.user_context("lokolis", author_name="Иван Тестов"):
            log_id = self.reports.create_work_log(self.row())
            self.reports.update_work_log(log_id, self.row(
                description="Обновлено", status="В работе", section="NTP"
            ))
            logs = self.reports.list_work_logs({})
        self.assertEqual(logs[0]["description"], "Обновлено")
        self.assertEqual(logs[0]["status"], "В работе")
        self.assertEqual(logs[0]["section"], "NTP")
        with closing(sqlite3.connect(self.db_path)) as db:
            actions = [r[0] for r in db.execute("SELECT action FROM audit_log")]
        self.assertIn("WORK_LOG_UPDATE", actions)

    def test_update_missing_row_raises(self) -> None:
        with self.service.user_context("lokolis", author_name="Иван Тестов"):
            with self.assertRaises(WarehouseError):
                self.reports.update_work_log(9999, self.row())

    # --- delete ---

    def test_delete_removes_row_and_audits(self) -> None:
        with self.service.user_context("lokolis", author_name="Иван Тестов"):
            log_id = self.reports.create_work_log(self.row())
            self.reports.delete_work_log(log_id)
            logs = self.reports.list_work_logs({})
        self.assertEqual(len(logs), 0)
        with closing(sqlite3.connect(self.db_path)) as db:
            actions = [r[0] for r in db.execute("SELECT action FROM audit_log")]
        self.assertIn("WORK_LOG_DELETE", actions)

    def test_delete_missing_row_raises(self) -> None:
        with self.service.user_context("lokolis", author_name="Иван Тестов"):
            with self.assertRaises(WarehouseError):
                self.reports.delete_work_log(9999)

    def test_viewer_cannot_update_or_delete(self) -> None:
        with self.service.user_context("lokolis", author_name="Иван Тестов"):
            log_id = self.reports.create_work_log(self.row())
            self.service.create_user("V", "O", "Viewer", "v@test.local", "secret1", "viewer")
        with self.service.user_context("v@test.local"):
            with self.assertRaises(WarehouseError):
                self.reports.update_work_log(log_id, self.row())
            with self.assertRaises(WarehouseError):
                self.reports.delete_work_log(log_id)

    # --- standalone task (no number) ---

    def test_standalone_task_source_needs_no_number(self) -> None:
        with self.service.user_context("lokolis", author_name="Иван Тестов"):
            log_id = self.reports.create_work_log(self.row(
                task_source="ROOMS", task_number="", task_type="Работа"
            ))
        self.assertGreater(log_id, 0)

    def test_anonymous_entry_without_source_or_number_rejected(self) -> None:
        with self.service.user_context("lokolis", author_name="Иван Тестов"):
            with self.assertRaises(WarehouseError):
                self.reports.create_work_log(self.row(
                    task_source="Не указан", task_number=""
                ))

    # --- reports over date range (shift / week share the work-log list) ---

    def test_work_logs_filtered_by_single_day_for_shift_report(self) -> None:
        with self.service.user_context("lokolis", author_name="Иван Петров"):
            self.reports.create_work_log(self.row(work_date="2026-07-13"))
            self.reports.create_work_log(self.row(work_date="2026-07-14", task_number="9002"))
            same_day = self.reports.list_work_logs({
                "date_from": "2026-07-14", "date_to": "2026-07-14"
            })
        self.assertEqual(len(same_day), 1)
        self.assertEqual(same_day[0]["work_date"], "2026-07-14")

    def test_work_logs_filtered_by_period_for_week_report(self) -> None:
        with self.service.user_context("lokolis", author_name="Иван Петров"):
            self.reports.create_work_log(self.row(work_date="2026-07-13"))
            self.reports.create_work_log(self.row(work_date="2026-07-14", task_number="9002"))
            self.reports.create_work_log(self.row(work_date="2026-07-20", task_number="9003"))
            period = self.reports.list_work_logs({
                "date_from": "2026-07-13", "date_to": "2026-07-14"
            })
        self.assertEqual(len(period), 2)

    # --- XLSX import ---

    def test_xlsx_preview_and_confirm_imports_logs(self) -> None:
        data = _make_xlsx("Логи", [
            ["Дата", "Номер задачи", "Описание работы", "Статус", "Раздел", "Тип", "Комментарий"],
            ["2026-07-14", "PNR-100", "Монтаж", "Выполнено", "Linux", "ПНР", "ok"],
            ["2026-07-14", "ЗНО-200", "Диагностика", "В работе", "NTP", "ЗНО", ""],
        ])
        with self.service.user_context("lokolis", author_name="Иван Тестов"):
            preview = self.reports.preview_work_log_xlsx(data, sheet_name="Логи")
            self.assertEqual(preview["total"], 2)
            self.assertEqual(preview["error_count"], 0)
            imported = self.reports.confirm_work_log_import(preview["preview_id"])
            self.assertEqual(imported, 2)
            logs = self.reports.list_work_logs({})
        self.assertEqual(len(logs), 2)

    def test_xlsx_import_flags_unknown_section_for_review(self) -> None:
        data = _make_xlsx("Логи", [
            ["Дата", "Номер задачи", "Описание работы", "Статус", "Раздел", "Тип", "Комментарий"],
            ["2026-07-14", "PNR-100", "Работа", "Выполнено", "Поддержка оборудования", "ПНР", ""],
        ])
        with self.service.user_context("lokolis", author_name="Иван Тестов"):
            preview = self.reports.preview_work_log_xlsx(data, sheet_name="Логи")
            self.reports.confirm_work_log_import(preview["preview_id"])
            logs = self.reports.list_work_logs({})
        self.assertEqual(logs[0]["section"], "Поддержка оборудования")
        self.assertEqual(logs[0]["needs_review"], 1)

    def test_xlsx_import_keeps_known_section_without_review(self) -> None:
        data = _make_xlsx("Логи", [
            ["Дата", "Номер задачи", "Описание работы", "Статус", "Раздел", "Тип", "Комментарий"],
            ["2026-07-14", "PNR-100", "Работа", "Выполнено", "Linux", "ПНР", ""],
        ])
        with self.service.user_context("lokolis", author_name="Иван Тестов"):
            preview = self.reports.preview_work_log_xlsx(data, sheet_name="Логи")
            self.reports.confirm_work_log_import(preview["preview_id"])
            logs = self.reports.list_work_logs({})
        self.assertEqual(logs[0]["needs_review"], 0)

    def test_xlsx_import_skips_date_only_spacer_rows(self) -> None:
        data = _make_xlsx("Логи", [
            ["Дата", "Номер задачи", "Описание работы", "Статус", "Раздел", "Тип", "Комментарий"],
            ["2026-07-14", "PNR-100", "Работа", "Выполнено", "Linux", "ПНР", ""],
            ["2026-07-15", "", "", "", "", "", ""],
        ])
        with self.service.user_context("lokolis", author_name="Иван Тестов"):
            preview = self.reports.preview_work_log_xlsx(data, sheet_name="Логи")
        self.assertEqual(preview["total"], 1)

    def test_xlsx_bad_file_raises(self) -> None:
        with self.service.user_context("lokolis", author_name="Иван Тестов"):
            with self.assertRaises(WarehouseError):
                self.reports.preview_work_log_xlsx(b"not a zip", sheet_name="Логи")

    # --- report export columns / section reference exposure ---

    def test_work_log_export_rows_carry_uvr_columns(self) -> None:
        with self.service.user_context("lokolis", author_name="Иван Тестов"):
            self.reports.create_work_log(self.row(section="Linux"))
            rows = self.reports.export_work_logs_rows({
                "date_from": self.today, "date_to": self.today
            })
        self.assertEqual(rows[0]["full_task_name"], "ПНР-9001")
        self.assertEqual(rows[0]["section"], "Linux")

    def test_section_reference_is_exposed_to_frontend(self) -> None:
        refs = self.service.references()
        sections = [r["name"] for r in refs if r["kind"] == "work_log_section"]
        self.assertIn("Linux", sections)
        self.assertIn("Виртуализация", sections)

    def test_xlsx_viewer_cannot_import(self) -> None:
        with self.service.user_context("lokolis", author_name="Иван Тестов"):
            self.service.create_user("V", "O", "Viewer", "v@test.local", "secret1", "viewer")
        data = _make_xlsx("Логи", [
            ["Дата", "Номер задачи", "Описание работы", "Статус", "Раздел", "Тип", "Комментарий"],
            ["2026-07-14", "PNR-100", "Работа", "Выполнено", "Linux", "ПНР", ""],
        ])
        with self.service.user_context("v@test.local"):
            with self.assertRaises(WarehouseError):
                self.reports.preview_work_log_xlsx(data, sheet_name="Логи")


if __name__ == "__main__":
    unittest.main()
