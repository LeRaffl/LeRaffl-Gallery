---
country: Estonia
slug: estonia
method: file
summary: First registrations in Estonia straight from Transpordiamet, the Transport
  Administration that keeps the traffic register — one workbook a month with every new
  vehicle, its EU category and its EU hybrid type, so BEV, PHEV and HEV are counted, not
  estimated. New cars (Whole), private and company buyers, used imports, vans, lorries and
  buses, about three weeks before ACEA publishes the month.
source_name: Transpordiamet — monthly first-registration statistics (Infoleht), from the traffic register
source_url: https://www.transpordiamet.ee/soidukitega-tehtud-toimingute-statistika
source_links:
- label: Transpordiamet — statistics of vehicle operations (the monthly Infoleht workbooks)
  url: https://www.transpordiamet.ee/soidukitega-tehtud-toimingute-statistika
  note: one XLS/XLSX per month back to 2006, "Infoleht MM-YYYY (esmaste ja uute sõidukite statistika)"; the sheets read are "Uued sõidukid" (every new vehicle, with the EU hybrid type from 2021), "Kytus_esm ( sh uued)" (first registrations by category and engine type) and "Esm(üldtabel)" (the month's headline totals)
- label: ACEA — monthly new-car registrations
  url: https://www.acea.auto/
  note: the Whole history before 2021 and the fallback for a month whose workbook is late
underlying: Estonian traffic register (liiklusregister), kept by Transpordiamet (Estonian Transport Administration)
auth: none
cadence: twice daily (07:05 and 13:05 UTC) on the 1st–15th; the month's workbook is posted in the first days of the next month and never restated
variants:
- Whole
- Private
- Industry
- Used
- Vans
- HDV
- Buses
variant_notes:
  Whole: New passenger cars — EU M1 incl. off-road M1G, from the register's list of new vehicles. Transpordiamet from 2021-01, ACEA before (quarterly until 2021).
  Private: New passenger cars registered to a private person (owner type FÜÜSILINE). From 2021-01. Private + Industry = Whole.
  Industry: New passenger cars registered to anyone else — legal persons (incl. leasing and rental), the state, foreign owners, companies being founded. From 2021-01.
  Used: Used passenger cars imported into Estonia (M1 incl. M1G), dated by the month of their first Estonian registration — all first registrations minus the new ones. From 2021-01. One combined hybrid number (in HEV, no PHEV column).
  Vans: New light commercial vehicles — EU N1 incl. N1G. From 2021-01 (quarterly ACEA before, kept in data/Estonia_legacy.csv).
  HDV: New lorries and tractor units — EU N2 + N3 incl. G. From 2021-01 (quarterly ACEA before, kept in data/Estonia_legacy.csv).
  Buses: New buses and coaches — EU M2 + M3 incl. G. From 2021-01 (quarterly ACEA before, kept in data/Estonia_legacy.csv).
hev_split: true
hev_note: PHEV and HEV come from the register's EU hybrid type of each new vehicle (certificate of conformity field 23.1) — OVC-HEV (externally chargeable) is PHEV, NOVC-HEV (not externally chargeable — full and mild hybrids) is HEV, as at ACEA. Fuel-cell vehicles (OVC/NOVC-FCHV) are OTHERS. A handful of hybrids a year have no hybrid type recorded; they are counted as HEV. Used imports carry engine types only, so their hybrids stay one combined number in HEV (no PHEV column; the chart draws no PHEV curve) — the Lithuania / Türkiye convention.
backfill: Whole is ACEA to 2020-12 (quarterly) and Transpordiamet from 2021-01 — the first workbook with the EU hybrid type. Private, Industry, Used, Vans, HDV and Buses from 2021-01; the quarterly ACEA rows of Vans/HDV/Buses are kept in data/Estonia_legacy.csv.
scope_note: Vehicles first registered in Estonia in the month — new ones from the register's list of new vehicles, used imports as the difference between all first registrations and the new ones. Vehicles deregistered since are still counted in the month they were registered.
caveats:
- 'Whole runs about 0.6% above ACEA''s Estonian figure (2022–2026), almost all of it in HEV and petrol; BEV and PHEV agree to within a few cars a month. December 2024 — the rush before the 2025 car tax — is 151 cars (4%) above ACEA. In January 2025 ACEA''s BEV figure includes 25 fuel-cell cars that this source counts as OTHERS.'
- 'Bi-fuel cars with a petrol engine and an LPG or CNG kit count as PETROL — the register''s engine type decides, which is also how ACEA''s figure (the legacy series) counts them. Cars with a dedicated CNG engine are OTHERS.'
- 'Used: hybrids are one combined number (HEV column, PHEV absent) — the first-registration sheet has engine types only, no hybrid type. Used imports are a market of their own: 11–12% of them were BEV in 2025–2026, more than among new cars.'
- 'Buses: a few to about 70 vehicles a month, so single fleet deliveries (electric city buses in 2024-05 and 2026-06/07) swing the shares.'
- 'The step at 2021-01 is a change of source, not of definition: ACEA''s Estonian figures are the same register (2021 quarters: within 3%, BEV and PHEV within a few cars), but they were quarterly before 2022.'
processing:
- title: Download
  text:
  - The fetcher reads Transpordiamet's statistics page, finds the month's "Infoleht" workbook by its link text and downloads it (0.5–1.5 MB, XLS until 2025-11, XLSX since). A run whose target month is already in every CSV makes no request at all. The workbook is never restated, so each month is read once.
- title: Pick the vehicles
  text:
  - The "Uued sõidukid" sheet lists every new vehicle of the month, grouped into rows of identical vehicles with a count. Its EU category decides the variant; the owner type splits new cars into Private and Industry. Used imports are not in this sheet — they are all first registrations of passenger cars minus the new ones, from the "Kytus_esm" sheet.
  decision:
    ask: EU vehicle category?
    branches:
    - when: M1 or M1G (passenger car)
      then:
        ask: New, or first registered abroad before?
        branches:
        - when: new — in the list of new vehicles
          then:
            ask: Owner type?
            branches:
            - when: FÜÜSILINE — a private person
              then: Whole + Private
            - when: JURIIDILINE, RIIGI, VÄLIS, ASUTAMISEL — legal person, state, foreign, company being founded
              then: Whole + Industry
        - when: used import — first registrations minus new, by engine type
          then: Used
    - when: N1 or N1G (van)
      then: Vans
    - when: N2, N3 (incl. G) (lorry, tractor unit)
      then: HDV
    - when: M2, M3 (incl. G) (bus, coach)
      then: Buses
    - when: anything else — motorcycles, mopeds, trailers, tractors, machines
      then: in no variant
- title: Powertrain
  text:
  - New vehicles carry the engine type (Mootori tüüp) and, from 2021, the EU hybrid type (Hübriidi tüüp, certificate of conformity field 23.1). The hybrid type decides first; the engine type decides the rest. Used imports have the engine type only.
  decision:
    ask: EU hybrid type, then engine type?
    branches:
    - when: OVC-FCHV / NOVC-FCHV or engine VESINIK (fuel cell, hydrogen)
      then: OTHERS
    - when: OVC-HEV (externally chargeable)
      then: PHEV
      note: new vehicles only; a used import's hybrid is one combined HEV
    - when: NOVC-HEV (full or mild hybrid)
      then: HEV
    - when: engine ELEKTER
      then: BEV
    - when: engine BENSIIN_HYBRIID / DIISEL_HYBRIID without a hybrid type
      then: HEV
      note: a few new cars a year; every used hybrid
    - when: engine BENSIIN, BENSIIN_KATALYSAATOR (incl. LPG / CNG bi-fuel kits)
      then: PETROL
    - when: engine DIISEL
      then: DIESEL
    - when: anything else — dedicated CNG or gas engine
      then: OTHERS
- title: Checks before writing
  text:
  - The workbook checks itself. New passenger cars counted from "Uued sõidukid" must equal the headline table's "sh uued" (of which new) passenger cars, and so must the "Kytus_esm" sheet's; all first registrations of passenger cars must equal its "Kokku"; new vans + lorries and new buses must equal their headline columns. A difference above 0.5% (and 3 vehicles) stops the run. Unknown engine, hybrid or owner values may not exceed 2% of a month, and a month below a quarter of the usual volume is not written. 69 of 69 months 2021-01 … 2026-09 pass; 68 match exactly, one (2024-07) by one car.
market_breakdown: market/estonia_top.json
market_designation_note: brand and model as the register writes them in the list of new vehicles (Mark, Mudel), upper-cased; "VOLKSWAGEN, VW" is shown as VOLKSWAGEN. The model is the register's model name — body and trim variants of one model stay separate where the register names them separately (BZ4X and BZ4X TOURING).
market_powertrain_note: the same classes as the Whole CSV — BEV, PHEV (OVC-HEV), HEV (NOVC-HEV), PETROL and DIESEL — counted per vehicle from the same sheet, so the tables add up to the chart's monthly figures exactly.
fetcher: scripts/fetch_estonia.py
workflow: .github/workflows/fetch-estonia.yml
fragility_doc: docs/architecture/57-source-estonia.md
data_file: data/Estonia.csv
---

# 57 · Source: Estonia (Transpordiamet)

**Status: LIVE since 2026-10.** Fetcher `scripts/fetch_estonia.py` (+ tests
`scripts/test_fetch_estonia.py`), workflow `.github/workflows/fetch-estonia.yml`.
Transpordiamet writes all seven Estonia CSVs from 2021-01. ACEA (`fetch_acea.py`) moved
Estonia from its always-list to the conditional list and only fills a Whole month the
workbook has not delivered yet; `fetch_acea_cv.py` no longer writes Estonia.

## TL;DR

```
Source:    transpordiamet.ee/soidukitega-tehtud-toimingute-statistika
             Infoleht MM-YYYY (esmaste ja uute sõidukite statistika).xls[x]
               "Uued sõidukid"      every new vehicle: category, make, model, engine
                                    type, EU hybrid type, owner type, count
               "Kytus_esm (sh uued)" first registrations / of which new,
                                    by category × engine type (→ Used)
               "Esm(üldtabel)"      headline totals (cross-check)
Auth:      None.
Timing:    the month's workbook is up in the first days of the next month
           (September 2026 was posted in early October); ACEA publishes ~20th.
Variants:  Whole · Private · Industry · Used · Vans · HDV · Buses (all monthly).
Split:     counted per vehicle: OVC-HEV → PHEV, NOVC-HEV → HEV (§3).
           Used: one combined hybrid number in HEV, no PHEV column.
Check:     every month against the workbook's headline table — 69/69 pass,
           68 exact (§4.1). vs ACEA 2022-01..2026-08: +0.6% total,
           BEV/PHEV within a few cars a month (§4.2).
```

## 1. Why this source clears the bar

Estonia was an ACEA "always" country, and a poor one: quarterly figures until 2021, monthly
from 2022, three weeks after month end, with commercial vehicles only as reconstructed
quarters and BEV + PHEV merged. The country stub in `country_source_stubs.yaml` and the
2026-10 register round of [33](33-expansion-candidates.md) recorded the Transpordiamet
workbook as "the best lead left among the ACEA countries".

Transpordiamet keeps the register ACEA's Estonian figure is built from, so the new series
reproduces ACEA's (§4.2) — a new source extends the legacy series in the same categories.
It is free, needs no login, is machine-readable and is reachable from GitHub's runners and
from the dev sandbox. What it adds:

* a **counted** PHEV/HEV split per vehicle (the EU hybrid type), not a derived one;
* **monthly** history from 2021 (ACEA was quarterly until 2021);
* **Private / Industry** (owner type) and **Used** imports — 14,335 used against 14,823
  new cars in January–September 2026;
* **Vans, HDV and Buses** monthly with a full fuel split, instead of ACEA's quarterly
  reconstructions with BEV and PHEV merged;
* brand and model per vehicle (`market/estonia_top.json`).

## 2. Record → CSV row

### 2.1 Workbook layouts

One workbook per month, never restated. The sheets keep their names; the columns of
"Uued sõidukid" moved over the years, so `parse_new()` finds them by header name:

| Workbooks | Engine type | Hybrid type | Owner type | Count |
|---|---|---|---|---|
| 2021-01 … 2024-05, 2024-09 … 2025-11 (XLS) | `Mootori tüüp` | `Hübriidi tüüp` | `Tüüp` / `Tüüp (isik)` | `Arv` |
| 2024-06 … 2024-08 (XLSX) | `MOOTORI_TYYP` | `HYBRIIDI_TYYP` | `V.KAS/OM TYYP` | `tk` |
| 2025-12 … (XLSX) | `Mootori tüüp` | `Hübriidi tüüp` | `Tüüp (isik)` | `Arv` |

The owner type is always the column just before the count (the word "Tüüp" alone means the
vehicle type in newer files, the owner type in 2021). Engine types are spelled
`BENSIIN HÜBRIID` / `BENSIIN KAT` in 2021 and `BENSIIN_HYBRIID` /
`BENSIIN_KATALYSAATOR` later; owner types `FÜÜSILINE` and (2024-06 … 08) `FYYSILINE` —
`engine_code()` and `owner_code()` fold both. Workbooks before 2021 have no hybrid type
column (and earlier ones other layouts), which is why the source starts at 2021-01.

### 2.2 Variants

| Variant | File | From | Filter |
|---|---|---|---|
| `Whole` | `data/Estonia.csv` | "Uued sõidukid" | category M1, M1G |
| `Private` | `data/Estonia_Private.csv` | same | … owner type FÜÜSILINE |
| `Industry` | `data/Estonia_Industry.csv` | same | … any other owner type (JURIIDILINE, RIIGI, VÄLIS, ASUTAMISEL) |
| `Used` | `data/Estonia_Used.csv` | "Kytus_esm" | M1, M1G: first registrations − of which new, per engine type |
| `Vans` | `data/Estonia_Vans.csv` | "Uued sõidukid" | N1, N1G |
| `HDV` | `data/Estonia_HDV.csv` | same | N2, N2G, N3, N3G |
| `Buses` | `data/Estonia_Buses.csv` | same | M2, M2G, M3, M3G |

M1G (off-road M1) is part of ACEA's passenger-car figure, which is why the totals match.
Motorcycles, mopeds, trailers, tractors and machines (L, O, T, LM, MS categories) are in no
variant.

## 3. Powertrain mapping

`fuel_class(engine, hybrid)`, first match wins:

| Hybrid type / engine type | Column |
|---|---|
| hybrid type `OVC_FCHV`, `NOVC_FCHV`, or engine `VESINIK` | OTHERS (fuel cell) |
| hybrid type `OVC_HEV` | PHEV |
| hybrid type `NOVC_HEV` | HEV (full and mild) |
| engine `ELEKTER` | BEV |
| engine `*_HYBRIID`, no hybrid type | HEV — a few new cars a year (listed in the log); every used hybrid |
| engine `BENSIIN`, `BENSIIN_KATALYSAATOR` | PETROL — incl. petrol engines with an LPG / CNG kit |
| engine `DIISEL` | DIESEL |
| anything else (`CNG`, `GAAS`, …) | OTHERS |

Bi-fuel cars go by their engine type, not by the fuel combination column
(`Kütusekombinatsioon`, e.g. `BENSIIN-LPG`): ACEA's Estonian figure counts them as petrol
(its OTHERS is 0 from 2025), and the Used sheet has only the engine type, so one rule
serves every variant. Unknown engine, hybrid or owner values are listed as a warning and
stop the run above 2% of a month (`KNOWN_ENGINES`, `KNOWN_HYBRID`, `KNOWN_OWNER`).

## 4. Validation

### 4.1 Against the workbook's own totals (every run)

| Check | Result 2021-01 … 2026-09 |
|---|---|
| new M1+M1G ("Uued sõidukid") = headline "sh uued" passenger cars | 68 exact, 2024-07 one car short (1,882 vs 1,883) |
| new M1+M1G ("Kytus_esm") = headline "sh uued" passenger cars | 69 exact |
| first-registered M1+M1G ("Kytus_esm") = headline "Kokku" passenger cars | 69 exact |
| new N1–N3 = headline "sh uued" lorries; new M2+M3 = buses | 69 exact |

### 4.2 Against ACEA (the legacy series)

Whole, Transpordiamet minus the ACEA row it replaced (ACEA monthly from 2022):

| Year | Total | BEV | PHEV | HEV | Petrol | Diesel | Others |
|---|---|---|---|---|---|---|---|
| 2022 | +94 (+0.5%) | −20 | −27 | +109 | +48 | −19 | +4 |
| 2023 | +171 (+0.8%) | +2 | −4 | +70 | +69 | +33 | +1 |
| 2024 | +359 (+1.4%) | −2 | 0 | +180 | +89 | +87 | +5 |
| 2025 | +72 (+0.6%) | −21 | 0 | +18 | +48 | +2 | +25 |
| 2026 (Jan–Aug) | +82 (+0.6%) | +5 | 0 | +34 | +37 | +6 | 0 |

The largest month is 2024-12 (+151, 4%, the rush before the car tax of 2025); every other
month is within 2.5%. The −21 BEV / +25 OTHERS of 2025 is January 2025: 25 fuel-cell cars
that ACEA counted as BEV. For the 2021 quarters (ACEA quarterly) the gap is +3.1%, +1.0%,
+0.4% and +0.6%. Each replaced row keeps ACEA's figure in its `notes`
(`replaces ACEA (TOTAL 1479, +7; BEV 174 / …)`), the correction trail for later checks.

Vans, HDV and Buses against ACEA's quarterly reconstructions (`data/Estonia_legacy.csv`):
Vans within −1 … +3% (ACEA's "BEV" is BEV + PHEV and matches ours), HDV within a few
vehicles a quarter, Buses equal or within 1–5 vehicles (2026-Q2: 74 = 74, 18 BEV = 18).

## 5. Interplay with fetch-acea

| Row in `data/Estonia.csv` | Written by |
|---|---|
| ≤ 2020-12 | ACEA (quarterly, unchanged) |
| ≥ 2021-01, the workbook is out | Transpordiamet, ACEA's figure in the note when it replaced one |
| the workbook is late, ACEA has the month | ACEA (conditional), replaced by Transpordiamet on the next run |

Estonia is in `CONDITIONAL_COUNTRIES` in `scripts/fetch_acea.py`. `fetch_acea_cv.py` no
longer lists Estonia; its quarterly Vans/HDV/Buses rows (2021-07 … 2026-05) are parked in
`data/Estonia_legacy.csv` (an archive, not a series — `ARCHIVE_VARIANTS`).

## 6. Outputs

| File | What |
|---|---|
| `data/Estonia.csv` | Whole: ACEA to 2020-12, Transpordiamet from 2021-01 |
| `data/Estonia_Private.csv`, `data/Estonia_Industry.csv` | new M1 by owner type, from 2021-01 |
| `data/Estonia_Used.csv` | used imports from 2021-01 — no `PHEV` column, hybrids combined in `HEV` |
| `data/Estonia_Vans.csv`, `_HDV.csv`, `_Buses.csv` | from 2021-01, full fuel split |
| `data/Estonia_legacy.csv` | the former quarterly ACEA CV rows (archive) |
| `market/estonia_months.json` | per-month brand/model counts (store, generated) |
| `market/estonia_top.json` | Whole: top BEV/PHEV/HEV/petrol/diesel brands and models, last 12 months (`market_top.py`) |

No Used brand table: the Used variant is a difference of two sheets that carry no make
and model for used imports (only a top-10 of all first registrations).

## 7. Operations and debugging

* **Cron** `5 7,13 1-15 * *` (UTC). A run makes no HTTP request when the target month (last
  month) is a Transpordiamet row in every CSV. A run also picks up any month since 2021-01
  a CSV still lacks (up to six).
* **Dispatch inputs:** `variant`, `period` (YYYY-MM), `backfill` (every workbook from
  2021-01, ~90 MB), `force` (skip throttle, completeness, cross-check and foreign-row
  guards).
* **Offline:** `python scripts/fetch_estonia.py --from-dir DIR --backfill --dry-run` with
  the workbooks saved as `DIR/YYYY-MM.xls[x]` (`--dump-dir` saves them on a live run).
* The step summary lists the month's cross-checks and every written row with the change
  against the row it replaced.

### Debugging runbook

| Symptom | Likely cause | What to do |
|---|---|---|
| `No 'Infoleht' workbook links found` | the statistics page moved or the link text changed | open the page; compare the link text with `find_workbooks()` ("Infoleht MM-YYYY"); update the pattern and `test_find_workbooks` |
| `No workbook for YYYY-MM on the page yet` | not posted yet | nothing — the next run retries until the 15th; after that fetch-acea fills the month and the next month's run picks it up |
| `sheet 'uuedsõidukid' not found` / `no header row` / `missing engine/hybrid/make/model column` | a new workbook layout | open the workbook; extend `parse_new()` / `find_sheet()`; add the layout to `test_layouts` |
| `cross-check failed — new passenger cars …` | a sheet cut off or a new category code | compare the sheet with the headline table by hand; a new category goes into `CATEGORY_VARIANT` / `PASSENGER` / `LORRY` / `BUS` |
| `::warning New value … owner X` / `engine X` | a new owner or engine code | decide the mapping, add it to `KNOWN_OWNER` / `KNOWN_ENGINES` and a test case |
| `… N vehicles (x %) with unknown values` | many vehicles with a new code | as above — the run writes nothing until it is mapped |
| `TOTAL … is x % of the trailing median` | a partial workbook, or a real shock (the 2025 car tax halved January) | check the headline table; `force` if genuine |
| `kept (foreign source …)` | a row written by hand or another fetcher | inspect it; `force` only if Transpordiamet is right |

## 8. Sequence

```mermaid
sequenceDiagram
  participant Cron as fetch-estonia.yml (07:05, 13:05, 1st-15th)
  participant T as transpordiamet.ee
  participant Repo as data/Estonia*.csv
  participant ACEA as fetch-acea.yml
  Cron->>Cron: target month in every CSV? → exit (no HTTP)
  Cron->>T: statistics page → Infoleht MM-YYYY link
  Cron->>T: the month's workbook (XLS/XLSX)
  Cron->>Cron: parse 3 sheets, cross-check vs headline table, guards
  Cron->>Repo: 7 CSVs (line-level upsert) + market/estonia_top.json
  Cron->>Cron: dispatch render-country.yml (touched variants)
  ACEA->>Repo: only a Whole month the workbook has not delivered yet
```
