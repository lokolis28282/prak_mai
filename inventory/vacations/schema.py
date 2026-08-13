"""Additive SQLite schema for the isolated vacation planning database."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from inventory.shared.db import connect
from inventory.shared.runtime_paths import RUNTIME_DATABASE_PATHS, same_path_or_file


DEFAULT_VACATIONS_DB_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "vacations.db"
)

VACATION_TABLES = frozenset(
    {
        "vacation_employees",
        "vacation_assignments",
        "vacation_requests",
        "vacation_conflicts",
        "vacation_history",
        "vacation_audit_log",
    }
)

VACATION_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS vacation_employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    full_name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    is_site_senior INTEGER NOT NULL DEFAULT 0 CHECK (is_site_senior IN (0, 1)),
    is_department_head INTEGER NOT NULL DEFAULT 0 CHECK (is_department_head IN (0, 1)),
    is_substitute INTEGER NOT NULL DEFAULT 0 CHECK (is_substitute IN (0, 1)),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS vacation_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES vacation_employees(id),
    site TEXT NOT NULL CHECK (site IN ('ixcellerate', 'solar', 'hybrid')),
    schedule_type TEXT NOT NULL CHECK (schedule_type IN ('FIVE_TWO', 'ONE_THREE')),
    shift_group INTEGER CHECK (
        (schedule_type = 'ONE_THREE' AND shift_group BETWEEN 0 AND 3)
        OR (schedule_type = 'FIVE_TWO' AND shift_group IS NULL)
    ),
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    note TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    CHECK (valid_to IS NULL OR valid_to >= valid_from),
    UNIQUE(employee_id, valid_from)
);

CREATE TABLE IF NOT EXISTS vacation_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES vacation_employees(id),
    date_from TEXT NOT NULL,
    date_to TEXT NOT NULL,
    calendar_days INTEGER NOT NULL CHECK (calendar_days > 0),
    sfera_status TEXT NOT NULL DEFAULT 'PLANNED'
        CHECK (sfera_status IN ('PLANNED', 'SUBMITTED', 'APPROVED', 'REJECTED', 'CANCELLED')),
    sfera_reference TEXT NOT NULL DEFAULT '',
    substitute_employee_id INTEGER REFERENCES vacation_employees(id),
    comment TEXT NOT NULL DEFAULT '',
    conflict_status TEXT NOT NULL DEFAULT 'NONE'
        CHECK (conflict_status IN ('NONE', 'PENDING', 'APPROVED_EXCEPTION', 'REJECTED')),
    created_by TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    CHECK (date_to >= date_from),
    CHECK (substitute_employee_id IS NULL OR substitute_employee_id <> employee_id)
);

CREATE TABLE IF NOT EXISTS vacation_conflicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL REFERENCES vacation_requests(id) ON DELETE CASCADE,
    code TEXT NOT NULL CHECK (
        code IN ('EMPLOYEE_OVERLAP', 'LEADERSHIP_OVERLAP',
                 'SUBSTITUTE_OVERLAP', 'DUTY_COVERAGE')
    ),
    conflict_date TEXT,
    related_employee_id INTEGER REFERENCES vacation_employees(id),
    details TEXT NOT NULL,
    decision TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (decision IN ('PENDING', 'APPROVED', 'REJECTED')),
    resolved_by TEXT NOT NULL DEFAULT '',
    resolution_comment TEXT NOT NULL DEFAULT '',
    resolved_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS vacation_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL CHECK (
        entity_type IN ('employee', 'assignment', 'request', 'conflict')
    ),
    entity_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS vacation_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL DEFAULT '',
    actor TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_vacation_assignments_effective
    ON vacation_assignments(employee_id, valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_vacation_requests_dates
    ON vacation_requests(date_from, date_to, sfera_status, conflict_status);
CREATE INDEX IF NOT EXISTS idx_vacation_requests_employee
    ON vacation_requests(employee_id, date_from, date_to);
CREATE INDEX IF NOT EXISTS idx_vacation_conflicts_pending
    ON vacation_conflicts(decision, request_id);
CREATE INDEX IF NOT EXISTS idx_vacation_audit_created
    ON vacation_audit_log(created_at, id);
"""


def install_vacations_schema(db_path: str | Path) -> None:
    """Install an empty, idempotent module schema.

    Employee rosters are operational company data. They are entered through
    the Vacations facade/UI and must never be embedded in a source release.
    """
    target = Path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with connect(target) as db:
        db.executescript(VACATION_SCHEMA)


def prepare_vacations_database(
    warehouse_db_path: str | Path,
    configured_path: str | Path | None = None,
    solar_db_path: str | Path | None = None,
) -> Path:
    """Resolve and initialize a DB that cannot alias either Warehouse DB."""
    warehouse = Path(warehouse_db_path).expanduser().resolve()
    candidate = Path(
        configured_path or warehouse.with_name("vacations.db")
    ).expanduser()
    if candidate.is_symlink():
        raise RuntimeError("БД отпусков не может быть symbolic link")
    target = candidate.resolve()
    forbidden = {"selected IXcellerate": warehouse}
    if solar_db_path:
        forbidden["selected Solar"] = Path(solar_db_path).expanduser().resolve()
    forbidden.update(
        {
            label: path
            for label, path in RUNTIME_DATABASE_PATHS.items()
            if label in {"IXcellerate", "Solar"}
        }
    )
    for label, path in forbidden.items():
        if same_path_or_file(target, path):
            alias_kind = "hardlink " if target != Path(path).expanduser().resolve() else ""
            raise RuntimeError(
                f"БД отпусков должна быть отдельна от складских БД; "
                f"обнаружен {alias_kind}{label}"
            )
    try:
        install_vacations_schema(target)
    except (OSError, sqlite3.Error) as error:
        raise RuntimeError(f"Не удалось инициализировать БД отпусков: {error}") from error
    return target


def vacations_schema_ready(db_path: str | Path) -> bool:
    """Return whether all module-owned tables exist."""
    try:
        uri = f"file:{Path(db_path).resolve().as_posix()}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as db:
            tables = {
                str(row[0])
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        return VACATION_TABLES <= tables
    except sqlite3.Error:
        return False
