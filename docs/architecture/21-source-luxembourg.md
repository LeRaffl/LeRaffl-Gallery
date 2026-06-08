# 21 · Source: Luxembourg (lustat.statec.lu / STATEC SDMX)

Per-country source playbook for Luxembourg. The fetcher lives in
[`scripts/fetch_luxembourg.py`](../../scripts/fetch_luxembourg.py); the workflow
in [`.github/workflows/fetch-luxembourg.yml`](../../.github/workflows/fetch-luxembourg.yml).

## TL;DR

* **Source:** `lustat.statec.lu` — STATEC's .Stat Suite, a standards-compliant
  **SDMX 2.1 REST** endpoint. No scraping, no session juggling: one GET per
  variant returns the full monthly history as SDMX-CSV.
* **Dataflow:** `LU1,DF_D6122,1.1` — *"Number of new road vehicles registrations
  by type of vehicle and fuel"*. Author: STATEC / SNCA. Monthly, 2010-present.
* **Three variants**, all `OPERATION=N` (new registration):
  * **Whole** — `VEHICLE_TYPE=CAR` → `data/Luxembourg.csv`
  * **Vans** — `VEHICLE_TYPE=VAN` → `data/Luxembourg_Vans.csv`
  * **HDV** — `VEHICLE_TYPE=TRUCK+BUS+ROADTRAC` → `data/Luxembourg_HDV.csv`
* **Used Imports is NOT available** in the gallery's fuel-split form — see
  §6.

## 1. Why this is easy (for once)

Unlike the Swing/Inertia/PxWeb portals other countries force us through, lustat
is a textbook SDMX endpoint. We ask for:

* `Accept: application/vnd.sdmx.data+csv;labels=id` → SDMX-CSV with machine codes
  (`LU`, `ELC`, `CAR`) instead of localised labels.
* `dimensionAtObservation=AllDimensions` → a **flat one-row-per-observation**
  table. Every row carries its full 13-dimension key plus `TIME_PERIOD` and
  `OBS_VALUE`, so a plain `csv.DictReader` is all the parsing we need — no JSON
  pivot walking, no pagination.

## 2. The SDMX key

`DSD_VEH` has 13 dimensions, in this order:

```
REF_AREA . FREQ . MEASURE . VEHICLE_TYPE . MOTOR_CAPACITY . BRAND . MASS .
MOTOR_ENERGY . AGE_CL . OPERATION . COLOR . LENGTHREG . TABLE_ID
```

We pin only what we need and leave the rest empty (they resolve to `_Z`, "not
applicable"):

| Dimension      | Value                                   |
|----------------|-----------------------------------------|
| `REF_AREA`     | `LU` (national total)                   |
| `FREQ`         | `M` (monthly)                           |
| `MEASURE`      | `VEH` (vehicle counts, not `AGE`)       |
| `VEHICLE_TYPE` | `CAR` / `VAN` / `TRUCK+BUS+ROADTRAC`    |
| `MOTOR_ENERGY` | the leaf fuel codes (see §3)            |
| `OPERATION`    | `N` (registration of new vehicle)       |

Combining codes with `+` (e.g. `TRUCK+BUS+ROADTRAC`) returns one observation row
per code; the parser sums them per period.

## 3. The MOTOR_ENERGY hierarchy trap

`CL_MOTOR_ENERGY_VEH` is **hierarchical**. If you leave `MOTOR_ENERGY` blank the
API returns, for each period:

* the grand total `_T`,
* the parent aggregates `ELC_PET_HYB` and `ELC_DIE_HYB`, **and**
* their `*_PLUGIN` / `*_NOTPLUGIN` children.

Since each parent = its two children, summing everything **double-counts
hybrids**. We avoid this by requesting the **leaf codes only**:

```
ELC, ELC_PET_HYB_PLUGIN, ELC_DIE_HYB_PLUGIN,
ELC_PET_HYB_NOTPLUGIN, ELC_DIE_HYB_NOTPLUGIN,
PET, DIE, OTH, NONE
```

## 4. Column mapping

| Canonical | lustat MOTOR_ENERGY leaf code(s)                  |
|-----------|---------------------------------------------------|
| `BEV`     | `ELC`                                             |
| `PHEV`    | `ELC_PET_HYB_PLUGIN` + `ELC_DIE_HYB_PLUGIN`       |
| `HEV`     | `ELC_PET_HYB_NOTPLUGIN` + `ELC_DIE_HYB_NOTPLUGIN` |
| `PETROL`  | `PET`                                             |
| `DIESEL`  | `DIE`                                             |
| `OTHERS`  | `OTH` + `NONE`                                     |
| `TOTAL`   | sum of the six above                              |

Luxembourg CSVs use the **no-FLEXFUEL** column layout (matching the pre-existing
`data/Luxembourg.csv`): `period, time_interval, variant, source, BEV, PHEV, HEV,
PETROL, DIESEL, OTHERS, TOTAL, notes`.

Validated against the pre-existing CSV: with the leaf-only mapping, lustat
reproduces BEV/PHEV/HEV exactly for 2026-02..04 (e.g. 2026-02 BEV=1022,
PHEV=272, HEV=1564 — identical). Only the months whose values had been sourced
from **ACEA** showed small (≤21-unit, mostly `OTHERS` rounding) deltas, which the
upsert restates to lustat (the authoritative primary source).

## 5. Upsert: history stays, only changed months move

`upsert_csv` is keyed by `period`. It **preserves unchanged historical rows
verbatim** (keeping their original `source`/`notes`) and only rewrites a period
when a fuel count actually differs. This keeps the curated 2010+ history stable —
the only rows that move on the first lustat run are the handful of ACEA-sourced
tail months, which get corrected to lustat. New periods are appended with
`source = lustat.statec.lu`.

## 6. Why Used Imports is not available

`OPERATION` has codes for used vehicles (`I` imported, `I_T` total used reg.,
`T` inland transfer), but they carry **no fuel breakdown**:

* In `DF_D6122` (the by-fuel dataflow) `OPERATION` only ever returns `N`. Every
  used-vehicle `OPERATION` 404s.
* `DF_D6140` *"Number of used vehicles registrations by type of vehicle"* does
  carry `OPERATION=I/I_T/T`, but shares `DSD_VEH` with `MOTOR_ENERGY=_Z` only —
  i.e. counts by vehicle type with **no powertrain split**.

The gallery's BEV-trajectory model needs at least a BEV-vs-rest split, so a
fuel-split "Used Imports" series cannot be produced from lustat. If STATEC ever
publishes a *used-by-fuel* dataflow, add it as a fourth variant (see §9).

## 7. Schedule and idempotency

`fetch-luxembourg.yml` runs daily on the **1st–15th at 06:45 UTC** plus manual
`workflow_dispatch`. STATEC publishes around the 6th of the following month, so
we poll until the previous month's row materialises. The script's per-variant
early-exit (skip a variant whose CSV already has last month's row, unless
`--force`) makes re-runs free: no diff → no commit → no render trigger. 06:45 UTC
sits clear of the Netherlands (06:30) and Brazil (08:00) slots.

## 8. Workflow data flow

```
fetch-luxembourg.yml (cron / dispatch)
  └─ python scripts/fetch_luxembourg.py [--variant all]
       └─ GET lustat SDMX-CSV per variant → upsert per-variant CSV
  └─ detect changed CSVs (git diff, git add -N for new files)
  └─ commit changed CSVs
  └─ for each touched variant: gh workflow run render-country.yml
                                 -f country=Luxembourg -f variant=<V>
       └─ render_country.R reads data/Luxembourg[_<V>].csv → PNGs + params.csv
       └─ build-manifest.yml
```

## 9. Maintenance recipes

### Force-refetch / restate older months
```
python scripts/fetch_luxembourg.py --variant all --force
```
`--force` skips the "already current" early-exit; the upsert still only rewrites
periods whose values changed.

### Add a fourth variant
1. Add an entry to `VARIANTS` in `scripts/fetch_luxembourg.py` (its
   `vehicle_types` and target CSV path).
2. Add the `name:file` pair to the `for pair in …` loop **and** the `add:` list
   in `fetch-luxembourg.yml`, and the choice to the `variant` input.
3. Ensure the variant name is one of `render-country.yml`'s `variant` options.

### Inspect the structure / codelists by hand
```
# DSD + all codelists
curl -H "Accept: application/vnd.sdmx.structure+json;version=1.0" \
  "https://lustat.statec.lu/rest/dataflow/LU1/DF_D6122/latest?references=all&detail=full"
# A single variant's data
curl -H "Accept: application/vnd.sdmx.data+csv;labels=id" \
  "https://lustat.statec.lu/rest/data/LU1,DF_D6122,1.1/LU.M.VEH.CAR....ELC+PET+DIE..N...?dimensionAtObservation=AllDimensions"
```

## 10. What is **not** in this pipeline

* **Used Imports / stock / exports** — see §6 (no fuel split available).
* **Sub-national (canton/commune) breakdowns** — `CL_AREA_VEH` has 866 codes but
  we pin `REF_AREA=LU` (national total only).
* **Mass / engine-size / brand / colour splits** — available in DF_D6122 and
  sibling dataflows, but out of scope for the BEV trajectory.
