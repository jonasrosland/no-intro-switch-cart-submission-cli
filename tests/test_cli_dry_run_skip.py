"""CLI: existing Submission.xml skip applies under --dry-run as well."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _python_for_subprocess() -> str:
    """sys.executable may point at IDE wrappers; prefer a real python3 on PATH."""
    exe = Path(sys.executable).resolve()
    if "python" in exe.name.lower():
        return str(exe)
    found = shutil.which("python3")
    if found:
        return found
    return str(exe)


class CliDryRunSkipsExistingSubmission(unittest.TestCase):
    def test_dry_run_skips_folder_with_submission_xml(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rel = root / "1.0.5"
            rel.mkdir()
            xci = rel / "Cyber Shadow [0100ABCDEF012345][v16].xci"
            xci.write_bytes(b"\xff")
            (rel / "Cyber Shadow - hitsaveorg - 2026-04-28 Submission.xml").write_text(
                "<datafile />", encoding="utf-8"
            )
            cfg_path = root / "cfg.json"
            cfg_path.write_text(
                json.dumps({"root": str(root.resolve()), "prod_keys": None}),
                encoding="utf-8",
            )
            env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT), "PYTHONWARNINGS": "ignore"}
            proc = subprocess.run(
                [
                    _python_for_subprocess(),
                    "-m",
                    "no_intro_switch_cart_submission_cli.cli",
                    "--config",
                    str(cfg_path),
                    "--root",
                    str(root.resolve()),
                    "--dry-run",
                ],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=180,
                env=env,
            )
            out = proc.stdout + proc.stderr
            self.assertEqual(proc.returncode, 0, msg=out)
            self.assertIn("skip — folder already contains Submission.xml", out)
            self.assertIn("Done. 0 submission file(s).", out)


if __name__ == "__main__":
    unittest.main()
