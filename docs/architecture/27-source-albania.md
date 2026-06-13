# 27 · Source: Albania (dpshtrr.al, via R. Andrew CSV)

Albania's General Directorate of Road Transport Services (DPSHTRR — *Drejtoria
e Përgjithshme e Shërbimeve të Transportit Rrugor*) publishes monthly vehicle
registration counts broken down by fuel type through its Open Data portal. The
data is displayed as an embedded Looker Studio (Google Data Studio) dashboard
rather than a direct-download file, which makes it impossible to automate
without Google authentication. Robbie Andrew
(`@robbieandrew.bsky.social`) mirrors the same underlying DPSHTRR figures as a
plain CSV at `robbieandrew.github.io/carsales/albania_carsales_monthly.csv`,
which is what we fetch. Attribution in every row's `source` column remains
`dpshtrr.al`; R. Andrew is credited in `footnotes.csv`.

## TL;DR

```
Source:    dpshtrr.al (DPSHTRR Open Data, Looker Studio dashboard)
Fetch URL: https://robbieandrew.github.io/carsales/albania_carsales_monthly.csv
Auth:      None (Robbie's mirror is a public CSV; the DPSHTRR dashboard requires Google auth)
Format:    CSV; rows = monthly period (YYYYMM), columns per fuel type
Parse:     Direct CSV parse — no scraping or PDF handling (scripts/fetch_albania.py)
Variant:   Whole (all first registrations, new + imported used)
Coverage:  2019-01 onward; grows as Robbie updates his mirror
Cadence:   Monthly; time_interval=monthly
Schedule:  Daily days 10-28, 07:00 UTC; commit-gated
Scripts:   scripts/fetch_albania.py
Workflow:  .github/workflows/fetch-albania.yml
```

## 1. Why this source (and not DPSHTRR directly)

DPSHTRR is the authoritative primary source — every figure ultimately comes
from their registration database. Their Open Data page
(`dpshtrr.al/open-data-dpshtrr-english`) is publicly accessible in a browser
but returns **HTTP 403** to any automated HTTP client. The visualizations are
embedded Looker Studio reports; exporting the underlying data from Looker Studio
requires signing in with a Google account, which is not automatable in a
headless CI environment.

Alternatives investigated and rejected:

* **INSTAT PxWeb** (`databaza.instat.gov.al/pxweb/`) — Albania's statistical
  institute publishes "Characteristics of Road Vehicles" via a PxWeb API, but
  this is **fleet stock** data (total vehicles currently in circulation), not
  monthly new/first registrations. Different metric, wrong for the gallery.
* **opendata.gov.al** — The national open data portal does not appear to host
  the DPSHTRR monthly registration breakdown in a directly downloadable format.
* **DPSHTRR Looker Studio embed** — Even if the report ID were known, the
  underlying BigQuery / Google Sheets data source is not publicly queryable
  without credentials.

Robbie Andrew's CSV is a reliable, well-maintained pre-parsed mirror of the
same DPSHTRR figures. If his mirror ever becomes unavailable the fallback is:
a) a manual download + CSV update from the DPSHTRR Looker Studio dashboard
(browser → Google sign-in → "Export as CSV") or b) a manual data entry from
the dashboard.

## 2. Column mapping

Robbie's header → gallery schema:

| Robbie CSV column    | Gallery column | Notes                                        |
|----------------------|----------------|----------------------------------------------|
| Battery electric     | BEV            |                                              |
| Plugin hybrid        | PHEV           |                                              |
| Non-plugin hybrid    | HEV            |                                              |
| Petrol               | PETROL         |                                              |
| Diesel               | DIESEL         |                                              |
| LPG / LPG blend      | OTHERS         | Summed with "Others"                         |
| Others               | OTHERS         | Summed with "LPG / LPG blend"                |
| —                    | TOTAL          | Sum of all six value columns                 |

LPG is a non-negligible fuel type in Albania (~200–600 registrations/month in
recent years) but the gallery schema has no dedicated LPG column; it folds into
`OTHERS` together with the residual "Others" bucket.

## 3. What the figures actually count

**All first registrations in Albania** — both brand-new vehicles and imported
used vehicles being registered for the first time in the Albanian vehicle
database. Albania has an exceptionally active used-car import market
(primarily from Western Europe and, increasingly, China), so headline monthly
totals (~5,000–7,000 in 2025–2026) are considerably larger than what a
new-car-only count would show. This is the same definition DPSHTRR uses and
what Robbie Andrew reproduces; it is consistent across the entire time series.

The rapid BEV share growth (from ~1% in 2019 to ~19% in 2026-03) reflects
both new BEV sales and the surge in imported used Chinese EVs (primarily BYD
and other brands entering the Albanian market at low price points).

Variant is `Whole` (no body-type or passenger/commercial sub-split available
from this source).

## 4. Upsert & idempotence

Keyed on `(period, variant)`. The workflow's commit step is change-gated, so
steady-state daily runs after a month is already in the CSV are a no-op. The
`--since YYYY-MM` flag limits the upsert window; omit it to refresh the full
series (useful if Robbie back-fills earlier months).

## 5. Source attribution & footnote

* **`source` column** (`data/Albania.csv`): `dpshtrr.al` for every row. This
  is what `render_country.R` prints as **"Source: dpshtrr.al"** on the rendered
  chart. (The legacy params.csv entry carried `dpshtrr.al / @robbieandrew.bsky.social`;
  the CSV normalises to the single official primary host for consistency.)
* **`footnotes.csv`** (`Albania,Whole`): rendered as a second caption line —
  > Figures include first registrations of both new and imported used vehicles.
  > Pre-automation series compiled by R. Andrew.

  R. Andrew is credited here and the used-car caveat is made explicit so chart
  readers are not misled into comparing Albania's total-registration BEV share
  directly with a new-car-only share from e.g. Germany.

## 6. Peculiarities to know about

* **New + used registrations.** See §3. Albania's figures are not comparable
  to new-car-only sources used for Germany, France, etc. The BEV share is
  directionally meaningful but the denominator differs.
* **LPG bucket.** LPG / LPG blend is a meaningful fuel category in Albania (a
  legacy of low petrol affordability), contributing 5–10% of monthly totals.
  It is silently folded into `OTHERS`; if you see `OTHERS` that looks high,
  that is why.
* **DPSHTRR 403 + Looker Studio.** The official portal blocks automated
  requests. If the Robbie Andrew mirror goes stale (e.g. Robbie stops
  maintaining it), the only recourse is a manual browser export from
  `dpshtrr.al/open-data-dpshtrr-english` using a Google account. This is
  documented in §1 and should be checked if CI starts returning stale data.
* **Data starts 2019-01.** Pre-2019 data is not available from DPSHTRR's open
  data platform. Earlier total-fleet statistics exist at INSTAT but do not have
  a fuel-type breakdown.
* **Robbie's CSV may lag 2–4 weeks.** DPSHTRR typically publishes the prior
  month's data in the first half of the following month; Robbie updates his
  mirror shortly after. The CI schedule (days 10–28) is chosen to avoid
  running before the data is typically available.
