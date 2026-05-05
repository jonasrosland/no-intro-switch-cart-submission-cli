#!/usr/bin/env python3
"""
Call an LM Studio OpenAI-compatible server and print one JSON object for ``scan_ocr.vlm_extract_command``.

Configure the server URL and model in ``no_intro_submit.json`` (argv list — no environment variables).

Example ``scan_ocr`` block::

    "vlm_extract_command": [
      "python3", "/ABS/PATH/TO/Gamecard/scripts/lmstudio_serial_extract.py",
      "--base-url", "http://10.1.1.110:1234/v1",
      "--model", "smolvlm2-2.2b-instruct",
      "--role", "{role}",
      "{image}"
    ]

If ``--model`` is omitted, the first model id from ``GET {base-url}/models`` is used (single loaded model).

For ``--role cart_back`` only: if both ``media_serial2`` and ``pcb_serial`` are empty after the first
reply (common SmolVLM2 flake), the script sends **one** follow-up request with a shorter nudge
prompt unless ``--no-retry-on-empty`` is set.

For ``--role insert_spread`` the script sends **two** requests per image (``box_serial`` then ``box_barcode``)
so the model is not asked to read both in one reply. Optional **one** extra ``box_serial`` retry unless
``--no-retry-on-insert-box`` is set (up to **three** HTTP calls per insert crop). Size timeouts accordingly.

The parent CLI replaces ``{image}`` and ``{role}`` when invoking the command per scan file.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import sys
import urllib.error
import urllib.request
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import vlm_serial_common as vlm  # noqa: E402

# Second pass when cart_back returns nothing (vision models often flake on one try).
_CART_BACK_RETRY_PROMPT = (
    "Same Nintendo Switch **cartridge back** photo again.\n"
    "Return **one JSON object** with every key: media_serial1, media_serial2, box_serial, "
    "box_barcode, pcb_serial. Use \"\" where not applicable.\n"
    "You **must** read from the plastic and PCB:\n"
    "- **media_serial2**: the **printed** twelve-to-sixteen character **A–Z**/**0–9** line on the "
    "shell (no spaces in output). **Not** embossed **HAC-008**. Optional **TSA-HAC-…-REG** line "
    "if printed instead.\n"
    "- **pcb_serial**: **▼** and digits seen **through the contact slots** on the PCB (e.g. **▼ 10**). "
    "Use **@** / **$** shortcuts if needed.\n"
    "Leave **media_serial1**, **box_serial**, **box_barcode** as \"\".\n"
    "No markdown. No prose outside the JSON.\n"
)

_INSERT_BOX_RETRY_PROMPT = (
    "Same Nintendo Switch **retail insert** crop again.\n"
    "Return **one JSON object** with every key: media_serial1, media_serial2, box_serial, "
    "box_barcode, pcb_serial. Use \"\" for media_serial1, media_serial2, box_barcode, and pcb_serial.\n"
    "**box_serial** only — Find the printed code **HAC-P-** (H, A, C, hyphen, P, hyphen) then copy "
    "**exactly five** letters or digits after that second hyphen as one token (e.g. **HAC-P-ATSVA**). "
    "Do **not** use **LA-H-** cart lines, **TSA-HAC-** media lines, or the **barcode digit row**.\n"
    "No markdown. No prose outside the JSON.\n"
)


def _chat_completions_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/chat/completions"


def _models_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/models"


def _http_json(
    url: str,
    payload: dict | None,
    *,
    method: str = "POST",
    timeout: float,
) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"HTTP {e.code} from {url}: {err_body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"request failed for {url}: {e}") from e
    return json.loads(body)


def _resolve_model_id(base_url: str, model: str, timeout: float) -> str:
    t = (model or "").strip()
    if t:
        return t
    doc = _http_json(_models_url(base_url), None, method="GET", timeout=timeout)
    ids: list[str] = []
    for m in doc.get("data") or []:
        if isinstance(m, dict) and m.get("id"):
            ids.append(str(m["id"]))
    if not ids:
        raise RuntimeError("LM Studio returned no models; load a model and start the local server")
    return ids[0]


def _image_data_url(path: Path) -> str:
    raw = path.read_bytes()
    mime, _ = mimetypes.guess_type(path.name)
    if not mime:
        mime = "image/png"
    b64 = base64.standard_b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _run_lm_studio_chat(
    base_url: str,
    model_id: str,
    image_path: Path,
    prompt: str,
    *,
    max_tokens: int,
    timeout: float,
) -> str:
    payload = {
        "model": model_id,
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": _image_data_url(image_path)},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }
    doc = _http_json(_chat_completions_url(base_url), payload, timeout=timeout)
    choices = doc.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError(f"unexpected chat response (no choices): {json.dumps(doc)[:500]}")
    msg = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = msg.get("content") if isinstance(msg, dict) else None
    if not isinstance(content, str):
        raise RuntimeError(f"unexpected chat response (no message content): {json.dumps(doc)[:500]}")
    return content.strip()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "image",
        help="Path to scan image (use {image} placeholder in vlm_extract_command)",
    )
    ap.add_argument(
        "--base-url",
        required=True,
        help="LM Studio server base, e.g. http://10.1.1.110:1234/v1",
    )
    ap.add_argument(
        "--model",
        default="",
        help="Model id as shown in LM Studio (optional if only one model is listed on /v1/models)",
    )
    ap.add_argument(
        "--role",
        default=None,
        choices=("insert_spread", "cart_front", "cart_back"),
        help="Scan role (use {role} in vlm_extract_command). Strongly recommended.",
    )
    ap.add_argument("--max-tokens", type=int, default=512)
    ap.add_argument(
        "--request-timeout",
        type=float,
        default=180.0,
        help="HTTP timeout in seconds for each request (separate from scan_ocr.vlm_timeout_seconds).",
    )
    ap.add_argument(
        "--no-retry-on-empty",
        action="store_true",
        help="For cart_back only: do not send a second request when both media_serial2 and pcb_serial are empty.",
    )
    ap.add_argument(
        "--no-retry-on-insert-box",
        action="store_true",
        help="For insert_spread only: do not send a second request when box_serial is missing or malformed.",
    )
    args = ap.parse_args()
    path = Path(args.image)
    if not path.is_file():
        print(f"lmstudio_serial_extract: not a file: {path}", file=sys.stderr)
        sys.exit(1)

    raw = ""
    try:
        model_id = _resolve_model_id(args.base_url, args.model, args.request_timeout)
        if args.role == "insert_spread":
            raw_serial = _run_lm_studio_chat(
                args.base_url,
                model_id,
                path,
                vlm.prompt_insert_spread_box_serial_only(),
                max_tokens=args.max_tokens,
                timeout=args.request_timeout,
            )
            out_serial = vlm.parse_and_postprocess_vlm_text(raw_serial, "insert_spread")
            if (
                not args.no_retry_on_insert_box
                and not vlm.valid_box_serial_strict((out_serial.get("box_serial") or "").strip())
            ):
                raw_serial = _run_lm_studio_chat(
                    args.base_url,
                    model_id,
                    path,
                    _INSERT_BOX_RETRY_PROMPT,
                    max_tokens=args.max_tokens,
                    timeout=args.request_timeout,
                )
                out_serial = vlm.parse_and_postprocess_vlm_text(raw_serial, "insert_spread")
            raw_barcode = _run_lm_studio_chat(
                args.base_url,
                model_id,
                path,
                vlm.prompt_insert_spread_box_barcode_only(),
                max_tokens=args.max_tokens,
                timeout=args.request_timeout,
            )
            out_barcode = vlm.parse_and_postprocess_vlm_text(raw_barcode, "insert_spread")
            out = vlm.merge_insert_spread_vlm_passes(
                out_serial,
                out_barcode,
                raw_serial=raw_serial,
                raw_barcode=raw_barcode,
            )
            raw = f"{raw_serial}\n--- insert barcode pass ---\n{raw_barcode}"
        else:
            prompt = vlm.prompt_for_role(args.role)
            raw = _run_lm_studio_chat(
                args.base_url,
                model_id,
                path,
                prompt,
                max_tokens=args.max_tokens,
                timeout=args.request_timeout,
            )
            out = vlm.parse_and_postprocess_vlm_text(raw, args.role)
        if (
            args.role == "cart_back"
            and not args.no_retry_on_empty
            and not (out.get("media_serial2") or "").strip()
            and not (out.get("pcb_serial") or "").strip()
        ):
            raw = _run_lm_studio_chat(
                args.base_url,
                model_id,
                path,
                _CART_BACK_RETRY_PROMPT,
                max_tokens=args.max_tokens,
                timeout=args.request_timeout,
            )
            out = vlm.parse_and_postprocess_vlm_text(raw, args.role)
    except json.JSONDecodeError as e:
        tail = (raw or "")[:800]
        print(f"lmstudio_serial_extract: invalid JSON from model: {e}\n---\n{tail}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"lmstudio_serial_extract: {e}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(out), flush=True)


if __name__ == "__main__":
    main()
