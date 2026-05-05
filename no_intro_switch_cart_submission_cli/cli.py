"""CLI: scan releases, metadata, write submission XML."""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from no_intro_switch_cart_submission_cli.config_serial import (
    apply_cli_serial_overrides,
    fill_gameid2_from_media_serial1_if_empty,
    interactive_prompt_manual,
    load_config,
    merged_serial_fields,
    version1_rev_from_media_serial2,
)
from no_intro_switch_cart_submission_cli.constants import DUMP_FILE_RE
from no_intro_switch_cart_submission_cli.echo import print_metadata_residual_gaps, print_submission_metadata_echo
from no_intro_switch_cart_submission_cli.hashing import hash_file_streaming, hash_full_xci_synthetic
from no_intro_switch_cart_submission_cli.jakcron_subproc import run_nstool
from no_intro_switch_cart_submission_cli.nacp_pipeline import enrich_meta_net_with_jakcron_secure_nacp
from no_intro_switch_cart_submission_cli.paths import CONFIG_FILE, config_path_base, resolve_path, resolve_nstool_binary
from no_intro_switch_cart_submission_cli.releases import (
    _release_banner_label,
    card_id_comment,
    discover_releases,
    format_title,
    list_trusted_dump_submission_xmls,
    parse_filename_fallback,
    version_segment_for_submission_xml,
)
from no_intro_switch_cart_submission_cli.nstool_stdout import parse_cup_metadata, parse_jakcron_nstool_application_meta
from no_intro_switch_cart_submission_cli.cart_scan_ocr import (
    format_ocr_serial_snapshot_lines,
    ocr_scans_enabled,
    run_vlm_on_ocr_crop_debug_for_cli,
    try_fill_serial_row_from_scans_for_cli,
    vlm_debug_crops_requested,
)
from no_intro_switch_cart_submission_cli.xml_build import build_xml, safe_filename_segment

def main() -> int:
    ap = argparse.ArgumentParser(description="Batch No-Intro Switch cart submission XML (Trusted Dump).")
    ap.add_argument("--config", type=Path, default=CONFIG_FILE, help=f"Configuration file (default: {CONFIG_FILE})")
    ap.add_argument("--root", type=str, help="Override root directory to scan")
    ap.add_argument(
        "--force",
        action="store_true",
        help="Regenerate Submission.xml even when the release folder already contains one.",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Same skip rules as a normal run (existing Submission.xml in the release folder unless --force). "
            "For processed releases: resolve metadata (including jakcron --secure / NACP when needed), "
            "apply serial fields and optional --ocr-scans, then skip hashing and writing XML."
        ),
    )
    ap.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help=(
            "Prompt for manual submission fields not passed on the command line; configuration file values are shown in [brackets] and accepted with Enter. "
            "gameid2 and version1 are not prompted — derived from media_serial1 / media_serial2 when empty "
            "(use --gameid2 / --version1 to override)."
        ),
    )
    manual = ap.add_argument_group(
        "manual submission fields (override config for this run; applied to each release under "
        "--root). Use -i/--interactive to type values instead of flags.",
    )
    manual.add_argument("--gameid2", default=None, metavar="ID", help="Retail catalog id (e.g. LA-H-A8BWA).")
    manual.add_argument("--media-serial1", dest="media_serial1", default=None)
    manual.add_argument("--media-serial2", dest="media_serial2", default=None)
    manual.add_argument("--box-serial", dest="box_serial", default=None)
    manual.add_argument("--box-barcode", dest="box_barcode", default=None)
    manual.add_argument(
        "--pcb-serial",
        dest="pcb_serial",
        default=None,
        help='PCB marking; whole-field shortcuts: @ → ▼, $ → ▼ 10. Otherwise type Unicode or any text.',
    )
    manual.add_argument(
        "--version1",
        default=None,
        metavar="REV",
        help='Archive version1 (e.g. "Rev 009", "Rev 02"). When set, overrides auto rule from media_serial2.',
    )
    ap.add_argument(
        "--ocr-scans",
        dest="ocr_scans",
        action="store_true",
        help=(
            "After config/CLI serial fields, fill any still-empty media_serial1, media_serial2, box_serial, "
            "box_barcode, and pcb_serial from Scans/ (insert spread, cart front/back; see README). "
            "Requires scan_ocr.vlm_extract_command (vision-model argv with {image} and optional {role}) "
            "and Pillow for ROI crops."
        ),
    )
    ap.add_argument(
        "--ocr-dump-crops",
        dest="ocr_dump_crops",
        action="store_true",
        help=(
            "With scan processing enabled, write each ROI crop (PNG) per role under "
            "<release>/_ocr_crop_debug/ and print that path. "
            "<role>_raw.txt is left empty (legacy field). "
            "If the VLM/crop step raises for a role, crops are still written when possible and "
            "<role>_ocr_exception.txt records the error. Remove the folder after debugging. "
            "No effect without --ocr-scans or configuration OCR enabled."
        ),
    )
    ap.add_argument(
        "--vlm-debug-crops",
        dest="vlm_debug_crops",
        action="store_true",
        help=(
            "After scan VLM on full images, run ``scan_ocr.vlm_extract_command`` again on "
            "``<release>/_ocr_crop_debug/<role>_r0.png`` for insert_spread, cart_front, and "
            "cart_back, and merge the JSON into the serial row (same rules as ``vlm_fill_empty_only``). "
            "No effect unless that argv list is set in the configuration file (same as live-scan VLM). "
            "Requires ROI crops from a prior ``--ocr-dump-crops`` run (or ``scan_ocr.dump_crops``). "
            "Can also be enabled with ``\"scan_ocr\": { \"vlm_debug_crops\": true }`` in the configuration file."
        ),
    )
    ap.add_argument(
        "--submission-xml",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Verify mode: compare this * Submission.xml to a fresh Scans/ VLM fill, then exit "
            "(same behavior as python -m no_intro_switch_cart_submission_cli.verify_scans_xml). "
            "Does not scan --root or write XML. Optional --ocr-dump-crops / --vlm-debug-crops apply "
            "to the verify run the same way as in batch mode."
        ),
    )
    ap.add_argument(
        "--release-dir",
        type=Path,
        default=None,
        metavar="PATH",
        help="With --submission-xml: release folder for Scans/ (default: parent directory of the XML).",
    )
    ap.add_argument(
        "--compare",
        choices=("stored", "all"),
        default="stored",
        help="With --submission-xml: stored vs all (default: stored). Ignored without --submission-xml.",
    )
    manual.add_argument("--dumper", default=None, help="Override config dumper for this run.")
    manual.add_argument("--region", default=None)
    manual.add_argument("--languages", default=None)
    manual.add_argument("--dump-date", dest="dump_date_cli", default=None, metavar="YYYY-MM-DD")
    args = ap.parse_args()

    if args.submission_xml is not None:
        from no_intro_switch_cart_submission_cli.verify_scans_xml import verify_scans_against_submission_xml

        return verify_scans_against_submission_xml(
            args.config,
            args.submission_xml,
            args.release_dir,
            args.compare,
            dump_roi_crops=bool(args.ocr_dump_crops),
            vlm_debug_crops=bool(args.vlm_debug_crops),
            config_path_for_debug=args.config,
        )

    cfg = load_config(args.config)
    if getattr(args, "ocr_dump_crops", False) and not ocr_scans_enabled(cfg, args):
        print(
            "Warning: --ocr-dump-crops does nothing unless OCR runs (--ocr-scans or ocr_scans / scan_ocr in config).",
            file=sys.stderr,
        )
    path_base = config_path_base(cfg)
    root = resolve_path(args.root or cfg.get("root", "."), path_base)
    if root is None:
        print("Invalid root.", file=sys.stderr)
        return 1

    nstool_bin = resolve_nstool_binary(cfg, path_base)
    raw_pk = cfg.get("prod_keys", "prod.keys")
    if raw_pk is None or (isinstance(raw_pk, str) and raw_pk.strip() == ""):
        prod_keys: Path | None = None
    else:
        prod_keys = resolve_path(str(raw_pk), path_base)

    skip_hidden = cfg.get("skip_hidden", True)

    interactive_prompt_manual(args, cfg)

    dumper = str(cfg.get("dumper") or "").strip()
    if args.dumper is not None:
        dumper = args.dumper
    tool = cfg.get("tool") or "nxdt_rw_poc v2.0.0 (rewrite-dirty)"
    region = str(cfg.get("region") or "").strip()
    if args.region is not None:
        region = args.region
    cfg_langs = str(cfg.get("languages") or "").strip()
    if args.languages is not None:
        cfg_langs = args.languages
    dump_date = ""
    if args.dump_date_cli is not None:
        dump_date = str(args.dump_date_cli).strip()
    elif cfg.get("dump_date"):
        dump_date = str(cfg.get("dump_date")).strip()
    if not dump_date:
        dump_date = date.today().isoformat()

    if not args.dry_run:
        if prod_keys is not None and not prod_keys.is_file():
            print(f"ERROR: prod.keys path invalid or missing: {prod_keys}", file=sys.stderr)
            print(
                'Use "prod_keys": null so NSTool/nstools load ~/.switch/prod.keys (or keys.txt), '
                "or set a valid path.",
                file=sys.stderr,
            )
            return 1
        if not nstool_bin:
            print(
                'ERROR: nstool not found (install NSTool or set "nstool" in the configuration file).',
                file=sys.stderr,
            )
            return 1

    releases = list(discover_releases(root, skip_hidden))
    if not releases:
        print(f"No release folders under {root} (need a Default XCI with [0100…] in the name).")
        return 0

    written = 0
    for rel in releases:
        # Skip entirely if Submission.xml exists (no nstool/NACP/hash) unless --force.
        existing_subs = list_trusted_dump_submission_xmls(rel.directory)
        if not args.force and existing_subs:
            label = _release_banner_label(rel, root)
            shown = ", ".join(p.name for p in existing_subs[:3])
            extra = f" (+{len(existing_subs) - 3} more)" if len(existing_subs) > 3 else ""
            print(
                f"\n{label}: skip — folder already contains Submission.xml ({shown}{extra}); "
                "use --force to overwrite"
            )
            continue

        print(
            f"\n{_release_banner_label(rel, root)}: extracting metadata and hashing game files"
        )

        meta_net = None
        meta_cup = None
        nstool_can_use_home = nstool_bin and prod_keys is None
        nstool_can_use_k = nstool_bin and prod_keys is not None and prod_keys.is_file()

        if nstool_can_use_home or nstool_can_use_k:
            rc, ht_out = run_nstool(nstool_bin, prod_keys, rel.default_xci)
            if rc == 0 and ht_out.strip():
                meta_cup = parse_cup_metadata(ht_out)
                m_fn = DUMP_FILE_RE.match(rel.default_xci.name)
                v_tok = m_fn.group("vnum") if m_fn else ""
                jm = parse_jakcron_nstool_application_meta(
                    ht_out, v_tok or "", default_xci_basename=rel.default_xci.name
                )
                if jm and jm.get("base_title_ids"):
                    meta_net = jm
            else:
                print(f"  warn: nstool failed (exit {rc}); using filename fallback")
        elif not nstool_bin:
            print("  warn: skipping nstool (binary missing); using filename fallback")
        elif prod_keys is not None and not prod_keys.is_file():
            print("  warn: skipping nstool (prod.keys path invalid); using filename fallback")

        meta_net = enrich_meta_net_with_jakcron_secure_nacp(
            meta_net,
            nstool_bin=nstool_bin,
            prod_keys=prod_keys,
            default_xci=rel.default_xci,
            cfg=cfg,
        )
        print_metadata_residual_gaps(meta_net)
        print_submission_metadata_echo(meta_net)

        gn, _, tid_fn = parse_filename_fallback(rel.default_xci.name)
        m_file = DUMP_FILE_RE.match(rel.default_xci.name)
        v_internal = m_file.group("vnum") if m_file else ""

        if meta_net and meta_net.get("base_title_ids"):
            title_parts = [format_title(t) for t in (meta_net.get("titles") or []) if str(t).strip()]
            game_name = ", ".join(title_parts) if title_parts else (gn or rel.directory.parent.name)
            gameid1 = ", ".join(meta_net["base_title_ids"])
            ver_str = ", ".join(meta_net["versions"])
            upd_str = ", ".join(meta_net["updates"])
            langs = cfg_langs or ",".join(meta_net["languages"])
        elif meta_cup and meta_cup.get("cup_title_id"):
            base_title = gn or rel.directory.parent.name
            game_name = format_title(base_title)
            gameid1 = meta_cup["cup_title_id"]
            ver_str = meta_cup.get("display_version") or ""
            upd_str = v_internal
            langs = cfg_langs
        else:
            game_name = gn or rel.directory.parent.name
            gameid1 = tid_fn.upper() if tid_fn else ""
            ver_str = ""
            upd_str = v_internal
            langs = cfg_langs

        if not rel.initial_data and not rel.full_xci_on_disk:
            print("  skip: need Initial Data .bin for synthetic Full XCI hashes, or a Full XCI file present")
            continue

        v_xml = version_segment_for_submission_xml(rel.default_xci)
        base_parts = [safe_filename_segment(game_name)]
        if v_xml:
            base_parts.append(safe_filename_segment(v_xml))
        base_parts.extend(
            [safe_filename_segment(dumper or "unknown"), dump_date],
        )
        out_name = " - ".join(base_parts) + " Submission.xml"
        out_path = rel.directory / out_name

        serial_row = merged_serial_fields(cfg)
        serial_row = apply_cli_serial_overrides(args, serial_row)
        for ocr_ln in try_fill_serial_row_from_scans_for_cli(rel.directory, serial_row, cfg, args):
            print(f"  {ocr_ln}")
        for vlm_ln in run_vlm_on_ocr_crop_debug_for_cli(
            rel.directory, serial_row, cfg, args, config_path=args.config
        ):
            print(f"  {vlm_ln}")
        fill_gameid2_from_media_serial1_if_empty(serial_row)
        if args.version1 is not None:
            v1s = args.version1.strip()
            version1_rev = v1s if v1s else None
        else:
            version1_rev = version1_rev_from_media_serial2(serial_row["media_serial2"])

        if ocr_scans_enabled(cfg, args):
            for snap_ln in format_ocr_serial_snapshot_lines(serial_row, version1_rev):
                print(f"  {snap_ln}")

        if args.dry_run:
            print(f"  would write: {out_path.name}")
            written += 1
            continue

        sz1, c1, m1, s1, h256_1 = hash_file_streaming(rel.default_xci)
        file_default = {
            "size": str(sz1),
            "crc32": c1,
            "md5": m1,
            "sha1": s1,
            "sha256": h256_1,
            "version": ver_str,
            "update_type": upd_str,
        }

        file_initial = None
        if rel.initial_data:
            iz, ic, im, is_, ih = hash_file_streaming(rel.initial_data)
            file_initial = {
                "size": str(iz),
                "crc32": ic,
                "md5": im,
                "sha1": is_,
                "sha256": ih,
            }

        if rel.initial_data:
            fsz, fc, fm, fs, fh256 = hash_full_xci_synthetic(rel.initial_data, rel.default_xci)
            file_full = {
                "size": str(fsz),
                "crc32": fc,
                "md5": fm,
                "sha1": fs,
                "sha256": fh256,
            }
        else:
            fsz, fc, fm, fs, fh256 = hash_file_streaming(rel.full_xci_on_disk)
            file_full = {
                "size": str(fsz),
                "crc32": fc,
                "md5": fm,
                "sha1": fs,
                "sha256": fh256,
            }

        comment1 = ""
        if rel.card_id_set:
            comment1 = card_id_comment(rel.card_id_set)

        xml_body = build_xml(
            game_name=game_name,
            region=region,
            languages=langs,
            gameid1=gameid1,
            gameid2=serial_row["gameid2"],
            version1_rev=version1_rev,
            dumper=dumper,
            tool=tool,
            dump_date=dump_date,
            comment1=comment1,
            media_serial1=serial_row["media_serial1"],
            media_serial2=serial_row["media_serial2"],
            pcb_serial=serial_row["pcb_serial"],
            box_serial=serial_row["box_serial"],
            box_barcode=serial_row["box_barcode"],
            file_default=file_default,
            file_initial=file_initial,
            file_full=file_full,
        )

        out_path.write_text(xml_body, encoding="utf-8")
        print(f"  wrote: {out_path.name}")
        written += 1

    print(f"\nDone. {written} submission file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
