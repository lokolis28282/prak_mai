"""Warehouse-owned delivery preview store."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from threading import RLock
from typing import Any

from inventory.importing import MAX_IMPORT_ROWS
from inventory.shared.validators import WarehouseError

from .delivery_models import DELIVERY_IMPORT_KIND


class DeliveryPreviewStore:
    _ROW_COLLECTION_KEYS = ("source_rows", "expanded_rows", "validation_results", "rows")

    def __init__(
        self,
        ttl_seconds: float = 3600,
        max_items: int = 16,
        *,
        max_rows_per_preview: int = MAX_IMPORT_ROWS,
        max_total_rows: int = MAX_IMPORT_ROWS * 6,
        max_items_per_owner: int = 2,
    ):
        if min(max_items, max_rows_per_preview, max_total_rows, max_items_per_owner) < 1:
            raise ValueError("Preview limits must be positive")
        if ttl_seconds <= 0:
            raise ValueError("Preview TTL must be positive")
        self.ttl_seconds = ttl_seconds
        self.max_items = max_items
        self.max_rows_per_preview = max_rows_per_preview
        self.max_total_rows = max_total_rows
        self.max_items_per_owner = max_items_per_owner
        self._items: dict[str, dict[str, Any]] = {}
        self._lock = RLock()

    def store(self, preview: dict[str, Any]) -> dict[str, Any]:
        logical_rows = self._logical_row_count(preview)
        if logical_rows > self.max_rows_per_preview:
            raise WarehouseError(
                f"Предпросмотр содержит больше {self.max_rows_per_preview:,} строк. "
                "Разделите файл на части."
            )
        retained_rows = self._retained_row_count(preview)
        if retained_rows > self.max_total_rows:
            raise WarehouseError("Предпросмотр слишком велик. Разделите файл на части.")
        preview_id = secrets.token_urlsafe(24)
        now = datetime.now()
        item = {
            **preview,
            "kind": DELIVERY_IMPORT_KIND,
            "preview_id": preview_id,
            "created_at": now.isoformat(timespec="seconds"),
            "expires_at": (now + timedelta(seconds=self.ttl_seconds)).isoformat(timespec="seconds"),
            "used": False,
        }
        owner = self._owner(item)
        with self._lock:
            self._purge_locked(now)
            while sum(
                self._owner(stored) == owner for stored in self._items.values()
            ) >= self.max_items_per_owner:
                oldest = next(
                    key for key, stored in self._items.items()
                    if self._owner(stored) == owner
                )
                self._items.pop(oldest, None)
            self._items[preview_id] = item
            while (
                len(self._items) > self.max_items
                or self._total_rows_locked() > self.max_total_rows
            ):
                self._items.pop(next(iter(self._items)), None)
        return item

    def get(self, preview_id: str, *, author: str, session: str = "") -> dict[str, Any]:
        with self._lock:
            self._purge_locked()
            item = self._items.get(preview_id)
            if item is None or item.get("kind") != DELIVERY_IMPORT_KIND:
                raise WarehouseError("Предпросмотр не найден или устарел")
            if item.get("used"):
                raise WarehouseError("Предпросмотр уже был подтвержден")
            if item.get("author") != author:
                raise WarehouseError("Предпросмотр создан другим пользователем")
            expected_session = str(item.get("session") or "")
            if expected_session and expected_session != session:
                raise WarehouseError("Предпросмотр создан в другой сессии")
            return item

    def consume(self, preview_id: str, *, author: str, session: str = "") -> dict[str, Any]:
        with self._lock:
            item = self.get(preview_id, author=author, session=session)
            item["used"] = True
            return self._items.pop(preview_id)

    def _purge(self) -> None:
        with self._lock:
            self._purge_locked()

    def _purge_locked(self, now: datetime | None = None) -> None:
        now = now or datetime.now()
        expired = [key for key, item in self._items.items() if self._expired(item, now)]
        for key in expired:
            self._items.pop(key, None)

    def _total_rows_locked(self) -> int:
        return sum(self._retained_row_count(item) for item in self._items.values())

    @classmethod
    def _logical_row_count(cls, preview: dict[str, Any]) -> int:
        return max(
            (
                len(rows)
                for key in ("expanded_rows", "source_rows", "rows")
                if isinstance((rows := preview.get(key)), list)
            ),
            default=0,
        )

    @classmethod
    def _retained_row_count(cls, preview: dict[str, Any]) -> int:
        total = 0
        seen: set[int] = set()
        for key in cls._ROW_COLLECTION_KEYS:
            rows = preview.get(key)
            if not isinstance(rows, list) or id(rows) in seen:
                continue
            seen.add(id(rows))
            total += len(rows)
        return total

    @staticmethod
    def _owner(item: dict[str, Any]) -> tuple[str, str]:
        return str(item.get("author") or ""), str(item.get("session") or "")

    @staticmethod
    def _expired(item: dict[str, Any], now: datetime) -> bool:
        try:
            return datetime.fromisoformat(str(item["expires_at"])) <= now
        except (KeyError, TypeError, ValueError):
            return True
