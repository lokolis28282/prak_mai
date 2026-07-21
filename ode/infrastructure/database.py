"""SQLite connection policy, deterministic schema hashing, and Unit of Work."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar, Token
from enum import Enum
from pathlib import Path
from types import TracebackType

from ode.application.config import DatabaseConfig
from ode.application.errors import (
    DatabaseError,
    NestedUnitOfWorkError,
    ReadOnlyMutationError,
    UnitOfWorkBeginError,
    UnitOfWorkCloseError,
    UnitOfWorkCommitError,
    UnitOfWorkError,
    UnitOfWorkRollbackError,
)
from ode.infrastructure.paths import canonical_database_path


class ConnectionMode(str, Enum):
    READ_ONLY = "READ_ONLY"
    IMMUTABLE_READ_ONLY = "IMMUTABLE_READ_ONLY"
    WRITE = "WRITE"
    MIGRATION = "MIGRATION"


_TRANSACTION_CONTROL = {"BEGIN", "COMMIT", "END", "ROLLBACK", "SAVEPOINT", "RELEASE"}
_DDL_CONTROL = {"ALTER", "CREATE", "DROP", "REINDEX", "VACUUM"}
_RUNTIME_DML = {"SELECT", "INSERT", "UPDATE", "DELETE"}
_SYSTEM_SCHEMA_TABLES = {
    "SQLITE_MASTER",
    "SQLITE_SCHEMA",
    "SQLITE_TEMP_MASTER",
    "SQLITE_TEMP_SCHEMA",
}
_AUTHORITATIVE_SQLITE_ACTIONS = {
    sqlite3.SQLITE_ATTACH,
    sqlite3.SQLITE_DETACH,
    sqlite3.SQLITE_PRAGMA,
    sqlite3.SQLITE_CREATE_INDEX,
    sqlite3.SQLITE_CREATE_TABLE,
    sqlite3.SQLITE_CREATE_TRIGGER,
    sqlite3.SQLITE_CREATE_VIEW,
    sqlite3.SQLITE_CREATE_TEMP_INDEX,
    sqlite3.SQLITE_CREATE_TEMP_TABLE,
    sqlite3.SQLITE_CREATE_TEMP_TRIGGER,
    sqlite3.SQLITE_CREATE_TEMP_VIEW,
    sqlite3.SQLITE_DROP_INDEX,
    sqlite3.SQLITE_DROP_TABLE,
    sqlite3.SQLITE_DROP_TRIGGER,
    sqlite3.SQLITE_DROP_VIEW,
    sqlite3.SQLITE_DROP_TEMP_INDEX,
    sqlite3.SQLITE_DROP_TEMP_TABLE,
    sqlite3.SQLITE_DROP_TEMP_TRIGGER,
    sqlite3.SQLITE_DROP_TEMP_VIEW,
    sqlite3.SQLITE_ALTER_TABLE,
    sqlite3.SQLITE_REINDEX,
    sqlite3.SQLITE_ANALYZE,
    sqlite3.SQLITE_TRANSACTION,
    sqlite3.SQLITE_SAVEPOINT,
}


def _runtime_authorizer(
    action: int,
    arg1: str | None,
    _arg2: str | None,
    _database: str | None,
    _source: str | None,
) -> int:
    """Deny schema, attachment, pragma and transaction control at SQLite level."""

    if action in _AUTHORITATIVE_SQLITE_ACTIONS:
        return sqlite3.SQLITE_DENY
    if action in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}:
        if arg1 is not None and arg1.upper() in _SYSTEM_SCHEMA_TABLES:
            return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def _permissive_authorizer(
    _action: int,
    _arg1: str | None,
    _arg2: str | None,
    _database: str | None,
    _source: str | None,
) -> int:
    """Allow-everything authorizer used to *replace* the runtime authorizer.

    Functionally equivalent to removing it, but works on Python 3.10 where
    ``set_authorizer(None)`` is not supported (support for ``None`` was added
    in Python 3.11)."""

    return sqlite3.SQLITE_OK


def _sql_tokens(sql: str) -> list[tuple[str, str, int]]:
    """Tokenize enough SQL structure to identify the outermost operation safely."""

    tokens: list[tuple[str, str, int]] = []
    index = 0
    depth = 0
    length = len(sql)
    while index < length:
        character = sql[index]
        if character.isspace():
            index += 1
            continue
        if sql.startswith("--", index):
            newline = sql.find("\n", index + 2)
            index = length if newline < 0 else newline + 1
            continue
        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            if end < 0:
                return []
            index = end + 2
            continue
        if character == "'":
            index += 1
            while index < length:
                if sql[index] == "'":
                    if index + 1 < length and sql[index + 1] == "'":
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        if character == '"':
            start = index + 1
            index += 1
            while index < length:
                if sql[index] == '"':
                    if index + 1 < length and sql[index + 1] == '"':
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            if index > start:
                tokens.append(("word", sql[start:index - 1].replace('""', '"').upper(), depth))
            continue
        if character == "`":
            start = index + 1
            index += 1
            while index < length:
                if sql[index] == "`":
                    index += 1
                    break
                index += 1
            if index > start:
                tokens.append(("word", sql[start:index - 1].upper(), depth))
            continue
        if character == "[":
            start = index + 1
            closing = sql.find("]", index + 1)
            index = length if closing < 0 else closing + 1
            if closing >= 0:
                tokens.append(("word", sql[start:closing].upper(), depth))
            continue
        if character == "(":
            depth += 1
            tokens.append(("punctuation", character, depth))
            index += 1
            continue
        if character == ")":
            tokens.append(("punctuation", character, depth))
            depth = max(depth - 1, 0)
            index += 1
            continue
        if character.isalpha() or character == "_":
            end = index + 1
            while end < length and (sql[end].isalnum() or sql[end] in {"_", "$"}):
                end += 1
            tokens.append(("word", sql[index:end].upper(), depth))
            index = end
            continue
        tokens.append(("punctuation", character, depth))
        index += 1
    return tokens


def _runtime_sql_operation(sql: str) -> str | None:
    """Return an allowed outer DML operation, or None for every other statement."""

    tokens = _sql_tokens(sql)
    if any(kind == "punctuation" and value == ";" for kind, value, _ in tokens):
        return None
    first_word = next(
        (value for kind, value, _depth in tokens if kind == "word"), None
    )
    if first_word in _RUNTIME_DML:
        return first_word
    if first_word != "WITH":
        return None
    for kind, value, depth in tokens[1:]:
        if kind == "word" and depth == 0 and value in _RUNTIME_DML:
            return value
    return None


def _references_system_schema(sql: str) -> bool:
    return any(
        kind == "word" and value in _SYSTEM_SCHEMA_TABLES
        for kind, value, _depth in _sql_tokens(sql)
    )


def _sql_first_word(sql: str) -> str | None:
    return next(
        (value for kind, value, _depth in _sql_tokens(sql) if kind == "word"), None
    )


def sqlite_sidecar_state(path: Path) -> dict[str, bool]:
    """Return exact SQLite sidecar presence without opening or changing the database."""

    return {
        "wal": Path(f"{path}-wal").exists(),
        "shm": Path(f"{path}-shm").exists(),
        "journal": Path(f"{path}-journal").exists(),
    }


def require_immutable_snapshot_safe(path: Path) -> None:
    """Fail closed when immutable SQLite would ignore a possible live sidecar."""

    sidecars = sqlite_sidecar_state(path)
    if any(sidecars.values()):
        raise DatabaseError(
            "IMMUTABLE_SNAPSHOT_UNSAFE",
            "Immutable diagnostics require a closed database without SQLite sidecars",
            details=sidecars,
        )


def _database_failure_type(error: BaseException) -> str:
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, sqlite3.Error):
            return type(current).__name__
        current = current.__cause__
    return type(error).__name__


def _is_database_failure(error: BaseException) -> bool:
    return isinstance(error, (sqlite3.Error, DatabaseError))


def _sql_keyword(sql: str) -> str:
    match = _LEADING_SQL_KEYWORD.match(sql)
    return match.group(1).upper() if match is not None else ""


class SQLiteConnectionFactory:
    """The only runtime owner of SQLite connection creation and PRAGMAs."""

    def __init__(self, config: DatabaseConfig) -> None:
        self._config = config

    @property
    def database_path(self) -> Path:
        return self._config.db_path

    @contextmanager
    def connect(
        self, mode: ConnectionMode | None = None
    ) -> Iterator[sqlite3.Connection]:
        selected = mode or (
            ConnectionMode.READ_ONLY if self._config.read_only else ConnectionMode.WRITE
        )
        connection: sqlite3.Connection | None = None
        try:
            connection = self._open(selected)
            yield connection
        except sqlite3.Error as exc:
            raise DatabaseError(
                "DATABASE_OPERATION_FAILED",
                "SQLite operation failed",
                details={"sqlite_error": type(exc).__name__},
            ) from exc
        finally:
            if connection is not None:
                connection.close()

    def _open(self, mode: ConnectionMode) -> sqlite3.Connection:
        current_path, _ = canonical_database_path(
            self._config.db_path,
            allow_external_dev_path=self._config.external_path_override,
        )
        if current_path != self._config.db_path:
            raise DatabaseError(
                "DATABASE_PATH_CHANGED",
                "Database path changed after configuration validation",
            )
        if self._config.read_only and mode in {
            ConnectionMode.WRITE,
            ConnectionMode.MIGRATION,
        }:
            raise DatabaseError(
                "READ_ONLY_CONFIGURATION",
                "Write connection is forbidden by DatabaseConfig",
            )
        if mode in {ConnectionMode.READ_ONLY, ConnectionMode.IMMUTABLE_READ_ONLY}:
            immutable = "&immutable=1" if mode is ConnectionMode.IMMUTABLE_READ_ONLY else ""
            uri = f"{self._config.db_path.as_uri()}?mode=ro{immutable}"
            connection = sqlite3.connect(
                uri,
                uri=True,
                isolation_level=None,
                timeout=self._config.busy_timeout_ms / 1000,
            )
        else:
            connection = sqlite3.connect(
                self._config.db_path,
                isolation_level=None,
                timeout=self._config.busy_timeout_ms / 1000,
            )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self._config.busy_timeout_ms:d}")
        connection.execute("PRAGMA trusted_schema = OFF")
        if mode in {ConnectionMode.READ_ONLY, ConnectionMode.IMMUTABLE_READ_ONLY}:
            connection.execute("PRAGMA query_only = ON")
        elif mode is ConnectionMode.WRITE:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
        else:
            connection.execute("PRAGMA journal_mode = DELETE")
            connection.execute("PRAGMA synchronous = FULL")
        return connection


def schema_dump_bytes(connection: sqlite3.Connection) -> bytes:
    """Reproduce sqlite3 CLI `.schema` bytes used by the approved DDL review."""

    parts: list[str] = []
    rows = connection.execute(
        "SELECT type, name, sql FROM sqlite_schema "
        "WHERE sql IS NOT NULL ORDER BY rowid"
    ).fetchall()
    for row in rows:
        object_type = str(row[0])
        name = str(row[1])
        sql = str(row[2])
        parts.append(sql)
        if object_type == "view":
            columns = connection.execute(
                "SELECT name FROM pragma_table_info(?) ORDER BY cid", (name,)
            ).fetchall()
            signature = ",".join(str(column[0]) for column in columns)
            parts.append(f"\n/* {name}({signature}) */")
        parts.append(";\n")
    return "".join(parts).encode("utf-8")


def compute_schema_hash(connection: sqlite3.Connection) -> str:
    return hashlib.sha256(schema_dump_bytes(connection)).hexdigest()


_active_write_uow: ContextVar[bool] = ContextVar("ode_active_write_uow", default=False)


class SqliteUnitOfWork:
    """Explicit transaction boundary; repositories must never commit independently."""

    def __init__(self, factory: SQLiteConnectionFactory, *, read_only: bool = False) -> None:
        self._factory = factory
        self._read_only = read_only
        self._manager: AbstractContextManager[sqlite3.Connection] | None = None
        self._connection: sqlite3.Connection | None = None
        self._write_token: Token[bool] | None = None
        self._commit_requested = False
        self._authorizer_installed = False

    def _install_authorizer(self) -> None:
        setter = getattr(self._connection, "set_authorizer", None)
        if setter is not None:
            setter(_runtime_authorizer)
            self._authorizer_installed = True

    def _disable_authorizer(self) -> None:
        if self._authorizer_installed and self._connection is not None:
            # Python 3.10 compatibility: set_authorizer(None) снимает
            # авторизатор только с Python 3.11+; на 3.10 None превращается в
            # deny-all колбэк и COMMIT/ROLLBACK падают с «not authorized».
            # Разрешающий колбэк работает одинаково на всех версиях.
            self._connection.set_authorizer(_permissive_authorizer)
            self._authorizer_installed = False

    def __enter__(self) -> "SqliteUnitOfWork":
        if not self._read_only and _active_write_uow.get():
            raise NestedUnitOfWorkError(
                "NESTED_WRITE_UNIT_OF_WORK",
                "Nested write Unit of Work is not allowed in one execution context",
            )
        mode = ConnectionMode.READ_ONLY if self._read_only else ConnectionMode.WRITE
        manager = self._factory.connect(mode)
        self._manager = manager
        try:
            self._connection = manager.__enter__()
            self._connection.execute("BEGIN" if self._read_only else "BEGIN IMMEDIATE")
            self._install_authorizer()
        except BaseException as error:
            close_error: BaseException | None = None
            if self._connection is not None:
                try:
                    manager.__exit__(None, None, None)
                except BaseException as cleanup_error:
                    close_error = cleanup_error
            self._manager = None
            self._connection = None
            self._authorizer_installed = False
            if _is_database_failure(error):
                details = {"sqlite_error": _database_failure_type(error)}
                if close_error is not None:
                    details["close_error"] = _database_failure_type(close_error)
                raise UnitOfWorkBeginError(
                    "UNIT_OF_WORK_BEGIN_FAILED",
                    "SQLite transaction could not begin",
                    details=details,
                ) from error
            raise
        if not self._read_only:
            self._write_token = _active_write_uow.set(True)
        return self

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise UnitOfWorkError(
                "UNIT_OF_WORK_NOT_ACTIVE", "Unit of Work is not active"
            )
        return self._connection

    def execute(
        self, sql: str, parameters: Sequence[object] = ()
    ) -> sqlite3.Cursor:
        operation = _runtime_sql_operation(sql)
        if operation is not None and _references_system_schema(sql):
            operation = None
        if operation is None:
            first_word = _sql_first_word(sql)
            if first_word in _TRANSACTION_CONTROL:
                code = "UNIT_OF_WORK_TRANSACTION_CONTROL_FORBIDDEN"
                message = "Transaction-control SQL is owned by Unit of Work"
            elif first_word in _DDL_CONTROL:
                code = "UNIT_OF_WORK_DDL_FORBIDDEN"
                message = "DDL is forbidden inside runtime Unit of Work"
            else:
                code = "SQL_OPERATION_FORBIDDEN"
                message = "Only application DML is allowed inside runtime Unit of Work"
            raise UnitOfWorkError(
                code,
                message,
            )
        try:
            return self.connection.execute(sql, parameters)
        except sqlite3.Error as exc:
            if "not authorized" in str(exc).lower():
                raise UnitOfWorkError(
                    "SQL_OPERATION_FORBIDDEN",
                    "SQLite authorizer rejected the operation",
                ) from exc
            code = "READ_ONLY_MUTATION" if self._read_only else "UNIT_OF_WORK_SQL_FAILED"
            message = (
                "Mutation is forbidden in a read-only Unit of Work"
                if self._read_only
                else "SQLite statement failed inside Unit of Work"
            )
            error_type = ReadOnlyMutationError if self._read_only else UnitOfWorkError
            raise error_type(
                code, message, details={"sqlite_error": type(exc).__name__}
            ) from exc

    def commit(self) -> None:
        if self._read_only:
            raise UnitOfWorkError(
                "READ_ONLY_COMMIT_FORBIDDEN",
                "A read-only Unit of Work cannot request commit",
            )
        if self._connection is None:
            raise UnitOfWorkError(
                "UNIT_OF_WORK_NOT_ACTIVE", "Unit of Work is not active"
            )
        self._commit_requested = True

    def rollback(self) -> None:
        self._disable_authorizer()
        try:
            if self._connection is not None:
                self._connection.rollback()
        except sqlite3.Error as exc:
            raise UnitOfWorkRollbackError(
                "UNIT_OF_WORK_ROLLBACK_FAILED",
                "SQLite transaction could not roll back",
                details={"sqlite_error": type(exc).__name__},
            ) from exc
        finally:
            if self._connection is not None:
                self._install_authorizer()
            self._commit_requested = False

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        connection = self._connection
        manager = self._manager
        transaction_error: BaseException | None = None
        transaction_stage: str | None = None
        transaction_details: dict[str, str] = {}
        close_error: BaseException | None = None
        try:
            if connection is not None:
                self._disable_authorizer()
                if exc_type is None and self._commit_requested and not self._read_only:
                    try:
                        connection.commit()
                    except sqlite3.Error as error:
                        transaction_error = error
                        transaction_stage = "commit"
                        transaction_details = {"sqlite_error": type(error).__name__}
                        if connection.in_transaction:
                            try:
                                connection.rollback()
                            except sqlite3.Error as rollback_error:
                                transaction_details["rollback_error"] = type(
                                    rollback_error
                                ).__name__
                else:
                    try:
                        connection.rollback()
                    except sqlite3.Error as error:
                        transaction_error = error
                        transaction_stage = "rollback"
                        transaction_details = {"sqlite_error": type(error).__name__}
        finally:
            if self._write_token is not None:
                _active_write_uow.reset(self._write_token)
            self._write_token = None
            self._connection = None
            self._manager = None
            self._commit_requested = False
            self._authorizer_installed = False
            if manager is not None:
                try:
                    manager.__exit__(None, None, None)
                except BaseException as error:
                    close_error = error
        if transaction_stage is not None:
            if close_error is not None:
                transaction_details["close_error"] = _database_failure_type(close_error)
            if transaction_stage == "commit":
                transaction_failure: UnitOfWorkError = UnitOfWorkCommitError(
                    "UNIT_OF_WORK_COMMIT_FAILED",
                    "SQLite transaction could not commit",
                    details=transaction_details,
                )
            else:
                transaction_failure = UnitOfWorkRollbackError(
                    "UNIT_OF_WORK_ROLLBACK_FAILED",
                    "SQLite transaction could not roll back",
                    details=transaction_details,
                )
            cause = exc if exc is not None else transaction_error
            raise transaction_failure from cause
        if close_error is not None:
            close_failure = UnitOfWorkCloseError(
                "UNIT_OF_WORK_CLOSE_FAILED",
                "SQLite connection could not close cleanly",
                details={"sqlite_error": _database_failure_type(close_error)},
            )
            raise close_failure from (exc if exc is not None else close_error)
        if exc is not None and _is_database_failure(exc) and not isinstance(
            exc, UnitOfWorkError
        ):
            raise UnitOfWorkError(
                "UNIT_OF_WORK_SQL_FAILED",
                "SQLite statement failed inside Unit of Work",
                details={"sqlite_error": _database_failure_type(exc)},
            ) from exc
        return False
