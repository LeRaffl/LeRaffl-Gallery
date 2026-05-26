# 06 · Tech Stack

What runs where, what version, what package.

## Language and runtime matrix

| Layer | Tech | Where | Version constraint |
|---|---|---|---|
| Frontend rendering | HTML5 + CSS3 + ES2020 JavaScript | `index.html` | Whatever evergreen browsers support today; no transpiler |
| Edge compute | JavaScript (V8 isolate, Workers runtime) | `worker/index.js` | `compatibility_date = 2026-04-25` in `wrangler.toml` |
| Data pipeline | R | `R/*.R`, `build_manifest.R` | R 4.5+ (CI uses `r-lib/actions/setup-r@v2` default) |
| CI orchestration | YAML for GitHub Actions | `.github/workflows/*.yml` | GitHub Actions current |
| Build / packaging | None | — | Static site, no bundler |

## R package dependencies

### Render-country pipeline (`R/*.R`, used by `render-country.yml`)

| Package | Used in | Why |
|---|---|---|
| `ggplot2` | plots.R | All plotting |
| `scales` | plots.R | `unit_format`, `percent_format` axis labels |
| `grid` | plots.R | `rasterGrob` for flag overlays |
| `png` | render_country.R | Read flag PNG into a raster |
| `ggtext` | plots.R | `element_markdown` for rich-text caption |
| `viridis` | plots.R | TTM stack colour palette |
| `showtext` | render_country.R | Render FontAwesome glyphs in captions |
| `sysfonts` | render_country.R | `font_add` for FA OTF files |
| `glue` | render_country.R | String interpolation for the social caption |

`R/fit.R` and `R/upsert.R` are pure base R — no extra packages.

### Manifest builder (`build_manifest.R`, used by `build-manifest.yml`)

| Package | Why |
|---|---|
| `jsonlite` | Write JSON |
| `stringr` | Filename parsing |
| `dplyr` | Frame manipulation |
| `lubridate` | Date parsing from filename suffix |
| `purrr` | Map over images/ tree |
| `fs` | Filesystem traversal |
| `tibble` | Lightweight frame |

### Legacy local R (off-repo)

The maintainer's per-country scripts pull `gert` (Git ops), `googlesheets4` (Google Sheets read), `readxl`, `tidyr`, `reshape2`, `xts`, `tidyquant`, `patchwork`, `lubridate`, `ggcorrplot`, `gridExtra`, `htmltools`, `fontawesome`, `emojifont`, on top of the render-pipeline set. None of those are needed in CI.

## Frontend dependencies

The page intentionally has **zero JS dependencies**. No React, Vue, jQuery, lodash, d3. Implementation:
- Plotly is loaded **on demand** for the Builder/Fleet tabs only, from a CDN, with `loading="lazy"`-style late inclusion.
- All other interactivity is hand-rolled vanilla DOM manipulation.

CDN inclusions (current):
- Plotly via CDN script tag (used in Builder, Fleet)
- That's it

## Worker dependencies

Pure ES module. No npm dependencies, no build step. The Workers runtime supplies `fetch`, `Request`, `Response`, `URL`, `caches`, KV bindings, `btoa`/`atob`. All HTTP work is direct `fetch`.

`wrangler.toml` declares:
```toml
name               = "leraffl-gallery-feedback"
main               = "index.js"
compatibility_date = "2026-04-25"
account_id         = "<redacted>"
preview_urls       = false

[observability]
enabled = true
[observability.logs]
enabled = true

[vars]
GITHUB_OWNER = "leraffl"
GITHUB_REPO  = "leraffl-gallery"

[[kv_namespaces]]
binding = "RATE_KV"
id      = "<redacted>"
```

## CI runner stack

- `actions/checkout@v4` — pull source
- `r-lib/actions/setup-r@v2` (with `use-public-rspm: true` for fast package binaries on Ubuntu)
- `r-lib/actions/setup-r-dependencies@v2` — install the package list with apt prebuilds
- `EndBug/add-and-commit@v9` — commit and push outputs back

## Hosting / SaaS

| Service | Tier | What it runs |
|---|---|---|
| GitHub | Free public repo | Source, Issues, PRs, Actions, Pages |
| Cloudflare Workers | Free | The edge worker |
| Cloudflare Workers Builds | Free | Auto-deploys the worker on every push to `master` that touches `worker/` — `npx wrangler deploy` runs in a Cloudflare-managed build container, no local CLI needed. Configured per-Worker in the dashboard (Settings → Builds → Connect to Git). |
| Cloudflare KV | Free (under 1k writes/day, 100k reads/day) | Rate-limit counters |
| Posit Public Package Manager | Free | R package binaries for CI |

No paid services in the critical path. The Cloudflare account does not have a billing card attached for this project.

## Why "no build step" everywhere

For a one-maintainer project documenting public data, every minute spent fixing a Webpack config or Babel preset is a minute not spent on data quality. The codebase is small enough that vanilla JS + plain R + plain CSS is faster to evolve than any framework. If this project ever grows past one maintainer, this is a decision to revisit.

## See also

- [02-components.md](02-components.md) — what each runtime is hosting
- [08-deploy-ops.md](08-deploy-ops.md) — install/deploy commands per layer
