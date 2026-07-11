"""Uploaded daily report write contract."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from inventory.shared.validators import WarehouseError

from .imports import ReportsPreviewStore, preview_limits
from .repository import ReportsRepository
from .validators import prepare_daily_report_row


class DailyReportImportService:
    def __init__(
        self,
        db_path: str | Path,
        *,
        work_logs: Any,
        previews: ReportsPreviewStore | None = None,
    ):
        self.repository = ReportsRepository(db_path)
        self.work_logs = work_logs
        self.previews = previews or ReportsPreviewStore()

    def import_daily_report(
        self, filename: str, rows: Iterable[dict[str, Any]]
    ) -> dict[str, Any]:
        self.work_logs._require_write()
        filename = Path(str(filename or "daily_report.csv")).name.strip()
        if not filename:
            raise WarehouseError("Поле «имя файла» не может быть пустым")
        prepared = self._prepare_rows(rows)
        return self.repository.insert_daily_report(
            filename,
            prepared,
            uploaded_by=self.work_logs.uploaded_by(),
            audit_author=self.work_logs.audit_author(),
        )

    def preview_daily_report_import(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        filename: str = "daily_report.csv",
    ) -> dict[str, Any]:
        self.work_logs._require_write()
        source_rows = [dict(row) for row in rows]
        shown: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        error_count = valid = total = 0
        row_limit, error_limit = preview_limits()
        for line, source in enumerate(source_rows, start=2):
            if not any(str(value or "").strip() for value in source.values()):
                continue
            total += 1
            reason = ""
            prepared: dict[str, Any] | None = None
            try:
                prepared = prepare_daily_report_row(source, line_number=line)
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
            errors.append({"line": 1, "reason": "В CSV-файле нет строк ежедневного отчета"})
        return self.previews.store(
            kind="daily_report",
            author=self.work_logs.audit_author(),
            filename=filename,
            rows=source_rows,
            validation={
                "total": total,
                "valid": valid,
                "new": valid,
                "duplicates": 0,
                "error_count": error_count,
                "errors": errors,
                "rows": shown,
                "mode": "strict",
            },
        )

    def confirm_daily_report_import(self, preview_id: str) -> dict[str, Any]:
        self.work_logs._require_write()
        preview = self.previews.consume(
            preview_id, kind="daily_report", author=self.work_logs.audit_author()
        )
        check = self.preview_daily_report_import(
            preview["rows"], filename=preview.get("filename", "daily_report.csv")
        )
        self.previews.consume(check["preview_id"], kind="daily_report", author=self.work_logs.audit_author())
        if check["errors"]:
            raise WarehouseError(check["errors"][0]["reason"])
        return self.import_daily_report(preview.get("filename", "daily_report.csv"), preview["rows"])

    def _prepare_rows(self, rows: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
        prepared: list[dict[str, str]] = []
        for line_number, source in enumerate(rows, start=2):
            if not any(str(value or "").strip() for value in source.values()):
                continue
            prepared.append(prepare_daily_report_row(source, line_number=line_number))
        if not prepared:
            raise WarehouseError("В CSV-файле нет строк ежедневного отчета")
        return prepared
