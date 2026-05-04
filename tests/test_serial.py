"""Tests for catalog serial helpers (gameid2 + archive version1 from media_serial2)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from no_intro_switch_cart_submission_cli.constants import SERIAL_FIELDS
from no_intro_switch_cart_submission_cli.config_serial import (
    apply_cli_serial_overrides,
    derive_gameid2_from_media_serial1,
    fill_gameid2_from_media_serial1_if_empty,
    merged_serial_fields,
    normalize_pcb_serial,
    version1_rev_from_media_serial2,
)


class NormalizePcbSerial(unittest.TestCase):
    def test_shortcuts(self) -> None:
        self.assertEqual(normalize_pcb_serial("@"), "\u25bc")
        self.assertEqual(normalize_pcb_serial("$"), "\u25bc 10")
        self.assertEqual(normalize_pcb_serial(" @ "), "\u25bc")

    def test_other_preserved(self) -> None:
        self.assertEqual(normalize_pcb_serial("\u25bc 10"), "\u25bc 10")
        self.assertEqual(normalize_pcb_serial("@not"), "@not")
        self.assertEqual(normalize_pcb_serial(""), "")


class PcbSerialIntegration(unittest.TestCase):
    def test_merged_config_shortcut(self) -> None:
        row = merged_serial_fields({"pcb_serial": "$"})
        self.assertEqual(row["pcb_serial"], "\u25bc 10")

    def test_cli_override_shortcut(self) -> None:
        blank_args = {k: None for k in SERIAL_FIELDS}
        blank_args["pcb_serial"] = "@"
        args = SimpleNamespace(**blank_args)
        out = apply_cli_serial_overrides(args, merged_serial_fields({}))
        self.assertEqual(out["pcb_serial"], "\u25bc")


class DeriveGameid2FromMediaSerial1(unittest.TestCase):
    def test_strips_known_region_suffix(self) -> None:
        self.assertEqual(derive_gameid2_from_media_serial1("LA-H-AACCA-EUR"), "LA-H-AACCA")
        self.assertEqual(derive_gameid2_from_media_serial1("LA-H-AACCA-USA"), "LA-H-AACCA")
        self.assertEqual(derive_gameid2_from_media_serial1("LA-H-AS7TA-EUR"), "LA-H-AS7TA")
        self.assertEqual(derive_gameid2_from_media_serial1("LA-H-AZRMA-EUR"), "LA-H-AZRMA")
        self.assertEqual(derive_gameid2_from_media_serial1("LA-H-AZRMA-USA"), "LA-H-AZRMA")
        self.assertEqual(derive_gameid2_from_media_serial1("LA-H-ACBAA-EUR"), "LA-H-ACBAA")
        self.assertEqual(derive_gameid2_from_media_serial1("LA-H-ACBAA-JPN"), "LA-H-ACBAA")
        self.assertEqual(derive_gameid2_from_media_serial1("LA-H-ACBAA-USA"), "LA-H-ACBAA")
        self.assertEqual(derive_gameid2_from_media_serial1("LA-H-A9RWA-USA"), "LA-H-A9RWA")

    def test_region_suffix_case_insensitive(self) -> None:
        self.assertEqual(derive_gameid2_from_media_serial1("LA-H-AACCA-eur"), "LA-H-AACCA")

    def test_no_region_suffix_unchanged(self) -> None:
        self.assertEqual(derive_gameid2_from_media_serial1("LA-H-AACCA"), "LA-H-AACCA")

    def test_unknown_trailing_segment_unchanged(self) -> None:
        self.assertEqual(derive_gameid2_from_media_serial1("LA-H-AACCA-FOO"), "LA-H-AACCA-FOO")

    def test_whitespace_stripped(self) -> None:
        self.assertEqual(derive_gameid2_from_media_serial1("  LA-H-AZRMA-USA  "), "LA-H-AZRMA")


class FillGameid2IfEmpty(unittest.TestCase):
    def test_fills_when_gameid2_blank(self) -> None:
        row = {"gameid2": "", "media_serial1": "LA-H-AACCA-EUR"}
        fill_gameid2_from_media_serial1_if_empty(row)
        self.assertEqual(row["gameid2"], "LA-H-AACCA")

    def test_skips_when_gameid2_set(self) -> None:
        row = {"gameid2": "KEEP", "media_serial1": "LA-H-AACCA-USA"}
        fill_gameid2_from_media_serial1_if_empty(row)
        self.assertEqual(row["gameid2"], "KEEP")


class Version1RevFromMediaSerial2(unittest.TestCase):
    """11-char: last three decimal digits; 13-char: revision at positions 9–10 (decimal)."""

    def test_eleven_chars_last_three_decimal_revision(self) -> None:
        self.assertEqual(version1_rev_from_media_serial2("12345678623"), "Rev 623")

    def test_revision_leading_zeros_decimal(self) -> None:
        self.assertEqual(version1_rev_from_media_serial2("00000000001"), "Rev 001")

    def test_revision_000_first_pressing(self) -> None:
        self.assertEqual(version1_rev_from_media_serial2("AAAAAAAA000"), "Rev 000")

    def test_revision_nine_with_padding(self) -> None:
        self.assertEqual(version1_rev_from_media_serial2("XXXXXXXX009"), "Rev 009")

    def test_thirteen_chars_positions_9_10_revision(self) -> None:
        # BJ76 AZ0 Y | 12 | 51H — revision digits at 1-based positions 9–10
        self.assertEqual(version1_rev_from_media_serial2("BJ76AZ0Y1251H"), "Rev 12")

    def test_thirteen_chars_rev_09_padding(self) -> None:
        self.assertEqual(version1_rev_from_media_serial2("BJ76AZ0Y0951H"), "Rev 09")

    def test_thirteen_chars_rev_00_first_pressing(self) -> None:
        self.assertEqual(version1_rev_from_media_serial2("BJ76AZ0Y0051H"), "Rev 00")

    def test_thirteen_shovel_style_rev00(self) -> None:
        self.assertEqual(version1_rev_from_media_serial2("A8BWA50B00623"), "Rev 00")

    def test_wrong_length_no_auto(self) -> None:
        self.assertIsNone(version1_rev_from_media_serial2("SHORT"))
        self.assertIsNone(version1_rev_from_media_serial2("123456789012"))

    def test_eleven_last_three_must_be_decimal_digits(self) -> None:
        self.assertIsNone(version1_rev_from_media_serial2("AAAAAAAABCD"))

    def test_thirteen_revision_pair_must_be_decimal(self) -> None:
        self.assertIsNone(version1_rev_from_media_serial2("BJ76AZ0YXY51H"))

    def test_whitespace_trim_before_length(self) -> None:
        self.assertEqual(version1_rev_from_media_serial2("  00000000001  "), "Rev 001")
        self.assertEqual(version1_rev_from_media_serial2("  BJ76AZ0Y1251H  "), "Rev 12")


if __name__ == "__main__":
    unittest.main()
