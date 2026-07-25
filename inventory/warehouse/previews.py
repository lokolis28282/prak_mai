"""Warehouse-owned import preview storage."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from threading import RLock
from typing import Any

from inventory.importing import MAX_IMPORT_ROWS
from inventory.shared.validators import WarehouseError


class WarehousePreviewStore:
    def __init__(
        self,
        max_items: int = 8,
        *,
        ttl_seconds: float = 3600,
        max_rows_per_preview: int = MAX_IMPORT_ROWS,
        max_total_rows: int = MAX_IMPORT_ROWS * 2,
        max_items_per_author: int = 2,
    ):
        if min(max_items, max_rows_per_preview, max_total_rows, max_items_per_author) < 1:
            raise ValueError("Preview limits must be positive")
        if ttl_seconds <= 0:
            raise ValueError("Preview TTL must be positive")
        self.max_items = max_items
        self.ttl_seconds = ttl_seconds
        self.max_rows_per_preview = max_rows_per_preview
        self.max_total_rows = max_total_rows
        self.max_items_per_author = max_items_per_author
        self._items: dict[str, dict[str, Any]] = {}
        self._last_rows: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = RLock()

    def store(
        self,
        *,
        kind: str,
        author: str,
        filename: str,
        rows: list[dict[str, Any]],
        validation: dict[str, Any],
    ) -> dict[str, Any]:
        row_count = len(rows)
        if row_count > self.max_rows_per_preview:
            raise WarehouseError(
                f"Предпросмотр содержит больше {self.max_rows_per_preview:,} строк. "
                "Разделите файл на части."
            )
        preview_id = secrets.token_urlsafe(24)
        now = datetime.now()
        created_at = now.isoformat(timespec="seconds")
        expires_at = (now + timedelta(seconds=self.ttl_seconds)).isoformat(timespec="seconds")
        item = {
            "kind": kind,
            "author": author,
            "filename": filename,
            "created_at": created_at,
            "expires_at": expires_at,
            "rows": rows,
            "validation": validation,
        }
        cache_key = (author, kind)
        with self._lock:
            self._purge_locked(now)
            while sum(
                stored.get("author") == author for stored in self._items.values()
            ) >= self.max_items_per_author:
                oldest = next(
                    key for key, stored in self._items.items()
                    if stored.get("author") == author
                )
                self._items.pop(oldest, None)
            self._items[preview_id] = item
            self._last_rows.pop(cache_key, None)
            self._last_rows[cache_key] = {
                "created_at": created_at,
                "expires_at": expires_at,
                "rows": rows,
            }
            self._enforce_limits_locked(preview_id, cache_key)
        return {**validation, "preview_id": preview_id, "can_confirm": not validation.get("errors")}

    def consume(self, preview_id: str, *, kind: str, author: str) -> dict[str, Any]:
        with self._lock:
            self._purge_locked()
            preview = self._items.get(preview_id)
            if preview is None or preview["kind"] != kind:
                raise WarehouseError("Предпросмотр не найден или устарел")
            if preview["author"] != author:
                raise WarehouseError("Предпросмотр создан другим пользователем")
            return self._items.pop(preview_id)

    def rows(self, kind: str, *, author: str, preview_id: str = "") -> list[dict[str, Any]]:
        with self._lock:
            self._purge_locked()
            if preview_id:
                preview = self._items.get(preview_id)
                if preview is None or preview["kind"] != kind:
                    raise WarehouseError("Предпросмотр не найден или устарел")
                if preview["author"] != author:
                    raise WarehouseError("Предпросмотр создан другим пользователем")
                return [dict(row) for row in preview["rows"]]
            cached = self._last_rows.get((author, kind))
            if cached is None:
                raise WarehouseError("Сначала загрузите CSV и откройте предпросмотр")
            return [dict(row) for row in cached["rows"]]

    def _enforce_limits_locked(
        self,
        protected_preview_id: str,
        protected_cache_key: tuple[str, str],
    ) -> None:
        while len(self._items) > self.max_items:
            oldest = next(key for key in self._items if key != protected_preview_id)
            self._items.pop(oldest, None)
        while len(self._last_rows) > self.max_items:
            oldest = next(key for key in self._last_rows if key != protected_cache_key)
            self._last_rows.pop(oldest, None)
        while self._total_rows_locked() > self.max_total_rows:
            candidates = [
                (str(item.get("created_at") or ""), "item", key)
                for key, item in self._items.items()
                if key != protected_preview_id
            ]
            candidates.extend(
                (str(item.get("created_at") or ""), "cache", key)
                for key, item in self._last_rows.items()
                if key != protected_cache_key
            )
            if not candidates:
                self._items.pop(protected_preview_id, None)
                self._last_rows.pop(protected_cache_key, None)
                raise WarehouseError("Предпросмотр слишком велик. Разделите файл на части.")
            _, source, key = min(candidates, key=lambda candidate: candidate[0])
            if source == "item":
                self._items.pop(str(key), None)
            else:
                self._last_rows.pop(key, None)

    def _total_rows_locked(self) -> int:
        total = 0
        seen: set[int] = set()
        collections = [item.get("rows") for item in self._items.values()]
        collections.extend(item.get("rows") for item in self._last_rows.values())
        for rows in collections:
            if not isinstance(rows, list) or id(rows) in seen:
                continue
            seen.add(id(rows))
            total += len(rows)
        return total

    def _purge_locked(self, now: datetime | None = None) -> None:
        now = now or datetime.now()
        for key in [
            key for key, item in self._items.items() if self._expired(item, now)
        ]:
            self._items.pop(key, None)
        for key in [
            key for key, item in self._last_rows.items() if self._expired(item, now)
        ]:
            self._last_rows.pop(key, None)

    @staticmethod
    def _expired(item: dict[str, Any], now: datetime) -> bool:
        try:
            return datetime.fromisoformat(str(item["expires_at"])) <= now
        except (KeyError, TypeError, ValueError):
            return True
