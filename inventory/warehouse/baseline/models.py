"""Stable public vocabulary for the initial-inventory safety gate."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class SystemState(StrEnum):
    NOT_INITIALIZED = "NOT_INITIALIZED"
    INVENTORY_IN_PROGRESS = "INVENTORY_IN_PROGRESS"
    INVENTORY_REVIEW = "INVENTORY_REVIEW"
    BASELINE_PUBLISHING = "BASELINE_PUBLISHING"
    READY = "READY"
    DEGRADED = "DEGRADED"


class SessionStatus(StrEnum):
    DRAFT = "DRAFT"
    UPLOADED = "UPLOADED"
    PREVIEWING = "PREVIEWING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


IN_PROGRESS_STATUSES = {
    SessionStatus.DRAFT.value,
    SessionStatus.UPLOADED.value,
    SessionStatus.PREVIEWING.value,
}
REVIEW_STATUSES = {
    SessionStatus.REVIEW_REQUIRED.value,
    SessionStatus.READY_FOR_APPROVAL.value,
}
INACTIVE_STATUSES = {SessionStatus.REJECTED.value}

COMPATIBILITY_MAPPING_VERSION = "COMPATIBILITY_V1_DATACENTER_SHELF"
TEMPLATE_ID = "ODE-FULL-INVENTORY"
TEMPLATE_VERSION = "1.0"
PARSER_VERSION = "inventory-xlsx/1"


@dataclass(frozen=True)
class InventoryPaths:
    root: Path

    @property
    def previews(self) -> Path:
        return self.root / "previews"

    @property
    def sources(self) -> Path:
        return self.root / "sources" / "sha256"

    @property
    def candidates(self) -> Path:
        return self.root / "candidates"

    def workspace(self, opaque_id: str) -> Path:
        return self.previews / f"{opaque_id}.db"


@dataclass(frozen=True)
class ActorSnapshot:
    actor_id: str
    display: str
    role: str


@dataclass(frozen=True)
class PreviewFinding:
    code: str
    severity: str
    blocking: bool
    field_code: str
    message: str
    evidence: dict[str, object]
    row_number: int | None = None
