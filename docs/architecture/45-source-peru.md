---
country: Peru
slug: peru
method: api
summary: New-car and light-commercial registration data for Peru — every first registration
  with SUNARP, the national registry, as compiled by the Asociación Automotriz del Perú and
  published in its public BI-AAP report, with brand, model, body type and powertrain.
source_name: Asociación Automotriz del Perú (AAP) — BI-AAP (SUNARP first registrations)
source_url: https://aap.org.pe/estadisticas/biaap
source_links:
- label: BI-AAP public Power BI report
  url: https://aap.org.pe/estadisticas/biaap
  note: the page embeds the report; its public query API is what the fetcher reads (no login, no key)
- label: AAP «Informe del Sector Automotor» (monthly report, cross-check)
  url: https://aap.org.pe/estadisticas/informes-del-sector-automotor
  note: the "Evolución mensual" table of new light + heavy vehicles is compared with the data on every run
- label: SUNARP — Superintendencia Nacional de los Registros Públicos
  url: https://www.gob.pe/sunarp
  note: the registry that records every first registration (inmatriculación)
underlying: SUNARP vehicle register — first registrations (inmatriculaciones), compiled by AAP
auth: none
cadence: daily 15:45 UTC — AAP reloads the report on no fixed day; a month is written once it is before the reload month, classified by AAP and confirmed by AAP's printed monthly report
variants:
- Whole
- Vans
variant_notes:
  Whole: New cars, station wagons, SUVs and MPVs (AAP classes Automóvil, Station Wagon, SUV/Todoterreno and Camionetas with body Multipropósito) ≈ EU M1. Pickups are not in Whole — they are in Vans.
  Vans: New pickups, chassis-cabs, dropside and box vans (class Pick up y Furgonetas) and panel vans (Camionetas with body Panel) ≈ EU N1.
hev_split: true
hev_note: BEV, PHEV and HEV are AAP's own powertrain classes. HEV counts full AND mild hybrids — the registry lumped them together until 2024 and only codes mild hybrids separately since 2025, so for a consistent series they stay in HEV (the top-brands table does rank MHEV separately).
backfill: from 2019-01, the first month in the BI-AAP model; April 2020 has no registrations (COVID-19 lockdown)
scope_note: First registrations of new light vehicles in Peru. Minibuses (Camionetas with body Microbús, M2), ambulances and hearses, all heavy vehicles and motorcycles are in no variant.
caveats:
- BEV and PHEV shares are still very small (0.5 % and 0.8 % of new cars in 2025–26) — the fit sits at the very start of the S-curve and moves a lot with each new month.
- 'Pickups are counted in Vans, not in Whole (they are N1 goods vehicles), so AAP''s "livianos" figures are larger than Whole: July 2026 BEV = 65 in BI-AAP''s light vehicles = 57 Whole + 6 Vans (pickups, dropsides) + 2 minibuses (in no variant).'
- HEV includes mild hybrids (48 V Suzuki, Mercedes, BMW, Audi systems), about half of all hybrids in 2025.
- No registrations in April 2020 (the registry was closed during the COVID-19 lockdown); that month has no row and May 2020 is tiny.
- AAP reports these first registrations as new-vehicle sales. Used imports are legal only up to two model years old, so a small near-new remainder may be included; the data has no new/used flag.
- The newest month in BI-AAP is a preliminary cut (August 2026 stopped at the 22nd, powertrain not yet classified). A month is written only once AAP has classified it and its printed monthly report confirms the month's total, so Peru usually runs one to two months behind.
- AAP re-classifies the powertrain split of earlier months after the fact (up to about 25 plug-ins a month moved between PHEV, BEV and HEV, as far back as 2024); month totals do not change. Every update re-reads the whole history, so earlier rows can change slightly.
processing:
- title: Download
  text:
  - The fetcher queries the public BI-AAP report directly, one month at a time, grouped by vehicle group, class, body, powertrain, brand and model. Each month's detailed rows must add up to a separate total query of the same month, or the run stops. Every new reload of the report re-reads the whole history from 2019.
- title: Pick the vehicles
  text:
  - AAP sorts every first registration into a vehicle group and a class; the class Camionetas mixes people carriers and vans, so there the body type decides.
  decision:
    ask: AAP vehicle group?
    branches:
    - when: Livianos — light vehicles
      then:
        ask: Class (Clase)?
        branches:
        - when: Automóvil, Station Wagon, SUV / Todoterreno
          then: Whole
        - when: Pick up y Furgonetas — pickups, chassis-cabs, dropside and box vans
          then: Vans
        - when: Camionetas
          then:
            ask: Body (Carrocería)?
            branches:
            - when: Multipropósito (MPV)
              then: Whole
            - when: Panel (panel van)
              then: Vans
            - when: Microbús (minibus, EU M2), ambulance, hearse, motorhome
              then: in no variant
            - when: any other body
              then: in no variant
              note: listed in the run summary; above 1 % of the month's light vehicles the run stops
        - when: any other class
          then: in no variant
          note: listed in the run summary; above 1 % of the month's light vehicles the run stops
    - when: Pesados (trucks, tractors, buses), Menores (motorcycles, three-wheelers) or any other group
      then: in no variant
- title: Powertrain
  text:
  - The powertrain is AAP's own class (Elect) — the registry's fuel value, harmonised by AAP across SUNARP's coding change of 2025 and with the plug-ins split out of the old HIBRIDO code. The fetcher only maps it to columns.
  decision:
    ask: AAP powertrain class?
    branches:
    - when: BEV
      then: BEV
    - when: PHEV
      then: PHEV
    - when: HEV
      then: HEV
      note: full and mild hybrids — the registry coded them together until 2024, so mild hybrids stay in HEV for a consistent series
    - when: Gasolina
      then: PETROL
    - when: Diesel
      then: DIESEL
    - when: GNV, BI-GNV, DUAL GNV (natural gas)
      then: CNG
    - when: GLP, BI-GLP, DUAL GLP
      then: LPG
    - when: GNL, BI-GNL, DUAL GNL (liquefied gas) or "-" (not stated)
      then: OTHERS
    - when: empty — AAP has not classified the vehicle yet
      then: the month is not written (see below)
    - when: any other value
      then: OTHERS
      note: above 2 % of a month's Whole the run stops
- title: Month
  text:
  - AAP reloads the report on no fixed day, and the newest month of each reload is a preliminary cut. A month goes into the CSV only once it is provably complete; months already written are rewritten on every reload, because AAP re-classifies the powertrain split of earlier months.
  decision:
    ask: Is the month before the month of AAP's last reload?
    branches:
    - when: "no"
      then: not written yet
    - when: "yes"
      then:
        ask: Has AAP classified every light vehicle of the month?
        branches:
        - when: "no"
          then: not written yet
        - when: "yes"
          then:
            ask: Does AAP's printed monthly report list the month?
            branches:
            - when: yes, with the same total of new light and heavy vehicles
              then: written
              note: a month not in the CSV yet that falls below 40 % of the trailing twelve-month median is still held back
            - when: yes, but the totals differ by more than 2 vehicles and 0.5 %
              then: the run stops, nothing is written
            - when: not yet
              then: held back until the report has it
            - when: the report could not be read this run
              then: only months already in the CSV are rewritten
market_breakdown: market/peru_top.json
market_designation_note: a "designation" is SUNARP's model string with the brand prefix removed; a few Chinese imports are registered under a type-approval code (e.g. LZW7007EVD2MBMA) rather than a commercial name and rank under that code.
market_powertrain_note: BEV / PHEV / HEV / petrol / diesel are AAP's classes, as in the CSV; HEV is split into HEV (full) and MHEV (mild) where the registry codes it, which covers the whole trailing year.
fetcher: scripts/fetch_peru.py
workflow: .github/workflows/fetch-peru.yml
fragility_doc: docs/architecture/45-source-peru.md
data_file: data/Peru.csv
---

# 45 · Source: Peru (SUNARP first registrations via AAP's BI-AAP)

**Status: LIVE since 2026-09.** Fetcher `scripts/fetch_peru.py` (+ tests
`scripts/test_fetch_peru.py`) and `.github/workflows/fetch-peru.yml`.
Peru is the gallery's sixth South American market (after Argentina, Brazil,
Chile, Colombia and Uruguay), and its source is the national registry itself,
at brand × model × body × powertrain level, day by day.

## TL;DR

```
Source:    Asociación Automotriz del Perú (AAP), public Power BI report
           "BI-AAP" (aap.org.pe/estadisticas/biaap). Its table `Base` holds
           SUNARP first registrations: date × registry office × group /
           class / body × brand × model × fuel × AAP powertrain class × count.
Auth:      None. The public ("publish to web") Power BI API the embedded
           report itself calls — resource key from the embed URL.
API:       discover key (BI-AAP page) → cluster (embed page) → model id
           (modelsAndExploration) → schema check (conceptualschema) → one
           querydata call per month.
Timing:    Rows are per registration DAY, but AAP reloads irregularly (last:
           2026-09-02). Each reload's newest month is a preliminary cut
           (2026-08 ended on the 22nd), unclassified. Written only when
           before the reload month + classified + confirmed by AAP's printed
           report (§5a). Polled daily.
Revisions: the powertrain split of old months is re-classified at later
           reloads (totals never change) → every real run re-reads the whole
           history and lists the revised rows (§5a).
History:   2019-01 → today (90 months at 2026-07; April 2020 empty).
Fuel:      AAP's powertrain class: BEV / PHEV / HEV (full + mild) / petrol /
           diesel / CNG / LPG / other.
Variants:  Whole (M1) · Vans (N1).
Checked:   AAP's printed monthly report, new light + heavy vehicles per
           month: exact for all 90 months 2019-01 → 2026-07.
```

## 1. Why this source clears the bar

The gallery's rule ([14](14-data-source-gaps.md)): direct from the registry
or its recognised body, complete for the market, obtainable without paying or
handing over an ID.

- **Registry-based and complete.** Every vehicle sold in Peru is first
  registered ("inmatriculado") with SUNARP; AAP compiles those registrations,
  so every brand is in — BYD, Changan, Geely, Jetour and the long tail of
  Chinese importers included. This is exactly the completeness failure the
  gallery rejected Mexico for (INEGI omits BYD, [14](14-data-source-gaps.md)).
- **The recognised body.** AAP is Peru's national automotive association
  (OICA member) and the source every Peruvian market figure is quoted from.
- **Free, no account.** The report is public; the fetcher uses the same
  anonymous API the browser uses when anyone opens the page.

**Why Peru — and not Russia.** The session that added Peru was asked to add
Russia if possible. Russia's only monthly fuel-split data (Autostat, and the
Autostat Info reseller) is sold per report (3,000–10,000 ₽); the free part is
news prose with a monthly BEV total and a top-10 list — no fuel split of the
total market, no complete brand/model table. It fails the bar; details in
[33](33-expansion-candidates.md#investigated-2026-09--large-markets-still-missing).
Peru (≈ 187,000 new light vehicles in 2025, +40 % in 2026) was the best
source found instead.

## 2. Record → CSV row

AAP's `Base` table is not one row per vehicle but one row per (date, office,
group, class, subclass, segment, body, brand, luxury flag, model, fuel,
powertrain) with a count — record-level detail, aggregated only over
identical vehicles registered the same day. The fetcher queries it grouped by
the columns it needs, one month at a time:

| Column | Use |
|---|---|
| `Fecha` (registration date) | the month filter |
| `Grupo` | `LIVIANOS` (light) → the variants; `PESADOS`, `MENORES` → cross-check only |
| `Clase`, `Carroceria` | EU class (§4) |
| `Elect` | fuel column (§3) |
| `Comb` | the registry's own fuel code — top table only (MHEV) |
| `Marca`, `Modelo` | `market/peru_top.json` |
| `nTotal` | registrations |

CSV columns: `BEV, PHEV, HEV, PETROL, DIESEL, CNG, LPG, OTHERS, TOTAL`;
`source` = `SUNARP via AAP (BI-AAP)`. Line-level upserts (invariant 2); a row
whose `source` is not ours is never overwritten without `--force`.

**The API, step by step** (all in `class Api`):

1. `GET aap.org.pe/estadisticas/biaap` → the `app.powerbi.com/view?r=…` embed
   URL; `r` is base64 JSON `{"k": resource key, "t": tenant, "c": …}`.
2. `GET` the embed URL → `resolvedClusterUri`
   (`https://wabi-south-central-us-redirect.analysis.windows.net/`) → the API
   host is the same name with `-api` instead of `-redirect`.
3. `GET {host}/public/reports/{key}/modelsAndExploration` (header
   `X-PowerBI-ResourceKey: {key}`) → model id and `LastRefreshTime`.
4. `POST {host}/public/reports/conceptualschema` → the tables and columns;
   the run aborts if `Base` lacks a column the fetcher uses.
5. `POST {host}/public/reports/querydata?synchronous=true` with a semantic
   query (`Select` the dimensions + `Sum(nTotal)`, `Where` Fecha in the month)
   → a compressed "DSR" result that `decode_dsr()` expands (value
   dictionaries, repeat bits `R`, null bits `Ø`; tested with a real response).

Steps 1–2 fall back to constants in the script if the page cannot be read
(a `::warning::` says so); a changed key is reported as a `::notice::`.

## 3. Fuel mapping

AAP's `Elect` column is the powertrain class. It is the registry's fuel value
(`Comb`) harmonised across SUNARP's coding change of 2025 — before: `ELECTRICO`
/ `HIBRIDO`; since: `BEV` / `PHEV` / `HEV` / `MHEV` — with AAP's own plug-in
split of the old `HIBRIDO` code.

| `Elect` | Column |
|---|---|
| `BEV` | BEV |
| `PHEV` | PHEV |
| `HEV` | HEV (full **and** mild hybrids) |
| `GASOLINA` | PETROL |
| `DIESEL` | DIESEL |
| `GNV`, `BI-GNV`, `DUAL GNV` | CNG |
| `GLP`, `BI-GLP`, `DUAL GLP` | LPG |
| `GNL`, `BI-GNL`, `DUAL GNL` (LNG), `-` (not stated) | OTHERS |
| anything else | OTHERS, listed in the report; > 2 % of Whole aborts |

**Mild hybrids.** Until 2024 the registry's `HIBRIDO` held full and mild
hybrids together — Suzuki's 48 V models, Mercedes, Audi and BMW mild hybrids
all sit in it — and AAP's `Elect` keeps both in `HEV` throughout. Splitting
them only from 2025 would put a step into the HEV series (invariant 3 spirit),
so the CSV has no MHEV column; the three-curve chart is unaffected (HEV counts
as ICE there). The top-brands table does rank `MHEV` separately, from `Comb`,
because its trailing year lies entirely after 2025-01.

**Known source quirks** (kept, not corrected — the source's classification is
the rule): a handful of early-2026 records coded `ELECTRICO` are BYD DM-i
plug-ins under their type codes (`BYD6472ST6HEV2`) and are counted as BEV by
AAP. AAP's printed reports show a somewhat different BEV/PHEV/HEV split
for many months of 2024–2026 with the same totals — BI-AAP is re-classified
after printing; see §5a.

## 4. Variants

| Variant | Rule (group `LIVIANOS`) | EU anchor | 2025 |
|---|---|---|---|
| `Whole` | class `AUTOMOVIL`, `STATION WAGON`, `SUV,TODOTERRENOS`, or `CAMIONETAS` with body `MULTIPROPOSITO` | M1 | 136,531 (BEV 0.47 %, PHEV 0.35 %, HEV 6.4 %) |
| `Vans` | class `PICK UP Y FURGONETAS` (pickup, chassis-cab, dropside, box van, reefer), or `CAMIONETAS` with body `PANEL` | N1 | 40,345 (BEV 0.25 %, diesel 84 %) |

**Pickups are in `Vans`, not in `Whole`.** Peru's pickups (Toyota Hilux, Ford
Ranger, Great Wall Poer, …) are registered as goods vehicles, so they follow
the EU N1 anchor into `Vans`. This differs from countries whose headline
series bundles them (Thailand's "Passenger Car and Pickup Truck") and from
those that split them into their own variant (Argentina, Canada, Indonesia
`Pickups`). Reconciling with BI-AAP's "LIVIANOS" view, July 2026 BEV: 65
there = 57 `Whole` (SUV 42, Automóvil 15) + 6 `Vans` (pickups, dropsides —
Qingling, Farizon, JAC) + 2 minibuses (Dongfeng, in no variant). The
top-brands table is `Whole` only, so pickup brands such as Qingling do not
appear in it.

AAP's class `CAMIONETAS` is a mixed bag: MPVs (Toyota Avanza, Mitsubishi
Xpander, Suzuki Ertiga — M1), minibuses (Toyota Hiace commuter, Changan Grand
Van Turismo registered as `MICROBUS` — M2) and panel vans (N1). The body type
separates them. **Not produced:** `MICROBUS` bodies (≈ 10,000 a year, M2 —
the gallery's `Buses` is M2+M3, but with the heavy buses in `PESADOS` it would
be a thin, near-zero-EV series), ambulances, hearses and motorhomes; all
`PESADOS` (trucks, tractors, buses — ≈ 25,000 a year, a few dozen BEVs); all
`MENORES` (motorcycles and three-wheelers, from 2022 — their fuel is not
recorded). Each is one filter away in `variant_for()`.

**New vs used.** The table has no new/used flag. AAP reports first
registrations as new-vehicle sales; Peruvian law admits used imports only up
to two model years old (D.L. 843) and bans used diesel light vehicles
(D.S. 005-2020-MTC), so the remainder is small and near-new.

## 5a. When is a month final — and how often are old months revised?

The table's rows are dated by **registration day**, but the report is not
live: AAP reloads the model on no fixed day (the reload in use on 2026-09-28
was from 2026-09-02). What a reload holds for its newest month is a cut, not a
month:

| Month (reload of 2026-09-02) | Last day with data | Light vehicles | Powertrain class | Printed report (light + heavy) |
|---|---|---|---|---|
| 2026-07 | 31st | 18,864 | filled | 21,767 = BI-AAP |
| 2026-08 | **22nd** (145 that day, ≈ 1,100 a normal day) | 16,412 | **empty** | 26,328 vs 18,421 in BI-AAP |

A fetch on the 2nd or 3rd therefore must never turn the current or the
preliminary month into a data point. **A month is written only when all three
hold** (`main()` steps 1–3 and the `writable` filter):

1. it is **strictly before the month of the model's last reload** — a reload
   on 2 October can never yield "October";
2. **AAP has classified it** — no light vehicle with an empty `Elect`;
3. **AAP's printed monthly report has it and the month's total agrees**
   (new light + heavy vehicles, ±2 units / 0.5 %).

Rule 3 is the proof of completeness, and it works because the printed totals
are **never revised**: the "Evolución mensual" tables of five editions
(March → August 2026 reports, 111–116 months each) are identical month for
month. A month that passes 1–2 but is not in the report yet is **held back**
(`::notice::`, step summary) and written on the first run after the report
appears. Without a reachable report no new month is written at all, only
revisions of months already in the CSVs. A new month below 40 % of the
trailing median is held back as well (a second guard, never needed so far).

**Revisions exist, and they are powertrain re-classifications, not new
registrations.** Comparing BI-AAP (reload of 2026-09-02) with the electrified
table of the printed reports (which, once printed, also never changes — one
BEV moved once in five editions), 20 of 31 months from 2024-01 to 2026-07
differ, with identical month totals:

| Month | Printed (BEV / PHEV / HEV, light + heavy) | BI-AAP now | |
|---|---|---|---|
| 2024-10 | 38 / 28 / 473 | 38 / 23 / 466 | 12 electrified → combustion |
| 2025-08 | 73 / 69 / 844 | 78 / 45 / 863 | 24 PHEV → BEV / HEV |
| 2025-10 | 48 / 81 / 780 | 55 / 64 / 790 | 17 PHEV → BEV / HEV |
| 2026-01 | 75 / 100 / 999 | 84 / 84 / 1,006 | |
| 2026-03 | 67 / 93 / 1,039 | 80 / 69 / 1,050 | |
| 2026-04 → 07 | = | = | (one BEV in 2026-05) |

So AAP keeps re-classifying months after it prints them, reaching back two
years and more — since 2025 BI-AAP's class simply equals the registry's own
fuel code (`Comb`), which suggests the registry records get corrected. The
fetcher follows BI-AAP (the live source) and is built for it:

- **every real run re-reads the whole history** (≈ 90 small queries, about a
  minute), not a recent window;
- **every new reload triggers a real run** — the reload stamp processed last
  is stored as `source_refreshed` in `market/peru_top.json`, and the
  self-throttle only skips when the CSVs hold the newest classified month
  *and* the stamp is unchanged;
- changed rows are upserted in place (invariant 2 — only those lines) and
  **listed in the step summary** under "Earlier months revised in this run",
  one line per row in the form `<month> <variant>: <column> old→new, …`, with
  a `::notice::`.

Invariant 3 ("don't rewrite the past") is about *definition* changes; these
are the source correcting its own records under an unchanged definition, which
the series should follow — like the Netherlands' or Spain's registry fetchers.

## 5. Governance — what every run checks

| Check | On failure |
|---|---|
| `Base` still has every column used (conceptual schema) | abort, nothing written |
| Every month query complete (the API's `IC` flag; ≤ 30,000 rows — a month is ~3,300) | abort |
| **Self-check:** detailed rows of each month = an independent `Grupo × Elect` aggregate query of the same month | abort (a decoding or truncation bug) |
| Month strictly before the reload month | never a candidate |
| Month classified by AAP (no light vehicle with an empty `Elect`) | month not written (`::warning::`), retried next run |
| **Month confirmed by AAP's printed report** (in its table, total agrees) | held back (`::notice::`), written once the report has it; no report reachable → no new month, revisions only |
| Unknown powertrain values ≤ 2 % of Whole | abort above; below → OTHERS, listed |
| Light-vehicle class/body in no variant (not on the excluded list) ≤ 1 % | abort above; listed in the step summary |
| A new month's Whole ≥ 40 % of the trailing-12 median | held back (`::warning::`; `--force` overrides) |
| **Cross-check vs AAP's printed report** — new light + heavy vehicles per month, every month in its "Evolución mensual" table | ≤ 2 units or 0.5 % → reported; more → abort (`--force` overrides); report unreachable → warning |
| Revised earlier rows | applied, listed in the step summary + `::notice::` |
| Fuels sum to TOTAL, every row | abort |
| Fetcher + `market_top` regression tests (`test_fetch_peru.py`) | the workflow stops before fetching |

## 6. Validation

**Against AAP's printed report** (`informe-del-sector-automotor-agosto.pdf`,
September 2026 edition): new light + heavy vehicles, all 90 months
2019-01 → 2026-07 — **exact match**, every month. The report is built from the
same SUNARP extract, so this checks the fetch (discovery, query, decoding,
scope of the group filter) rather than the registry itself; the registry is
the primary source and has no independent twin.

**Sandbox = runner = offline.** The backfill was run three ways on
2026-09-28: against the live API from the dev sandbox (which, unlike for most
sources, reaches both `aap.org.pe` and the Power BI API), on a GitHub runner
through a temporary probe workflow (since removed), and offline from the saved
rows (`--from-json`). All three produced byte-identical CSVs and
`market/peru_top.json`, and a second, non-backfill run on the runner was a
no-op.

**Plausibility.** New light vehicles 2025 (group `LIVIANOS`): 186,981;
Whole + Vans = 176,876, the rest (≈ 10,100) minibuses and special bodies. The 2026 boom (+40 % year on year)
is in AAP's report too. BEV share of new cars 0.01 % (2019) → 0.14 % (2023) →
0.47 % (2025); PHEV 0.35 % (2025) → 0.8 % (Jan–Jul 2026); HEV incl. mild
0.3 % → 6.4 % → 7.5 %. Top BEVs in the year to July 2026: Volvo EX30, BYD
Yuan Up, BYD Seagull, Changan Deepal; top PHEVs BYD Song Plus DM-i, Volvo
XC60, Geely EX5 EM-i.

## 6a. Reading the fit

Peru is at the very start of the curve: under 1 % BEV, with hybrids (mostly
Toyota's Corolla Cross and Yaris Cross, plus Suzuki's mild hybrids) doing the
electrification so far. A Weibull fit on shares this small is dominated by the
last few months and will swing as each new month lands; read the level, not
the crossing years. Two things move the denominator: the COVID-19 gap
(April 2020 no row, May 2020 ≈ 300 cars) and the 2026 market boom
(≈ 15,000–17,000 new cars a month against ≈ 11,000 in 2025).

**How Peru shows in the gallery (until BEV passes 1 %).** At 0.46 % BEV in
the trailing twelve months, Peru falls under the gallery's *no transition*
rule (`rowHasNoTransition`: under 1 % BEV), whatever the fitted curve says —
and that is shown, not hidden: the *No transition* pill on its cards, *shows
no transition* in Thresholds and Durations, dark grey on the World Map (Cars
and Vans) listed with its observed share. Its fit is not collapsed, so it is
not treated like Argentina (whose collapsed fit is kept out on purpose).
Checked in a headless browser with the backtest fit of 2026-07. Once the
trailing share passes 1 % (5 % at the latest) the label goes away by itself.

## 7. Outputs

- `data/Peru.csv`, `data/Peru_Vans.csv` (monthly, 2019-01 →).
- `market/peru_top.json` — trailing-12-month top brands and models per class
  (BEV, PHEV, HEV, MHEV) for Whole, plus one ranking per month, via
  `scripts/market_top.py`. Display names only: registry spellings of one brand
  merged (`BIYADI` → BYD, `CHANA` → CHANGAN, `WULING BAOJUN` → BAOJUN,
  `MERCEDES BENZ` → MERCEDES-BENZ, …) and the brand prefix stripped from the
  model (`BYD SEAGULL` → SEAGULL). The data CSVs never use these names.

## 8. Operations and debugging

```mermaid
sequenceDiagram
    participant Cron as fetch-peru.yml (cron / dispatch)
    participant Test as test_fetch_peru.py
    participant Py as fetch_peru.py
    participant AAP as aap.org.pe (BI-AAP page, reports)
    participant PBI as Power BI public API
    participant CSV as data/Peru*.csv
    participant Top as market/peru_top.json
    participant Render as render-country.yml
    Cron->>Test: scope + mapping + DSR decoder + report parser + upsert (gate)
    Cron->>Py: run
    Py->>AAP: BI-AAP page → resource key; embed page → API host
    Py->>PBI: model + refresh stamp; schema check
    Py->>PBI: Grupo×Elect of the months before the reload month → newest classified month
    Py->>CSV: that month in every CSV AND this reload stamp already processed (Top)?
    alt yes
        Py-->>Cron: no-op (no month queries)
    else no
        Py->>AAP: newest monthly report PDF → confirmed months (printed totals)
        opt same reload, newest classified month not printed yet
            Py-->>Cron: waiting — no month queries
        end
        Py->>PBI: every month since 2019-01 + aggregate self-check
        Py->>Py: cross-check totals vs report; writable = classified ∧ confirmed
        Py->>CSV: line-level upserts (new months + revised rows)
        Py->>Top: trailing-12-month top brands / models + reload stamp
        Py-->>Cron: run report → step summary
        Cron->>Render: once, variants = touched of "Vans|Whole"
    end
```

- **Schedule:** `45 15 * * *` (daily, Lima 10:45). A no-op run makes six
  small requests (two pages, model, schema, one or two aggregate queries); a
  "waiting for the report" run also downloads the report PDF (~6 MB).
- **Real run** (after each AAP reload, and when a held month's report
  appears): re-reads every month since 2019-01 (≈ 90 queries, about a minute),
  writes new confirmed months and revised rows, rebuilds the top list and
  stores the reload stamp.
- **Backfill / rebuild:** dispatch with `backfill = true` — the same run,
  forced past the self-throttle.
- **Offline:** `--backfill --dump-json rows.json` saves the raw month rows;
  `--from-json rows.json [--report-pdf report.pdf]` rebuilds without network.
- **Render:** the fetch job dispatches `render-country.yml` once with the
  changed variants (`Vans|Whole`).
- **After each monthly run:** read the step summary — BEV/PHEV brands, unknown
  powertrain values, unexpected classes/bodies, the cross-check line, the
  revised rows and the months held back.

**If a run fails — where to look:**

| Symptom in the log | Cause | Fix |
|---|---|---|
| `::warning title=BI-AAP discovery failed, using fallback` | the BI-AAP page moved or no longer embeds `app.powerbi.com/view?r=` | open the page; if the report moved, update `BIAAP_PAGE` / the regex in `Api.discover()`; the fallback key keeps working until AAP republishes |
| `::notice title=BI-AAP report key changed` | AAP republished the report | update `FALLBACK_RESOURCE_KEY` (the run itself already used the new key) |
| HTTP 401/404 on `modelsAndExploration` | a stale key with the fallback (page unreachable), or AAP unpublished the report | check the page in a browser; if the report is gone, the source is gone — record it in [14](14-data-source-gaps.md) |
| `schema drift: table 'Base' lacks [...]` | AAP renamed a column or table | read the new names from `conceptualschema` (the script prints what is there); map them in `DIMS` / `ENTITY` |
| `query result incomplete` | a month exceeded 30,000 grouped rows | group by fewer columns or split the month in two date ranges in `build_query()` |
| `detailed rows disagree with the month aggregate` | a DSR decoding bug (new compression feature) or a model refresh between the two queries | re-run; if it persists, dump the raw `querydata` response and extend `decode_dsr()` + its test |
| `Unclassified months skipped` warning | the newest month is a preliminary load | nothing — written after AAP's next refresh |
| `Months held back` notice / `waiting — nothing to do` | a classified month not yet in AAP's printed report | nothing — written on the first run after the report appears (usually 1–3 weeks) |
| `Earlier months revised by BI-AAP` notice | AAP re-classified old months at its reload (§5a) | expected; skim the listed rows — a sudden large move (hundreds of units, or a TOTAL change) is worth a look |
| `No classified month found in BI-AAP` | no month in the last four is classified | check the report; AAP may have stopped filling `Elect` — then map `Comb` (the registry code) instead, with tests |
| `Cross-check against AAP's printed report failed` | BI-AAP and the report disagree beyond 2 units | compare the named months by hand (report page "Evolución mensual"). A report built from an older extract → wait for the next one or `force`; a scope change in `Grupo` → document it here |
| `AAP report unavailable` warning | the reports page or PDF layout changed | revisions are still written but **no new month** until it is fixed: fix `latest_report_url()` / `report_table_from_pdf()` and `test_report_table` (or dispatch with `force` for one month, after checking it by hand) |
| `unknown powertrain values … schema drift` | a new `Elect` value (> 2 % of Whole) | map it in `FUEL_MAP` with a test |
| `light vehicles in a class/body no variant knows` | a new AAP class or body | decide M1 / N1 / excluded in `variant_for()` and the constants above it, with a test |
| commit step `non-fast-forward` | a concurrent commit | already rebased by the action; re-run |
