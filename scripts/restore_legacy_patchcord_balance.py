#!/usr/bin/env python3
"""Restore only unambiguous UTP/OM4 patchcord opening balances from legacy history.

Dry-run is the default. Applying requires an exact database SHA-256 and an
external manifest path. Serialized equipment, AOC/DAC, MTP/MPO and ambiguous
quantity rows are deliberately outside this correction.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import closing
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any, Sequence
import unicodedata


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from inventory.db import DEFAULT_DB_PATH  # noqa: E402
from scripts.reclassify_warehouse_cards import (  # noqa: E402
    _assert_no_sidecars,
    _validate_database,
    _write_manifest,
    readonly_connection,
    sha256_file,
)


PUBLICATION_DATE = "2026-07-14"
PUBLICATION_ACTION = "LEGACY_PATCHCORD_BASELINE_PUBLISHED"


def _clean(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def classify_patchcord(value: object) -> tuple[str, str] | None:
    text = _clean(value).casefold().replace("патч-корд", "патчкорд").replace("ом4", "om4")
    if "патчкорд" not in text or any(token in text for token in ("mtp", "mpo", "aoc", "dac")):
        return None
    length_match = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*м(?:\b|$)", text)
    if length_match is None:
        return None
    length = length_match.group(1).replace(",", ".") + "м"
    if "utp" in text or "медн" in text:
        return f"Патчкорд UTP {length}", "UTP"
    if "оптич" in text or "om4" in text:
        return f"Патчкорд оптический OM4 {length}", "OM4"
    return None


def build_plan(db: sqlite3.Connection) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"receipt": Decimal(0), "issue": Decimal(0), "source_hashes": []}
    )
    rows = db.execute(
        """SELECT id,operation_kind,source_item_name,canonical_item_name,quantity,
                  source_row_hash
             FROM migration_full_reconciliation
            WHERE final_status='QUANTITY_DEFERRED'
            ORDER BY id"""
    ).fetchall()
    for row in rows:
        identity = classify_patchcord(row["canonical_item_name"] or row["source_item_name"])
        if identity is None:
            continue
        try:
            quantity = Decimal(str(row["quantity"]))
        except (InvalidOperation, ValueError):
            continue
        if not quantity.is_finite() or quantity <= 0:
            continue
        bucket = grouped[identity]
        bucket["receipt" if row["operation_kind"] == "RECEIPT" else "issue"] += quantity
        bucket["source_hashes"].append(str(row["source_row_hash"]))

    plan: list[dict[str, Any]] = []
    for (item_name, cable_type), values in sorted(grouped.items()):
        balance = values["receipt"] - values["issue"]
        if balance <= 0:
            continue
        source_hashes = sorted(values["source_hashes"])
        source_digest = hashlib.sha256("\n".join(source_hashes).encode("ascii")).hexdigest()
        plan.append({
            "item_name": item_name,
            "cable_type": cable_type,
            "quantity": str(balance),
            "receipt_quantity": str(values["receipt"]),
            "issue_quantity": str(values["issue"]),
            "source_row_count": len(source_hashes),
            "source_rows_sha256": source_digest,
            "source_row_hashes": source_hashes,
        })
    return plan


def plan_digest(plan: list[dict[str, Any]]) -> str:
    payload = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def summary(plan: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "positions": len(plan),
        "quantity": str(sum((Decimal(row["quantity"]) for row in plan), Decimal(0))),
        "plan_sha256": plan_digest(plan),
    }


def apply_plan(
    path: Path, *, expected_sha256: str, manifest_path: Path, author: str
) -> dict[str, Any]:
    before_sha = sha256_file(path)
    if before_sha != expected_sha256:
        raise RuntimeError(f"SHA-256 изменился: expected={expected_sha256}, actual={before_sha}")
    _assert_no_sidecars(path)
    with closing(sqlite3.connect(path, timeout=30)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")
        try:
            _validate_database(db)
            if db.execute(
                "SELECT 1 FROM audit_log WHERE action=? LIMIT 1", (PUBLICATION_ACTION,)
            ).fetchone() is not None:
                raise RuntimeError("Patchcord baseline уже опубликован")
            plan = build_plan(db)
            if not plan:
                raise RuntimeError("Нет доказуемых patchcord opening balances")
            approved = {
                str(row[0]) for row in db.execute(
                    """SELECT v.display_name FROM reference_values_v2 v
                       JOIN reference_domains_v2 d ON d.id=v.domain_id
                       WHERE d.domain_key='cable_type' AND v.active=1
                         AND v.approval_status='APPROVED'"""
                )
            }
            if any(row["cable_type"] not in approved for row in plan):
                raise RuntimeError("Target cable type отсутствует в approved справочнике")
            before_count = int(db.execute("SELECT COUNT(*) FROM stock_receipts").fetchone()[0])
            digest = plan_digest(plan)
            for row in plan:
                receipt_id = int(db.execute(
                    """INSERT INTO stock_receipts(
                           receipt_date,responsible,item_name,project,serial_number,
                           inventory_number,supplier,vendor,model,shelf,object_name,
                           datacenter,equipment_type,component_type,cable_type,unit,
                           quantity,is_opening_balance
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
                    (PUBLICATION_DATE, author, row["item_name"], "", "", "",
                     "Исторический учет", "Не указан", "", "", "Склад Ixcellerate",
                     "Ixcellerate", "", "", row["cable_type"], "шт",
                     row["quantity"]),
                ).lastrowid)
                db.execute(
                    """INSERT INTO audit_log(action,entity_type,entity_id,details,author)
                       VALUES('LEGACY_PATCHCORD_OPENING_BALANCE_CREATED','stock_receipt',?,?,?)""",
                    (str(receipt_id), json.dumps({
                        key: value for key, value in row.items() if key != "source_row_hashes"
                    }, ensure_ascii=False, sort_keys=True), author),
                )
            after_count = int(db.execute("SELECT COUNT(*) FROM stock_receipts").fetchone()[0])
            if after_count - before_count != len(plan):
                raise RuntimeError("Неожиданное изменение числа stock_receipts")
            db.execute(
                "INSERT INTO audit_log(action,entity_type,entity_id,details,author) VALUES(?,?,?,?,?)",
                (PUBLICATION_ACTION, "warehouse_database", "", json.dumps({
                    **summary(plan), "source_sha256": before_sha,
                    "publication_date": PUBLICATION_DATE,
                }, ensure_ascii=False, sort_keys=True), author),
            )
            _validate_database(db)
            db.commit()
        except Exception:
            db.rollback()
            raise
    _assert_no_sidecars(path)
    report = {
        "database": str(path.resolve()), "before_sha256": before_sha,
        "after_sha256": sha256_file(path), **summary(plan), "plan": plan,
    }
    _write_manifest(manifest_path, report)
    return report


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    result.add_argument("--apply", action="store_true")
    result.add_argument("--expected-sha256", default="")
    result.add_argument("--manifest", type=Path)
    result.add_argument("--author", default="ODE legacy patchcord balance correction")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    path = args.db.expanduser().resolve()
    if args.apply:
        if not args.expected_sha256 or args.manifest is None:
            raise RuntimeError("--expected-sha256 и --manifest обязательны с --apply")
        report = apply_plan(path, expected_sha256=args.expected_sha256,
                            manifest_path=args.manifest, author=str(args.author))
    else:
        _assert_no_sidecars(path)
        with closing(readonly_connection(path)) as db:
            _validate_database(db)
            plan = build_plan(db)
        report = {"database": str(path), "source_sha256": sha256_file(path),
                  **summary(plan), "plan": plan}
        if args.manifest is not None:
            _write_manifest(args.manifest, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
