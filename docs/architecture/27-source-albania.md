# 27 · Source: Albania (dpshtrr.al, Looker Studio batchedDataV2 API)

Albania's General Directorate of Road Transport Services (DPSHTRR — *Drejtoria
e Përgjithshme e Shërbimeve të Transportit Rrugor*) publishes monthly vehicle
registration counts broken down by fuel type through its Open Data portal.  The
data is presented as a public Looker Studio (Google Data Studio) report that
does **not** require a Google account to view.  We query the report's
`batchedDataV2` JSON API directly — no browser, no login, no headless
automation needed.

## TL;DR

```
Source:        dpshtrr.al  (DPSHTRR Open Data, Looker Studio)
API endpoint:  POST https://datastudio.google.com/batchedDataV2?appVersion=20260607_0101
Report ID:     407ce08b-d3ce-478e-9bc7-a50125f875f3
Page (URL):    VPWqB   (Vehicles by type of fuel or power source)
Page (numeric):24871631
datasourceId:  7705f3ec-84aa-4432-bbed-d61775f98126
Auth:          None — anonymous session; RAP_XSRF_TOKEN obtained from page load
Format:        JSON (batchedDataV2 response)
Parse:         flat-table request: Month × Fuel type × Record Count,
               filtered to Autoveturë (passenger cars)
Variant:       Whole (all first registrations, new + imported used)
Coverage:      Current-year months via API; pre-2026 from bootstrapped CSV
               (compiled by R. Andrew from same DPSHTRR source)
Cadence:       Monthly; time_interval=monthly
Schedule:      Daily days 10-28, 07:00 UTC; commit-gated
Scripts:       scripts/fetch_albania.py
Workflow:      .github/workflows/fetch-albania.yml
```

## 1. Source overview

DPSHTRR is the authoritative primary source.  Their Open Data page
(`dpshtrr.al/open-data-dpshtrr-english`) embeds a public Looker Studio report.
The report is publicly viewable without signing in; exporting via the built-in
Download button requires a Google account, but the underlying `batchedDataV2`
data API is accessible anonymously for public reports.

The automation flow:
1. `GET` the report page → Google sets `RAP_XSRF_TOKEN` cookie (anonymous session).
2. `POST https://datastudio.google.com/batchedDataV2` with the token + payload →
   returns JSON with (Month, Fuel type, Record Count) rows for `Autoveturë`.
3. Parse → map fuel types → upsert `data/Albania.csv`.

## 2. Report internals (reverse-engineered 2026-06-13)

These IDs were obtained by capturing a `batchedDataV2` network request in
Safari DevTools while viewing the report.

| Item | Value |
|---|---|
| Report ID | `407ce08b-d3ce-478e-9bc7-a50125f875f3` |
| Page ID (URL) | `VPWqB` |
| Page ID (numeric, in API body) | `24871631` |
| Component ID | `cd-p9hqinijec` |
| datasourceId | `7705f3ec-84aa-4432-bbed-d61775f98126` |
| revisionNumber | `13` |

Internal field IDs used in `queryFields`:

| Field | sourceFieldName | Maps to |
|---|---|---|
| Month / Date | `_3076010_` | `dateRangeDimensions` + `qt_date` |
| Vehicle type (Lloji) | `_73515086_` | filter target (= "Autoveturë") |
| Fuel type (Lenda Djegese) | `_818800577_` | dimension |
| Record Count | `datastudio_record_count_system_field_id_98323387` | metric |

**If DPSHTRR updates their data source**, `revisionNumber` in
`scripts/fetch_albania.py` will need bumping; the workflow will fail with an
HTTP 4xx or an empty response.  Check the Network tab on the report page for
the new `revisionNumber` value in the next `batchedDataV2` request body.

## 3. Fuel-type mapping (Lenda Djegese → gallery schema)

Derived from the DPSHTRR Looker table export (Jan–May 2026, `Autoveturë` only):

| DPSHTRR Lenda Djegese | Gallery column | Notes |
|---|---|---|
| Elektrik | BEV | |
| Hybrid plug-in, Benzinë/Elektrik | PHEV | |
| Hybrid plug-in, Naftë/Elektrik | PHEV | diesel PHEV |
| Hybrid Benzinë/Elektrik | HEV | |
| Hybrid Naftë/Elektrik | HEV | mild-hybrid diesel |
| Hybrid Benzinë/Gaz/Elektrik | HEV | gas-electric hybrid |
| Benzinë | PETROL | |
| Naftë | DIESEL | |
| Benzinë/Gaz, Gaz, Benzinë/Metan, Metan, Naftë/Gaz, `-` | OTHERS | LPG, CNG, Gas blends |

Albania **does** have separate PHEV and HEV tracking — both are small (≈84
PHEV, ≈944 HEV for the full Autoveturë fleet in Jan–May 2026).  No combined
hybrid footnote is needed.

## 4. What the figures actually count

**All first registrations in Albania** — both brand-new vehicles and imported
used vehicles being registered for the first time in the Albanian vehicle
database.  Albania has an exceptionally active used-car import market
(primarily from Western Europe and, increasingly, China), so headline monthly
totals (~5,000–8,000 in 2025–2026) are considerably larger than what a
new-car-only count would show.

The rapid BEV share growth reflects both new BEV sales and the surge in
imported used Chinese EVs.

Variant is `Whole` (no body-type or passenger/commercial sub-split available).

## 5. Historical data (pre-2026)

The DPSHTRR Looker report is published per calendar year (the 2026 report is
titled "year 2026").  Historical years (2019–2025) were bootstrapped into
`data/Albania.csv` from Robbie Andrew's pre-parsed mirror of the same DPSHTRR
figures (`robbieandrew.github.io/carsales/albania_carsales_monthly.csv`).
Attribution for all rows remains `dpshtrr.al`.

**When a new calendar year begins:** DPSHTRR will publish a new Looker report
for that year.  To onboard it:
1. Open the new report in a browser and copy the URL (new Report ID).
2. Capture a `batchedDataV2` request in DevTools.
3. Update `REPORT_ID`, `PAGE_ID_URL`, `PAGE_ID_NUM`, `COMPONENT_ID`,
   `DATASOURCE_ID`, `REVISION_NUMBER` in `scripts/fetch_albania.py`.
4. Dispatch the workflow with `--year-from <new_year>`.

## 6. Upsert & idempotence

Keyed on `(period, variant)`.  Normal CI runs pass `--year-from <current_year>`
so only the current calendar year is queried from the API; older rows are
untouched.  The commit step is change-gated, so steady-state daily runs after
a month is already in the CSV are a no-op.

## 7. Source attribution & footnote

* **`source` column** (`data/Albania.csv`): `dpshtrr.al` for every row.
* **`footnotes.csv`** (`Albania,Whole`):
  > Figures include first registrations of both new and imported used vehicles.
  > Historical series (pre-2026) compiled by R. Andrew from DPSHTRR open data.

## 8. Peculiarities to know about

* **New + used registrations.** Albania's figures are not comparable to
  new-car-only sources (Germany, France, …).  The BEV share is directionally
  meaningful but the denominator differs.
* **LPG / Gas bucket.**  LPG, CNG, and gas blends fold into `OTHERS`.  If
  `OTHERS` looks high, that is why.
* **DPSHTRR 403.** The report embed at `dpshtrr.al/open-data-dpshtrr-english`
  returns HTTP 403 to automated clients; the Looker Studio API endpoint
  (`datastudio.google.com`) does not.  We never fetch from `dpshtrr.al` directly.
* **revisionNumber.** Hardcoded to `13` (captured 2026-06-13).  Bump it in
  `scripts/fetch_albania.py` if the workflow starts failing with 4xx or
  returning empty data — then recapture from DevTools as described in §2.
* **Year-scoped report.** DPSHTRR appears to publish a fresh Looker report per
  calendar year.  Pre-2026 data will not appear when querying the 2026 report,
  and vice versa.  Follow the procedure in §5 when a new year begins.
* **Data starts 2019-01.**  Pre-2019 data is not available from DPSHTRR's open
  data platform.
