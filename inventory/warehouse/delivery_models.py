"""Delivery import constants and small helpers."""

from __future__ import annotations

from typing import Any


DELIVERY_IMPORT_KIND = "delivery_import"
PREVIEW_ROW_LIMIT = 100

STATE_WAITING = "Ожидается"
STATE_EXISTING = "Уже на складе"
STATE_DUPLICATE = "Дубль в файле"
STATE_ERROR = "Ошибка"

READY_LABEL = "Готово к загрузке документа"
REVIEW_LABEL = "Требует проверки"
NO_SERIAL_LABEL = "Нет S/N"
QUANTITY_ERROR_LABEL = "Ошибка количества"
UNKNOWN_REQUIRED_LABEL = "Не распознаны обязательные поля"

COMPATIBLE_LINE_STATES = {
    STATE_WAITING,
    STATE_EXISTING,
    STATE_DUPLICATE,
    STATE_ERROR,
}

DELIVERY_TEMPLATE_HEADERS = (
    "Дата",
    "Поставщик",
    "Номер поставки",
    "Заявка",
    "Заказ",
    "PLU",
    "Серийный номер",
    "Инвентарный номер",
    "Вендор",
    "Модель",
    "Тип оборудования",
    "Проект",
    "ЦОД",
    "Полка",
    "Количество",
    "Комментарий",
)


CANONICAL_FIELDS = (
    "delivery_date",
    "supplier",
    "delivery_number",
    "request_number",
    "order_number",
    "plu",
    "serial_number",
    "inventory_number",
    "vendor",
    "model",
    "item_type",
    "project",
    "datacenter",
    "shelf",
    "quantity",
    "comment",
)


def clean_text(value: Any) -> str:
    return str(value or "").strip()
