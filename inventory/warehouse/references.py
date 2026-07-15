"""Canonical Warehouse reference-data repository and workflows.

The promoted warehouse database owns the ``reference_*_v2`` tables.  Legacy
test databases still use ``reference_values``; the fallback is deliberately
read-only from the v2 point of view and keeps older tests/startup paths usable.
Operational text columns are evidence/provenance and are never rewritten by
reference rename, deactivate or merge operations.
"""

from __future__ import annotations

from datetime import datetime
import json
import sqlite3
from typing import Any, Iterable

from inventory.db import connect
from inventory.shared.reference_normalization import (
    clean_reference_display,
    normalize_reference_key,
)
from inventory.shared.audit import write_audit
from inventory.shared.validators import WarehouseError


FORM_DOMAIN_MAP = {
    "item_name": "catalog_item",
    "model": "model",
    "supplier": "supplier",
    "vendor": "vendor",
    "shelf": "shelf",
    "object": "warehouse_location",
    "datacenter": "datacenter",
    "project": "project",
    "equipment_type": "equipment_type",
    "component_type": "component_type",
    "cable_type": "cable_type",
    "unit": "unit_of_measure",
    "task_source": "operation_source",
    "issue_reason": "issue_reason",
}

EDITOR_DOMAIN_ORDER = (
    "equipment_category", "equipment_type", "equipment_role", "component_type",
    "cable_type", "vendor", "model", "supplier", "datacenter",
    "warehouse_location", "storage_zone", "rack", "shelf", "unit_of_measure",
    "project", "operation_source", "issue_reason",
)

USAGE_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "catalog_item": (("stock_receipts", "item_name"), ("delivery_lines", "item_name")),
    "supplier": (("stock_receipts", "supplier"), ("deliveries", "supplier"), ("delivery_lines", "supplier")),
    "vendor": (("stock_receipts", "vendor"), ("delivery_lines", "vendor")),
    "model": (("stock_receipts", "model"), ("delivery_lines", "model")),
    "datacenter": (("stock_receipts", "datacenter"), ("delivery_lines", "datacenter")),
    "warehouse_location": (("stock_receipts", "object_name"), ("delivery_lines", "object_name")),
    "shelf": (("stock_receipts", "shelf"), ("delivery_lines", "shelf")),
    "project": (("stock_receipts", "project"), ("delivery_lines", "project")),
    "equipment_type": (("stock_receipts", "equipment_type"), ("delivery_lines", "equipment_type")),
    "component_type": (("stock_receipts", "component_type"), ("delivery_lines", "component_type")),
    "cable_type": (("stock_receipts", "cable_type"), ("delivery_lines", "cable_type")),
    "unit_of_measure": (("stock_receipts", "unit"), ("delivery_lines", "unit")),
}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class ReferenceDataService:
    """Single runtime boundary for canonical reference data."""

    def __init__(self, actor_provider: Any):
        self.actor = actor_provider
        self.db_path = actor_provider.db_path

    @staticmethod
    def has_v2(db: sqlite3.Connection) -> bool:
        return int(db.execute(
            """SELECT COUNT(*) FROM sqlite_master
               WHERE type='table' AND name IN (
                 'reference_domains_v2','reference_values_v2','reference_aliases_v2'
               )"""
        ).fetchone()[0]) == 3

    @staticmethod
    def _domain_for_kind(kind: str) -> str:
        return FORM_DOMAIN_MAP.get(kind, "")

    def form_references(
        self, kind: str = "", *, active_only: bool = True
    ) -> list[dict[str, Any]]:
        with connect(self.db_path) as db:
            if not self.has_v2(db):
                return self._legacy_references(db, kind, active_only)
            if kind and kind not in self.actor.REFERENCE_KINDS:
                raise WarehouseError("Неизвестный справочник")
            kinds = [kind] if kind else list(self.actor.REFERENCE_KINDS)
            result: list[dict[str, Any]] = []
            for legacy_kind in kinds:
                domain = self._domain_for_kind(legacy_kind)
                if not domain:
                    result.extend(self._legacy_references(db, legacy_kind, active_only))
                    continue
                rows = db.execute(
                    """SELECT v.id, v.display_name, v.active, v.approval_status,
                              v.scope_key, d.domain_key
                       FROM reference_values_v2 v
                       JOIN reference_domains_v2 d ON d.id=v.domain_id
                       WHERE d.domain_key=? AND d.active=1
                         AND (?=0 OR (v.active=1 AND v.approval_status='APPROVED'))
                       ORDER BY v.display_name COLLATE NOCASE, v.id""",
                    (domain, 1 if active_only else 0),
                ).fetchall()
                for row in rows:
                    result.append({
                        "id": int(row["id"]),
                        "kind": legacy_kind,
                        "name": str(row["display_name"]),
                        "is_active": bool(row["active"]),
                        "approval_status": str(row["approval_status"]),
                        "domain_key": str(row["domain_key"]),
                        "parent_key": str(row["scope_key"] or ""),
                    })
            return result

    @staticmethod
    def _legacy_references(
        db: sqlite3.Connection, kind: str, active_only: bool
    ) -> list[dict[str, Any]]:
        sql = "SELECT id,kind,name,is_active FROM reference_values WHERE 1=1"
        params: list[Any] = []
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        if active_only:
            sql += " AND is_active=1"
        sql += " ORDER BY kind,is_active DESC,name COLLATE NOCASE"
        return [dict(row) for row in db.execute(sql, params)]

    def form_reference_sets(self, db: sqlite3.Connection) -> dict[str, set[str]]:
        if not self.has_v2(db):
            result: dict[str, set[str]] = {}
            for row in db.execute("SELECT kind,name FROM reference_values WHERE is_active=1"):
                result.setdefault(str(row["kind"]), set()).add(str(row["name"]).casefold())
            return result
        result: dict[str, set[str]] = {}
        for kind, domain in FORM_DOMAIN_MAP.items():
            result[kind] = {
                str(row[0]).casefold()
                for row in db.execute(
                    """SELECT v.display_name FROM reference_values_v2 v
                       JOIN reference_domains_v2 d ON d.id=v.domain_id
                       WHERE d.domain_key=? AND d.active=1 AND v.active=1
                         AND v.approval_status='APPROVED'""",
                    (domain,),
                )
            }
        # Report/task domains remain legacy until those separately owned modules migrate.
        for row in db.execute(
            "SELECT kind,name FROM reference_values WHERE is_active=1 AND kind IN ('task_type','work_log_status')"
        ):
            result.setdefault(str(row["kind"]), set()).add(str(row["name"]).casefold())
        return result

    def collect_pending(
        self,
        db: sqlite3.Connection,
        row: dict[str, Any],
        fields: dict[str, str],
    ) -> None:
        """Record unknown operational values as inactive proposals, never canonical."""
        if not self.has_v2(db):
            return
        for field, kind in fields.items():
            value = clean_reference_display(str(row.get(field, "")))
            domain = self._domain_for_kind(kind)
            if not value or not domain or value.casefold() in {"?", "n/a", "#n/a", "unknown", "null"}:
                continue
            domain_row = db.execute(
                "SELECT id FROM reference_domains_v2 WHERE domain_key=? AND active=1", (domain,)
            ).fetchone()
            if domain_row is None:
                continue
            scope = normalize_reference_key(str(row.get("vendor", ""))) if domain == "model" else ""
            cursor = db.execute(
                """INSERT OR IGNORE INTO reference_values_v2(
                       domain_id,canonical_value,display_name,normalized_key,scope_key,
                       active,approval_status,source,created_at,updated_at
                   ) VALUES (?,?,?,?,?,0,'CANDIDATE','Warehouse operational proposal',?,?)""",
                (int(domain_row["id"]), value, value, normalize_reference_key(value),
                 scope, _now(), _now()),
            )
            if cursor.rowcount:
                write_audit(self.actor, db, "REFERENCE_PROPOSAL_CREATE", "reference_value_v2",
                            int(cursor.lastrowid), {"domain": domain, "value": value,
                                                    "source": "warehouse operation"})

    def models_for_vendor(self, vendor: str) -> list[dict[str, Any]]:
        vendor_key = normalize_reference_key(vendor)
        with connect(self.db_path) as db:
            if not self.has_v2(db):
                return self._legacy_references(db, "model", True)
            return [
                {"id": int(row["id"]), "name": str(row["display_name"]), "vendor": vendor}
                for row in db.execute(
                    """SELECT v.id,v.display_name FROM reference_values_v2 v
                       JOIN reference_domains_v2 d ON d.id=v.domain_id
                       WHERE d.domain_key='model' AND v.scope_key=?
                         AND v.active=1 AND v.approval_status='APPROVED'
                       ORDER BY v.display_name COLLATE NOCASE""",
                    (vendor_key,),
                )
            ]

    def editor_catalog(self) -> dict[str, Any]:
        self.actor._require_role("admin")
        with connect(self.db_path) as db:
            if not self.has_v2(db):
                raise WarehouseError("Canonical Reference Data недоступны в этой базе")
            domains = [dict(row) for row in db.execute(
                """SELECT id,domain_key,display_name,description,active,source,created_at,updated_at
                   FROM reference_domains_v2
                   WHERE domain_key IN (%s)
                   ORDER BY CASE domain_key %s ELSE 999 END""" % (
                       ",".join("?" for _ in EDITOR_DOMAIN_ORDER),
                       " ".join(f"WHEN ? THEN {index}" for index, _ in enumerate(EDITOR_DOMAIN_ORDER)),
                   ),
                (*EDITOR_DOMAIN_ORDER, *EDITOR_DOMAIN_ORDER),
            )]
            values = [dict(row) for row in db.execute(
                """SELECT v.id,d.domain_key,v.canonical_value,v.display_name,
                          v.normalized_key,v.scope_key,v.active,v.approval_status,
                          v.source,v.created_at,v.updated_at,
                          COALESCE((SELECT a.author FROM audit_log a
                            WHERE a.entity_type='reference_value_v2'
                              AND a.entity_id=CAST(v.id AS TEXT)
                            ORDER BY a.id DESC LIMIT 1),'system') author,
                          (SELECT COUNT(*) FROM reference_aliases_v2 a
                            WHERE a.canonical_id=v.id) alias_count,
                          (SELECT COUNT(*) FROM reference_aliases_v2 a
                            WHERE a.canonical_id=v.id AND a.resolution_status='PENDING') warning_count
                   FROM reference_values_v2 v
                   JOIN reference_domains_v2 d ON d.id=v.domain_id
                   WHERE d.domain_key IN (%s)
                   ORDER BY d.domain_key,v.active DESC,v.display_name COLLATE NOCASE"""
                % ",".join("?" for _ in EDITOR_DOMAIN_ORDER),
                EDITOR_DOMAIN_ORDER,
            )]
            aliases = [dict(row) for row in db.execute(
                """SELECT a.*,d.domain_key,v.display_name canonical_value
                   FROM reference_aliases_v2 a
                   JOIN reference_domains_v2 d ON d.id=a.domain_id
                   JOIN reference_values_v2 v ON v.id=a.canonical_id
                   WHERE d.domain_key IN (%s)
                   ORDER BY d.domain_key,a.source_value COLLATE NOCASE"""
                % ",".join("?" for _ in EDITOR_DOMAIN_ORDER),
                EDITOR_DOMAIN_ORDER,
            )]
            for value in values:
                value["usage"] = self._usage(db, value["domain_key"], value["display_name"])
            return {"domains": domains, "values": values, "aliases": aliases}

    @staticmethod
    def _usage(db: sqlite3.Connection, domain: str, value: str) -> dict[str, int]:
        result: dict[str, int] = {}
        for table, column in USAGE_COLUMNS.get(domain, ()):
            result[table] = int(db.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {column}=? COLLATE NOCASE", (value,)
            ).fetchone()[0])
        result["operational_rows"] = sum(result.values())
        if domain in USAGE_COLUMNS:
            result["cards"] = int(db.execute(
                """SELECT COUNT(*) FROM stock_receipts
                   WHERE serial_number<>'' AND %s=? COLLATE NOCASE"""
                % dict(USAGE_COLUMNS[domain]).get("stock_receipts", "item_name"),
                (value,),
            ).fetchone()[0]) if any(t == "stock_receipts" for t, _ in USAGE_COLUMNS[domain]) else 0
        else:
            result["cards"] = 0
        return result

    def add_proposal(self, domain: str, value: str, *, parent: str = "") -> int:
        actor = self.actor._require_write()
        value = clean_reference_display(value)
        if not value:
            raise WarehouseError("Значение справочника не может быть пустым")
        if value.casefold() in {"?", "n/a", "#n/a", "unknown", "null"}:
            raise WarehouseError("Технический placeholder нельзя добавить в справочник")
        with connect(self.db_path) as db:
            domain_row = db.execute(
                "SELECT id FROM reference_domains_v2 WHERE domain_key=? AND active=1", (domain,)
            ).fetchone()
            if domain_row is None:
                raise WarehouseError("Неизвестный справочник")
            scope = normalize_reference_key(parent) if domain == "model" else ""
            try:
                cursor = db.execute(
                    """INSERT INTO reference_values_v2(
                           domain_id,canonical_value,display_name,normalized_key,scope_key,
                           active,approval_status,source,created_at,updated_at
                       ) VALUES (?,?,?,?,?,0,'CANDIDATE',?,?,?)""",
                    (int(domain_row["id"]), value, value, normalize_reference_key(value),
                     scope, "ODE controlled UI proposal", _now(), _now()),
                )
            except sqlite3.IntegrityError as error:
                raise WarehouseError("Такое значение уже существует или ожидает проверки") from error
            reference_id = int(cursor.lastrowid)
            write_audit(self.actor, db, "REFERENCE_PROPOSAL_CREATE", "reference_value_v2",
                        reference_id, {"domain": domain, "value": value, "parent": parent,
                                       "actor_id": actor["id"]})
            return reference_id

    def set_active(self, reference_id: int, is_active: bool) -> None:
        self.actor._require_role("admin")
        with connect(self.db_path) as db:
            row = db.execute(
                """SELECT v.id,v.display_name,d.domain_key FROM reference_values_v2 v
                   JOIN reference_domains_v2 d ON d.id=v.domain_id WHERE v.id=?""",
                (reference_id,),
            ).fetchone()
            if row is None:
                raise WarehouseError("Значение справочника не найдено")
            db.execute(
                """UPDATE reference_values_v2 SET active=?,approval_status='APPROVED',updated_at=?
                   WHERE id=?""",
                (1 if is_active else 0, _now(), reference_id),
            )
            write_audit(self.actor, db, "REFERENCE_ACTIVATE" if is_active else "REFERENCE_DEACTIVATE",
                        "reference_value_v2", reference_id,
                        {"domain": row["domain_key"], "value": row["display_name"]})

    def rename(self, reference_id: int, display_name: str) -> None:
        self.actor._require_role("admin")
        display_name = clean_reference_display(display_name)
        if not display_name:
            raise WarehouseError("Новое название не может быть пустым")
        with connect(self.db_path) as db:
            row = db.execute("SELECT * FROM reference_values_v2 WHERE id=?", (reference_id,)).fetchone()
            if row is None:
                raise WarehouseError("Значение справочника не найдено")
            try:
                db.execute(
                    """UPDATE reference_values_v2
                       SET canonical_value=?,display_name=?,normalized_key=?,updated_at=? WHERE id=?""",
                    (display_name, display_name, normalize_reference_key(display_name), _now(), reference_id),
                )
            except sqlite3.IntegrityError as error:
                raise WarehouseError("Значение с таким названием уже существует") from error
            write_audit(self.actor, db, "REFERENCE_RENAME", "reference_value_v2", reference_id,
                        {"before": row["display_name"], "after": display_name,
                         "operational_values_preserved": True})

    def merge_preview(self, source_id: int, target_id: int) -> dict[str, Any]:
        self.actor._require_role("admin")
        with connect(self.db_path) as db:
            source, target = self._merge_rows(db, source_id, target_id)
            usage = self._usage(db, str(source["domain_key"]), str(source["display_name"]))
            aliases = [dict(row) for row in db.execute(
                "SELECT * FROM reference_aliases_v2 WHERE canonical_id=? ORDER BY id", (source_id,)
            )]
            return {
                "source": dict(source), "target": dict(target), "usage": usage,
                "aliases": aliases, "conflict_risk": "LOW" if not aliases else "REVIEW",
                "operational_values_preserved": True,
            }

    def merge(self, source_id: int, target_id: int) -> dict[str, Any]:
        self.actor._require_role("admin")
        with connect(self.db_path) as db:
            source, target = self._merge_rows(db, source_id, target_id)
            preview = {
                "usage": self._usage(db, str(source["domain_key"]), str(source["display_name"])),
                "operational_values_preserved": True,
            }
            db.execute("UPDATE reference_values_v2 SET active=0,updated_at=? WHERE id=?", (_now(), source_id))
            db.execute(
                """INSERT OR IGNORE INTO reference_aliases_v2(
                       domain_id,source_value,normalized_source_key,canonical_id,
                       source_file,source_sheet,usage_count,confidence,resolution_status,
                       approved_by,approved_at,notes
                   ) VALUES (?,?,?,?, 'ODE UI','Reference editor',?,'HIGH','APPROVED',?,?,?)""",
                (int(source["domain_id"]), str(source["display_name"]),
                 normalize_reference_key(str(source["display_name"])), target_id,
                 int(preview["usage"]["operational_rows"]),
                 str(self.actor.current_user()["email"]), _now(),
                 "Canonical merge; operational raw values preserved"),
            )
            db.execute("UPDATE reference_aliases_v2 SET canonical_id=? WHERE canonical_id=?", (target_id, source_id))
            write_audit(self.actor, db, "REFERENCE_MERGE", "reference_value_v2", source_id,
                        {"target_id": target_id, **preview})
            return preview

    @staticmethod
    def _merge_rows(
        db: sqlite3.Connection, source_id: int, target_id: int
    ) -> tuple[sqlite3.Row, sqlite3.Row]:
        if source_id == target_id:
            raise WarehouseError("Нельзя объединить значение с самим собой")
        sql = """SELECT v.*,d.domain_key FROM reference_values_v2 v
                 JOIN reference_domains_v2 d ON d.id=v.domain_id WHERE v.id=?"""
        source = db.execute(sql, (source_id,)).fetchone()
        target = db.execute(sql, (target_id,)).fetchone()
        if source is None or target is None:
            raise WarehouseError("Значение справочника не найдено")
        if source["domain_id"] != target["domain_id"] or source["scope_key"] != target["scope_key"]:
            raise WarehouseError("Объединять можно только значения одного домена и parent scope")
        return source, target
