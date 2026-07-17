---
country: Indonesia
slug: indonesia
status: live
summary: >-
  Wholesale (factory-to-dealer) figures for Indonesia from GAIKINDO's monthly
  "Wholesales" report.
source_name: "GAIKINDO — files.gaikindo.or.id (Wholesales PDF)"
source_url: "https://www.gaikindo.or.id/"
underlying: "GAIKINDO — Indonesian Automotive Industry Association"
auth: "client login to GAIKINDO's ProjectSend"
cadence: "daily 09:35 UTC, 10th–EOM (GAIKINDO publishes ~10th–15th)"
variants: [Whole, Pickups, HDV, Buses]
hev_split: true
backfill: none
scope_note: "Whole = GAIKINDO Passenger Car (≈ EU M1); figures are wholesales, not registrations."
caveats:
  - "Figures are wholesales (manufacturer shipments), not registrations."
  - "Access needs a client login to GAIKINDO's ProjectSend portal."
  - "A full fuel split incl. Petrol and Diesel is available."
fetcher: "scripts/fetch_indonesia.py"
workflow: ".github/workflows/fetch-indonesia.yml"
fragility_doc: "docs/architecture/30-source-indonesia.md"
data_file: "data/Indonesia.csv"
---

# 30 · Source: Indonesia (GAIKINDO wholesales PDF)

GAIKINDO (Gabungan Industri Kendaraan Bermotor Indonesia, the automotive
manufacturers association) publishes monthly cumulative **wholesales** PDFs on
its ProjectSend file portal. The wholesales file is the only GAIKINDO product
with a full fuel-type split (G/D/BEV/HEV/PHEV per model), which is why we parse
it instead of the retail/by-category files. Until 2025-12 the `Whole` series
was fed from R. Andrew's aggregation of the same source; from 2026-01 the
fetcher reads GAIKINDO directly — same scope, continuous series.

## TL;DR

```
Variants:
  Whole     data/Indonesia.csv           GAIKINDO "Passenger Car" (≈ EU M1):
                                         Sedan + 4x2 + 4x4 + LCGC
  Pickups   data/Indonesia_Pickups.csv   Pick ups GVW < 5 t + Double Cabins
  HDV       data/Indonesia_HDV.csv       Trucks ≥ 5 t GVW (incl. tractor heads)
  Buses     data/Indonesia_Buses.csv     Buses (all GVW bands)

Source:    files.gaikindo.or.id (ProjectSend) -> "Wholesales Jan-XXX YYYY" PDF
Auth:      client login, plain POST {csrf_token, do=login, username, password}
           to index.php — no captcha
Secrets:   INDONESIA_GAIKINDO_USER (plain env, default "LeRaffl")
           INDONESIA_GAIKINDO_PW   (GH Actions repo secret)
Schema:    BEV,PHEV,HEV,PETROL,DIESEL,OTHERS,TOTAL  (full fuel split)
Schedule:  Daily 10th-EOM at 09:35 UTC (GAIKINDO publishes ~10th-15th)
Scripts:   scripts/fetch_indonesia.py
Workflow:  .github/workflows/fetch-indonesia.yml
```

## 1. Semantics: wholesales, not registrations

GAIKINDO reports **factory→dealer wholesales** (and, separately, retail
sales; only wholesales carries the fuel split). Everything downstream —
footnotes, article wording — must say *sales/wholesales*, not registrations.
Monthly wholesales can lead retail by a few weeks around launches and
year-end stock pushes.

## 2. Portal & auth

* Public file list: `https://files.gaikindo.or.id/list-files.php` shows all
  titles (no login), but carries **no file IDs** — links point at the portal
  root. Historical yearly files ("Wholesales 2022" … "Wholesales 2025") exist
  there too; see § 7.
* The portal is a 2018-era **ProjectSend**. Login = GET `/` (grab
  `csrf_token` from the form), then POST to `index.php` with
  `{csrf_token, do=login, username, password}`. The reCAPTCHA strings in the
  page are inert translation bundles — the install has no captcha.
* After login the portal root redirects to the client list
  **`my_files/index.php`** (date-sorted newest-first, paginated; download
  links are `process.php?do=download&id=N`). The fetcher tries
  `?search=wholesales` first, then walks the first five plain pages, and
  picks the newest title matching `Wholesales Jan-<Mon> <Year>`. Month
  abbreviations appear in English *and* Indonesian (`Mei`, `Agu`, `Okt`,
  `Des`) — both are mapped. (`manage-files.php` renders its rows
  client-side and `list-files.php` carries no links even when logged in —
  neither is scrapeable.)
* `--download-url` (workflow input `download_url`) bypasses discovery if the
  portal layout shifts; `--pdf-path` bypasses the portal entirely (offline
  parse for testing).

## 3. The PDF: seven Excel sheets pasted at 1.56 pt

Three A3 pages, each a paste-up of per-model Excel sheets in ~1.56 pt font.
Sheet titles carry an Excel-artifact backtick date (`` `JAN-JUN 2026 ``) that
doubles as the coverage marker:

```
1. SEDAN TYPE SALES                    → Whole
2. 4X2 TYPE SALES                      → Whole      (spans pages; repeats title+header)
3. 4X4 TYPE SALES                      → Whole
4. BUS SALES                           → Buses
5. PICK UP/TRUCK SALES                 → Pickups (PICK UP GVW < 5 t subsection)
                                         / HDV (TRUCK GVW ≥ 5 t subsections)
6. DOUBLE CABIN SALES                  → Pickups
7. AFFORDABLE ENERGY SAVING CARS 4X2   → Whole      (LCGC; no "SALES" in title)
```

The last page ends with three summary rows — `PASSENGER CAR SALES TOTAL`,
`COMMERCIAL VEHICLE SALES TOTAL`, `DOMESTIC SALES TOTAL` — which confirm
GAIKINDO's own PC definition (they print "SEDAN, 4X2, 4X4, KBM HEMAT ENERGI &
TERJANGKAU") and anchor the validation.

Parsing gotchas, all handled in `scripts/fetch_indonesia.py`:

* **Tolerances**: at 1.56 pt, pdfplumber's default `y_tolerance=3` merges
  ~2 pt-high *rows* into word soup. Extraction runs at `x_tolerance=0.7`,
  `y_tolerance=0.4`; `pdftotext` silently drops most rows — don't use it.
* **Split numbers**: cells sometimes tokenize as `3 00` (= 300). Values are
  reassembled by concatenating all tokens inside a month's x-band (bands come
  from each sheet's own JAN..DEC header row; `.`/`,` are thousands separators,
  `-` = 0).
* **Wrapped rows**: long tyre-size texts push a row's numbers onto a second
  visual row (vertical cell centering). Value rows without a fuel cell are
  re-attached to the nearest fuel row within 1.8 pt.
* **The TOTAL trap**: on several sheets the right edge of the
  "… SALES TOTAL" label lands exactly inside the FUEL column band. Row type
  (TOTAL/CUMULATIVE, decided from tokens left of the JAN band) is classified
  *before* fuel detection, else every section double-counts.
* **Fuel column**: token under the FUEL header → `G`→PETROL, `D`→DIESEL,
  `BEV`/`HEV`/`PHEV`→ same-named columns; `-` (blank spec rows, a few dozen
  units/month) and rarities (`CNG` tractor heads) → OTHERS with a warning.
* **Corrupt digits**: some spec columns render `0` as `-`
  (`462-X1776X146-`) — a font-encoding defect in the source file. Sales
  columns are unaffected; if it ever bleeds into them the checksums below
  catch it.

## 4. Validation (hard fail, no partial writes)

Every layer of printed totals in the PDF is cross-checked per month before
any CSV is touched:

1. per section: Σ model rows == printed `<SECTION> SALES TOTAL`;
2. Σ(Sedan, 4x2, 4x4, LCGC) == `PASSENGER CAR SALES TOTAL`,
   Σ(Bus, PU/Truck, DC) == `COMMERCIAL VEHICLE SALES TOTAL`;
3. PC + CV == `DOMESTIC SALES TOTAL`;
4. Pickups + HDV subsection split == PU/TRUCK section total;
5. all seven sections must be present and agree on the `JAN-XXX` coverage.

Any mismatch exits non-zero (workflow fails visibly), so a silent format
change cannot write wrong rows.

## 5. Upsert semantics

Each cumulative file restates the whole year to date, so a run rewrites
**all covered months** of that year (absorbing GAIKINDO's revisions) and
leaves earlier years untouched. `source` = `GAIKINDO`, `notes` = portal file
title. Self-throttle: if the newest portal title's last month already exists
as a GAIKINDO-sourced row in `Indonesia.csv`, the run stops before the
download. Only `Whole` is auto-rendered; the three variant CSVs accumulate
data without a params/render entry until deliberately onboarded.

## 6. Series continuity (R. Andrew handoff)

The pre-2026 rows in `data/Indonesia.csv` come from robbieandrew.github.io's
carsales aggregation of the same GAIKINDO passenger-car scope. Verified at
handoff: 2026-03 TOTAL identical (46 466); 2026-01/02/04 within a few dozen
units (GAIKINDO's own revisions); BEV/HEV/PHEV columns matched to the unit.
2026-01 onward is fetched directly and minor revisions of those months are
expected and fine.

## 7. Backfill option (not implemented)

The portal also hosts full-year files ("Wholesales 2025", "Wholesales 2024",
… back to at least 2022) in the same sheet format. If the Pickups/HDV/Buses
variants ever need pre-2026 history, the same parser should apply to those
files (`--download-url` + a year override would be the starting point).
Until then the variant series simply start at 2026-01.
