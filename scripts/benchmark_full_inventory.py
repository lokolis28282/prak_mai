#!/usr/bin/env python3
"""Disposable 1k/10k/50k FULL Inventory Preview benchmark."""

from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import resource
import sqlite3
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inventory.migration.xlsx_cells import write_text_xlsx
from inventory.service import WarehouseService
from inventory.warehouse.baseline.models import ActorSnapshot
from inventory.warehouse.baseline.service import FullInventoryService


COLUMNS = [
    "RowId", "ItemKind", "WarehouseCode", "LocationCode", "SerialNumber",
    "InventoryNumber", "PartNumber", "Vendor", "Model", "Description",
    "Quantity", "UOM", "Condition", "Lot", "CountedBy", "CountedAt", "Comment",
]


def _install_references(path: Path) -> None:
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(
            """
            CREATE TABLE reference_domains_v2(
                id INTEGER PRIMARY KEY, domain_key TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL, source TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE reference_values_v2(
                id INTEGER PRIMARY KEY, domain_id INTEGER NOT NULL REFERENCES reference_domains_v2(id),
                canonical_value TEXT NOT NULL, display_name TEXT NOT NULL,
                normalized_key TEXT NOT NULL, scope_key TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL, approval_status TEXT NOT NULL,
                source TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(domain_id,scope_key,normalized_key)
            );
            CREATE TABLE reference_aliases_v2(
                id INTEGER PRIMARY KEY, domain_id INTEGER NOT NULL REFERENCES reference_domains_v2(id),
                source_value TEXT NOT NULL, normalized_source_key TEXT NOT NULL,
                canonical_id INTEGER NOT NULL REFERENCES reference_values_v2(id),
                source_file TEXT NOT NULL, source_sheet TEXT NOT NULL,
                usage_count INTEGER NOT NULL DEFAULT 0, confidence TEXT NOT NULL,
                resolution_status TEXT NOT NULL, approved_by TEXT NOT NULL DEFAULT '',
                approved_at TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
                UNIQUE(domain_id,source_value,canonical_id,source_file,source_sheet)
            );
            INSERT INTO reference_domains_v2 VALUES
                (1,'datacenter','ЦОД','',1,'benchmark','2026','2026'),
                (2,'shelf','Полка','',1,'benchmark','2026','2026'),
                (3,'warehouse_location','Локация','',1,'benchmark','2026','2026'),
                (4,'unit_of_measure','Единица','',1,'benchmark','2026','2026');
            INSERT INTO reference_values_v2 VALUES
                (10,1,'Ixcellerate','Ixcellerate','ixcellerate','',1,'APPROVED','benchmark','2026','2026'),
                (20,2,'1-1','1-1','1-1','',1,'APPROVED','benchmark','2026','2026'),
                (40,4,'piece','шт','piece','',1,'APPROVED','benchmark','2026','2026');
            """
        )


def _rows(count: int):
    for index in range(1, count + 1):
        yield {
            "RowId": f"ROW-{index:06d}", "ItemKind": "SERIALIZED",
            "WarehouseCode": "Ixcellerate", "LocationCode": "1-1",
            "SerialNumber": f"PERF-{index:010d}", "InventoryNumber": f"INV-{index:010d}",
            "PartNumber": "PN-PERF", "Vendor": "Benchmark", "Model": "M1",
            "Description": "Performance fixture", "Quantity": "1", "UOM": "шт",
            "Condition": "AVAILABLE", "Lot": "", "CountedBy": "Benchmark",
            "CountedAt": "2026-07-16T00:30:00+03:00", "Comment": "",
        }


def _manifest(reference_fingerprint: str):
    values = {
        "TemplateId": "ODE-FULL-INVENTORY", "TemplateVersion": "1.0",
        "InventoryExternalId": "PERFORMANCE", "WarehouseCode": "Ixcellerate",
        "CountStartedAt": "2026-07-16T00:00:00+03:00",
        "CountFinishedAt": "2026-07-16T01:00:00+03:00",
        "CountedBy": "Benchmark", "TimeZone": "Europe/Moscow",
        "ReferenceVersion": reference_fingerprint, "Comment": "disposable benchmark",
    }
    return [{"Key": key, "Value": value} for key, value in values.items()]


def run(size: int) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix=f"ode-full-inventory-{size}-") as temporary:
        root = Path(temporary)
        database = root / "warehouse.db"
        WarehouseService(database)
        _install_references(database)
        inventory = FullInventoryService(database, state_root=root / "state")
        actor = ActorSnapshot("benchmark:operator", "Benchmark Operator", "engineer")
        workbook = root / f"inventory-{size}.xlsx"
        started = time.perf_counter()
        write_text_xlsx(
            workbook,
            {
                "Manifest": (["Key", "Value"], _manifest(inventory.reference_fingerprint().hex())),
                "Inventory": (COLUMNS, _rows(size)),
            },
            identifier_columns={"Manifest": ["Key", "Value"], "Inventory": COLUMNS},
        )
        generated_seconds = time.perf_counter() - started
        operational_sha = hashlib.sha256(database.read_bytes()).hexdigest()
        session = inventory.create_session(actor, correlation_id=f"benchmark-create-{size:08d}")
        with workbook.open("rb") as stream:
            inventory.upload_source(
                session["public_id"], filename=workbook.name,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                content_length=workbook.stat().st_size, stream=stream, actor=actor,
                correlation_id=f"benchmark-upload-{size:08d}",
            )
        started = time.perf_counter()
        summary = inventory.build_preview(
            session["public_id"], actor, correlation_id=f"benchmark-preview-{size:08d}"
        )
        preview_seconds = time.perf_counter() - started
        if summary["session"]["row_count"] != size or summary["session"]["blocker_count"]:
            raise RuntimeError("benchmark Preview result is not valid")
        if hashlib.sha256(database.read_bytes()).hexdigest() != operational_sha:
            raise RuntimeError("operational fixture DB changed during Preview")
        peak_rss_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            peak_rss_kib //= 1024
        return {
            "rows": size, "xlsx_bytes": workbook.stat().st_size,
            "generation_seconds": round(generated_seconds, 3),
            "preview_seconds": round(preview_seconds, 3),
            "rows_per_second": round(size / preview_seconds, 1),
            "peak_rss_kib": peak_rss_kib,
            "session_status": summary["session"]["session_status"],
            "operational_db_unchanged": True,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=[1_000, 10_000, 50_000])
    args = parser.parse_args()
    if any(size < 1 or size > 50_000 for size in args.sizes):
        parser.error("sizes must be between 1 and 50000")
    results = [run(size) for size in args.sizes]
    print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
