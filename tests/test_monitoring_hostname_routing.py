from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from inventory.migration.xlsx_cells import write_text_xlsx
from inventory.monitoring.facade import MonitoringFacade

from inventory.monitoring.hostname_routing import (
    DIGITAL_RULES_NAME,
    TECH_RULES_NAME,
    RoutingDecision,
    build_email_body,
    build_email_subject,
    dedupe_recipients,
    greeting_for_hour,
    resolve_hostname_routing,
)
from scripts.generate_hostname_rules import build_digital_payload, build_tech_payload


class MonitoringHostnameRoutingTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.rules_dir = Path(self._tmp.name)

    def write_rules(self, tech_rules: list[dict], digital_hostnames: list[str] | None = None) -> None:
        tech = {
            "version": 1,
            "cc_exclusions": ["Excluded.One", "Excluded.Two"],
            "rules": tech_rules,
        }
        digital = {
            "version": 1,
            "default_to": ["Digital.Primary", "Digital.Secondary"],
            "default_cc": ["Digital.Primary@x5.ru", "Copy.One", "copy.one", " Copy.Two "],
            "hostnames": digital_hostnames or [],
        }
        (self.rules_dir / TECH_RULES_NAME).write_text(json.dumps(tech), encoding="utf-8")
        (self.rules_dir / DIGITAL_RULES_NAME).write_text(json.dumps(digital), encoding="utf-8")

    @staticmethod
    def tech_rule(pattern: str, *, salt: bool = False) -> dict:
        return {
            "hostname_pattern": pattern,
            "match_type": "wildcard",
            "project": "Salt" if salt else "X5Tech",
            "is_salt": salt,
            "to": ["Owner.One", "owner.one", "Owner.Two"],
            "cc": ["Excluded.One@x5.ru", "Excluded.Two", "Copy.One", " copy.one "],
        }

    def test_x5tech_rule_sets_tag_and_filters_cc(self) -> None:
        self.write_rules([self.tech_rule("server-*")])
        decision = resolve_hostname_routing(" SERVER-01 ", rules_dir=self.rules_dir)
        self.assertTrue(decision.email_ready)
        self.assertEqual(decision.tag, "[X5Tech]")
        self.assertEqual(decision.to, ("Owner.One", "Owner.Two"))
        self.assertEqual(decision.cc, ("Copy.One",))

    def test_salt_has_priority_over_digital(self) -> None:
        self.write_rules([self.tech_rule("salt-*", salt=True)], ["salt-app-03"])
        decision = resolve_hostname_routing("salt-app-03", rules_dir=self.rules_dir)
        self.assertEqual(decision.tag, "[Salt]")
        self.assertTrue(any("Salt" in warning for warning in decision.warnings))

    def test_salt_has_priority_over_more_specific_x5tech_rule(self) -> None:
        salt = self.tech_rule("shared-*", salt=True)
        x5tech = self.tech_rule("shared-server-01")
        x5tech["match_type"] = "exact"
        self.write_rules([salt, x5tech])
        decision = resolve_hostname_routing("shared-server-01", rules_dir=self.rules_dir)
        self.assertEqual(decision.tag, "[Salt]")
        self.assertTrue(any("приоритет Salt" in warning for warning in decision.warnings))

    def test_digital_has_priority_over_non_salt_tech(self) -> None:
        self.write_rules([self.tech_rule("shared-*")], ["shared-01"])
        decision = resolve_hostname_routing("shared-01", rules_dir=self.rules_dir)
        self.assertEqual(decision.tag, "[Digital]")
        self.assertEqual(decision.to, ("Digital.Primary", "Digital.Secondary"))
        self.assertEqual(decision.cc, ("Copy.One", "Copy.Two"))
        self.assertTrue(any("Digital" in warning for warning in decision.warnings))

    def test_unknown_hostname_does_not_choose_random_project(self) -> None:
        self.write_rules([self.tech_rule("known-*")])
        decision = resolve_hostname_routing("unknown-01", rules_dir=self.rules_dir)
        self.assertFalse(decision.email_ready)
        self.assertEqual(decision.tag, "")
        self.assertTrue(any("не найден" in error for error in decision.errors))

    def test_broken_tech_file_does_not_break_valid_digital_rule(self) -> None:
        (self.rules_dir / TECH_RULES_NAME).write_text("{broken", encoding="utf-8")
        digital = {
            "version": 1,
            "default_to": ["Digital.Primary", "Digital.Secondary"],
            "default_cc": ["Copy.One"],
            "hostnames": ["digital-01"],
        }
        (self.rules_dir / DIGITAL_RULES_NAME).write_text(json.dumps(digital), encoding="utf-8")
        decision = resolve_hostname_routing("digital-01", rules_dir=self.rules_dir)
        self.assertTrue(decision.email_ready)
        self.assertEqual(decision.tag, "[Digital]")
        self.assertTrue(decision.warnings)

    def test_missing_files_return_controlled_error(self) -> None:
        decision = resolve_hostname_routing("server-01", rules_dir=self.rules_dir)
        self.assertFalse(decision.email_ready)
        self.assertTrue(decision.warnings)
        self.assertTrue(decision.errors)

    def test_invalid_hostname_and_header_injection_are_rejected(self) -> None:
        self.write_rules([self.tech_rule("server-*")])
        decision = resolve_hostname_routing("server-01\r\nBcc: attacker", rules_dir=self.rules_dir)
        self.assertFalse(decision.email_ready)
        self.assertIn("недопустимый формат", decision.errors[0])

    def test_invalid_rules_file_fails_closed(self) -> None:
        self.write_rules([self.tech_rule("known-*")], ["digital-01", "DIGITAL-01"])
        decision = resolve_hostname_routing("digital-01", rules_dir=self.rules_dir)
        self.assertFalse(decision.email_ready)
        self.assertTrue(any("отклонён" in warning for warning in decision.warnings))

    def test_rules_cache_reloads_after_file_replacement(self) -> None:
        self.write_rules([self.tech_rule("first-*")])
        self.assertTrue(
            resolve_hostname_routing("first-01", rules_dir=self.rules_dir).email_ready
        )
        self.write_rules([self.tech_rule("second-*")])
        decision = resolve_hostname_routing("first-01", rules_dir=self.rules_dir)
        self.assertFalse(decision.email_ready)
        self.assertTrue(any("не найден" in error for error in decision.errors))

    def test_unsafe_regex_configuration_is_rejected(self) -> None:
        rule = self.tech_rule("(a+)+")
        rule["match_type"] = "regex"
        rule["regex"] = rule.pop("hostname_pattern")
        self.write_rules([rule])
        decision = resolve_hostname_routing("aaaa", rules_dir=self.rules_dir)
        self.assertFalse(decision.email_ready)
        self.assertTrue(any("вложенные квантификаторы" in warning for warning in decision.warnings))

    def test_equal_tech_matches_are_reported_as_ambiguous(self) -> None:
        first = self.tech_rule("server-*")
        second = self.tech_rule("server-*")
        second["to"] = ["Different.Owner"]
        self.write_rules([first, second])
        decision = resolve_hostname_routing("server-01", rules_dir=self.rules_dir)
        self.assertFalse(decision.email_ready)
        self.assertTrue(any("равнозначных" in error for error in decision.errors))

    def test_subject_and_body_use_required_format(self) -> None:
        subject = build_email_subject("[Digital]", "digital-db-02", "высокая загрузка CPU")
        body = build_email_body(
            "digital-db-02",
            "высокая загрузка CPU",
            "Текст Rooms без изменений.",
            at=datetime(2026, 7, 15, 18, 30),
        )
        self.assertEqual(subject, "[Digital] digital-db-02 высокая загрузка CPU")
        self.assertTrue(body.startswith("Коллеги, добрый вечер!\n\n"))
        self.assertTrue(body.endswith("Текст Rooms без изменений."))

    def test_greeting_covers_all_time_ranges(self) -> None:
        self.assertEqual(greeting_for_hour(5), "Коллеги, доброе утро!")
        self.assertEqual(greeting_for_hour(12), "Коллеги, добрый день!")
        self.assertEqual(greeting_for_hour(18), "Коллеги, добрый вечер!")
        self.assertEqual(greeting_for_hour(23), "Коллеги, доброй ночи!")
        self.assertEqual(greeting_for_hour(4), "Коллеги, доброй ночи!")

    def test_recipient_deduplication_is_case_insensitive(self) -> None:
        self.assertEqual(
            dedupe_recipients([" User.One ", "user.one", "USER.ONE@x5.ru", "User.Two"]),
            ["User.One", "User.Two"],
        )

    def test_facade_exposes_only_the_isolated_routing_capability(self) -> None:
        self.write_rules([self.tech_rule("server-*")])
        facade = MonitoringFacade(rules_dir=self.rules_dir)
        decision = facade.resolve_hostname("server-01")
        self.assertTrue(decision.email_ready)
        status = facade.module_status()
        self.assertTrue(status["capabilities"]["hostname_routing"])
        self.assertFalse(status["capabilities"]["manual_search"])
        self.assertFalse(status["enabled"])


class DigitalRulesGenerationTest(unittest.TestCase):
    def test_reads_x5t_support_hostname_from_column_f(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "digital.xlsx"
            write_text_xlsx(
                source,
                {
                    "Технические имена": (
                        ["N", "N_IN_SRV", "ID", "Name", "X5D_OS_HostName", "X5T_Support_HostName"],
                        [
                            ["1", "79", "999", "Reserve", "wrong-os-host", "digital-support-001"],
                            ["2", "27", "10", "ELK", "wrong-os-host-2", "digital-support-002"],
                        ],
                    ),
                    "Сервера": (
                        ["N", "ID", "Name", "Tag", "IP", "Hostname (имя хоста)"],
                        [["1", "999", "Reserve", "tag", "127.0.0.1", "wrong-server-sheet-host"]],
                    ),
                },
            )

            payload, stats = build_digital_payload(
                source,
                ["Digital.Owner@x5.ru", "Copy.One@x5.ru"],
                ["Digital.Owner"],
            )

        self.assertEqual(payload["source_sheet"], "Технические имена")
        self.assertEqual(payload["source_column"], "F")
        self.assertEqual(payload["source_header"], "X5T_Support_HostName")
        self.assertEqual(payload["hostnames"], ["digital-support-001", "digital-support-002"])
        self.assertEqual(stats.unique_hostnames, 2)

    def test_generates_tech_rules_without_optional_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "tech.xlsx"
            write_text_xlsx(
                source,
                {
                    "Routing": (
                        ["Технический владелец", "адресаты", "Примеры нейминга", "Всегда добавляем"],
                        [
                            ["Platform", "Owner.One@x5.ru", "server-", "Copy.One@x5.ru"],
                            ["Salt", "Salt.Owner@x5.ru", "salt-*", "Excluded.One@x5.ru"],
                        ],
                    )
                },
            )
            payload, stats, global_cc = build_tech_payload(
                source,
                cc_exclusions=["Excluded.One"],
            )

        self.assertEqual(stats.unique_hostnames, 2)
        self.assertEqual(payload["rules"][0]["hostname_pattern"], "server-*")
        self.assertTrue(payload["rules"][1]["is_salt"])
        self.assertIn("Copy.One@x5.ru", global_cc)
        self.assertNotIn("Excluded.One@x5.ru", payload["rules"][0]["cc"])

    def test_generator_help_works_on_stdlib_only_runtime(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/generate_hostname_rules.py", "--help"],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--tech-source", result.stdout)

    def test_generator_cli_writes_both_rule_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tech_source = root / "tech.xlsx"
            digital_source = root / "digital.xlsx"
            output = root / "rules"
            write_text_xlsx(
                tech_source,
                {
                    "Routing": (
                        ["Технический владелец", "адресаты", "Примеры нейминга", "Всегда добавляем"],
                        [["Platform", "Owner.One", "server-", "Copy.One"]],
                    )
                },
            )
            write_text_xlsx(
                digital_source,
                {
                    "Технические имена": (
                        ["A", "B", "C", "D", "X5D_OS_HostName", "X5T_Support_HostName"],
                        [["1", "2", "3", "4", "ignored-host", "digital-host-01"]],
                    )
                },
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/generate_hostname_rules.py",
                    "--tech-source",
                    str(tech_source),
                    "--digital-source",
                    str(digital_source),
                    "--digital-default-to",
                    "Digital.Owner",
                    "--output-dir",
                    str(output),
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            tech = json.loads((output / TECH_RULES_NAME).read_text(encoding="utf-8"))
            digital = json.loads((output / DIGITAL_RULES_NAME).read_text(encoding="utf-8"))

        self.assertEqual(tech["rules"][0]["hostname_pattern"], "server-*")
        self.assertEqual(digital["hostnames"], ["digital-host-01"])
        self.assertEqual(digital["default_to"], ["Digital.Owner"])


if __name__ == "__main__":
    unittest.main()
