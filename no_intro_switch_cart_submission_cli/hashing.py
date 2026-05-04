"""Checksum helpers for Default XCI and synthetic Full XCI."""

from __future__ import annotations

import hashlib
import zlib
from pathlib import Path


def is_full_xci(path: Path) -> bool:
    with open(path, "rb") as f:
        f.seek(0x1A0)
        seg = f.read(96)
    return len(seg) == 96 and all(b == 0 for b in seg)


def hash_file_streaming(path: Path, chunk: int = 4 * 1024 * 1024) -> tuple[int, str, str, str, str]:
    crc = 0
    md5 = hashlib.md5()
    sha1 = hashlib.sha1()
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            crc = zlib.crc32(block, crc)
            md5.update(block)
            sha1.update(block)
            sha256.update(block)
    size = path.stat().st_size
    return (
        size,
        format(crc & 0xFFFFFFFF, "08x"),
        md5.hexdigest(),
        sha1.hexdigest(),
        sha256.hexdigest(),
    )


def hash_full_xci_synthetic(initial_path: Path, default_xci_path: Path, chunk: int = 4 * 1024 * 1024) -> tuple[int, str, str, str, str]:
    # Initial Area + 3584 zero pad + Default XCI (synthetic Full XCI layout).
    total_size = initial_path.stat().st_size + 3584 + default_xci_path.stat().st_size
    crc = 0
    md5 = hashlib.md5()
    sha1 = hashlib.sha1()
    sha256 = hashlib.sha256()

    with open(initial_path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            crc = zlib.crc32(block, crc)
            md5.update(block)
            sha1.update(block)
            sha256.update(block)

    zeroes = b"\x00" * 3584
    crc = zlib.crc32(zeroes, crc)
    md5.update(zeroes)
    sha1.update(zeroes)
    sha256.update(zeroes)

    with open(default_xci_path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            crc = zlib.crc32(block, crc)
            md5.update(block)
            sha1.update(block)
            sha256.update(block)

    return (
        total_size,
        format(crc & 0xFFFFFFFF, "08x"),
        md5.hexdigest(),
        sha1.hexdigest(),
        sha256.hexdigest(),
    )
