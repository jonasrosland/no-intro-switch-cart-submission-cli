"""
Trusted Dump submission XML batch tool. Config: no_intro_submit.json in repo root.

Run: ``python3 -m no_intro_switch_cart_submission_cli`` (not ``…cli`` — see package ``__main__``).
"""

from __future__ import annotations

from typing import Any

__all__ = ["main"]


def __getattr__(name: str) -> Any:
    """Lazy ``main`` so ``-m no_intro_switch_cart_submission_cli.cli`` does not load ``cli`` during package init."""
    if name == "main":
        from no_intro_switch_cart_submission_cli.cli import main as _main

        return _main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
