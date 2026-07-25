"""Warehouse item naming rules."""

from __future__ import annotations


def build_item_name(category: str, item_type: str, vendor: str = "", model: str = "") -> str:
    kind = str(item_type or category or "").strip()
    maker = str(vendor or "").strip()
    model_text = str(model or "").strip()
    parts: list[str] = []
    if kind:
        parts.append(kind)
    if maker and maker.casefold() not in " ".join(parts).casefold().split():
        parts.append(maker)
    if model_text:
        current = " ".join(parts).casefold()
        if not kind or kind.casefold() not in model_text.casefold() or model_text.casefold() != current:
            parts.append(model_text)
    return " ".join(part for part in parts if part).strip() or "Позиция"
