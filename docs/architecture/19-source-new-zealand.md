---
country: New Zealand
slug: new-zealand
method: api
summary: New-vehicle registrations for New Zealand — new passenger cars, vans and trucks, plus
  used-import cars — counted automatically from NZTA Waka Kotahi's open Motor Vehicle Register,
  the register behind the Ministry of Transport's fleet statistics. The former light-vehicle
  series (new and used together) is archived in data/New Zealand_legacy.csv.
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
- Vans
- HDV
- Used
variant_notes:
  Whole: New passenger cars — register classes MA (car), MB (passenger van) and MC (off-road passenger vehicle), i.e. EU M1, at their first New Zealand registration.
  Vans: New goods vehicles up to 3.5 t (register class NA, EU N1) — utes and vans, which dominate New Zealand's light-commercial market.
  HDV: New goods vehicles over 3.5 t (register classes NB and NC, EU N2/N3).
  Used: Used-import passenger vehicles (classes MA, MB, MC — EU M1) at their first New Zealand registration, mostly from Japan.
hev_split: true
hev_note: PHEV and HEV come from the register's motive power. Range-extended EVs ("ELECTRIC [PETROL EXTENDED]") are counted as PHEV, as in the history. HEV is whatever was entered as a petrol or diesel hybrid — mostly full hybrids, but some 48 V mild-hybrid utes are registered as "DIESEL HYBRID" and count here too.
backfill: Whole, Vans, HDV and Used were counted from the register's 2026-10 snapshot (Whole from 2012-01, the others from 2015-01), with undercount notes on every row before 2026-07. The former data/New Zealand.csv (light vehicles, new and used) is archived in data/New Zealand_legacy.csv — Prof. Ray Willis's rows 2012-01 to 2026-03, the register from 2026-04 (the hand rows for 2026-04..09 were replaced, see §7); it is no longer fetched or rendered.
scope_note: First registrations in New Zealand by the register's own vehicle class and import status, mapped onto the EU classes like every other country. Before 2026-10 the gallery's New Zealand series was all light vehicles, new and used imports together; that series is archived, not continued.
caveats:
- Whole, Vans, HDV and Used were counted from today's register back to 2012 / 2015. The register lists vehicles registered today, so older months miss the vehicles scrapped or exported since — little for recent years, more further back (for the former light-vehicle scope about 4 % for 2024, 15 % for 2019, 30 % for 2015; less for new cars, more for used imports). Shares are affected less than volumes. Each such row says "undercount" in its notes; from 2026-10 every month is written once, right after it ends.
- NZTA leaves out vehicles whose owners have a confidential listing; with the deregistrations this puts the register about 1 % below the Ministry's published figures.
- Some 48 V mild-hybrid utes are registered as diesel hybrids and count as HEV — most visibly in Vans.
- The New Zealand series shown until 2026-10 included used imports (about 40 % of its volume) and light goods vehicles, so its BEV share was about half of today's Whole (8.5 % against 15 % in the year to September 2026). Whole is now new cars only — the jump in the chart's history is this change of scope, not a market event.
processing:
- title: Ask the register
  text:
  - The register is an ArcGIS feature service with about 5.8 million records. The fetcher never downloads them; it asks the service for grouped counts (first registration month × import status × motive power), a handful of small JSON requests. The service address changes when NZTA republishes the register, so it is looked up from the stable open-data item on every run. A month is only read once the register's load date is after the month ended.
- title: Pick the vehicles
  text:
  - Every record carries its import status, its vehicle class and the year and month of its first registration in New Zealand. Together they decide the variant, mapped onto the EU classes like every other country.
  decision:
    ask: Import status?
    branches:
    - when: NEW or USED (used import)
      then:
        ask: Vehicle class?
        branches:
        - when: MA, MB, MC — passenger car, passenger van, off-road passenger vehicle (EU M1)
          then:
            ask: New or used import?
            branches:
            - when: NEW
              then: Whole
            - when: USED
              then: Used
        - when: NA — goods vehicle up to 3.5 t (EU N1)
          then:
            ask: New or used import?
            branches:
            - when: NEW
              then: Vans
            - when: USED
              then: in no variant
              note: used goods vehicles are in no EU-class variant
        - when: NB, NC — goods vehicle over 3.5 t (EU N2/N3)
          then:
            ask: New or used import?
            branches:
            - when: NEW
              then: HDV
            - when: USED
              then: in no variant
        - when: anything else — buses (MD, ME), motorcycles and mopeds (L), trailers (T), tractors and machines
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
market_heading: Who sells the new electrified cars
market_designation_note: Make and model as the entry certifier typed them on the register, upper-cased; a model typed with the brand in front is merged with the plain one. Some models are generic (BMW's electric cars are partly registered as model "I").
market_powertrain_note: BEV / PHEV / HEV exactly as in the CSV, for Whole — new passenger cars (MA/MB/MC). Used imports (the Nissan Leafs) have their own section below; utes are in neither.
market_breakdown_extra:
- path: market/new_zealand_used_top.json
  id: market-used
  heading: Who sells the imported used electrified cars
  note: "Used imports (the Used variant): passenger cars (MA/MB/MC) first registered abroad — mostly in Japan — at their first New Zealand registration. BEV / PHEV / HEV from the register's motive power, exactly as in the Used CSV."
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
Scope:     IMPORT_STATUS × CLASS, by first NZ registration month
Variants:  Whole   data/New Zealand.csv          NEW, MA/MB/MC (M1)
           Vans    data/New Zealand_Vans.csv     NEW, NA (N1)
           HDV     data/New Zealand_HDV.csv      NEW, NB/NC (N2+N3)
           Used    data/New Zealand_Used.csv     USED, MA/MB/MC (M1 used imports)
Archive:   data/New Zealand_legacy.csv — the pre-2026-10 series (NEW + USED, MA/MB/MC/NA), not written
Columns:   BEV, PHEV, HEV, PETROL, DIESEL, OTHERS, TOTAL (no FLEXFUEL)
Top lists: market/new_zealand_top.json (Whole) + market/new_zealand_used_top.json (Used);
           BEV / PHEV / HEV, trailing 12 months + single months
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
petrol / diesel split as the legacy series — no coarser hybrid bucket — and
it reproduces the legacy rows (§2), which are archived.

## 2. Scope — EU classes, and the legacy series reproduced

Until 2026-10 the gallery's New Zealand series was the Ministry's "light
vehicles": **new and used-import** passenger cars and goods vehicles up to
3.5 t, in one number. It never matched the EU-class variants of the other
countries, so since 2026-10 New Zealand is split like them, by the register's
own class and import status. The old series is archived unchanged in
`data/New Zealand_legacy.csv` (the former `data/New Zealand.csv`; not fetched,
not rendered — the `_legacy` convention, like Czechia's or Spain's):

| Variant | `IMPORT_STATUS` | `CLASS` | EU class |
|---|---|---|---|
| Whole | `NEW` | `MA`, `MB`, `MC` | M1 |
| Vans | `NEW` | `NA` | N1 |
| HDV | `NEW` | `NB`, `NC` | N2 + N3 |
| Used | `USED` | `MA`, `MB`, `MC` | M1, used imports at their first national registration |

`RE-REG` and `SCRATCH` are not first registrations and are in no variant. The
month is `FIRST_NZ_REGISTRATION_YEAR` / `_MONTH`, the month the plates were
issued. Buses (`MD*`, `ME`) are not built (§9). Year to 2026-09: Whole 109,477
(BEV 14.7 %), Vans 32,964 (BEV 1.8 %, PHEV 7.4 % — mostly the BYD Shark 6
ute), HDV 5,177 (BEV 1.7 %), Used 88,446 (BEV 3.9 %, HEV 49.7 %); the former
light-vehicle scope would be 235,700 (BEV 8.5 %).

The register settles what the legacy series was: with used imports in, it
matches the legacy rows in every column; without them it is 40 % short and
has half the hybrids.

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
still registered: in the former light-vehicle scope 2024 is about 4 % short, 2019 about 15 %,
2015 about 30 %. That is why the fetcher writes each month once, right after
it ends, and does not rebuild a history it already has (invariant 3).

### 2.1 The new variants' history

Whole, Vans, HDV and Used had no history of their own, so it was counted from
the 2026-10 snapshot — Whole back to 2012-01 (as far as the old series went), the
others back to 2015-01 — and every row before 2026-07 carries the undercount
note. The undercount is smaller for new cars (kept longer, rarely exported)
than for used imports; it lowers volumes more than shares. From 2026-10 each
month of every variant is written once, right after it ends.

## 3. Record → row

```
1. GET the Hub item → `url` = the current FeatureServer (fallback: the last
   known one, with a warning).
2. GET the service + table metadata → required fields present?
   dataLastEditDate = the date the register was loaded.
3. Is the load date after the target month ended?  no → no-op (error from the 20th).
4. Grouped count: where first-registration month in [target−3 … target],
   IMPORT_STATUS NEW/USED and CLASS MA/MB/MC/NA/NB/NC, group by year, month,
   IMPORT_STATUS, CLASS, MOTIVE_POWER.
5. Map MOTIVE_POWER → column (§4); TOTAL = the sum; the IMPORT_STATUS × CLASS
   of each count decides its variant (§2, `VARIANTS` in the fetcher) — at
   most one.
6. Checks (§5) per variant → upsert the target month into each variant's CSV,
   line-level.
7. Top lists: Whole's scope over the 12 months to the target, electrified
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

The former light-vehicle scope 2012-01 → 2026-09 by label: petrol 1.97 M, diesel 684k, petrol
hybrid 428k, electric 105k, plug-in petrol hybrid 53k, diesel hybrid 16k,
petrol electric hybrid 12k, EREV 925, LPG 249, hydrogen 38, plug-in diesel
hybrid 21, diesel electric hybrid 6, other 4, CNG 2.

**MHEV.** The register has no mild-hybrid label. Diesel hybrids are mostly
48 V mild-hybrid utes (Hilux, from 2024), registered as "DIESEL HYBRID"; they
count as HEV here, as they did in the Ministry's figures — mostly in Vans. A label the map does
not know goes to OTHERS with a warning, and stops the run above 1 % of a month
(`UNKNOWN_ABORT`).

## 5. Governance and validation

- **Schema:** the fields of §2/§4 plus MAKE and MODEL must exist, or the run stops.
- **Freshness:** a month is read only when the register's `dataLastEditDate`
  is after the month ended. Before that, a run is a no-op; from the 20th
  (`STALE_DAY`) it fails, because NZTA's refresh normally lands around the 5th.
- **Plausibility:** each variant's TOTAL within ×0.5–×2 of the same month a
  year earlier (`PLAUSIBLE`); outside stops the run (skip with `force`).
- **Overlap:** every run recounts the three months before the target and lists
  register − CSV per column in the step summary; above 5 % (`OVERLAP_WARN`) it
  is a warning. Rows from another source are never replaced without `force`.
- **Unknown labels:** listed; abort above 1 % of the month (all variants
  together).
- **No independent total:** the Ministry's dashboard is the only other
  publication and it is behind Imperva — the overlap check against the
  committed history stands in for it.

## 6. Brands and models (`market/new_zealand_top.json`, `market/new_zealand_used_top.json`)

One grouped query — passenger cars (MA/MB/MC), new and used imports, by
`IMPORT_STATUS`, `MAKE` and `MODEL` for BEV, PHEV and HEV over the twelve
months to the target — feeds two tables with their CSV's scope and the same
powertrain mapping: Whole (`NEW`) and Used (`USED`, its own section on the
source page via `market_breakdown_extra` — the rule for every `Used` variant,
[03](03-data-objects.md) §3.16). Each has a ranking per single month too
(`market_top.build_top_monthly`). Make and model are free
text typed by the entry certifier; `market_top.clean()` upper-cases them and
`strip_brand()` merges "BYD ATTO 3" with "ATTO 3". Utes (class NA) are in
neither list. A `--save-json` file from before the Used table has no
`IMPORT_STATUS` on its model rows; they are read as new cars. The refresh runs inside
`market_top.guarded()`: if it fails, the CSV is still committed and the run
shows a warning.

## 7. History

- **2012-01 → 2026-03 (now the archive):** compiled by Prof. Ray Willis from the
  Ministry of Transport's dashboard (`source = transport.govt.nz & Prof. Ray
  Willis`). Kept.
- **2026-04 → 2026-09 (now the archive):** were entered by hand from the dashboard
  after the fetcher stopped; petrol and diesel were inflated against the rest
  of the series (§2). They were rewritten from the register in the automation
  PR (`--since 2026-04 --force`), so the archive has one definition from 2012 on;
  2026-04..06 carry an "undercount" note because they were counted a few
  months late.
- **2026-10:** the series was split into EU-class variants (§2). The former
  `data/New Zealand.csv` was archived as `data/New Zealand_legacy.csv` (rows
  unchanged, variant label `Whole` kept; no longer written or rendered — a
  `Legacy` variant was considered and dropped); Whole is now new M1 cars,
  counted from the register back to 2012-01; Vans, HDV and Used back to
  2015-01.
- **2026-10 →:** every variant is written by the fetcher each month
  (`source = NZTA Motor Vehicle Register`).

## 8. Operations and debugging

```mermaid
sequenceDiagram
    participant Cron as fetch-new-zealand.yml (cron / dispatch)
    participant Test as test_fetch_new_zealand.py + test_market_top.py
    participant Py as fetch_new_zealand.py
    participant Hub as opendata-nzta Hub API
    participant FS as ArcGIS FeatureServer (MVR)
    participant CSV as data/New Zealand*.csv (5 variants)
    participant Top as market/new_zealand_top.json + _used_top.json
    participant Render as render-country.yml
    Cron->>Test: mapping, scope, guards, upsert, throttle, top lists (gate)
    Cron->>Py: run
    Py->>CSV: target month in every variant and top file current?
    alt yes
        Py-->>Cron: no-op (no HTTP request)
    else no
        Py->>Hub: item 7b4df667… → current service URL
        Py->>FS: table metadata → fields, dataLastEditDate
        Py->>Py: loaded after the month ended?
        Py->>FS: grouped counts (month × status × class × motive power), target−3 … target
        Py->>Py: labels known? year-ago ratio? overlap with the CSV?
        Py->>CSV: append the month to each variant (line-level)
        Py->>FS: grouped counts with MAKE, MODEL (12 months, electrified)
        Py->>Top: trailing 12 months + single months
        Py-->>Cron: run report → step summary
        Cron->>Render: once, with the changed variants (Whole|Vans|HDV|Used)
    end
```

- **Normal run:** about six small JSON requests (Hub item, service, table,
  one fuel query, one or two pages of make × model).
- **Dispatch inputs:** `variant` (comma-separated subset of Whole, Vans, HDV, Used), `period` (target month), `since` (backfill — only adds
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

`Buses` (`MD*`/`ME`, new) is as cheap as HDV was — one more entry in
`VARIANTS` — and would undercount the same way. A used-import goods-vehicle
slice is possible but has no counterpart in any other country.
