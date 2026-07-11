from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ArchitectureBoundaryTest(unittest.TestCase):
    def test_module_boundary_audit_passes(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/audit_module_boundaries.py"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
