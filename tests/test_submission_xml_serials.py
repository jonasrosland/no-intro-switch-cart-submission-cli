"""Tests for parsing serials from existing submission XML."""

from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

import xml.etree.ElementTree as ET
from pathlib import Path

from no_intro_switch_cart_submission_cli.submission_xml_serials import (
    parse_trusted_dump_serials_from_submission_xml,
)
from no_intro_switch_cart_submission_cli.verify_scans_xml import (
    canonical_serial_for_compare,
    verify_scans_against_submission_xml,
)


class ParseTrustedDumpSerials(unittest.TestCase):
    def test_round_trip_minimal_tree(self) -> None:
        datafile = ET.Element("datafile")
        game = ET.SubElement(datafile, "game", name="Test")
        ET.SubElement(
            game,
            "archive",
            clone="P",
            name="Test",
            region="World",
            languages="",
            langchecked="unk",
            gameid1="0100000000000000",
            gameid2="HAC-P-ABCDE",
            categories="Games",
        )
        source = ET.SubElement(game, "source")
        ET.SubElement(
            source,
            "serials",
            media_serial1="LA-H-X-UKV",
            media_serial2="TSA-HAC-X-UKV",
            pcb_serial="@",
            box_serial="HAC-P-ABCDE",
            box_barcode="6 59048 99044 8",
        )
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "t Submission.xml"
            p.write_bytes(ET.tostring(datafile, encoding="utf-8"))
            got = parse_trusted_dump_serials_from_submission_xml(p)
        self.assertEqual(got["gameid2"], "HAC-P-ABCDE")
        self.assertEqual(got["media_serial1"], "LA-H-X-UKV")
        self.assertEqual(got["media_serial2"], "TSA-HAC-X-UKV")
        self.assertEqual(got["pcb_serial"], "@")
        self.assertEqual(got["box_serial"], "HAC-P-ABCDE")
        self.assertEqual(got["box_barcode"], "6 59048 99044 8")

    def test_missing_serials_returns_empty_strings(self) -> None:
        datafile = ET.Element("datafile")
        ET.SubElement(datafile, "game", name="X")
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "empty Submission.xml"
            p.write_bytes(ET.tostring(datafile, encoding="utf-8"))
            got = parse_trusted_dump_serials_from_submission_xml(p)
        self.assertEqual(got["media_serial1"], "")


class CanonicalSerialCompare(unittest.TestCase):
    def test_box_serial_xml_space_between_hac_and_p(self) -> None:
        self.assertEqual(
            canonical_serial_for_compare("box_serial", "HAC P AT5VA"),
            canonical_serial_for_compare("box_serial", "HAC-P-AT5VA"),
        )

    def test_barcode_spacing_equivalent(self) -> None:
        a = canonical_serial_for_compare("box_barcode", "659048990448")
        b = canonical_serial_for_compare("box_barcode", "6 59048 99044 8")
        self.assertEqual(a, b)

    def test_pcb_shortcut(self) -> None:
        self.assertEqual(
            canonical_serial_for_compare("pcb_serial", "@"),
            canonical_serial_for_compare("pcb_serial", "\u25bc"),
        )


class VerifyScansAgainstSubmission(unittest.TestCase):
    @patch("no_intro_switch_cart_submission_cli.verify_scans_xml.try_fill_serial_row_from_scans")
    @patch("no_intro_switch_cart_submission_cli.verify_scans_xml.vlm_extract_command")
    def test_verify_exits_0_when_canonical_match(self, mock_vlm_cmd, mock_try_fill) -> None:
        mock_vlm_cmd.return_value = ["true"]
        mock_try_fill.return_value = ["ocr_scans: ok"]

        datafile = ET.Element("datafile")
        game = ET.SubElement(datafile, "game", name="T")
        ET.SubElement(
            game,
            "archive",
            clone="P",
            name="T",
            region="W",
            languages="",
            langchecked="unk",
            gameid1="0100000000000000",
            gameid2="HAC-P-ABCDE",
            categories="Games",
        )
        source = ET.SubElement(game, "source")
        ET.SubElement(
            source,
            "serials",
            media_serial1="LA-H-X-UKV",
            media_serial2="MS2",
            pcb_serial="@",
            box_serial="HAC-P-ABCDE",
            box_barcode="6 59048 99044 8",
        )
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            xml_path = td_path / "x Submission.xml"
            xml_path.write_bytes(ET.tostring(datafile, encoding="utf-8"))
            rel = td_path / "1.0"
            rel.mkdir()
            cfg_path = td_path / "cfg.json"
            cfg_path.write_text(
                '{"scan_ocr": {"vlm_extract_command": ["true"]}}',
                encoding="utf-8",
            )

            def fill_side_effect(release_dir: Path, row: dict, cfg: dict) -> list[str]:
                row["media_serial1"] = "LA-H-X-UKV"
                row["media_serial2"] = "MS2"
                row["pcb_serial"] = "\u25bc"
                row["box_serial"] = "HAC-P-ABCDE"
                row["box_barcode"] = "6 59048 99044 8"
                return ["ok"]

            mock_try_fill.side_effect = fill_side_effect
            rc = verify_scans_against_submission_xml(cfg_path, xml_path, rel, "stored")
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
