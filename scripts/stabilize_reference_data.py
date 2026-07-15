#!/usr/bin/env python3
"""Idempotent canonical Reference Data stabilization for the promoted warehouse DB.

This script never updates operational tables.  It only changes the existing
reference_*_v2 tables and appends an audit event.  Historical spellings remain
available in stock_receipts and migration provenance.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inventory.migration.reference_data import normalize_reference_key


DEFAULT_DB = ROOT / "data" / "warehouse.db"
PLACEHOLDERS = {"", "?", "???", "n/a", "#n/a", "unknown", "null"}
REQUIRED_VENDORS = {
    "AIC", "APC", "Aquarius", "AVAGO", "AVAYA", "Broadcom", "Brocade",
    "Check Point Software", "Cisco", "Citrix", "Dell", "FIBO", "Finisar",
    "HPE", "Huawei", "Hynix", "IBM", "Intel", "ITPOD", "Juniper",
    "Kingston", "Kioxia", "Lenovo", "Mellanox", "Micron", "Modultech",
    "Nerpa", "NetApp", "Netwell", "NIO Electronics", "NTSS", "NVIDIA",
    "Palo Alto", "Radware", "Ruijie Networks", "Samsung", "Seagate", "SEH",
    "Solidigm", "Supermicro", "UPNET", "Vegman", "Western Digital",
    "xFusion", "YADRO", "ДатаРу",
}
VENDOR_CANONICAL = {
    normalize_reference_key(value): value for value in REQUIRED_VENDORS
}
VENDOR_CANONICAL.update({
    "dell": "Dell", "huawei": "Huawei", "xfusion": "xFusion",
    "hpe": "HPE", "cisco": "Cisco", "juniper": "Juniper",
    "micron": "Micron", "brocade": "Brocade", "solidigm": "Solidigm",
    "nvidia": "NVIDIA", "netwell": "Netwell", "modultech": "Modultech",
})
SUPPLIER_GARBAGE_PREFIXES = ("взято из ",)
MODEL_GARBAGE = {"добавить название", "указать имя хоста", "n/a", "?", "unknown"}


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def serial_digest(db: sqlite3.Connection) -> tuple[int, str]:
    digest = hashlib.sha256()
    count = 0
    for row in db.execute("SELECT id,serial_number FROM stock_receipts ORDER BY id"):
        value = str(row[1] or "").encode("utf-8")
        digest.update(str(int(row[0])).encode("ascii") + b":" + str(len(value)).encode("ascii") + b":" + value + b"\n")
        count += 1
    return count, digest.hexdigest()


def domain_id(db: sqlite3.Connection, key: str) -> int:
    row = db.execute("SELECT id FROM reference_domains_v2 WHERE domain_key=?", (key,)).fetchone()
    if row is None:
        raise RuntimeError(f"missing reference domain: {key}")
    return int(row[0])


def ensure_domain(db: sqlite3.Connection, key: str, label: str, description: str) -> int:
    row = db.execute("SELECT id FROM reference_domains_v2 WHERE domain_key=?", (key,)).fetchone()
    if row is not None:
        return int(row[0])
    next_id = int(db.execute("SELECT COALESCE(MAX(id),0)+1 FROM reference_domains_v2").fetchone()[0])
    stamp = now()
    db.execute(
        """INSERT INTO reference_domains_v2(
               id,domain_key,display_name,description,active,source,created_at,updated_at
           ) VALUES (?,?,?,?,1,'Warehouse Stabilization',?,?)""",
        (next_id, key, label, description, stamp, stamp),
    )
    return next_id


def upsert_value(
    db: sqlite3.Connection,
    domain: str,
    value: str,
    *,
    scope: str = "",
    active: bool = True,
    status: str = "APPROVED",
    source: str = "Warehouse Stabilization approved reference",
) -> int:
    did = domain_id(db, domain)
    key = normalize_reference_key(value)
    row = db.execute(
        "SELECT id FROM reference_values_v2 WHERE domain_id=? AND scope_key=? AND normalized_key=?",
        (did, scope, key),
    ).fetchone()
    stamp = now()
    if row is None:
        next_id = int(db.execute("SELECT COALESCE(MAX(id),0)+1 FROM reference_values_v2").fetchone()[0])
        db.execute(
            """INSERT INTO reference_values_v2(
                   id,domain_id,canonical_value,display_name,normalized_key,scope_key,
                   active,approval_status,source,created_at,updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (next_id, did, value, value, key, scope, int(active), status, source, stamp, stamp),
        )
        return next_id
    reference_id = int(row[0])
    db.execute(
        """UPDATE reference_values_v2
           SET canonical_value=?,display_name=?,active=?,approval_status=?,source=?,updated_at=?
           WHERE id=?""",
        (value, value, int(active), status, source, stamp, reference_id),
    )
    return reference_id


def reject_values(db: sqlite3.Connection, domain: str, predicate) -> list[str]:
    did = domain_id(db, domain)
    rows = db.execute(
        "SELECT id,display_name FROM reference_values_v2 WHERE domain_id=?", (did,)
    ).fetchall()
    rejected = []
    for reference_id, value in rows:
        if predicate(str(value)):
            db.execute(
                """UPDATE reference_values_v2
                   SET active=0,approval_status='REJECTED',updated_at=? WHERE id=?""",
                (now(), int(reference_id)),
            )
            rejected.append(str(value))
    return rejected


def add_alias(
    db: sqlite3.Connection,
    domain: str,
    source_value: str,
    canonical_id: int,
    usage: int,
    *,
    status: str,
    notes: str,
) -> None:
    did = domain_id(db, domain)
    row = db.execute(
        """SELECT id FROM reference_aliases_v2
           WHERE domain_id=? AND source_value=? AND canonical_id=?
             AND source_file='Warehouse Stabilization' AND source_sheet='Reference audit'""",
        (did, source_value, canonical_id),
    ).fetchone()
    values = (
        normalize_reference_key(source_value), usage,
        "HIGH" if status == "APPROVED" else "MEDIUM", status,
        "Warehouse Stabilization" if status == "APPROVED" else "", now() if status == "APPROVED" else "", notes,
    )
    if row is None:
        next_id = int(db.execute("SELECT COALESCE(MAX(id),0)+1 FROM reference_aliases_v2").fetchone()[0])
        db.execute(
            """INSERT INTO reference_aliases_v2(
                   id,domain_id,source_value,normalized_source_key,canonical_id,
                   source_file,source_sheet,usage_count,confidence,resolution_status,
                   approved_by,approved_at,notes
               ) VALUES (?,?,?,?,?,'Warehouse Stabilization','Reference audit',?,?,?,?,?,?)""",
            (next_id, did, source_value, values[0], canonical_id, *values[1:]),
        )
    else:
        db.execute(
            """UPDATE reference_aliases_v2 SET normalized_source_key=?,usage_count=?,
                   confidence=?,resolution_status=?,approved_by=?,approved_at=?,notes=? WHERE id=?""",
            (*values, int(row[0])),
        )


def usage(db: sqlite3.Connection, column: str, value: str) -> int:
    if column not in {"supplier", "vendor", "shelf"}:
        raise ValueError(column)
    return int(db.execute(
        f"SELECT COUNT(*) FROM stock_receipts WHERE {column}=? COLLATE NOCASE", (value,)
    ).fetchone()[0])


def stabilize(db: sqlite3.Connection) -> dict[str, object]:
    before_serial_count, before_serial_digest = serial_digest(db)
    before_operational = tuple(db.execute(
        """SELECT (SELECT COUNT(*) FROM stock_receipts),
                  (SELECT COUNT(*) FROM stock_issues),
                  (SELECT COUNT(*) FROM stock_issue_allocations)"""
    ).fetchone())

    ensure_domain(db, "project", "Проекты", "Warehouse project; not equipment identity.")
    ensure_domain(db, "storage_zone", "Зоны хранения", "Named warehouse zone.")
    ensure_domain(db, "rack", "Стеллажи", "Rack or shelving unit.")
    ensure_domain(db, "shelf", "Полки", "Approved shelf values only.")

    datacenter_id = upsert_value(db, "datacenter", "Ixcellerate")
    db.execute(
        """UPDATE reference_values_v2 SET active=0,approval_status='REJECTED',updated_at=?
           WHERE domain_id=? AND id<>?""",
        (now(), domain_id(db, "datacenter"), datacenter_id),
    )

    location_id = upsert_value(db, "warehouse_location", "Склад Ixcellerate")
    zone_id = upsert_value(db, "storage_zone", "Выгородка 1")
    shelf_values = [
        str(row[0]) for row in db.execute(
            "SELECT DISTINCT trim(shelf) FROM stock_receipts WHERE trim(shelf)<>'' ORDER BY trim(shelf)"
        ) if re.fullmatch(r"[1-9]\d*-[1-9]\d*", str(row[0]))
    ]
    for value in shelf_values:
        upsert_value(db, "shelf", value)
    excluded_shelves = [
        str(row[0]) for row in db.execute(
            "SELECT DISTINCT shelf FROM stock_receipts WHERE trim(shelf)<>'' ORDER BY shelf COLLATE NOCASE"
        ) if str(row[0]).strip() not in shelf_values
    ]
    for alias in ("выгородка 1", "Выгородка 1"):
        add_alias(db, "storage_zone", alias, zone_id, usage(db, "shelf", alias),
                  status="APPROVED", notes="Safe case/whitespace alias; stored as zone, not shelf")
    add_alias(db, "storage_zone", "Выгородка1", zone_id, usage(db, "shelf", "Выгородка1"),
              status="PENDING", notes="Missing-space variant requires explicit review")
    reject_values(db, "warehouse_location", lambda value: value.casefold() == "лорпач")

    supplier_values = [
        str(row[0]).strip() for row in db.execute(
            "SELECT DISTINCT supplier FROM stock_receipts ORDER BY supplier COLLATE NOCASE"
        )
    ]
    excluded_suppliers = sorted({
        value for value in supplier_values
        if value.casefold() in PLACEHOLDERS
        or any(value.casefold().startswith(prefix) for prefix in SUPPLIER_GARBAGE_PREFIXES)
    }, key=str.casefold)
    supplier_ids: dict[str, int] = {}
    unspecified_id = upsert_value(db, "supplier", "Не указан")
    supplier_ids[normalize_reference_key("Не указан")] = unspecified_id
    for value in supplier_values:
        if value in excluded_suppliers or not value:
            continue
        supplier_ids[normalize_reference_key(value)] = upsert_value(db, "supplier", value)
    reject_values(
        db, "supplier",
        lambda value: value.casefold() in PLACEHOLDERS
        or any(value.casefold().startswith(prefix) for prefix in SUPPLIER_GARBAGE_PREFIXES),
    )
    supplier_aliases = (
        ("БИГ КОМПЬЮТЕРС", "БИГ-Компьютерс"),
        ("Тела-Телеком", "ТЕЛА ТЕЛЕКОМ"),
        ("ПАО ВЫМПЕЛКОМ", 'ПАО "ВЫМПЕЛКОМ"'),
    )
    for alias, canonical in supplier_aliases:
        target = supplier_ids.get(normalize_reference_key(canonical))
        if target:
            db.execute("UPDATE reference_values_v2 SET active=0 WHERE domain_id=? AND normalized_key=?",
                       (domain_id(db, "supplier"), normalize_reference_key(alias)))
            add_alias(db, "supplier", alias, target, usage(db, "supplier", alias),
                      status="PENDING", notes="Punctuation/legal spelling proposal; admin review required")

    vendor_ids: dict[str, int] = {}
    for key, canonical in sorted(VENDOR_CANONICAL.items()):
        vendor_ids[key] = upsert_value(db, "vendor", canonical)
    did_vendor = domain_id(db, "vendor")
    placeholders = ",".join("?" for _ in vendor_ids)
    db.execute(
        f"""UPDATE reference_values_v2 SET active=0,updated_at=?
            WHERE domain_id=? AND normalized_key NOT IN ({placeholders})""",
        (now(), did_vendor, *vendor_ids),
    )
    rejected_vendors = reject_values(
        db, "vendor", lambda value: value.casefold() in PLACEHOLDERS
    )
    vendor_aliases = (
        ("CeckPoint", "Check Point Software"), ("Check Point", "Check Point Software"),
        ("INTEL CORPORATION", "Intel"), ("KIOXIA CORPORATION", "Kioxia"),
        ("Ruijie", "Ruijie Networks"), ("DATARU", "ДатаРу"),
    )
    for alias, canonical in vendor_aliases:
        target = vendor_ids[normalize_reference_key(canonical)]
        add_alias(db, "vendor", alias, target, usage(db, "vendor", alias),
                  status="PENDING", notes="Semantic vendor alias proposal; admin review required")

    did_model = domain_id(db, "model")
    active_vendor_keys = set(vendor_ids)
    db.execute(
        "UPDATE reference_values_v2 SET active=0,updated_at=? WHERE domain_id=?",
        (now(), did_model),
    )
    for model_id, display, scope in db.execute(
        "SELECT id,display_name,scope_key FROM reference_values_v2 WHERE domain_id=?", (did_model,)
    ).fetchall():
        normalized_model = normalize_reference_key(str(display))
        if str(scope) in active_vendor_keys and normalized_model not in MODEL_GARBAGE:
            # A source value explicitly saying xFusion cannot be offered under Huawei.
            if str(scope) == "huawei" and "xfusion" in normalized_model:
                continue
            db.execute(
                """UPDATE reference_values_v2
                   SET active=1,approval_status='APPROVED',updated_at=? WHERE id=?""",
                (now(), int(model_id)),
            )
    upsert_value(db, "model", "PowerEdge R650", scope="dell")
    upsert_value(db, "model", "R200", scope="vegman")
    upsert_value(db, "model", "R220", scope="vegman")
    upsert_value(db, "model", "2288H", scope="xfusion")

    for project in (
        str(row[0]).strip() for row in db.execute(
            "SELECT DISTINCT project FROM stock_receipts WHERE trim(project)<>'' ORDER BY project COLLATE NOCASE"
        )
    ):
        if project.casefold() not in PLACEHOLDERS:
            upsert_value(db, "project", project)

    after_serial_count, after_serial_digest = serial_digest(db)
    after_operational = tuple(db.execute(
        """SELECT (SELECT COUNT(*) FROM stock_receipts),
                  (SELECT COUNT(*) FROM stock_issues),
                  (SELECT COUNT(*) FROM stock_issue_allocations)"""
    ).fetchone())
    if (before_serial_count, before_serial_digest, before_operational) != (
        after_serial_count, after_serial_digest, after_operational
    ):
        raise RuntimeError("operational/SN preservation invariant failed")

    summary = {
        "active_datacenter": ["Ixcellerate"],
        "warehouse_location_id": location_id,
        "active_shelves": shelf_values,
        "excluded_shelves": excluded_shelves,
        "excluded_suppliers": excluded_suppliers,
        "rejected_vendors": rejected_vendors,
        "serial_count": before_serial_count,
        "serial_digest": before_serial_digest,
        "operational_counts": list(before_operational),
    }
    db.execute(
        """INSERT INTO audit_log(action,entity_type,entity_id,details,author)
           VALUES ('REFERENCE_DATA_STABILIZED','reference_data','v2',?,
                   'Warehouse Stabilization')""",
        (json.dumps(summary, ensure_ascii=False, sort_keys=True),),
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--expected-sha256", default="")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not args.db.is_file():
        parser.error(f"database not found: {args.db}")
    if args.expected_sha256:
        actual = hashlib.sha256(args.db.read_bytes()).hexdigest()
        if actual != args.expected_sha256:
            parser.error(f"database SHA256 changed: {actual}")
    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        db.execute("BEGIN IMMEDIATE")
        summary = stabilize(db)
        foreign_keys = db.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_keys:
            raise RuntimeError(f"foreign_key_check failed: {foreign_keys[:5]}")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    text = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
