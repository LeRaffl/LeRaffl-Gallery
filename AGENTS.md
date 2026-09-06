# AGENTS.md — LeRaffl BEV Trajectory Gallery

Guidance for any AI/LLM working with this repository.

**What this repo is.** A public, fully client-side static site (GitHub Pages,
<https://leraffl.github.io/LeRaffl-Gallery/>) that models and visualises the
BEV / PHEV / ICE share of new-vehicle registrations across ~40+ countries:
per-country charts, a fitted generalized Weibull distribution ("S-curve") model,
and interactive tools (Builder, Thresholds, Durations, World Map, Fleet).

There are **two ways to use this file**. Read the part that fits your task:
Part 1 if you're *answering a question about the data*, Part 2 if you're
*changing the repo*.

The **canonical, always-current detail** lives in `docs/architecture/` (start at
`01-overview.md`, `02-components.md`, `05-flows.md`; per-country playbooks are
`NN-source-<country>.md`). This file is deliberately compact and stable — it
**links** to the living docs rather than copying volatile specifics (the country
list, exact schemas, cron times). If this file and the code/docs ever disagree,
the code and `docs/architecture/` win — treat the gap as a bug.

---

## Part 1 — Answering a question about the data

Use this when someone asks the repo for numbers, sources, or definitions.

**The one rule:** `data/<Country>.csv` is the **single source of truth**. Every
chart, PNG, parameter and aggregate is *derived* from it. Never quote a number
off a rendered image — read it from the CSV.

**Where things are:**

| You want… | Look at |
|---|---|
| A country's headline series (passenger cars) | `data/<Country>.csv` |
| A sub-slice (vans, trucks, private, used, …) | `data/<Country>_<Variant>.csv` |
| What a variant *means* | `docs/architecture/09-glossary.md` (canonical) |
| Fitted model parameters | `params.csv` (one row per `country,variant`) |
| Trailing-12-month totals (for aggregates) | `weights.csv` |
| The chart image index | `manifest.json` → `images/YYYY-MM/…png` |
| Human-readable per-country source write-up | `docs/architecture/NN-source-<country>.md`, or the published page under `sources/` |
| Where a specific row came from | the `source` column of that CSV row |
| Chart caveats / footnotes | `footnotes.csv` (keyed by `country,variant`) |

**CSV schema.** One row per `(period, variant)`. Columns: `period,
time_interval, variant, source,` then the fuel columns `BEV, PHEV, EREV, HEV,
MHEV, PETROL, DIESEL, GAS, CNG, LPG, FLEXFUEL, ETHANOL, OTHERS, TOTAL,` then
`notes`. Only the columns a country actually reports are present.

**Reading the numbers correctly:**

- **BEV share = `BEV / TOTAL`**, where `TOTAL` is exactly the source's scope.
  Scopes differ by country (e.g. weight caps), so absolute volumes are **not**
  directly comparable across countries — see the scope discussion in
  `09-glossary.md` before comparing.
- Variants are anchored to **EU vehicle classes**: `Whole` = M1 passenger cars
  (the default, no suffix), `Vans` = N1, `HDV` = N2+N3, `Buses` = M2+M3;
  `Private`/`Industry`/`Used`/`Rental`/`NonRental` are M1 sub-slices. Not every
  country has every variant — check the CSV and the `09-glossary.md` table.
- **The EU-class anchoring is the *intent*, not a guarantee — country scopes
  deviate, and the exceptions matter.** A source may exclude a segment (e.g.
  Japan's kei cars), split off pickups into their own slice, or change coverage
  over time (older history missing a body type). Never assume a variant means
  exactly its EU class for a given country: the real per-country scope — and
  every such caveat — is written up in that country's
  `docs/architecture/NN-source-<country>.md`, the per-country scope table in
  `09-glossary.md`, and `footnotes.csv`. Read those before comparing.
- Where a source publishes **no petrol/diesel split**, `PETROL`/`DIESEL` are
  left **empty** and the combustion total sits in ICE/`TOTAL − electrified`.
  Empty ≠ 0.
- `EREV` is a real column but folds into `PHEV` in the 3-curve plot.
- `MHEV` (mild hybrids) is **not** classified consistently across sources:
  depending on the country it's its own column, folded into `HEV`, or counted on
  the combustion side (`ICE`, or `PETROL`/`DIESEL`). Don't assume `MHEV ⊂ HEV` —
  check the country's `NN-source-<country>.md` for how that source treats it.
- Rows whose value is **modelled/estimated** say so in their `notes` column.

**Don't:** cite an image as data; assume a variant/country exists without
checking; compare TOTALs across countries without checking scope; treat the
fitted curve as an official forecast (it's this project's own model).

---

## Part 2 — Changing this repo

Use this when you (the owner, or a dev agent) are editing or extending the repo.

### Repository map

| Path | What it is |
|---|---|
| `data/<Country>[_<Variant>].csv` | **Source of truth.** Registration data. |
| `scripts/fetch_<country>.py` | Per-country data ingesters (one per source; intentionally country-local). |
| `scripts/build_*.py`, `build_manifest.R` | Generators for series, source pages, schedule, manifest. |
| `R/` | Render pipeline: `render_country.R` (orchestrator) → `fit.R` (model), `plots.R`, `data.R`, `upsert.R`, `post_text.R`; `render_schedule.R`. |
| `.github/workflows/` | `fetch-*.yml` (cron ingesters), `render-country.yml` (chart render), `build-manifest.yml`, `build-series.yml`, `build-source-pages.yml`, `snapshot-builder.yml`. |
| `index.html` | The entire single-file frontend (all tabs, JS, `SD_COUNTRIES`, `SD_FUEL_ORDER`). |
| `worker/` | Cloudflare Worker: feedback issues + Submit-Data → opens a PR touching one `data/<Country>.csv`. |
| `docs/architecture/` | **Canonical architecture docs** (numbered). The spec. |
| `sources/`, `series/`, `schedule*.html/.ics`, `manifest.json`, `params.csv`, `weights.csv`, `images/`, `posts/` | **Generated** — do not hand-edit (see below). |
| `assets/` | Flags, fonts, variant icons (embedded at render time). |

### The pipeline

`fetch-<country>.yml` (cron/dispatch, self-throttling) → upsert
`data/<Country>.csv` → change-gated commit → dispatch **`render-country.yml`
once with the touched variants** (it renders them serially in one run and
commits `images/`+`params.csv`+`weights.csv`+`posts/`) → `build-manifest.yml`
reindexes → GitHub Pages redeploys. `fetch-acea.yml` is the one multi-**country**
fetcher and fans render-country out via a `workflow_call` matrix instead.

### Invariants — never break these

1. `data/<Country>.csv` is the single source of truth. **Never hand-edit**
   `params.csv`, `weights.csv`, `manifest.json`, `images/`, `posts/`,
   `sources/`, `series/`, `schedule*` — they are generated.
2. CSV writes are **line-level upserts** keyed on `(period, variant)`
   (`R/upsert.R`). Never round-trip a whole CSV through read/write — it
   reformats untouched numbers (scientific notation, trailing zeros) and
   creates noisy, wrong diffs.
3. **Don't rewrite the past.** Historical `source` labels / values that predate
   a definition or parser fix are left as-is; the series converges forward.
4. **No-split fuel column → leave empty, never `0.0`.** A `0.0` wrongly asserts
   "zero petrol cars" and breaks the TTM strict-window logic (see the
   production issues in `05-flows.md`).
5. Variant definitions stay anchored to EU vehicle classes (`09-glossary.md`)
   so countries remain comparable.
6. Estimated/modelled rows are flagged in their `notes` column.

### When you change X, also update Y

- **A data source's logic** → `scripts/fetch_<c>.py` **and** `.github/workflows/fetch-<c>.yml` **and** `docs/architecture/NN-source-<c>.md` (and `footnotes.csv` if a caveat changed).
- **A workflow or the render/dispatch mechanism** → mirror it in `docs/architecture/02-components.md`, `05-flows.md`, `08-deploy-ops.md`, `architecture/bev-gallery-architecture-brief.md` **and** `README.md`. These are the canonical architecture; leaving them stale is a bug.
- **The model / plots / render** → `R/*.R`, then re-render the affected countries, then update the docs if behaviour changed.
- **Country source pages** (`sources/*.html`) → edit the source doc `docs/architecture/*-source-*.md` or an entry in `docs/architecture/country_source_stubs.yaml`; the HTML is regenerated by `scripts/build_source_pages.py`. Likewise `schedule*.html/.ics` come from `scripts/build_schedule.py` and `manifest.json` from `build_manifest.R`.
- **Frontend / UI** → `index.html` (single file; the country registry `SD_COUNTRIES` and fuel order `SD_FUEL_ORDER` live there).
- **Add a country** → follow `docs/architecture/08-deploy-ops.md` §8.3 (write `data/<Country>.csv`, add to `SD_COUNTRIES` in `index.html`, add `assets/flags/<slug>.png`, map the flag emoji in `R/post_text.R`, PR, then render) and give it a source doc or a `country_source_stubs.yaml` entry.
- **Add/rename a variant** → the `09-glossary.md` variant table, the fetcher, and the country's `variants` list in `SD_COUNTRIES`.

### Conventions

- **Validate every workflow change with `actionlint`** before pushing. YAML
  parsing is *not* enough: GitHub evaluates `${{ … }}` expressions anywhere in
  a `run:` block — **including inside shell comments** — so a stray or empty
  `${{ }}` makes the whole file "Invalid workflow file".
- Commit messages: conventional prefixes (`chore:`/`fix:`/`feat:`/`ci:`). Data
  commits read `chore: update <Country> data from <source>`; render commits
  `chore: render <Country> (<variant>)`.
- Keep changes **surgical** and single-concern. A Submit-Data PR must touch
  exactly one `data/<Country>.csv` and nothing else.
- **Never commit secrets/tokens.** Fetchers use repo secrets and relays
  (`docs/architecture/07-secrets-trust.md`, `08-deploy-ops.md` §8.4); the Worker
  holds a fine-grained PAT set via `wrangler secret`.

Keep this file compact and permanent. Push volatile detail down into the linked
living docs and link to it — don't duplicate it here.
