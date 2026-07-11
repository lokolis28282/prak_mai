"""Issue domain model placeholders."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IssueModel:
    id: int
    quantity: float
    source_serial_number: str = ""
