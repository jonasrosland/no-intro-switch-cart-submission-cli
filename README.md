# no-intro-switch-cart-submission-cli

Batch-generate **No-Intro Trusted Dump** submission XML for Nintendo Switch cartridge dumps with nxdt output (Default XCI with `[0100…][v…]` in the name).

## Acknowledgements

Trusted Dump **XML shape** and **synthetic Full XCI** hashing are modeled on **[No-Intro Switch Cart Submission Tool](https://github.com/rarenight/No-Intro-Switch-Cart-Submission-Tool)** (rarenight). This project uses a **different metadata toolchain** (jakcron NSTool + `nstools` / NACP instead of hactoolnet in rarenight’s GUI), with minor changes to how output is calculated.

This tool was built using Composer 2 through Cursor.

## Requirements

- **Python 3.10+**
- **jakcron [NSTool](https://github.com/jakcron/nstool)** (CLI) on `PATH` or configured in the configuration file
- **`pip install -r requirements.txt`** (PyPI `nstools` — RomFS / NACP parsing after extract)
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

Default configuration path is **`no_intro_submit.json`** in the **repository root** (same folder as `no_intro_switch_cart_submission_cli/`); use **`--config /path/to/file.json`** to override. Typical keys match **`no_intro_submit.example.json`**: **`root`**, **`nstool`**, **`prod_keys`**, **`dumper`**, **`tool`**, **`region`**, **`languages`**, **`dump_date`**, **`skip_hidden`**, **`jakcron_extract_temp_dir`** (parent folder for jakcron secure extract; relative to **`path_root`**, default example **`temp-extract`**), plus the catalog serial fields below (and optional **`path_root`** for Docker). If **`jakcron_extract_temp_dir`** is omitted, **`<cwd>/temp-extract`** is used instead.

You do not need **`skip_hidden`**, **`jakcron_basenca`**, **`title_keys`**, or a custom **`jakcron_extract_temp_dir`** unless you want non-default behavior (dot-folder scan; BKTR base NCA; extra Lockpick keys; extract parent path other than the example **`temp-extract`** under **`path_root`**).

### Dump folder layout

**Recommended dumping:** Use **[NX Dump Client](https://github.com/v1993/nxdumpclient)** with **nxdumptool** over USB. By default it writes a single-file gamecard **`.xci`** (plus **`(Initial Data)`** / **`(Card ID Set)`** bins when selected) into your chosen output folder — which matches what this tool expects.

**One cart = one folder.** Treat each release directory as holding **at most one** matching **Default** **`.xci`** (name includes **`[0100…]`** retail Title ID and **`[v…]`**). The scanner walks **`--root` recursively** and assigns **one** submission per folder that contains such an `.xci`.

An example layout (point **`--root`** at **`Dumps/`**; the tool recurses into each game and version folder):

```text
Dumps/
├── Cyber Shadow/
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

Then run the main submission script and point **`--root`** at your organized tree (e.g. `Dumps/` as above).

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
  would write: Aka - v393216 - hitsaveorg - 2026-05-04 Submission.xml

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

**`--dry-run`** uses the same skip as a normal run (existing `… Submission.xml` unless **`--force`**). Processed releases still resolve metadata but skip hashing and XML write. Missing **`nstool`** / invalid **`prod_keys`** does **not** abort a dry run (you may see warnings and thinner metadata).

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

Run:

```bash
python3 no_intro_batch_submit.py --root /path/to/dump-folder
# equivalent: python3 -m no_intro_switch_cart_submission_cli --root …
```

Use **`--dry-run`**, **`--force`**, or **`-i`** as needed.

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

Adjust **`--root`** to your layout. **`--dry-run`** resolves metadata but does not write XML.

## License

This project is licensed under the [MIT License](LICENSE).

## Tests

```bash
python3 -m unittest discover -s tests -v
```

No ROM images required — checks stdout parsing and **when** NACP enrichment would be requested.

## Security

Do **not** commit `prod.keys`, `title.keys`, or ROM images. They are listed in `.gitignore`. The default jakcron extract directory **`temp-extract/`** (under your process **current working directory**) may contain short-lived decrypted partition data; it is gitignored and you can delete it after a run.
