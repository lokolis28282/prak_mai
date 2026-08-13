"""Fail-closed path guards for the three installation-owned runtime databases."""

from __future__ import annotations

import os
import sqlite3
import stat
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from inventory.db import DEFAULT_DB_PATH


RUNTIME_DATABASE_PATHS = {
    "IXcellerate": DEFAULT_DB_PATH,
    "Solar": DEFAULT_DB_PATH.with_name("warehouse_solar.db"),
    "Vacations": DEFAULT_DB_PATH.with_name("vacations.db"),
}
TEST_CONTOUR_MARKER_TABLE = "ode_test_contour_marker"
TEST_CONTOUR_MARKER_VALUE = "ODE_DISPOSABLE_TEST_DB_V1"
TEST_CONTOUR_ROLES = frozenset({"warehouse", "vacations"})
TEST_CONTOUR_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
TEST_CONTOUR_STATE_ABSENT = "absent"
TEST_CONTOUR_STATE_INVALID = "invalid"
TEST_CONTOUR_STATE_MISSING = "missing"


@dataclass(frozen=True, slots=True)
class DisposableDatabaseTargetState:
    """Exact pre-build identity of an absent or marked disposable target."""

    existed: bool
    database_role: str
    stat_result: os.stat_result | None


def install_test_contour_marker(
    connection: sqlite3.Connection, database_role: str
) -> None:
    """Stamp a database built for the explicit disposable test contour."""
    role = str(database_role).strip().casefold()
    if role not in TEST_CONTOUR_ROLES:
        raise ValueError(f"Неизвестная роль тестовой БД: {database_role}")
    connection.execute(f'DROP TABLE IF EXISTS "{TEST_CONTOUR_MARKER_TABLE}"')
    connection.execute(
        f'''CREATE TABLE "{TEST_CONTOUR_MARKER_TABLE}" (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                marker TEXT NOT NULL,
                database_role TEXT NOT NULL
                    CHECK (database_role IN ('warehouse', 'vacations'))
            )'''
    )
    connection.execute(
        f'''INSERT INTO "{TEST_CONTOUR_MARKER_TABLE}"(
                id, marker, database_role
            ) VALUES (1, ?, ?)''',
        (TEST_CONTOUR_MARKER_VALUE, role),
    )


def test_contour_database_has_sidecars(path: str | Path) -> bool:
    """Return whether a test DB has any SQLite journal/coordination sidecar."""
    candidate = Path(path).expanduser()
    return any(
        sidecar.exists() or sidecar.is_symlink()
        for sidecar in (
            Path(str(candidate) + suffix)
            for suffix in TEST_CONTOUR_SIDECAR_SUFFIXES
        )
    )


def test_contour_database_state(path: str | Path) -> str:
    """Return absent, invalid, or the exact marker role without DB writes."""
    candidate = Path(path).expanduser()
    if candidate.is_symlink() or test_contour_database_has_sidecars(candidate):
        return TEST_CONTOUR_STATE_INVALID
    try:
        candidate_stat = candidate.lstat()
    except FileNotFoundError:
        return TEST_CONTOUR_STATE_MISSING
    except OSError:
        return TEST_CONTOUR_STATE_INVALID
    if not stat.S_ISREG(candidate_stat.st_mode):
        return TEST_CONTOUR_STATE_INVALID
    try:
        # A database may retain persistent WAL mode in its main-file header
        # after the last connection has removed the WAL/SHM files. Ordinary
        # mode=ro would recreate those sidecars just to read this marker.
        uri = f"{candidate.resolve().as_uri()}?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            connection.execute("PRAGMA query_only=ON")
            rows = connection.execute(
                f'''SELECT marker, database_role
                    FROM "{TEST_CONTOUR_MARKER_TABLE}"
                    WHERE id = 1'''
            ).fetchall()
        # Do not trust a marker read that overlapped the start of a writer.
        # Immutable mode itself never creates these files, so any sidecar that
        # appeared during the probe belongs to external SQLite activity.
        if test_contour_database_has_sidecars(candidate):
            return TEST_CONTOUR_STATE_INVALID
        if len(rows) != 1 or str(rows[0][0]) != TEST_CONTOUR_MARKER_VALUE:
            return TEST_CONTOUR_STATE_INVALID
        role = str(rows[0][1])
        return role if role in TEST_CONTOUR_ROLES else TEST_CONTOUR_STATE_INVALID
    except sqlite3.OperationalError as error:
        if "no such table" in str(error).casefold():
            return TEST_CONTOUR_STATE_ABSENT
        return TEST_CONTOUR_STATE_INVALID
    except (OSError, sqlite3.Error):
        return TEST_CONTOUR_STATE_INVALID


def test_contour_database_role(path: str | Path) -> str:
    """Return the exact role for a valid quiescent disposable test DB."""
    state = test_contour_database_state(path)
    if state in TEST_CONTOUR_ROLES:
        return state
    return ""


def capture_disposable_database_target_state(
    path: str | Path,
    expected_role: str,
) -> DisposableDatabaseTargetState:
    """Capture a quiescent disposable target before a potentially long build."""
    role = str(expected_role).strip().casefold()
    if role not in TEST_CONTOUR_ROLES:
        raise ValueError(f"Неизвестная роль тестовой БД: {expected_role}")
    candidate = Path(path).expanduser()
    if test_contour_database_has_sidecars(candidate):
        raise RuntimeError(
            "рядом с target найдены SQLite sidecar-файлы; публикация запрещена"
        )
    marker_state = test_contour_database_state(candidate)
    if marker_state == TEST_CONTOUR_STATE_MISSING:
        return DisposableDatabaseTargetState(False, role, None)
    if marker_state != role:
        raise RuntimeError(
            f"существующий target не имеет marker одноразовой {role} test DB; "
            "перезапись неизвестной БД запрещена"
        )
    try:
        before = candidate.lstat()
        after = candidate.lstat()
    except OSError as error:
        raise RuntimeError("target изменился во время проверки marker") from error
    if (
        not stat.S_ISREG(before.st_mode)
        or not stat.S_ISREG(after.st_mode)
        or not os.path.samestat(before, after)
        or test_contour_database_has_sidecars(candidate)
    ):
        raise RuntimeError("target изменился во время проверки marker")
    return DisposableDatabaseTargetState(True, role, after)


def revalidate_disposable_database_target_state(
    path: str | Path,
    expected: DisposableDatabaseTargetState,
) -> None:
    """Fail closed if a disposable target changed before atomic publication."""
    candidate = Path(path).expanduser()
    marker_state = test_contour_database_state(candidate)
    if not expected.existed:
        if marker_state != TEST_CONTOUR_STATE_MISSING:
            raise RuntimeError(
                "target появился или изменился во время сборки; публикация запрещена"
            )
        return
    if marker_state != expected.database_role or expected.stat_result is None:
        raise RuntimeError(
            "target marker/role или SQLite sidecar изменились во время сборки; "
            "публикация запрещена"
        )
    try:
        current = candidate.lstat()
    except OSError as error:
        raise RuntimeError("target исчез во время сборки; публикация запрещена") from error
    original = expected.stat_result
    if (
        not stat.S_ISREG(current.st_mode)
        or not os.path.samestat(original, current)
        or current.st_size != original.st_size
        or current.st_mtime_ns != original.st_mtime_ns
        or current.st_ctime_ns != original.st_ctime_ns
        or test_contour_database_has_sidecars(candidate)
    ):
        raise RuntimeError(
            "target identity/content изменились во время сборки; публикация запрещена"
        )


def same_path_or_file(left: str | Path, right: str | Path) -> bool:
    """Compare paths, portable case collisions, and existing hardlink aliases."""
    selected = Path(left).expanduser().resolve()
    protected = Path(right).expanduser().resolve()
    if selected == protected or (
        selected.parent == protected.parent
        and selected.name.casefold() == protected.name.casefold()
    ):
        return True
    try:
        return selected.exists() and protected.exists() and os.path.samefile(
            selected, protected
        )
    except OSError:
        return False


def runtime_database_alias(path: str | Path) -> str:
    """Return the protected runtime label aliased by ``path``, if any."""
    for label, protected in RUNTIME_DATABASE_PATHS.items():
        if same_path_or_file(path, protected):
            return label
    return ""


def disposable_database_target(path: str | Path) -> Path:
    """Resolve an output path only after rejecting symlinks and runtime aliases."""
    candidate = Path(path).expanduser()
    if candidate.is_symlink():
        raise RuntimeError("тестовая БД не может быть symbolic link")
    target = candidate.resolve()
    if label := runtime_database_alias(target):
        raise RuntimeError(
            f"тестовая БД не может заменять рабочую {label} runtime-БД"
        )
    return target
