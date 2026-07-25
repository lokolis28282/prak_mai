"""Shared helpers and exceptions for warehouse services."""

from __future__ import annotations


STRICT_REFERENCES = False


class WarehouseError(ValueError):
    """Ошибка проверки или выполнения складской операции."""
