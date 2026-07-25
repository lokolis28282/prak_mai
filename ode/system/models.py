"""Immutable system diagnostics and health contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class HealthStatus(str, Enum):
    READY = "READY"
    NOT_INITIALIZED = "NOT_INITIALIZED"
    DEGRADED = "DEGRADED"
    INVALID_SCHEMA = "INVALID_SCHEMA"
    INTEGRITY_FAILED = "INTEGRITY_FAILED"
    FOREIGN_KEY_FAILED = "FOREIGN_KEY_FAILED"
    UNSUPPORTED_VERSION = "UNSUPPORTED_VERSION"


class BaselineState(str, Enum):
    NOT_INITIALIZED = "NOT_INITIALIZED"
    ACTIVE = "ACTIVE"
    INCONSISTENT = "INCONSISTENT"
    UNKNOWN = "UNKNOWN"


class ProjectionState(str, Enum):
    UNAVAILABLE = "UNAVAILABLE"
    ACTIVE = "ACTIVE"
    INCONSISTENT = "INCONSISTENT"
    UNKNOWN = "UNKNOWN"


class LegacyHistoryState(str, Enum):
    NOT_IMPORTED = "NOT_IMPORTED"
    IMPORTED = "IMPORTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class DatabaseObjectCounts:
    tables: int
    indexes: int
    triggers: int
    views: int

    def to_dict(self) -> dict[str, int]:
        return {
            "tables": self.tables,
            "indexes": self.indexes,
            "triggers": self.triggers,
            "views": self.views,
        }


@dataclass(frozen=True)
class MigrationEntry:
    version: int
    name: str
    checksum: str

    def to_dict(self) -> dict[str, str | int]:
        return {
            "version": self.version,
            "name": self.name,
            "checksum": self.checksum,
        }


@dataclass(frozen=True)
class MigrationStatus:
    expected_schema_version: int
    user_version: int
    expected_application_id: int
    application_id: int
    expected_migration_count: int
    applied_migration_count: int
    expected: tuple[MigrationEntry, ...]
    applied: tuple[MigrationEntry, ...]
    ready: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "expected_schema_version": self.expected_schema_version,
            "user_version": self.user_version,
            "expected_application_id": self.expected_application_id,
            "application_id": self.application_id,
            "expected_migration_count": self.expected_migration_count,
            "applied_migration_count": self.applied_migration_count,
            "expected": [entry.to_dict() for entry in self.expected],
            "applied": [entry.to_dict() for entry in self.applied],
            "ready": self.ready,
        }


@dataclass(frozen=True)
class DatabaseDiagnostics:
    database_path: str
    file_size_bytes: int
    user_version: int
    application_id: int
    migrations: MigrationStatus
    integrity_result: str
    foreign_key_violations: int
    wal_present: bool
    shm_present: bool
    journal_present: bool
    objects: DatabaseObjectCounts
    active_snapshot_id: int | None
    ledger_head: int
    baseline_state: BaselineState
    projection_state: ProjectionState
    legacy_history_state: LegacyHistoryState
    schema_hash: str
    schema_ready: bool
    warehouse_posting_enabled: bool
    users_count: int
    equipment_count: int
    legacy_events_count: int
    snapshots_count: int
    ledger_count: int
    projections_count: int
    external_path_override: bool
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "database_path": self.database_path,
            "file_size_bytes": self.file_size_bytes,
            "user_version": self.user_version,
            "application_id": self.application_id,
            "migrations": self.migrations.to_dict(),
            "integrity_result": self.integrity_result,
            "foreign_key_violations": self.foreign_key_violations,
            "sidecars": {
                "wal": self.wal_present,
                "shm": self.shm_present,
                "journal": self.journal_present,
            },
            "objects": self.objects.to_dict(),
            "active_snapshot_id": self.active_snapshot_id,
            "ledger_head": self.ledger_head,
            "baseline_state": self.baseline_state.value,
            "projection_state": self.projection_state.value,
            "legacy_history_state": self.legacy_history_state.value,
            "schema_hash": self.schema_hash,
            "schema_ready": self.schema_ready,
            "warehouse_posting_enabled": self.warehouse_posting_enabled,
            "empty_domain_counts": {
                "users": self.users_count,
                "equipment": self.equipment_count,
                "legacy_events": self.legacy_events_count,
                "snapshots": self.snapshots_count,
                "ledger": self.ledger_count,
                "projections": self.projections_count,
            },
            "external_path_override": self.external_path_override,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class SystemHealth:
    status: HealthStatus
    schema_ready: bool
    baseline_state: BaselineState
    warehouse_posting_enabled: bool
    active_snapshot_id: int | None
    ledger_head: int
    projection_state: ProjectionState
    legacy_history_state: LegacyHistoryState
    warnings: tuple[str, ...]
    diagnostics: DatabaseDiagnostics

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "schema_ready": self.schema_ready,
            "baseline_state": self.baseline_state.value,
            "warehouse_posting_enabled": self.warehouse_posting_enabled,
            "active_snapshot_id": self.active_snapshot_id,
            "ledger_head": self.ledger_head,
            "projection_state": self.projection_state.value,
            "legacy_history_state": self.legacy_history_state.value,
            "warnings": list(self.warnings),
            "diagnostics": self.diagnostics.to_dict(),
        }
