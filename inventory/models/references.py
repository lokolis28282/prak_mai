"""Reference domain model placeholders."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReferenceValue:
    id: int
    kind: str
    name: str
    is_active: bool
