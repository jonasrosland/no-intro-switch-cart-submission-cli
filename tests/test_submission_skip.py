"""Detection of existing Trusted Dump Submission.xml in release folders."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from no_intro_switch_cart_submission_cli.releases import TRUSTED_DUMP_SUBMISSION_XML_SUFFIX, list_trusted_dump_submission_xmls


class ListTrustedDumpSubmissionXmls(unittest.TestCase):
    def test_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(list_trusted_dump_submission_xmls(Path(td)), [])

    def test_finds_submission_xml(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            f = d / "Cyber Shadow - hitsaveorg - 2026-04-29 Submission.xml"
            f.write_text("<datafile />", encoding="utf-8")
            self.assertEqual(list_trusted_dump_submission_xmls(d), [f])

    def test_sorted_when_multiple(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            b = d / "B Game - x - 2026-01-01 Submission.xml"
            a = d / "A Game - x - 2026-01-01 Submission.xml"
            b.write_text("x", encoding="utf-8")
            a.write_text("x", encoding="utf-8")
            self.assertEqual(list_trusted_dump_submission_xmls(d), [a, b])

    def test_ignores_wrong_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "foo.xml").write_text("x", encoding="utf-8")
            (d / "Submission.xml").write_text("x", encoding="utf-8")
            (d / "Game copy.xml").write_text("x", encoding="utf-8")
            self.assertEqual(list_trusted_dump_submission_xmls(d), [])

    def test_suffix_documents_tool_output(self) -> None:
        self.assertTrue("Title - dumper - 2026-04-28 Submission.xml".endswith(TRUSTED_DUMP_SUBMISSION_XML_SUFFIX))


if __name__ == "__main__":
    unittest.main()
