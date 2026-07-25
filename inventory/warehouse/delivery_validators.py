"""Validation helpers for delivery document import."""

from __future__ import annotations

import re
from typing import Any

from .delivery_models import (
    NO_SERIAL_LABEL,
    QUANTITY_ERROR_LABEL,
    REVIEW_LABEL,
    STATE_ERROR,
    STATE_WAITING,
)


def split_serials(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    parts = re.split(r"[,;\n\r\t]+|\s{2,}", text)
    if len(parts) == 1:
        parts = [text]
    return [part.strip() for part in parts if part.strip()]


def parse_quantity(value: Any) -> tuple[float | None, str]:
    text = str(value if value is not None and value != "" else "1").strip().replace(",", ".")
    try:
        quantity = float(text)
    except ValueError:
        return None, "Некорректное количество"
    if quantity <= 0:
        return None, "Количество должно быть больше нуля"
    return quantity, ""


def quantity_warning(quantity: float | None, serial_count: int) -> str:
    if quantity is None:
        return QUANTITY_ERROR_LABEL
    if serial_count == 0:
        return NO_SERIAL_LABEL
    if serial_count == 1 and quantity > 1:
        return REVIEW_LABEL
    if serial_count > 1 and int(quantity) != serial_count:
        return QUANTITY_ERROR_LABEL
    return ""


def state_for_validation(serial: str, quantity_error: str) -> tuple[str, str]:
    if not serial:
        return STATE_ERROR, "Не указан S/N"
    if quantity_error == QUANTITY_ERROR_LABEL:
        return STATE_ERROR, "Количество и S/N не согласованы"
    return STATE_WAITING, ""
