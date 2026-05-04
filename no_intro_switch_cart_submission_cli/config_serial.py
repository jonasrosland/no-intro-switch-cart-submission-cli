"""JSON config load and optional serial / CLI fields."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

from no_intro_switch_cart_submission_cli.constants import MEDIA_SERIAL1_REGION_SUFFIXES, SERIAL_FIELDS

# Whole-field shortcuts for pcb_serial (config / CLI / -i): easier than typing Unicode ▼.
PCB_SERIAL_SHORTCUTS: dict[str, str] = {
    "@": "\u25bc",  # ▼
    "$": "\u25bc 10",  # ▼ 10
}


def normalize_pcb_serial(raw: str | None) -> str:
    s = "" if raw is None else str(raw).strip()
    return PCB_SERIAL_SHORTCUTS.get(s, s)


def load_config(path: Path) -> dict:
    if not path.is_file():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def version1_rev_from_media_serial2(media_serial2: str) -> str | None:
    # 11 chars: last 3 digits → Rev NNN; 13 chars: positions 9–10 → Rev NN.
    s = (media_serial2 or "").strip()
    if len(s) == 11:
        tail = s[-3:]
        if not re.match(r"^[0-9]{3}$", tail):
            return None
        return f"Rev {tail}"
    if len(s) == 13:
        pair = s[8:10]
        if not re.match(r"^[0-9]{2}$", pair):
            return None
        return f"Rev {pair}"
    return None


def merged_serial_fields(cfg: dict) -> dict[str, str]:
    row: dict[str, str] = {}
    for k in SERIAL_FIELDS:
        v = cfg.get(k)
        s = "" if v is None else str(v).strip()
        if k == "pcb_serial":
            s = normalize_pcb_serial(s)
        row[k] = s
    return row


def apply_cli_serial_overrides(args: argparse.Namespace, row: dict[str, str]) -> dict[str, str]:
    out = dict(row)
    for k in SERIAL_FIELDS:
        val = getattr(args, k, None)
        if val is not None:
            out[k] = str(val).strip()
    out["pcb_serial"] = normalize_pcb_serial(out.get("pcb_serial"))
    return out


def derive_gameid2_from_media_serial1(media_serial1: str) -> str:
    # Strip trailing -EUR / -USA etc. from Media Serial 1 for catalog gameid2.
    ms = (media_serial1 or "").strip()
    if not ms:
        return ""
    parts = ms.split("-")
    if len(parts) >= 2:
        last = parts[-1].strip().upper()
        if last in MEDIA_SERIAL1_REGION_SUFFIXES:
            return "-".join(parts[:-1])
    return ms


def fill_gameid2_from_media_serial1_if_empty(row: dict[str, str]) -> None:
    if (row.get("gameid2") or "").strip():
        return
    ms = (row.get("media_serial1") or "").strip()
    if not ms:
        return
    row["gameid2"] = derive_gameid2_from_media_serial1(ms)


def interactive_prompt_manual(args: argparse.Namespace, cfg: dict) -> None:
    if not args.interactive:
        return
    print()
    print("Manual submission fields — [brackets] show values from your JSON config; Enter accepts the default.")
    print('pcb_serial shortcuts (whole value): @ → ▼, $ → ▼ 10.')
    print()

    def default_for(attr: str) -> str:
        if attr == "dump_date_cli":
            raw = cfg.get("dump_date")
            if raw is not None and str(raw).strip():
                return str(raw).strip()
            return date.today().isoformat()
        raw = cfg.get(attr)
        return "" if raw is None else str(raw).strip()

    def ask(attr: str, label: str) -> None:
        if getattr(args, attr, None) is not None:
            return
        default = default_for(attr)
        if default:
            sys.stdout.write(f"{label} [{default}]: ")
        else:
            sys.stdout.write(f"{label}: ")
        sys.stdout.flush()
        try:
            line = sys.stdin.readline()
        except EOFError:
            print(file=sys.stderr)
            return
        if not sys.stdin.isatty():
            sys.stdout.write("\n")
            sys.stdout.flush()
        line = line.rstrip("\r\n").strip()
        if not line:
            line = default
        setattr(args, attr, line)

    ask("media_serial1", "media_serial1")
    ask("media_serial2", "media_serial2")
    ask("box_serial", "box_serial")
    ask("box_barcode", "box_barcode")
    ask("pcb_serial", "pcb_serial")
    ask("dumper", "dumper")
    ask("region", "region")
    ask("languages", "languages")
    ask("dump_date_cli", "dump-date (YYYY-MM-DD)")
    print()
