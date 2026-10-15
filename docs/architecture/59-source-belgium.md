---
country: Belgium
slug: belgium
method: file
summary: Vehicle registrations in Belgium straight from the FPS Mobility and Transport (DIV, the
  vehicle registration service) — the monthly open-data files behind ACEA's Belgian figure,
  published on the 2nd of the following month, about three weeks before ACEA. New cars
  (Whole), private and VAT-registered keepers, vans, lorries and buses, monthly from 2013,
  with plug-in and non-plug-in hybrids counted separately.
source_name: FPS Mobility and Transport (FOD Mobiliteit en Vervoer / SPF Mobilité et Transports) — monthly vehicle registrations (open data, CC0)
source_url: https://mobilit.belgium.be/nl/documenten/open-data/wegverkeer/inschrijvingen-van-voertuigen
source_links:
- label: FPS Mobility — "Inschrijvingen van voertuigen" (open data page with the monthly Power BI report)
  url: https://mobilit.belgium.be/nl/documenten/open-data/wegverkeer/inschrijvingen-van-voertuigen
  note: the report's last page ("Downloaden") links the source CSVs; the web page itself sits behind a bot challenge for scripts, the file server below does not
- label: DIV monthly registration CSVs (file server)
  url: https://datafiles.mobilit.belgium.be/OPENDATA/DGTRSR/MonthlyRegistrations/
  note: one file per month, YYYYMM_Immatriculations-Inschrijvingen.csv (from 2025-01, ~220 KB), plus 2013_2024_Immatriculations-Inschrijvingen.csv (28 MB); an aggregate by month, new/used vehicle, new/reused plate, keeper type, engine size, vehicle use group and fuel
- label: ACEA — monthly new-car registrations
  url: https://www.acea.auto/
  note: the cross-check of the Whole series (same register) and the fallback for a month DIV has not published yet
underlying: Belgian vehicle register (Directie Inschrijving van de Voertuigen / Direction pour l'Immatriculation des Véhicules — DIV), FPS Mobility and Transport
auth: none
cadence: daily at 17:10 UTC on the 2nd–20th; DIV writes a month's file on the 2nd of the following month (~16:00 UTC)
variants:
- Whole
- Private
- Industry
- Vans
- HDV
- Buses
variant_notes:
  Whole: New passenger cars registered in Belgium (DIV "New vehicle", use group Passenger car — new plate or a transferred plate), monthly from 2013-01. The figures behind ACEA's Belgian series; DIV runs ~0.4 % above it.
  Private: New passenger cars whose keeper is not VAT-registered (DIV keeper type "Natural/Legal Person") — in practice private persons. From 2013-01. Private + Industry = Whole.
  Industry: New passenger cars whose keeper is a VAT-registered legal person (DIV "Legal Person (VAT)") — companies, leasing and rental fleets; Belgium's large company-car market — plus the few rows without a keeper type (0–63 cars a month), so that Private + Industry = Whole. From 2013-01.
  Vans: New light goods vehicles (camionnettes, up to 3.5 t). Monthly from 2013-01 (yearly/quarterly ACEA before, kept in data/Belgium_legacy.csv).
  HDV: New lorries and tractor units for semi-trailers (over 3.5 t). Monthly from 2013-01 (ACEA before, kept in data/Belgium_legacy.csv).
  Buses: New buses and coaches (DIV use group Bus). Monthly from 2013-01 (ACEA before, kept in data/Belgium_legacy.csv).
hev_split: true
hev_note: DIV's fuel field has "Plug-in Hybrid Petrol / Gasoil / LPG" for plug-in hybrids (→ PHEV) and "Hybrid Petrol / Gasoil / LPG" for every other hybrid (→ HEV). DIV does not tell full from mild hybrids, so HEV here counts both — about 2.5 times ACEA's full-hybrid figure for Belgium, with PETROL and DIESEL correspondingly lower (they hold no hybrid at all). BEV + PHEV + the rest is unaffected.
backfill: Every variant is DIV from 2013-01 (the start of the history file). The former ACEA rows — Whole quarterly 2018-01…2022-09 and every ACEA row of Vans/HDV/Buses (yearly 2021–2022, then quarterly) — are kept in data/Belgium_legacy.csv. Whole's ACEA monthly rows 2022-10…2026-08 were replaced; each DIV row's note keeps ACEA's figure where it differed.
scope_note: Registrations of new vehicles in the month as DIV booked them — a new car counts whether it got a new plate or a plate transferred from the keeper's previous car (Belgian plates follow the owner). Used-vehicle registrations are not written (see caveats).
caveats:
- 'Whole runs 86–251 cars (median 155, ~0.4 %) above ACEA''s monthly figure in every month 2022-10 … 2026-08 but one; BEV agrees within 0–34 cars. PHEV is 1–13 % below ACEA in 2025–2026 (ACEA''s July 2026 row is derived from a year-to-date difference and is 24 % higher). Two of ACEA''s Belgian rows were plainly wrong (2023-02: 2,291, 2023-09: 2,965 against DIV 40,056 / 39,034) and are corrected.'
- 'April 2025 is the exception the other way: DIV''s 2025-04 file is about 13 % short (32,737 cars against ACEA''s 37,812, which equals ACEA''s own year-to-date difference; FY2025 ACEA 414,770, DIV 411,384; the Vans / HDV / Buses quarter holding April 2025 is 3–5 % low as well). The DIV rows are kept, because their HEV definition matches the rest of the series and the shares are usable, and their notes say CHECK. Volumes for that month are too low.'
- 'HEV includes mild hybrids (see the hybrid note), so the HEV column is not comparable with ACEA-fed countries; the PHEV and BEV curves are.'
- 'Private is "not VAT-registered", not strictly natural persons: DIV''s keeper type lumps natural persons with legal persons that have no VAT number (associations, some public bodies). Leased cars count by their keeper (the leasing company is VAT-registered, so leased cars are Industry).'
- 'No Used variant: DIV''s "Used vehicle" counts every registration of a used car — imports and domestic changes of keeper alike — and the files cannot separate them, so it does not match this repo''s Used definition (first national registration). An open decision for the reviewer.'
- 'No brand or model: the monthly files carry no make, so there is no market_top table for Belgium. The yearly DIV files (by make and model) are booked at year end.'
- 'DIV''s files are written once and not restated (Last-Modified on the 2nd of the following month). The 2026-09 file was still missing on 2026-10-15 — DIV''s publication can slip.'
processing:
- title: Download
  text:
  - The fetcher asks the file server for the monthly CSVs by name (YYYYMM_Immatriculations-Inschrijvingen.csv), starting three months before the last DIV month in the CSV and stepping forward until the server answers 404 ("not published yet"). There is no directory listing. A run whose target month is already a DIV row in every CSV makes no request; a backfill also reads the 28 MB history file 2013–2024.
- title: Pick the vehicles
  text:
  - Each file is an aggregate — one row per month, new or used vehicle, new or reused plate, keeper type, engine-size band, use group and fuel, with a count. Only new vehicles are counted; the use group decides the variant and, for passenger cars, the keeper type decides Private or Industry.
  decision:
    ask: New Vehicle Flag?
    branches:
    - when: Used vehicle
      then: in no variant (imports and domestic resales cannot be told apart)
    - when: New vehicle
      then:
        ask: Vehicle use group?
        branches:
        - when: Passenger car
          then:
            ask: Keeper type?
            branches:
            - when: Natural/Legal Person (not VAT-registered)
              then: Whole + Private
            - when: Legal Person (VAT)
              then: Whole + Industry
        - when: Light goods vehicle
          then: Vans
        - when: Lorry, Tractor unit for semitrailer
          then: HDV
        - when: Bus
          then: Buses
        - when: trailers, caravans, motorcycles, agricultural and special vehicles, motor caravans
          then: in no variant
- title: Powertrain
  text:
  - DIV's fuel field ("Fuel Plus") decides the column. Plug-in hybrids and other hybrids have values of their own; DIV does not tell full from mild hybrids.
  decision:
    ask: Fuel Plus?
    branches:
    - when: Electricity
      then: BEV
    - when: Plug-in Hybrid Petrol / Gasoil / LPG / …
      then: PHEV
    - when: Hybrid Petrol / Gasoil / LPG
      then: HEV
      note: full and mild hybrids together
    - when: Petrol
      then: PETROL
      note: no hybrids
    - when: Gasoil
      then: DIESEL
      note: no hybrids
    - when: LPG, CNG, LNG, Hydrogen, Other, empty
      then: OTHERS
- title: Checks before writing
  text:
  - The header must be exactly DIV's 14 columns and every row of a monthly file must belong to that month. Unknown use-group, fuel, keeper or vehicle-flag values may not exceed 2 % of a month (below that they go to OTHERS with a warning). A Whole month below a quarter of the usual volume is not written. Whole is compared with the ACEA row it replaces and the difference reported (more than 2 % is flagged); it is not enforced, because three of ACEA's Belgian rows were wrong.
fetcher: scripts/fetch_belgium.py
workflow: .github/workflows/fetch-belgium.yml
fragility_doc: docs/architecture/59-source-belgium.md
data_file: data/Belgium.csv
---

# 59 — Source: Belgium (FPS Mobility / DIV)

**TL;DR.** Belgium moved from ACEA to the FPS Mobility and Transport's own
monthly registration files (DIV, the vehicle registration service). They are
open data (CC0), ~220 KB a month, on a plain file server, published on the 2nd
of the following month — about three weeks before ACEA — and they are what
ACEA's Belgian figure is built from: Whole runs ~0.4 % above ACEA every month,
BEV agrees within ~30 cars. They add `Private` / `Industry` (VAT-registered
keeper) and turn Vans / HDV / Buses from quarterly ACEA reconstructions into
monthly series, all from 2013-01. Hybrids are split into plug-in (PHEV) and
non-plug-in (HEV, full + mild together).

## 1. Where the files are

The open-data page "Inschrijvingen van voertuigen" shows the monthly figures
as a Power BI report; its last page ("Downloaden") links the source files:

```
https://datafiles.mobilit.belgium.be/OPENDATA/DGTRSR/MonthlyRegistrations/
    YYYYMM_Immatriculations-Inschrijvingen.csv      202501 … (one per month)
    2013_2024_Immatriculations-Inschrijvingen.csv   history 2013-01 … 2024-12
```

* The web page (`mobilit.belgium.be`, also `statbel.fgov.be`) is behind an F5
  bot challenge with a CAPTCHA for scripts — from the sandbox and from GitHub
  runners alike. The **file server is not**: plain `200 text/csv`, no cookie,
  no challenge (checked 2026-10-15 from the sandbox).
* There is no directory listing (`/` and the folder answer 404), so the
  fetcher probes the name pattern forward; 404 = not published yet.
* Publication: each monthly file's `Last-Modified` is the 2nd of the following
  month at ~16:00 UTC (202606 → 2026-07-02, 202607 → 2026-08-02, 202608 →
  2026-09-02). Files are written once, not restated. **202609 was still 404 on
  2026-10-15** — DIV can be late, which is why the cron runs to the 20th and
  ACEA stays as a fallback.
* Licence: the FPS Mobility publishes its open data under CC0 (data.gov.be
  dataset 52ea177d…cdfe, "Inschrijvingen van voertuigen (maandelijks)").

## 2. Schema (14 columns, identical in every file)

| column | values |
|---|---|
| Month End Date | `2026-08-31 23:59:59` — the month |
| New Plate Flag Label | New Plate / Plate reused |
| New Vehicle Flag Label | New vehicle / Used vehicle |
| Titular Type Label | Legal Person (VAT) / Natural/Legal Person |
| Cylinder Capacity Range | `'-`, `0001-0799` … `3000+` |
| Vehicle Use Group Fr / Nl / De / En | Passenger car, Light goods vehicle, Lorry, Tractor unit for semitrailer, Bus, Trailer, Semi-trailer, Motor caravan, Agricultural vehicle, Light / Heavy two-, three- or four-wheel vehicle, Special purpose vehicle, `~?~`, Undetermined |
| Fuel Plus Fr / Nl / De / En | Electricity, Petrol, Gasoil, Hybrid Petrol, Hybrid Gasoil, Hybrid LPG, Plug-in Hybrid Petrol / Gasoil / LPG / CNG / Other, LPG, CNG, LNG, Hydrogen, Other, empty |
| N Rowcount | registrations |

The fetcher reads the English columns.

## 3. Mapping

See the processing block above (it renders as the decision tree on the source
page). Points worth knowing:

* **Plates follow the owner in Belgium.** A new car registered on a plate
  transferred from the keeper's previous car is "Plate reused" but still a new
  vehicle — both plate flags count (about 25–30 % of new cars). Counting only
  "New Plate" would undercount Whole by ~30 %.
* **Keeper type** is VAT-based: "Legal Person (VAT)" → Industry; "Natural/Legal
  Person" (no VAT number) → Private. In 2026 Industry is 54 % of new cars (61 %
  BEV), Private 46 % (11 % BEV).
* **Hybrids**: DIV distinguishes plug-in from non-plug-in, but not full from
  mild hybrids, so HEV = full + mild.

## 4. Validation

### 4.1 Against ACEA (Whole)

ACEA's monthly Belgian rows 2022-10 … 2026-08 (44 comparable months):

| | DIV − ACEA |
|---|---|
| TOTAL | +86 … +251 cars, median +155 (~0.4 %), never below — except 2025-04 (−5,075: DIV's file is short, below) |
| BEV | 0 … +34 cars |
| PHEV | median −1 %; 2025–2026 DIV 1–13 % lower |
| HEV | DIV ~2.5× higher (mild hybrids — ACEA files them under petrol/diesel) |

Two ACEA rows in the repo were wrong and are corrected by DIV: 2023-02
(2,291 — DIV 40,056) and 2023-09 (2,965 — DIV 39,034). 2026-07 is an ACEA
row derived from a year-to-date difference (ACEA had no July release); its
PHEV is 24 % above DIV.

**2025-04 is a short DIV file, not an ACEA error.** DIV has 32,737 cars,
ACEA 37,812 — and ACEA's figure is its own year-to-date difference
(Jan–Apr 158,751 − Jan–Mar 120,939). Over 2025 DIV is 3,386 below ACEA
(411,384 vs 414,770) although it is ~0.4 % *above* in every other month, and
the CV quarter holding April 2025 is 3–5 % low in Vans, HDV and Buses alike.
The DIV rows stay (their HEV includes mild hybrids like the rest of the
series; an ACEA row would put a one-month HEV dip into it), and their notes
say `CHECK`. Since 2026-10 the fetcher raises a `::warning::` and writes the
same remark when a month it writes over an ACEA row is more than 2 % off.

### 4.2 Against ACEA's CV quarters (Vans / HDV / Buses)

| quarter | Vans DIV / ACEA | HDV DIV / ACEA | Buses DIV / ACEA |
|---|---|---|---|
| 2024-Q1 | 18,264 / 18,211 | 2,798 / 2,779 | 265 / 265 |
| 2025-Q1 | 20,266 / 20,247 | 2,765 / 2,739 | 300 / 299 |
| 2025-Q2 | 18,506 / 19,146 | 2,187 / 2,284 | 519 / 544 |
| 2026-Q1 | 18,886 / 18,870 | 2,390 / 2,379 | 328 / 328 |
| 2026-Q2 | 18,605 / 18,585 | 2,292 / 2,279 | 291 / 290 |

DIV is ACEA's source for commercial vehicles too.

## 5. Variants and files

| file | variant | from |
|---|---|---|
| `data/Belgium.csv` | Whole | 2013-01 |
| `data/Belgium_Private.csv` | Private (new) | 2013-01 |
| `data/Belgium_Industry.csv` | Industry (new) | 2013-01 |
| `data/Belgium_Vans.csv` | Vans | 2013-01 |
| `data/Belgium_HDV.csv` | HDV | 2013-01 |
| `data/Belgium_Buses.csv` | Buses | 2013-01 |
| `data/Belgium_legacy.csv` | the former ACEA rows (Whole quarterly 2018–2022, all CV rows) — an archive, not a series | — |

January–August 2026: Whole 289,454 (BEV 37.7 %, PHEV 5.4 %, HEV 33.3 %),
Private 134,120, Industry 155,333, Vans 47,229 (BEV 7.4 %), HDV 5,791, Buses
864 (BEV 20.7 %).

## 6. Open decisions

* **Used.** DIV's "Used vehicle" (~55,000 passenger cars a month in 2026) mixes used imports
  with domestic changes of keeper, so it is left out. A `Resale`-style variant
  (all used-car registrations) would be possible if wanted.
* **HEV = full + mild.** Kept as DIV reports it (counted, not derived). The
  alternative — splitting HEV with ACEA's full-hybrid count — would mix a
  derived figure into a counted series.
* **params.csv** still holds the ACEA-era fits for Belgium Whole / Vans / HDV
  / Buses; the history now starts in 2013 and is monthly throughout, so a
  `backtest_only` refit is due.

## 7. ACEA's role

`fetch_acea.py`: Belgium moved from the always-list to the conditional list —
ACEA writes a Belgian month only when no DIV row exists yet, and the next DIV
run replaces it (`REPLACEABLE = {"ACEA"}`). `fetch_acea_cv.py`: Belgium left the
roster; its self-throttle sentinel is now Germany.

## 8. Runbook

| symptom | check |
|---|---|
| "not published yet (404)" for days after the 2nd | open the Power BI report's "Downloaden" page in a browser — did the file name pattern change? |
| "unexpected header" | DIV changed the schema: compare the new header with `HEADER` in the fetcher |
| "got an HTML page, not a CSV" | the file server now has the bot challenge too — run from a browser, report upstream |
| "unknown values" | a new fuel / use-group label: add it to `FUEL_CLASS` / `USE_VARIANT` / `USE_IGNORED` and a test |
| `::warning:: Belgium YYYY-MM vs ACEA` / notes say CHECK | DIV is more than 2 % off the ACEA row it replaced. Check ACEA's month against its year-to-date difference: if ACEA is consistent, DIV's file is short (as 2025-04) — the row stays, flagged; if ACEA is not, ACEA was wrong (as 2023-02 / 2023-09) |

```mermaid
sequenceDiagram
  participant GH as fetch-belgium.yml (cron 2nd–20th)
  participant F as fetch_belgium.py
  participant D as datafiles.mobilit.belgium.be
  participant R as render-country.yml
  GH->>F: tests, then run
  F->>F: target month DIV in every CSV? → stop, no HTTP
  loop from 3 months before the last DIV month
    F->>D: GET YYYYMM_Immatriculations-Inschrijvingen.csv
    D-->>F: 200 CSV / 404 → stop
  end
  F->>F: schema, month, unknown-value and volume guards
  F->>F: line-level upsert of the 6 CSVs (ACEA rows replaceable)
  GH->>R: dispatch once with the changed variants
```
