"""Unit tests for stdout metadata parsing and NACP-gap detection (no cart images required)."""

from __future__ import annotations

import unittest

from no_intro_switch_cart_submission_cli.constants import DUMP_FILE_RE
from no_intro_switch_cart_submission_cli.nacp_pipeline import needs_nacp_enrichment
from no_intro_switch_cart_submission_cli.nstool_stdout import parse_jakcron_nstool_application_meta

# Stylized NSTool (-v)-style fragments
STDOUT_FULL = """
XCI:
  Magic: XCI

[ApplicationExtendedHeader]
  TitleId: 0x01008D100DE46000
  DisplayVersion: v1.0.5

English Title: Cyber Shadow
Supported Languages: AmericanEnglish, Japanese, French, German, Spanish, Italian, Dutch, Portuguese, Russian, Korean, TraditionalChinese, SimplifiedChinese
"""

STDOUT_CUP = """
CUP TitleId: 0x0100AAAAAAAA0000
CUP Version: 1.2.3 (v456)
"""

STDOUT_SPARSE = """
Something something
01008D100DE46000
nothing else useful
"""


class NeedsNacpEnrichment(unittest.TestCase):
    def test_none_needs_enrichment(self) -> None:
        self.assertTrue(needs_nacp_enrichment(None))

    def test_complete_meta_skips_nacp_path(self) -> None:
        m = {
            "base_title_ids": ["01008D100DE46000"],
            "titles": ["Cyber Shadow"],
            "languages": ["En", "Ja"],
            "versions": ["v1.0.5"],
            "updates": ["v196608"],
            "update_title_ids": ["01008D100DE46800"],
        }
        self.assertFalse(needs_nacp_enrichment(m))

    def test_tid_only_still_needs_nacp(self) -> None:
        """Title ID from stdout/filename is not enough — display submission needs title/lang/version."""
        m = {
            "base_title_ids": ["01008D100DE46000"],
            "titles": [""],
            "languages": [],
            "versions": [""],
            "updates": ["v1"],
            "update_title_ids": ["01008D100DE46800"],
        }
        self.assertTrue(needs_nacp_enrichment(m))


class JakcronStdoutFixtures(unittest.TestCase):
    def test_full_stdout_yields_tid_version_title_langs(self) -> None:
        meta = parse_jakcron_nstool_application_meta(
            STDOUT_FULL,
            "v196608",
            default_xci_basename=None,
        )
        self.assertIsNotNone(meta)
        assert meta is not None
        self.assertEqual(meta["base_title_ids"], ["01008D100DE46000"])
        self.assertEqual(meta["versions"], ["v1.0.5"])
        self.assertEqual(meta["titles"], ["Cyber Shadow"])
        self.assertTrue(meta["languages"])
        self.assertFalse(needs_nacp_enrichment(meta))

    def test_cup_sets_display_version_and_tid(self) -> None:
        meta = parse_jakcron_nstool_application_meta(
            STDOUT_CUP,
            "v1",
            default_xci_basename=None,
        )
        self.assertIsNotNone(meta)
        assert meta is not None
        self.assertEqual(meta["base_title_ids"], ["0100AAAAAAAA0000"])
        self.assertTrue(meta["versions"][0].startswith("v"))

    def test_sparse_stdout_needs_nacp_but_tid_from_filename(self) -> None:
        meta = parse_jakcron_nstool_application_meta(
            STDOUT_SPARSE,
            "v196608",
            default_xci_basename="Game [01008D100DE46000][v196608].xci",
        )
        self.assertIsNotNone(meta)
        assert meta is not None
        self.assertEqual(meta["base_title_ids"], ["01008D100DE46000"])
        self.assertEqual(meta["titles"], [""])
        self.assertEqual(meta["languages"], [])
        self.assertTrue(needs_nacp_enrichment(meta))

    def test_dump_file_re_matches_nxdt_style_names(self) -> None:
        name = "Cyber Shadow 1.0.5 [01008D100DE46000][v196608] [NKA][NC][NT].xci"
        m = DUMP_FILE_RE.match(name)
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.group("tid").upper(), "01008D100DE46000")
        self.assertEqual(m.group("vnum"), "v196608")


if __name__ == "__main__":
    unittest.main()
