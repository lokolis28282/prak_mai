"""Reports-owned import preview storage."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from threading import RLock
from typing import Any

from inventory.importing import MAX_IMPORT_ROWS, PREVIEW_ERROR_LIMIT, PREVIEW_ROW_LIMIT
from inventory.shared.validators import WarehouseError


class ReportsPreviewStore:
    def __init__(
        self,
        max_items: int = 6,
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
        self._previews: dict[str, dict[str, Any]] = {}
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
        if row_count > self.max_total_rows:
            raise WarehouseError("Предпросмотр слишком велик. Разделите файл на части.")
        preview_id = secrets.token_urlsafe(24)
        now = datetime.now()
        item = {
            "kind": kind,
            "author": author,
            "filename": filename,
            "created_at": now.isoformat(timespec="seconds"),
            "expires_at": (now + timedelta(seconds=self.ttl_seconds)).isoformat(timespec="seconds"),
            "rows": rows,
            "validation": validation,
        }
        with self._lock:
            self._purge_locked(now)
            while sum(
                stored.get("author") == author for stored in self._previews.values()
            ) >= self.max_items_per_author:
                oldest = next(
                    key for key, stored in self._previews.items()
                    if stored.get("author") == author
                )
                self._previews.pop(oldest, None)
            self._previews[preview_id] = item
            while (
                len(self._previews) > self.max_items
                or self._total_rows_locked() > self.max_total_rows
            ):
                self._previews.pop(next(iter(self._previews)), None)
        return {
            **validation,
            "preview_id": preview_id,
            "can_confirm": not validation.get("errors"),
        }

    def consume(self, preview_id: str, *, kind: str, author: str) -> dict[str, Any]:
        with self._lock:
            self._purge_locked()
            preview = self._previews.get(preview_id)
            if preview is None or preview["kind"] != kind:
                raise WarehouseError("Предпросмотр не найден или устарел")
            if preview["author"] != author:
                raise WarehouseError("Предпросмотр создан другим пользователем")
            return self._previews.pop(preview_id)

    def _purge_locked(self, now: datetime | None = None) -> None:
        now = now or datetime.now()
        expired = [
            key for key, item in self._previews.items() if self._expired(item, now)
        ]
        for key in expired:
            self._previews.pop(key, None)

    def _total_rows_locked(self) -> int:
        return sum(len(item["rows"]) for item in self._previews.values())

    @staticmethod
    def _expired(item: dict[str, Any], now: datetime) -> bool:
        try:
            return datetime.fromisoformat(str(item["expires_at"])) <= now
        except (KeyError, TypeError, ValueError):
            return True


def preview_limits() -> tuple[int, int]:
    return PREVIEW_ROW_LIMIT, PREVIEW_ERROR_LIMIT
