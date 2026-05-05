"""
Shared prompts and post-processing for cart scan VLM helpers (SmolVLM, LM Studio, etc.).
"""

from __future__ import annotations

import json
import re
from typing import Any

_JSON_KEYS = ("media_serial1", "media_serial2", "box_serial", "box_barcode", "pcb_serial")

_LINE_KEY = re.compile(
    r"^(media_serial1|media_serial2|box_serial|box_barcode|pcb_serial)\s*:\s*(.*)$",
    re.IGNORECASE,
)

ROLE_ALLOWED: dict[str, frozenset[str]] = {
    "insert_spread": frozenset({"box_serial", "box_barcode"}),
    "cart_front": frozenset({"media_serial1"}),
    "cart_back": frozenset({"media_serial2", "pcb_serial"}),
}


# Whole-field shortcuts for pcb_serial (same semantics as ``config_serial.normalize_pcb_serial``).
_PCB_SERIAL_SHORTCUTS: dict[str, str] = {
    "@": "\u25bc",
    "$": "\u25bc 10",
}


def normalize_pcb_serial_vlm(raw: str | None) -> str:
    s = "" if raw is None else str(raw).strip()
    return _PCB_SERIAL_SHORTCUTS.get(s, s)


def normalize_media_serial2_vlm(raw: str | None) -> str:
    """
    Collapse stray spaces in the **printed / etched cart id** (twelve to sixteen alnums) and in
    hyphenated **TSA-HAC-…** lines.
    """
    s = (raw or "").strip()
    if not s:
        return ""
    u = s.upper()
    if "HAC-" in u:
        return re.sub(r"\s+", "", s).upper()
    compact = re.sub(r"\s+", "", s).upper()
    if 12 <= len(compact) <= 16 and re.fullmatch(r"[A-Z0-9]+", compact):
        return compact
    return s


def prompt_insert_spread_box_serial_only() -> str:
    """Insert crop: one model call focused only on **HAC-P-** retail line (reduces confusion with barcode)."""
    common = (
        "Return one JSON object only. It must list all five keys explicitly (never omit a key): "
        "media_serial1, media_serial2, box_serial, box_barcode, pcb_serial. "
        "Use \"\" for any key you must leave blank per the rules below.\n"
        "Copy only visible printed text from the image. No markdown. No text outside the JSON.\n"
    )
    return (
        common
        + "This image is a **retail insert** scan crop (may show barcode and catalog text).\n"
        + "**Ignore the barcode digits row for this task.**\n"
        + "**box_serial** — Find the printed **retail product code** above the barcode, starting with **HAC-P-** "
        + "then read **exactly five** more letters or digits "
        + "immediately after that second hyphen as **one** code (no spaces inside those five) \n "
        + "Do **not** use **TSA-HAC-** media lines.\n"
        + "Set media_serial1, media_serial2, box_barcode, and pcb_serial to \"\".\n"
        + "Output **one JSON object only** — no numbered lists, no markdown headings, no commentary.\n"
    )


def prompt_insert_spread_box_barcode_only() -> str:
    """Insert crop: second model call focused only on the retail barcode."""
    common = (
        "Return one JSON object only. It must list all five keys explicitly (never omit a key): "
        "media_serial1, media_serial2, box_serial, box_barcode, pcb_serial. "
        "Use \"\" for any key you must leave blank per the rules below.\n"
        "Copy only visible printed text from the image. No markdown. No text outside the JSON.\n"
    )
    return (
        common
        + "This image is a **retail insert** scan crop.\n"
        + "**box_barcode** — Read the numbers below the retail **barcode**\n"
        + "Often printed with spaces between digit groups, like **1 22222 33333 4**; **keep spaces**, and remember to include the control check digit. \n"
        + "Set media_serial1, media_serial2, box_serial, and pcb_serial to \"\".\n"
        + "Output **one JSON object only** — no numbered lists, no markdown headings, no commentary.\n"
    )


def prompt_for_role(role: str | None) -> str:
    """Narrow the task so a tiny model does not copy one stamp into every JSON key."""
    common = (
        "Return one JSON object only. It must list all five keys explicitly (never omit a key): "
        "media_serial1, media_serial2, box_serial, box_barcode, pcb_serial. "
        "Use \"\" for any key you must leave blank per the rules below.\n"
        "Copy only visible printed text from the image. No markdown. No text outside the JSON.\n"
    )
    if role == "cart_front":
        return (
            common
            + "This image is a **cartridge front** stamp crop.\n"
            + "Fill **only** media_serial1: the small line that starts with **L** then **A** then **-H-** "
            + "(two letters **LA** before the first hyphen — not **L-H-**). Read that stamp line "
            + "character by character from the image.\n"
            + "Set media_serial2, box_serial, box_barcode, and pcb_serial to empty strings \"\" "
            + "(those codes are not on this face).\n"
        )
    if role == "cart_back":
        return (
            common
            + "This image is the **back of a Nintendo Switch game cartridge** (black plastic shell).\n"
            + "Fill **only**:\n"
            + "- **media_serial2**: the **main product serial** on the flat plastic: one line of "
            + "**twelve to sixteen** letters and digits (**A–Z**, **0–9**), usually **printed** in "
            + "light ink (tiny gaps between characters are normal — output **one token with no spaces**). "
            + "**Do not** use the **embossed** ``HAC-008`` / ``CE`` moulding — that is a **model** "
            + "mark, **not** media_serial2.\n"
            + "- **pcb_serial**: marks **on the green/gold PCB** visible **through the vertical slots** "
            + "above the contacts: a small **downward triangle** (Unicode **▼**, U+25BC) and/or "
            + "digits printed on the board (e.g. **10** in another slot); write **▼ 10** when both "
            + "apply. **V**/**Y** may stand in for **▼**. Use **@** for bare triangle only or **$** "
            + "for **▼ 10** if you cannot type **▼**. Use **\"\"** if no PCB mark is visible.\n"
            + "Set media_serial1, box_serial, and box_barcode to empty strings **\"\"**.\n"
        )
    if role == "insert_spread":
        # LM Studio / SmolVLM use **two** separate prompts per insert image (see those scripts).
        return prompt_insert_spread_box_serial_only()
    return (
        common
        + "Identify which Nintendo Switch codes appear in the photo and fill only matching keys; "
        + "leave unrelated keys as \"\".\n"
        + "media_serial1: stamp starting with **LA-H-** (letter L then letter A). "
        + "media_serial2: printed/etched cart id (twelve to sixteen alnums) or TSA-HAC-… line; "
        + "box_serial: **HAC-P-** plus **five** alphanumerics read strictly left-to-right (avoid transposing). "
        + "box_barcode: the numbers from the barcode. pcb_serial: triangle mark ± digits.\n"
    )


def scrub_instruction_echo(d: dict[str, str]) -> dict[str, str]:
    """Drop values that are clearly echoed instructions, not image text."""
    out = dict(d)
    for k, v in list(out.items()):
        if not v or not isinstance(v, str):
            continue
        vl = v.lower()
        # Models copy "12–16" / "12-16" (length hint) into media_serial2; normalize Unicode dashes.
        vd = re.sub(r"[\u2013\u2014–—]", "-", vl)
        vd = re.sub(r"\s+", " ", vd.strip())
        if re.fullmatch(r"12-16(\s*characters?|\s*chars?)?\.?", vd):
            out[k] = ""
            continue
        if k == "media_serial2" and re.fullmatch(r"HAC-\d{3}", v.strip(), flags=re.IGNORECASE):
            out[k] = ""
            continue
        if any(
            p in vl
            for p in (
                "12-16 character",
                "laser-etched",
                "five alphanumeric",
                "hyphen-separated",
                "three-letter region",
            )
        ):
            out[k] = ""
            continue
        if re.fullmatch(r"HAC-P-ABCDE", v, flags=re.IGNORECASE):
            out[k] = ""
        if re.fullmatch(r"TSA-HAC-ABCDE-UKV", v, flags=re.IGNORECASE):
            out[k] = ""
    return out


def enforce_role_keys(d: dict[str, str], role: str | None) -> dict[str, str]:
    if not role or role not in ROLE_ALLOWED:
        return d
    allowed = ROLE_ALLOWED[role]
    out = dict(d)
    for k in _JSON_KEYS:
        if k not in allowed:
            out[k] = ""
    return out


def repair_cart_front_la_h_prefix(media_serial1: str) -> str:
    """
    Models often output **L-H-…** instead of **LA-H-…** on the small stamp (the **A** is dropped).
    ``L-H-`` is not a valid ``L[letter]-H-`` prefix for these stamps; insert the missing **A**
    only in this case (``LB-H-`` etc. do not start with ``L-H-``).
    """
    s = (media_serial1 or "").strip()
    if len(s) < 4:
        return s
    if s.upper().startswith("L-H-") and not s.upper().startswith("LA-H-"):
        return "LA-H-" + s[4:]
    return s


def strip_json_blob(text: str) -> str:
    s = (text or "").strip()
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
    return s


def empty_payload() -> dict[str, str]:
    return {k: "" for k in _JSON_KEYS}


def normalize_keys(data: dict[Any, Any]) -> dict[str, str]:
    out = empty_payload()
    for k in _JSON_KEYS:
        v = data.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            out[k] = s
    return out


_RE_INSERT_HAC_P = re.compile(r"\bHAC-P-[A-Z0-9]{4,5}\b", re.IGNORECASE)
# Same semantics as submission OCR: retail id is **HAC-P-** plus **five** alphanumerics; reject
# ``…-HAC-P-`` inside ``TSA-HAC-P-…`` / ``LA-HAC-P-…`` style media strings.
_RE_BOX_STRICT = re.compile(r"\bHAC-P-[A-Z0-9]{5}\b", re.IGNORECASE)
_RE_BOX_SPACED = re.compile(
    r"(?<![A-Za-z0-9])H\s*A\s*C\s*-\s*P\s*-\s*([A-Za-z0-9]{5})(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_RE_BOX_NO_C_HYPH = re.compile(
    r"(?<![A-Za-z0-9])H\s*A\s*C\s*P\s*-\s*([A-Za-z0-9]{5})(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_RE_MEDIA_PREFIX_HAC_P = re.compile(r"\b[A-Z]{2,3}-HAC-P-", re.IGNORECASE)


def _normalize_hyphens_for_box_scan(text: str) -> str:
    s = text or ""
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


def extract_box_serial_from_free_text(text: str) -> str | None:
    """
    Pull **HAC-P-** + five alphanumerics from arbitrary model output (JSON, prose, numbered lists).

    Mirrors the submission tool's OCR ``find_box_serial_in_ocr_text`` rules (strict token,
    spaced letters, missing **C-** hyphen) and rejects ``XXX-HAC-P-`` overlaps.
    """
    t = _normalize_hyphens_for_box_scan(text)
    for m in _RE_BOX_STRICT.finditer(t):
        if _flex_hac_p_overlaps_media_prefix(t, m):
            continue
        return m.group(0).upper()
    for rx in (_RE_BOX_SPACED, _RE_BOX_NO_C_HYPH):
        for m in rx.finditer(t):
            if _flex_hac_p_overlaps_media_prefix(t, m):
                continue
            suf = m.group(1).upper()
            if re.fullmatch(r"[A-Z0-9]{5}", suf):
                return f"HAC-P-{suf}"
    return None


def valid_box_serial_strict(s: str) -> bool:
    return bool(re.fullmatch(r"HAC-P-[A-Z0-9]{5}", (s or "").strip().upper()))


def parse_insert_spread_prose(text: str) -> dict[str, Any] | None:
    """
    VLMs sometimes answer insert crops with prose or numbered lists instead of JSON. Extract
    ``HAC-P-`` + five alphanumerics when possible, else four–five legacy match, and the first
    twelve-digit barcode run.
    """
    if not (text or "").strip():
        return None
    raw = _normalize_hyphens_for_box_scan(text)
    out: dict[str, Any] = dict(empty_payload())
    strict = extract_box_serial_from_free_text(raw)
    if strict:
        out["box_serial"] = strict
    else:
        for m in _RE_INSERT_HAC_P.finditer(raw):
            if _flex_hac_p_overlaps_media_prefix(raw, m):
                continue
            out["box_serial"] = m.group(0).upper()
            break
    for line in raw.splitlines():
        low = line.lower()
        if "barcode" not in low:
            continue
        if not re.search(r"barcode\s*:", low):
            continue
        tail = line.split(":", 1)[-1]
        digits = "".join(ch for ch in tail if ch.isdigit())
        if len(digits) >= 12:
            out["box_barcode"] = digits[:12]
            break
    if not out.get("box_barcode"):
        for line in raw.splitlines():
            digits = "".join(ch for ch in line if ch.isdigit())
            if len(digits) == 12:
                out["box_barcode"] = digits
                break
    if not out.get("box_serial") and not out.get("box_barcode"):
        return None
    return out


def parse_relaxed_key_line_format(text: str) -> dict[str, Any] | None:
    """
    Some VLMs (e.g. SmolVLM2 in LM Studio) answer with labeled lines instead of JSON::

        media_serial1: LA-H-AT5VA-EUR

        media_serial2: empty string ""

    Map those into the same dict shape as ``json.loads`` would produce. Returns ``None`` if no
    recognized keys were found.
    """
    out: dict[str, Any] = {}
    n = 0
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        m = _LINE_KEY.match(line)
        if not m:
            continue
        raw_key = m.group(1).lower()
        canon = next((k for k in _JSON_KEYS if k.lower() == raw_key), None)
        if canon is None:
            continue
        val = (m.group(2) or "").strip()
        vl = val.lower()
        if not val or "empty string" in vl or vl in ('""', "''", "empty", "n/a", "none", "null"):
            out[canon] = ""
        elif (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            out[canon] = val[1:-1].strip()
        else:
            out[canon] = val
        n += 1
    if n == 0:
        return None
    return out


def postprocess_vlm_dict(
    data: dict[Any, Any], role: str | None, *, raw_fallback: str | None = None
) -> dict[str, str]:
    if not isinstance(data, dict):
        raise ValueError("model output JSON was not an object")
    out = normalize_keys(data)
    out = scrub_instruction_echo(out)
    out = enforce_role_keys(out, role)
    if role == "cart_front":
        out["media_serial1"] = repair_cart_front_la_h_prefix(out.get("media_serial1", ""))
    elif role == "cart_back":
        out["media_serial2"] = normalize_media_serial2_vlm(out.get("media_serial2", ""))
        out["pcb_serial"] = normalize_pcb_serial_vlm(out.get("pcb_serial", ""))
    elif role == "insert_spread":
        blob = raw_fallback or ""
        bs = (out.get("box_serial") or "").strip()
        found = extract_box_serial_from_free_text(blob) or extract_box_serial_from_free_text(bs)
        if found and valid_box_serial_strict(found):
            if not valid_box_serial_strict(bs) or found.upper() != bs.upper():
                out["box_serial"] = found
    return out


def merge_insert_spread_vlm_passes(
    serial_out: dict[str, str],
    barcode_out: dict[str, str],
    *,
    raw_serial: str,
    raw_barcode: str,
) -> dict[str, str]:
    """Combine **box_serial** from the first insert call and **box_barcode** from the second."""
    merged = empty_payload()
    merged["box_serial"] = (serial_out.get("box_serial") or "").strip()
    merged["box_barcode"] = (barcode_out.get("box_barcode") or "").strip()
    return postprocess_vlm_dict(
        merged, "insert_spread", raw_fallback=f"{raw_serial}\n{raw_barcode}"
    )


def parse_and_postprocess_vlm_text(raw: str, role: str | None) -> dict[str, str]:
    blob = strip_json_blob(raw)
    try:
        data: dict[Any, Any] = json.loads(blob)
    except json.JSONDecodeError:
        relaxed = parse_relaxed_key_line_format(blob)
        if relaxed is not None:
            data = relaxed
        elif role == "insert_spread":
            prose = parse_insert_spread_prose(blob)
            if prose is None:
                raise
            data = prose
        else:
            raise
    return postprocess_vlm_dict(data, role, raw_fallback=raw)
