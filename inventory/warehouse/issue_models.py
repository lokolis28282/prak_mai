"""Serialized equipment/component issue models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IssueRequest:
    issue_date: str
    responsible: str
    task_type: str
    task_number: str
    source_serial_number: str
    quantity: float
    target_serial_number: str = ""
    target_hostname: str = ""
    comment: str = ""


@dataclass(frozen=True)
class IssueResult:
    issue_id: int
    allocated_count: int
    unmatched: bool = False
