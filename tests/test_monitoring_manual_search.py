from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from inventory.monitoring.facade import MonitoringError, MonitoringFacade
from inventory.monitoring.hostname_routing import RoutingDecision
from inventory.monitoring.manual_search import (
    ManualSearchError,
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
            run_manual_search("bad host", "BMC unavailable", collect_dcim=False)

    def test_dcim_parser_extracts_operational_fields(self) -> None:
        parsed = parse_dcim_page(
            "Имя\nMN-SRV-01\nМодель\nPowerEdge R760\n"
            "Серийный номер мониторинг\nABC123\n"
            "ЦОД IXcellerate / Маш.зал 1 / Ряд A / Стойка 12 / Unit 20\n"
            "Технический владелец\nOwner Name owner@x5.ru\nИнформационная система\nERP",
            "mn-srv-01",
        )
        self.assertEqual(parsed["host"], "MN-SRV-01")
        self.assertEqual(parsed["model"], "PowerEdge R760")
        self.assertEqual(parsed["serial"], "ABC123")
        self.assertIn("owner@x5.ru", parsed["owner"])

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
        self.assertIn(event["message"], event["email_text"])
        self.assertEqual(event["email_to"], ["Owner.One"])

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
