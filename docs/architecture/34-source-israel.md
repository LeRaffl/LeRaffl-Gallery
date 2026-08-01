---
country: Israel
slug: israel
method: api
summary: New-registration data for Israel derived from the Ministry of Transport's open vehicle registry
  — registry-direct, counted from the licensing database itself.
source_name: data.gov.il — vehicle registry (CKAN datastore)
source_url: https://data.gov.il/dataset/private-and-commercial-vehicles
source_links:
- label: Registry resource (מאגר מספרי רישוי של כלי רכב)
  url: https://data.gov.il/dataset/private-and-commercial-vehicles
  note: ~4.15M currently-registered vehicles; the dataset's second resource holds extra columns for the
    same vehicles, not extra rows
- label: Model catalogue (degem-rechev-wltp)
  url: https://data.gov.il/dataset/degem-rechev-wltp
  note: propulsion technology per make/model/year/trim — the HEV/PHEV split comes from joining this
- label: I-VIA monthly reviews (cross-check)
  url: https://www.car-importers.org.il/Monthly_reviews
underlying: Ministry of Transport and Road Safety — vehicle licensing database
auth: none
cadence: daily 08:00 UTC, 10th–20th of the month; self-throttles once the previous month is in
variants:
- Whole
- Vans
variant_notes:
  Whole: New private passenger cars (registry `sug_degem` = P), from 2017-01.
  Vans: New light commercial vehicles up to 3.5t (registry `sug_degem` = M); low volume, roughly
    500–1,100 per month.
hev_split: true
hev_note: The registry codes regular hybrids as plain petrol and reserves its two electric/fuel values
  for plug-ins; the real HEV and PHEV figures are recovered by joining the official model catalogue.
backfill: none — the fetcher walks the registry back to 2017-01 itself
scope_note: Registry-derived monthly counts; no motorcycles, no trucks above 3.5t, no buses in this
  dataset.
caveats:
- The registry is a stock snapshot of currently-registered vehicles, so older months lose deregistered
  vehicles and undercount slightly; recent months are effectively exact.
- Regular hybrids are hidden inside the petrol fuel value — HEV/PHEV come from the model-catalogue join
  (100% coverage back to 2017; the fetcher warns above 5% unmatched).
- Counts slice by road-entry date, whereas the importers' association reports deliveries, so single
  months can differ a few percent in either direction.
fetcher: scripts/fetch_israel.py
workflow: .github/workflows/fetch-israel.yml
fragility_doc: docs/architecture/34-source-israel.md
data_file: data/Israel.csv
---

# 34 · Source playbook — Israel (data.gov.il vehicle registry)

First MENA-region country on the gallery. Registry-direct, CKAN datastore
API, no auth, no scraping. Fetcher: `scripts/fetch_israel.py`, workflow:
`.github/workflows/fetch-israel.yml`. Investigated & built 2026-07 (see
[33-expansion-candidates.md](33-expansion-candidates.md) for the wider
region survey).

## TL;DR

```
Source:    data.gov.il — Ministry of Transport vehicle registry (CKAN)
           Dataset: private-and-commercial-vehicles
Auth:      None — public CKAN datastore API, no key.
Format:    JSON (datastore_search), 32k-row pages.
Variants:  Whole (sug_degem=P, private cars) + Vans (sug_degem=M, LCV ≤3.5t).
HEV split: YES, but NOT from the fuel column — the registry codes regular
           hybrids as plain petrol (בנזין) and uses חשמל/בנזין only for
           plug-ins. Every petrol/diesel/hybrid row is joined against the
           WLTP model catalogue on (make, model code, model year, trim);
           technologiat_hanaa_nm gives PLUG IN / regular hybrid / electric /
           conventional. Join coverage: 100% back to 2017.
History:   2017-01 onward (both variants).
Schedule:  Daily 08:00 UTC, 10th–20th; early-exits once last month is in.
Scripts:   scripts/fetch_israel.py  (--probe / --crosscheck modes included)
Workflow:  .github/workflows/fetch-israel.yml
```

## The source

- **Dataset:** [`private-and-commercial-vehicles`](https://data.gov.il/dataset/private-and-commercial-vehicles)
  ("מספרי רישוי של כלי רכב פרטיים ומסחריים") — the Ministry of Transport's
  licensing database, ~4.15M currently-registered private & light-commercial
  vehicles, refreshed daily (~03:00 UTC).
- **Registry resource:** `053cea08-09bc-40ec-8f7a-156f0677aff3`. The
  dataset's second resource (`0866573c-…`, "… - המשך") is **extra columns**
  (tyre codes, tow bar) for the same 4.15M vehicles, NOT more rows — never
  aggregate over it.
- **Model catalogue:** dataset `degem-rechev-wltp`, resource
  `142afde2-6228-49f9-8a29-9b6c3a0cbe40` (~100k rows) — needed for the
  hybrid split, see below.
- **API:** standard CKAN `datastore_search` with `filters`/`fields`/paging
  (32k page cap). Rejects default python user agents — send a browser-ish UA.

## How monthly registrations are derived

The registry is a **stock snapshot**, not an events feed. Monthly new
registrations = count of rows per road-entry month (`moed_aliya_lakvish`),
scope-filtered on `sug_degem`: `"P"` (private passenger cars) = gallery
`Whole`, `"M"` (light commercial ≤3.5t) = the `Vans` variant
(`data/Israel_Vans.csv`, ~500–1,100/month, diesel-dominated with BEV
climbing from ~0% to ~8% by mid-2026). Both variants share one fetcher run;
the workflow's changed-variants detector renders only what moved.

Quirks (all verified by the probe runs, 2026-07):

- **`moed_aliya_lakvish` is unpadded** — `"2016-3"`, not `"2016-03"`.
  Filter values must drop the leading zero; CSV periods stay padded.
- **Survivorship:** deregistered (scrapped/exported) vehicles drop out of
  the snapshot, so older months undercount slightly. Backfill starts
  2017-01; the caveat is footnoted in `footnotes.csv`.
- **Timing:** the registry slices by road-entry date, I-VIA (importers
  association) reports deliveries — single months can differ a few percent
  in both directions but consecutive-month sums agree (<1% on Apr+May 2026).
- No motorcycles, no >3.5t trucks, no buses in this dataset.

## THE trap: HEVs hide inside "בנזין"

`sug_delek_nm` has six values: בנזין / דיזל / גפ"מ / חשמל / חשמל/בנזין /
חשמל/דיזל. **The two `חשמל/*` hybrid values are PLUG-INs only** — regular
HEVs (a quarter of the Israeli market) are coded as plain petrol. A naive
fuel-column mapping produces PETROL ≈ 60% and HEV = 0.

Recovery: join every petrol/diesel/hybrid row against the model catalogue
on `(tozeret_cd, degem_cd, shnat_yitzur, ramat_gimur)` — trim level included
because one model code + year can carry different powertrains — with a
majority vote over the model's trims as fallback. The catalogue's
`technologiat_hanaa_nm` has exactly four values:

| technologiat_hanaa_nm | meaning | gallery column |
|---|---|---|
| `PLUG IN` (sic, English) | plug-in hybrid | PHEV |
| `היברידי רגיל` | regular hybrid | HEV |
| `רכב חשמלי` | battery electric | (BEV comes from the fuel column) |
| `הנעה רגילה` | conventional | PETROL / DIESEL per fuel column |

Cross-tab verification (probe v4): join coverage was **100% back to 2017**;
resulting shares reproduce I-VIA's quarterly powertrain mix within ~2pp
(2025-06: petrol 37.9% vs I-VIA Q3 37.0%, BEV 20.5% vs 20.5%). The fetcher
prints per-month join statistics and warns if the unmatched share exceeds
5% (HEV undercount risk).

## Cross-check sources

- **I-VIA monthly reviews** (free English PDFs):
  [car-importers.org.il/Monthly_reviews](https://www.car-importers.org.il/Monthly_reviews)
  — passenger-car totals + powertrain shares; used to validate the fetcher.
- CBS publishes registry-based vehicle statistics with a lag.
- **R. Andrew's carsales mirror**
  (`robbieandrew.github.io/carsales/data/israel_carsales_monthly.csv`,
  columns YYYYMM / ICE / Non-plugin hybrid / Plugin hybrid / Battery
  electric, fractional values ⇒ a derived series, not raw counts). The
  fetcher's `--crosscheck` mode diffs against it. Result (2026-07): in the
  mature overlap **2023–2025 the two independent pipelines agree within
  1–4% on yearly totals and ~1pp on monthly BEV shares** (BEV 2024:
  67,556 vs 67,171; 2025: 57,961 vs 58,166). Deviations concentrate in
  three explainable zones: (a) **his 2026 months carry Plugin hybrid = 0**
  and his totals ≈ ours − PHEV — a gap in his series, not ours (ours match
  I-VIA); (b) his pre-2023 coverage looks partial (his 2021 total 212,580
  vs our 272,912 — 2021 was Israel's record year, our figure matches the
  known market size); (c) single-month splits differ a few pp where
  delivery-vs-registration timing diverges (war months especially).

## Cadence & workflow

Registry updates daily; the previous month is effectively complete within
the first days of the following month. The workflow crons daily 10th–20th
(08:00 UTC) and self-throttles: early-exit once the previous month is in
`data/Israel.csv`. Each real run re-counts the last 3 months (late entries
trickle in), so recent revisions self-heal. `workflow_dispatch` accepts
`mode=probe|fetch`, `start`/`end` (YYYY-MM) for backfills, and a `commit`
gate.
