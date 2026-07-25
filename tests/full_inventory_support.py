from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
from typing import Any

from inventory.migration.xlsx_cells import write_text_xlsx
from inventory.service import WarehouseService
from inventory.warehouse.baseline.models import ActorSnapshot
from inventory.warehouse.baseline.service import FullInventoryService


INVENTORY_COLUMNS = [
    "RowId", "ItemKind", "WarehouseCode", "LocationCode", "SerialNumber",
    "InventoryNumber", "PartNumber", "Vendor", "Model", "Description",
    "Quantity", "UOM", "Condition", "Lot", "CountedBy", "CountedAt", "Comment",
]


class FullInventoryFixture:
    def create_fixture(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.runtime = self.root / "runtime"
        self.runtime.mkdir()
        self.db_path = self.runtime / "warehouse.db"
        self.legacy_service = WarehouseService(self.db_path)
        self._install_references()
        self.state_root = self.root / "state"
        self.inventory = FullInventoryService(
            self.db_path, state_root=self.state_root
        )
        self.actor = ActorSnapshot(
            "legacy-user:1", "Тестовый Инженер", "engineer"
        )

    def cleanup_fixture(self) -> None:
        self.temporary.cleanup()

    def _install_references(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as db, db:
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
                    (1,'datacenter','ЦОД','',1,'test','2026','2026'),
                    (2,'shelf','Полка','',1,'test','2026','2026'),
                    (3,'warehouse_location','Локация','',1,'test','2026','2026'),
                    (4,'unit_of_measure','Единица','',1,'test','2026','2026');
                INSERT INTO reference_values_v2 VALUES
                    (10,1,'Ixcellerate','Ixcellerate','ixcellerate','',1,'APPROVED','test','2026','2026'),
                    (20,2,'1-1','1-1','1-1','',1,'APPROVED','test','2026','2026'),
                    (30,3,'candidate-a','Candidate A','candidate a','',0,'CANDIDATE','test','2026','2026'),
                    (40,4,'piece','шт','piece','',1,'APPROVED','test','2026','2026'),
                    (41,4,'metre','м','metre','',1,'APPROVED','test','2026','2026');
                """
            )

    def manifest(self, **overrides: str) -> list[dict[str, str]]:
        values = {
            "TemplateId": "ODE-FULL-INVENTORY",
            "TemplateVersion": "1.0",
            "InventoryExternalId": "FULL-TEST-1",
            "WarehouseCode": "Ixcellerate",
            "CountStartedAt": "2026-07-15T10:00:00+03:00",
            "CountFinishedAt": "2026-07-15T11:00:00+03:00",
            "CountedBy": "Тестовый Инженер",
            "TimeZone": "Europe/Moscow",
            "ReferenceVersion": self.inventory.reference_fingerprint().hex(),
            "Comment": "",
        }
        values.update(overrides)
        return [{"Key": key, "Value": value} for key, value in values.items()]

    def row(self, **overrides: str) -> dict[str, str]:
        values = {
            "RowId": "ROW-1",
            "ItemKind": "SERIALIZED",
            "WarehouseCode": "Ixcellerate",
            "LocationCode": "1-1",
            "SerialNumber": "0000012345",
            "InventoryNumber": "",
            "PartNumber": "PN-1",
            "Vendor": "Dell",
            "Model": "R760",
            "Description": "Сервер Dell R760",
            "Quantity": "1",
            "UOM": "шт",
            "Condition": "AVAILABLE",
            "Lot": "",
            "CountedBy": "Тестовый Инженер",
            "CountedAt": "2026-07-15T10:30:00+03:00",
            "Comment": "",
        }
        values.update(overrides)
        return values

    def workbook(
        self,
        *,
        rows: list[dict[str, str]] | None = None,
        manifest: list[dict[str, str]] | None = None,
        filename: str = "inventory.xlsx",
    ) -> Path:
        target = self.root / filename
        write_text_xlsx(
            target,
            {
                "Manifest": (["Key", "Value"], manifest or self.manifest()),
                "Inventory": (INVENTORY_COLUMNS, rows or [self.row()]),
            },
            identifier_columns={"Manifest": ["Key", "Value"], "Inventory": INVENTORY_COLUMNS},
        )
        return target

    def create_session(self) -> dict[str, Any]:
        return self.inventory.create_session(
            self.actor, correlation_id="corr_create_0123456789"
        )

    def upload(self, session: dict[str, Any], workbook: Path) -> dict[str, Any]:
        with workbook.open("rb") as stream:
            return self.inventory.upload_source(
                session["public_id"],
                filename=workbook.name,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                content_length=workbook.stat().st_size,
                stream=stream,
                actor=self.actor,
                correlation_id="corr_upload_0123456789",
            )
