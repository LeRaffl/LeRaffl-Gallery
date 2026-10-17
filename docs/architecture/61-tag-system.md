---
explainer: true
slug: tags
title: How the tags work
summary: Every gallery card carries up to three small tags — Status, Speed and Timing — read off the market's fitted S-curve. Status is absolute (80 % share and the year 2035). Speed and Timing are relative — a market is compared with the other markets of its vehicle type, so trucks are measured against trucks, not against cars.
boxplots: true
sections:
- heading: Reference groups
  text:
  - Only base variants define a scale. For cars that is the main new-car curve (Whole) of every market, one per country. Car subsets — private and company keepers, rental and non-rental, used imports, and other car slices — do not shape the scale; they are placed on Whole's scale, like a dot on Whole's boxplot.
  - Vans, trucks (HDV), buses, two- and three-wheelers and so on are their own reference groups. A subset of one of them is compared against that parent — Canada's pickup trucks, for example, are placed on the Vans scale.
  - In the sidebar filter, a market in a group too small for a scale has no speed or timing tag. It shows while that category is unfiltered and is hidden as soon as a specific speed or timing value is selected; it is never counted as Mid.
  - A reference group needs at least 4 markets. Smaller groups — and their subsets — get no speed or timing tag.
- heading: The three tags
  text:
  - Status — where the fitted curve crosses 80 % BEV share of new registrations. Past 80 % (already crossed), On track (by the end of 2035), Late (after 2035). The same for every vehicle type.
  - Speed — the slope of the fitted curve at its steepest point. Fast = top quarter of the reference group, Slow = bottom quarter, Avg speed = the middle half.
  - Timing — the year the fitted curve crosses 10 % BEV share. Markets still below 10 % count with their projected year. Early starter = earliest quarter of the reference group, Late starter = latest quarter; the middle half carries no timing tag.
  - Curves that show no transition get a single No transition tag, and fits that cannot be trusted yet (unsettled, collapsed or stale) a single Unreliable fit tag; neither counts towards any scale.
processing:
- title: Read every fitted curve
  text:
  - One row per market and variant from params.csv (the S-curve parameters, the latest data month, the observed BEV share and the re-fit stability).
- title: Can the curve carry tags?
  decision:
    ask: Does the curve show a transition?
    branches:
    - when: no — no S-shape, or the peak adoption rate stays negligible
      then: No transition (single tag, not in any scale)
    - when: 'yes'
      then:
        ask: Is the fit reliable?
        branches:
        - when: no — unsettled, collapsed or stale
          then: Unreliable fit (single tag, not in any scale)
        - when: provisional — moved 5–25 years across re-fits
          then: tags drawn hollow, counts in its scale
        - when: 'yes'
          then: tags solid, counts in its scale
- title: Pick the reference group
  decision:
    ask: Is the variant a subset of another one (TAG_PARENT)?
    branches:
    - when: Private, Industry, Rental, NonRental, Used, Custom, Wholesale, 4-Wheelers, …
      then: Whole (classified on Whole's scale, does not shape it)
    - when: Pickups
      then: Vans (classified on the Vans scale)
    - when: no — a base variant (Whole, Vans, HDV, Buses, 2-Wheelers, …)
      then: its own group (shapes the scale, one row per country)
- title: Build each group's scale
  decision:
    ask: At least 4 markets in the reference group?
    branches:
    - when: 'no'
      then: no speed / timing tag for the group and its subsets
    - when: 'yes'
      then: 25th and 75th percentile of the 10 % year and of the speed
- title: Assign the tags
  rules_head: [When, Then]
  rules:
  - [fitted 80 % crossing before today, Past 80%]
  - [fitted 80 % crossing by end of 2035, On track]
  - [fitted 80 % crossing after 2035, Late]
  - [speed at or above the group's 75th percentile, Fast]
  - [speed at or below the group's 25th percentile, Slow]
  - [speed in between, Avg speed]
  - [10 % year at or below the group's 25th percentile, Early starter]
  - [10 % year at or above the group's 75th percentile, Late starter]
  - [10 % year in between, no timing tag]
---

# 61 — Gallery tag system (v2)

Reader-facing page: **`sources/tags.html`** ("How the tags work"), generated
from the front-matter above by `scripts/build_source_pages.py` (explainer
pages; same flow / decision-tree renderer as the country source pages). Linked
from the gallery sidebar (*Status, speed, timing & fit* → *How the tags work*),
the FAQ entry *What do the small tags on gallery cards mean?*, and named in
every tag popover. The page draws **live boxplots** (`assets/tag_boxplots.js`)
from `params.csv` with the gallery's own tag functions.

Introduced for [#294](https://github.com/LeRaffl/LeRaffl-Gallery/issues/294):
the old timing cut-offs were fixed calendar years (10 % before 2023 = *Early*,
after 2025 = *Late*) for every variant, and the speed quartiles came from one
pool mixing cars with trucks, so not a single HDV market could ever be an
*Early starter*.

## Code map

| File | Role |
|---|---|
| `assets/fit_core.js` | `parseCSV`, `normNumber`, `getDataPer`, `inv_x_years`, `rowHasNoTransition`, `fitReliability` + `FIT_*` — moved verbatim out of index.html; classic script, globals as before |
| `assets/tag_system.js` | **all tag logic**: `TAG_PARENT` (subset → parent; **add a line here for a new subset**), `tagGroupOf()`, `tagIsReference()`, `tagGroupCutoffs()` (only eligible reference rows, one per country; `TAG_MIN_GROUP = 4`, `TAG_LOW_Q / TAG_HIGH_Q`), `timingTagFor()`, `speedTagFor()`, `statusTagFor()` (80 % / `TAG_TARGET_YEAR` 2035), `tagComputeAll(rows)` |
| `assets/tag_boxplots.js` | SVG boxplots with tag braces; `mount()` for sources/tags.html, `svg()` for the gallery popover |
| `index.html` | loads `fit_core.js` + `tag_system.js` in `<head>` (before every inline script), `tag_boxplots.js` deferred. Tag IIFE (*gallery status pills*): pills, `window.__bevTagsByCountry / __bevTagCutoffs / __bevTagPoints`; glossary IIFE: popover with group cut-offs and mini boxplot (`boxplotRow()`) |
| `sources/tags.html` | generated explainer page; loads the three assets + `../params.csv` — never index.html |
| `scripts/tag_system_report.js` | runs the same assets under node (one `vm` context = one page); `--by-variant`, `--legacy`, `--json` |
| `scripts/test_tag_system.py` | tests on the same assets |

## Consumers of the tag outputs (audit, 2026-10-17)

| Consumer | Uses | Changed by v2? | Adapted |
|---|---|---|---|
| Gallery cards (`.tag-stack` in the card footer, `paint()`) | `__bevTagsByCountry[key]` | yes — speed/timing pills follow the reference group | yes (same object) |
| Thresholds table, "Tags" column | same `.tag-stack` / `paint()` (MutationObserver on `thresholdsMount`) | yes, identical to the cards | yes (automatic) |
| Durations table, "Tags" column | same (`durationsMount`) | yes, identical | yes (automatic) |
| Durations "Numerical speed" column / sort, Speed tab chart, Time interval | raw slope / crossing years, **not** the tags | no | not needed — rankings stay global numbers; only the *labels* are per group |
| Sidebar tag filters (`getActiveTagFilters`, `passesTagFilter`) | `__bevTagsByCountry[*].{status,speed,timing,unsettled,notrans,noscale}`; missing timing ⇒ `mid` | yes — pills differ | yes — rows whose reference group has < 4 markets carry `noscale.{timing,speed}`: shown while that category is unfiltered, **hidden as soon as a specific value of that category is selected**, never counted as *Mid* (decision 2026-10-17) |
| Tag popover / glossary | cut-offs, points, CATS texts | yes | yes (per-group wording, mini boxplot, link text) |
| FAQ "What do the small tags…" | static text | yes | yes |
| Sidebar labels (Speed / Timing) | static text | yes | yes ("quartile of its group") |
| World map (`wmClassify`, `wmBuildRows`) | `rowHasNoTransition`, `rowIsUnreliableFit` — no tags | no | moved functions only (now from `fit_core.js`) |
| Fit reliability gate in Thresholds / Durations / Time interval | `fitReliability` | no | moved only |
| `scripts/snapshot_builder.py` (+ test) | own Python mirror of the curve maths; no tags | no | no |
| R (`fit.R` refit_swing, `post_text.R`, `render_*.R`) | no tags (refit_swing feeds `fitReliability`) | no | no |
| posts/*.txt, X/Bluesky drafts | BEV/PHEV/ICE shares only; no tag words | no | no |
| `manifest.json`, `weights.csv`, `params.csv`, `bands/*.json`, `sources/sources.json` | no tag fields | no | no |
| `index_legacy.html` | its own frozen copy of the old v1 rules (2023/2025) | — | **not adapted** (legacy snapshot, not linked from anywhere) — flagged |
| `.github/workflows/build-source-pages.yml` | builds `sources/` | doc 61 now produces `sources/tags.html` | yes — path trigger for `61-tag-system.md` added |

## Parent map (current)

| Variant | Reference group |
|---|---|
| Whole | Whole (reference) |
| Private, Industry, Rental, NonRental, Used, Used Imports, Resale, Fleet, Custom, Wholesale, 4-Wheelers | Whole |
| Pickups (Canada, StatCan pickup trucks GVWR ≤ 14,000 lb ≈ N1 + part N2) | Vans |
| Vans, HDV, Buses, 2-Wheelers, 3-Wheelers, Non-Passenger | own group |

**Non-Passenger (Canada)** is an orphan `params.csv` / `weights.csv` row from the pre-pipeline hand-maintained sheet (last data 2025-12, `refit_swing` Inf → *Unreliable fit*, so it never carries speed/timing tags). Its TTM volume (1.63 M) only fits "all light vehicles except passenger cars" (SUVs + pickups + vans). Not retired yet: `render-country.yml` still offers it as a dispatch option — see PR #326.

## Cut-offs on params.csv as of 2026-10-17

| Group | timing n | t10 P25 / P75 | speed n | speed P25 / P75 (%/yr) |
|---|---|---|---|---|
| Cars (Whole) | 52 | 2021.9 / 2026.7 | 51 | 5.0 / 11.4 |
| Vans | 18 | 2024.5 / 2028.8 | 18 | 3.7 / 10.5 |
| HDV | 16 | 2025.0 / 2028.8 | 16 | 7.4 / 11.6 |
| Buses | 13 | 2021.7 / 2024.7 | 13 | 3.9 / 15.5 |
| 3-Wheelers | 2 | no tag | 0 | no tag |
| 2-Wheelers | 0 | no tag | 0 | no tag |
| Non-Passenger | 0 | no tag | 0 | no tag |

Regenerate with `node scripts/tag_system_report.js` (`--by-variant` for one
line per variant, `--legacy` for the pre-v2 rules, `--json`).

## Tests

- `python scripts/test_tag_system.py` — parent mapping, reference-only
  pools, one row per country, quartiles, minimum, extrapolated years, the
  #294 symptom on the live `params.csv`, and that `assets/tag_boxplots.js`
  can load every function it names from index.html.
- `python scripts/build_source_pages.py --check` validates the front-matter.
