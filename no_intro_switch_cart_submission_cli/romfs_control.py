"""RomFS walking and control.nacp extraction from decrypted NCAs (PyPI nstools)."""
from __future__ import annotations

import struct

from no_intro_switch_cart_submission_cli.constants import (
    MAX_ROMFS_SECTION_BYTES_FOR_NACP,
    ROMFS_DIR_FIXED,
    ROMFS_ENTRY_EMPTY,
    ROMFS_FILE_FIXED,
    ROMFS_HEADER_SIZE,
    ROMFS_MAX_NAME_LEN,
    ROMFS_WALK_MAX_STEPS,
)

def _decode_romfs_filename(raw: bytes) -> str:
    if not raw:
        return ""
    z = raw.split(b"\x00\x00")[0] if b"\x00\x00" in raw else raw.rstrip(b"\x00")
    if not z:
        return ""
    for enc in ("utf-8", "utf-16-le"):
        try:
            return z.decode(enc)
        except UnicodeDecodeError:
            continue
    return z.decode("utf-8", errors="replace")


def _romfs_hdr_ok(blob: bytes, base: int, maxlen: int) -> bool:
    if base + ROMFS_HEADER_SIZE > maxlen:
        return False
    h = struct.unpack_from("<10Q", blob, base)
    if h[0] != ROMFS_HEADER_SIZE:
        return False
    if h[9] >= maxlen - base:
        return False
    if h[3] + h[4] > maxlen - base or h[7] + h[8] > maxlen - base:
        return False
    return True


def _romfs_ivfc_romfs_tails(blob: bytes, ivfc_off: int) -> list[bytes]:
    # IVFC levels: try each inner level start for a valid RomFS header.
    out: list[bytes] = []
    if ivfc_off < 0 or ivfc_off + 0x40 > len(blob):
        return out
    ivfc = blob[ivfc_off:]
    if ivfc[:4] != b"IVFC":
        return out
    nl = int.from_bytes(ivfc[12:16], "little")
    if nl < 2 or nl > 16:
        return out
    for idx in range(nl - 1):
        lo = 16 + idx * 24
        if lo + 16 > len(ivfc):
            break
        level_off = int.from_bytes(ivfc[lo : lo + 8], "little")
        if level_off < 0 or level_off >= len(ivfc):
            continue
        tail = ivfc[level_off:]
        if len(tail) < ROMFS_HEADER_SIZE:
            continue
        if struct.unpack_from("<Q", tail, 0)[0] != ROMFS_HEADER_SIZE:
            continue
        if _romfs_hdr_ok(tail, 0, len(tail)):
            out.append(tail)
    return out


def _find_romfs_image(section_plain: bytes) -> bytes | None:
    start_ivfc = 0
    while True:
        io = section_plain.find(b"IVFC", start_ivfc)
        if io < 0:
            break
        for tail in _romfs_ivfc_romfs_tails(section_plain, io):
            if _romfs_hdr_ok(tail, 0, len(tail)):
                return tail
        start_ivfc = io + 4
    scan_limit = min(len(section_plain), 512 * 1024 * 1024)
    for i in range(0, scan_limit - ROMFS_HEADER_SIZE, 4):
        if struct.unpack_from("<Q", section_plain, i)[0] != ROMFS_HEADER_SIZE:
            continue
        cand = section_plain[i:]
        if _romfs_hdr_ok(cand, 0, len(cand)):
            return cand
    return None


def _romfs_extract_file(romfs: bytes, path_parts: tuple[str, ...]) -> bytes | None:
    if not path_parts:
        return None
    if not _romfs_hdr_ok(romfs, 0, len(romfs)):
        return None
    hdr = struct.unpack_from("<10Q", romfs, 0)
    dirs_off, dirs_sz = hdr[3], hdr[4]
    files_off, files_sz = hdr[7], hdr[8]
    data_off = hdr[9]
    dirs_blob = romfs[dirs_off : dirs_off + dirs_sz]
    files_blob = romfs[files_off : files_off + files_sz]

    def nm_eq(a: str, b: str) -> bool:
        return a.casefold() == b.casefold()

    def read_dir(off: int) -> tuple[int, int, int, int, int, bytes]:
        if off < 0 or off + ROMFS_DIR_FIXED > len(dirs_blob):
            raise struct.error("dir oob")
        sib, child, file_first, _hashv, namelen = struct.unpack_from("<IIIII", dirs_blob, off)
        if namelen > ROMFS_MAX_NAME_LEN or off + ROMFS_DIR_FIXED + namelen > len(dirs_blob):
            raise struct.error("dir name oob")
        nm = dirs_blob[off + ROMFS_DIR_FIXED : off + ROMFS_DIR_FIXED + namelen]
        return sib, child, file_first, _hashv, namelen, nm

    def read_file_meta(off: int) -> tuple[int, int, int, int, int, int, bytes]:
        if off < 0 or off + ROMFS_FILE_FIXED > len(files_blob):
            raise struct.error("file oob")
        parent, sib, offset, size, _hashv, namelen = struct.unpack_from("<IIQQII", files_blob, off)
        if namelen > ROMFS_MAX_NAME_LEN or off + ROMFS_FILE_FIXED + namelen > len(files_blob):
            raise struct.error("file name oob")
        nm = files_blob[off + ROMFS_FILE_FIXED : off + ROMFS_FILE_FIXED + namelen]
        return parent, sib, offset, size, _hashv, namelen, nm

    def find_named_dir_among_siblings(first_off: int, target: str) -> int | None:
        off = first_off
        steps = 0
        while off != ROMFS_ENTRY_EMPTY:
            if steps >= ROMFS_WALK_MAX_STEPS:
                return None
            steps += 1
            sib, child, file_first, hv, nl, nm = read_dir(off)
            name = _decode_romfs_filename(nm)
            if nm_eq(name, target):
                return off
            off = sib
        return None

    def find_file_in_dir(dir_meta_off: int, fname: str) -> tuple[int, int] | None:
        _, _, file_first, _, _, _ = read_dir(dir_meta_off)
        off = file_first
        steps = 0
        while off != ROMFS_ENTRY_EMPTY:
            if steps >= ROMFS_WALK_MAX_STEPS:
                return None
            steps += 1
            parent, sib, offset, size, hv, nl, nm = read_file_meta(off)
            name = _decode_romfs_filename(nm)
            if nm_eq(name, fname):
                return offset, size
            off = sib
        return None

    if len(path_parts) == 1:
        got = find_file_in_dir(0, path_parts[0])
        if got is None:
            return None
        offset, size = got
        start = data_off + offset
        end = start + size
        if start > len(romfs) or end > len(romfs) or size < 0 or offset < 0:
            return None
        return romfs[start:end]

    _, root_child, _, _, _, _ = read_dir(0)
    current_first = root_child
    last_dir_off: int | None = None
    for seg in path_parts[:-1]:
        found = find_named_dir_among_siblings(current_first, seg)
        if found is None:
            return None
        last_dir_off = found
        _, child_first, _, _, _, _ = read_dir(found)
        current_first = child_first

    if last_dir_off is None:
        return None
    got = find_file_in_dir(last_dir_off, path_parts[-1])
    if got is None:
        return None
    offset, size = got
    start = data_off + offset
    end = start + size
    if start > len(romfs) or end > len(romfs) or size < 0 or offset < 0:
        return None
    return romfs[start:end]


def _romfs_try_control_nacp_from_romfs_image(img: bytes) -> bytes | None:
    # LibHac opens ``/control.nacp`` at RomFS root; ``control/control.nacp`` is also common.
    for path in (("control.nacp",), ("control", "control.nacp")):
        try:
            data = _romfs_extract_file(img, path)
        except (struct.error, IndexError, MemoryError):
            data = None
        if data:
            return data
    return None


def _read_plain_romfs_section(fs: object) -> bytes | None:
    # Full decrypted RomFS; BKTR uses ciphertext + bktrSeek (not nstools linear CTR on BKTR).
    try:
        fs.rewind()
        sz = fs.size
        if sz is None or sz <= 0:
            return None
        if sz > MAX_ROMFS_SECTION_BYTES_FOR_NACP:
            return None
        has_bktr = bool(
            getattr(fs, "hasBktr", lambda: False)()
            and getattr(fs, "bktrSubsection", None) is not None
        )
        if not has_bktr:
            return fs.read(sz)

        from nstools.Fs.Type import Crypto as FsCrypto
        from nstools.nut import aes128

        parent = getattr(fs, "f", None)
        key = getattr(fs, "cryptoKey", None)
        nonce = getattr(fs, "cryptoCounter", None)
        if parent is None or not key or not nonce:
            return fs.read(sz)

        subs = fs.bktrSubsection.getAllEntries()
        if not subs:
            return fs.read(sz)

        subs_sorted = sorted(subs, key=lambda e: int(getattr(e, "virtualOffset", 0)))
        out = bytearray(sz)
        real = fs.realOffset()
        prev_crypto = parent.crypto
        prev_ct = getattr(parent, "cryptoType", None)
        nonce_b = bytes(nonce) if isinstance(nonce, bytearray) else nonce
        try:
            parent.crypto = None
            parent.cryptoType = FsCrypto.NONE
            max_end = 0
            for entry in subs_sorted:
                vo = int(entry.virtualOffset)
                n = int(entry.size)
                if n <= 0 or vo >= sz:
                    continue
                if vo + n > sz:
                    n = sz - vo
                parent.seek(vo + real)
                raw = parent.read(n)
                if len(raw) != n:
                    raise OSError("short BKTR RomFS read")
                # BKTR: bktrSeek for subsection IVs; plain AESCTR linear mode is insufficient here.
                ctr_val = int(getattr(entry, "ctr", 0)) & 0xFFFFFFFF
                aes = aes128.AESCTR(key, nonce_b, offset=0)
                aes.bktrSeek(0, ctr_val, 0)
                plain = aes.decrypt(raw)
                out[vo : vo + n] = plain[:n]
                max_end = max(max_end, vo + n)
            if max_end < sz:
                n = sz - max_end
                parent.seek(max_end + real)
                raw = parent.read(n)
                aes = aes128.AESCTR(key, nonce_b, offset=0)
                aes.seek(max_end)
                plain = aes.decrypt(raw)
                out[max_end:sz] = plain[:n]
        finally:
            parent.crypto = prev_crypto
            if prev_ct is not None:
                parent.cryptoType = prev_ct
        return bytes(out)
    except Exception:
        try:
            fs.rewind()
            esz = getattr(fs, "size", None) or 0
            if esz <= 0 or esz > MAX_ROMFS_SECTION_BYTES_FOR_NACP:
                return None
            return fs.read(esz)
        except Exception:
            return None


def _nca_physical_section_fs_pairs(nca: object) -> list[tuple[int, object]]:
    # Map sectionFilesystems entries to physical indices 0..3 via header.sectionTables offsets.
    pairs: list[tuple[int, object]] = []
    sections = getattr(nca, "sections", None) or []
    fss = getattr(nca, "sectionFilesystems", None) or []
    hdr = getattr(nca, "header", None)
    if hdr is None or len(sections) != len(fss):
        return pairs
    tables = getattr(hdr, "sectionTables", None) or []
    for sec, fs in zip(sections, fss):
        parent_off = getattr(sec, "offset", None)
        if parent_off is None:
            continue
        try:
            po = int(parent_off)
        except (TypeError, ValueError):
            continue
        pi: int | None = None
        for i in range(min(4, len(tables))):
            st = tables[i]
            st_off = getattr(st, "offset", None)
            if st_off is None:
                continue
            try:
                if int(st_off) == po:
                    pi = i
                    break
            except (TypeError, ValueError):
                continue
        if pi is None:
            continue
        pairs.append((pi, fs))
    return pairs


def _libhac_physical_section_try_order(content_type: object) -> list[int]:
    # LibHac Data section index: Program uses RomFS at 1; other types typically 0.
    try:
        from nstools.Fs.Type import Content

        if isinstance(content_type, Content):
            ct = content_type
        else:
            ct = Content(content_type)
    except Exception:
        return [0, 1, 2, 3]
    # Mirrors LibHac ``GetSectionIndexFromType(Data, contentType)``.
    if ct == Content.PROGRAM:
        return [1, 0, 2, 3]
    return [0, 1, 2, 3]


def _romfs_extract_control_nacp(section_plain: bytes) -> bytes | None:
    start = 0
    while True:
        io = section_plain.find(b"IVFC", start)
        if io < 0:
            break
        for tail in _romfs_ivfc_romfs_tails(section_plain, io):
            if not _romfs_hdr_ok(tail, 0, len(tail)):
                continue
            data = _romfs_try_control_nacp_from_romfs_image(tail)
            if data:
                return data
        start = io + 4
    img = _find_romfs_image(section_plain)
    if not img:
        return None
    return _romfs_try_control_nacp_from_romfs_image(img)


def _extract_raw_control_nacp_from_nca(nca: object) -> bytes | None:
    # RomFS/PFS0 control.nacp; try sections in LibHac Data order; BKTR handled in _read_plain_romfs_section.
    try:
        from nstools.Fs.Type import Fs as FsType
    except ImportError:
        return None

    hdr = getattr(nca, "header", None)
    ct = getattr(hdr, "contentType", None) if hdr else None
    priority = _libhac_physical_section_try_order(ct)

    pairs = _nca_physical_section_fs_pairs(nca)
    if not pairs:
        pairs = [
            (i, fs) for i, fs in enumerate(getattr(nca, "sectionFilesystems", []) or [])
        ]

    def sort_phys(pi: int) -> tuple[int, int]:
        try:
            pr = priority.index(pi)
        except ValueError:
            pr = 99
        return (pr, pi)

    romfs_first = [(pi, fs) for pi, fs in pairs if getattr(fs, "fsType", None) == FsType.ROMFS]
    romfs_first.sort(key=lambda t: sort_phys(t[0]))
    pfs_rest = [(pi, fs) for pi, fs in pairs if getattr(fs, "fsType", None) == FsType.PFS0]
    pfs_rest.sort(key=lambda t: sort_phys(t[0]))

    for _pi, fs in romfs_first:
        try:
            fs.rewind()
            sec_plain = _read_plain_romfs_section(fs)
            if not sec_plain:
                fs.rewind()
                sz_fb = int(getattr(fs, "size", 0) or 0)
                if sz_fb > MAX_ROMFS_SECTION_BYTES_FOR_NACP:
                    continue
                sec_plain = fs.read(sz_fb)
        except BaseException:
            continue
        raw = _romfs_extract_control_nacp(sec_plain)
        if raw and len(raw) >= 0x80:
            return raw

    for _pi, fs in pfs_rest:
        for entry in getattr(fs, "files", []) or []:
            path = str(getattr(entry, "_path", "") or "")
            if path.lower() != "control.nacp":
                continue
            try:
                entry.rewind()
                sz = int(getattr(entry, "size", 0) or 0)
                raw = entry.read(sz)
                if raw and len(raw) >= 0x80:
                    return raw
            except BaseException:
                continue
    return None

