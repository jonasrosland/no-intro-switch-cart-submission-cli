"""jakcron extract + PyPI nstools helpers (Control spill, loose RomFS NACP, Nacp parse)."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from no_intro_switch_cart_submission_cli.constants import (
    DUMP_FILE_RE,
    MAX_CONTROL_NCA_BYTES_BUFFERED_FROM_XCI,
)
from no_intro_switch_cart_submission_cli.jakcron_subproc import (
    find_control_nacp_under_extract_root,
    run_nstool_nca_partition_extract,
    run_nstool_secure_extract,
)
from no_intro_switch_cart_submission_cli.meta_net import (
    _meta_dict_from_nacp_bytes,
    merge_meta_net_with_nacp_overlay,
)
from no_intro_switch_cart_submission_cli.paths import config_path_base, resolve_path, _jakcron_tempdir_kwargs
from no_intro_switch_cart_submission_cli.romfs_control import _extract_raw_control_nacp_from_nca
from no_intro_switch_cart_submission_cli.nstool_stdout import _retail_title_id_from_dump_filename
from no_intro_switch_cart_submission_cli import nstools_keys as nk


def _read_secure_nca_blob(src: Any, max_bytes: int) -> bytes | None:
    try:
        src.rewind()
    except BaseException:
        pass
    chunks: list[bytes] = []
    total = 0
    chunk_sz = 8 * 1024 * 1024
    try:
        while total < max_bytes:
            want = min(chunk_sz, max_bytes - total)
            block = src.read(want)
            if not block:
                break
            chunks.append(block)
            total += len(block)
            if len(block) < want:
                break
    except BaseException:
        return None
    if not chunks:
        return None
    return b"".join(chunks)


def _spill_secure_control_ncas_to_dir(
    out_dir: Path,
    default_xci: Path,
    prod_keys: Path | None,
    cfg: dict | None,
) -> tuple[int, str]:
    # Copy Control-type secure/*.nca only (small); skip Program/Data/Meta for --partN.
    try:
        from nstools.Fs.File import MemoryFile
        from nstools.Fs.Nca import Nca
        from nstools.Fs.Type import Content
        from nstools.Fs.Xci import Xci
    except ImportError:
        return 0, "PyPI nstools not installed"

    if not nk._load_nstools_keys(prod_keys):
        return 0, "could not load encryption keys (prod.keys)"

    nk._nstools_merge_title_keys_files(cfg if cfg is not None else {}, config_path_base(cfg))
    nk._nstools_set_quiet()

    try:
        xci = Xci(str(default_xci))
        nk._nstools_merge_titles_from_xci_tickets(xci)
        secure_hfs0 = None
        for part in getattr(xci.hfs0, "files", []) or []:
            if getattr(part, "_path", None) == "secure":
                secure_hfs0 = part
                break
        if secure_hfs0 is None:
            return 0, "no secure partition in XCI"
    except BaseException as e:
        return 0, f"nstools XCI open failed ({e})"

    cnmt_hints = _cnmt_control_nca_id_hints(secure_hfs0)
    nk._nstools_propagate_title_keys_patch_slots()
    nk._nstools_bridge_filename_tid_to_patch_slot(default_xci)

    def cnmt_rank(path_s: str) -> tuple[int, str]:
        pl = path_s.lower()
        stem_l = Path(pl).stem.lower()
        for hid in cnmt_hints:
            h = hid.lower()
            if len(h) >= 16 and (stem_l.startswith(h[:16]) or h[:16] in stem_l):
                return (0, path_s)
        return (1, path_s)

    candidates: list[tuple[tuple[int, str], str, bytes]] = []
    for child in getattr(secure_hfs0, "files", []) or []:
        path_s = str(getattr(child, "_path", "") or "")
        if not path_s.lower().endswith(".nca"):
            continue
        blob = _read_secure_nca_blob(child, MAX_CONTROL_NCA_BYTES_BUFFERED_FROM_XCI)
        if not blob:
            continue
        nca = Nca()
        try:
            nca.open(MemoryFile(blob))
        except BaseException:
            continue
        if not nca.header or nca.header.contentType != Content.CONTROL:
            continue
        candidates.append((cnmt_rank(path_s), path_s, blob))

    candidates.sort(key=lambda t: t[0])
    for i, (_rk, path_s, blob) in enumerate(candidates):
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in Path(path_s).name)[:120]
        out_path = out_dir / f"{i:03d}_{safe}.nca"
        try:
            out_path.write_bytes(blob)
        except OSError as e:
            return i, str(e)

    return len(candidates), ""


def extract_metadata_nacp_from_xci_via_jakcron_control_parts(
    nstool_bin: Path,
    prod_keys: Path | None,
    default_xci: Path,
    filename_version_token: str,
    cfg: dict | None,
) -> tuple[dict | None, str]:
    # jakcron --part0..3 on Control NCAs spilled from secure (no full --secure).
    if not nstool_bin.is_file():
        return None, "nstool binary missing"
    with tempfile.TemporaryDirectory(**_jakcron_tempdir_kwargs("nacp_xci_ctl_", cfg)) as td:
        td_path = Path(td)
        n_spilled, spill_err = _spill_secure_control_ncas_to_dir(td_path, default_xci, prod_keys, cfg)
        if n_spilled <= 0:
            return None, spill_err or "no Control NCAs in secure partition"
        return extract_metadata_via_jakcron_nca_partition_walk(
            td_path,
            nstool_bin,
            prod_keys,
            default_xci,
            filename_version_token or "",
            cfg,
        )


def _extract_nacp_from_loose_nca_disk_paths(
    sources: list[tuple[str, Path]],
    cnmt_hints: list[str],
    filename_v: str,
) -> tuple[dict | None, str]:
    # Loose Control NCAs on disk (jakcron extract paths).
    try:
        from nstools.Fs.File import File
        from nstools.Fs.Nca import Nca
        from nstools.Fs.Type import Content
    except ImportError:
        return None, "PyPI nstools not installed"

    def source_rank(t: tuple[str, Path]) -> tuple[int, str]:
        name = t[0].lower()
        stem = Path(name).stem.lower()
        for hid in cnmt_hints:
            h = hid.lower()
            if len(h) >= 16 and (stem.startswith(h[:16]) or h[:16] in stem):
                return (0, name)
        return (1, name)

    ranked = sorted(sources, key=source_rank)
    saw_candidate_nca = False
    nca_decrypt_failed = False
    decrypt_fail_hint = ""

    for _label, path in ranked:
        nca = Nca()
        try:
            nca.open(File(str(path), "rb"))
        except BaseException:
            continue
        if not nca.header:
            continue
        if nca.header.contentType != Content.CONTROL:
            continue
        saw_candidate_nca = True
        key_ok = getattr(nca.header, "keyStatus", False) is True
        if not key_ok:
            nk._nstools_alias_title_key_rights_to_app(nca.header)
            nca = Nca()
            try:
                nca.open(File(str(path), "rb"))
            except BaseException:
                nca_decrypt_failed = True
                hdr = getattr(nca, "header", None)
                if hdr:
                    decrypt_fail_hint = nk._nstools_decrypt_fail_hint(hdr)
                continue
            key_ok = getattr(nca.header, "keyStatus", False) is True
        if not key_ok:
            nca_decrypt_failed = True
            if nca.header:
                decrypt_fail_hint = nk._nstools_decrypt_fail_hint(nca.header)
            continue

        raw_nacp = _extract_raw_control_nacp_from_nca(nca)
        if raw_nacp and len(raw_nacp) >= 0x80:
            meta = _meta_dict_from_nacp_bytes(
                raw_nacp,
                title_id=str(nca.header.titleId).upper(),
                filename_version_token=filename_v or "",
            )
            if meta:
                return meta, ""

    where = "extracted .nca on disk"
    tree = "under extracted secure tree"
    if nca_decrypt_failed:
        msg = f"{where} could not be decrypted for NACP (title keys / prod.keys)"
        if decrypt_fail_hint:
            msg += f" — {decrypt_fail_hint}"
        return None, msg
    if not saw_candidate_nca:
        return None, f"no Control-type NCA opened {tree}"
    return None, "no control.nacp inside Control NCAs (RomFS control/ or PFS0)"


def extract_metadata_via_jakcron_secure_nacp(
    nstool_bin: Path,
    prod_keys: Path | None,
    default_xci: Path,
    filename_version_token: str,
    cfg: dict | None = None,
) -> tuple[dict | None, str]:
    # Prefer Control --part on spilled NCAs; else --secure tree, loose NCAs, then per-NCA --part.
    try:
        fn_tid = _retail_title_id_from_dump_filename(default_xci.name)
        tid_arg = fn_tid if fn_tid else "0100000000000000"

        ctl_meta, ctl_err = extract_metadata_nacp_from_xci_via_jakcron_control_parts(
            nstool_bin, prod_keys, default_xci, filename_version_token or "", cfg
        )
        if ctl_meta:
            return ctl_meta, ""

        if ctl_err:
            print(
                f"  info: NACP: jakcron Control --part ({ctl_err}); falling back to jakcron --secure extract",
                file=sys.stderr,
            )

        with tempfile.TemporaryDirectory(**_jakcron_tempdir_kwargs("nst_secure_", cfg)) as td:
            td_path = Path(td)
            rc, log = run_nstool_secure_extract(nstool_bin, prod_keys, default_xci, td_path)
            if rc != 0:
                tail = (log or "").strip()
                tail = tail[-1200:] if len(tail) > 1200 else tail
                return None, f"jakcron secure extract failed (exit {rc})" + (f": {tail}" if tail else "")

            nacp_path = find_control_nacp_under_extract_root(td_path)
            if nacp_path is not None:
                raw = nacp_path.read_bytes()
                if len(raw) >= 0x80:
                    meta = _meta_dict_from_nacp_bytes(
                        raw,
                        title_id=tid_arg,
                        filename_version_token=filename_version_token or "",
                    )
                    if meta:
                        return meta, ""

            meta_nca, err_nca = extract_metadata_nacp_from_loose_nca_files(
                td_path, default_xci, prod_keys, cfg
            )
            if meta_nca:
                return meta_nca, ""

            meta_part, err_part = extract_metadata_via_jakcron_nca_partition_walk(
                td_path,
                nstool_bin,
                prod_keys,
                default_xci,
                filename_version_token or "",
                cfg,
            )
            if meta_part:
                return meta_part, ""

            parts = []
            if nacp_path is None:
                parts.append("no loose control.nacp file next to extracted .nca blobs")
            else:
                parts.append("loose control.nacp present but parse failed")
            if err_nca:
                parts.append(err_nca)
            if err_part:
                parts.append(err_part)
            return None, "; ".join(parts)
    except subprocess.TimeoutExpired:
        return None, "jakcron secure extract timed out"
    except OSError as e:
        return None, str(e)


def needs_nacp_enrichment(meta: dict | None) -> bool:
    if not meta:
        return True
    no_titles = not any(str(t).strip() for t in (meta.get("titles") or []))
    no_lang = not (meta.get("languages") or [])
    no_ver = not str((meta.get("versions") or [""])[0]).strip()
    return no_titles or no_lang or no_ver


def enrich_meta_net_with_jakcron_secure_nacp(
    meta_net: dict | None,
    *,
    nstool_bin: Path | None,
    prod_keys: Path | None,
    default_xci: Path,
    cfg: dict,
) -> dict | None:
    if not nstool_bin or not nstool_bin.is_file():
        return meta_net
    if prod_keys is not None and not prod_keys.is_file():
        return meta_net

    if not needs_nacp_enrichment(meta_net):
        return meta_net

    mf = DUMP_FILE_RE.match(default_xci.name)
    v_tok = mf.group("vnum") if mf else ""
    nacp_meta, err = extract_metadata_via_jakcron_secure_nacp(
        nstool_bin, prod_keys, default_xci, v_tok or "", cfg
    )
    if nacp_meta:
        merged = merge_meta_net_with_nacp_overlay(meta_net, nacp_meta)
        return merged
    if err:
        print(f"  warn: NACP enrichment: {err}", file=sys.stderr)
    return meta_net


def _cnmt_control_nca_id_hints(secure_hfs0: object) -> list[str]:
    # Control ncaIds from Meta/CNMT entries — rank which spilled NCAs to try first.
    hints: list[str] = []
    try:
        from nstools.Fs.Cnmt import Cnmt
        from nstools.Fs.File import MemoryFile
        from nstools.Fs.Nca import Nca
        from nstools.Fs.Type import Content, Fs as FsType
    except ImportError:
        return hints

    for child in getattr(secure_hfs0, "files", []) or []:
        path_s = str(getattr(child, "_path", "") or "")
        if not path_s.lower().endswith(".nca"):
            continue
        nca = Nca()
        try:
            nca.open(child)
        except BaseException:
            continue
        if not nca.header or nca.header.contentType != Content.META:
            continue
        key_ok = getattr(nca.header, "keyStatus", False) is True
        if not key_ok:
            nk._nstools_alias_title_key_rights_to_app(nca.header)
            nca = Nca()
            try:
                nca.open(child)
            except BaseException:
                continue
            key_ok = getattr(nca.header, "keyStatus", False) is True
        if not key_ok:
            continue
        for fs in getattr(nca, "sectionFilesystems", []) or []:
            if getattr(fs, "fsType", None) != FsType.PFS0:
                continue
            for entry in getattr(fs, "files", []) or []:
                name = str(getattr(entry, "_path", "") or "")
                if ".cnmt" not in name.lower():
                    continue
                try:
                    entry.rewind()
                    sz = int(getattr(entry, "size", 0) or 0)
                    blob = entry.read(sz)
                    cnmt = Cnmt()
                    cnmt.open(MemoryFile(blob), "rb")
                    for ce in getattr(cnmt, "contentEntries", []) or []:
                        typ = getattr(ce, "type", None)
                        if typ is None:
                            continue
                        try:
                            ti = int(typ)
                        except (TypeError, ValueError):
                            continue
                        if ti != 3:
                            continue
                        nid = str(getattr(ce, "ncaId", "") or "").lower().replace(" ", "")
                        if len(nid) >= 16 and nid not in hints:
                            hints.append(nid)
                except BaseException:
                    continue
    return hints


def extract_metadata_nacp_from_loose_nca_files(
    extract_root: Path,
    default_xci: Path,
    prod_keys: Path | None,
    cfg: dict | None,
) -> tuple[dict | None, str]:
    # Control NCAs only (RomFS/PFS0); never load full Program/Data partitions.
    try:
        from nstools.Fs.Xci import Xci
    except ImportError:
        return None, "PyPI nstools not installed"

    if not nk._load_nstools_keys(prod_keys):
        return None, "could not load encryption keys (prod.keys)"

    nk._nstools_merge_title_keys_files(cfg if cfg is not None else {}, config_path_base(cfg))
    nk._nstools_set_quiet()

    cnmt_hints: list[str] = []
    try:
        xci = Xci(str(default_xci))
        nk._nstools_merge_titles_from_xci_tickets(xci)
        secure_hfs0 = None
        for part in getattr(xci.hfs0, "files", []) or []:
            if getattr(part, "_path", None) == "secure":
                secure_hfs0 = part
                break
        if secure_hfs0 is not None:
            cnmt_hints = _cnmt_control_nca_id_hints(secure_hfs0)
    except BaseException:
        pass

    nk._nstools_propagate_title_keys_patch_slots()
    nk._nstools_bridge_filename_tid_to_patch_slot(default_xci)

    nca_paths: list[Path] = []
    try:
        for p in extract_root.rglob("*"):
            if p.is_file() and p.suffix.lower() == ".nca":
                nca_paths.append(p)
    except OSError as e:
        return None, str(e)

    if not nca_paths:
        return None, "no .nca files under extracted secure tree"

    filename_v = ""
    m = DUMP_FILE_RE.match(default_xci.name)
    if m:
        filename_v = m.group("vnum")

    sources = [(p.name, p) for p in nca_paths]
    return _extract_nacp_from_loose_nca_disk_paths(sources, cnmt_hints, filename_v or "")


def _nca_content_type_peek(path: Path) -> int | None:
    try:
        from nstools.Fs.File import File
        from nstools.Fs.Nca import Nca

        nca = Nca()
        nca.open(File(str(path), "rb"))
        if nca.header:
            return int(nca.header.contentType)
    except BaseException:
        pass
    return None


def extract_metadata_via_jakcron_nca_partition_walk(
    extract_root: Path,
    nstool_bin: Path,
    prod_keys: Path | None,
    default_xci: Path,
    filename_version_token: str,
    cfg: dict | None,
) -> tuple[dict | None, str]:
    # jakcron --partN per NCA until control.nacp; optional jakcron_basenca for BKTR.
    basenca: Path | None = None
    raw_b = (cfg or {}).get("jakcron_basenca") if cfg else None
    if raw_b is not None and str(raw_b).strip():
        p = resolve_path(str(raw_b).strip(), config_path_base(cfg))
        if p is not None and p.is_file():
            basenca = p

    fn_tid = _retail_title_id_from_dump_filename(default_xci.name)
    tid_arg = fn_tid if fn_tid else "0100000000000000"

    seen: set[str] = set()
    nca_paths: list[Path] = []
    try:
        for p in extract_root.rglob("*"):
            if not p.is_file() or p.suffix.lower() != ".nca":
                continue
            k = str(p.resolve()).casefold()
            if k in seen:
                continue
            seen.add(k)
            nca_paths.append(p)
    except OSError as e:
        return None, str(e)

    if not nca_paths:
        return None, "no .nca files for jakcron partition extract"

    ctype_rank = {2: 0, 0: 1, 4: 2, 3: 3}

    def sort_key(p: Path) -> tuple[int, str]:
        ct = _nca_content_type_peek(p)
        r = ctype_rank.get(ct, 9) if ct is not None else 9
        return (r, p.name.casefold())

    nca_paths.sort(key=sort_key)

    part_flags = ("--part0", "--part1", "--part2", "--part3")
    for nca_path in nca_paths:
        for pf in part_flags:
            with tempfile.TemporaryDirectory(**_jakcron_tempdir_kwargs("nst_part_", cfg)) as tpart:
                tp = Path(tpart)
                rc, _ = run_nstool_nca_partition_extract(
                    nstool_bin, prod_keys, nca_path, pf, tp, basenca
                )
                if rc != 0:
                    continue
                hit = find_control_nacp_under_extract_root(tp)
                if hit is None:
                    continue
                raw = hit.read_bytes()
                if len(raw) < 0x80:
                    continue
                meta = _meta_dict_from_nacp_bytes(
                    raw,
                    title_id=tid_arg,
                    filename_version_token=filename_version_token or "",
                )
                if meta:
                    return meta, ""

    hint = ""
    if basenca is None and cfg and cfg.get("jakcron_basenca"):
        hint = " — jakcron_basenca path missing or invalid (required for some BKTR update NCAs)"
    return None, "jakcron --partN did not yield readable control.nacp" + hint

