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
cadence: daily 15:45 UTC — AAP refreshes the report on no fixed day; a month is written once AAP has classified it
variants:
- Whole
- Vans
variant_notes:
  Whole: New cars, station wagons, SUVs and MPVs (AAP classes Automóvil, Station Wagon, SUV/Todoterreno and Camionetas with body Multipropósito) ≈ EU M1.
  Vans: New pickups, chassis-cabs, dropside and box vans (class Pick up y Furgonetas) and panel vans (Camionetas with body Panel) ≈ EU N1.
hev_split: true
hev_note: BEV, PHEV and HEV are AAP's own powertrain classes. HEV counts full AND mild hybrids — the registry lumped them together until 2024 and only codes mild hybrids separately since 2025, so for a consistent series they stay in HEV (the top-brands table does rank MHEV separately).
backfill: from 2019-01, the first month in the BI-AAP model; April 2020 has no registrations (COVID-19 lockdown)
scope_note: First registrations of new light vehicles in Peru. Minibuses (Camionetas with body Microbús, M2), ambulances and hearses, all heavy vehicles and motorcycles are in no variant.
caveats:
- BEV and PHEV shares are still very small (0.5 % and 0.8 % of new cars in 2025–26) — the fit sits at the very start of the S-curve and moves a lot with each new month.
- HEV includes mild hybrids (48 V Suzuki, Mercedes, BMW, Audi systems), about half of all hybrids in 2025.
- No registrations in April 2020 (the registry was closed during the COVID-19 lockdown); that month has no row and May 2020 is tiny.
- AAP reports these first registrations as new-vehicle sales. Used imports are legal only up to two model years old, so a small near-new remainder may be included; the data has no new/used flag.
- The newest month in BI-AAP is a preliminary load (incomplete, powertrain not yet classified); it is written only after AAP's next refresh classifies it, so Peru usually runs one to two months behind.
market_breakdown: market/peru_top.json
market_designation_note: a "designation" is SUNARP's model string with the brand prefix removed; a few Chinese imports are registered under a type-approval code (e.g. LZW7007EVD2MBMA) rather than a commercial name and rank under that code.
market_powertrain_note: BEV / PHEV / HEV are AAP's classes; HEV is split into HEV (full) and MHEV (mild) where the registry codes it, which covers the whole trailing year.
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
Timing:    AAP refreshes irregularly (last: 2026-09-02). The newest month is
           a preliminary, unclassified load; it becomes final at the next
           refresh. Polled daily.
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
AAP; AAP's printed report for January–March 2026 shows a slightly different
BEV/PHEV split (e.g. January: BEV 75 / PHEV 100 vs 84 / 84 here) with the same
total. From April 2026 the two agree exactly.

## 4. Variants

| Variant | Rule (group `LIVIANOS`) | EU anchor | 2025 |
|---|---|---|---|
| `Whole` | class `AUTOMOVIL`, `STATION WAGON`, `SUV,TODOTERRENOS`, or `CAMIONETAS` with body `MULTIPROPOSITO` | M1 | 136,531 (BEV 0.47 %, PHEV 0.35 %, HEV 6.4 %) |
| `Vans` | class `PICK UP Y FURGONETAS` (pickup, chassis-cab, dropside, box van, reefer), or `CAMIONETAS` with body `PANEL` | N1 | 40,345 (BEV 0.25 %, diesel 84 %) |

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

## 5. Governance — what every run checks

| Check | On failure |
|---|---|
| `Base` still has every column used (conceptual schema) | abort, nothing written |
| Every month query complete (the API's `IC` flag; ≤ 30,000 rows — a month is ~3,300) | abort |
| **Self-check:** detailed rows of each month = an independent `Grupo × Elect` aggregate query of the same month | abort (a decoding or truncation bug) |
| Month classified by AAP (no light vehicle with an empty `Elect`) | month not written (`::warning::`), retried next run |
| Unknown powertrain values ≤ 2 % of Whole | abort above; below → OTHERS, listed |
| Light-vehicle class/body in no variant (not on the excluded list) ≤ 1 % | abort above; listed in the step summary |
| Target Whole ≥ 40 % of the trailing-12 median | not written (`--force` overrides) |
| **Cross-check vs AAP's printed report** — new light + heavy vehicles per month, every month in its "Evolución mensual" table | ≤ 2 units or 0.5 % → reported; more → abort (`--force` overrides); report unreachable → warning |
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
    Py->>PBI: Grupo×Elect of the newest months → newest classified month
    Py->>CSV: that month already from BI-AAP in every CSV?
    alt yes
        Py-->>Cron: no-op (no month queries)
    else no
        Py->>PBI: 12 month queries (all since 2019-01 on backfill) + aggregate self-check
        Py->>AAP: newest monthly report PDF → cross-check light + heavy per month
        Py->>CSV: line-level upserts (changed lines only)
        Py->>Top: trailing-12-month top brands / models (if changed)
        Py-->>Cron: run report → step summary
        Cron->>Render: once, variants = touched of "Vans|Whole"
    end
```

- **Schedule:** `45 15 * * *` (daily, Lima 10:45). A no-op run makes six
  small requests (two pages, model, schema, one or two aggregate queries).
- **Normal run:** re-reads the newest 12 classified months (SUNARP corrects
  registrations late; the rows update in place) and rebuilds the top list.
- **Backfill / rebuild:** dispatch with `backfill = true` (90 month queries,
  about a minute).
- **Offline:** `--backfill --dump-json rows.json` saves the raw month rows;
  `--from-json rows.json [--report-pdf report.pdf]` rebuilds without network.
- **Render:** the fetch job dispatches `render-country.yml` once with the
  changed variants (`Vans|Whole`).
- **After each monthly run:** read the step summary — BEV/PHEV brands, unknown
  powertrain values, unexpected classes/bodies, the cross-check line.

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
| `No classified month found in BI-AAP` | no month in the last four is classified | check the report; AAP may have stopped filling `Elect` — then map `Comb` (the registry code) instead, with tests |
| `Cross-check against AAP's printed report failed` | BI-AAP and the report disagree beyond 2 units | compare the named months by hand (report page "Evolución mensual"). A report built from an older extract → wait for the next one or `force`; a scope change in `Grupo` → document it here |
| `AAP report cross-check unavailable` warning | the reports page or PDF layout changed | the data is still written; fix `latest_report_url()` / `report_table_from_pdf()` and `test_report_table` |
| `unknown powertrain values … schema drift` | a new `Elect` value (> 2 % of Whole) | map it in `FUEL_MAP` with a test |
| `light vehicles in a class/body no variant knows` | a new AAP class or body | decide M1 / N1 / excluded in `variant_for()` and the constants above it, with a test |
| commit step `non-fast-forward` | a concurrent commit | already rebased by the action; re-run |
