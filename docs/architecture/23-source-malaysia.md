# 23 · Source: Malaysia (data.gov.my parquet)

Malaysia's open government data portal publishes individual vehicle
registration events as annual **parquet files**, one file per calendar year,
with one row per registration. The gallery aggregates these to monthly
BEV / HEV / PETROL / DIESEL / OTHERS / TOTAL figures.

## TL;DR

```
Source:    data.gov.my — Malaysia Open Data Portal
           Catalogue: https://data.gov.my/data-catalogue/cars
Auth:      None — public download, no API key.
Format:    Parquet (pyarrow), one file per year.
           URL: https://storage.data.gov.my/transportation/cars_<YYYY>.parquet
Variants:  Whole only (all passenger cars).
HEV split: NONE. Source labels all hybrids as hybrid_petrol / hybrid_diesel
           (combined bucket; no PHEV/HEV split in historical data).
           → Türkiye/Georgia/Colombia convention: combined hybrids go in
           the HEV column, labelled "Hybrid" in the TTM split chart.
           PHEV is left empty. Counted within ICE in the BEV/ICE trajectory.
           Note: plug_in_hybrid_petrol / plug_in_hybrid_diesel fields exist
           from ~2024 and are mapped to PHEV when present.
History:   2018-01 onward (data.gov.my table start).
Schedule:  Daily 07:00 UTC, 15th–31st each month.
Scripts:   scripts/fetch_malaysia.py
Workflow:  .github/workflows/fetch-malaysia.yml
```

## 1. Source

[data.gov.my](https://data.gov.my) is Malaysia's official open data portal,
operated by the Department of Statistics Malaysia (DOSM). The `cars` catalogue
(<https://data.gov.my/data-catalogue/cars>) publishes one parquet file per
calendar year at a stable URL:

```
https://storage.data.gov.my/transportation/cars_{YYYY}.parquet
```

Each file has one row per individual vehicle registration event, with columns
including `date_reg` (registration date, `YYYY-MM-DD`), `fuel` (fuel type
string, lowercase), make, model, state, etc.

## 2. Fuel mapping

| Source `fuel` value | Gallery column | Notes |
|---|---|---|
| `electric` | `BEV` | |
| `plug_in_hybrid_petrol` | `PHEV` | Present from ~2024 |
| `plug_in_hybrid_diesel` | `PHEV` | Present from ~2024 |
| `hybrid_petrol` | `HEV` | Combined hybrid bucket — see §3 |
| `hybrid_diesel` | `HEV` | Combined hybrid bucket — see §3 |
| `petrol` | `PETROL` | |
| `diesel` | `DIESEL` | |
| `greendiesel` | `DIESEL` | Biodiesel blend, merged with diesel |
| *(anything else)* | `OTHERS` | |

`TOTAL` is computed as the row sum across all gallery columns.

## 3. Combined hybrid convention

The `fuel` column does not carry a PHEV/HEV distinction in historical data
(pre-2024): all hybrids are simply `hybrid_petrol` or `hybrid_diesel`. The
gallery follows the **single-Hybrid-bucket convention** also used for Türkiye,
Georgia, and Colombia:

- Combined hybrids → `HEV` column.
- `PHEV` column left empty (not zero — empty, to signal "not reported").
- TTM split chart labels the band **"Hybrid"** (not "HEV"), via the
  `compute_ttm_long` relabelling in `R/data.R`.
- In the BEV / ICE / PHEV trajectory chart, hybrids count as **ICE**
  (same as full HEV in all other countries).

From ~2024, `plug_in_hybrid_*` values appear in the data. When present,
these are mapped to `PHEV`, which means the Hybrid label logic in
`compute_ttm_long` will revert to the standard HEV label (since PHEV is
now populated). This is the correct long-term behaviour as the data improves.

## 4. Aggregation

The fetcher (`scripts/fetch_malaysia.py`) downloads one or two parquet files
(current year + previous year), groups by `(date_reg.year-month, fuel)`,
applies the fuel mapping, and sums to monthly totals. The aggregation is
simple: `groupby(["period", "gallery_col"]).size()`.

## 5. Schedule and publication cadence

data.gov.my typically updates the current-year parquet within **~2 weeks of
month-end**. The workflow therefore starts polling on the **15th** of each
month at 07:00 UTC (staggered between the Colombia slot at 07:30 and the
Turkey slot at 08:30). The fetcher's `csv_has_period` early-exit means all
but one run per month are no-ops.

## 6. History

The parquet files go back to **2018-01** (table start on data.gov.my). No
earlier data is available from this source. The backfill covers
2018-01 → 2026-04 (100 months at time of initial commit).

## 7. Known limitations

- **No PHEV/HEV split before ~2024.** Historical hybrid counts are a combined
  bucket. The gallery footnote explains this to readers.
- **No commercial vehicle split.** The `cars` catalogue covers passenger
  cars only. Vans, trucks, and buses are not in scope from this source.
- **greendiesel merged into diesel.** A small number of registrations use
  biodiesel blends (`greendiesel`); these are merged into DIESEL as an
  approximation. Volume is negligible (<0.1 % of DIESEL).
- **`import io` duplicated in script.** Cosmetic only — `import io` appears
  at module level and again inside `download_parquet()`; the inner import is
  a no-op but harmless.

## 8. Fragility and maintenance

- **URL structure.** The parquet URL (`storage.data.gov.my/transportation/cars_{YYYY}.parquet`)
  is stable by convention but undocumented. If it changes, update `BASE_URL`
  in `scripts/fetch_malaysia.py`.
- **Schema changes.** If data.gov.my renames the `fuel` or `date_reg`
  columns, the fetcher will raise `RuntimeError("'fuel' column not found")`.
  Check `df.columns` against `FUEL_MAP` keys.
- **New fuel types.** Unknown `fuel` values fall silently into `OTHERS`.
  Run `fetch_malaysia.py --year <YYYY>` locally and inspect the OTHERS
  total — a large spike suggests a new fuel type that should be mapped
  explicitly in `FUEL_MAP`.
