from __future__ import annotations

import dataclasses
import unittest

from inventory.migration.canonical_naming import (
    build_component_name,
    build_equipment_name,
)
from inventory.migration.models import AUTO_APPROVED, CANDIDATE, PENDING_REVIEW
from inventory.migration.reference_data import (
    DOMAIN_DEFINITIONS,
    REFERENCE_SEEDS,
    build_alias,
    model_identity,
    normalize_reference_key,
    propose_unknown_reference,
    resolve_alias_safety,
    vendor_scoped_model_key,
)


class ReferenceDataFoundationTest(unittest.TestCase):
    def test_all_requested_domains_are_defined_once(self) -> None:
        expected = {
            "object_kind", "equipment_category", "equipment_role", "equipment_type",
            "component_type", "cable_type", "cable_category", "vendor", "model",
            "catalog_item", "supplier", "datacenter", "warehouse_location",
            "storage_zone", "rack", "shelf", "project", "unit_of_measure",
            "operation_source", "issue_reason",
        }
        keys = [definition.key for definition in DOMAIN_DEFINITIONS]
        self.assertEqual(set(keys), expected)
        self.assertEqual(len(keys), len(expected))

    def test_controlled_typing_seeds_are_present(self) -> None:
        values = {(value.domain, value.canonical_value) for value in REFERENCE_SEEDS}
        self.assertTrue({
            ("object_kind", "equipment"),
            ("object_kind", "component"),
            ("object_kind", "cable"),
            ("object_kind", "consumable"),
            ("object_kind", "unknown"),
            ("equipment_type", "server"),
            ("equipment_type", "SAN switch"),
            ("component_type", "memory"),
            ("component_type", "RAID controller"),
        }.issubset(values))

    def test_reference_models_are_immutable(self) -> None:
        seed = REFERENCE_SEEDS[0]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            seed.display_name = "changed"  # type: ignore[misc]

    def test_nfkc_case_and_whitespace_share_one_key(self) -> None:
        # Full-width Latin letters are normalized by NFKC.
        self.assertEqual(normalize_reference_key("  ＤＥＬＬ\t  PowerEdge  "), "dell poweredge")
        decision = resolve_alias_safety("vendor", "  ＤＥＬＬ  ", "Dell")
        self.assertEqual(decision.resolution_status, AUTO_APPROVED)
        self.assertFalse(decision.requires_manual_review)

    def test_safe_alias_contains_required_evidence(self) -> None:
        alias = build_alias(
            "vendor", " dell ", "Dell", canonical_id=7,
            source_file="source.xlsx", source_sheet="ПРИХОД", usage_count=42,
        )
        self.assertEqual(alias.resolution_status, AUTO_APPROVED)
        self.assertEqual(alias.normalized_source_key, "dell")
        self.assertEqual(alias.canonical_id, 7)
        self.assertEqual(alias.usage_count, 42)

    def test_prohibited_vendor_pairs_are_never_auto_merged(self) -> None:
        for left, right in (("Huawei", "xFusion"), ("HP", "HPE"), ("Hunix", "Hynix")):
            with self.subTest(left=left, right=right):
                decision = resolve_alias_safety("vendor", left, right)
                self.assertEqual(decision.resolution_status, PENDING_REVIEW)
                self.assertTrue(decision.requires_manual_review)
                self.assertEqual(decision.rule, "PROHIBITED_SEMANTIC_MERGE")

    def test_different_legal_supplier_names_require_review(self) -> None:
        decision = resolve_alias_safety(
            "supplier", 'ООО "Поставка"', 'АО "Поставка"'
        )
        self.assertEqual(decision.resolution_status, PENDING_REVIEW)
        self.assertEqual(decision.rule, "SEMANTIC_REVIEW_REQUIRED")

    def test_models_are_vendor_scoped(self) -> None:
        self.assertNotEqual(
            vendor_scoped_model_key("Dell", "R650"),
            vendor_scoped_model_key("HPE", "R650"),
        )
        identity = model_identity(" Dell ", " PowerEdge  R650 ")
        self.assertEqual(identity.scoped_key, "dell\x1fpoweredge r650")

    def test_distinct_r200_and_r220_models_never_merge(self) -> None:
        self.assertNotEqual(
            vendor_scoped_model_key("Vegman", "R200"),
            vendor_scoped_model_key("Vegman", "R220"),
        )
        decision = resolve_alias_safety(
            "model", "R200", "R220",
            source_vendor="Vegman", canonical_vendor="Vegman",
        )
        self.assertEqual(decision.resolution_status, PENDING_REVIEW)
        self.assertEqual(decision.rule, "DISTINCT_MODEL")

    def test_model_alias_needs_equal_vendor_scope(self) -> None:
        safe = resolve_alias_safety(
            "model", " POWEREDGE  R650 ", "PowerEdge R650",
            source_vendor="Dell", canonical_vendor="DELL",
        )
        self.assertEqual(safe.resolution_status, AUTO_APPROVED)
        conflict = resolve_alias_safety(
            "model", "R650", "R650",
            source_vendor="Dell", canonical_vendor="HPE",
        )
        self.assertEqual(conflict.rule, "MODEL_VENDOR_CONFLICT")

    def test_unknown_value_is_candidate_only(self) -> None:
        candidate = propose_unknown_reference(
            "vendor", " New Vendor ", source_file="source.xlsx", source_sheet="ПРИХОД",
        )
        self.assertEqual(candidate.resolution_status, CANDIDATE)
        self.assertTrue(candidate.requires_manual_review)
        self.assertEqual(candidate.proposed_value, "New Vendor")
        self.assertFalse(hasattr(candidate, "active"))

    def test_equipment_names_use_structured_type_vendor_model(self) -> None:
        self.assertEqual(build_equipment_name("server", "Dell", "PowerEdge R650"), "Сервер Dell PowerEdge R650")
        self.assertEqual(build_equipment_name("server", "Vegman", "R200"), "Сервер Vegman R200")
        self.assertEqual(build_equipment_name("server", "Vegman", "R220"), "Сервер Vegman R220")
        self.assertEqual(build_equipment_name("switch", "Huawei", "CE6865"), "Коммутатор Huawei CE6865")
        self.assertEqual(
            build_equipment_name("storage system", "Huawei", "OceanStor 5500"),
            "Система хранения данных Huawei OceanStor 5500",
        )

    def test_component_names_use_model_or_part_number(self) -> None:
        self.assertEqual(
            build_component_name("memory", "Samsung", main_characteristic="32 GB DDR4"),
            "Оперативная память Samsung 32 GB DDR4",
        )
        self.assertEqual(
            build_component_name("SSD", "Intel", "D7-P5500", main_characteristic="7.68 TB"),
            "SSD Intel D7-P5500 7.68 TB",
        )
        self.assertEqual(
            build_component_name("NIC", "Intel", part_number="X710"),
            "Сетевой адаптер Intel X710",
        )


if __name__ == "__main__":
    unittest.main()
