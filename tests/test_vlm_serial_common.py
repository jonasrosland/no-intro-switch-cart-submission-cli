"""Tests for scripts/vlm_serial_common.py (stdlib only)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import vlm_serial_common as vlm  # noqa: E402


class TestRepairCartFrontLaHPrefix(unittest.TestCase):
    def test_inserts_missing_a(self):
        f = vlm.repair_cart_front_la_h_prefix
        self.assertEqual(f("L-H-AT5VA-EUR"), "LA-H-AT5VA-EUR")
        self.assertEqual(f("l-h-at5va-eur"), "LA-H-at5va-eur")
        self.assertEqual(f("LA-H-AT5VA-EUR"), "LA-H-AT5VA-EUR")
        self.assertEqual(f("LB-H-XXXX"), "LB-H-XXXX")
        self.assertEqual(f(""), "")


class TestPostprocessCartFront(unittest.TestCase):
    def test_l_h_repair_after_parse(self):
        raw = '{"media_serial1": "L-H-AT5VA-EUR", "media_serial2": ""}'
        import json

        data = json.loads(raw)
        out = vlm.postprocess_vlm_dict(data, "cart_front")
        self.assertEqual(out["media_serial1"], "LA-H-AT5VA-EUR")


class TestRelaxedKeyLineFormat(unittest.TestCase):
    def test_lm_studio_labeled_lines(self):
        raw = """media_serial1: LA-H-AT5VA-EUR

media_serial2: empty string ""

box_serial: empty string ""

box_barcode: empty string ""

pcb_serial: empty string ""
"""
        out = vlm.parse_and_postprocess_vlm_text(raw, "cart_front")
        self.assertEqual(out["media_serial1"], "LA-H-AT5VA-EUR")
        self.assertEqual(out["media_serial2"], "")


class TestCartBackPostprocess(unittest.TestCase):
    def test_laser_media_serial2_collapses_spaces(self):
        import json

        data = json.loads('{"media_serial2": "AT5 VA 20B0053 G", "pcb_serial": ""}')
        out = vlm.postprocess_vlm_dict(data, "cart_back")
        self.assertEqual(out["media_serial2"], "AT5VA20B0053G")

    def test_tsa_style_collapses_whitespace(self):
        import json

        data = json.loads(
            '{"media_serial2": "TSA- HAC- AT5VA- UKV", "pcb_serial": ""}'
        )
        out = vlm.postprocess_vlm_dict(data, "cart_back")
        self.assertEqual(out["media_serial2"], "TSA-HAC-AT5VA-UKV")

    def test_pcb_serial_shortcut_at(self):
        import json

        data = json.loads('{"media_serial2": "", "pcb_serial": "@"}')
        out = vlm.postprocess_vlm_dict(data, "cart_back")
        self.assertEqual(out["pcb_serial"], "\u25bc")

    def test_media_serial2_length_hint_echo_scrubbed(self):
        data = {
            "media_serial1": "",
            "media_serial2": "12\u201316",
            "pcb_serial": "\u25bc 10",
        }
        out = vlm.postprocess_vlm_dict(data, "cart_back")
        self.assertEqual(out["media_serial2"], "")
        self.assertEqual(out["pcb_serial"], "\u25bc 10")

    def test_media_serial2_embossed_model_scrubbed(self):
        data = {
            "media_serial1": "",
            "media_serial2": "HAC-008",
            "pcb_serial": "",
        }
        out = vlm.postprocess_vlm_dict(data, "cart_back")
        self.assertEqual(out["media_serial2"], "")


class TestExtractBoxSerialFromFreeText(unittest.TestCase):
    def test_strict_token(self) -> None:
        self.assertEqual(
            vlm.extract_box_serial_from_free_text("Retail HAC-P-ATSVA and digits"),
            "HAC-P-ATSVA",
        )

    def test_rejects_overlap_inside_tsa_hac_p(self) -> None:
        self.assertIsNone(vlm.extract_box_serial_from_free_text("TSA-HAC-P-ATSVA-UKV"))

    def test_spaced_letters(self) -> None:
        self.assertEqual(
            vlm.extract_box_serial_from_free_text("H A C - P - ATSVA"),
            "HAC-P-ATSVA",
        )


class TestInsertBoxRecovery(unittest.TestCase):
    def test_postprocess_prefers_strict_from_raw_when_json_truncated(self) -> None:
        import json

        raw = (
            '{"box_serial": "HAC-P-T5A", "box_barcode": "6 59048 99044 8", '
            '"media_serial1": "", "media_serial2": "", "pcb_serial": ""}\n'
            "Model also said in prose: catalog HAC-P-ATSVA confirmed.\n"
        )
        data = json.loads(raw.split("\n")[0])
        out = vlm.postprocess_vlm_dict(data, "insert_spread", raw_fallback=raw)
        self.assertEqual(out["box_serial"], "HAC-P-ATSVA")


class TestMergeInsertSpreadPasses(unittest.TestCase):
    def test_combines_serial_and_barcode_dicts(self) -> None:
        out = vlm.merge_insert_spread_vlm_passes(
            {"box_serial": "HAC-P-ATSVA"},
            {"box_barcode": "6 59048 99044 8"},
            raw_serial="",
            raw_barcode="",
        )
        self.assertEqual(out["box_serial"], "HAC-P-ATSVA")
        self.assertEqual(out["box_barcode"], "6 59048 99044 8")


class TestInsertSplitPrompts(unittest.TestCase):
    def test_serial_prompt_ignores_barcode_row(self) -> None:
        p = vlm.prompt_insert_spread_box_serial_only()
        self.assertIn("Ignore the barcode", p)

    def test_barcode_prompt_ignores_hac_p_line(self) -> None:
        p = vlm.prompt_insert_spread_box_barcode_only()
        self.assertIn("Ignore the HAC-P-", p)


class TestInsertSpreadProse(unittest.TestCase):
    def test_numbered_list_lm_studio_blob(self):
        raw = """The image is a barcode from a Nintendo product, specifically the Super Mario Bros. 3 Limited Edition. Here are the details of the barcode:

1. Media Serial Number (MSN): HAC-P-A754
2. Barcode: 6 59084 99044 8
3. Manufacturer: Nintendo Co., Ltd.
4. Made in Japan
5. Box Serial: "
6. Box Barcode: "
7. Pcb Serial: ""
"""
        out = vlm.parse_and_postprocess_vlm_text(raw, "insert_spread")
        self.assertEqual(out["box_serial"], "HAC-P-A754")
        self.assertEqual(out["box_barcode"], "659084990448")
        self.assertEqual(out["media_serial1"], "")

    def test_insert_prose_prefers_hac_p_five(self):
        raw = "Catalog line HAC-P-ATSVA and Barcode: 6 59084 99044 8 on the insert.\n"
        out = vlm.parse_insert_spread_prose(raw)
        assert out is not None
        self.assertEqual(out["box_serial"], "HAC-P-ATSVA")
        self.assertEqual(out["box_barcode"], "659084990448")


if __name__ == "__main__":
    unittest.main()
