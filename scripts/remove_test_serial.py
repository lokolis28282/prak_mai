#!/usr/bin/env python3
"""Remove one proven manual-test receipt from the working warehouse database.

The correction is deliberately tied to receipt 1050001 and exact S/N ``1``.
It refuses to run unless the migration/provenance links are absent, the known
manual audit trail is present, and the supplied pre-delete backups are healthy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "warehouse.db"
EXPECTED_RECEIPT_ID = 1_050_001
EXPECTED_SERIAL = "1"
TEST_AUDIT_IDS = (146634, 146635, 146636, 146637, 146638)
TEST_REFERENCE_IDS = (714096, 714098, 714101, 714103)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def serial_digest(db: sqlite3.Connection, *, exclude_test: bool) -> tuple[int, str]:
    digest = hashlib.sha256()
    count = 0
    sql = "SELECT id,serial_number FROM stock_receipts"
    params: tuple[object, ...] = ()
    if exclude_test:
        sql += " WHERE NOT (id=? AND serial_number=?)"
        params = (EXPECTED_RECEIPT_ID, EXPECTED_SERIAL)
    sql += " ORDER BY id"
    for receipt_id, serial in db.execute(sql, params):
        value = str(serial or "").encode("utf-8")
        digest.update(
            str(int(receipt_id)).encode("ascii")
            + b":" + str(len(value)).encode("ascii") + b":" + value + b"\n"
        )
        count += 1
    return count, digest.hexdigest()


def scalar(db: sqlite3.Connection, sql: str, params: tuple[object, ...] = ()) -> int:
    return int(db.execute(sql, params).fetchone()[0])


def verify_backup(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise RuntimeError(f"backup is missing: {path}")
    uri = f"file:{path.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as backup:
        integrity = str(backup.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = list(backup.execute("PRAGMA foreign_key_check"))
        candidate_count = scalar(
            backup,
            "SELECT COUNT(*) FROM stock_receipts WHERE id=? AND serial_number=?",
            (EXPECTED_RECEIPT_ID, EXPECTED_SERIAL),
        )
        receipts = scalar(backup, "SELECT COUNT(*) FROM stock_receipts")
    if integrity != "ok" or foreign_keys or candidate_count != 1:
        raise RuntimeError(f"invalid pre-delete backup: {path}")
    return {
        "path": str(path.resolve()), "sha256": sha256(path),
        "integrity": integrity, "foreign_key_rows": 0,
        "stock_receipts": receipts, "exact_candidate": candidate_count,
    }


def prove_candidate(db: sqlite3.Connection) -> dict[str, object]:
    row = db.execute(
        """SELECT id,receipt_date,responsible,item_name,project,serial_number,
                  supplier,vendor,model,shelf,object_name,datacenter,created_at
           FROM stock_receipts WHERE id=? AND serial_number=?""",
        (EXPECTED_RECEIPT_ID, EXPECTED_SERIAL),
    ).fetchone()
    if row is None:
        raise RuntimeError("exact correction candidate is absent")
    expected = {
        "receipt_date": "2026-07-14", "responsible": "Мерненко Александр Николаевич",
        "item_name": "Сервер Dell PowerEdge R650", "project": "digital",
        "supplier": "IT Global", "vendor": "Dell", "model": "PowerEdge R650",
        "shelf": "1-2", "object_name": "Склад", "datacenter": "Ixcellerate",
        "created_at": "2026-07-14 20:28:22",
    }
    names = (
        "id", "receipt_date", "responsible", "item_name", "project", "serial_number",
        "supplier", "vendor", "model", "shelf", "object_name", "datacenter", "created_at",
    )
    candidate = dict(zip(names, row))
    mismatches = {key: (candidate[key], value) for key, value in expected.items() if candidate[key] != value}
    if mismatches:
        raise RuntimeError(f"candidate no longer matches reviewed evidence: {mismatches}")

    checks = {
        "allocations": scalar(db, "SELECT COUNT(*) FROM stock_issue_allocations WHERE receipt_id=?", (EXPECTED_RECEIPT_ID,)),
        "delivery_links": scalar(db, "SELECT COUNT(*) FROM delivery_lines WHERE receipt_id=?", (EXPECTED_RECEIPT_ID,)),
        "migration_identities": scalar(db, "SELECT COUNT(*) FROM migration_full_identities WHERE target_receipt_id=?", (EXPECTED_RECEIPT_ID,)),
        "migration_reconciliation_links": scalar(db, "SELECT COUNT(*) FROM migration_full_reconciliation WHERE target_receipt_id=?", (EXPECTED_RECEIPT_ID,)),
        "migration_reconciliation_source": scalar(db, "SELECT COUNT(*) FROM migration_full_reconciliation WHERE source_serial_value=? OR display_serial_value=?", (EXPECTED_SERIAL, EXPECTED_SERIAL)),
        "migration_serial_cells": scalar(db, "SELECT COUNT(*) FROM migration_serial_cells WHERE source_serial_value=? OR raw_xml_value=?", (EXPECTED_SERIAL, EXPECTED_SERIAL)),
        "migration_staging": scalar(db, "SELECT COUNT(*) FROM migration_staging_rows WHERE source_serial_value=? OR normalized_matching_serial=?", (EXPECTED_SERIAL, EXPECTED_SERIAL)),
        "legacy_equipment": scalar(db, "SELECT COUNT(*) FROM equipment WHERE serial_number=?", (EXPECTED_SERIAL,)),
        "legacy_operations": scalar(db, "SELECT COUNT(*) FROM operations WHERE equipment_id IN (SELECT id FROM equipment WHERE serial_number=?)", (EXPECTED_SERIAL,)),
    }
    nonzero = {key: value for key, value in checks.items() if value}
    if nonzero:
        raise RuntimeError(f"candidate has operational or migration provenance: {nonzero}")

    audit_rows = scalar(
        db,
        f"SELECT COUNT(*) FROM audit_log WHERE id IN ({','.join('?' for _ in TEST_AUDIT_IDS)})",
        TEST_AUDIT_IDS,
    )
    reference_rows = scalar(
        db,
        f"SELECT COUNT(*) FROM reference_values WHERE id IN ({','.join('?' for _ in TEST_REFERENCE_IDS)}) AND created_at='2026-07-14 20:28:22'",
        TEST_REFERENCE_IDS,
    )
    if audit_rows != len(TEST_AUDIT_IDS) or reference_rows != len(TEST_REFERENCE_IDS):
        raise RuntimeError("reviewed manual audit/reference trail no longer matches")
    return {"candidate": candidate, "zero_link_checks": checks}


def correct(db_path: Path, byte_backup: Path, sqlite_backup: Path, expected_sha: str) -> dict[str, object]:
    backups = [verify_backup(byte_backup), verify_backup(sqlite_backup)]
    actual_sha = sha256(db_path)
    if actual_sha != expected_sha:
        raise RuntimeError(f"working DB SHA changed: expected {expected_sha}, got {actual_sha}")

    db = sqlite3.connect(db_path)
    try:
        db.execute("PRAGMA foreign_keys=ON")
        proof = prove_candidate(db)
        before_counts = tuple(db.execute(
            "SELECT (SELECT COUNT(*) FROM stock_receipts),(SELECT COUNT(*) FROM stock_issues),(SELECT COUNT(*) FROM stock_issue_allocations),(SELECT COUNT(*) FROM migration_full_identities)"
        ).fetchone())
        retained_before = serial_digest(db, exclude_test=True)
        similar_before = scalar(db, "SELECT COUNT(*) FROM stock_receipts WHERE serial_number<>? AND serial_number LIKE '%1%'", (EXPECTED_SERIAL,))

        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("DELETE FROM stock_receipts WHERE id=? AND serial_number=?", (EXPECTED_RECEIPT_ID, EXPECTED_SERIAL))
            if db.total_changes < 1:
                raise RuntimeError("exact candidate was not deleted")
            db.execute(
                f"DELETE FROM audit_log WHERE id IN ({','.join('?' for _ in TEST_AUDIT_IDS)})",
                TEST_AUDIT_IDS,
            )
            db.execute(
                f"DELETE FROM reference_values WHERE id IN ({','.join('?' for _ in TEST_REFERENCE_IDS)})",
                TEST_REFERENCE_IDS,
            )
            details = {
                "reason": "Proven manual-test receipt created after full migration promotion",
                "exact_serial": EXPECTED_SERIAL,
                "removed_receipt_id": EXPECTED_RECEIPT_ID,
                "removed_audit_ids": list(TEST_AUDIT_IDS),
                "removed_legacy_reference_ids": list(TEST_REFERENCE_IDS),
                "pre_delete_backups": backups,
                "evidence": proof,
            }
            db.execute(
                """INSERT INTO audit_log(action,entity_type,entity_id,details,author)
                   VALUES ('TEST_DATA_REMOVED_AFTER_MANUAL_REVIEW','stock_receipt',?,?,?)""",
                (str(EXPECTED_RECEIPT_ID), json.dumps(details, ensure_ascii=False, sort_keys=True), "ODE Warehouse Stabilization"),
            )
            if scalar(db, "SELECT COUNT(*) FROM stock_receipts WHERE serial_number=?", (EXPECTED_SERIAL,)) != 0:
                raise RuntimeError("exact S/N remains after correction")
            if list(db.execute("PRAGMA foreign_key_check")):
                raise RuntimeError("foreign key failure inside correction transaction")
            db.commit()
        except Exception:
            db.rollback()
            raise

        after_counts = tuple(db.execute(
            "SELECT (SELECT COUNT(*) FROM stock_receipts),(SELECT COUNT(*) FROM stock_issues),(SELECT COUNT(*) FROM stock_issue_allocations),(SELECT COUNT(*) FROM migration_full_identities)"
        ).fetchone())
        retained_after = serial_digest(db, exclude_test=False)
        similar_after = scalar(db, "SELECT COUNT(*) FROM stock_receipts WHERE serial_number LIKE '%1%'", ())
        if retained_before != retained_after or similar_before != similar_after:
            raise RuntimeError("retained serial character digest/count changed")
        if after_counts != (before_counts[0] - 1, before_counts[1], before_counts[2], before_counts[3]):
            raise RuntimeError(f"unexpected operational count change: {before_counts} -> {after_counts}")
        integrity = str(db.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = list(db.execute("PRAGMA foreign_key_check"))
        if integrity != "ok" or foreign_keys:
            raise RuntimeError("post-correction database health check failed")
        correction = db.execute(
            "SELECT id,event_date,action,entity_type,entity_id,author FROM audit_log WHERE action='TEST_DATA_REMOVED_AFTER_MANUAL_REVIEW' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return {
            "before_sha256": actual_sha,
            "after_sha256": sha256(db_path),
            "backups": backups,
            "before_counts": before_counts,
            "after_counts": after_counts,
            "retained_serial_digest": retained_after,
            "similar_serials_preserved": similar_after,
            "integrity_check": integrity,
            "foreign_key_rows": len(foreign_keys),
            "exact_serial_remaining": scalar(db, "SELECT COUNT(*) FROM stock_receipts WHERE serial_number=?", (EXPECTED_SERIAL,)),
            "correction_audit": correction,
        }
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--byte-backup", type=Path, required=True)
    parser.add_argument("--sqlite-backup", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(correct(args.db, args.byte_backup, args.sqlite_backup, args.expected_sha256), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
