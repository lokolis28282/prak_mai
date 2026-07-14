"""Work log write contract implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from inventory.shared.db import connect
from inventory.shared.validators import WarehouseError

from .imports import ReportsPreviewStore, preview_limits
from .repository import ReportsRepository
from .validators import (
    match_section,
    migration_placeholders,
    parse_date,
    prepare_work_log,
    soft_work_log_source,
)


class WorkLogService:
    def __init__(
        self,
        db_path: str | Path,
        *,
        actor_provider: Any,
        strict_reference_validation: bool = True,
        previews: ReportsPreviewStore | None = None,
    ):
        self.repository = ReportsRepository(db_path)
        self.actor_provider = actor_provider
        self.strict_reference_validation = strict_reference_validation
        self.previews = previews or ReportsPreviewStore()

    def create_work_log(self, data: dict[str, Any]) -> int:
        self._require_write()
        with connect(self.repository.db_path) as db:
            row = prepare_work_log(
                data,
                references=self.repository.reference_sets(db),
                strict_references=self.strict_reference_validation,
            )
        return self.repository.insert_work_log(row, author=self.audit_author())

    def update_work_log(self, log_id: int, data: dict[str, Any]) -> None:
        self._require_write()
        with connect(self.repository.db_path) as db:
            row = prepare_work_log(
                data,
                references=self.repository.reference_sets(db),
                strict_references=self.strict_reference_validation,
            )
        self.repository.update_work_log(int(log_id), row, author=self.audit_author())

    def delete_work_log(self, log_id: int) -> None:
        self._require_write()
        self.repository.delete_work_log(int(log_id), author=self.audit_author())

    def _known_sections(self) -> dict[str, str]:
        from inventory.reports.validators import _normalize

        with connect(self.repository.db_path) as db:
            names = [
                str(row["name"])
                for row in db.execute(
                    "SELECT name FROM reference_values "
                    "WHERE kind = 'work_log_section' AND is_active = 1"
                )
            ]
        return {_normalize(name): name for name in names}

    def resolve_import_sections(
        self, rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Match each row's section to a known value, flagging unmatched rows.

        Migrated data is never dropped: an unmatched section is kept verbatim and
        the row is marked `needs_review` so it can be corrected in the UI later.
        """
        known = self._known_sections()
        resolved: list[dict[str, Any]] = []
        for source in rows:
            row = migration_placeholders(source)
            matched, needs_review = match_section(str(row.get("section", "")), known)
            row["section"] = matched
            if needs_review:
                row["needs_review"] = 1
            resolved.append(row)
        return resolved

    def preview_xlsx_import(
        self, data: bytes, *, sheet_name: str, filename: str
    ) -> dict[str, Any]:
        """Read a work-log sheet from an XLSX file and produce an import preview."""
        from inventory.importing import xlsx_rows_to_records
        from inventory.shared.xlsx import MAX_XLSX_BYTES, XlsxError, read_sheet

        self._require_write()
        if len(data) > MAX_XLSX_BYTES:
            raise WarehouseError("XLSX-файл превышает допустимый размер 50 МБ")
        try:
            raw_rows = read_sheet(data, sheet_name)
        except XlsxError as error:
            raise WarehouseError(str(error)) from error
        records = xlsx_rows_to_records(raw_rows)
        rows = self.resolve_import_sections(records)
        return self.preview_work_log_import(rows, filename=filename, soft=True)

    def create_work_logs(self, rows: Iterable[dict[str, Any]]) -> int:
        self._require_write()
        source_rows = [dict(row) for row in rows]
        if not source_rows:
            raise WarehouseError("Добавьте хотя бы одну задачу")
        with connect(self.repository.db_path) as db:
            references = self.repository.reference_sets(db)
            prepared = [
                prepare_work_log(
                    row,
                    references=references,
                    line_number=index,
                    strict_references=self.strict_reference_validation,
                )
                for index, row in enumerate(source_rows, start=1)
            ]
        return self.repository.insert_work_logs(prepared, author=self.audit_author())

    def import_work_logs(self, rows: Iterable[dict[str, Any]], *, soft: bool = False) -> int:
        self._require_write()
        prepared = self._prepare_import_rows(rows, soft=soft)
        return self.repository.import_work_logs(
            prepared,
            author=self.audit_author(),
            collect_soft_references=soft and not self.strict_reference_validation,
        )

    def preview_work_log_import(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        filename: str = "work_logs.csv",
        soft: bool = True,
    ) -> dict[str, Any]:
        self._require_write()
        source_rows = [dict(row) for row in rows]
        shown: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        error_count = valid = total = duplicates = 0
        seen: set[tuple[str, ...]] = set()
        row_limit, error_limit = preview_limits()
        with connect(self.repository.db_path) as db:
            references = self.repository.reference_sets(db)
            for line, source in enumerate(source_rows, start=2):
                if not any(str(value or "").strip() for value in source.values()):
                    continue
                total += 1
                reason = ""
                prepared: dict[str, Any] | None = None
                try:
                    candidate = soft_work_log_source(source) if soft else source
                    prepared = prepare_work_log(
                        candidate,
                        references=references,
                        line_number=line,
                        strict_references=not soft,
                    )
                    signature = self.repository.work_log_values(prepared)
                    if signature in seen:
                        duplicates += 1
                    seen.add(signature)
                    valid += 1
                except WarehouseError as error:
                    reason = str(error)
                    error_count += 1
                    if len(errors) < error_limit:
                        errors.append({"line": line, "reason": reason})
                if len(shown) < row_limit:
                    item = dict(prepared or source)
                    item.update({"line": line, "valid": not reason, "error": reason})
                    shown.append(item)
        if not total:
            error_count = 1
            errors.append({"line": 1, "reason": "В CSV-файле нет логов работ"})
        return self.previews.store(
            kind="work_logs",
            author=self.audit_author(),
            filename=filename,
            rows=source_rows,
            validation={
                "total": total,
                "valid": valid,
                "new": valid,
                "duplicates": duplicates,
                "error_count": error_count,
                "errors": errors,
                "rows": shown,
                "mode": "soft" if soft else "strict",
            },
        )

    def confirm_work_log_import(self, preview_id: str) -> int:
        self._require_write()
        preview = self.previews.consume(
            preview_id, kind="work_logs", author=self.audit_author()
        )
        soft = preview.get("validation", {}).get("mode") == "soft"
        check = self.preview_work_log_import(
            preview["rows"], filename=preview.get("filename", "work_logs.csv"), soft=soft
        )
        self.previews.consume(check["preview_id"], kind="work_logs", author=self.audit_author())
        if check["errors"]:
            raise WarehouseError(check["errors"][0]["reason"])
        return self.import_work_logs(preview["rows"], soft=soft)

    def _prepare_import_rows(
        self, rows: Iterable[dict[str, Any]], *, soft: bool
    ) -> list[dict[str, str]]:
        with connect(self.repository.db_path) as db:
            references = self.repository.reference_sets(db)
            prepared: list[dict[str, str]] = []
            for line_number, source in enumerate(rows, start=2):
                if not any(str(value or "").strip() for value in source.values()):
                    continue
                candidate = soft_work_log_source(source) if soft else source
                prepared.append(prepare_work_log(
                    candidate,
                    references=references,
                    line_number=line_number,
                    strict_references=not soft,
                ))
        if not prepared:
            raise WarehouseError("В CSV-файле нет логов работ")
        return prepared

    def validate_period(
        self, date_from: str, date_to: str, *, optional: bool = False
    ) -> tuple[str, str]:
        if optional and not date_from and not date_to:
            return "", ""
        start = parse_date(date_from, "дата начала") if date_from else ""
        end = parse_date(date_to, "дата окончания") if date_to else ""
        if not optional and (not start or not end):
            raise WarehouseError("Укажите дату начала и дату окончания")
        if start and end and start > end:
            raise WarehouseError("Дата начала не может быть позже даты окончания")
        return start, end

    def current_user(self) -> dict[str, Any]:
        return self.actor_provider.current_user()

    def audit_author(self) -> str:
        user = self.current_user()
        name = getattr(self.actor_provider, "_core", self.actor_provider)._actor_name.get()
        return name or str(user.get("email") or "lokolis")

    def uploaded_by(self) -> str:
        return str(self.current_user().get("email") or self.audit_author())

    def _require_write(self) -> dict[str, Any]:
        user = self.current_user()
        if user.get("role") not in {"admin", "engineer"}:
            raise WarehouseError("Недостаточно прав для выполнения операции")
        return user
