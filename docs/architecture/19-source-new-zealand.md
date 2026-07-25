---
country: New Zealand
slug: new-zealand
method: manual
summary: New light-vehicle registrations for New Zealand from the Ministry of Transport's fleet statistics.
source_name: transport.govt.nz — fleet statistics
source_url: https://www.transport.govt.nz/statistics-and-insights/fleet-statistics/
source_links:
- label: data.govt.nz vehicle fleet statistics dataset
  url: https://catalogue.data.govt.nz/dataset/vehicle-fleet-statistics
  note: the EV/hybrid fallback resource
underlying: NZ Ministry of Transport / Waka Kotahi
auth: none
cadence: entered by hand once the Ministry publishes, usually the 5th–10th of the following month
variants:
- Whole
variant_notes:
  Whole: All new light-vehicle registrations, GVM under 3,500 kg — cars and light commercials combined.
hev_split: true
backfill: none
scope_note: All new light registrations (GVM < 3,500 kg) — passenger cars and light commercials combined.
caveats:
- Automated fetching has been switched off since 2026-06 — both upstream endpoints now sit behind Imperva
  anti-bot. Months are read off the published dashboard and entered by hand.
- Cars and light commercials are not separated by this source.
- Flexfuel is not reported; OTHERS (LPG etc.) is typically 0 in recent months.
- The whole series before automation was compiled by Prof. Ray Willis.
fetcher: scripts/fetch_new_zealand.py
workflow: .github/workflows/fetch-new-zealand.yml
fragility_doc: docs/architecture/19-source-new-zealand.md
data_file: data/New Zealand.csv
---

# 19 · Source: New Zealand (transport.govt.nz)

> ### ⚠️ Status (since 2026-06): **New Zealand is a manual source.**
>
> Both the primary `/inner` endpoint and the `catalogue.data.govt.nz` CKAN
> fallback are now served behind Imperva (Incapsula/Reese84). Plain
> `requests` from a GHA runner receives a JS challenge stub / "Pardon Our
> Interruption" interstitial, not data. The scheduled trigger in
> `.github/workflows/fetch-new-zealand.yml` is **commented out**;
> `workflow_dispatch` is retained for manual runs from an unblocked host.
>
> **In the meantime the maintainer reads the published dashboard and enters
> each month by hand** — that is why rows through 2026-06 exist even though
> nothing is fetching them. New rows keep the
> `transport.govt.nz & Prof. Ray Willis` source string.
>
> Everything below §2 describes the *automated* path, which is dormant but
> still the code in the repo. An alternate ingestion path (Stats NZ API or
> NZTA open-data ArcGIS) is the likely longer-term fix.

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
Schedule:  NONE — cron disabled 2026-06 (Imperva). Manual entry; the dormant
           cron was twice daily 06:00 & 14:00 UTC on the 5th–12th
Scripts:   scripts/fetch_new_zealand.py   (dispatch-only)
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
10th** of the following month. That is when the maintainer currently reads
the dashboard and enters the row.

The workflow's cron is **disabled** (see the status banner). When it ran, it
polled twice daily on the 5th–12th, and those two slots are still the ones
to restore if an unblocked ingestion path is found:

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
- **Anti-bot, and it is currently fatal.** As of 2026-06 both transport.govt.nz
  and catalogue.data.govt.nz sit behind Imperva (Incapsula/Reese84). A GHA
  runner gets a 212-byte JS challenge stub from `/inner` and a "Pardon Our
  Interruption" HTML interstitial from the CKAN API — neither is JSON, and
  plain `requests` cannot pass either. This is what took the cron down; see
  the status banner at the top.

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
