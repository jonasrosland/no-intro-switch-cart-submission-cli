# no-intro-switch-cart-submission-cli

Batch-generate **No-Intro Trusted Dump** submission XML for Nintendo Switch cartridge dumps with nxdt output (Default XCI with `[0100…][v…]` in the name).

## Acknowledgements

Trusted Dump **XML shape** and **synthetic Full XCI** hashing are modeled on **[No-Intro Switch Cart Submission Tool](https://github.com/rarenight/No-Intro-Switch-Cart-Submission-Tool)** (rarenight). This project uses a **different metadata toolchain** (jakcron NSTool + `nstools` / NACP instead of hactoolnet in rarenight’s GUI), with minor changes to how output is calculated.

This tool was built using Composer 2 through Cursor.

## Requirements

- **Python 3.10+**
- **jakcron [NSTool](https://github.com/jakcron/nstool)** (CLI) on `PATH` or configured in the configuration file
- **`pip install -r requirements.txt`** (PyPI `nstools` — RomFS / NACP parsing after extract; **Pillow** for optional **`Scans/`** ROI crops and vision-model crops)
- **`scan_ocr.vlm_extract_command`** — argv list for a helper that reads each ROI crop and prints JSON (see **Optional VLM-powered OCR of scanned images**); not bundled in the default **Dockerfile**
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

Default configuration path is **`no_intro_submit.json`** in the **repository root** (same folder as `no_intro_switch_cart_submission_cli/`); use **`--config /path/to/file.json`** to override. Typical keys match **`no_intro_submit.example.json`**: **`root`**, **`nstool`**, **`prod_keys`**, **`dumper`**, **`tool`**, **`region`**, **`languages`**, **`dump_date`**, **`skip_hidden`**, **`jakcron_extract_temp_dir`** (parent folder for jakcron secure extract; relative to **`path_root`**, default example **`temp-extract`**), optional **`ocr_scans`** / **`scan_ocr`** for **`Scans/`** serial extraction (see **Optional VLM-powered OCR of scanned images** below), plus the catalog serial fields below (and optional **`path_root`** for Docker). If **`jakcron_extract_temp_dir`** is omitted, **`<cwd>/temp-extract`** is used instead.

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

### Optional VLM-powered OCR of scanned images

Completely optional, but if you want to try this feature it *can* be helpful in reading the serials from backs of covers, and front/back of carts. **Always verify manually**, as VLMs (Vision Language Models) can make mistakes, just like any other OCR tool. I tried using `tesseract` and it's OCR functionality to perform this task, but the results were unfortunately not good enough.

This option expects **up to three** scans per title (by filenames or `scan_ocr.files` in the configuration file):

| Role | Typical content | Optional? |
|------|-----------------|-----------|
| **insert_spread** | Full scan of **retail insert** (front + spine + back in one wide image) | Matched only by **`scan_ocr.files`** or default **`fnmatch`** patterns (e.g. `*spread*`, `*flatbed*`); see **Discovery** below |
| **cart_front** | **Cartridge front** (LA-H-… → **`media_serial1`**) | Yes if you only have packaging scans |
| **cart_back** | **Cartridge back** (**`media_serial2`**, **`pcb_serial`**) | Yes |

Other photos in **`Scans/`** (inside cover, reverse insert, camera extras, etc.) are **ignored** unless you map them with **`scan_ocr.files`** or they match a role pattern. They are **not** cropped, sent to a VLM, or written to **`_ocr_crop_debug`**.

**Vision model on ROI crops:** set **`scan_ocr.vlm_extract_command`** to an argv list (see below). The tool applies the same **ROI crops** (grayscale, autocontrast, resize) as for **`--ocr-dump-crops`**; **`{image}`** is each **temporary crop PNG** in turn (not the full flatbed). Each role triggers **one subprocess per ROI** (e.g. two ROIs → two calls). Set **`vlm_timeout_seconds`** high enough for the slowest role (**`insert_spread`** uses **two** HTTP calls per crop in **`lmstudio_serial_extract.py`** — **`box_serial`** then **`box_barcode`**).

Enable with **`"ocr_scans": true`**, **`"scan_ocr": { "enabled": true, … }`**, or **`--ocr-scans`**. **`--ocr-dump-crops`** (or **`"scan_ocr": { "dump_crops": true }`**) writes each ROI crop to **`<release folder>/_ocr_crop_debug/`** (and **`{role}_raw.txt`** as an empty legacy slot); delete that folder when done.

**`Scans/`** next to the **version** folder is preferred (e.g. `Dumps/Cyber Shadow/Scans/` next to `…/1.0.5/`); otherwise **`Scans/`** inside the release folder is used.

#### VLM hook (`vlm_extract_command`)

Without bundling PyTorch or any model in the default **Dockerfile** / **`requirements.txt`**, set **`scan_ocr.vlm_extract_command`** to an **argv list** (no shell): each string may contain **`{image}`** — the **absolute path** to each **ROI crop** (same preprocessing as **`--ocr-dump-crops`**). **`{role}`** may appear for **`insert_spread`**, **`cart_front`**, or **`cart_back`**. The command must print **one JSON object** on stdout, with any subset of:

**`media_serial1`**, **`media_serial2`**, **`box_serial`**, **`box_barcode`**, **`pcb_serial`**

Unknown keys are ignored. Trailing prose is tolerated if the first ``{`` starts a valid JSON object. Markdown JSON code fences are stripped.

- **`vlm_timeout_seconds`** (default **120**) — subprocess timeout **per** VLM invocation (each ROI crop is a separate run).
- **`vlm_fill_empty_only`** (default **true**) — only fill keys still empty after earlier steps (including prior ROI passes for that role); set **`false`** so each VLM response can overwrite non-empty values for keys it returns.

**Bundled helper — LM Studio (OpenAI-compatible server, e.g. on a LAN GPU):** no PyTorch in the submission venv — only stdlib **`urllib`**. Start the **local server** in LM Studio, then point **`vlm_extract_command`** at **`scripts/lmstudio_serial_extract.py`** with **`--base-url`** (must include the **`/v1`** suffix, e.g. **`http://10.1.1.110:1234/v1`**) and **`--model`** set to the exact id LM Studio shows for the loaded checkpoint. Omit **`--model`** to pick the **first** id from **`GET /v1/models`** when only one model is loaded. Pass **`--role {role}`** so the helper only asks for fields that exist on that scan (**`cart_front`** → **`media_serial1`** only, etc.). Example (replace paths, URL, and model id)::

    "vlm_extract_command": [
      "python3", "/ABS/PATH/TO/Gamecard/scripts/lmstudio_serial_extract.py",
      "--base-url", "http://10.1.1.110:1234/v1",
      "--model", "your-model-id-from-lm-studio",
      "--role", "{role}",
      "{image}"
    ]

For **`insert_spread`**, **`lmstudio_serial_extract.py`** sends **two** HTTP requests per crop (**`box_serial`**, then **`box_barcode`**); **`cart_front`** and **`cart_back`** use **one** each. There are no automatic retries — size **`vlm_timeout_seconds`** for that many round-trips per subprocess invocation.

**OlmOCR and other document VLMs:** any wrapper that accepts an image path, runs your model (e.g. [allenai OlmOCR](https://github.com/allenai/olmocr)), and prints **one JSON object** on stdout with the keys above can be listed in **`vlm_extract_command`** the same way — use **`{image}`** / **`{role}`** placeholders like the bundled scripts.

**External runners (Ollama, etc.):** e.g. **`["ollama", "run", "--format", "json", "minicpm-v", "…prompt… {image}"]`** — match your local install; **`--format json`** helps when supported.

The tool reads **each assigned image** by role and merges VLM JSON per field rules below. The insert spread defaults to **one** ROI: the **bottom** of the frame, horizontally the **right quarter** of the width — i.e. the **right half of the left half** (**x = 0.25–0.5**), where the barcode and **HAC-P-** / **TSA-HAC-** line often sit on a wide scan. Override **`scan_ocr.rois`** when your barcode sits elsewhere. Cart photos default to **stamp ROIs** unless overridden. The tool fills **only still-empty** **`media_serial1`**, **`media_serial2`**, **`box_serial`**, and **`box_barcode`** unless **`vlm_fill_empty_only`** is **false**. Field **role** sourcing (**`media_serial1`** from **cart_front**, etc.) is unchanged.

**Merge rules (which scan wins when both see a code):**

- **`box_serial` / `box_barcode`** — **insert_spread** only (cart photos are **not** used for box fields).
- **`media_serial1`** — **cart_front** only (LA-H-… on the cartridge face).
- **`media_serial2`** — **cart_back** only (laser etch and/or ``TSA-HAC-…`` on the cart reverse).
- **`pcb_serial`** — **cart_back** only.

**Discovery:** (1) **`scan_ocr.files`** maps each role to a **basename** under `Scans/`; (2) else **fnmatch** on the filename (`scan_ocr.role_patterns` overrides defaults — default insert patterns include `*spread*`, `*flatbed*`, etc., but not `*insert*` so names like `reverse-insert.jpg` are not picked up); (3) if **`"assign_by_sorted_order": true`**, any role that is still empty gets the next unused image in **sorted filename order**, following **insert_spread** → **cart_front** → **cart_back** — use this when filenames are generic (e.g. camera rolls) but you **always order** the three shots the same way before running the tool.

The tool does **not** inspect image content to guess roles. If nothing matches a role, that role is left unset and any extra files in `Scans/` are simply ignored. For predictable cart roles you need **`scan_ocr.files`**, filenames that match the defaults, or **`assign_by_sorted_order`**.

**`box_barcode`:** twelve digit characters (spaced retail line or digit-heavy line); compact runs are normalized to **`d ddddd ddddd d`**. **Thirteen-digit** runs are **not** used. When a twelve-digit read **fails the GTIN check digit**, the tool tries **single** digit substitutions in priority order (**0** vs **5** first, then a few other common confusions) and uses the **first** substitution that yields a valid check digit.

**`box_serial`:** **`HAC-P-`** plus five alphanumerics (retail catalog id on the case). On the **insert** strip, a **`TSA-HAC-…`**-shaped line is **not** copied into **`media_serial2`** (that field is filled only from **cart_back**). Parsing tolerates OCR spacing, Unicode dashes, or a missing hyphen between **`C`** and **`P`**. Matches that overlap an **`XXX-HAC-P-`** prefix inside a longer media-style string are ignored.

**Dependencies:** **Pillow** is required for ROI cropping. The default **Dockerfile** does **not** install PyTorch or local VLM weights; run **`vlm_extract_command`** on the host or a machine with your model stack.

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

## Verify ``Scans/`` VLM output against an existing submission

After you have a ``* Submission.xml`` and the same **``Scans/``** layout used for OCR, you can re-run the VLM pipeline into a blank serial row and compare to the XML (same ``scan_ocr.vlm_extract_command`` as normal runs):

```bash
python3 -m no_intro_switch_cart_submission_cli.verify_scans_xml \
  --config no_intro_submit.json \
  --submission-xml "games/Cyber Shadow/1.0.5/Cyber Shadow - v16 - dumper - 2026-04-28 Submission.xml" \
  --release-dir "games/Cyber Shadow/1.0.5"
```

The same **``--submission-xml``**, **``--release-dir``**, and **``--compare``** options work on **``no_intro_batch_submit.py``** (and **``python -m no_intro_switch_cart_submission_cli.cli``**): when **``--submission-xml``** is set, the program runs verify only and exits (**``--root``** is ignored). You may add **``--ocr-dump-crops``** on the same invocation (same behavior as the main batch tool).

**Shell (zsh/bash):** for a command split across lines, the backslash must be the **last character** on the line — **no space after** **`\`**. A stray **`\ `** breaks continuation so the next line may run as a new command (e.g. **``command not found: --submission-xml``**).

**``--release-dir``** is the version folder next to (or containing) **``Scans/``** — the same directory the main CLI uses as the release folder. If omitted, the XML file’s parent directory is used.

By default (**``--compare stored``**), only fields that are **non-empty in the XML** must match the VLM (so you can check a partial submission). Use **``--compare all``** to require every serial field to match, including empty-in-XML vs non-empty VLM. Exit code **``1``** on mismatch, **``0``** when comparison passes. **``box_serial``** is compared after normalizing common formatting drift (e.g. XML ``HAC P AT5VA`` vs VLM ``HAC-P-AT5VA``).

## License

This project is licensed under the [MIT License](LICENSE).

## Tests

```bash
python3 -m unittest discover -s tests -v
```

No ROM images required — checks stdout parsing and **when** NACP enrichment would be requested.

## Security

Do **not** commit `prod.keys`, `title.keys`, or ROM images. They are listed in `.gitignore`. The default jakcron extract directory **`temp-extract/`** (under your process **current working directory**) may contain short-lived decrypted partition data; it is gitignored and you can delete it after a run.
