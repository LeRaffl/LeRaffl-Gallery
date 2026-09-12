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
(`fleet/fleet_initial.csv`, see `03-data-objects.md` §3.8) that today has **no
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
  unit, different model (hazard-rate retirement, doc 03 §3.8).
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
| **Denmark** | Danmarks Statistik StatBank, PxWeb API (`api.statbank.dk`). Reg uses **BIL53**; **stock table ⚠ verify** (BILA/BEST family — "Bestanden af køretøjer"). | BEV, PHEV; **HEV not split** | 1993–2025 (long) | **High** — open API | `hev_in_ice`. M1 personbiler. |
| **Finland** | Traficom vehicle register / Tilastokeskus **StatFin**, PxWeb API. Reg uses table **121d**; **stock table ⚠ verify** (Traficom *Ajoneuvokanta* by *käyttövoima*). | BEV, PHEV; **HEV not split / =0** | 1990–2025 (**longest**) | **High** — open API | `hev_in_ice`. M1 henkilöautot. |
| **United Kingdom** | DfT **VEH0105 / VEH0203** "Licensed vehicles by body type & fuel", quarterly ODS, GB + UK. `gov.uk/.../vehicle-licensing-statistics-data-tables`. | BEV, PHEV, HEV split | 2014–2024 | **High** — open, authoritative | "**Licensed**" excludes SORN (off-road) vehicles — a scope difference vs ever-registered registers. Cars = M1. |
| **New Zealand** | Ministry of Transport / NZTA Waka Kotahi fleet statistics; open dataset on `data.govt.nz` (see `19-source-new-zealand.md`). | BEV, PHEV, HEV, petrol, diesel | 2015–2025 | **High** — open | Light passenger fleet. Cross-check the light/heavy cut against the reg variant. |
| **Canada** | Statistics Canada. Reg uses cube **20-10-0025** (new regs). **Stock cube ⚠ verify** — 20-10-0025 is *registrations*, not parc; confirm a stock-by-fuel cube exists (else this stays estimate-flagged). | BEV, PHEV, HEV split | 2017–2024 | **Medium** — stock source unconfirmed | If no true stock cube, rows are derived/estimated → flag `estimated` in `notes`. Light vehicles; confirm M1 cut. |
| **China** | CPCA / CAAM / MIIT / 公安部 (traffic-police NEV ownership releases); report-derived, no single clean table (cf. `24-source-china.md` for the reg CPCA scrape). | BEV, PHEV; HEV & ICE **not split** | 2017–2025 | **Medium** — multi-report | Current `HYBRID` column is actually **PHEV** (China NEV = BEV+PHEV) → migrate to `PHEV`, not `HEV`. Non-plug HEV + all ICE sit in `OTHERS` (aggregate) → flag. Scope = NEV定义; huge absolute base. |
| **India** | VAHAN dashboard, MoRTH (`vahan.parivahan.gov.in`; see `33-expansion-candidates.md`). | BEV; petrol/diesel; **no PHEV/HEV** | 2018–2024 | **Medium** — coverage gaps | VAHAN historically **excludes some states** (e.g. Telangana, parts of MP) → under-counts stock; scope caveat in `notes`. Registered motor vehicles, M1 slice. |
| **Georgia** | ⚠ **source unconfirmed** — likely Geostat (National Statistics Office of Georgia) or a customs/used-import-derived series. | Combined hybrid | 2017–2025 | **Low** — provenance unclear | `combined_hybrid`; heavily used-import-driven fleet. **Disambiguate: `Georgia` the country, not the US state; full-name migration removes the `GE`/`DE` collision.** Confirm publisher before the next refresh. |

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

- **Germany — KBA FZ 27, sheet FZ 27.9** ✅ **confirmed (see §4b).**
  Overview `kba.de/.../FZ27/fz27_b_uebersicht.html`; files
  `fz27_YYYYMM.xlsx` with `MM ∈ {01,04,07,10}` (quarterly snapshots
  1 Jan/Apr/Jul/Oct). **Sheet FZ 27.9** = Pkw stock **by quarter** and drivetrain,
  one clean time series back to **01.07.2018** — the automatable backbone.
  (The older FZ 13 is the annual equivalent; 27.9 supersedes it with quarterly
  depth and the same splits.)

- **United Kingdom — DfT VEH0105** ✅ (or VEH0203).
  `gov.uk` → *"Vehicle licensing statistics data tables"* → **VEH0105**
  (licensed vehicles by body type & fuel), ODS. Filter: BodyType = **Cars** ·
  fuel = Petrol, Diesel, **Battery electric, Plug-in hybrid electric, Hybrid
  electric (petrol), Hybrid electric (diesel)**, Gas/Other · geography = UK ·
  period = year-end (Q4) rows, all years. Scope note: "licensed" **excludes
  SORN** (off-road) cars.

- **Denmark — Danmarks Statistik StatBank** `⚠`.
  `statbank.dk` (PxWeb API `api.statbank.dk`) → transport → *bestand af
  køretøjer* (stock, **not** BIL53 which is new regs). Find the personbiler ×
  drivmiddel × tid table. Select: *personbiler* · drivmiddel = **El, Plug-in
  hybrid, Benzin, Diesel, (Andet)** · tid = all years → CSV. HEV folds into
  benzin/diesel → `hev_in_ice`.

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

## 4b · Germany — confirmed source & mapping (KBA FZ 27.9)

Verified against `fz27_202607.xlsx` and cross-checked against the existing
hand-entered `DE` rows. **FZ 27.9** ("Bestand an Personenkraftwagen nach
Quartalen sowie nach ausgewählten Kraftstoffarten") is a quarterly matrix; one
row per snapshot date (`01.01/04/07/10.YYYY`), back to `01.07.2018`.

**Column → canonical mapping** (0-indexed A=0):

| Canonical | FZ 27.9 column | Header |
|---|---|---|
| `TOTAL` | B | Anzahl insgesamt (all Pkw) |
| `BEV` | **G** | Elektro (BEV) — **not** col E, which is BEV+FCEV+PHEV combined |
| `PHEV` | I | Plug-in-Hybrid |
| `HEV` | J | Hybrid (ohne Plug-in) — **incl. mild hybrids** → flag `mhev_in_hev` |
| `GAS` | M | Gas insgesamt |
| `OTHERS` | H + N | Brennstoffzelle (FCEV) + Wasserstoff |
| `PETROL`/`DIESEL` | — | not split in 27.9; **leave empty**, ICE = `TOTAL − alt` residual (aggregate-ICE). Petrol/diesel split exists only in FZ 27.2/27.4 (per-Bundesland snapshot, awkward, not worth automating). |

**Two things this settles:**

1. **Germany becomes fully split** — the old `HYBRID` column held KBA's
   `PHEV(I)+HEV(J)` lumped together (verified: `2025` HYBRID 4,362,563 =
   1,122,958 + 3,239,605 at 01.01.2026). Harmonized, DE fills `PHEV` **and**
   `HEV` separately. No combined bucket needed.
2. **Year convention** — the maintainer labels **year `Y` = the `01.01.(Y+1)`
   snapshot** (stock at end of year `Y`): `DE 2025` BEV 2,034,260 = KBA
   `01.01.2026` col G exactly. Keep this convention (don't rewrite the past) and
   record the snapshot date in `notes`/`source`. *Open choice:* stay annual
   (Jan-1 snapshot per year) or exploit the quarterly depth — annual keeps DE
   consistent with the other 11 countries and the annual fleet model; recommended.

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
Germany currently has **no dedicated registration fetcher** (it rides ACEA) — a
native KBA API could upgrade that later.

### Cron — yes for Germany. Unlike the general "no cron" stance, Germany earns
one: a stable overview page, predictable quarterly `fz27_YYYYMM.xlsx` files, one
clean sheet, rich splits. Shape it like the existing `fetch-*.yml`:
`scripts/fetch_fleet_germany.py` scrapes `fz27_b_uebersicht.html` for the newest
`fz27_*.xlsx` (the `?v=N` version param rules out a hard-coded URL), parses
FZ 27.9, line-upserts the new snapshot into the fleet CSV; a self-throttling
monthly cron + `workflow_dispatch`. **No render dispatch** (fleet is computed in
the browser). This is the natural pilot for the whole fleet-fetch pattern.

---

## 5 · What to do next (in order)

1. **Sign off §2** (schema + adopting the doc-35 contract, dropping `HYBRID`).
2. **Migrate `fleet/fleet_initial.csv`** to the new schema: full names, `variant`,
   `source`, `TOTAL`, `HYBRID`→`HEV`+note, China `HYBRID`→`PHEV`. A one-shot
   rewrite is acceptable here (unlike `data/` line-upserts) because it's a schema
   migration, but preserve every historical value (invariant 3 — don't rewrite the
   past).
3. **Update `index.html:loadFleetObserved`** to read the new columns and the
   `hev_note`/collapse contract; delete the `hybrid > 100` heuristic; surface the
   combined-hybrid label per §2.2.
   **Don't break the tab: migrate data and parser in one change, or make the
   parser dual-read first.** The parser currently keys on `country` codes,
   `HYBRID`, and no `source`/`TOTAL`; renaming `NO→Norway` and dropping `HYBRID`
   *before* the parser handles it blanks the Fleet tab. Safe order: (a) teach the
   parser to accept **both** old and new schema (fall back `HYBRID`→`HEV`, code→
   name), (b) migrate the CSV, (c) remove the old-schema branch. Verify locally
   against the real downloaded files before pushing.
4. **Confirm the ⚠ verify sources** (one live call each) and write per-country
   fetch helpers `scripts/fetch_fleet_<country>.py` — **no cron**; run on demand /
   yearly with an agent. Line-upsert keyed on `(country, variant, year)`.
5. **Backfill `source` and flags** for the 12 existing countries from §4.

### When you change X, also update Y (fleet)

- **This schema / the contract** → `index.html:loadFleetObserved`, `03-data-objects.md`
  §3.8, and keep it consistent with the registration contract in `35-proposal-raw-data-tab.md` §2.
- **A fleet source's logic** → `scripts/fetch_fleet_<c>.py` **and** this §4 row
  **and** the country's `notes`/flags.
- **A new fleet country / variant** → this §4 table, `SD_COUNTRIES` variants in
  `index.html`, and `09-glossary.md` if the scope needs a note.

---

## 6 · Open verification points

- SSB 07849 fuel-leaf granularity (does it split plug-in/hybrid, or only "other"?).
- Denmark & Finland exact **stock** (not registration) table IDs.
- Canada: whether a stock-by-fuel cube exists, or fleet rows are estimates.
- Georgia: the actual publisher and its split capability.
- ~~KBA~~ — **resolved**: FZ 27.9 confirmed, mapping in §4b.
- ~~KBA ArcGIS Hub~~ — **resolved**: Hub has no national fuel×time series
  (only capped model-level + regional e-mobility); FZ 27.9 xlsx stays the source.

These are the only gaps between this spec and a mechanical yearly refresh.
