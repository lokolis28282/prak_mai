#!/usr/bin/env python3
"""Check ODE module boundaries without importing the application."""

from __future__ import annotations

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

MIGRATION_REQUIRED_MODULES = (
    "__init__.py",
    "models.py",
    "reference_data.py",
    "canonical_naming.py",
    "xlsx_cells.py",
    "serial_preservation.py",
    "staging_schema.py",
    "candidate_db.py",
    "validation.py",
    "pilot_models.py",
    "pilot_schema.py",
    "pilot_selector.py",
    "pilot_builder.py",
)

# Candidate-only table names must never leak into the production initializer.
MIGRATION_CANDIDATE_TABLES = (
    "migration_batches",
    "migration_source_files",
    "reference_domains_v2",
    "reference_values_v2",
    "reference_aliases_v2",
    "catalog_items_v2",
    "migration_staging_rows",
    "migration_serial_cells",
    "migration_validation_results",
    "migration_pilot_marker",
    "migration_pilot_selection",
    "migration_pilot_identities",
    "migration_pilot_provenance",
    "migration_pilot_quarantine",
    "migration_pilot_performance",
)


def python_imports(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as error:
        return {f"SYNTAX_ERROR:{error}"}
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            result.add(module)
            # ``from inventory import migration`` and ``from . import webapp``
            # carry the imported module in ``names``, not in ``node.module``.
            for alias in node.names:
                if alias.name != "*":
                    separator = "" if module.endswith(".") else "."
                    result.add(f"{module}{separator}{alias.name}")
    return result


def files(root: str, pattern: str = "*.py") -> list[Path]:
    base = ROOT / root
    if not base.exists():
        return []
    return [path for path in base.rglob(pattern) if "__pycache__" not in path.parts]


def contains(path: Path, needles: tuple[str, ...]) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return [needle for needle in needles if needle in text]


def direct_service_calls_in_function(path: Path, function_name: str, forbidden: set[str]) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            for child in ast.walk(node):
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and isinstance(child.func.value, ast.Name)
                    and child.func.value.id == "service"
                    and child.func.attr in forbidden
                ):
                    calls.append(child.func.attr)
    return sorted(set(calls))


def main() -> int:
    errors: list[str] = []

    # ODE 0.13 is a side-by-side runtime and must remain isolated from 0.12.
    for path in files("ode"):
        imports = python_imports(path)
        bad = sorted(item for item in imports if item == "inventory" or item.startswith("inventory."))
        if bad:
            errors.append(
                f"{path.relative_to(ROOT)} imports legacy runtime: " + ", ".join(bad)
            )
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(isinstance(node, ast.Name) and node.id == "Any" for node in ast.walk(tree)):
            errors.append(f"{path.relative_to(ROOT)} uses Any in the ODE 0.13 contract")

    for path in files("inventory"):
        imports = python_imports(path)
        bad = sorted(item for item in imports if item == "ode" or item.startswith("ode."))
        if bad:
            errors.append(
                f"{path.relative_to(ROOT)} imports ODE 0.13 runtime: " + ", ".join(bad)
            )

    # The disposable baseline rehearsal is the only explicit anti-corruption
    # bridge between legacy Preview evidence and the target ODE schema.
    for path in files("baseline_rehearsal"):
        imports = python_imports(path)
        forbidden = sorted(
            item for item in imports
            if item in {
                "inventory.webapp", "inventory.service", "inventory.db",
                "inventory.migration", "inventory.reports", "inventory.monitoring",
            }
            or item.startswith("inventory.migration.")
            or item.startswith("inventory.reports.")
            or item.startswith("inventory.monitoring.")
        )
        if forbidden:
            errors.append(
                f"{path.relative_to(ROOT)} crosses rehearsal bridge boundary: "
                + ", ".join(forbidden)
            )
        if "data/warehouse.db" in path.read_text(encoding="utf-8"):
            errors.append(f"{path.relative_to(ROOT)} embeds the production DB path")

    for path in files("inventory"):
        imports = python_imports(path)
        bridge = sorted(
            item for item in imports
            if item == "baseline_rehearsal" or item.startswith("baseline_rehearsal.")
        )
        if bridge and path.relative_to(ROOT).as_posix() != "inventory/warehouse/baseline/service.py":
            errors.append(
                f"{path.relative_to(ROOT)} imports the restricted rehearsal bridge: "
                + ", ".join(bridge)
            )

    for path in files("ode"):
        imports = python_imports(path)
        bridge = sorted(
            item for item in imports
            if item == "baseline_rehearsal" or item.startswith("baseline_rehearsal.")
        )
        if bridge:
            errors.append(
                f"{path.relative_to(ROOT)} imports the legacy rehearsal bridge: "
                + ", ".join(bridge)
            )

    for path in files("ode/system"):
        imports = python_imports(path)
        bad = sorted(
            item for item in imports
            if item in {"sqlite3", "os", "pathlib"} or item.startswith("ode.infrastructure")
        )
        if bad:
            errors.append(
                f"{path.relative_to(ROOT)} crosses the system/infrastructure boundary: "
                + ", ".join(bad)
            )

    for path in files("ode/application"):
        imports = python_imports(path)
        bad = sorted(item for item in imports if item == "inventory" or item.startswith("inventory."))
        if bad:
            errors.append(
                f"{path.relative_to(ROOT)} imports legacy application runtime: "
                + ", ".join(bad)
            )

    for path in files("ode/application") + files("ode/system"):
        sql = contains(path, ("CREATE TABLE", "ALTER TABLE", "DROP TABLE", "INSERT INTO"))
        if sql:
            errors.append(
                f"{path.relative_to(ROOT)} embeds infrastructure SQL: " + ", ".join(sql)
            )

    for path in files("ode"):
        if "data/warehouse.db" in path.read_text(encoding="utf-8"):
            errors.append(f"{path.relative_to(ROOT)} embeds the production DB path")

    migration_root = ROOT / "inventory/migration"
    missing_migration_modules = [
        f"inventory/migration/{name}"
        for name in MIGRATION_REQUIRED_MODULES
        if not (migration_root / name).is_file()
    ]
    if missing_migration_modules:
        errors.append(
            "offline migration foundation modules are missing: "
            + ", ".join(missing_migration_modules)
        )

    forbidden_migration_roots = (
        "inventory.webapp",
        "inventory.service",
        "inventory.services",
        "inventory.warehouse",
        "inventory.reports",
        "inventory.administration",
        "webapp",
        "service",
        "services",
        "warehouse",
        "reports",
        "administration",
    )
    for path in files("inventory/migration"):
        imports = python_imports(path)
        bad = sorted(
            item
            for item in imports
            for forbidden in forbidden_migration_roots
            if item.lstrip(".") == forbidden
            or item.lstrip(".").startswith(forbidden + ".")
        )
        if bad:
            errors.append(
                f"{path.relative_to(ROOT)} imports runtime/production modules: "
                + ", ".join(sorted(set(bad)))
            )

    for path in files("inventory"):
        if migration_root in path.parents:
            continue
        imports = python_imports(path)
        bad = sorted(
            item for item in imports
            if item == "inventory.migration"
            or item.startswith("inventory.migration.")
            or item.lstrip(".") == "migration"
            or item.lstrip(".").startswith("migration.")
        )
        if bad:
            errors.append(
                f"{path.relative_to(ROOT)} imports offline migration modules: "
                + ", ".join(bad)
            )

    production_db = ROOT / "inventory/db.py"
    leaked_candidate_tables = contains(production_db, MIGRATION_CANDIDATE_TABLES)
    if leaked_candidate_tables:
        errors.append(
            "inventory/db.py contains candidate-only migration tables: "
            + ", ".join(leaked_candidate_tables)
        )

    forbidden_monitoring = (
        "inventory.service",
        "inventory.services.warehouse_service",
        "inventory.warehouse",
        "inventory.reports",
        ".warehouse",
        ".reports",
    )
    for path in files("inventory/monitoring"):
        imports = python_imports(path)
        bad = sorted(item for item in imports for forbidden in forbidden_monitoring if item == forbidden or item.startswith(forbidden + "."))
        if bad:
            errors.append(f"{path.relative_to(ROOT)} imports forbidden modules: {', '.join(bad)}")

    forbidden_reports = (
        "inventory.routes",
        "inventory.services.warehouse_service",
        "inventory.warehouse.receipts",
        "inventory.warehouse.issues",
        "inventory.warehouse.balance",
        "inventory.warehouse.deliveries",
        "inventory.warehouse.history",
    )
    for path in files("inventory/reports"):
        imports = python_imports(path)
        bad = sorted(item for item in imports for forbidden in forbidden_reports if item == forbidden or item.startswith(forbidden + "."))
        if bad:
            errors.append(f"{path.relative_to(ROOT)} imports internal warehouse modules: {', '.join(bad)}")
        table_refs = contains(path, (
            "FROM stock_receipts", "JOIN stock_receipts", "FROM stock_issues",
            "JOIN stock_issues", "FROM stock_issue_allocations",
            "JOIN stock_issue_allocations", "FROM deliveries",
            "JOIN deliveries", "FROM delivery_lines", "JOIN delivery_lines",
            "INSERT INTO stock_receipts", "INSERT INTO stock_issues",
            "INSERT INTO stock_issue_allocations", "INSERT INTO deliveries",
            "INSERT INTO delivery_lines", "UPDATE stock_receipts",
            "UPDATE stock_issues", "UPDATE stock_issue_allocations",
            "UPDATE deliveries", "UPDATE delivery_lines",
        ))
        if table_refs:
            errors.append(f"{path.relative_to(ROOT)} references warehouse-owned tables: {', '.join(table_refs)}")
        forbidden_sql_refs = contains(path, (
            "INSERT INTO equipment", "INSERT INTO operations",
            "UPDATE equipment", "UPDATE operations",
            "DELETE FROM equipment", "DELETE FROM operations",
        ))
        if forbidden_sql_refs:
            errors.append(f"{path.relative_to(ROOT)} writes non-reports tables: {', '.join(forbidden_sql_refs)}")

    for path in files("inventory/warehouse"):
        imports = python_imports(path)
        bad = sorted(item for item in imports if item == "inventory.reports" or item.startswith("inventory.reports."))
        if bad:
            errors.append(f"{path.relative_to(ROOT)} imports reports: {', '.join(bad)}")
    receipt_modules = {
        ROOT / "inventory/warehouse/receipts.py",
        ROOT / "inventory/warehouse/receipt_imports.py",
        ROOT / "inventory/warehouse/receipt_repository.py",
        ROOT / "inventory/warehouse/validators.py",
        ROOT / "inventory/warehouse/naming.py",
        ROOT / "inventory/warehouse/previews.py",
    }
    missing_receipt_modules = [
        path.relative_to(ROOT).as_posix() for path in receipt_modules if not path.exists()
    ]
    if missing_receipt_modules:
        errors.append(
            "receipt implementation modules are missing: "
            + ", ".join(missing_receipt_modules)
        )
    cable_modules = {
        ROOT / "inventory/warehouse/cables.py",
        ROOT / "inventory/warehouse/cable_repository.py",
        ROOT / "inventory/warehouse/cable_validators.py",
        ROOT / "inventory/warehouse/cable_models.py",
    }
    missing_cable_modules = [
        path.relative_to(ROOT).as_posix() for path in cable_modules if not path.exists()
    ]
    if missing_cable_modules:
        errors.append(
            "cable implementation modules are missing: "
            + ", ".join(missing_cable_modules)
        )
    issue_modules = {
        ROOT / "inventory/warehouse/issues.py",
        ROOT / "inventory/warehouse/issue_imports.py",
        ROOT / "inventory/warehouse/issue_repository.py",
        ROOT / "inventory/warehouse/issue_validators.py",
        ROOT / "inventory/warehouse/issue_models.py",
        ROOT / "inventory/warehouse/issue_previews.py",
    }
    missing_issue_modules = [
        path.relative_to(ROOT).as_posix() for path in issue_modules if not path.exists()
    ]
    if missing_issue_modules:
        errors.append(
            "issue implementation modules are missing: "
            + ", ".join(missing_issue_modules)
        )
    delivery_modules = {
        ROOT / "inventory/warehouse/deliveries.py",
        ROOT / "inventory/warehouse/delivery_imports.py",
        ROOT / "inventory/warehouse/delivery_acceptance.py",
        ROOT / "inventory/warehouse/delivery_repository.py",
        ROOT / "inventory/warehouse/delivery_validators.py",
        ROOT / "inventory/warehouse/delivery_mapping.py",
        ROOT / "inventory/warehouse/delivery_models.py",
        ROOT / "inventory/warehouse/delivery_previews.py",
    }
    missing_delivery_modules = [
        path.relative_to(ROOT).as_posix() for path in delivery_modules if not path.exists()
    ]
    if missing_delivery_modules:
        errors.append(
            "delivery implementation modules are missing: "
            + ", ".join(missing_delivery_modules)
        )
    delivery_imports = ROOT / "inventory/warehouse/delivery_imports.py"
    if delivery_imports.exists():
        bad_delivery_writes = contains(delivery_imports, (
            "INSERT INTO stock_receipts", "UPDATE stock_receipts", "DELETE FROM stock_receipts",
            "INSERT INTO stock_issues", "UPDATE stock_issues", "DELETE FROM stock_issues",
            "INSERT INTO stock_issue_allocations", "UPDATE stock_issue_allocations",
            "DELETE FROM stock_issue_allocations", "allocations",
        ))
        if bad_delivery_writes:
            errors.append(
                "inventory/warehouse/delivery_imports.py writes forbidden warehouse movement tables: "
                + ", ".join(bad_delivery_writes)
            )
    delivery_acceptance = ROOT / "inventory/warehouse/delivery_acceptance.py"
    if delivery_acceptance.exists():
        bad_acceptance_sql = contains(delivery_acceptance, (
            "INSERT INTO stock_receipts", "ReceiptRepository.insert_sql",
            "INSERT INTO stock_issues", "INSERT INTO stock_issue_allocations",
            "DELETE FROM stock_receipts", "DELETE FROM stock_issues",
            "DELETE FROM stock_issue_allocations",
        ))
        if bad_acceptance_sql:
            errors.append(
                "inventory/warehouse/delivery_acceptance.py bypasses receipt contract or writes forbidden tables: "
                + ", ".join(bad_acceptance_sql)
            )
        if "insert_one_in_transaction" not in delivery_acceptance.read_text(encoding="utf-8"):
            errors.append("delivery acceptance does not use receipt repository transaction contract")

    for path in files("static/js/monitoring", "*.js"):
        bad = contains(path, ("warehouse.", "ODE.warehouse", "reports.", "ODE.reports"))
        if bad:
            errors.append(f"{path.relative_to(ROOT)} references forbidden frontend modules: {', '.join(bad)}")

    webapp = ROOT / "inventory/webapp.py"
    webapp_text = webapp.read_text(encoding="utf-8")
    warehouse_routes = ROOT / "inventory/routes/warehouse.py"
    reports_routes = ROOT / "inventory/routes/reports.py"
    administration_routes = ROOT / "inventory/routes/administration.py"
    warehouse_routes_text = warehouse_routes.read_text(encoding="utf-8")
    if "ApplicationContext" not in webapp_text or "ensure_application_context" not in webapp_text:
        errors.append("inventory/webapp.py does not use ApplicationContext boundary")
    if "WarehouseCore" in webapp_text:
        errors.append("inventory/webapp.py references WarehouseCore directly")
    if "WarehouseEventReader" in webapp_text:
        errors.append("inventory/webapp.py creates or references WarehouseEventReader directly")
    if len(webapp_text.splitlines()) > 1_000:
        errors.append("inventory/webapp.py exceeds the Stage 4 thin-shell limit of 1000 lines")
    if "<!doctype html>" in webapp_text:
        errors.append("inventory/webapp.py still embeds an HTML document")
    for route_name in (
        "administration", "reports", "warehouse", "monitoring", "knowledge",
    ):
        route_path = ROOT / "inventory/routes" / f"{route_name}.py"
        if not route_path.is_file():
            errors.append(f"missing Stage 4 route module inventory/routes/{route_name}.py")
    template_path = ROOT / "inventory/templates/webapp.py"
    if not template_path.is_file() or "<!doctype html>" not in template_path.read_text(
        encoding="utf-8"
    ):
        errors.append("inventory/templates/webapp.py does not own the HTML template")
    for forbidden_facade in (
        "app_context.reports.",
        "app_context.monitoring.",
        "app_context.knowledge.",
    ):
        if forbidden_facade in webapp_text:
            errors.append(
                f"inventory/webapp.py still contains domain route logic: {forbidden_facade}"
            )
    forbidden_read_calls = {
        "dashboard_stats", "equipment", "operation_log", "reference_data",
        "references", "stock_balance", "stock_receipts", "stock_issue_rows",
        "data_quality_problems", "deliveries", "delivery", "warehouse_categories",
        "warehouse_history", "search_stock_positions", "position_card",
    }
    bad_read_calls = direct_service_calls_in_function(
        warehouse_routes, "handle_get", forbidden_read_calls
    )
    if bad_read_calls:
        errors.append(
            "inventory/routes/warehouse.py handle_get calls warehouse compatibility methods directly: "
            + ", ".join(bad_read_calls)
        )
    forbidden_report_calls = {
        "work_logs", "daily_report", "weekly_report", "weekly_report_rows",
        "daily_report_uploads", "uploaded_daily_report", "export_work_logs_csv",
    }
    bad_report_calls = direct_service_calls_in_function(
        reports_routes, "handle_get", forbidden_report_calls
    )
    if bad_report_calls:
        errors.append(
            "inventory/routes/reports.py handle_get calls reports compatibility methods directly: "
            + ", ".join(bad_report_calls)
        )
    forbidden_report_write_calls = {
        "add_work_log", "add_work_logs", "import_work_log_rows",
        "preview_work_log_rows", "confirm_work_log_preview",
        "import_daily_report_rows",
    }
    bad_report_write_calls = direct_service_calls_in_function(
        reports_routes, "handle_action", forbidden_report_write_calls
    )
    if bad_report_write_calls:
        errors.append(
            "inventory/routes/reports.py calls reports write compatibility methods directly: "
            + ", ".join(bad_report_write_calls)
        )
    forbidden_receipt_write_calls = {
        "add_stock_receipt", "preview_stock_receipt_rows",
        "confirm_stock_receipt_preview", "scan_receipt_serial",
        "confirm_scanned_receipts", "import_stock_receipt_rows",
    }
    bad_receipt_write_calls = direct_service_calls_in_function(
        warehouse_routes, "handle_action", forbidden_receipt_write_calls
    )
    bad_receipt_get_calls = direct_service_calls_in_function(
        warehouse_routes, "handle_get", {"scan_receipt_serial"}
    )
    if bad_receipt_write_calls or bad_receipt_get_calls:
        errors.append(
            "inventory/routes/warehouse.py calls receipt write compatibility methods directly: "
            + ", ".join(sorted(set(bad_receipt_write_calls + bad_receipt_get_calls)))
        )
    if (
        "create_cable_receipt" not in warehouse_routes_text
        or "create_cable_issue" not in warehouse_routes_text
    ):
        errors.append(
            "inventory/routes/warehouse.py does not route cable writes through WarehouseFacade"
        )
    if "app_context.warehouse._is_cable_issue(data)" not in warehouse_routes_text:
        errors.append(
            "inventory/routes/warehouse.py does not branch cable issue before legacy issue flow"
        )
    forbidden_issue_write_calls = {
        "add_stock_issue", "scan_issue_serial", "confirm_scanned_issues",
        "import_stock_issue_rows", "preview_stock_issue_rows",
        "confirm_stock_issue_preview", "preview_bulk_issue_serials",
        "confirm_bulk_issue_preview",
    }
    bad_issue_write_calls = sorted(set(
        direct_service_calls_in_function(
            warehouse_routes, "handle_get", forbidden_issue_write_calls
        )
        + direct_service_calls_in_function(
            warehouse_routes, "handle_action", forbidden_issue_write_calls
        )
        + direct_service_calls_in_function(
            warehouse_routes, "import_csv", forbidden_issue_write_calls
        )
    ))
    if bad_issue_write_calls:
        errors.append(
            "inventory/routes/warehouse.py calls issue write compatibility methods directly: "
            + ", ".join(bad_issue_write_calls)
        )
    forbidden_delivery_import_calls = {
        "preview_delivery_rows", "confirm_delivery_preview",
    }
    bad_delivery_import_calls = sorted(set(
        direct_service_calls_in_function(
            warehouse_routes, "handle_action", forbidden_delivery_import_calls
        )
        + direct_service_calls_in_function(
            warehouse_routes, "import_csv", forbidden_delivery_import_calls
        )
    ))
    if bad_delivery_import_calls:
        errors.append(
            "inventory/routes/warehouse.py calls legacy delivery import methods directly: "
            + ", ".join(bad_delivery_import_calls)
        )
    forbidden_delivery_acceptance_calls = {
        "accept_delivery_serial", "update_delivery_lines",
    }
    bad_delivery_acceptance_calls = sorted(set(
        direct_service_calls_in_function(
            warehouse_routes, "handle_action", forbidden_delivery_acceptance_calls
        )
    ))
    if bad_delivery_acceptance_calls:
        errors.append(
            "inventory/routes/warehouse.py calls legacy delivery acceptance methods directly: "
            + ", ".join(bad_delivery_acceptance_calls)
        )
    for required_call in (
        "preview_delivery_import", "confirm_delivery_import",
        "list_deliveries", "get_delivery", "export_delivery_rows",
        "get_delivery_import_template",
        "inspect_delivery_serial", "accept_delivery_serial",
        "accept_unplanned_delivery_serial", "accept_delivery_batch",
        "update_delivery_line_metadata",
    ):
        if required_call not in warehouse_routes_text:
            errors.append(
                f"inventory/routes/warehouse.py missing facade delivery route {required_call}"
            )
    for required_call in (
        "validate_issue_serial", "create_issue(", "create_issue_by_serials",
        "preview_issue_import", "confirm_issue_import", "import_issues",
        "preview_bulk_issue_serials", "confirm_bulk_issue_preview",
    ):
        if required_call not in warehouse_routes_text:
            errors.append(
                f"inventory/routes/warehouse.py missing facade issue route {required_call}"
            )
    forbidden_administration_calls = {
        "current_user", "user_by_email", "users", "audit_entries", "list_backups",
    }
    bad_administration_calls = direct_service_calls_in_function(
        administration_routes, "handle_get", forbidden_administration_calls
    )
    if bad_administration_calls:
        errors.append(
            "inventory/routes/administration.py calls administration compatibility methods directly: "
            + ", ".join(bad_administration_calls)
        )

    forbidden_administration_imports = (
        "inventory.services.warehouse_service",
        "inventory.warehouse",
        "inventory.reports",
    )
    for path in files("inventory/administration"):
        imports = python_imports(path)
        bad = sorted(item for item in imports for forbidden in forbidden_administration_imports if item == forbidden or item.startswith(forbidden + "."))
        if bad:
            errors.append(f"{path.relative_to(ROOT)} imports forbidden modules: {', '.join(bad)}")

    # Vacations is a standalone application module with its own SQLite file.
    forbidden_vacations = (
        "inventory.service",
        "inventory.warehouse",
        "inventory.reports",
        "inventory.monitoring",
        "inventory.knowledge",
        "inventory.administration",
    )
    for path in files("inventory/vacations"):
        imports = python_imports(path)
        bad = sorted(
            item
            for item in imports
            for forbidden in forbidden_vacations
            if item == forbidden or item.startswith(forbidden + ".")
        )
        if bad:
            errors.append(
                f"{path.relative_to(ROOT)} imports forbidden modules: "
                + ", ".join(bad)
            )
        forbidden_storage = contains(
            path,
            (
                "warehouse.db",
                "warehouse_solar.db",
                "stock_receipts",
                "stock_issues",
                "work_logs",
                "INSERT INTO audit_log",
            ),
        )
        if forbidden_storage:
            errors.append(
                f"{path.relative_to(ROOT)} references non-vacation storage: "
                + ", ".join(forbidden_storage)
            )

    for path in files("inventory/monitoring"):
        if contains(path, ("WarehouseEventReader", "warehouse_events")):
            errors.append(f"{path.relative_to(ROOT)} references WarehouseEventReader")

    reports_facade = ROOT / "inventory/reports/facade.py"
    if "warehouse_events" not in reports_facade.read_text(encoding="utf-8"):
        errors.append("ReportsFacade does not receive warehouse_events through constructor")
    application = ROOT / "inventory/core/application.py"
    app_text = application.read_text(encoding="utf-8")
    service_composition = (ROOT / "inventory/service.py").read_text(encoding="utf-8")
    reports_wired_once = (
        "WarehouseEventReader(self)" in service_composition
        and "warehouse_events=self.warehouse_event_reader" in service_composition
        and "reports=service.reports_service" in app_text
    )
    if not reports_wired_once:
        errors.append(
            "composition does not wire one WarehouseEventReader into the shared ReportsFacade"
        )
    forbidden_report_sql = contains(
        ROOT / "inventory/services/warehouse_service.py",
        (
            "INSERT INTO work_logs",
            "FROM work_logs",
            "INSERT INTO daily_report_uploads",
            "FROM daily_report_rows",
        ),
    )
    if forbidden_report_sql:
        errors.append(
            "WarehouseCore still contains Reports-owned SQL: "
            + ", ".join(forbidden_report_sql)
        )
    if "self.reports_service = ReportsFacade(" not in service_composition:
        errors.append("WarehouseService does not expose the independent Reports boundary")
    if (ROOT / "inventory/services/report_service.py").exists():
        errors.append("obsolete compatibility ReportService still exists")

    warehouse_core = ROOT / "inventory/services/warehouse_service.py"
    warehouse_domain = ROOT / "inventory/warehouse/service.py"
    core_text = warehouse_core.read_text(encoding="utf-8")
    domain_text = warehouse_domain.read_text(encoding="utf-8")
    forbidden_warehouse_core_tokens = (
        "SELECT ",
        "INSERT ",
        "UPDATE ",
        "DELETE ",
        "connect(",
    )
    for path, text in (
        (warehouse_core, core_text),
        (warehouse_domain, domain_text),
    ):
        bad = [token for token in forbidden_warehouse_core_tokens if token in text]
        if bad:
            errors.append(
                f"{path.relative_to(ROOT)} contains Warehouse business persistence: "
                + ", ".join(bad)
            )
    if len(core_text.splitlines()) > 250:
        errors.append("WarehouseCore is no longer a thin compatibility adapter")
    for method in (
        "add_stock_receipt",
        "import_stock_receipt_rows",
        "add_stock_issue",
        "import_stock_issue_rows",
        "preview_delivery_rows",
        "accept_delivery_serial",
        "stock_balance",
        "global_search",
        "data_quality_problems",
    ):
        if f"def {method}(" in core_text or f"def {method}(" in domain_text:
            errors.append(
                f"removed Warehouse workflow still has a second implementation: {method}"
            )
    for composition_token in (
        "WarehouseHistoryService(self)",
        "LegacyInventoryService(self)",
        "WarehouseBalanceService(self)",
        "WarehouseMonitoringService(self)",
        "WarehouseReferenceService(self)",
    ):
        if composition_token not in domain_text:
            errors.append(
                "WarehouseDomainService missing component "
                + composition_token
            )
    for shared_token in (
        "previews=self.receipt_service.previews",
        "cables=self.receipt_service.cables",
        "receipt_writer=self.receipt_service.writer",
    ):
        if shared_token not in service_composition:
            errors.append(
                "WarehouseService does not share extracted write dependency "
                + shared_token
            )
    facade_text = (ROOT / "inventory/warehouse/facade.py").read_text(
        encoding="utf-8"
    )
    for shared_token in (
        'getattr(receipt_compat, "writer", None)',
        'getattr(issue_compat, "writer", None)',
        'delivery_compat, "acceptance", None',
    ):
        if shared_token not in facade_text:
            errors.append(
                "WarehouseFacade does not reuse composed compatibility service "
                + shared_token
            )
    for compatibility_alias in (
        "balance_service.py",
        "history_service.py",
        "inventory_service.py",
        "monitoring_service.py",
        "reference_service.py",
    ):
        adapter_text = (
            ROOT / "inventory/services" / compatibility_alias
        ).read_text(encoding="utf-8")
        if "ServiceAdapter" in adapter_text or "self.call(" in adapter_text:
            errors.append(
                f"inventory/services/{compatibility_alias} still delegates "
                "business logic back to WarehouseCore"
            )
    if (ROOT / "inventory/services/_base.py").exists():
        errors.append("obsolete string-dispatch ServiceAdapter still exists")
    profile_adapter = (
        ROOT / "inventory/services/profile_service.py"
    ).read_text(encoding="utf-8")
    if "ServiceAdapter" in profile_adapter or "self.call(" in profile_adapter:
        errors.append(
            "ProfileService still dispatches Administration through WarehouseCore"
        )

    ownership = ROOT / "docs/DATABASE_OWNERSHIP.md"
    if not ownership.exists():
        errors.append("docs/DATABASE_OWNERSHIP.md is missing")
    else:
        text = ownership.read_text(encoding="utf-8")
        for table in (
            "stock_receipts", "stock_issues", "stock_issue_allocations",
            "deliveries", "delivery_lines", "equipment", "operations",
            "reference_values", "work_logs", "daily_report_uploads",
            "daily_report_rows", "users", "audit_log",
        ):
            if f"`{table}`" not in text:
                errors.append(f"docs/DATABASE_OWNERSHIP.md missing owner for {table}")

    if errors:
        print("module-boundaries: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("module-boundaries: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
