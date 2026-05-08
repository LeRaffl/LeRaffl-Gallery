# 09 · Glossary

Domain jargon used across the codebase, the data, and the chats. Look here when an LLM session or a new contributor asks "what does X mean".

## Vehicle / fuel categories

| Term | Meaning | Notes |
|---|---|---|
| **BEV** | Battery Electric Vehicle | Pure-electric, no combustion engine. The headline metric. |
| **PHEV** | Plug-in Hybrid Electric Vehicle | Has both a battery (chargeable from outside) and a combustion engine. |
| **EREV** | Extended-Range Electric Vehicle | A specific PHEV variant where the engine only acts as a generator for the battery. Some sources (notably China's CPCA from 2025-01-01 onwards) report this separately from PHEV. In our 3-curve plot, EREV is folded into PHEV. In the TTM stack, EREV is its own layer. |
| **HEV** | (Full) Hybrid Electric Vehicle | Battery is regen-charged only, can't be plugged in. Counts as ICE in our 3-curve rollup; renders as a parenthetical "of which Xp were HEV" in the post text. |
| **MHEV** | Mild Hybrid | Small battery assist; effectively ICE. Reserved column, not yet used. |
| **PETROL / DIESEL / FLEXFUEL / ETHANOL** | Conventional ICE subcategories | Where reported. |
| **GAS / CNG / LPG** | Gas-powered ICE variants | Reserved columns; only Georgia currently uses GAS (via a re-mapped PETROL-GAS column). |
| **OTHERS** | Catch-all | Any fuel not fitting the named categories. |
| **ICE** | Internal Combustion Engine, single bucket | Used by countries (China, USA, South Korea, Thailand, Chile) that don't break ICE down further. In the 3-curve rollup ICE is *derived* (TOTAL − BEV − PHEV − EREV); when reported as an explicit column it's used directly in the TTM stack. |
| **TOTAL** | All registrations in the period | Required field. The denominator for every share computation. |
| **Hybrid (capital, no qualifier)** | A country's single combined hybrid bucket | Some sources (Türkiye `HYBRIDS`, Georgia `Hybrid`) don't split PHEV vs HEV. In our schema this maps to the `HEV` column and the post text labels it as "Hybrid" without parentheses. |

## Time / period

| Term | Meaning |
|---|---|
| **period** | A YYYY-MM string identifying the data point. Quarterly entries use the middle month (Q1→Feb, Q2→May, Q3→Aug, Q4→Nov). Yearly entries use July (`YYYY-07`). |
| **time_interval** | One of `monthly`, `quarterly`, `yearly`. Drives how the row is plotted and aggregated. |
| **TTM** | Trailing Twelve Months. Rolling sum of the last 12 monthly rows; shown as the `_ttm_shares` chart and as the second block in the post text. |
| **data_per** | The `period` of the most recent data row this fit was based on. Lives in `params.csv` and `weights.csv`. |
| **model_date** | The day the fit was last run, in `YYYY-MM-DD`. Mostly informational. |
| **baseline_date** | Reserved field in `params.csv`; always blank currently. |

## Identifiers and naming

| Term | Meaning | Example |
|---|---|---|
| **slug** | Lowercase form of country (and optionally variant) with non-alphanumerics replaced by `_`. Used in image filenames and post filenames. | `germany`, `new_zealand`, `denmark_hdv` |
| **country** | The display name of the country | `Germany`, `Türkiye`, `New Zealand` |
| **variant** | A within-country slice | `Whole` (default — labelled "New Cars" in the UI), `Custom`, `HDV`, `Vans`, `Private`, `Industry`, `2-Wheelers`, `3-Wheelers`, `4-Wheelers`, `Used`, `Used Imports`, `Fleet` |
| **type** (in chart filenames) | One of the four canonical chart types | empty (BEV trajectory), `ICE_BEV`, `time`, `ttm_shares` |

## Model parameters

| Term | Meaning |
|---|---|
| **v1, v2, t0** | The three parameters of the BEV-curve fit. The curve is `share(t) = 1 − exp(v1 × (t − (t0 − 1))^v2)`. `t0` is the integer floor of the earliest data year for that country. |
| **ice_v1, ice_v2, ice_t0** | Same shape, fit independently on the ICE share. |
| **verschiebung** | Internal R variable for `t0`. Historical name kept because the math comes from a German R script and renaming it would obscure the byte-for-byte invariant. |
| **extrapol** | The integer year the regression extrapolates to. Currently 2200, far enough that all countries cross every meaningful threshold. |
| **confidence_level** | `0.999` — used for the BEV/ICE confidence ribbons on the trajectory plots. |
| **weight** | In `weights.csv`, the trailing 12-month sum of TOTAL for monthly countries (or trailing-4-quarter sum, or last-yearly). Used as a country importance weight in cross-country aggregates. |

## Architecture / deployment

| Term | Meaning |
|---|---|
| **Worker** | Cloudflare Workers runtime instance running `worker/index.js`. Single deployed unit. |
| **Action** | A GitHub Actions workflow defined in `.github/workflows/*.yml`. We have two: `render-country` (manual) and `build-manifest` (push-triggered). |
| **PAT** | Personal Access Token. The Worker holds a fine-grained PAT scoped to this one repo. |
| **KV** | Cloudflare KV, a key-value store. Used only for rate-limit counters. |
| **Pages** | GitHub Pages, the static-site hosting that serves `index.html` and friends. |
| **manifest** | `manifest.json` at repo root, listing every PNG in `images/`. Built by `build_manifest.R`. |
| **upsert** | Insert-or-update by key. `(country, variant)` for params/weights; `(period, variant)` for `data/<Country>.csv` rows. |
| **honeypot** | A hidden form field that humans never fill but bots auto-populate. Submissions with a non-empty honeypot are silently dropped (response 200 to fool the bot). |
| **rate-limit window** | 60 minutes (`RATE_LIMIT_WINDOW`). Each IP can submit at most `RATE_LIMIT_MAX = 3` of either `/issues` or `/submissions` in that window. |

## Conventions

| Term | Meaning |
|---|---|
| **canonical schema** | The wide-but-sparse fuel-column header that each `data/<Country>.csv` follows. See [03-data-objects.md § 3.1](03-data-objects.md#31-country-raw-data). |
| **wide-but-sparse** | One row per (period, variant); fuel columns are NA where not reported, never zero-filled. |
| **line-level upsert** | Modifying just one line of a CSV without round-tripping the whole file through a parser. Used in `R/upsert.R` to keep diffs minimal. |
| **3-curve rollup** | The aggregation rule for the ICE/BEV/PHEV trajectory plot: BEV / (PHEV + EREV) / (everything else). The "everything else" includes HEV, MHEV, Petrol, Diesel, Gas, OTHERS, and an explicit ICE column if reported. |
| **byte-identical** | The result of a refit must equal the historical params row to ~1e-7 relative tolerance. Drift larger than that means the math has changed and historical thresholds become non-reproducible. |

## Common abbreviations in commit messages and chat

| Abbrev | Stands for |
|---|---|
| **TTM** | Trailing Twelve Months |
| **EAM** | Enterprise Architecture Management |
| **EREV / PHEV / HEV / BEV / MHEV / ICE** | (See vehicle categories above) |
| **PR** | Pull Request |
| **PAT** | Personal Access Token |
| **KV** | Cloudflare Key-Value store |
| **CI** | Continuous Integration (here: GitHub Actions) |
| **`%p`** | Percentage points — the suffix used in the post text to distinguish a sub-percentage value from a top-level percent (e.g. "63.1% ICE (of which 28.2%p were HEV)") |

## See also

- [01-overview.md](01-overview.md) for the high-level picture
- [03-data-objects.md](03-data-objects.md) for schema details
