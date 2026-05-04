"""Project paths: config JSON beside repo root (parent of package)."""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
CONFIG_FILE = PROJECT_ROOT / "no_intro_submit.json"


def resolve_path(p: str | None, base: Path) -> Path | None:
    if not p:
        return None
    x = Path(p).expanduser()
    if not x.is_absolute():
        x = (base / x).resolve()
    return x


def config_path_base(cfg: dict | None) -> Path:
    # Resolve relative JSON paths; default repo root unless path_root is set.
    if not cfg:
        return PROJECT_ROOT
    raw = cfg.get("path_root")
    if raw is None or str(raw).strip() == "":
        return PROJECT_ROOT
    p = resolve_path(str(raw).strip(), PROJECT_ROOT)
    return p if p is not None else PROJECT_ROOT


def _jakcron_default_extract_parent() -> str | None:
    base = Path.cwd() / "temp-extract"
    try:
        base.mkdir(parents=True, exist_ok=True)
        if base.is_dir() and os.access(base, os.W_OK):
            return str(base.resolve())
    except OSError:
        pass
    return None


def _jakcron_extract_parent_dir(cfg: dict | None) -> str | None:
    c = cfg or {}
    raw = c.get("jakcron_extract_temp_dir", None)
    if raw is not None and str(raw).strip() != "":
        rp = resolve_path(str(raw).strip(), config_path_base(c))
        if rp is not None and rp.is_dir() and os.access(rp, os.W_OK):
            return str(rp)
    return _jakcron_default_extract_parent()


def _jakcron_tempdir_kwargs(prefix: str, cfg: dict | None) -> dict:
    d = _jakcron_extract_parent_dir(cfg)
    if d is not None:
        return {"prefix": prefix, "dir": d}
    return {"prefix": prefix}


def resolve_nstool_binary(cfg: dict, script_dir: Path) -> Path | None:
    import shutil

    seen: set[str] = set()
    candidates: list[Path] = []
    raw = cfg.get("nstool")
    if raw is not None and str(raw).strip():
        p = resolve_path(str(raw).strip(), script_dir)
        if p is not None:
            candidates.append(p)
    candidates.extend([script_dir / "nstool", Path.cwd() / "nstool"])
    for p in candidates:
        try:
            rp = p.resolve()
        except OSError:
            continue
        key = str(rp)
        if key in seen:
            continue
        seen.add(key)
        if rp.is_file():
            return rp
    w = shutil.which("nstool")
    return Path(w) if w else None
