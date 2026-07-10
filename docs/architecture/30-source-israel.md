# 30 · Source playbook — Israel (data.gov.il vehicle registry)

First MENA-region country on the gallery. Registry-direct, CKAN datastore
API, no auth, no scraping. Fetcher: `scripts/fetch_israel.py`, workflow:
`.github/workflows/fetch-israel.yml`. Investigated & built 2026-07 (see
[29-expansion-candidates.md](29-expansion-candidates.md) for the wider
region survey).

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
