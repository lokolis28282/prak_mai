from __future__ import annotations

from contextlib import closing
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from inventory.core import application as _application_wiring  # noqa: F401
from inventory.db import DEFAULT_DB_PATH, initialize
from inventory.migration.pilot_builder import (
    EXPECTED_DECISION_COUNTS,
    PilotRuntimeHooks,
    _selection_serialized,
    build_pilot,
    validate_pilot_database,
)
from inventory.migration.pilot_models import (
    CONFLICT_HISTORY_ONLY,
    EXACT_DUPLICATE,
    IMPORT,
    MANUAL_REVIEW,
    PILOT_SELECTION_SEED,
    QUANTITY_POSITION_DEFERRED,
    QUARANTINE,
    SOURCE_CORRUPTED_REJECTED,
    PilotPaths,
    PilotSelection,
    PilotSelectionRow,
)
from inventory.migration.pilot_selector import (
    parse_excel_receipt_date,
    selection_rank,
)
from inventory.migration.validation import sha256_file
from inventory.migration.xlsx_cells import XlsxCell, iter_xlsx_cells, read_text_xlsx
from inventory.warehouse.migration_pilot import (
    MigrationPilotReceiptWriter,
    write_migration_conflict_recorded,
    write_migration_exact_duplicate_skipped,
    write_migration_serial_quarantined,
    write_migration_source_row_linked,
)
from inventory.warehouse.receipt_repository import ReceiptRepository


ROOT = Path(__file__).resolve().parent.parent
REAL_PILOT = (
    ROOT / "migration_inputs" / "workspace" / "warehouse_pilot_candidate.db"
)


def _xlsx_cell(
    raw: str,
    *,
    cell_type: str = "n",
    number_format: str = "dd.mm.yyyy",
) -> XlsxCell:
    return XlsxCell(
        source_file="source.xlsx",
        source_sheet="ПРИХОД",
        source_row=2,
        source_column="A",
        excel_cell_coordinate="A2",
        excel_cell_type=cell_type,
        excel_number_format=number_format,
        raw_xml_value=raw,
        source_display_value=raw,
        source_hash="1" * 64,
        source_file_hash="2" * 64,
    )


def _row(
    row_id: int,
    decision: str,
    *,
    identity_number: int | None = None,
) -> PilotSelectionRow:
    identity_number = identity_number if identity_number is not None else row_id
    identity_serial = f"000PILOT-{identity_number:04d}-Ab-С Н"
    source_serial = identity_serial
    if decision == CONFLICT_HISTORY_ONLY:
        source_serial = identity_serial.swapcase()
    if decision == SOURCE_CORRUPTED_REJECTED:
        source_serial = "4.225112538E15"
    preservation = (
        "SOURCE_CORRUPTED"
        if decision == SOURCE_CORRUPTED_REJECTED
        else "NUMERIC_FORMAT_UNPROVEN"
        if decision == QUARANTINE
        else "TEXT_EXACT"
    )
    linked = decision in {IMPORT, EXACT_DUPLICATE, CONFLICT_HISTORY_ONLY}
    return PilotSelectionRow(
        selection_order=row_id,
        staging_row_id=row_id,
        migration_batch_id=1,
        source_file="source.xlsx",
        source_sheet="ПРИХОД",
        source_row=row_id + 1,
        source_row_hash=f"{row_id:064x}",
        source_serial_value=source_serial,
        normalized_match_value=(
            identity_serial.casefold() if preservation == "TEXT_EXACT" else ""
        ),
        serial_preservation_status=preservation,
        excel_cell_type="inlineStr" if preservation == "TEXT_EXACT" else "n",
        excel_number_format="@" if preservation == "TEXT_EXACT" else "General",
        raw_xml_value=source_serial,
        source_display_value=source_serial,
        source_serial_hash=f"{row_id + 500:064x}",
        source_item_name=f"source item {row_id}",
        canonical_item_name=(
            "Сервер Dell PowerEdge R650" if decision == IMPORT else ""
        ),
        object_kind="equipment" if decision == IMPORT else "unknown",
        equipment_category="server equipment" if decision == IMPORT else "",
        equipment_type="server" if decision == IMPORT else "",
        component_type="",
        vendor="Dell" if decision == IMPORT else "",
        model="PowerEdge R650" if decision == IMPORT else "",
        part_number=f"000PN-{row_id:04d}",
        supplier="Supplier" if decision == IMPORT else "",
        datacenter="",
        shelf="" if row_id % 2 else "A-01",
        quantity="2" if decision == QUANTITY_POSITION_DEFERRED else "1",
        source_receipt_date="2024-01-02" if decision == IMPORT else "",
        source_receipt_date_raw="45293",
        source_receipt_date_status=(
            "NUMERIC_DATE_EXACT_1900_EPOCH" if decision == IMPORT else "UNPROVEN"
        ),
        source_receipt_date_cell_type="n",
        source_receipt_date_number_format="dd.mm.yyyy",
        migration_warnings=(decision,) if decision != IMPORT else (),
        selection_reasons=("deterministic fixture",),
        quota_flags=("LEADING_ZERO",) if decision == IMPORT else (),
        conflict_types=("MODEL_CONFLICT",)
        if decision == CONFLICT_HISTORY_ONLY
        else (),
        duplicate_group_size=2 if linked and decision != IMPORT else 1,
        import_decision=decision,
        identity_key=identity_serial.casefold() if linked else "",
    )


def _selection(source_candidate: Path) -> PilotSelection:
    rows: list[PilotSelectionRow] = []
    rows.extend(_row(index, IMPORT) for index in range(1, 131))
    rows.extend(
        _row(index, EXACT_DUPLICATE, identity_number=index - 130)
        for index in range(131, 137)
    )
    rows.extend(
        _row(index, CONFLICT_HISTORY_ONLY, identity_number=index - 130)
        for index in range(137, 172)
    )
    rows.extend(_row(index, QUARANTINE) for index in range(172, 182))
    rows.extend(_row(index, MANUAL_REVIEW) for index in range(182, 189))
    rows.extend(
        _row(index, QUANTITY_POSITION_DEFERRED) for index in range(189, 199)
    )
    rows.extend(_row(index, SOURCE_CORRUPTED_REJECTED) for index in range(199, 201))
    frozen = tuple(rows)
    selection_sha = hashlib.sha256(_selection_serialized(frozen)).hexdigest()
    return PilotSelection(
        rows=frozen,
        decision_counts=dict(EXPECTED_DECISION_COUNTS),
        quota_counts={"LEADING_ZERO": 130, "TEXT_EXACT": 188},
        selection_sha256=selection_sha,
        source_candidate_sha256=sha256_file(source_candidate),
        source_manifest_sha256="a" * 64,
        serial_review_sha256="b" * 64,
        unavailable_requirements=("VEGMAN_R200_UNAVAILABLE_FROM_SOURCE",),
    )


class MigrationPilotBuilderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.production_db = self.root / "production.db"
        self.source_candidate = self.root / "source_candidate.db"
        initialize(self.production_db)
        initialize(self.source_candidate)
        with closing(sqlite3.connect(self.source_candidate)) as connection:
            connection.execute("CREATE TABLE migration_batches(id INTEGER PRIMARY KEY)")
            connection.execute(
                "CREATE TABLE migration_staging_rows(id INTEGER PRIMARY KEY)"
            )
            connection.execute("INSERT INTO migration_batches(id) VALUES (1)")
            connection.executemany(
                "INSERT INTO migration_staging_rows(id) VALUES (?)",
                ((index,) for index in range(1, 201)),
            )
            connection.commit()
        if os.name == "posix":
            self.source_candidate.chmod(0o600)
        self.raw_dir = self.root / "raw"
        self.raw_dir.mkdir()
        (self.raw_dir / "source.xlsx").write_bytes(b"immutable-source")
        self.normalized_dir = self.root / "normalized"
        self.normalized_dir.mkdir()
        self.serial_review = self.normalized_dir / "serial_review.xlsx"
        self.serial_review.write_bytes(b"immutable-review")
        self.paths = PilotPaths(
            source_candidate=self.source_candidate,
            production_db=self.production_db,
            raw_dir=self.raw_dir,
            normalized_dir=self.normalized_dir,
            serial_review=self.serial_review,
            pilot_db=self.root / "workspace" / "warehouse_pilot_candidate.db",
            selection_xlsx=self.root / "reports" / "PILOT_RECEIPT_SELECTION.xlsx",
            selection_markdown=self.root / "reports" / "PILOT_RECEIPT_SELECTION.md",
        )
        self.selection = _selection(self.source_candidate)
        writer = MigrationPilotReceiptWriter(ReceiptRepository(self.paths.pilot_db))
        self.hooks = PilotRuntimeHooks(
            write_receipt=writer.write_receipt,
            write_source_row_linked=write_migration_source_row_linked,
            write_conflict_recorded=write_migration_conflict_recorded,
            write_exact_duplicate_skipped=write_migration_exact_duplicate_skipped,
            write_serial_quarantined=write_migration_serial_quarantined,
        )

    def test_excel_receipt_date_uses_raw_token_and_proven_format_only(self) -> None:
        exact = parse_excel_receipt_date(_xlsx_cell("45293"))
        self.assertEqual(exact.iso_value, "2024-01-02")
        self.assertEqual(exact.raw_xml_value, "45293")
        self.assertEqual(exact.status, "NUMERIC_DATE_EXACT_1900_EPOCH")
        self.assertFalse(
            parse_excel_receipt_date(
                _xlsx_cell("45293", number_format="General")
            ).proven
        )
        self.assertFalse(parse_excel_receipt_date(_xlsx_cell("45293.5")).proven)
        self.assertFalse(parse_excel_receipt_date(_xlsx_cell("1E+20")).proven)
        text = parse_excel_receipt_date(
            _xlsx_cell("2024-01-02", cell_type="inlineStr", number_format="@")
        )
        self.assertEqual(text.iso_value, "2024-01-02")
        self.assertEqual(text.status, "TEXT_ISO_DATE_EXACT")

    def test_selection_rank_is_stable_and_seeded(self) -> None:
        first = selection_rank("source-row-hash")
        self.assertEqual(first, selection_rank("source-row-hash"))
        self.assertNotEqual(
            first,
            selection_rank("source-row-hash", seed=PILOT_SELECTION_SEED + "-other"),
        )

    def test_build_is_atomic_preserves_sources_and_writes_text_reports(self) -> None:
        before = {
            "production": sha256_file(self.production_db),
            "candidate": sha256_file(self.source_candidate),
            "raw": sha256_file(self.raw_dir / "source.xlsx"),
            "review": sha256_file(self.serial_review),
        }
        with patch(
            "inventory.migration.pilot_builder.select_pilot_receipts",
            return_value=self.selection,
        ):
            result = build_pilot(self.paths, self.hooks)
        after = {
            "production": sha256_file(self.production_db),
            "candidate": sha256_file(self.source_candidate),
            "raw": sha256_file(self.raw_dir / "source.xlsx"),
            "review": sha256_file(self.serial_review),
        }
        self.assertEqual(after, before)
        self.assertTrue(result.report["production_database_unchanged"])
        self.assertTrue(result.report["raw_sha_unchanged"])
        validation = validate_pilot_database(self.paths.pilot_db)
        self.assertEqual(validation["decision_counts"], EXPECTED_DECISION_COUNTS)
        self.assertEqual(validation["imported_cards"], 130)
        self.assertEqual(validation["quarantine_rows"], 29)
        self.assertEqual(validation["historical_issues_imported"], 0)
        self.assertEqual(validation["production_mutations"], 0)

        report = read_text_xlsx(self.paths.selection_xlsx)
        self.assertEqual(len(report["PILOT_SELECTION"]), 200)
        self.assertEqual(report["PILOT_SELECTION"][0]["source_serial_value"], "000PILOT-0001-Ab-С Н")
        serial_cells = [
            cell
            for cell in iter_xlsx_cells(
                self.paths.selection_xlsx,
                sheet_names={"PILOT_SELECTION"},
                columns={"PILOT_SELECTION": {"H"}},
            )
            if cell.source_row > 1
        ]
        self.assertEqual(len(serial_cells), 200)
        self.assertTrue(all(cell.excel_cell_type == "inlineStr" for cell in serial_cells))
        self.assertTrue(all(cell.excel_number_format == "@" for cell in serial_cells))
        self.assertNotIn(str(self.root), self.paths.selection_markdown.read_text(encoding="utf-8"))

    def test_failure_never_publishes_partial_database_or_reports(self) -> None:
        failed = replace(
            self.paths,
            pilot_db=self.root / "failed" / "warehouse_pilot_candidate.db",
            selection_xlsx=self.root / "failed-reports" / "selection.xlsx",
            selection_markdown=self.root / "failed-reports" / "selection.md",
        )
        source_hashes = (
            sha256_file(self.production_db),
            sha256_file(self.source_candidate),
            sha256_file(self.raw_dir / "source.xlsx"),
        )

        def fail_write(*_args: object, **_kwargs: object) -> int:
            raise RuntimeError("injected pilot write failure")

        hooks = replace(self.hooks, write_receipt=fail_write)
        with patch(
            "inventory.migration.pilot_builder.select_pilot_receipts",
            return_value=self.selection,
        ):
            with self.assertRaisesRegex(RuntimeError, "injected pilot write failure"):
                build_pilot(failed, hooks)
        self.assertFalse(failed.pilot_db.exists())
        self.assertFalse(failed.selection_xlsx.exists())
        self.assertFalse(failed.selection_markdown.exists())
        self.assertEqual(
            source_hashes,
            (
                sha256_file(self.production_db),
                sha256_file(self.source_candidate),
                sha256_file(self.raw_dir / "source.xlsx"),
            ),
        )


@unittest.skipUnless(REAL_PILOT.is_file(), "real ignored pilot artifact is absent")
class RealMigrationPilotArtifactTest(unittest.TestCase):
    def test_real_pilot_preserves_cards_and_source_separation(self) -> None:
        production_before = sha256_file(DEFAULT_DB_PATH)
        result = validate_pilot_database(REAL_PILOT)
        self.assertEqual(result["selected_count"], 200)
        self.assertEqual(result["decision_counts"], EXPECTED_DECISION_COUNTS)
        self.assertEqual(result["imported_cards"], 130)
        self.assertEqual(result["integrity_check"], "ok")
        self.assertEqual(result["foreign_key_errors"], 0)
        with closing(
            sqlite3.connect(
                f"{REAL_PILOT.resolve().as_uri()}?mode=ro&immutable=1", uri=True
            )
        ) as connection:
            connection.row_factory = sqlite3.Row
            leading = connection.execute(
                """SELECT s.source_serial_value, r.serial_number
                     FROM migration_pilot_selection s
                     JOIN stock_receipts r ON r.id=s.target_receipt_id
                    WHERE s.import_decision='IMPORT'
                      AND s.source_serial_value GLOB '0*'
                    ORDER BY s.selection_order"""
            ).fetchall()
            self.assertGreaterEqual(len(leading), 20)
            self.assertTrue(
                all(row["source_serial_value"] == row["serial_number"] for row in leading)
            )
            vendors = {
                str(row[0]).casefold()
                for row in connection.execute(
                    "SELECT DISTINCT vendor FROM migration_pilot_selection"
                )
            }
            self.assertIn("huawei", vendors)
            self.assertIn("xfusion", vendors)
            models = {
                str(row[0]).casefold()
                for row in connection.execute(
                    "SELECT DISTINCT model FROM migration_pilot_selection"
                )
            }
            self.assertTrue(any("r220" in value for value in models))
            self.assertFalse(any("r200" in value for value in models))
            quota_counts = json.loads(
                str(
                    connection.execute(
                        "SELECT quota_counts FROM migration_pilot_marker WHERE id=1"
                    ).fetchone()[0]
                )
            )
            self.assertEqual(quota_counts["DUPLICATE_GROUP"], 41)
            self.assertEqual(quota_counts["CONFLICT_GROUP"], 26)
        self.assertEqual(sha256_file(DEFAULT_DB_PATH), production_before)


if __name__ == "__main__":
    unittest.main()
