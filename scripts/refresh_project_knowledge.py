#!/usr/bin/env python3
"""Refresh the committed code graph and the external Codebase Memory index.

The Codebase Memory artifact is deliberately never persisted in the repository.
Use this after a material code or module-topology change:

    python3 scripts/refresh_project_knowledge.py
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
ARTIFACT = ROOT / ".codebase-memory"
GRAPH_SCRIPT = ROOT / "scripts" / "generate_code_graph.py"


def _memory_binary() -> Path | None:
    configured = os.environ.get("CODEBASE_MEMORY_MCP_BIN", "").strip()
    candidates = [
        Path(configured).expanduser() if configured else None,
        Path(found) if (found := shutil.which("codebase-memory-mcp")) else None,
        Path.home() / ".local" / "bin" / "codebase-memory-mcp",
    ]
    return next(
        (path.resolve() for path in candidates if path is not None and path.is_file()),
        None,
    )


def _assert_no_repository_artifact() -> None:
    if ARTIFACT.exists():
        raise RuntimeError(
            f"refusing to continue while repository artifact exists: {ARTIFACT}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh ODE's committed code graph and external memory index."
    )
    parser.add_argument(
        "--graph-only",
        action="store_true",
        help="refresh only docs/assets/code_graph.html",
    )
    parser.add_argument(
        "--mode",
        choices=("full", "moderate", "fast"),
        default="full",
        help="Codebase Memory indexing mode (default: full)",
    )
    args = parser.parse_args()

    _assert_no_repository_artifact()
    subprocess.run([sys.executable, str(GRAPH_SCRIPT)], cwd=ROOT, check=True)
    if args.graph_only:
        return 0

    binary = _memory_binary()
    if binary is None:
        raise RuntimeError(
            "codebase-memory-mcp is not installed; set CODEBASE_MEMORY_MCP_BIN "
            "or use --graph-only"
        )

    env = os.environ.copy()
    env["CBM_ALLOWED_ROOT"] = str(ROOT)
    if not env.get("CBM_CACHE_DIR") and sys.platform == "darwin":
        env["CBM_CACHE_DIR"] = str(
            Path.home() / "Library" / "Caches" / "codebase-memory-mcp" / "ode"
        )
    subprocess.run(
        [
            str(binary),
            "cli",
            "index_repository",
            "--repo-path",
            str(ROOT),
            "--mode",
            args.mode,
            "--persistence",
            "false",
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )
    _assert_no_repository_artifact()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
