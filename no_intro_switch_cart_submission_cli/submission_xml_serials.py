"""Read serial fields from an existing Trusted Dump ``* Submission.xml``."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

# Fields under ``<serials …/>`` plus ``gameid2`` from ``<archive …/>`` (not filled from scans).
_SERIAL_ATTRS = (
    "media_serial1",
    "media_serial2",
    "box_serial",
    "box_barcode",
    "pcb_serial",
)


def parse_trusted_dump_serials_from_submission_xml(path: Path) -> dict[str, str]:
    """
    Parse the first ``game/source/serials`` element and its sibling ``archive`` for ``gameid2``.

    Missing elements or attributes become empty strings.
    """
    out: dict[str, str] = {k: "" for k in ("gameid2", *_SERIAL_ATTRS)}
    tree = ET.parse(path)
    root = tree.getroot()
    arch = root.find(".//archive")
    if arch is not None:
        g2 = arch.get("gameid2")
        if g2 is not None:
            out["gameid2"] = str(g2).strip()

    serials = root.find(".//serials")
    if serials is None:
        return out

    for k in _SERIAL_ATTRS:
        v = serials.get(k)
        if v is not None:
            out[k] = str(v).strip()
    return out


def submission_xml_serials_summary(row: dict[str, Any]) -> str:
    """One-line debug summary of serial-related keys."""
    parts = [f"{k}={row.get(k)!r}" for k in ("media_serial1", "media_serial2", "box_serial", "box_barcode", "pcb_serial")]
    return "  " + "  ".join(parts)
