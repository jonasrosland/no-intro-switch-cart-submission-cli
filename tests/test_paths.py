"""Paths / jakcron extract temp."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from no_intro_switch_cart_submission_cli.paths import _jakcron_extract_parent_dir


class JakcronExtractTemp(unittest.TestCase):
    def test_default_uses_cwd_temp_extract(self) -> None:
        expected = (Path.cwd() / "temp-extract").resolve()
        d0 = _jakcron_extract_parent_dir({})
        d1 = _jakcron_extract_parent_dir(None)
        self.assertIsNotNone(d0)
        self.assertIsNotNone(d1)
        self.assertEqual(Path(d0).resolve(), expected)
        self.assertEqual(Path(d1).resolve(), expected)
        self.assertTrue(expected.is_dir())

    def test_jakcron_extract_temp_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = _jakcron_extract_parent_dir({"jakcron_extract_temp_dir": td})
            self.assertIsNotNone(d)
            self.assertEqual(Path(d).resolve(), Path(td).resolve())
