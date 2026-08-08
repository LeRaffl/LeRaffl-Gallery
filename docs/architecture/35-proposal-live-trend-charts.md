# 35 · Proposal: live, configurable observation charts ("Monthly" tab)

**Status:** Concept, decisions locked (2026-08). Nothing built.
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
| 1 | The raw monthly share. Noisy, seasonal, and the number people actually quote. **Default.** |
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

### 1.1 Relationship to the static PNGs

The PNGs stay. They are not a legacy format this tab grows out of — they do a
different job:

> **The PNG is the record. The tab is the instrument.**

A committed `images/2026-07/germany_ttm_shares_20260806.png` is a timestamped,
content-addressable file in Git history: it says what the data looked like on
that date and cannot be silently re-rendered into a different claim. The live
tab always shows *current* data, including revisions — which is what makes it
useful and exactly what disqualifies it as a receipt. Both artifacts compute the
same thing at `N = 12`, and two artifacts agreeing is fine until they disagree —
at which point the PNG's date tells you which revision landed in between.

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
   segment are therefore blank. This is exactly the "don't open the series with
   partial-window noise" behaviour `compute_ttm_long()` documents.
2. **Residuals are recomputed on the window sums.** `ICE = TOTAL − BEV − PHEV −
   EREV`, evaluated on the summed window, not averaged from per-month residuals.
   Same for `OTHERS`.
3. **EREV folds into PHEV** unless a full window of EREV data exists — the
   existing 3-curve rollup convention.

Consequence for storage: **the artifact stores counts, not shares.** Any window
is then derivable, and the wrong computation is not the convenient one.

---

## 3 · Cadence policy: native monthly only

**Decision: the tab shows a period only where a genuinely monthly observation
exists for it.** No interpolation, no spreading a quarterly figure across three
months, no bridging. This is the rule the rest of the design has to serve, so it
comes before the schema rather than after it.

It bites in three distinct places, and each needs its own answer.

### 3.1 `time_interval` cannot be trusted to decide this

Per [31-proposal-country-source-pages.md](31-proposal-country-source-pages.md),
22 CSVs carry `quarterly`/`yearly` labels on runs of consecutive months. And the
reverse also happens: `data/Germany.csv` 2012–2014 is labelled `quarterly` while
carrying twelve rows a year whose BEV values are a repeated fraction — a
quarterly figure already spread across months by whoever entered it.

So the cadence must be **derived from the observed spacing of the period
labels**, not read off the row. `build_source_pages.py:observed_cadence()`
already does this and is the function to reuse.

### 3.2 Monthly runs are not always contiguous — draw segments, don't bridge

The obvious implementation ("start the series at the first monthly period") is
wrong, and so is the careful-looking version ("use the trailing monthly run").
Checked against the actual data — 4 of 105 files have more than one monthly run
of ≥ 12 periods:

| File | Monthly runs (periods) |
|---|---|
| `Italy_Rental.csv` | 63, 75 |
| `Italy_NonRental.csv` | 63, 75 |
| `Singapore.csv` | 37, 78 |
| `Ireland_Buses.csv` | 12, 40, 74 |

Taking only the trailing run would throw away 63 months of real Italian history
in two series. Bridging the gap would invent months that were never reported.

**Decision: every contiguous monthly run is its own line segment.** Gaps render
as gaps — the line simply stops and restarts. Rolling windows never span a gap
(the strict-window rule in § 2 gives this for free once each run is treated as
an independent series). `build_source_pages.py:contiguous_runs()` already
computes exactly these runs for the coverage bars on the source pages; same
logic, second consumer.

### 3.3 Quarterly-native series are out of scope for v1

Two countries never have monthly data at all: **Canada** (`Whole`, `Pickups`,
`Vans` — StatCan's cube is quarterly) and **Georgia**. Four files.

They are excluded from the tab in v1, not silently but visibly: they appear in
the country selector, disabled, with the reason (*"quarterly source — no monthly
data"*) and a link to their source page. Silently omitting them produces the
"why isn't Canada there?" question the `sources/` pages exist to pre-answer.

The alternative — supporting them with `N` snapped to multiples of 3 — was
rejected for v1 because it makes the one control on the page mean two different
things depending on which country is selected. It is cheap to add later
(§ 6, phase 4) once the monthly case is shipped and the control is understood.

---

## 4 · Backend

### 4.1 The problem the backend actually solves

The frontend *could* read `data/<Country>.csv` directly — the Compare tab
already does exactly that (`fetchCompareObs()`, `COMPARE_OBS_CACHE`). So why
build anything?

Because `data/` is an **editor-friendly source format, not a serving format**:

- **10 different header shapes** across the 105 CSVs. Some carry an explicit
  `ICE` column, most want it derived. Some have `EREV`, some `FLEXFUEL`, some
  neither. A client that branches on all of this is a client that silently
  mis-sums one country.
- **The cadence work in § 3** — observed spacing, contiguous runs, the
  quarterly exclusions — is real logic with real edge cases, and it belongs
  where it can be tested and where it already exists, not inlined in a chart
  handler.
- **One source of truth for the rollup.** The BEV/PHEV+EREV/ICE-residual
  convention lives in `R/data.R`. Re-deriving it in JS means two implementations
  that drift, and the drift shows up as a number in a screenshot on X.

So the backend's job is narrow and worth doing: **normalise once, at build time,
into a serving format that has already resolved what is genuinely monthly.** The
window arithmetic itself stays in the browser — it has to be live.

### 4.2 The artifact: `series/`

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
      "cadence_observed": "monthly",
      "monthly": true,
      "monthly_runs": [["2015-01", "2026-07"]],
      "last": "2026-07",
      "columns": ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS"]
    },
    {
      "slug": "canada",
      "country": "Canada",
      "variant": "Whole",
      "cadence_observed": "quarterly",
      "monthly": false,
      "monthly_runs": [],
      "unavailable_reason": "quarterly source — no monthly data"
    }
  ]
}
```

`monthly_runs` is the field that carries the whole § 3 story: the contiguous
stretches of genuinely monthly observation, and nothing else is plottable.
`monthly: false` entries render as disabled selector options.

**`series/<slug>.json`** — column-major arrays aligned to one period vector
(~40 % smaller than row objects, and trivially indexable):

```json
{
  "slug": "germany",
  "country": "Germany",
  "variant": "Whole",
  "periods": ["2015-01", "…", "2026-07"],
  "run":     [0, "…", 0],
  "canon": {
    "BEV":   [659, "…"],
    "PHEV":  [1095.7, "…"],
    "ICE":   [209583, "…"],
    "OTHERS":[0, "…"],
    "TOTAL": [211337, "…"]
  },
  "raw": {
    "HEV":    [1566.98, "…"],
    "PETROL": [null, "…"],
    "DIESEL": [null, "…"]
  }
}
```

**The file carries only monthly periods.** Coarser history is dropped at build
time rather than shipped with a flag — if it can never be plotted, serving it is
just bytes and a footgun. (It stays in `data/` and on the source pages, which is
where coverage belongs.) `run` is the segment index, so the client splits into
line segments without re-deriving anything.

Two column groups, deliberately:

- **`canon`** — always present, always consistent, always summing to `TOTAL`.
  The 3-curve rollup from `R/data.R`. The tab's default metrics read only this,
  so no country can be missing a metric the UI offers.
- **`raw`** — whatever the source actually reported, `null` where it didn't.
  Lets the tab offer "Diesel share" for the countries that have it and say
  *"not reported for this country"* for the rest, instead of silently plotting a
  residual as if it were a measurement.

### 4.3 The generator

`scripts/build_series.py`, alongside the existing build-time generators.

**Why Python and not R** — this is the one genuinely contested call, so the
reasoning in full. R owns the rollup (`R/data.R`); Python owns the harder half,
the cadence work of § 3 (`observed_cadence()` and `contiguous_runs()` in
`build_source_pages.py`). Whichever language you pick, you reimplement
something. Python wins because:

1. The cadence logic is the fussy, easy-to-get-subtly-wrong part, it exists, and
   it is already exercised by two shipped pages.
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

Note that check keeps its teeth even though the *default* window is now 1: it is
an internal assertion about the rollup, independent of what the UI shows.

**Validation, `--check` mode** (mirroring `build_source_pages.py --check`, run on
PRs; writes nothing):

| Check | Severity |
|---|---|
| Duplicate periods in a CSV | fatal |
| `TOTAL` missing/≤ 0 while fuel counts present | fatal |
| Σ reported fuels > `TOTAL` beyond rounding tolerance | fatal |
| `N=12` BEV share ≠ `params.csv:ttm_bev_share` (tolerance 1e-6) | fatal |
| A monthly run shorter than 12 periods | recorded in `report.json` |
| `time_interval` label contradicts observed spacing | recorded, not fatal |
| Series dropped entirely (no monthly run) | recorded, not fatal |

Fatal-by-default matches how the fetchers already behave (Indonesia's checksum
abort, Türkiye's three validation layers). A wrong number that renders is worse
than a build that stops.

### 4.4 CI wiring

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

### 4.5 What this proposal does *not* add

- **No Worker involvement, no API, no new secret.** Operating principle 4
  (static-first on the read path) holds: the tab fetches static JSON from Pages.
  The feature keeps working if Cloudflare is down.
- **No database, no build step on the frontend.** Consistent with § 6 of the
  tech-stack doc.
- **No new CDN dependency.** Plotly is already loaded.

### 4.6 Size budget

All 105 CSVs are **1.4 MB raw**. The normalised per-country JSON is smaller
(counts only, no `notes`/`source` repeated per row, non-monthly history dropped),
and Pages serves it gzipped. Per-country files rather than one bundle, because:

- the tab loads only what is selected (1–5 files of ~10–30 KB),
- a single-country data update invalidates one cache entry, not all of them,
- it mirrors how `COMPARE_OBS_CACHE` already works.

A combined `series/bundle.json` is a later optimisation, and only if
multi-country selection routinely needs more than ~5 fetches.

---

## 5 · Frontend

### 5.1 Placement: own tab, in a renamed group

The tab belongs thematically next to Builder — both are "configure it yourself
and look at the result". But it should **not** be a sub-tab inside Builder:

- Builder's bootstrap loads `params.csv` + `weights.csv` + Plotly and carries
  aggregate/weighting state this tab needs none of. Nesting inherits all of it.
- **Deep links are the whole social use-case** (§ 5.3). `#monthly?c=Germany&n=1`
  is a link you paste into a reply; `#builder?sub=monthly&c=Germany&n=1` is one
  level deeper, one more thing to get wrong, and couples two tabs' URL grammars.
- Builder is model, this is observation. § 1 argues that distinction should be
  visible in the navigation, and burying one inside the other erases it.

**Decision: own tab, in the existing Builder group, with the group renamed.**
"DIY Curves" promises curves; this tab has no curve in it. Rename the group to
**"DIY Charts"** — one word, keeps the voice, stops making a promise the group no
longer keeps:

```
DIY Charts:  Builder · Compare · Monthly · Fleet
```

The thematic link Builder deserves is made with **cross-links, not structure**:
Builder gets a "see the observed data" link that opens `#monthly` pre-filled
with the country in the current slot, and the Monthly tab gets the reverse.
That gives the association without the coupling.

### 5.2 Controls

| Control | Default | Notes |
|---|---|---|
| Country + variant | Germany · Whole | Multi-select, reusing the searchable-select helper already in `index.html`. Quarterly-native entries disabled with reason (§ 3.3) |
| Window `N` | **1** | Slider 1–24 plus preset chips `1 / 3 / 6 / 12` |
| Timeframe | last 24 months | 12 / 24 / 36 / 60 / all — 24 because that is the framing the thread started from |
| Metric | BEV share | BEV / PHEV / BEV+PHEV / ICE from `canon`; raw fuels where the country has them |
| Units | **share (%) · absolute** | Both shipped. Toggle, defaults to share |
| Y-axis | auto | Toggle to fixed 0–100 in share mode; log toggle in absolute mode |
| Endpoint labels | on, last 2 points | `Jul 26: 29.3 %`, exactly the annotation in the thread's chart |

**`N = 1` as the default** is the honest choice — it is the raw observation,
nothing derived, and it is what the thread asked for. Two consequences to handle
rather than discover:

- The first-load view **will not match** `params.csv:ttm_bev_share` or the
  published TTM PNG, because those are `N = 12`. The window caption (§ 5.4)
  carries this, and the `12` preset chip is one click away.
- `N = 1` is the noisiest view, so the seasonal warning matters *more* at the
  default than it would have at 12, not less.

**Absolute units in multi-country mode** are allowed rather than blocked —
Germany vs. Luxembourg on one linear axis is unreadable, but that is the user's
call to make and the log-y toggle is the fix. Blocking it would be the tab
deciding it knows better; the y-axis control is cheaper and more honest.

### 5.3 Rendering and state

- **Plotly**, via the existing `ensurePlotly()` + `hashchange` lazy-init pattern
  (`loadFleetWhenActive()` / `loadWorldMapWhenActive()` are the template).
  Reuse the dark layout object and the `@LeRaffl` paper annotation from Compare.
- **Segments** from § 3.2 render as `null` breaks in a single Plotly trace, so a
  gap needs no extra trace and no legend entry.
- **Prefix sums per segment.** Compute cumulative sums of every count column once
  per loaded series; a window is then two array lookups, so dragging the slider
  is O(1) per point. Debounce with the existing helper anyway.
- **Fetch cache.** A module-level `SERIES_CACHE` keyed by slug, same shape as
  `COMPARE_OBS_CACHE`.

**Deep links.** The whole social use-case is replying to a thread with *"here's
that chart, live"*. That needs `…/#monthly?c=Germany&n=1&t=24&m=BEV` to work.
Today `activateTabByHash()` does `hash.replace('#','')` →
`getElementById('tab-' + id)`, so any query string falls through to About.
Required change, small and contained:

1. split the hash on `?` before the `tab-` lookup (all existing tabs unaffected),
2. hand the parsed `URLSearchParams` to the tab's init,
3. write state back with `history.replaceState` on every control change, so the
   URL in the address bar is always the shareable one.

This is also what makes the Builder ↔ Monthly cross-links of § 5.1 possible.

### 5.4 Honesty affordances

These are requirements, not polish:

- **Window caption.** A permanent sub-caption that changes with the slider:
  *"1-month — raw, seasonal"* … *"12-month trailing window — seasonality
  removed"*. A screenshot must carry its own definition, because screenshots are
  the output format this feature exists to serve.
- **Gaps stay visible.** Segment breaks are never bridged and never explained
  away; hovering a break shows the missing span.
- **Source line.** Country, source name, last data month, and a link to the
  `sources/<slug>.html` page — the fields are already in `index.json`.
- **CSV export** of exactly what is plotted (period, window, country, numerator,
  denominator, share), so anyone can check the numbers. Plus the existing
  `downloadPlotlyChart()` for PNG, and a clipboard-copy path for posting from
  mobile.

### 5.5 Cost to `index.html`

The file is already ~428 KB / ~9.5k lines. This adds ~400 lines. That is
acceptable and no split is proposed here — but this is the tab where a `js/`
extraction would start if the single-file approach ever stops paying. Worth
naming so the decision is deliberate rather than accidental.

---

## 6 · Phasing

| Phase | Scope | Ships without the next phase? |
|---|---|---|
| **0 · Spike** | One country, client-side straight from `data/Germany.csv` via the existing `fetchCompareObs()`. Throwaway. Proves the UX and the slider feel before any backend exists. | n/a — not shipped |
| **1 · Backend** | `scripts/build_series.py`, `series/index.json` + per-country files, `--check`, `build-series.yml`, handbook entry. | Yes — a normalised, validated, cadence-resolved observation store is useful on its own |
| **2 · The tab** | Single country, window slider, timeframe, metric, share + absolute, segments, deep links, group rename, Builder cross-links, PNG + CSV export. | Yes — this is the feature as asked for in the thread |
| **3 · Multi-country** | 2–5 series overlaid, shared window, log-y for absolute mode. | Yes |
| **4 · Quarterly support** | Canada + Georgia, `N` snapped to multiples of 3. | Yes |
| **5 · Aggregates** | EU / World / regional groups, summing counts across members. **Strict membership**: a period is emitted only if every member reports it, otherwise the denominator jumps when one country publishes late and the line lies. Show `n = 14/16 reporting`. | Yes |

Phases 1 and 2 are the proposal. 3–5 are consequences that become cheap once the
artifact exists.

---

## 7 · Decisions on record

Settled with the maintainer, 2026-08. Recorded because each one has a plausible
opposite and re-litigating them later without the reasoning is expensive.

| # | Decision | Why |
|---|---|---|
| 1 | **Native monthly only**, no interpolation, no bridging | § 3. Drives the schema, the segment rendering and the quarterly exclusions |
| 2 | **Default window `N = 1`** | The raw observation is the honest default; the cost is that first load disagrees with the TTM artifacts, handled by the caption (§ 5.2) |
| 3 | **Share and absolute both ship in v1** | Absolute makes the seasonality argument visible; multi-country scale problems are handled with a log toggle, not a block |
| 4 | **`series/` is committed to Git** | Operating principle 1. Accepted cost: a commit per data update |
| 5 | **Own tab, group renamed "DIY Curves" → "DIY Charts"**, Builder association via cross-links | § 5.1. Thematically Builder's neighbour, structurally independent — deep links and the model/observation distinction both depend on it |
| 6 | **PNGs coexist, permanently** | § 1.1. The PNG is the tamper-evident dated record; the tab always shows current data including revisions |
| 7 | **Generator in Python**, pinned by the `ttm_bev_share` contract test | § 4.3 |
| 8 | Aggregates deferred to after the tab ships | § 6 phase 5 |

---

## 8 · See also

- [03-data-objects.md](03-data-objects.md) — where `series/` would be documented once built
- [05-flows.md](05-flows.md) — where the build-series flow diagram would go
- [31-proposal-country-source-pages.md](31-proposal-country-source-pages.md) — the cadence-honesty precedent, `observed_cadence()` and `contiguous_runs()`
- `R/data.R` — `load_country_csv()` and `compute_ttm_long()`, the rollup and the strict-window rule this inherits
- `index.html` — `fetchCompareObs()` / `COMPARE_OBS_CACHE`, the client-side fetch pattern to reuse
