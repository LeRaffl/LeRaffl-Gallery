# market/

**Generated — never hand-edit.** One `<slug>_top.json` per country whose
source carries brands (and usually models): the trailing-twelve-month top
brands and models per electrified class (BEV / PHEV / EREV / HEV / MHEV), plus
one ranking per single month (`months`, newest first).

| file | written by |
|---|---|
| `spain_top.json` | `scripts/fetch_spain.py` (DGT `MARCA_ITV` / `MODELO_ITV`, Whole) |
| `malaysia_top.json` | `scripts/fetch_malaysia.py` (data.gov.my `maker` / `model`) |
| `ukraine_top.json` | `scripts/fetch_ukraine.py` (MIA register `BRAND` / `MODEL`, Whole; BEV, PHEV, EREV, HEV — plug-ins via `classification/ecuador_rules.csv`) |
| `hong_kong_top.json` | `scripts/fetch_hong_kong.py` (TD `Vehicle Make` / `Vehicle Model`, Whole; BEV + classified PHEV/EREV; trims merged for display) |
| `peru_top.json` | `scripts/fetch_peru.py` (AAP BI-AAP `Marca` / `Modelo` from SUNARP, Whole; BEV / PHEV / HEV / MHEV) |
| `paraguay_top.json` + `paraguay_months.json` | `scripts/fetch_paraguay.py` (customs `MARCA ITEM` / designation from the free-text description, new cars imported for consumption; BEV / PHEV / HEV from the tariff subheading) |
| `ecuador_top.json` | `scripts/fetch_ecuador.py` (SRI register `MARCA` / start of the catalogue description `MODELO`, Whole; BEV + combined Hybrid) |
| `taiwan_top.json` | `scripts/fetch_taiwan.py` (MOTC statistics database, THB brand table — new passenger cars by brand; brands only, **every powertrain in one class `ALL`**: THB has no brand × fuel table) |
| `uk_top.json` (+ `uk_months.json`) | `scripts/fetch_uk.py` (SMMT vehicle-data page — marque table and top-10 models of new cars; **every powertrain in one class `ALL`**: SMMT's brand table has no fuel split; headline January-to-date from SMMT's own year-to-date tables, single months from the month store) |
| `georgia_top.json` | `scripts/fetch_georgia.py` (Geostat «Automobile» portal API, `mobile/treemap` — vehicles initially registered in Georgia by brand and model, top 25 brands per quarter; **every powertrain and vehicle category in one class `ALL`**, new and imported used; the last four quarters summed) |
| `norway_top.json` (+ `norway_months.json`) | `scripts/fetch_norway.py` (OFV's monthly release — top-30 brands and top-30 models of new passenger cars; **every powertrain in one class `ALL`**: OFV's brand table has no fuel split, and ~98 % of the market is BEV) |
| `austria_top.json` | `scripts/fetch_austria.py` (DE2 Tabelle 7 / 14 — top 10 BEV makes and types; year-to-date headline) |
| `ireland_top.json` | `scripts/fetch_ireland.py` (SIMI dashboard make / model rankings per engine type) |
| `czechia_top.json` + `czechia_months.json`, `czechia_used_top.json` + `czechia_used_months.json` | `scripts/fetch_czechia.py` (RSV register `Tovární značka` / `Obchodní označení`, Whole and Used; BEV / PHEV only — the register cannot identify full and mild hybrids) |
| `greece_top.json` + `greece_months.json` | `scripts/fetch_greece.py` (SEAA's BEV / PHEV PDFs: make / "Range"; BEV / PHEV only — SEAA publishes hybrids as a share) |
| `lithuania_top.json`, `lithuania_used_top.json` (+ `lithuania_fleet.json`, the PHEV/HEV split store) | `scripts/fetch_lithuania.py` (Regitra open register snapshot `MARKE` / `KOMERCINIS_PAV`, Whole and Used; BEV / PHEV / HEV from the EU hybrid category; cars still registered on the snapshot date) |
| `finland_top.json` | `scripts/fetch_finland.py` (Traficom PxWeb make and model-series tables) |
| `israel_top.json` | `scripts/fetch_israel.py` (registry `tozeret_nm` translated from Hebrew / `kinuy_mishari`, Whole; BEV / PHEV / HEV) |
| `portugal_top.json` + `portugal_months.json` | `scripts/fetch_portugal.py` (motordata `result_table` brands; brands only; January-to-date headline, months accumulate) |
| `netherlands_top.json` + `netherlands_months.json` | `scripts/fetch_netherlands.py` (RDW open-data register `merk` / `handelsbenaming` + fuel table; new passenger cars; BEV / PHEV; trim codes stripped for display) |
| `netherlands_used_top.json` + `netherlands_used_months.json` | the same script, imported used passenger cars (Used variant); shown as a second section via front-matter `market_breakdown_extra` |
| `japan_top.json` + `japan_months.json` | `scripts/fetch_japan.py` (JADA maker rows; brands only, imports one row) |
| `singapore_top.json` + `singapore_months.json` | `scripts/fetch_singapore.py` (LTA M03 makes; brands only) |
| `uruguay_top.json` + `uruguay_months.json` | `scripts/fetch_uruguay.py` (ACAU Compilado `Marca` / `Modelo`, AUTOS + SUV) |

`<slug>_months.json` is the **month store** of a source whose files only
carry a few recent months: per-month electrified brand/model counts the
fetcher accumulates and rebuilds `<slug>_top.json` from. Also generated.

Argentina's equivalent is `classification/argentina_top.json` (same schema).

All of them go through the shared builder `scripts/market_top.py`, so the
schema is identical; the country's source page renders the file when its
front-matter has `market_breakdown: market/<slug>_top.json`, and
`build-source-pages.yml` rebuilds on `market/**`.
Schema, behaviour and how to add a country:
[docs/architecture/03-data-objects.md §3.16](../docs/architecture/03-data-objects.md#316-top-brands--models-market).
