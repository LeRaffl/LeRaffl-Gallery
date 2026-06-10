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

## 4. Variants and self-throttle

```
VARIANT_CONFIG = {
    "Whole": {"sheets": ("AUTOS", "SUV"),  "csv": "data/Uruguay.csv"},
    "Vans":  {"sheets": ("UTILITARIO",),   "csv": "data/Uruguay_Vans.csv"},
    "HDV":   {"sheets": ("CAMIONES",),     "csv": "data/Uruguay_HDV.csv"},
    "Buses": {"sheets": ("OMNIBUS",),      "csv": "data/Uruguay_Buses.csv"},
}
```

The self-throttle checks each variant's CSV independently:
- If the latest period in the CSV is already ≥ the previous calendar month,
  that variant is skipped without downloading the workbook at all.
- The workbook is downloaded **once** and parsed for all pending variants.

**Whole as publication gate.** Before processing commercial variants, the script
parses the Whole (AUTOS+SUV) result and checks that `target_period` is present
with non-zero values. ACAU pre-fills the entire year with zeros and overwrites
month-by-month, so if Whole is still zero for the target month, none of the
commercial sheets will have data either. This avoids writing empty rows for
months not yet published.

## 5. Workflow

`.github/workflows/fetch-uruguay.yml` runs:

- **Daily from the 1st of each month** (`cron: '10 8 1-31 * *'`, 08:10 UTC,
  staggered from the 08:00 pile-up). Idempotent — the self-throttle makes all
  subsequent same-month runs a sub-second no-op once data is in the CSVs.
- The workflow commits all four CSVs (`data/Uruguay.csv`, `_Vans`, `_HDV`,
  `_Buses`) in one commit and then dispatches `render-country.yml` for each
  variant whose CSV appears in the commit diff.

Manual run:
```sh
python scripts/fetch_uruguay.py --variant all
# or force a re-parse of already-present periods:
python scripts/fetch_uruguay.py --variant hdv --force
# or point at a local file (useful when testing against an archived workbook):
python scripts/fetch_uruguay.py --url /tmp/compilado_2026.xlsx --year 2026
```

## 6. Gotchas

- **Timestamp-based filenames.** Never hard-code the Compilado URL — always
  scrape the homepage.
- **Pre-2026 layout is incompatible.** Do not run this parser against a 2025 or
  earlier Compilado; it will fail on the missing month headers or wrong sheet names.
- **MINIBUSES excluded.** The `MINIBUSES` sheet exists but is not ingested.
  Its EU-class ambiguity (M1/M2 boundary) and negligible volume make it not
  worth the complexity of deciding where it belongs in cross-country comparisons.
- **CRLF line endings.** `data/Uruguay.csv` was originally created with CRLF.
  The upsert function detects the on-disk line-ending convention and preserves
  it, so the diff stays clean.
- **Historical commercial data (pre-2026) is absent.** The 2026+ parser can't
  parse older files, and the maintainer did not bulk-import those years. Vans/HDV/
  Buses start from 2026-01. Backfilling earlier years would require a second
  parser targeting the 2025 layout.
