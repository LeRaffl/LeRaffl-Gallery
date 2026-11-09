---
title: Fleet dataset — harmonized format, sources & category contract
status: proposal / working spec
summary: >
  How the Fleet (stock / parc) dataset gets a harmonized schema, a per-country
  source catalogue, and the same category contract the registration side already
  uses (doc 35). Converges the hand-curated fleet/fleet_initial.csv onto
  data/<Country>.csv conventions so a future annual "update the fleet" agent has
  one format, one mapping table, and one set of definitions to work against.
---

# 37 · Fleet data — harmonization, sources & category contract

**What this doc is.** The Fleet tab is fed by a hand-curated dataset
(`fleet/fleet_initial.csv`, see `03-data-objects.md` §3.9) that today has **no
fetcher, no source column, no per-row provenance, and a drivetrain taxonomy that
diverges from the registration side.** This is the spec for pulling it onto a
harmonized format so its yearly refresh (done by a maintainer + agent, **not** a
cron — stock moves once a year) becomes a mechanical, well-defined task.

It answers the six things that have to be nailed *before* any fetcher is written:
**format, sources, mapping, extent, quality, definitions.**

> Scope note: this doc specifies the target. The migration of the existing CSV
> and the frontend parser (`index.html:loadFleetObserved`) is a follow-up, gated
> on sign-off of §2. Nothing here has been applied to the data yet.

---

## 1 · Where we are today

`fleet/fleet_initial.csv` — 12 countries, columns
`country,year,BEV,PHEV,HEV,HYBRID,DIESEL,PETROL,OTHERS`:

| Code | Country | Years | n | Hybrid encoding | ICE encoding |
|---|---|---|---|---|---|
| NZ | New Zealand | 2015–2025 | 11 | split `PHEV`+`HEV` | petrol/diesel |
| CN | China | 2017–2025 | 9 | combined in `HYBRID` (really PHEV) | in `OTHERS` (aggregate) |
| AT | Austria | 2000–2025 | 26 | combined in `HYBRID` | petrol/diesel |
| IN | India | 2018–2024 | 7 | none | petrol/diesel |
| GE | **Georgia** | 2017–2025 | 9 | combined in `HYBRID` | petrol/diesel |
| UK | United Kingdom | 2014–2024 | 11 | split `PHEV`+`HEV` | petrol/diesel |
| DE | Germany | 2016–2025 | 10 | combined in `HYBRID` | petrol/diesel |
| NO | Norway | 2016–2025 | 10 | split `PHEV`+`HEV` | petrol/diesel |
| FI | Finland | 1990–2025 | 36 | split `PHEV` (HEV folded) | petrol/diesel |
| DK | Denmark | 1993–2025 | 33 | split `PHEV` (HEV folded) | petrol/diesel |
| CA | Canada | 2017–2024 | 8 | split `PHEV`+`HEV` | petrol/diesel |
| NL | Netherlands | 2018–2025 | 8 | split `PHEV` (HEV folded) | petrol/diesel |

Four defects fall straight out of the table:

1. **`HEV` and `HYBRID` are the same concept stored in two different columns.**
   A source that can't separate plug-in from non-plug-in hybrids goes in
   `HYBRID`; one that can, splits into `PHEV`+`HEV`. The registration side already
   solved this — combined buckets live in `HEV` with a `hev_note`, **there is no
   separate `HYBRID` column** (doc 35 §2.2). Fleet should not invent a second
   convention.
2. **No `source` column.** `data/<Country>.csv` carries per-row provenance; fleet
   carries none. A yearly agent can't tell where 2024's number came from.
3. **No `TOTAL`.** The registration contract validates every row against `TOTAL`
   (doc 35 §2.4). Fleet has no residual check, so a miscoded row is invisible.
4. **ISO codes, and `GE` = Georgia collides visually with `DE` = Germany.** The
   rest of the repo keys on full country names (`data/Netherlands.csv`).

The frontend parser (`index.html:loadFleetObserved`) already papers over #1 with a
`hybrid > 100` heuristic to decide combined-vs-split per row. Harmonizing the data
lets that heuristic be deleted in favour of the real contract.

---

## 2 · The harmonized format

**Principle (the one the maintainer set): store at the finest granularity the
source provides; never fold a category into the wrong parent; let a coarser
common denominator always be *computed* by roll-up.** This is exactly the
registration category contract (doc 35 §2) — Fleet adopts it verbatim rather than
inventing its own, so the two datasets stay one taxonomy.

### 2.1 Schema

One row per `(country, variant, year)`. **The column set is the full "fat
template" — the complete `data/<Country>.csv` fuel set, every drivetrain a
source could ever report.** A country fills only the leaves it publishes and
leaves the rest **empty** (empty ≠ 0, §2.2); no column is dropped just because
today's 12 countries don't use it. Adding a country that reports CNG or flexfuel
then needs no schema change.

```
country, variant, year, source, BEV, PHEV, EREV, HEV, MHEV,
PETROL, DIESEL, GAS, CNG, LPG, FLEXFUEL, ETHANOL, OTHERS, TOTAL, notes
```

- **`country`** — full name (`Netherlands`, `Norway`, `Georgia`, …), matching
  `SD_COUNTRIES` in `index.html`. Migrate the 12 ISO codes.
- **`variant`** — EU-class anchored, same as registrations (`09-glossary.md`):
  `Whole` = M1 passenger cars = the default, no suffix. **`HDV`, `Vans`, `Buses`
  come later** — the column exists now so the schema doesn't move when they do.
- **`year`** — stock is a year-end (or Jan-1, source-dependent — record which in
  `notes`) snapshot. No `period`/`time_interval` needed; annual by definition.
- **`source`** — per-row provenance string, like `data/<Country>.csv`.
- Fuel columns — the **whole** registration set. `GAS` is the aggregate gas
  bucket; `CNG`/`LPG` are its split, `FLEXFUEL`/`ETHANOL` the bio-fuel leaves —
  present in the template so a future source that separates them needs no
  migration. **`EREV` folds into `PHEV`** in the 3-curve view, as on the
  registration side. A country with none of these simply leaves them blank.
- **`TOTAL`** — the source's own total (its scope). Enables the residual check.
- **`notes`** — the `hev_note`/scope/estimate text (see §3, §4).

### 2.2 The category contract (inherited from doc 35 §2, restated for stock)

- **Combined hybrid → `HEV`, `PHEV` empty, flagged by `hev_note`.** Retire the
  `HYBRID` column. China/Austria/Germany/Georgia migrate their `HYBRID` figure
  into `HEV` + a note. (China is special — see §4.) **Frontend requirement: when
  a combined value lives in `HEV`, the Fleet tab MUST make that visible** — the
  legend/definition labels it "Hybrid (combined PHEV+HEV)" and the row's
  `hev_note` is surfaced (tooltip or definitions panel), *even after* it has been
  folded into a shared `Hybrid` band. Folding for comparison must never silently
  present a combined bucket as if it were a split `HEV`.
- **Aggregate-ICE → leave `PETROL`/`DIESEL` empty; the combustion total sits in
  `TOTAL − electrified − OTHERS`.** Populating both an aggregate and the split in
  one row is a validation error, not a merge.
- **Empty ≠ 0** (AGENTS.md invariant 4). A blank means "not broken out"; a real
  `0` means "measured zero of these". Only electrified zeros are believed.
- **Roll-up / common denominator (doc 35 §3).** When the Fleet tab shows or
  aggregates several countries, it collapses to the *coarsest granularity any
  selected country can fill*: `PETROL+DIESEL → ICE` where any member is
  aggregate-ICE; `PHEV+HEV → Hybrid` where any member has a combined bucket.
  Collapsing is always safe (summing bands you already have); un-collapsing is
  impossible. **This is the fix for the exact failure the maintainer flagged** —
  summing a `PETROL` column across members where half don't report one
  under-counts petrol and inflates the residual.
- **Residual check (doc 35 §2.4).** A row whose populated leaves miss `TOTAL` by
  more than ~3 % is suspect: either a category is folded into the wrong parent or
  a leaf is missing. Flag, don't silently draw.

### 2.3 The danger flags — the cases that are *not* safe to roll up

The maintainer's rule has one sharp edge: roll-up only works when every category
sits under its *correct* parent. Two miscodings break it and must be recorded as
data-quality flags (in `notes`, and mirrored in this doc's §4 table), because they
cannot be detected from the numbers alone:

- **`hev_in_ice`** — full/mild hybrids counted on the combustion side
  (petrol/diesel/ICE) instead of as `HEV`. Then "ICE" is overstated and "Hybrid"
  understated, and no collapse recovers it. Affects **NL, DK, FI** (RDW/StatBank
  don't split full HEVs) and is the single most common fleet-source trap.
- **`ev_contaminated`** — hybrids (or PHEVs) counted inside `BEV`. Rare but fatal:
  it inflates the headline BEV-share the whole site is about. No known current
  case, but every new source is checked for it before ingest.

A third, milder flag:

- **`combined_hybrid`** — the honest combined bucket (→ `HEV` + `hev_note`). Safe
  to roll up; only blocks the *split* view, never the aggregate.

---

## 3 · Definitions (what a fleet number means here)

- **Fleet / stock / parc** = vehicles *registered and on the road* at the snapshot
  date — a **stock**, not the **flow** of new registrations in `data/`. Different
  unit, different model (hazard-rate retirement, doc 03 §3.9).
- **Scope is the source's scope.** Like registrations, `BEV share = BEV / TOTAL`
  where `TOTAL` is whatever the national register counts (licensed vs
  ever-registered; M1 only vs light vehicles). Absolute stocks are **not**
  cross-country comparable without reading the scope — record it per country (§4).
- **Snapshot date varies** (Jan-1 for KBA, year-end for others). Recorded in
  `notes`; matters when lining fleet up against year-end registration cumulatives.
- **Variant = EU class**, as intent not guarantee (AGENTS.md, `09-glossary.md`) —
  the per-country scope deviations in §4 are authoritative over the class label.

---

## 4 · Per-country source catalogue

Columns: **Source** (authoritative publisher + access) · **Split** (what the
source can separate) · **Extent** (coverage) · **Quality** · **Flags / scope**.

Access identifiers marked **⚠ verify** still need one live call to the source to
confirm the exact table/endpoint — the egress proxy in the authoring session
blocked several national stats hosts, and the fetcher's CI runner (open egress)
or the maintainer confirms them at build time.

| Country | Source (publisher / access) | Split | Extent | Quality | Flags / scope |
|---|---|---|---|---|---|
| **Netherlands** | RDW (Rijksdienst voor het Wegverkeer). Open Data `opendata.rdw.nl` (Socrata) / CBS StatLine motorvoertuigenpark; the repo already hits RDW via `duurzamemobiliteit.databank.nl` (see `10-source-netherlands.md`), and `fleet_observed.csv` is RDW. | BEV, PHEV; **HEV not split** | 2018–2025 | **High** — open, authoritative | `hev_in_ice` (full HEV in petrol/diesel). M1 personenauto's. |
| **Norway** | SSB StatBank **table 07849** "Registered vehicles by type of transport and type of fuel", PxWebApi (JSON-stat2), annual `data.ssb.no/api/v0/en/table/07849`. PHEV/HEV split from **OFV** *bilparken*. | BEV, petrol, diesel, "other" from SSB; PHEV/HEV from OFV | SSB 2008– (fleet rows 2016–2025) | **High** (SSB official); OFV medium (report-based, no open API) | SSB fuel dimension is coarse pre-recode — **⚠ verify** whether 07849 now carries plug-in/hybrid petrol+diesel leaves; if not, PHEV/HEV need OFV. M1. |
| **Germany** ✅ **confirmed (§4b)** | KBA **FZ 27, sheet FZ 27.9** — Pkw stock by quarter & drivetrain, XLSX (`kba.de/.../FZ27/`). | BEV, PHEV, HEV(+MHEV), gas, FCEV/H₂; **petrol/diesel not split** (aggregate-ICE) | quarterly 2018-07 → now | **High** | Old `HYBRID` was PHEV+HEV lumped → now split. `mhev_in_hev`. Year `Y` = `01.01.(Y+1)` snapshot. **Cron candidate.** M1 Pkw. |
| **Austria** | Statistik Austria "Kfz-Bestand" (Kraftfahrzeuge – Bestand), annual. `statistik.at`. | Combined hybrid only (today) | 2000–2025 (long) | **High** | `combined_hybrid` → `HEV`+note. **⚠ verify** whether STAT now splits PHEV/HEV (recent years likely do). M1. |
| **Denmark** ✅ | Danmarks Statistik StatBank, API `api.statbank.dk`. Reg uses **BIL53**; stock is **BIL710** "Stock of passenger cars as per 1 January" (by propellant, 2018–), the curated rows match it to the vehicle; totals back to 1993 match **BIL8**. | BEV, PHEV; **HEV not split** | 1992–2025 (long) | **High** — open API | `hev_in_ice`. M1 personbiler. **Year = the 1 January (Y+1) table**, like KBA; until 2026-10 every row sat one year late (row Y held the stock on 1 January Y). |
| **Finland** | Traficom vehicle register / Tilastokeskus **StatFin**, PxWeb API. Reg uses table **121d**; **stock table ⚠ verify** (Traficom *Ajoneuvokanta* by *käyttövoima*). | BEV, PHEV; **HEV not split / =0** | 1990–2025 (**longest**) | **High** — open API | `hev_in_ice`. M1 henkilöautot. |
| **United Kingdom** | DfT **VEH0105 / VEH0203** "Licensed vehicles by body type & fuel", quarterly ODS, GB + UK. `gov.uk/.../vehicle-licensing-statistics-data-tables`. | BEV, PHEV, HEV split | 2014–2024 | **High** — open, authoritative | "**Licensed**" excludes SORN (off-road) vehicles — a scope difference vs ever-registered registers. Cars = M1. |
| **New Zealand** | Ministry of Transport / NZTA Waka Kotahi fleet statistics; open dataset on `data.govt.nz` (see `19-source-new-zealand.md`). | BEV, PHEV, HEV, petrol, diesel | 2015–2025 | **High** — open | Light passenger fleet. Cross-check the light/heavy cut against the reg variant. |
| **Canada** | Statistics Canada. Reg uses cube **20-10-0025** (new regs). **Stock cube ⚠ verify** — 20-10-0025 is *registrations*, not parc; confirm a stock-by-fuel cube exists (else this stays estimate-flagged). | BEV, PHEV, HEV split | 2017–2024 | **Medium** — stock source unconfirmed | If no true stock cube, rows are derived/estimated → flag `estimated` in `notes`. Light vehicles; confirm M1 cut. |
| **China** | CPCA / CAAM / MIIT / 公安部 (traffic-police NEV ownership releases); report-derived, no single clean table (cf. `24-source-china.md` for the reg CPCA scrape). | BEV, PHEV; HEV & ICE **not split** | 2017–2025 | **Medium** — multi-report | Current `HYBRID` column is actually **PHEV** (China NEV = BEV+PHEV) → migrate to `PHEV`, not `HEV`. Non-plug HEV + all ICE sit in `OTHERS` (aggregate) → flag. Scope = NEV定义; huge absolute base. |
| **India** | VAHAN dashboard, MoRTH (`vahan.parivahan.gov.in`; see `33-expansion-candidates.md`). | BEV; petrol/diesel; **no PHEV/HEV** | 2018–2024 | **Medium** — coverage gaps | VAHAN historically **excludes some states** (e.g. Telangana, parts of MP) → under-counts stock; scope caveat in `notes`. Registered motor vehicles, M1 slice. |
| **Georgia** | ⚠ **source unconfirmed** — likely Geostat (National Statistics Office of Georgia) or a customs/used-import-derived series. | Combined hybrid | 2017–2025 | **Low** — provenance unclear | `combined_hybrid`; heavily used-import-driven fleet. **Disambiguate: `Georgia` the country, not the US state; full-name migration removes the `GE`/`DE` collision.** Confirm publisher before the next refresh. Eurostat's Georgia rows (reported by Geostat) are within 3–4 % of these BEV figures (§4c). |
| **22 more countries** ✅ | **Eurostat `road_eqs_carpda`**, built — see §4c for the list, mapping and per-country caveats. | mostly BEV/PHEV/HEV/petrol/diesel | 2013–2025 | **High** for most, caveats per country | One source, one fetcher: `scripts/fetch_fleet_eurostat.py`. |

---

## 4a · Download recipes — where to click and which filters to set

For manually pulling a country's file. Each recipe = **portal → dataset →
selections → format**. The universal selection everywhere: **vehicle type =
passenger cars (M1) · measure = stock/count at snapshot · fuel = the finest
breakdown offered · time = all available years**. `✅` = confirmed identifier;
`⚠` = navigate by the described selections and confirm the exact table.

- **Netherlands — CBS StatLine (cleanest fuel×time) or RDW.**
  `⚠` CBS `opendata.cbs.nl/statline` → search *"Personenauto's; brandstofsoort,
  ..."* (motorvoertuigenpark, 1 januari). Filter: *Personenauto's* · brandstof =
  **Benzine, Diesel, Elektriciteit, Plug-in hybride, (Overig)** · perioden = all
  years → download CSV. Trap: CBS/RDW **do not split full HEV** — full hybrids
  sit in Benzine → set `hev_in_ice`. (RDW Socrata alternative:
  `opendata.rdw.nl` "Open Data RDW: Gekentekende_voertuigen" joined to the fuel
  dataset — heavier, same HEV trap.)

- **Norway — SSB table 07849** ✅.
  `data.ssb.no/api/v0/en/table/07849` (or the `ssb.no/en/statbank/table/07849`
  UI → "Save/query as..."). Select: *type of transport = Passenger cars* ·
  *type of fuel = ALL categories* · *contents = Registered vehicles* · *year =
  all*. **Check whether the fuel list includes "Plug-in hybrid petrol/diesel"
  and "Hybrid petrol/diesel"** — if yes, SSB alone gives the full split; if only
  "Electricity / Other", take PHEV/HEV from **OFV** *bilparken* year-end reports.

- **Germany — KBA FZ 13, sheet FZ 13.2.1** ✅ **BUILT (see §4b).**
  Overview `kba.de/.../fz13_b_uebersicht.html`; files `fz13_YYYY.xlsx` (annual,
  snapshot 1 Jan). **Sheet FZ 13.2.1** = Pkw stock by fuel, annual **2010→now**,
  full petrol/diesel/LPG/CNG/BEV/PHEV/HEV split; every row sums to TOTAL.
  Automated by `scripts/fetch_fleet_germany.py` + `fetch-fleet-germany.yml`.

- **United Kingdom — DfT VEH0105** ✅ (or VEH0203).
  `gov.uk` → *"Vehicle licensing statistics data tables"* → **VEH0105**
  (licensed vehicles by body type & fuel), ODS. Filter: BodyType = **Cars** ·
  fuel = Petrol, Diesel, **Battery electric, Plug-in hybrid electric, Hybrid
  electric (petrol), Hybrid electric (diesel)**, Gas/Other · geography = UK ·
  period = year-end (Q4) rows, all years. Scope note: "licensed" **excludes
  SORN** (off-road) cars.

- **Denmark — Danmarks Statistik StatBank, table BIL710** ✅.
  `statbank.dk/BIL710` (API `api.statbank.dk`, stock, **not** BIL53 which is
  new regs). Select: *All Denmark* · ownership *Total* · propellant = all ·
  time = all → CSV. Map Electricity → `BEV`, Pluginhybrid → `PHEV`, Petrol,
  Diesel, and LPG + N-gas + Kerosene + Hydrogen + Ethanol + Other → `OTHERS`;
  the propellants sum to the total. HEV folds into petrol/diesel →
  `hev_in_ice`. **BIL710 year Y is the stock on 1 January Y: write it as year
  Y − 1** (end of the previous year, the convention of every country here).

- **Finland — Traficom / Tilastokeskus StatFin** `⚠`.
  Traficom open data *"Ajoneuvokanta"* (vehicle stock) or StatFin (reg uses 121d;
  stock is a sibling). Select: *henkilöautot* · käyttövoima = **sähkö (BEV),
  ladattava hybridi (PHEV), bensiini, diesel, (muu)** · vuosi = all → CSV. HEV
  folds into bensiini → `hev_in_ice`. Longest series (1990–).

- **Canada — Statistics Canada** `⚠` **(needs a stock cube, not 20-10-0025).**
  `www150.statcan.gc.ca` → search *"vehicle registrations by fuel type"*; confirm
  a **stock/parc** cube exists (20-10-0025 is new registrations). If none, this
  country's rows stay `estimated`. If found: filter fuel = BEV, PHEV, HEV, petrol,
  diesel · geography = Canada · year = all.

- **Austria — Statistik Austria** `⚠`.
  `statistik.at` → Fahrzeuge → *Kfz-Bestand* (STATcube or .ods). Select Pkw ×
  Kraftstoff × Jahr. Check whether recent years split PHEV from HEV; older years
  are combined → `combined_hybrid`.

- **New Zealand — Ministry of Transport / data.govt.nz** ✅.
  `data.govt.nz` → *"NZ vehicle fleet"* open dataset (or
  `transport.govt.nz/statistics-and-insights/fleet-statistics`). Light passenger
  fleet by fuel × year, full BEV/PHEV/HEV/petrol/diesel split.

- **China — CPCA / CAAM / 公安部** (no clean table).
  Traffic-police (公安部) year-end *"新能源汽车保有量"* releases give BEV + PHEV
  ownership; CAAM/CPCA fill gaps. **Their "hybrid" figure is PHEV** (NEV =
  BEV+PHEV) → map to `PHEV`, not `HEV`; non-plug HEV + all ICE stay aggregate in
  `OTHERS`. Report-derived → cite the specific release in `source`.

- **India — VAHAN** `⚠`.
  `vahan.parivahan.gov.in` dashboard → vehicle class = **Motor Car / LMV** ·
  fuel = Electric(BEV), Petrol, Diesel, ... · state = **All India** · year.
  Caveat: some states join VAHAN late → older totals under-count; note it.

- **Georgia — publisher unconfirmed** `⚠`.
  Try Geostat (`geostat.ge`) transport statistics; failing that the series is
  customs/used-import-derived. **Confirm the publisher before the next refresh**
  — this is the weakest link.

**Most useful files to send me first** (they resolve the open `⚠` points and let
me test the migration against real columns before touching the frontend):
**Netherlands, Norway, Denmark, Finland, Canada** (Germany is now confirmed —
§4b). Raw as downloaded (CSV/ODS/XLSX) is perfect — I map them, I don't need
them pre-cleaned.

---

## 4b · Germany — BUILT source & mapping (KBA FZ 13.2.1)

**Source chosen: FZ 13.2.1**, not FZ 27.9. FZ 27.9 is quarterly but gives ICE
only as one aggregate (no petrol/diesel split — it would blow a 42 M-car hole in
the chart or dump it all in `OTHERS`). **FZ 13.2.1** ("Bestand an
Personenkraftwagen 2010 bis YYYY nach Kraftstoffarten", in the annual
`fz13_YYYY.xlsx`) is annual (matches the schema's `year`), splits petrol/diesel
**and** LPG/CNG, reaches back to 2010, and **every row sums exactly to TOTAL** —
so the ICE question is moot. Implemented in `scripts/fetch_fleet_germany.py`.

**Column → canonical mapping** (verified against `fz13_2026.xlsx`; the year sits
in spreadsheet **column B** — column A is blank — so these are 1-based cell
columns):

| Canonical | FZ 13.2.1 col | Header |
|---|---|---|
| (year) | 2 | Jahr — snapshot 1 Jan; **our year = Jahr − 1** |
| `PETROL` | 3 | Benzin (from 2017 **excl. ethanol** → note on older rows) |
| `DIESEL` | 4 | Diesel |
| `LPG` | 5 | Flüssiggas (LPG) |
| `CNG` | 6 | Erdgas (CNG) |
| `BEV` | 7 | Elektro (BEV) |
| `PHEV` | 9 | *darunter* Plug-in |
| `HEV` | 8 − 9 | Hybrid insgesamt − Plug-in (**incl. mild** → `mhev_in_hev`) |
| `OTHERS` | 10 | Sonstige (incl. FCEV/H₂) |
| `TOTAL` | 11 | Insgesamt |

`GAS` is left empty (populate the finer `CNG`+`LPG` leaves instead). Pre-2011
rows have Plug-in unavailable (`X`/`-`) → PHEV empty and the whole hybrid bucket
kept as a combined `HEV` (noted).

**Verified** (snapshot `01.01.2026` → our year 2025): BEV 2,034,260 ✓, PETROL
29,343,732 ✓, DIESEL 13,385,662 ✓ (all = hand data); LPG 284,455 + CNG 66,396 =
350,851 = the old `OTHERS`/gas ✓; PHEV 1,122,958 + HEV 3,239,605 = 4,362,563 =
the old combined `HYBRID` ✓. All 17 rows (our years 2009–2025) close to TOTAL.

**Two things this settles:**

1. **Germany is now fully split** — the old `HYBRID` column lumped `PHEV+HEV`.
   FZ 13.2.1 separates them, so DE fills `PHEV` **and** `HEV`, extends the series
   back to **2009**, and gains real `PETROL/DIESEL/LPG/CNG/TOTAL/source`.
2. **Year convention** — year `Y` = the `01.01.(Y+1)` snapshot (stock at end of
   `Y`); matches the maintainer's existing rows exactly. Snapshot date recorded
   in `notes`/`source`. Stays **annual** (consistent with the other 11 countries
   and the annual fleet model); FZ 27.9's quarterly depth is a future option.

**Scope notes** (from the FZ 13.2.1 Hinweis): motorhomes/ambulances counted as
Pkw since 2006; only currently-registered vehicles (no temporary de-registrations)
since 2008; Benzin excludes ethanol from 2017.

### FZ 27.9 (quarterly) — the alternative, not used

FZ 27 sheet **FZ 27.9** carries the same drivetrain splits **by quarter** back to
`01.07.2018` (verified indices: TOTAL=2, BEV=7, FCEV=8, PHEV=9, HEV=10, GAS=13,
H₂=14), but **no petrol/diesel split** (aggregate ICE only). Kept on the shelf in
case a future quarterly fleet view is wanted; FZ 13.2.1 is preferred for the
annual series.

### ArcGIS Hub API — a cleaner source, pending one check

KBA also runs an **ArcGIS Hub** (`das-kba-statistikportal.hub.arcgis.com`, app
`experience.arcgis.com/experience/85fe6a72369a4700878c72bb9da8dfa6`). A Hub is a
front-end over **ArcGIS Feature Services** with a real REST API — no xlsx
parsing, stable URLs, JSON:

- **Catalog feed** (enumerate everything + its service URLs):
  `.../api/feed/dcat-us/1.1.json`.
- **Feature-service query** (the data): each dataset →
  `https://services-euN.arcgis.com/<orgId>/arcgis/rest/services/<Name>/FeatureServer/0/query?where=1=1&outFields=*&returnGeometry=false&f=json`,
  paginated via `resultOffset`/`resultRecordCount`, server-side aggregation via
  `outStatistics`.
- **Direct CSV** per dataset:
  `https://opendata.arcgis.com/api/v3/datasets/<id>/downloads/data?format=csv`.

**Check done — the Hub does NOT carry the FZ 27.9 equivalent, so FZ 27.9 xlsx
stays the source.** The DCAT feed (23 datasets, org `U09msXRZoxesNntH`,
`services-eu1.arcgis.com`) was inspected. Its stock datasets are:

- **`FZ Modellreihen Bestand`** (+ Top50/Top3 variants) — Pkw stock by
  brand/model/segment *with* an "Antriebsarten" attribute, but **only Modellreihen
  with >1,000 vehicles** (the long tail is dropped) and a snapshot, not a clean
  national fuel×time series. Aggregating drivetrain over models would under-count.
- **`FZ Pkw mit Elektro(-)antrieb {Bundesland,Gemeinde,Zulassungsbezirk,
  Gitterzellen,RegioStaR,Regionen}`** — electric-drive Pkw only (BEV+PHEV),
  regional. No petrol/diesel/HEV.

None is the national Pkw × Kraftstoffart × time series. So the JSON API is **not**
a drop-in for FZ 27.9. Two side-notes: the model-level Bestand service carries
**Erstzulassungsdatum (from 1990)** per record — a future input for the fleet
model's **age/vintage distribution** (hazard curve), not the headline series; and
the Neuzulassungen services (`Top50Modellreihen`, `Top3ModellreihenSegment`) are
likewise **capped at top models**, so they don't cleanly beat ACEA for national
registration totals either.

**Registrations bonus (out of scope, noted):** `FZ_Top50Modellreihen` /
`FZ_Top3ModellreihenSegment` are monthly **Neuzulassungen** feature services.
Germany now has a **dedicated registration fetcher** — `scripts/fetch_germany.py`
(`.github/workflows/fetch-germany.yml`) parses the KBA monthly press-release
`…_merkmale.xlsx` and upserts `data/Germany.csv` (Whole), replacing the old
hand-entry / ACEA path. A native KBA ArcGIS API could upgrade the *source*
later, but the top-model feature services above still don't give a clean
national total, so the press-release workbook remains the source.

### Cron — yes for Germany. Unlike the general "no cron" stance, Germany earns
one: a stable overview page, a predictable annual `fz13_YYYY.xlsx`, one clean
sheet. Built as `.github/workflows/fetch-fleet-germany.yml`:
`scripts/fetch_fleet_germany.py` scrapes `fz13_b_uebersicht.html` for the newest
`fz13_*.xlsx`, parses FZ 13.2.1, line-upserts the Germany/Whole rows into the
fleet CSV; monthly `workflow_dispatch` + cron (idempotent, off-season runs
no-op). **No render dispatch** (fleet is computed in the browser). This is the
pilot for the whole fleet-fetch pattern.

---

## 4c · Eurostat — BUILT source for 22 countries (`road_eqs_carpda`)

**Source.** Eurostat *Passenger cars by type of motor energy*
(`road_eqs_carpda`), JSON-stat from the dissemination API
(`ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/road_eqs_carpda`),
open, no key, about 100 KB. Unit `NR`, legal form `TOTAL`, stock **at 31
December** of the reference year: the same `year` as everywhere else in this
file. National registers report it to Eurostat, so it is the fleet-side
counterpart of ACEA: one fetcher instead of 22. Implemented in
`scripts/fetch_fleet_eurostat.py` (tests: `scripts/test_fetch_fleet_eurostat.py`).
No cron and no render: the table refreshes once a year (autumn), so run the
script by hand or with an agent, like the other curated countries.

**Checked against the series already here** (same year, BEV): Germany, Austria
and Finland are identical to the vehicle (KBA stock on 1 Jan 2025 = Eurostat
2024); Norway, the Netherlands and the UK are within 2 %, Georgia within 4 %.
That pins the year convention. The same check showed that the curated
**Denmark** rows were one year late (each was the stock on 1 January of its own
year); fixed in #362, see the Denmark row in §4.

**Hierarchy** (every level sums exactly on full rows):
`TOTAL = PET + DIE + ALT`, `PET = PET_X_HYB + ELC_PET_HYB + ELC_PET_PI` (diesel
alike), `ALT ⊇ ELC + HYD_FCELL + REN_OTH + GAS + LPG + OTH`.

| Canonical | Eurostat |
|---|---|
| `BEV` | `ELC` |
| `PHEV` | `ELC_PET_PI + ELC_DIE_PI` |
| `HEV` | the rest of the hybrids: `(PET − PET_X_HYB − ELC_PET_PI)` + diesel alike |
| `PETROL` / `DIESEL` | `PET_X_HYB` / `DIE_X_HYB` |
| `CNG` / `LPG` | `GAS` (natural gas) / `LPG` |
| `OTHERS` | `HYD_FCELL + REN_OTH + OTH` + any part of `ALT` without a leaf |
| `TOTAL` | `TOTAL` |

**Degraded rows** follow §2.2, decided per row (a country often changes how it
reports): no plug-in leaf → `PHEV` empty and `HEV` is the combined bucket
(noted); no "excluding hybrids" leaf → `PETROL`/`DIESEL` are the family total
minus the hybrid leaves that exist, the rest of the hybrids stay in ICE (noted,
`hev_in_ice`); no hybrid leaf and nothing to derive one from → `PHEV`/`HEV`
empty, noted as "no hybrid figure" (empty ≠ 0); no petrol or no diesel figure at all → row skipped (an empty ICE
would make the row's stock vanish in the Fleet tab); columns missing `TOTAL` by
more than 3 % → row skipped. Eurostat's flags go into `notes` (`i` imputed,
`p` provisional), plus the caveats below. The fetcher refuses to overwrite a
country whose rows come from any other source, so the national series in §4
stay as they are.

| Country | Years | Notes |
|---|---|---|
| Albania | 2014–2025 | Hybrids are in `HEV` only in 2020; in every other year they are most likely in `OTHERS` (≈ 10 % of the stock). BEV looks sound. |
| Belgium | 2013–2025 | Combined hybrids until 2021 (PHEV boom inside `HEV`). |
| Bulgaria | 2016–2024 | Most cells imputed by Eurostat; combined hybrids until 2022; 2025 misses 16 % of `TOTAL` (no `LPG`), skipped. |
| Croatia | 2013–2025 | Hybrids in ICE 2013–14, no hybrid figure at all 2015–22; 3–4 % of `ALT` without a leaf until 2024 (in `OTHERS`). |
| Cyprus | 2013–2025 | Full split throughout. |
| Czechia | 2013–2025 | Hybrids in ICE until 2021, combined in 2022; Eurostat breaks in 2018 (LPG) and 2023 (diesel). |
| Estonia | 2013–2025 | Combined hybrids until 2020; the 2025 drop is most likely the new car tax (owners deregistering unused cars). |
| France | 2013–2024 | 2025 has no petrol/diesel figure yet. |
| Hungary | 2013–2025 | **Hybrids sit in `OTHERS` until 2023** (they appear as `HEV` in 2024 as `OTHERS` falls to near zero). BEV stock is about twice the cumulative new BEV registrations; most likely used EV imports, not checked against a national source. |
| Ireland | 2013–2025 | Hybrids in ICE until 2016, combined 2017–22. |
| Italy | 2013–2025 | Combined hybrids in most years until 2022. |
| Latvia, Lithuania | 2013/2014–2025 | Combined hybrids until 2021/22; Lithuania's `OTHERS` (≈ 6 %) is most likely LPG conversions; Lithuania 2013 skipped (misses 17 % of `TOTAL`). |
| Luxembourg, Spain | 2013/2014–2025 | Full split throughout. |
| Malta, Portugal | 2013–2025 | Combined hybrids until 2018 (Malta) and in 2013 (Portugal); Portugal 2025 provisional. |
| Slovenia | 2013–2025 | No hybrid figure at all until 2021 (`PET` = `PET_X_HYB`), full split from 2022. |
| Romania | 2018–2025 | Before 2018 `ELC` falls tenfold the year the hybrid leaves appear, so it held hybrids: those years are not written. Combined hybrids until 2022. |
| Sweden | 2013–2025 | `OTHERS` ≈ 3 % = E85 flexifuel (`REN_OTH`) and gas. |
| Switzerland | 2013–2025 | Full split throughout. |
| Türkiye | 2013–2025 | Combined hybrids in 2013–16, 2022–23 and 2025 (no plug-in leaf); `LPG` ≈ 30 % of the stock. |

**Not built, and why:** Greece and Slovakia report no petrol or diesel figure in
any year; Poland none in 2015–23 or 2025, and its register keeps cars that no
longer drive; Iceland has one usable year. Liechtenstein, Moldova, Serbia,
Bosnia, Montenegro, North Macedonia and Kosovo have no registration series in
the gallery, so the Fleet tab could not project them. **The countries already in
§4 are not taken from Eurostat**, but its rows could fill gaps there (Austria's
PHEV/HEV split from 2013, a cross-check for Georgia); that is a decision per
country, not part of this fetcher.

**Annual refresh:** `python scripts/fetch_fleet_eurostat.py` (add `--dry-run`
first). It rewrites the Eurostat rows of every country in `COUNTRIES`, so a
revised year is picked up too. New country: add its geo code to `COUNTRIES` (the
gallery name must match `params.csv`, which is what the Fleet tab joins on), add
a row to the table above.

---

## 5 · Status & what's next

**Done (the Germany pilot):**
- ✅ Harmonized schema (§2.1) applied to `fleet/fleet_initial.csv` — full country
  names, `variant`, `source`, `TOTAL`, `notes`, the fat fuel template; `HYBRID`
  column retired (combined → `HEV`, China → `PHEV`). All rows preserved; DE
  extended back to 2009.
- ✅ `index.html:loadFleetObserved` reads the harmonized schema (dual-read, so it
  also tolerates the old one), folds `EREV→PHEV`/`MHEV→HEV`/gas→`OTHERS`, and
  resolves combined-vs-split by whether `PHEV` is populated (no more `>100`
  heuristic). Combined buckets surface as a labelled "HYBRID (combined PHEV+HEV)"
  band.
- ✅ `scripts/fetch_fleet_germany.py` (FZ 13.2.1 parser + overview scrape +
  line-upsert) and `.github/workflows/fetch-fleet-germany.yml` (monthly cron +
  dispatch, `actionlint`-clean, no render). Parser verified against the real file.
- ✅ **22 more countries from Eurostat** (§4c): `scripts/fetch_fleet_eurostat.py`,
  one source for the EU/EFTA countries plus Albania and Türkiye that have a
  registration series. The Fleet tab now offers 34 countries.
- ✅ **Calibration from the repo's own data** (§7): `scripts/build_fleet_calibration.py`
  → `fleet/fleet_calibration.json` (observed net attrition, inflow mix, age
  structure per country), rebuilt monthly by
  `.github/workflows/build-fleet-calibration.yml`; `scripts/fetch_grid_mix.py` →
  `fleet/grid_mix.csv` (each country's electricity mix and CO2e intensity, for
  the Energy view). The loader now reads **`Whole` rows only**, so a stock row
  of another variant can be added without being counted as a passenger car.

**Next:**
1. **Roll the pattern out** to the other ⚠ countries: confirm each source (one
   live call), add `scripts/fetch_fleet_<country>.py`. Cron only where it earns
   it (like DE); otherwise on-demand/yearly with an agent.
2. **Backfill `source` + flags** for the 11 not-yet-automated countries from §4
   (they migrated with values intact but mostly empty `source`/`TOTAL`).
3. **Fleet variants (Vans / HDV / Buses)** — the next step after §7. What is
   already in place: the schema has `variant` (§2.1), the loader filters on it,
   the calibration builder reads `Whole` only, and the registration side already
   carries `data/<Country>_{Vans,HDV,Buses}.csv` with fitted curves in
   `params.csv` and volumes in `weights.csv`. What it takes, in this order:
   1. **Stock rows.** Eurostat `road_eqs_lormot` (lorries by motor energy),
      `road_eqs_busmot` (buses) and the N1 share of lorries extend
      `fetch_fleet_eurostat.py`; KBA FZ 13.1/13.7/13.9/13.10 extend
      `fetch_fleet_germany.py`. Check scope per source first: the N1/N2 boundary
      (3.5 t) and "lorries" vs "road tractors" differ by country.
   2. **Calibration per variant.** `build_fleet_calibration.py` keyed
      `(country, variant)`; the stock-flow identity is the same, the turnover is
      not (vans leave faster than cars, tractors are exported young).
   3. **A variant picker** in the Fleet tab (one variant at a time: a van and a
      car do not stack), reusing `getCountryWholeParam` / `getCountryAnnualInflow`
      with the variant instead of `whole`.
   4. **Energy factors per variant** — the hard part, and the reason this is not
      a rename: consumption (an articulated lorry burns ~30 l/100 km), mileage
      (~100,000 km a year for long-haul tractors against ~13,000 for a car) and
      the powertrain set (diesel-only today, gas and fuel-cell as real niches)
      need their own sourced rows in `energy_factors.csv`, keyed by variant.
      Per vehicle an HDV emits 30 to 60 times a car's CO2e, so a wrong factor
      here outweighs everything calibrated for cars.
4. **Later:** KBA Neuzulassungen via the ArcGIS API (§4b) to replace ACEA for
   Germany registrations.

### When you change X, also update Y (fleet)

- **This schema / the contract** → `index.html:loadFleetObserved`, `03-data-objects.md`
  §3.9, and keep it consistent with the registration contract in `35-proposal-raw-data-tab.md` §2.
- **A fleet source's logic** → `scripts/fetch_fleet_<c>.py` **and** this §4 row
  **and** the country's `notes`/flags. For a Eurostat country: `COUNTRIES` in
  `scripts/fetch_fleet_eurostat.py` and the §4c table.
- **A new fleet country / variant** → this §4 table, `SD_COUNTRIES` variants in
  `index.html`, and `09-glossary.md` if the scope needs a note. A new country
  also needs its grid rows: re-run `scripts/fetch_grid_mix.py` (it reads the
  country list from the stock file) and `scripts/build_fleet_calibration.py`.
- **The projection model or its defaults** (`index.html`: `projectCountryFleet*`,
  `fleetTurnover`, `fleetIceSplit`, `initVintageBuckets`, the `haz*` defaults) →
  §7 here, the Fleet entries of the in-page FAQ, and `scripts/test_fleet_model.py`.
- **What the calibration file contains** → `scripts/build_fleet_calibration.py`,
  `scripts/test_build_fleet_calibration.py`, §7 here, and the readers in
  `index.html` (`fleetCalibration`, `fleetAgeProfile`, `fleetCombustionHistory`).
- **The grid data or its scenarios** → `scripts/fetch_grid_mix.py`,
  `index.html` (`parseGridMix`, `feGridAt`), `energy_factors.csv` (target rows)
  and `architecture/energy-view-methodology.md` §6a/§7.

---

## 6 · Open verification points

- SSB 07849 fuel-leaf granularity (does it split plug-in/hybrid, or only "other"?).
- Finland exact **stock** (not registration) table ID. (~~Denmark~~ —
  **resolved**: BIL710, see §4a; it also showed the rows were one year late.)
- Canada: whether a stock-by-fuel cube exists, or fleet rows are estimates.
- Georgia: the actual publisher and its split capability. (Eurostat carries
  Geostat's figures within 3–4 % of the curated BEV values, §4c: a strong lead.)
- ~~KBA~~ — **resolved**: FZ 27.9 confirmed, mapping in §4b.
- ~~KBA ArcGIS Hub~~ — **resolved**: Hub has no national fuel×time series
  (only capped model-level + regional e-mobility); FZ 27.9 xlsx stays the source.

These are the only gaps between this spec and a mechanical yearly refresh.

---

## 7 · Calibration — what the projection is fitted to

Until 2026-11 the Fleet tab's projection ran on seven global attrition rates
typed into the page (BEV 0.035 … OTHERS 0.060), one age assumption, and one rule
for where new cars go. A review against the repo's own data found all three
wrong in ways that were visible in the default chart:

| Defect | Effect in the default view |
|---|---|
| One attrition level for every country | Observed net attrition ranges from −2 % (Romania) to +9 % (Luxembourg) a year. With the global ~5–6 %, Finland's fleet fell from 3.8 M to 2.0 M by 2035, Romania's from 8.8 M to 4.0 M, China's from 359 M to 278 M. None of these fleets is shrinking. |
| A rate box did not mean what it said | The Weibull scale was set by equal *median* life, and the start fleet was spread uniformly over ages 0…scale. A fleet with "0.050" in the box lost about 6.4 % in its first year. |
| Every category assumed mature | A battery fleet whose cars are mostly under five years old was spread over 22 years of ages and started losing cars at once. |
| BEV 0.035 vs petrol 0.050 | Asserted a 40 % longer life for battery cars. No source, and no battery fleet is old enough to show it. |
| Combustion inflow booked to `OTHERS` | The S-curve "ICE" share is everything but BEV/PHEV/EREV (`R/data.R`): full hybrids, petrol, diesel, gas. All of it went to `OTHERS`, which the Energy view reads as LPG/CNG. By 2035, 23 % of Germany's projected fleet was a gas car; full hybrids (46 % of Germany's combustion-side registrations) never reached the HEV band. |
| Rates rose with *projection* time (knee 12 y, +0.4 pp/y) | Only in the non-default linear mode, but there a fleet with steady inflow shed cars ever faster after 2037 for no physical reason. |

### 7.1 `fleet/fleet_calibration.json`

Generated by `scripts/build_fleet_calibration.py` from `fleet/fleet_initial.csv`
and `data/<Country>.csv` (passenger cars, `Whole`, only). Never hand-edit.
Per country, each block present only where the data supports it:

```json
"Germany": {
  "attrition":   {"rate": 0.0515, "n": 5, "from": 2021, "to": 2025,
                  "by_year": {"2021": 0.0483, "…": 0},
                  "by_fuel": {"BEV": 0.1229, "PHEV": 0.1406, "PETROL": 0.0433, "DIESEL": 0.0563}},
  "inflow_mix":  {"window": "2025-11..2026-10",
                  "HEV": 0.4613, "PETROL": 0.3381, "DIESEL": 0.1922, "OTHERS": 0.0083},
  "reg_by_year": {"BEV": {"2012": 2956, "…": 0}, "PHEV": {}, "HEV": {}, "COMBUSTION": {}}
}
```

**`attrition.rate`** — net attrition of the whole passenger-car stock, from the
stock-flow identity (year = stock at 31 December, §3):

```
net_exits[Y] = stock[Y-1] + new_registrations[Y] - stock[Y]
rate[Y]      = net_exits[Y] / stock[Y-1]
```

published as the **median of the last five** stock years that have a complete
registration year (12 months, or four quarters, or one yearly row), and only
with at least three of them. It is a **net** figure and it describes the
**registry**:

- scrappage and exports **minus** used imports and re-registrations. Exporters
  of young used cars are high (Luxembourg 9.1 %, Belgium 6.1 %, Germany 5.1 %),
  importers low or negative (Lithuania −0.9 %, Romania −2.0 %, New Zealand
  1.1 %);
- registries that rarely deregister (Finland 1.2 %, Türkiye 0.0 %) show low
  values that say more about the register than about the cars. The calibration
  reproduces them on purpose: the projection continues the *published* series.
- it also inherits any scope difference between a country's stock and
  registration source. The published `by_year` values are the check: a stable
  series is a real rate, a jumpy one is a scope or revision artefact (Estonia
  2025 jumps to 8.5 % on a register clean-up; the median ignores it).

**`attrition.by_fuel`** — the same identity per fuel. **Diagnostic only, not
used by the model.** It shows what a single rate hides — Germany loses 12 % of
its battery cars a year (young used BEVs exported), the Netherlands 16 % of its
diesels — and it is what a later per-category calibration would start from.
Values beyond ±50 % (India's BEV row) are a scope mismatch and are left out.

**`inflow_mix`** — shares of the combustion side (`TOTAL − BEV − PHEV − EREV`)
over the latest 12 months of registrations: `HEV` (incl. `MHEV` where the source
has that column), `PETROL`, `DIESEL`, `OTHERS`. Published only where the source
reports its own petrol **and** diesel split for the whole window (invariant 4:
an empty column is not zero).

**`reg_by_year`** — yearly registrations of complete years per class, the raw
material for age profiles. `COMBUSTION = TOTAL − BEV − PHEV − HEV`.

### 7.2 How the page uses it

**Turnover boxes.** Each of the seven boxes is the share of a *mature* fleet of
that type that leaves per year — in both hazard modes. In Weibull mode the scale
is solved so that `1 / Σ S(a) = rate` (a mature fleet holds `S(a)` cars of age
`a` per car registered a year). Defaults: 0.045 everywhere, diesel 0.050.
0.045 is the middle of the large non-import-dominated registries (Germany 5.1 %,
UK 4.5 %, Norway 4.4 %, Austria 4.0 %, France 3.7 %). The only difference
between categories the stock data supports is diesel leaving western fleets
faster than petrol (≈ 1.1×).

**Calibration switch** (default on, `fleetTurnover`). One factor per country
scales all seven rates so the first projected year loses the country's observed
share. The boxes then set how categories differ; the country's record sets the
level. Bounds: the survival model is never asked for less than 1 % or more than
15 % a year. Below 1 % — which no survival curve can produce — the model retires
1 % and books the difference as **net used imports**, arriving each year in the
current fleet's own mix and age structure. The line under the switch states the
figure for every selected country.

**Age structure** (`initVintageBuckets`), best source first:

1. BEV / PHEV / HEV (and the combined HYBRID bucket): spread over the ages in
   proportion to the country's own yearly registrations of that class.
2. Everything else, where at least five unbroken years of `COMBUSTION` exist: each
   category takes its share of every registered year, thinned by its own
   survival curve; stock left over is older than the record and takes the mature
   shape beyond it. A fleet that grew fast starts young and loses more as it
   ages (China: 1.5 % a year now, 2.1 % in 2035, 3.2 % in 2050); a steady fleet
   starts near mature (Germany stays at 5.1 to 5.4 %). This is the browser's answer to
   the young-fleet problem `R/energy_flows.R` handles by converging the rate.
3. Otherwise mature.

**Inflow** (`fleetYearInflow`, shared by both modes). Volume: the last 12 months
of registrations (`weights.csv`). BEV by the fitted curve, plug-ins between the
BEV and ICE curves, and the combustion side split by `inflow_mix` into HEV /
PETROL / DIESEL / OTHERS (`fleetIceSplit`). A class the stock does not carry
goes where that stock keeps those cars (full hybrids → HYBRID, else PETROL;
petrol/diesel → OTHERS where the stock has no split, i.e. China). Without an
`inflow_mix` the split follows the stock, which overstates diesel.

### 7.3 What is still assumed — read before quoting a projection

- **Turnover is constant at its recent level.** No saturation: a fleet that has
  been growing keeps growing. Romania (+3.6 % a year observed) reaches 1.4× by
  2035 and 2.2× by 2050 in the projection. Over 10 years that is the recent
  trend; over 25 it is an extrapolation nobody should quote.
- **Registration volume is constant** at the last 12 months (× the multiplier).
- **The inflow mix inside the combustion side is constant.** Diesel's share of
  sales is still falling in most markets, so future diesel stock is overstated.
- **One turnover level per country, not per fuel.** Countries that export young
  battery cars (Germany, `by_fuel.BEV` 12 %) keep them in the projection:
  Germany's projected BEV stock is too high by roughly the cumulative export.
- **Used imports arrive in the current fleet's mix.** In reality the used cars
  entering Lithuania or New Zealand will be increasingly electric.
- **Weibull shape 3** for every category and country. Published car survival
  curves put the shape between roughly 2 and 6 depending on country and method;
  it is an input, not a measurement, and has not been fitted here.

### 7.4 Maintenance

- `build-fleet-calibration.yml` rebuilds the JSON monthly (10th) and on any push
  that changes the stock file or the script. Deterministic, no timestamp:
  unchanged input → no commit.
- `scripts/build_fleet_calibration.py --report` prints the table; read it after
  a yearly stock refresh. A rate that moved by more than a point is a data
  question (a scope change, a revised stock year), not a model question.
- `fleet/grid_mix.csv` is refreshed by hand once a year with
  `scripts/fetch_grid_mix.py` (Ember's release is in spring);
  `architecture/energy-view-methodology.md` §6a.
- `fleet/hazard_defaults.csv`, `fleet/fleet_observed.csv` and
  `fleet/fleet_meta.json` predate the harmonized dataset and are **not read by
  the page**. `hazard_defaults.csv` still feeds `R/energy_flows.R`. Their rates
  (NL-based, borrowed for "EU" and "WORLD") are superseded by §7.1 and should
  not be quoted.
