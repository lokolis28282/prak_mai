from __future__ import annotations

from contextlib import closing, redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import string
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile

from inventory.db import SCHEMA as PRODUCTION_SCHEMA
from inventory.migration.candidate_db import (
    CandidatePaths,
    build_candidate,
)
from inventory.migration.reference_data import DOMAIN_KEYS
from inventory.migration.staging_schema import STAGING_TABLES
from inventory.migration.validation import (
    PRODUCTION_OPERATIONAL_TABLES,
    candidate_sidecars,
    sha256_file,
    validate_candidate,
)
from inventory.migration.xlsx_cells import (
    MAIN_NS,
    iter_xlsx_cells,
    read_text_csv,
    read_text_xlsx,
    write_text_xlsx,
)
from scripts import migration_reference_data


SENTINEL_PASSWORD_HASH = "SENTINEL_PASSWORD_HASH_MUST_NEVER_BE_REPORTED"
SOURCE_XLSX = "warehouse_accounting_source.xlsx"
DCIM_XLSX = "dcim_lookup_source.xlsx"
SERIAL_REVIEW_TXT = "serial_review_source.txt"


def _file_hashes(directory: Path) -> dict[str, str]:
    return {
        path.name: sha256_file(path)
        for path in sorted(directory.iterdir())
        if path.is_file()
    }


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def _create_source_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.executescript(PRODUCTION_SCHEMA)
        connection.execute(
            """INSERT INTO users(
                   id, first_name, last_name, position, email, password_hash,
                   role, must_change_password, is_active, created_at
               ) VALUES (7, 'Migration', 'Admin', 'Administrator',
                         'migration-admin@example.test', ?, 'admin', 1, 1,
                         '2026-07-14 12:00:00')""",
            (SENTINEL_PASSWORD_HASH,),
        )
        connection.commit()


def _receipt_row(
    *, serial: str, inventory: str, model: str, part_number: str
) -> list[str]:
    values = [""] * 25
    values[0] = "2024-01-02"
    values[6] = f"Сервер Acme New {model}"
    values[7] = "1"
    values[11] = serial
    values[12] = inventory
    values[16] = "Acme New"
    values[17] = model
    values[18] = part_number
    values[21] = "Оборудование"
    values[22] = "Серверное оборудование"
    return values


def _create_source_workbook(path: Path) -> None:
    receipt_headers = [f"column_{letter}" for letter in string.ascii_uppercase[:25]]
    issue_headers = [f"column_{letter}" for letter in string.ascii_uppercase[:16]]
    issue_row = [""] * 16
    issue_row[1] = "2024-01-03"
    issue_row[3] = "TARGET-0001"
    issue_row[8] = "1"
    issue_row[9] = "ISSUE-0001"
    issue_row[12] = "Монтаж"
    write_text_xlsx(
        path,
        {
            "ПРИХОД": (
                receipt_headers,
                [
                    [""] * 25,
                    _receipt_row(
                        serial="numeric-placeholder",
                        inventory="000INV220",
                        model="R220",
                        part_number="000PN220",
                    ),
                    _receipt_row(
                        serial="00012345",
                        inventory="000INV200",
                        model="R200",
                        part_number="000PN200",
                    ),
                ],
            ),
            "РАСХОД": (issue_headers, [issue_row]),
        },
        identifier_columns={
            "ПРИХОД": {
                "column_D",
                "column_E",
                "column_F",
                "column_L",
                "column_M",
                "column_S",
            },
            "РАСХОД": {"column_C", "column_D", "column_J"},
        },
    )
    _replace_cell_with_numeric_token(path, "L3", "4.225112539E17")


def _replace_cell_with_numeric_token(
    workbook: Path, coordinate: str, raw_token: str
) -> None:
    temporary = workbook.with_suffix(".numeric.tmp.xlsx")
    with ZipFile(workbook, "r") as source, ZipFile(
        temporary, "w", compression=ZIP_DEFLATED
    ) as destination:
        for info in source.infolist():
            payload = source.read(info.filename)
            if info.filename == "xl/worksheets/sheet1.xml":
                root = ElementTree.fromstring(payload)
                cell = root.find(
                    f".//{{{MAIN_NS}}}c[@r='{coordinate}']"
                )
                if cell is None:
                    raise AssertionError(f"fixture cell not found: {coordinate}")
                cell.set("t", "n")
                for child in list(cell):
                    cell.remove(child)
                value = ElementTree.SubElement(cell, f"{{{MAIN_NS}}}v")
                value.text = raw_token
                payload = ElementTree.tostring(
                    root, encoding="utf-8", xml_declaration=True
                )
            destination.writestr(info, payload)
    os.replace(temporary, workbook)


def _create_reference_review(path: Path) -> None:
    headers = [
        "source_value",
        "proposed_value",
        "rule",
        "confidence",
        "requires_manual_review",
        "source_sheet",
        "source_row",
        "domain",
        "usage_count",
        "all_source_sheets",
        "aliases_in_group",
        "conflict",
        "recommendation",
    ]
    write_text_xlsx(
        path,
        {
            "REFERENCE_CANDIDATES": (
                headers,
                [
                    [
                        "  ACME NEW  ",
                        "Acme New",
                        "SAFE_NORMALIZATION",
                        "0.99",
                        "false",
                        "ПРИХОД",
                        "3",
                        "vendor",
                        "2",
                        "ПРИХОД",
                        "Acme New",
                        "",
                        "create",
                    ],
                    [
                        "Huawei",
                        "xFusion",
                        "MANUAL_REVIEW",
                        "0.1",
                        "true",
                        "ПРИХОД",
                        "4",
                        "vendor",
                        "1",
                        "ПРИХОД",
                        "",
                        "PROHIBITED_SEMANTIC_MERGE",
                        "manual review",
                    ],
                ],
            )
        },
    )


def _create_raw_sources(raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    _create_source_workbook(raw_dir / SOURCE_XLSX)
    write_text_xlsx(
        raw_dir / DCIM_XLSX,
        {"DCIM": (["serial_number", "inventory_number"], [])},
        identifier_columns={"serial_number", "inventory_number"},
    )
    (raw_dir / SERIAL_REVIEW_TXT).write_text(
        "ПРИХОД\t3\tL\t4.225112539E17\n", encoding="utf-8"
    )
    entries = []
    for name in (SOURCE_XLSX, DCIM_XLSX, SERIAL_REVIEW_TXT):
        entries.append(f"{sha256_file(raw_dir / name)}  {name}")
    (raw_dir / "SHA256SUMS.local").write_text(
        "\n".join(entries) + "\n", encoding="utf-8"
    )


class MigrationCandidateDatabaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.raw_dir = cls.root / "raw"
        cls.normalized_dir = cls.root / "normalized"
        cls.workspace = cls.root / "workspace"
        cls.source_db = cls.root / "source.db"
        cls.normalized_dir.mkdir(parents=True)
        cls.workspace.mkdir(parents=True)
        _create_source_database(cls.source_db)
        _create_raw_sources(cls.raw_dir)
        _create_reference_review(cls.normalized_dir / "reference_candidates.xlsx")
        cls.paths = CandidatePaths(
            source_db=cls.source_db,
            raw_dir=cls.raw_dir,
            normalized_dir=cls.normalized_dir,
            candidate_db=cls.workspace / "candidate.db",
            reference_package=cls.workspace / "reference_package.xlsx",
            serial_export=cls.workspace / "serial_preservation.csv",
            report=cls.workspace / "candidate_validation.json",
        )
        cls.source_sha_before = sha256_file(cls.source_db)
        cls.raw_sha_before = _file_hashes(cls.raw_dir)
        cls.build_result = build_candidate(cls.paths)

    def _connect_candidate(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.paths.candidate_db)
        connection.row_factory = sqlite3.Row
        return connection

    def test_candidate_contains_current_schema_and_candidate_only_schema(self) -> None:
        with closing(sqlite3.connect(":memory:")) as expected_connection:
            expected_connection.executescript(PRODUCTION_SCHEMA)
            expected_production_tables = _table_names(expected_connection)
        with closing(self._connect_candidate()) as candidate:
            candidate_tables = _table_names(candidate)
            domains = {
                str(row[0])
                for row in candidate.execute(
                    "SELECT domain_key FROM reference_domains_v2"
                )
            }
        self.assertTrue(expected_production_tables.issubset(candidate_tables))
        self.assertEqual(set(STAGING_TABLES), candidate_tables & set(STAGING_TABLES))
        self.assertEqual(len(STAGING_TABLES), 9)
        self.assertEqual(domains, set(DOMAIN_KEYS))
        self.assertEqual(len(domains), 20)

    def test_source_database_has_no_staging_schema_and_never_changes(self) -> None:
        with closing(sqlite3.connect(self.source_db)) as source:
            tables = _table_names(source)
        self.assertFalse(tables & set(STAGING_TABLES))
        self.assertEqual(sha256_file(self.source_db), self.source_sha_before)
        self.assertEqual(_file_hashes(self.raw_dir), self.raw_sha_before)

    def test_only_security_users_are_copied_exactly(self) -> None:
        with closing(self._connect_candidate()) as candidate:
            users = candidate.execute(
                """SELECT id, first_name, last_name, position, email,
                          password_hash, role, must_change_password, is_active,
                          created_at
                   FROM users ORDER BY id"""
            ).fetchall()
        self.assertEqual(len(users), 1)
        self.assertEqual(
            tuple(users[0]),
            (
                7,
                "Migration",
                "Admin",
                "Administrator",
                "migration-admin@example.test",
                SENTINEL_PASSWORD_HASH,
                "admin",
                1,
                1,
                "2026-07-14 12:00:00",
            ),
        )
        serialized_report = json.dumps(
            self.build_result.report, ensure_ascii=False, sort_keys=True
        )
        report_file = self.paths.report.read_text(encoding="utf-8")
        for text in (serialized_report, report_file):
            self.assertNotIn(SENTINEL_PASSWORD_HASH, text)
            self.assertNotIn("password_hash", text.casefold())

    def test_report_fully_replaces_legacy_secret_bearing_json(self) -> None:
        legacy_secret = "LEGACY_REPORT_SECRET_MUST_BE_REMOVED"
        legacy_local_path = "/Users/example/private/source.xlsx"
        self.paths.report.write_text(
            json.dumps(
                {
                    "password_hash": legacy_secret,
                    "source_path": legacy_local_path,
                    "stale": True,
                }
            ),
            encoding="utf-8",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            return_code = migration_reference_data.main(
                ["report", *self._cli_path_arguments()]
            )
        self.assertEqual(return_code, 0, stderr.getvalue())
        report_text = self.paths.report.read_text(encoding="utf-8")
        output_text = stdout.getvalue() + stderr.getvalue()
        for text in (report_text, output_text):
            self.assertNotIn("password_hash", text.casefold())
            self.assertNotIn(legacy_secret, text)
            self.assertNotIn(legacy_local_path, text)
            self.assertNotIn("/Users/", text)
        report = json.loads(report_text)
        printed = json.loads(stdout.getvalue())
        self.assertNotIn("stale", report)
        self.assertTrue(report["valid"])
        self.assertEqual(report["stage"], "0.13.3A")
        self.assertEqual(report["status"], "REVIEW_REQUIRED")
        self.assertTrue(printed["valid"])

    def test_report_rejects_source_database_path_and_hardlink(self) -> None:
        for collision_kind in ("same_path", "hardlink"):
            with self.subTest(collision_kind=collision_kind), tempfile.TemporaryDirectory(
                dir=self.root
            ) as temporary:
                directory = Path(temporary)
                source_copy = directory / "source.db"
                shutil.copy2(self.source_db, source_copy)
                if collision_kind == "same_path":
                    report_target = source_copy
                else:
                    report_target = directory / "source-report-hardlink.db"
                    os.link(source_copy, report_target)
                source_before = sha256_file(source_copy)
                report_before = sha256_file(report_target)
                raw_before = _file_hashes(self.raw_dir)
                stdout = io.StringIO()
                stderr = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    return_code = migration_reference_data.main(
                        [
                            "report",
                            *self._cli_path_arguments(
                                source_db=source_copy,
                                report=report_target,
                            ),
                        ]
                    )
                self.assertEqual(return_code, 1)
                self.assertEqual(sha256_file(source_copy), source_before)
                self.assertEqual(sha256_file(report_target), report_before)
                self.assertEqual(_file_hashes(self.raw_dir), raw_before)
                combined = stdout.getvalue() + stderr.getvalue()
                self.assertNotIn(SENTINEL_PASSWORD_HASH, combined)
                self.assertNotIn("password_hash", combined.casefold())
                self.assertNotIn("/Users/", combined)

    def test_no_production_operations_or_production_references_are_loaded(self) -> None:
        with closing(self._connect_candidate()) as candidate:
            operation_counts = {
                table: int(
                    candidate.execute(
                        f'SELECT COUNT(*) FROM "{table}"'
                    ).fetchone()[0]
                )
                for table in PRODUCTION_OPERATIONAL_TABLES
            }
            production_reference_count = int(
                candidate.execute("SELECT COUNT(*) FROM reference_values").fetchone()[0]
            )
        self.assertEqual(set(operation_counts.values()), {0})
        self.assertEqual(production_reference_count, 0)

    def test_unknown_references_are_inactive_candidates_and_aliases_are_safe(self) -> None:
        with closing(self._connect_candidate()) as candidate:
            values = candidate.execute(
                """SELECT d.domain_key, v.canonical_value, v.active,
                          v.approval_status, v.scope_key
                   FROM reference_values_v2 v
                   JOIN reference_domains_v2 d ON d.id=v.domain_id
                   WHERE (d.domain_key='vendor' AND v.normalized_key IN ('acme new', 'xfusion'))
                      OR (d.domain_key='model' AND v.normalized_key IN ('r200', 'r220'))
                   ORDER BY d.domain_key, v.normalized_key"""
            ).fetchall()
            aliases = {
                str(row[0]): str(row[1])
                for row in candidate.execute(
                    """SELECT a.source_value, a.resolution_status
                       FROM reference_aliases_v2 a
                       JOIN reference_domains_v2 d ON d.id=a.domain_id
                       WHERE d.domain_key='vendor'"""
                )
            }
        self.assertGreaterEqual(len(values), 4)
        self.assertTrue(all(int(row[2]) == 0 for row in values))
        self.assertTrue(all(str(row[3]) == "CANDIDATE" for row in values))
        model_scopes = {
            (str(row[1]), str(row[4]))
            for row in values
            if str(row[0]) == "model"
        }
        self.assertEqual(model_scopes, {("R200", "acme new"), ("R220", "acme new")})
        self.assertEqual(aliases["  ACME NEW  "], "AUTO_APPROVED")
        self.assertEqual(aliases["Huawei"], "PENDING")

    def test_serials_are_sqlite_text_and_corrupted_values_never_get_a_match(self) -> None:
        with closing(self._connect_candidate()) as candidate:
            serials = candidate.execute(
                """SELECT excel_cell_coordinate, raw_xml_value,
                          source_serial_value, normalized_match_value,
                          preservation_status, typeof(source_serial_value),
                          typeof(normalized_match_value)
                   FROM migration_serial_cells
                   ORDER BY source_sheet, source_row, serial_role"""
            ).fetchall()
        self.assertTrue(serials)
        self.assertTrue(
            all(str(row[5]) == "text" and str(row[6]) == "text" for row in serials)
        )
        corrupted = [row for row in serials if str(row[4]) == "SOURCE_CORRUPTED"]
        self.assertEqual(len(corrupted), 1)
        self.assertEqual(str(corrupted[0][0]), "L3")
        self.assertEqual(str(corrupted[0][1]), "4.225112539E17")
        self.assertEqual(str(corrupted[0][2]), "4.225112539E17")
        self.assertEqual(str(corrupted[0][3]), "")
        safe = [row for row in serials if str(row[0]) == "L4"]
        self.assertEqual(str(safe[0][2]), "00012345")
        self.assertEqual(str(safe[0][3]), "00012345")

    def test_exported_reference_package_and_identifiers_are_text(self) -> None:
        package = read_text_xlsx(self.paths.reference_package)
        part_numbers = {
            row["part_number"] for row in package["CATALOG_ITEMS"]
        }
        self.assertTrue({"000PN200", "000PN220"}.issubset(part_numbers))
        for cell in iter_xlsx_cells(self.paths.reference_package):
            self.assertEqual(cell.excel_cell_type, "inlineStr")
            self.assertEqual(cell.excel_number_format, "@")

        serial_rows = read_text_csv(self.paths.serial_export)
        self.assertIn("00012345", {row["source_serial_value"] for row in serial_rows})
        corrupted = [
            row
            for row in serial_rows
            if row["preservation_status"] == "SOURCE_CORRUPTED"
        ]
        self.assertEqual(corrupted[0]["normalized_match_value"], "")

    def test_candidate_validation_and_sidecar_gate(self) -> None:
        report = validate_candidate(self.paths.candidate_db)
        self.assertTrue(report["valid"])
        self.assertEqual(report["reference_domains"], 20)
        self.assertEqual(report["staging_rows"], 3)
        self.assertEqual(report["serial_cells"], 4)
        self.assertEqual(report["source_corrupted_serial_cells"], 1)
        self.assertEqual(candidate_sidecars(self.paths.candidate_db), [])
        for path in (self.source_db, self.paths.candidate_db):
            for suffix in ("-wal", "-shm", "-journal"):
                self.assertFalse(Path(str(path) + suffix).exists())

    def test_cli_validation_is_successful_and_secret_free(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            return_code = migration_reference_data.main(
                ["validate-candidate", *self._cli_path_arguments()]
            )
        self.assertEqual(return_code, 0, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["valid"])
        self.assertTrue(payload["source_inspection"]["working_database"]["content_state_unchanged"])
        combined = stdout.getvalue() + stderr.getvalue()
        self.assertNotIn(SENTINEL_PASSWORD_HASH, combined)
        self.assertNotIn("password_hash", combined.casefold())
        self.assertEqual(sha256_file(self.source_db), self.source_sha_before)
        self.assertEqual(_file_hashes(self.raw_dir), self.raw_sha_before)

    def test_cli_rejects_source_database_as_candidate_output(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        before = sha256_file(self.source_db)
        arguments = self._cli_path_arguments(candidate=self.source_db)
        with redirect_stdout(stdout), redirect_stderr(stderr):
            return_code = migration_reference_data.main(
                ["build-candidate", "--overwrite", *arguments]
            )
        self.assertEqual(return_code, 1)
        self.assertIn("must be different files", stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(sha256_file(self.source_db), before)
        self.assertNotIn(SENTINEL_PASSWORD_HASH, stderr.getvalue())

    def test_build_requires_overwrite_and_successfully_rebuilds(self) -> None:
        with self.assertRaises(FileExistsError):
            build_candidate(self.paths)
        result = build_candidate(self.paths, overwrite=True)
        self.assertTrue(result.report["valid"])
        self.assertTrue(result.report["raw_sha_unchanged"])
        self.assertTrue(result.report["working_database_unchanged"])
        self.assertEqual(sha256_file(self.source_db), self.source_sha_before)
        self.assertEqual(_file_hashes(self.raw_dir), self.raw_sha_before)

    def test_export_failure_does_not_replace_previous_candidate_bundle(self) -> None:
        artifacts = (
            self.paths.candidate_db,
            self.paths.reference_package,
            self.paths.serial_export,
            self.paths.report,
        )
        hashes_before = {path: sha256_file(path) for path in artifacts}
        with patch(
            "inventory.migration.candidate_db.export_reference_package",
            side_effect=RuntimeError("injected export failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "injected export failure"):
                build_candidate(self.paths, overwrite=True)
        self.assertEqual(
            {path: sha256_file(path) for path in artifacts}, hashes_before
        )
        self.assertFalse(
            any(
                path.name.startswith(".ode-migration-candidate.")
                for path in self.workspace.iterdir()
            )
        )
        self.assertEqual(sha256_file(self.source_db), self.source_sha_before)
        self.assertEqual(_file_hashes(self.raw_dir), self.raw_sha_before)

    def _cli_path_arguments(
        self,
        *,
        candidate: Path | None = None,
        source_db: Path | None = None,
        report: Path | None = None,
    ) -> list[str]:
        return [
            "--source-db",
            str(source_db or self.source_db),
            "--raw-dir",
            str(self.raw_dir),
            "--normalized-dir",
            str(self.normalized_dir),
            "--candidate",
            str(candidate or self.paths.candidate_db),
            "--reference-package",
            str(self.paths.reference_package),
            "--serial-export",
            str(self.paths.serial_export),
            "--report",
            str(report or self.paths.report),
        ]


if __name__ == "__main__":
    unittest.main()
