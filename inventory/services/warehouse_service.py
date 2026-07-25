"""Deprecated compatibility adapter for the extracted Warehouse domain."""

from __future__ import annotations

from typing import Any

from ..administration.diagnostics import AdministrationDiagnosticsService
from ..administration.service import AdministrationService
from ..warehouse.service import WarehouseDomainService


class WarehouseCore:
    """Thin adapter retained for imports from ODE 0.15 and earlier."""

    DELIVERY_STATUSES = WarehouseDomainService.DELIVERY_STATUSES
    DELIVERY_EDITABLE_FIELDS = WarehouseDomainService.DELIVERY_EDITABLE_FIELDS
    STRICT_REFERENCE_VALIDATION = WarehouseDomainService.STRICT_REFERENCE_VALIDATION
    STRICT_REFERENCES = WarehouseDomainService.STRICT_REFERENCES
    ROLES = WarehouseDomainService.ROLES
    STATUSES = WarehouseDomainService.STATUSES
    TASK_SOURCES = WarehouseDomainService.TASK_SOURCES
    TASK_TYPES = WarehouseDomainService.TASK_TYPES
    WORK_LOG_STATUSES = WarehouseDomainService.WORK_LOG_STATUSES
    REFERENCE_KINDS = WarehouseDomainService.REFERENCE_KINDS
    RECEIPT_REFERENCE_FIELDS = WarehouseDomainService.RECEIPT_REFERENCE_FIELDS
    ISSUE_REFERENCE_FIELDS = WarehouseDomainService.ISSUE_REFERENCE_FIELDS
    KEY_TABLES = WarehouseDomainService.KEY_TABLES
    RESTORE_BASE_TABLES = WarehouseDomainService.RESTORE_BASE_TABLES

    def __init__(self, *args: Any, **kwargs: Any):
        self._warehouse = WarehouseDomainService(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._warehouse, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_warehouse":
            object.__setattr__(self, name, value)
            return
        setattr(self._warehouse, name, value)

    @staticmethod
    def _public_user(row: Any) -> dict[str, Any]:
        # DEPRECATED: Administration owns user presentation.
        return AdministrationService._public_user(row)

    def authenticate(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: use ApplicationContext.administration.authenticate.
        return self.administration.authenticate(*args, **kwargs)

    def user_by_email(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: use ApplicationContext.administration.get_user.
        return self.administration.user_by_email(*args, **kwargs)

    def current_user(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: use ApplicationContext.administration.current_user.
        return self.administration.current_user(*args, **kwargs)

    def user_context(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: use ApplicationContext.administration.user_context.
        return self.administration.user_context(*args, **kwargs)

    def _require_role(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: Administration owns access policy.
        return self.administration._require_role(*args, **kwargs)

    def _require_write(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: Administration owns access policy.
        return self.administration._require_write(*args, **kwargs)

    def users(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: use ApplicationContext.administration.list_users.
        return self.administration.users(*args, **kwargs)

    def create_user(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: use ApplicationContext.administration.create_user.
        return self.administration.create_user(*args, **kwargs)

    def change_password(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: use ApplicationContext.administration.change_password.
        return self.administration.change_password(*args, **kwargs)

    def update_profile(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: use ApplicationContext.administration.update_profile.
        return self.administration.update_profile(*args, **kwargs)

    def _audit(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: Administration owns the audit trail.
        return self.administration._audit(*args, **kwargs)

    def audit_entries(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: use ApplicationContext.administration.list_audit_entries.
        return self.administration.audit_entries(*args, **kwargs)

    @staticmethod
    def _database_check(*args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: Administration owns database diagnostics.
        return AdministrationDiagnosticsService.database_check(*args, **kwargs)

    def list_backups(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: use ApplicationContext.administration.list_backups.
        return self.administration.list_backups(*args, **kwargs)

    @property
    def backup_dir(self) -> Any:
        # DEPRECATED: Administration owns the backup directory.
        return self.administration.backup_dir

    def _next_backup_path(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: Administration owns backup naming.
        return self.administration._next_backup_path(*args, **kwargs)

    def _backup_by_name(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: Administration owns backup resolution.
        return self.administration._backup_by_name(*args, **kwargs)

    def check_integrity(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: use ApplicationContext.administration.integrity_check.
        return self.administration.check_integrity(*args, **kwargs)

    def create_backup(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: use ApplicationContext.administration.create_backup.
        return self.administration.create_backup(*args, **kwargs)

    def restore_backup(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: use ApplicationContext.administration.restore_backup.
        return self.administration.restore_backup(*args, **kwargs)

    def replace_production_database(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: use Administration.replace_production_database.
        return self.administration.replace_production_database(*args, **kwargs)

    def add_work_log(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: use ApplicationContext.reports.add_work_log.
        return self.reports.add_work_log(*args, **kwargs)

    def add_work_logs(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: use ApplicationContext.reports.add_work_logs.
        return self.reports.add_work_logs(*args, **kwargs)

    def work_logs(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: use ApplicationContext.reports.list_work_logs.
        return self.reports.work_logs(*args, **kwargs)

    def import_work_log_rows(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: use ApplicationContext.reports.import_work_log_rows.
        return self.reports.import_work_log_rows(*args, **kwargs)

    def preview_work_log_rows(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: use ApplicationContext.reports.preview_work_log_rows.
        return self.reports.preview_work_log_rows(*args, **kwargs)

    def confirm_work_log_preview(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: use ApplicationContext.reports.confirm_work_log_preview.
        return self.reports.confirm_work_log_preview(*args, **kwargs)

    def daily_report(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: use ApplicationContext.reports.daily_report.
        return self.reports.daily_report(*args, **kwargs)

    def weekly_report(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: use ApplicationContext.reports.weekly_report.
        return self.reports.weekly_report(*args, **kwargs)

    def weekly_report_rows(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: use ApplicationContext.reports.weekly_report_rows.
        return self.reports.weekly_report_rows(*args, **kwargs)

    def import_daily_report_rows(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: use ApplicationContext.reports.import_daily_report_rows.
        return self.reports.import_daily_report_rows(*args, **kwargs)

    def daily_report_uploads(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: use ApplicationContext.reports.daily_report_uploads.
        return self.reports.daily_report_uploads(*args, **kwargs)

    def uploaded_daily_report(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: use ApplicationContext.reports.uploaded_daily_report.
        return self.reports.uploaded_daily_report(*args, **kwargs)

    def export_work_logs_csv(self, *args: Any, **kwargs: Any) -> Any:
        # DEPRECATED: use ApplicationContext.reports.export_work_logs_csv.
        return self.reports.export_work_logs_csv(*args, **kwargs)
