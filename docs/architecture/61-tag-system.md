# 61 — Gallery tag system (v2)

The small pills on every gallery card (and the sidebar tag filters) summarise
one fitted curve per `params.csv` row. This page is the spec; the code lives in
`index.html` (`tagGroupCutoffs()` and friends next to `fitReliability()`, the
tag IIFE under *gallery status pills*, the glossary IIFE right after it, and the
FAQ entry *What do the small tags on gallery cards mean?*). Keep the four in
sync.

Introduced for [#294](https://github.com/LeRaffl/LeRaffl-Gallery/issues/294):
the old timing cut-offs were fixed calendar years (10 % before 2023 = *Early*,
after 2025 = *Late*) for every variant, and the speed quartiles came from one
pool mixing cars with trucks. Electric trucks only became available years after
electric cars, so not a single HDV market could ever be an *Early starter*.

## Order of decisions per row

1. `rowHasNoTransition(row)` → single **No transition** pill, nothing else.
2. `fitReliability(row).status === 'excluded'` → single **Unreliable fit** pill.
3. Otherwise **Status**, **Speed**, **Timing** as below; a `provisional` fit
   keeps them, drawn hollow.

## Vehicle groups

`tagGroupOf(variant)`: `Whole`, `Private` and `Industry` form one group
(**Cars**). Every other variant is its own group (`Vans`, `HDV`, `Buses`,
`Used`, `Rental`, `NonRental`, `2-Wheelers`, …). Speed and timing compare a row
only with rows of its group.

**Pool** = rows of the group that transition and are not excluded
(provisional fits count). The quartiles are taken over all pool rows; the
minimum counts **distinct countries**, so a market with Whole + Private +
Industry rows counts once towards the minimum but contributes three values.

**Minimum**: `TAG_MIN_GROUP = 4` countries per pool and dimension. Below that
the group gets **no speed / no timing pill** at all.

## The three tags

| Tag | Read off | Rule | Scope |
|---|---|---|---|
| Status | fitted 80 % crossing `t80` | `≤ today` *Past 80 %*, `≤ 2035` *On track*, else *Late* | absolute, unchanged |
| Speed | slope at the inflection point | `≥ P75` *Fast*, `≤ P25` *Slow*, else *Avg speed* | per group |
| Timing | fitted 10 % crossing `t10` | `≤ P25` *Early starter*, `≥ P75` *Late starter*, middle half: no pill | per group |

Timing is **share-based**: the fitted calendar year at 10 % BEV share.
Markets still below 10 % count with their **extrapolated** year — leaving them
out would make the late quarter consist of markets that have already arrived.

Constants: `TAG_MIN_GROUP`, `TAG_LOW_Q = 0.25`, `TAG_HIGH_Q = 0.75` (top
level), `PAST_THRESHOLD = 0.8`, `TARGET_YEAR = 2035` (tag IIFE).

## Explanations shown to readers

- Hovering a speed or timing pill shows that group's actual cut-offs, e.g.
  *Crosses 10 % BEV share by 2025 — earliest quarter of HDV (16 markets)*
  (`groupView()` in the glossary IIFE, data from `window.__bevTagCutoffs`).
- Hovering a sidebar chip lists the cut-offs of every group, and *no tag* for
  groups below the minimum.

## Cut-offs on params.csv as of 2026-10-17

| Group | timing n | t10 P25 / P75 | speed n | speed P25 / P75 (%/yr) |
|---|---|---|---|---|
| Cars | 53 | 2021.6 / 2026.7 | 52 | 5.1 / 11.6 |
| Vans | 18 | 2024.5 / 2028.8 | 18 | 3.7 / 10.5 |
| HDV | 16 | 2025.0 / 2028.8 | 16 | 7.4 / 11.6 |
| Buses | 13 | 2021.7 / 2024.7 | 13 | 3.9 / 15.5 |
| Used | 6 | 2026.1 / 2026.6 | 6 | 3.5 / 11.4 |
| NonRental, 3-Wheelers, Pickups, Rental, 2-Wheelers, … | < 4 | no tag | < 4 | no tag |

Regenerate with `node scripts/tag_system_report.js` (add `--legacy` for the
pre-v2 rules, `--json` for machine output).

## Processing

```text
params.csv
  → per row: noTrans? → "No transition"
            excluded? → "Unreliable fit"
  → eligible rows → group = tagGroupOf(variant)
  → per group: ≥ 4 countries? → P25/P75 of t10 and of inflection speed
  → per row: Status (absolute) + Speed + Timing (group cut-offs)
  → window.__bevTagsByCountry / __bevTagCutoffs → pills, filters, glossary
```

## Tests

- `python scripts/test_tag_system.py` — grouping, quartiles, minimum,
  extrapolated years, and the #294 symptom on the live `params.csv`.
