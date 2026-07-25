from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor

# Initialize the existing package graph before importing Warehouse submodules directly.
from inventory.core.application import create_application_context  # noqa: F401
from inventory.reports.imports import ReportsPreviewStore
from inventory.shared.validators import WarehouseError
from inventory.warehouse.delivery_previews import DeliveryPreviewStore
from inventory.warehouse.previews import WarehousePreviewStore


EXPIRED_AT = "2000-01-01T00:00:00"


def rows(count: int) -> list[dict[str, str]]:
    return [{"serial_number": f"SN-{index}"} for index in range(count)]


def validation() -> dict[str, object]:
    return {"errors": [], "rows": []}


def delivery_preview(author: str, session: str, count: int) -> dict[str, object]:
    source = rows(count)
    return {
        "author": author,
        "session": session,
        "source_rows": source,
        "expanded_rows": [dict(row) for row in source],
        "validation_results": [{"valid": True} for _ in source],
    }


class WarehousePreviewStoreLimitsTest(unittest.TestCase):
    def test_rejects_single_oversized_preview_without_retaining_rows(self) -> None:
        store = WarehousePreviewStore(max_rows_per_preview=2, max_total_rows=4)

        with self.assertRaisesRegex(WarehouseError, "больше 2 строк"):
            store.store(
                kind="receipt", author="one", filename="large.csv",
                rows=rows(3), validation=validation(),
            )

        self.assertFalse(store._items)
        self.assertFalse(store._last_rows)

    def test_ttl_expires_active_preview_and_last_rows(self) -> None:
        store = WarehousePreviewStore()
        result = store.store(
            kind="receipt", author="one", filename="rows.csv",
            rows=rows(1), validation=validation(),
        )
        store._items[result["preview_id"]]["expires_at"] = EXPIRED_AT
        store._last_rows[("one", "receipt")]["expires_at"] = EXPIRED_AT

        with self.assertRaisesRegex(WarehouseError, "устарел"):
            store.consume(result["preview_id"], kind="receipt", author="one")
        with self.assertRaisesRegex(WarehouseError, "Сначала загрузите CSV"):
            store.rows("receipt", author="one")

    def test_per_author_cap_and_total_row_budget_evict_oldest(self) -> None:
        per_author = WarehousePreviewStore(
            max_items=10, max_items_per_author=2,
            max_rows_per_preview=5, max_total_rows=20,
        )
        first = per_author.store(
            kind="receipt", author="one", filename="1.csv",
            rows=rows(1), validation=validation(),
        )
        second = per_author.store(
            kind="issue", author="one", filename="2.csv",
            rows=rows(1), validation=validation(),
        )
        third = per_author.store(
            kind="bulk_issue", author="one", filename="3.csv",
            rows=rows(1), validation=validation(),
        )
        per_author.store(
            kind="receipt", author="two", filename="other.csv",
            rows=rows(1), validation=validation(),
        )

        with self.assertRaisesRegex(WarehouseError, "устарел"):
            per_author.consume(first["preview_id"], kind="receipt", author="one")
        self.assertEqual(
            per_author.consume(second["preview_id"], kind="issue", author="one")["filename"],
            "2.csv",
        )
        self.assertEqual(
            per_author.consume(third["preview_id"], kind="bulk_issue", author="one")["filename"],
            "3.csv",
        )

        budget = WarehousePreviewStore(
            max_items=10, max_items_per_author=2,
            max_rows_per_preview=3, max_total_rows=5,
        )
        old = budget.store(
            kind="receipt", author="old", filename="old.csv",
            rows=rows(3), validation=validation(),
        )
        current = budget.store(
            kind="receipt", author="new", filename="new.csv",
            rows=rows(3), validation=validation(),
        )
        self.assertLessEqual(budget._total_rows_locked(), 5)
        with self.assertRaisesRegex(WarehouseError, "устарел"):
            budget.consume(old["preview_id"], kind="receipt", author="old")
        self.assertEqual(
            budget.consume(current["preview_id"], kind="receipt", author="new")["filename"],
            "new.csv",
        )


class ReportsPreviewStoreLimitsTest(unittest.TestCase):
    def test_rejects_oversized_preview_and_expires_items(self) -> None:
        store = ReportsPreviewStore(max_rows_per_preview=2, max_total_rows=4)
        with self.assertRaisesRegex(WarehouseError, "больше 2 строк"):
            store.store(
                kind="work_logs", author="one", filename="large.csv",
                rows=rows(3), validation=validation(),
            )
        self.assertFalse(store._previews)

        total_budget = ReportsPreviewStore(
            max_rows_per_preview=5, max_total_rows=2,
        )
        with self.assertRaisesRegex(WarehouseError, "слишком велик"):
            total_budget.store(
                kind="work_logs", author="one", filename="large.csv",
                rows=rows(3), validation=validation(),
            )
        self.assertFalse(total_budget._previews)

        saved = store.store(
            kind="work_logs", author="one", filename="valid.csv",
            rows=rows(1), validation=validation(),
        )
        store._previews[saved["preview_id"]]["expires_at"] = EXPIRED_AT
        with self.assertRaisesRegex(WarehouseError, "устарел"):
            store.consume(saved["preview_id"], kind="work_logs", author="one")

    def test_concurrent_stores_respect_per_author_and_total_caps(self) -> None:
        store = ReportsPreviewStore(
            max_items=10, max_items_per_author=2,
            max_rows_per_preview=1, max_total_rows=4,
        )

        def save(index: int) -> None:
            store.store(
                kind="work_logs", author=f"author-{index % 3}",
                filename=f"{index}.csv", rows=rows(1), validation=validation(),
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(save, range(40)))

        self.assertLessEqual(len(store._previews), 4)
        self.assertLessEqual(store._total_rows_locked(), 4)
        for author in {item["author"] for item in store._previews.values()}:
            self.assertLessEqual(
                sum(item["author"] == author for item in store._previews.values()),
                2,
            )


class DeliveryPreviewStoreLimitsTest(unittest.TestCase):
    def test_rejects_logically_or_physically_oversized_preview(self) -> None:
        logical = DeliveryPreviewStore(max_rows_per_preview=2, max_total_rows=20)
        with self.assertRaisesRegex(WarehouseError, "больше 2 строк"):
            logical.store(delivery_preview("one", "s1", 3))
        self.assertFalse(logical._items)

        uneven = delivery_preview("one", "s1", 3)
        uneven["expanded_rows"] = rows(1)
        with self.assertRaisesRegex(WarehouseError, "больше 2 строк"):
            logical.store(uneven)
        self.assertFalse(logical._items)

        retained = DeliveryPreviewStore(max_rows_per_preview=2, max_total_rows=5)
        with self.assertRaisesRegex(WarehouseError, "слишком велик"):
            retained.store(delivery_preview("one", "s1", 2))
        self.assertFalse(retained._items)

    def test_owner_cap_total_budget_and_ttl(self) -> None:
        store = DeliveryPreviewStore(
            max_items=10, max_items_per_owner=2,
            max_rows_per_preview=2, max_total_rows=9,
        )
        first = store.store(delivery_preview("one", "s1", 1))
        second = store.store(delivery_preview("one", "s1", 1))
        third = store.store(delivery_preview("one", "s1", 1))
        other_session = store.store(delivery_preview("one", "s2", 1))

        with self.assertRaisesRegex(WarehouseError, "устарел"):
            store.get(first["preview_id"], author="one", session="s1")
        self.assertEqual(store.get(second["preview_id"], author="one", session="s1")["session"], "s1")
        self.assertEqual(store.get(third["preview_id"], author="one", session="s1")["session"], "s1")
        self.assertEqual(store.get(other_session["preview_id"], author="one", session="s2")["session"], "s2")
        with self.assertRaisesRegex(WarehouseError, "другой сессии"):
            store.get(other_session["preview_id"], author="one", session="s1")
        with self.assertRaisesRegex(WarehouseError, "другой сессии"):
            store.get(other_session["preview_id"], author="one")

        newest = store.store(delivery_preview("two", "s1", 1))
        self.assertLessEqual(store._total_rows_locked(), 9)
        self.assertEqual(store.get(newest["preview_id"], author="two", session="s1")["author"], "two")
        newest["expires_at"] = EXPIRED_AT
        with self.assertRaisesRegex(WarehouseError, "устарел"):
            store.get(newest["preview_id"], author="two", session="s1")


if __name__ == "__main__":
    unittest.main()
