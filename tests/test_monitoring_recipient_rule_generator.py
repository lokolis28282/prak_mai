from __future__ import annotations

import unittest

from scripts import integrate_recipient_rules_from_xlsx as rules


class MonitoringRecipientRuleGeneratorTest(unittest.TestCase):
    def example(
        self,
        row: int,
        hostname: str,
        recipients: tuple[str, ...] = ("owner@example.invalid",),
        *,
        project: str = "Project A",
        information_system: str = "System A",
        route_project: str = "X5Tech",
    ) -> rules.Example:
        return rules.Example(
            row_number=row,
            hostname=hostname,
            hostname_norm=hostname.casefold(),
            hostname_mask=rules.hostname_family(hostname),
            information_system=information_system,
            information_system_norm=rules.normalize_information_system(
                information_system
            ),
            project=project,
            project_norm=rules.normalize_project(project),
            comment="",
            recipients=recipients,
            route_project=route_project,
        )

    def test_normalization_and_recipient_deduplication(self) -> None:
        self.assertEqual(rules.hostname_family("APP-SRV-001"), "app-srv-*")
        self.assertEqual(
            rules.split_recipients(
                "Owner.One@x5.ru; owner.one@x5.ru, second@example.invalid"
            ),
            ("owner.one@x5.ru", "second@example.invalid"),
        )

    def test_repeated_family_derives_only_confident_candidates(self) -> None:
        examples = [
            self.example(index, f"APP-SRV-{index:03d}")
            for index in range(1, 4)
        ]

        accepted, rejected = rules.derive_candidates(examples)

        family = [
            candidate
            for candidate in accepted
            if candidate.hostname_pattern == "app-srv-*"
            and not candidate.dcim_project
            and not candidate.information_system
        ]
        self.assertEqual(len(family), 1)
        self.assertEqual(family[0].confidence, 1.0)
        self.assertTrue(all(item["confidence"] <= 1.0 for item in rejected))

    def test_conflicting_existing_rule_is_preserved(self) -> None:
        candidate = rules.exact_rule(self.example(1, "APP-SRV-001"))
        existing = [
            {
                "hostname": "app-srv-001",
                "match_type": "exact",
                "project": "X5Tech",
                "is_salt": False,
                "to": ["different@example.invalid"],
                "cc": [],
            }
        ]

        merged, added, conflicts = rules.merge_rules(
            existing, [candidate], "confirmed.xlsx"
        )

        self.assertEqual(merged, existing)
        self.assertEqual(added, [])
        self.assertEqual(len(conflicts), 1)

    def test_group_holdout_is_deterministic_and_disjoint(self) -> None:
        examples = [
            self.example(index, f"FAMILY-{index:03d}")
            for index in range(1, 11)
        ]

        first = rules.group_holdout(examples)
        second = rules.group_holdout(examples)

        self.assertEqual(first, second)
        self.assertFalse(set(first[0]) & set(first[1]))
        self.assertEqual(len(first[0]) + len(first[1]), len(examples))


if __name__ == "__main__":
    unittest.main()
