from __future__ import annotations

import hashlib
import os
import sqlite3
import unicodedata
import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

from ode.application.config import DatabaseConfig, Environment
from ode.application.errors import (
    ConfigurationError,
    NestedUnitOfWorkError,
    ReadOnlyMutationError,
    UnitOfWorkBeginError,
    UnitOfWorkCloseError,
    UnitOfWorkCommitError,
    UnitOfWorkError,
    UnitOfWorkRollbackError,
)
from ode.infrastructure.database import (
    ConnectionMode,
    SQLiteConnectionFactory,
    SqliteUnitOfWork,
)
from ode.infrastructure.migrations import MigrationRunner
from ode.infrastructure.paths import LOCAL_DATABASE_ROOT, PROJECT_ROOT
from tests.ode013.support import config


class _FailingConnection:
    def __init__(
        self,
        *,
        begin_error: sqlite3.Error | None = None,
        commit_error: sqlite3.Error | None = None,
        rollback_error: sqlite3.Error | None = None,
    ) -> None:
        self.begin_error = begin_error
        self.commit_error = commit_error
        self.rollback_error = rollback_error
        self.in_transaction = True
        self.closed = False
        self.calls: list[str] = []

    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> object:
        del parameters
        self.calls.append(sql)
        if sql.startswith("BEGIN") and self.begin_error is not None:
            raise self.begin_error
        return object()

    def commit(self) -> None:
        self.calls.append("commit")
        if self.commit_error is not None:
            raise self.commit_error
        self.in_transaction = False

    def rollback(self) -> None:
        self.calls.append("rollback")
        if self.rollback_error is not None:
            raise self.rollback_error
        self.in_transaction = False


class _FailingManager:
    def __init__(
        self, connection: _FailingConnection, close_error: sqlite3.Error | None
    ) -> None:
        self.connection = connection
        self.close_error = close_error

    def __enter__(self) -> _FailingConnection:
        return self.connection

    def __exit__(self, *_args: object) -> bool:
        self.connection.calls.append("close")
        self.connection.closed = True
        if self.close_error is not None:
            raise self.close_error
        return False


class _FailingFactory:
    def __init__(
        self, connection: _FailingConnection, close_error: sqlite3.Error | None = None
    ) -> None:
        self.connection = connection
        self.close_error = close_error

    def connect(self, _mode: ConnectionMode) -> _FailingManager:
        return _FailingManager(self.connection, self.close_error)


class PathPolicyTests(unittest.TestCase):
    def test_production_database_is_always_rejected(self) -> None:
        with self.assertRaises(ConfigurationError) as caught:
            config(PROJECT_ROOT / "data" / "warehouse.db")
        self.assertEqual(caught.exception.code, "PRODUCTION_DATABASE_FORBIDDEN")

    def test_raw_source_directory_is_rejected_even_with_override(self) -> None:
        with self.assertRaises(ConfigurationError) as caught:
            DatabaseConfig.create(
                PROJECT_ROOT / "migration_inputs" / "raw" / "not-a-target.db",
                environment=Environment.TEST,
                read_only=False,
                expected_schema_version=8,
                expected_application_id=1329874225,
                allow_external_dev_path=True,
            )
        self.assertEqual(caught.exception.code, "SOURCE_PATH_FORBIDDEN")

    def test_allowed_local_and_system_temp_paths(self) -> None:
        local = config(LOCAL_DATABASE_ROOT / "allowed.db")
        self.assertFalse(local.external_path_override)
        with TemporaryDirectory() as directory:
            temporary = config(Path(directory) / "allowed.db")
            self.assertFalse(temporary.external_path_override)

    def test_external_path_requires_explicit_override_and_is_reported(self) -> None:
        external = PROJECT_ROOT / "external-development.db"
        with self.assertRaises(ConfigurationError) as caught:
            config(external)
        self.assertEqual(caught.exception.code, "EXTERNAL_PATH_REQUIRES_OVERRIDE")
        allowed = DatabaseConfig.create(
            external,
            environment=Environment.DEVELOPMENT,
            read_only=False,
            expected_schema_version=8,
            expected_application_id=1329874225,
            allow_external_dev_path=True,
        )
        self.assertTrue(allowed.external_path_override)

    @unittest.skipIf(os.name == "nt", "requires POSIX symlink support")
    def test_symlink_escape_from_local_root_is_rejected(self) -> None:
        LOCAL_DATABASE_ROOT.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory() as directory:
            link = LOCAL_DATABASE_ROOT / f"escape-{uuid.uuid4().hex}"
            link.symlink_to(directory, target_is_directory=True)
            try:
                with self.assertRaises(ConfigurationError) as caught:
                    config(link / "escaped.db")
                self.assertEqual(caught.exception.code, "SYMLINK_ESCAPE")
            finally:
                link.unlink()

    def test_malformed_path_is_typed_rejection(self) -> None:
        with self.assertRaises(ConfigurationError) as caught:
            config(Path("bad\x00path.db"))
        self.assertEqual(caught.exception.code, "INVALID_DATABASE_PATH")

    def test_unicode_normalization_remains_filesystem_path_identity(self) -> None:
        with TemporaryDirectory() as directory:
            nfc = Path(directory) / "café.db"
            nfd = Path(directory) / unicodedata.normalize("NFD", "café.db")
            self.assertNotEqual(config(nfc).db_path, config(nfd).db_path)


class ConnectionAndUnitOfWorkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.path = Path(self.temporary.name) / "uow.db"
        self.config = config(self.path)
        MigrationRunner(self.config).create()
        self.factory = SQLiteConnectionFactory(self.config)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_connection_pragmas_and_close(self) -> None:
        with self.factory.connect(ConnectionMode.WRITE) as connection:
            handle = connection
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA busy_timeout").fetchone()[0], 10000)
            self.assertEqual(connection.execute("PRAGMA trusted_schema").fetchone()[0], 0)
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        with self.assertRaises(sqlite3.ProgrammingError):
            handle.execute("SELECT 1")

    def test_read_only_configuration_cannot_open_write_connection(self) -> None:
        read_factory = SQLiteConnectionFactory(config(self.path, read_only=True))
        from ode.application.errors import DatabaseError

        with self.assertRaises(DatabaseError) as caught:
            with read_factory.connect(ConnectionMode.WRITE):
                pass
        self.assertEqual(caught.exception.code, "READ_ONLY_CONFIGURATION")

    def test_commit_is_explicit_and_no_commit_rolls_back(self) -> None:
        with SqliteUnitOfWork(self.factory) as uow:
            uow.execute(
                "INSERT INTO schema_migrations VALUES (99, 'test', ?, 1, 'test', 'test')",
                (b"x" * 32,),
            )
            uow.commit()
        with self.factory.connect(ConnectionMode.READ_ONLY) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM schema_migrations WHERE version=99"
                ).fetchone()[0],
                1,
            )
        with SqliteUnitOfWork(self.factory) as uow:
            uow.execute("DELETE FROM schema_migrations WHERE version=99")
        with self.factory.connect(ConnectionMode.READ_ONLY) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM schema_migrations WHERE version=99"
                ).fetchone()[0],
                1,
            )

    def test_exception_and_failed_constraint_rollback_without_partial_rows(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "preserved"):
            with SqliteUnitOfWork(self.factory) as uow:
                uow.execute(
                    "INSERT INTO schema_migrations VALUES (98, 'first', ?, 1, 'test', 'test')",
                    (b"x" * 32,),
                )
                uow.commit()
                raise RuntimeError("preserved")
        with self.assertRaises(UnitOfWorkError) as caught:
            with SqliteUnitOfWork(self.factory) as uow:
                uow.execute(
                    "INSERT INTO schema_migrations VALUES (97, 'valid-first', ?, 1, 'test', 'test')",
                    (b"x" * 32,),
                )
                uow.execute(
                    "INSERT INTO schema_migrations VALUES (96, 'invalid', ?, 1, 'test', 'test')",
                    (b"short",),
                )
                uow.commit()
        self.assertEqual(caught.exception.code, "UNIT_OF_WORK_SQL_FAILED")
        with self.factory.connect(ConnectionMode.READ_ONLY) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM schema_migrations WHERE version IN (97,98)"
                ).fetchone()[0],
                0,
            )

    def test_nested_write_is_rejected(self) -> None:
        with SqliteUnitOfWork(self.factory):
            with self.assertRaises(NestedUnitOfWorkError) as caught:
                with SqliteUnitOfWork(self.factory):
                    pass
        self.assertEqual(caught.exception.code, "NESTED_WRITE_UNIT_OF_WORK")

    def test_read_only_mutation_is_typed_and_rolled_back(self) -> None:
        with SqliteUnitOfWork(self.factory, read_only=True) as uow:
            self.assertEqual(uow.execute("SELECT count(*) FROM users").fetchone()[0], 0)
            with self.assertRaises(ReadOnlyMutationError) as caught:
                uow.execute("DELETE FROM schema_migrations")
        self.assertEqual(caught.exception.code, "READ_ONLY_MUTATION")

    def test_real_v005_deferred_fk_commit_is_typed_and_fully_rolled_back(self) -> None:
        with SqliteUnitOfWork(self.factory) as uow:
            uow.execute(
                "INSERT INTO users "
                "(user_id, public_id, login_key, display_name, password_hash, status, "
                "created_at_us, updated_at_us) VALUES (1, ?, 'repro', 'Repro', ?, "
                "'ACTIVE', 1, 1)",
                ("u" * 32, "$argon2id$" + "x" * 30),
            )
            uow.execute(
                "INSERT INTO import_commits "
                "(import_commit_id, public_id, import_kind, source_object_key, "
                "source_file_name, source_sha256, source_size_bytes, template_version, "
                "parser_version, schema_version, preview_digest, manifest_json, "
                "committed_by_user_id, actor_display_name, committed_at_us, "
                "idempotency_key, correlation_id) VALUES "
                "(1, ?, 'FULL_INVENTORY', 'source-object-key', 'repro.csv', ?, 1, "
                "'1', '1', '8', ?, '{}', 1, 'Repro', 1, "
                "'idempotency-key-1', 'correlation-1')",
                ("c" * 32, b"x" * 32, b"y" * 32),
            )
            uow.execute(
                "INSERT INTO inventory_sessions "
                "(session_id, public_id, import_commit_id, scope_type, scope_json, "
                "status, source_sha256, template_version, parser_version, "
                "schema_version, preview_digest, freeze_ledger_cutoff, "
                "freeze_started_at_us, effective_at_us, count_started_at_us, "
                "count_finished_at_us, approved_by_user_id, actor_display_name, "
                "approved_at_us, approval_idempotency_key, created_at_us, updated_at_us) "
                "VALUES (1, ?, 1, 'FULL', '{}', 'APPROVED', ?, '1', '1', '8', ?, "
                "0, 1, 1, 1, 1, 1, 'Repro', 1, 'approval-key-0001', 1, 1)",
                ("s" * 32, b"x" * 32, b"y" * 32),
            )
            uow.commit()

        failed = SqliteUnitOfWork(self.factory)
        handle: sqlite3.Connection | None = None
        with self.assertRaises(UnitOfWorkCommitError) as caught:
            with failed as uow:
                handle = uow.connection
                uow.execute(
                    "INSERT INTO inventory_snapshots "
                    "(snapshot_id, public_id, session_id, superseded_by_snapshot_id, "
                    "ledger_cutoff, effective_at_us, status, is_active, item_count, "
                    "totals_json, content_checksum, approved_by_user_id, "
                    "actor_display_name, approved_at_us) VALUES "
                    "(1, ?, 1, 999, 0, 1, 'SUPERSEDED', 0, 0, '{}', ?, 1, "
                    "'Repro', 1)",
                    ("n" * 32, b"z" * 32),
                )
                uow.commit()
        self.assertEqual(caught.exception.code, "UNIT_OF_WORK_COMMIT_FAILED")
        self.assertIsInstance(caught.exception.__cause__, sqlite3.IntegrityError)
        self.assertEqual(caught.exception.body.details["sqlite_error"], "IntegrityError")
        self.assertIsNotNone(handle)
        with self.assertRaises(sqlite3.ProgrammingError):
            handle.execute("SELECT 1")
        with self.assertRaises(UnitOfWorkError) as inactive:
            failed.connection.execute("SELECT 1")
        self.assertEqual(inactive.exception.code, "UNIT_OF_WORK_NOT_ACTIVE")
        with self.factory.connect(ConnectionMode.READ_ONLY) as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) FROM inventory_snapshots").fetchone()[0],
                0,
            )
        with SqliteUnitOfWork(self.factory) as reusable:
            reusable.execute(
                "INSERT INTO schema_migrations VALUES "
                "(99, 'state-clean', ?, 1, 'test', 'test')",
                (b"s" * 32,),
            )
            reusable.commit()

    def test_immediate_fk_check_unique_and_direct_sqlite_failures_are_typed(self) -> None:
        statements = (
            (
                "immediate-fk",
                "INSERT INTO user_roles "
                "(user_role_id, user_id, role_id, assigned_at_us) "
                "VALUES (1, 999, 999, 1)",
                (),
            ),
            (
                "check",
                "INSERT INTO schema_migrations VALUES "
                "(98, 'bad-check', ?, 1, 'test', 'test')",
                (b"short",),
            ),
            (
                "unique",
                "INSERT INTO schema_migrations VALUES "
                "(8, 'duplicate', ?, 1, 'test', 'test')",
                (b"x" * 32,),
            ),
        )
        for label, statement, parameters in statements:
            with self.subTest(label=label):
                with self.assertRaises(UnitOfWorkError) as caught:
                    with SqliteUnitOfWork(self.factory) as uow:
                        uow.execute(statement, parameters)
                        uow.commit()
                self.assertEqual(caught.exception.code, "UNIT_OF_WORK_SQL_FAILED")
                self.assertIsInstance(caught.exception.__cause__, sqlite3.IntegrityError)
        with self.assertRaises(UnitOfWorkError) as direct:
            with SqliteUnitOfWork(self.factory) as uow:
                uow.connection.execute("SELECT * FROM table_that_does_not_exist")
        self.assertEqual(direct.exception.code, "UNIT_OF_WORK_SQL_FAILED")
        self.assertIsInstance(direct.exception.__cause__, sqlite3.OperationalError)

    def test_programmer_exception_is_preserved_and_rolls_back(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "programmer failure") as caught:
            with SqliteUnitOfWork(self.factory) as uow:
                uow.execute(
                    "INSERT INTO schema_migrations VALUES "
                    "(99, 'programmer', ?, 1, 'test', 'test')",
                    (b"p" * 32,),
                )
                uow.commit()
                raise RuntimeError("programmer failure")
        self.assertIsNone(caught.exception.__cause__)
        with self.factory.connect(ConnectionMode.READ_ONLY) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM schema_migrations WHERE version = 99"
                ).fetchone()[0],
                0,
            )

    def test_transaction_control_and_ddl_are_rejected_without_partial_writes(self) -> None:
        for statement, expected in (
            ("/* comment */ COMMIT", "UNIT_OF_WORK_TRANSACTION_CONTROL_FORBIDDEN"),
            ("-- comment\nCREATE TABLE forbidden(id INTEGER)", "UNIT_OF_WORK_DDL_FORBIDDEN"),
        ):
            with self.subTest(statement=statement):
                with self.assertRaises(UnitOfWorkError) as caught:
                    with SqliteUnitOfWork(self.factory) as uow:
                        uow.execute(
                            "INSERT INTO schema_migrations VALUES "
                            "(99, 'guarded', ?, 1, 'test', 'test')",
                            (b"g" * 32,),
                        )
                        uow.execute(statement)
                        uow.commit()
                self.assertEqual(caught.exception.code, expected)
        with self.factory.connect(ConnectionMode.READ_ONLY) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM schema_migrations WHERE version = 99"
                ).fetchone()[0],
                0,
            )
            self.assertIsNone(
                connection.execute(
                    "SELECT 1 FROM sqlite_schema WHERE name = 'forbidden'"
                ).fetchone()
            )

    def test_attach_detach_and_parameterized_variants_are_forbidden(self) -> None:
        victim = self.path.parent / "victim.sqlite3"
        victim_connection = sqlite3.connect(victim)
        victim_connection.execute("CREATE TABLE untouched(id INTEGER PRIMARY KEY, value TEXT)")
        victim_connection.execute("INSERT INTO untouched VALUES (1, 'before')")
        victim_connection.commit()
        victim_connection.close()
        before = (
            hashlib.sha256(victim.read_bytes()).hexdigest(),
            victim.stat().st_mtime_ns,
        )
        statements = (
            ("ATTACH DATABASE ? AS victim", (str(victim),)),
            ("attach database ? as victim", (str(victim),)),
            ("/* comment */ ATTACH DATABASE ? AS victim", (str(victim),)),
            ("-- comment\nATTACH DATABASE ? AS victim", (str(victim),)),
            ("ATTACH ? AS victim", (str(victim),)),
            ("ATTACH DATABASE ? AS victim; SELECT 1", (str(victim),)),
            ("DETACH DATABASE victim", ()),
        )
        for statement, parameters in statements:
            with self.subTest(statement=statement):
                with self.assertRaises(UnitOfWorkError) as caught:
                    with SqliteUnitOfWork(self.factory) as uow:
                        uow.execute(
                            "INSERT INTO schema_migrations VALUES "
                            "(99, 'attach-rollback', ?, 1, 'test', 'test')",
                            (b"a" * 32,),
                        )
                        uow.execute(statement, parameters)
                        uow.commit()
                self.assertEqual(caught.exception.code, "SQL_OPERATION_FORBIDDEN")
        self.assertEqual(before, (hashlib.sha256(victim.read_bytes()).hexdigest(), victim.stat().st_mtime_ns))
        with self.factory.connect(ConnectionMode.READ_ONLY) as connection:
            self.assertIsNone(
                connection.execute(
                    "SELECT 1 FROM pragma_database_list WHERE name = 'victim'"
                ).fetchone()
            )

    def test_runtime_pragma_policy_is_closed(self) -> None:
        pragmas = (
            "PRAGMA writable_schema=ON",
            "pragma writable_schema(1)",
            "PRAGMA main.writable_schema = ON",
            "PRAGMA foreign_keys=OFF",
            "PRAGMA trusted_schema=ON",
            "PRAGMA journal_mode=DELETE",
            "PRAGMA locking_mode=EXCLUSIVE",
            "PRAGMA synchronous=OFF",
            "PRAGMA temp_store=FILE",
            "PRAGMA schema_version=1",
            "PRAGMA user_version=1",
            "PRAGMA application_id=1",
            "PRAGMA recursive_triggers=OFF",
            "PRAGMA defer_foreign_keys=ON",
            "PRAGMA ignore_check_constraints=ON",
            "/* comment */ PrAgMa writable_schema=ON",
        )
        for statement in pragmas:
            with self.subTest(statement=statement):
                with self.assertRaises(UnitOfWorkError) as caught:
                    with SqliteUnitOfWork(self.factory) as uow:
                        uow.execute(statement)
                self.assertEqual(caught.exception.code, "SQL_OPERATION_FORBIDDEN")
        with self.factory.connect(ConnectionMode.READ_ONLY) as connection:
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA trusted_schema").fetchone()[0], 0)

    def test_system_schema_mutations_are_authorizer_forbidden(self) -> None:
        statements = (
            "INSERT INTO sqlite_master(type,name,tbl_name,rootpage,sql) VALUES "
            "('table','evil','evil',0,'CREATE TABLE evil(id INTEGER)')",
            "UPDATE sqlite_schema SET sql = sql WHERE name = 'users'",
            "DELETE FROM sqlite_master WHERE name = 'users'",
            "INSERT INTO main.sqlite_master(type,name,tbl_name,rootpage,sql) "
            "VALUES ('table','evil2','evil2',0,'CREATE TABLE evil2(id INTEGER)')",
            "INSERT INTO \"sqlite_master\"(type,name,tbl_name,rootpage,sql) "
            "VALUES ('table','evil3','evil3',0,'CREATE TABLE evil3(id INTEGER)')",
            "INSERT INTO temp.sqlite_master(type,name,tbl_name,rootpage,sql) "
            "VALUES ('table','evil4','evil4',0,'CREATE TABLE evil4(id INTEGER)')",
        )
        for statement in statements:
            with self.subTest(statement=statement):
                with self.assertRaises(UnitOfWorkError) as caught:
                    with SqliteUnitOfWork(self.factory) as uow:
                        uow.execute(statement)
                self.assertEqual(caught.exception.code, "SQL_OPERATION_FORBIDDEN")
        with self.factory.connect(ConnectionMode.READ_ONLY) as connection:
            self.assertIsNone(
                connection.execute(
                    "SELECT 1 FROM sqlite_schema WHERE name LIKE 'evil%'"
                ).fetchone()
            )
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_allowlisted_dml_with_cte_literals_comments_and_parameters(self) -> None:
        with SqliteUnitOfWork(self.factory) as uow:
            uow.execute(
                "INSERT INTO schema_migrations VALUES "
                "(90, 'CREATE DROP PRAGMA COMMIT', ?, 1, 'test', 'test')",
                (b"d" * 32,),
            )
            uow.execute(
                "/* ordinary comment */ UPDATE schema_migrations "
                "SET applied_by = ? WHERE version = 90",
                ("updated",),
            )
            self.assertEqual(
                uow.execute("SELECT \"ATTACH\" AS attach_identifier").fetchone()[0],
                "ATTACH",
            )
            self.assertEqual(
                uow.execute("WITH selected AS (SELECT version FROM schema_migrations) "
                            "SELECT count(*) FROM selected").fetchone()[0],
                9,
            )
            uow.execute(
                "WITH candidate(version, name, checksum, applied_at_us, applied_by, "
                "application_version) AS (SELECT 91, 'with-insert', ?, 1, 'test', 'test') "
                "INSERT INTO schema_migrations "
                "SELECT version, name, checksum, applied_at_us, applied_by, "
                "application_version FROM candidate",
                (b"w" * 32,),
            )
            uow.execute("DELETE FROM schema_migrations WHERE version IN (90, 91)")
            uow.commit()
        with self.assertRaises(UnitOfWorkError) as multiple:
            with SqliteUnitOfWork(self.factory) as uow:
                uow.execute("SELECT 1; SELECT 2")
        self.assertEqual(multiple.exception.code, "SQL_OPERATION_FORBIDDEN")

    def test_authorizer_blocks_raw_connection_attach_and_temp_schema(self) -> None:
        victim = self.path.parent / "authorizer-victim.db"
        sqlite3.connect(victim).close()
        with SqliteUnitOfWork(self.factory) as uow:
            with self.assertRaises(sqlite3.DatabaseError):
                uow.connection.execute("ATTACH DATABASE ? AS victim", (str(victim),))
            with self.assertRaises(sqlite3.DatabaseError):
                uow.connection.execute("CREATE TEMP TABLE hidden(id INTEGER)")

    def test_closed_write_connection_leaves_no_sidecars(self) -> None:
        with self.factory.connect(ConnectionMode.WRITE) as connection:
            connection.execute("SELECT 1").fetchone()
        self.assertFalse(Path(f"{self.path}-wal").exists())
        self.assertFalse(Path(f"{self.path}-shm").exists())


class UnitOfWorkFailurePrecedenceTests(unittest.TestCase):
    def test_begin_and_close_failures_are_typed_and_state_is_cleared(self) -> None:
        connection = _FailingConnection(
            begin_error=sqlite3.OperationalError("begin failed")
        )
        uow = SqliteUnitOfWork(
            _FailingFactory(connection, sqlite3.OperationalError("close failed"))
        )
        with self.assertRaises(UnitOfWorkBeginError) as caught:
            with uow:
                pass
        self.assertEqual(caught.exception.code, "UNIT_OF_WORK_BEGIN_FAILED")
        self.assertIsInstance(caught.exception.__cause__, sqlite3.OperationalError)
        self.assertEqual(caught.exception.body.details["close_error"], "OperationalError")
        self.assertTrue(connection.closed)
        with self.assertRaises(UnitOfWorkError):
            _ = uow.connection

    def test_commit_failure_rolls_back_and_close_does_not_hide_original(self) -> None:
        connection = _FailingConnection(
            commit_error=sqlite3.IntegrityError("commit failed"),
            rollback_error=sqlite3.OperationalError("rollback failed"),
        )
        uow = SqliteUnitOfWork(
            _FailingFactory(connection, sqlite3.OperationalError("close failed"))
        )
        with self.assertRaises(UnitOfWorkCommitError) as caught:
            with uow:
                uow.commit()
        self.assertEqual(caught.exception.code, "UNIT_OF_WORK_COMMIT_FAILED")
        self.assertIsInstance(caught.exception.__cause__, sqlite3.IntegrityError)
        self.assertEqual(caught.exception.body.details["rollback_error"], "OperationalError")
        self.assertEqual(caught.exception.body.details["close_error"], "OperationalError")
        self.assertEqual(connection.calls, ["BEGIN IMMEDIATE", "commit", "rollback", "close"])
        self.assertTrue(connection.closed)

    def test_body_exception_is_cause_when_rollback_and_close_also_fail(self) -> None:
        body_error = RuntimeError("programmer failure")
        connection = _FailingConnection(
            rollback_error=sqlite3.OperationalError("rollback failed")
        )
        uow = SqliteUnitOfWork(
            _FailingFactory(connection, sqlite3.OperationalError("close failed"))
        )
        with self.assertRaises(UnitOfWorkRollbackError) as caught:
            with uow:
                raise body_error
        self.assertIs(caught.exception.__cause__, body_error)
        self.assertEqual(caught.exception.body.details["sqlite_error"], "OperationalError")
        self.assertEqual(caught.exception.body.details["close_error"], "OperationalError")
        self.assertTrue(connection.closed)

    def test_close_failure_after_successful_commit_is_typed(self) -> None:
        connection = _FailingConnection()
        uow = SqliteUnitOfWork(
            _FailingFactory(connection, sqlite3.OperationalError("close failed"))
        )
        with self.assertRaises(UnitOfWorkCloseError) as caught:
            with uow:
                uow.commit()
        self.assertEqual(caught.exception.code, "UNIT_OF_WORK_CLOSE_FAILED")
        self.assertIsInstance(caught.exception.__cause__, sqlite3.OperationalError)
        self.assertTrue(connection.closed)


if __name__ == "__main__":
    unittest.main()
