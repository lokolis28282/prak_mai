"""Canonical project paths and fail-closed development database policy."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from ode.application.errors import ConfigurationError


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DDL_ROOT = PROJECT_ROOT / "docs" / "architecture" / "ddl"
MANIFEST_PATH = PROJECT_ROOT / "ode" / "schema_manifest.json"
LOCAL_DATABASE_ROOT = PROJECT_ROOT / ".local" / "ode013"
SYSTEM_TEMP_ROOT = Path(tempfile.gettempdir()).resolve(strict=False)
PRODUCTION_DATABASE = (PROJECT_ROOT / "data" / "warehouse.db").resolve(strict=False)
FORBIDDEN_SOURCE_ROOTS = (
    (PROJECT_ROOT / "migration_inputs" / "raw").resolve(strict=False),
)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _lexical_absolute(path: Path) -> Path:
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return Path(os.path.abspath(os.fspath(path)))


def canonical_database_path(
    value: str | Path,
    *,
    allow_external_dev_path: bool,
) -> tuple[Path, bool]:
    """Validate a development/test DB path and report external override use."""

    try:
        raw = Path(value).expanduser()
        path_text = os.fspath(raw)
        lexical = _lexical_absolute(raw)
        resolved = lexical.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ConfigurationError(
            "INVALID_DATABASE_PATH", "Database path is malformed"
        ) from exc
    if not path_text.strip() or raw.name in {"", ".", ".."}:
        raise ConfigurationError("INVALID_DATABASE_PATH", "Database path is malformed")
    if resolved.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
        raise ConfigurationError(
            "INVALID_DATABASE_PATH", "Database path must name a SQLite file"
        )
    if resolved == PRODUCTION_DATABASE:
        raise ConfigurationError(
            "PRODUCTION_DATABASE_FORBIDDEN",
            "ODE 0.13 foundation cannot open the legacy production database",
        )
    try:
        aliases_production = (
            resolved.exists()
            and PRODUCTION_DATABASE.exists()
            and os.path.samefile(resolved, PRODUCTION_DATABASE)
        )
    except OSError:
        aliases_production = False
    if aliases_production:
        raise ConfigurationError(
            "PRODUCTION_DATABASE_FORBIDDEN",
            "ODE 0.13 foundation cannot open an alias of the legacy production database",
        )
    if any(_is_within(resolved, root) for root in FORBIDDEN_SOURCE_ROOTS):
        raise ConfigurationError(
            "SOURCE_PATH_FORBIDDEN",
            "Database path cannot be inside an immutable source directory",
        )

    allowed_lexical_root = next(
        (root for root in (LOCAL_DATABASE_ROOT, SYSTEM_TEMP_ROOT) if _is_within(lexical, root)),
        None,
    )
    if allowed_lexical_root is not None and not _is_within(resolved, allowed_lexical_root):
        raise ConfigurationError(
            "SYMLINK_ESCAPE",
            "Database path escapes its allowed development/test root through a symlink",
        )
    if _is_within(resolved, LOCAL_DATABASE_ROOT) or _is_within(
        resolved, SYSTEM_TEMP_ROOT
    ):
        return resolved, False
    if not allow_external_dev_path:
        raise ConfigurationError(
            "EXTERNAL_PATH_REQUIRES_OVERRIDE",
            "External development/test path requires --allow-external-dev-path",
        )
    return resolved, True
