"""Pure reference-domain, key-normalization and alias-safety rules.

Only syntactic equivalents may be approved automatically: Unicode NFKC,
outer whitespace, repeated whitespace and case.  Different semantic values are
always candidates for manual review even when a human might eventually decide
to merge them.
"""

from __future__ import annotations

from typing import Iterator

from inventory.shared.reference_normalization import (
    clean_reference_display,
    normalize_reference_key,
)

from .models import (
    AUTO_APPROVED,
    CANDIDATE,
    PENDING_REVIEW,
    AliasResolution,
    ModelIdentity,
    ReferenceAlias,
    ReferenceCandidate,
    ReferenceDomain,
    ReferenceValue,
)


DOMAIN_DEFINITIONS: tuple[ReferenceDomain, ...] = (
    ReferenceDomain("object_kind", "Объект учёта", "Equipment, component, cable or consumable."),
    ReferenceDomain("equipment_category", "Категория оборудования", "High-level equipment family."),
    ReferenceDomain("equipment_role", "Роль оборудования", "Operational role of equipment."),
    ReferenceDomain("equipment_type", "Тип оборудования", "Concrete equipment type."),
    ReferenceDomain("component_type", "Тип компонента", "Concrete component type."),
    ReferenceDomain("cable_type", "Тип кабеля", "Concrete cable construction/type."),
    ReferenceDomain("cable_category", "Категория кабеля", "High-level cable family."),
    ReferenceDomain("vendor", "Вендор", "Product manufacturer."),
    ReferenceDomain("model", "Модель", "Vendor-scoped product model."),
    ReferenceDomain("catalog_item", "Каталожная позиция", "Canonical product/catalog item."),
    ReferenceDomain("supplier", "Поставщик", "Legal supplier value."),
    ReferenceDomain("datacenter", "ЦОД", "Datacenter site."),
    ReferenceDomain("warehouse_location", "Складская локация", "Storage placement, not identity."),
    ReferenceDomain("storage_zone", "Зона хранения", "Named warehouse storage zone."),
    ReferenceDomain("rack", "Стеллаж", "Rack or shelving unit."),
    ReferenceDomain("shelf", "Полка", "Approved shelf value, not identity."),
    ReferenceDomain("project", "Проект", "Warehouse project reference."),
    ReferenceDomain("unit_of_measure", "Единица измерения", "Quantity unit."),
    ReferenceDomain("operation_source", "Источник операции", "Provenance of a warehouse operation."),
    ReferenceDomain("issue_reason", "Причина расхода", "Reason for issuing stock."),
)

DOMAIN_KEYS = frozenset(definition.key for definition in DOMAIN_DEFINITIONS)


def _seed(domain: str, canonical_value: str, display_name: str) -> ReferenceValue:
    return ReferenceValue(
        domain=domain,
        canonical_value=canonical_value,
        display_name=display_name,
        normalized_key=normalize_reference_key(canonical_value),
        source="ODE 0.13.3A controlled seed",
    )


REFERENCE_SEEDS: tuple[ReferenceValue, ...] = (
    _seed("object_kind", "equipment", "Оборудование"),
    _seed("object_kind", "component", "Компонент"),
    _seed("object_kind", "cable", "Кабель"),
    _seed("object_kind", "consumable", "Расходный материал"),
    _seed("object_kind", "unknown", "Неизвестно"),
    _seed("equipment_category", "server equipment", "Серверное оборудование"),
    _seed("equipment_category", "network equipment", "Сетевое оборудование"),
    _seed("equipment_category", "storage", "Системы хранения данных"),
    _seed("equipment_category", "SAN", "SAN"),
    _seed("equipment_category", "power/infrastructure", "Электропитание и инфраструктура"),
    _seed("equipment_category", "other", "Прочее"),
    _seed("equipment_type", "server", "Сервер"),
    _seed("equipment_type", "switch", "Коммутатор"),
    _seed("equipment_type", "storage system", "Система хранения данных"),
    _seed("equipment_type", "SAN switch", "SAN-коммутатор"),
    _seed("equipment_type", "load balancer", "Балансировщик нагрузки"),
    _seed("equipment_type", "PDU", "PDU"),
    _seed("equipment_type", "UPS", "ИБП"),
    _seed("equipment_type", "other", "Прочее оборудование"),
    _seed("component_type", "CPU", "Процессор"),
    _seed("component_type", "memory", "Оперативная память"),
    _seed("component_type", "SSD", "SSD"),
    _seed("component_type", "HDD", "HDD"),
    _seed("component_type", "NIC", "Сетевой адаптер"),
    _seed("component_type", "HBA", "HBA-адаптер"),
    _seed("component_type", "RAID controller", "RAID-контроллер"),
    _seed("component_type", "PSU", "Блок питания"),
    _seed("component_type", "fan", "Вентилятор"),
    _seed("component_type", "transceiver", "Трансивер"),
    _seed("component_type", "motherboard", "Материнская плата"),
    _seed("component_type", "other", "Прочий компонент"),
    _seed("cable_type", "UTP", "UTP"),
    _seed("cable_type", "OM4", "OM4"),
    _seed("cable_type", "MTP", "MTP"),
    _seed("cable_type", "AOC", "AOC"),
    _seed("cable_type", "DAC", "DAC"),
    _seed("cable_type", "other", "Прочий кабель"),
    _seed("cable_category", "copper", "Медь"),
    _seed("cable_category", "fiber", "Оптика"),
    _seed("cable_category", "active", "Активный кабель"),
    _seed("cable_category", "unknown", "Неизвестно"),
    _seed("unit_of_measure", "piece", "шт"),
    _seed("unit_of_measure", "metre", "м"),
    _seed("operation_source", "legacy_xlsx_receipt", "Исторический XLSX: приход"),
    _seed("operation_source", "legacy_xlsx_issue", "Исторический XLSX: расход"),
    _seed("operation_source", "manual", "Ручной ввод"),
    _seed("operation_source", "DCIM", "DCIM"),
    _seed("operation_source", "migration", "Миграция"),
)


def iter_domain_definitions() -> Iterator[ReferenceDomain]:
    return iter(DOMAIN_DEFINITIONS)


def iter_seed_values() -> Iterator[ReferenceValue]:
    return iter(REFERENCE_SEEDS)


_PROHIBITED_VENDOR_MERGES = frozenset(
    {
        frozenset(("huawei", "xfusion")),
        frozenset(("hp", "hpe")),
        frozenset(("hunix", "hynix")),
    }
)


def vendor_scoped_model_key(vendor: str, model: str) -> str:
    """Return a stable model identity that cannot collide across vendors."""

    vendor_key = normalize_reference_key(vendor)
    model_key = normalize_reference_key(model)
    if not vendor_key or not model_key:
        raise ValueError("vendor and model are required for a scoped model key")
    return f"{vendor_key}\x1f{model_key}"


def model_identity(vendor: str, model: str) -> ModelIdentity:
    vendor_key = normalize_reference_key(vendor)
    model_key = normalize_reference_key(model)
    return ModelIdentity(
        vendor=clean_reference_display(vendor),
        model=clean_reference_display(model),
        normalized_vendor_key=vendor_key,
        normalized_model_key=model_key,
        scoped_key=vendor_scoped_model_key(vendor, model),
    )


def resolve_alias_safety(
    domain: str,
    source_value: str,
    canonical_value: str,
    *,
    source_vendor: str = "",
    canonical_vendor: str = "",
) -> AliasResolution:
    """Decide whether an alias is a mechanically safe equivalent.

    No fuzzy matching is used.  In particular known vendor near-matches and
    distinct model labels are never auto-approved.
    """

    if domain not in DOMAIN_KEYS:
        raise ValueError(f"unknown reference domain: {domain}")
    source_key = normalize_reference_key(source_value)
    canonical_key = normalize_reference_key(canonical_value)
    if not source_key or not canonical_key:
        return AliasResolution(
            domain, source_value, canonical_value, source_key, canonical_key,
            PENDING_REVIEW, 0.0, True, "EMPTY_VALUE", "Empty aliases cannot be approved.",
        )

    if domain == "vendor" and frozenset((source_key, canonical_key)) in _PROHIBITED_VENDOR_MERGES:
        return AliasResolution(
            domain, source_value, canonical_value, source_key, canonical_key,
            PENDING_REVIEW, 0.0, True, "PROHIBITED_SEMANTIC_MERGE",
            "These vendor names are explicitly independent until manually proven otherwise.",
        )

    if domain == "model":
        if source_key != canonical_key:
            return AliasResolution(
                domain, source_value, canonical_value, source_key, canonical_key,
                PENDING_REVIEW, 0.0, True, "DISTINCT_MODEL",
                "Different model keys must remain separate.",
            )
        source_vendor_key = normalize_reference_key(source_vendor)
        canonical_vendor_key = normalize_reference_key(canonical_vendor)
        if not source_vendor_key or not canonical_vendor_key:
            return AliasResolution(
                domain, source_value, canonical_value, source_key, canonical_key,
                PENDING_REVIEW, 0.5, True, "MODEL_VENDOR_SCOPE_REQUIRED",
                "A model alias requires source and canonical vendor scope.",
            )
        if source_vendor_key != canonical_vendor_key:
            return AliasResolution(
                domain, source_value, canonical_value, source_key, canonical_key,
                PENDING_REVIEW, 0.0, True, "MODEL_VENDOR_CONFLICT",
                "Equal model labels under different vendors are not the same model identity.",
            )

    if source_key == canonical_key:
        return AliasResolution(
            domain, source_value, canonical_value, source_key, canonical_key,
            AUTO_APPROVED, 1.0, False, "SAFE_TEXT_EQUIVALENCE",
            "Values differ only by NFKC, case or safe whitespace normalization.",
        )

    return AliasResolution(
        domain, source_value, canonical_value, source_key, canonical_key,
        PENDING_REVIEW, 0.0, True, "SEMANTIC_REVIEW_REQUIRED",
        "Different normalized keys cannot be merged automatically.",
    )


# Name requested by the CLI integration contract.
alias_resolution = resolve_alias_safety


def build_alias(
    domain: str,
    source_value: str,
    canonical_value: str,
    *,
    canonical_id: int | None = None,
    source_vendor: str = "",
    canonical_vendor: str = "",
    source_file: str = "",
    source_sheet: str = "",
    usage_count: int = 0,
    notes: str = "",
) -> ReferenceAlias:
    resolution = resolve_alias_safety(
        domain,
        source_value,
        canonical_value,
        source_vendor=source_vendor,
        canonical_vendor=canonical_vendor,
    )
    return ReferenceAlias(
        domain=domain,
        source_value=source_value,
        normalized_source_key=resolution.normalized_source_key,
        canonical_id=canonical_id,
        canonical_value=canonical_value,
        source_file=source_file,
        source_sheet=source_sheet,
        usage_count=usage_count,
        confidence=resolution.confidence,
        resolution_status=resolution.resolution_status,
        notes=notes or resolution.reason,
    )


def propose_unknown_reference(
    domain: str,
    source_value: str,
    *,
    source_file: str = "",
    source_sheet: str = "",
    usage_count: int = 0,
) -> ReferenceCandidate:
    """Return review data only; unknown values are never silently activated."""

    if domain not in DOMAIN_KEYS:
        raise ValueError(f"unknown reference domain: {domain}")
    proposed = clean_reference_display(source_value)
    return ReferenceCandidate(
        domain=domain,
        source_value=source_value,
        proposed_value=proposed,
        normalized_key=normalize_reference_key(source_value),
        source_file=source_file,
        source_sheet=source_sheet,
        usage_count=usage_count,
        confidence=0.0,
        resolution_status=CANDIDATE,
        requires_manual_review=True,
        notes="Unknown value requires explicit approval before reference creation.",
    )
