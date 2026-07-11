"""Balance domain model placeholders."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BalanceModel:
    position_key: str
    item_name: str
    balance: float
