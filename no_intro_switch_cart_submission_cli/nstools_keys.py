"""PyPI nstools key merge and ticket helpers."""
from __future__ import annotations

import re
from pathlib import Path

from no_intro_switch_cart_submission_cli.constants import DUMP_FILE_RE
from no_intro_switch_cart_submission_cli.paths import resolve_path

def _nstools_set_quiet() -> None:
    import nstools.nut.Print as NPrint

    NPrint.silent = True
    NPrint.enableInfo = False


def _load_nstools_keys(prod_keys: Path | None) -> bool:
    from nstools.nut import Keys

    _nstools_set_quiet()
    if prod_keys is not None and prod_keys.is_file():
        return bool(Keys.load(str(prod_keys)))
    return bool(Keys.load_default())


# Lockpick title.keys: left column is 16 hex chars (application ID) OR 32 hex chars (full rights ID).
# nstools only looks up Titles[first 16 hex chars of NCA rightsId].
_TITLE_KEYS_LINE = re.compile(
    r"^\s*([0-9a-fA-F]{16}|[0-9a-fA-F]{32})\s*=\s*([0-9a-fA-F]{32})\s*(?:#.*)?$",
    re.IGNORECASE,
)
# Spaces in key, ":" separator, or long rights-ID lines.
_TITLE_KEYS_RELAXED = re.compile(
    r"^\s*([0-9a-fA-F]{16}|[0-9a-fA-F]{32})\s*[=:]\s*([^#\r\n]+?)\s*(?:#.*)?$",
    re.IGNORECASE,
)


def _nstools_register_encrypted_title_key(left_hex: str, enc_key_hex: str) -> bool:
    try:
        from nstools.nut import Titles
    except ImportError:
        return False
    left = re.sub(r"[^0-9a-fA-F]", "", left_hex, flags=re.I).upper()
    key = re.sub(r"[^0-9a-fA-F]", "", enc_key_hex, flags=re.I).upper()
    if len(key) != 32 or len(left) not in (16, 32):
        return False
    if len(left) == 32:
        Titles.get(left[:16]).key = key
    else:
        Titles.get(left).key = key
    return True


def _nstools_merge_title_keys_files(cfg: dict, script_dir: Path) -> int:
    # PyPI nstools does not read title.keys from disk; merge Lockpick-format lines into Titles.
    paths: list[Path] = [
        Path.home() / ".switch" / "title.keys",
        script_dir / "title.keys",
    ]
    raw = cfg.get("title_keys")
    if raw is not None and str(raw).strip():
        extra = resolve_path(str(raw).strip(), script_dir)
        if extra is not None:
            paths.append(extra)

    merged = 0
    seen_resolved: set[str] = set()
    for path in paths:
        try:
            rp = str(path.resolve())
        except OSError:
            continue
        if rp in seen_resolved:
            continue
        seen_resolved.add(rp)
        if not path.is_file():
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    raw = line.strip()
                    if not raw or raw.startswith("#"):
                        continue
                    m = _TITLE_KEYS_LINE.match(raw)
                    if m:
                        left_s, tkey = m.group(1), m.group(2).upper()
                    else:
                        m2 = _TITLE_KEYS_RELAXED.match(raw)
                        if not m2:
                            continue
                        left_s = m2.group(1)
                        rawk = re.sub(r"[^0-9a-fA-F]", "", m2.group(2), flags=re.I)
                        if len(rawk) != 32:
                            continue
                        tkey = rawk.upper()
                    if _nstools_register_encrypted_title_key(left_s, tkey):
                        merged += 1
        except OSError:
            continue
    return merged


def _nstools_propagate_title_keys_patch_slots() -> None:
    # Duplicate app title key to patch slot (…800 → …888) when nstools looks up by rightsId prefix.
    try:
        from nstools.nut import Titles
    except ImportError:
        return
    td = Titles.data()
    if not td:
        return
    for tid_upper, title_obj in list(td.items()):
        key = getattr(title_obj, "key", None)
        if not key:
            continue
        try:
            base = int(tid_upper, 16)
        except ValueError:
            continue
        patch_tid = f"{base | 0x800:016X}".upper()
        if patch_tid == tid_upper.upper():
            continue
        other = Titles.get(patch_tid)
        if other.key:
            continue
        other.key = key


def _nstools_bridge_filename_tid_to_patch_slot(default_xci: Path) -> None:
    # Copy title key from XCI filename [tid] to tid|0x800 when Titles state is odd.
    m = DUMP_FILE_RE.match(default_xci.name)
    if not m:
        return
    try:
        from nstools.nut import Titles

        tid = m.group("tid").upper()
        k = Titles.get(tid).key
        if not k:
            return
        patch_tid = f"{int(tid, 16) | 0x800:016X}".upper()
        if patch_tid == tid:
            return
        slot = Titles.get(patch_tid)
        if slot.key:
            return
        slot.key = k
    except Exception:
        pass


def _nstools_merge_titles_from_xci_tickets(xci: object) -> int:
    # Load .tik from XCI secure so Titles has keys for Program NCAs without a huge title.keys file.
    try:
        from nstools.Fs.Ticket import Ticket
    except ImportError:
        return 0
    root = getattr(xci, "hfs0", None)
    if not root:
        return 0
    to_scan: list = list(getattr(root, "files", []) or [])
    for p in getattr(root, "files", []) or []:
        if getattr(p, "_path", None) == "secure":
            to_scan.extend(getattr(p, "files", []) or [])
            break
    count = 0
    for part in to_scan:
        ps = str(getattr(part, "_path", "") or "").lower()
        if not ps.endswith(".tik"):
            continue
        tik = Ticket()
        try:
            tik.open(part)
            tkh = tik.titleKey()
            if not tkh or len(tkh) != 32:
                continue
            try:
                if int(tkh, 16) == 0:
                    continue
            except ValueError:
                continue
            tid = tik.titleId()
            if not tid or len(tid) != 16:
                continue
            if _nstools_register_encrypted_title_key(tid, tkh):
                count += 1
        except BaseException:
            continue
    return count


def _nstools_alias_title_key_rights_to_app(hdr: object) -> bool:
    # When rightsId prefix ≠ application titleId, copy Titles[app] key to Titles[rights] for decrypt.
    try:
        from nstools.nut import Titles
    except ImportError:
        return False
    has_tr = getattr(hdr, "hasTitleRights", None)
    if not callable(has_tr) or not has_tr():
        return False
    try:
        rid = hdr.rightsId.decode()[0:16].upper()
        aid = str(hdr.titleId).upper()
    except Exception:
        return False
    if not rid or not aid or rid == aid:
        return False
    try:
        app_key = Titles.get(aid).key
        if not app_key:
            return False
        if Titles.get(rid).key:
            return False
        Titles.get(rid).key = app_key
        return True
    except Exception:
        return False


def _nstools_decrypt_fail_hint(hdr: object) -> str:
    try:
        rid = hdr.rightsId.decode()[0:16].upper()
        aid = str(hdr.titleId).upper()
        return f"need title key for rights prefix {rid} (header title ID {aid}; Lockpick lines often use the latter)"
    except Exception:
        return ""

