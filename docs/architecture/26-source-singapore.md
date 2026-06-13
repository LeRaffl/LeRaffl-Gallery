# 26 · Source: Singapore (lta.gov.sg / M03 "Cars by Make" PDF)

Singapore's Land Transport Authority (LTA) publishes new-car registrations in
its **Monthly Vehicle Statistics** as PDFs. The file **M03 "New Registration of
Cars by Make"** breaks registrations down by `Make × Importer Type × Fuel Type`
and is the only current, official source with a fuel-type split. We parse it
positionally and upsert `data/Singapore.csv`.

## TL;DR

```
Source:    lta.gov.sg — Monthly Vehicle Statistics, file M03
URL:       https://www.lta.gov.sg/content/dam/ltagov/who_we_are/
           statistics_and_publications/statistics/pdf/M03-Car_Regn_by_make.pdf
Auth:      None
Format:    PDF table; rows = Make × Importer × Fuel Type, per-month sub-columns
           HB / SDN / MPV / STW / SUV / Conv / Total
Parse:     pdfplumber, positional — sum each month's per-row Total column across
           all makes, grouped by Fuel Type (scripts/fetch_singapore.py)
Variant:   Whole (all cars)
Coverage:  Rolling current half-year (≈6 recent months per fetch); older months
           stay in the CSV (upsert keyed on (period, variant))
Cadence:   Monthly; time_interval=monthly
Schedule:  Daily days 15-31, 08:00 UTC; commit-gated
Scripts:   scripts/fetch_singapore.py
Workflow:  .github/workflows/fetch-singapore.yml
```

## 1. Why this source (and not a clean API)

Investigated and rejected:

* **data.gov.sg** "New Registration of Cars by Make" (`d_d3f4d708…`) — has a
  fuel-type column and a clean CKAN JSON API, but is **frozen at 2025-05**.
  Useful only as a historical cross-check (it reproduces these figures exactly
  for the overlap).
* **SingStat Table Builder M650281** — current, but only the VQS categories
  (A/B/C/D); **no fuel/BEV split**.
* **Robbie Andrew's `singapore_carsales_monthly.csv`** — this same LTA data,
  pre-parsed and current; a convenient third-party fallback, but not the
  official primary.

The LTA M03 PDF is the official primary source that is both current and
fuel-typed.

## 2. Parsing M03 (`parse_m03`)

The PDF's text has zero-suppressed cells, so text parsing is ambiguous; we work
positionally with `pdfplumber.extract_words`:

1. The sub-header line carrying `HB SDN MPV STW SUV Conv Total` gives every body
   column's x-centre. Grouped in 7s, the **7th ("Total") of each block** is that
   month's total column; the `YYYY-MM` labels order the blocks.
2. Each data row's **fuel** is the suffix of its label (`Make Importer Fuel`),
   matched longest-first so `…(Plug-In)` wins over plain `…-Electric`.
3. Every numeric cell is assigned to its **nearest column**; only cells landing
   on a month-Total column are summed, per fuel, into the month.

Fuel mapping (`classify_fuel`, ordered rules):

```
Electric                    → BEV
Petrol-Electric (Plug-In)   → PHEV   (also Diesel-Electric (Plug-In))
Petrol-Electric             → HEV    (also Diesel-Electric; "plug" guarded
                                      against "non-plug")
Petrol                      → PETROL
Diesel                      → DIESEL
CNG / Petrol-CNG / Others   → OTHERS
```

Validation: the parser reproduces the known monthly fuel totals exactly, e.g.
2026-05 = BEV 2930 / PHEV 121 / HEV 1230 / PETROL 196 / DIESEL 1 (rows_ok=125,
rows_bad=0). Footnote/header lines are skipped (they carry no fuel suffix).

## 3. Fragility & maintenance

PDF layout parsing is inherently brittle. Guards in place:

* If a page's body-column count isn't a multiple of 7, that page is skipped
  (logged under `--debug`) rather than mis-parsed.
* `rows_bad` and any genuinely `unmapped` fuel labels are printed; watch these
  in the workflow log after an LTA format change.
* `--dry-run` prints the parsed monthly totals without writing — run it after
  any suspected layout change to confirm before committing.

If LTA changes the M03 layout and parsing breaks, the data.gov.sg datastore (for
≤2025-05) and Robbie Andrew's CSV (current) remain as cross-checks/fallbacks.

## 4. Upsert & idempotence

Keyed on `(period, variant)`, mirroring `fetch_malaysia.py`. The workflow's
commit step is change-gated, so steady-state daily runs are a no-op once the
latest month is present. `--since YYYY-MM` limits the upsert to recent months.
