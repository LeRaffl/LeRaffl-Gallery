# R Pipeline

The R pipeline replaces the old per-country scripts in `legacy/`. It reads
canonical long-format CSVs from `data/markets/`, detects each market schema,
fits the transition model, and writes charts plus generated CSV outputs.

## Entry Points

```sh
Rscript R/bev_share.R Austria
Rscript R/bev_share.R "Denmark (HDV)"
Rscript R/run_all.R --skip-fail
Rscript R/run_all.R --skip-fail Brazil Georgia
```

`R/run_all.R` reads `data/markets/_index.csv`. The `sheet_name` column is what
you pass to `R/bev_share.R`.

## Output Per Market

- `images/<YYYY-MM>/<slug>_<YYYYMMDD>.png`
- `images/<YYYY-MM>/<slug>_ICE_BEV_<YYYYMMDD>.png`
- `images/<YYYY-MM>/<slug>_time_<YYYYMMDD>.png`
- `images/<YYYY-MM>/<slug>_ttm_shares_<YYYYMMDD>.png`
- one upserted row in `params.csv`
- one upserted row in `weights.csv`
- one post snippet in `posts/<slug>_<YYYYMMDD>.txt`

The `<YYYY-MM>` folder is derived from the latest usable data period, not from
the current date.

## Internal Layout

```text
R/
├── bev_share.R
├── run_all.R
└── lib/
    ├── load_data.R
    ├── variants.R
    ├── model.R
    ├── plots.R
    ├── params_io.R
    ├── captions.R
    └── posts.R
```

## Schema Handling

- Standard split: `PETROL`, `DIESEL`, `HEV`, `PHEV`, `BEV`, `OTHER`, `TOTAL`.
- Single-ICE split: `ICE` instead of `PETROL`/`DIESEL`.
- China-style split: `EREV` is rendered separately in TTM but folded into the PHEV-like trajectory line.
- Combined-hybrid split: `HYBRIDS` replaces separate `HEV`/`PHEV`.
- Source-specific split: categories such as `FLEXFUEL` and `PETROL-GAS` are kept in CSV data.
- Residual ICE: if visible categories do not cover the total, the TTM stack can add a residual ICE layer.
- Quarterly data uses four-quarter rolling TTM fallback.
- Rows with non-finite BEV/ICE shares are dropped before fitting.

## Model Handling

- Core function: `1 - exp(v1 * x^v2)`.
- Weighted fit, using registration volume.
- Hard 0%/100% bounds are intentional.
- The model describes current observed transition shape; it is not a promise about the future.

## Do Not Forget

- `params.csv` and `weights.csv` are generated.
- `build_manifest.R` must run after images change.
- Country spelling matters because the browser dedupes and warns on legacy aliases.
- The default passenger-car variant is `New Cars`; older default-scope inputs
  are normalized as legacy aliases and should not be written to generated CSVs.
- The pipeline writes to the working tree only; GitHub Actions or a human commits the output.
