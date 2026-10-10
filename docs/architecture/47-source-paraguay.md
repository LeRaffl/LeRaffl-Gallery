---
country: Paraguay
slug: paraguay
method: file
summary: New-car import data for Paraguay from the customs administration's
  record-level open data — every import declaration item, with the tariff line that names
  the powertrain, the declared state new or used, brand and description. Paraguay builds no
  cars, so its car market is measured by its imports.
source_name: DNIT (customs, ex Dirección Nacional de Aduanas) — Portal de Datos Abiertos
source_url: https://datosabiertos.aduana.gov.py/ddaa/app/#/inicio
source_links:
- label: Customs open-data portal — monthly files ("Descargas")
  url: https://datosabiertos.aduana.gov.py/ddaa/app/#/inicio
  note: one CSV per month from 1997, item level ("Nivel_Item", ≈ 300 MB in 2026) and sub-item level; the fetcher reads the item level
- label: List of customs regimes (destinaciones)
  url: https://datosabiertos.aduana.gov.py/all_data/files/LISTADO_DE_DESTINACIONES.xlsx
  note: defines which regime codes are definitive imports for consumption (counted) and which are suspensive or entries into a bonded warehouse / free zone (not counted)
- label: CADAM — Cámara de Distribuidores de Automotores y Maquinarias
  url: https://www.cadam.com.py/
  note: the distributors' chamber; its import figures (press releases) are the reference the series was validated against
underlying: SOFIA, the customs declaration system of the Dirección Nacional de Ingresos Tributarios (DNIT)
auth: none
cadence: twice daily on the 1st–7th — the portal regenerates month M's files on the 1st of M+1
variants:
- Whole
variant_notes:
  Whole: New cars imported for consumption — NCM heading 87.03 (cars, SUVs, MPVs ≈ EU M1) with the declaration's own state NUEVO.
hev_split: true
hev_note: BEV, PHEV and HEV are the tariff subheadings of HS 2017 (8703.80 electric only; 8703.60/.70 plug-in hybrids, range extenders included; 8703.40/.50 hybrids that cannot be charged from the grid). HEV therefore counts full AND mild hybrids.
backfill: from 2017-01, the first month of the HS 2017 nomenclature that splits cars by powertrain; the customs files reach back to 1997 but without a powertrain split
scope_note: Imports for consumption of new cars (Whole) into Paraguay — counted when they clear customs, not when they are registered. Pickups and goods vehicles (NCM 87.04), golf carts, cars entering a bonded warehouse or free zone (counted when they leave it), temporary imports and leasing are in no variant.
caveats:
- These are imports, not registrations. Paraguay has no car industry, so over a year imports and the market are the same thing, and the distributors' chamber CADAM measures the market this way too. A single month can still run ahead of sales when importers stock up.
- The powertrain is the tariff line the importer declares and customs accepts. Validated against CADAM's published yearly electrified imports, 2021–2025, within 2–6 % every year.
- BEV here is lower than CADAM's published figure (2025 — 698 vs 858, −19 %). The gap is one of definition and is reconciled to a single car (see "Check against CADAM" below): CADAM adds up every declaration on the electric-only tariff line, so it counts the Nissan X-Trail e-POWER (a hybrid without a plug) as electric, counts a car that goes through a bonded warehouse or free zone twice — on entry and again on release — and includes used imports. This series counts each new car once, on release, and the e-POWER as a hybrid. Quoting CADAM's BEV figure next to this chart will therefore always show a gap.
- HEV includes mild hybrids (they share tariff subheading 8703.40 with full hybrids) — except where an importer declares them on a petrol line (Fiat Pulse/Fastback and Mazda CX-60/CX-90 mild hybrids, about 500 cars 2025–26), where they stay in PETROL.
- A few models are declared on the wrong electrified tariff line and are corrected from their description: the Nissan X-Trail e-POWER (a hybrid without a plug, declared as electric-only) is counted as HEV, range-extender models (Leapmotor C10 REEV, Deepal S05) as PHEV.
- Pickups are not in Whole (they are NCM 87.04, goods vehicles) — in Paraguay a large segment (Hilux, Ranger, …), so CADAM's "vehicles" figure is larger than Whole.
- Used-car imports (one and a half to three times the number of new cars every year since 2017, almost all combustion — BEV about 0.03 %) are kept as a data-only file (data/Paraguay_Used.csv): fetched every month, not charted. The new-car chart therefore describes well under half of the cars entering the Paraguayan fleet.
- One declaration item is one car. The quantity column is unreliable for cars (thousands of single cars a month carry "7"); a larger quantity is believed only when the item weighs that many cars.
processing:
- title: Download
  text:
  - The customs portal publishes every import and export declaration item of a month as one CSV (about 300 MB in 2026). The server is slow per connection but serves byte ranges, so the fetcher downloads a month as twelve parallel pieces (about a minute) and checks the size. A month is only used once its file was generated after the month ended.
- title: Pick the cars
  text:
  - Only imports of NCM heading 87.03 (passenger cars, SUVs, MPVs) count. Whether the car enters the Paraguayan market is decided by the customs regime of the declaration.
  decision:
    ask: Customs regime of the declaration?
    branches:
    - when: definitive import for consumption (IC… — incl. from a bonded warehouse, IC09), diplomatic (ID04/ID09) or from a free zone (ZF2I)
      then:
        ask: Declared state of the goods (USO)?
        branches:
        - when: NUEVO
          then: Whole
        - when: USADO
          then: Used (data-only file, not charted)
    - when: entry into a bonded warehouse (IDA…) or a free zone (ZF01)
      then: not counted
      note: the car is counted when it leaves for consumption (IC09 / ZF2I) — never twice
    - when: temporary import, leasing, complementary fraction (IFC1)
      then: not counted
- title: Powertrain
  text:
  - Since 2017 the international tariff nomenclature (HS 2017) splits cars by powertrain, and the declaration's tariff line (NCM, eight digits) carries it.
  decision:
    ask: Tariff subheading?
    branches:
    - when: 8703.80 — electric motor only
      then: BEV
    - when: 8703.60 / 8703.70 — combustion + electric, chargeable from the grid
      then: PHEV
      note: range extenders included
    - when: 8703.40 / 8703.50 — combustion + electric, not chargeable
      then: HEV
      note: full and mild hybrids
    - when: 8703.21–.24 — spark ignition only
      then: PETROL
    - when: 8703.31–.33 — diesel only
      then: DIESEL
    - when: 8703.90 — other
      then: OTHERS
- title: Correct the declared line
  text:
  - The tariff line is what the importer declares. Within the electrified lines a few models are declared on the wrong one, and their description says so — a short table of explicit rules (each with its reason) moves them; petrol and diesel lines are never moved, only reported for review.
  decision:
    ask: What does the description of an electrified line name?
    branches:
    - when: e-POWER on the electric-only line (Nissan X-Trail)
      then: HEV
      note: a series hybrid without a plug — the petrol engine only charges the battery
    - when: REEV / PHEV / DM-i / plug-in on the electric-only or the hybrid line
      then: PHEV
    - when: HEV / hybrid on the electric-only line
      then: HEV
    - when: anything else
      then: the declared line
- title: Count
  text:
  - One declaration item is one car — the quantity column is unreliable for cars, so a quantity above one is believed only when the item's net weight is that of that many cars (at least 600 kg each). A chassis number (VIN) quoted twice in one month counts once.
- title: Check against CADAM
  text:
  - CADAM, the distributors' chamber, publishes yearly electrified imports. BEV + PHEV + HEV together match within 2–6 % every year 2021–2025, PHEV and HEV in 2025 within 0.5 %. BEV is lower here (2025 — 698 vs 858) because the two count differently; going through every 2025 declaration on the electric-only line reconciles the two to a single car (698 + 82 + 68 + 9 = 857 vs 858).
  decision:
    ask: A declaration on the electric-only line (8703.80) that CADAM counts as a BEV — what does this series do with it?
    branches:
    - when: a new car released for consumption
      then: BEV (698 in 2025)
    - when: Nissan X-Trail e-POWER
      then: HEV, not BEV (82 in 2025)
      note: a hybrid without a plug — CADAM's own brand table has Nissan at 13 % of its BEVs
    - when: entry into a bonded warehouse or free zone (IDA3, ZF01, IT04)
      then: not counted on entry (68 in 2025)
      note: counted once, when it is released; a gross count takes it twice (15 Xiaomi into the free zone in 2025 and the same 15 out)
    - when: a used car (USADO)
      then: Used data file (9 in 2025)
market_breakdown: market/paraguay_top.json
market_designation_note: the model is read from the declaration's free-text description (the words after "MODELO", or the whole text when it is just a designation such as "TANK 400 PHEV 4WD"), first three words, upper-cased. A description without a model counts for its brand only.
market_powertrain_note: BEV / PHEV / HEV / petrol / diesel exactly as in the CSV — the tariff subheading; HEV includes mild hybrids.
fetcher: scripts/fetch_paraguay.py
workflow: .github/workflows/fetch-paraguay.yml
fragility_doc: docs/architecture/47-source-paraguay.md
data_file: data/Paraguay.csv
---

# 47 · Source: Paraguay (DNIT customs import declarations)

**Status: LIVE since 2026-10.** Fetcher `scripts/fetch_paraguay.py` (+ tests
`scripts/test_fetch_paraguay.py`) and `.github/workflows/fetch-paraguay.yml`.
Paraguay is the gallery's seventh South American market and its second
customs-based one after Nepal: the source counts cars when they are imported,
not when they are registered — in a country with no car industry the two are
the same market, a few weeks apart.

The facts below were established by temporary probe workflows (runs of
2026-10-02 on the development branch; since removed): the dev sandbox cannot
reach any `.gov.py` host, the GitHub runners reach the customs portal but not
the motor-vehicle registry.

## TL;DR

```
Source:    DNIT customs open data, datosabiertos.aduana.gov.py.
           File list: GET /ddaa/mainctrl/listaArchivos (JSON).
           Month:     /all_data/<YYYY>/<MES>/<YYYY>_<MES>_Nivel_Item.csv
           One row per declaration item, 42 columns, all goods, imports and
           exports; ≈ 300 MB a month in 2026 (100 MB in 2017).
Auth:      None. No login, no key.
Transfer:  ~0.4 MB/s per connection, HTTP Range honoured → 12 parallel
           ranges, ≈ 1 min a month; size checked against Content-Length.
Timing:    month M's files regenerated on the 1st of M+1 (Aug 2026: Sep 1
           14:23 UTC; Sep 2026: Oct 1 15:22 UTC). Used once the file's
           Last-Modified is after the month's end.
History:   2017-01 → today (HS 2017 powertrain subheadings).
Scope:     NCM 87.03, imports for consumption; USO NUEVO → Whole,
           USADO → Used (data-only CSV, never rendered).
Fuel:      the tariff subheading: .80 BEV · .60/.70 PHEV · .40/.50 HEV
           (full + mild) · .2x petrol · .3x diesel · .90 other.
Checked:   CADAM's yearly electrified imports 2021–2025: 0.94–1.04.
```

## 1. Why this source — and not the registry

The gallery's rule ([14](14-data-source-gaps.md)): direct from the registry
or a recognised official body, complete for the market, free.

- **The registry (DNRA) is not usable.** The Dirección Nacional del Registro
  de Automotores (judiciary, `www.dnra.gov.py`) has a statistics portal by
  vehicle type, fuel, brand and locality, but it **does not answer from
  outside Paraguay** (connect timeout from GitHub runners, 2026-10-02; the
  bare `dnra.gov.py` does not resolve) and, by every account found, publishes
  no monthly series. Its only open data on `datos.gov.py` are yearly fleet
  totals 2010–2019 without fuel.
- **Customs is complete by construction.** Every car that enters Paraguay —
  every brand, every importer, CADAM member or not — passes a customs
  declaration, and the declaration carries the tariff line that names the
  powertrain and the declared state (new / used). The open data are DNIT's own
  record-level extract, free and without login.
- **Imports are how Paraguay measures its market.** There is no domestic car
  production; CADAM's monthly market figure is "importación de vehículos 0 km".
  The precedent in the gallery is Nepal (customs HS 8703 imports,
  [32](32-source-nepal.md)).
- **What imports cannot see.** A month can run ahead of sales when importers
  stock up (e.g. before a tax or price change) — over twelve months this
  washes out. Re-exports are measured and negligible (§6).

## 2. Record → CSV row

| Column | Use |
|---|---|
| `OPERACION` | `IMPORTACION` → counted; `EXPORTACION` → export check only (§6) |
| `DESTINACION` | the customs regime (§4) |
| `USO` | `NUEVO` → Whole, `USADO` → Used, a data-only file (the declared state of the goods) |
| `POSICION ` (trailing space) | NCM tariff line `8703.80.00.000L` → heading 87.03 and the fuel column (§3) |
| `CANTIDAD ESTADISTICA`, `KILO NETO` | units (§5) |
| `AÑO`, `MES` | period (must equal the file's month — a mismatch aborts) |
| `MARCA ITEM`, `MERCADERIA` | `market/paraguay_top.json`; VIN for the double-count check (§5) |

The header has been identical from 2017-01 to 2026-09. CSV columns:
`BEV, PHEV, HEV, PETROL, DIESEL, OTHERS, TOTAL`; `source` = `DNIT customs import
declarations (datosabiertos.aduana.gov.py)`. Line-level upserts (invariant 2);
a row whose `source` is not ours is never overwritten without `--force`.

## 3. Fuel mapping

HS 2017 (in force in the Mercosur NCM from 2017-01) split heading 87.03 by
powertrain. The subheading is what the importer declares and customs accepts —
a legal classification, not a model-name heuristic.

| Subheading | Meaning | Column |
|---|---|---|
| 8703.21–.24 | spark-ignition engine only (by cylinder capacity) | PETROL (flex-fuel included) |
| 8703.31–.33 | compression-ignition only | DIESEL |
| 8703.40 | spark ignition + electric motor, not externally chargeable | HEV (full **and mild**) |
| 8703.50 | diesel + electric, not externally chargeable | HEV |
| 8703.60 | spark ignition + electric, externally chargeable | PHEV (range extenders included) |
| 8703.70 | diesel + electric, externally chargeable | PHEV |
| 8703.80 | electric motor only | BEV |
| 8703.90 | other | OTHERS |
| 8703.10 | snow vehicles, golf carts | in no variant |

Any other 87.03 subheading is reported; above 2 % of Whole the run aborts
(nomenclature change — HS 2022 kept these lines; HS 2027 should be checked).

### 3a. Corrections of the declared line (`RECLASS_RULES`)

The subheading is the importer's declaration, and customs accepts some odd
ones. Within the **electrified** lines a model is moved when its description
names its real powertrain — ordered rules, first match wins, every rule with a
test (`test_reclass_rules`, including look-alikes such as CHEVROLET, which
contains "HEV"):

| Declared | Description names | → | Cars 2017–2026-09 |
|---|---|---|---:|
| BEV (8703.80) | `E-POWER` — Nissan X-Trail e-POWER, a series hybrid: the petrol engine only charges the battery, no plug | HEV | 290 |
| BEV, HEV | `REEV`, `PHEV`, `DM-i`, plug-in — Leapmotor C10 REEV, Deepal S05, GWM New H6 PHEV, BMW X5 PHEV | PHEV | 52 |
| BEV | `HEV`, `HYBRID` | HEV | 0 (a single BMW) |

Without the first rule the BEV series would be about 9 % too high in 2025–26
(166 e-POWER on 1,894 BEV; 290 in 2023–26).
**Petrol and diesel lines are never moved.** A description there that names
a hybrid or plug-in is listed in the run report ("Petrol/diesel lines whose
description names a hybrid or plug-in"); in 2017–2026 that was 553 cars,
almost all mild hybrids that importers declare as petrol cars (Fiat Pulse /
Fastback "MILD", Mazda CX-60 / CX-90 "MILD HYBRID"), plus single Renault
Arkana E-Tech and Porsche E-Hybrid units. They stay in PETROL.

## 4. Which customs regimes count

From DNIT's own list of regimes (`LISTADO_DE_DESTINACIONES.xlsx`):

| Regime | Meaning | Counted? |
|---|---|---|
| `IC04` | import for consumption with transport document — **≈ 97 % of all cars** | yes |
| `IC09` | import for consumption **from a bonded warehouse** | yes |
| `IC01/02/03/07/08/13/20…` | re-imports, regularisation (Law 608/95), temporary → definitive, advance OEA | yes (definitive) |
| `ID04`, `ID09` | diplomatic imports | yes (definitive) |
| `ZF2I` | import **from a free zone** to consumption | yes |
| `IDA3`, `IDA2` | **entry into** a bonded warehouse | no — the car counts when it leaves (`IC09`) |
| `ZF01` | **entry into** a free zone | no — counted on `ZF2I` |
| `IT…` | temporary import (suspensive) | no |
| `IML…` | leasing (suspensive) | no |
| `IFC1` | "importación de fracciones complementarias" | **no** — DNIT lists it as neither definitive nor suspensive (`*`), and a fraction was seen to repeat a car of the main declaration (VIN `JY43GGA0XPA051489`, `IC04` + `IFC1`, 2025-03). At most 1.3 % of new cars a year (2026: 392, mostly GWM and Jetour) |

An unknown regime is reported and, above 2 % of Whole, aborts the run.

## 5. Units and double counts

- **One item is one car.** `CANTIDAD ESTADISTICA` is unreliable for cars: in
  2026-08, 3,437 of 7,640 car items carried `7,0` although weight and value
  are those of one car (a used Ford Ranger of 1,700 kg, a new Corolla Cross of
  1,435 kg). A quantity ≥ 2 is believed only when the item's net weight is at
  least 600 kg per unit (genuine multi-car items carry the weight of all cars).
- **VINs.** About 2 % of items quote the chassis number in the description.
  Across 2017-01..2026-09, about 6,200 counted cars quote one; 8 VINs
  appeared twice — 7 of them twice in the same month and declaration (now
  counted once), one an IFC1 fraction (§4, no longer counted). The only one
  left is a Tesla imported new in 2021 and re-imported used in 2024
  (legitimately two imports).

## 6. Validation

**CADAM's yearly electrified imports** (BEV + PHEV + HEV, press releases):

| Year | Customs (this fetcher) | CADAM | ratio |
|---|---:|---:|---:|
| 2021 | 565 | 543 | 1.04 |
| 2022 | 1,266 | 1,291 | 0.98 |
| 2023 | 1,474 | 1,560 | 0.94 |
| 2024 | 2,399 | 2,443 | 0.98 |
| 2025 | 3,876 | 4,049 | 0.96 |

2025 by class: BEV 698 vs 858, PHEV 1,100 vs 1,105, HEV 2,078 vs 2,086 —
PHEV and HEV within 0.5 %. BEV is 19 % below CADAM — a difference of
definition, fully accounted for by a probe over every 2025 declaration
(2026-10-03):

| 2025 BEV | units |
|---|---:|
| this fetcher (8703.80, new, imports for consumption, e-POWER moved to HEV) | 698 |
| + Nissan X-Trail e-POWER, kept as BEV as declared | +82 |
| + bonded-warehouse / free-zone **entries** (IDA3 44, ZF01 22, IT04 2) | +68 |
| + used BEV imports | +9 |
| = every 8703.80 declaration, gross | 857 |
| CADAM | 858 |

So CADAM counts the tariff line gross and literally. Its own brand ranking
confirms the e-POWER (Nissan 13.1 % of BEV January–November 2025; the
declarations give 12.6 %). The gross count also takes a warehoused car twice —
once on entry and again on release: 15 Xiaomi entered the free zone (ZF01) and
the same 15 left it for consumption (ZF2I); BMW 15 into a bonded warehouse
(IDA3), 14 out (IC09). This fetcher counts each car once, on release, and
the e-POWER as the hybrid it is, so its BEV figure is the lower and the
correct one. HEV and PHEV reconcile the same way (gross new HEV 2,066 vs
CADAM 2,086; PHEV, where CADAM appears to drop the entries, 1,099 vs 1,105). First half of 2026: 3,924 vs 4,098 (0.96).

**Fleet.** OLACDE's Latin-American e-mobility monitor (June 2026) counts 4,359
light electric vehicles in circulation in Paraguay in March 2026. Cumulative
BEV + PHEV imports (new + used) since 2017 are 3,879 to the end of 2025 and
4,752 to March 2026 — the same order, imports somewhat above the fleet as
expected (dealer stock, scrappage, the monitor's lag).

**Re-exports** of cars (NCM 87.03 `EXPORTACION`) are at most 230 a year
(2025: 37 new, 193 used) against ≈ 30,000 new and ≈ 60,000 used imports — not
subtracted.

**Totals.** CADAM's "vehicles imported" (2025: > 38,000) include pickups,
vans and trucks (NCM 87.04); Whole (cars only) was 28,987 in 2025.

## 6a. Reading the fit

The electrified share of new cars rose from 2.6 % (2021) to 13.4 % (2025) and
24 % in 2026 to September, with BEV 2.4 % (2025) → 4.0 % (2026). August 2026
stands out (32 % electrified — GWM and Jetour PHEV shipments); September came
in at 27 %. Single import months are lumpier than registrations would be.

## 7. Outputs

- `data/Paraguay.csv` (monthly, 2017-01 →), rendered.
- `data/Paraguay_Used.csv` (monthly, 2017-01 →) — **data only** (owner decision
  2026-10): BEV is about 0.03 % of used imports, so the fit is flat and the
  chart said nothing ("-Inf years"). Kept current by every run, never passed to
  `render-country.yml` (`RENDERED_VARIANTS`), no `params.csv` row, not in the
  backtest (`DATA_ONLY_SERIES` in `R/build_backtest.R` and
  `scripts/check_country_integration.py`).
- `market/paraguay_top.json` — trailing-12-month top brands and models per
  class (BEV, PHEV, HEV, and since 2026-10 PETROL / DIESEL with their models)
  for Whole, built from the month store
  `market/paraguay_months.json` (a normal run downloads only two months, so it
  cannot re-read twelve). Brand = `MARCA ITEM` with aliases merged
  (`GREATWALL` → GREAT WALL, `LYNK  CO` → LYNK & CO, `MERCEDES BENZ` →
  MERCEDES-BENZ); model = first three words after `MODELO` in the free text
  (`model_of()`), blank when there is none.

## 8. Operations and debugging

```mermaid
sequenceDiagram
    participant Cron as fetch-paraguay.yml (cron / dispatch)
    participant Test as test_fetch_paraguay.py
    participant Py as fetch_paraguay.py
    participant DNIT as datosabiertos.aduana.gov.py
    participant CSV as data/Paraguay*.csv
    participant Top as market/paraguay_top.json (+ _months.json)
    participant Render as render-country.yml
    Cron->>Test: tariff map + regimes + units + VIN + header + upsert tests (gate)
    Cron->>Py: run
    Py->>DNIT: listaArchivos → newest files; HEAD → Last-Modified after month end?
    Py->>CSV: newest complete month already from DNIT in every CSV?
    alt yes
        Py-->>Cron: no-op (two small requests)
    else no
        Py->>DNIT: newest two months, 12 parallel byte ranges each
        Py->>Py: 87.03 × regime × USO → variant; subheading → column
        Py->>CSV: line-level upserts (changed lines only)
        Py->>Top: month store + trailing-12-month top list
        Py-->>Cron: run report → step summary
        Cron->>Render: once, if Whole changed (Used is data only)
    end
```

- **Schedule:** `55 16,22 1-7 * *`. The first HTTP calls are the file list
  and one HEAD; when every CSV already has the newest complete month the run
  ends there.
- **Normal run:** downloads the newest two months (≈ 2 × 300 MB, ≈ 2 min).
- **Backfill / rebuild:** dispatch with `backfill = true` (117 months, ≈ 70
  min). Locally, `--cache-dir DIR` keeps each parsed month and resumes an
  interrupted backfill (bump `RULES_VERSION` when a counting rule changes).
- **After each monthly run:** read the step summary — counted / excluded
  regimes, items whose quantity was not believed, the double-count line,
  exports, the plug-in list by brand and model, unknown subheadings/regimes.

**If a run fails — where to look:**

| Symptom in the log | Cause | Fix |
|---|---|---|
| `No monthly files in the portal's file list` | `listaArchivos` changed shape | open `/ddaa/mainctrl/listaArchivos`; adjust `list_month_urls()` |
| `RemoteDisconnected` / `range … failed` after retries | the portal is down or throttling | re-run later; the portal drops single connections now and then (retried 6×) |
| `got N bytes, Content-Length M` | a truncated transfer | re-run |
| `file generated … before the month ended; not used yet` | normal on the 1st before the regeneration | nothing |
| `Schema drift: columns [...]` | DNIT renamed a column | map it in `REQUIRED` / `resolve_columns()`; add the header to the tests |
| `Row for … in the file for …` | a file holds another month | check the portal by hand; report to DNIT |
| `unknown subheading / regime / USO … not writing` | a new regime code, a nomenclature change (HS 2027), or a new USO value | look it up in `LISTADO_DE_DESTINACIONES.xlsx`; add it to `CONSUMPTION_REGIMES` / `EXCLUDED_REGIMES` / `POSITION_FUEL` with a test |
| `below 25 % of the trailing median` | a partial file — or a real collapse | compare with CADAM's press release; `force` if genuine |
| commit step `non-fast-forward` | a concurrent commit | already rebased by the action; re-run |
