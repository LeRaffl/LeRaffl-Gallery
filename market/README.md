# market/

**Generated — never hand-edit.** One `<slug>_top.json` per country whose
source carries brands (and usually models): the trailing-twelve-month top
brands and models per electrified class (BEV / PHEV / EREV / HEV / MHEV), plus
one ranking per single month (`months`, newest first).

| file | written by |
|---|---|
| `spain_top.json` | `scripts/fetch_spain.py` (DGT `MARCA_ITV` / `MODELO_ITV`, Whole) |
| `malaysia_top.json` | `scripts/fetch_malaysia.py` (data.gov.my `maker` / `model`) |
| `ukraine_top.json` | `scripts/fetch_ukraine.py` (MIA register `BRAND` / `MODEL`, Whole; BEV + combined Hybrid) |
| `hong_kong_top.json` | `scripts/fetch_hong_kong.py` (TD `Vehicle Make` / `Vehicle Model`, Whole; BEV + classified PHEV/EREV; trims merged for display) |
| `peru_top.json` | `scripts/fetch_peru.py` (AAP BI-AAP `Marca` / `Modelo` from SUNARP, Whole; BEV / PHEV / HEV / MHEV) |
| `austria_top.json` | `scripts/fetch_austria.py` (DE2 Tabelle 7 / 14 — top 10 BEV makes and types; year-to-date headline) |
| `ireland_top.json` | `scripts/fetch_ireland.py` (SIMI dashboard make / model rankings per engine type) |
| `finland_top.json` | `scripts/fetch_finland.py` (Traficom PxWeb make and model-series tables) |
| `israel_top.json` | `scripts/fetch_israel.py` (registry `tozeret_nm` translated from Hebrew / `kinuy_mishari`, Whole; BEV / PHEV / HEV) |
| `portugal_top.json` + `portugal_months.json` | `scripts/fetch_portugal.py` (motordata `result_table` brands; brands only; January-to-date headline, months accumulate) |
| `netherlands_top.json` + `netherlands_months.json` | `scripts/fetch_netherlands.py` (RDW open-data register `merk` / `handelsbenaming` + fuel table; BEV / PHEV; trim codes stripped for display) |
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
