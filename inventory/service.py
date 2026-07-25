"""Facade for ODE warehouse backend services."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .db import DEFAULT_DB_PATH
from .shared.helpers import STRICT_REFERENCES, WarehouseError
from .services.balance_service import BalanceService
from .services.delivery_service import DeliveryService
from .services.history_service import HistoryService
from .services.inventory_service import InventoryService
from .services.issue_service import IssueService
from .services.monitoring_service import MonitoringService
from .services.profile_service import ProfileService
from .services.receipt_service import ReceiptService
from .services.reference_service import ReferenceService
from .services.report_service import ReportService
from .services.warehouse_service import WarehouseCore


class WarehouseService:
    """Compatibility facade over specialized backend services."""

    DELIVERY_STATUSES = WarehouseCore.DELIVERY_STATUSES
    DELIVERY_EDITABLE_FIELDS = WarehouseCore.DELIVERY_EDITABLE_FIELDS
    STRICT_REFERENCE_VALIDATION = STRICT_REFERENCES
    STRICT_REFERENCES = STRICT_REFERENCES
    ROLES = WarehouseCore.ROLES
    STATUSES = WarehouseCore.STATUSES
    TASK_SOURCES = WarehouseCore.TASK_SOURCES
    TASK_TYPES = WarehouseCore.TASK_TYPES
    WORK_LOG_STATUSES = WarehouseCore.WORK_LOG_STATUSES
    REFERENCE_KINDS = WarehouseCore.REFERENCE_KINDS
    RECEIPT_REFERENCE_FIELDS = WarehouseCore.RECEIPT_REFERENCE_FIELDS
    ISSUE_REFERENCE_FIELDS = WarehouseCore.ISSUE_REFERENCE_FIELDS
    KEY_TABLES = WarehouseCore.KEY_TABLES
    RESTORE_BASE_TABLES = WarehouseCore.RESTORE_BASE_TABLES

    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB_PATH,
        *,
        strict_reference_validation: bool = STRICT_REFERENCE_VALIDATION,
        initialize_database: bool = True,
    ):
        self._core = WarehouseCore(
            db_path,
            strict_reference_validation=strict_reference_validation,
            initialize_database=initialize_database,
        )
        self.profile_service = ProfileService(self._core)
        self.reference_service = ReferenceService(self._core)
        self.receipt_service = ReceiptService(self._core)
        self.issue_service = IssueService(self._core)
        self.delivery_service = DeliveryService(self._core)
        self.balance_service = BalanceService(self._core)
        self.history_service = HistoryService(self._core)
        self.report_service = ReportService(self._core)
        self.monitoring_service = MonitoringService(self._core)
        self.inventory_service = InventoryService(self._core)

    @property
    def db_path(self) -> Path:
        return self._core.db_path

    @property
    def strict_reference_validation(self) -> bool:
        return self._core.strict_reference_validation

    @property
    def lock(self) -> Any:
        return self._core.lock

    @property
    def default_admin_created(self) -> bool:
        return self._core.default_admin_created

    @property
    def backup_dir(self) -> Path:
        return self._core.backup_dir

    def __getattr__(self, name: str) -> Any:
        # Compatibility for private helpers used by legacy CLI/tests during migration.
        return getattr(self._core, name)

    def authenticate(self, *args: Any, **kwargs: Any) -> Any:
        return self.profile_service.authenticate(*args, **kwargs)

    def user_by_email(self, *args: Any, **kwargs: Any) -> Any:
        return self.profile_service.user_by_email(*args, **kwargs)

    def current_user(self, *args: Any, **kwargs: Any) -> Any:
        return self.profile_service.current_user(*args, **kwargs)

    def user_context(self, *args: Any, **kwargs: Any) -> Any:
        return self.profile_service.user_context(*args, **kwargs)

    def users(self, *args: Any, **kwargs: Any) -> Any:
        return self.profile_service.users(*args, **kwargs)

    def create_user(self, *args: Any, **kwargs: Any) -> Any:
        return self.profile_service.create_user(*args, **kwargs)

    def change_password(self, *args: Any, **kwargs: Any) -> Any:
        return self.profile_service.change_password(*args, **kwargs)

    def update_profile(self, *args: Any, **kwargs: Any) -> Any:
        return self.profile_service.update_profile(*args, **kwargs)

    def audit_entries(self, *args: Any, **kwargs: Any) -> Any:
        return self.history_service.audit_entries(*args, **kwargs)

    def warehouse_history(self, *args: Any, **kwargs: Any) -> Any:
        return self.history_service.warehouse_history(*args, **kwargs)

    def operation_log(self, *args: Any, **kwargs: Any) -> Any:
        return self.history_service.operation_log(*args, **kwargs)

    def list_backups(self, *args: Any, **kwargs: Any) -> Any:
        return self.inventory_service.list_backups(*args, **kwargs)

    def create_backup(self, *args: Any, **kwargs: Any) -> Any:
        return self.inventory_service.create_backup(*args, **kwargs)

    def restore_backup(self, *args: Any, **kwargs: Any) -> Any:
        return self.inventory_service.restore_backup(*args, **kwargs)

    def replace_production_database(self, *args: Any, **kwargs: Any) -> Any:
        return self.inventory_service.replace_production_database(*args, **kwargs)

    def add_equipment(self, *args: Any, **kwargs: Any) -> Any:
        return self.inventory_service.add_equipment(*args, **kwargs)

    def move(self, *args: Any, **kwargs: Any) -> Any:
        return self.inventory_service.move(*args, **kwargs)

    def equipment(self, *args: Any, **kwargs: Any) -> Any:
        return self.inventory_service.equipment(*args, **kwargs)

    def inventory_compare(self, *args: Any, **kwargs: Any) -> Any:
        return self.inventory_service.inventory_compare(*args, **kwargs)

    def import_operation_rows(self, *args: Any, **kwargs: Any) -> Any:
        return self.inventory_service.import_operation_rows(*args, **kwargs)

    def import_equipment_rows(self, *args: Any, **kwargs: Any) -> Any:
        return self.inventory_service.import_equipment_rows(*args, **kwargs)

    def export_csv(self, *args: Any, **kwargs: Any) -> Any:
        return self.inventory_service.export_csv(*args, **kwargs)

    def import_preview_rows(self, *args: Any, **kwargs: Any) -> Any:
        return self.inventory_service.import_preview_rows(*args, **kwargs)

    def check_integrity(self, *args: Any, **kwargs: Any) -> Any:
        return self.monitoring_service.check_integrity(*args, **kwargs)

    def data_quality_problems(self, *args: Any, **kwargs: Any) -> Any:
        return self.monitoring_service.data_quality_problems(*args, **kwargs)

    def add_category(self, *args: Any, **kwargs: Any) -> Any:
        return self.reference_service.add_category(*args, **kwargs)

    def add_location(self, *args: Any, **kwargs: Any) -> Any:
        return self.reference_service.add_location(*args, **kwargs)

    def references(self, *args: Any, **kwargs: Any) -> Any:
        return self.reference_service.references(*args, **kwargs)

    def reference_groups(self, *args: Any, **kwargs: Any) -> Any:
        return self.reference_service.reference_groups(*args, **kwargs)

    def add_reference(self, *args: Any, **kwargs: Any) -> Any:
        return self.reference_service.add_reference(*args, **kwargs)

    def set_reference_active(self, *args: Any, **kwargs: Any) -> Any:
        return self.reference_service.set_reference_active(*args, **kwargs)

    def reference_data(self, *args: Any, **kwargs: Any) -> Any:
        return self.reference_service.reference_data(*args, **kwargs)

    def receipt(self, *args: Any, **kwargs: Any) -> Any:
        return self.receipt_service.receipt(*args, **kwargs)

    def preview_stock_receipt_rows(self, *args: Any, **kwargs: Any) -> Any:
        return self.receipt_service.preview_stock_receipt_rows(*args, **kwargs)

    def confirm_stock_receipt_preview(self, *args: Any, **kwargs: Any) -> Any:
        return self.receipt_service.confirm_stock_receipt_preview(*args, **kwargs)

    def scan_receipt_serial(self, *args: Any, **kwargs: Any) -> Any:
        return self.receipt_service.scan_receipt_serial(*args, **kwargs)

    def confirm_scanned_receipts(self, *args: Any, **kwargs: Any) -> Any:
        return self.receipt_service.confirm_scanned_receipts(*args, **kwargs)

    def add_stock_receipt(self, *args: Any, **kwargs: Any) -> Any:
        return self.receipt_service.add_stock_receipt(*args, **kwargs)

    def import_stock_receipt_rows(self, *args: Any, **kwargs: Any) -> Any:
        return self.receipt_service.import_stock_receipt_rows(*args, **kwargs)

    def stock_receipts(self, *args: Any, **kwargs: Any) -> Any:
        return self.receipt_service.stock_receipts(*args, **kwargs)

    def preview_delivery_rows(self, *args: Any, **kwargs: Any) -> Any:
        return self.delivery_service.preview_delivery_rows(*args, **kwargs)

    def confirm_delivery_preview(self, *args: Any, **kwargs: Any) -> Any:
        return self.delivery_service.confirm_delivery_preview(*args, **kwargs)

    def deliveries(self, *args: Any, **kwargs: Any) -> Any:
        return self.delivery_service.deliveries(*args, **kwargs)

    def delivery(self, *args: Any, **kwargs: Any) -> Any:
        return self.delivery_service.delivery(*args, **kwargs)

    def update_delivery_lines(self, *args: Any, **kwargs: Any) -> Any:
        return self.delivery_service.update_delivery_lines(*args, **kwargs)

    def accept_delivery_serial(self, *args: Any, **kwargs: Any) -> Any:
        return self.delivery_service.accept_delivery_serial(*args, **kwargs)

    def close_delivery(self, *args: Any, **kwargs: Any) -> Any:
        return self.delivery_service.close_delivery(*args, **kwargs)

    def dashboard_stats(self, *args: Any, **kwargs: Any) -> Any:
        return self.balance_service.dashboard_stats(*args, **kwargs)

    def balance_by_category(self, *args: Any, **kwargs: Any) -> Any:
        return self.balance_service.balance_by_category(*args, **kwargs)

    def warehouse_categories(self, *args: Any, **kwargs: Any) -> Any:
        return self.balance_service.warehouse_categories(*args, **kwargs)

    def warehouse_type_summary(self, *args: Any, **kwargs: Any) -> Any:
        return self.balance_service.warehouse_type_summary(*args, **kwargs)

    def stock_balance(self, *args: Any, **kwargs: Any) -> Any:
        return self.balance_service.stock_balance(*args, **kwargs)

    def search_stock_positions(self, *args: Any, **kwargs: Any) -> Any:
        return self.balance_service.search_stock_positions(*args, **kwargs)

    def position_card(self, *args: Any, **kwargs: Any) -> Any:
        return self.balance_service.position_card(*args, **kwargs)

    def issue(self, *args: Any, **kwargs: Any) -> Any:
        return self.issue_service.issue(*args, **kwargs)

    def add_stock_issue(self, *args: Any, **kwargs: Any) -> Any:
        return self.issue_service.add_stock_issue(*args, **kwargs)

    def scan_issue_serial(self, *args: Any, **kwargs: Any) -> Any:
        return self.issue_service.scan_issue_serial(*args, **kwargs)

    def confirm_scanned_issues(self, *args: Any, **kwargs: Any) -> Any:
        return self.issue_service.confirm_scanned_issues(*args, **kwargs)

    def import_stock_issue_rows(self, *args: Any, **kwargs: Any) -> Any:
        return self.issue_service.import_stock_issue_rows(*args, **kwargs)

    def preview_stock_issue_rows(self, *args: Any, **kwargs: Any) -> Any:
        return self.issue_service.preview_stock_issue_rows(*args, **kwargs)

    def confirm_stock_issue_preview(self, *args: Any, **kwargs: Any) -> Any:
        return self.issue_service.confirm_stock_issue_preview(*args, **kwargs)

    def preview_bulk_issue_serials(self, *args: Any, **kwargs: Any) -> Any:
        return self.issue_service.preview_bulk_issue_serials(*args, **kwargs)

    def confirm_bulk_issue_preview(self, *args: Any, **kwargs: Any) -> Any:
        return self.issue_service.confirm_bulk_issue_preview(*args, **kwargs)

    def stock_issue_rows(self, *args: Any, **kwargs: Any) -> Any:
        return self.issue_service.stock_issue_rows(*args, **kwargs)

    def add_work_log(self, *args: Any, **kwargs: Any) -> Any:
        return self.report_service.add_work_log(*args, **kwargs)

    def add_work_logs(self, *args: Any, **kwargs: Any) -> Any:
        return self.report_service.add_work_logs(*args, **kwargs)

    def work_logs(self, *args: Any, **kwargs: Any) -> Any:
        return self.report_service.work_logs(*args, **kwargs)

    def import_work_log_rows(self, *args: Any, **kwargs: Any) -> Any:
        return self.report_service.import_work_log_rows(*args, **kwargs)

    def preview_work_log_rows(self, *args: Any, **kwargs: Any) -> Any:
        return self.report_service.preview_work_log_rows(*args, **kwargs)

    def confirm_work_log_preview(self, *args: Any, **kwargs: Any) -> Any:
        return self.report_service.confirm_work_log_preview(*args, **kwargs)

    def daily_report(self, *args: Any, **kwargs: Any) -> Any:
        return self.report_service.daily_report(*args, **kwargs)

    def weekly_report(self, *args: Any, **kwargs: Any) -> Any:
        return self.report_service.weekly_report(*args, **kwargs)

    def weekly_report_rows(self, *args: Any, **kwargs: Any) -> Any:
        return self.report_service.weekly_report_rows(*args, **kwargs)

    def import_daily_report_rows(self, *args: Any, **kwargs: Any) -> Any:
        return self.report_service.import_daily_report_rows(*args, **kwargs)

    def daily_report_uploads(self, *args: Any, **kwargs: Any) -> Any:
        return self.report_service.daily_report_uploads(*args, **kwargs)

    def uploaded_daily_report(self, *args: Any, **kwargs: Any) -> Any:
        return self.report_service.uploaded_daily_report(*args, **kwargs)

    def export_work_logs_csv(self, *args: Any, **kwargs: Any) -> Any:
        return self.report_service.export_work_logs_csv(*args, **kwargs)
