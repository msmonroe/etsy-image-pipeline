from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


class DeliveryCliTests(unittest.TestCase):
    def test_help_runs_from_repo_root(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script = repo_root / "tools" / "generate_etsy_delivery.py"

        completed = subprocess.run(
            [sys.executable, str(script), "--help"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        self.assertEqual(
            completed.returncode,
            0,
            msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )
        self.assertIn("Etsy-safe delivery PNG", completed.stdout)


if __name__ == "__main__":
    unittest.main()
