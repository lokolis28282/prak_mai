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
    "README.md",
    "ARCHITECTURE.md",
    "ITOG.md",
    "README_WINDOWS.md",
    "WINDOWS_RELEASE.md",
    "docs/README.md",
    "docs/API_REFERENCE.md",
    "docs/CODEBASE_GRAPH.md",
    "docs/project/CURRENT_STATE.md",
    "docs/project/DOCUMENTATION_INDEX.md",
)
CURRENT_RELEASE_REPORT = "RELEASE_REPORT_ODE_0_20_0.md"
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

    windows_text = "\n".join(
        (root / relative).read_text("utf-8")
        for relative in ("README_WINDOWS.md", "WINDOWS_RELEASE.md")
    )
    if "data\\backups" in windows_text:
        violations.append("Windows documentation still names legacy data\\backups")
    if re.search(r"восстанов(?:ить|ление).{0,80}через интерфейс", windows_text, re.I):
        violations.append("Windows documentation claims that UI restore is enabled")
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
