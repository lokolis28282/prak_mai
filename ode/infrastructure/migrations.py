"""Manifest-verified, atomic creation of a new ODE 0.13 database."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from ode.application.config import DatabaseConfig
from ode.application.errors import DatabaseError, MigrationError
from ode.infrastructure.database import (
    ConnectionMode,
    SQLiteConnectionFactory,
    compute_schema_hash,
    require_immutable_snapshot_safe,
)
from ode.infrastructure.paths import DDL_ROOT, MANIFEST_PATH
from ode.system.models import MigrationEntry, MigrationStatus


_MIGRATION_NAME = re.compile(r"^V(?P<version>[0-9]{3})__.+\.sql$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class MigrationDefinition:
    version: int
    file: str
    sha256: str


@dataclass(frozen=True)
class SchemaManifest:
    schema_version: int
    application_id: int
    approved_schema_hash: str
    migrations: tuple[MigrationDefinition, ...]
    expected_migration_count: int
    expected_user_version: int


@dataclass(frozen=True)
class VerificationReport:
    schema_hash: str
    integrity_result: str
    foreign_key_violations: int
    schema_checks: tuple[tuple[str, str], ...]
    domain_invariants: tuple[tuple[str, int], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_hash": self.schema_hash,
            "integrity_result": self.integrity_result,
            "foreign_key_violations": self.foreign_key_violations,
            "schema_checks": dict(self.schema_checks),
            "domain_invariants": dict(self.domain_invariants),
        }


@dataclass(frozen=True)
class DatabaseCreateResult:
    database_path: str
    permissions: str
    verification: VerificationReport

    def to_dict(self) -> dict[str, object]:
        return {
            "database_path": self.database_path,
            "permissions": self.permissions,
            "verification": self.verification.to_dict(),
        }


def _require_mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise MigrationError("INVALID_SCHEMA_MANIFEST", f"{field} must be an object")
    return value


def _require_int(mapping: dict[str, object], field: str) -> int:
    value = mapping.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise MigrationError("INVALID_SCHEMA_MANIFEST", f"{field} must be an integer")
    return value


def _require_str(mapping: dict[str, object], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value:
        raise MigrationError("INVALID_SCHEMA_MANIFEST", f"{field} must be a string")
    return value


def load_schema_manifest(path: Path = MANIFEST_PATH) -> SchemaManifest:
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationError(
            "INVALID_SCHEMA_MANIFEST", "Schema manifest cannot be read"
        ) from exc
    mapping = _require_mapping(raw, "manifest")
    migration_values = mapping.get("migrations")
    if not isinstance(migration_values, list):
        raise MigrationError(
            "INVALID_SCHEMA_MANIFEST", "migrations must be an ordered array"
        )
    migrations: list[MigrationDefinition] = []
    for position, value in enumerate(migration_values, start=1):
        item = _require_mapping(value, f"migrations[{position - 1}]")
        migrations.append(
            MigrationDefinition(
                version=_require_int(item, "version"),
                file=_require_str(item, "file"),
                sha256=_require_str(item, "sha256"),
            )
        )
    return SchemaManifest(
        schema_version=_require_int(mapping, "schema_version"),
        application_id=_require_int(mapping, "application_id"),
        approved_schema_hash=_require_str(mapping, "approved_schema_hash"),
        migrations=tuple(migrations),
        expected_migration_count=_require_int(mapping, "expected_migration_count"),
        expected_user_version=_require_int(mapping, "expected_user_version"),
    )


class MigrationRunner:
    """Creates only absent targets; upgrades are deliberately outside this stage."""

    def __init__(
        self,
        config: DatabaseConfig,
        *,
        ddl_root: Path = DDL_ROOT,
        manifest_path: Path = MANIFEST_PATH,
    ) -> None:
        self._config = config
        self._ddl_root = ddl_root
        self._manifest_path = manifest_path

    @property
    def manifest(self) -> SchemaManifest:
        manifest = load_schema_manifest(self._manifest_path)
        self._validate_manifest_contract(manifest)
        return manifest

    def validate_sources(self) -> tuple[MigrationDefinition, ...]:
        manifest = self.manifest
        try:
            discovered = sorted(
                path.name for path in self._ddl_root.glob("V[0-9][0-9][0-9]__*.sql")
            )
        except OSError as exc:
            raise MigrationError(
                "MIGRATION_SOURCE_READ_FAILED",
                "Canonical migration sources could not be enumerated",
                details={"failure_type": type(exc).__name__},
            ) from exc
        expected = [migration.file for migration in manifest.migrations]
        if discovered != sorted(expected):
            missing = len(set(expected) - set(discovered))
            extra = len(set(discovered) - set(expected))
            raise MigrationError(
                "MIGRATION_SET_MISMATCH",
                "Canonical migration file set does not match the approved manifest",
                details={"missing_count": missing, "extra_count": extra},
            )
        seen_versions: set[int] = set()
        previous = 0
        for migration in manifest.migrations:
            if migration.version in seen_versions:
                raise MigrationError(
                    "DUPLICATE_MIGRATION_VERSION",
                    "Manifest contains a duplicate migration version",
                    details={"version": migration.version},
                )
            match = _MIGRATION_NAME.fullmatch(migration.file)
            if match is None or int(match.group("version")) != migration.version:
                raise MigrationError(
                    "MIGRATION_NAME_VERSION_MISMATCH",
                    "Migration filename and manifest version do not match",
                    details={"version": migration.version},
                )
            if migration.version != previous + 1:
                raise MigrationError(
                    "MIGRATION_ORDER_MISMATCH",
                    "Manifest migration versions must be contiguous and ordered",
                    details={"version": migration.version},
                )
            seen_versions.add(migration.version)
            previous = migration.version
            try:
                source = (self._ddl_root / migration.file).read_bytes()
            except OSError as exc:
                raise MigrationError(
                    "MIGRATION_SOURCE_READ_FAILED",
                    "Canonical migration source could not be read",
                    details={
                        "version": migration.version,
                        "failure_type": type(exc).__name__,
                    },
                ) from exc
            digest = hashlib.sha256(source).hexdigest()
            if digest != migration.sha256:
                raise MigrationError(
                    "SCHEMA_MIGRATION_CHECKSUM_MISMATCH",
                    "Canonical migration checksum does not match the approved manifest",
                    details={"version": migration.version},
                )
        return manifest.migrations

    def create(self) -> DatabaseCreateResult:
        target = self._config.db_path
        if self._config.read_only:
            raise MigrationError(
                "READ_ONLY_CONFIGURATION",
                "Database creation requires a write-enabled configuration",
            )
        if target.exists():
            raise MigrationError(
                "DATABASE_ALREADY_EXISTS", "Target database already exists"
            )
        migrations = self.validate_sources()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise MigrationError(
                "DATABASE_CREATE_FAILED",
                "Target database directory could not be prepared",
                details={"failure_type": type(exc).__name__},
            ) from exc
        candidate = target.with_name(
            f".{target.stem}.candidate-{uuid.uuid4().hex}{target.suffix}"
        )
        candidate_config = DatabaseConfig(
            db_path=candidate,
            environment=self._config.environment,
            busy_timeout_ms=self._config.busy_timeout_ms,
            read_only=False,
            expected_schema_version=self._config.expected_schema_version,
            expected_application_id=self._config.expected_application_id,
            external_path_override=self._config.external_path_override,
        )
        published_by_runner = False
        try:
            candidate.touch(mode=0o600, exist_ok=False)
            os.chmod(candidate, 0o600)
            factory = SQLiteConnectionFactory(candidate_config)
            with factory.connect(ConnectionMode.MIGRATION) as connection:
                for migration in migrations:
                    sql = (self._ddl_root / migration.file).read_text(encoding="utf-8")
                    connection.executescript(sql)
                    connection.execute("BEGIN IMMEDIATE")
                    connection.execute(
                        "INSERT INTO schema_migrations "
                        "(version, name, checksum, applied_at_us, applied_by, application_version) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            migration.version,
                            migration.file,
                            bytes.fromhex(migration.sha256),
                            max(time.time_ns() // 1_000, 1),
                            "ode-db-create",
                            "0.13.1-foundation",
                        ),
                    )
                    self._verify_applied_prefix(connection, migrations, migration.version)
                    connection.commit()
                report = self._verify_connection(connection)
            self._assert_no_sidecars(candidate)
            self._fsync_file(candidate)
            self._publish_absent_target(candidate, target)
            published_by_runner = True
            return DatabaseCreateResult(
                database_path=str(target), permissions="0600", verification=report
            )
        except MigrationError:
            self._cleanup_candidate(candidate)
            raise
        except DatabaseError as exc:
            self._cleanup_candidate(candidate)
            raise MigrationError(
                "DATABASE_CREATE_FAILED",
                "Candidate database creation failed; target was not published",
                details={"failure_type": exc.code},
            ) from exc
        except (OSError, sqlite3.Error) as exc:
            self._cleanup_candidate(candidate)
            raise MigrationError(
                "DATABASE_CREATE_FAILED",
                "Candidate database creation failed; target was not published",
                details={"failure_type": type(exc).__name__},
            ) from exc
        except BaseException:
            self._cleanup_candidate(candidate)
            if published_by_runner:
                try:
                    target.unlink()
                except FileNotFoundError:
                    pass
            raise

    def migration_status(self) -> MigrationStatus:
        manifest = self.manifest
        if not self._config.db_path.exists():
            raise MigrationError("DATABASE_NOT_FOUND", "Database file does not exist")
        require_immutable_snapshot_safe(self._config.db_path)
        factory = SQLiteConnectionFactory(self._config)
        try:
            with factory.connect(ConnectionMode.IMMUTABLE_READ_ONLY) as connection:
                status = self._migration_status(connection, manifest)
            require_immutable_snapshot_safe(self._config.db_path)
            return status
        except MigrationError:
            raise
        except Exception as exc:
            raise MigrationError(
                "DATABASE_STATUS_FAILED", "Database migration status could not be read"
            ) from exc

    def verify(self) -> VerificationReport:
        self.validate_sources()
        if not self._config.db_path.exists():
            raise MigrationError("DATABASE_NOT_FOUND", "Database file does not exist")
        require_immutable_snapshot_safe(self._config.db_path)
        factory = SQLiteConnectionFactory(self._config)
        try:
            with factory.connect(ConnectionMode.IMMUTABLE_READ_ONLY) as connection:
                report = self._verify_connection(connection)
            require_immutable_snapshot_safe(self._config.db_path)
            return report
        except MigrationError:
            raise
        except Exception as exc:
            raise MigrationError(
                "DATABASE_VERIFY_FAILED", "Database verification could not complete"
            ) from exc

    def _validate_manifest_contract(self, manifest: SchemaManifest) -> None:
        if (
            manifest.schema_version != self._config.expected_schema_version
            or manifest.expected_user_version != self._config.expected_schema_version
            or manifest.application_id != self._config.expected_application_id
            or manifest.expected_migration_count != len(manifest.migrations)
            or manifest.expected_migration_count != manifest.schema_version
        ):
            raise MigrationError(
                "MANIFEST_CONTRACT_MISMATCH",
                "Manifest does not match configured approved schema expectations",
            )
        if not _SHA256.fullmatch(manifest.approved_schema_hash) or any(
            not _SHA256.fullmatch(migration.sha256)
            or Path(migration.file).name != migration.file
            for migration in manifest.migrations
        ):
            raise MigrationError(
                "INVALID_SCHEMA_MANIFEST",
                "Manifest hashes or migration filenames are malformed",
            )

    def _verify_applied_prefix(
        self,
        connection: sqlite3.Connection,
        migrations: tuple[MigrationDefinition, ...],
        version: int,
    ) -> None:
        application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if application_id != self._config.expected_application_id:
            raise MigrationError(
                "INVALID_APPLICATION_ID", "Migration changed the application ID"
            )
        if user_version != version:
            raise MigrationError(
                "SCHEMA_VERSION_MISMATCH", "Migration did not set its expected user_version"
            )
        rows = connection.execute(
            "SELECT version, name, hex(checksum) FROM schema_migrations ORDER BY version"
        ).fetchall()
        expected = migrations[:version]
        if len(rows) != version or any(
            int(row[0]) != item.version
            or str(row[1]) != item.file
            or str(row[2]).lower() != item.sha256
            for row, item in zip(rows, expected, strict=True)
        ):
            raise MigrationError(
                "MIGRATION_REGISTRY_MISMATCH",
                "Migration registry does not match the applied approved prefix",
            )

    def _migration_status(
        self, connection: sqlite3.Connection, manifest: SchemaManifest
    ) -> MigrationStatus:
        application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        expected = tuple(
            MigrationEntry(item.version, item.file, item.sha256)
            for item in manifest.migrations
        )
        exists = connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        applied: tuple[MigrationEntry, ...] = ()
        if exists is not None:
            rows = connection.execute(
                "SELECT version, name, hex(checksum) FROM schema_migrations ORDER BY version"
            ).fetchall()
            applied = tuple(
                MigrationEntry(int(row[0]), str(row[1]), str(row[2]).lower()) for row in rows
            )
        ready = (
            user_version == manifest.expected_user_version
            and application_id == manifest.application_id
            and applied == expected
        )
        return MigrationStatus(
            expected_schema_version=manifest.expected_user_version,
            user_version=user_version,
            expected_application_id=manifest.application_id,
            application_id=application_id,
            expected_migration_count=manifest.expected_migration_count,
            applied_migration_count=len(applied),
            expected=expected,
            applied=applied,
            ready=ready,
        )

    def _verify_connection(self, connection: sqlite3.Connection) -> VerificationReport:
        manifest = self.manifest
        status = self._migration_status(connection, manifest)
        if status.application_id != manifest.application_id:
            raise MigrationError(
                "INVALID_APPLICATION_ID", "Database application_id is not ODE 0.13"
            )
        if status.user_version != manifest.expected_user_version:
            raise MigrationError(
                "SCHEMA_VERSION_MISMATCH", "Database user_version is unsupported"
            )
        if not status.ready:
            raise MigrationError(
                "MIGRATION_REGISTRY_MISMATCH",
                "Applied migration registry does not match the approved manifest",
            )
        schema_hash = compute_schema_hash(connection)
        if schema_hash != manifest.approved_schema_hash:
            raise MigrationError(
                "SCHEMA_HASH_MISMATCH",
                "Database schema hash does not match the approved schema",
            )
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise MigrationError("INTEGRITY_FAILED", "Database integrity_check failed")
        foreign_keys = len(connection.execute("PRAGMA foreign_key_check").fetchall())
        if foreign_keys:
            raise MigrationError(
                "FOREIGN_KEY_FAILED",
                "Database contains foreign key violations",
                details={"violation_count": foreign_keys},
            )
        schema_checks = self._execute_proof(
            connection, self._ddl_root / "verify_schema.sql"
        )
        bad_schema = [
            (name, value)
            for name, value in schema_checks
            if not (
                value == "PASS"
                or (name == "integrity_check" and value == "ok")
                or (name == "foreign_key_violations" and value == "0")
                or (name == "schema_counts" and value == '{"tables":41,"indexes":73,"triggers":73,"views":3}')
            )
        ]
        if bad_schema:
            raise MigrationError(
                "SCHEMA_VERIFICATION_FAILED",
                "Approved schema verification proof reported a failure",
                details={"failure_count": len(bad_schema)},
            )
        invariant_values = self._execute_proof(
            connection, self._ddl_root / "verify_domain_invariants.sql"
        )
        invariants: list[tuple[str, int]] = []
        for name, value in invariant_values:
            try:
                count = int(value)
            except ValueError as exc:
                raise MigrationError(
                    "DOMAIN_VERIFICATION_FAILED",
                    "Domain invariant proof returned a non-integer result",
                ) from exc
            invariants.append((name, count))
        violations = sum(count for _, count in invariants)
        if violations:
            raise MigrationError(
                "DOMAIN_VERIFICATION_FAILED",
                "Domain invariant proof reported violations",
                details={"violation_count": violations},
            )
        return VerificationReport(
            schema_hash=schema_hash,
            integrity_result=integrity,
            foreign_key_violations=foreign_keys,
            schema_checks=tuple(schema_checks),
            domain_invariants=tuple(invariants),
        )

    @staticmethod
    def _execute_proof(
        connection: sqlite3.Connection, script_path: Path
    ) -> list[tuple[str, str]]:
        statements: list[str] = []
        buffer = ""
        for line in script_path.read_text(encoding="utf-8").splitlines(keepends=True):
            buffer += line
            if sqlite3.complete_statement(buffer):
                statements.append(buffer)
                buffer = ""
        if buffer.strip():
            raise MigrationError(
                "INVALID_VERIFICATION_SCRIPT", "Verification SQL has an incomplete statement"
            )
        results: list[tuple[str, str]] = []
        for statement in statements:
            cursor = connection.execute(statement)
            if cursor.description is not None:
                for row in cursor.fetchall():
                    results.append((str(row[0]), str(row[1])))
        return results

    @staticmethod
    def _assert_no_sidecars(path: Path) -> None:
        if any(Path(f"{path}{suffix}").exists() for suffix in ("-wal", "-shm", "-journal")):
            raise MigrationError(
                "DATABASE_SIDECAR_REMAINS", "Closed migration candidate has SQLite sidecars"
            )

    @staticmethod
    def _fsync_file(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _publish_absent_target(candidate: Path, target: Path) -> None:
        try:
            os.link(candidate, target)
        except FileExistsError as exc:
            raise MigrationError(
                "DATABASE_ALREADY_EXISTS", "Target database already exists"
            ) from exc
        try:
            directory = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            candidate.unlink()
        except BaseException:
            try:
                target.unlink()
            except FileNotFoundError:
                pass
            raise

    @staticmethod
    def _cleanup_candidate(candidate: Path) -> None:
        for path in (
            candidate,
            Path(f"{candidate}-wal"),
            Path(f"{candidate}-shm"),
            Path(f"{candidate}-journal"),
        ):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
