"""Extracted Warehouse domain service."""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from inventory.db import connect
from inventory.shared.validators import WarehouseError

from .classification import (
    canonical_vendor,
    classify_card,
    infer_vendor,
    operational_category,
)
from .component import WarehouseComponent
from .issue_repository import IssueRepository


class WarehouseReferenceService(WarehouseComponent):
    def references(self, kind: str = "", active_only: bool = False) -> list[dict[str, Any]]:
        """Return form-safe canonical values from the existing Reference layer."""
        return self.reference_catalog.form_references(kind, active_only=active_only)

    def reference_groups(self) -> list[dict[str, Any]]:
        """Вернуть значения готовыми группами в порядке экранных справочников."""
        rows = self.references()
        return [
            {
                "kind": kind,
                "label": label,
                "values": [row for row in rows if row["kind"] == kind],
            }
            for kind, label in self.REFERENCE_KINDS.items()
        ]

    def add_reference(self, kind: str, name: str) -> int:
        with connect(self.db_path) as db:
            has_v2 = self.reference_catalog.has_v2(db)
        if not has_v2:
            self._require_write()
            if kind not in self.REFERENCE_KINDS:
                raise WarehouseError("Неизвестный справочник")
            name = self._required(name, "значение справочника")
            try:
                with connect(self.db_path) as db:
                    cursor = db.execute(
                        "INSERT INTO reference_values(kind,name) VALUES (?,?)", (kind, name)
                    )
                    reference_id = int(cursor.lastrowid)
                    self._audit(db, "REFERENCE_CREATE", "reference_value", reference_id,
                                {"kind": kind, "name": name})
                    return reference_id
            except sqlite3.IntegrityError as error:
                raise WarehouseError(f"Значение «{name}» уже существует") from error
        domain = self.reference_catalog._domain_for_kind(kind)
        if not domain:
            raise WarehouseError("Неизвестный canonical справочник")
        return self.reference_catalog.add_proposal(domain, name)

    def set_reference_active(self, reference_id: int, is_active: bool) -> None:
        with connect(self.db_path) as db:
            has_v2 = self.reference_catalog.has_v2(db)
        if not has_v2:
            self._require_write()
            with connect(self.db_path) as db:
                cursor = db.execute(
                    "UPDATE reference_values SET is_active=? WHERE id=?",
                    (1 if is_active else 0, reference_id),
                )
                if not cursor.rowcount:
                    raise WarehouseError("Значение справочника не найдено")
                self._audit(db, "REFERENCE_TOGGLE", "reference_value", reference_id,
                            {"is_active": bool(is_active)})
            return
        self.reference_catalog.set_active(reference_id, is_active)

    def reference_editor_catalog(self) -> dict[str, Any]:
        return self.reference_catalog.editor_catalog()

    def reference_models(self, vendor: str) -> list[dict[str, Any]]:
        return self.reference_catalog.models_for_vendor(vendor)

    def propose_reference(self, domain: str, value: str, parent: str = "") -> int:
        return self.reference_catalog.add_proposal(domain, value, parent=parent)

    def rename_reference(self, reference_id: int, display_name: str) -> None:
        self.reference_catalog.rename(reference_id, display_name)

    def preview_reference_merge(self, source_id: int, target_id: int) -> dict[str, Any]:
        return self.reference_catalog.merge_preview(source_id, target_id)

    def merge_reference(self, source_id: int, target_id: int) -> dict[str, Any]:
        return self.reference_catalog.merge(source_id, target_id)

    # Compatibility vocabulary used by WarehouseService.reference_service.
    def editor_catalog(self) -> dict[str, Any]:
        return self.reference_editor_catalog()

    def models(self, vendor: str) -> list[dict[str, Any]]:
        return self.reference_models(vendor)

    def propose(self, domain: str, value: str, parent: str = "") -> int:
        return self.propose_reference(domain, value, parent)

    def rename(self, reference_id: int, display_name: str) -> None:
        self.rename_reference(reference_id, display_name)

    def merge_preview(
        self, source_id: int, target_id: int
    ) -> dict[str, Any]:
        return self.preview_reference_merge(source_id, target_id)

    def merge(self, source_id: int, target_id: int) -> dict[str, Any]:
        return self.merge_reference(source_id, target_id)
