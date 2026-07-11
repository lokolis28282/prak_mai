"""Shared date helpers boundary."""

from __future__ import annotations

from datetime import date


def today_iso() -> str:
    return date.today().isoformat()
