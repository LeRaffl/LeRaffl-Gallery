# 25 · Source: Uruguay (ACAU Compilado xlsx)

ACAU (*Asociación del Comercio Automotor del Uruguay*, the Uruguayan automotive
trade association) publishes monthly new-registration data in a yearly Excel
workbook ("Compilado YYYY") on `www.acau.com.uy`. Four variants are extracted
from one shared workbook per year, so a single download serves all CSV updates.

## TL;DR

```
Source:    ACAU "Compilado YYYY" .xlsx from https://www.acau.com.uy/
Auth:      None
API:       None. Scrape the ACAU homepage for the year's Compilado link
           (filenames are timestamp-based and unpredictable), download xlsx.
Variants:  Whole (AUTOS + SUV), Vans (UTILITARIO), HDV (CAMIONES), Buses (OMNIBUS)
Coverage:  AUTOS+SUV from first data (pre-2026 Whole rows already in CSV);
           Vans/HDV/Buses from 2026-01 onward (new with this pipeline)
HEV:       Reported natively as "H" (Híbrido); split available for all variants
PHEV:      Reported as "PHEV" for all variants (2026+ layout)
OTHERS:    MHEV (mild hybrid) by maintainer convention — see note below
Backfill:  Pre-2026 history uses a different worksheet layout and wasn't
           bulk-imported; those rows are absent from the commercial CSVs
Schedule:  Daily from the 1st of each month, self-throttle per variant
Scripts:   scripts/fetch_uruguay.py
Workflow:  .github/workflows/fetch-uruguay.yml
```

## 1. The workbook

ACAU publishes two Excel files per year:

| File | Content | Used? |
|---|---|---|
| `Compilado YYYY` | Per-model rows, one sheet per vehicle category, monthly + YTD totals | ✅ |
| `Mercado YYYY` | Per-manufacturer monthly totals | ❌ (useful for cross-checking only) |

The download filename is unpredictable — something like `15_18_25ar1.xlsx`
(HH\_MM\_SS of the local Uruguay upload time + `ar1.xlsx`). A new file is
uploaded for the same year as each month is published, replacing the previous
one. We scrape the homepage for the current year's Compilado link by matching
the link text `"Compilado YYYY"` rather than the URL.

### Sheets

| Sheet | Variant | EU class | Notes |
|---|---|---|---|
| `AUTOS` + `SUV` | `Whole` | M1 | Summed together |
| `UTILITARIO` | `Vans` | N1 | Light commercial, includes pickups |
| `CAMIONES` | `HDV` | N2/N3 | Medium+heavy trucks |
| `OMNIBUS` | `Buses` | M2/M3 | Coaches and city buses |
| `MINIBUSES` | — | M1/M2 border | **Excluded** — ambiguous class, negligible volume |

### Sheet layout (2026+ format)

```
row 5:  "COMPILADO YYYY"          ← year header (cross-checked by parser)
row 6:  sheet kind ("AUTOMOVILES" / "S.U.V." …)
row 8:  column headers — includes "Combustible" and "Enero" … "Diciembre"
row 9+: data rows (one per model)
last:   "TOTAL" row with monthly totals (used as per-sheet sanity check)
```

The parser locates the header row dynamically by searching for the cell value
`"Combustible"`, so minor row-shifts survive. Month columns are matched against
the 12 Spanish month names and fail loudly if any are missing.

> **Pre-2026 files have a different layout** — sheet named `"MINI"` instead of
> `"MINIBUSES"`, per-brand subtotal rows, abbreviated month headers `"Ene"/"Feb"`/…,
> and no PHEV split. The current parser targets the 2026+ layout exclusively.
> Back-filling 2025 and earlier commercial variants would require a separate parser.

## 2. Fuel mapping

| ACAU code | CSV column | Notes |
|---|---|---|
| `E` | `BEV` | Eléctrico (battery-electric) |
| `PHEV` | `PHEV` | Plug-in híbrido (2026+ layout) |
| `H` | `HEV` | Híbrido (full / regular hybrid) |
| `N` | `PETROL` | Nafta (gasoline) |
| `D` | `DIESEL` | Diesel |
| `MHEV` | `OTHERS` | Mild hybrid — see note below |

**MHEV → OTHERS** is a maintainer convention: mild hybrids are bucketed into
`OTHERS` rather than mixed into `HEV` (which would inflate full-hybrid counts)
or absorbed into `PETROL`/`DIESEL` (where they technically belong but losing
the distinction makes the EV-share series jittery when manufacturers relabel
models). Unknown fuel codes encountered in future workbook revisions are also
folded into `OTHERS` with a `WARNING` printed to the action log.

## 3. Parsing logic

`parse_sheet(ws)` is stateless and generic: it works for all six sheets
because they share the identical 2026+ column layout. It returns
`({csv_col: [12 monthly floats]}, total_per_month_or_None)`.

`parse_workbook(wb_bytes, year, variant)` looks up the target sheet names from
`VARIANT_CONFIG[variant]["sheets"]`, calls `parse_sheet` for each, and sums the
per-fuel monthly arrays (only Whole has two sheets; others have one). It
cross-checks each sheet's per-fuel sum against the sheet's own `TOTAL` row and
raises loudly on any mismatch — if the cross-check fails, the parser almost
certainly missed rows due to a layout change.

Future months in the workbook are pre-filled with zeros. Any month where **all**
fuel values across the variant's combined sheets are zero is skipped — this
means the script can run mid-year without writing fake all-zero rows.

## 4. Variants, self-throttle, and publication gate

```
VARIANT_CONFIG = {
    "Whole": {"sheets": ("AUTOS", "SUV"),  "csv": "data/Uruguay.csv"},
    "Vans":  {"sheets": ("UTILITARIO",),   "csv": "data/Uruguay_Vans.csv"},
    "HDV":   {"sheets": ("CAMIONES",),     "csv": "data/Uruguay_HDV.csv"},
    "Buses": {"sheets": ("OMNIBUS",),      "csv": "data/Uruguay_Buses.csv"},
}
```

### target_period

Every run computes a **target period** — the month the script is trying to
fetch. It is always `"{year}-{prev_month:02d}"` where:

- `prev_month` = the previous calendar month (relative to today)
- `year` = the year being fetched: `--year` if given, otherwise the year
  of the previous calendar month

Examples (assuming today is 2026-06-10):

| Invocation | year | target_period |
|---|---|---|
| `(cron / no flags)` | 2026 | `2026-05` |
| `--year 2026` | 2026 | `2026-05` |
| `--year 2025` | 2025 | `2025-05` |

The target period is used for two things: the self-throttle check and the
publication gate check. It does **not** limit which months get written —
the script always upserts every non-zero month it finds in the workbook.

### Self-throttle

For each requested variant, the script reads the latest period already in
that variant's CSV. If `latest >= target_period`, the variant is skipped
and the workbook is not downloaded. Once all variants are current, the
run exits in under a second.

`--force` bypasses the self-throttle — every requested variant is
processed regardless of what's in the CSVs.

### Whole as publication gate

Before writing any commercial variant (Vans/HDV/Buses), the script parses
the Whole (AUTOS+SUV) result and checks that `target_period` is present
with non-zero values. ACAU pre-fills the entire calendar year with zeros
and overwrites month-by-month, so if Whole is still zero for the target
month, none of the commercial sheets will have data either. This avoids
writing empty rows for months not yet published.

`--force` also bypasses the gate — commercial variants are written even
if Whole is missing or zero for that month. Use with care.

## 5. Workflow

`.github/workflows/fetch-uruguay.yml` runs:

- **Daily from the 1st of each month** (`cron: '10 8 1-31 * *'`, 08:10 UTC,
  staggered from the 08:00 pile-up). Idempotent — the self-throttle makes all
  subsequent same-month runs a sub-second no-op once data is in the CSVs.
- Detects which of the four CSVs actually changed (pre-commit `git diff`)
  and dispatches `render-country.yml` only for those variants.

### CLI reference

```
python scripts/fetch_uruguay.py [--year YEAR] [--url URL_OR_PATH]
                                [--variant {whole,vans,hdv,buses,all}]
                                [--force]
```

| Flag | Default | Purpose |
|---|---|---|
| `--year` | year of previous calendar month | Which Compilado workbook to fetch / parse |
| `--url` | scraped from ACAU homepage | Direct xlsx URL or local file path (skips scrape) |
| `--variant` | `all` | Limit to one variant; `all` runs Whole + Vans + HDV + Buses |
| `--force` | off | Bypass self-throttle and publication gate; overwrite existing rows |

### Common operations

```sh
# Normal: fetch latest data for all variants (same as the cron job)
python scripts/fetch_uruguay.py

# Fetch only one variant
python scripts/fetch_uruguay.py --variant vans

# Backfill a year where the commercial CSVs don't have data yet
# (--force not needed — the self-throttle only skips if target_period
# is already in the CSV, and new variant CSVs start empty)
python scripts/fetch_uruguay.py --year 2026 --variant vans

# Re-parse periods that are already in the CSV (overwrite):
python scripts/fetch_uruguay.py --variant hdv --force

# Test against a local copy without hitting ACAU's server:
python scripts/fetch_uruguay.py --url /tmp/compilado_2026.xlsx --year 2026

# Force re-parse of a specific year + variant (overwrites existing rows):
python scripts/fetch_uruguay.py --year 2026 --variant whole --force
```

### Workflow dispatch inputs

The GitHub Actions workflow exposes the same flags as a `workflow_dispatch`
form with a `type: choice` dropdown for `variant` (options: `all`, `whole`,
`vans`, `hdv`, `buses`). Use the GitHub Actions UI or:

```sh
gh workflow run fetch-uruguay.yml \
  -f year=2026 -f variant=vans -f force=true
```

## 6. Gotchas

- **Timestamp-based filenames.** Never hard-code the Compilado URL — always
  scrape the homepage.

- **Pre-2026 layout is incompatible.** Do not run this parser against a 2025 or
  earlier Compilado; it will fail with missing month headers or wrong sheet names.
  Backfilling pre-2026 commercial data requires a separate parser targeting the
  2025 layout.

- **`--year` sets `target_period` relative to the fetched year, not today.**
  `--year 2026` in December 2027 gives `target_period = "2026-11"`. The
  self-throttle then checks whether `"2026-11"` is in the CSV; the gate checks
  whether `"2026-11"` is in the 2026 workbook. All months through November 2026
  are upserted (not just November). Use `--force` if you also need to overwrite
  months that are already in the CSV.

- **`--force` bypasses both the self-throttle and the publication gate.**
  It will overwrite existing rows and write commercial data even if Whole is
  missing for that month. Only use it when you know the workbook has correct
  data and you deliberately want to overwrite what's on disk.

- **First run after merge creates new CSV files.**
  `data/Uruguay_Vans.csv`, `data/Uruguay_HDV.csv`, `data/Uruguay_Buses.csv`
  don't exist on `master` yet. The first cron run after merging this PR creates
  them. The workflow's `git add -N` step covers untracked new files so render
  dispatch fires correctly on first creation.

- **MINIBUSES excluded.** The `MINIBUSES` sheet exists but is not ingested.
  Its EU-class ambiguity (M1/M2 boundary) and negligible volume make it not
  worth the complexity of deciding where it belongs in cross-country comparisons.

- **CRLF line endings.** `data/Uruguay.csv` was originally created with CRLF.
  The upsert function detects the on-disk line-ending convention and preserves
  it, so the diff stays clean. New CSVs are written with LF.
