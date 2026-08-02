"""Independent local Warehouse contours behind one ODE application session."""

from __future__ import annotations

from contextlib import closing, contextmanager, nullcontext
from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from inventory.core.application import ApplicationContext
from inventory.core.context import RuntimeConfig
from inventory.db import DEFAULT_DB_PATH, initialize
from inventory.routes.runtime import RouteRuntime
from inventory.service import WarehouseService


SOLAR_DB_PATH = DEFAULT_DB_PATH.with_name("warehouse_solar.db")
DEFAULT_SITE_KEY = "ixcellerate"
REFERENCE_TABLES = (
    "categories",
    "locations",
    "reference_values",
    "reference_domains_v2",
    "reference_values_v2",
    "reference_aliases_v2",
)
OPERATIONAL_TABLES = (
    "equipment",
    "operations",
    "stock_receipts",
    "stock_issues",
    "stock_issue_allocations",
    "deliveries",
    "delivery_lines",
)
REFERENCE_V2_SCHEMA = """
CREATE TABLE reference_domains_v2 (
    id INTEGER PRIMARY KEY,
    domain_key TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE reference_values_v2 (
    id INTEGER PRIMARY KEY,
    domain_id INTEGER NOT NULL REFERENCES reference_domains_v2(id),
    canonical_value TEXT NOT NULL,
    display_name TEXT NOT NULL,
    normalized_key TEXT NOT NULL,
    scope_key TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    approval_status TEXT NOT NULL CHECK (
        approval_status IN ('APPROVED', 'CANDIDATE', 'REJECTED')
    ),
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(domain_id, scope_key, normalized_key)
);
CREATE TABLE reference_aliases_v2 (
    id INTEGER PRIMARY KEY,
    domain_id INTEGER NOT NULL REFERENCES reference_domains_v2(id),
    source_value TEXT NOT NULL,
    normalized_source_key TEXT NOT NULL,
    canonical_id INTEGER NOT NULL REFERENCES reference_values_v2(id),
    source_file TEXT NOT NULL,
    source_sheet TEXT NOT NULL,
    usage_count INTEGER NOT NULL DEFAULT 0 CHECK (usage_count >= 0),
    confidence TEXT NOT NULL CHECK (confidence IN ('HIGH', 'MEDIUM', 'LOW')),
    resolution_status TEXT NOT NULL CHECK (
        resolution_status IN ('AUTO_APPROVED', 'APPROVED', 'PENDING', 'REJECTED')
    ),
    approved_by TEXT NOT NULL DEFAULT '',
    approved_at TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    UNIQUE(domain_id, source_value, canonical_id, source_file, source_sheet)
);
CREATE INDEX idx_reference_values_v2_domain
    ON reference_values_v2(domain_id, active, display_name);
CREATE INDEX idx_reference_aliases_v2_lookup
    ON reference_aliases_v2(domain_id, normalized_source_key, resolution_status);
"""


def warehouse_site_settings(
    primary_path: str | Path,
    contour: str,
    solar_path: str | Path | None,
) -> dict[str, Any]:
    enabled = bool(solar_path) or (
        Path(primary_path).resolve() == DEFAULT_DB_PATH.resolve()
        and contour == "production"
    )
    return {
        "warehouse_sites_enabled": enabled,
        **({"solar_db_path": Path(solar_path).expanduser()} if solar_path else {}),
    }


def configured_solar_path(settings: dict[str, Any]) -> Path:
    return Path(settings.get("solar_db_path", SOLAR_DB_PATH)).resolve()


def warehouse_runtime_config(
    primary_path: str | Path,
    *,
    contour: str,
    inventory_state_root: str | Path | None,
    solar_path: str | Path | None,
) -> RuntimeConfig:
    return RuntimeConfig(
        Path(primary_path),
        warehouse_contour=contour,
        production_db_path=DEFAULT_DB_PATH,
        full_inventory_state_root=(
            Path(inventory_state_root).expanduser()
            if inventory_state_root
            else None
        ),
        settings=warehouse_site_settings(primary_path, contour, solar_path),
    )


def _database_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _table_exists(db: sqlite3.Connection, table: str) -> bool:
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _copy_table(
    source: sqlite3.Connection, target: sqlite3.Connection, table: str
) -> int:
    if not _table_exists(source, table) or not _table_exists(target, table):
        return 0
    columns = [
        str(row[1]) for row in source.execute(f'PRAGMA table_info("{table}")')
    ]
    target_columns = {
        str(row[1]) for row in target.execute(f'PRAGMA table_info("{table}")')
    }
    if not columns or set(columns) != target_columns:
        raise RuntimeError(f"Несовместимая схема справочника {table}")
    target.execute(f'DELETE FROM "{table}"')
    placeholders = ",".join("?" for _ in columns)
    column_sql = ",".join(f'"{name}"' for name in columns)
    rows = source.execute(f'SELECT {column_sql} FROM "{table}"').fetchall()
    if rows:
        target.executemany(
            f'INSERT INTO "{table}" ({column_sql}) VALUES ({placeholders})',
            [tuple(row) for row in rows],
        )
    return len(rows)


def bootstrap_solar_database(
    source_path: str | Path,
    target_path: str | Path = SOLAR_DB_PATH,
) -> dict[str, Any]:
    """Atomically create an operationally empty Solar DB with IX references."""
    source = Path(source_path).resolve()
    target_candidate = Path(target_path)
    if target_candidate.is_symlink():
        raise RuntimeError("Solar DB не может быть symbolic link")
    target = target_candidate.resolve()
    if source == target:
        raise RuntimeError("IXcellerate и Solar должны использовать разные БД")
    if target.exists():
        if os.path.samefile(source, target):
            raise RuntimeError("IXcellerate и Solar указывают на один файл")
        return {"created": False, "path": target}
    if not source.is_file():
        raise FileNotFoundError(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.bootstrap-{os.getpid()}")
    if temporary.exists():
        raise FileExistsError(temporary)
    try:
        initialize(temporary)
        copied: dict[str, int] = {}
        source_uri = f"file:{source.as_posix()}?mode=ro"
        with closing(sqlite3.connect(source_uri, uri=True)) as source_db, closing(
            sqlite3.connect(temporary)
        ) as target_db:
            source_db.row_factory = sqlite3.Row
            target_db.execute("PRAGMA foreign_keys=ON")
            if all(
                _table_exists(source_db, table)
                for table in (
                    "reference_domains_v2",
                    "reference_values_v2",
                    "reference_aliases_v2",
                )
            ) and not any(
                _table_exists(target_db, table)
                for table in (
                    "reference_domains_v2",
                    "reference_values_v2",
                    "reference_aliases_v2",
                )
            ):
                target_db.executescript(REFERENCE_V2_SCHEMA)
            target_db.execute("PRAGMA foreign_keys=OFF")
            for table in REFERENCE_TABLES:
                copied[table] = _copy_table(source_db, target_db, table)
            target_db.execute("PRAGMA foreign_keys=ON")
            for table in OPERATIONAL_TABLES:
                if _table_exists(target_db, table):
                    count = int(
                        target_db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                    )
                    if count:
                        raise RuntimeError(
                            f"Solar bootstrap содержит operational rows: {table}={count}"
                        )
            integrity = str(target_db.execute("PRAGMA integrity_check").fetchone()[0])
            foreign_keys = target_db.execute("PRAGMA foreign_key_check").fetchall()
            if integrity != "ok" or foreign_keys:
                raise RuntimeError("Solar bootstrap не прошёл SQLite-проверки")
            target_db.commit()
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        return {
            "created": True,
            "path": target,
            "source_sha256": _database_sha256(source),
            "reference_rows": copied,
        }
    finally:
        if temporary.exists():
            temporary.unlink()


@dataclass(frozen=True, slots=True)
class WarehouseSite:
    key: str
    label: str
    runtime: RouteRuntime

    def public(self, *, selected: bool) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "selected": selected,
            "database": self.runtime.service.db_path.name,
        }


class WarehouseSiteRegistry:
    """Resolve a session warehouse without moving shared ODE modules."""

    def __init__(
        self,
        primary_context: ApplicationContext,
        *,
        solar_db_path: str | Path | None = None,
        enable_solar: bool = False,
    ):
        primary_runtime = self._runtime(
            primary_context, key=DEFAULT_SITE_KEY, label="IXcellerate"
        )
        self._sites = {
            DEFAULT_SITE_KEY: WarehouseSite(
                DEFAULT_SITE_KEY, "IXcellerate", primary_runtime
            )
        }
        if enable_solar:
            solar_path = Path(solar_db_path or SOLAR_DB_PATH)
            bootstrap_solar_database(primary_context.db_path, solar_path)
            solar_service = WarehouseService(solar_path, initialize_database=False)
            if primary_context.full_inventory is None:
                raise RuntimeError("Primary Full Inventory context не настроен")
            primary_inventory_root = primary_context.full_inventory.paths.root
            primary_configuration = primary_context.configuration
            solar_contour = (
                primary_configuration.warehouse_contour
                if primary_configuration is not None
                else "unknown"
            )
            solar_production_path = (
                solar_service.db_path
                if solar_contour == "production"
                else (
                    primary_configuration.production_db_path
                    if primary_configuration is not None
                    else DEFAULT_DB_PATH
                )
            )
            solar_context = ApplicationContext.from_service(
                solar_service,
                configuration=RuntimeConfig(
                    solar_service.db_path,
                    primary_context.feature_flags,
                    warehouse_contour=solar_contour,
                    production_db_path=solar_production_path,
                    full_inventory_state_root=primary_inventory_root / "solar",
                ),
            )
            solar_context.reports = primary_context.reports
            solar_context.monitoring = primary_context.monitoring
            solar_context.knowledge = primary_context.knowledge
            solar_context.administration = primary_context.administration
            self._sites["solar"] = WarehouseSite(
                "solar",
                "Solar",
                self._runtime(solar_context, key="solar", label="Solar"),
            )

    @staticmethod
    def _runtime(
        context: ApplicationContext, *, key: str, label: str
    ) -> RouteRuntime:
        service = context.service_adapter()
        stat = service.db_path.stat()
        return RouteRuntime(
            app_context=context,
            service=service,
            migration_full_status={"enabled": False, "read_only": False},
            migration_pilot_status={"enabled": False},
            database_fingerprint=(
                f"local:{stat.st_dev:x}:{stat.st_ino:x}:{service.db_path.name}"
            ),
            warehouse_key=key,
            warehouse_label=label,
        )

    def replace_primary_runtime(self, runtime: RouteRuntime) -> None:
        self._sites[DEFAULT_SITE_KEY] = WarehouseSite(
            DEFAULT_SITE_KEY, "IXcellerate", runtime
        )

    def get(self, key: str) -> WarehouseSite:
        normalized = str(key or DEFAULT_SITE_KEY).strip().lower()
        try:
            return self._sites[normalized]
        except KeyError as error:
            raise ValueError("Неизвестный склад") from error

    def public(self, selected: str) -> list[dict[str, Any]]:
        return [
            site.public(selected=site.key == selected)
            for site in self._sites.values()
        ]

    def selected_key(self, session: dict[str, str]) -> str:
        try:
            return self.get(session.get("warehouse", DEFAULT_SITE_KEY)).key
        except ValueError:
            return DEFAULT_SITE_KEY

    def select_session(
        self,
        sessions: dict[str, dict[str, str]],
        lock: Any,
        *,
        token: str,
        requested: str,
        last_seen: str,
        purge: Any,
    ) -> WarehouseSite:
        selected = self.get(requested)
        with lock:
            purge()
            session = sessions.get(token)
            if session is None:
                raise ValueError("Сессия завершена")
            session.update(warehouse=selected.key, last_seen=last_seen)
        return selected

    @contextmanager
    def actor_context(
        self,
        site: WarehouseSite,
        primary_context: ApplicationContext,
        *,
        author_name: str,
        role_override: str | None,
    ) -> Iterable[None]:
        if site.runtime.service is primary_context.service_adapter():
            context = nullcontext()
        else:
            context = site.runtime.service.administration_service.delegated_user_context(
                primary_context.administration.current_user(),
                author_name=author_name,
                role_override=role_override,
            )
        with context:
            yield


def build_warehouse_site_registry(
    primary_context: ApplicationContext,
    primary_runtime: RouteRuntime,
) -> WarehouseSiteRegistry:
    """Build configured sites without expanding the common HTTP shell."""
    settings = (
        primary_context.configuration.settings
        if primary_context.configuration is not None
        else {}
    )
    enable_solar = bool(
        settings.get(
            "warehouse_sites_enabled",
            primary_context.db_path.resolve() == DEFAULT_DB_PATH.resolve()
            and primary_context.configuration is not None
            and primary_context.configuration.warehouse_contour == "production"
            and not primary_runtime.migration_full_status.get("read_only")
            and not primary_runtime.migration_pilot_status.get("enabled"),
        )
    )
    registry = WarehouseSiteRegistry(
        primary_context,
        solar_db_path=settings.get("solar_db_path"),
        enable_solar=enable_solar,
    )
    registry.replace_primary_runtime(primary_runtime)
    return registry
