"""Cable warehouse data models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CableStockItem:
    cable_type: str
    item_name: str
    supplier: str
    vendor: str
    project: str
    datacenter: str
    shelf: str
    object_name: str
    quantity: float
    unit: str
    operation_date: str
    responsible: str
    comment: str = ""


@dataclass(frozen=True)
class CableOperation:
    cable_type: str
    item_name: str
    quantity: float
    unit: str
    operation_date: str
    responsible: str
    project: str = ""
    datacenter: str = ""
    shelf: str = ""
    task_type: str = ""
    task_number: str = ""
    comment: str = ""
