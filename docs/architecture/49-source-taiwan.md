---
country: Taiwan
slug: taiwan
method: api
summary: New-vehicle registration data for Taiwan from the Highway Bureau's national
  motor-vehicle register — monthly new registrations by vehicle kind and fuel, with
  battery-electric, plug-in, range-extender and hybrid each its own category — read from
  the Ministry of Transportation's statistics database.
source_name: MOTC statistics database (交通部統計查詢網) — Highway Bureau new registrations by fuel
source_url: https://statis.motc.gov.tw/motc/Statistics/Display?Seq=104
source_links:
- label: Table Seq 104 — 機動車輛新領牌車輛數－按使用燃料分 (new registrations by vehicle kind and fuel)
  url: https://statis.motc.gov.tw/motc/Statistics/Display?Seq=104
  note: monthly from 2012-01; the table's notes define every fuel category; the fetcher reads it through the JSON endpoint the page itself calls (Display.json)
- label: Table Seq 118 — 各型汽車新領牌車輛數－按廠牌分 (new registrations by vehicle kind and brand)
  url: https://statis.motc.gov.tw/motc/Statistics/Display?Seq=118
  note: compiled separately from the same register — its totals are the cross-check of every run, and its passenger-car brands feed the brand table below
- label: Highway Bureau statistics site (公路局統計查詢網)
  url: https://stat.thb.gov.tw/hb01/webMain.aspx?sys=100&funid=defjsp
  note: the register owner's own site — it blocks automated access from data centres (Imperva), so the gallery reads the ministry's copy
underlying: The national motor-vehicle register of the Highway Bureau (交通部公路局, THB), Ministry of Transportation and Communications (MOTC)
auth: none
cadence: twice daily on the 12th–28th, 01:45 and 09:45 UTC — MOTC publishes month M around the 15th of M+1 (August 2026 on September 15)
variants:
- Whole
- Vans
- HDV
- Buses
variant_notes:
  Whole: New passenger cars — THB vehicle kind 小客車 (up to 9 seats, EU M1), private and commercial, including taxis and rental cars.
  Vans: New light goods vehicles — 小貨車 (gross weight up to 3.5 t ≈ EU N1; since 2020-09-04 also 3.5–5 t vehicles up to 6 m long). Pickups, panel vans and Taiwan's small cab-over trucks.
  HDV: New heavy goods vehicles — 大貨車 (over 3.5 t ≈ EU N2+N3, including tractor units; since 2020-09-04 without the 3.5–5 t vehicles up to 6 m long).
  Buses: New buses and coaches — 大客車 (10 seats or more, or over 3.5 t; EU M2+M3), city buses and tour coaches alike.
hev_split: true
hev_note: THB's own fuel categories separate battery-electric, plug-in hybrid (four combined-fuel codes — petrol or diesel plus electricity, combustion- or electric-led), range extender (EREV) and hybrid. HEV is the register's hybrid codes 汽油(油電) / 柴油(油電) plus 汽油(電能) (driven only by the motor, fuelled only by petrol — Nissan e-POWER). The register has no mild-hybrid code; a 48 V mild hybrid sits in whichever of petrol or hybrid its type approval names.
backfill: from 2021-01, the first month in which the plug-in codes hold plug-ins only — before that the code 汽油/電能 still carried conventional full hybrids (§4)
scope_note: New registrations (新領牌照) of vehicles with a regular Taiwanese plate — military vehicles, unregistered vehicles and temporary plates excluded — counted in the month the plate was issued. Motorcycles and special vehicles are in no variant.
caveats:
- The series starts in 2021-01. Until 2020 the register coded many conventional full hybrids as 汽油/電能 ("petrol and electricity", today's plug-in code) — about 17,000 a year in 2012–14, when plug-ins were almost unknown. The dedicated hybrid code appeared in 2017 and took over completely in December 2020; from 2021 the plug-in codes are consistent, so the history is not spliced across the recoding.
- Hybrids are a large and growing slice (39 % of new cars in the twelve months to August 2026) and count as ICE in the BEV/PHEV/ICE curves. The register has no separate mild-hybrid code, so HEV can hold mild hybrids registered as hybrids.
- BEV registrations come in waves (Tesla, about 60 % of BEVs, delivers in quarter-end pushes — December 2025 had 7,166 BEVs, November 1,926). Single months swing between 5 % and 17 %; read the trend.
- Vans include vehicles from 3.5 to 5 t up to 6 m long since 2020-09-04 (a regulatory change that moved them from 大貨車), so Vans is slightly wider than EU N1 and HDV slightly narrower than N2+N3.
- The brand table on this page is every powertrain together — THB publishes brands and fuels in two separate tables, so who sells the battery-electric cars cannot be read from it (Tesla, a battery-only brand, is the exception).
processing:
- title: Download
  text:
  - The fetcher reads the ministry's table page (which lists the newest month and the id of every vehicle kind and fuel), then one small JSON query per vehicle kind for the fuel table and one for the brand table — the same queries the database's own page sends. A normal run re-reads the newest 24 months, so a later correction by THB is picked up; nothing is written until every check below has passed.
- title: Pick the vehicles
  text:
  - THB's vehicle kind (車種) decides the variant. Its definitions follow Taiwan's road-traffic rules (seats and gross weight), which line up with the EU classes.
  decision:
    ask: THB vehicle kind?
    branches:
    - when: 小客車 — passenger car, up to 9 seats
      then: Whole
      note: private (自用) and commercial (營業 — taxis, rental cars) together
    - when: 小貨車 — goods vehicle up to 3.5 t (since 2020-09-04 also up to 5 t if at most 6 m long)
      then: Vans
    - when: 大貨車 — goods vehicle over 3.5 t, tractor units included
      then: HDV
    - when: 大客車 — bus or coach, 10 seats or more, or over 3.5 t
      then: Buses
    - when: 特種車 (special vehicles), 機車 (motorcycles and mopeds)
      then: in no variant
- title: Powertrain
  text:
  - THB records each vehicle's fuel (使用燃料) from its type approval in thirteen categories, each defined in the table's notes. They map one to one onto the gallery's columns; a category the fetcher does not know is counted as OTHERS and listed, and above 1 % of a month's cars the run stops.
  decision:
    ask: THB fuel category?
    branches:
    - when: 電能 — electricity only
      then: BEV
    - when: 汽油/電能, 柴油/電能 (petrol or diesel plus electricity, mainly combustion) or 電能/汽油, 電能/柴油 (electricity plus petrol or diesel, mainly electric)
      then: PHEV
      note: from 2021-01 — before that, 汽油/電能 still held conventional hybrids
    - when: 電能(增程) — electric drive with a range-extender engine
      then: EREV
      note: folds into the PHEV curve in the charts
    - when: 汽油(油電), 柴油(油電) — fuel only, can drive on the electric motor (hybrid)
      then: HEV
    - when: 汽油(電能) — fuel only, driven only by the electric motor (Nissan e-POWER)
      then: HEV
      note: a series hybrid without a plug, not a BEV
    - when: 汽油 / 柴油
      then: PETROL / DIESEL
    - when: 液化石油氣, 汽油/液化石油氣 (LPG, petrol/LPG)
      then: LPG
- title: Check against the brand table
  text:
  - The ministry publishes THB's new registrations a second time, by brand (table Seq 118), compiled separately. For every month and vehicle kind the fetcher writes, the brand table's total must equal the fuel table's — they have been identical for every month since 2012. A difference beyond 3 vehicles (0.1 %) stops the run, as does a month whose fuels do not add up to the table's own total.
market_breakdown: market/taiwan_top.json
market_heading: Who sells the new cars
market_designation_note: THB publishes brands only, no models. A brand is the registrant THB records; locally built cars appear under the local maker (國瑞 Kuozui for Toyota, 本田 Honda Taiwan, 三陽 San Yang for Hyundai, 福特六和 Ford Lio Ho, 日產 Yulon Nissan) and are merged with the marque's imports; China Motor (中華 — Mitsubishi and its own models) stays itself. THB's own "others" line (brands without a code of their own) counts towards the total but is not ranked; so do, since June 2026, about 600–850 cars a month that THB's total holds but no brand in the ministry's code list carries (a newly itemised brand the database does not list yet).
market_powertrain_note: Every powertrain together — THB publishes brands and fuels in two separate tables, so the brand ranking cannot be split into battery-electric, plug-in and combustion cars. Tesla, a battery-only brand, is the one maker whose units are all BEV.
fetcher: scripts/fetch_taiwan.py
workflow: .github/workflows/fetch-taiwan.yml
fragility_doc: docs/architecture/49-source-taiwan.md
data_file: data/Taiwan.csv
---

# 49 · Source: Taiwan (Highway Bureau register via the MOTC statistics database)

**Status: LIVE since 2026-10.** Fetcher `scripts/fetch_taiwan.py` (+ tests
`scripts/test_fetch_taiwan.py`) and `.github/workflows/fetch-taiwan.yml`.
Taiwan is one of the larger markets the gallery had been missing (≈ 400,000
new passenger cars a year, [33](33-expansion-candidates.md)) and its source is
the national register itself, with the finest fuel split of any Asian country
on the gallery: battery-electric, plug-in, range extender and hybrid are each
THB's own category.

The facts below were established on 2026-10-04 by temporary probe workflows
on the PR branch (since removed): the dev sandbox reaches none of the
Taiwanese hosts, GitHub runners reach the ministry's database but not THB's
own statistics site. The finished fetcher ran online on a runner (backfill,
2021-01 → 2026-08); its output was byte-identical to the offline rebuild from
the saved responses.

## TL;DR

```
Source:    MOTC statistics database (交通部統計查詢網), statis.motc.gov.tw —
           the ministry's copy of THB's monthly register tables:
             Seq 104  new registrations × vehicle kind × fuel (2012-01 →)
             Seq 118  new registrations × vehicle kind × brand (2012-09 →)
API:       the page's own JSON endpoint:
           GET /motc/Statistics/Display?Seq=104      → newest month + ids
           GET /motc/Statistics/Display.json?Seq=104&Start=110-01-00
               &End=115-08-00&ShowMonth=true&ShowYear=false&ShowQuarter=false
               &ShowHalfYear=false&Mode=0&ColumnValues=<kind>&CodeListValues=<fuels>
           GET /motc/Statistics/DisplayPublishDate.json?seq=104
Auth:      None. No login, no key. (stat.thb.gov.tw, THB's own site, answers
           every GitHub-runner request with Imperva "Error 16".)
Dates:     ROC years: 115-08-00 = 2026-08. Cells "31,361 " ; "-" = none.
Timing:    month M published around the 15th of M+1 (Aug 2026: Sep 15).
Scope:     小客車 → Whole (M1) · 小貨車 → Vans (≈ N1) · 大貨車 → HDV (≈ N2+N3)
           · 大客車 → Buses (M2+M3)
Fuel:      電能 → BEV; 汽油/電能, 柴油/電能, 電能/汽油, 電能/柴油 → PHEV;
           電能(增程) → EREV; 汽油(油電), 柴油(油電), 汽油(電能) → HEV;
           汽油 → PETROL; 柴油 → DIESEL; LPG codes → LPG.
History:   2021-01 → today (68 months at 2026-08); earlier plug-in coding
           is inconsistent (§4).
Checked:   brand-table totals = fuel-table totals for every vehicle kind and
           month (272 of 272); BEV 2025 32,358 vs 32,558 in the press (−0.6 %).
```

## 1. Why this source

The gallery's bar ([14](14-data-source-gaps.md)): direct from the registry
or a recognised official body, complete for the market, free.

- **It is the register.** THB issues every plate in Taiwan; the ministry's
  database republishes THB's monthly statistics ("資料來源：交通部公路局" on
  every table). Every brand is in it — there is no member-reporting hole.
- **The finest fuel split available.** THB's fuel categories separate
  battery-electric, four flavours of plug-in, range extender, hybrid and the
  Nissan e-POWER series hybrid, each defined in the table's notes (§3).
- **Free, stable, reachable.** No login or key; the database answers the same
  JSON its own page uses. One table, one query per vehicle kind, from 2012.
- **What else was looked at** (2026-10-04, [33](33-expansion-candidates.md)):
  - THB's own statistics site `stat.thb.gov.tw` has the same tables (and
    possibly more — whether it has brand × fuel could not be checked) but
    blocks GitHub runners at IP level —
    Imperva "Error 16", also for a real headless browser and for
    TLS-impersonating clients; the Cloudflare relay ([08](08-deploy-ops.md))
    allow-lists only its current hosts.
  - data.gov.tw (52,000 datasets searched): THB's open dataset 30202
    (新車領牌數) has totals by vehicle kind only; Taipei City's 157969 has the
    fuel split for Taipei only (and was last refreshed 2024-10).
  - THB's open-data service (`www.thb.gov.tw/Common/ThbOpenDataService.ashx`,
    225 dataset ids probed): no new-registration table by fuel; the CSV of
    dataset 30202 answers 403 to runners.

## 2. Record → CSV row

The fuel table (Seq 104) is THB's monthly count by vehicle kind (統計項,
columns) × fuel (複分類, code list). The fetcher resolves the ids of the
labels it needs from the table page (`parse_display_page`), then queries one
vehicle kind at a time for all fuels and months, and checks that the JSON's
own `nameMapping` gives the same labels back (`parse_display_json`).

| THB kind | Variant | 2025 | BEV 2025 | TTM to 2026-08 BEV |
|---|---|---:|---:|---:|
| 小客車 passenger cars | Whole | 363,653 | 8.9 % | 10.5 % |
| 小貨車 light goods | Vans | 39,089 | 0.5 % | 0.7 % |
| 大貨車 heavy goods | HDV | 5,519 | 0.3 % | 0.4 % |
| 大客車 buses and coaches | Buses | 1,950 | 46.2 % | 60.1 % |

CSV columns: `BEV, PHEV, EREV, HEV, PETROL, DIESEL, LPG, OTHERS, TOTAL`;
`source` = `THB register via MOTC statistics database`. TOTAL is THB's own
總計; the fuels must add up to it exactly. Line-level upserts (invariant 2); a
row whose `source` is not ours is never overwritten without `--force`.

Not used: the sub-items of each kind (自用 private / 營業 commercial, 租賃
rental, 計程車 taxi, 遊覽車 coach) — they would make Private/Rental slices
possible later, but THB's "自用" includes company cars, so it is not the
gallery's `Private` (persons) without more work. 機車 (motorcycles): §9.

## 3. Fuel categories (`FUEL_COLUMN`)

THB's definitions (table notes, 4.(1)–(13)), shortened:

| THB category | Definition | → |
|---|---|---|
| 汽油 | petrol only | PETROL |
| 柴油 | diesel only | DIESEL |
| 電能 | driven by electricity only | BEV |
| 液化石油氣 / 汽油/液化石油氣 | LPG only / petrol and LPG, mainly petrol | LPG |
| 汽油/電能 / 柴油/電能 | petrol or diesel **and** electricity, mainly combustion | PHEV |
| 電能/汽油 / 電能/柴油 | electricity **and** petrol or diesel, mainly the electric motor | PHEV |
| 電能(增程) | electric drive, an engine drives a generator to extend range | EREV |
| 汽油(油電) / 柴油(油電) | only fuel, but can drive on an electric motor fed by on-board conversion | HEV |
| 汽油(電能) | only petrol, driven only by the motor (on-board conversion) — e-POWER | HEV |

"Uses electricity" in THB's wording is electricity as an energy input — a
plug. The hybrid codes say "only fuel". So PHEV/HEV is the register's own
distinction, not a classification from model names. 2026 to August (Whole):
PHEV 2,531 (1.1 %), of which 2,322 electric-led (電能/汽油) and 207
combustion-led (汽油/電能); EREV practically zero; HEV 99,154 (41.5 %), of which
611 e-POWER.

Every label has a test, including the look-alikes 電能 / 電能(增程) /
電能/汽油 / 汽油(電能); full-width parentheses and slashes are normalised.

## 4. Why the series starts in 2021-01

The plug-in code 汽油/電能 meant something else until 2020:

| Year | 汽油/電能 (Whole) | 汽油(油電) hybrid code | BEV |
|---|---:|---:|---:|
| 2012 | 17,636 | — | 215 |
| 2016 | 8,418 | 3 | 22 |
| 2017 | 6,518 | 1,964 (from June) | 766 |
| 2019 | 4,906 | 21,140 | 3,361 |
| 2020 | 5,396 | 35,051 | 6,243 |
| 2021 | 465 | 59,212 | 6,997 |

Before 2017 the register had no hybrid code, and Toyota's hybrids were
registered as "petrol and electricity" — 5 % of the market in 2012 "plug-ins"
is impossible. The dedicated code appeared in June 2017 and took over model by
model; in December 2020 汽油/電能 fell from 554 to 104 a month, and from
January 2021 it holds 20–60 genuine plug-ins a month. BEV and the totals are
unaffected, but one series has one start (invariant 3) — the gallery does not
reclassify THB's old codes by guesswork. The 2012–2020 months remain in the
ministry's table for anyone who wants the BEV history alone (BEV share 0.07 %
in 2012, 1.6 % in 2020).

## 5. Governance and validation

Every real run (the self-throttle exits before any of this when the CSVs
already hold the newest month):

- **Schema drift aborts:** a vehicle kind or fuel label missing from the
  table page, a JSON id whose label differs from the page's, an answer for a
  different vehicle kind, a month missing from the response.
- **Sums:** every month's fuels must add up to THB's 總計 exactly.
- **Unknown fuel categories** are queried too, counted as OTHERS and listed
  (`::warning`); above 1 % of a month's Whole the run aborts.
- **Cross-check against the brand table** (Seq 118, compiled separately):
  each vehicle kind's monthly total must equal the fuel table's — beyond
  max(3, 0.1 %) the run aborts. Result of the backfill: **272 of 272
  variant-months identical** (2021-01 → 2026-08); for passenger cars, all 167
  months 2012-09 → 2026-08 are identical.
- **Completeness:** a new month below 40 % of the trailing-12 median Whole
  TOTAL is held back (Lunar New Year Februaries run at 54–74 % of it: 2026-02
  had 19,676, 65 %).

Independent check (press, same register): full-year 2025 BEV registrations
32,358 here vs 32,558 in the Taiwanese motoring press (TVBS, −0.6 %);
December 2025 7,166 vs 7,186 (−0.3 %). The press's "nearly 8 %" BEV share of
2025 is BEV over passenger cars **plus** light goods vehicles (32,358 /
402,742 = 8.0 %); over passenger cars alone it is 8.9 %.

## 6. Reading the fit

Taiwan's BEV share of new passenger cars went from 1.8 % (2021) to 4.4 %
(2022), 5.9 % (2023), 9.3 % (2024), 8.9 % (2025) and 10.4 % in January–August
2026 (August 12.6 %). Hybrids are the bigger movement — 15.6 % in 2021, 41.5 %
in 2026 — and count as ICE in the curves, so the combustion share in the
charts falls far slower than "petrol" does. BEVs have long been exempt from
commodity tax (貨物稅) and from the vehicle license tax (使用牌照稅); both
exemptions have been extended several times rather than phased out, and
hybrids pay half the commodity tax. Tesla, about 60 % of BEVs, delivers in
quarter-end waves (June 2026 15.6 %, July 4.7 %), so single months are lumpy.

Buses are a real transition (15.6 % electric in 2021, 59.6 % in 2026 —
the government's city-bus electrification programme), but a small, lumpy
series (100–200 a month, fleet batches). Vans and HDV are below 1 % BEV:
*No transition* by the gallery's rule.

## 7. Outputs

- `data/Taiwan.csv` (Whole), `data/Taiwan_Vans.csv`, `data/Taiwan_HDV.csv`,
  `data/Taiwan_Buses.csv`, monthly, 2021-01 →, all rendered.
- `market/taiwan_top.json` — trailing-12-month brand ranking of new passenger
  cars plus single-month rankings, from the brand table, under the class
  `ALL` (every powertrain — [03](03-data-objects.md) §3.16): THB publishes no
  brand × fuel table, so the source page's section is "Who sells the new
  cars", not the electrified-cars section other countries have. THB's own
  "其他" (others) line counts towards the total, never into the ranking.
- **A brand missing from the code list (since 2026-06).** From June 2026 the
  brand table's total is larger than the sum of its listed brands — by 624
  (June), 736 (July) and 838 (August) passenger cars — while "其他" fell from
  about 880 to about 190 a month: THB began itemising a brand (out of
  "其他") that the ministry's database does not list as a code yet. It could
  not be identified from runners (connections dropped on the probe that
  queried unlisted ids). The fetcher counts the difference as unranked rest
  (`unlisted()`), so the ranking still adds up to the market, and reports it
  in every step summary; once the database lists the brand, it appears in
  the ranking by itself. The totals the cross-check compares are unaffected.

## 8. Operations and debugging

```mermaid
sequenceDiagram
    participant Cron as fetch-taiwan.yml (cron / dispatch)
    participant Test as test_fetch_taiwan.py + test_market_top.py
    participant Py as fetch_taiwan.py
    participant MOTC as statis.motc.gov.tw
    participant CSV as data/Taiwan*.csv
    participant Top as market/taiwan_top.json
    participant Render as render-country.yml
    Cron->>Test: fuel mapping, ROC dates, parsers, checks, upsert, end-to-end (gate)
    Cron->>Py: run
    Py->>MOTC: Display?Seq=104 (page) → newest month, ids by label
    Py->>CSV: newest month already in every CSV?
    alt yes
        Py-->>Cron: no-op (one page request)
    else no
        Py->>MOTC: DisplayPublishDate.json; Display?Seq=118
        Py->>MOTC: Display.json Seq 104, one query per vehicle kind (24 months)
        Py->>Py: labels = page labels? fuels sum to 總計? unknown fuels ≤ 1 %?
        Py->>MOTC: Display.json Seq 118 (brand totals; all brands for Whole)
        Py->>Py: brand-table totals = fuel-table totals? completeness ≥ 40 %?
        Py->>CSV: line-level upserts (changed lines only)
        Py->>Top: trailing-12-month brand ranking (class ALL)
        Py-->>Cron: run report → step summary
        Cron->>Render: once, with the changed variants
    end
```

- **Schedule:** `45 1,9 12-28 * *` (Taipei 09:45 / 17:45). A no-op costs one
  page request.
- **Normal run:** 2 pages + 8 small JSON queries (about 10 s); re-derives the
  newest 24 months, so THB's corrections are picked up and listed.
- **Backfill:** dispatch with `backfill = true` (2021-01 → newest).
- **Offline:** `python scripts/fetch_taiwan.py --dump-dir DIR` saves every
  response; `--from-dir DIR` replays them. Dispatching the workflow with
  `debug_dump = true` uploads the responses as the artifact
  `taiwan-motc-responses` (kept also when the run fails).
- **After each monthly run:** read the step summary — the month's table per
  variant, the cross-check line, fuel categories the script did not know,
  rows THB revised, the month's top brands.

**If a run fails — where to look:**

| Symptom in the log | Cause | Fix |
|---|---|---|
| `statis.motc.gov.tw unreachable after 5 tries` (`ConnectTimeout`) | the ministry's server refuses some runner IPs now and then (seen in probes 2026-10-04) | re-run; it passes on another runner. If it persists for days, check from a browser whether the database moved |
| `No month found in the Seq 104 period picker` | the table page's HTML changed | open the page; adapt `parse_display_page()` (test `test_parse_display_page`) |
| `Schema drift: Seq 104 page no longer lists [...]` | THB renamed or retired a vehicle kind / fuel label | compare with the page; update `VARIANTS` / `FUEL_COLUMN` and the tests |
| `Schema drift: code N is … in the JSON` / `asked for N` | ids reassigned, or the endpoint changed its key format | dump with `debug_dump`, read `fuel_<Variant>.json`; adapt `parse_display_json()` |
| `::warning title=New THB fuel categories` | THB added a fuel category (hydrogen, a new hybrid code) | read its definition in the table notes; map it in `FUEL_COLUMN` with a test |
| `fuels sum to X, 總計 is Y` / `fuel cells missing` | a partial or malformed response | re-run; if it persists, dump and compare with the web page |
| `Cross-check against the brand table failed` | the two tables updated at different times, or a scope change | wait a day and re-run; if the page shows the same mismatch, dispatch with `force` and note it |
| `looks incomplete` warning (month not written) | a partial month — or a real collapse | compare with the ministry page; `force` if genuine |
| commit step `non-fast-forward` | a concurrent commit | already rebased by the action; re-run |

## 9. Not built (yet)

- **Motorcycles (`2-Wheelers`)** are in the same table (機車, ≈ 700,000 a year):
  electric scooters peaked at 18.7 % in 2019 (Gogoro, subsidies) and fell to
  about 6 %; a 2026 recoding puts 18 % of new motorcycles under a hybrid code.
  A subsidy-driven, non-monotonic curve with a fresh coding change — left out
  until the coding settles.
- **Private / Rental slices** of Whole are in the table (自用 / 營業 / 租賃 /
  計程車); see §2 for why 自用 is not the gallery's `Private`.
- **Brand × fuel:** THB's own site (blocked) may carry it; if the relay ever
  reaches `stat.thb.gov.tw`, the brand table could become the usual
  electrified-cars section.
