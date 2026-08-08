# 35 · Proposal: the "Raw Data" tab

**Status:** Concept, decisions locked (2026-08). Nothing built.
**Audience:** the maintainer + whoever implements this later.
**Origin:** an X thread with @AndreasMemmer — a static PNG of the German BEV
share of new registrations over the last 24 months, and the reply *"sone
Graphik live und einstellbar bei mir auf der gallery einzubauen. Monatlich,
2,3,4… wieviele Monate auch immer."*

---

## 1 · What this is

**A viewer for the country CSVs.** Stacked bars, one bar per period, absolute or
relative, with the bar width set by a window control: 1 period, 2, 3, … 12.
Optionally aggregated across countries.

That is the whole feature. No model, no fit, no projection, no `params.csv`.
Every number on this tab is a number that is literally in
`data/<Country>.csv`, or a sum of such numbers.

Why it is worth building: the gallery has ~6 800 rows of hand-collected
registration data across 51 countries, and **there is currently no way to look
at it on the site.** Every existing tab shows model output derived from it. The
raw data is downloadable and diffable in Git, which serves contributors, and
invisible to everyone else.

### 1.1 The window control

The window `N` sums `N` consecutive periods into one bar:

| `N` | What one bar is |
|---|---|
| 1 | One reporting period as filed. **Default.** |
| 3 | A quarter's worth |
| 12 | A year's worth — the same trailing-twelve-month figure the TTM PNGs show |

For quarterly-native countries (§ 3.3) a period *is* a quarter, so the same
control gives 1 quarter, 2 quarters, 4 quarters (= a year). The unit follows the
data; the label follows the unit.

No seasonality lecture in the UI. A stacked bar chart of registration counts is
a thing people can read, and the window is self-evident once labelled. What the
tab *does* owe the reader is what the coloured bands mean — which is § 2, and is
the hard part.

### 1.2 Relationship to the static PNGs

The PNGs stay, permanently. They do a different job:

> **The PNG is the record. The tab is the instrument.**

A committed `images/2026-07/germany_ttm_shares_20260806.png` is a timestamped
file in Git history: it says what the data looked like on that date and cannot
be silently re-rendered into a different claim. The live tab always shows
*current* data, including later revisions — which is what makes it useful and
exactly what disqualifies it as a receipt.

---

## 2 · The category contract

> *"die fuel type definitions … müssen passen, das Problem hatten wir im Fleet
> Chart schon, dass wir aggregieren was teilweise nicht 100 % stimmig in fuel
> type Kategorien ist"*

This is the design problem. A line chart of BEV share can dodge it — one
numerator, one denominator. **A stacked bar cannot:** every band is a claim
about what the remaining bands are, and the bands have to add up to something
the reader believes. Below is what the data actually looks like, and the rules
that follow.

### 2.1 The 51 `Whole` CSVs are not one schema

Ten header shapes, but only two real families, and **the family is a property of
the row, not of the file**:

| Family | Bands available | Files |
|---|---|---|
| **Split-ICE** | BEV · PHEV · (EREV) · HEV · PETROL · DIESEL · (FLEXFUEL) · OTHERS | the majority |
| **Aggregate-ICE** | BEV · PHEV · (EREV) · HEV · ICE · OTHERS | China, South Korea, Thailand, USA, Chile, Colombia |

Chile and Colombia carry *both* an `ICE` column and `PETROL`/`DIESEL` columns.
The petrol/diesel columns are vestigial — Colombia: 0 of 89 rows populated;
Chile: 9 of 137, and `0.0` in all recent rows while `ICE` carries the real
number. A naive "sum every fuel column" double-counts them.

**Rule 1 — resolve the family per row.** If `ICE` is populated, the row is
aggregate-ICE and `PETROL`/`DIESEL`/`FLEXFUEL` are ignored. Otherwise the row is
split-ICE. Both populated and non-zero in the same row is a validation error, not
something to average over.

### 2.2 `HEV` does not mean the same thing everywhere

Some sources report a **single combined hybrid bucket** — HEV + PHEV (+ MHEV)
all in the `HEV` column, with `PHEV` left empty. Colombia is the clear case: 0 of
89 rows have a `PHEV` value. Malaysia, Nepal and Israel have their own variants
of this.

This is already documented, and — importantly — **already machine-readable**: the
source docs and `country_source_stubs.yaml` carry a `hev_note` front-matter field
for exactly this, consumed today by `build_source_pages.py`. It becomes a second
consumer here.

**Rule 2 — a country with a combined hybrid bucket gets one `Hybrid` band, not a
`HEV` band and an empty `PHEV` band.** Same colour as the combined bucket in the
TTM charts (`R/plots.R:TTM_FUEL_COLORS` already has a `Hybrid` entry for this
case — reuse it). The legend says "combined" and the definitions panel (§ 5.4)
carries the `hev_note` text verbatim.

### 2.3 Bands are not comparable across countries — so collapse before comparing

Germany reports Petrol and Diesel separately. Thailand reports one ICE number.
Colombia cannot separate PHEV from HEV. Put them side by side with their native
bands and the reader compares three different taxonomies.

**Rule 3 — the stack renders at the *coarsest granularity any selected country
can fill*.** Two modes:

- **As reported** (single country, default): the country's native bands.
- **Comparable** (auto-engaged as soon as a second country is selected, or
  aggregation is on): collapse to the common denominator — Petrol + Diesel +
  Flexfuel → ICE where any member is aggregate-ICE; PHEV + HEV → Hybrid where
  any member has a combined bucket.

Collapsing is always safe (summing bands you already have); un-collapsing is
impossible. So the common denominator is computable from the per-country
capability metadata alone, and the UI states which collapse was applied and why.

**For aggregation this is mandatory, not a preference.** Summing a `PETROL`
column across members where half of them do not report one silently under-counts
petrol and inflates the residual. This is the Fleet-chart failure mode, and the
collapse rule is what prevents it.

### 2.4 The residual: a period either adds up or is not served

Across the 51 `Whole` files, summing each row's resolved bands and comparing to
`TOTAL`: **5,779 of 6,849 rows close to within 0.5 %.** The rest are mostly
early history where `BEV` was collected years before `PETROL`/`DIESEL` —
`data/Germany.csv` 2012-07 sums to 0.4 % of `TOTAL`.

An earlier draft gave the gap its own hatched `Unreported` band. **Dropped** —
it put a validation artifact in front of a reader who came to look at
registrations, and it is the kind of thing that makes a simple chart look
complicated. A stacked bar has to add up; a period that cannot is not served.

**Rule 4 — a period whose bands fall short of, or exceed, `TOTAL` is not
drawn.** The chart carries one quiet line instead: *"Germany shown from 2017-01;
the CSV holds back to 2012-01 (60 periods not usable at this quality)."* The
data stays in `data/` and on the source pages, where coverage belongs.

### 2.5 A negative residual is a data error, and one country has them

`Σ bands > TOTAL` cannot be drawn and must not be clamped. It happens:

- **France, 11 rows** where `PETROL + DIESEL` alone exceed `TOTAL`. Worst case
  2020-04: `PETROL 61 796 + DIESEL 33 986` against `TOTAL 20 997` — the COVID
  lockdown month, where the total collapsed but petrol/diesel did not.
- The cause looks structural: **32 of France's 102 petrol/diesel rows repeat the
  previous row's values verbatim** (2020-04 and 2020-05 share `61796 / 33986`;
  2021-04 and 2021-05 share `66149 / 34932`). That is a coarser ACEA figure
  carried across months, the same shape as Germany's pre-2015 BEV values.
- Smaller overshoots elsewhere: Iceland (12 rows), Czechia (14), China (36, all
  under 0.6 % — rounding/OCR noise).

**Rule 5 — a negative residual fails the build** (§ 4.3). Not a render-time
clamp: a chart that quietly hides a 3× overshoot is worse than a build that
stops. France needs a data fix before it can appear on this tab; that is a
separate issue, and this proposal's job is to surface it rather than absorb it.

---

## 3 · Scope of the data shown

### 3.1 `Whole` variants only

Like Builder. `data/<Country>.csv`, no `_Rental` / `_Vans` / `_HDV` / `_Buses`
suffixes. **51 files.** Keeps the selector a country list, keeps the category
contract to one axis of variation, and matches how the rest of the DIY group
already scopes itself.

### 3.2 Native cadence only, contiguous runs as separate blocks

No interpolation, no bridging, no spreading a coarser figure across finer
periods. Cadence is derived from the **observed spacing** of the period labels,
not from `time_interval` — per
[31-proposal-country-source-pages.md](31-proposal-country-source-pages.md), 22
CSVs carry labels that contradict their own spacing.

The obvious implementation ("start at the first monthly period") is wrong, and
so is the careful-looking one ("use the trailing run"). Checked against the data,
4 files have several separate monthly runs of ≥ 12 periods:

| File | Monthly runs (periods) |
|---|---|
| `Italy_Rental.csv` | 63, 75 |
| `Italy_NonRental.csv` | 63, 75 |
| `Singapore.csv` | 37, 78 |
| `Ireland_Buses.csv` | 12, 40, 74 |

(Italy and Singapore are `Whole`-relevant via their siblings' shape; the point
stands for the `Whole` set too.) Taking only the trailing run would discard 63
months of real Italian history. Bridging would invent periods.

**Every contiguous run is its own block of bars.** A gap is a gap on the x-axis —
bars simply stop and resume. Windows never span a gap: a window needs `N`
consecutive periods within one run, otherwise it produces no bar.
`build_source_pages.py:contiguous_runs()` already computes these runs for the
source-page coverage bars; second consumer.

### 3.3 Quarterly-native countries are in, at quarterly resolution

**Canada** (StatCan's cube is quarterly) and **Georgia** never have monthly data.
They are not excluded — they render as quarterly bars, and the window control
offers multiples of a quarter (1, 2, 4, 8 …). The control means "N periods"
throughout; only the label changes with the country.

Mixing a monthly and a quarterly country in one comparison collapses the shared
axis to quarters, by the same logic as § 2.3: aggregate up, never split down.

---

## 4 · Backend

### 4.1 Why an artifact rather than reading the CSVs in the browser

The Compare tab already fetches `data/<Country>.csv` client-side
(`fetchCompareObs()`, `COMPARE_OBS_CACHE`), so this is a real option. The reason
not to: **§ 2 and § 3 are the feature**, and they are not chart code.

Per-row family resolution, the combined-hybrid-bucket lookup, cadence inference,
contiguous runs, the residual computation and its sign check — that is a body of
rules with documented exceptions per country. In the browser it would be a
`switch` on country name inside a render path, re-run on every slider drag, with
no test harness and no way to fail loudly. At build time it runs once, has a
`--check` mode, and blocks a bad merge.

`data/` is an editor-friendly *source* format (principle 6). This adds a serving
format. It does not replace or duplicate the CSVs — it is a projection of them.

### 4.2 The artifact: `series/`

Committed to the repo like `manifest.json` and `sources/` (principle 1).

```
series/
  index.json          # catalogue + per-country capabilities
  <slug>.json         # one per country, 51 files
  report.json         # validation output from the last build
```

**`series/index.json`** — enough to build the selector and the collapse logic
without fetching a single series file:

```json
{
  "generated": "2026-08-08",
  "definitions": {
    "BEV":    "Battery-electric. Plug-in, no combustion engine.",
    "PHEV":   "Plug-in hybrid.",
    "HEV":    "Full hybrid, not plug-in.",
    "Hybrid": "Combined hybrid bucket — this source does not separate PHEV from HEV.",
    "ICE":    "Combustion, not separable into petrol/diesel by this source.",
    "OTHERS": "Reported, but none of the above — LPG, CNG, fuel-cell, …",
    "Unreported": "TOTAL minus everything the source reported for this period. Not a fuel type."
  },
  "countries": [
    {
      "slug": "germany", "country": "Germany", "source": "KBA",
      "source_page": "sources/germany.html",
      "cadence": "monthly",
      "runs": [["2015-01", "2026-07"]],
      "bands": ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS"],
      "ice_split": true, "hybrid_combined": false,
      "unreported_rows": 60
    },
    {
      "slug": "colombia", "country": "Colombia", "source": "ANDI/FENALCO",
      "cadence": "monthly",
      "runs": [["2019-01", "2026-05"]],
      "bands": ["BEV", "Hybrid", "ICE"],
      "ice_split": false, "hybrid_combined": true,
      "hev_note": "Combined hybrids (HEV + PHEV + MHEV) are reported in the HEV column; PHEV is left empty.",
      "unreported_rows": 89
    }
  ]
}
```

`ice_split` and `hybrid_combined` are what the frontend's collapse rule (§ 2.3)
reads; `bands` is already the resolved set, so no client-side schema sniffing.
`hev_note` is lifted verbatim from the source doc front-matter — one source of
truth for that sentence, already rendered on the source pages.

**`series/<slug>.json`** — column-major, aligned to one period vector:

```json
{
  "slug": "germany",
  "periods": ["2015-01", "…", "2026-07"],
  "run":     [0, "…", 0],
  "bands": {
    "BEV":    [659, "…"],
    "PHEV":   [1095.7, "…"],
    "HEV":    [1566.98, "…"],
    "PETROL": [null, "…"],
    "DIESEL": [null, "…"],
    "OTHERS": [0, "…"]
  },
  "unreported": [207415.3, "…"],
  "TOTAL":      [211337, "…"]
}
```

Bands are already family-resolved (§ 2.1) and hybrid-resolved (§ 2.2), so
`Σ bands + unreported ≡ TOTAL` holds for every period in every file, by
construction. The client stacks what it is given.

### 4.3 The generator

`scripts/build_series.py`, alongside `build_schedule.py` and
`build_source_pages.py`. Python because `observed_cadence()`, `contiguous_runs()`
and the `hev_note` front-matter reader all already live there, and because no
other build-time generator needs an R toolchain.

**No cross-check against `params.csv`.** An earlier draft proposed pinning the
generator's 12-period BEV share to `params.csv:ttm_bev_share`. That was model
thinking leaking into a raw-data feature: this tab has no relationship to the
fit, and a coupling to the fitted parameter file would make a raw-data build fail
for a modelling reason. Dropped.

**Validation, `--check` mode** (mirrors `build_source_pages.py --check`, runs on
PRs, writes nothing):

| Check | Severity |
|---|---|
| `Σ bands > TOTAL` (negative residual) | **fatal** — § 2.5, France today |
| `ICE` and `PETROL`/`DIESEL` both populated non-zero in one row | **fatal** — § 2.1 |
| Duplicate periods | fatal |
| `TOTAL` missing or ≤ 0 while bands are populated | fatal |
| `hev_note` present but `PHEV` column also populated | fatal — the metadata and the data disagree |
| A band at exactly zero between two populated, non-trivial neighbours | recorded in `report.json` — § 4.3b |
| Periods flagged as smeared (§ 3.1b) | recorded, and marked in the artifact |
| Rows with a non-zero `Unreported` band | recorded in `report.json` |
| `time_interval` contradicts observed spacing | recorded |
| Runs shorter than 12 periods | recorded |

Fatal-by-default matches the fetchers (Indonesia's checksum abort, Türkiye's
three validation layers). **France fails this gate today** and needs its
petrol/diesel carry-forward fixed before it can render.

### 4.3b A band can vanish without breaking any sum

`data/Colombia.csv` carries `BEV = 0.0` for `2025-07`, between **1,143** in June
and **1,647** in August. Colombia did not sell zero BEVs that month.

What makes this worth its own check: **the row still closes to `TOTAL`
perfectly**, because `ICE` is a residual that absorbed the missing cars. Every
check in the table above passes. The stacked bar simply drops its green band for
one month, and nothing anywhere says why.

The detector is cheap — a band at exactly zero with populated, non-trivial
neighbours on both sides. Across all 51 `Whole` files it finds **7 candidates**:

```
Belgium    OTHERS  2022-03     258 →  0 →   171
Belgium    OTHERS  2023-02     281 →  0 →   403
Belgium    OTHERS  2023-09     166 →  0 →   248
Colombia   BEV     2020-04     110 →  0 →    51   (April lockdown — may be real)
Colombia   BEV     2023-11     287 →  0 →   493
Colombia   BEV     2025-07   1,143 →  0 → 1,647
Singapore  HEV     2022-12     930 →  0 →   776
```

Not all are necessarily errors, which is why this is a `report.json` flag to
review rather than a fatal check.

### 4.4 CI wiring

New workflow `build-series.yml`:

- **Trigger:** `push` on `master`, path filter `data/**`, plus
  `workflow_dispatch`. One rule catches every writer — the 29 fetchers, manual
  commits, merged submission PRs — instead of chaining a dispatch into 29
  workflow files.
- **Writes** `series/**` only; since the trigger filters on `data/**` its own
  commit cannot re-trigger it.
- **On PRs:** `--check` only. This is the useful part: a submission PR that
  breaks the category contract is rejected before merge.
- Not folded into `build-manifest.yml`, which is keyed on `images/**`.

### 4.5 What this does not add

No Worker, no API, no secret, no database, no frontend build step, no new CDN
dependency (Plotly is already loaded). Operating principle 4 — static-first on
the read path — holds.

### 4.6 Size

51 files, counts only, non-native periods dropped, gzipped by Pages. Well under
the 1.4 MB the full `data/` tree occupies today. Per-country files so the tab
fetches only what is selected and a single-country update invalidates one cache
entry; mirrors `COMPARE_OBS_CACHE`.

---

## 5 · Frontend

### 5.1 Name and placement

**"Raw Data"**, in the Builder group, with the group renamed **"DIY Curves" →
"DIY Charts"** (the tab has no curve in it):

```
DIY Charts:  Builder · Compare · Raw Data · Fleet
```

"Raw Data" over "Monthly" because it says what the tab is — the CSVs, drawn —
rather than one of its settings, and because it stays accurate for the quarterly
countries.

**Own tab, not a Builder sub-tab.** Thematically it is Builder's neighbour, and
that is what the group and cross-links are for. Structurally: Builder's bootstrap
loads `params.csv` + `weights.csv` + aggregate state this tab uses none of; and
deep links are the point (§ 5.3) — `#rawdata?c=Germany&n=1` is a link you paste
into a reply, `#builder?sub=rawdata&…` is a level deeper and couples two URL
grammars. Builder gets a "see the raw data" link that opens this tab pre-filled
with the current country, and back.

### 5.2 Controls

| Control | Default | Notes |
|---|---|---|
| Country | Germany | Multi-select; a second selection engages Comparable mode (§ 2.3) |
| Window `N` | 1 period | Slider 1–12 (quarterly countries: multiples of a quarter), presets `1 / 3 / 12` |
| Timeframe | **all bars** | all / 5y / 2y |
| Units | absolute | Toggle to relative (100 % stacked) |
| Aggregate | off | Sums selected countries into one stack; forces Comparable mode |
| Export | — | PNG and CSV of exactly what is plotted, plus an optional QR of the settings URL rendered into the chart |

### 5.3 Rendering and state

- **Plotly** stacked bar (`barmode: 'stack'` / `'relative'`), via the existing
  `ensurePlotly()` + `hashchange` lazy-init pattern (`loadFleetWhenActive()` is
  the template). Dark layout object and `@LeRaffl` annotation from Compare.
- **Band colours from the Fleet tab's palette** (`FE_C` in `index.html`), which
  is already built for the dark surface Builder and Compare use. Two pairs had
  to be re-stepped to be tellable apart as adjacent bands — BEV↔PHEV measured
  ΔE 12.5 and Diesel↔Petrol ΔE 9.1 against a threshold of 15. After re-stepping,
  both band sets pass colour-vision separation, normal-vision separation and
  contrast. `ICE` reuses the diesel brown: a country reports one or the other,
  never both in the same stack.
- **Run blocks** (§ 3.2) render as gaps in the category axis, not as bridged bars.
- **Prefix sums per run**, so a window is two lookups and dragging the slider is
  O(1) per bar. Debounce with the existing helper.
- **`SERIES_CACHE`** keyed by slug, same shape as `COMPARE_OBS_CACHE`.

**Deep links.** `…/#rawdata?c=Germany&n=1&t=24&u=abs` has to work — pasting a
configured chart into a reply is the use-case the thread started from. Today
`activateTabByHash()` does `hash.replace('#','')` → `getElementById('tab-'+id)`,
so a query string falls through to About. Contained change: split on `?` before
the lookup (existing tabs unaffected), pass the `URLSearchParams` to the tab's
init, write state back with `history.replaceState`. Also what makes the
Builder ↔ Raw Data cross-links work.

### 5.4 The definitions panel

The one piece of explanation the tab owes the reader, and the answer to *"sie
brauchen nur Kontext was sie da sehen"*. Below the chart, driven entirely by
`index.json`, changing with the selection:

- **What each visible band means** — one line each, from `definitions`.
- **What this country cannot separate** — the `hev_note` verbatim where present
  ("Colombia reports hybrids as one combined bucket"), and an aggregate-ICE note
  where `ice_split` is false.
- **What was collapsed and why** — in Comparable mode: *"Petrol and Diesel merged
  into ICE because Thailand does not report them separately."*
- **What `Unreported` is** — stated as the absence of a measurement, not a fuel,
  with the affected span (*"Germany: petrol/diesel from 2015-01; earlier bars
  show BEV against the market total only"*).
- **Source and freshness** — source name, last period, link to
  `sources/<slug>.html`.

No seasonality warning at `N = 1` or `N = 12`. Users can read a bar chart; what
they cannot do is guess that Colombia's yellow band means something different
from Germany's.

### 5.5 Cost to `index.html`

~428 KB / ~9.5k lines today; this adds ~400. Acceptable, no split proposed — but
this is where a `js/` extraction would start if the single-file approach stops
paying.

---

## 6 · Phasing

| Phase | Scope | Ships alone? |
|---|---|---|
| **0 · Spike** | One country, client-side straight from `data/Germany.csv`. Throwaway; proves the stack reads well and the slider feels right before any backend exists. | not shipped |
| **1 · Backend** | `build_series.py`, `series/`, `--check`, `build-series.yml`, handbook entry. | Yes — a validated, category-resolved projection of the CSVs is useful on its own, and the PR gate catches bad submissions immediately |
| **1b · France** | Fix the petrol/diesel carry-forward (§ 2.5) so France passes the gate. Separate issue, blocking only for France. | Yes |
| **2 · The tab** | Single country, stacked bars, window, timeframe, absolute + relative, run blocks, definitions panel, deep links, group rename, cross-links, PNG + CSV export. | Yes — this is the feature |
| **3 · Multi-country** | 2–5 countries, Comparable mode + collapse notices. | Yes |
| **4 · Aggregation** | Sum across countries. **Strict membership**: a period is emitted only if every member reports it, otherwise the denominator jumps when one country publishes late. Show `n = 14/16 reporting`. | Yes |

---

## 7 · Decisions on record

Settled with the maintainer, 2026-08.

| # | Decision | Where |
|---|---|---|
| 1 | Stacked bars of the country CSVs — **no model, no `params.csv`, no fit** | § 1, § 4.3 |
| 2 | **`Whole` variants only**, like Builder — 51 files | § 3.1 |
| 3 | **Native cadence only.** Quarterly countries render as quarters with quarter-multiple windows; monthly runs are separate blocks, never bridged | § 3.2, § 3.3 |
| 4 | **Absolute and relative** both ship; aggregation optional | § 5.2 |
| 5 | **Tab named "Raw Data"**, own tab, group renamed "DIY Curves" → "DIY Charts", Builder association via cross-links | § 5.1 |
| 6 | **No seasonality warnings.** A definitions panel instead — fuel-type meanings, per-country quirks, collapse notices | § 5.4 |
| 7 | **A period that does not add up is not drawn**, and the chart says so in one line — no `Unreported` band, no validation UI in front of the reader | § 2.4 |
| 8 | **Negative residuals fail the build**, they are not clamped at render time | § 2.5 |
| 8b | **Smearing and zero-dropout detectors** added after the mockup — both catch conditions no sum check sees | § 3.1b, § 4.3b |
| 8c | **Granularity per period drives the window control** — divided smears keep their data at multiples, copied smears are dropped | § 3.1b |
| 8d | **Fleet-tab palette**, re-stepped where adjacent bands were not tellable apart | § 5.3 |
| 9 | `series/` committed to Git | § 4.2 |
| 10 | Aggregation deferred to after the tab ships | § 6 |

---

## 8 · Open items

**A clickable mockup exists** — the real CSVs run through a ~150-line prototype
of § 2 and § 3, rendered as the tab would render them, with all eight demo
countries and the findings below written up inline.

**France does not pass the category contract.** 11 rows where petrol + diesel
alone exceed `TOTAL`, and 32 of 102 petrol/diesel rows repeating the previous
row verbatim — a coarser ACEA figure carried across months. Needs a data
decision (drop the carried values to `null` and let them show as `Unreported`, or
re-derive from a finer source) before France can render. Tracked as phase 1b.

**Two data-quality checks were added by the mockup**, both catching things the
original rules missed: smeared values (§ 3.1b) and zero-dropouts (§ 4.3b).
Neither is a chart problem — they are pre-existing data conditions that a
stacked bar makes visible for the first time.

**The band palette does not survive a dark plot surface.** Against the
`#0f1525` that Builder and Compare use, Petrol `#502900` sits at 1.44:1 and
Other `#3c2f2f` at 1.42:1 — the combustion half of the stack disappears. The
mockup solves it by keeping the plot panel light inside the dark chrome, which
also matches the PNGs. Separately and on any background, `Petrol #502900` vs
`Other #3c2f2f` measures ΔE 6.4 for normal colour vision against a threshold of
15 — they are effectively one colour, **already true in every TTM PNG showing
both**. Moving `Other` to a neutral (e.g. `#6b7280`, ΔE 34) fixes it in one
value, but it changes the PNGs too, so it is a maintainer call. `TTM_FUEL_COLORS`
is untouched.

---

## 9 · See also

- [03-data-objects.md](03-data-objects.md) — where `series/` gets documented once built
- [05-flows.md](05-flows.md) — where the build-series flow diagram goes
- [31-proposal-country-source-pages.md](31-proposal-country-source-pages.md) — `observed_cadence()`, `contiguous_runs()`, and the `hev_note` front-matter this reuses
- `R/plots.R` — `TTM_FUEL_COLORS`, the palette this tab must match
- `index.html` — `fetchCompareObs()` / `COMPARE_OBS_CACHE`, the fetch pattern to reuse
