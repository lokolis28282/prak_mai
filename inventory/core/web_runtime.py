"""Fail-closed composition of databases used by the local web runtime."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from inventory.core.application import ApplicationContext, create_application_context
from inventory.db import DEFAULT_DB_PATH
from inventory.monitoring.facade import MonitoringFacade
from inventory.service import WarehouseService
from inventory.shared.runtime_paths import (
    RUNTIME_DATABASE_PATHS,
    same_path_or_file,
    test_contour_database_has_sidecars,
    test_contour_database_state,
    TEST_CONTOUR_STATE_ABSENT,
    TEST_CONTOUR_STATE_MISSING,
)
from inventory.vacations.schema import prepare_vacations_database
from inventory.warehouse.baseline.posting_policy import PostingPolicy
from inventory.warehouse.migration_full_review import validate_full_migration_database
from inventory.warehouse.migration_pilot_review import validate_migration_pilot_database
from inventory.warehouse.sites import (
    configured_solar_path,
    warehouse_runtime_config,
)


@dataclass(slots=True)
class PreparedWebRuntime:
    """Composed application objects plus owned review-only temporary state."""

    app_context: ApplicationContext
    service: WarehouseService
    contour_label: str
    cards: int
    integrity_status: str
    solar_path: Path | None
    _owned_runtime: tempfile.TemporaryDirectory[str] | None = None

    def close(self) -> None:
        if self._owned_runtime is not None:
            self._owned_runtime.cleanup()
            self._owned_runtime = None


def _selected_databases(
    db_path: str | Path,
    solar_db_path: str | Path | None,
    vacations_db_path: str | Path | None,
) -> dict[str, tuple[str | Path, str]]:
    selected: dict[str, tuple[str | Path, str]] = {
        "IXcellerate": (db_path, "warehouse")
    }
    if solar_db_path is not None:
        selected["Solar"] = (solar_db_path, "warehouse")
    if vacations_db_path is not None:
        selected["Vacations"] = (vacations_db_path, "vacations")
    return selected


def validate_runtime_database_contours(
    *,
    test_mode: bool,
    db_path: str | Path,
    solar_db_path: str | Path | None = None,
    vacations_db_path: str | Path | None = None,
    warehouse_contour: str = "production",
) -> None:
    """Reject production/test contour confusion before any schema write."""
    if test_mode:
        missing = [
            option
            for option, value in (
                ("--solar-db", solar_db_path),
                ("--vacations-db", vacations_db_path),
            )
            if value is None
        ]
        if missing:
            raise RuntimeError(
                "ODE_TEST_MODE=1 требует явные отдельные пути " + ", ".join(missing)
            )

    selected = _selected_databases(db_path, solar_db_path, vacations_db_path)
    selected_items = list(selected.items())
    for index, (left_name, (left_path, _)) in enumerate(selected_items):
        for right_name, (right_path, _) in selected_items[index + 1 :]:
            if same_path_or_file(left_path, right_path):
                raise RuntimeError(
                    "Runtime-БД должны использовать разные физические файлы; "
                    f"{left_name} и {right_name} указывают на один файл"
                )
    for selected_name, (selected_path, expected_role) in selected.items():
        if Path(selected_path).expanduser().is_symlink():
            raise RuntimeError(
                f"{selected_name} DB не может быть symbolic link"
            )
        if test_contour_database_has_sidecars(selected_path):
            raise RuntimeError(
                f"{selected_name} DB имеет SQLite sidecar (-wal/-shm/-journal); "
                "остановите другой процесс и используйте согласованно закрытую БД"
            )
        marker_state = test_contour_database_state(selected_path)
        if not test_mode and marker_state not in {
            TEST_CONTOUR_STATE_ABSENT,
            TEST_CONTOUR_STATE_MISSING,
        }:
            raise RuntimeError(
                f"{selected_name} содержит test contour marker/state "
                f"{marker_state}; запустите exact-valid test DB только штатным "
                "test launcher, повреждённый marker не используйте"
            )

        for protected_name, protected_path in RUNTIME_DATABASE_PATHS.items():
            if same_path_or_file(selected_path, protected_path):
                if test_mode or warehouse_contour == "demo":
                    mode = "ODE_TEST_MODE=1" if test_mode else "Demo contour"
                    raise RuntimeError(
                        f"{mode} нельзя использовать с рабочей {protected_name} DB "
                        f"({protected_path}); укажите отдельную БД для {selected_name}"
                    )
                if protected_name != selected_name:
                    raise RuntimeError(
                        f"{selected_name} не может использовать installation-owned "
                        f"{protected_name} DB; роли runtime-БД перепутаны"
                    )

        if test_mode and marker_state != expected_role:
            raise RuntimeError(
                "ODE_TEST_MODE=1 принимает только БД, созданные штатными "
                f"clean-test builders; {selected_name} не имеет marker роли "
                f"{expected_role}"
            )


def prepare_web_runtime(
    *,
    db_path: str | Path,
    solar_db_path: str | Path | None,
    vacations_db_path: str | Path | None,
    warehouse_contour: str,
    inventory_state_root: str | Path | None,
    test_mode: bool,
) -> PreparedWebRuntime:
    """Validate, initialize and compose the web runtime as one owned unit."""
    contour_policy = PostingPolicy(
        db_path,
        mode=warehouse_contour,
        production_db_path=DEFAULT_DB_PATH,
    )
    if warehouse_contour == "demo" and not contour_policy.demo:
        raise RuntimeError(str(contour_policy.status()["configuration_error"]))

    configuration = warehouse_runtime_config(
        db_path,
        contour=warehouse_contour,
        inventory_state_root=inventory_state_root,
        solar_path=solar_db_path,
    )
    selected_solar = (
        configured_solar_path(configuration.settings)
        if configuration.settings.get("warehouse_sites_enabled")
        else None
    )
    owned_runtime: tempfile.TemporaryDirectory[str] | None = None
    configured_vacations = vacations_db_path
    selected_vacations = Path(
        configured_vacations or Path(db_path).expanduser().with_name("vacations.db")
    )

    # Contour/path checks run before every review probe and every schema writer.
    validate_runtime_database_contours(
        test_mode=test_mode,
        db_path=db_path,
        solar_db_path=selected_solar,
        vacations_db_path=selected_vacations,
        warehouse_contour=warehouse_contour,
    )
    migration_full_status = validate_full_migration_database(db_path)
    migration_pilot_status = validate_migration_pilot_database(db_path)
    review_mode = bool(
        migration_pilot_status.get("enabled")
        or migration_full_status.get("read_only")
    )
    if review_mode and (solar_db_path or vacations_db_path):
        raise RuntimeError("Review contour не принимает --solar-db/--vacations-db")

    if test_mode or review_mode:
        owned_runtime = tempfile.TemporaryDirectory(prefix="ode_isolated_runtime_")
        owned_root = Path(owned_runtime.name).resolve()
        configuration.full_inventory_state_root = owned_root / "full_inventory"
        configuration.settings["backup_root"] = owned_root / "backups"
        if review_mode:
            configured_vacations = owned_root / "vacations.db"

    try:
        vacations_path = prepare_vacations_database(
            db_path, configured_vacations, selected_solar
        )
        service = WarehouseService(
            db_path,
            initialize_database=not migration_pilot_status.get("enabled")
            and not migration_full_status.get("read_only"),
        )
        app_context = create_application_context(
            db_path,
            service=service,
            vacations_db_path=vacations_path,
            configuration=configuration,
        )
        if owned_runtime is not None:
            owned_root = Path(owned_runtime.name).resolve()
            app_context.knowledge.upload_root = owned_root / "knowledge_uploads"
            monitoring_rules = owned_root / "monitoring_rules"
            monitoring_rules.mkdir(mode=0o700)
            app_context.monitoring = MonitoringFacade(
                rules_dir=monitoring_rules,
                collect_dcim=False,
                development_mock=True,
            )
        stats = service.dashboard_stats()
        health = app_context.administration.database_check(
            service.db_path, service.KEY_TABLES
        )
        contour_label = "REVIEW DATABASE" if review_mode else (
            "DEMO DATABASE" if contour_policy.demo else "WORKING PROVISIONAL DATABASE"
        )
        return PreparedWebRuntime(
            app_context=app_context,
            service=service,
            contour_label=contour_label,
            cards=int(stats.get("cards", stats["positions"])),
            integrity_status=(
                "ok" if health["ok"] else "; ".join(health["messages"])
            ),
            solar_path=selected_solar,
            _owned_runtime=owned_runtime,
        )
    except BaseException:
        if owned_runtime is not None:
            owned_runtime.cleanup()
        raise
