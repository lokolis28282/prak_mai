"""Immutable contracts for reference-data migration candidates.

These models deliberately contain no persistence code.  They are shared by the
offline candidate builder and its validation/reporting commands; they are not
ORM models for ``data/warehouse.db``.
"""

from __future__ import annotations

from dataclasses import dataclass


AUTO_APPROVED = "AUTO_APPROVED"
PENDING_REVIEW = "PENDING_REVIEW"
CANDIDATE = "CANDIDATE"
APPROVED = "APPROVED"
REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class ReferenceDomain:
    """Definition of one controlled reference domain."""

    key: str
    display_name: str
    description: str
    active: bool = True
    source: str = "ODE 0.13.3A"


@dataclass(frozen=True, slots=True)
class ReferenceValue:
    """Canonical value proposed for a controlled reference domain."""

    domain: str
    canonical_value: str
    display_name: str
    normalized_key: str
    active: bool = True
    source: str = "ODE 0.13.3A"
    created_at: str = ""
    updated_at: str = ""
    id: int | None = None


@dataclass(frozen=True, slots=True)
class ReferenceAlias:
    """Evidence-backed link from a source spelling to a canonical value."""

    domain: str
    source_value: str
    normalized_source_key: str
    canonical_id: int | None = None
    canonical_value: str = ""
    source_file: str = ""
    source_sheet: str = ""
    usage_count: int = 0
    confidence: float = 0.0
    resolution_status: str = PENDING_REVIEW
    approved_by: str = ""
    approved_at: str = ""
    notes: str = ""


@dataclass(frozen=True, slots=True)
class AliasResolution:
    """Pure safety decision; it does not write or approve anything itself."""

    domain: str
    source_value: str
    canonical_value: str
    normalized_source_key: str
    normalized_canonical_key: str
    resolution_status: str
    confidence: float
    requires_manual_review: bool
    rule: str
    reason: str

    @property
    def auto_approved(self) -> bool:
        return self.resolution_status == AUTO_APPROVED


@dataclass(frozen=True, slots=True)
class ReferenceCandidate:
    """Unknown raw value awaiting approval, never a production reference."""

    domain: str
    source_value: str
    proposed_value: str
    normalized_key: str
    source_file: str = ""
    source_sheet: str = ""
    usage_count: int = 0
    confidence: float = 0.0
    resolution_status: str = CANDIDATE
    requires_manual_review: bool = True
    notes: str = ""


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    """A model key scoped by vendor so equal labels cannot cross vendors."""

    vendor: str
    model: str
    normalized_vendor_key: str
    normalized_model_key: str
    scoped_key: str


@dataclass(frozen=True, slots=True)
class CatalogItemCandidate:
    """Structured catalog proposal used to derive a display name."""

    source_item_name: str
    canonical_item_name: str
    vendor: str = ""
    model: str = ""
    part_number: str = ""
    category: str = ""
    equipment_type: str = ""
    component_type: str = ""
    normalization_rule: str = ""
    confidence: float = 0.0
    requires_manual_review: bool = True
