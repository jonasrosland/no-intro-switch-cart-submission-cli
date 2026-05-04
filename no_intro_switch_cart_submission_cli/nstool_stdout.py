"""Parse jakcron NSTool stdout (CUP, TitleId, application strings)."""
from __future__ import annotations

import re

from no_intro_switch_cart_submission_cli.constants import DUMP_FILE_RE
from no_intro_switch_cart_submission_cli.meta_net import (
    _is_switch_retail_application_title_id,
    parse_meta_net_from_nstools,
)


# CUP: "CUP TitleId:" with or without 0x prefix.
def parse_cup_metadata(stdout: str) -> dict | None:
    m = re.search(r"CUP TitleId:\s*(?:0x)?([0-9a-fA-F]{16})", stdout, re.I | re.MULTILINE)
    if not m:
        return None
    tid = m.group(1).upper()
    display_version = ""
    # NSTool: "CUP Version: <semver-ish> (v<decimal>)"
    m_n = re.search(r"CUP Version:\s*(\S+)\s*\(v(\d+)\)", stdout)
    if m_n:
        dv = m_n.group(1).strip()
        display_version = dv if dv.startswith("v") else f"v{dv}"
    else:
        # Alternate: "CUP Version vA.B.C-D"
        m_h = re.search(r"CUP Version v(\d+)\.(\d+)\.(\d+)-(\d+)", stdout)
        if m_h:
            display_version = f"v{m_h.group(1)}.{m_h.group(2)}.{m_h.group(3)}"
    return {"cup_title_id": tid, "display_version": display_version}


def _jakcron_title_id_near_marker(stdout: str, marker: str, window: int = 24576) -> str | None:
    low = stdout.casefold()
    mpos = low.find(marker.casefold())
    if mpos < 0:
        return None
    chunk = stdout[mpos : mpos + window]
    m = re.search(r"\bTitleId\s*[:#]\s*(?:0x)?([0-9a-fA-F]{16})\b", chunk, re.I)
    if not m:
        return None
    return m.group(1).upper()


def jakcron_pick_application_title_id(stdout: str, cup: dict | None) -> str | None:
    # Prefer retail 0100… from CUP or Application Extended Header; ignore arbitrary 16-hex TitleIds.
    if cup and cup.get("cup_title_id"):
        ct = str(cup["cup_title_id"]).upper()
        if _is_switch_retail_application_title_id(ct):
            return ct

    for marker in (
        "ApplicationExtendedHeader",
        "APPLICATION_META_EXTENDED_HEADER",
        "Application Meta Extended Header",
    ):
        tid = _jakcron_title_id_near_marker(stdout, marker)
        if tid and _is_switch_retail_application_title_id(tid):
            return tid

    line_patterns = (
        r"\bTitleId\s*[:#]\s*(?:0x)?([0-9a-fA-F]{16})\b",
        r"\bApplicationId\s*[:#]\s*(?:0x)?([0-9a-fA-F]{16})\b",
        r"\bProgramID\s*[:#]\s*(?:0x)?([0-9a-fA-F]{16})\b",
        r"\bPackageId\s*[:#]\s*(?:0x)?([0-9a-fA-F]{16})\b",
        r"(?:Title|Application)\s+(?:Id|ID)\s*[:#]\s*(?:0x)?([0-9a-fA-F]{16})\b",
    )
    positioned: list[tuple[int, str]] = []
    for pat in line_patterns:
        for m in re.finditer(pat, stdout, re.I | re.MULTILINE):
            positioned.append((m.start(), m.group(1).upper()))
    positioned.sort(key=lambda x: x[0])

    for _, t in positioned:
        if _is_switch_retail_application_title_id(t):
            return t

    m = re.search(r"\b(0100[0-9a-fA-F]{12})\b", stdout)
    if m:
        return m.group(1).upper()

    return None


def _retail_title_id_from_dump_filename(basename: str | None) -> str | None:
    # Default.xci name [0100…][v…] when NSTool output is ambiguous.
    if not basename:
        return None
    m = DUMP_FILE_RE.match(basename)
    if not m:
        return None
    tid = m.group("tid").upper()
    return tid if _is_switch_retail_application_title_id(tid) else None


def parse_jakcron_nstool_application_meta(
    stdout: str,
    filename_version_token: str,
    *,
    default_xci_basename: str | None = None,
) -> dict | None:
    cup = parse_cup_metadata(stdout)
    display_version = ""
    if cup and cup.get("cup_title_id"):
        display_version = str(cup.get("display_version") or "").strip()
    if not display_version:
        m_dv = re.search(
            r"^\s*DisplayVersion\s*:\s*(.+?)\s*$", stdout, re.I | re.MULTILINE
        )
        if m_dv:
            dv_raw = m_dv.group(1).strip()
            if dv_raw and dv_raw != "(NotSet)":
                display_version = dv_raw

    tid = jakcron_pick_application_title_id(stdout, cup)
    fn_tid = _retail_title_id_from_dump_filename(default_xci_basename)
    if fn_tid:
        if not tid or not _is_switch_retail_application_title_id(tid):
            tid = fn_tid

    if not tid:
        return None

    primary = ""
    for pat in (
        r"(?:English|American)\s+Title\s*[:#]\s*(.+?)(?:\r?\n|$)",
        r"Application\s+Name\s*[:#]\s*(.+?)(?:\r?\n|$)",
        r"Title\s+Name\s*[:#]\s*(.+?)(?:\r?\n|$)",
        r"(?:Icon\s+-\s*)(.+?)(?:\r?\n|$)",
    ):
        m = re.search(pat, stdout, re.I | re.MULTILINE)
        if m:
            primary = m.group(1).strip()
            if primary:
                break

    langs: list[str] = []
    m = re.search(r"Supported\s+Languages?\s*[:#]\s*(.+?)(?:\r?\n|$)", stdout, re.I)
    if m:
        langs = [x.strip() for x in re.split(r"[,;/]", m.group(1)) if x.strip()]

    return parse_meta_net_from_nstools(
        title_id=tid,
        filename_version_token=filename_version_token or "",
        primary_title=primary,
        display_version_nacp=display_version,
        languages=langs,
    )
