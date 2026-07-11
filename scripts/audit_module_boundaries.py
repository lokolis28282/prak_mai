#!/usr/bin/env python3
"""Check Stage 0.12.6 module boundaries without importing the application."""

from __future__ import annotations

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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
    if "ApplicationContext" not in webapp_text or "ensure_application_context" not in webapp_text:
        errors.append("inventory/webapp.py does not use ApplicationContext boundary")
    if "WarehouseCore" in webapp_text:
        errors.append("inventory/webapp.py references WarehouseCore directly")
    if "WarehouseEventReader" in webapp_text:
        errors.append("inventory/webapp.py creates or references WarehouseEventReader directly")
    forbidden_read_calls = {
        "dashboard_stats", "equipment", "operation_log", "reference_data",
        "references", "stock_balance", "stock_receipts", "stock_issue_rows",
        "data_quality_problems", "deliveries", "delivery", "warehouse_categories",
        "warehouse_history", "search_stock_positions", "position_card",
    }
    bad_read_calls = direct_service_calls_in_function(webapp, "_do_GET", forbidden_read_calls)
    if bad_read_calls:
        errors.append(
            "inventory/webapp.py _do_GET calls read-only warehouse service methods directly: "
            + ", ".join(bad_read_calls)
        )
    forbidden_report_calls = {
        "work_logs", "daily_report", "weekly_report", "weekly_report_rows",
        "daily_report_uploads", "uploaded_daily_report", "export_work_logs_csv",
    }
    bad_report_calls = direct_service_calls_in_function(webapp, "_do_GET", forbidden_report_calls)
    if bad_report_calls:
        errors.append(
            "inventory/webapp.py _do_GET calls read-only reports service methods directly: "
            + ", ".join(bad_report_calls)
        )
    forbidden_report_write_calls = {
        "add_work_log", "add_work_logs", "import_work_log_rows",
        "preview_work_log_rows", "confirm_work_log_preview",
        "import_daily_report_rows",
    }
    bad_report_write_calls = direct_service_calls_in_function(
        webapp, "_do_POST", forbidden_report_write_calls
    )
    if bad_report_write_calls:
        errors.append(
            "inventory/webapp.py _do_POST calls reports write compatibility methods directly: "
            + ", ".join(bad_report_write_calls)
        )
    forbidden_receipt_write_calls = {
        "add_stock_receipt", "preview_stock_receipt_rows",
        "confirm_stock_receipt_preview", "scan_receipt_serial",
        "confirm_scanned_receipts", "import_stock_receipt_rows",
    }
    bad_receipt_write_calls = direct_service_calls_in_function(
        webapp, "_do_POST", forbidden_receipt_write_calls
    )
    bad_receipt_get_calls = direct_service_calls_in_function(
        webapp, "_do_GET", {"scan_receipt_serial"}
    )
    if bad_receipt_write_calls or bad_receipt_get_calls:
        errors.append(
            "inventory/webapp.py calls receipt write compatibility methods directly: "
            + ", ".join(sorted(set(bad_receipt_write_calls + bad_receipt_get_calls)))
        )
    if "create_cable_receipt" not in webapp_text or "create_cable_issue" not in webapp_text:
        errors.append("inventory/webapp.py does not route cable write flows through WarehouseFacade")
    if "app_context.warehouse._is_cable_issue(data)" not in webapp_text:
        errors.append("inventory/webapp.py does not branch cable issue before legacy issue flow")
    forbidden_issue_write_calls = {
        "add_stock_issue", "scan_issue_serial", "confirm_scanned_issues",
        "import_stock_issue_rows", "preview_stock_issue_rows",
        "confirm_stock_issue_preview", "preview_bulk_issue_serials",
        "confirm_bulk_issue_preview",
    }
    bad_issue_write_calls = sorted(set(
        direct_service_calls_in_function(webapp, "_do_GET", forbidden_issue_write_calls)
        + direct_service_calls_in_function(webapp, "_do_POST", forbidden_issue_write_calls)
        + direct_service_calls_in_function(webapp, "_import_csv", forbidden_issue_write_calls)
    ))
    if bad_issue_write_calls:
        errors.append(
            "inventory/webapp.py calls issue write compatibility methods directly: "
            + ", ".join(bad_issue_write_calls)
        )
    forbidden_delivery_import_calls = {
        "preview_delivery_rows", "confirm_delivery_preview",
    }
    bad_delivery_import_calls = sorted(set(
        direct_service_calls_in_function(webapp, "_do_POST", forbidden_delivery_import_calls)
        + direct_service_calls_in_function(webapp, "_import_csv", forbidden_delivery_import_calls)
    ))
    if bad_delivery_import_calls:
        errors.append(
            "inventory/webapp.py calls legacy delivery import methods directly: "
            + ", ".join(bad_delivery_import_calls)
        )
    forbidden_delivery_acceptance_calls = {
        "accept_delivery_serial", "update_delivery_lines",
    }
    bad_delivery_acceptance_calls = sorted(set(
        direct_service_calls_in_function(webapp, "_do_POST", forbidden_delivery_acceptance_calls)
    ))
    if bad_delivery_acceptance_calls:
        errors.append(
            "inventory/webapp.py calls legacy delivery acceptance methods directly: "
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
        if required_call not in webapp_text:
            errors.append(f"inventory/webapp.py missing facade delivery route {required_call}")
    for required_call in (
        "validate_issue_serial", "create_issue(", "create_issue_by_serials",
        "preview_issue_import", "confirm_issue_import", "import_issues",
        "preview_bulk_issue_serials", "confirm_bulk_issue_preview",
    ):
        if required_call not in webapp_text:
            errors.append(f"inventory/webapp.py missing facade issue route {required_call}")
    forbidden_administration_calls = {
        "current_user", "user_by_email", "users", "audit_entries", "list_backups",
    }
    bad_administration_calls = direct_service_calls_in_function(
        webapp, "_do_GET", forbidden_administration_calls
    )
    if bad_administration_calls:
        errors.append(
            "inventory/webapp.py _do_GET calls read-only administration service methods directly: "
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

    for path in files("inventory/monitoring"):
        if contains(path, ("WarehouseEventReader", "warehouse_events")):
            errors.append(f"{path.relative_to(ROOT)} references WarehouseEventReader")

    reports_facade = ROOT / "inventory/reports/facade.py"
    if "warehouse_events" not in reports_facade.read_text(encoding="utf-8"):
        errors.append("ReportsFacade does not receive warehouse_events through constructor")
    application = ROOT / "inventory/core/application.py"
    app_text = application.read_text(encoding="utf-8")
    if "WarehouseEventReader" not in app_text or "warehouse_events=event_reader" not in app_text:
        errors.append("ApplicationContext does not wire WarehouseEventReader into ReportsFacade")

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
