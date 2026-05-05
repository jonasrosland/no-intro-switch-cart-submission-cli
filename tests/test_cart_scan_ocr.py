"""Tests for optional ``Scans/`` OCR helpers (no real ROM or scan binaries in git)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from no_intro_switch_cart_submission_cli.cart_scan_ocr import (
    DEFAULT_CART_BACK_OCR_ROIS,
    DEFAULT_CART_FRONT_OCR_ROIS,
    DEFAULT_SCAN_OCR_ROIS,
    combine_extractions_by_field_priority,
    discover_scan_paths_by_role,
    extract_serial_fields_from_ocr_text,
    extract_serial_fields_from_ocr_text_for_role,
    find_pcb_serial_in_ocr_text,
    format_ocr_serial_snapshot_lines,
    list_scan_image_paths,
    merge_ocr_into_serial_row,
    merge_vlm_serial_fields,
    ocr_scans_enabled,
    resolve_scans_dir,
    run_vlm_on_ocr_crop_debug_for_cli,
    run_vlm_serial_extract,
    scan_ocr_rois_for_role,
    scan_ocr_rois_from_cfg,
    scan_ocr_use_tesseract,
    tesseract_cart_config,
    try_fill_serial_row_from_scans,
    try_fill_serial_row_from_scans_for_cli,
    vlm_debug_crops_requested,
)
from no_intro_switch_cart_submission_cli.constants import SERIAL_FIELDS


class FormatOcrSerialSnapshotLines(unittest.TestCase):
    def test_two_lines_and_empty_placeholder(self) -> None:
        row = {
            "media_serial1": "HAC-P-AT5VA-USA",
            "media_serial2": "",
            "box_serial": "",
            "box_barcode": "6 59048 99044 8",
            "pcb_serial": "",
            "gameid2": "HAC-P-AT5VA",
        }
        lines = format_ocr_serial_snapshot_lines(row, "Rev 005")
        self.assertEqual(len(lines), 2)
        self.assertIn("media_serial1=HAC-P-AT5VA-USA", lines[0])
        self.assertIn("box_barcode=6 59048 99044 8", lines[0])
        self.assertIn("(empty)", lines[0])
        self.assertIn("version1=Rev 005", lines[1])
        self.assertIn("gameid2=HAC-P-AT5VA", lines[1])


class OcrScansEnabled(unittest.TestCase):
    def test_cli_flag_wins(self) -> None:
        args = SimpleNamespace(ocr_scans=True)
        self.assertTrue(ocr_scans_enabled({}, args))

    def test_config_top_level(self) -> None:
        args = SimpleNamespace(ocr_scans=False)
        self.assertTrue(ocr_scans_enabled({"ocr_scans": True}, args))

    def test_scan_ocr_block(self) -> None:
        args = SimpleNamespace(ocr_scans=False)
        self.assertTrue(ocr_scans_enabled({"scan_ocr": {"enabled": True}}, args))

    def test_default_off(self) -> None:
        args = SimpleNamespace(ocr_scans=False)
        self.assertFalse(ocr_scans_enabled({}, args))


class ResolveScansDir(unittest.TestCase):
    def test_prefers_parent_scans(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            game = tmp_path / "My Game"
            ver = game / "1.0.0"
            ver.mkdir(parents=True)
            scans = game / "Scans"
            scans.mkdir()
            self.assertEqual(resolve_scans_dir(ver), scans.resolve())

    def test_falls_back_to_release_scans(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ver = tmp_path / "1.0.0"
            scans = ver / "Scans"
            ver.mkdir(parents=True)
            scans.mkdir()
            self.assertEqual(resolve_scans_dir(ver), scans.resolve())

    def test_none_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ver = Path(td) / "v1"
            ver.mkdir()
            self.assertIsNone(resolve_scans_dir(ver))


class ListScanImages(unittest.TestCase):
    def test_sorted_and_filtered(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "Scans"
            d.mkdir()
            (d / "b.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            (d / "a.jpg").write_text("x")
            (d / "readme.txt").write_text("no")
            names = [p.name for p in list_scan_image_paths(d)]
            self.assertEqual(names, ["a.jpg", "b.png"])


class ExtractSerialFields(unittest.TestCase):
    def test_cyber_shadow_style_blob(self) -> None:
        text = """
        HAC-P-AT5VA
        TSA-HAC-AT5VA-UKV
        LA-H-AS7TA-UKV
        6 59048 99044 8
        """
        got = extract_serial_fields_from_ocr_text(text)
        self.assertEqual(got["box_serial"], "HAC-P-AT5VA")
        self.assertEqual(got["media_serial2"], "TSA-HAC-AT5VA-UKV")
        self.assertEqual(got["media_serial1"], "LA-H-AS7TA-UKV")
        self.assertEqual(got["box_barcode"], "6 59048 99044 8")

    def test_box_serial_reports_ocr_verbatim(self) -> None:
        got = extract_serial_fields_from_ocr_text("HAC-P-ATSVA\nTSA-HAC-ATSVA-UKV\n")
        self.assertEqual(got["box_serial"], "HAC-P-ATSVA")

    def test_insert_role_ocr_ignores_media_serial_fields(self) -> None:
        text = "HAC-P-AT5VA\nTSA-HAC-AT5VA-UKV\nLA-H-AS7TA-UKV\n"
        got = extract_serial_fields_from_ocr_text_for_role(text, "insert_spread")
        self.assertEqual(got.get("box_serial"), "HAC-P-AT5VA")
        self.assertNotIn("media_serial1", got)
        self.assertNotIn("media_serial2", got)

    def test_media_serial2_cart_back_laser_etched(self) -> None:
        got = extract_serial_fields_from_ocr_text("HAC-008\nAT5VA20B0053G\nCE\n")
        self.assertEqual(got.get("media_serial2"), "AT5VA20B0053G")

    def test_media_serial2_prefers_tsa_hac_over_laser_when_both(self) -> None:
        blob = "TSA-HAC-AT5VA-UKV\nAT5VA20B0053G\n"
        self.assertEqual(extract_serial_fields_from_ocr_text(blob).get("media_serial2"), "TSA-HAC-AT5VA-UKV")

    def test_media_serial2_matches_tsa_wrapped_across_line_break(self) -> None:
        text = "noise\nTSA-HAC-\nAT5VA-UKV\n"
        self.assertEqual(
            extract_serial_fields_from_ocr_text(text).get("media_serial2"),
            "TSA-HAC-AT5VA-UKV",
        )

    def test_media_serial2_matches_when_ocr_inserts_p_after_hac(self) -> None:
        got = extract_serial_fields_from_ocr_text("x\nTSA-HAC-P-AT5VA-UKV\n")
        self.assertEqual(got.get("media_serial2"), "TSA-HAC-P-AT5VA-UKV")

    def test_spaced_retail_barcode_only_line(self) -> None:
        """Twelve digit characters in common retail spacing, not thirteen concatenated."""
        self.assertEqual(
            extract_serial_fields_from_ocr_text("  6 59048 99044 8  ")["box_barcode"],
            "6 59048 99044 8",
        )

    def test_plain_twelve_digit_barcode_line(self) -> None:
        got = extract_serial_fields_from_ocr_text("noise\n036000291452\n")
        self.assertEqual(got["box_barcode"], "0 36000 29145 2")

    def test_pcb_serial_from_v_and_unicode_triangle(self) -> None:
        self.assertEqual(find_pcb_serial_in_ocr_text("noise\nV 10\n"), "\u25bc 10")
        self.assertEqual(find_pcb_serial_in_ocr_text("\u25bc\n"), "\u25bc")
        self.assertEqual(find_pcb_serial_in_ocr_text("TSA-HAC-AT5VA-UKV\n\nV 10"), "\u25bc 10")

    def test_cart_back_role_keeps_pcb_not_box(self) -> None:
        blob = "HAC-P-WRONG\nTSA-HAC-AT5VA-UKV\nV 10\n"
        got = extract_serial_fields_from_ocr_text_for_role(blob, "cart_back")
        self.assertEqual(got.get("media_serial2"), "TSA-HAC-AT5VA-UKV")
        self.assertEqual(got.get("pcb_serial"), "\u25bc 10")
        self.assertNotIn("box_serial", got)
        self.assertNotIn("media_serial1", got)

    def test_cart_front_role_only_media_serial1(self) -> None:
        blob = "LA-H-AS7TA-UKV\nTSA-HAC-AT5VA-UKV\nV 10\n"
        got = extract_serial_fields_from_ocr_text_for_role(blob, "cart_front")
        self.assertEqual(got.get("media_serial1"), "LA-H-AS7TA-UKV")
        self.assertEqual(len(got), 1)
        self.assertNotIn("media_serial2", got)
        self.assertNotIn("pcb_serial", got)

    def test_barcode_gtin_self_corrects_5_read_as_0(self) -> None:
        got = extract_serial_fields_from_ocr_text("6 09048 99044 8\n")
        self.assertEqual(got["box_barcode"], "6 59048 99044 8")

    def test_thirteen_digit_line_not_box_barcode(self) -> None:
        self.assertNotIn("box_barcode", extract_serial_fields_from_ocr_text("4006381333931"))

    def test_barcode_line_must_be_digit_heavy(self) -> None:
        """Unconstrained OCR often merges letters into the GTIN row; detector requires ≥75% digit/space."""
        from no_intro_switch_cart_submission_cli.cart_scan_ocr import _find_box_barcode_line

        self.assertIsNone(_find_box_barcode_line("6 S O 9048 99044 8 noise"))
        self.assertEqual(_find_box_barcode_line("  6 59048 99044 8  "), "6 59048 99044 8")

    def test_box_serial_ocr_spaced_letters(self) -> None:
        self.assertEqual(
            extract_serial_fields_from_ocr_text("back\nH A C - P - AT5VA\n")["box_serial"],
            "HAC-P-AT5VA",
        )

    def test_box_serial_unicode_hyphen_then_strict(self) -> None:
        self.assertEqual(
            extract_serial_fields_from_ocr_text("HAC\u2013P\u2013AT5VA")["box_serial"],
            "HAC-P-AT5VA",
        )

    def test_box_serial_missing_hyphen_between_c_and_p(self) -> None:
        self.assertEqual(
            extract_serial_fields_from_ocr_text("HACP-AT5VA")["box_serial"],
            "HAC-P-AT5VA",
        )

    def test_box_serial_not_snipped_from_tsa_hac_p_media_style(self) -> None:
        got = extract_serial_fields_from_ocr_text("TSA-HAC-P-AT5VA-UKV\n6 59048 99044 8\n")
        self.assertNotIn("box_serial", got)


class ScanOcrRoisFromCfg(unittest.TestCase):
    def test_defaults_when_missing(self) -> None:
        self.assertEqual(scan_ocr_rois_from_cfg({}), list(DEFAULT_SCAN_OCR_ROIS))
        self.assertEqual(len(DEFAULT_SCAN_OCR_ROIS), 1)

    def test_custom_rois(self) -> None:
        cfg = {
            "scan_ocr": {
                "rois": [
                    {"x0": 0.1, "x1": 0.2, "y0": 0.3, "y1": 0.4},
                ]
            }
        }
        self.assertEqual(scan_ocr_rois_from_cfg(cfg), [(0.1, 0.2, 0.3, 0.4)])

    def test_cart_front_defaults_to_bottom_stamp_band(self) -> None:
        self.assertEqual(scan_ocr_rois_for_role({}, "cart_front"), list(DEFAULT_CART_FRONT_OCR_ROIS))

    def test_cart_back_defaults_to_single_stamp_roi(self) -> None:
        self.assertEqual(scan_ocr_rois_for_role({}, "cart_back"), list(DEFAULT_CART_BACK_OCR_ROIS))
        self.assertEqual(len(DEFAULT_CART_BACK_OCR_ROIS), 1)

    def test_tesseract_cart_config_default_and_override(self) -> None:
        self.assertEqual(tesseract_cart_config(None), "--oem 3 --psm 6")
        self.assertEqual(tesseract_cart_config({}), "--oem 3 --psm 6")
        self.assertEqual(
            tesseract_cart_config(
                {"scan_ocr": {"tesseract_cart_config": "  --oem 3 --psm 7  "}}
            ),
            "--oem 3 --psm 7",
        )

    def test_rois_by_role_override(self) -> None:
        cfg = {
            "scan_ocr": {
                "rois_by_role": {
                    "cart_back": [{"x0": 0.2, "x1": 0.8, "y0": 0.3, "y1": 0.7}],
                }
            }
        }
        self.assertEqual(
            scan_ocr_rois_for_role(cfg, "cart_back"),
            [(0.2, 0.8, 0.3, 0.7)],
        )


class DiscoverScanPathsByRole(unittest.TestCase):
    def test_explicit_files_win_over_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "Scans"
            d.mkdir()
            (d / "spread.png").write_bytes(b"x")
            (d / "custom.jpg").write_bytes(b"x")
            cfg = {
                "scan_ocr": {
                    "files": {
                        "insert_spread": "custom.jpg",
                        "cart_front": "spread.png",
                    }
                }
            }
            got = discover_scan_paths_by_role(d, cfg)
            self.assertEqual(got["insert_spread"], d / "custom.jpg")
            self.assertEqual(got["cart_front"], d / "spread.png")
            self.assertIsNone(got["cart_back"])

    def test_fnmatch_cart_and_legacy_insert(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "Scans"
            d.mkdir()
            (d / "cart-back.png").write_bytes(b"x")
            (d / "cart-front.png").write_bytes(b"x")
            (d / "orphan.png").write_bytes(b"x")
            got = discover_scan_paths_by_role(d, {})
            self.assertEqual(got["cart_front"], d / "cart-front.png")
            self.assertEqual(got["cart_back"], d / "cart-back.png")
            self.assertEqual(got["insert_spread"], d / "orphan.png")

    def test_assign_by_sorted_order_fills_unnamed_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "Scans"
            d.mkdir()
            for name in ("z.png", "a.png", "m.png", "b.png"):
                (d / name).write_bytes(b"x")
            cfg = {"scan_ocr": {"assign_by_sorted_order": True}}
            got = discover_scan_paths_by_role(d, cfg)
            self.assertEqual(got["insert_spread"], d / "a.png")
            self.assertEqual(got["cart_front"], d / "b.png")
            self.assertEqual(got["cart_back"], d / "m.png")


class CombineExtractions(unittest.TestCase):
    def test_pcb_serial_only_from_cart_back(self) -> None:
        by_role = {
            "cart_front": {"pcb_serial": "\u25bc"},
            "cart_back": {"pcb_serial": "\u25bc 10"},
        }
        self.assertEqual(combine_extractions_by_field_priority(by_role).get("pcb_serial"), "\u25bc 10")

    def test_media_serial1_only_from_cart_front_merge(self) -> None:
        by_role = {
            "cart_back": {"media_serial1": "LA-H-AAAAA-EUR"},
            "cart_front": {"media_serial1": "LA-H-BBBBB-EUR"},
        }
        self.assertEqual(
            combine_extractions_by_field_priority(by_role)["media_serial1"],
            "LA-H-BBBBB-EUR",
        )

    def test_media_serial2_only_from_cart_back_merge(self) -> None:
        by_role = {
            "cart_front": {"media_serial2": "SHOULD-NOT-WIN"},
            "cart_back": {"media_serial2": "00000000001"},
        }
        self.assertEqual(
            combine_extractions_by_field_priority(by_role)["media_serial2"],
            "00000000001",
        )

    def test_cart_ignored_for_box_serial_and_barcode(self) -> None:
        by_role = {
            "cart_front": {"box_serial": "HAC-P-WRONG", "box_barcode": "4006381333931"},
        }
        self.assertEqual(combine_extractions_by_field_priority(by_role), {})


class MergeOcrIntoSerialRow(unittest.TestCase):
    def test_only_fills_blanks(self) -> None:
        row = {
            "media_serial1": "KEEP",
            "media_serial2": "",
            "box_serial": "",
            "box_barcode": "",
            "pcb_serial": "",
        }
        filled = merge_ocr_into_serial_row(
            row,
            {
                "media_serial1": "LA-H-AAAAA-EUR",
                "media_serial2": "TSA-HAC-AAAAA-EUR",
                "box_serial": "HAC-P-AAAAA",
                "box_barcode": "4006381333931",
                "pcb_serial": "\u25bc 10",
            },
        )
        self.assertEqual(row["media_serial1"], "KEEP")
        self.assertEqual(row["media_serial2"], "TSA-HAC-AAAAA-EUR")
        self.assertEqual(row["pcb_serial"], "\u25bc 10")
        self.assertEqual(set(filled), {"media_serial2", "box_serial", "box_barcode", "pcb_serial"})


class ScanOcrUseTesseract(unittest.TestCase):
    def test_defaults_true(self) -> None:
        self.assertTrue(scan_ocr_use_tesseract({}))
        self.assertTrue(scan_ocr_use_tesseract({"scan_ocr": {}}))

    def test_false_when_disabled_in_config(self) -> None:
        self.assertFalse(scan_ocr_use_tesseract({"scan_ocr": {"use_tesseract": False}}))
        self.assertFalse(scan_ocr_use_tesseract({"scan_ocr": {"use_tesseract": "no"}}))


class VlmExtractHelpers(unittest.TestCase):
    def test_merge_vlm_fill_empty_only(self) -> None:
        ex = {"box_serial": "", "box_barcode": "6 59048 99044 8"}
        vlm = {"box_serial": "HAC-P-AT5VA"}
        m = merge_vlm_serial_fields(ex, vlm, fill_empty_only=True)
        self.assertEqual(m["box_serial"], "HAC-P-AT5VA")
        self.assertEqual(m["box_barcode"], "6 59048 99044 8")

    def test_merge_vlm_overwrites_when_fill_empty_false(self) -> None:
        ex = {"box_barcode": "111"}
        vlm = {"box_barcode": "6 59048 99044 8"}
        m = merge_vlm_serial_fields(ex, vlm, fill_empty_only=False)
        self.assertEqual(m["box_barcode"], "6 59048 99044 8")

    def test_run_vlm_serial_extract_python_echo(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.png"
            p.write_bytes(b"")
            cfg = {
                "scan_ocr": {
                    "vlm_extract_command": [
                        "echo",
                        '{"box_serial": "HAC-P-TESTA", "box_barcode": ""}',
                    ]
                }
            }
            out, err = run_vlm_serial_extract(p, cfg)
            self.assertIsNone(err, msg=str(err))
            self.assertEqual(out.get("box_serial"), "HAC-P-TESTA")

    def test_run_vlm_serial_extract_substitutes_role_in_argv(self) -> None:
        from unittest.mock import MagicMock, patch

        p = Path("/tmp/scan.png")
        cfg = {"scan_ocr": {"vlm_extract_command": ["noop", "{role}", "{image}"]}}
        with patch(
            "no_intro_switch_cart_submission_cli.cart_scan_ocr.subprocess.run",
        ) as run:
            run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")
            run_vlm_serial_extract(p, cfg, role="cart_front")
        argv = run.call_args[0][0]
        self.assertEqual(argv, ["noop", "cart_front", str(p.resolve())])


class TryFillFromScansMocked(unittest.TestCase):
    def test_fills_when_ocr_returns_blob(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            game = tmp_path / "G"
            ver = game / "1.0"
            scans = game / "Scans"
            ver.mkdir(parents=True)
            scans.mkdir()
            # Content unused while OCR is mocked (real runs need a valid image Pillow can open).
            (scans / "scan.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            row = {k: "" for k in ("media_serial1", "media_serial2", "box_serial", "box_barcode", "pcb_serial")}
            fake = (
                "HAC-P-AT5VA\n"
                "TSA-HAC-AT5VA-UKV\n"
                "LA-H-AS7TA-UKV\n"
                "6 59048 99044 8\n"
            )
            cfg = {
                "scan_ocr": {
                    "files": {
                        "insert_spread": "scan.png",
                    }
                }
            }
            with patch(
                "no_intro_switch_cart_submission_cli.cart_scan_ocr._tesseract_on_path",
                return_value=True,
            ), patch(
                "no_intro_switch_cart_submission_cli.cart_scan_ocr._ocr_one_image",
                return_value=fake,
            ):
                msgs = try_fill_serial_row_from_scans(ver, row, cfg)
            self.assertTrue(any("filled" in m for m in msgs))
            self.assertEqual(row["box_serial"], "HAC-P-AT5VA")
            self.assertEqual(row.get("media_serial1", ""), "")
            self.assertEqual(row.get("media_serial2", ""), "")

    def test_vlm_only_without_tesseract_fills_from_echo(self) -> None:
        """use_tesseract false: wiring calls crop-based VLM path (Pillow mocked away)."""
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            game = tmp_path / "G"
            ver = game / "1.0"
            scans = game / "Scans"
            ver.mkdir(parents=True)
            scans.mkdir()
            (scans / "scan.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            row = {
                k: ""
                for k in ("media_serial1", "media_serial2", "box_serial", "box_barcode", "pcb_serial")
            }
            cfg = {
                "scan_ocr": {
                    "use_tesseract": False,
                    "vlm_fill_empty_only": False,
                    "files": {"insert_spread": "scan.png"},
                    "vlm_extract_command": ["true"],
                }
            }
            with patch(
                "no_intro_switch_cart_submission_cli.cart_scan_ocr._tesseract_on_path",
                return_value=False,
            ), patch(
                "no_intro_switch_cart_submission_cli.cart_scan_ocr._vlm_fields_from_cropped_rois",
                return_value=({"box_serial": "HAC-P-VLMONLY"}, None),
            ) as vlm_mock:
                msgs = try_fill_serial_row_from_scans(ver, row, cfg)
            vlm_mock.assert_called_once()
        self.assertTrue(any("filled" in m for m in msgs), msg=msgs)
        self.assertEqual(row.get("box_serial"), "HAC-P-VLMONLY")

    def test_vlm_only_missing_extract_command_errors(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            game = tmp_path / "G"
            ver = game / "1.0"
            scans = game / "Scans"
            ver.mkdir(parents=True)
            scans.mkdir()
            (scans / "x.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            row = {k: "" for k in ("media_serial1", "media_serial2", "box_serial", "box_barcode", "pcb_serial")}
            msgs = try_fill_serial_row_from_scans(ver, row, {"scan_ocr": {"use_tesseract": False}})
        self.assertTrue(any("use_tesseract is false" in m for m in msgs))

    def test_dump_crops_prepends_debug_line(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            game = tmp_path / "G"
            ver = game / "1.0"
            scans = game / "Scans"
            ver.mkdir(parents=True)
            scans.mkdir()
            (scans / "scan.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            row = {k: "" for k in ("media_serial1", "media_serial2", "box_serial", "box_barcode", "pcb_serial")}
            fake = (
                "HAC-P-AT5VA\n"
                "TSA-HAC-AT5VA-UKV\n"
                "LA-H-AS7TA-UKV\n"
                "6 59048 99044 8\n"
            )
            cfg = {
                "scan_ocr": {
                    "files": {
                        "insert_spread": "scan.png",
                    }
                }
            }
            with patch(
                "no_intro_switch_cart_submission_cli.cart_scan_ocr._tesseract_on_path",
                return_value=True,
            ), patch(
                "no_intro_switch_cart_submission_cli.cart_scan_ocr._ocr_one_image",
                return_value=fake,
            ), patch(
                "no_intro_switch_cart_submission_cli.cart_scan_ocr.write_ocr_debug_crops",
            ) as w:
                msgs = try_fill_serial_row_from_scans(ver, row, cfg, dump_roi_crops=True)
            self.assertTrue(any("debug ROI crops" in m for m in msgs))
            self.assertTrue(any("filled" in m for m in msgs))
            w.assert_called_once()

    def test_dump_crops_written_when_cart_ocr_raises(self) -> None:
        """Debug dumps must still be produced for cart roles even if Tesseract path raises."""
        with tempfile.TemporaryDirectory() as td:
            ver = Path(td) / "1.0"
            scans = Path(td) / "Scans"
            ver.mkdir(parents=True)
            scans.mkdir()
            (scans / "cart.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            row = {k: "" for k in ("media_serial1", "media_serial2", "box_serial", "box_barcode", "pcb_serial")}
            cfg = {"scan_ocr": {"files": {"cart_front": "cart.png"}}}
            with patch(
                "no_intro_switch_cart_submission_cli.cart_scan_ocr._tesseract_on_path",
                return_value=True,
            ), patch(
                "no_intro_switch_cart_submission_cli.cart_scan_ocr._ocr_one_image",
                side_effect=RuntimeError("tesseract boom"),
            ), patch(
                "no_intro_switch_cart_submission_cli.cart_scan_ocr.write_ocr_debug_crops",
            ) as w:
                try_fill_serial_row_from_scans(ver, row, cfg, dump_roi_crops=True)
            w.assert_called_once()
            self.assertEqual(w.call_args[0][1], "cart_front")

    def test_dump_writes_scan_crop_for_unassigned_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ver = Path(td) / "1.0"
            scans = Path(td) / "Scans"
            ver.mkdir(parents=True)
            scans.mkdir()
            (scans / "insert_only.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            (scans / "orphan.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            row = {k: "" for k in ("media_serial1", "media_serial2", "box_serial", "box_barcode", "pcb_serial")}
            cfg = {"scan_ocr": {"files": {"insert_spread": "insert_only.png"}}}
            with patch(
                "no_intro_switch_cart_submission_cli.cart_scan_ocr._tesseract_on_path",
                return_value=True,
            ), patch(
                "no_intro_switch_cart_submission_cli.cart_scan_ocr._ocr_one_image",
                return_value="x",
            ), patch(
                "no_intro_switch_cart_submission_cli.cart_scan_ocr.write_ocr_debug_crops",
            ) as w:
                try_fill_serial_row_from_scans(ver, row, cfg, dump_roi_crops=True)
            tags = [c.args[1] for c in w.call_args_list]
            self.assertIn("insert_spread", tags)
            self.assertIn("scan_orphan", tags)

    def test_for_cli_respects_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            row = {"media_serial1": ""}
            args = SimpleNamespace(ocr_scans=False)
            msgs = try_fill_serial_row_from_scans_for_cli(Path(td), row, {}, args)
            self.assertEqual(msgs, [])


class VlmDebugCropsCli(unittest.TestCase):
    def test_requested_from_cli_flag(self) -> None:
        args = SimpleNamespace(vlm_debug_crops=True)
        self.assertTrue(vlm_debug_crops_requested({}, args))

    def test_requested_from_config(self) -> None:
        args = SimpleNamespace(vlm_debug_crops=False)
        self.assertTrue(vlm_debug_crops_requested({"scan_ocr": {"vlm_debug_crops": True}}, args))

    def test_not_requested(self) -> None:
        args = SimpleNamespace(vlm_debug_crops=False)
        self.assertFalse(vlm_debug_crops_requested({}, args))

    def test_skipped_no_vlm_command(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            row = {k: "" for k in SERIAL_FIELDS}
            cfg_path = Path(td) / "cfg.json"
            cfg_path.write_text("{}", encoding="utf-8")
            lines = run_vlm_on_ocr_crop_debug_for_cli(
                Path(td),
                row,
                {},
                SimpleNamespace(vlm_debug_crops=True),
                config_path=cfg_path,
            )
        self.assertEqual(len(lines), 1)
        self.assertIn("vlm_debug_crops: skipped", lines[0])
        self.assertIn("vlm_extract_command", lines[0])
        self.assertIn(str(cfg_path.resolve()), lines[0])

    def test_skipped_no_debug_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            rel = Path(td) / "1.0"
            rel.mkdir()
            row = {k: "" for k in SERIAL_FIELDS}
            cfg = {"scan_ocr": {"vlm_extract_command": ["noop", "{role}", "{image}"]}}
            lines = run_vlm_on_ocr_crop_debug_for_cli(
                rel, row, cfg, SimpleNamespace(vlm_debug_crops=True)
            )
        self.assertTrue(lines[0].startswith("vlm_debug_crops: skipped"))

    @patch("no_intro_switch_cart_submission_cli.cart_scan_ocr.run_vlm_serial_extract")
    def test_merge_three_roles(self, mock_run) -> None:
        def se(path: Path, cfg, role=None):
            if role == "insert_spread":
                return ({"box_serial": "HAC-P-ATSVA", "box_barcode": "659084990448"}, None)
            if role == "cart_front":
                return ({"media_serial1": "LA-H-TEST-EUR"}, None)
            return ({"media_serial2": "AT5VA20B0053G", "pcb_serial": "\u25bc 10"}, None)

        mock_run.side_effect = se
        with tempfile.TemporaryDirectory() as td:
            rel = Path(td) / "1.0"
            dbg = rel / "_ocr_crop_debug"
            dbg.mkdir(parents=True)
            for role in ("insert_spread", "cart_front", "cart_back"):
                (dbg / f"{role}_r0.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            row = {k: "" for k in SERIAL_FIELDS}
            cfg = {
                "scan_ocr": {
                    "vlm_extract_command": ["noop", "{role}", "{image}"],
                    "vlm_fill_empty_only": True,
                }
            }
            args = SimpleNamespace(vlm_debug_crops=True)
            lines = run_vlm_on_ocr_crop_debug_for_cli(rel, row, cfg, args)
        self.assertEqual(len(lines), 3)
        self.assertEqual(row["box_serial"], "HAC-P-ATSVA")
        self.assertEqual(row["box_barcode"], "659084990448")
        self.assertEqual(row["media_serial1"], "LA-H-TEST-EUR")
        self.assertEqual(row["media_serial2"], "AT5VA20B0053G")
        self.assertEqual(row["pcb_serial"], "\u25bc 10")


if __name__ == "__main__":
    unittest.main()
