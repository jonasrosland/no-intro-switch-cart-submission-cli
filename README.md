# no-intro-switch-cart-submission-cli

Batch-generate **No-Intro Trusted Dump** submission XML for Nintendo Switch cartridge dumps with nxdt output (Default XCI with `[0100…][v…]` in the name).

## Acknowledgements

Trusted Dump **XML shape** and **synthetic Full XCI** hashing are modeled on **[No-Intro Switch Cart Submission Tool](https://github.com/rarenight/No-Intro-Switch-Cart-Submission-Tool)** (rarenight). This project uses a **different metadata toolchain** (jakcron NSTool + `nstools` / NACP instead of hactoolnet in rarenight’s GUI), with minor changes to how output is calculated.

This tool was built using Composer 2 through Cursor.

## Requirements

- **Python 3.10+**
- **jakcron [NSTool](https://github.com/jakcron/nstool)** (CLI) on `PATH` or configured in the configuration file
- **`pip install -r requirements.txt`** (PyPI `nstools` — RomFS / NACP parsing after extract; **Pillow** for optional **`Scans/`** ROI crops; **pytesseract** only needed when **`scan_ocr.use_tesseract`** is true / default)
- Optional **Tesseract** on **`PATH`** when using Tesseract-backed **`ocr_scans`** / **`--ocr-scans`** (not required for VLM-only: **`use_tesseract`: false** plus **`vlm_extract_command`**)
- **`prod.keys`** from Lockpick/firmware (or `null` in the configuration file to use files located in `~/.switch/` like normal for `nstool`)
- **USB dumps (recommended):** **[NX Dump Client](https://github.com/v1993/nxdumpclient)** — host app for **nxdumptool**; default output layout matches **Dump folder layout** below

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp no_intro_submit.example.json no_intro_submit.json
# Edit the configuration file (e.g. no_intro_submit.json) — paths are relative to this directory unless you set path_root
```

Default configuration path is **`no_intro_submit.json`** in the **repository root** (same folder as `no_intro_switch_cart_submission_cli/`); use **`--config /path/to/file.json`** to override. Typical keys match **`no_intro_submit.example.json`**: **`root`**, **`nstool`**, **`prod_keys`**, **`dumper`**, **`tool`**, **`region`**, **`languages`**, **`dump_date`**, **`skip_hidden`**, **`jakcron_extract_temp_dir`** (parent folder for jakcron secure extract; relative to **`path_root`**, default example **`temp-extract`**), optional **`ocr_scans`** / **`scan_ocr`** for **`Scans/`** OCR (see **Optional cart scan OCR** below), plus the catalog serial fields below (and optional **`path_root`** for Docker). If **`jakcron_extract_temp_dir`** is omitted, **`<cwd>/temp-extract`** is used instead.

You do not need **`skip_hidden`**, **`jakcron_basenca`**, **`title_keys`**, or a custom **`jakcron_extract_temp_dir`** unless you want non-default behavior (dot-folder scan; BKTR base NCA; extra Lockpick keys; extract parent path other than the example **`temp-extract`** under **`path_root`**).

### Dump folder layout

**Recommended dumping:** Use **[NX Dump Client](https://github.com/v1993/nxdumpclient)** with **nxdumptool** over USB. By default it writes a single-file gamecard **`.xci`** (plus **`(Initial Data)`** / **`(Card ID Set)`** bins when selected) into your chosen output folder — which matches what this tool expects.

**One cart = one folder.** Treat each release directory as holding **at most one** matching **Default** **`.xci`** (name includes **`[0100…]`** retail Title ID and **`[v…]`**). The scanner walks **`--root` recursively** and assigns **one** submission per folder that contains such an `.xci`.

An example layout (point **`--root`** at **`Dumps/`**; the tool recurses into each game and version folder):

```text
Dumps/
├── Cyber Shadow/
│   ├── Scans/                         (optional — insert spread, cart front/back; see README)
│   └── 1.0.5/
│       ├── Cyber Shadow 1.0.5 [01008D100DE46000][v196608] [NKA][NC][NT].xci
│       ├── Cyber Shadow 1.0.5 [01008D100DE46000][v196608] (Initial Data) (57A3A06C).bin
│       └── Cyber Shadow 1.0.5 [01008D100DE46000][v196608] (Card ID Set) (6CD8FDA1).bin   (optional)
└── Another Game/
    └── v393216/
        ├── Another Game 2.0 [0100ABCDEF012345][v393216] [NKA][NC][NT].xci
        └── Another Game 2.0 [0100ABCDEF012345][v393216] (Initial Data) (AB12CD34).bin
```

Each **version** folder (e.g. `1.0.5/`) should contain **one** release’s files — not multiple unrelated Default XCIs in the same directory.

### `sort_gamecard.sh` (optional organizer)

After dumping over USB, files often land in one flat folder (e.g. NX Dump Client’s default **Downloads**). **`sort_gamecard.sh`** is a small **bash** helper in the repo root that **reorganizes** nxdt-style dumps into **`Game title/<version>/`** (it parses the title and version token from each filename’s **`[0100…][v…]`** block).

The main CLI writes submission XML as **`Game - <version> - <dumper> - <YYYY-MM-DD> Submission.xml`**: **`<version>`** is taken from the nxdt basename when present (e.g. **`Aka 1.0.5 [0100…][v…].xci`** → **`1.0.5`**), else from a **version-shaped parent folder** (e.g. **`…/Aka/2.0.0/`**), else the bracket **`v…`** token so names stay unique. **`sort_gamecard.sh`** recognizes that pattern and moves orphaned **`… Submission.xml`** files into **`Title/<version>/`** when the embedded version parses as a version token; legacy **`Game - dumper - date Submission.xml`** names still go under **`Title/_metadata/`**.

- Run **`./sort_gamecard.sh`** for a **dry run** (lists planned moves only).
- Run **`./sort_gamecard.sh --execute`** to **apply** moves (creates directories as needed).
- By default the script walks the directory **that contains the script** (see **`SOURCE_ROOT`** at the top of the file if you symlink or copy the script elsewhere).

### Run the script

From the repository (venv activated, `no_intro_submit.json` in place):

```bash
python3 no_intro_batch_submit.py --root /path/to/dump-or-scan-root
# or: python3 -m no_intro_switch_cart_submission_cli --root …
```

Point **`--root`** at your organized tree (e.g. `Dumps/`) or any parent folder the tool should recurse under. Use **`--dry-run`**, **`--force`**, or **`-i`** when needed; see **`--help`** for every flag.

Example output:
```
❯ python no_intro_batch_submit.py --dry-run --force --root ../Submitted/Aka 

Aka: extracting metadata and hashing game files
  info: metadata (jakcron NSTool CLI)
      base_title_ids: 0100B0601852A000
      update_title_ids: 0100B0601852A800
      versions (display): v1.0.0
      updates (from filename token): v393216
      titles: Aka
      languages: De, En, Es, Fr, Ja, Ko, Pt
  would write: Aka - 1.0.6 - hitsaveorg - 2026-05-04 Submission.xml

Done. 1 submission file(s).
```

**Caveats**
- **Do not** point **`--root`** at a folder that mixes **two games** or **two different dumps** of the same game as separate Default XCIs: the tool still picks **one** Default (non‑Full) file — preferring a name that contains **`[NKA]`** among defaults, otherwise the first after sorting — and may pick the **wrong** file with no error.
- **Do not** use **split / multi-part** XCIs (`00`, `01`, …) as the input: merge or concatenate them first so you have **one** Default **`.xci`** whose name matches the pattern (e.g. via **NxDumpFuse** or copy `/b` as in the nxdumptool docs). Partial parts are not a valid “release” for this tool.
- **Full XCI** is optional and separate: the tool detects Full images via the marker at **`0x1A0`** and does **not** treat them as the Default. You may have **Default + Full** for the same cart in one folder; hashing still needs **Initial Data** or that Full file per the rules below.

**`[NKA][NC][NT]`** in the filename comes from **nxdumptool** options: **N**o **K**ey **A**rea prepended, **N**o **C**ertificate in the image, **N**o **T**rim (vs **`KA` / `C` / `T`** when those options are on). Same defaults → same tags; they do **not** disambiguate two different defaults in one folder.

To **write** submission XML, that folder must also have either an **`(Initial Data)`** **`.bin`** (hashes use synthetic Full XCI) **or** a **Full XCI** **`.xci`** on disk; otherwise metadata may run but the release is **skipped** with a short message. Optional: **`(Card ID Set)`** **`.bin`** for the Card ID block in XML.

If the folder already contains a Trusted Dump file whose name **ends with** **` Submission.xml`**, the whole release is **skipped** unless you specify **`--force`**.

`dump_date` may be omitted or `null`; it defaults to **today’s date** (`YYYY-MM-DD`, local calendar day). Override in the configuration file or with `--dump-date`.

**Metadata:** jakcron NSTool stdout first; if title, languages, or display version are still missing, jakcron **`--partN`** runs on **Control** NCAs only (spilled from the Default XCI via PyPI **`nstools`** — no full **`--secure`** yet). If that fails, jakcron **`--secure`** (temp dir) plus loose **`control.nacp`** / PyPI RomFS on disk / **`--part`** runs. NACP is taken only from **Control** NCAs (small RomFS); Default XCI hashing is streamed in chunks, not loaded whole into RAM.

**`--dry-run`** uses the same skip as a normal run (existing `… Submission.xml` unless **`--force`**). Processed releases still resolve metadata, apply serial fields and optional **`--ocr-scans`**, then skip hashing and XML write. Missing **`nstool`** / invalid **`prod_keys`** does **not** abort a dry run (you may see warnings and thinner metadata).

**`-i` / `--interactive`** prompts for manual fields not set on the CLI — not **`gameid2`** or **`version1`** (those are derived from **`media_serial1`** / **`media_serial2`** when blank; override with **`--gameid2`** / **`--version1`** if needed). JSON defaults appear in **`[brackets]`** ( **`dump_date`** null → today). CLI flags skip prompts. Prompts use line-buffered input; a real TTY is required (use **`docker run -it`** in containers).

### Serial fields and archive `version1`

Put catalog strings in the configuration file (**`dumper`**, **`tool`**, **`region`**, **`languages`**, **`gameid2`**, **`media_serial1`**, **`media_serial2`**, **`box_serial`**, **`box_barcode`**, **`pcb_serial`**, optional **`version1`**) or pass the corresponding CLI flags (see **`--help`**).

- **`gameid2`** — If blank but **`media_serial1`** is set, **`gameid2`** is derived by dropping a **trailing cart region** after the final hyphen when it matches a known code (e.g. **`LA-H-AACCA-EUR`** → **`LA-H-AACCA`**; **`USA`**, **`JPN`**, **`EUR`**, **`AUS`**, **`KOR`**, **`CHN`**, **`CHT`**, **`ASI`**, **`UKV`**, **`RUS`**, **`MSE`** — case-insensitive). Other suffixes are left unchanged. Any explicit **`gameid2`** wins.

- **`mediastamp`** — Not written to XML (this tool omits that attribute currently).

- **`pcb_serial`** — Optional whole-field shortcuts **`@`** → **`▼`** (U+25BC), **`$`** → **`▼ 10`** (same in JSON, **`--pcb-serial`**, and **`-i`**). Any other value is kept as entered.

- **`version1`** on **`<archive>`** — Auto-filled from **`media_serial2`** (trimmed) when the layout matches (digits copied **verbatim**, including leading zeros):
  - **11 characters:** last **three** decimal digits → e.g. **`Rev 000`**, **`Rev 009`**, **`Rev 623`**.
  - **13 characters:** digits at positions **9–10** (1-based) → e.g. **`Rev 00`**, **`Rev 02`**, **`Rev 12`**.
  - Any other length: no auto **`version1`**; set **`version1`** in the configuration file or **`--version1`** manually.

**`--version1`** always overrides the automatic rule.

### Optional cart scan OCR (`Scans/`)

Expect **up to three** photos per title (names or `scan_ocr.files` in the configuration file):

| Role | Typical content | Optional? |
|------|-----------------|-----------|
| **insert_spread** | Full flatbed of **retail insert** (front + spine + back in one wide image) | Prefer at least one; if nothing matches by name, the first sorted image in `Scans/` is treated as the insert |
| **cart_front** | **Cartridge front** (LA-H-… → **`media_serial1`**) | Yes if you only have packaging scans |
| **cart_back** | **Cartridge back** (**`media_serial2`**, **`pcb_serial`**) | Yes |

**Inside / reverse cover** flatbeds are **not** OCR’d or cropped by this tool (keep them in `Scans/` for your own archive if you like; they are ignored for role assignment and serial extraction).

**VLM-only (skip Tesseract):** set **`"use_tesseract": false`** under **`scan_ocr`** together with **`vlm_extract_command`**. The tool still applies the same **ROI crops** (grayscale, autocontrast, resize) as for OCR and for **`--ocr-dump-crops`**; the VLM runs **once per ROI** with **`{image}`** set to each temporary crop file (not the full flatbed). Each role therefore triggers **one subprocess per ROI** (e.g. two ROIs → two calls). Default **`use_tesseract`** is **true** (Tesseract on ROIs plus optional VLM on the **full** scan when a VLM command is set).

Enable with **`"ocr_scans": true`**, **`"scan_ocr": { "enabled": true, … }`**, or **`--ocr-scans`**. **`--ocr-dump-crops`** (or **`"scan_ocr": { "dump_crops": true }`**) writes each ROI crop and optional Tesseract text to **`<release folder>/_ocr_crop_debug/`** so you can verify framing; delete that folder when done.

With **`scan_ocr.vlm_extract_command`** set, **`--vlm-debug-crops`** (or **`"scan_ocr": { "vlm_debug_crops": true }`**) runs that command again on each role’s **`<role>_r0.png`** under **`_ocr_crop_debug/`** (first ROI) and merges the JSON into the serial row using the same **`vlm_fill_empty_only`** rules. Use after you have debug crops (e.g. from a prior **`--ocr-dump-crops`** run). Allow enough **`vlm_timeout_seconds`** for **three** extra subprocess invocations when this is enabled.

**`Scans/`** next to the **version** folder is preferred (e.g. `Dumps/Cyber Shadow/Scans/` next to `…/1.0.5/`); otherwise **`Scans/`** inside the release folder is used.

#### Optional VLM (vision model) hook

Yes — without bundling PyTorch or any model in the default **Dockerfile** / **`requirements.txt`**. Set **`scan_ocr.vlm_extract_command`** to an **argv list** (no shell): each string may contain **`{image}`** — the **absolute path** to either the **full scan** (default: Tesseract enabled and VLM runs after Tesseract) or, when **`use_tesseract`** is **false**, to each **ROI crop PNG** in turn (same preprocessing as **`--ocr-dump-crops`**). **`{role}`** may appear for **`insert_spread`**, **`cart_front`**, or **`cart_back`**. The command must print **one JSON object** on stdout, with any subset of:

**`media_serial1`**, **`media_serial2`**, **`box_serial`**, **`box_barcode`**, **`pcb_serial`**

Unknown keys are ignored. Trailing prose is tolerated if the first ``{`` starts a valid JSON object. Markdown JSON code fences are stripped.

- **`vlm_timeout_seconds`** (default **120**) — subprocess timeout.
- **`vlm_fill_empty_only`** (default **true**) — only fill keys still empty after earlier steps (Tesseract text and/or earlier ROI VLM passes); set **`false`** so each VLM response can overwrite non-empty values for keys it returns.

If **`vlm_extract_command`** is set, **Tesseract is optional** when **`use_tesseract`** is **false** (VLM-only on crops) or when you omit Tesseract on **`PATH`** (then only the VLM runs, on the **full** scan). Otherwise Tesseract must be on **`PATH`**.

**Python / Hugging Face (e.g. SmolVLM, no Ollama):** install **`pip install -r requirements-vlm.txt`**, then point **`vlm_extract_command`** at **`scripts/smolvlm_serial_extract.py`** (absolute path). Pass **`--role {role}`** so the helper only asks for fields that exist on that scan (**`cart_front`** → **`media_serial1`** only, etc.). Default model is **`HuggingFaceTB/SmolVLM-256M-Instruct`**. Example::

    "vlm_extract_command": [
      "python3", "/ABS/PATH/TO/Gamecard/scripts/smolvlm_serial_extract.py",
      "--model", "HuggingFaceTB/SmolVLM-256M-Instruct",
      "--role", "{role}",
      "{image}"
    ]

**LM Studio (OpenAI-compatible server, e.g. on a LAN GPU):** no PyTorch in the submission venv — only stdlib **`urllib`**. Start the **local server** in LM Studio, then point **`vlm_extract_command`** at **`scripts/lmstudio_serial_extract.py`** with **`--base-url`** (must include the **`/v1`** suffix, e.g. **`http://10.1.1.110:1234/v1`**) and **`--model`** set to the exact id LM Studio shows for the loaded checkpoint (example below uses **`smolvlm2-2.2b-instruct`**). Omit **`--model`** to pick the **first** id from **`GET /v1/models`** when only one model is loaded. Example (adjust the script path and model id if yours differs)::

    "vlm_extract_command": [
      "python3", "/ABS/PATH/TO/Gamecard/scripts/lmstudio_serial_extract.py",
      "--base-url", "http://10.1.1.110:1234/v1",
      "--model", "smolvlm2-2.2b-instruct",
      "--role", "{role}",
      "{image}"
    ]

For **`cart_back`**, the script may issue **one extra** HTTP request when the first reply leaves **both** **`media_serial2`** and **`pcb_serial`** empty (small VLMs are flaky). Pass **`--no-retry-on-empty`** in **`vlm_extract_command`** to disable that. For **`insert_spread`**, **`lmstudio_serial_extract.py`** and **`smolvlm_serial_extract.py`** send **two** requests per crop (**`box_serial`**, then **`box_barcode`**) and may send **one** more to retry **`box_serial`** when it is still invalid; pass **`--no-retry-on-insert-box`** to disable that retry. Allow enough **`vlm_timeout_seconds`** for **three** HTTP round-trips on **insert** crops when retries are enabled (two passes minimum).

**External runners (Ollama, etc.):** e.g. **`["ollama", "run", "--format", "json", "minicpm-v", "…prompt… {image}"]`** — match your local install; **`--format json`** helps when supported.

The tool reads **each assigned image** by role (Tesseract on ROIs when enabled, else VLM-only on those crops). The insert spread defaults to **one** ROI: the **bottom** of the frame, horizontally the **right quarter** of the width — i.e. the **right half of the left half** (**x = 0.25–0.5**), where the barcode and **HAC-P-** / **TSA-HAC-** line often sit on a wide scan. Override **`scan_ocr.rois`** when your barcode sits elsewhere. Cart photos default to **stamp ROIs** unless overridden. With Tesseract enabled, serial-like strings are parsed from OCR text; with VLM-only, serials come from the model’s JSON. The tool fills **only still-empty** **`media_serial1`**, **`media_serial2`**, **`box_serial`**, and **`box_barcode`** unless **`vlm_fill_empty_only`** is **false**. Field **role** sourcing (**`media_serial1`** from **cart_front**, etc.) is unchanged.

**Merge rules (which scan wins when both see a code):**

- **`box_serial` / `box_barcode`** — **insert_spread** only (cart photos are **not** used for box fields).
- **`media_serial1`** — **cart_front** only (LA-H-… on the cartridge face).
- **`media_serial2`** — **cart_back** only (laser etch and/or ``TSA-HAC-…`` on the cart reverse).
- **`pcb_serial`** — **cart_back** only.

**Discovery:** (1) **`scan_ocr.files`** maps each role to a **basename** under `Scans/`; (2) else **fnmatch** on the filename (`scan_ocr.role_patterns` overrides defaults); (3) if **insert_spread** is still unassigned, the first sorted image not already used for another role becomes the insert (legacy single-scan layout); (4) if **`"assign_by_sorted_order": true`**, any role that is still empty gets the next unused image in **sorted filename order**, following **insert_spread** → **cart_front** → **cart_back** — use this when filenames are generic (e.g. camera rolls) but you **always order** the three shots the same way before running the tool.

The tool does **not** inspect image content to guess roles; without names or patterns you only get a reliable **insert** from the first file (step 3). For cart photos you need either **meaningful names**, **`scan_ocr.files`**, or **`assign_by_sorted_order`**.

**`box_barcode`:** twelve digit characters (spaced retail line or digit-heavy line); compact runs are normalized to **`d ddddd ddddd d`**. **Thirteen-digit** runs are **not** used. When a twelve-digit read **fails the GTIN check digit**, the tool tries **single** digit substitutions in priority order (**0** vs **5** first, then a few other common confusions) and uses the **first** substitution that yields a valid check digit.

**`box_serial`:** **`HAC-P-`** plus five alphanumerics (retail catalog id on the case). On the **insert** strip, a **`TSA-HAC-…`**-shaped line is **not** copied into **`media_serial2`** (that field is filled only from **cart_back** OCR). Parsing tolerates OCR spacing, Unicode dashes, or a missing hyphen between **`C`** and **`P`**. Matches that overlap an **`XXX-HAC-P-`** prefix inside a longer media-style string are ignored.

**Dependencies:** **Pillow** is required for ROI cropping (including VLM-only). **`pip install -r requirements.txt`** also installs **pytesseract**; with **`use_tesseract`: true** (default), you need a **tesseract** binary on **`PATH`**. The **Dockerfile** installs **`tesseract-ocr`**.

OCR is **best-effort**; verify serials in the generated XML. Tune **`scan_ocr.rois`** (insert), **`scan_ocr.rois_by_role`** (per role), **`scan_ocr.role_patterns`**, or **`assign_by_sorted_order`** if your filenames differ.

### Docker

The image downloads **jakcron NSTool** at build time and installs it at **`/opt/nstool`** (release zip is **linux amd64**).

**1. Build the image** (from the repository root):

```bash
docker build -t no-intro-switch-cart-submission-cli .
```

**2. Configuration file for the container** — edit **`no_intro_submit.json`** next to your dumps and `prod.keys`, and set at least:

- **`"path_root": "/data"`** — relative paths resolve under the mount  
- **`"nstool": "/opt/nstool"`**  
- **`"prod_keys": "prod.keys"`** — and keep **`prod.keys`** in that same folder  

Omit **`path_root`** when running on the host without Docker.

**3. Run** — mount that folder at **`/data`** and point **`--root`** at the release directory inside the mount (cart dump folder containing the Default `.xci`):

```bash
cd /path/to/your/switch-cart-dumps

docker run --rm \
  -v "$PWD:/data" \
  no-intro-switch-cart-submission-cli \
  --config /data/no_intro_submit.json \
  --root "/data/games/Cyber Shadow/1.0.5"
```

Adjust **`--root`** to your layout. **`--dry-run`** resolves metadata and runs **`--ocr-scans`** when enabled, but does not hash or write XML.

## License

This project is licensed under the [MIT License](LICENSE).

## Tests

```bash
python3 -m unittest discover -s tests -v
```

No ROM images required — checks stdout parsing and **when** NACP enrichment would be requested.

## Security

Do **not** commit `prod.keys`, `title.keys`, or ROM images. They are listed in `.gitignore`. The default jakcron extract directory **`temp-extract/`** (under your process **current working directory**) may contain short-lived decrypted partition data; it is gitignored and you can delete it after a run.
