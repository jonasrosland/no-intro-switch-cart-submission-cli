"""Discover nxdt-style release folders under a scan root."""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from no_intro_switch_cart_submission_cli.constants import DUMP_FILE_RE
from no_intro_switch_cart_submission_cli.hashing import is_full_xci

TRUSTED_DUMP_SUBMISSION_XML_SUFFIX = " Submission.xml"


def list_trusted_dump_submission_xmls(directory: Path) -> list[Path]:
    directory = directory.resolve()
    found: list[Path] = []
    try:
        for p in directory.iterdir():
            if p.is_file() and p.name.endswith(TRUSTED_DUMP_SUBMISSION_XML_SUFFIX):
                found.append(p)
    except OSError:
        return []
    return sorted(found)


def format_title(title: str) -> str:
    title = title.replace(":", " - ").replace("~", "-")
    title = re.sub(r'[\\/:*?"<>|`]', "", title)
    title = re.sub(r"\s+", " ", title).strip()
    words = title.split()
    articles = {"a", "an", "the"}
    link_words = {
        "and",
        "or",
        "but",
        "nor",
        "so",
        "yet",
        "for",
        "at",
        "by",
        "in",
        "on",
        "to",
        "of",
        "up",
        "with",
        "as",
        "per",
    }
    formatted_words = []
    for word in words:
        wl = word.lower()
        if wl in articles or wl in link_words:
            formatted_words.append(word.lower())
        elif word.isupper() or (word.isalpha() and word.isupper()):
            formatted_words.append(word)
        else:
            formatted_words.append(word.capitalize())

    if formatted_words and formatted_words[0].lower() in articles:
        article = formatted_words.pop(0).capitalize()
        try:
            sep_index = formatted_words.index("-")
            formatted_words[sep_index - 1] += ","
            formatted_words.insert(sep_index, article)
        except ValueError:
            formatted_words[-1] += ","
            formatted_words.append(article)

    return " ".join(formatted_words)


def card_id_comment(card_id_bin: Path) -> str:
    data = card_id_bin.read_bytes()
    hx = data.hex().upper()
    c1, c2, c3 = hx[:8], hx[8:16], hx[16:24]
    crc = zlib.crc32(data) & 0xFFFFFFFF
    crc_s = format(crc, "08x").upper()
    lines = [
        f"Card ID 1: {c1}",
        f"Card ID 2: {c2}",
        f"Card ID 3: {c3}",
        f"CRC32: {crc_s}",
    ]
    return "&#10;".join(lines)


def parse_filename_fallback(filename: str) -> tuple[str | None, str | None, str | None]:
    m = DUMP_FILE_RE.match(filename)
    if not m:
        return None, None, None
    prefix = m.group("prefix").strip()
    tid = m.group("tid")
    parts = prefix.rsplit(" ", 1)
    if len(parts) == 2 and re.match(r"^[0-9]", parts[1]):
        return parts[0], parts[1], tid
    return prefix, None, tid


_XCI_FOLDER_VER_DOT_RE = re.compile(
    r"^[0-9]+(?:\.[0-9]+)*(?:[a-zA-Z]+|\.Switch)?$",
    re.I,
)
_XCI_FOLDER_VER_USCORE_RE = re.compile(r"^[0-9]+(?:_[0-9A-Za-z]+)+$", re.I)
_VNUM_BRACKET_STYLE_RE = re.compile(r"^v\d+$", re.I)


def is_xci_folder_version_token(name: str) -> bool:
    """True when ``name`` looks like an nxdt-style version folder (aligned with ``sort_gamecard.sh``)."""
    n = (name or "").strip()
    if not n:
        return False
    if _XCI_FOLDER_VER_DOT_RE.fullmatch(n):
        return True
    if _XCI_FOLDER_VER_USCORE_RE.fullmatch(n):
        return True
    return bool(_VNUM_BRACKET_STYLE_RE.fullmatch(n))


def version_segment_for_submission_xml(default_xci: Path) -> str | None:
    """
    Middle segment for ``… - <segment> - <dumper> - <date> Submission.xml``.

    Prefer the human version token from the nxdt basename (before ``[tid]``), else a
    version-like parent directory name, else the bracket ``v…`` update token.
    """
    _, v_fn, _ = parse_filename_fallback(default_xci.name)
    if v_fn and str(v_fn).strip():
        return str(v_fn).strip()
    if is_xci_folder_version_token(default_xci.parent.name):
        return default_xci.parent.name.strip()
    m = DUMP_FILE_RE.match(default_xci.name)
    if m:
        return m.group("vnum")
    return None


@dataclass
class ReleaseFiles:
    directory: Path
    default_xci: Path
    initial_data: Path | None = None
    card_id_set: Path | None = None
    full_xci_on_disk: Path | None = None


def discover_releases(root: Path, skip_hidden: bool) -> Iterator[ReleaseFiles]:
    root = root.resolve()
    seen: set[Path] = set()
    for xci in sorted(root.rglob("*.xci")):
        if "[0100" not in xci.name:
            continue
        if skip_hidden and any(part.startswith(".") for part in xci.parts):
            continue
        d = xci.parent.resolve()
        if d in seen:
            continue
        files = [p for p in d.iterdir() if p.is_file()]
        xcis = [p for p in files if p.suffix.lower() == ".xci" and "[0100" in p.name]
        if not xcis:
            continue
        defaults = [p for p in xcis if not is_full_xci(p)]
        full_on_disk = [p for p in xcis if is_full_xci(p)]
        if not defaults:
            continue
        prefer = [p for p in defaults if "[NKA]" in p.name]
        default_xci = prefer[0] if prefer else defaults[0]
        initial_data = next((p for p in files if "(Initial Data)" in p.name and p.suffix.lower() == ".bin"), None)
        card_id_set = next((p for p in files if "(Card ID Set)" in p.name and p.suffix.lower() == ".bin"), None)
        full_disk = full_on_disk[0] if full_on_disk else None

        seen.add(d)

        yield ReleaseFiles(
            directory=d,
            default_xci=default_xci,
            initial_data=initial_data,
            card_id_set=card_id_set,
            full_xci_on_disk=full_disk,
        )


def _release_banner_label(rel: ReleaseFiles, root: Path) -> str:
    scan_root = root.resolve()
    release_dir = rel.directory.resolve()

    if release_dir.parent == scan_root:
        return scan_root.name

    parts = release_dir.relative_to(scan_root).parts
    if len(parts) >= 2:
        return parts[0]
    return parts[0] if parts else release_dir.name
