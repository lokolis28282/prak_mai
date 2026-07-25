"""Serialized equipment/component issue write/import service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from inventory.importing import PREVIEW_ERROR_LIMIT, PREVIEW_ROW_LIMIT
from inventory.shared.db import connect
from inventory.shared.validators import WarehouseError

from .issue_previews import WarehousePreviewStore
from .issue_repository import IssueRepository
from .issue_validators import prepare_issue, soft_issue_source


class IssueWriteService:
    def __init__(
        self,
        db_path: str | Path,
        *,
        actor_provider: Any,
        strict_reference_validation: bool = True,
        previews: WarehousePreviewStore | None = None,
    ):
        self.repository = IssueRepository(db_path)
        self.actor_provider = actor_provider
        self.strict_reference_validation = strict_reference_validation
        self.previews = previews or WarehousePreviewStore()

    def validate_issue_serial(self, serial_number: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        self._require_write()
        serial = self._required(str(serial_number).strip().upper(), "S/N")
        item = self.repository.available_position(serial)
        if item is None:
            return {
                "serial_number": serial, "found": False, "valid": False,
                "error": "S/N не найден — расход запрещён",
                "item_name": "", "model": "", "shelf": "", "available": 0,
            }
        available = float(item["available"])
        error = ""
        if item["cable_type"]:
            error = "Кабель нельзя списывать сканированием S/N"
        elif available < 1 - 1e-9:
            error = "Позиция уже списана или не имеет остатка"
        return {
            "serial_number": serial, "found": True, "valid": not error,
            "warning": "", "error": error, "item_name": item["item_name"],
            "model": item["model"], "shelf": item["shelf"], "available": available,
        }

    def validate_issue_target(self, serial_number: str) -> dict[str, Any]:
        self._require_write()
        serial = self._required(str(serial_number).strip().upper(), "S/N целевого оборудования")
        with connect(self.repository.db_path) as db:
            row = db.execute(
                """SELECT serial_number, item_name, model, datacenter, shelf
                     FROM stock_receipts
                    WHERE trim(serial_number) <> ''
                      AND trim(serial_number) = trim(?) COLLATE NOCASE
                      AND trim(equipment_type) <> ''
                    ORDER BY id LIMIT 1""",
                (serial,),
            ).fetchone()
        if row is None:
            return {
                "serial_number": serial, "found": False, "valid": False,
                "error": "Целевое оборудование с таким S/N не найдено",
            }
        return {
            "serial_number": serial, "found": True, "valid": True,
            "item_name": row["item_name"], "model": row["model"],
            "datacenter": row["datacenter"], "shelf": row["shelf"],
        }

    def prepare_issue(self, data: dict[str, Any], *, line_number: int | None = None, soft: bool = False) -> dict[str, Any]:
        source = soft_issue_source(data) if soft else dict(data)
        with connect(self.repository.db_path) as db:
            return prepare_issue(
                source,
                self.repository.reference_sets(db),
                line_number=line_number,
                strict_references=not soft if soft else self.strict_reference_validation,
            )

    def create_issue(self, data: dict[str, Any]) -> int:
        self._require_write()
        row = self.prepare_issue(data)
        return self.repository.insert_one(
            row,
            author=self.audit_author(),
            collect_refs=not self.strict_reference_validation,
        )

    def create_issue_batch(self, rows: Iterable[dict[str, Any]], *, soft: bool = False) -> dict[str, Any]:
        self._require_write()
        prepared = self._prepare_rows(rows, soft=soft)
        count = self.repository.insert_many(
            prepared,
            author=self.audit_author(),
            collect_refs=soft or not self.strict_reference_validation,
            soft=soft,
            audit_action="ISSUE_BATCH_CREATE",
        )
        return {"created_count": count, "skipped_count": 0, "errors": []}

    def create_issue_by_serials(
        self, common_fields: dict[str, Any], serial_numbers: Iterable[str]
    ) -> dict[str, int]:
        self._require_write()
        serials = [str(value).strip().upper() for value in serial_numbers]
        if not serials or any(not value for value in serials):
            raise WarehouseError("Список S/N пуст или содержит пустое значение")
        folded = [value.casefold() for value in serials]
        if len(set(folded)) != len(folded):
            raise WarehouseError("Список содержит повторяющиеся S/N")
        rows = [
            {**common_fields, "source_serial_number": serial,
             "source_item_name": "", "source_cable_type": "", "quantity": 1}
            for serial in serials
        ]
        prepared = self._prepare_rows(rows, soft=False)
        imported = self.repository.insert_many(
            prepared,
            author=self.audit_author(),
            collect_refs=not self.strict_reference_validation,
            soft=False,
            audit_action="SCANNED_ISSUE_IMPORT",
        )
        return {"imported": imported, "unmatched": 0}

    def create_issue_pairs(
        self, common_fields: dict[str, Any], pairs: Iterable[dict[str, Any]]
    ) -> dict[str, int]:
        self._require_write()
        source_pairs = [dict(pair) for pair in pairs]
        if not source_pairs or len(source_pairs) > 1000:
            raise WarehouseError("Список пар пуст или превышает 1000 строк")
        normalized: list[dict[str, Any]] = []
        seen_sources: set[str] = set()
        for line, pair in enumerate(source_pairs, start=1):
            source = str(pair.get("source_serial_number", "")).strip().upper()
            target = str(pair.get("target_serial_number", "")).strip().upper()
            if not source or not target:
                raise WarehouseError(f"Строка {line}: укажите S/N компонента и S/N целевого оборудования")
            source_key = source.casefold()
            if source_key in seen_sources:
                raise WarehouseError(f"Строка {line}: S/N компонента повторяется в списке")
            seen_sources.add(source_key)
            normalized.append({
                **common_fields,
                "source_serial_number": source,
                "target_serial_number": target,
                "source_item_name": "",
                "source_cable_type": "",
                "quantity": 1,
            })
        prepared = self._prepare_rows(normalized, soft=False)
        imported = self.repository.insert_many(
            prepared,
            author=self.audit_author(),
            collect_refs=not self.strict_reference_validation,
            soft=False,
            audit_action="SCANNED_ISSUE_PAIR_IMPORT",
        )
        return {"imported": imported}

    def import_issues(self, rows: Iterable[dict[str, Any]], *, soft: bool = True) -> int:
        self._require_write()
        prepared = self._prepare_rows(rows, soft=soft)
        return self.repository.insert_many(
            prepared,
            author=self.audit_author(),
            collect_refs=soft or not self.strict_reference_validation,
            soft=soft,
            audit_action="ISSUE_IMPORT",
        )

    def preview_issue_import(
        self,
        rows: Iterable[dict[str, Any]],
        filename: str = "issue.csv",
        *,
        unknown_columns: list[str] | None = None,
        soft: bool = False,
    ) -> dict[str, Any]:
        self._require_write()
        source_rows = [dict(row) for row in rows]
        errors: list[dict[str, Any]] = []
        preview_rows: list[dict[str, Any]] = []
        valid = duplicates = total = error_count = 0
        seen_serials: set[str] = set()
        with connect(self.repository.db_path) as db:
            references = self.repository.reference_sets(db)
            db.execute("BEGIN")
            try:
                for line, source in enumerate(source_rows, start=2):
                    if not any(str(value or "").strip() for value in source.values()):
                        continue
                    total += 1
                    reason = ""
                    prepared: dict[str, Any] | None = None
                    db.execute("SAVEPOINT issue_preview_row")
                    try:
                        candidate = soft_issue_source(source) if soft else source
                        prepared = prepare_issue(
                            candidate,
                            references,
                            line_number=line,
                            strict_references=not soft,
                        )
                        serial = prepared["source_serial_number"].casefold()
                        if serial and serial in seen_serials:
                            duplicates += 1
                        try:
                            self.repository.create_issue(db, prepared, author=self.audit_author(), line_number=line)
                        except WarehouseError as issue_error:
                            reason_text = str(issue_error)
                            unmatched = self.repository.is_unmatched_issue(db, prepared, reason_text)
                            if not soft or not unmatched:
                                raise
                            self.repository.create_unmatched_issue(db, prepared, reason_text, author=self.audit_author())
                            prepared["warning"] = reason_text
                        if serial:
                            seen_serials.add(serial)
                        valid += 1
                        db.execute("RELEASE issue_preview_row")
                    except WarehouseError as error:
                        reason = str(error)
                        error_count += 1
                        if len(errors) < PREVIEW_ERROR_LIMIT:
                            errors.append({"line": line, "reason": reason})
                        db.execute("ROLLBACK TO issue_preview_row")
                        db.execute("RELEASE issue_preview_row")
                    if len(preview_rows) < PREVIEW_ROW_LIMIT:
                        shown = dict(prepared or source)
                        shown.update({"line": line, "valid": not reason, "error": reason})
                        preview_rows.append(shown)
            finally:
                db.rollback()
        if total == 0:
            error_count += 1
            errors.append({"line": 1, "reason": "В CSV-файле нет строк расхода"})
        return self.previews.store(
            kind="issue",
            author=self.audit_author(),
            filename=filename,
            rows=source_rows,
            validation={
                "total": total, "valid": valid, "new": valid,
                "duplicates": duplicates, "error_count": error_count,
                "errors": errors, "rows": preview_rows,
                "mode": "soft" if soft else "strict",
                "unknown_columns": list(unknown_columns or []),
            },
        )

    def confirm_issue_import(self, preview_id: str) -> int:
        self._require_write()
        preview = self.previews.consume(preview_id, kind="issue", author=self.audit_author())
        soft = preview.get("validation", {}).get("mode") == "soft"
        check = self.preview_issue_import(preview["rows"], preview.get("filename", "issue.csv"), soft=soft)
        self.previews.consume(check["preview_id"], kind="issue", author=self.audit_author())
        if check["errors"]:
            raise WarehouseError(check["errors"][0]["reason"])
        return self.import_issues(preview["rows"], soft=soft)

    def preview_bulk_issue_serials(
        self,
        rows: Iterable[dict[str, Any]],
        filename: str = "bulk_issue.csv",
    ) -> dict[str, Any]:
        self._require_write()
        source_rows = [dict(row) for row in rows]
        errors: list[dict[str, Any]] = []
        preview_rows: list[dict[str, Any]] = []
        found = unavailable = duplicates = total = 0
        seen: set[str] = set()
        with connect(self.repository.db_path) as db:
            for line, source in enumerate(source_rows, start=2):
                if not any(str(value or "").strip() for value in source.values()):
                    continue
                total += 1
                serial = str(source.get("serial_number", source.get("source_serial_number", ""))).strip().upper()
                reason = ""
                item = None
                if not serial:
                    reason = "S/N не может быть пустым"
                elif serial.casefold() in seen:
                    duplicates += 1
                    reason = f"S/N «{serial}» повторяется в файле"
                else:
                    seen.add(serial.casefold())
                    item = self.repository.available_position(serial)
                    if item is None:
                        reason = f"S/N «{serial}» не найден"
                    elif item["cable_type"]:
                        reason = f"S/N «{serial}»: кабели нельзя списывать скан-листом"
                    elif float(item["available"]) < 1 - 1e-9:
                        unavailable += 1
                        reason = f"S/N «{serial}» уже списан или не имеет остатка"
                    else:
                        found += 1
                if reason:
                    errors.append({"line": line, "reason": reason})
                if len(preview_rows) < 50:
                    preview_rows.append({
                        "line": line, "serial_number": serial,
                        "item_name": item["item_name"] if item is not None else "",
                        "model": item["model"] if item is not None else "",
                        "available": float(item["available"]) if item is not None else 0,
                        "comment": str(source.get("comment", "")).strip(),
                        "valid": not reason, "error": reason,
                    })
        if total == 0:
            errors.append({"line": 1, "reason": "В CSV-файле нет S/N"})
        return self.previews.store(
            kind="bulk_issue",
            author=self.audit_author(),
            filename=filename,
            rows=source_rows,
            validation={
                "total": total, "valid": found, "found": found,
                "not_found": sum("не найден" in error["reason"] for error in errors),
                "unavailable": unavailable, "duplicates": duplicates,
                "new": found, "error_count": len(errors),
                "errors": errors, "rows": preview_rows,
            },
        )

    def confirm_bulk_issue_preview(
        self,
        preview_id: str,
        issue_date: str,
        responsible: str,
        task_type: str,
        task_number: str,
        comment: str = "",
        target_serial_number: str = "",
    ) -> int:
        self._require_write()
        preview = self.previews.consume(preview_id, kind="bulk_issue", author=self.audit_author())
        check = self.preview_bulk_issue_serials(preview["rows"], preview.get("filename", "bulk_issue.csv"))
        self.previews.consume(check["preview_id"], kind="bulk_issue", author=self.audit_author())
        if check["errors"]:
            raise WarehouseError(check["errors"][0]["reason"])
        common = {
            "issue_date": issue_date, "responsible": responsible,
            "task_type": task_type, "task_number": task_number,
            "target_serial_number": target_serial_number,
            "target_hostname": "", "source_item_name": "",
            "source_cable_type": "", "quantity": 1, "comment": comment,
        }
        rows = []
        for line, source in enumerate(preview["rows"], start=2):
            if not any(str(value or "").strip() for value in source.values()):
                continue
            serial = str(source.get("serial_number", source.get("source_serial_number", ""))).strip().upper()
            row = self.prepare_issue(
                {**common, "source_serial_number": serial,
                 "comment": str(source.get("comment", "")).strip() or comment},
                line_number=line,
            )
            row["_line"] = line
            rows.append(row)
        count = self.repository.insert_many(
            rows,
            author=self.audit_author(),
            collect_refs=not self.strict_reference_validation,
            soft=False,
            audit_action="BULK_ISSUE_IMPORT",
        )
        return count

    def find_issue_candidates(self, query: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        # Read side remains the existing WarehouseFacade balance/search contract.
        return []

    def get_available_position(self, serial_number: str) -> dict[str, Any] | None:
        row = self.repository.available_position(serial_number)
        return dict(row) if row is not None else None

    def _prepare_rows(self, rows: Iterable[dict[str, Any]], *, soft: bool) -> list[dict[str, Any]]:
        source_rows = [dict(row) for row in rows]
        prepared: list[dict[str, Any]] = []
        with connect(self.repository.db_path) as db:
            references = self.repository.reference_sets(db)
            for line, source in enumerate(source_rows, start=2):
                if not any(str(value or "").strip() for value in source.values()):
                    continue
                candidate = soft_issue_source(source) if soft else source
                row = prepare_issue(
                    candidate,
                    references,
                    line_number=line,
                    strict_references=not soft if soft else self.strict_reference_validation,
                )
                row["_line"] = line
                prepared.append(row)
        if not prepared:
            raise WarehouseError("В CSV-файле нет строк расхода")
        return prepared

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

    @staticmethod
    def _required(value: str, field: str) -> str:
        value = value.strip()
        if not value:
            raise WarehouseError(f"Поле «{field}» не может быть пустым")
        return value
