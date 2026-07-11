"""Receipt domain model placeholders."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReceiptModel:
    id: int
    item_name: str
    quantity: float
    serial_number: str = ""
