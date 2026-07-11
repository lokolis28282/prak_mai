"""Delivery domain model placeholders."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeliveryModel:
    id: int
    delivery_number: str
    status: str
