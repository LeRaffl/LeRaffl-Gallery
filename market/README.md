# market/

**Generated — never hand-edit.** One `<slug>_top.json` per country whose
source carries brand + model per registration: the trailing-twelve-month top
brands and models per electrified class (BEV / PHEV / EREV / HEV / MHEV).

| file | written by |
|---|---|
| `spain_top.json` | `scripts/fetch_spain.py` (DGT `MARCA_ITV` / `MODELO_ITV`, Whole) |
| `malaysia_top.json` | `scripts/fetch_malaysia.py` (data.gov.my `maker` / `model`) |
| `ukraine_top.json` | `scripts/fetch_ukraine.py` (MIA register `BRAND` / `MODEL`, Whole; BEV + combined Hybrid) |

Argentina's equivalent is `classification/argentina_top.json` (same schema).

All of them go through the shared builder `scripts/market_top.py`, so the
schema is identical; the country's source page renders the file when its
front-matter has `market_breakdown: market/<slug>_top.json`, and
`build-source-pages.yml` rebuilds on `market/**`.
Schema, behaviour and how to add a country:
[docs/architecture/03-data-objects.md §3.16](../docs/architecture/03-data-objects.md#316-top-brands--models-market).
