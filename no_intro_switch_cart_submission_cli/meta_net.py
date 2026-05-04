"""NACP → merged meta-net dict shape used by submission XML."""
from __future__ import annotations

from no_intro_switch_cart_submission_cli.constants import NACP_INDEX_TO_LANG

def _meta_dict_from_nacp_bytes(
    raw_nacp: bytes,
    *,
    title_id: str,
    filename_version_token: str,
) -> dict | None:
    try:
        from nstools.Fs.File import MemoryFile
        from nstools.Fs.Nacp import Nacp
    except ImportError:
        return None
    nacp = Nacp()
    try:
        nacp.open(MemoryFile(raw_nacp), "rb")
    except BaseException:
        return None
    primary = ""
    for idx in (0, 1):
        primary = nacp.getName(idx).strip()
        if primary:
            break
    if not primary:
        for idx in range(15):
            primary = nacp.getName(idx).strip()
            if primary:
                break
    dv = nacp.getDisplayVersion().strip()
    langs: list[str] = []
    for idx in range(15):
        if nacp.getName(idx).strip():
            tag = NACP_INDEX_TO_LANG.get(idx)
            if tag:
                langs.append(tag)
    return parse_meta_net_from_nstools(
        title_id=title_id,
        filename_version_token=filename_version_token,
        primary_title=primary,
        display_version_nacp=dv,
        languages=langs,
    )


def parse_meta_net_from_nstools(
    *,
    title_id: str,
    filename_version_token: str,
    primary_title: str,
    display_version_nacp: str,
    languages: list[str],
) -> dict:
    tid = title_id.upper()
    dv = display_version_nacp.strip()
    if dv.startswith("v"):
        dv = dv[1:]
    ver_str = "v" + dv if dv else ""
    upd_str = filename_version_token
    utid = f"{int(tid, 16) | 0x800:016X}"
    return {
        "base_title_ids": [tid],
        "update_title_ids": [utid],
        "updates": [upd_str],
        "versions": [ver_str],
        "titles": [primary_title],
        "languages": sorted(set(languages)),
    }


def _is_switch_retail_application_title_id(tid: str) -> bool:
    t = (tid or "").strip().upper()
    return len(t) == 16 and t.startswith("0100")


def merge_meta_net_with_nacp_overlay(base: dict | None, nacp: dict) -> dict:
    if not base:
        return dict(nacp)
    out = dict(base)
    bt_b = (base.get("base_title_ids") or [""])[0]
    if _is_switch_retail_application_title_id(str(bt_b)):
        tid = str(bt_b).upper()
        out["base_title_ids"] = [tid]
        out["update_title_ids"] = [f"{int(tid, 16) | 0x800:016X}"]
    else:
        bt_n = (nacp.get("base_title_ids") or [""])[0]
        if _is_switch_retail_application_title_id(str(bt_n)):
            out["base_title_ids"] = list(nacp["base_title_ids"])
            out["update_title_ids"] = list(nacp["update_title_ids"])

    if any(str(t).strip() for t in (nacp.get("titles") or [])):
        out["titles"] = list(nacp["titles"])
    if nacp.get("languages"):
        out["languages"] = list(nacp["languages"])

    bv = str((base.get("versions") or [""])[0]).strip()
    nv = str((nacp.get("versions") or [""])[0]).strip()
    if nv and (not bv or not base.get("versions")):
        out["versions"] = list(nacp["versions"])

    bu = str((base.get("updates") or [""])[0]).strip()
    if bu:
        out["updates"] = list(base["updates"])
    elif nacp.get("updates"):
        out["updates"] = list(nacp["updates"])
    return out

