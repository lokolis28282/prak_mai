"""History domain model placeholders."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HistoryEvent:
    event_date: str
    action: str
    quantity: float | str = ""
