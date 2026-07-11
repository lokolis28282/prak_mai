"""Warehouse-owned import preview storage."""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any

from inventory.shared.validators import WarehouseError


class WarehousePreviewStore:
    def __init__(self, max_items: int = 8):
        self.max_items = max_items
        self._items: dict[str, dict[str, Any]] = {}
        self._last_rows: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def store(
        self,
        *,
        kind: str,
        author: str,
        filename: str,
        rows: list[dict[str, Any]],
        validation: dict[str, Any],
    ) -> dict[str, Any]:
        preview_id = secrets.token_urlsafe(24)
        self._items[preview_id] = {
            "kind": kind,
            "author": author,
            "filename": filename,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "rows": rows,
            "validation": validation,
        }
        self._last_rows[(author, kind)] = rows
        while len(self._items) > self.max_items:
            self._items.pop(next(iter(self._items)))
        while len(self._last_rows) > self.max_items:
            self._last_rows.pop(next(iter(self._last_rows)))
        return {**validation, "preview_id": preview_id, "can_confirm": not validation.get("errors")}

    def consume(self, preview_id: str, *, kind: str, author: str) -> dict[str, Any]:
        preview = self._items.get(preview_id)
        if preview is None or preview["kind"] != kind:
            raise WarehouseError("Предпросмотр не найден или устарел")
        if preview["author"] != author:
            raise WarehouseError("Предпросмотр создан другим пользователем")
        return self._items.pop(preview_id)

    def rows(self, kind: str, *, author: str, preview_id: str = "") -> list[dict[str, Any]]:
        if preview_id:
            preview = self._items.get(preview_id)
            if preview is None or preview["kind"] != kind:
                raise WarehouseError("Предпросмотр не найден или устарел")
            if preview["author"] != author:
                raise WarehouseError("Предпросмотр создан другим пользователем")
            return [dict(row) for row in preview["rows"]]
        rows = self._last_rows.get((author, kind))
        if rows is None:
            raise WarehouseError("Сначала загрузите CSV и откройте предпросмотр")
        return [dict(row) for row in rows]
