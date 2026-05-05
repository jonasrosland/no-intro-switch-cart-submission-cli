#!/usr/bin/env python3
"""
Run a small SmolVLM checkpoint locally and print one JSON object for ``scan_ocr.vlm_extract_command``.

Install extras first: ``pip install -r requirements-vlm.txt``

Example ``no_intro_submit.json`` (argv list, no shell). Use ``{role}`` so the model is only asked for
fields that exist on that scan (``insert_spread`` | ``cart_front`` | ``cart_back``)::

    "vlm_extract_command": [
      "python3", "/ABS/PATH/TO/Gamecard/scripts/smolvlm_serial_extract.py",
      "--model", "HuggingFaceTB/SmolVLM-256M-Instruct",
      "--role", "{role}",
      "{image}"
    ]

The parent CLI replaces ``{image}`` and ``{role}`` when invoking the command per scan file.
For ``insert_spread``, the script runs **two** model generations per image (``box_serial`` then ``box_barcode``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import vlm_serial_common as vlm  # noqa: E402


def _run_hf_image_text_to_text(model_id: str, image_path: Path, max_new: int, prompt: str) -> str:
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor

    processor = AutoProcessor.from_pretrained(model_id)
    dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
    kwargs: dict = {"dtype": dtype}
    if torch.cuda.is_available():
        kwargs["device_map"] = "auto"
    model = AutoModelForImageTextToText.from_pretrained(model_id, **kwargs)
    if not torch.cuda.is_available():
        model = model.to("cpu")

    conversation = [
        {
            "role": "user",
            "content": [
                {"type": "image", "path": str(image_path.resolve())},
                {"type": "text", "text": prompt},
            ],
        },
    ]
    inputs = processor.apply_chat_template(
        conversation,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
    )
    dev = next(model.parameters()).device
    inputs = inputs.to(dev)
    input_len = inputs["input_ids"].shape[1]
    output_ids = model.generate(**inputs, max_new_tokens=max_new, do_sample=False)
    new_tokens = output_ids[:, input_len:]
    return processor.batch_decode(new_tokens, skip_special_tokens=True)[0].strip()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "image",
        help="Path to scan image (use {image} placeholder in vlm_extract_command)",
    )
    ap.add_argument(
        "--model",
        default="HuggingFaceTB/SmolVLM-256M-Instruct",
        help="Hugging Face model id (SmolVLM / SmolVLM2 checkpoints using ImageTextToText).",
    )
    ap.add_argument(
        "--role",
        default=None,
        choices=("insert_spread", "cart_front", "cart_back"),
        help="Scan role (use {role} in vlm_extract_command). Strongly recommended.",
    )
    ap.add_argument("--max-new-tokens", type=int, default=384)
    args = ap.parse_args()
    path = Path(args.image)
    if not path.is_file():
        print(f"smolvlm_serial_extract: not a file: {path}", file=sys.stderr)
        sys.exit(1)

    raw = ""
    try:
        if args.role == "insert_spread":
            raw_s = _run_hf_image_text_to_text(
                args.model,
                path,
                args.max_new_tokens,
                vlm.prompt_insert_spread_box_serial_only(),
            )
            out_s = vlm.parse_and_postprocess_vlm_text(raw_s, "insert_spread")
            raw_b = _run_hf_image_text_to_text(
                args.model,
                path,
                args.max_new_tokens,
                vlm.prompt_insert_spread_box_barcode_only(),
            )
            out_b = vlm.parse_and_postprocess_vlm_text(raw_b, "insert_spread")
            out = vlm.merge_insert_spread_vlm_passes(
                out_s, out_b, raw_serial=raw_s, raw_barcode=raw_b
            )
            raw = f"{raw_s}\n--- insert barcode pass ---\n{raw_b}"
        else:
            prompt = vlm.prompt_for_role(args.role)
            raw = _run_hf_image_text_to_text(args.model, path, args.max_new_tokens, prompt)
            out = vlm.parse_and_postprocess_vlm_text(raw, args.role)
    except json.JSONDecodeError as e:
        tail = (raw or "")[:800]
        print(f"smolvlm_serial_extract: invalid JSON from model: {e}\n---\n{tail}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"smolvlm_serial_extract: {e}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(out), flush=True)


if __name__ == "__main__":
    main()
