---
country: USA
slug: usa
method: pdf
summary: Monthly new light-vehicle SALES in the United States — cars and light trucks
  including pickups, SUVs and vans (GVWR up to 10,000 lb) — with battery-electric,
  plug-in hybrid and hybrid counts, compiled by Argonne National Laboratory (ANL) from
  Wards Auto. These are sales, not registrations, and pickups cannot be separated out.
source_name: Argonne National Laboratory — Light Duty Electric Drive Vehicles Monthly Sales Updates ("Total Sales for Website" PDF)
source_url: https://www.anl.gov/esia/reference/light-duty-electric-drive-vehicles-monthly-sales-updates-historical-data
source_links:
- label: ANL monthly sales updates (web page with the latest month's headline figures)
  url: https://www.anl.gov/esia/light-duty-electric-drive-vehicles-monthly-sales-updates
  note: methodology ("Data Sources"), the ≤ 10,000 lb definition, Wards Auto as reference since Oct-2019, the month's HEV car / light-truck split and FCEV counts (text only)
- label: ANL historical data page (link to the PDF the fetcher reads)
  url: https://www.anl.gov/esia/reference/light-duty-electric-drive-vehicles-monthly-sales-updates-historical-data
  note: one PDF, full monthly history Dec-2010 → latest, columns Month · BEV · PHEV · HEV · Total LDV
- label: BTS National Transportation Statistics table 1-19 (a copy of the same ANL series)
  url: https://www.bts.gov/content/gasoline-hybrid-and-electric-vehicle-sales
  note: useful as an independent snapshot of ANL's figures; not used by the fetcher
underlying: Wards Auto (Wards Intelligence) monthly US light-vehicle sales, compiled by Argonne's Systems Assessment Center for DOE's Vehicle Technologies Office; before Oct-2019 EDTA, Hybrid Dashboard, InsideEVs and Green Car Congress
auth: none (anl.gov returns 403 to non-browser User-Agents; the fetcher sends a desktop browser UA)
cadence: daily from the 10th to the end of the month, 10:30 UTC — ANL publishes about 6–7 weeks after the month (the Aug-2026 PDF is dated 17 Sep 2026)
variants:
- Whole
variant_notes:
  Whole: "All new light-duty vehicles SOLD in the US — passenger cars AND light trucks (pickups, SUVs/crossovers, minivans, vans) up to 10,000 lb GVWR. Not EU M1 — pickups (≈ 15% of US production per EPA's Automotive Trends Report) and light commercial vans are inside. Not registrations."
hev_split: true
hev_note: ANL reports HEV (conventional, non-plug-in hybrids) as its own column; ANL does not say whether mild hybrids are counted as HEV.
backfill: none needed — every PDF carries the full history from Dec-2010; a full refresh (`--months 0`) rewrites all rows from the current release.
scope_note: New light-duty vehicle sales (cars + light trucks incl. pickups, ≤ 10,000 lb GVWR) as compiled by ANL from Wards Auto. Sales, not registrations. Compare with other countries' passenger-car (M1) curves with care — the US light-truck share is very large.
caveats:
- SALES, not registrations — the US has no free national new-registration feed (state DMVs publish separately; Experian/S&P registration data is paid).
- Cars + light trucks INCLUDING pickups, SUVs and vans (GVWR ≤ 10,000 lb; EPA's light-duty definition is 8,500 lb). Not comparable 1:1 with EU-M1 passenger-car series. ANL publishes no car/truck split of the table, so a cars-only or pickups series is not possible from this source.
- Combustion is not reported; ICE = Total − BEV − PHEV − HEV (no petrol/diesel split).
- Fuel-cell cars are not in the PDF table and stay inside the ICE residual — a few dozen a month (ANL web page, Jul-2025 — 32 Toyota Mirai and 5 Honda CR-V), so OTHERS is 0.
- ANL revises recent months and sometimes whole earlier years between releases; the fetcher re-writes the last 3 months and warns about any older drift (full refresh with months=0). The full history was refreshed from the Aug-2026 release on 2026-10-18.
- Source lineage changes in Oct-2019 (Wards Auto as reference); earlier months come from EDTA / Hybrid Dashboard / InsideEVs / Green Car Congress.
processing:
- title: Find the PDF
  text:
  - The fetcher opens ANL's historical-data page with a browser User-Agent and takes the link whose URL or text contains "total" and "sales" and ends in .pdf ("Total Sales for Website_<Month> <Year>.pdf").
- title: Read the table
  text:
  - pypdf turns the PDF into text; every line that starts with a month tag (e.g. "Aug-25") followed by four numbers is a row — BEV, PHEV, HEV, Total LDV. Legend text after the numbers and the "PEV Sales by Size" box are ignored.
  decision:
    ask: ANL column?
    branches:
    - when: BEV
      then: BEV
    - when: PHEV
      then: PHEV
    - when: HEV
      then: HEV
    - when: Total LDV
      then: TOTAL
    - when: (none — fuel cell)
      then: inside ICE
      note: OTHERS = 0; FCEVs are a few dozen a month
- title: Which vehicles are counted
  text:
  - ANL's light-duty total is every new car and light truck up to 10,000 lb GVWR sold in the month. Nothing is reclassified.
  decision:
    ask: Vehicle type?
    branches:
    - when: Passenger cars (sedans, hatchbacks, coupés, wagons)
      then: Whole
    - when: SUVs / crossovers, minivans
      then: Whole
    - when: Pickups and vans ≤ 10,000 lb GVWR
      then: Whole
      note: not separable in the ANL table
    - when: Medium/heavy trucks and buses (> 10,000 lb)
      then: in no variant
- title: Check it
  text:
  - Before anything is written the whole table must pass — no missing month between the first and the last, no negative value, BEV + PHEV + HEV not above the total, and the total between 0.5 M and 2.5 M. Any failure stops the run and leaves the CSV untouched. A value identical in two consecutive months, a PDF more than two months behind, and older CSV rows that no longer match the PDF are reported as warnings.
  decision:
    ask: All checks pass?
    branches:
    - when: "yes"
      then: last 3 months written (all months with months=0)
    - when: no
      then: run fails, CSV untouched
- title: Build the row
  text:
  - ICE = TOTAL − BEV − PHEV − HEV; OTHERS = 0. The file is rewritten only when a value changed, then render-country.yml is dispatched for USA. The exact PDF and its text are kept as a 7-day workflow artifact (anl-total-sales).
fetcher: scripts/fetch_usa.py
workflow: .github/workflows/fetch-usa.yml
fragility_doc: docs/architecture/62-source-usa.md
data_file: data/USA.csv
tests: scripts/test_fetch_usa.py
---

# 62 · Source: USA (Argonne National Laboratory, monthly LDV sales)

## TL;DR

```
Source:    anl.gov — "Total Sales for Website_<Month> <Year>.pdf" (full history)
Underlying: Wards Auto (since Oct-2019), compiled by ANL for DOE VTO
Measure:   new-vehicle SALES (not registrations)
Scope:     light-duty vehicles ≤ 10,000 lb GVWR = cars + light trucks
           INCLUDING pickups, SUVs, minivans, vans (not EU M1)
Columns:   BEV · PHEV · HEV · Total LDV → ICE = residual, OTHERS = 0
           (no FCEV column; FCEVs — dozens/month — sit in the ICE residual)
Coverage:  monthly, 2010-12 → latest (about 6–7 weeks lag)
Revisions: last 3 months rewritten each run; older drift → ::warning;
           workflow input months=0 refreshes everything
Checks:    gap / negative / sum>total / total band → abort; repeats,
           staleness, drift → warning
Scripts:   scripts/fetch_usa.py, tests scripts/test_fetch_usa.py
Workflow:  .github/workflows/fetch-usa.yml (daily 10th→EOM 10:30 UTC)
```

## 1 · What the number means

ANL's "Total LDV" is US **light-duty vehicle sales** as reported by Wards Auto:
every new passenger car and light truck with a GVWR up to **10,000 lb** sold
in the calendar month. ANL itself notes the difference to EPA, whose
light-duty shares use ≤ 8,500 lb. Light trucks — pickups, SUVs/crossovers,
minivans and vans — are the large majority of the US market, so this series is
not the EU-M1 "new passenger cars" most other gallery countries chart.

Pickups cannot be removed: the PDF table has no car/truck split; ANL's web page
only gives the month's HEV headline as cars vs light trucks, and model-level
sales stopped in Nov-2019. A 2026-10 survey of free alternatives (OEM releases,
BEA, EPA Trends, Cox/KBB, state DMVs) found no monthly national source with a
pickup and fuel split; see the PR discussion of the USA audit.

## 2 · 2026-10 data audit (the reason for this doc)

The PDF of the Aug-2026 release (fetched in CI, artifact `anl-total-sales`) was
compared with `data/USA.csv` row by row:

| Finding | Cause | Fix |
|---|---|---|
| HEV identical in 2025-08 and 2025-09 (150,988) | **2025-08 was stale**: written before ANL's revision and then outside the 3-month window. The current PDF has Aug-25 = 148,234 / 27,597 / 187,113 / 1,466,105. Sep-25 HEV 150,988 is genuine. | full refresh |
| 2025-11 OTHERS empty | legacy row, never normalised | full refresh (now 0.0) + test |
| 39 rows drifted from the current PDF (largest 2023-08 … 2025-08, e.g. 2025-06 BEV 92,514 → 111,577; plus single-digit typos in 2011–2021 such as 2015-07 TOTAL 1,410,941 vs 1,510,941) | revisions outside the window; hand-maintained history | full refresh; drift now reported every run |
| 2010-12 missing | the CSV started in 2011-01 | added from the PDF |
| FCEV "dropped" | the PDF has no FCEV column (only ANL's web text has the current month's counts) | documented; OTHERS stays 0 |

## 3 · Debugging

- **403 from anl.gov** on a laptop or the agent box is normal; the GitHub
  runner gets through with the browser UA. To inspect a release, run the
  workflow (any harmless cutoff, e.g. year=2011 month=1 months=1) and download
  the `anl-total-sales` artifact (PDF + extracted text).
- **Sanity failure**: read the `::error` lines; a gap or a total outside the
  band almost always means the PDF layout changed — compare the artifact text
  with `PDF_TEXT` in `scripts/test_fetch_usa.py`.
- **Drift warning**: dispatch the workflow with `months=0`.
