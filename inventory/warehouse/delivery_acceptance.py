"""Physical delivery acceptance through WarehouseFacade."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from inventory.shared.audit import write_audit_entry
from inventory.shared.db import connect
from inventory.shared.validators import WarehouseError

from .delivery_repository import DeliveryRepository
from .receipt_imports import ReceiptWriteService


FILL_EMPTY_RECEIPT_FIELDS = {
    "inventory_number", "supplier", "vendor", "model", "project", "datacenter",
    "shelf", "order_number", "request_number", "plu", "item_name",
}

EDITABLE_LINE_FIELDS = {
    "item_name", "model", "vendor", "supplier", "project", "datacenter",
    "shelf", "object_name", "equipment_type", "component_type", "cable_type",
    "asset_number", "inventory_number", "quantity",
}


class DeliveryAcceptanceService:
    def __init__(
        self,
        db_path: str | Path,
        *,
        actor_provider: Any,
        receipt_writer: ReceiptWriteService,
    ):
        self.repository = DeliveryRepository(db_path)
        self.actor_provider = actor_provider
        self.receipt_writer = receipt_writer

    def inspect_delivery_serial(self, delivery_id: int, serial_number: str) -> dict[str, Any]:
        self._require_write()
        serial = self._serial(serial_number)
        with connect(self.repository.db_path) as db:
            delivery = self.repository.get_delivery_in_db(db, int(delivery_id))
            if delivery is None:
                raise WarehouseError("Поставка не найдена")
            line = self.repository.get_line_by_serial_in_db(db, int(delivery_id), serial)
            existing = self.repository.existing_stock_by_serial_in_db(db, serial)
        return self._inspection(delivery, line, existing, serial)

    def accept_delivery_serial(
        self,
        delivery_id: int,
        serial_number: str,
        values: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_write()
        serial = self._serial(serial_number)
        values = dict(values or {})
        actor = self.audit_author()
        with connect(self.repository.db_path) as db:
            delivery = self._delivery_for_update(db, int(delivery_id))
            line = self.repository.get_line_by_serial_in_db(db, int(delivery_id), serial)
            if line is None:
                return {"found": False, "serial_number": serial, "accepted": False}
            existing = self.repository.existing_stock_by_serial_in_db(db, serial)
            result = self._accept_line(db, delivery, line, existing, values, actor)
            result["updated_delivery_status"] = self.repository.refresh_status_in_db(db, int(delivery_id))
            return result

    def accept_unplanned_delivery_serial(
        self,
        delivery_id: int,
        serial_number: str,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        self._require_write()
        serial = self._serial(serial_number)
        clean = self._required_unplanned_values(values)
        actor = self.audit_author()
        with connect(self.repository.db_path) as db:
            delivery = self._delivery_for_update(db, int(delivery_id))
            if self.repository.get_line_by_serial_in_db(db, int(delivery_id), serial):
                raise WarehouseError("S/N уже есть в документе поставки")
            if self.repository.existing_stock_by_serial_in_db(db, serial):
                raise WarehouseError("Этот S/N уже есть на складе")
            clean.setdefault("delivery_number", delivery.get("delivery_number", ""))
            clean.setdefault("supplier", delivery.get("supplier", ""))
            line_id = self.repository.insert_unplanned_line_in_db(db, int(delivery_id), serial, clean, actor)
            line = self.repository.get_line_by_id_in_db(db, int(delivery_id), line_id)
            result = self._accept_line(db, delivery, line or {}, None, clean, actor, unplanned=True)
            result["updated_delivery_status"] = self.repository.refresh_status_in_db(db, int(delivery_id))
            return result

    def accept_delivery_batch(
        self,
        delivery_id: int,
        line_ids: list[int],
        common_values: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_write()
        ids = [int(value) for value in line_ids]
        if not ids:
            raise WarehouseError("Выберите строки для приемки")
        common = dict(common_values or {})
        actor = self.audit_author()
        summary = {
            "accepted_new": 0, "linked_existing": 0, "filled_existing": 0,
            "skipped": 0, "conflicts": [], "errors": [],
        }
        with connect(self.repository.db_path) as db:
            delivery = self._delivery_for_update(db, int(delivery_id))
            for line_id in ids:
                line = self.repository.get_line_by_id_in_db(db, int(delivery_id), line_id)
                if line is None:
                    raise WarehouseError("Строка поставки не найдена")
                serial = self._serial(line.get("serial_number"))
                existing = self.repository.existing_stock_by_serial_in_db(db, serial)
                result = self._accept_line(db, delivery, line, existing, common, actor)
                if result.get("created_receipt"):
                    summary["accepted_new"] += 1
                elif result.get("accepted"):
                    summary["linked_existing"] += 1
                    if result.get("updated_fields"):
                        summary["filled_existing"] += 1
                if result.get("conflicts"):
                    summary["conflicts"].append({"line_id": line_id, "serial_number": serial, "conflicts": result["conflicts"]})
            summary["updated_delivery_status"] = self.repository.refresh_status_in_db(db, int(delivery_id))
            write_audit_entry(
                db,
                action="DELIVERY_ACCEPT_BATCH",
                entity_type="delivery",
                entity_id=int(delivery_id),
                author=actor,
                details={key: value for key, value in summary.items() if key != "conflicts"},
            )
            return summary

    def update_delivery_line_metadata(
        self,
        delivery_id: int,
        line_ids: list[int],
        values: dict[str, Any],
        *,
        only_empty: bool = False,
    ) -> int:
        self._require_write()
        ids = [int(value) for value in line_ids]
        clean = {self._line_field(key): value for key, value in values.items() if self._line_field(key) in EDITABLE_LINE_FIELDS}
        if not ids or not clean:
            raise WarehouseError("Выберите строки и поле для заполнения")
        actor = self.audit_author()
        changed = 0
        with connect(self.repository.db_path) as db:
            for line_id in ids:
                if self.repository.update_line_metadata_in_db(
                    db, int(delivery_id), line_id, clean, actor,
                    only_empty=only_empty, allowed_fields=EDITABLE_LINE_FIELDS,
                ):
                    changed += 1
                    write_audit_entry(
                        db,
                        action="DELIVERY_LINE_UPDATE",
                        entity_type="delivery_line",
                        entity_id=line_id,
                        author=actor,
                        details={"fields": list(clean)},
                    )
        return changed

    def get_delivery_acceptance_summary(self, delivery_id: int) -> dict[str, Any]:
        with connect(self.repository.db_path) as db:
            delivery = self.repository.get_delivery_in_db(db, int(delivery_id))
            if delivery is None:
                raise WarehouseError("Поставка не найдена")
            rows = db.execute(
                """SELECT state, receipt_id FROM delivery_lines WHERE delivery_id=?""",
                (int(delivery_id),),
            ).fetchall()
        total = len(rows)
        accepted = sum(1 for row in rows if row["state"] == "Принято")
        existing = sum(1 for row in rows if row["state"] == "Уже на складе")
        errors = sum(1 for row in rows if row["state"] in {"Ошибка", "Дубль в файле"})
        waiting = sum(1 for row in rows if row["state"] == "Ожидается")
        processed = sum(1 for row in rows if row["state"] == "Принято" or (row["state"] == "Уже на складе" and row["receipt_id"]))
        return {
            "delivery_id": int(delivery_id), "status": delivery["status"],
            "total": total, "accepted": accepted, "existing": existing,
            "errors": errors, "waiting": waiting, "processed": processed,
        }

    def get_delivery_conflicts(self, delivery_id: int) -> list[dict[str, Any]]:
        with connect(self.repository.db_path) as db:
            rows = db.execute(
                """SELECT * FROM delivery_lines
                   WHERE delivery_id=? AND trim(serial_number) <> ''
                   ORDER BY row_number,id""",
                (int(delivery_id),),
            ).fetchall()
            result = []
            for row in rows:
                existing = self.repository.existing_stock_by_serial_in_db(db, row["serial_number"])
                if not existing:
                    continue
                conflicts = self._conflicts(self._receipt_values_from_line(dict(row), {}), existing)
                if conflicts:
                    result.append({"line_id": row["id"], "serial_number": row["serial_number"], "conflicts": conflicts})
            return result

    def refresh_delivery_status(self, delivery_id: int) -> str:
        self._require_write()
        with connect(self.repository.db_path) as db:
            return self.repository.refresh_status_in_db(db, int(delivery_id))

    def _accept_line(
        self,
        db: Any,
        delivery: dict[str, Any],
        line: dict[str, Any],
        existing: dict[str, Any] | None,
        values: dict[str, Any],
        actor: str,
        *,
        unplanned: bool = False,
    ) -> dict[str, Any]:
        if not line:
            raise WarehouseError("Строка поставки не найдена")
        if line.get("state") == "Принято" or line.get("receipt_id"):
            raise WarehouseError("Этот S/N уже принят")
        serial = self._serial(line.get("serial_number"))
        merged = {**line, **{key: value for key, value in values.items() if value not in (None, "")}}
        if existing:
            fill_values = self._receipt_values_from_line(merged, delivery)
            fill = self.receipt_writer.repository.fill_empty_fields_in_transaction(
                db,
                int(existing["id"]),
                fill_values,
                allowed_fields=FILL_EMPTY_RECEIPT_FIELDS,
            )
            self.repository.link_line_in_db(
                db, int(line["id"]), int(existing["id"]), actor,
                state="Уже на складе", error_text="S/N уже есть на складе",
            )
            write_audit_entry(
                db,
                action="DELIVERY_ACCEPT_EXISTING",
                entity_type="delivery_line",
                entity_id=int(line["id"]),
                author=actor,
                details={
                    "delivery_id": delivery["id"], "serial_number": serial,
                    "receipt_id": existing["id"], "updated_fields": list(fill["updated_fields"]),
                    "conflicts": fill["conflicts"],
                },
            )
            return {
                "found": True, "accepted": True, "created_receipt": False,
                "receipt_id": int(existing["id"]), "line_id": int(line["id"]),
                "updated_fields": fill["updated_fields"], "conflicts": fill["conflicts"],
            }
        receipt = self._receipt_values_from_line(merged, delivery)
        prepared = self.receipt_writer.prepare_receipt(receipt, soft=True)
        receipt_id = self.receipt_writer.repository.insert_one_in_transaction(
            db,
            prepared,
            author=actor,
            collect_refs=True,
        )
        self.repository.link_line_in_db(db, int(line["id"]), receipt_id, actor, state="Принято")
        write_audit_entry(
            db,
            action="DELIVERY_ACCEPT_UNPLANNED" if unplanned else "DELIVERY_ACCEPT",
            entity_type="delivery_line",
            entity_id=int(line["id"]),
            author=actor,
            details={
                "delivery_id": delivery["id"], "serial_number": serial,
                "receipt_id": receipt_id, "unplanned": bool(unplanned or line.get("is_unplanned")),
            },
        )
        return {
            "found": True, "accepted": True, "created_receipt": True,
            "receipt_id": receipt_id, "line_id": int(line["id"]),
        }

    def _inspection(
        self,
        delivery: dict[str, Any],
        line: dict[str, Any] | None,
        existing: dict[str, Any] | None,
        serial: str,
    ) -> dict[str, Any]:
        receipt_values = self._receipt_values_from_line(line or {"serial_number": serial}, delivery)
        missing = [field for field in ("item_name", "supplier", "vendor", "datacenter", "shelf") if not str(receipt_values.get(field) or "").strip()]
        conflicts = self._conflicts(receipt_values, existing) if existing else {}
        already = bool(line and (line.get("state") == "Принято" or line.get("receipt_id")))
        actions: list[str] = []
        if already:
            actions.append("blocked_already_accepted")
        elif line and existing:
            actions.append("fill_empty_existing")
            if conflicts:
                actions.append("require_override_confirmation")
        elif line:
            actions.append("accept_new")
        else:
            actions.extend(["accept_unplanned", "skip"])
        return {
            "found_in_delivery": line is not None,
            "delivery_line_id": line.get("id") if line else None,
            "current_line_state": line.get("state") if line else "",
            "already_accepted": already,
            "exists_in_warehouse": existing is not None,
            "existing_receipt_id": existing.get("id") if existing else None,
            "serial_number": serial,
            "item_name": receipt_values.get("item_name", ""),
            "vendor": receipt_values.get("vendor", ""),
            "model": receipt_values.get("model", ""),
            "inventory_number": receipt_values.get("inventory_number", ""),
            "supplier": receipt_values.get("supplier", ""),
            "project": receipt_values.get("project", ""),
            "datacenter": receipt_values.get("datacenter", ""),
            "shelf": receipt_values.get("shelf", ""),
            "type": receipt_values.get("equipment_type") or receipt_values.get("component_type") or receipt_values.get("cable_type") or "",
            "missing_fields": missing,
            "conflicting_fields": conflicts,
            "allowed_actions": actions,
        }

    def _receipt_values_from_line(self, line: dict[str, Any], delivery: dict[str, Any]) -> dict[str, Any]:
        item_type = line.get("equipment_type") or line.get("component_type") or line.get("equipment_unit") or "Не указан"
        return {
            "receipt_date": date.today().isoformat(),
            "responsible": self.audit_author(),
            "order_date": line.get("order_date", ""),
            "request_number": line.get("request_number", ""),
            "order_number": line.get("order_number", ""),
            "plu": line.get("plu", ""),
            "item_name": line.get("item_name") or line.get("equipment_unit") or item_type,
            "project": line.get("project", ""),
            "serial_number": line.get("serial_number", ""),
            "inventory_number": line.get("inventory_number") or line.get("asset_number", ""),
            "supplier": line.get("supplier") or delivery.get("supplier") or "Не указан",
            "vendor": line.get("vendor") or "Не указан",
            "model": line.get("model", ""),
            "shelf": line.get("shelf", ""),
            "object_name": line.get("object_name") or line.get("accounting_object") or "Не указано",
            "datacenter": line.get("datacenter") or "Ixcellerate",
            "equipment_type": line.get("equipment_type") or (item_type if not line.get("component_type") else ""),
            "component_type": line.get("component_type", ""),
            "cable_type": line.get("cable_type", ""),
            "unit": line.get("unit") or "шт",
            "quantity": 1,
        }

    @staticmethod
    def _conflicts(incoming: dict[str, Any], existing: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
        if not existing:
            return {}
        conflicts: dict[str, dict[str, Any]] = {}
        for field in FILL_EMPTY_RECEIPT_FIELDS:
            old = str(existing.get(field) or "").strip()
            new = str(incoming.get(field) or "").strip()
            if old and new and old.casefold() != new.casefold():
                conflicts[field] = {"current": old, "incoming": new}
        return conflicts

    def _delivery_for_update(self, db: Any, delivery_id: int) -> dict[str, Any]:
        delivery = self.repository.get_delivery_in_db(db, delivery_id)
        if delivery is None or delivery["status"] == "Закрыта":
            raise WarehouseError("Поставка не найдена или уже закрыта")
        return delivery

    def _required_unplanned_values(self, values: dict[str, Any]) -> dict[str, Any]:
        row = dict(values or {})
        row["quantity"] = 1
        for field, label in (
            ("supplier", "поставщик"), ("vendor", "вендор"), ("datacenter", "ЦОД"),
            ("shelf", "стеллаж/полка"), ("project", "проект"),
        ):
            if not str(row.get(field) or "").strip():
                raise WarehouseError(f"Поле «{label}» не может быть пустым")
        if not (str(row.get("equipment_type") or "").strip() or str(row.get("component_type") or "").strip()):
            if str(row.get("item_type") or "").strip():
                row["equipment_type"] = row["item_type"]
            else:
                raise WarehouseError("Укажите тип оборудования или компонента")
        if not str(row.get("item_name") or "").strip():
            row["item_name"] = " ".join(
                part for part in (row.get("equipment_type") or row.get("component_type"), row.get("vendor"), row.get("model"))
                if str(part or "").strip()
            ) or "Позиция поставки"
        row.setdefault("object_name", "Не указано")
        row.setdefault("unit", "шт")
        return row

    @staticmethod
    def _line_field(field: str) -> str:
        return "asset_number" if field == "inventory_number" else field

    def audit_author(self) -> str:
        return self.receipt_writer.audit_author()

    def _require_write(self) -> dict[str, Any]:
        user = self.actor_provider.current_user()
        if user.get("role") not in {"admin", "engineer"}:
            raise WarehouseError("Недостаточно прав для выполнения операции")
        return user

    @staticmethod
    def _serial(value: Any) -> str:
        serial = str(value or "").strip().upper()
        if not serial:
            raise WarehouseError("Поле «S/N» не может быть пустым")
        return serial
