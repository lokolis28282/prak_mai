from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from inventory.core.application import create_application_context
from inventory.db import initialize
from inventory.migration.pilot_schema import create_pilot_schema
from inventory.service import WarehouseService
from inventory.shared.validators import WarehouseError
from inventory.warehouse.migration_pilot_review import (
    MigrationPilotReviewService,
    PILOT_ENV,
    PILOT_FILENAME,
    validate_migration_pilot_database,
)
from inventory.webapp import make_handler


SERIAL = "000Ab-С Н-01"
SERIAL_VARIANT = "000aB-С Н-01"


def _insert_selection(
    connection: sqlite3.Connection,
    row_id: int,
    decision: str,
    *,
    target_receipt_id: int | None = None,
) -> None:
    columns = [
        str(row[1])
        for row in connection.execute("PRAGMA table_info(migration_pilot_selection)")
        if str(row[1]) != "id"
    ]
    serial = (
        SERIAL
        if row_id in {1, 3}
        else SERIAL_VARIANT
        if row_id == 2
        else f"PILOT-{row_id:04d}"
    )
    values: dict[str, object] = {
        "selection_order": row_id,
        "staging_row_id": row_id,
        "migration_batch_id": 1,
        "source_file": "/Users/private/migration/raw/source.xlsx",
        "source_sheet": "ПРИХОД",
        "source_row": row_id + 1,
        "source_row_hash": f"{row_id:064x}",
        "source_serial_value": serial,
        "normalized_match_value": serial.strip().casefold(),
        "serial_preservation_status": (
            "SOURCE_CORRUPTED" if decision == "SOURCE_CORRUPTED_REJECTED" else "TEXT_EXACT"
        ),
        "excel_cell_type": "inlineStr",
        "excel_number_format": "@",
        "raw_xml_value": "<v><script>not-for-browser</script></v>",
        "source_display_value": serial,
        "source_serial_hash": f"{row_id + 100:064x}",
        "source_item_name": "<img src=x onerror=alert(1)>",
        "canonical_item_name": "Сервер Dell PowerEdge R650",
        "object_kind": "equipment",
        "equipment_category": "server equipment",
        "equipment_type": "server",
        "component_type": "",
        "vendor": "Dell",
        "model": "PowerEdge R650",
        "part_number": "000PN-01",
        "supplier": "Supplier",
        "datacenter": "MOS1",
        "shelf": "" if row_id == 1 else "A-01",
        "quantity": "1",
        "source_receipt_date": "2024-01-02",
        "source_receipt_date_raw": "45293",
        "source_receipt_date_status": "EXACT_DATE",
        "source_receipt_date_cell_type": "n",
        "source_receipt_date_number_format": "dd.mm.yyyy",
        "migration_warnings": json.dumps(
            ["manual <review>", "evidence /Users/private/warning.txt"],
            ensure_ascii=False,
        ),
        "selection_reasons": json.dumps(["deterministic fixture"]),
        "quota_flags": json.dumps(["TEXT_EXACT"]),
        "conflict_types": json.dumps(["MODEL_CONFLICT"] if row_id == 2 else []),
        "duplicate_group_size": 3 if row_id in {1, 2, 3} else 0,
        "import_decision": decision,
        "identity_key": SERIAL.casefold() if row_id in {1, 2, 3} else serial.casefold(),
        "target_receipt_id": target_receipt_id,
        "created_at": "2026-07-14 12:00:00",
    }
    placeholders = ", ".join("?" for _ in columns)
    connection.execute(
        f"INSERT INTO migration_pilot_selection(id, {', '.join(columns)}) "
        f"VALUES (?, {placeholders})",
        [row_id, *(values[column] for column in columns)],
    )


def _create_pilot_database(path: Path) -> None:
    initialize(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE migration_batches (id INTEGER PRIMARY KEY);
            CREATE TABLE migration_staging_rows (id INTEGER PRIMARY KEY);
            INSERT INTO migration_batches(id) VALUES (1);
            """
        )
        for row_id in range(1, 101):
            connection.execute("INSERT INTO migration_staging_rows(id) VALUES (?)", (row_id,))
        connection.execute(
            """INSERT INTO stock_receipts(
                   id, receipt_date, responsible, item_name, serial_number,
                   supplier, vendor, model, object_name, datacenter,
                   equipment_type, unit, quantity
               ) VALUES (1, '2024-01-02', 'Migration', ?, ?, 'Supplier',
                         'Dell', 'PowerEdge R650', 'Warehouse', 'MOS1',
                         'server', 'шт', 1)""",
            ("Сервер Dell PowerEdge R650", SERIAL),
        )
        connection.execute(
            """INSERT INTO audit_log(
                   event_date, action, entity_type, entity_id, details, author
               ) VALUES ('2026-07-14 12:00:00', 'MIGRATION_RECEIPT_IMPORTED',
                         'stock_receipt', '1', 'pilot fixture', 'migration')"""
        )
        create_pilot_schema(connection)
        decisions = {
            1: "IMPORT",
            2: "CONFLICT_HISTORY_ONLY",
            3: "EXACT_DUPLICATE",
            4: "SOURCE_CORRUPTED_REJECTED",
            5: "QUARANTINE",
        }
        for row_id in range(1, 101):
            decision = decisions.get(row_id, "MANUAL_REVIEW")
            _insert_selection(
                connection,
                row_id,
                decision,
                target_receipt_id=1 if row_id in {1, 2, 3} else None,
            )
        connection.execute(
            """INSERT INTO migration_pilot_identities(
                   id, normalized_match_value, preserved_serial_value,
                   primary_selection_id, target_receipt_id, source_row_count, created_at
                   ) VALUES (1, ?, ?, 1, 1, 3, '2026-07-14 12:00:00')""",
            (SERIAL.casefold(), SERIAL),
        )
        for row_id in (1, 2, 3):
            connection.execute(
                """INSERT INTO migration_pilot_provenance(
                       id, selection_id, identity_id, target_receipt_id,
                       source_file, source_sheet, source_row, source_row_hash,
                       source_serial_value, normalized_match_value,
                       source_item_name, canonical_item_name,
                       source_receipt_date, source_receipt_date_raw,
                       source_receipt_date_status, shelf, import_decision,
                       warnings, created_at
                   ) SELECT id, id, 1, 1, source_file, source_sheet, source_row,
                            source_row_hash, source_serial_value, normalized_match_value,
                            source_item_name, canonical_item_name, source_receipt_date,
                            source_receipt_date_raw, source_receipt_date_status, shelf,
                            import_decision, migration_warnings, created_at
                     FROM migration_pilot_selection WHERE id = ?""",
                (row_id,),
            )
        for row_id in range(4, 101):
            connection.execute(
                """INSERT INTO migration_pilot_quarantine(
                       id, selection_id, reason_code, created_at
                   ) VALUES (?, ?, 'IDENTITY_REVIEW', '2026-07-14 12:00:00')""",
                (row_id, row_id),
            )
        connection.execute(
            """INSERT INTO migration_pilot_marker(
                   id, marker, stage, pilot_only, review_read_only, status,
                   selection_seed, selection_sha256, source_candidate_sha256,
                   source_manifest_sha256, serial_review_sha256, selected_count,
                   imported_count, quarantined_count, decision_counts, quota_counts,
                   unavailable_requirements, build_started_at, built_at
               ) VALUES (
                   1, 'ODE_MIGRATION_PILOT', '0.13.3A.5', 1, 1,
                   'READY_FOR_REVIEW', 'fixture-seed', ?, ?, ?, ?, 100, 1, 97,
                   ?, '{}', '[]', '2026-07-14 11:59:00', '2026-07-14 12:00:00'
               )""",
            (
                "1" * 64,
                "2" * 64,
                "3" * 64,
                "4" * 64,
                json.dumps(
                    {
                        "IMPORT": 1,
                        "CONFLICT_HISTORY_ONLY": 1,
                        "EXACT_DUPLICATE": 1,
                        "SOURCE_CORRUPTED_REJECTED": 1,
                        "QUARANTINE": 1,
                        "MANUAL_REVIEW": 95,
                    }
                ),
            ),
        )
        connection.commit()
    if os.name == "posix":
        path.chmod(0o600)


class _Actor:
    def __init__(self, role: str = "engineer") -> None:
        self.role = role
        self.receipt_ids: list[int] = []

    def current_user(self) -> dict[str, str]:
        return {"role": self.role, "email": "engineer@example.test"}

    def position_card(self, *, receipt_id: int) -> dict[str, object]:
        self.receipt_ids.append(receipt_id)
        return {
            "position": {
                "serial_number": SERIAL,
                "item_name": "Сервер Dell PowerEdge R650",
                "vendor": "Dell",
                "model": "PowerEdge R650",
            },
            "history": [
                {"date": "2024-01-02", "event_type": "Приход", "quantity": 1},
                {
                    "date": "2026-07-14 12:00:00",
                    "event_type": "Запись журнала: MIGRATION_RECEIPT_IMPORTED",
                    "quantity": "",
                },
            ],
        }


class MigrationPilotRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.db_path = self.root / PILOT_FILENAME
        _create_pilot_database(self.db_path)

    def test_marker_guard_accepts_only_explicit_valid_pilot(self) -> None:
        status = validate_migration_pilot_database(self.db_path, enabled=True)
        self.assertTrue(status["enabled"])
        self.assertEqual(status["stage"], "0.13.3A.5")
        self.assertEqual(status["status"], "READY_FOR_REVIEW")
        self.assertEqual(status["database"], PILOT_FILENAME)
        with self.assertRaisesRegex(RuntimeError, "обязателен"):
            validate_migration_pilot_database(self.db_path, enabled=False)

    def test_read_only_service_startup_does_not_initialize_or_change_pilot(self) -> None:
        before = hashlib.sha256(self.db_path.read_bytes()).hexdigest()
        service = WarehouseService(self.db_path, initialize_database=False)
        self.assertEqual(service.current_user()["role"], "admin")
        self.assertEqual(
            service.position_card(receipt_id=1)["position"]["serial_number"],
            SERIAL,
        )
        after = hashlib.sha256(self.db_path.read_bytes()).hexdigest()
        self.assertEqual(after, before)
        self.assertFalse(Path(str(self.db_path) + "-wal").exists())
        self.assertFalse(Path(str(self.db_path) + "-journal").exists())

    def test_flag_without_marker_and_wrong_filename_fail_closed(self) -> None:
        ordinary = self.root / PILOT_FILENAME
        self.db_path.rename(self.root / "valid.db")
        initialize(ordinary)
        with self.assertRaisesRegex(RuntimeError, "marker"):
            validate_migration_pilot_database(ordinary, enabled=True)
        with self.assertRaisesRegex(RuntimeError, "называться"):
            validate_migration_pilot_database(self.root / "valid.db", enabled=True)

    def test_production_samefile_and_sidecars_are_rejected(self) -> None:
        with patch(
            "inventory.warehouse.migration_pilot_review.DEFAULT_DB_PATH", self.db_path
        ):
            with self.assertRaisesRegex(RuntimeError, "data/warehouse.db"):
                validate_migration_pilot_database(self.db_path, enabled=True)
        wal = Path(str(self.db_path) + "-wal")
        wal.write_bytes(b"not-empty")
        with self.assertRaisesRegex(RuntimeError, "sidecar"):
            validate_migration_pilot_database(self.db_path, enabled=True)

    def test_marker_counts_are_verified(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                "UPDATE migration_pilot_marker SET selected_count = 101 WHERE id = 1"
            )
            connection.commit()
        with self.assertRaisesRegex(RuntimeError, "selected_count"):
            validate_migration_pilot_database(self.db_path, enabled=True)

    @unittest.skipUnless(os.name == "posix", "POSIX permission contract")
    def test_group_or_world_readable_pilot_is_rejected(self) -> None:
        for mode in (0o644, 0o400):
            with self.subTest(mode=oct(mode)):
                self.db_path.chmod(mode)
                with self.assertRaisesRegex(RuntimeError, "mode 0600"):
                    validate_migration_pilot_database(self.db_path, enabled=True)
                self.db_path.chmod(0o600)

    def test_review_projection_filters_and_excludes_raw_xml_and_paths(self) -> None:
        service = MigrationPilotReviewService(self.db_path, actor_provider=_Actor())
        result = service.list_rows(filter_name="IMPORT", query=SERIAL, limit=300)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["counts"]["IMPORT"], 1)
        row = result["rows"][0]
        self.assertEqual(row["source_serial_value"], SERIAL)
        self.assertEqual(row["source_file"], "source.xlsx")
        self.assertNotIn("raw_xml_value", row)
        self.assertNotIn("/Users/private", json.dumps(result, ensure_ascii=False))
        self.assertEqual(row["source_receipt_date_raw"], "45293")
        conflict = service.list_rows(filter_name="CONFLICT", limit=300)
        exact_duplicate = next(
            row for row in conflict["rows"] if row["import_decision"] == "EXACT_DUPLICATE"
        )
        self.assertTrue(exact_duplicate["has_card"])
        self.assertNotIn("target_receipt_id", exact_duplicate)

    def test_card_uses_receipt_id_and_preserves_exact_serial_and_timeline(self) -> None:
        actor = _Actor()
        service = MigrationPilotReviewService(self.db_path, actor_provider=actor)
        card = service.get_card(1)
        self.assertEqual(actor.receipt_ids, [1])
        self.assertEqual(card["position"]["serial_number"], SERIAL)
        self.assertEqual(
            card["history"][0]["event_type"], "Исторический приход (миграция)"
        )
        self.assertIn("MIGRATION_RECEIPT_IMPORTED", card["history"][1]["event_type"])
        self.assertEqual(len(card["migration"]["source_rows"]), 3)
        self.assertEqual(
            {row["source_serial_value"] for row in card["migration"]["source_rows"]},
            {SERIAL, SERIAL_VARIANT},
        )
        self.assertEqual(card["migration"]["source_serial_value"], SERIAL)
        duplicate_card = service.get_card(2)
        self.assertEqual(duplicate_card["position"]["serial_number"], SERIAL)
        self.assertEqual(duplicate_card["migration"]["source_serial_value"], SERIAL_VARIANT)
        self.assertEqual(duplicate_card["migration"]["preserved_identity_serial"], SERIAL)
        exact_duplicate_card = service.get_card(3)
        self.assertEqual(exact_duplicate_card["position"]["serial_number"], SERIAL)

    def test_non_import_and_viewer_cannot_open_review_card(self) -> None:
        service = MigrationPilotReviewService(self.db_path, actor_provider=_Actor())
        with self.assertRaisesRegex(WarehouseError, "не связана с Equipment Card"):
            service.get_card(4)
        viewer = MigrationPilotReviewService(self.db_path, actor_provider=_Actor("viewer"))
        with self.assertRaisesRegex(WarehouseError, "инженеру"):
            viewer.list_rows()
        admin = MigrationPilotReviewService(self.db_path, actor_provider=_Actor("admin"))
        self.assertEqual(admin.list_rows(limit=1)["limit"], 1)

    def test_http_api_is_role_gated_and_all_mutations_are_denied(self) -> None:
        previous = os.environ.get(PILOT_ENV)
        os.environ[PILOT_ENV] = "1"
        try:
            context = create_application_context(
                self.db_path,
                service=WarehouseService(
                    self.db_path,
                    initialize_database=False,
                ),
            )
            handler_type = make_handler(context)

            # Exercise the generated handler without opening a listening socket.
            # This keeps the contract test hermetic in restricted CI sandboxes.
            handler = handler_type.__new__(handler_type)
            sent: list[tuple[int, dict[str, object]]] = []
            handler._send_json = lambda status, payload: sent.append((status, payload))
            handler.path = "/api/migration-pilot?filter=IMPORT"
            with context.service_adapter().user_context("lokolis", role_override="engineer"):
                handler._do_GET()
            self.assertEqual(sent[-1][0], 200)
            self.assertEqual(sent[-1][1]["rows"][0]["source_serial_value"], SERIAL)

            handler.path = "/api/position-card?pilot_selection_id=1"
            with context.service_adapter().user_context("lokolis", role_override="engineer"):
                handler._do_GET()
            self.assertEqual(sent[-1][0], 200)
            self.assertEqual(sent[-1][1]["position"]["serial_number"], SERIAL)
            self.assertIn("migration", sent[-1][1])

            handler.path = "/api/action"
            handler.headers = {}
            handler._session_email = lambda: "lokolis"
            handler.do_POST()
            self.assertEqual(sent[-1][0], 403)
            self.assertIn("только в режиме просмотра", sent[-1][1]["error"])
        finally:
            if previous is None:
                os.environ.pop(PILOT_ENV, None)
            else:
                os.environ[PILOT_ENV] = previous


if __name__ == "__main__":
    unittest.main()
