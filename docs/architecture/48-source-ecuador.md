---
country: Ecuador
slug: ecuador
method: file
summary: New-vehicle sales data for Ecuador from the tax authority's record-level open data —
  every new vehicle invoiced in the country, with brand, catalogue description, class and fuel.
  The same register AEADE, the importers' and assemblers' association, builds the official
  monthly sales statistics from.
source_name: SRI (Servicio de Rentas Internas) — open data «Vehículos Nuevos»
source_url: https://www.datosabiertos.gob.ec/dataset/?organization=sri-servicio-de-rentas-internas&tags=Vehiculos+Nuevos
source_links:
- label: SRI yearly file (the URL pattern the fetcher reads; 2017 → current year)
  url: https://descargas.sri.gob.ec/download/datosAbiertos/SRI_Vehiculos_Nuevos_2026.csv
  note: one ";"-separated CSV per calendar year, one row per processing of a vehicle (≈ 400–650k rows a year, motorcycles included); the current year is regenerated early each month with the month just ended
- label: Ecuador's open-data portal — «Estadísticas Vehículos <YYYY>»
  url: https://www.datosabiertos.gob.ec/dataset/estadisticas-vehiculos-2025
  note: the catalogue entries that link the yearly files (the portal answers 403 to scripts, so the fetcher goes to the SRI download server directly)
- label: AEADE — monthly press bulletin «venta de vehículos»
  url: https://www.aeade.net/boletines-de-prensa-venta-de-vehiculos/
  note: built from the same register (signed "FUENTE SRI"); its energy and segment tables are the cross-check of every run
- label: AEADE — yearbooks (Anuario)
  url: https://www.aeade.net/anuario/
  note: annual sales by segment and powertrain; used for the 2018–2025 validation below
underlying: SRI's register of new-vehicle invoices (the basis of the vehicle tax and the first registration)
auth: none
cadence: twice daily on the 1st–14th — SRI regenerates the current year's file early in the month (August 2026 on Sep 4)
variants:
- Whole
- Vans
variant_notes:
  Whole: New cars and SUVs — SRI classes AUTOMOVIL (sedans, hatchbacks, wagons, coupés) and JEEP (SUVs), EU M1. The same set as AEADE's segments «automóvil» + «SUV».
  Vans: New pickups and vans — SRI class CAMIONETA (≈ EU N1). About four fifths pickups; the rest panel vans and van-based minibuses («furgonetas»), some of them passenger versions.
hev_split: true
hev_note: SRI has a single hybrid code and its catalogue a single "HYBRID" ending for mild, full, plug-in and range-extender hybrids. The plug-ins are picked out of the hybrids by this project's own rule table (classification/ecuador_rules.csv, below) — from the model name, or from the model where the name does not say it — and counted as PHEV or EREV; the rest stays HEV (full and mild hybrids, not split). Checked against ZEMO's monthly plug-in counts and AEADE's yearbook (§3b). Nissan's e-POWER (a series hybrid without a plug) is HEV, not BEV or EREV.
backfill: from 2018-01, the first year whose file has a processing date (the 2017 file has only a month of sale, and no 2016 file exists to deduplicate its January against — it is read only to deduplicate 2018–2019)
scope_note: New vehicles invoiced in Ecuador (dealer sales and new vehicles imported directly by their buyer), counted once each, in the month SRI first processed the vehicle. Ecuador does not allow imports of used vehicles, so there is no used-import series. Motorcycles, trucks, buses, tractor units and special vehicles are in no variant.
caveats:
- These are sales (invoices of new vehicles registered with the tax authority), not registrations — in Ecuador the first registration follows the invoice, and AEADE reports this register as the country's vehicle sales. Each vehicle is counted once, in the month SRI first processed it; the series reproduces AEADE's published annual market within 0.2 % for 2019–2024 and its monthly figures within about 1 %.
- PHEV and EREV are derived: SRI does not distinguish plug-in from other hybrids, so this project classifies them from the model with a published rule table. 2025 plug-ins agree with ZEMO's count within 0.3 % and are 5 % below AEADE's yearbook; before 2025 they are 10–18 % below AEADE and 3–13 % above ZEMO (small numbers, §3b). HEV (full and mild hybrids together) is counted within ICE in the BEV/ICE trajectory.
- The powertrain is read from SRI's catalogue description where it names one (… EV, … HYBRID, … DIESEL), and from the invoice's fuel field otherwise. The fuel field is filled per invoice and is less reliable — about 5,300 cars and pickups 2018–2026 whose description says HYBRID were invoiced as GASOLINA (Toyota Corolla Cross, Kia Niro, Suzuki mild hybrids). Mild hybrids the description does not call HYBRID stay in PETROL.
- Nissan's X-Trail e-POWER is coded ELECTRICO by SRI and catalogued as "EV", but has no plug — the petrol engine only charges the battery. It is counted as a hybrid (2,814 cars 2023–2026). AEADE counts it as a hybrid too (in 2023–2024 as "ELECTRICO EREV", outside its BEV figure).
- Pickups are not in Whole — they are Ecuador (Vans), a large segment (about a fifth of the market). Passenger minivans built on vans (≈ 800 a year named as passenger versions) are in Vans, not Whole, as in AEADE's «VAN» segment.
processing:
- title: Download
  text:
  - SRI publishes one CSV per calendar year, 2017 to the current year (40–110 MB each). A month is used only once its year's file was regenerated after the month ended (the server's Last-Modified date), so a month is never taken half-done. A normal run downloads the newest two years plus the two before them (to recognise vehicles already counted); a backfill reads all ten.
- title: One count per vehicle
  text:
  - A vehicle appears once per processing — the invoice, corrections, the hand-over to the registry — always with the same catalogue data (1.4 to 3.7 rows per vehicle a year). It is counted once, in the month of its first processing.
  decision:
    ask: Was the vehicle (same CÓDIGO DE VEHÍCULO) already processed in either of the two preceding calendar years?
    branches:
    - when: no
      then: counted in the month of its first processing this year
    - when: yes
      then: not counted again
      note: it was counted then — 1,000 to 2,400 a year, mostly December sales processed again in January
- title: Pick the vehicles
  text:
  - SRI's CLASE decides the variant. Motorcycles are dropped first; everything else counts towards the all-segment total that AEADE publishes.
  decision:
    ask: SRI class (CLASE)?
    branches:
    - when: AUTOMOVIL (cars) or JEEP (SUVs)
      then: Whole
    - when: CAMIONETA (pickups, panel vans, van-based minibuses)
      then: Vans
    - when: CAMION, VOLQUETA, TANQUERO, TRAILER, OMNIBUS, ESPECIAL
      then: no variant (in the all-segment cross-check only)
    - when: MOTOCICLETA
      then: not counted
- title: Powertrain
  text:
  - SRI's catalogue description ends in the powertrain for every electric, hybrid and diesel model ("YUAN PRO GS AC 5P 4X2 TA EV", "COROLLA CROSS MID AC 1.8 5P 4X2 TA HYBRID"). It is filled from the vehicle's homologation, while the invoice's fuel field is typed per sale — so the description wins where it names a powertrain.
  decision:
    ask: What does the catalogue description (MODELO) say?
    branches:
    - when: E-POWER anywhere (Nissan X-Trail e-POWER)
      then: HEV
      note: a series hybrid without a plug; SRI codes it ELECTRICO and catalogues it as EV
    - when: ends in HYBRID
      then: a hybrid — split by the rule table (below)
      note: mild, full and plug-in hybrids alike in SRI's catalogue
    - when: ends in EV
      then: BEV
    - when: ends in DIESEL
      then: DIESEL
    - when: nothing
      then:
        ask: Invoice fuel code (TIPO COMBUSTIBLE)?
        branches:
        - when: GASOLINA
          then: PETROL
        - when: DIESEL
          then: DIESEL
        - when: ELECTRICO
          then: BEV
        - when: HIBRIDO_GASOLINA_BATERIAS / HIBRIDO_DIESEL_BATERIAS
          then: a hybrid — split by the rule table (below)
        - when: dual gas, CNG, LPG, alcohol, other
          then: OTHERS
- title: Plug-in or not
  text:
  - Every hybrid is tested against the rule table in the section below, top to bottom; the first rule whose brand and pattern match makes it a plug-in (PHEV) or a range-extender (EREV). Most plug-ins say so in the name (PHEV, DM-i, REEV); for the ones that do not — the DFSK E5, the Changan CS55 Plus and Deepal, a BMW "…e" — a brand- or model-specific rule was written from the importer's Ecuadorian spec page. A hybrid no rule matches stays HEV.
- title: Check against AEADE
  text:
  - AEADE's monthly press bulletin is built from this register. Every run compares the all-segment total, the BEV count and Whole (against AEADE's automóvil + SUV) for the months the newest bulletin shows. Over all 16 bulletins with these tables (May 2025 to August 2026, months from 2024-05) totals agree within 1.5 % and BEV within 3.4 %; a gap beyond 10 % stops the run.
  - The one exception is AEADE's first edition for October/November 2025, which put about 500 vehicles in October that the register puts in November (the two months together agree within 0.5 %).
market_breakdown: market/ecuador_top.json
market_designation_note: the model is the start of SRI's catalogue description, up to the first trim or specification word and at most two words ("YUAN PRO GS AC 5P 4X2 TA EV" → YUAN PRO; "TIGGO 4 PRO COMFORT AC 1.5 …" → TIGGO 4), so trims of one model are one row.
market_powertrain_note: exactly as in the CSV — the end of SRI's catalogue description, else the invoice's fuel code; hybrids split into plug-in (PHEV), range-extender (EREV) and the rest (HEV, full and mild) by the rule table below. The Nissan e-POWER is HEV.
market_class_names:
  HEV: Hybrid
market_class_labels:
  HEV: Hybrid without a plug — full and mild hybrids, not split (counted as ICE in the curves)
classification:
  rules: classification/ecuador_rules.csv
  mapping: classification/ecuador_models.csv
  scopes: [Whole, Vans]
  default:
    id: default-hev
    class: HEV
    text: "No rule matched: a hybrid whose designation names no plug and no model-specific rule applies, so it is counted as a hybrid without a plug (full or mild)."
    leftover: "This is where a plug-in hiding behind a designation without any marker would show up — every one of these was checked when the rules were written, and the fetcher lists hybrid designations it has not seen before on every run."
  labels:
    seen: hybrid designations seen
    decided: classified plug-in
    heading: classified as plug-in (PHEV or EREV)
    token: of plug-in sales say so in the designation (PHEV, DM-i, REEV …)
    specific: decided by a brand- or model-specific rule
    recent: Newest year
  intro:
  - "SRI's catalogue ends every hybrid's description in the same word, HYBRID, and its fuel field has one hybrid code — a Toyota Corolla Cross hybrid and a BYD Song Plus DM-i plug-in look alike. So among the hybrids this project picks out the plug-ins itself, from the designation, and publishes every step here so you can check it."
  - "Step 1 — only hybrids. Battery-electric, petrol and diesel cars are decided as described above and never reach this table. Nissan's e-POWER (no plug) is decided before it, as a hybrid."
  - "Step 2 — rules. Each hybrid's designation (upper-case, as SRI writes it) is tested against the rule table below, top to bottom. The first rule that matches both the brand and the pattern decides: plug-in hybrid (PHEV) or range-extender (EREV). Many designations say it outright ('SONG PLUS DM-I …', 'TIGGO 7 PHEV …', 'HUNTER REEV …'); the brand- and model-specific rules cover the ones that do not — the DFSK E5 and Changan's CS55 Plus are sold in Ecuador only as plug-ins, a Deepal only as a range-extender, a BMW '330E' or a Volvo 'T8' is a plug-in. Every model-specific rule was checked against the importer's or a dealer's Ecuadorian page; the evidence is listed with the rule."
  - "Step 3 — the rest. A hybrid no rule matches is counted as HEV: full and mild hybrids, which the source does not tell apart either."
  - "Check. ZEMO (the Latin American e-mobility platform) publishes monthly plug-in counts for Ecuador; AEADE's yearbook has yearly ones. 2025: 2,495 plug-ins here, ZEMO 2,502, AEADE 2,636 (all segments)."
fetcher: scripts/fetch_ecuador.py
workflow: .github/workflows/fetch-ecuador.yml
fragility_doc: docs/architecture/48-source-ecuador.md
data_file: data/Ecuador.csv
---

# 48 · Source: Ecuador (SRI new-vehicle register, open data)

**Status: LIVE since 2026-10.** Fetcher `scripts/fetch_ecuador.py` (+ tests
`scripts/test_fetch_ecuador.py`) and `.github/workflows/fetch-ecuador.yml`.
Ecuador is the gallery's eighth South American market and its third
record-level source there after Argentina and Paraguay: every new vehicle
sold in the country, one record per processing, from the tax authority.

The facts below were established on 2026-10-04 from the dev sandbox (which,
unusually, reaches both the SRI download server and AEADE) and confirmed by a
temporary probe workflow on the PR branch (since removed): GitHub runners
download the ten yearly files in about 40 s in total, find AEADE's newest
bulletin on its own, and the online backfill is **byte-identical** to the
offline one.

## TL;DR

```
Source:    SRI open data «Vehículos Nuevos», one CSV per calendar year:
           https://descargas.sri.gob.ec/download/datosAbiertos/SRI_Vehiculos_Nuevos_<YYYY>.csv
           2017 → current year; ";"-separated; one row per PROCESSING of a
           vehicle (1.4–3.7 rows per vehicle), motorcycles included.
Auth:      None. No login, no key. (datosabiertos.gob.ec, the catalogue,
           answers 403 to scripts — the download server does not.)
Timing:    the current year's file is regenerated early in the month with the
           month just ended (Aug 2026: Sep 4 22:33 UTC). A month is used once
           Last-Modified ≥ the 1st of the next month.
Count:     each vehicle (CÓDIGO DE VEHÍCULO) once, in the month of its first
           processing — unless processed in either of the two preceding years.
History:   2018-01 → today (2017 has no processing date; lookback only).
Scope:     CLASE AUTOMOVIL + JEEP → Whole (M1); CAMIONETA → Vans (≈ N1).
Fuel:      end of the catalogue description: EV → BEV, HYBRID → HEV,
           DIESEL → DIESEL, E-POWER → HEV; else the invoice's fuel code.
Plug-ins:  hybrids → PHEV / EREV / HEV by classification/ecuador_rules.csv
           (13 ordered rules, first match wins; default HEV). 2025 vs ZEMO
           −0.3 %, vs AEADE yearbook −5 % (§3b).
Checked:   AEADE (same register): annual market 2019–2024 within 0.2 %;
           every bulletin month 2024-05 → 2026-08: total ≤ 1.5 %, BEV ≤ 3.4 %
           (except AEADE's own Oct/Nov 2025 month-boundary shift, below).
```

## 1. Why this source

The gallery's bar ([14](14-data-source-gaps.md)): direct from the registry
or a recognised official body, complete for the market, free.

- **It is the register the official statistics come from.** AEADE (Asociación
  de Empresas Automotrices del Ecuador) publishes Ecuador's monthly vehicle
  sales; every table in its bulletin and yearbook is signed "FUENTE: SRI".
  The SRI open data are the record-level form of the same register: every
  invoiced new vehicle, every brand, AEADE member or not — so there is no
  BYD-style completeness hole (BYD is 40 % of Ecuador's BEVs).
- **Record level.** One row per vehicle processing, with the vehicle's id,
  brand, the SRI catalogue description (which names the powertrain), class
  and fuel code — enough for the gallery's split, for brand and model tables,
  and for an exact reproduction of the published totals.
- **Free and stable.** No login, no key, one stable URL pattern for ten
  years of files (2017–2026), reachable from GitHub runners.
- **What else was looked at.** AEADE's monthly bulletin (a 17-page Power-BI
  export: market by fuel for all segments, BEV and hybrid totals) is the
  cross-check rather than the source: its fuel table covers all segments
  including trucks and buses, and it has carried that table only since
  2025-05. AEADE's Power BI report on its site is about «compra programada»
  (a savings-plan purchase scheme), not the market. The national transit
  agency ANT and INEC publish fleet statistics (yearly, by fuel), not monthly
  new-vehicle sales. AEADE's yearbook is annual.

## 2. Record → CSV row

| Column (normalised) | Use |
|---|---|
| `CÓDIGO DE VEHÍCULO` (2018: `CODIGO VEHICULO`, 2017: `Código Vehículo 1`) | the vehicle's id — one count per id (§4) |
| `FECHA PROCESO` | the processing date → month (§4); six spellings since 2018 (§5) |
| `CLASE` | the variant (§3) |
| `MODELO` | SRI catalogue description → powertrain (§3a), model name for `market/` |
| `TIPO COMBUSTIBLE` | the invoice's fuel code (§3a) |
| `MARCA` | brand for `market/` |

Not used: `TIPO TRANSACCIÓN` (COMPRA LOCAL ≈ 99.6 %, IMPORTACIÓN DIRECTA —
both new vehicles), `FECHA COMPRA`, `AVALÚO`, `TIPO SERVICIO`, colours,
canton, owner type. CSV columns: `BEV, PHEV, EREV, HEV, PETROL, DIESEL,
OTHERS, TOTAL`;
`source` = `SRI new-vehicle register (open data)`. Line-level upserts (invariant
2); a row whose `source` is not ours is never overwritten without `--force`.

## 3. Scope

| SRI `CLASE` | Contents (`SUB CLASE`) | Variant | 2025 |
|---|---|---|---:|
| `AUTOMOVIL` | sedan, station wagon, coupé, convertible (+ the subclasses HIBRIDO-A / ELECTRICO-A) | Whole | 21,602 |
| `JEEP` | SUVs (+ HIBRIDO-J / ELECTRICO-J) | Whole | 59,848 |
| `CAMIONETA` | doble / cabina simple (pickups, ≈ 78 %), furgoneta (vans and van-based minibuses, ≈ 19 %), furgón, reparto, utility | Vans | 27,734 |
| `CAMION`, `VOLQUETA`, `TANQUERO`, `TRAILER` (tractor units), `OMNIBUS`, `ESPECIAL` | trucks, buses, special vehicles | — (all-segment total only) | 15,442 |
| `MOTOCICLETA` | motorcycles | not counted | — |

Whole is exactly AEADE's «automóvil» + «SUV» (August 2026: 10,658 vs
AEADE's 10,733, −0.7 %). AEADE splits SRI's CAMIONETA into «camioneta»
(pickups) and «VAN» with its own catalogue; the register has no such field,
so both are Vans. About 800 furgonetas a year are named as passenger versions
(Chevrolet N400 Move Pasajeros, Hyundai Staria 11 pas …) — M1 or M2 vehicles
in Vans; the series is still dominated by diesel pickups. An unknown CLASE is
listed in the run report; above 2 % of the month's vehicles the run aborts.

### 3a. Powertrain (`DESCRIPTION_RULES`, then `FUEL_CODE`)

SRI's catalogue description ends in the powertrain for electric, hybrid and
diesel models (`… TA EV`, `… TA HYBRID`, `… TM DIESEL`, trucks `… DIESEL CN`).
The invoice's `TIPO COMBUSTIBLE` is filled per sale and disagrees with the
description on just under 1 % of cars and pickups — almost always a hybrid
invoiced as GASOLINA, or the e-POWER. Ordered rules on the description, first match wins:

| Description | → | Cars + pickups moved off their fuel code, 2018 – 2026-08 |
|---|---|---:|
| `E-POWER` / `EPOWER` anywhere — Nissan X-Trail e-POWER: series hybrid, no plug (SRI codes ELECTRICO, catalogues "EV") | HEV | 2,814 (2023: 1,043 · 2024: 782 · 2025: 630 · 2026: 359) |
| ends in `HYBRID` | HEV | 5,314 from GASOLINA (2025: 1,295), 12 from DIESEL |
| ends in `EV` / `EV CN` | BEV | 6 (GASOLINA / HIBRIDO codes on a Yuan Pro, a Spark EUV, three JAC E30X) |
| ends in `DIESEL` / `DIESEL CN` | DIESEL | 108 (mostly GASOLINA codes) |

Otherwise the fuel code decides: `GASOLINA` → PETROL, `DIESEL` → DIESEL,
`ELECTRICO` → BEV, `HIBRIDO_GASOLINA_BATERIAS` / `HIBRIDO_DIESEL_BATERIAS` →
HEV, `DUAL_GAS_GASOLINA`, `GAS_NATURAL_COMPRIMIDO`, `GAS_LICUADO_PETROLEO`,
`ALCOHOL`, `OTROS`, `SOLAR`, `NO_UTILIZA` → OTHERS (a handful a year). An
unknown code is counted as OTHERS and listed; above 2 % of Whole the run
aborts. Every rule has a test, including look-alikes that must not match
(`EVOQUE`, `EV18 …` with EV not at the end, `… HYBRID LINE …`, `POWERTRAIN`).

Without the description rules HEV (here: all hybrids before the plug-in
split) would be about 7 % too low in 2025, and BEV more than double in 2023
(1,043 e-POWER on about 830 BEV) and 15 % too high in 2025.

### 3b. Plug-in split (`classification/ecuador_rules.csv`)

SRI has one hybrid code and one `HYBRID` ending, so a plug-in can only be
recognised by its model. Words in the description (`PHEV`, `DM-i`, `REEV`)
find only 1,102 of 2025's plug-ins — two of the three biggest plug-ins in
Ecuador, the DFSK E5 and the Changan CS55 Plus, carry no such word. So the
split follows Argentina's design ([39](39-source-argentina.md) §4,
[`classification/README.md`](../../classification/README.md)): a
**hand-edited, ordered rule table**, first match wins, every rule with a
reason, evidence and a real Ecuadorian example — but a separate file, since
Ecuador's designations (SRI's catalogue, ending in `HYBRID`) and its model
range differ from Argentina's and only hybrids reach it.

| # | Rule | Brand | Pattern | → | 2018–24 | 2025 | 2026 Jan–Aug |
|---:|---|---|---|---|---:|---:|---:|
| 1 | `erev-token` | any | `REEV` / `EREV` | EREV | 0 | 60 | 128 |
| 2 | `erev-deepal` | Changan | `DEEPAL` (sold as range-extender only) | EREV | 0 | 94 | 191 |
| 3 | `phev-token` | any | `PHEV`, `PLUG-IN`, `ENCHUFABLE` | PHEV | 149 | 563 | 1,957 |
| 4 | `phev-dm-idm` | any | BYD `DM-i` / `DM-p` / `DMO`, Jetour / Chery `i-DM` | PHEV | 171 | 458 | 502 |
| 5 | `phev-jeep-4xe` | Jeep | `4XE` | PHEV | 90 | 5 | 1 |
| 6 | `phev-porsche-ehybrid` | Porsche | `E-HYBRID`, `CAYENNE E` | PHEV | 51 | 16 | 13 |
| 7 | `phev-volvo` | Volvo | `T8`, `RECHARGE` | PHEV | 1 | 0 | 0 |
| 8 | `phev-bmw-e` | BMW | a model number ending in E (`330E`, `X5 45E`) | PHEV | 417 | 91 | 35 |
| 9 | `phev-mercedes-e` | Mercedes-Benz | `300E`-style, `HIBRIDA EQ` | PHEV | 0 | 1 | 28 |
| 10 | `phev-mini-countryman-se` | Mini | `COUNTRYMAN COOPER SE` | PHEV | 14 | 0 | 0 |
| 11 | `phev-dfsk-e5` | DFSK | `E5` (sold as PHEV only) | PHEV | 137 | 707 | 715 |
| 12 | `phev-changan-cs55` | Changan | `CS55` hybrid (sold as PHEV only) | PHEV | 0 | 493 | 636 |
| 13 | `phev-jaecoo-j7` | Jaecoo | `J7` hybrid (SHS-P, a plug-in) | PHEV | 0 | 7 | 56 |
| — | `default-hev` | | anything left | HEV | | | |

(Counts: all segments, vehicles counted as in §4.) The full rule table with
patterns, reasons and evidence, and every hybrid designation with its deciding
rule, are on the [source page](../../sources/ecuador.html#classification) and
in `classification/ecuador_models.csv` (generated, one row per brand,
designation, scope and year). Look-alikes the tests pin down as *not*
plug-ins: BMW `X3 XDRIVE 40I` (mild), Mercedes `GLC 300` / `GLE 53 … EQ
BOOST` (mild), Kia Sorento hybrid (full), Chery Tiggo 7 Pro hybrid (mild),
GWM Tank 500 (full), Jaecoo J5, JAC `E5` (a BEV brand rule must not leak),
Nissan e-POWER.

**How the model-specific rules were found.** ZEMO (zemo-la.com/data, the
Latin American e-mobility platform) publishes monthly BEV and PHEV counts
for Ecuador, built from the same register — its BEV equals this fetcher's
all-segment BEV to the unit. The monthly gap between ZEMO's PHEV and the
token rules (1–3) pointed to the hybrid models that fill it exactly
(DFSK E5, Changan CS55 Plus and Deepal, BMW "…e"); each was then confirmed
on the Ecuadorian importer's or a dealer's page before a rule was written.
ZEMO is a **check, never an input**: no number is taken from it.

**Check, all segments (PHEV + EREV):**

| Year | This fetcher | ZEMO | | AEADE yearbook | |
|---|---:|---:|---:|---:|---:|
| 2019 | 8 | 7 | | | |
| 2020 | 39 | 29 | | | |
| 2021 | 35 | 40 | | | |
| 2022 | 156 | 138 | +13 % | | |
| 2023 | 308 | 273 | +13 % | 375 | −18 % |
| 2024 | 484 | 468 | +3 % | 540 | −10 % |
| 2025 | 2,495 | 2,502 | −0.3 % | 2,636 | −5 % |
| 2026 Jan–Aug | 4,262 | 4,114 | +4 % | | |

Month by month, 2025-01 → 2026-08: within ±12 % of ZEMO in every month but
one (2026-02: 353 vs 313, +13 %). AEADE classifies with its own model
catalogue and counts somewhat more plug-ins; the remaining gap (2025: 141)
is no single model — no hybrid designation the rules leave as HEV is a known
plug-in. AEADE's yearbook also has an "EREV" line (2023: 1,043, 2024: 782,
2025: 644): that is Nissan's e-POWER, which has no plug and is HEV here (§3a).
Real range-extenders (Deepal, Changan Hunter REEV) only arrived in 2025.

Plug-in share of new cars and SUVs (Whole): 0.3 % (2023), 0.6 % (2024),
2.8 % (2025), 5.4 % (2026 Jan–Aug), 7.1 % in August 2026.

**Changing a rule.** Edit `classification/ecuador_rules.csv` (ordered;
fill `reason`, `evidence`, a real example — `load_rules()` refuses the file
otherwise, and checks that each example is decided by its own rule), run
`scripts/test_fetch_ecuador.py`, then dispatch the fetch with `backfill` so
the whole history is re-classified. Never widen a brand-wide rule to fix one
model. Every run lists hybrid designations it has not seen before in the step
summary ("New hybrid designations") — that list is where a new plug-in shows
up first.

## 4. One count per vehicle

Each yearly file holds one row per **processing**: the invoice, corrections,
and the hand-over of the invoice to the vehicle registry — 1.4 rows per
vehicle in 2025, 3.7 in 2021. All rows of a vehicle carry the same brand,
model, class, fuel, canton and purchase date; only `FECHA PROCESO` differs.

Rule: **a vehicle counts once, in the month of its first processing, unless
it was already processed in either of the two preceding calendar years**
(`LOOKBACK_YEARS = 2`). Vehicles found in the year before: 1,000–2,400 a
year (2025: 1,715), almost all December sales processed again in January —
without the lookback January would be 5–8 % too high. Two years back adds
25–137 a year; three or more years back 5–27 (ignored).

The rule is applied identically in backfills and monthly runs (a normal run
downloads the newest two years and the two before them), so both write the
same rows — verified: the forced monthly run on the runner changed none of
the 20 rows it re-derived. Every real run re-derives both years, so a later
SRI correction of an earlier month is picked up and listed in the step
summary ("Earlier rows changed by this run").

**Why the first processing date, not the purchase date.** AEADE's figures
match the processing month: by first processing month the series' totals
are within 0.1–0.2 % of AEADE's restated months (later bulletins), by
purchase month (`FECHA COMPRA`) up to 9 % off.

## 5. Formats over the years

| File | Encoding | Code column | Date column, spelling |
|---|---|---|---|
| 2017 | cp1252 | `Código Vehículo 1` | none — `Mes registro venta` (month only) → lookback only |
| 2018 | cp1252 | `CODIGO VEHICULO` | `FECHA PROCESO (MM/DD/AA)` but day first: `28/12/2018 21:50` |
| 2019 | cp1252 | `CÓDIGO DE VEHÍCULO` | `27/12/2019 22:46:06` |
| 2020 | cp1252 | 〃 | `27-Nov-20`, `29-Ago-20`, `30-Sept-20` (English, Spanish, four letters) |
| 2021–2023 | cp1252 | 〃 | `2-dic-21` |
| 2024 | cp1252 | 〃 | `9/12/2024` |
| 2025 | cp1252 | 〃 | `17/9/2025` |
| 2026 | UTF-8 + BOM | 〃 | `24/06/2026` |

`parse_date()` reads all of them; a date that does not parse or falls outside
the file's year is counted, and above 0.5 % of a file's vehicle rows the run
aborts (zero in every file 2018–2026). Headers are matched after stripping
accents, so `PAÍS`/`PAIS`, `AVALÚO`/`AVALUO` do not matter.

## 6. Validation

**AEADE yearbook, all segments (AEADE's scope: everything but motorcycles):**

| Year | This fetcher | AEADE | | BEV | AEADE | Hybrid | AEADE |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2018 | 136,328 | 137,615 | −0.9 % | 134 | 130 | 2,848 | 3,390 |
| 2019 | 132,308 | 132,208 | +0.1 % | 106 | 103 | 1,401 | 1,415 |
| 2020 | 81,915 | 81,821 | +0.1 % | 136 | 134 | 1,053 | 1,053 |
| 2021 | 115,946 | 115,731 | +0.2 % | 284 | 284 | 3,928 | 3,926 |
| 2022 | 134,363 | 134,170 | +0.1 % | 465 | 436 | 6,512 | 6,510 |
| 2023 | 132,567 | 132,388 | +0.1 % | 833 | 767 | 11,504 | 11,508 |
| 2024 | 108,446 | 108,266 | +0.2 % | 1,450 | 1,416 | 13,082 | 13,088 |
| 2025 | 124,626 | 125,505 | −0.7 % | 4,332 | 4,276 | 18,327 | 18,370 |

Hybrids (here PHEV + EREV + HEV) match to a few units from 2020 (AEADE's
yearbook hybrids include the e-POWER, as here); the plug-in split is checked
in §3b. BEV runs 1–9 % above AEADE's — a few dozen vehicles a
year (2023: 66) that SRI codes and catalogues as electric but AEADE, which
classifies with its own model catalogue, leaves out of its BEV figure. 2018
is the one year with a larger gap, in hybrids (−16 %, 542 vehicles); the
register shows no hybrid model under another fuel code that would explain
it.

**Every AEADE bulletin with an energy table** (16 bulletins, 2025-05 →
2026-08; each shows the month and the same month a year earlier), offline
run against each — total / BEV / car + SUV:

- 2024-05 … 2026-08, about 30 month comparisons: total within **1.5 %**, BEV
  within **3.4 %** (BEV ±15 units pass regardless — small numbers), Whole vs
  car + SUV within 1.5 %;
- **except AEADE's first edition for October and November 2025**: total
  −4.2 % / +3.4 %, car + SUV −6.3 % / +5.2 %, hybrids −18 % / +20 %. The two
  months together are within 0.5 %: AEADE's first edition put about 500
  vehicles in October that the register (and AEADE's later restatements of
  other months, which all match to 0.1 %) puts in November.

The fetcher repeats this check on every real run against the newest bulletin
it can find (§8): above 3 % a month is flagged (warning annotation), above
10 % the run aborts. A missing bulletin is a warning, not a hold: AEADE's
bulletins appear on its site irregularly (the April, May and June 2026
bulletins were all uploaded in July).

## 6a. Reading the fit

Ecuador's BEV share of new cars and SUVs went from ≈ 0.1–0.4 % (2018–2022)
to 0.8 % (2023), 1.9 % (2024), 5.1 % (2025) and 11.5 % in January–August
2026, with August 2026 at 18.9 %; hybrids are another 27 % (plug-ins 5.4 %, August 7.1 %). The rise is
almost entirely Chinese brands (BYD 40 % of BEVs in the last twelve months,
then Chevrolet's China-built Spark EUV, Kia, Dongfeng, GAC). BEVs pay no VAT
and no special consumption tax (ICE) and are exempt from the vehicle property
tax; the Ecuador–China trade agreement (in force 1 May 2024) phases out
tariffs on Chinese cars, and the diesel subsidy ended on 13 September 2025.
Single months are lumpy (June 2026 14.7 %, July 9.2 %, August 18.9 % — August
coincided with Guayaquil's Autoshow); no policy change explains them, so the
fit should be read on the trend, not the last month.

Vans: BEV ≈ 0.3–0.5 % (Riddara RD6, BYD T3, Keyton vans), hybrids 4 %
(Ford F-150, RAM, Foton Tunland), plug-ins 1.4 % in 2026 (BYD Shark,
Changan Hunter REEV) — *No transition* by the gallery's rule.

## 7. Outputs

- `data/Ecuador.csv` (Whole) and `data/Ecuador_Vans.csv` (Vans), monthly,
  2018-01 →, both rendered.
- `classification/ecuador_models.csv` — every hybrid designation with its
  class and deciding rule, per scope and year (generated; the years a run
  re-derives are replaced, older years kept and re-classified with the current
  rules). `classification/ecuador_rules.csv` is the hand-edited source of
  truth (§3b).
- `market/ecuador_top.json` — trailing-12-month top brands and models per
  class (BEV, PHEV, EREV, HEV) for Whole, plus single-month rankings, built straight
  from the records of the two years each run reads (no month store needed).
  Brand = `MARCA` with a few aliases (`MERCEDES BENZ` → MERCEDES-BENZ,
  `URVANE MOVILITY` → URVANE MOBILITY, `LYNK AND CO` → LYNK & CO); model =
  `display_model()` (front matter, `market_designation_note`).

## 8. Operations and debugging

```mermaid
sequenceDiagram
    participant Cron as fetch-ecuador.yml (cron / dispatch)
    participant Test as test_fetch_ecuador.py
    participant Py as fetch_ecuador.py
    participant SRI as descargas.sri.gob.ec
    participant AEADE as aeade.net (bulletin)
    participant CSV as data/Ecuador*.csv
    participant Top as market/ecuador_top.json
    participant Render as render-country.yml
    Cron->>Test: headers + dates + one-count + lookback + rules + bulletin tests (gate)
    Cron->>Py: run
    Py->>SRI: HEAD current year (else last year) → Last-Modified → newest complete month
    Py->>CSV: that month already from SRI in every CSV?
    alt yes
        Py-->>Cron: no-op (one HEAD)
    else no
        Py->>SRI: newest two yearly files + the two before (lookback), ≈ 4 × 75 MB
        Py->>Py: first processing per vehicle → class → variant; description / fuel code → column; hybrids → ecuador_rules.csv
        Py->>AEADE: bulletin page → newest download ids → PDF of the target month (else newest usable)
        Py->>Py: cross-check total / BEV / car+SUV (abort > 10 %)
        Py->>CSV: line-level upserts (changed lines only)
        Py->>Top: trailing-12-month top list + classification/ecuador_models.csv
        Py-->>Cron: run report → step summary
        Cron->>Render: once, with the changed variants
    end
```

- **Schedule:** `5 14,23 1-14 * *` (Quito 09:05 / 18:05). A no-op costs one
  HEAD request.
- **Normal run:** four yearly files (≈ 300 MB, under a minute on a runner),
  then about 30 s of parsing; re-derives the newest two years.
- **Backfill:** dispatch with `backfill = true` (all ten files, ≈ 2 min).
  Locally: `python scripts/fetch_ecuador.py --backfill --from-dir DIR
  --bulletin Boletin-de-Prensa-<Mes>-<YYYY>.pdf` with the yearly files saved
  under their published names.
- **January:** the new year's file appears in February. Until then the
  newest file is last year's, regenerated in January with December — the
  run writes December then; nothing else changes.
- **After each monthly run:** read the step summary — the month's table, the
  AEADE comparison, earlier rows SRI revised, records whose fuel code the
  description overrode (review that they are real hybrids / BEVs), BEV and
  plug-in and hybrid models, hybrid designations never seen before (check
  each for a plug — §3b), classes in no variant, unknown classes / fuel codes.

**If a run fails — where to look:**

| Symptom in the log | Cause | Fix |
|---|---|---|
| `No SRI_Vehiculos_Nuevos file for this or last year` | SRI moved the files | find the new location from datosabiertos.gob.ec («Estadísticas Vehículos <YYYY>»); update `FILE_URL` |
| `got N bytes, Content-Length M` / connection errors after retries | truncated transfer, server down | re-run later |
| `… is not (completely) in the SRI files yet` | the file was regenerated but lacks the month, or not yet regenerated | nothing; the next scheduled run retries |
| `Schema drift: columns [...]` | SRI renamed a column | map it in `COLUMN_NAMES` / `resolve_columns()`; add the header to `test_every_header_layout_and_encoding` |
| `rows (x %) with an unreadable processing date` | a new date spelling | extend `parse_date()` / `MONTHS`; add it to `test_every_date_spelling` |
| `unknown CLASE … / unknown fuel code … schema drift` | a new class or fuel code | classify it in `CLASS_VARIANT` / `OTHER_CLASSES` / `FUEL_CODE` with a test |
| `AEADE cross-check failed` | an incomplete SRI file, a broken counting rule — or an AEADE slip (Oct 2025) | compare the step summary with the bulletin by hand; if the register is right, dispatch with `force` |
| warning `AEADE cross-check not run` | bulletin not uploaded yet / page changed / table layout changed | nothing if the bulletin is just late; else adapt `find_bulletins()` / `_table()` (tests: `test_bulletin_*`) |
| `below 40 % of the trailing median` | a partial file — or a real collapse (April 2020: 423 cars) | check AEADE; `force` if genuine |
| `classification/ecuador_rules.csv: …` (rule id, example, header) | a rule edit broke the table's checks | fix the row as the message says; run `scripts/test_fetch_ecuador.py` |
| a new plug-in counted as HEV (seen in "New hybrid designations" or a ZEMO gap) | its designation names no plug | add a rule with evidence (§3b), test, dispatch with `backfill` |
| commit step `non-fast-forward` | a concurrent commit | already rebased by the action; re-run |
