"""Optional ``Scans/`` pipeline: ROI crops + vision-model subprocess to fill empty serial fields."""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import sys
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from no_intro_switch_cart_submission_cli.config_serial import normalize_pcb_serial
from no_intro_switch_cart_submission_cli.constants import SERIAL_FIELDS

# Insert spread: **one** ROI — bottom band like the old ``r2`` strip, but horizontally only the
# **right half of the left half** of the frame (**x ∈ [0.25, 0.5]**): typical spot for the barcode,
# **HAC-P-**, and **TSA-HAC-** on a wide front|spine|back scan. Override ``scan_ocr.rois`` if your
# layout differs (e.g. barcode under **x ∈ [0.5, 0.75]** → use ``0.5, 0.75`` for that slice).
DEFAULT_SCAN_OCR_ROIS: tuple[tuple[float, float, float, float], ...] = (
    (0.25, 0.5, 0.78, 1.0),
)

# Whole-frame ROI fallback (e.g. custom ``rois_by_role`` for an extra role).
DEFAULT_FULL_FRAME_ROIS: tuple[tuple[float, float, float, float], ...] = ((0.0, 1.0, 0.0, 1.0),)

# Cart **back**: one ROI from below the embossed model line through the PCB windows (etched
# media_serial2 + PCB marks). Override ``scan_ocr.rois_by_role.cart_back`` if your framing differs.
DEFAULT_CART_FRONT_OCR_ROIS: tuple[tuple[float, float, float, float], ...] = ((0.05, 0.95, 0.48, 1.0),)
DEFAULT_CART_BACK_OCR_ROIS: tuple[tuple[float, float, float, float], ...] = ((0.05, 0.95, 0.18, 1.0),)

_VLM_JSON_KEYS = frozenset(k for k in SERIAL_FIELDS if k != "gameid2")

_SCAN_ROLES: tuple[str, ...] = (
    "insert_spread",
    "cart_front",
    "cart_back",
)

# fnmatch on basename (case-insensitive). First unused file wins per role, in role order.
_DEFAULT_ROLE_PATTERNS: dict[str, tuple[str, ...]] = {
    "insert_spread": (
        "*insert*",
        "*spread*",
        "*flatbed*",
        "*front*back*",
        "*back*front*",
        "*cover*spread*",
    ),
    "cart_front": ("*cart*front*", "*front*cart*", "*cart_front*"),
    "cart_back": ("*cart*back*", "*back*cart*", "*cart_back*"),
}

# Basenames matching these fnmatch patterns (case-insensitive) are skipped for scan OCR entirely:
# no role assignment (including ``scan_ocr.files``), no VLM crops, no ``_ocr_crop_debug`` dumps.
# Extend with ``scan_ocr.ignore_scan_patterns`` (list of strings).
_DEFAULT_IGNORE_SCAN_BASENAME_PATTERNS: tuple[str, ...] = (
    "*reverse*",
    "*inside*",
)

# When merging OCR from several images, which role wins for each XML field (first hit wins).
_FIELD_ROLE_PRIORITY: dict[str, tuple[str, ...]] = {
    "box_serial": ("insert_spread",),
    "box_barcode": ("insert_spread",),
    # ``media_serial1`` only from **cart_front**; ``media_serial2`` and ``pcb_serial`` only from
    # **cart_back**. **insert_spread** supplies ``box_serial`` / ``box_barcode`` only.
    "media_serial1": ("cart_front",),
    "media_serial2": ("cart_back",),
    "pcb_serial": ("cart_back",),
}

# Insert spread only: packaging retail fields (never ``media_serial1`` / ``media_serial2``).
_PACKAGING_OCR_ROLES = frozenset({"insert_spread"})

_CART_FRONT_EXTRACT_KEYS = frozenset({"media_serial1"})
_CART_BACK_EXTRACT_KEYS = frozenset({"media_serial2", "pcb_serial"})

_MAX_OCR_WIDTH = 2200
_SCAN_IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"})

_RE_MEDIA1 = re.compile(r"\bL[A-Z]-H-[A-Z0-9]{5}(?:-[A-Z]{3})?\b", re.IGNORECASE)
_RE_BOX_HAC_P = re.compile(r"\bHAC-P-[A-Z0-9]{5}\b", re.IGNORECASE)
# OCR may drop spaces, merge hyphens, or use Unicode dashes — but avoid matching the inner
# ``HAC-P-`` inside ``TSA-HAC-P-…``-style media strings (overlap with ``_RE_MEDIA_PREFIX_HAC_P``).
_RE_BOX_HAC_P_SPACED = re.compile(
    r"(?<![A-Za-z0-9])H\s*A\s*C\s*-\s*P\s*-\s*([A-Za-z0-9]{5})(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_RE_BOX_HAC_P_NO_C_HYPH = re.compile(
    r"(?<![A-Za-z0-9])H\s*A\s*C\s*P\s*-\s*([A-Za-z0-9]{5})(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_RE_MEDIA_PREFIX_HAC_P = re.compile(r"\b[A-Z]{2,3}-HAC-P-", re.IGNORECASE)
# Optional ``P-`` after ``HAC-`` catches OCR that merges the retail ``HAC-P-`` prefix into the
# media line (``TSA-HAC-P-AT5VA-UKV``). Optional ``\\s*`` after ``HAC-`` / ``P-`` tolerates a line
# break collapsed to a space (``TSA-HAC-\\nAT5VA-UKV``). Search runs on a whitespace-collapsed copy
# of the **cart** OCR blob so wrapped lines still match.
_RE_MEDIA2_LONG = re.compile(
    r"\b[A-Z]{2,3}-HAC-\s*(?:P-\s*)?[A-Z0-9]+-[A-Z]{3}\b",
    re.IGNORECASE,
)
# Cart back: laser-etched media_serial2 (no ``TSA-HAC-…``); allow single spaces between chars.
_RE_MEDIA2_CART_LASER = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z0-9](?:\s*[A-Za-z0-9]){11,15})(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_RE_PCB_V_LIKE_TRIANGLE = re.compile(r"^\s*[VvYy]\s*(\d{1,3})?\s*$")
_RE_PCB_UNICODE_TRIANGLE = re.compile(r"\u25bc", re.UNICODE)

# Retail box codes: **12 digit characters** per line (often printed ``d ddddd ddddd d``).
# OCR may return a compact run; we normalize to that spaced layout for ``box_barcode`` XML.


def format_box_barcode12_digits(comp: str) -> str:
    """Twelve digits as ``d ddddd ddddd d`` (common Switch retail print layout)."""
    if len(comp) != 12 or not comp.isdigit():
        return comp
    return f"{comp[0]} {comp[1:6]} {comp[6:11]} {comp[11]}"


def _gtin12_check_digit_valid(comp12: str) -> bool:
    """GS1-style check on twelve digit characters (last digit is check)."""
    if len(comp12) != 12 or not comp12.isdigit():
        return False
    s = 0
    for i, c in enumerate(reversed(comp12[:11])):
        s += int(c) * (3 if i % 2 == 0 else 1)
    chk = (10 - (s % 10)) % 10
    return chk == int(comp12[11])


def refine_barcode_comp_with_gtin12_checksum(comp: str) -> str:
    """
    If twelve digits fail the GTIN check, try **single** substitutions; return the **first**
    checksum-valid hit using swap priority (**0** vs **5** first — common OCR digit confusion), then
    other digit pairs. Ambiguous multi-fix cases are left unchanged.
    """
    if len(comp) != 12 or not comp.isdigit():
        return comp
    if _gtin12_check_digit_valid(comp):
        return comp
    swaps = (
        ("0", "5"),
        ("5", "0"),
        ("6", "8"),
        ("8", "6"),
        ("1", "7"),
        ("7", "1"),
        ("3", "8"),
        ("8", "3"),
    )
    for i, ch in enumerate(comp):
        for a, b in swaps:
            if ch != a:
                continue
            cand = comp[:i] + b + comp[i + 1 :]
            if _gtin12_check_digit_valid(cand):
                return cand
    return comp


def ocr_scans_enabled(cfg: dict[str, Any], args: Any) -> bool:
    if getattr(args, "ocr_scans", False):
        return True
    if cfg.get("ocr_scans"):
        return True
    block = cfg.get("scan_ocr")
    if isinstance(block, dict) and block.get("enabled"):
        return True
    return False


def resolve_scans_dir(release_dir: Path) -> Path | None:
    """Prefer ``<game>/Scans`` next to the version folder; else ``<version>/Scans``."""
    release_dir = release_dir.resolve()
    parent_scans = release_dir.parent / "Scans"
    if parent_scans.is_dir():
        return parent_scans
    local = release_dir / "Scans"
    if local.is_dir():
        return local
    return None


def list_scan_image_paths(scans_dir: Path) -> list[Path]:
    out: list[Path] = []
    try:
        for p in scans_dir.iterdir():
            if not p.is_file():
                continue
            if p.suffix.lower() in _SCAN_IMAGE_EXTS:
                out.append(p)
    except OSError:
        return []
    return sorted(out, key=lambda x: x.name.lower())


def _ignore_scan_basename_patterns(cfg: dict[str, Any]) -> list[str]:
    patterns = list(_DEFAULT_IGNORE_SCAN_BASENAME_PATTERNS)
    block = cfg.get("scan_ocr") if isinstance(cfg.get("scan_ocr"), dict) else {}
    extra = block.get("ignore_scan_patterns")
    if isinstance(extra, list):
        for x in extra:
            s = str(x).strip()
            if s:
                patterns.append(s)
    return patterns


def scan_basename_ignored_for_scan_ocr(basename: str, cfg: dict[str, Any]) -> bool:
    """True if this scan basename must not participate in role assignment or OCR/debug dumps."""
    name_lower = basename.lower()
    for pat in _ignore_scan_basename_patterns(cfg):
        if fnmatch.fnmatch(name_lower, pat.lower()):
            return True
    return False


def _list_scan_image_paths_for_ocr(scans_dir: Path, cfg: dict[str, Any]) -> list[Path]:
    return [
        p
        for p in list_scan_image_paths(scans_dir)
        if not scan_basename_ignored_for_scan_ocr(p.name, cfg)
    ]


def _parse_roi_dict_list(raw: Any) -> list[tuple[float, float, float, float]]:
    if not isinstance(raw, list) or not raw:
        return []
    parsed: list[tuple[float, float, float, float]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            parsed.append(
                (
                    float(item["x0"]),
                    float(item["x1"]),
                    float(item["y0"]),
                    float(item["y1"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return parsed


def scan_ocr_rois_from_cfg(cfg: dict[str, Any]) -> list[tuple[float, float, float, float]]:
    """ROIs for the **insert spread** only (``scan_ocr.rois``)."""
    block = cfg.get("scan_ocr")
    if not isinstance(block, dict):
        return list(DEFAULT_SCAN_OCR_ROIS)
    parsed = _parse_roi_dict_list(block.get("rois"))
    return parsed or list(DEFAULT_SCAN_OCR_ROIS)


def scan_ocr_rois_for_role(cfg: dict[str, Any], role: str) -> list[tuple[float, float, float, float]]:
    """ROIs for a scan **role** (insert strip or cart stamp bands)."""
    block = cfg.get("scan_ocr")
    if isinstance(block, dict):
        by_role = block.get("rois_by_role")
        if isinstance(by_role, dict):
            raw = by_role.get(role)
            parsed = _parse_roi_dict_list(raw)
            if parsed:
                return parsed
    if role == "insert_spread":
        return scan_ocr_rois_from_cfg(cfg)
    if role == "cart_front":
        return list(DEFAULT_CART_FRONT_OCR_ROIS)
    if role == "cart_back":
        return list(DEFAULT_CART_BACK_OCR_ROIS)
    return list(DEFAULT_FULL_FRAME_ROIS)


def _role_patterns_for(cfg: dict[str, Any], role: str) -> tuple[str, ...]:
    block = cfg.get("scan_ocr")
    if not isinstance(block, dict):
        return _DEFAULT_ROLE_PATTERNS.get(role, ())
    rp = block.get("role_patterns")
    if isinstance(rp, dict):
        custom = rp.get(role)
        if isinstance(custom, list) and custom:
            return tuple(str(x).strip() for x in custom if str(x).strip())
    return _DEFAULT_ROLE_PATTERNS.get(role, ())


def discover_scan_paths_by_role(scans_dir: Path, cfg: dict[str, Any]) -> dict[str, Path | None]:
    """
    Map role -> image path.

    Resolution: (1) ``scan_ocr.files`` basename entries, (2) fnmatch on sorted files per role
    (each file at most one role, order insert_spread → cart_front → cart_back),
    (3) if **insert_spread** is still unset, assign the first sorted image not yet used (legacy),
    (4) if ``scan_ocr.assign_by_sorted_order`` is true, assign any still-empty role from remaining
    images in that same role order (**insert_spread** → **cart_front** → **cart_back**).

    Files whose basenames match ``scan_ocr.ignore_scan_patterns`` (plus built-in defaults such as
    ``*reverse*`` / ``*inside*``) are omitted from (1)–(4); they are never used for OCR or debug crops.
    """
    scans_dir = scans_dir.resolve()
    out: dict[str, Path | None] = {r: None for r in _SCAN_ROLES}
    pics = _list_scan_image_paths_for_ocr(scans_dir, cfg)
    if not pics:
        return out

    used: set[Path] = set()
    block = cfg.get("scan_ocr") if isinstance(cfg.get("scan_ocr"), dict) else {}

    explicit = block.get("files")
    if isinstance(explicit, dict):
        for role in _SCAN_ROLES:
            raw_name = explicit.get(role)
            if raw_name is None or not str(raw_name).strip():
                continue
            safe = Path(str(raw_name).strip()).name
            if not safe or safe in (".", ".."):
                continue
            if scan_basename_ignored_for_scan_ocr(safe, cfg):
                continue
            candidate = (scans_dir / safe).resolve()
            try:
                candidate.relative_to(scans_dir)
            except ValueError:
                continue
            if candidate.is_file():
                out[role] = candidate
                used.add(candidate)

    for role in _SCAN_ROLES:
        if out.get(role) is not None:
            continue
        patterns = _role_patterns_for(cfg, role)
        for pic in pics:
            if pic.resolve() in used:
                continue
            name_lower = pic.name.lower()
            for pat in patterns:
                if fnmatch.fnmatch(name_lower, pat.lower()):
                    out[role] = pic
                    used.add(pic.resolve())
                    break

    if out["insert_spread"] is None:
        for pic in pics:
            pr = pic.resolve()
            if pr not in used:
                out["insert_spread"] = pic
                used.add(pr)
                break

    if block.get("assign_by_sorted_order"):
        remaining = [p for p in pics if p.resolve() not in used]
        for role in _SCAN_ROLES:
            if out.get(role) is not None:
                continue
            if not remaining:
                break
            nxt = remaining.pop(0)
            out[role] = nxt
            used.add(nxt.resolve())

    return out


def combine_extractions_by_field_priority(by_role: dict[str, dict[str, str]]) -> dict[str, str]:
    """Pick one value per field using ``_FIELD_ROLE_PRIORITY``."""
    combined: dict[str, str] = {}
    for field, role_order in _FIELD_ROLE_PRIORITY.items():
        for role in role_order:
            blob = by_role.get(role) or {}
            v = (blob.get(field) or "").strip()
            if v:
                combined[field] = v
                break
    return combined


def _find_box_barcode_line(text: str) -> str | None:
    """Digit-heavy lines whose non-digits strip to twelve digits → canonical ``d ddddd ddddd d``."""
    for line in text.splitlines():
        s = line.strip()
        if len(s) < 7:
            continue
        ratio = sum(1 for c in s if c.isdigit() or c.isspace()) / len(s)
        if ratio < 0.75:
            continue
        comp = re.sub(r"\D", "", s)
        if len(comp) == 12 and comp.isdigit():
            comp = refine_barcode_comp_with_gtin12_checksum(comp)
            return format_box_barcode12_digits(comp)
    return None


def _finalize_hac_p_box_serial(code: str) -> str:
    """Uppercase a matched ``HAC-P-`` + five-character retail code (no OCR character guessing)."""
    return code.upper()


def _normalize_ocr_hyphen_like(s: str) -> str:
    """Map Unicode dashes and NBSP to ASCII hyphen / space so regexes behave."""
    for u, rep in (
        ("\u2013", "-"),
        ("\u2014", "-"),
        ("\u2212", "-"),
        ("\u00a0", " "),
    ):
        s = s.replace(u, rep)
    return s


def _flex_hac_p_overlaps_media_prefix(text: str, m: re.Match[str]) -> bool:
    s, e = m.span()
    for m2 in _RE_MEDIA_PREFIX_HAC_P.finditer(text):
        a, b = m2.span()
        if s < b and a < e:
            return True
    return False


def find_box_serial_in_ocr_text(text: str) -> str | None:
    """
    Nintendo retail **box** product id ``HAC-P-`` + five alphanumerics.

    Prefer strict word-boundary match (``\\b`` can still start after ``-`` in ``…-HAC-P-…``,
    so overlaps with ``XXX-HAC-P-`` media-style prefixes are rejected); else tolerate OCR
    spacing / missing hyphen after ``C``.
    """
    t = _normalize_ocr_hyphen_like(text)
    for m in _RE_BOX_HAC_P.finditer(t):
        if _flex_hac_p_overlaps_media_prefix(t, m):
            continue
        return _finalize_hac_p_box_serial(m.group(0))
    for rx in (_RE_BOX_HAC_P_SPACED, _RE_BOX_HAC_P_NO_C_HYPH):
        for m in rx.finditer(t):
            if _flex_hac_p_overlaps_media_prefix(t, m):
                continue
            suf = m.group(1).upper()
            if re.fullmatch(r"[A-Z0-9]{5}", suf):
                return _finalize_hac_p_box_serial(f"HAC-P-{suf}")
    return None


def _line_looks_like_long_digit_stamp(s: str) -> bool:
    """True for digit-heavy lines (e.g. 11-char media_serial2) that are not PCB rows."""
    if len(s) < 8:
        return False
    d = sum(1 for c in s if c.isdigit())
    return d / max(len(s), 1) >= 0.85


def _parse_pcb_serial_from_line(line: str) -> str | None:
    """
    PCB row: factory triangle (U+25BC) ± digits, or OCR reading **V** / **Y** as **▼**.

    Config shortcuts ``@`` / ``$`` are accepted on a whole line.
    """
    s = _normalize_ocr_hyphen_like(line).strip()
    if not s or len(s) > 24:
        return None
    if _RE_MEDIA1.search(s) or _RE_MEDIA2_LONG.search(s) or _RE_BOX_HAC_P.search(s):
        return None
    if _line_looks_like_long_digit_stamp(s):
        return None

    sc = normalize_pcb_serial(s)
    if sc in ("\u25bc", "\u25bc 10"):
        return sc
    if s in ("@", "$"):
        return sc

    if _RE_PCB_UNICODE_TRIANGLE.search(s):
        m = re.search(r"\u25bc\s*(\d{1,3})?", s, flags=re.UNICODE)
        if not m:
            return "\u25bc"
        tail = (m.group(1) or "").strip()
        return "\u25bc" if not tail else f"\u25bc {tail}"

    m = _RE_PCB_V_LIKE_TRIANGLE.match(s)
    if m:
        tail = (m.group(1) or "").strip()
        return "\u25bc" if not tail else f"\u25bc {tail}"

    return None


def _cart_laser_media_serial2_candidate(compact: str) -> str | None:
    """Validate a space-stripped 12–16 char token as a cart laser-etched media_serial2."""
    s = compact.upper()
    if len(s) < 12 or len(s) > 16 or not re.fullmatch(r"[A-Z0-9]+", s):
        return None
    if re.match(r"^[0-9]{2,}", s):
        return None
    if not any(c.isdigit() for c in s) or not any("A" <= c <= "Z" for c in s):
        return None
    if len(set(s)) < 4:
        return None
    return s


def find_media_serial2_in_ocr_text(text: str) -> str | None:
    """
    From **cart** OCR text: prefer a ``TSA-HAC-…-REG``-style token when present on the photo; else
    the **laser-etched** media id (12–16 alphanumerics, e.g. ``AT5VA20B0053G``), tolerating light
    OCR spacing.

    Matching is **per line** so ``HAC-008`` on one line does not merge with the etched code.
    """
    t = _normalize_ocr_hyphen_like(text)
    collapsed = re.sub(r"\s+", " ", t.strip())
    m_pkg = _RE_MEDIA2_LONG.search(collapsed)
    if m_pkg:
        return re.sub(r"\s+", "", m_pkg.group(0)).upper()
    best: str | None = None
    for line in t.splitlines():
        sline = line.strip()
        if not sline:
            continue
        for m in _RE_MEDIA2_CART_LASER.finditer(sline):
            cand = _cart_laser_media_serial2_candidate(re.sub(r"\s+", "", m.group(1)))
            if cand is None:
                continue
            if best is None or len(cand) > len(best):
                best = cand
    if best is None:
        return None
    return best


def find_pcb_serial_in_ocr_text(text: str) -> str | None:
    """First plausible PCB stencil line; prefers the **last** OCR block (cart_back lower ROI)."""
    t = (text or "").strip()
    if not t:
        return None
    for block in reversed(t.split("\n\n")):
        for line in block.splitlines():
            got = _parse_pcb_serial_from_line(line)
            if got:
                return got
    return None


def extract_serial_fields_from_ocr_text_for_role(text: str, role: str) -> dict[str, str]:
    """Filter parsed fields by scan role (insert packaging vs cart)."""
    ex = extract_serial_fields_from_ocr_text(text)
    if role in _PACKAGING_OCR_ROLES:
        return {k: v for k, v in ex.items() if k in ("box_serial", "box_barcode")}
    if role == "cart_front":
        return {k: v for k, v in ex.items() if k in _CART_FRONT_EXTRACT_KEYS}
    if role == "cart_back":
        return {k: v for k, v in ex.items() if k in _CART_BACK_EXTRACT_KEYS}
    return ex


def extract_serial_fields_from_ocr_text(text: str) -> dict[str, str]:
    """Map OCR blob to submission keys (subset). Only high-confidence patterns."""
    out: dict[str, str] = {}
    if not (text or "").strip():
        return out

    bc = _find_box_barcode_line(text)
    if bc:
        out["box_barcode"] = bc

    bs = find_box_serial_in_ocr_text(text)
    if bs:
        out["box_serial"] = bs

    ms2 = find_media_serial2_in_ocr_text(text)
    if ms2:
        out["media_serial2"] = ms2

    for m in _RE_MEDIA1.finditer(text):
        cand = m.group(0).upper()
        if cand and cand not in out.get("media_serial2", ""):
            out["media_serial1"] = cand
            break

    pcb = find_pcb_serial_in_ocr_text(text)
    if pcb:
        out["pcb_serial"] = normalize_pcb_serial(pcb)

    return out


def _prepare_roi_crop(im: Any, frac: tuple[float, float, float, float]) -> Any:
    from PIL import Image, ImageOps

    w, h = im.size
    x0, x1, y0, y1 = frac
    box = (
        int(max(0, min(1, x0)) * w),
        int(max(0, min(1, y0)) * h),
        int(max(0, min(1, x1)) * w),
        int(max(0, min(1, y1)) * h),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError(f"invalid ROI {frac}")
    crop = im.crop(box).convert("L")
    crop = ImageOps.autocontrast(crop)
    cw, ch = crop.size
    min_side = min(cw, ch)
    if min_side > 0 and min_side < 560:
        z = min(2.6, 1120 / min_side)
        if z > 1.02:
            crop = crop.resize((int(cw * z), int(ch * z)), Image.Resampling.LANCZOS)
            cw, ch = crop.size
    if cw > _MAX_OCR_WIDTH:
        scale = _MAX_OCR_WIDTH / cw
        crop = crop.resize((int(cw * scale), int(ch * scale)), Image.Resampling.LANCZOS)
    return crop


def merge_ocr_into_serial_row(serial_row: dict[str, str], ocr_fields: dict[str, str]) -> list[str]:
    """Fill only empty keys among media / box / pcb serial fields from merged scan hints."""
    filled: list[str] = []
    for k in ("media_serial1", "media_serial2", "box_serial", "box_barcode", "pcb_serial"):
        v = (ocr_fields.get(k) or "").strip()
        if not v:
            continue
        if (serial_row.get(k) or "").strip():
            continue
        serial_row[k] = normalize_pcb_serial(v) if k == "pcb_serial" else v
        filled.append(k)
    return filled


def ocr_dump_crops_requested(cfg: dict[str, Any], args: Any) -> bool:
    if getattr(args, "ocr_dump_crops", False):
        return True
    block = cfg.get("scan_ocr")
    return isinstance(block, dict) and bool(block.get("dump_crops"))


def _prepend_ocr_debug_path(note: str | None, lines: list[str]) -> list[str]:
    if note:
        return [note, *lines]
    return lines


def vlm_extract_command(cfg: dict[str, Any]) -> list[str] | None:
    """Optional argv for a vision helper; each element may contain ``{image}`` (absolute path)."""
    block = cfg.get("scan_ocr")
    if not isinstance(block, dict):
        return None
    cmd = block.get("vlm_extract_command")
    if not isinstance(cmd, list) or not cmd:
        return None
    if not all(isinstance(x, str) for x in cmd):
        return None
    return [str(x) for x in cmd]


def _vlm_timeout_seconds(cfg: dict[str, Any]) -> int:
    block = cfg.get("scan_ocr")
    if not isinstance(block, dict):
        return 120
    try:
        return max(5, min(600, int(block.get("vlm_timeout_seconds", 120))))
    except (TypeError, ValueError):
        return 120


def vlm_fill_empty_only(cfg: dict[str, Any]) -> bool:
    """
    When true (default), each VLM JSON merge only fills keys still empty in the working dict
    (including across multiple ROI passes for the same role).
    """
    block = cfg.get("scan_ocr")
    if not isinstance(block, dict):
        return True
    v = block.get("vlm_fill_empty_only", True)
    if v is False or str(v).strip().lower() in ("0", "false", "no"):
        return False
    return True


def _parse_vlm_json_stdout(stdout: str) -> dict[str, str]:
    s = (stdout or "").strip()
    if not s:
        return {}
    if "```" in s:
        for part in s.split("```"):
            p = part.strip()
            if p.lower().startswith("json"):
                p = p[4:].lstrip()
            if p.startswith("{") and "}" in p:
                s = p
                break
    if not s.startswith("{"):
        i = s.find("{")
        if i != -1:
            s = s[i:].strip()
    data = json.loads(s)
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for k in _VLM_JSON_KEYS:
        v = data.get(k)
        if v is None:
            continue
        s2 = str(v).strip()
        if s2:
            out[k] = s2
    return out


def merge_vlm_serial_fields(
    extracted: dict[str, str],
    vlm: dict[str, str],
    *,
    fill_empty_only: bool,
) -> dict[str, str]:
    out = dict(extracted)
    for k, vs in vlm.items():
        if k not in _VLM_JSON_KEYS:
            continue
        t = vs.strip()
        if not t:
            continue
        if fill_empty_only and (out.get(k) or "").strip():
            continue
        out[k] = t
    return out


def run_vlm_serial_extract(
    image_path: Path, cfg: dict[str, Any], *, role: str | None = None
) -> tuple[dict[str, str], str | None]:
    """
    Run ``scan_ocr.vlm_extract_command`` with ``{image}`` replaced by the given path (typically a
    temporary ROI crop file produced for each ``Scans/`` region).

    If ``role`` is set, ``{role}`` in each argv element is replaced (e.g. ``cart_front``) so
    wrappers can tailor prompts to the scan type.

    The process must print one JSON object on stdout with optional keys
    ``media_serial1``, ``media_serial2``, ``box_serial``, ``box_barcode``, ``pcb_serial``.
    """
    cmd = vlm_extract_command(cfg)
    if not cmd:
        return {}, None
    ip = str(image_path.resolve())
    argv: list[str] = []
    for x in cmd:
        if "{role}" in x and role is None:
            return (
                {},
                "vlm_extract_command contains {role} but no scan role was passed (internal error)",
            )
        s = x.replace("{image}", ip)
        if role is not None:
            s = s.replace("{role}", role)
        argv.append(s)
    timeout = _vlm_timeout_seconds(cfg)
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {}, f"vlm_extract_command timed out after {timeout}s"
    except OSError as e:
        return {}, str(e)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[:400]
        return {}, f"vlm_extract_command exit {proc.returncode}: {tail}"
    try:
        return _parse_vlm_json_stdout(proc.stdout or ""), None
    except json.JSONDecodeError as e:
        return {}, f"invalid JSON from vlm_extract_command: {e}"


def _vlm_fields_from_cropped_rois(
    path: Path,
    rois: list[tuple[float, float, float, float]],
    role: str,
    cfg: dict[str, Any],
) -> tuple[dict[str, str], str | None]:
    """
    Run ``vlm_extract_command`` once per prepared ROI crop (same preprocessing as ``--ocr-dump-crops``
    PNGs). ``{image}`` is each temp crop file in turn.
    """
    from PIL import Image

    combined: dict[str, str] = {}
    fill_empty = vlm_fill_empty_only(cfg)
    try:
        im = Image.open(path)
        im.load()
        if im.mode not in ("RGB", "L", "RGBA"):
            im = im.convert("RGB")
    except Exception as e:  # noqa: BLE001
        return {}, f"Pillow could not open image: {e}"

    for frac in rois:
        try:
            prepared = _prepare_roi_crop(im, frac)
        except Exception as e:  # noqa: BLE001
            return combined, f"ROI crop failed: {e}"

        fd, tmp = tempfile.mkstemp(suffix=".png", prefix="scan_ocr_vlm_")
        os.close(fd)
        tpath = Path(tmp)
        try:
            prepared.save(tpath)
            chunk, err = run_vlm_serial_extract(tpath, cfg, role=role)
            if err:
                return combined, err
            combined = merge_vlm_serial_fields(combined, chunk, fill_empty_only=fill_empty)
        finally:
            try:
                tpath.unlink(missing_ok=True)
            except OSError:
                pass

    return combined, None


def _debug_tag_for_unassigned_scan(p: Path) -> str:
    """Stable filename segment for debug dumps of scans not matched to a role."""
    safe = re.sub(r"[^\w\-.]+", "_", p.stem).strip("._-")
    if not safe:
        safe = "image"
    return f"scan_{safe[:72]}"


def write_ocr_debug_crops(debug_dir: Path, role: str, src: Path, rois: list[tuple[float, float, float, float]], raw: str) -> None:
    """Save per-ROI PNGs (same preprocessing as VLM crops) plus ``{role}_raw.txt`` (optional legacy text)."""
    from PIL import Image

    im = Image.open(src)
    im.load()
    if im.mode not in ("RGB", "L", "RGBA"):
        im = im.convert("RGB")
    for i, frac in enumerate(rois):
        prepared = _prepare_roi_crop(im, frac)
        base = f"{role}_r{i}"
        prepared.save(debug_dir / f"{base}.png")
        last_is_digit_only = (
            len(rois) > 1 and i == len(rois) - 1 and role not in ("cart_front", "cart_back")
        )
        (debug_dir / f"{base}_roi.txt").write_text(
            f"x0={frac[0]} x1={frac[1]} y0={frac[2]} y1={frac[3]}\nlast_roi_digit_only={'yes' if last_is_digit_only else 'no'}\n",
            encoding="utf-8",
        )
    (debug_dir / f"{role}_raw.txt").write_text(raw or "", encoding="utf-8", errors="replace")


def try_fill_serial_row_from_scans(
    release_dir: Path,
    serial_row: dict[str, str],
    cfg: dict[str, Any],
    *,
    dump_roi_crops: bool = False,
) -> list[str]:
    """
    Read serial hints from ``Scans/`` by **role** (insert spread, cart front, cart back),
    merge into serial fields (empty only), using field-specific role priority.

    Requires **``scan_ocr.vlm_extract_command``**: a vision helper argv list; each **``{image}``**
    is a temporary ROI crop (same preprocessing as ``--ocr-dump-crops``). See README.
    """
    scans = resolve_scans_dir(release_dir)
    if scans is None:
        return ["ocr_scans: no Scans folder (tried parent and release directory)"]
    raw_pics = list_scan_image_paths(scans)
    pics = [p for p in raw_pics if not scan_basename_ignored_for_scan_ocr(p.name, cfg)]
    if not raw_pics:
        return [f"ocr_scans: empty {scans.name}/"]
    if not pics:
        return [
            "ocr_scans: no images left after built-in reverse/inside skips and "
            f"scan_ocr.ignore_scan_patterns under {scans.name}/",
        ]

    vlm_argv = vlm_extract_command(cfg)
    if not vlm_argv:
        return [
            "ocr_scans: set scan_ocr.vlm_extract_command in your JSON (argv with {image} and optional {role}) — "
            "Scans/ serial reading uses a vision-model subprocess on ROI crops only; see README.",
        ]

    by_role: dict[str, dict[str, str]] = {}
    used_labels: list[str] = []
    errors: list[str] = []
    post_debug_hints: list[str] = []

    role_paths = discover_scan_paths_by_role(scans, cfg)
    debug_dir = release_dir / "_ocr_crop_debug"
    debug_dir_initialized = False
    debug_note: str | None = None
    for role in _SCAN_ROLES:
        path = role_paths.get(role)
        if path is None:
            continue
        rois = scan_ocr_rois_for_role(cfg, role)
        raw = ""
        ocr_exception: str | None = None
        vlm_fields: dict[str, str] = {}
        vlm_err: str | None = None
        try:
            vlm_fields, vlm_err = _vlm_fields_from_cropped_rois(path, rois, role, cfg)
            if vlm_err:
                errors.append(f"{role} ({path.name}) vlm: {vlm_err}")
        except ModuleNotFoundError as e:
            name = getattr(e, "name", "") or ""
            if name == "PIL" or name.startswith("PIL."):
                return [
                    "ocr_scans: install pillow for this interpreter "
                    f"(e.g. {sys.executable} -m pip install pillow)"
                ]
            errors.append(f"{role} ({path.name}): {e}")
            continue
        except ImportError as e:
            msg = str(e).lower()
            if "pillow" in msg or "pil" in msg:
                return [
                    "ocr_scans: install pillow for this interpreter "
                    f"(e.g. {sys.executable} -m pip install pillow)"
                ]
            errors.append(f"{role} ({path.name}): {e}")
            continue
        except Exception as e:  # noqa: BLE001
            ocr_exception = str(e)
            errors.append(f"{role} ({path.name}): {e}")

        if dump_roi_crops:
            try:
                if not debug_dir_initialized:
                    if debug_dir.exists():
                        shutil.rmtree(debug_dir)
                    debug_dir.mkdir(parents=True, exist_ok=True)
                    debug_dir_initialized = True
                write_ocr_debug_crops(debug_dir, role, path, rois, raw)
                debug_note = str(debug_dir.resolve())
            except Exception as de:  # noqa: BLE001
                errors.append(f"{role} ({path.name}) debug crops: {de}")
            else:
                if ocr_exception:
                    try:
                        (debug_dir / f"{role}_ocr_exception.txt").write_text(
                            ocr_exception, encoding="utf-8", errors="replace"
                        )
                    except OSError:
                        pass

        extracted = merge_vlm_serial_fields(
            {},
            vlm_fields,
            fill_empty_only=vlm_fill_empty_only(cfg),
        )
        if role in _PACKAGING_OCR_ROLES:
            extracted = {k: v for k, v in extracted.items() if k in ("box_serial", "box_barcode")}
        elif role == "cart_front":
            extracted = {k: v for k, v in extracted.items() if k in _CART_FRONT_EXTRACT_KEYS}
        elif role == "cart_back":
            extracted = {k: v for k, v in extracted.items() if k in _CART_BACK_EXTRACT_KEYS}
        if extracted:
            by_role[role] = extracted
        used_labels.append(f"{role}={path.name}")

    if dump_roi_crops and pics:
        assigned_resolved = {p.resolve() for p in role_paths.values() if p is not None}
        n_unassigned_dump = 0
        for pic in pics:
            if pic.resolve() in assigned_resolved:
                continue
            n_unassigned_dump += 1
            try:
                if not debug_dir_initialized:
                    if debug_dir.exists():
                        shutil.rmtree(debug_dir)
                    debug_dir.mkdir(parents=True, exist_ok=True)
                    debug_dir_initialized = True
                tag = _debug_tag_for_unassigned_scan(pic)
                write_ocr_debug_crops(debug_dir, tag, pic, [(0.0, 1.0, 0.0, 1.0)], "")
                debug_note = str(debug_dir.resolve())
            except Exception as de:  # noqa: BLE001
                errors.append(f"{pic.name} (extra debug crops): {de}")
        if n_unassigned_dump and (
            role_paths.get("cart_front") is None or role_paths.get("cart_back") is None
        ):
            post_debug_hints.append(
                "ocr_scans: some Scans/ files are not assigned to cart_front/cart_back — "
                "see scan_* crops (full frame); map them with scan_ocr.files or rename (*cart*front*, *cart*back*)."
            )

    dbg = f"ocr_scans: debug ROI crops → {debug_note}" if debug_note else None

    if errors and not by_role:
        return _prepend_ocr_debug_path(dbg, [*post_debug_hints, f"ocr_scans: failed — {'; '.join(errors)}"])

    combined = combine_extractions_by_field_priority(by_role)
    if not combined:
        hint = f" ({'; '.join(errors)})" if errors else ""
        return _prepend_ocr_debug_path(
            dbg,
            [
                *post_debug_hints,
                "ocr_scans: no serial patterns in assigned scan(s)"
                f" ({', '.join(used_labels) or 'no roles matched'}){hint}",
            ],
        )

    filled = merge_ocr_into_serial_row(serial_row, combined)
    summary = ", ".join(used_labels) if used_labels else "no files"
    if not filled:
        extra = f"; {'; '.join(errors)}" if errors else ""
        return _prepend_ocr_debug_path(
            dbg,
            [*post_debug_hints, f"ocr_scans: parsed [{summary}] but all target fields already set{extra}"],
        )
    err_tail = f"; warnings: {'; '.join(errors)}" if errors else ""
    return _prepend_ocr_debug_path(
        dbg,
        [*post_debug_hints, f"ocr_scans: filled {', '.join(filled)} from [{summary}]{err_tail}"],
    )


def try_fill_serial_row_from_scans_for_cli(
    release_dir: Path,
    serial_row: dict[str, str],
    cfg: dict[str, Any],
    args: Any,
) -> list[str]:
    if not ocr_scans_enabled(cfg, args):
        return []
    dump = ocr_dump_crops_requested(cfg, args)
    return try_fill_serial_row_from_scans(release_dir, serial_row, cfg, dump_roi_crops=dump)


def format_ocr_serial_snapshot_lines(
    serial_row: dict[str, str],
    version1_rev: str | None,
) -> list[str]:
    """Two-line summary of submission serial fields after scan merge (CLI when ``--ocr-scans``)."""

    def cell(key: str) -> str:
        t = (serial_row.get(key) or "").strip()
        return t if t else "(empty)"

    v1 = (version1_rev or "").strip()
    v1_s = v1 if v1 else "(empty)"
    return [
        "ocr_scans: media_serial1={}  media_serial2={}  box_serial={}  box_barcode={}".format(
            cell("media_serial1"),
            cell("media_serial2"),
            cell("box_serial"),
            cell("box_barcode"),
        ),
        "ocr_scans: pcb_serial={}  gameid2={}  version1={}".format(
            cell("pcb_serial"),
            cell("gameid2"),
            v1_s,
        ),
    ]

