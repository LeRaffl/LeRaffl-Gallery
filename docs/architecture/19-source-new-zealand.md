---
country: New Zealand
slug: new-zealand
method: api
summary: First registrations of light vehicles in New Zealand — new and used imports, cars and
  light goods vehicles — counted automatically from NZTA Waka Kotahi's open Motor Vehicle
  Register, the register behind the Ministry of Transport's fleet statistics.
source_name: NZTA Waka Kotahi — Motor Vehicle Register (open data)
source_url: https://opendata-nzta.opendata.arcgis.com/datasets/NZTA::motor-vehicle-register-1/about
source_links:
- label: Motor Vehicle Register on NZTA's open-data hub
  url: https://opendata-nzta.opendata.arcgis.com/datasets/NZTA::motor-vehicle-register-1/about
  note: one record per currently-registered vehicle with its first NZ registration month, import status, vehicle class, motive power, make and model; refreshed monthly, CC BY 4.0
- label: Hub item the fetcher resolves the service from
  url: https://opendata-nzta.opendata.arcgis.com/api/search/v1/collections/all/items/7b4df667d5014f1a93e6050b31d18407
  note: its `url` names the current ArcGIS feature service (it changes when NZTA republishes)
- label: Ministry of Transport — light motor vehicle registrations
  url: https://www.transport.govt.nz/statistics-and-insights/fleet-statistics/
  note: the dashboard the history up to 2026-09 was compiled from (behind Imperva since 2026-06)
underlying: Motor Vehicle Register (MVR), run by NZ Transport Agency Waka Kotahi
auth: none
cadence: twice daily on the 3rd–20th, 04:55 and 18:55 UTC — NZTA reloads the register once a month, accurate to the end of the previous month (September 2026 was loaded on 6 October)
variants:
- Whole
variant_notes:
  Whole: Every light vehicle registered in New Zealand for the first time in the month — new vehicles and used imports, passenger cars (classes MA, MB, MC) and goods vehicles up to 3.5 t (NA). This is the scope of the series since 2012, not EU M1.
hev_split: true
hev_note: PHEV and HEV come from the register's motive power. Range-extended EVs ("ELECTRIC [PETROL EXTENDED]") are counted as PHEV, as in the history. HEV is whatever was entered as a petrol or diesel hybrid — mostly full hybrids, but some 48 V mild-hybrid utes are registered as "DIESEL HYBRID" and count here too.
backfill: hand-compiled by Prof. Ray Willis from the Ministry of Transport's dashboard, 2012-01 to 2026-03; 2026-04 on from the register (the hand rows for 2026-04..09 were replaced, see §7)
scope_note: First registrations of light vehicles in New Zealand — new and used imports together, cars and light goods vehicles (GVM up to 3.5 t). New Zealand's used-import market is about 40 % of all light registrations and mostly hybrids, so this series has far more HEV than a new-car series would.
caveats:
- The series includes used imports (about 40 % of the volume) and light goods vehicles, as the Ministry of Transport's light-vehicle statistics always did. It is not comparable in volume with an EU-style new-passenger-car series.
- The register lists vehicles registered today. A month counted later misses the vehicles scrapped or exported since, so each month is written once, right after it ends. Rows counted later than that say "undercount" in their notes (about 1 % for 2026-04..06).
- NZTA leaves out vehicles whose owners have a confidential listing; with the deregistrations this puts the register about 1 % below the Ministry's published figures.
- Some 48 V mild-hybrid utes are registered as diesel hybrids and count as HEV.
processing:
- title: Ask the register
  text:
  - The register is an ArcGIS feature service with about 5.8 million records. The fetcher never downloads them; it asks the service for grouped counts (first registration month × import status × motive power), a handful of small JSON requests. The service address changes when NZTA republishes the register, so it is looked up from the stable open-data item on every run. A month is only read once the register's load date is after the month ended.
- title: Pick the vehicles
  text:
  - Every record carries its import status, the vehicle class and the year and month of its first registration in New Zealand. Together they decide whether it belongs to the series — the same scope the Ministry of Transport's light-vehicle statistics used, so the history continues without a break.
  decision:
    ask: Import status?
    branches:
    - when: NEW or USED (used import)
      then:
        ask: Vehicle class?
        branches:
        - when: MA, MB, MC — passenger car, passenger van, off-road passenger vehicle
          then: Whole
        - when: NA — goods vehicle up to 3.5 t
          then: Whole
        - when: anything else — heavy goods (NB, NC), buses (MD, ME), motorcycles and mopeds (L), trailers (T), tractors and machines
          then: in no variant
    - when: RE-REG (re-registered) or SCRATCH (scratch-built)
      then: in no variant
      note: not a first registration
- title: Powertrain
  text:
  - The register's motive power is mapped one to one. A label the fetcher does not know is counted in OTHERS and listed in the run report; above 1 % of a month it stops the run until someone decides its column.
  decision:
    ask: Motive power?
    branches:
    - when: ELECTRIC
      then: BEV
    - when: PLUGIN PETROL HYBRID, PLUGIN DIESEL HYBRID
      then: PHEV
    - when: ELECTRIC [PETROL EXTENDED], ELECTRIC [DIESEL EXTENDED]
      then: PHEV
      note: range extenders, as in the history (no EREV column)
    - when: PETROL HYBRID, PETROL ELECTRIC HYBRID, DIESEL HYBRID, DIESEL ELECTRIC HYBRID
      then: HEV
      note: some 48 V mild-hybrid utes included
    - when: PETROL
      then: PETROL
    - when: DIESEL
      then: DIESEL
    - when: LPG, CNG, hydrogen fuel cell, OTHER, blank
      then: OTHERS
- title: Check it
  text:
  - The month's total must be within half to twice the same month a year earlier. Every run also recounts the three months before and compares them with the rows already in the chart; a difference above 5 % is flagged for review. Only then is the month written — as a new line, never by rewriting earlier ones.
market_breakdown: market/new_zealand_top.json
market_heading: Who sells the electrified light vehicles
market_designation_note: Make and model as the entry certifier typed them on the register, upper-cased; a model typed with the brand in front is merged with the plain one. Some models are generic (BMW's electric cars are partly registered as model "I").
market_powertrain_note: BEV / PHEV / HEV exactly as in the CSV, and the same scope — new and used imports together, so the BEV list includes the used Nissan Leafs that dominate New Zealand's used-import EVs.
fetcher: scripts/fetch_new_zealand.py
workflow: .github/workflows/fetch-new-zealand.yml
fragility_doc: docs/architecture/19-source-new-zealand.md
data_file: data/New Zealand.csv
---

# 19 · Source: New Zealand (NZTA Motor Vehicle Register)

**Status: LIVE since 2026-10.** Fetcher `scripts/fetch_new_zealand.py` (+ tests
`scripts/test_fetch_new_zealand.py`), workflow `.github/workflows/fetch-new-zealand.yml`.
Replaces the transport.govt.nz fetcher, whose cron was switched off in 2026-06
when both of its endpoints went behind Imperva (Incapsula/Reese84); from then
until 2026-09 the maintainer entered each month by hand from the dashboard.

## TL;DR

```
Source:    NZTA open data, Motor Vehicle Register (ArcGIS feature service)
           resolved from Hub item 7b4df667d5014f1a93e6050b31d18407
Auth:      none (CC BY 4.0)
Query:     grouped counts (outStatistics) — no record download
Scope:     IMPORT_STATUS NEW + USED, CLASS MA/MB/MC/NA, by first NZ registration month
Variants:  Whole   data/New Zealand.csv
Columns:   BEV, PHEV, HEV, PETROL, DIESEL, OTHERS, TOTAL (no FLEXFUEL)
Top lists: market/new_zealand_top.json (BEV / PHEV / HEV, trailing 12 months + single months)
Schedule:  55 4,18 3-20 * *   (self-throttling; a no-op costs no HTTP request)
```

## 1. Why this source

The Ministry of Transport's light-vehicle statistics — the source of the whole
history — are read from the Motor Vehicle Register. NZTA publishes that
register itself as open data: one record per currently-registered vehicle,
refreshed monthly, with the year and month of its first registration in New
Zealand, whether it was new or a used import, its vehicle class, motive power,
make and model. So the register gives the same numbers as the Ministry, by a
route that is not behind a bot wall, and adds brands and models.

It clears the gallery's bar ([14](14-data-source-gaps.md)): registry-based (no
member-brand completeness gap), monthly, and with the same BEV / PHEV / HEV /
petrol / diesel split as the legacy series — no coarser hybrid bucket.

## 2. Scope — the legacy series, reproduced

The doc used to describe the series as "new light registrations". It never
was: the Ministry's figure, and so every row since 2012, counts **new and
used-import** light vehicles. The register settles it — with used imports in,
it matches the legacy rows in every column; without them it is 40 % short and
has half the hybrids.

| Register field | Kept | Why |
|---|---|---|
| `IMPORT_STATUS` | `NEW`, `USED` | first registrations; `RE-REG` and `SCRATCH` are not |
| `CLASS` | `MA`, `MB`, `MC`, `NA` | the Ministry's "light" = passenger vehicles + goods vehicles ≤ 3.5 t |
| month | `FIRST_NZ_REGISTRATION_YEAR` / `_MONTH` | the month the plates were issued |

Overlap with the legacy rows (register queried 2026-10-09, register − CSV):

| Month | BEV | PHEV | HEV | PETROL | DIESEL | TOTAL |
|---|---:|---:|---:|---:|---:|---:|
| 2025-09 | −4 | −5 | −91 | −111 | −68 | −279 (−1.3 %) |
| 2025-12 | −5 | −12 | −61 | −93 | −63 | −234 (−1.5 %) |
| 2026-01 | −9 | −3 | −54 | −70 | −59 | −195 (−1.0 %) |
| 2026-02 | −1 | −1 | −35 | −67 | −50 | −154 (−0.9 %) |
| 2026-03 | −17 | +4 | −65 | −64 | −76 | −218 (−0.9 %) |
| 2026-04 | −105 | −4 | −42 | −2,360 | −449 | −2,960 (−15.3 %) |
| 2026-09 | −41 | −6 | −8 | −798 | −753 | −1,606 (−6.1 %) |

Through 2026-03 the register is about 1 % below in every column — vehicles
deregistered since, and owners with a confidential listing whom NZTA leaves
out. The six months entered by hand from 2026-04 are another matter: BEV, PHEV
and HEV still agree, but petrol and diesel are several hundred to 2,360
vehicles higher every month. Those rows were read off the dashboard by hand after the
fetcher stopped (the 2026-04 row carries its URL). Why they differ is not
known — possibly a view that also counts re-registrations, which are almost
all petrol and diesel — but they are not the series the history is. See §7 for how they were handled.

Earlier months undercount more, because the register only lists vehicles
still registered: 2024 is about 4 % short, 2019 about 15 %, 2015 about 30 %.
That is why the fetcher writes each month once, right after it ends, and does
not rebuild the history (invariant 3).

## 3. Record → row

```
1. GET the Hub item → `url` = the current FeatureServer (fallback: the last
   known one, with a warning).
2. GET the service + table metadata → required fields present?
   dataLastEditDate = the date the register was loaded.
3. Is the load date after the target month ended?  no → no-op (error from the 20th).
4. Grouped count: where first-registration month in [target−3 … target] and the
   scope of §2, group by year, month, IMPORT_STATUS, MOTIVE_POWER.
5. Map MOTIVE_POWER → column (§4); TOTAL = the sum.
6. Checks (§5) → upsert the target month, line-level.
7. Top lists: the same scope over the 12 months to the target, electrified
   powertrains only, grouped by MAKE and MODEL as well (§6).
```

## 4. Motive power → column (`MOTIVE_MAP`)

| Register `MOTIVE_POWER` | Column |
|---|---|
| ELECTRIC | BEV |
| PLUGIN PETROL HYBRID, PLUGIN DIESEL HYBRID | PHEV |
| ELECTRIC [PETROL EXTENDED], ELECTRIC [DIESEL EXTENDED] | PHEV (EREV folded in) |
| PETROL HYBRID, PETROL ELECTRIC HYBRID, DIESEL HYBRID, DIESEL ELECTRIC HYBRID | HEV |
| PETROL | PETROL |
| DIESEL | DIESEL |
| LPG, CNG, ELECTRIC FUEL CELL HYDROGEN, PLUG IN FUEL CELL HYDROGEN HYBRID, OTHER, blank | OTHERS |

Light vehicles 2012-01 → 2026-09 by label: petrol 1.97 M, diesel 684k, petrol
hybrid 428k, electric 105k, plug-in petrol hybrid 53k, diesel hybrid 16k,
petrol electric hybrid 12k, EREV 925, LPG 249, hydrogen 38, plug-in diesel
hybrid 21, diesel electric hybrid 6, other 4, CNG 2.

**MHEV.** The register has no mild-hybrid label. Diesel hybrids are mostly
48 V mild-hybrid utes (Hilux, from 2024), registered as "DIESEL HYBRID"; they
count as HEV here, as they did in the Ministry's figures. A label the map does
not know goes to OTHERS with a warning, and stops the run above 1 % of a month
(`UNKNOWN_ABORT`).

## 5. Governance and validation

- **Schema:** the fields of §2/§4 plus MAKE and MODEL must exist, or the run stops.
- **Freshness:** a month is read only when the register's `dataLastEditDate`
  is after the month ended. Before that, a run is a no-op; from the 20th
  (`STALE_DAY`) it fails, because NZTA's refresh normally lands around the 5th.
- **Plausibility:** TOTAL within ×0.5–×2 of the same month a year earlier
  (`PLAUSIBLE`); outside stops the run (skip with `force`).
- **Overlap:** every run recounts the three months before the target and lists
  register − CSV per column in the step summary; above 5 % (`OVERLAP_WARN`) it
  is a warning. Rows from another source are never replaced without `force`.
- **Unknown labels:** listed; abort above 1 %.
- **No independent total:** the Ministry's dashboard is the only other
  publication and it is behind Imperva — the overlap check against the
  committed history stands in for it.

## 6. Brands and models (`market/new_zealand_top.json`)

The same scope and the same powertrain mapping, grouped by `MAKE` and `MODEL`
for BEV, PHEV and HEV, over the twelve months to the target, plus a ranking
per single month (`market_top.build_top_monthly`). Make and model are free
text typed by the entry certifier; `market_top.clean()` upper-cases them and
`strip_brand()` merges "BYD ATTO 3" with "ATTO 3". Because used imports are in
scope, used Nissan Leafs rank high in BEV. The refresh runs inside
`market_top.guarded()`: if it fails, the CSV is still committed and the run
shows a warning.

## 7. History

- **2012-01 → 2026-03:** compiled by Prof. Ray Willis from the Ministry of
  Transport's dashboard (`source = transport.govt.nz & Prof. Ray Willis`). Kept.
- **2026-04 → 2026-09:** were entered by hand from the dashboard after the
  fetcher stopped; petrol and diesel were inflated against the rest of the
  series (§2). They were rewritten from the register in the automation PR
  (`--since 2026-04 --force`), so the series has one definition from 2012 on;
  2026-04..06 carry an "undercount" note because they were counted a few
  months late.
- **2026-10 →:** written by the fetcher each month (`source = NZTA Motor
  Vehicle Register`).

## 8. Operations and debugging

```mermaid
sequenceDiagram
    participant Cron as fetch-new-zealand.yml (cron / dispatch)
    participant Test as test_fetch_new_zealand.py + test_market_top.py
    participant Py as fetch_new_zealand.py
    participant Hub as opendata-nzta Hub API
    participant FS as ArcGIS FeatureServer (MVR)
    participant CSV as data/New Zealand.csv
    participant Top as market/new_zealand_top.json
    participant Render as render-country.yml
    Cron->>Test: mapping, scope, guards, upsert, throttle, top lists (gate)
    Cron->>Py: run
    Py->>CSV: target month already there and top file current?
    alt yes
        Py-->>Cron: no-op (no HTTP request)
    else no
        Py->>Hub: item 7b4df667… → current service URL
        Py->>FS: table metadata → fields, dataLastEditDate
        Py->>Py: loaded after the month ended?
        Py->>FS: grouped counts (month × status × motive power), target−3 … target
        Py->>Py: labels known? year-ago ratio? overlap with the CSV?
        Py->>CSV: append the month (line-level)
        Py->>FS: grouped counts with MAKE, MODEL (12 months, electrified)
        Py->>Top: trailing 12 months + single months
        Py-->>Cron: run report → step summary
        Cron->>Render: once, Whole
    end
```

- **Normal run:** about six small JSON requests (Hub item, service, table,
  one fuel query, one or two pages of make × model).
- **Dispatch inputs:** `period` (target month), `since` (backfill — only adds
  months the CSV lacks unless `force`; old months undercount, §2), `force`,
  `dry_run` (query and report, write and commit nothing).
- **Offline:** `python scripts/fetch_new_zealand.py --period 2026-09 --dry-run
  --save-json nz.json` saves the query result; `--from-json nz.json` replays it
  without the network (the tests use the same path).
- **Regression check after a change:** `--dry-run --period <a month the CSV
  holds>` must list that month as "identical".
- **After each monthly run:** read the step summary — the month's table, new
  vs used, the year-ago ratio, the overlap list, the top-file log line.

**If a run fails — where to look:**

| Symptom in the log | Cause | Fix |
|---|---|---|
| `::warning title=NZ register URL::Hub lookup failed` | Hub search API down or moved | harmless while the fallback service still answers; if NZTA has republished, update `FALLBACK_SERVICE` (open the dataset page, "View API resources") |
| `GET … failed after 4 tries: HTTP 403/5xx` | ArcGIS outage, or the service was deleted | re-run; if it persists, check the dataset page — a new item id means updating `ITEM_ID` and `HUB_ITEM` |
| `register schema changed — fields [...] missing` | NZTA renamed a field | read the table's `?f=json`, adapt `F_YEAR`/`F_MONTH`/`REQUIRED_FIELDS` and the queries |
| `register has no dataLastEditDate` | metadata changed | find another load-date field (`editingInfo.lastEditDate`, the item's `modified`) and adapt `layer_info()` |
| `the register snapshot (loaded …) does not cover … yet — and it is the 20th` | NZTA's monthly refresh is late, or the Hub item now points at an old copy | check the dataset page's "updated" date; wait, or point `ITEM_ID` at the new item |
| `unmapped MOTIVE_POWER label(s) … above 1%` | NZTA added a motive power | decide the column (glossary: EREV → PHEV, MHEV → its fuel or HEV as the history does, hydrogen → OTHERS), add it to `MOTIVE_MAP` and `LABEL_CASES` in the test |
| `TOTAL … is ×N the same month a year earlier` | a real shock (a tax or rebate change, like the Clean Car Discount's end in 2023-12) or a wrong scope | look at the step summary's new/used split; dispatch with `force` if genuine |
| overlap warning `register differs from the CSV by …` | a scope drift (a new class code, a new import status) or a revised history | compare the classes in a grouped query (§3 step 4, grouped by CLASS); adapt `CLASSES`/`STATUSES` only if the definition really moved |
| `::warning title=top brands/models not refreshed` | make × model query failed | the CSV was committed; re-run, or check the query in the log |
| `New Zealand.csv: unexpected header` | someone changed the CSV's columns | restore the 12-column header (no FLEXFUEL) |

## 9. Not built (yet)

The register's class and import status would make further variants nearly free:
`Used` (used-import passenger cars), `Vans` (NA new), `HDV` (NB + NC new) and
`Buses` (MD/ME new). Their history can only be counted from today's register,
so it would undercount the earlier years (§2) — a decision for a later PR. A
new-cars-only M1 series would be the EU-anchored alternative to Whole.
