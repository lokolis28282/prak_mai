"""Health policy over typed read-only diagnostics."""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    BaselineState,
    HealthStatus,
    ProjectionState,
    SystemHealth,
)
from .queries import DiagnosticsQuery


@dataclass(frozen=True)
class SystemService:
    diagnostics_query: DiagnosticsQuery

    def health(self) -> SystemHealth:
        diagnostics = self.diagnostics_query.diagnostics()
        if diagnostics.integrity_result != "ok":
            status = HealthStatus.INTEGRITY_FAILED
        elif diagnostics.foreign_key_violations:
            status = HealthStatus.FOREIGN_KEY_FAILED
        elif diagnostics.user_version != diagnostics.migrations.expected_schema_version:
            status = HealthStatus.UNSUPPORTED_VERSION
        elif not diagnostics.schema_ready:
            status = HealthStatus.INVALID_SCHEMA
        elif diagnostics.baseline_state is BaselineState.NOT_INITIALIZED:
            status = HealthStatus.NOT_INITIALIZED
        elif (
            diagnostics.baseline_state is BaselineState.ACTIVE
            and diagnostics.projection_state is ProjectionState.ACTIVE
            and diagnostics.warehouse_posting_enabled
        ):
            status = HealthStatus.READY
        else:
            status = HealthStatus.DEGRADED
        return SystemHealth(
            status=status,
            schema_ready=diagnostics.schema_ready,
            baseline_state=diagnostics.baseline_state,
            warehouse_posting_enabled=diagnostics.warehouse_posting_enabled,
            active_snapshot_id=diagnostics.active_snapshot_id,
            ledger_head=diagnostics.ledger_head,
            projection_state=diagnostics.projection_state,
            legacy_history_state=diagnostics.legacy_history_state,
            warnings=diagnostics.warnings,
            diagnostics=diagnostics,
        )
