"""Subprocess calls to jakcron NSTool C++ CLI."""

from __future__ import annotations

import subprocess
from pathlib import Path


def run_nstool(nstool: Path, prod_keys: Path | None, xci: Path) -> tuple[int, str]:
    cmd = [str(nstool)]
    if prod_keys is not None:
        cmd.extend(["-k", str(prod_keys)])
    cmd.append(str(xci))
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout + ("\n" + r.stderr if r.stderr else "")


def run_nstool_secure_extract(
    nstool: Path, prod_keys: Path | None, xci: Path, out_dir: Path
) -> tuple[int, str]:
    base = [str(nstool)]
    if prod_keys is not None:
        base.extend(["-k", str(prod_keys)])
    variants = (
        base + ["--secure", str(out_dir), str(xci)],
        base + ["-x", "/secure", str(out_dir), str(xci)],
    )
    last_log = ""
    for cmd in variants:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=7200,
        )
        last_log = r.stdout + ("\n" + r.stderr if r.stderr else "")
        if r.returncode == 0:
            return 0, last_log
    return 1, last_log


def run_nstool_nca_partition_extract(
    nstool: Path,
    prod_keys: Path | None,
    nca_path: Path,
    part_flag: str,
    out_dir: Path,
    basenca: Path | None,
) -> tuple[int, str]:
    base = [str(nstool)]
    if prod_keys is not None:
        base.extend(["-k", str(prod_keys)])
    if basenca is not None and basenca.is_file():
        base.extend(["--basenca", str(basenca)])
    variants = (
        base + [part_flag, str(out_dir), str(nca_path)],
        base + ["-x", f"/{part_flag.removeprefix('--part')}", str(out_dir), str(nca_path)],
    )
    last_log = ""
    for cmd in variants:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=7200,
        )
        last_log = r.stdout + ("\n" + r.stderr if r.stderr else "")
        if r.returncode == 0:
            return 0, last_log
    return 1, last_log


def find_control_nacp_under_extract_root(root: Path) -> Path | None:
    hits: list[Path] = []
    try:
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if p.name.casefold() == "control.nacp":
                hits.append(p)
    except OSError:
        return None
    if not hits:
        return None

    def score(p: Path) -> tuple[int, int]:
        parts = [x.casefold() for x in p.parts]
        prefer_parent_ctrl = 1 if len(parts) >= 2 and parts[-2] == "control" else 0
        return (-prefer_parent_ctrl, len(str(p)))

    hits.sort(key=score)
    return hits[0]
