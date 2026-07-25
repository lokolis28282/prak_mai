"""Immutable contracts for the Stage 0.13.3A.5 migration pilot.

The contracts live in the offline migration package.  Runtime warehouse code
may accept their plain mapping representation, but must not import this module.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping


PILOT_STAGE = "0.13.3A.5"
PILOT_MARKER = "ODE_MIGRATION_PILOT"
PILOT_STATUS = "READY_FOR_REVIEW"
PILOT_SELECTION_SEED = "ODE-0.13.3A.5-PILOT-v1"
PILOT_SELECTION_SIZE = 200
SERIAL_REVIEW_SHA256 = (
    "1d8cf4557d47a50206fbaad6f53a1515cf164a5ecdbb613afd7d7e64005c59a4"
)

IMPORT = "IMPORT"
QUARANTINE = "QUARANTINE"
MANUAL_REVIEW = "MANUAL_REVIEW"
EXACT_DUPLICATE = "EXACT_DUPLICATE"
CONFLICT_HISTORY_ONLY = "CONFLICT_HISTORY_ONLY"
QUANTITY_POSITION_DEFERRED = "QUANTITY_POSITION_DEFERRED"
SOURCE_CORRUPTED_REJECTED = "SOURCE_CORRUPTED_REJECTED"

PILOT_DECISIONS = (
    IMPORT,
    QUARANTINE,
    MANUAL_REVIEW,
    EXACT_DUPLICATE,
    CONFLICT_HISTORY_ONLY,
    QUANTITY_POSITION_DEFERRED,
    SOURCE_CORRUPTED_REJECTED,
)


@dataclass(frozen=True)
class PilotPaths:
    """All mutable and immutable paths used by one offline pilot build."""

    source_candidate: Path
    production_db: Path
    raw_dir: Path
    normalized_dir: Path
    serial_review: Path
    pilot_db: Path
    selection_xlsx: Path
    selection_markdown: Path


@dataclass(frozen=True)
class PilotSelectionRow:
    """One selected receipt source row and its preservation-aware decision."""

    selection_order: int
    staging_row_id: int
    migration_batch_id: int
    source_file: str
    source_sheet: str
    source_row: int
    source_row_hash: str
    source_serial_value: str
    normalized_match_value: str
    serial_preservation_status: str
    excel_cell_type: str
    excel_number_format: str
    raw_xml_value: str
    source_display_value: str
    source_serial_hash: str
    source_item_name: str
    canonical_item_name: str
    object_kind: str
    equipment_category: str
    equipment_type: str
    component_type: str
    vendor: str
    model: str
    part_number: str
    supplier: str
    datacenter: str
    shelf: str
    quantity: str
    source_receipt_date: str
    source_receipt_date_raw: str
    source_receipt_date_status: str
    source_receipt_date_cell_type: str
    source_receipt_date_number_format: str
    migration_warnings: tuple[str, ...]
    selection_reasons: tuple[str, ...]
    quota_flags: tuple[str, ...]
    conflict_types: tuple[str, ...]
    duplicate_group_size: int
    import_decision: str
    identity_key: str
    target_receipt_id: int | None = None

    def as_mapping(self) -> dict[str, Any]:
        """Return a writer-friendly mapping without exposing local paths."""
        return asdict(self)


@dataclass(frozen=True)
class PilotSelection:
    rows: tuple[PilotSelectionRow, ...]
    decision_counts: Mapping[str, int]
    quota_counts: Mapping[str, int]
    selection_sha256: str
    source_candidate_sha256: str
    source_manifest_sha256: str
    serial_review_sha256: str
    unavailable_requirements: tuple[str, ...]


@dataclass(frozen=True)
class PilotBuildResult:
    report: Mapping[str, Any]
    selection: PilotSelection
