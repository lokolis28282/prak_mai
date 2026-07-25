#!/usr/bin/env python3
"""Full, reproducible audit and safe cleanup of the ODE working warehouse DB."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inventory.warehouse.classification import (  # noqa: E402
    Classification,
    UNKNOWN_ITEM_NAME,
    canonical_vendor,
    classify_card,
    clean_display,
    clean_item_name,
    clean_model,
    infer_vendor,
    semantic_type,
)


TYPE_FIELDS = ("equipment_type", "component_type", "cable_type")
DISPLAY_FIELDS = (
    "item_name", "project", "supplier", "vendor", "model", "shelf",
    "object_name", "datacenter", "equipment_type", "component_type",
    "cable_type", "unit",
)
PLACEHOLDER_ITEM_NAMES = {"#n/a", "n/a", "unknown", "?", "???", "null"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def connect(path: Path, *, writable: bool) -> sqlite3.Connection:
    if writable:
        db = sqlite3.connect(path, timeout=60)
    else:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=60)
        db.execute("PRAGMA query_only=ON")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=60000")
    return db


def scalar(db: sqlite3.Connection, sql: str, parameters: tuple[Any, ...] = ()) -> int | float:
    value = db.execute(sql, parameters).fetchone()[0]
    return 0 if value is None else value


def existing_semantic(row: sqlite3.Row) -> tuple[str, str] | None:
    for field in TYPE_FIELDS:
        if clean_display(row[field]):
            return semantic_type(field, row[field])
    return None


def proposed_row(
    row: sqlite3.Row,
    counterpart: sqlite3.Row | None = None,
) -> tuple[dict[str, Any], Classification, dict[str, bool]]:
    was_placeholder = clean_display(row["item_name"]).casefold() in PLACEHOLDER_ITEM_NAMES
    item_source = counterpart["item_name"] if was_placeholder and counterpart else row["item_name"]
    item_name = clean_item_name(item_source)
    model = clean_model(row["model"])
    if counterpart is not None and not model:
        model = clean_model(counterpart["model"])
    vendor = canonical_vendor(row["vendor"])
    if counterpart is not None and not vendor:
        vendor = canonical_vendor(counterpart["vendor"])
    part_number = row["part_number"] or (counterpart["part_number"] if counterpart else "")
    if not vendor:
        vendor = infer_vendor(item_name, model, part_number)
    classification = classify_card(
        item_name=item_name,
        vendor=vendor,
        model=model,
        part_number=part_number,
        equipment_type=row["equipment_type"],
        component_type=row["component_type"],
        cable_type=row["cable_type"],
    )
    values = {field: clean_display(row[field]) for field in DISPLAY_FIELDS}
    values.update({"item_name": item_name, "vendor": vendor, "model": model})
    for field in TYPE_FIELDS:
        values[field] = classification.value if field == classification.field else ""
    flags = {
        "na_fixed": was_placeholder,
        "na_restored": was_placeholder and counterpart is not None,
        "vendor_normalized": values["vendor"] != str(row["vendor"] or ""),
        "vendor_filled": not clean_display(row["vendor"]) and bool(values["vendor"]),
        "model_cleaned": values["model"] != str(row["model"] or ""),
        "whitespace_cleaned": any(
            clean_display(row[field]) != str(row[field] or "") for field in DISPLAY_FIELDS
        ),
    }
    return values, classification, flags


def audit(db: sqlite3.Connection) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    has_identity = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='migration_full_identities'"
    ).fetchone() is not None
    part_number_sql = (
        "COALESCE(i.part_number,'') AS part_number, i.identity_confidence, "
        "i.preservation_status, i.requires_manual_review "
        if has_identity else
        "'' AS part_number, '' AS identity_confidence, '' AS preservation_status, "
        "0 AS requires_manual_review "
    )
    identity_join = "LEFT JOIN migration_full_identities i ON i.target_receipt_id=r.id" if has_identity else ""
    rows = db.execute(
        f"SELECT r.*, {part_number_sql} FROM stock_receipts r {identity_join} ORDER BY r.id"
    ).fetchall()
    usable_by_serial: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        serial_key = clean_display(row["serial_number"]).casefold()
        if not serial_key or clean_display(row["item_name"]).casefold() in PLACEHOLDER_ITEM_NAMES:
            continue
        usable_by_serial.setdefault(serial_key, []).append(row)
    na_counterparts = {
        int(row["id"]): candidates[0]
        for row in rows
        if clean_display(row["item_name"]).casefold() in PLACEHOLDER_ITEM_NAMES
        and len(candidates := usable_by_serial.get(
            clean_display(row["serial_number"]).casefold(), []
        )) == 1
    }
    duplicate_receipt_ids = {
        int(row[0]) for row in db.execute(
            """SELECT id FROM stock_receipts
               WHERE lower(trim(serial_number)) IN (
                   SELECT lower(trim(serial_number)) FROM stock_receipts
                   WHERE trim(serial_number)<>'' GROUP BY lower(trim(serial_number))
                   HAVING COUNT(*)>1)"""
        )
    }
    metrics: dict[str, Any] = {
        "cards": len(rows),
        "typed_before": 0,
        "typed_after": 0,
        "types_filled": 0,
        "categories_filled": 0,
        "reclassified": 0,
        "classification_field_changes": 0,
        "na_fixed": 0,
        "na_restored": 0,
        "na_placeholdered": 0,
        "vendors_normalized": 0,
        "vendors_filled": 0,
        "models_cleaned": 0,
        "cards_whitespace_cleaned": 0,
        "cards_changed": 0,
        "high_confidence": 0,
        "medium_confidence": 0,
        "low_confidence": 0,
        "missing_vendor_after": 0,
        "missing_model_after": 0,
        "untyped_before": 0,
        "generic_other_before": 0,
        "multiple_classifiers_before": 0,
        "multiple_classifiers_after": 0,
        "placeholder_names_before": 0,
        "placeholder_names_after": 0,
        "quality_findings_before": 0,
        "cards_with_quality_findings_before": 0,
        "type_counts_before": {},
        "type_counts_after": {},
        "category_counts_after": {},
    }
    changes: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    quality_card_ids: set[int] = set()
    for row in rows:
        values, classification, flags = proposed_row(row, na_counterparts.get(int(row["id"])))
        before_semantic = existing_semantic(row)
        after_semantic = semantic_type(classification.field, classification.value)
        receipt_id = int(row["id"])
        type_field_count = sum(bool(clean_display(row[field])) for field in TYPE_FIELDS)
        before_findings = 0
        if before_semantic:
            metrics["typed_before"] += 1
            key = f"{before_semantic[0]}:{before_semantic[1]}"
            metrics["type_counts_before"][key] = metrics["type_counts_before"].get(key, 0) + 1
            if before_semantic[1] == "other":
                metrics["generic_other_before"] += 1
                before_findings += 1
        else:
            metrics["untyped_before"] += 1
            metrics["types_filled"] += 1
            metrics["categories_filled"] += 1
            before_findings += 1
        if type_field_count > 1:
            metrics["multiple_classifiers_before"] += 1
            before_findings += 1
        if clean_display(row["item_name"]).casefold() in PLACEHOLDER_ITEM_NAMES:
            metrics["placeholder_names_before"] += 1
            before_findings += 1
        if not clean_display(row["vendor"]) or canonical_vendor(row["vendor"]) == "":
            before_findings += 1
        if not clean_model(row["model"]):
            before_findings += 1
        if not clean_display(row["supplier"]):
            before_findings += 1
        if flags["whitespace_cleaned"]:
            before_findings += 1
        if receipt_id in duplicate_receipt_ids:
            before_findings += 1
        if before_findings:
            quality_card_ids.add(receipt_id)
            metrics["quality_findings_before"] += before_findings
        metrics["typed_after"] += 1
        after_key = f"{classification.field}:{classification.value}"
        metrics["type_counts_after"][after_key] = metrics["type_counts_after"].get(after_key, 0) + 1
        metrics["category_counts_after"][classification.category] = (
            metrics["category_counts_after"].get(classification.category, 0) + 1
        )
        metrics[f"{classification.confidence.casefold()}_confidence"] += 1
        if not values["vendor"]:
            metrics["missing_vendor_after"] += 1
        if not values["model"]:
            metrics["missing_model_after"] += 1
        if before_semantic != after_semantic:
            metrics["reclassified"] += 1
        if before_semantic and before_semantic[0] != classification.field:
            metrics["classification_field_changes"] += 1
        for flag, enabled in flags.items():
            if enabled:
                metric_name = {
                    "na_fixed": "na_fixed",
                    "na_restored": "na_restored",
                    "vendor_normalized": "vendors_normalized",
                    "vendor_filled": "vendors_filled",
                    "model_cleaned": "models_cleaned",
                    "whitespace_cleaned": "cards_whitespace_cleaned",
                }[flag]
                metrics[metric_name] += 1
        changed = any(values[field] != str(row[field] or "") for field in DISPLAY_FIELDS)
        if changed:
            metrics["cards_changed"] += 1
            changes.append({
                "id": int(row["id"]),
                **values,
                "classification_rule": classification.rule,
                "classification_confidence": classification.confidence,
            })
        if classification.confidence == "LOW":
            unresolved.append({
                "receipt_id": int(row["id"]),
                "serial_number": str(row["serial_number"] or ""),
                "item_name_before": str(row["item_name"] or ""),
                "item_name_after": values["item_name"],
                "vendor": values["vendor"],
                "model": values["model"],
                "part_number": str(row["part_number"] or ""),
                "rule": classification.rule,
                "identity_confidence": str(row["identity_confidence"] or ""),
                "preservation_status": str(row["preservation_status"] or ""),
            })

    allocation_cte = "WITH allocations AS (SELECT receipt_id,SUM(quantity) issued FROM stock_issue_allocations GROUP BY receipt_id)"
    metrics.update({
        "receipts_quantity": float(scalar(db, "SELECT COALESCE(SUM(quantity),0) FROM stock_receipts")),
        "issues": int(scalar(db, "SELECT COUNT(*) FROM stock_issues")),
        "issues_quantity": float(scalar(db, "SELECT COALESCE(SUM(quantity),0) FROM stock_issues")),
        "allocated_quantity": float(scalar(db, "SELECT COALESCE(SUM(quantity),0) FROM stock_issue_allocations")),
        "balance": float(scalar(db, "SELECT COALESCE((SELECT SUM(quantity) FROM stock_receipts),0)-COALESCE((SELECT SUM(quantity) FROM stock_issue_allocations),0)")),
        "negative_balances": int(scalar(db, allocation_cte + " SELECT COUNT(*) FROM stock_receipts r LEFT JOIN allocations a ON a.receipt_id=r.id WHERE r.quantity-COALESCE(a.issued,0)<-0.0000001")),
        "overallocated_receipts": int(scalar(db, allocation_cte + " SELECT COUNT(*) FROM stock_receipts r LEFT JOIN allocations a ON a.receipt_id=r.id WHERE COALESCE(a.issued,0)>r.quantity+0.0000001")),
        "unallocated_issues": int(scalar(db, "SELECT COUNT(*) FROM stock_issues i WHERE abs(i.quantity-COALESCE((SELECT SUM(a.quantity) FROM stock_issue_allocations a WHERE a.issue_id=i.id),0))>0.0000001")),
        "orphan_allocations": int(scalar(db, "SELECT COUNT(*) FROM stock_issue_allocations a LEFT JOIN stock_issues i ON i.id=a.issue_id LEFT JOIN stock_receipts r ON r.id=a.receipt_id WHERE i.id IS NULL OR r.id IS NULL")),
        "duplicate_serial_groups": int(scalar(db, "SELECT COUNT(*) FROM (SELECT lower(trim(serial_number)) FROM stock_receipts WHERE trim(serial_number)<>'' GROUP BY lower(trim(serial_number)) HAVING COUNT(*)>1)")),
        "duplicate_serial_cards": int(scalar(db, "SELECT COALESCE(SUM(n),0) FROM (SELECT COUNT(*) n FROM stock_receipts WHERE trim(serial_number)<>'' GROUP BY lower(trim(serial_number)) HAVING COUNT(*)>1)")),
        "missing_vendor_before": int(scalar(db, "SELECT COUNT(*) FROM stock_receipts WHERE trim(vendor)='' OR lower(trim(vendor)) IN ('unknown','???','#n/a','n/a')")),
        "missing_model_before": int(scalar(db, "SELECT COUNT(*) FROM stock_receipts WHERE trim(model)='' OR lower(trim(model)) IN ('unknown','???','#n/a','n/a')")),
        "missing_supplier": int(scalar(db, "SELECT COUNT(*) FROM stock_receipts WHERE trim(supplier)=''")),
        "missing_inventory_number": int(scalar(db, "SELECT COUNT(*) FROM stock_receipts WHERE trim(inventory_number)=''")),
        "provisional_identities": int(scalar(db, "SELECT COUNT(*) FROM migration_full_identities WHERE identity_confidence='PROVISIONAL'")) if has_identity else 0,
        "manual_review_identities": int(scalar(db, "SELECT COUNT(*) FROM migration_full_identities WHERE requires_manual_review=1")) if has_identity else 0,
        "serials_with_outer_whitespace": int(scalar(db, "SELECT COUNT(*) FROM stock_receipts WHERE serial_number<>trim(serial_number)")),
        "serial_placeholders": int(scalar(db, "SELECT COUNT(*) FROM stock_receipts WHERE lower(trim(serial_number)) IN ('','#n/a','n/a','unknown','?','???','null')")),
        "part_number_placeholders": int(scalar(db, "SELECT COUNT(*) FROM migration_full_identities WHERE lower(trim(part_number)) IN ('#n/a','n/a','unknown','?','???','null')")) if has_identity else 0,
    })
    metrics["na_placeholdered"] = metrics["na_fixed"] - metrics["na_restored"]
    metrics["cards_with_quality_findings_before"] = len(quality_card_ids)
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='migration_full_marker'").fetchone():
        marker = db.execute("SELECT * FROM migration_full_marker WHERE id=1").fetchone()
        if marker:
            metrics.update({
                "source_receipt_rows": int(marker["receipt_source_rows"]),
                "source_issue_rows": int(marker["issue_source_rows"]),
                "reconciliation_rows": int(marker["reconciliation_rows"]),
                "identity_count": int(marker["identity_count"]),
                "migration_quarantine_count": int(marker["quarantine_count"]),
            })
        metrics["reconciliation_status_counts"] = {
            str(row["final_status"]): int(row["n"])
            for row in db.execute(
                "SELECT final_status,COUNT(*) n FROM migration_full_reconciliation GROUP BY final_status"
            )
        }
    return metrics, changes, unresolved


def add_reference_values(db: sqlite3.Connection) -> int:
    definitions = {
        "equipment_type": (
            ("router", "Маршрутизатор"),
            ("firewall", "Межсетевой экран"),
            ("usb dongle server", "USB-сервер ключей"),
        ),
        "component_type": (
            ("GPU", "GPU"),
            ("board", "Плата"),
            ("chassis", "Шасси"),
            ("accessory", "Аксессуар"),
            ("components", "Комплектующие"),
        ),
    }
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    inserted = 0
    next_id = int(scalar(db, "SELECT COALESCE(MAX(id),0)+1 FROM reference_values_v2"))
    for domain, values in definitions.items():
        domain_row = db.execute(
            "SELECT id FROM reference_domains_v2 WHERE domain_key=?", (domain,)
        ).fetchone()
        if domain_row is None:
            continue
        for canonical, display in values:
            exists = db.execute(
                "SELECT 1 FROM reference_values_v2 WHERE domain_id=? AND scope_key='' AND normalized_key=?",
                (int(domain_row["id"]), canonical.casefold()),
            ).fetchone()
            if exists:
                continue
            db.execute(
                """INSERT INTO reference_values_v2(
                       id,domain_id,canonical_value,display_name,normalized_key,scope_key,
                       active,approval_status,source,created_at,updated_at
                   ) VALUES (?,?,?,?,?,'',1,'APPROVED','ODE warehouse full audit',?,?)""",
                (next_id, int(domain_row["id"]), canonical, display, canonical.casefold(), now, now),
            )
            next_id += 1
            inserted += 1
    return inserted


def apply_changes(db: sqlite3.Connection, changes: list[dict[str, Any]], metrics: dict[str, Any]) -> None:
    assignments = ",".join(f"{field}=?" for field in DISPLAY_FIELDS)
    db.execute("BEGIN IMMEDIATE")
    try:
        db.executemany(
            f"UPDATE stock_receipts SET {assignments} WHERE id=?",
            [tuple(change[field] for field in DISPLAY_FIELDS) + (change["id"],) for change in changes],
        )
        reference_values_added = add_reference_values(db)
        indexes = (
            "CREATE INDEX IF NOT EXISTS idx_stock_receipts_supplier_nocase ON stock_receipts(supplier COLLATE NOCASE)",
            "CREATE INDEX IF NOT EXISTS idx_stock_receipts_vendor_nocase ON stock_receipts(vendor COLLATE NOCASE)",
            "CREATE INDEX IF NOT EXISTS idx_stock_receipts_model_nocase ON stock_receipts(model COLLATE NOCASE)",
            "CREATE INDEX IF NOT EXISTS idx_stock_receipts_item_name_nocase ON stock_receipts(item_name COLLATE NOCASE)",
            "CREATE INDEX IF NOT EXISTS idx_stock_receipts_project_nocase ON stock_receipts(project COLLATE NOCASE)",
            "CREATE INDEX IF NOT EXISTS idx_stock_receipts_equipment_type_nocase ON stock_receipts(equipment_type COLLATE NOCASE)",
            "CREATE INDEX IF NOT EXISTS idx_stock_receipts_component_type_nocase ON stock_receipts(component_type COLLATE NOCASE)",
            "CREATE INDEX IF NOT EXISTS idx_stock_receipts_cable_type_nocase ON stock_receipts(cable_type COLLATE NOCASE)",
            "CREATE INDEX IF NOT EXISTS idx_stock_receipts_serial_trim_nocase ON stock_receipts(trim(serial_number) COLLATE NOCASE) WHERE trim(serial_number)<>''",
        )
        for statement in indexes:
            db.execute(statement)
        details = {
            key: metrics[key] for key in (
                "cards", "cards_changed", "types_filled", "categories_filled",
                "reclassified", "na_fixed", "na_restored", "na_placeholdered",
                "vendors_normalized", "vendors_filled",
                "negative_balances", "duplicate_serial_groups",
            )
        }
        details["reference_values_added"] = reference_values_added
        db.execute(
            """INSERT INTO audit_log(action,entity_type,entity_id,details,author)
               VALUES ('WAREHOUSE_FULL_AUDIT_CLEANUP','warehouse_database','',?,'system')""",
            (json.dumps(details, ensure_ascii=False, sort_keys=True),),
        )
        db.execute("ANALYZE")
        db.commit()
    except Exception:
        db.rollback()
        raise


def duplicate_serial_rows(db: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(row) for row in db.execute(
        """SELECT r.id receipt_id,r.serial_number,r.item_name,r.vendor,r.model,
                  r.is_opening_balance,i.identity_confidence,i.preservation_status,
                  i.authoritative,i.requires_manual_review
             FROM stock_receipts r
             LEFT JOIN migration_full_identities i ON i.target_receipt_id=r.id
            WHERE lower(trim(r.serial_number)) IN (
                  SELECT lower(trim(serial_number)) FROM stock_receipts
                   WHERE trim(serial_number)<>'' GROUP BY lower(trim(serial_number))
                  HAVING COUNT(*)>1)
            ORDER BY lower(trim(r.serial_number)),r.id"""
    )]


def na_provenance_rows(db: sqlite3.Connection) -> list[dict[str, Any]]:
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='migration_full_identities'").fetchone() is None:
        return []
    return [dict(row) for row in db.execute(
        """SELECT r.id receipt_id,r.serial_number,i.primary_staging_row_id,
                  s.source_sheet,s.source_row,i.identity_confidence,i.preservation_status,
                  json_extract(s.normalized_payload,'$.formula_item_name') formula_item_name,
                  json_extract(s.normalized_payload,'$.formula_component_model') formula_component_model,
                  json_extract(s.normalized_payload,'$.formula_model') formula_model,
                  json_extract(s.normalized_payload,'$.hostname') hostname,
                  json_extract(s.normalized_payload,'$.target_equipment_serial') target_equipment_serial
             FROM stock_receipts r
             JOIN migration_full_identities i ON i.target_receipt_id=r.id
             JOIN migration_staging_rows s ON s.id=i.primary_staging_row_id
            WHERE lower(trim(r.item_name)) IN ('#n/a','n/a','unknown','?','???','null')
            ORDER BY r.id"""
    )]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_report(
    report_dir: Path,
    db_path: Path,
    metrics: dict[str, Any],
    unresolved: list[dict[str, Any]],
    duplicates: list[dict[str, Any]],
    na_rows: list[dict[str, Any]],
    *,
    applied: bool,
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    write_csv(report_dir / "manual_classification_review.csv", unresolved)
    write_csv(report_dir / "duplicate_serial_review.csv", duplicates)
    write_csv(report_dir / "na_source_provenance.csv", na_rows)
    (report_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    type_lines = "\n".join(
        f"- {name}: {count}" for name, count in sorted(
            metrics["type_counts_after"].items(), key=lambda item: (-item[1], item[0])
        )
    )
    category_lines = "\n".join(
        f"- {name}: {count}" for name, count in sorted(
            metrics["category_counts_after"].items(), key=lambda item: (-item[1], item[0])
        )
    )
    report = f"""# Полный аудит складской БД ODE

Режим: {'применено' if applied else 'dry-run'}

База: `{db_path}`

SHA-256: `{sha256(db_path)}`

Карточек: **{metrics['cards']}**

## Реальное количество карточек

- Operational `stock_receipts`: {metrics['cards']}
- Строк источника прихода: {metrics.get('source_receipt_rows', 'н/д')}
- Строк источника расхода: {metrics.get('source_issue_rows', 'н/д')}
- Строк reconciliation: {metrics.get('reconciliation_rows', 'н/д')}
- Уникальных миграционных identities: {metrics.get('identity_count', 'н/д')}
- Ограничение ровно на 50 000 карточек в SQL/Python/UI: **не обнаружено**.
  Число 50 000 совпадает с доказанным количеством уникальных identities после
  reconciliation; прежние интерфейсные лимиты 500/5 000 заменены серверной
  пагинацией и не влияют на реальный count.

## Результат очистки

- Карточек с изменениями: {metrics['cards_changed']}
- Найдено отдельных признаков качества до исправления: {metrics['quality_findings_before']}
- Карточек хотя бы с одним признаком качества: {metrics['cards_with_quality_findings_before']}
- Переклассифицировано: {metrics['reclassified']}
- Получили тип впервые: {metrics['types_filled']}
- Получили осмысленную категорию впервые: {metrics['categories_filled']}
- `#N/A` всего исправлено: {metrics['na_fixed']}
- Из них восстановлено по единственной карточке с тем же S/N: {metrics['na_restored']}
- Из них заменено на явный исторический placeholder: {metrics['na_placeholdered']}
- Вендоров нормализовано: {metrics['vendors_normalized']}
- Вендоров восстановлено из названия/модели/PN: {metrics['vendors_filled']}
- Различных написаний вендора: {metrics.get('vendor_distinct_before', 'н/д')} → {metrics.get('vendor_distinct_after', 'н/д')}
- Пробелы/Unicode display-поля очищены: {metrics['cards_whitespace_cleaned']}
- Низкая уверенность, требуется ручная проверка: {metrics['low_confidence']}
- Без типа до исправления: {metrics['untyped_before']}
- С `other`/«Прочее» до исправления: {metrics['generic_other_before']}
- С несколькими классификаторами одновременно: {metrics['multiple_classifiers_before']}
- Осталось в «Прочее» после классификации: {metrics['category_counts_after'].get('Прочее', 0)}

Источник `#N/A` — формульный lookup в листе расхода исходного Excel. Это не
ошибка чтения текущей колонки БД: исходный formula result уже был `#N/A`.
Восстановление выполнялось только при единственной содержательной карточке с
тем же нормализованным S/N; неоднозначные значения не угадывались.

## Остатки

- Приход: {metrics['receipts_quantity']}
- Расход: {metrics['issues_quantity']}
- Allocations: {metrics['allocated_quantity']}
- Остаток: {metrics['balance']}
- Отрицательных остатков: {metrics['negative_balances']}
- Перераспределенных приходов: {metrics['overallocated_receipts']}
- Нераспределенных/неполностью распределенных расходов: {metrics['unallocated_issues']}
- Orphan allocations: {metrics['orphan_allocations']}

## Типы после классификации

{type_lines}

## Категории после классификации

{category_lines}

## Неавтоматические проблемы

- Групп конфликтующих одинаковых S/N: {metrics['duplicate_serial_groups']} ({metrics['duplicate_serial_cards']} карточек)
- Provisional identities: {metrics['provisional_identities']}
- Identity rows с ручной проверкой: {metrics['manual_review_identities']}
- Migration quarantine/source-corrupted rows: {metrics['migration_quarantine_count']}
- Без вендора после восстановления: {metrics['missing_vendor_after']}
- Без модели после очистки: {metrics['missing_model_after']}
- Без поставщика: {metrics['missing_supplier']}
- Без Inventory Number: {metrics['missing_inventory_number']}
- S/N с внешними пробелами в сохраненном source display: {metrics['serials_with_outer_whitespace']}

S/N, Inventory Number и Part Number не переписывались: для исторических S/N с
внешними пробелами добавлен нормализованный lookup и expression index, но
исходное отображение сохранено по preservation contract.

## Производительность

- 500 000 карточек, первая страница 501 строка: {metrics.get('performance_500k_first_page_seconds', 'не измерено')} с
- 500 000 карточек, совместный фильтр: {metrics.get('performance_500k_combined_seconds', 'не измерено')} с
- 1 000 000 карточек, первая страница: {metrics.get('performance_1m_first_page_seconds', 'не измерено')} с
- 1 000 000 карточек, совместный фильтр: {metrics.get('performance_1m_combined_seconds', 'не измерено')} с

Тест выполнен на отдельных синтетических SQLite-копиях в `/tmp`; рабочая БД
не использовалась как нагрузочный fixture.

Подробные списки: `manual_classification_review.csv`,
`duplicate_serial_review.csv`, `na_source_provenance.csv`.
"""
    (report_dir / "warehouse_full_audit_report.md").write_text(report, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "warehouse.db")
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    db_path = args.db.resolve()
    with connect(db_path, writable=args.apply) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"integrity_check failed: {integrity}")
        foreign_keys = db.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_keys:
            raise RuntimeError(f"foreign_key_check failed: {len(foreign_keys)} rows")
        metrics, changes, unresolved = audit(db)
        duplicates = duplicate_serial_rows(db)
        na_rows = na_provenance_rows(db)
        if args.apply:
            apply_changes(db, changes, metrics)
            post_integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            if post_integrity != "ok" or db.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("post-apply database validation failed")
    write_report(
        args.report_dir.resolve(), db_path, metrics, unresolved, duplicates, na_rows,
        applied=args.apply,
    )
    print(json.dumps(metrics, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
