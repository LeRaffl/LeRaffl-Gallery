# 35 · Proposal: live, configurable observation charts ("Monthly" tab)

**Status:** Concept. Nothing built. Written 2026-08.
**Audience:** the maintainer + whoever implements this later.
**Origin:** an X thread with @AndreasMemmer — a static PNG of the German BEV
share of new registrations over the last 24 months, and the reply *"sone
Graphik live und einstellbar bei mir auf der gallery einzubauen. Monatlich,
2,3,4… wieviele Monate auch immer."*

---

## 1 · What this is, and what it deliberately is not

Every chart the gallery publishes today is **model output**. The four canonical
PNGs, Builder, Compare, Thresholds, Durations, Time Interval, World Map and
Fleet all read `params.csv` — the fitted Weibull/logistic parameters — or the
weights that aggregate them. The one exception is the TTM stacked bar, which is
observation, but only at a fixed 12-month window and only as a static image.

This proposal adds the missing half: **a tab that shows the observed
registration numbers themselves, with the smoothing window as a live control.**

The single control that matters is the trailing window `N`:

| `N` | What you are looking at |
|---|---|
| 1 | The raw monthly share. Noisy, seasonal, and the number people actually quote. |
| 3 | Quarter-ish smoothing. Kills reporting-calendar jitter, keeps turning points. |
| 6 | Half-year. Seasonality still partly in. |
| 12 | TTM — identical to the published TTM chart and to `params.csv:ttm_bev_share`. Seasonality fully removed. |

`N = 12` is not just "more smoothing": it is the only window that removes
seasonality *by construction*, because it always contains each calendar month
exactly once. Everything below 12 trades seasonal contamination for
responsiveness. The UI has to say this out loud (§ 5.4) or the tab becomes a
machine for producing confidently wrong takes.

**Explicit non-goals.** No forecasting, no fitted curve on this tab, no
extrapolation past the last observed period. If someone wants the trajectory,
that is what the rest of the gallery is for. Keeping observation and model in
separate tabs is the point of the feature, not an omission.

---

## 2 · The one piece of math, written down once

Everything in this proposal reduces to one formula, and it must be implemented
identically on both sides of the pipeline:

```
share(t, N) = Σ_{i = t-N+1 … t} count_i  /  Σ_{i = t-N+1 … t} TOTAL_i
```

**A rolling window is a volume-weighted ratio of sums — never a mean of
shares.** A 3-month mean of `[10 %, 40 %, 10 %]` is 20 %; the correct answer
depends on how many cars were sold in each of those months and is generally not
20 %. `R/data.R:compute_ttm_long()` already gets this right for the fixed
12-window; the new artifact and the new tab must not quietly get it wrong for
the configurable one.

Three rules that follow, all of which `R/data.R` already applies and which the
new code inherits:

1. **Strict windows only.** If any of the `N` periods in the window is missing,
   the output is `null` — never a partial window. The first `N-1` periods of any
   series are therefore blank. This is exactly the "don't open the series with
   partial-window noise" behaviour `compute_ttm_long()` documents.
2. **Residuals are recomputed on the window sums.** `ICE = TOTAL − BEV − PHEV −
   EREV`, evaluated on the summed window, not averaged from per-month residuals.
   Same for `OTHERS`.
3. **EREV folds into PHEV** unless a full window of EREV data exists — the
   existing 3-curve rollup convention.

Consequence for storage: **the artifact stores counts, not shares.** Any window
is then derivable, and the wrong computation is not the convenient one.

---

## 3 · Backend

### 3.1 The problem the backend actually solves

The frontend *could* read `data/<Country>.csv` directly — the Compare tab
already does exactly that (`fetchCompareObs()`, `COMPARE_OBS_CACHE`). So why
build anything?

Because `data/` is an **editor-friendly source format, not a serving format**,
and the gap between the two is where this feature would rot:

- **10 different header shapes** across the 105 CSVs. Some carry an explicit
  `ICE` column, most want it derived. Some have `EREV`, some `FLEXFUEL`, some
  neither. A client that branches on all of this is a client that silently
  mis-sums one country.
- **`time_interval` lies, in both directions.** Per
  [31-proposal-country-source-pages.md](31-proposal-country-source-pages.md),
  22 CSVs carry `quarterly`/`yearly` labels on runs of consecutive months. And
  `data/Germany.csv` 2012–2014 is labelled `quarterly` while carrying twelve
  rows a year whose BEV values are a repeated fraction — i.e. a quarterly figure
  spread across months. **A monthly chart that plots those as monthly
  observations is lying**, and no amount of frontend care fixes it, because the
  information needed to tell them apart isn't reliably in the row.
- **One source of truth for the rollup.** The BEV/PHEV+EREV/ICE-residual
  convention lives in `R/data.R`. Re-deriving it in JS means two implementations
  that drift, and the drift shows up as a number in a screenshot on X.

So the backend's job is narrow and worth doing: **normalise once, at build time,
into a serving format that is honest about its own cadence.** The window
arithmetic itself stays in the browser — it has to be live.

### 3.2 The artifact: `series/`

A new build-time output, committed to the repo like `manifest.json` and
`sources/` (operating principle 1: Git is the source of truth).

```
series/
  index.json          # catalogue — what exists, how good it is
  <slug>.json         # one per country+variant, e.g. germany.json, italy_rental.json
  report.json         # validation output from the last build
```

**`series/index.json`** — small enough to load on tab open, enough to build every
selector without touching a series file:

```json
{
  "generated": "2026-08-08",
  "series": [
    {
      "slug": "germany",
      "country": "Germany",
      "variant": "Whole",
      "source": "KBA",
      "source_page": "sources/germany.html",
      "first": "2012-01",
      "last": "2026-07",
      "n_periods": 175,
      "cadence_observed": "monthly",
      "monthly_from": "2015-01",
      "has_gaps": false,
      "columns": ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS"]
    }
  ]
}
```

`monthly_from` is the field that carries the whole cadence-honesty story: the
first period from which the series is genuinely monthly. Everything before it is
coarser data spread across months and must not be drawn as a monthly
observation.

**`series/<slug>.json`** — column-major arrays aligned to one period vector
(~40 % smaller than row objects, and trivially indexable):

```json
{
  "slug": "germany",
  "country": "Germany",
  "variant": "Whole",
  "periods": ["2012-01", "…", "2026-07"],
  "native":  ["Q", "…", "M"],
  "canon": {
    "BEV":   [244.2, "…"],
    "PHEV":  [735.1, "…"],
    "ICE":   [208164.7, "…"],
    "OTHERS":[0, "…"],
    "TOTAL": [210195, "…"]
  },
  "raw": {
    "HEV":    [1051.4, "…"],
    "PETROL": [null, "…"],
    "DIESEL": [null, "…"]
  }
}
```

Two column groups, deliberately:

- **`canon`** — always present, always consistent, always summing to `TOTAL`.
  The 3-curve rollup from `R/data.R`. The tab's default metrics read only this,
  so no country can be missing a metric the UI offers.
- **`raw`** — whatever the source actually reported, `null` where it didn't.
  Lets the tab offer "Diesel share" for the countries that have it and say
  *"not reported for this country"* for the rest, instead of silently plotting a
  residual as if it were a measurement.

`native` is per-period: `M` / `Q` / `Y` — the **observed** spacing, not the
`time_interval` label. `Q` and `Y` entries are values spread from a coarser
report; the frontend must not offer `N < 3` (resp. `N < 12`) across them.

### 3.3 The generator

`scripts/build_series.py`, alongside the existing build-time generators.

**Why Python and not R** — this is the one genuinely contested call, so the
reasoning in full. R owns the rollup (`R/data.R`); Python owns the harder half,
cadence detection (`build_source_pages.py:observed_cadence()`, which already
infers real spacing from the period labels and reports whether the series is
uniform). Whichever language you pick, you reimplement something. Python wins
because:

1. `observed_cadence()` is the fussy, easy-to-get-subtly-wrong part, and it
   exists, tested by two shipped pages.
2. The rollup is ~15 lines of arithmetic that hasn't changed in the project's
   lifetime.
3. Every other build-time generator (`build_schedule.py`,
   `build_source_pages.py`) is Python — no R toolchain in the workflow, faster
   CI.
4. **The drift risk is neutralised by a contract test, which is stronger than
   sharing a language:** for every country, the generator's own `N = 12` BEV
   share at the last period must equal `params.csv:ttm_bev_share` within
   tolerance. That is a cross-language golden check against the R pipeline's
   committed output, and it fails the build the day the two rollups disagree —
   including the day someone changes `R/data.R` and forgets this artifact.

**Validation, `--check` mode** (mirroring `build_source_pages.py --check`, run on
PRs; writes nothing):

| Check | Severity |
|---|---|
| Duplicate periods in a CSV | fatal |
| `TOTAL` missing/≤ 0 while fuel counts present | fatal |
| Σ reported fuels > `TOTAL` beyond rounding tolerance | fatal |
| `N=12` BEV share ≠ `params.csv:ttm_bev_share` (tolerance 1e-6) | fatal |
| Gaps in the period sequence | recorded in `report.json`, not fatal |
| `time_interval` label contradicts observed spacing | recorded, not fatal |

Fatal-by-default matches how the fetchers already behave (Indonesia's checksum
abort, Türkiye's three validation layers). A wrong number that renders is worse
than a build that stops.

### 3.4 CI wiring

New workflow `build-series.yml`:

- **Trigger:** `push` on `master` with path filter `data/**`, plus
  `workflow_dispatch`. One rule catches every writer — the 29 fetchers, manual
  maintainer commits, and merged submission PRs — instead of adding a chained
  dispatch to 29 workflow files.
- **Writes:** `series/**` only. Since the trigger filters on `data/**`, the
  workflow's own commit cannot re-trigger it. No loop guard needed.
- **On PRs:** run `--check` only.
- Not folded into `build-manifest.yml`: that one is keyed on `images/**` and has
  a different dependency (renders, not data).

### 3.5 What this proposal does *not* add

- **No Worker involvement, no API, no new secret.** Operating principle 4
  (static-first on the read path) holds: the tab fetches static JSON from Pages.
  The feature keeps working if Cloudflare is down.
- **No database, no build step on the frontend.** Consistent with § 6 of the
  tech-stack doc.
- **No new CDN dependency.** Plotly is already loaded.

### 3.6 Size budget

All 105 CSVs are **1.4 MB raw**. The normalised per-country JSON is comparable
or smaller (counts only, no `notes`/`source` repeated per row), and Pages serves
it gzipped. Per-country files rather than one bundle, because:

- the tab loads only what is selected (1–5 files of ~10–30 KB),
- a single-country data update invalidates one cache entry, not all of them,
- it mirrors how `COMPARE_OBS_CACHE` already works.

A combined `series/bundle.json` is a later optimisation, and only if
multi-country selection routinely needs more than ~5 fetches.

---

## 4 · Frontend

### 4.1 Placement and naming

A new tab, in the nav's **"DIY Curves"** group or a new **"Observed"** group.

Name it something that cannot be mistaken for model output. **"Monthly"** with
the subtitle *"observed registrations — no model, no projection"*. "Trends"
sounds like a forecast; "Actuals" is finance jargon. Every other analytical tab
on this page shows a fitted curve, so the distinction has to be carried by the
label, not by a footnote.

### 4.2 Controls

| Control | Default | Notes |
|---|---|---|
| Country + variant | Germany · Whole | Multi-select, reusing the searchable-select helper already in `index.html`; Compare's slot pattern is the fallback if multi-select proves fiddly |
| Window `N` | **12** | Slider 1–24 plus preset chips `1 / 3 / 6 / 12`. Clamped to the native cadence of the visible range (§ 3.2) |
| Timeframe | last 24 months | 12 / 24 / 36 / 60 / all — 24 because that is the framing the thread started from |
| Metric | BEV share | BEV / PHEV / BEV+PHEV / ICE from `canon`; raw fuels where the country has them |
| Units | share (%) | Toggle to absolute registrations |
| Y-axis | auto | Toggle to fixed 0–100 for cross-country comparability |
| Endpoint labels | on, last 2 points | `Jul 26: 29.3 %`, exactly the annotation in the thread's chart |

Default `N = 12` rather than `1`, because it is the only window that is
seasonality-free and it reproduces the number already published in
`params.csv:ttm_bev_share` — so the tab agrees with the rest of the site on
first load. The slider is the feature; the raw month is one click away and
labelled as noisy.

### 4.3 Rendering and state

- **Plotly**, via the existing `ensurePlotly()` + `hashchange` lazy-init pattern
  (`loadFleetWhenActive()` / `loadWorldMapWhenActive()` are the template).
  Reuse the dark layout object and the `@LeRaffl` paper annotation from Compare.
- **Prefix sums.** Compute cumulative sums of every count column once per loaded
  series; a window is then two array lookups, so dragging the slider is O(1) per
  point. Debounce with the existing helper anyway.
- **Fetch cache.** A module-level `SERIES_CACHE` keyed by slug, same shape as
  `COMPARE_OBS_CACHE`.

**Deep links — the part that makes it postable.** The whole social use-case is
replying to a thread with *"here's that chart, live"*. That needs
`…/#monthly?c=Germany&n=3&t=24&m=BEV` to work. Today `activateTabByHash()` does
`hash.replace('#','')` → `getElementById('tab-' + id)`, so any query string
falls through to About. Required change, small and contained:

1. split the hash on `?` before the `tab-` lookup (all existing tabs unaffected),
2. hand the parsed `URLSearchParams` to the tab's init,
3. write state back with `history.replaceState` on every control change, so the
   URL in the address bar is always the shareable one.

### 4.4 Honesty affordances

These are requirements, not polish:

- **Cadence.** Periods where `native ≠ "M"` render dashed and greyed, with a
  legend note. Default view starts at `monthly_from`; an "include coarser
  history" toggle extends it.
- **Window caption.** A permanent sub-caption: *"12-month trailing window —
  seasonality removed"* / *"1-month — raw, seasonal"*. It changes with the
  slider so a screenshot always carries its own definition.
- **Source line.** Country, source name, last data month, and a link to the
  `sources/<slug>.html` page — the fields are already in `index.json`.
- **CSV export** of exactly what is plotted (period, window, country, numerator,
  denominator, share), so anyone can check the numbers. Plus the existing
  `downloadPlotlyChart()` for PNG, and a clipboard-copy path for posting from
  mobile.

### 4.5 Cost to `index.html`

The file is already ~428 KB / ~9.5k lines. This adds ~400 lines. That is
acceptable and no split is proposed here — but this is the tab where a `js/`
extraction would start if the single-file approach ever stops paying. Worth
naming so the decision is deliberate rather than accidental.

---

## 5 · Phasing

| Phase | Scope | Ships without the next phase? |
|---|---|---|
| **0 · Spike** | One country, client-side straight from `data/Germany.csv` via the existing `fetchCompareObs()`. Throwaway. Proves the UX and the slider feel before any backend exists. | n/a — not shipped |
| **1 · Backend** | `scripts/build_series.py`, `series/index.json` + per-country files, `--check`, `build-series.yml`, handbook entry. | Yes — a normalised, validated observation store is useful on its own |
| **2 · The tab** | Single country, window slider, timeframe, metric, endpoint labels, deep links, PNG + CSV export. | Yes — this is the feature as asked for in the thread |
| **3 · Multi-country** | 2–5 series overlaid, shared window. | Yes |
| **4 · Aggregates** | EU / World / regional groups, summing counts across members. **Strict membership**: a period is emitted only if every member reports it, otherwise the denominator jumps when one country publishes late and the line lies. Show `n = 14/16 reporting`. | Yes |
| **5 · Optional** | Render the same view from the R pipeline as a static PNG, so a configured chart can be posted from the existing render/post workflow. | Yes |

Phases 1 and 2 are the proposal. 3–5 are consequences that become cheap once the
artifact exists.

---

## 6 · Open questions for the maintainer

1. **Default window: 12 or 1?** The argument for 12 is in § 4.2; the argument for
   1 is that the thread asked for "monthly" and the raw month is the honest
   default. Cheap to change, expensive to change later once links are shared.
2. **Absolute units in v1, or share-only?** Absolutes make the seasonality story
   visible in one glance, but multi-country absolute scales are unreadable
   (Germany vs. Luxembourg). Possibly: absolutes only in single-country mode.
3. **Are aggregates in scope before phase 4**, or is single-country enough for
   the first release?
4. **Committed `series/` or built at deploy?** Committed, per operating
   principle 1 — but it adds ~1–2 MB and a commit per data update. Confirm that's
   acceptable churn.
5. **Tab name.** "Monthly" / "Observed" / "Trends" / something else.
6. **Does this eventually replace the static TTM PNG**, or do they coexist? They
   compute the same thing at `N = 12`; two artifacts saying the same number is
   fine until they disagree.

---

## 7 · See also

- [03-data-objects.md](03-data-objects.md) — where `series/` would be documented once built
- [05-flows.md](05-flows.md) — where the build-series flow diagram would go
- [31-proposal-country-source-pages.md](31-proposal-country-source-pages.md) — the cadence-honesty precedent and `observed_cadence()`
- `R/data.R` — `load_country_csv()` and `compute_ttm_long()`, the rollup and the strict-window rule this inherits
- `index.html` — `fetchCompareObs()` / `COMPARE_OBS_CACHE`, the client-side fetch pattern to reuse
