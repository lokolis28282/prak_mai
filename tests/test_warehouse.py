from __future__ import annotations

import csv
import shutil
import sqlite3
import tempfile
import unittest
import re
import zipfile
from contextlib import closing
from datetime import date
from pathlib import Path

from inventory.seed import seed_database
from inventory.db import verify_password
from inventory.importing import parse_csv_bytes
from inventory.service import WarehouseError, WarehouseService
from build_windows_package import build_windows_package
from inventory.webapp import HTML, USER_CSV_TEMPLATES, csv_download_bytes


class WarehouseServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        seed_database(self.db_path, reset=True)
        self.service = WarehouseService(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def new_receipt(self, **overrides: object) -> dict[str, object]:
        row: dict[str, object] = {
            "receipt_date": date.today().isoformat(), "responsible": "Инженер Тест",
            "order_date": "", "request_number": "З-1", "order_number": "П-1",
            "plu": "", "item_name": "Тестовый сервер", "project": "",
            "serial_number": "SN-STAGE2-001", "inventory_number": "INV-STAGE2-001",
            "supplier": "Не указан", "vendor": "Не указан", "model": "MODEL-1",
            "shelf": "R1-S1", "object_name": "Ixcellerate",
            "equipment_type": "Серверы", "component_type": "", "cable_type": "",
            "unit": "шт", "quantity": "1",
        }
        row.update(overrides)
        return row

    def test_seed_contains_unique_identifiers(self) -> None:
        items = self.service.equipment()
        self.assertEqual(len(items), 8)
        self.assertEqual(len({item["serial_number"] for item in items}), 8)
        self.assertEqual(len({item["inventory_number"] for item in items}), 8)

    def test_receipt_and_issue_update_balance_and_log(self) -> None:
        before = next(item for item in self.service.equipment() if item["id"] == 1)
        self.service.receipt(1, 2, "Накладная Н-010", "Кладовщик № 1")
        self.service.issue(1, 1, "Заявка З-010", "Кладовщик № 1")
        after = next(item for item in self.service.equipment() if item["id"] == 1)
        self.assertEqual(after["quantity"], before["quantity"] + 1)
        self.assertEqual(self.service.operation_log(limit=1)[0]["operation_type"], "ISSUE")

    def test_dashboard_stats_show_flow_and_current_balance(self) -> None:
        stats = self.service.dashboard_stats()
        self.assertEqual(stats["balance"], sum(item["quantity"] for item in self.service.equipment()))
        self.assertGreater(stats["receipts"], stats["issues"])
        self.assertEqual(stats["positions"], 7)

    def test_issue_cannot_make_negative_balance(self) -> None:
        with self.assertRaises(WarehouseError):
            self.service.issue(1, 999, "Заявка З-011", "Кладовщик № 1")

    def test_move_changes_location(self) -> None:
        self.service.move(1, "Q-01", "Перемещение ПР-010", "Кладовщик № 1")
        item = next(item for item in self.service.equipment() if item["id"] == 1)
        self.assertEqual(item["location"], "Q-01")

    def test_rejects_duplicate_identifier(self) -> None:
        with self.assertRaises(WarehouseError):
            self.service.add_equipment(
                "Серверы", "SRV-R260", "SN-SRV-260001", "INV-DC-9999", "A-01"
            )

    def test_export_csv(self) -> None:
        output = Path(self.temp_dir.name) / "export"
        stock_path, log_path = self.service.export_csv(output)
        self.assertTrue(stock_path.exists())
        self.assertTrue(log_path.exists())
        with stock_path.open(encoding="utf-8-sig") as file:
            rows = list(csv.DictReader(file, delimiter=","))
        self.assertEqual(len(rows), 8)

    def test_excel_friendly_csv_uses_semicolon_and_utf8_bom(self) -> None:
        body = csv_download_bytes([{"Наименование": "Сервер, 1", "Кол-во": 2}])
        self.assertTrue(body.startswith(b"\xef\xbb\xbf"))
        text = body.decode("utf-8-sig")
        self.assertEqual(text.splitlines()[0], "Наименование;Кол-во")
        rows = list(csv.DictReader(text.splitlines(), delimiter=";"))
        self.assertEqual(rows, [{"Наименование": "Сервер, 1", "Кол-во": "2"}])

    def test_user_csv_templates_use_excel_semicolon(self) -> None:
        for name, template in USER_CSV_TEMPLATES.items():
            header = template.splitlines()[0]
            with self.subTest(template=name):
                self.assertNotIn(",", header)
                if name != "inventory":
                    self.assertIn(";", header)

    def test_interface_uses_working_labels_instead_of_technical_terms(self) -> None:
        visible = re.sub(r"<script>.*?</script>|<style>.*?</style>", "", HTML, flags=re.S)
        visible = re.sub(r"<[^>]+>", " ", visible).casefold()
        for term in ("prod db", "legacy", "preview", "confirm", "soft import"):
            self.assertNotIn(term, visible)
        for label in (
            "Склад Ixcellerate", "Скачать баланс", "Предпросмотр файла",
            "Создать резервную копию", "Загрузить базу",
        ):
            self.assertIn(label, HTML)

    def test_windows_zip_contains_only_portable_runtime_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = build_windows_package(Path(directory) / "ODE_windows_ready.zip")
            with zipfile.ZipFile(archive_path) as archive:
                names = set(archive.namelist())
            self.assertIn("ODE/WINDOWS_RELEASE.md", names)
            self.assertIn("ODE/QA_STAGE_0_12_17.md", names)
            self.assertIn("ODE/PRODUCT_REVIEW.md", names)
            self.assertIn("ODE/docs/README.md", names)
            self.assertIn("ODE/start_windows.bat", names)
            self.assertIn("ODE/start_test_windows.bat", names)
            self.assertIn("ODE/start_test_macos.command", names)
            self.assertIn("ODE/scripts/create_clean_test_db.py", names)
            self.assertIn("ODE/data/warehouse.db", names)
            self.assertFalse(any("backups" in name.casefold() for name in names))
            self.assertFalse(any("__pycache__" in name or name.endswith(".pyc") for name in names))

    def test_current_receipt_export_contains_only_last_preview_file(self) -> None:
        first = self.new_receipt(serial_number="PREVIEW-1", inventory_number="PREVIEW-INV-1")
        second = self.new_receipt(serial_number="PREVIEW-2", inventory_number="PREVIEW-INV-2")
        preview = self.service.preview_stock_receipt_rows([first, second])
        current = self.service.import_preview_rows("receipt", preview["preview_id"])
        self.assertEqual([row["serial_number"] for row in current], ["PREVIEW-1", "PREVIEW-2"])
        self.assertLess(len(current), len(self.service.stock_receipts()))
        self.service.confirm_stock_receipt_preview(preview["preview_id"])
        self.assertEqual(
            [row["serial_number"] for row in self.service.import_preview_rows("receipt")],
            ["PREVIEW-1", "PREVIEW-2"],
        )

    def test_import_equipment_rows(self) -> None:
        imported = self.service.import_equipment_rows([
            {
                "category": "Комплектующие",
                "model": "RAM 64GB",
                "serial_number": "SN-RAM-IMPORT-001",
                "inventory_number": "INV-IMPORT-001",
                "location": "A-01",
                "quantity": "6",
                "notes": "Импортировано из CSV",
            }
        ])
        self.assertEqual(imported, 1)
        item = next(
            row for row in self.service.equipment()
            if row["inventory_number"] == "INV-IMPORT-001"
        )
        self.assertEqual(item["quantity"], 6)

    def test_import_is_atomic_when_a_row_is_invalid(self) -> None:
        before = len(self.service.equipment())
        rows = [
            {
                "category": "Серверы", "model": "SRV-IMPORT",
                "serial_number": "SN-IMPORT-ATOMIC-001",
                "inventory_number": "INV-IMPORT-ATOMIC-001",
                "location": "B-01", "quantity": "1",
            },
            {
                "category": "Несуществующая категория", "model": "BAD-ROW",
                "serial_number": "SN-IMPORT-ATOMIC-002",
                "inventory_number": "INV-IMPORT-ATOMIC-002",
                "location": "B-01", "quantity": "1",
            },
        ]
        with self.assertRaises(WarehouseError):
            self.service.import_equipment_rows(rows)
        self.assertEqual(len(self.service.equipment()), before)

    def test_existing_equipment_has_default_datacenter(self) -> None:
        self.assertTrue(all(row["datacenter"] == "Ixcellerate" for row in self.service.equipment()))

    def test_wire_categories_are_available(self) -> None:
        names = {row["name"] for row in self.service.reference_data("categories")}
        self.assertIn("Провода — оптика", names)
        self.assertIn("Провода — медь", names)

    def test_import_receipt_and_issue_rows(self) -> None:
        inventory_number = self.service.equipment()[0]["inventory_number"]
        before = next(
            row["quantity"] for row in self.service.equipment()
            if row["inventory_number"] == inventory_number
        )
        common = {
            "inventory_number": inventory_number,
            "quantity": "2",
            "basis": "Массовая операция",
            "responsible": "Тест",
        }
        self.assertEqual(self.service.import_operation_rows([common], "RECEIPT"), 1)
        self.assertEqual(
            self.service.import_operation_rows([{**common, "quantity": "1"}], "ISSUE"), 1
        )
        after = next(
            row["quantity"] for row in self.service.equipment()
            if row["inventory_number"] == inventory_number
        )
        self.assertEqual(after, before + 1)

    def test_bulk_issue_import_is_atomic(self) -> None:
        item = self.service.equipment()[0]
        before = item["quantity"]
        rows = [
            {
                "inventory_number": item["inventory_number"],
                "quantity": "1", "basis": "Тест", "responsible": "Тест",
            },
            {
                "inventory_number": item["inventory_number"],
                "quantity": "999", "basis": "Тест", "responsible": "Тест",
            },
        ]
        with self.assertRaises(WarehouseError):
            self.service.import_operation_rows(rows, "ISSUE")
        current = next(
            row["quantity"] for row in self.service.equipment()
            if row["id"] == item["id"]
        )
        self.assertEqual(current, before)

    def test_add_filter_and_export_work_log(self) -> None:
        today = date.today().isoformat()
        log_id = self.service.add_work_log(
            today, "DCIM", "ПНР", "123", "Проверка стойки", "Выполнено", "Без замечаний"
        )
        logs = self.service.work_logs(today, today)
        self.assertEqual(logs[0]["id"], log_id)
        self.assertEqual(logs[0]["full_task_name"], "ПНР-123")

        output = Path(self.temp_dir.name) / "work_logs.csv"
        self.service.export_work_logs_csv(output, today, today)
        with output.open(encoding="utf-8-sig") as file:
            rows = list(csv.DictReader(file, delimiter=","))
        self.assertEqual(rows[0]["Номер задачи"], "123")
        self.assertEqual(rows[0]["Тип задачи"], "ПНР")

    def test_import_work_logs_is_atomic(self) -> None:
        today = date.today().isoformat()
        rows = [
            {
                "work_date": today, "task_source": "ITSM", "task_type": "ИНЦ",
                "task_number": "77", "description": "Диагностика", "status": "В работе",
                "comment": "",
            },
            {
                "work_date": today, "task_source": "Неизвестный источник",
                "task_type": "ИНЦ", "task_number": "78", "description": "Ошибка",
                "status": "В работе", "comment": "",
            },
        ]
        with self.assertRaisesRegex(WarehouseError, "Строка 3"):
            self.service.import_work_log_rows(rows)
        self.assertEqual(self.service.work_logs(), [])

    def test_daily_report_preserves_block_order(self) -> None:
        today = date.today().isoformat()
        self.service.add_work_log(
            today, "Zabbix", "ИНЦ", "900", "Проверка события", "Выполнено"
        )
        self.service.add_stock_receipt(**self.new_receipt(
            serial_number="SN-REPORT-001", inventory_number="INV-REPORT-001"
        ))
        self.service.add_stock_issue(
            issue_date=today, responsible="Инженер", task_type="ИНЦ", task_number="900",
            target_serial_number="", target_hostname="",
            source_serial_number="SN-REPORT-001", source_item_name="",
            source_cable_type="", quantity="1", comment="Отчет",
        )
        report = self.service.daily_report(today)
        blocks = [row["report_block"] for row in report]
        self.assertEqual(blocks[0], "Логи работ")
        self.assertIn("Приход", blocks)
        self.assertIn("Расход", blocks)
        order = {"Логи работ": 0, "Приход": 1, "Расход": 2}
        self.assertEqual([order[block] for block in blocks], sorted(order[block] for block in blocks))
        self.assertEqual(report[0]["task_number"], "ИНЦ-900")

    def test_daily_report_uses_one_date_and_full_day_range(self) -> None:
        report_date = "2026-07-01"
        self.service.add_work_log(
            report_date, "Zabbix", "ИНЦ", "901", "В границах дня", "Выполнено"
        )
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute(
                "UPDATE work_logs SET work_date = ? WHERE task_number = ?",
                ("2026-07-01 23:59:59", "901"),
            )
        rows = self.service.daily_report(report_date)
        self.assertTrue(any(row["description"] == "В границах дня" for row in rows))
        with self.assertRaises(TypeError):
            self.service.daily_report(report_date, report_date)  # type: ignore[call-arg]

    def test_report_forms_and_routes_use_separate_query_contracts(self) -> None:
        source = Path("inventory/webapp.py").read_text(encoding="utf-8")
        self.assertIn('name="date" type="date"', HTML)
        self.assertIn('name="start_date" type="date"', HTML)
        self.assertIn('name="end_date" type="date"', HTML)
        self.assertIn('self._query(query, "date")', source)
        self.assertIn(
            'self._query(query, "start_date"), self._query(query, "end_date")', source
        )
        self.assertEqual(self.service.weekly_report(report_date := "2026-07-01", report_date)["date_from"], report_date)

    def test_stage2_migrates_current_stock_without_changing_legacy_data(self) -> None:
        self.assertEqual(len(self.service.equipment()), 8)
        opening = [row for row in self.service.stock_receipts() if row["is_opening_balance"]]
        self.assertEqual(len(opening), 7)
        self.assertEqual(
            sum(row["available"] for row in opening),
            sum(row["quantity"] for row in self.service.equipment()),
        )
        self.assertTrue(all(row["datacenter"] == "Ixcellerate" for row in opening))

    def test_serial_issue_requires_task_and_pulls_project(self) -> None:
        self.service.add_reference("project", "PROJECT-ODE")
        self.service.add_stock_receipt(**self.new_receipt(project="PROJECT-ODE"))
        issue = {
            "issue_date": date.today().isoformat(), "responsible": "Инженер",
            "task_type": "", "task_number": "", "target_serial_number": "",
            "target_hostname": "", "source_serial_number": "SN-STAGE2-001",
            "source_item_name": "", "source_cable_type": "", "quantity": "1",
            "comment": "",
        }
        with self.assertRaisesRegex(WarehouseError, "обязательна задача"):
            self.service.add_stock_issue(**issue)
        issue.update(task_type="ПНР", task_number="123")
        self.service.add_stock_issue(**issue)
        exported = self.service.stock_issue_rows()
        self.assertEqual(exported[0]["task_number"], "ПНР-123")
        self.assertEqual(exported[0]["project"], "PROJECT-ODE")

    def test_equipment_cannot_be_issued_to_itself(self) -> None:
        self.service.add_stock_receipt(**self.new_receipt())
        with self.assertRaisesRegex(WarehouseError, "само на себя"):
            self.service.add_stock_issue(
                issue_date=date.today().isoformat(), responsible="Инженер",
                task_type="ИНЦ", task_number="5", target_serial_number="SN-STAGE2-001",
                target_hostname="host-1", source_serial_number="SN-STAGE2-001",
                source_item_name="", source_cable_type="", quantity="1", comment="",
            )

    def test_component_requires_target_equipment(self) -> None:
        self.service.add_stock_receipt(**self.new_receipt(
            item_name="SSD", serial_number="SN-COMP-001", inventory_number="",
            equipment_type="", component_type="Комплектующие",
        ))
        with self.assertRaisesRegex(WarehouseError, "целевое оборудование"):
            self.service.add_stock_issue(
                issue_date=date.today().isoformat(), responsible="Инженер",
                task_type="ЗНР", task_number="7", target_serial_number="",
                target_hostname="", source_serial_number="SN-COMP-001",
                source_item_name="", source_cable_type="", quantity="1", comment="",
            )

    def test_cable_issue_without_task_uses_name_type_and_metres(self) -> None:
        cable = self.new_receipt(
            item_name="Патч-корд LC-LC", serial_number="", inventory_number="",
            model="", shelf="SHELF-A", equipment_type="", cable_type="Оптика",
            unit="м", quantity="10.5",
        )
        self.service.add_stock_receipt(**cable)
        self.service.add_stock_receipt(**{**cable, "shelf": "SHELF-B", "quantity": "20"})
        self.service.add_stock_issue(
            issue_date=date.today().isoformat(), responsible="Инженер",
            task_type="", task_number="", target_serial_number="", target_hostname="",
            source_serial_number="", source_item_name="Патч-корд LC-LC",
            source_cable_type="Оптика", quantity="15", comment="Трасса",
        )
        matching = [r for r in self.service.stock_receipts() if r["item_name"] == "Патч-корд LC-LC"]
        self.assertAlmostEqual(sum(r["available"] for r in matching), 15.5)
        rows = [r for r in self.service.stock_issue_rows() if r["item_name"] == "Патч-корд LC-LC"]
        self.assertEqual(sum(r["quantity"] for r in rows), 15)
        self.assertTrue(all(r["unit"] == "м" for r in rows))
        balance = [r for r in self.service.stock_balance() if r["item_name"] == "Патч-корд LC-LC"]
        self.assertEqual(len(balance), 1)
        self.assertAlmostEqual(balance[0]["balance"], 15.5)
        self.assertEqual(set(balance[0]["shelf"].split(",")), {"SHELF-A", "SHELF-B"})
        self.assertEqual(len(self.service.stock_balance(cable_type="Оптика", unit="м")), 1)

    def test_strict_receipt_import_rejects_unknown_reference_atomically(self) -> None:
        strict_service = WarehouseService(
            self.db_path, strict_reference_validation=True
        )
        for kind, name in (
            ("item_name", "Тестовый сервер"), ("model", "MODEL-1"),
            ("shelf", "R1-S1"),
        ):
            strict_service.add_reference(kind, name)
        before = len(self.service.stock_receipts())
        rows = [self.new_receipt(serial_number="SN-IMP-1", inventory_number="INV-IMP-1"),
                self.new_receipt(serial_number="SN-IMP-2", inventory_number="INV-IMP-2",
                                 project="Несуществующий проект")]
        with self.assertRaisesRegex(WarehouseError, "Строка 3"):
            strict_service.import_stock_receipt_rows(rows)
        self.assertEqual(len(self.service.stock_receipts()), before)

    def test_disabled_reference_is_rejected_in_strict_mode(self) -> None:
        for kind, name in (
            ("item_name", "Тестовый сервер"), ("model", "MODEL-1"),
            ("shelf", "R1-S1"),
        ):
            self.service.add_reference(kind, name)
        reference_id = self.service.add_reference("project", "DISABLED-PROJECT")
        self.service.set_reference_active(reference_id, False)
        strict_service = WarehouseService(
            self.db_path, strict_reference_validation=True
        )
        with self.assertRaisesRegex(WarehouseError, "активном справочнике"):
            strict_service.add_stock_receipt(**self.new_receipt(project="DISABLED-PROJECT"))

    def test_free_receipt_import_collects_references_and_builds_balance(self) -> None:
        self.assertFalse(self.service.strict_reference_validation)
        row = self.new_receipt(
            item_name="vegman", vendor="Вегман", model="p220",
            shelf="выгородка 1", object_name="любое значение",
            project="Новый проект", equipment_type="Серверы тестовые",
            supplier="Новый поставщик", datacenter="Новый ЦОД",
            unit="комплект", serial_number="SN-VEGMAN-1",
            inventory_number="INV-VEGMAN-1",
        )
        self.assertEqual(self.service.import_stock_receipt_rows([row]), 1)
        expected = {
            "item_name": "vegman", "vendor": "Вегман", "model": "p220",
            "shelf": "выгородка 1", "object": "любое значение",
            "project": "Новый проект", "equipment_type": "Серверы тестовые",
            "supplier": "Новый поставщик", "datacenter": "Новый ЦОД",
            "unit": "комплект",
        }
        for kind, name in expected.items():
            values = {value["name"] for value in self.service.references(kind)}
            self.assertIn(name, values)
        balance = self.service.stock_balance(
            project="Новый проект", equipment_type="Серверы тестовые",
            unit="комплект", datacenter="Новый ЦОД",
        )
        self.assertEqual(len(balance), 1)
        self.assertEqual(balance[0]["item_name"], "vegman")
        self.assertEqual(balance[0]["balance"], 1)

    def test_free_issue_import_accepts_disabled_reference_values(self) -> None:
        cable = self.new_receipt(
            item_name="Свободный кабель", serial_number="", inventory_number="",
            model="", shelf="Новая полка", equipment_type="", cable_type="Новый кабель",
            unit="бухта", quantity="10",
        )
        self.service.add_stock_receipt(**cable)
        for kind, name in (("item_name", "Свободный кабель"), ("cable_type", "Новый кабель")):
            reference = next(x for x in self.service.references(kind) if x["name"] == name)
            self.service.set_reference_active(reference["id"], False)
        imported = self.service.import_stock_issue_rows([{
            "issue_date": date.today().isoformat(), "responsible": "Инженер",
            "task_type": "", "task_number": "", "target_serial_number": "",
            "target_hostname": "", "source_serial_number": "",
            "source_item_name": "Свободный кабель", "source_cable_type": "Новый кабель",
            "quantity": "2", "comment": "Свободный режим",
        }])
        self.assertEqual(imported, 1)
        balance = next(x for x in self.service.stock_balance() if x["item_name"] == "Свободный кабель")
        self.assertEqual(balance["balance"], 8)

    def test_editable_task_reference_is_used_by_work_logs(self) -> None:
        self.service.add_reference("task_source", "Ручная задача")
        self.service.add_work_log(
            date.today().isoformat(), "Ручная задача", "ПНР", "501",
            "Работа из нового источника", "В работе",
        )
        self.assertEqual(self.service.work_logs()[0]["task_source"], "Ручная задача")

    def test_legacy_cli_stock_stays_synchronized(self) -> None:
        item = next(row for row in self.service.equipment() if row["id"] == 4)
        self.service.issue(4, item["quantity"], "Полная выдача", "Тест")
        self.assertFalse(any(row["legacy_equipment_id"] == 4 for row in self.service.stock_receipts()))
        self.service.receipt(4, 2, "Возврат", "Тест")
        restored = next(row for row in self.service.stock_receipts() if row["legacy_equipment_id"] == 4)
        self.assertEqual(restored["available"], 2)

    def test_balance_filters_all_new_dimensions(self) -> None:
        self.service.add_reference("project", "PROJECT-FILTER")
        self.service.add_stock_receipt(**self.new_receipt(
            project="PROJECT-FILTER", datacenter="DC-TEST",
            serial_number="SN-FILTER-1", inventory_number="INV-FILTER-1",
        ))
        rows = self.service.stock_balance(
            project="PROJECT-FILTER", object_name="Ixcellerate",
            equipment_type="Серверы", unit="шт", datacenter="DC-TEST",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["datacenter"], "DC-TEST")
        self.assertEqual(self.service.stock_balance(project="UNKNOWN"), [])

    def test_balance_and_overview_do_not_read_legacy_tables(self) -> None:
        before_balance = self.service.stock_balance()
        before_stats = self.service.dashboard_stats()
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("UPDATE equipment SET quantity = 0")
            db.execute("DELETE FROM operations")
        self.assertEqual(self.service.stock_balance(), before_balance)
        self.assertEqual(self.service.dashboard_stats(), before_stats)

    def test_database_backup_is_valid_and_audited(self) -> None:
        backup = self.service.create_backup()
        backup_path = self.service.backup_dir / backup["name"]
        self.assertTrue(backup_path.exists())
        self.assertGreater(backup["size"], 0)
        check = self.service._database_check(backup_path, self.service.KEY_TABLES)
        self.assertTrue(check["ok"])
        entry = self.service.audit_entries(limit=1)[0]
        self.assertEqual(entry["action"], "BACKUP_CREATE")
        self.assertEqual(entry["author"], "lokolis")

    def test_integrity_check_validates_tables_and_writes_audit(self) -> None:
        result = self.service.check_integrity()
        self.assertTrue(result["ok"])
        self.assertEqual(result["messages"], ["ok"])
        self.assertEqual(result["missing_tables"], [])
        self.assertEqual(self.service.audit_entries(limit=1)[0]["action"], "INTEGRITY_CHECK")

        incomplete = self.service.backup_dir / "incomplete.db"
        incomplete.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(incomplete)) as db, db:
            db.execute("CREATE TABLE example(id INTEGER)")
        invalid = self.service._database_check(incomplete, self.service.KEY_TABLES)
        self.assertFalse(invalid["ok"])
        self.assertIn("stock_receipts", invalid["missing_tables"])

        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("DROP TABLE audit_log")
        missing_audit = self.service.check_integrity()
        self.assertFalse(missing_audit["ok"])
        self.assertIn("audit_log", missing_audit["missing_tables"])

    def test_restore_requires_confirmation_creates_safety_backup_and_audits(self) -> None:
        self.service.add_reference("project", "BEFORE-BACKUP")
        backup = self.service.create_backup()
        self.service.add_reference("project", "AFTER-BACKUP")
        with self.assertRaisesRegex(WarehouseError, "подтверждения"):
            self.service.restore_backup(backup["name"], confirmed=False)

        result = self.service.restore_backup(backup["name"], confirmed=True)
        self.assertTrue(result["ok"])
        self.assertTrue((self.service.backup_dir / result["safety_backup"]).exists())
        projects = {row["name"] for row in self.service.references("project")}
        self.assertIn("BEFORE-BACKUP", projects)
        self.assertNotIn("AFTER-BACKUP", projects)
        self.assertEqual(self.service.audit_entries(limit=1)[0]["action"], "RESTORE_SUCCESS")

    def test_business_actions_are_written_to_unified_audit(self) -> None:
        self.service.add_reference("project", "AUDIT-PROJECT")
        self.service.add_stock_receipt(**self.new_receipt(
            project="AUDIT-PROJECT", serial_number="SN-AUDIT-1",
            inventory_number="INV-AUDIT-1",
        ))
        self.service.add_stock_issue(
            issue_date=date.today().isoformat(), responsible="Инженер",
            task_type="ПНР", task_number="100", target_serial_number="",
            target_hostname="", source_serial_number="SN-AUDIT-1",
            source_item_name="", source_cable_type="", quantity="1", comment="",
        )
        self.service.add_work_log(
            date.today().isoformat(), "DCIM", "ПНР", "100",
            "Проверка аудита", "Выполнено",
        )
        actions = {row["action"] for row in self.service.audit_entries()}
        self.assertTrue({
            "REFERENCE_CREATE", "RECEIPT_CREATE", "ISSUE_CREATE", "WORK_LOG_CREATE"
        }.issubset(actions))

    def test_issue_import_rolls_back_all_rows(self) -> None:
        self.service.add_stock_receipt(**self.new_receipt(quantity="1"))
        base = {
            "issue_date": date.today().isoformat(), "responsible": "Инженер",
            "task_type": "ПНР", "task_number": "42", "target_serial_number": "",
            "target_hostname": "", "source_serial_number": "SN-STAGE2-001",
            "source_item_name": "", "source_cable_type": "", "quantity": "1", "comment": "",
        }
        with self.assertRaisesRegex(WarehouseError, "Строка 3"):
            self.service.import_stock_issue_rows([base, base])
        self.assertFalse(any(row["serial_number"] == "SN-STAGE2-001" for row in self.service.stock_issue_rows()))
        receipt = next(row for row in self.service.stock_receipts() if row["serial_number"] == "SN-STAGE2-001")
        self.assertEqual(receipt["available"], 1)

    def test_default_admin_is_created_once_with_hashed_password(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as db:
            db.row_factory = sqlite3.Row
            user = db.execute("SELECT * FROM users WHERE email = 'lokolis'").fetchone()
            self.assertIsNotNone(user)
            self.assertEqual(user["first_name"], "Александр")
            self.assertEqual(user["last_name"], "Мерненко")
            self.assertEqual(user["role"], "admin")
            self.assertNotEqual(user["password_hash"], "lokolis")
            self.assertTrue(verify_password("lokolis", user["password_hash"]))
        with self.service.user_context("lokolis"):
            self.service.change_password("lokolis", "new-secure-password")
        WarehouseService(self.db_path)
        with self.assertRaisesRegex(WarehouseError, "Неверный"):
            self.service.authenticate("lokolis", "lokolis")
        self.assertEqual(
            self.service.authenticate("lokolis", "new-secure-password")["email"], "lokolis"
        )

    def test_login_and_password_change(self) -> None:
        user = self.service.authenticate("lokolis", "lokolis")
        self.assertTrue(user["must_change_password"])
        with self.service.user_context("lokolis"):
            self.service.change_password("lokolis", "changed-password")
        with self.assertRaises(WarehouseError):
            self.service.authenticate("lokolis", "lokolis")
        changed = self.service.authenticate("lokolis", "changed-password")
        self.assertFalse(changed["must_change_password"])

    def test_password_change_uses_current_user_from_context(self) -> None:
        self.service.create_user(
            "Иван", "Инженеров", "Инженер", "engineer", "secret1", "engineer"
        )
        with self.service.user_context("engineer"):
            self.service.change_password("secret1", "new-secret")
        self.assertEqual(self.service.authenticate("engineer", "new-secret")["email"], "engineer")
        self.assertEqual(self.service.authenticate("lokolis", "lokolis")["email"], "lokolis")

    def test_profile_updates_name_and_position_but_not_email(self) -> None:
        with self.service.user_context("lokolis"):
            updated = self.service.update_profile("Александр", "Мерненко", "Старший инженер")
        self.assertEqual(updated["position"], "Старший инженер")
        self.assertEqual(updated["email"], "lokolis")

    def test_receipt_accepts_russian_date_and_normalizes_it(self) -> None:
        self.service.add_stock_receipt(**self.new_receipt(receipt_date="27.06.2026"))
        receipt = next(
            row for row in self.service.stock_receipts()
            if row["serial_number"] == "SN-STAGE2-001"
        )
        self.assertEqual(receipt["receipt_date"], "2026-06-27")

    def test_receipt_csv_header_is_quantity_only(self) -> None:
        from inventory.webapp import RECEIPT_HEADERS

        self.assertEqual(RECEIPT_HEADERS["quantity"], "Кол-во")
        self.assertNotIn("Кол-во / метраж", RECEIPT_HEADERS.values())

    def test_engineer_and_viewer_cannot_use_admin_functions(self) -> None:
        self.service.create_user("Иван", "Инженеров", "Инженер", "engineer", "secret1", "engineer")
        self.service.create_user("Вера", "Просмотр", "Наблюдатель", "viewer", "secret2", "viewer")
        for email in ("engineer", "viewer"):
            with self.service.user_context(email):
                with self.assertRaisesRegex(WarehouseError, "Недостаточно прав"):
                    self.service.create_backup()
                with self.assertRaisesRegex(WarehouseError, "Недостаточно прав"):
                    self.service.audit_entries()
                with self.assertRaisesRegex(WarehouseError, "Недостаточно прав"):
                    self.service.restore_backup("missing.db", confirmed=True)
                with self.assertRaisesRegex(WarehouseError, "Недостаточно прав"):
                    self.service.replace_production_database("missing.db", confirmed=True)

    def test_viewer_cannot_write_but_engineer_can_and_audit_has_author(self) -> None:
        self.service.create_user("Иван", "Инженеров", "Инженер", "engineer", "secret1", "engineer")
        self.service.create_user("Вера", "Просмотр", "Наблюдатель", "viewer", "secret2", "viewer")
        with self.service.user_context("viewer"):
            with self.assertRaisesRegex(WarehouseError, "Недостаточно прав"):
                self.service.add_work_log(
                    date.today().isoformat(), "DCIM", "ПНР", "1", "Нельзя", "В работе"
                )
            self.assertIsInstance(self.service.work_logs(), list)
        with self.service.user_context("engineer"):
            self.service.add_work_log(
                date.today().isoformat(), "DCIM", "ПНР", "2", "Можно", "Выполнено"
            )
        entry = next(
            row for row in self.service.audit_entries() if row["action"] == "WORK_LOG_CREATE"
        )
        self.assertEqual(entry["author"], "engineer")

    def test_admin_can_replace_production_database_with_safety_backup(self) -> None:
        uploaded = Path(self.temp_dir.name) / "uploaded.db"
        shutil.copy2(self.db_path, uploaded)
        result = self.service.replace_production_database(uploaded, confirmed=True)
        self.assertTrue(result["ok"])
        self.assertTrue((self.service.backup_dir / result["safety_backup"]).exists())
        self.assertEqual(
            self.service.audit_entries(limit=1)[0]["action"], "PRODUCTION_DATABASE_UPLOAD"
        )

    def test_reference_groups_are_ordered_by_activity_and_name(self) -> None:
        second = self.service.add_reference("project", "Zulu")
        first = self.service.add_reference("project", "Alpha")
        self.service.set_reference_active(first, False)
        group = next(x for x in self.service.reference_groups() if x["kind"] == "project")
        self.assertEqual([x["name"] for x in group["values"]], ["Zulu", "Alpha"])
        self.assertEqual([x["is_active"] for x in group["values"]], [1, 0])
        self.assertNotEqual(first, second)

    def test_daily_report_csv_import_is_atomic(self) -> None:
        valid = {
            "date": date.today().isoformat(), "report_block": "Смена",
            "task_number": "ПНР-10", "description": "Проверка",
            "quantity": "", "serial_number": "", "responsible": "Инженер",
            "comment": "Готово",
        }
        invalid = {**valid, "date": "не-дата", "description": "Ошибка"}
        with self.assertRaisesRegex(WarehouseError, "Строка 3"):
            self.service.import_daily_report_rows("broken.csv", [valid, invalid])
        self.assertEqual(self.service.daily_report_uploads(), [])
        with closing(sqlite3.connect(self.db_path)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM daily_report_rows").fetchone()[0], 0)

    def test_uploaded_daily_report_does_not_mix_with_work_logs(self) -> None:
        before = self.service.work_logs()
        result = self.service.import_daily_report_rows("ready.csv", [{
            "date": date.today().isoformat(), "report_block": "Готовый отчет",
            "task_number": "ИНЦ-42", "description": "Внешняя строка",
            "quantity": "1", "serial_number": "SN-1", "responsible": "Инженер",
            "comment": "Импорт",
        }])
        self.assertEqual(self.service.work_logs(), before)
        rows = self.service.uploaded_daily_report(result["id"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["description"], "Внешняя строка")
        generated = self.service.daily_report(date.today().isoformat())
        self.assertNotIn("Внешняя строка", {row["description"] for row in generated})

    def test_receipt_preview_does_not_change_database_and_confirm_imports(self) -> None:
        row = self.new_receipt(serial_number="SN-PREVIEW-1", inventory_number="INV-PREVIEW-1")
        before_receipts = len(self.service.stock_receipts())
        before_audit = len(self.service.audit_entries())
        preview = self.service.preview_stock_receipt_rows([row])
        self.assertTrue(preview["can_confirm"])
        self.assertEqual(preview["new"], 1)
        self.assertEqual(len(self.service.stock_receipts()), before_receipts)
        self.assertEqual(len(self.service.audit_entries()), before_audit)
        self.assertEqual(self.service.confirm_stock_receipt_preview(preview["preview_id"]), 1)
        self.assertEqual(len(self.service.stock_receipts()), before_receipts + 1)

    def test_previews_report_row_errors_without_writes(self) -> None:
        receipt_before = len(self.service.stock_receipts())
        receipt = self.service.preview_stock_receipt_rows([
            self.new_receipt(receipt_date="bad-date")
        ])
        self.assertFalse(receipt["can_confirm"])
        self.assertEqual(receipt["errors"][0]["line"], 2)
        self.assertEqual(len(self.service.stock_receipts()), receipt_before)

        issue_before = len(self.service.stock_issue_rows())
        issue = self.service.preview_stock_issue_rows([{
            "issue_date": date.today().isoformat(), "responsible": "Инженер",
            "task_type": "ПНР", "task_number": "1", "source_serial_number": "UNKNOWN",
            "source_item_name": "", "source_cable_type": "", "quantity": "1",
        }])
        self.assertFalse(issue["can_confirm"])
        self.assertIn("не найдена", issue["errors"][0]["reason"])
        self.assertEqual(len(self.service.stock_issue_rows()), issue_before)

    def test_issue_preview_and_confirm_use_same_validation(self) -> None:
        self.service.add_stock_receipt(**self.new_receipt(
            serial_number="SN-ISSUE-PREVIEW", inventory_number="INV-ISSUE-PREVIEW"
        ))
        rows = [{
            "issue_date": date.today().isoformat(), "responsible": "Инженер",
            "task_type": "ПНР", "task_number": "42",
            "target_serial_number": "", "target_hostname": "",
            "source_serial_number": "SN-ISSUE-PREVIEW", "source_item_name": "",
            "source_cable_type": "", "quantity": "1", "comment": "preview",
        }]
        before = len(self.service.stock_issue_rows())
        preview = self.service.preview_stock_issue_rows(rows)
        self.assertTrue(preview["can_confirm"])
        self.assertEqual(len(self.service.stock_issue_rows()), before)
        self.assertEqual(self.service.confirm_stock_issue_preview(preview["preview_id"]), 1)
        self.assertEqual(len(self.service.stock_issue_rows()), before + 1)

    def test_position_search_card_and_balance_query(self) -> None:
        self.service.add_stock_receipt(**self.new_receipt(
            item_name="Поисковый сервер", vendor="SearchVendor", model="Needle-9000",
            serial_number="SN-SEARCH-43", inventory_number="INV-SEARCH-43",
        ))
        self.assertEqual(self.service.search_stock_positions("SN-SEARCH-43")[0]["model"], "Needle-9000")
        self.assertEqual(self.service.search_stock_positions("searchvendor")[0]["serial_number"], "SN-SEARCH-43")
        self.assertEqual(self.service.stock_balance(query="Needle-9000")[0]["item_name"], "Поисковый сервер")
        card = self.service.position_card(serial_number="SN-SEARCH-43")
        self.assertEqual(card["position"]["vendor"], "SearchVendor")
        self.assertTrue(any(row["event_type"] == "Приход" for row in card["history"]))

    def test_bulk_serial_issue_is_strict_and_atomic(self) -> None:
        for number in (1, 2):
            self.service.add_stock_receipt(**self.new_receipt(
                serial_number=f"SN-BULK-{number}", inventory_number=f"INV-BULK-{number}"
            ))
        blocked = self.service.preview_bulk_issue_serials([
            {"serial_number": "SN-BULK-1"}, {"serial_number": "UNKNOWN"},
        ])
        self.assertFalse(blocked["can_confirm"])
        with self.assertRaises(WarehouseError):
            self.service.confirm_bulk_issue_preview(
                blocked["preview_id"], date.today().isoformat(), "Инженер", "ПНР", "700"
            )
        self.assertEqual(self.service.search_stock_positions("SN-BULK-1")[0]["balance"], 1)

        preview = self.service.preview_bulk_issue_serials([
            {"serial_number": "SN-BULK-1"}, {"serial_number": "SN-BULK-2"},
        ])
        self.assertEqual(self.service.confirm_bulk_issue_preview(
            preview["preview_id"], date.today().isoformat(), "Инженер", "ПНР", "701"
        ), 2)
        self.assertEqual(self.service.search_stock_positions("SN-BULK-1")[0]["balance"], 0)
        self.assertEqual(self.service.search_stock_positions("SN-BULK-2")[0]["balance"], 0)

    def test_scanned_receipt_checks_serial_and_confirms_atomically(self) -> None:
        common = self.new_receipt(serial_number="", inventory_number="")
        self.assertTrue(self.service.scan_receipt_serial(" scan-new-1 ")["valid"])
        self.assertEqual(
            self.service.confirm_scanned_receipts(common, ["scan-new-1", "scan-new-2"]), 2
        )
        self.assertFalse(self.service.scan_receipt_serial("SCAN-NEW-1")["valid"])
        before = len(self.service.stock_receipts())
        with self.assertRaises(WarehouseError):
            self.service.confirm_scanned_receipts(common, ["SCAN-NEW-3", "SCAN-NEW-1"])
        self.assertEqual(len(self.service.stock_receipts()), before)

    def test_scanned_issue_saves_unknown_as_problem(self) -> None:
        self.service.add_stock_receipt(**self.new_receipt(
            serial_number="SCAN-ISSUE-1", inventory_number="SCAN-INV-1"
        ))
        self.assertTrue(self.service.scan_issue_serial("scan-issue-1")["found"])
        self.assertFalse(self.service.scan_issue_serial("scan-unknown")["found"])
        result = self.service.confirm_scanned_issues({
            "issue_date": date.today().isoformat(), "responsible": "Инженер",
            "task_type": "ПНР", "task_number": "SCAN-1",
            "target_serial_number": "", "target_hostname": "host-1",
            "comment": "Сканирование",
        }, ["SCAN-ISSUE-1", "SCAN-UNKNOWN"])
        self.assertEqual(result, {"imported": 2, "unmatched": 1})
        self.assertTrue(any(
            row["serial_number"] == "SCAN-UNKNOWN"
            for row in self.service.data_quality_problems()["unmatched_issues"]
        ))

    def test_scanned_issue_rolls_back_whole_list_on_invalid_position(self) -> None:
        self.service.add_stock_receipt(**self.new_receipt(
            serial_number="SCAN-OK", inventory_number="SCAN-OK-INV"
        ))
        self.service.add_stock_receipt(**self.new_receipt(
            serial_number="SCAN-COMP", inventory_number="SCAN-COMP-INV",
            equipment_type="", component_type="Диск",
        ))
        before = len(self.service.stock_issue_rows())
        with self.assertRaises(WarehouseError):
            self.service.confirm_scanned_issues({
                "issue_date": date.today().isoformat(), "responsible": "Инженер",
                "task_type": "ПНР", "task_number": "SCAN-2",
                "target_serial_number": "", "target_hostname": "", "comment": "",
            }, ["SCAN-OK", "SCAN-COMP"])
        self.assertEqual(len(self.service.stock_issue_rows()), before)

    def test_weekly_report_aggregates_existing_data(self) -> None:
        today = date.today().isoformat()
        self.service.add_work_log(today, "DCIM", "ПНР", "W-1", "Работа", "Выполнено")
        self.service.add_stock_receipt(**self.new_receipt(
            receipt_date=today, serial_number="SN-WEEK", inventory_number="INV-WEEK"
        ))
        report = self.service.weekly_report(today, today)
        self.assertEqual(report["summary"]["work_logs"], 1)
        self.assertGreaterEqual(report["summary"]["receipts"], 1)
        self.assertTrue(self.service.weekly_report_rows(today, today))

    def test_soft_import_accepts_free_references_and_slash_date(self) -> None:
        row = {
            "receipt_date": "27/06/2026", "item_name": "Неизвестная позиция",
            "quantity": "2", "vendor": "Новый вендор", "model": "Новая модель",
            "project": "Новый проект", "shelf": "кривая полка",
        }
        self.assertEqual(self.service.import_stock_receipt_rows([row]), 1)
        receipt = next(x for x in self.service.stock_receipts() if x["item_name"] == row["item_name"])
        self.assertEqual(receipt["receipt_date"], "2026-06-27")
        self.assertEqual(receipt["project"], "Новый проект")
        refs = {x["name"] for x in self.service.references("vendor")}
        self.assertIn("Новый вендор", refs)

    def test_csv_header_aliases_and_clear_missing_column_error(self) -> None:
        rows = parse_csv_bytes(
            "Серийник;Инвентарный номер;Название;Qty;Vendor;Model;Полка;Project;Ответственный;Task\n"
            "SN-X;INV-X;Сервер;1;V;M;R1;P;Иванов;42\n".encode(),
            "receipt",
        )
        self.assertEqual(rows[0]["serial_number"], "SN-X")
        self.assertEqual(rows[0]["inventory_number"], "INV-X")
        self.assertEqual(rows[0]["item_name"], "Сервер")
        with self.assertRaisesRegex(ValueError, "Не найден обязательный столбец: S/N"):
            parse_csv_bytes("Название\nСервер\n".encode(), "inventory")

    def test_large_work_log_preview_is_limited_and_confirm_writes(self) -> None:
        rows = [{
            "work_date": "27.06.2026", "task_source": "Свободный источник",
            "task_type": "Свободный тип", "task_number": str(number),
            "description": f"Работа {number}", "status": "Выполнено", "comment": "",
        } for number in range(40_000)]
        before = len(self.service.work_logs())
        preview = self.service.preview_work_log_rows(rows, soft=True)
        self.assertEqual(preview["total"], 40_000)
        self.assertEqual(len(preview["rows"]), 100)
        self.assertEqual(len(self.service.work_logs()), before)
        self.assertEqual(self.service.confirm_work_log_preview(preview["preview_id"]), 40_000)
        self.assertEqual(len(self.service.work_logs()), before + 40_000)

    def test_unmatched_issue_is_imported_as_problem(self) -> None:
        row = {
            "issue_date": "27.06.2026", "responsible": "Инженер",
            "task_type": "ПНР", "task_number": "404",
            "source_serial_number": "SN-NOT-IN-BASE", "quantity": "1",
        }
        self.assertEqual(self.service.import_stock_issue_rows([row]), 1)
        problems = self.service.data_quality_problems("2026-06-27", "2026-06-27")
        self.assertEqual(problems["unmatched_issues"][0]["serial_number"], "SN-NOT-IN-BASE")
        report = self.service.weekly_report("2026-06-27", "2026-06-27")
        self.assertTrue(report["problems"]["unmatched_issues"])

    def test_balance_allows_empty_project_and_shelf(self) -> None:
        self.service.import_stock_receipt_rows([{
            "receipt_date": "27.06.2026", "item_name": "Кабель без реквизитов",
            "quantity": "10", "project": "", "shelf": "",
        }])
        row = next(x for x in self.service.stock_balance() if x["item_name"] == "Кабель без реквизитов")
        self.assertEqual(row["project"], "")
        self.assertEqual(row["shelf"], None)
        self.assertEqual(row["balance"], 10)

    def test_inventory_compare_found_unknown_missing_and_duplicates(self) -> None:
        serial = next(x["serial_number"] for x in self.service.stock_balance() if x["serial_number"])
        result = self.service.inventory_compare([
            {"serial_number": serial}, {"serial_number": serial},
            {"serial_number": "SN-UNKNOWN-SCAN"},
        ])
        self.assertTrue(result["found"])
        self.assertTrue(result["not_found"])
        self.assertTrue(result["missing"])
        self.assertEqual(result["duplicates"][0]["count"], 2)

    def test_delivery_upload_splits_serials_and_detects_duplicates_and_stock(self) -> None:
        existing = next(x["serial_number"] for x in self.service.stock_balance() if x["serial_number"])
        parsed = parse_csv_bytes(
            ("Серийные номера;Номер поставки;Поставщик;шт;единица оборудования\n"
             f"NEW-1, NEW-2, NEW-1;П-77;ТестПоставка;1;Сервер\n"
             f"{existing};П-77;ТестПоставка;1;Сервер\n").encode(), "delivery"
        )
        result = self.service.preview_delivery_rows(parsed, "supply.csv")
        self.assertEqual(result["total"], 4)
        self.assertEqual(result["counts"]["Дубль в файле"], 1)
        self.assertEqual(result["counts"]["Уже на складе"], 1)
        delivery_id = self.service.confirm_delivery_preview(result["preview_id"])
        card = self.service.delivery(delivery_id)
        self.assertEqual(card["delivery"]["source_filename"], "supply.csv")
        self.assertEqual(len(card["lines"]), 4)

    def test_delivery_web_confirm_adds_new_and_fills_only_empty_existing_fields(self) -> None:
        existing = self.new_receipt(serial_number="DEL-EXIST", vendor="Сохранить", model="")
        self.service.add_stock_receipt(**existing)
        preview = self.service.preview_delivery_rows([
            {"serial_number": "DEL-NEW", "supplier": "Новый", "vendor": "Dell", "model": "R760", "equipment_type": "Сервер"},
            {"serial_number": "DEL-EXIST", "supplier": "Дополнить", "vendor": "Не перетирать", "model": "M2", "equipment_type": "Сервер"},
        ], "delivery.csv", unknown_columns=["Лишняя колонка"], auto_apply=True)
        self.assertEqual((preview["new"], preview["updated"]), (1, 1))
        self.assertEqual(preview["unknown_columns"], ["Лишняя колонка"])
        self.service.confirm_delivery_preview(preview["preview_id"])
        receipts = {x["serial_number"]: x for x in self.service.stock_receipts()}
        self.assertIn("DEL-NEW", receipts)
        self.assertEqual(receipts["DEL-EXIST"]["vendor"], "Сохранить")
        self.assertEqual(receipts["DEL-EXIST"]["model"], "M2")

    def test_warehouse_history_uses_human_labels(self) -> None:
        self.service.add_stock_receipt(**self.new_receipt(serial_number="HISTORY-1"))
        history = self.service.warehouse_history()
        self.assertTrue(any(row["action"] == "Приход" for row in history))
        self.assertFalse(any("stock_" in row["action"] or "audit" in row["action"] for row in history))

    def test_delivery_acceptance_creates_receipt_blocks_repeat_and_updates_status(self) -> None:
        preview = self.service.preview_delivery_rows([
            {"serial_number": "DEL-A", "delivery_number": "П-80", "supplier": "Поставщик", "quantity": "1", "equipment_unit": "Сервер"},
            {"serial_number": "DEL-B", "delivery_number": "П-80", "supplier": "Поставщик", "quantity": "1", "equipment_unit": "Сервер"},
        ], "delivery.csv")
        delivery_id = self.service.confirm_delivery_preview(preview["preview_id"])
        self.service.accept_delivery_serial(delivery_id, "DEL-A", {"model": "M1", "vendor": "V1"})
        self.assertEqual(self.service.delivery(delivery_id)["delivery"]["status"], "Частично принята")
        self.assertTrue(any(x["serial_number"] == "DEL-A" for x in self.service.stock_receipts()))
        with self.assertRaises(WarehouseError):
            self.service.accept_delivery_serial(delivery_id, "DEL-A")
        self.service.accept_delivery_serial(delivery_id, "DEL-B")
        self.assertEqual(self.service.delivery(delivery_id)["delivery"]["status"], "Принята")

    def test_unplanned_delivery_acceptance_and_bulk_fill(self) -> None:
        preview = self.service.preview_delivery_rows([
            {"serial_number": "DEL-C", "delivery_number": "П-81", "supplier": "Поставщик", "quantity": "1", "equipment_unit": "Сервер"},
            {"serial_number": "DEL-D", "delivery_number": "П-81", "supplier": "Поставщик", "quantity": "1", "equipment_unit": "Сервер"},
        ], "delivery.csv")
        delivery_id = self.service.confirm_delivery_preview(preview["preview_id"])
        lines = self.service.delivery(delivery_id)["lines"]
        changed = self.service.update_delivery_lines(
            delivery_id, [x["id"] for x in lines], {"datacenter": "ЦОД-2", "shelf": "R9"}
        )
        self.assertEqual(changed, 2)
        self.assertTrue(all(x["shelf"] == "R9" for x in self.service.delivery(delivery_id)["lines"]))
        result = self.service.accept_delivery_serial(delivery_id, "UNPLANNED-1", unplanned=True)
        self.assertTrue(result["accepted"])
        self.assertTrue(any(x["serial_number"] == "UNPLANNED-1" for x in self.service.stock_receipts()))

    def test_reports_include_delivery_activity(self) -> None:
        today = date.today().isoformat()
        preview = self.service.preview_delivery_rows([
            {"serial_number": "DEL-REPORT", "delivery_number": "П-82", "supplier": "Поставщик", "quantity": "1", "equipment_unit": "Сервер"},
        ], "delivery.csv")
        delivery_id = self.service.confirm_delivery_preview(preview["preview_id"])
        self.service.accept_delivery_serial(delivery_id, "DEL-REPORT")
        self.assertTrue(any(x["report_block"] == "Поставки" for x in self.service.daily_report(today)))
        report = self.service.weekly_report(today, today)
        self.assertEqual(report["summary"]["loaded_deliveries"], 1)
        self.assertEqual(report["summary"]["accepted_delivery_items"], 1)

    def test_receipt_category_maps_to_legacy_type_fields(self) -> None:
        cases = (
            ("Оборудование", "Сервер", "equipment_type"),
            ("Компоненты", "RAM", "component_type"),
            ("Кабели", "Оптика", "cable_type"),
        )
        for index, (category, item_type, expected_field) in enumerate(cases, start=1):
            row = self.new_receipt(
                category=category, item_type=item_type,
                serial_number="" if category == "Кабели" else f"SN-CATEGORY-{index}",
                inventory_number="", equipment_type="старое", component_type="старое",
                cable_type="старое", quantity="2",
            )
            self.service.add_stock_receipt(**row)
            saved = self.service.stock_receipts()[0]
            self.assertEqual(saved[expected_field], item_type)
            self.assertEqual(
                sum(bool(saved[field]) for field in
                    ("equipment_type", "component_type", "cable_type")), 1
            )
            if category != "Кабели":
                self.assertEqual(saved["quantity"], 1)

    def test_cable_receipt_does_not_require_serial_number(self) -> None:
        self.service.add_stock_receipt(**self.new_receipt(
            category="Кабели", item_type="DAC", serial_number="",
            inventory_number="", quantity="5",
        ))
        self.assertEqual(self.service.stock_receipts()[0]["quantity"], 5)

    def test_equipment_and_component_receipts_still_require_serial_number(self) -> None:
        for category, item_type in (("Оборудование", "Сервер"), ("Компоненты", "RAM")):
            with self.assertRaisesRegex(WarehouseError, "S/N обязателен"):
                self.service.add_stock_receipt(**self.new_receipt(
                    category=category, item_type=item_type,
                    serial_number="", inventory_number="",
                ))

    def test_balance_exposes_supplier_type_and_category(self) -> None:
        self.service.add_stock_receipt(**self.new_receipt(
            supplier="ООО Поставка", category="Компоненты", item_type="NIC",
        ))
        row = next(x for x in self.service.stock_balance() if x["serial_number"] == "SN-STAGE2-001")
        self.assertEqual(row["supplier"], "ООО Поставка")
        self.assertEqual(row["item_type"], "NIC")
        self.assertEqual(row["category"], "Компоненты")
        self.assertEqual(self.service.stock_balance(category="Компоненты", item_type="NIC"), [row])

    def test_daily_report_saves_multiple_work_log_rows_atomically(self) -> None:
        today = date.today().isoformat()
        saved = self.service.add_work_logs([
            {"work_date": today, "task_source": "Rooms", "task_type": "ЗНР",
             "task_number": "1", "description": "Работа 1", "status": "Выполнено"},
            {"work_date": today, "task_source": "Склад", "task_type": "ПНР",
             "task_number": "2", "description": "Работа 2", "status": "Ожидание"},
        ])
        self.assertEqual(saved, 2)
        self.assertEqual(len(self.service.work_logs(today, today)), 2)

    def test_ready_report_import_is_not_in_report_navigation(self) -> None:
        self.assertNotIn("['uploaded','Загруженные отчеты']", HTML)
        self.assertIn("Сохранить отчет", HTML)
        self.assertIn("+ Добавить задачу", HTML)


if __name__ == "__main__":
    unittest.main()
