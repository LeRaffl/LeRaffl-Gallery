# R pipeline consolidation — project plan

> Visible plan tracker for the consolidation of 63 country-specific R scripts into one harmonized R pipeline. Mirrors the persistent memory entry. Update as phases complete.

## Goal

Replace 63 near-clone country scripts in `legacy/country_models/` with **one** parameterized R pipeline in `R/` that produces bit-identical math + visually identical charts. Long term: feeds a GitHub Actions workflow so the iPhone-Shortcut → local-R → push-to-prod-repo loop becomes "click in GitHub → site updates".

## Constraints (user-confirmed)

- Math + chart visuals must stay identical to the originals
- Strictly inside `Gallery-TEST` repo — no external pushes, no production actions
- No Google Sheets dependency in the new pipeline (data file lives in repo)
- No iCloud staging step
- No git push from inside R
- Original 63 scripts archived under `legacy/`, not deleted (yet)

## Target schema

Canonical fuel-type categories: **BEV / PHEV / HEV / Petrol / Diesel / Other**.

Variations to handle gracefully:
- China-style: `EREV` instead of HEV → folds into PHEV in the BEV/ICE/PHEV trajectory plot, but appears as its own stack layer in the TTM bar plot
- USA / South Korea / China-style: single `ICE` column instead of `Petrol` + `Diesel` split
- Türkiye-style: single `HYBRIDS` column (HEV + PHEV combined), no PHEV
- Thailand-style: has BOTH `ICE` AND `Petrol`+`Diesel`
- Denmark default market: missing `Petrol TTM` and `Other TTM`
- Europeanunion: 26 cols, duplicated TTMs, has `Hybrid` and `Fossil` aggregates
- Malaysia: not in spreadsheet — pulled via API
- India variants: `india` (cars), `india_2` (2-wheelers), `india_3` (3-wheelers)
- HDV (>3500 kg trucks), Private, Industry, Vans, Used / Used Imports, Custom, Legacy, Fleet variants

## Planned target architecture

```
Gallery-TEST/
├── R/
│   ├── bev_share.R                # entry: Rscript R/bev_share.R <market sheet name>
│   ├── lib/
│   │   ├── load_data.R            # XLSX read + schema detect
│   │   ├── normalize_schema.R     # → canonical BEV/PHEV/HEV/Petrol/Diesel/Other
│   │   ├── model.R                # optim regression, IDENTICAL math
│   │   ├── plots.R                # ggplot fns, IDENTICAL visuals
│   │   ├── params_io.R            # upsert params.csv + weights.csv
│   │   └── sources.R              # special: Malaysia API
│   └── config/
│       └── countries.yaml (or .R) # per-country overrides
├── data/
│   └── bev_share_acea.xlsx        # canonical raw data, manually updated
├── legacy/
│   ├── country_models/            # all 63 original R scripts archived ← Phase A
│   └── country_shell_scripts/     # all 62 shell wrappers archived ← Phase A
└── .github/workflows/
    └── r_pipeline.yml             # optional: GitHub Actions — Phase F
```

## Phases

- **Phase A — Baseline + discovery** ✅
  - [x] Inspect XLSX schema across sheets
  - [x] Skim Austria.R + Indonesia.R structure
  - [x] Confirm scope with user
  - [x] Copy `country_models/` + `country_shell_scripts/` into worktree under `legacy/`
  - [x] Baseline commit
  - [x] Save plan to memory + repo

- **Phase B — Schema catalog + special-case analysis** ✅
  - [x] Read all relevant scripts, categorize variations
  - [x] Document Malaysia API (parquet from `storage.data.gov.my`)
  - [x] Document Indonesia rounding failure (`scipen=999` + default `digits=7` truncated `1e-20` to 0)
  - [x] Document Türkiye HYBRIDS, China EREV handling
  - [x] Output baked into `R/lib/load_data.R::detect_schema_flags` — no separate config file needed

- **Phase C — Minimal example: Austria** ✅
  - [x] `R/lib/load_data.R` — XLSX read + schema detect
  - [x] `R/lib/model.R` — verbatim optim math
  - [x] `R/lib/plots.R` — verbatim ggplots, schema-aware TTM stack
  - [x] `R/lib/params_io.R` — upsert with `formatC(format="g", digits=15)` to fix the rounding bug
  - [x] `R/lib/captions.R` — flag image + social caption helpers (graceful fallback when assets missing)
  - [x] `R/bev_share.R` — entry point
  - [x] `R/run_all.R` — batch driver
  - [x] Validated on Austria — params.csv values match expected magnitude, PNGs visually consistent with legacy

- **Phase D — Scale to all 59** ✅
  - [x] Indonesia rounding fix VERIFIED (was `0`, now `-6.11e-20` for `v1`, `-1.97e-20` for `ice_v1`)
  - [x] China EREV handling verified (folds into PHEV trajectory line, separate TTM layer)
  - [x] Türkiye HYBRIDS handling verified
  - [x] Quarterly fallback in TTM plot (Canada, Denmark default market, Georgia)
  - [x] Year reconstruction from `YYYYMMM` for sheets with empty `year` column (Malta)
  - [x] `OTHER` → `OTHERS` column alias (Malta)
  - [x] NA-share row filter before optim (Denmark default market 3 rows, NewZealand (HDV) 22 rows)
  - [x] Defensive timer-plot trim on non-finite BEV_time / ICE_time (Croatia)
  - [x] Defensive annotation loops (no crash on empty subsets)
  - [x] Robust `data_per_from_data` (skip NA-time_interval rows; fix q=5 bug)
  - [x] Full batch passes: **59/59 sheets**

- **Phase E — Cleanup + docs** (done)
  - [x] Update root README.md
  - [x] Update CLAUDE.md
  - [x] R/README.md
  - [x] PROJECT_PLAN.md visible in repo
  - [x] .gitignore for R session artifacts

- **Phase F — GitHub Actions** ✅
  - [x] `.github/workflows/r_pipeline.yml`
  - [x] Manual `workflow_dispatch` trigger; optional sheet filter; optional commit-back; always uploads artifact

## Out of scope for this branch (phase 2 candidates)
- **Malaysia parquet loader**: source is `https://storage.data.gov.my/transportation/cars_<year>.parquet`, not the XLSX. Needs a dedicated loader plug-in (`R/lib/sources/malaysia.R` or similar). Schema is bespoke (`Hybrid (Petrol)`, `Hybrid (Diesel)`, `Green Diesel`).
- **India 2/3-wheelers**: legacy had `bev_share_India_2_*.R` (2-wheelers) and `bev_share_India_3_*.R` (3-wheelers). The XLSX only has a single `India` sheet (cars). To bring 2/3-wheelers in we'd add new sheets to the XLSX.
- **SKIP_SHEETS**: currently skipped — `Europeanunion`, `Netherlands_HDV(old)`, `NewZealand (Legacy)`, `Georgia (Fleet)`, `Netherlands (Fleet)`. These are aggregates / archived snapshots / fleet variants with different layouts. Decide later whether to plug them in.
- **Visual diff vs. legacy PNGs**: byte-level identity wasn't validated; the new PNGs differ slightly from the legacy April-12 set because new April/March data has landed. Spot-checking by eye looked consistent. If needed, the user can run a single legacy script side by side and compare with `compare` from ImageMagick.

## Phase G: data format + mobile workflow ✅ DONE

- Long-format CSVs per country/variant under `data/markets/<slug>.csv` are the canonical data store; XLSX dropped from the repo (lives in git history at commit `ca95420` if needed).
- Pipeline reads CSVs, computes TTM dynamically with a 12-month rolling window, produces byte-identical posts to the user's existing X/Bluesky output (verified against Albania, China, Türkiye, South Korea, UK, Germany, NewZealand, Portugal, Ireland, Romania).
- `posts/<slug>_<YYYYMMDD>.txt` files are committed by the render Action; mobile reads them via `https://raw.githubusercontent.com/LeRaffl/Gallery-TEST/main/posts/<slug>_<date>.txt`.
- ACEA scraper (`scripts/scrape_acea.py` + `.github/workflows/scrape_acea.yml`) — manual `workflow_dispatch` with year/month inputs, fetches PDF from the stable acea.auto URL, parses the by-market table (pdfplumber.extract_tables), upserts into `data/markets/*.csv`, commits.
- Render workflow auto-triggers on push to `data/markets/**.csv` — the full chain is **click ACEA scrape → 1-2 min → CSV diff committed → render auto-fires → 5 min → PNGs/params.csv/posts committed**. Two sequential Action runs, no local R needed.

## What's NOT covered (future phases)

- **Mobile: read posts**: works today, but a one-tap iPhone Shortcut to fetch `posts/<slug>_<date>.txt` and copy to pasteboard isn't shipped here. (User had one for the old terminal-output workflow; needs porting.)
- **Mobile: trigger ACEA scrape**: works via GitHub mobile app's "Run workflow" button; no custom shortcut needed.
- **Non-ACEA monthly inputs (Austria, Germany, UK, Italy, Portugal, Sweden, Finland, Denmark, Netherlands)**: still tipped manually by editing `data/markets/<slug>.csv` directly via GitHub web UI. A scraper per non-ACEA source can be added later if any of them get tedious.
- **Robust quarter→monthly handling for sheets without monthly data** (Canada, Denmark default market, Georgia): pipeline handles them today but the TTM plot uses a quarterly fallback that visually differs from the monthly stack. Acceptable for now.
- **PROD repo (LeRaffl-Gallery) migration**: user will pull this when ready; expect a separate guide written closer to the cutover.
