#!/usr/bin/env python3
"""Audit living Markdown contracts and local links.

Historical reports may keep their original version statements.  The stricter
version and operational checks therefore apply only to the small allowlist of
documents that describe the current product.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
CURRENT_DOCUMENTS = (
    "CHANGELOG.md",
    "CONTRIBUTORS.md",
    "LAN_ACCESS_WINDOWS.md",
    "ODE_PRESENTATION.html",
    "ODE_USER_GUIDE.html",
    "ODE_USER_GUIDE.md",
    "PRIVATE_WINDOWS_TRANSFER_README_ODE_0_21_1.md",
    "AGENTS.md",
    "README.md",
    "ARCHITECTURE.md",
    "CLAUDE.md",
    "ITOG.md",
    "README_WINDOWS.md",
    "TECH_DEBT.md",
    "WINDOWS_RELEASE.md",
    "data/README.md",
    "docs/ADMINISTRATION_ARCHITECTURE.md",
    "docs/ADMINISTRATION_API_MIGRATION.md",
    "docs/DATABASE_OWNERSHIP.md",
    "docs/LOCAL_WORKING_DATABASE_RUNBOOK.md",
    "docs/MANUAL_TESTING_0_21_1_WINDOWS.md",
    "docs/MONITORING_KNOWLEDGE_GUIDE.md",
    "docs/MULTI_WAREHOUSE_ARCHITECTURE.md",
    "docs/README.md",
    "docs/API_REFERENCE.md",
    "docs/APPLICATION_CONTEXT.md",
    "docs/AUTHENTICATION_AND_API_ACCESS.md",
    "docs/CODEBASE_GRAPH.md",
    "docs/DEVELOPER_GUIDE.md",
    "docs/FRONTEND_CONTRACTS.md",
    "docs/MONITORING_MODULE_BOUNDARIES.md",
    "docs/MONITORING_HOSTNAME_ROUTING.md",
    "docs/RUNTIME_CONFIGURATION.md",
    "docs/SECURITY_BOUNDARIES.md",
    "docs/TEST_DATABASE_GUIDE.md",
    "docs/USER_GUIDE.md",
    "docs/VACATIONS_ARCHITECTURE.md",
    "docs/BACKEND_ARCHITECTURE.md",
    "docs/CODEBASE_MEMORY_MCP.md",
    "docs/INVENTORY_NUMBER_IMPORT_ARCHITECTURE.md",
    "docs/MODULE_ARCHITECTURE.md",
    "docs/operations/backup-restore.md",
    "docs/operations/release-data-separation.md",
    "docs/project/AGENT_HANDOFF.md",
    "docs/project/CURRENT_STATE.md",
    "docs/project/DOCUMENTATION_INDEX.md",
    "docs/project/MASTER_CONTEXT.md",
    "docs/project/README.md",
    "docs/project/REPOSITORY_MAP.md",
    "docs/project/RISKS_AND_BACKLOG.md",
    "docs/project/ROADMAP.md",
    "docs/project/SYSTEM_FUNCTION_MATRIX.md",
    "docs/project/VERSION_HISTORY.md",
)
MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
VERSION_RE = re.compile(r'__version__\s*=\s*["\']([^"\']+)["\']')
FINAL_TEST_COUNT = 754
FINAL_GRAPH_NODES = 254
FINAL_GRAPH_EDGES = 527


def source_version(root: Path = ROOT) -> str:
    match = VERSION_RE.search((root / "inventory/__init__.py").read_text("utf-8"))
    if not match:
        raise ValueError("inventory/__init__.py does not declare __version__")
    return match.group(1)


def markdown_paths(root: Path = ROOT) -> list[Path]:
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            "*.md",
        ],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return sorted(root / item for item in result.stdout.splitlines() if item)


def _local_target(raw_target: str) -> str | None:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        target = target[1 : target.index(">")]
    else:
        # Optional Markdown link titles follow the path after whitespace.
        target = target.split(maxsplit=1)[0]
    if not target or target.startswith(("#", "/")):
        return None
    if re.match(r"^[a-z][a-z0-9+.-]*:", target, flags=re.IGNORECASE):
        return None
    return unquote(target.split("#", 1)[0].split("?", 1)[0])


def audit_local_links(paths: list[Path], root: Path = ROOT) -> list[str]:
    violations: list[str] = []
    for path in paths:
        if (root / "docs/history") in path.parents:
            # Immutable snapshots may intentionally reference topology removed
            # after that review; their current status is carried by the index.
            continue
        text = path.read_text("utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for match in MARKDOWN_LINK_RE.finditer(line):
                target = _local_target(match.group(1))
                if target is None:
                    continue
                candidates = (
                    (path.parent / target).resolve(),
                    (root / target).resolve(),
                    (root / "docs" / target).resolve(),
                )
                safe_candidates = tuple(
                    candidate
                    for candidate in candidates
                    if candidate == root.resolve() or root.resolve() in candidate.parents
                )
                if not safe_candidates:
                    violations.append(
                        f"{path.relative_to(root)}:{line_number}: link escapes repository: {target}"
                    )
                    continue
                if not any(candidate.exists() for candidate in safe_candidates):
                    violations.append(
                        f"{path.relative_to(root)}:{line_number}: missing link target: {target}"
                    )
    return violations


def audit_current_contracts(root: Path = ROOT) -> list[str]:
    version = source_version(root)
    current_release_report = f"RELEASE_REPORT_ODE_{version.replace('.', '_')}.md"
    violations: list[str] = []
    for relative in CURRENT_DOCUMENTS:
        path = root / relative
        if not path.is_file():
            violations.append(f"missing current document: {relative}")
            continue
        if version not in path.read_text("utf-8"):
            violations.append(f"{relative}: current source version {version} is absent")

    index = (root / "docs/project/DOCUMENTATION_INDEX.md").read_text("utf-8")
    if current_release_report not in index:
        violations.append(
            "docs/project/DOCUMENTATION_INDEX.md: current release report is absent"
        )
    report_path = root / current_release_report
    if not report_path.is_file():
        violations.append(f"missing current release report: {current_release_report}")
    elif version not in report_path.read_text("utf-8"):
        violations.append(
            f"{current_release_report}: current source version {version} is absent"
        )

    test_count_marker = str(FINAL_TEST_COUNT)
    for relative in (
        "AGENTS.md",
        "CLAUDE.md",
        "ITOG.md",
        "README.md",
        "ODE_PRESENTATION.html",
        "docs/project/CURRENT_STATE.md",
        current_release_report,
    ):
        if test_count_marker not in (root / relative).read_text("utf-8"):
            violations.append(
                f"{relative}: final test count {FINAL_TEST_COUNT} is absent"
            )

    graph_marker = str(FINAL_GRAPH_NODES)
    edge_marker = str(FINAL_GRAPH_EDGES)
    for relative in (
        "README.md",
        "ITOG.md",
        "docs/CODEBASE_GRAPH.md",
        "docs/project/CURRENT_STATE.md",
        "docs/assets/ode-architecture-graph.svg",
        current_release_report,
    ):
        current_text = (root / relative).read_text("utf-8")
        if graph_marker not in current_text or edge_marker not in current_text:
            violations.append(
                f"{relative}: final graph {FINAL_GRAPH_NODES}/{FINAL_GRAPH_EDGES} is absent"
            )

    report_text = report_path.read_text("utf-8") if report_path.is_file() else ""
    for stale in (
        "будут внесены в этот раздел",
        "результаты полного gate фиксируются ниже после завершения",
    ):
        if stale in report_text:
            violations.append(f"{current_release_report}: stale placeholder {stale}")
    if "physical Windows sign-off pending" not in report_text:
        violations.append(
            f"{current_release_report}: physical Windows PENDING status is absent"
        )

    expected_graph = f"ode-code-graph-{version}.png"
    for relative in ("README.md", "docs/CODEBASE_GRAPH.md"):
        text = (root / relative).read_text("utf-8")
        graph_versions = re.findall(r"ode-code-graph-([0-9.]+)\.png", text)
        if expected_graph not in text:
            violations.append(f"{relative}: current graph {expected_graph} is absent")
        for graph_version in graph_versions:
            if graph_version != version:
                violations.append(
                    f"{relative}: old graph {graph_version} is presented as current"
                )

    windows_text = "\n".join(
        (root / relative).read_text("utf-8")
        for relative in ("README_WINDOWS.md", "WINDOWS_RELEASE.md")
    )
    if "data\\backups" in windows_text:
        violations.append("Windows documentation still names legacy data\\backups")
    if re.search(r"восстанов(?:ить|ление).{0,80}через интерфейс", windows_text, re.I):
        violations.append("Windows documentation claims that UI restore is enabled")
    for relative in CURRENT_DOCUMENTS:
        if "/api/equipment-composition" in (root / relative).read_text("utf-8"):
            violations.append(
                f"{relative}: names removed /api/equipment-composition endpoint"
            )

    auth_text = (root / "docs/AUTHENTICATION_AND_API_ACCESS.md").read_text("utf-8")
    api_text = (root / "docs/API_REFERENCE.md").read_text("utf-8")
    user_text = (root / "docs/USER_GUIDE.md").read_text("utf-8")
    quick_user_text = (root / "ODE_USER_GUIDE.md").read_text("utf-8")
    quick_user_html = (root / "ODE_USER_GUIDE.html").read_text("utf-8")
    presentation_path = root / "ODE_PRESENTATION.html"
    presentation_html = (
        presentation_path.read_text("utf-8") if presentation_path.is_file() else ""
    )
    if not presentation_html:
        violations.append("ODE_PRESENTATION.html: required current artifact is absent")
    developer_text = (root / "docs/DEVELOPER_GUIDE.md").read_text("utf-8")
    matrix_text = (root / "docs/project/SYSTEM_FUNCTION_MATRIX.md").read_text("utf-8")
    env_example = (root / ".env.example").read_text("utf-8")
    for marker in (
        '"mode":"engineer"',
        '"mode":"admin"',
        "ode_session",
        "X-API-Key",
        "ODE_API_KEY",
    ):
        if marker not in auth_text:
            violations.append(
                f"docs/AUTHENTICATION_AND_API_ACCESS.md: missing auth marker {marker}"
            )
    for relative, text in (
        ("docs/API_REFERENCE.md", api_text),
        ("docs/USER_GUIDE.md", user_text),
        ("ODE_USER_GUIDE.md", quick_user_text),
        ("docs/DEVELOPER_GUIDE.md", developer_text),
    ):
        normalized = text.casefold()
        if "api-key" not in normalized and "api-ключ" not in normalized:
            violations.append(f"{relative}: API-key authentication status is absent")
    if "start_windows.bat" not in quick_user_text:
        violations.append("ODE_USER_GUIDE.md: Windows launcher is absent")
    if "Preview" not in quick_user_text or "Confirm" not in quick_user_text:
        violations.append("ODE_USER_GUIDE.md: safe Preview/Confirm flow is absent")
    if "start_windows.bat" not in quick_user_html:
        violations.append("ODE_USER_GUIDE.html: Windows launcher is absent")
    if "Мониторинг" not in quick_user_html or "Резервная копия" not in quick_user_html:
        violations.append("ODE_USER_GUIDE.html: core user workflows are absent")
    for relative, marker in (
        ("ODE_USER_GUIDE.md", "Статус 0.21.1 RC"),
        ("ODE_USER_GUIDE.html", "Статус Windows-приёмки — PENDING"),
        ("LAN_ACCESS_WINDOWS.md", "legacy/dev only"),
        ("data/README.md", "data/vacations.db"),
        ("README_WINDOWS.md", "| Monitoring | таблиц не имеет"),
        ("README.md", "docs/project/VERSION_HISTORY.md"),
        ("README.md", "CONTRIBUTORS.md"),
        ("docs/APPLICATION_CONTEXT.md", "- `vacations`;"),
        ("docs/APPLICATION_CONTEXT.md", "- `knowledge`;"),
        ("docs/MODULE_ARCHITECTURE.md", "- `KnowledgeFacade`"),
        ("docs/MODULE_ARCHITECTURE.md", "- `VacationFacade`"),
        ("docs/MULTI_WAREHOUSE_ARCHITECTURE.md", "standalone DB: Vacations"),
        ("docs/VACATIONS_ARCHITECTURE.md", "ODE_TEST_MODE=1"),
        ("docs/MANUAL_TESTING_0_21_1_WINDOWS.md", "PRIVATE TRANSFER"),
        ("docs/MANUAL_TESTING_0_21_1_WINDOWS.md", "credentialed `LOGIN` audit"),
        ("PRIVATE_WINDOWS_TRANSFER_README_ODE_0_21_1.md", "разделы 1, 2P, 3P и 5–7"),
        ("docs/project/SYSTEM_FUNCTION_MATRIX.md", "вход инженера по ФИО не пишет login audit"),
        ("docs/TEST_DATABASE_GUIDE.md", "CURRENT LOCAL FACT"),
    ):
        if marker not in (root / relative).read_text("utf-8"):
            violations.append(f"{relative}: missing living-contract marker {marker}")

    for relative, phrase in (
        ("README.md", "python3 app.py gui --db data/warehouse_test.db"),
        ("docs/DATABASE_OWNERSHIP.md", "data/uploads/knowledge"),
        ("docs/MONITORING_KNOWLEDGE_GUIDE.md", "implemented on integration branch"),
        ("ODE_PRESENTATION.html", "фактический остаток"),
    ):
        if phrase in (root / relative).read_text("utf-8"):
            violations.append(f"{relative}: stale living-contract phrase {phrase}")
    for marker in (
        f"ODE {version}",
        "50 000",
        "IXcellerate",
        "Solar",
        "Юра Устинов",
        "Никита Боронев",
        "Александр Мерненко",
    ):
        if presentation_html and marker not in presentation_html:
            violations.append(f"ODE_PRESENTATION.html: missing marker {marker}")
    if "/api/search`" in matrix_text or "| `/api/search`" in matrix_text:
        violations.append(
            "docs/project/SYSTEM_FUNCTION_MATRIX.md: names removed /api/search endpoint"
        )
    if "/api/global-search" not in matrix_text:
        violations.append(
            "docs/project/SYSTEM_FUNCTION_MATRIX.md: current global-search endpoint is absent"
        )
    monitoring_text = (root / "docs/MONITORING_HOSTNAME_ROUTING.md").read_text("utf-8")
    if "future operator UI / API" in monitoring_text:
        violations.append(
            "docs/MONITORING_HOSTNAME_ROUTING.md: current operator UI is still described as future"
        )
    if "POST /api/monitoring/manual-search" not in monitoring_text:
        violations.append(
            "docs/MONITORING_HOSTNAME_ROUTING.md: current manual-search route is absent"
        )
    if "does not load .env automatically" not in env_example:
        violations.append(".env.example: automatic-loading warning is absent")
    return violations


def audit(root: Path = ROOT) -> tuple[list[Path], list[str]]:
    paths = markdown_paths(root)
    violations = audit_local_links(paths, root)
    violations.extend(audit_current_contracts(root))
    return paths, violations


def main() -> int:
    try:
        paths, violations = audit()
    except (OSError, subprocess.CalledProcessError, UnicodeError, ValueError) as error:
        print(f"documentation: audit failed: {error}", file=sys.stderr)
        return 2
    if violations:
        print("documentation: FAILED", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        return 1
    print(
        f"documentation: OK, {len(paths)} Markdown files; "
        f"current version {source_version()} and local links verified"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
