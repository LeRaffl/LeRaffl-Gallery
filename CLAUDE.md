# BEV Trajectories — Gallery-TEST

This repo is the **development/staging counterpart** to LeRaffl-Gallery (the public live gallery at leraffl.github.io/LeRaffl-Gallery). Changes are tested here before being merged to the public repo.

## What this project is

An interactive, fully client-side dashboard visualising EV transition dynamics per country:

- **Gallery tab** — browse PNG charts (BEV trajectories, ICE↔BEV transitions, TTM splits, transition-time curves) filtered by country / date / chart type
- **Thresholds tab** — when does a market reach 20 / 50 / 80% BEV share, computed from `params.csv`
- **Durations tab** — how long does a market take to move between share levels (e.g. 20→80%)

All computation runs in the browser. No backend.

## Key files

| File | Purpose |
|------|---------|
| `index.html` | Full UI — Gallery, Thresholds, Durations tabs |
| `manifest.json` | Auto-generated chart list (built by `build_manifest.R`) |
| `params.csv` | Fitted model parameters (v1, v2, t0, baseline year, last data month) per market |
| `images/YYYY-MM/` | PNG exports, served statically |
| `R/` | Consolidated BEV trajectory pipeline (replaces 63 per-country scripts). See `R/README.md`. |
| `data/raw/bev_share_acea.xlsx` | Canonical raw registration data, one sheet per country/variant |
| `legacy/country_models/` | Archived per-country R scripts — reference only, not maintained |
| `legacy/country_shell_scripts/` | Archived iPhone-Shortcut wrappers — reference only |

## Data & model

- Input: monthly new-car registration data (ACEA, KBA, CPCA, Statistik Austria, etc.)
- Model: Weibull-style generalised logistic — `1 - exp(v1 * x^v2)`, fitted via weighted OLS
- Parameters: `v1` (transition intensity), `v2` (transition shape), `t0` (time shift)
- Hard bounds: 0% start, 100% asymptote — intentional; model visibly breaks if data contradicts this
- Charts cover BEV, PHEV, and ICE (ICE = everything that is not BEV or PHEV)
- **Not a forecast** — a best-fit description of the transition as observed today

## R pipeline

The `R/` directory holds the consolidated pipeline. To regenerate one country:

```sh
Rscript R/bev_share.R Austria
Rscript R/bev_share.R "Denmark (HDV)"
```

To regenerate everything:

```sh
Rscript R/run_all.R --skip-fail
```

This reads `data/raw/bev_share_acea.xlsx`, fits the Weibull-style logistic, writes the four standard PNG charts per country/variant under `images/<YYYY-MM>/`, and upserts the fitted parameters into `params.csv` + `weights.csv`. **No git push from inside R** — the new pipeline writes only to the working tree; committing is up to a human (or a future GitHub Actions workflow).

The pipeline detects schema variations automatically (HEV / PHEV / EREV / HYBRIDS / single-ICE / Petrol+Diesel split). See `R/README.md` for details.

## Planned features

- `world_interval` plots
- Variant research per country
- Sources tab (URLs tracked in Google Sheets)
- GitHub Actions workflow that runs `R/run_all.R` on schedule and commits the regenerated charts
