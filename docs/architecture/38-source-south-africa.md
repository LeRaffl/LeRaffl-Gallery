---
country: South Africa
slug: south-africa
method: pdf
summary: New-vehicle sales for South Africa from naamsa's Quarterly Review of Business
  Conditions — the first African market on the gallery. All-vehicle market, not M1-only.
source_name: naamsa — Quarterly Review of Business Conditions
source_url: https://naamsa.net/quarterly-reviews/
source_links:
- label: Quarterly reviews (QBR PDFs)
  url: https://naamsa.net/quarterly-reviews/
  note: Each review carries the NEV drivetrain table (yearly + two quarter columns) and the passenger + commercial totals
- label: Industry Vehicle Sales (actuals and projections)
  url: https://naamsa.net/quarterly-reviews/
  note: Companion PDF; the TOTAL AGGREGATE MARKET row is the yearly denominator
- label: Press releases (monthly flash / media)
  url: https://naamsa.net/press-releases/
  note: Monthly totals and, from 2026, lagged NEV commentary — not used as the primary split
underlying: naamsa member companies / Lightstone Auto (manufacturer-reported domestic sales)
auth: none
cadence: 07:20 UTC, 15th–28th of Feb/May/Aug/Nov; self-throttles via change-gated commit
variants:
- Whole
variant_notes:
  Whole: All-vehicle naamsa market (passenger + LCV + MCV/HCV + buses), from 2020 (yearly) and 2024-Q1 (quarterly).
hev_split: true
hev_note: Full BEV / PHEV / HEV split. No petrol/diesel split of the remainder — ICE = TOTAL − BEV − PHEV − HEV.
backfill: none — the fetcher walks the public QBR archive itself
scope_note: All-vehicle new sales, not EU M1. Mixing a passenger-only total with all-vehicle NEV would distort the BEV share.
caveats:
- Manufacturer-reported; Geely, Dongfeng and some other importers do not report to naamsa.
- 2026 NEV volumes include new reporters joining naamsa/Lightstone — a coverage step, not only demand.
- The NEV table is not split by body type, so Whole is the total market with a footnote, not passenger cars.
- naamsa's Q4-2025 drivetrain table prints the PHEV and HEV *quarter* columns swapped; the fetcher detects and repairs this against the yearly totals.
fetcher: scripts/fetch_southafrica.py
workflow: .github/workflows/fetch-southafrica.yml
fragility_doc: docs/architecture/38-source-south-africa.md
data_file: data/South Africa.csv
---

# 38 · Source playbook — South Africa (naamsa)

First African country on the gallery. Industry-body PDFs, no auth, no
scraping of a login wall. Fetcher: `scripts/fetch_southafrica.py`,
workflow: `.github/workflows/fetch-southafrica.yml`. Investigated July 2026
([33-expansion-candidates.md](33-expansion-candidates.md)) as **verified
viable**; built September 2026.

## TL;DR

```
Source:    naamsa (Automotive Business Council) Quarterly Review of
           Business Conditions + Industry Vehicle Sales companion PDF
Auth:      None — public PDFs on naamsa.net/quarterly-reviews/
Format:    PDF, parsed with pdftotext -layout (poppler)
Variants:  Whole only (all-vehicle market)
HEV split: YES — BEV / PHEV / HEV. ICE = TOTAL − those three (no
           petrol/diesel split).
History:   yearly 2020–2023 (mid-year rows) + quarterly 2024-Q1 onward
           (Canada middle-month convention).
Schedule:  07:20 UTC, 15th–28th of Feb/May/Aug/Nov
Scripts:   scripts/fetch_southafrica.py  (--probe / --dry-run)
Workflow:  .github/workflows/fetch-southafrica.yml
```

## The source

- **Industry body:** naamsa NPC, trading as the Automotive Business
  Council. OICA-style manufacturer association; domestic sales reported
  by members and compiled with Lightstone Auto.
- **QBR:** [naamsa.net/quarterly-reviews](https://naamsa.net/quarterly-reviews/)
  lists every Quarterly Review of Business Conditions back to 2016, each
  with a companion *Industry Vehicle Sales, Production, Export and Import
  Data* PDF.
- **NEV table:** from 2020 the QBR carries a drivetrain table — yearly
  columns 2020…current year plus two quarter columns (`Qn:YYYY-1`,
  `Qn:YYYY`) for Plug-in hybrid / Traditional hybrid / Electric / Total
  NEVs.
- **Quarterly TOTAL:** "aggregate industry new passenger car sales" +
  "aggregate industry commercial vehicle sales" in the same QBR's
  *Business Conditions* section. That is the all-vehicle denominator the
  NEV table is defined against (Q2 2026: 8,611 NEV / 153,119 = 5.6%,
  matching the prose).
- **Yearly TOTAL:** `TOTAL AGGREGATE MARKET` on the Industry Vehicle
  Sales PDF. 2025 = 597,338; 16,716 NEV = 2.8%, matching the QBR.

Monthly flash reports and media releases carry industry totals (and,
from 2026, lagged NEV commentary) but **not** a stable historical
drivetrain table. They are not the fetcher's primary source.

## Cadence and storage

Canada convention: each quarter is stored under its middle month
(`Q1→YYYY-02` … `Q4→YYYY-11`), `time_interval=quarterly`. Yearly 2020–2023
sit at `YYYY-06` and stop where the quarterly series begins, so TTM never
mixes annual and quarterly volumes.

QBRs land mid-month after quarter-end (Q1 late May, Q2 mid-August, Q3
mid-November, Q4 mid-February). Cron: `20 7 15-28 2,5,8,11 *`. The
script always re-parses the archive (naamsa revises recent years); the
commit is change-gated.

## Scope — why Whole is all-vehicles

The NEV table is **not** split into passenger / LCV / MCV. Using
naamsa's passenger-car total as `TOTAL` and the all-vehicle NEV count as
the numerator would understate the denominator and overstate BEV share —
the Mexico two-universes failure mode. `Whole` is therefore the **total
domestic new-vehicle market**, footnoted as not EU M1.

## Completeness

Manufacturer-reported. naamsa's own NEV line says "sales by N industry
brands" (21 / 22 / 23 / 30 depending on the edition). Press notes that
Geely and Dongfeng do not currently report. Chinese brands that *do*
report (Chery, GWM, Jetour, Omoda/Jaecoo) sit in the monthly flash top
15, so this is not a Mexico-scale BYD hole, but it is not a registry.
The Q2 2026 QBR states that 2026 NEV growth was "supported by new
entrants starting to report … to naamsa/Lightstone Auto" — a coverage
step, called out in the 2026 row notes.

## Parser traps

1. **Ligatures.** `pdftotext` emits `;rst` / `Nrst` for "first". The
   fetcher normalises these before the passenger/commercial regex.
2. **Q4-2025 PHEV/HEV swap.** The Q4 2025 table's *quarter* columns on
   the Plug-in / Traditional hybrid rows are swapped (yearly columns on
   the same rows are fine). Detected when a quarter's PHEV exceeds that
   year's yearly PHEV; the swap preserves the NEV total. After repair,
   2024 and 2025 quarterly sums match the yearly NEV table within a
   handful of units.
3. **SAAM 2035.** Cutting the table block at the `Total NEVs` row stops
   "2035" in nearby policy prose from becoming a year column.
4. **Projections.** The Industry Vehicle Sales PDF's last two year
   columns are forecasts (round thousands). Years `>=` the current
   calendar year are dropped.

## Cross-checks (2026-09)

| Period | BEV | PHEV | HEV | TOTAL | BEV share |
|---|---:|---:|---:|---:|---:|
| 2025 (year) | 1,088 | 2,810 | 12,818 | 597,338 | 0.18 % |
| 2026 Q1 | 544 | 1,277 | 2,764 | 161,946 | 0.34 % |
| 2026 Q2 | 1,353 | 3,346 | 3,912 | 153,119 | 0.88 % |

2026 H1 PHEV 1,277+3,346 = 4,623 matches naamsa's June-2026 YTD PHEV
figure in the July media release. Q2 2026 NEV 8,611 / 153,119 = 5.6 %
matches the QBR prose.

## Cadence & workflow

`scripts/fetch_southafrica.py` discovers QBR + Industry Vehicle Sales
PDFs from the listing page, parses every recent QBR (newest wins on
overlap), upserts `data/South Africa.csv`. `--probe` dumps the listing
and the newest table; `--dry-run` prints rows without writing.
`workflow_dispatch` accepts `qbr_url` / `industry_url` overrides.
