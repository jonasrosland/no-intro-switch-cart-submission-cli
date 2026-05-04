"""No-Intro Trusted Dump submission XML builder."""
from __future__ import annotations

from xml.dom import minidom
import xml.etree.ElementTree as ET

def build_xml(
    *,
    game_name: str,
    region: str,
    languages: str,
    gameid1: str,
    gameid2: str,
    version1_rev: str | None,
    dumper: str,
    tool: str,
    dump_date: str,
    comment1: str,
    media_serial1: str,
    media_serial2: str,
    pcb_serial: str,
    box_serial: str,
    box_barcode: str,
    file_default: dict,
    file_initial: dict | None,
    file_full: dict,
) -> str:
    datafile = ET.Element("datafile")
    game = ET.SubElement(datafile, "game", name=game_name)

    archive_attrs: dict[str, str] = {
        "clone": "P",
        "name": game_name,
        "region": region,
        "languages": languages,
        "langchecked": "unk",
        "gameid1": gameid1,
        "gameid2": gameid2,
        "categories": "Games",
    }
    if version1_rev:
        archive_attrs["version1"] = version1_rev

    ET.SubElement(game, "archive", **archive_attrs)

    source = ET.SubElement(game, "source")
    details = ET.SubElement(
        source,
        "details",
        section="Trusted Dump",
        d_date=dump_date,
        r_date="",
        r_date_info="0",
        region=region,
        dumper=dumper,
        project="No-Intro",
        tool=tool,
        comment1=comment1,
        originalformat="Default",
    )

    serials_attrs = {
        "media_serial1": media_serial1,
        "media_serial2": media_serial2.strip(),
        "pcb_serial": pcb_serial,
        "box_serial": box_serial,
        "box_barcode": box_barcode,
    }

    ET.SubElement(source, "serials", **serials_attrs)

    ET.SubElement(
        source,
        "file",
        forcename="",
        size=file_default["size"],
        crc32=file_default["crc32"],
        md5=file_default["md5"],
        sha1=file_default["sha1"],
        sha256=file_default["sha256"],
        extension="xci",
        version=file_default["version"],
        update_type=file_default["update_type"],
        format="Default",
    )

    if file_initial:
        ET.SubElement(
            source,
            "file",
            forcename="",
            size=file_initial["size"],
            crc32=file_initial["crc32"],
            md5=file_initial["md5"],
            sha1=file_initial["sha1"],
            sha256=file_initial["sha256"],
            extension="bin",
            item="Initial Area",
            format="Default",
            filter="Initial Area",
        )

    ET.SubElement(
        source,
        "file",
        forcename="",
        size=file_full["size"],
        crc32=file_full["crc32"],
        md5=file_full["md5"],
        sha1=file_full["sha1"],
        sha256=file_full["sha256"],
        extension="xci",
        format="FullXCI",
    )

    raw = ET.tostring(datafile, encoding="utf-8")
    pretty = minidom.parseString(raw).toprettyxml(indent="    ")
    pretty = pretty.replace("&amp;#10;", "&#10;")
    lines = [ln for ln in pretty.splitlines() if ln.strip()]
    return "\n".join(lines) + "\n"


def safe_filename_segment(s: str) -> str:
    for ch in '\\/:*?"<>|':
        s = s.replace(ch, "-")
    return s.strip() or "Submission"

