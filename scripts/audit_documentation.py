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
    "AGENTS.md",
    "README.md",
    "ARCHITECTURE.md",
    "CLAUDE.md",
    "ITOG.md",
    "README_WINDOWS.md",
    "TECH_DEBT.md",
    "WINDOWS_RELEASE.md",
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
    "docs/USER_GUIDE.md",
    "docs/project/CURRENT_STATE.md",
    "docs/project/DOCUMENTATION_INDEX.md",
    "docs/project/MASTER_CONTEXT.md",
    "docs/project/RISKS_AND_BACKLOG.md",
    "docs/project/ROADMAP.md",
    "docs/project/SYSTEM_FUNCTION_MATRIX.md",
)
CURRENT_RELEASE_REPORT = "RELEASE_REPORT_ODE_0_21_0.md"
MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
VERSION_RE = re.compile(r'__version__\s*=\s*["\']([^"\']+)["\']')


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
    violations: list[str] = []
    for relative in CURRENT_DOCUMENTS:
        path = root / relative
        if not path.is_file():
            violations.append(f"missing current document: {relative}")
            continue
        if version not in path.read_text("utf-8"):
            violations.append(f"{relative}: current source version {version} is absent")

    index = (root / "docs/project/DOCUMENTATION_INDEX.md").read_text("utf-8")
    if CURRENT_RELEASE_REPORT not in index:
        violations.append(
            "docs/project/DOCUMENTATION_INDEX.md: current release report is absent"
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
        ("docs/DEVELOPER_GUIDE.md", developer_text),
    ):
        normalized = text.casefold()
        if "api-key" not in normalized and "api-ключ" not in normalized:
            violations.append(f"{relative}: API-key authentication status is absent")
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
