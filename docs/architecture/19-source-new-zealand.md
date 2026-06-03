# 19 · Source: New Zealand (transport.govt.nz)

The New Zealand Ministry of Transport (MoT) publishes monthly light motor
vehicle registration statistics via an interactive fleet-statistics dashboard
at `transport.govt.nz/statistics-and-insights/fleet-statistics`.

## TL;DR

```
Variants:
  Whole   data/New Zealand.csv   All new light registrations by fuel type

NOTE: No Private / Rental / Industry split is available from this source.
  The dashboard aggregates all new registrations for light vehicles
  (GVM < 3,500 kg — passenger cars and light commercial vehicles combined).

Source:    transport.govt.nz fleet-statistics /inner AJAX endpoint
Fallback:  catalogue.data.govt.nz CKAN resource fc87b220 (EV/hybrid only)
Auth:      None
FLEXFUEL:  Not reported — column absent from the CSV
OTHERS:    LPG and other minor fuels; typically 0 in recent months
Schedule:  Twice daily 06:00 & 14:00 UTC, 5th–12th of the following month
Scripts:   scripts/fetch_new_zealand.py
Workflow:  .github/workflows/fetch-new-zealand.yml
```

## 1. CSV schema

`data/New Zealand.csv` uses the **12-column schema (no FLEXFUEL)**. New
Zealand does not report ethanol/flexfuel registrations.

```
period,time_interval,variant,source,BEV,PHEV,HEV,PETROL,DIESEL,OTHERS,TOTAL,notes
```

All rows carry `variant = "Whole"` and `time_interval = "monthly"`.

## 2. Data flow

```
1. GET transport.govt.nz/statistics-and-insights/fleet-statistics/
   light-motor-vehicle-registrations/inner
   → AJAX endpoint returning chart payload (JSON or HTML-with-embedded-JSON)

2. Parse response:
   A) Highcharts-style JSON: {xAxis.categories, series[{name, data}]}
   B) Tabular rows: {data: [{period, fuel_type, count}]}
   C) HTML fragment: JSON extracted from <script> tags / data-chart= attrs

3. Map fuel-type labels → canonical columns (see § 4 below)

4. Compute TOTAL = sum of all fuel columns
5. Upsert data/New Zealand.csv (keyed on period)
```

Fallback (when /inner is unreachable or returns unrecognised format):

```
1. GET catalogue.data.govt.nz/api/3/action/resource_show
   ?id=fc87b220-59ec-4678-a09a-88497bb1018d
   → CKAN metadata with resource download URL

2. Download CSV from resource URL
3. Map columns heuristically (period + fuel-type columns)

⚠ WARNING: CKAN resource covers EV/hybrid only (resource name:
   "Monthly electric and hybrid light vehicle registrations").
   PETROL/DIESEL/TOTAL will be 0 or partial. Script emits a WARNING
   and the operator must re-run once the primary source recovers.
```

## 3. Month publication schedule

MoT typically publishes the previous month's data between the **5th and
10th** of the following month. The workflow polls twice daily on the 5th–12th:

| Time slot | UTC | Rationale |
|-----------|-----|-----------|
| Morning   | 06:00 | ~19:00 NZ time — data usually available |
| Afternoon | 14:00 | ~03:00 NZ time — catches late releases |

The fetch script self-throttles: if the latest period already in the CSV equals
the previous calendar month and `--force` is not set, the run exits immediately
without hitting the source.

## 4. Fuel-type label mapping

The transport.govt.nz dashboard uses these labels (verified against 2026 data):

| Dashboard label                 | CSV column |
|---------------------------------|------------|
| Battery Electric / BEV          | BEV        |
| Plug-in Hybrid / PHEV           | PHEV       |
| Full Hybrid / Hybrid / HEV      | HEV        |
| Petrol                          | PETROL     |
| Diesel                          | DIESEL     |
| LPG / Gas / Other / Other Fuel  | OTHERS     |

The complete `FUEL_MAP` (including aliases) lives in `scripts/fetch_new_zealand.py`.
If a new label appears, the script prints `WARNING: unmapped fuel label <label>`
and skips that category. Add the new label to `FUEL_MAP` and re-run with `--force`.

## 5. Known limitations

- **No Private/Rental split.** The dashboard only exposes total new registrations.
  A breakdown by buyer type is not publicly available from MoT.
- **Light vehicles only.** Covers GVM < 3,500 kg (passenger cars + light
  commercial). Heavy vehicles (HDV) are on a separate NZTA/MoT page and not
  currently ingested.
- **Response-format fragility.** The `/inner` endpoint is an internal AJAX
  endpoint, not a documented public API. If MoT redesigns the dashboard, the
  parser may need updating. The `--debug` flag prints the raw response to help
  diagnose format changes.
- **CKAN fallback is EV/hybrid only.** The data.govt.nz CKAN resource
  (`fc87b220`) is named "Monthly electric and hybrid light vehicle registrations"
  and may not include petrol/diesel totals. Use only as a temporary fallback.
- **IP restrictions.** transport.govt.nz and data.govt.nz use IP allowlists that
  block some cloud environments. The workflow runs on `ubuntu-latest` (GitHub
  Actions / Azure) which has not been blocked in practice.

## 6. Manual override

Dispatch `fetch-new-zealand.yml` manually with:

- `since = YYYY-MM` — backfill from that month through last month
- `force = true` — re-fetch months already in the CSV
- `debug = true` — print raw /inner response to the workflow log (useful when
  the response format changes or labels are unknown)
- `months = N` — re-fetch the trailing N months (default 3)

## 7. Historical data

`data/New Zealand.csv` contains monthly data from **2012-01** onward, originally
compiled by **Prof. Ray Willis** and sourced from `transport.govt.nz`. The
automated fetcher writes new months on top of this history without touching
pre-existing rows (unless `--force` is set).

The source field on historical rows reads `"transport.govt.nz & Prof. Ray Willis"`.
New rows written by the automated fetcher use `"transport.govt.nz"`.
