"""CLI echo lines after metadata resolution."""
from __future__ import annotations


def print_submission_metadata_echo(meta: dict | None) -> None:
    print("  info: metadata (jakcron NSTool CLI)")
    if not meta or not meta.get("base_title_ids"):
        return

    def field(label: str, values: list | None, *, empty: str = "(empty)") -> None:
        vals = values or []
        s = ", ".join(str(x) for x in vals if str(x).strip())
        print(f"      {label}: {s if s else empty}")

    field("base_title_ids", meta.get("base_title_ids"))
    field("update_title_ids", meta.get("update_title_ids"))
    field("versions (display)", meta.get("versions"))
    field("updates (from filename token)", meta.get("updates"))
    field("titles", meta.get("titles"))
    field("languages", meta.get("languages"))


def print_metadata_residual_gaps(meta: dict | None) -> None:
    if not meta:
        return
    gaps: list[str] = []
    if not any(str(t).strip() for t in (meta.get("titles") or [])):
        gaps.append("application title(s)")
    if not (meta.get("languages") or []):
        gaps.append("languages")
    if not str((meta.get("versions") or [""])[0]).strip():
        gaps.append("display version")
    if gaps:
        print(
            "  info: metadata gaps remaining: "
            + ", ".join(gaps)
            + " — you can edit the XML by hand or verify prod.keys / disk space."
        )


