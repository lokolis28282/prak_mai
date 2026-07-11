"""Reports-owned import preview storage."""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any

from inventory.importing import PREVIEW_ERROR_LIMIT, PREVIEW_ROW_LIMIT
from inventory.shared.validators import WarehouseError


class ReportsPreviewStore:
    def __init__(self, max_items: int = 6):
        self.max_items = max_items
        self._previews: dict[str, dict[str, Any]] = {}

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
        self._previews[preview_id] = {
            "kind": kind,
            "author": author,
            "filename": filename,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "rows": rows,
            "validation": validation,
        }
        while len(self._previews) > self.max_items:
            self._previews.pop(next(iter(self._previews)))
        return {
            **validation,
            "preview_id": preview_id,
            "can_confirm": not validation.get("errors"),
        }

    def consume(self, preview_id: str, *, kind: str, author: str) -> dict[str, Any]:
        preview = self._previews.get(preview_id)
        if preview is None or preview["kind"] != kind:
            raise WarehouseError("Предпросмотр не найден или устарел")
        if preview["author"] != author:
            raise WarehouseError("Предпросмотр создан другим пользователем")
        return self._previews.pop(preview_id)


def preview_limits() -> tuple[int, int]:
    return PREVIEW_ROW_LIMIT, PREVIEW_ERROR_LIMIT
