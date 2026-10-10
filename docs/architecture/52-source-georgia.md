---
country: Georgia
slug: georgia
method: api
summary: Quarterly initial vehicle registrations in Georgia by fuel type from Geostat,
  the National Statistics Office — read automatically from the public API behind its
  "Automobile" statistics portal.
source_name: Geostat — Automobile statistics portal (initial registrations)
source_url: https://automobile.geostat.ge/en/automobiles/rating
source_links:
- label: Geostat Automobile portal — Rating page
  url: https://automobile.geostat.ge/en/automobiles/rating
  note: set the period switch to "during the period" and pick a year and quarter; the fuel-type chart is the quarter's row in data/Georgia.csv, the treemap is the brand and model table below
- label: Fuel split of one quarter (the API the page reads)
  url: https://autoapi.geostat.ge/mobile/fuels?lang=en&year=2026&quarter=II&table=true
  note: public JSON, no key — but the API only answers requests that send the portal's Origin / Referer headers, so a bare browser tab may be refused
underlying: Ministry of Internal Affairs of Georgia — Service Agency vehicle register, compiled and published by Geostat (National Statistics Office of Georgia)
auth: none
cadence: daily on the 10th–31st of the two months after each quarter (Jan/Feb, Apr/May, Jul/Aug, Oct/Nov), 06:55 UTC — Geostat publishes a quarter some weeks after it ends (2026-Q2 was online before 25 July 2026)
variants:
- Whole
variant_notes:
  Whole: Every vehicle registered in Georgia for the first time in the quarter, as Geostat counts its "initial registrations" — all vehicle categories (passenger cars, light and heavy trucks, buses, special vehicles) and new and imported used vehicles together. This is the scope the series has had since it started; Geostat's fuel table has no vehicle-category or new/used filter.
hev_split: false
hev_note: Geostat publishes one "Hybrid" category for plug-in and full hybrids together; it sits in the HEV column and there is no PHEV column. In the BEV/PHEV/ICE curves the hybrids count as ICE.
backfill: hand-entered from Geostat since 2017-Q1 (the API's first quarter); automated from October 2026. The fetcher reproduces 37 of the 38 hand-entered quarters (2017-Q1 to 2026-Q2) exactly; the 38th, 2023-Q3, had a transcription slip of 10 battery-electric vehicles and was corrected to Geostat's figure — see §5.
scope_note: Initial registrations of road motor vehicles in Georgia per quarter — every vehicle category, new and imported used. Georgia's market is dominated by imported used cars (in 2026-Q2 only about one in six newly registered vehicles was at most two years old), so the series measures the drivetrain mix of the vehicles entering the national fleet, not of new-car sales, and is not comparable with ACEA-style new-car counts.
caveats:
- Quarterly, not monthly — each row sits on the quarter's middle month (Feb, May, Aug, Nov), so Georgia has fewer points than the monthly countries and the newest one lags them.
- Every vehicle category, new and imported used together — Geostat's fuel table has no filter for either. Most vehicles are used imports, so the shares describe what enters Georgia's fleet, not new-car sales.
- Plug-in and full hybrids are one combined bucket (HEV column); there is no PHEV curve.
- PETROL includes Geostat's "Gasoline-gas" (petrol cars converted to LPG / CNG); OTHERS is "Gas" plus "Others".
- The brand and model table below covers every powertrain — Geostat publishes brands and models without a fuel split.
processing:
- title: Ask which quarters exist
  text:
  - The portal's period picker lists, per year, the quarters Geostat has published. The fetcher asks for the current year's list (one small request) and stops right there when the newest quarter is already in the chart.
- title: Read the quarter's fuel split
  text:
  - For a new quarter the fetcher reads Geostat's fuel-type table for "vehicles registered during the period" — seven categories — and maps them to the chart's columns. A category it does not know stops the run until someone decides its column.
  decision:
    ask: Geostat fuel category?
    branches:
    - when: Electric
      then: BEV
    - when: Hybrid
      then: HEV
      note: plug-in and full hybrids together
    - when: Gasoline, Gasoline-gas
      then: PETROL
      note: Gasoline-gas = petrol cars converted to LPG / CNG
    - when: Diesel
      then: DIESEL
    - when: Gas, Others
      then: OTHERS
- title: Check it
  text:
  - Geostat's own figure for the year (January to the newest quarter) must equal the sum of its quarters, category by category, and the new quarter's total must be at least half of the same quarter a year earlier (a partial upload stops the run). Only then is the quarter written — as a new line; quarters already in the chart are compared and any difference is reported, never written over.
market_breakdown: market/georgia_top.json
market_heading: Who registers the vehicles
market_total_word: initial (new and imported used)
market_designation_note: Brands and models as Geostat's treemap names them — the top 25 brands of each quarter and the top models of each brand; the rest counts towards the total but is not ranked. A model string is Geostat's (hybrid versions such as "FUSION HYBRID" are separate models).
market_powertrain_note: Every powertrain together, and every vehicle category (vans and trucks included) — Geostat publishes its brand and model table without a fuel or category split.
market_window_note: The last four quarters Geostat has published, summed — quarterly data, so the twelve months are four whole quarters.
fetcher: scripts/fetch_georgia.py
workflow: .github/workflows/fetch-georgia.yml
fragility_doc: docs/architecture/52-source-georgia.md
data_file: data/Georgia.csv
---

# 52 · Source: Georgia (Geostat, initial vehicle registrations)

**Status: LIVE since 2026-10 (automated).** Fetcher `scripts/fetch_georgia.py`
(+ tests `scripts/test_fetch_georgia.py`) and `.github/workflows/fetch-georgia.yml`.
Before that Georgia was entered by hand from the same Geostat portal
(`country_source_stubs.yaml`, method `manual`); the automation keeps the
series exactly as it was — same scope, same columns, same quarterly rows.

## TL;DR

```
Geostat Automobile portal (automobile.geostat.ge, React front end)
  └─ public JSON API autoapi.geostat.ge   (no key; Origin/Referer of the portal)
       mobile-text/ratings?year=Y                → quarters published in Y
       mobile/fuels?year=Y&quarter=Q&table=true  → 7 fuel categories, one quarter
       mobile/fuels?…&quarter=99                 → the year so far (cross-check)
       mobile/treemap?year=Y&quarter=Q&table=true→ brand → model counts
         │
         ▼  fetch_georgia.py
  Electric→BEV · Hybrid→HEV · Gasoline+Gasoline-gas→PETROL · Diesel→DIESEL
  Gas+Others→OTHERS · TOTAL = sum            row on the middle month, quarterly
         │
         ├─ data/Georgia.csv          (line-level upsert, Whole)
         └─ market/georgia_top.json   (last four quarters, class ALL)
```

## 1. Why this source

- **It is the series the gallery already had.** Every hand-entered row since
  2017-Q1 came from this portal; the API is what the portal's own charts read.
  Run against the whole history (2026-10-09, GitHub runner) the fetcher gives
  37 of 38 quarters identically; the 38th was a typo, corrected (§5) — the
  new source *extends* the legacy data rather than replacing it, in the same
  categories (the owner's rule for new sources, 2026-10-09).
- **Official and complete:** Geostat publishes the Interior Ministry's Service
  Agency register — every vehicle registered in Georgia, not a dealer sample.
- **Machine-readable without a key.** The API needs only the portal's
  `Origin` / `Referer` headers. It answers GitHub runners; the Claude dev
  sandbox's proxy refuses `autoapi.geostat.ge` (403 on CONNECT), so probe from
  a runner (doc 42, Phase 0).
- **Only quarterly.** The portal has no monthly breakdown, and the fuel table
  has no filter for vehicle category or for new vs used (`transport=`,
  `v_type=`, `vehicle=`, `filter=` were all tried and are ignored). A finer
  series is not on offer; see §9.

## 2. API → CSV row

| Request | What it gives | Used for |
|---|---|---|
| `mobile-text/ratings?lang=en&year=Y&table=true` | the Rating page's selectors; the one with `placeholder: "Quarter"` lists `99` (All) plus the published quarters as Roman numerals `I`…`IV` | which quarters exist (an unpublished year lists only `99`) |
| `mobile/fuels?lang=en&year=Y&quarter=Q&table=true` | `[{"name": "Gasoline", "value": 22349}, …]` — seven categories; `[]` for an unpublished quarter | the row |
| `mobile/fuels?…&quarter=99` | the same for January → newest published quarter | year cross-check (§5) |
| `mobile/treemap?lang=en&year=Y&quarter=Q&table=true` | `{"TOYOTA": {"CAMRY": 946, …, "დანარჩენი": 780}, …}` — top 25 brands, top models per brand, `დანარჩენი` = "others" | `market/georgia_top.json` |

`table=true` is the page's period switch "during the period" (vehicles
registered in the quarter); `table=false` would be the fleet at the end of
the period — never used here. The year starts at 2017; 2016 and earlier answer `[]`.

Row: `period` = the quarter's middle month (`I`→`-02`, `II`→`-05`,
`III`→`-08`, `IV`→`-11`), `time_interval = quarterly`, `variant = Whole`,
`source = National Statistics Office of Georgia`, integers (older
hand-entered lines keep their `.0` floats — untouched lines are never
rewritten), `notes` empty.

## 3. Category mapping (`CATEGORY_MAP`)

| Geostat | Column | Note |
|---|---|---|
| Electric | BEV | |
| Hybrid | HEV | plug-in and full hybrids in one bucket — `hev_split: false`, no PHEV column (the Türkiye convention; footnote in `footnotes.csv`) |
| Gasoline | PETROL | |
| Gasoline-gas | PETROL | petrol vehicles converted to LPG/CNG; the hand-entered rows did the same ("PETROL = Gasoline+Gasoline-gas") |
| Diesel | DIESEL | |
| Gas | OTHERS | dedicated gas vehicles |
| Others | OTHERS | |

`TOTAL` is the sum of all seven. `Electric`, `Hybrid`, `Gasoline` and
`Diesel` must be present; any name not in the table stops the run.

## 4. Variants

Only `Whole`. Its scope is wider than the EU M1 anchor of most countries:
**all vehicle categories, new and imported used** (`variant_notes` above,
`09-glossary.md` scope table). That is what the source's fuel table measures
and what the hand-entered series always held; changing it would splice two
definitions (invariant 3). The body-type split of the same quarter
(`mobile/body`) shows the order of magnitude of the non-car part: in 2026-Q2,
1,999 lorries/trucks, 1,313 special vehicles, 985 vans ("furgon") and 124
buses out of 43,449. The age split (`mobile/vehicle-age`) shows how used the
flow is: 7,440 vehicles at most two years old in 2026-Q2.

## 5. Governance and validation

- **Year cross-check (every run, stops on failure).** For each year read,
  once all its published quarters are in hand, `quarter=99` must equal the
  sum of the quarters category by category. It held for every year 2017–2025
  and for 2026 (I+II) on 2026-10-09 — Geostat's year figure is the year to
  date, so this is also a check of the newest quarter.
- **Completeness guard (new quarter).** TOTAL < 50 % of the same quarter a
  year earlier stops the run (`force` overrides it); < 75 % is a warning in
  the step summary. Real shocks exist (2020-Q2 was 10,025 against 19,574 a
  year earlier — 51 %), hence the loose limit.
- **Schema drift stops:** an unknown or missing category, a value that is not
  a non-negative integer, a category listed twice, a picker without a
  "Quarter" selector, or a quarter the picker lists while `mobile/fuels` is
  empty.
- **Revisions are reported, not written.** A normal run re-reads the three
  quarters before the target; a difference from the CSV is listed in the step
  summary and kept unless the run is dispatched with `force` (invariant 3).
- **Reproduction of the history (2026-10-09):** `--backfill --dry-run` over
  2017-Q1…2026-Q2 — 37 quarters identical; **2023-Q3** differs: the CSV has
  BEV 463 / TOTAL 44,923, Geostat BEV 453 / TOTAL 44,913. Geostat's 2023
  year figure equals the sum of its quarters with 453, so the CSV row is most
  likely a transcription slip. **Corrected** to Geostat's figure in the
  automation PR (owner's rule, 2026-10-09: typos in hand-entered rows are
  corrected; real definition changes are not rewritten — invariant 3).
  Since then all 38 quarters match.

## 6. Reading the fit

BEV share of the flow: around 1 % in 2017–2019, down to 0.3–0.5 % in
2020–2021, 1.3 % in 2023, 3.0 % in 2024, 4.5 % in 2025 and 7.4 % in
2026-Q1–Q2 (8.6 % in Q2 alone). Because most vehicles are used imports
(the model table is led by models of the US used market — Subaru Forester,
VW Jetta, Toyota Camry, Ford Fusion, Tesla Model 3), the curve tracks what the used-car supply
offers a few years after the new-car markets that produce it; read it next
to Albania (also new + imported used), not next to new-car countries. The
quarterly cadence gives four points a year, so the fit tightens slowly.

## 7. Outputs

| File | Written | Content |
|---|---|---|
| `data/Georgia.csv` | when a quarter is new (or with `force`) | one `Whole` row per quarter |
| `market/georgia_top.json` | when the newest published quarter changes | the last four quarters summed: top 10 brands, top 15 models, class `ALL` (every powertrain) — `market_top.build_top` with the window set to the four quarters' months; an extra `quarters` key names them |

The top file is refreshed inside `market_top.guarded()`: a treemap failure is
a warning annotation and never blocks the CSV commit. It renders on
`sources/georgia.html` (front-matter `market_breakdown`).

## 8. Operations and debugging

```mermaid
sequenceDiagram
    participant Cron as fetch-georgia.yml (cron / dispatch)
    participant Test as test_fetch_georgia.py + test_market_top.py
    participant Py as fetch_georgia.py
    participant API as autoapi.geostat.ge
    participant CSV as data/Georgia.csv
    participant Top as market/georgia_top.json
    participant Render as render-country.yml
    Cron->>Test: mapping, picker, cross-check, guard, upsert, treemap, throttle (gate)
    Cron->>Py: run
    Py->>API: mobile-text/ratings (current year; last year if empty)
    Py->>CSV: newest published quarter already there and top file current?
    alt yes
        Py-->>Cron: no-op (one request)
    else no
        Py->>API: mobile/fuels for the target and the 3 quarters before it
        Py->>Py: categories known? year (quarter=99) = sum of quarters? total ≥ 50 % of a year earlier?
        Py->>CSV: append the new quarter (line-level)
        Py->>API: mobile/treemap × 4
        Py->>Top: last four quarters, class ALL
        Py-->>Cron: run report → step summary
        Cron->>Render: once, Whole
    end
```

- **Schedule:** `55 6 10-31 1,2,4,5,7,8,10,11 *` — the two months after each
  quarter. `build_schedule.py` expects the newest quarter that ended before
  the polling month (July → Q2), so the schedule page shows Georgia as "due"
  in a polling month until Geostat publishes.
- **Normal run:** 1 request when nothing is new; ~12 when a quarter arrives.
- **Backfill:** dispatch with `backfill = true` — every quarter since 2017-Q1
  (~70 requests); only missing quarters are added, differences are listed.
- **Offline:** `python scripts/fetch_georgia.py --dry-run --dump-dir /tmp/geo`
  on a runner saves every answer; `--from-dir /tmp/geo` replays them anywhere
  (file names `mobile_fuels_<year>_<quarter>.json` etc.).

### Runbook

| Symptom (step summary / annotation) | Likely cause | What to do |
|---|---|---|
| `GET … failed: HTTP 403` | the API refused the request — missing Origin/Referer (the dev sandbox proxy also answers 403, at CONNECT) or Geostat started blocking runners | check `HTTP_HEADERS` against what the portal sends (browser devtools on the Rating page); from a runner `curl -H 'Origin: https://automobile.geostat.ge' -H 'Referer: https://automobile.geostat.ge/' 'https://autoapi.geostat.ge/mobile/fuels?lang=en&year=2026&quarter=II&table=true'` |
| `GET … failed: HTTP 404` / `not JSON` | an endpoint was renamed in a new portal build | open the portal, find the new name in its JS bundle (`/assets/index-*.js`, search `autoapi.geostat.ge`), update the path in `Source` |
| `no 'Quarter' selector` | the picker's JSON changed shape | dump `mobile-text/ratings?year=…` and adapt `Source.quarters` + its test |
| `Georgia: no quarter published` | the picker lists no quarter for this year or last | look at the portal; if it shows data, the picker parse is wrong (row above) |
| `unknown category ['…']` | Geostat added or renamed a fuel category | decide the column (a new hybrid split → talk to the owner first: PHEV would be a new column and needs the history to stay comparable), add it to `CATEGORY_MAP` and to `CATEGORY_CASES` in the test |
| `categories … missing` | a required category vanished — likely a rename | as above |
| `listed in the picker but mobile/fuels is empty` | Geostat lists a quarter before its data is loaded | wait for the next run; if it persists, check the portal |
| `year cross-check` | the year figure ≠ the sum of the quarters: a quarter was revised, or the year figure is being reloaded | re-run later; if it persists, compare the quarters on the portal and decide with `force` |
| `completeness guard` | the new quarter is under 50 % of a year earlier — a partial upload, or a real collapse | check the portal and the news; if real, dispatch with `force` |
| `… differs from the CSV … kept unless force` | Geostat revised an older quarter (or a hand-entered row has a typo — those are corrected, as 2023-Q3 was) | nothing breaks; to adopt Geostat's figure dispatch with `quarter = YYYY-Qn` and `force` |
| `top brands/models not refreshed` warning | the treemap failed or lists more vehicles than the quarter | the CSV is committed anyway; replay with `--from-dir` and look at `treemap_units` |

## 9. Not built (yet)

- **Passenger cars only (EU M1) / new only.** Geostat's model rating
  (`mobile/full-raiting`) takes `transport=1` (passenger cars), but it is a
  yearly model list without fuel; the fuel table itself has no category or
  age filter. A Whole restricted to new M1 cars would need record-level data
  that Geostat does not publish.
- **PHEV.** The register's "Hybrid" is one category; no split exists.
- **Monthly rows.** The portal is quarterly throughout.
