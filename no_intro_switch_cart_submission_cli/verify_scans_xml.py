"""
Compare ``Scans/`` VLM extraction to serials already stored in a ``* Submission.xml``.

Uses ``try_fill_serial_row_from_scans`` (requires ``scan_ocr.vlm_extract_command`` in the
configuration file). Example::

    python3 -m no_intro_switch_cart_submission_cli.verify_scans_xml \\
      --config no_intro_submit.json \\
      --submission-xml /abs/path/to/Submission.xml \\
      --release-dir path/to/version-folder

Optional: ``--ocr-dump-crops`` (same as the main CLI).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from no_intro_switch_cart_submission_cli.cart_scan_ocr import (
    find_box_serial_in_ocr_text,
    format_box_barcode12_digits,
    refine_barcode_comp_with_gtin12_checksum,
    try_fill_serial_row_from_scans,
    vlm_extract_command,
)
from no_intro_switch_cart_submission_cli.constants import SERIAL_FIELDS
from no_intro_switch_cart_submission_cli.config_serial import load_config, normalize_pcb_serial
from no_intro_switch_cart_submission_cli.paths import CONFIG_FILE
from no_intro_switch_cart_submission_cli.submission_xml_serials import (
    parse_trusted_dump_serials_from_submission_xml,
    submission_xml_serials_summary,
)

_COMPARE_KEYS = ("media_serial1", "media_serial2", "box_serial", "box_barcode", "pcb_serial")


def _canonical_barcode(s: str) -> str:
    t = (s or "").strip()
    d = re.sub(r"\D", "", t)
    if len(d) == 12 and d.isdigit():
        d = refine_barcode_comp_with_gtin12_checksum(d)
        return format_box_barcode12_digits(d)
    return t


def _canonical_box_serial(s: str) -> str:
    """
    Match ``HAC-P-`` + five alphanumerics across minor formatting drift (XML / OCR / VLM).

    Handles strict ``HAC-P-AT5VA``, spaced letters ``H A C - P - AT5VA``, ``HACP-AT5VA``, and
    common pretty-print loss of hyphens: ``HAC P AT5VA``.
    """
    v = (s or "").strip()
    if not v:
        return ""
    guess = find_box_serial_in_ocr_text(v)
    if guess:
        return guess.upper()
    # Hyphens missing between HAC and P (e.g. some XML serializers): "HAC P AT5VA"
    collapsed = re.sub(
        r"(?<![A-Za-z0-9])HAC\s+P\s+([A-Za-z0-9]{5})(?![A-Za-z0-9])",
        r"HAC-P-\1",
        v,
        flags=re.IGNORECASE,
    )
    if collapsed != v:
        guess = find_box_serial_in_ocr_text(collapsed)
        if guess:
            return guess.upper()
    return v.upper()


def canonical_serial_for_compare(key: str, value: str) -> str:
    """Normalize values the same way we expect minor formatting drift between XML and VLM."""
    v = (value or "").strip()
    if key == "pcb_serial":
        return normalize_pcb_serial(v)
    if key == "box_barcode":
        return _canonical_barcode(v)
    if key in ("media_serial1", "media_serial2"):
        return re.sub(r"\s+", "", v).upper()
    if key == "box_serial":
        return _canonical_box_serial(v)
    return v


def verify_scans_against_submission_xml(
    cfg_path: Path,
    submission_xml: Path,
    release_dir: Path | None,
    compare: str,
    *,
    dump_roi_crops: bool = False,
) -> int:
    """
    Compare serials in ``submission_xml`` to a fresh ``Scans/`` VLM extraction using ``cfg_path``.

    ``release_dir`` may be ``None`` (use parent directory of the XML). ``compare`` is ``stored`` or ``all``.
    When ``dump_roi_crops`` is true, ROI debug PNGs are written like ``--ocr-dump-crops`` on the main CLI.
    """
    xml_path = submission_xml.expanduser().resolve()
    if not xml_path.is_file():
        print(f"verify_scans_xml: not a file: {xml_path}", file=sys.stderr)
        return 2

    rel_dir = (release_dir.expanduser().resolve() if release_dir else xml_path.parent)
    if not rel_dir.is_dir():
        print(f"verify_scans_xml: not a directory: {rel_dir}", file=sys.stderr)
        return 2

    cfg_p = cfg_path.expanduser()
    if not cfg_p.is_file():
        print(f"verify_scans_xml: configuration not found: {cfg_p}", file=sys.stderr)
        return 2

    cfg = load_config(cfg_p)
    if not vlm_extract_command(cfg):
        print(
            "verify_scans_xml: set scan_ocr.vlm_extract_command in your configuration "
            "(same as for --ocr-scans).",
            file=sys.stderr,
        )
        return 2

    expected = parse_trusted_dump_serials_from_submission_xml(xml_path)
    vlm_row: dict[str, str] = {k: "" for k in SERIAL_FIELDS}
    msgs = try_fill_serial_row_from_scans(
        rel_dir, vlm_row, cfg, dump_roi_crops=dump_roi_crops
    )

    print(f"Submission XML: {xml_path}")
    print(f"Release / Scans anchor: {rel_dir}")
    print("Expected (XML):", submission_xml_serials_summary(expected))
    print("VLM (Scans/): ", submission_xml_serials_summary(vlm_row))
    for ln in msgs:
        print(f"  {ln}")

    mismatches: list[str] = []
    for key in _COMPARE_KEYS:
        e = canonical_serial_for_compare(key, expected.get(key, ""))
        g = canonical_serial_for_compare(key, vlm_row.get(key, ""))
        if e == g:
            continue
        if compare == "stored" and not (expected.get(key) or "").strip():
            continue
        mismatches.append(f"{key}: XML {expected.get(key, '')!r} vs VLM {vlm_row.get(key, '')!r} (normalized {e!r} vs {g!r})")

    if mismatches:
        print("\nMismatch:", file=sys.stderr)
        for m in mismatches:
            print(f"  {m}", file=sys.stderr)
        return 1

    print("\nOK: serial fields match within the chosen compare mode.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, default=CONFIG_FILE, help="JSON configuration (default: repo no_intro_submit.json)")
    ap.add_argument(
        "--submission-xml",
        type=Path,
        required=True,
        help="Path to an existing * Submission.xml",
    )
    ap.add_argument(
        "--release-dir",
        type=Path,
        default=None,
        help="Version folder that contains or sits next to Scans/ (default: parent of the XML file)",
    )
    ap.add_argument(
        "--compare",
        choices=("stored", "all"),
        default="stored",
        help=(
            "stored: only keys with a non-empty value in the XML must match the VLM (default). "
            "all: every key must match, including empty-in-XML vs non-empty VLM."
        ),
    )
    ap.add_argument(
        "--ocr-dump-crops",
        dest="ocr_dump_crops",
        action="store_true",
        help="Write <release>/_ocr_crop_debug/ ROI PNGs during the VLM fill (same as main CLI).",
    )
    args = ap.parse_args()

    return verify_scans_against_submission_xml(
        args.config,
        args.submission_xml,
        args.release_dir,
        args.compare,
        dump_roi_crops=args.ocr_dump_crops,
    )


if __name__ == "__main__":
    raise SystemExit(main())
