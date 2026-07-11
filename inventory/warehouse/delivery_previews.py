"""Warehouse-owned delivery preview store."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Any

from inventory.shared.validators import WarehouseError

from .delivery_models import DELIVERY_IMPORT_KIND


class DeliveryPreviewStore:
    def __init__(self, ttl_seconds: int = 3600, max_items: int = 16):
        self.ttl_seconds = ttl_seconds
        self.max_items = max_items
        self._items: dict[str, dict[str, Any]] = {}

    def store(self, preview: dict[str, Any]) -> dict[str, Any]:
        self._purge()
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
        self._items[preview_id] = item
        while len(self._items) > self.max_items:
            self._items.pop(next(iter(self._items)))
        return item

    def get(self, preview_id: str, *, author: str, session: str = "") -> dict[str, Any]:
        self._purge()
        item = self._items.get(preview_id)
        if item is None or item.get("kind") != DELIVERY_IMPORT_KIND:
            raise WarehouseError("Предпросмотр не найден или устарел")
        if item.get("used"):
            raise WarehouseError("Предпросмотр уже был подтвержден")
        if item.get("author") != author:
            raise WarehouseError("Предпросмотр создан другим пользователем")
        expected_session = str(item.get("session") or "")
        if expected_session and session and expected_session != session:
            raise WarehouseError("Предпросмотр создан в другой сессии")
        return item

    def consume(self, preview_id: str, *, author: str, session: str = "") -> dict[str, Any]:
        item = self.get(preview_id, author=author, session=session)
        item["used"] = True
        return self._items.pop(preview_id)

    def _purge(self) -> None:
        now = datetime.now()
        expired = [
            key for key, item in self._items.items()
            if datetime.fromisoformat(str(item["expires_at"])) < now
        ]
        for key in expired:
            self._items.pop(key, None)
