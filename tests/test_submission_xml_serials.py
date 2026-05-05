"""Tests for parsing serials from existing submission XML."""

from __future__ import annotations

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from no_intro_switch_cart_submission_cli.submission_xml_serials import (
    parse_trusted_dump_serials_from_submission_xml,
)
from no_intro_switch_cart_submission_cli.verify_scans_xml import canonical_serial_for_compare


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
    def test_barcode_spacing_equivalent(self) -> None:
        a = canonical_serial_for_compare("box_barcode", "659048990448")
        b = canonical_serial_for_compare("box_barcode", "6 59048 99044 8")
        self.assertEqual(a, b)

    def test_pcb_shortcut(self) -> None:
        self.assertEqual(
            canonical_serial_for_compare("pcb_serial", "@"),
            canonical_serial_for_compare("pcb_serial", "\u25bc"),
        )


if __name__ == "__main__":
    unittest.main()
