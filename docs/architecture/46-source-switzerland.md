---
country: Switzerland
slug: switzerland
method: file
summary: New-vehicle registration data for Switzerland (with Liechtenstein) straight from
  the national vehicle register IVZ — ASTRA's open-data extracts, one row per vehicle with
  its EU vehicle class, fuel and hybrid type — calibrated to reproduce ACEA's Swiss figure
  about three weeks before ACEA publishes it.
source_name: ASTRA — IVZ vehicle register, open data (Neuzulassungen / Gebrauchtimporte)
source_url: https://www.astra.admin.ch/de/fahrzeugdaten
source_links:
- label: ASTRA open-data directory (IVZ extracts)
  url: https://opendata.astra.admin.ch/ivzod/
  note: NEUZU.txt (new registrations of the running year, refreshed every two weeks) and GEBR.txt (used imports, monthly), plus closed years
- label: ASTRA — overview of the vehicle-data information products (PDF)
  url: https://www.astra.admin.ch/dam/de/sd-web/BakiDqfaJMx8/01%20%C3%9Cbersicht%20Informationsprodukte%20Fahrzeugdaten-20260701.pdf
  note: field definitions, publication rhythm, and how new registrations and used imports are told apart (§3.4)
- label: ACEA — monthly new-car registrations
  url: https://www.acea.auto/
  note: the reference the Swiss series is checked against every month
underlying: IVZ (Informationssystem Verkehrszulassung) — the national register of the cantonal road-traffic offices, run by ASTRA (Federal Roads Office)
auth: none
cadence: twice daily on the 1st–6th — ASTRA posts the new snapshot on the 1st; a month is written once, from the first snapshot after it ends
variants:
- Whole
- Vans
- HDV
- Buses
- 2-Wheelers
- Used
variant_notes:
  Whole: New passenger cars — register vehicle kind Personenwagen (EU M1). Campers and other M1 "light motor vehicles" are not cars and are left out, as at ACEA.
  Vans: New light goods vans — EU N1 with vehicle kind Lieferwagen (≤ 3.5 t).
  HDV: New lorries and tractor units — EU N2/N3 with vehicle kind Lastwagen or Sattelschlepper (> 3.5 t). Work machines on a truck chassis are left out.
  Buses: New buses and coaches — EU M2/M3 over 3.5 t gross weight (ACEA's definition).
  2-Wheelers: New mopeds and motorcycles — EU L1 + L3. Trikes, sidecar combinations and quads are left out.
  Used: Used passenger cars at their first Swiss registration — used imports (first registered abroad), dated by the month they entered the Swiss register.
hev_split: true
hev_note: PHEV and HEV come from the register's own hybrid code (off-vehicle-charging vs not). HEV includes mild hybrids, as ACEA's does. Range-extender EVs are counted as PHEV. Vehicles on an older national type approval carry no hybrid code; there, a recorded electric consumption or CO2 of at most 60 g/km marks a plug-in.
backfill: Whole keeps its history (BFS from 2010, ACEA in 2026) and is written from ASTRA from 2026-09; Vans, HDV, Buses and 2-Wheelers from 2016-01, Used from 2017-01, all from the register's year files
scope_note: First registrations in Switzerland and Liechtenstein (one register, one market — ACEA's Swiss figure includes Liechtenstein). Vehicles taken off the road since are still counted in the month they were registered new.
caveats:
- A month is attributed the way ACEA attributes it: a car keyed into the register after the month closed (late registrations, typically after a quarter-end push) counts in the next month written. Every row is written once and never revised, so monthly figures can differ from a later look at the register by a few hundred cars while the year totals agree.
- The Whole history before 2026-09 is not from ASTRA. Up to 2026-03 it is BFS (the Federal Statistical Office), from 2026-04 ACEA. In 2025 the BFS months run about 5 % above ACEA's figures for the same months (BEV about 2,300 cars over the year); the BEV share is barely affected.
- Vans, HDV and Buses were quarterly ACEA figures before (with BEV and PHEV merged into one "electrically chargeable" number); they are now monthly register counts with a real BEV/PHEV split, back to 2016. The old ACEA series is kept as an archive (data/Switzerland_legacy.csv).
- Before 2022 the register has no hybrid code; plug-ins of that period are recognised by CO2 alone, which under-counts some 2019 PHEVs by up to a third (a small series then).
processing:
- title: Download
  text:
  - ASTRA restates the whole running year in one file on every refresh, one row per vehicle (about 270,000 rows by September). The fetcher first reads only the first 16 KB — the header and one row — to see which month the snapshot is complete to; only when a CSV lacks that month does it download the file (about 90 MB of new registrations, about 15 MB of used imports).
- title: Pick the vehicles
  text:
  - Each record carries its EU vehicle class and the register's vehicle kind; together they decide the variant. Switzerland and Liechtenstein are one register and are counted together, as ACEA does. Vehicles taken off the road since still count in the month they were registered new.
  rules_head: [Register record, Variant]
  rules:
  - ["Vehicle kind Personenwagen (EU class M1) — campers and other M1 \"light motor vehicles\" are not cars and stay out", Whole]
  - ["EU class N1 and vehicle kind Lieferwagen", Vans]
  - ["EU class N2 or N3 and vehicle kind Lastwagen or Sattelschlepper (lorries, tractor units)", HDV]
  - ["EU class M2 or M3 with a gross weight over 3.5 t", Buses]
  - ["EU class L1 (moped) or L3 (motorcycle)", 2-Wheelers]
  - ["Used-import file (first registered abroad) and vehicle kind Personenwagen", Used]
  - ["Anything else — trailers, tractors, work machines, quads, trikes, minibuses up to 3.5 t", in no variant]
- title: Powertrain
  text:
  - The register states the fuel and, for hybrids, whether the battery can be charged from the grid. The rules below are tested from top to bottom and the first match decides. Only vehicles approved under the older national type approval have no hybrid code (roughly a third of the hybrids in 2026); for them a recorded electric consumption or a CO2 value of at most 60 g/km marks a plug-in.
  rules_head: [Register fuel and hybrid code, Column]
  rules:
  - ["Fuel E — electric", BEV]
  - ["Fuel R — electric with range extender", PHEV]
  - ["Fuel petrol/diesel + electric, hybrid code OVC-HEV (chargeable from outside)", PHEV]
  - ["Fuel petrol/diesel + electric, hybrid code NOVC-HEV (not chargeable — full and mild hybrids)", HEV]
  - ["Fuel petrol/diesel + electric, no hybrid code, electric consumption recorded", PHEV]
  - ["Fuel petrol/diesel + electric, no hybrid code, CO2 at most 60 g/km", PHEV]
  - ["Fuel petrol/diesel + electric, no hybrid code, otherwise", HEV]
  - ["Fuel B — petrol", PETROL]
  - ["Fuel D — diesel", DIESEL]
  - ["Anything else (hydrogen, petrol/gas bi-fuel, …)", OTHERS]
- title: Month
  text:
  - A month is written once, from the first snapshot after it ends — the way ACEA counts it. A car keyed into the register after its month closed (typically after a quarter-end push) is added to the next month written, so year totals agree with ACEA and no written month is ever revised. Closed years (the history back to 2016) are counted by registration month from ASTRA's year files.
- title: Check against ACEA
  text:
  - ACEA is the reference. When ACEA publishes the month (third to fourth week), the newest months are compared with ACEA's Swiss figure; a gap above 1 % in the total, or 3 % in one fuel, raises a warning. Over 2025-01 to 2026-08 (19 releases, 366,000 cars) the register reproduces ACEA to −0.02 % in total and +0.1 % in BEV.
market_breakdown: market/switzerland_top.json
market_designation_note: the model is the register's type designation (Typ2, completed by Typ3 where Typ2 alone is a number or "Model"), upper-cased — e.g. ENYAQ, MODEL Y, 5 E-TECH.
market_powertrain_note: BEV / PHEV / HEV exactly as in the CSV (register fuel + hybrid code); HEV includes mild hybrids.
fetcher: scripts/fetch_switzerland.py
workflow: .github/workflows/fetch-switzerland.yml
fragility_doc: docs/architecture/46-source-switzerland.md
data_file: data/Switzerland.csv
---

# 46 · Source: Switzerland (ASTRA IVZ open data)

**Status: LIVE since 2026-10.** Fetcher `scripts/fetch_switzerland.py` (+ tests
`scripts/test_fetch_switzerland.py`), workflow `.github/workflows/fetch-switzerland.yml`,
ACEA cross-check `.github/workflows/check-switzerland-acea.yml`. Replaces ACEA as the
writer of every Switzerland CSV; ACEA stays the reference the numbers are checked against.

## TL;DR

```
Source:    ASTRA open data, opendata.astra.admin.ch/ivzod/1000-Fahrzeuge_IVZ/
             1200-Neuzulassungen/1210-Datensaetze_monatlich/NEUZU.txt   (~90 MB)
             1500-Gebrauchtimporte/GEBR.txt                              (~15 MB)
           + closed years NEUZU-<YYYY>.txt (2016+), GEBR-<YYYY>.txt (2017+)
           Tab-separated UTF-8, one row per vehicle: EU class, vehicle kind,
           make/type, fuel code, hybrid code, CO2, el. consumption, month.
Auth:      None. The WAF wants a full browser UA + an Accept header.
Timing:    NEUZU refreshed on the 1st (data to the last day of the month) and
           mid-month; GEBR on the 1st. September 2026 was in the 1 October
           snapshot — ACEA publishes the same month around the 22nd.
Variants:  Whole · Vans · HDV · Buses · 2-Wheelers (NEUZU) · Used (GEBR)
Month:     the ACEA rule — written once from the first snapshot after the
           month; late registrations of earlier written months of the year
           flow into it (§5). History by registration month (§5b).
Check:     ACEA. 2025-01..2026-08 (19 releases, 366k cars): total −0.02 %,
           BEV +0.11 %, PHEV −0.20 %, HEV +0.11 %, petrol +0.13 %,
           diesel −1.5 % (§4).
```

## 1. Why this source clears the bar

Before 2026-10 Switzerland was an ACEA "conditional" country (`fetch_acea.py`), with the
history from the Federal Statistical Office's PxWeb table `px-x-1103020200_101`. That made
it one of the gallery's most hand-held countries:

- **BFS's table is gone** from PxWeb (the API lists no `px-x-1103…` database any more), so
  the BFS rows stopped in 2026-03 and ACEA took over.
- **ACEA is three weeks late** and **has no July release** — the 2026-07 row had to be derived
  by hand from year-to-date sums (and was off: PHEV 2,413 vs the register's 2,599).
- **Vans/HDV/Buses** were quarterly ACEA commercial-vehicle figures with BEV and PHEV merged.

ASTRA's register extracts are the primary source behind every one of those numbers
(auto-schweiz, and through it ACEA, count the same register). They are free, record-level,
carry the EU vehicle class directly, and are out on the 1st of the following month.

## 2. Record → CSV row

| File | Keys used |
|---|---|
| NEUZU | `Fahrzeugklasse` (EU class), `Fahrzeugart` (vehicle kind), `Gesamtgewicht`, `Treibstoff_Code`, `Hybridcode`, `El-Verbrauch`, `CO2-WLTP`/`CO2-NEFZ`/`CO2`, `Erstinverkehrsetzung_Jahr`/`_Monat`, `Marke`, `Typ1..3`, `Datenstand`, `Neuzulassungen_bis` |
| GEBR | the same, but the month is `Ersterfassung_Jahr`/`_Monat` (first Swiss registration; `Erstinverkehrsetzung` is the first registration abroad) |

NEUZU holds only new vehicles (ASTRA's split, §3.4 of its product overview: no used code,
first registration in CH or FL); GEBR holds the used imports. The files restate the running
year on every refresh; in January NEUZU still holds the whole previous year.

The 2011–2015 archive files (`NEUZU_ARCHIV-*`) have no EU class and no hybrid data and are
not used.

## 3. Variants

| Variant | Filter | ACEA counterpart |
|---|---|---|
| `Whole` | `Fahrzeugart = Personenwagen` (EU class M1, or blank on a handful of old records) | new passenger cars |
| `Vans` | `Fahrzeugklasse = N1` ∧ `Fahrzeugart = Lieferwagen` | vans ≤ 3.5 t |
| `HDV` | `Fahrzeugklasse ∈ {N2, N3}` ∧ `Fahrzeugart ∈ {Lastwagen, Sattelschlepper}` | trucks > 3.5 t |
| `Buses` | `Fahrzeugklasse ∈ {M2, M3}` ∧ `Gesamtgewicht > 3500` | buses & coaches > 3.5 t |
| `2-Wheelers` | `Fahrzeugklasse ∈ {L1, L3}` | — (as Spain's) |
| `Used` | GEBR ∧ `Fahrzeugart = Personenwagen` | — |

In no variant: M1 "Leichter/Schwerer Motorwagen" (campers, special vehicles), N1 work
machines and small tractor units, N2/N3 work machines, M2 minibuses ≤ 3.5 t, L2/L4–L7,
trailers, agricultural and industrial vehicles.

Each filter was chosen among the plausible readings of the EU class by its distance to
ACEA (§4) — the EU class alone (all N1, all N2/N3, all M2/M3) is 1–4 % off in every case.

## 4. Calibration against ACEA

ACEA is the maintainer's reference. Comparisons below use the ASTRA snapshot of
2026-10-01 (and the 2025 year file) against every ACEA release of 2025–2026 (monthly car
PDFs; commercial-vehicle checkpoints Q1/H1/Q1-Q3/FY).

**Whole, 19 months 2025-01 … 2026-08 (no ACEA July):** −89 cars on 366,335 (−0.02 %);
by fuel BEV +95 (+0.11 %), PHEV −86 (−0.20 %), HEV +141 (+0.11 %), petrol +111 (+0.13 %),
diesel −347 (−1.5 %). Most months are within ±0.5 %. The exceptions are month boundaries, not definitions —
2025-06 +822 / 2025-07 −1,207 (30 June 2025 was a quarter-end Monday with 2,321 cars),
2025-12 −500, 2026-06 +265. ACEA prints last year's months unchanged a year later, so it
never revises them.

**Year to date 2026, ASTRA (snapshot 1 Oct) − ACEA:**

| through | BEV | PHEV | HEV | Petrol | Diesel | Total |
|---|---|---|---|---|---|---|
| Mar | +7 | +22 | +27 | +73 | −2 | +127 (+0.24 %) |
| Jun | +125 | −18 | +187 | +79 | 0 | +373 (+0.32 %) |
| Aug | +86 | +216 | −102 | +43 | −27 | +216 (+0.14 %) |

The positive remainder is late registrations keyed in after ACEA's cut-off. The PHEV/HEV
swing in July–August (about 200 cars) is classification: ACEA counts some July 2026
plug-ins (new models on a national type approval, e.g. Leapmotor B10 range extenders) as
HEV. It has no July release to compare against month by month.

**Commercial vehicles, cumulative checkpoints (Total; BEV+PHEV within ±10 at every checkpoint except Vans FY 2025, −31):**

| | 2025 H1 | 2025 Q1-Q3 | 2025 FY | 2026 Q1 | 2026 H1 |
|---|---|---|---|---|---|
| Vans (N1 Lieferwagen) | −20 | −171 | −208 | −1 | −100 |
| HDV (N2/N3 lorries + tractors) | −6 | −162 | −247 | +1 | −6 |
| Buses (M2/M3 > 3.5 t) | −1 | −15 | −23 | −1 | −4 |

The 2025 second-half gap of Vans and HDV is all diesel (ACEA higher); 2026 is close to exact.

**Ruled out** (each made the match worse): excluding Liechtenstein, military or diplomatic
plates, vehicles taken off the road, or used-code A; including M1 campers.

The cross-check runs every month (`check-switzerland-acea.yml`, 23rd–28th): it compares the
newest ASTRA months of `Switzerland.csv` with ACEA's release and annotates a gap beyond 1 %
(total) or 3 % (a fuel with ≥ 200 cars) as a warning. Nothing is written.

## 5. Month attribution

### 5a. Live months — the ACEA rule

ACEA's Swiss month is a year-to-date total at a cut-off shortly after month end, differenced
against the previous month's. A car registered on 30 June but keyed in on 2 July counts in
July there, while the register dates it 30 June. To reproduce that, `flow_months()` writes
month M **once**, from the first snapshot after M ends:

    M = snapshot count of M  +  Σ over the year's months already written by ASTRA
                                 (snapshot count − CSV row)

Late registrations flow forward into the next written month; no written row is revised
(invariant 3). Rows from another source (the BFS/ACEA history of Whole) are not differenced:
their gap to the register is definition and classification, not late registrations. So the
first ASTRA month of Whole (2026-09) starts without a carry-over, and January starts every
year fresh — as ACEA's January does. A carry-over above 3 % of the month is written but
raised as a workflow warning.

### 5b. History — by registration month

Closed years have no snapshots left, so the backfill counts them by registration month from
the year files (`--backfill`), and the running year's months from the current snapshot.
Only months a CSV does not have yet are written.

## 6. Fuel mapping

| Register | Column |
|---|---|
| `E` Elektrisch | BEV |
| `R` Elektrisch mit Range Extender | PHEV (no EREV column — ACEA counts them as PHEV) |
| `C`/`F` Benzin/Diesel / Elektrisch, Hybridcode `OVC-HEV` | PHEV |
| `C`/`F`, Hybridcode `NOVC-HEV` | HEV (full and mild hybrids) |
| `C`/`F` without hybrid code | PHEV if `El-Verbrauch` > 0 or CO2 ≤ 60 g/km, else HEV |
| `B` Benzin | PETROL |
| `D` Diesel | DIESEL |
| anything else (hydrogen, LPG/CNG bi-fuel, …) | OTHERS |

Vehicles registered through an electronic CoC (most since 2022) carry the hybrid code;
vehicles on an older national type approval do not. Without the CO2 rule the PHEV count for
January–April 2025 is 435 below ACEA's (with it: −36).

## 7. History and archives

- **`data/Switzerland.csv`** keeps its rows: BFS 2010-01 … 2026-03 (`pxweb.bfs.admin.ch /
  ACEA`), ACEA 2026-04 … 2026-08 (2026-07 derived), ASTRA from 2026-09. The 2025 BFS months
  are about 5 % above ACEA's own figures for those months (BFS counted differently); they are
  left as they are (invariant 3). Rebuilding the history from ASTRA's year files is possible
  back to 2016 (PHEV by CO2 before 2022).
- **`data/Switzerland_legacy.csv`** — the quarterly ACEA commercial-vehicle rows that were
  `Switzerland_Vans/HDV/Buses.csv` until 2026-10, parked byte for byte. Never rendered
  (`ARCHIVE_VARIANTS`, `R/build_backtest.R` skips `_legacy` files).
- `fetch_acea.py` and `fetch_acea_cv.py` no longer write Switzerland.

## 8. Outputs

| File | Content |
|---|---|
| `data/Switzerland.csv` | Whole |
| `data/Switzerland_Vans.csv`, `_HDV.csv`, `_Buses.csv`, `_2-Wheelers.csv`, `_Used.csv` | the variants |
| `market/switzerland_top.json` | top BEV/PHEV/HEV brands and models, trailing 12 months + per month (Whole) |
| `market/switzerland_months.json` | the month store behind it (electrified brand/model counts per month) |

## 9. Operations and debugging

- **Nothing new on the 1st?** ASTRA posted the 2026-10-01 snapshot at 10:33 Swiss time; the
  runs at 09:20 and 15:20 UTC on the 1st–6th cover a late upload. The script reads only the
  first 16 KB (header + first row: `Datenstand`, `Neuzulassungen_bis`) and exits when every
  CSV has the newest complete month.
- **HTTP "Request Rejected" page:** the WAF blocks a bare `Mozilla/5.0` UA and requests
  without an `Accept` header — keep `HTTP_HEADERS`.
- **A month is wrong:** rows are never revised automatically. Delete the row (and every later
  ASTRA row of that year) and dispatch the workflow: the next run re-derives them by the
  ACEA rule. `force` overwrites rows from other sources.
- **New variant or rebuilt history:** dispatch with `backfill` (and `backfill_from`); only
  missing months are written.
- **ACEA disagrees:** the cross-check names the month and fuel. Late registrations show as a
  positive total; a PHEV/HEV swing of the same size in opposite directions is
  classification (§4).
- Local run: `python scripts/fetch_switzerland.py [--variant Vans] [--backfill --from 2016]
  [--acea-check]`.
