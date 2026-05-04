"""Regex and lookup tables shared across metadata paths."""

from __future__ import annotations

import re

NACP_INDEX_TO_LANG = {
    0: "En",
    1: "En",
    2: "Ja",
    3: "Fr",
    4: "De",
    5: "Es",
    6: "Es",
    7: "It",
    8: "Nl",
    9: "Fr",
    10: "Pt",
    11: "Ru",
    12: "Ko",
    13: "Zh-Hant",
    14: "Zh-Hans",
}

DUMP_FILE_RE = re.compile(
    r"^(?P<prefix>.+)\s+\[(?P<tid>0100[0-9A-Fa-f]{12})\]\[(?P<vnum>v\d+)\]",
    re.IGNORECASE,
)

# Media Serial 1: strip trailing -USA / -EUR etc. when deriving gameid2.
MEDIA_SERIAL1_REGION_SUFFIXES: frozenset[str] = frozenset({
    "USA",
    "EUR",
    "JPN",
    "AUS",
    "KOR",
    "CHN",
    "CHT",
    "ASI",
    "UKV",
    "RUS",
    "MSE",
})

# Config + CLI manual submission field keys.
SERIAL_FIELDS = (
    "gameid2",
    "media_serial1",
    "media_serial2",
    "box_serial",
    "box_barcode",
    "pcb_serial",
)

ROMFS_HEADER_SIZE = 0x50
ROMFS_ENTRY_EMPTY = 0xFFFFFFFF
ROMFS_DIR_FIXED = 0x14
ROMFS_FILE_FIXED = 0x20
ROMFS_MAX_NAME_LEN = 0x400
ROMFS_WALK_MAX_STEPS = 65536

# RomFS scan limits for control.nacp (Program NCAs are huge).
MAX_ROMFS_SECTION_BYTES_FOR_NACP = 96 * 1024 * 1024

# Max buffered bytes per secure/*.nca when sniffing Control type from XCI.
MAX_CONTROL_NCA_BYTES_BUFFERED_FROM_XCI = 256 * 1024 * 1024
