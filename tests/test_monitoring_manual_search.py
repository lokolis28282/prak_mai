from __future__ import annotations

from datetime import datetime
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from inventory.monitoring.facade import MonitoringError, MonitoringFacade
from inventory.monitoring.hostname_routing import RoutingDecision
from inventory.monitoring.hostname_routing import build_email_body
from inventory.monitoring.manual_search import (
    ManualSearchError,
    build_rooms_message,
    extract_dcim_labeled_value,
    normalize_hostname_input,
    parse_dcim_page,
    run_manual_search,
    validate_hostname,
    validate_problem_text,
)


class MonitoringManualSearchTest(unittest.TestCase):
    def test_input_validation_rejects_unsafe_or_empty_values(self) -> None:
        self.assertFalse(validate_hostname("host\r\nBcc: attacker")[0])
        self.assertFalse(validate_hostname("x")[0])
        self.assertFalse(validate_problem_text("")[0])
        with self.assertRaises(ManualSearchError):
            run_manual_search("bad/host", "BMC unavailable", collect_dcim=False)

    def test_hostname_input_removes_all_unicode_whitespace(self) -> None:
        cases = {
            "p1-nx-apl0039": "p1-nx-apl0039",
            " p1-nx-apl0039": "p1-nx-apl0039",
            "p1-nx-apl0039 ": "p1-nx-apl0039",
            " p1-nx-apl0039 ": "p1-nx-apl0039",
            "p1-nx- apl0039": "p1-nx-apl0039",
            "p1 -nx-apl0039": "p1-nx-apl0039",
            "p1-nx-apl 0039": "p1-nx-apl0039",
            "MSK-DPRO- ESX158": "MSK-DPRO-ESX158",
            "  p2-x5d-001": "p2-x5d-001",
            "p1-nx-\tapl0039": "p1-nx-apl0039",
            "p1-nx-apl0039\n": "p1-nx-apl0039",
            "p1-nx-\u00a0apl0039": "p1-nx-apl0039",
        }
        for entered, expected in cases.items():
            with self.subTest(entered=entered):
                self.assertEqual(normalize_hostname_input(entered), expected)
                self.assertTrue(validate_hostname(entered)[0])

    def test_whitespace_only_hostname_is_rejected_without_search(self) -> None:
        for entered in (" ", "     ", "\t", "\n", " \t \n ", "\u00a0"):
            with self.subTest(entered=repr(entered)):
                self.assertEqual(normalize_hostname_input(entered), "")
                self.assertFalse(validate_hostname(entered)[0])
                with self.assertRaises(ManualSearchError):
                    run_manual_search(entered, "BMC unavailable", collect_dcim=False)

    def test_manual_search_uses_normalized_hostname_everywhere(self) -> None:
        decision = RoutingDecision(
            hostname="p1-nx-apl0039",
            project="X5Tech",
            tag="[X5Tech]",
            to=("Owner.One",),
        )
        with patch(
            "inventory.monitoring.manual_search.resolve_hostname_routing",
            return_value=decision,
        ) as resolve:
            result = run_manual_search(
                " p1-nx-\u00a0apl 0039\t",
                "BMC unavailable",
                collect_dcim=False,
            )
        self.assertEqual(result["event"]["input_host"], "p1-nx-apl0039")
        self.assertEqual(result["event"]["host"], "p1-nx-apl0039")
        self.assertIn("p1-nx-apl0039", result["event"]["message"])
        resolve.assert_called_once()
        self.assertEqual(resolve.call_args.args[0], "p1-nx-apl0039")

    def test_dcim_parser_extracts_operational_fields(self) -> None:
        parsed = parse_dcim_page(
            "Имя\nMN-SRV-01\nМодель\nPowerEdge R760\n"
            "Серийный номер мониторинг\nABC123\n"
            "ЦОД IXcellerate / Маш.зал 1 / Ряд A / Стойка 12 / Unit 20\n"
            "Технический владелец\nOwner Name owner@example.invalid\n"
            "Информационная система\nERP\nПроект\nProject ABC\n"
            "Класс критичности\nMISSION CRITICAL\nITSM\nИНЦ-023484089",
            "mn-srv-01",
        )
        self.assertEqual(parsed["host"], "MN-SRV-01")
        self.assertEqual(parsed["model"], "PowerEdge R760")
        self.assertEqual(parsed["serial"], "ABC123")
        self.assertIn("owner@example.invalid", parsed["owner"])
        self.assertEqual(parsed["information_system"], "ERP")
        self.assertEqual(parsed["project"], "Project ABC")
        self.assertEqual(parsed["criticality_class"], "MISSION CRITICAL")
        self.assertEqual(parsed["itsm"], "ИНЦ-023484089")

    def test_dcim_parser_keeps_missing_criticality_as_fallback(self) -> None:
        parsed = parse_dcim_page(
            "Имя\nMN-SRV-01\nКласс критичности\nИнформационная система\nERP",
            "mn-srv-01",
        )

        self.assertEqual(parsed["criticality_class"], "-")

    def test_rooms_message_matches_required_template_with_all_fields(self) -> None:
        problem = (
            "Storage disk (Disk.Bay.5:\\Enclosure/Internal[0-1]:RAID.Slot.1-1): "
            "Health is in critical state"
        )
        message = build_rooms_message(
            {
                "host": "MSK-DPRO-TRN070",
                "model": "POWEREDGE R840",
                "serial": "F22JLK3",
                "location_raw": "ЦОД DataPro Маш.зал №16 Ряд B / 16B08 / U 15–16",
                "criticality_class": "MISSION CRITICAL",
            },
            problem,
            project="[X5TECH]",
            itsm="ИНЦ-023484089",
            at=datetime(2026, 8, 8, 23, 0),
        )

        self.assertEqual(
            message,
            "Коллеги, доброй ночи!\n\n"
            f"На хосте MSK-DPRO-TRN070 наблюдается проблема: {problem}\n\n"
            f"1. Описание проблемы: {problem}\n"
            "2. имя хоста: MSK-DPRO-TRN070\n"
            "3. Модель оборудования: POWEREDGE R840\n"
            "4. S/N: F22JLK3\n"
            "5. ЦОД DataPro Маш.зал №16 Ряд B / 16B08 / U 15–16\n"
            "6. Проект: [X5TECH]\n"
            "7. ITSM: ИНЦ-023484089\n"
            "8. Отложенный ремонт: YES\n"
            "9. Класс критичности: MISSION CRITICAL",
        )
        self.assertEqual(message.count(problem), 2)

    def test_criticality_flows_to_rooms_and_outlook_body(self) -> None:
        rooms = build_rooms_message(
            {
                "host": "SERVER-01",
                "criticality_class": "MISSION CRITICAL",
            },
            "Disk failure",
            at=datetime(2026, 8, 8, 12, 0),
        )
        outlook = build_email_body(
            "SERVER-01",
            "Disk failure",
            rooms,
            at=datetime(2026, 8, 8, 12, 0),
        )

        self.assertIn("9. Класс критичности: MISSION CRITICAL", rooms)
        self.assertIn("9. Класс критичности: MISSION CRITICAL", outlook)
        self.assertEqual(rooms, outlook)

    def test_dcim_parser_reads_inline_criticality_value(self) -> None:
        parsed = parse_dcim_page(
            "Имя\nMN-SRV-01\nКласс критичности MISSION CRITICAL\nИнформационная система\nERP",
            "mn-srv-01",
        )
        self.assertEqual(parsed["criticality_class"], "MISSION CRITICAL")

    def test_dcim_dom_reader_uses_label_sibling_and_expands_section(self) -> None:
        class Element:
            def __init__(self, text="", candidates=None, attrs=None):
                self.text = text
                self.candidates = candidates or []
                self.attrs = attrs or {}
                self.clicked = False

            def get_attribute(self, name):
                return self.attrs.get(name, "")

            def click(self):
                self.clicked = True

            def find_elements(self, by, xpath):
                del by
                return self.candidates if "following-sibling" in xpath else []

        section = Element(attrs={"aria-expanded": "false", "class": "collapsed"})
        value = Element(text="MISSION CRITICAL")
        label = Element(text="Класс критичности", candidates=[value])

        class Driver:
            def find_elements(self, by, xpath):
                del by
                if "Принадлежность к ИС/ЭИС" in xpath:
                    return [section]
                if "Класс критичности" in xpath:
                    return [label]
                return []

        by = type("By", (), {"XPATH": "xpath"})
        with patch(
            "inventory.monitoring.manual_search.import_selenium",
            return_value=(None, by, None, None, None),
        ):
            result = extract_dcim_labeled_value(Driver(), "Класс критичности")

        self.assertTrue(section.clicked)
        self.assertEqual(result, "MISSION CRITICAL")

    def test_rooms_message_uses_fallbacks_without_losing_long_problem(self) -> None:
        problem = "Disk / RAID [0] (slot): \\ state " + "critical " * 200
        message = build_rooms_message({"host": "SERVER-01"}, problem)

        self.assertEqual(message.count(problem.strip()), 2)
        self.assertIn("3. Модель оборудования: -", message)
        self.assertIn("4. S/N: -", message)
        self.assertIn("5. -", message)
        self.assertIn("6. Проект: -", message)
        self.assertIn("7. ITSM: -", message)
        self.assertIn("9. Класс критичности: -", message)

    def test_manual_result_uses_safe_hostname_routing(self) -> None:
        decision = RoutingDecision(
            hostname="server-01",
            project="X5Tech",
            tag="[X5Tech]",
            to=("Owner.One",),
            cc=("Copy.One",),
            matched_rules=("Tech: server-*",),
        )
        with patch(
            "inventory.monitoring.manual_search.resolve_hostname_routing",
            return_value=decision,
        ):
            result = run_manual_search(
                "server-01",
                "BMC: No health data more than 10m",
                collect_dcim=False,
            )
        event = result["event"]
        self.assertTrue(event["email_ready"])
        self.assertEqual(event["email_body"], event["message"])
        self.assertTrue(event["email_text"].endswith(event["message"]))
        self.assertEqual(event["email_to"], ["Owner.One"])
        self.assertIn("6. Проект: [X5Tech]", event["message"])
        self.assertIn("7. ITSM: -", event["message"])
        self.assertIn("9. Класс критичности: -", event["message"])
        self.assertTrue(any("класс критичности не найден" in line for line in event["logs"]))

    def test_facade_requires_explicit_mock_when_collection_is_disabled(self) -> None:
        facade = MonitoringFacade(collect_dcim=False, development_mock=False)
        with self.assertRaises(MonitoringError):
            facade.manual_search("server-01", "BMC unavailable")

    def test_explicit_development_mock_is_clearly_marked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            rules = Path(temp_dir)
            (rules / "Hostname Tech.json").write_text(
                json.dumps({"version": 1, "cc_exclusions": [], "rules": []}),
                encoding="utf-8",
            )
            (rules / "Hostname Digital.json").write_text(
                json.dumps({"version": 1, "default_to": [], "default_cc": [], "hostnames": []}),
                encoding="utf-8",
            )
            facade = MonitoringFacade(
                rules_dir=rules,
                collect_dcim=False,
                development_mock=True,
            )
            result = facade.manual_search("server-01", "BMC unavailable")
        self.assertTrue(result["development_mock"])
        self.assertIn("[DEV]", result["event"]["logs"][0])


if __name__ == "__main__":
    unittest.main()
