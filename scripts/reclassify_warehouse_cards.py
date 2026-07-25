#!/usr/bin/env python3
"""Audit and safely correct warehouse type fields from descriptive evidence.

The command never changes identifiers, quantities, receipts, issues or
allocations.  Dry-run is the default.  Production application requires an
exact pre-run SHA-256 and writes one audit event per corrected card plus an
external JSON manifest.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from inventory.db import DEFAULT_DB_PATH  # noqa: E402
from inventory.warehouse.classification import (  # noqa: E402
    Classification,
    classify_card,
    semantic_type,
)


TYPE_FIELDS = ("equipment_type", "component_type", "cable_type")
ALLOWED_CONFIDENCE = {"HIGH"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def readonly_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _current_type(row: sqlite3.Row) -> tuple[str, str]:
    for field in TYPE_FIELDS:
        value = str(row[field] or "").strip()
        if value:
            return field, value
    return "component_type", ""


def _source_item_names(db: sqlite3.Connection, receipt_id: int) -> list[str]:
    rows = db.execute(
        """SELECT details FROM audit_log
            WHERE action IN (
                    'MIGRATION_RECEIPT_IMPORTED',
                    'MIGRATION_SOURCE_ROW_LINKED',
                    'MIGRATION_CONFLICT_RECORDED'
                  )
              AND entity_type='stock_receipt' AND entity_id=?
            ORDER BY id""",
        (str(receipt_id),),
    ).fetchall()
    names: list[str] = []
    for row in rows:
        try:
            details = json.loads(str(row["details"] or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        name = str(details.get("source_item_name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _source_item_name(db: sqlite3.Connection, receipt_id: int) -> str:
    names = _source_item_names(db, receipt_id)
    return names[-1] if names else ""


def _provenance_classification(
    db: sqlite3.Connection,
    row: sqlite3.Row,
) -> Classification | None:
    """Use audit evidence only when every classifiable source name agrees.

    This is intentionally limited to generic/unknown cards.  It never guesses
    from identifiers and never lets one migration row override conflicting
    preserved source descriptions.
    """

    current_field, current_value = _current_type(row)
    generic_current = (
        current_value in {"", "Комплектующие", "Прочий компонент"}
        or str(row["item_name"] or "").startswith("Историческая позиция")
    )
    if not generic_current:
        return None
    inferred: list[Classification] = []
    for source_name in _source_item_names(db, int(row["id"])):
        proposed = classify_card(
            item_name=source_name,
            vendor=row["vendor"],
            model=row["model"],
        )
        if proposed.confidence == "HIGH":
            inferred.append(proposed)
    identities = {(item.field, item.value) for item in inferred}
    if len(identities) != 1:
        return None
    field, value = identities.pop()
    rules = sorted({item.rule for item in inferred})
    return Classification(
        field=field,
        value=value,
        confidence="HIGH",
        rule="PROVENANCE_" + "+".join(rules),
    )


def _provenance_display_correction(
    db: sqlite3.Connection,
    row: sqlite3.Row,
    proposed_field: str,
    proposed_value: str,
) -> tuple[str, str]:
    """Repair cable display fields only when proven by preserved source audit."""

    item_name = str(row["item_name"] or "")
    model = str(row["model"] or "")
    if proposed_field != "cable_type" or proposed_value not in {"DAC", "AOC"}:
        return item_name, model
    source_name = _source_item_name(db, int(row["id"]))
    if not source_name.casefold().startswith(f"{proposed_value.casefold()}-кабел"):
        return item_name, model
    display = re.sub(r"\s+p/n\s*:.*$", "", source_name, flags=re.IGNORECASE).strip()
    match = re.match(
        rf"^{re.escape(proposed_value)}-кабель\s+\S+\s+(.+)$",
        display,
        flags=re.IGNORECASE,
    )
    if match is None:
        return item_name, model
    return display, match.group(1).strip()


def build_plan(db: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = db.execute(
        """SELECT id,item_name,vendor,model,
                  equipment_type,component_type,cable_type
             FROM stock_receipts ORDER BY id"""
    ).fetchall()
    changes: list[dict[str, Any]] = []
    for row in rows:
        current_field, current_value = _current_type(row)
        proposed = classify_card(
            item_name=row["item_name"],
            vendor=row["vendor"],
            model=row["model"],
            equipment_type=row["equipment_type"],
            component_type=row["component_type"],
            cable_type=row["cable_type"],
        )
        provenance = _provenance_classification(db, row)
        if provenance is not None:
            proposed = provenance
        if proposed.confidence not in ALLOWED_CONFIDENCE:
            continue
        new_item_name, new_model = _provenance_display_correction(
            db, row, proposed.field, proposed.value
        )
        type_changed = semantic_type(current_field, current_value) != semantic_type(
            proposed.field, proposed.value
        )
        display_changed = (
            new_item_name != str(row["item_name"] or "")
            or new_model != str(row["model"] or "")
        )
        if not type_changed and not display_changed:
            continue
        new_types = {field: "" for field in TYPE_FIELDS}
        new_types[proposed.field] = proposed.value
        changes.append({
            "receipt_id": int(row["id"]),
            "item_name_before": str(row["item_name"] or ""),
            "item_name_after": new_item_name,
            "model_before": str(row["model"] or ""),
            "model_after": new_model,
            "type_before": {field: str(row[field] or "") for field in TYPE_FIELDS},
            "type_after": new_types,
            "rule": proposed.rule,
            "confidence": proposed.confidence,
        })
    return changes


def plan_digest(changes: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        changes, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def summarize(changes: list[dict[str, Any]]) -> dict[str, Any]:
    transitions = Counter(
        (
            next((f"{key}={value}" for key, value in change["type_before"].items() if value), "untyped"),
            next((f"{key}={value}" for key, value in change["type_after"].items() if value), "untyped"),
            str(change["rule"]),
        )
        for change in changes
    )
    return {
        "changed_cards": len(changes),
        "display_corrections": sum(
            change["item_name_before"] != change["item_name_after"]
            or change["model_before"] != change["model_after"]
            for change in changes
        ),
        "plan_sha256": plan_digest(changes),
        "transitions": [
            {"before": before, "after": after, "rule": rule, "count": count}
            for (before, after, rule), count in sorted(
                transitions.items(), key=lambda item: (-item[1], item[0])
            )
        ],
    }


def _assert_no_sidecars(path: Path) -> None:
    sidecars = [Path(str(path) + suffix) for suffix in ("-wal", "-shm", "-journal")]
    existing = [str(item) for item in sidecars if item.exists()]
    if existing:
        raise RuntimeError(f"SQLite sidecars должны отсутствовать: {existing}")


def _validate_database(db: sqlite3.Connection) -> None:
    integrity = str(db.execute("PRAGMA integrity_check").fetchone()[0])
    if integrity != "ok":
        raise RuntimeError(f"integrity_check: {integrity}")
    foreign_keys = db.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_keys:
        raise RuntimeError(f"foreign_key_check: {foreign_keys[:10]}")


def _assert_approved_targets(
    db: sqlite3.Connection, changes: list[dict[str, Any]]
) -> None:
    approved = {
        (str(row["domain_key"]), str(row["display_name"]))
        for row in db.execute(
            """SELECT d.domain_key,v.display_name
                 FROM reference_domains_v2 d
                 JOIN reference_values_v2 v ON v.domain_id=d.id
                WHERE v.active=1 AND v.approval_status='APPROVED'"""
        )
    }
    for change in changes:
        for field, value in change["type_after"].items():
            if value and (field, value) not in approved:
                raise RuntimeError(f"Неутвержденный target type: {field}={value}")


def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise RuntimeError("Manifest должен находиться вне repository")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=resolved.name + ".", suffix=".tmp", dir=resolved.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary_name, resolved)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def apply_plan(
    path: Path,
    *,
    expected_sha256: str,
    manifest_path: Path,
    author: str,
) -> dict[str, Any]:
    before_sha = sha256_file(path)
    if before_sha != expected_sha256:
        raise RuntimeError(
            f"SHA-256 изменился: expected={expected_sha256}, actual={before_sha}"
        )
    _assert_no_sidecars(path)
    with closing(sqlite3.connect(path, timeout=30)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 30000")
        db.execute("BEGIN IMMEDIATE")
        try:
            _validate_database(db)
            before_count = int(db.execute("SELECT COUNT(*) FROM stock_receipts").fetchone()[0])
            changes = build_plan(db)
            _assert_approved_targets(db, changes)
            digest = plan_digest(changes)
            for change in changes:
                after = change["type_after"]
                db.execute(
                    """UPDATE stock_receipts
                          SET item_name=?,model=?,equipment_type=?,component_type=?,cable_type=?
                        WHERE id=?""",
                    (
                        change["item_name_after"], change["model_after"],
                        after["equipment_type"], after["component_type"],
                        after["cable_type"], change["receipt_id"],
                    ),
                )
                details = {
                    "before": change["type_before"],
                    "after": change["type_after"],
                    "rule": change["rule"],
                    "confidence": change["confidence"],
                }
                if (
                    change["item_name_before"] != change["item_name_after"]
                    or change["model_before"] != change["model_after"]
                ):
                    details["display_before"] = {
                        "item_name": change["item_name_before"],
                        "model": change["model_before"],
                    }
                    details["display_after"] = {
                        "item_name": change["item_name_after"],
                        "model": change["model_after"],
                    }
                db.execute(
                    """INSERT INTO audit_log(action,entity_type,entity_id,details,author)
                       VALUES('WAREHOUSE_CARD_RECLASSIFIED','stock_receipt',?,?,?)""",
                    (
                        str(change["receipt_id"]),
                        json.dumps(details, ensure_ascii=False, sort_keys=True),
                        author,
                    ),
                )
            after_count = int(db.execute("SELECT COUNT(*) FROM stock_receipts").fetchone()[0])
            if before_count != after_count:
                raise RuntimeError("Количество stock_receipts изменилось")
            _validate_database(db)
            db.execute(
                """INSERT INTO audit_log(action,entity_type,entity_id,details,author)
                   VALUES('WAREHOUSE_RECLASSIFICATION_COMPLETED','warehouse_database','',?,?)""",
                (
                    json.dumps(
                        {
                            "changed_cards": len(changes),
                            "plan_sha256": digest,
                            "source_sha256": before_sha,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    author,
                ),
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
    _assert_no_sidecars(path)
    after_sha = sha256_file(path)
    report = {
        "database": str(path.resolve()),
        "before_sha256": before_sha,
        "after_sha256": after_sha,
        **summarize(changes),
        "changes": changes,
    }
    _write_manifest(manifest_path, report)
    return report


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    result.add_argument("--apply", action="store_true")
    result.add_argument("--expected-sha256", default="")
    result.add_argument("--manifest", type=Path)
    result.add_argument("--author", default="ODE warehouse classification correction")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    path = arguments.db.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    if arguments.apply:
        if not arguments.expected_sha256:
            raise RuntimeError("--expected-sha256 обязателен с --apply")
        if arguments.manifest is None:
            raise RuntimeError("--manifest обязателен с --apply")
        report = apply_plan(
            path,
            expected_sha256=arguments.expected_sha256,
            manifest_path=arguments.manifest,
            author=str(arguments.author),
        )
    else:
        _assert_no_sidecars(path)
        with closing(readonly_connection(path)) as db:
            _validate_database(db)
            changes = build_plan(db)
        report = {
            "database": str(path),
            "source_sha256": sha256_file(path),
            **summarize(changes),
        }
        if arguments.manifest is not None:
            _write_manifest(arguments.manifest, {**report, "changes": changes})
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
