"""Cable warehouse write service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from inventory.importing import PREVIEW_ERROR_LIMIT, PREVIEW_ROW_LIMIT
from inventory.shared.db import connect
from inventory.shared.validators import WarehouseError

from .cable_repository import CableRepository
from .cable_validators import (
    is_cable_issue,
    is_cable_receipt,
    prepare_cable_issue,
    prepare_cable_receipt,
    soft_cable_receipt_source,
)
from .previews import WarehousePreviewStore


class CableService:
    def __init__(
        self,
        db_path: str | Path,
        *,
        actor_provider: Any,
        strict_reference_validation: bool = True,
        previews: WarehousePreviewStore | None = None,
    ):
        self.repository = CableRepository(db_path)
        self.actor_provider = actor_provider
        self.strict_reference_validation = strict_reference_validation
        self.previews = previews or WarehousePreviewStore()

    def validate_cable_receipt(self, data: dict[str, Any]) -> dict[str, Any]:
        self._require_write()
        return self._prepare_receipt(data)

    def validate_cable_issue(self, data: dict[str, Any]) -> dict[str, Any]:
        self._require_write()
        return self._prepare_issue(data)

    def create_cable_receipt(self, data: dict[str, Any]) -> int:
        self._require_write()
        row = self._prepare_receipt(data)
        return self.repository.insert_receipt(
            row,
            author=self.audit_author(),
            collect_refs=not self.strict_reference_validation,
        )

    def create_cable_receipt_batch(self, rows: Iterable[dict[str, Any]], *, soft: bool = True) -> dict[str, Any]:
        self._require_write()
        prepared = self._prepare_receipt_rows(rows, soft=soft)
        ids = self.repository.insert_receipts(
            prepared,
            author=self.audit_author(),
            collect_refs=soft or not self.strict_reference_validation,
        )
        return {"created_count": len(ids), "skipped_count": 0, "errors": [], "receipt_ids": ids}

    def create_cable_issue(self, data: dict[str, Any]) -> int:
        self._require_write()
        row = self._prepare_issue(data)
        return self.repository.insert_issue(
            row,
            author=self.audit_author(),
            collect_refs=not self.strict_reference_validation,
        )

    def get_cable_balance(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self.repository.cable_balance(filters)

    def get_cable_types(self) -> list[str]:
        return self.repository.cable_types()

    def get_cable_items(self, cable_type: str | None = None) -> list[dict[str, Any]]:
        return self.repository.cable_items(cable_type or "")

    def preview_cable_import(
        self,
        rows: Iterable[dict[str, Any]],
        filename: str = "receipt.csv",
        *,
        unknown_columns: list[str] | None = None,
        soft: bool = False,
    ) -> dict[str, Any]:
        self._require_write()
        source_rows = [dict(row) for row in rows]
        errors: list[dict[str, Any]] = []
        preview_rows: list[dict[str, Any]] = []
        valid = error_count = total = 0
        with connect(self.repository.db_path) as db:
            references = self.repository.reference_sets(db)
            for line, source in enumerate(source_rows, start=2):
                if not any(str(value or "").strip() for value in source.values()):
                    continue
                total += 1
                reason = ""
                prepared: dict[str, Any] | None = None
                try:
                    if not is_cable_receipt(source):
                        raise WarehouseError(f"Строка {line}: файл содержит некабельную строку")
                    candidate = soft_cable_receipt_source(source) if soft else source
                    prepared = prepare_cable_receipt(
                        candidate,
                        references,
                        line_number=line,
                        strict_references=not soft,
                    )
                    valid += 1
                except WarehouseError as error:
                    reason = str(error)
                    error_count += 1
                    if len(errors) < PREVIEW_ERROR_LIMIT:
                        errors.append({"line": line, "reason": reason})
                if len(preview_rows) < PREVIEW_ROW_LIMIT:
                    shown = dict(prepared or source)
                    shown.update({"line": line, "valid": not reason, "error": reason})
                    preview_rows.append(shown)
        if total == 0:
            error_count += 1
            errors.append({"line": 1, "reason": "В CSV-файле нет строк прихода"})
        return self.previews.store(
            kind="cable_receipt",
            author=self.audit_author(),
            filename=filename,
            rows=source_rows,
            validation={
                "total": total,
                "valid": valid,
                "new": valid,
                "duplicates": 0,
                "error_count": error_count,
                "errors": errors,
                "rows": preview_rows,
                "mode": "soft" if soft else "strict",
                "unknown_columns": list(unknown_columns or []),
            },
        )

    def confirm_cable_import(self, preview_id: str) -> int:
        self._require_write()
        preview = self.previews.consume(preview_id, kind="cable_receipt", author=self.audit_author())
        soft = preview.get("validation", {}).get("mode") == "soft"
        check = self.preview_cable_import(preview["rows"], preview.get("filename", "receipt.csv"), soft=soft)
        self.previews.consume(check["preview_id"], kind="cable_receipt", author=self.audit_author())
        if check["errors"]:
            raise WarehouseError(check["errors"][0]["reason"])
        return int(self.create_cable_receipt_batch(preview["rows"], soft=soft)["created_count"])

    def preview_rows(self, preview_id: str = "") -> list[dict[str, Any]]:
        return self.previews.rows("cable_receipt", author=self.audit_author(), preview_id=preview_id)

    def _prepare_receipt_rows(self, rows: Iterable[dict[str, Any]], *, soft: bool) -> list[dict[str, Any]]:
        source_rows = [dict(row) for row in rows]
        prepared: list[dict[str, Any]] = []
        with connect(self.repository.db_path) as db:
            references = self.repository.reference_sets(db)
            for line, source in enumerate(source_rows, start=2):
                if not any(str(value or "").strip() for value in source.values()):
                    continue
                if not is_cable_receipt(source):
                    raise WarehouseError(f"Строка {line}: файл содержит некабельную строку")
                candidate = soft_cable_receipt_source(source) if soft else source
                row = prepare_cable_receipt(
                    candidate,
                    references,
                    line_number=line,
                    strict_references=not soft if soft else self.strict_reference_validation,
                )
                row["_line"] = line
                prepared.append(row)
        if not prepared:
            raise WarehouseError("В CSV-файле нет строк прихода")
        return prepared

    def _prepare_receipt(self, data: dict[str, Any]) -> dict[str, Any]:
        if not is_cable_receipt(data):
            raise WarehouseError("Операция не является кабельным приходом")
        with connect(self.repository.db_path) as db:
            return prepare_cable_receipt(
                data,
                self.repository.reference_sets(db),
                strict_references=self.strict_reference_validation,
            )

    def _prepare_issue(self, data: dict[str, Any]) -> dict[str, Any]:
        if not is_cable_issue(data):
            raise WarehouseError("Операция не является кабельным расходом")
        with connect(self.repository.db_path) as db:
            return prepare_cable_issue(
                data,
                self.repository.reference_sets(db),
                strict_references=self.strict_reference_validation,
            )

    def current_user(self) -> dict[str, Any]:
        return self.actor_provider.current_user()

    def audit_author(self) -> str:
        core = getattr(self.actor_provider, "_core", self.actor_provider)
        name = core._actor_name.get()
        user = self.current_user()
        return name or str(user.get("email") or "lokolis")

    def _require_write(self) -> dict[str, Any]:
        user = self.current_user()
        if user.get("role") not in {"admin", "engineer"}:
            raise WarehouseError("Недостаточно прав для выполнения операции")
        return user
