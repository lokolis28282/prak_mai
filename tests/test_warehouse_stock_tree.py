from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from inventory.core.application import create_application_context
from inventory.db import connect
from inventory.service import WarehouseError, WarehouseService


class WarehouseStockTreeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "warehouse.db"
        self.service = WarehouseService(self.db_path)
        self.context = create_application_context(
            self.db_path, service=self.service, warehouse_contour="demo"
        )
        rows = [
            ("Server Dell PowerEdge R760", "SN-001", "INV-001", "Dell", "R760", "Server", "", "", 1),
            ("Server Dell PowerEdge R760", "SN-002", "INV-002", "Dell", "R760", "Server", "", "", 1),
            ("ConnectX-7", "SN-003", "INV-003", "Mellanox", "CX75210AA", "", "Network adapter", "", 2),
            ("Memory DDR4 64GB", "SN-004", "INV-004", "", "", "", "RAM", "", 4),
            ("AOC cable 100G", "", "", "Modultech", "MT-AOC-100G", "", "", "AOC", 3),
            ("AOC cable 100G", "", "", "Modultech", "MT-AOC-100G", "", "", "AOC", 4),
            ("PDU 100% load", "SN-%", "INV-%", "APC", "AP8853", "PDU", "", "", 1),
        ]
        with connect(self.db_path) as db:
            db.executemany(
                """INSERT INTO stock_receipts(
                       receipt_date,responsible,item_name,project,serial_number,
                       inventory_number,supplier,vendor,model,shelf,object_name,
                       datacenter,equipment_type,component_type,cable_type,unit,quantity
                   ) VALUES ('2026-07-21','Test',?,'Project',?,?,'Supplier',?,?,
                             'A-01','Warehouse','Ixcellerate',?,?,?,'шт',?)""",
                rows,
            )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def fetch(self, **kwargs):
        return self.context.warehouse.get_stock_tree(**kwargs)

    def test_root_is_aggregated_and_totals_cover_full_result(self) -> None:
        result = self.fetch(limit=2)
        self.assertEqual(result["level"], "category")
        self.assertEqual(len(result["nodes"]), 2)
        self.assertTrue(result["has_more"])
        self.assertGreater(result["node_count"], len(result["nodes"]))
        self.assertEqual(result["total"], {"positions": 6, "available": 16.0})
        self.assertTrue(all(node["kind"] == "group" for node in result["nodes"]))
        self.assertNotIn("receipt_id", json.dumps(result, ensure_ascii=False))
        complete = self.fetch()
        self.assertEqual(
            sum(node["positions"] for node in complete["nodes"]),
            complete["total"]["positions"],
        )
        self.assertEqual(
            sum(node["available"] for node in complete["nodes"]),
            complete["total"]["available"],
        )

    def test_four_aggregate_levels_are_lazy_and_model_is_terminal(self) -> None:
        category = self.fetch(level="category")["nodes"][0]
        self.assertEqual(category["label"], "Оборудование")
        item_type = self.fetch(level="item_type", path=category["path"])["nodes"][0]
        self.assertEqual(item_type["label"], "PDU")

        server_category = next(
            node for node in self.fetch(level="category")["nodes"]
            if node["label"] == "Оборудование"
        )
        server_type = next(
            node for node in self.fetch(level="item_type", path=server_category["path"])["nodes"]
            if node["label"] == "Server"
        )
        vendor = self.fetch(level="vendor", path=server_type["path"])["nodes"][0]
        model = self.fetch(level="model", path=vendor["path"])["nodes"][0]
        self.assertEqual(model["label"], "R760")
        self.assertEqual(model["positions"], 2)
        self.assertEqual(model["available"], 2.0)
        self.assertFalse(model["has_children"])
        self.assertIsNone(model["next_level"])
        self.assertNotIn("serial_number", model)

    def test_missing_values_are_human_readable_and_model_falls_back_to_name(self) -> None:
        root = self.fetch(filters={"query": "SN-004"})
        category = root["nodes"][0]
        item_type = self.fetch(level="item_type", path=category["path"], filters={"query": "SN-004"})["nodes"][0]
        vendor = self.fetch(level="vendor", path=item_type["path"], filters={"query": "SN-004"})["nodes"][0]
        self.assertEqual(vendor["label"], "Не указано")
        model = self.fetch(level="model", path=vendor["path"], filters={"query": "SN-004"})["nodes"][0]
        self.assertEqual(model["label"], "Memory DDR4 64GB")

    def test_search_escapes_sql_wildcards_and_empty_state_is_explicit(self) -> None:
        percent = self.fetch(filters={"query": "%"})
        self.assertEqual(percent["total"]["positions"], 1)
        missing = self.fetch(filters={"query": "definitely-missing"})
        self.assertEqual(missing["nodes"], [])
        self.assertEqual(missing["empty_reason"], "filtered")
        unfiltered = self.fetch(filters={"sort_by": "item_name", "sort_dir": "asc"})
        self.assertEqual(unfiltered["empty_reason"], "warehouse")

    def test_duplicate_cable_lots_become_one_position(self) -> None:
        result = self.fetch(filters={"query": "AOC cable 100G"})
        self.assertEqual(result["total"], {"positions": 1, "available": 7.0})

    def test_invalid_parent_path_is_rejected(self) -> None:
        with self.assertRaises(WarehouseError):
            self.fetch(level="vendor", path={"category": "Оборудование"})
        with self.assertRaises(WarehouseError):
            self.fetch(level="position", path={})

    def test_valid_but_missing_aggregate_branch_is_empty(self) -> None:
        result = self.fetch(
            level="model",
            path={
                "category": "Оборудование",
                "item_type": "Server",
                "vendor": "missing-vendor",
            },
        )
        self.assertEqual(result["nodes"], [])
        self.assertEqual(result["node_count"], 0)
        self.assertEqual(result["total"], {"positions": 0, "available": 0.0})

    def test_sort_and_node_ids_are_stable(self) -> None:
        first = self.fetch(level="category")
        second = self.fetch(level="category")
        self.assertEqual(
            [(node["id"], node["label"]) for node in first["nodes"]],
            [(node["id"], node["label"]) for node in second["nodes"]],
        )

    def test_overview_can_skip_legacy_balance_payload(self) -> None:
        overview = self.context.warehouse.get_overview(include_balance=False)
        self.assertEqual(overview["balance"], [])
        self.assertEqual(overview["balance_limit"], 0)
        self.assertEqual(overview["stats"]["cards"], 7)
        self.assertEqual(overview["stats"]["positions"], 6)


if __name__ == "__main__":
    unittest.main()
