"""Deterministic canonical display names built from structured fields.

Canonical names are recalculable presentation values, never identifiers.  This
module does not inspect or transform Serial Number values.
"""

from __future__ import annotations

from .reference_data import clean_reference_display, normalize_reference_key


_EQUIPMENT_TYPE_LABELS = {
    "server": "Сервер",
    "switch": "Коммутатор",
    "storage system": "Система хранения данных",
    "san switch": "SAN-коммутатор",
    "load balancer": "Балансировщик нагрузки",
    "pdu": "PDU",
    "ups": "ИБП",
    "other": "Оборудование",
}

_COMPONENT_TYPE_LABELS = {
    "cpu": "Процессор",
    "memory": "Оперативная память",
    "ssd": "SSD",
    "hdd": "HDD",
    "nic": "Сетевой адаптер",
    "hba": "HBA-адаптер",
    "raid controller": "RAID-контроллер",
    "psu": "Блок питания",
    "fan": "Вентилятор",
    "transceiver": "Трансивер",
    "motherboard": "Материнская плата",
    "other": "Компонент",
}


def _label(value: str, labels: dict[str, str]) -> str:
    display = clean_reference_display(value)
    return labels.get(normalize_reference_key(display), display)


def _join(*parts: str) -> str:
    return " ".join(clean_reference_display(part) for part in parts if clean_reference_display(part))


def build_equipment_name(equipment_type: str, vendor: str, model: str) -> str:
    """Build ``<Тип> <Вендор> <Модель>`` without fuzzy model handling."""

    return _join(_label(equipment_type, _EQUIPMENT_TYPE_LABELS), vendor, model)


def build_component_name(
    component_type: str,
    vendor: str,
    model: str = "",
    part_number: str = "",
    main_characteristic: str = "",
) -> str:
    """Build a component name from type, vendor, model/PN and characteristic."""

    model_or_part_number = model if clean_reference_display(model) else part_number
    return _join(
        _label(component_type, _COMPONENT_TYPE_LABELS),
        vendor,
        model_or_part_number,
        main_characteristic,
    )
