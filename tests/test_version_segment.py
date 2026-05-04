"""version_segment_for_submission_xml (basename vs parent dir vs v-token)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from no_intro_switch_cart_submission_cli.releases import version_segment_for_submission_xml


class VersionSegmentForSubmissionXml(unittest.TestCase):
    def test_human_version_from_nxdt_basename(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "Aka 1.0.5 [0100B0601852A000][v393216] [NKA][NC][NT].xci"
            self.assertEqual(version_segment_for_submission_xml(p), "1.0.5")

    def test_parent_folder_when_basename_has_no_human_version(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "Aka" / "2.0.0"
            d.mkdir(parents=True)
            p = d / "Aka [0100B0601852A000][v458752] [NKA][NC][NT].xci"
            self.assertEqual(version_segment_for_submission_xml(p), "2.0.0")

    def test_bracket_vnum_when_no_other_hint(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "Cyber Shadow [01008D100DE46000][v196608] [NKA][NC][NT].xci"
            self.assertEqual(version_segment_for_submission_xml(p), "v196608")


if __name__ == "__main__":
    unittest.main()
