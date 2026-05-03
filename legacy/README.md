# Legacy R + shell scripts

This directory archives the per-country R scripts (and matching iPhone-Shortcut shell wrappers) that drove the BEV trajectory pipeline before the consolidation into a single harmonized `R/` pipeline.

## What's here

- `country_models/` — 63 R scripts, one per country/variant (~1300+ lines each, ~50 KB each). Each was responsible for: loading data from a Google Sheet, fitting a Weibull-style logistic via `optim`, generating ~4 PNG charts, upserting into `params.csv`/`weights.csv`, and pushing the result directly to the live `LeRaffl-Gallery` repo via `gert`.
- `country_shell_scripts/` — 62 shell wrappers. Each was triggered from an iPhone Shortcut: `cd <project_dir>`, run `Rscript <script>`, return path of latest PNG to the Shortcut so it could display the result on the phone.

## Why archived, not deleted

These contain a lot of country-specific decisions (init params for `optim`, special-case data handling, custom captions, etc.) that need to be carefully extracted into the harmonized pipeline. Keeping them in the repo makes it easy to diff/cross-reference while building the replacement, and gives a record of the original behaviour after the consolidation lands. They are no longer maintained — the harmonized pipeline lives in `R/` (once built).

## What was different per country

Worth knowing while reading these:

- Most scripts are near-clones of one another with country name + sheet URL swapped
- A few have genuine special cases:
  - `bev_share_Malaysia_20251231.R` — pulls data from an API (Malaysia not in the Google Sheet)
  - `bev_share_Indonesia_20251231.R` — has a known issue with very small `optim` parameters being lost on round-trip through `params.csv`
  - `bev_share_China_20251231.R` — `EREV` category instead of `HEV`
  - `bev_share_Tuerkiye_20251231.R` — single `HYBRIDS` column (HEV + PHEV combined)
  - `bev_share_USA_20251231.R`, `bev_share_SouthKorea_20251231.R` — single `ICE` column instead of `PETROL` + `DIESEL` split
  - `bev_share_Germany_Custom_20251231.R` — one-off simulation with a date range removed
  - `bev_share_India_2_*.R` / `bev_share_India_3_*.R` — 2-wheeler / 3-wheeler variants
  - `bev_share_Latvia_20251231.R.R` — typo, double extension
- Hard-coded paths inside these scripts:
  - `/Users/leraffl/Projects/GitHub/LeRaffl-Gallery` (the live, prod repo — DO NOT push there from automation)
  - `/Users/leraffl/Library/Mobile Documents/com~apple~CloudDocs/R/bev_share_*` (iCloud staging)
  - `/Users/leraffl/Projects/bev_assets/{flags,fonts}/...` (local asset directory)

These are NOT used by the harmonized pipeline.
