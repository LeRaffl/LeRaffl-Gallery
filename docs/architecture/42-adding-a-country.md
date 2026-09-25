# 42 · Adding a country — the complete playbook

The one checklist for putting a new country (or a new country-level source)
on the gallery, from the first probe to the first render. Every item names
the file it touches and, where one exists, the check in
`scripts/check_country_integration.py` that fails when it is forgotten — CI
runs that script on every PR (`check-country-integration.yml`), so a country
cannot be merged half-wired.

Worked example throughout: **Hong Kong** (PR #254,
[41-source-hong-kong.md](41-source-hong-kong.md)). Earlier ones: Ukraine
([40](40-source-ukraine.md)), Argentina ([39](39-source-argentina.md)).

```
Phase 0  Find and probe the source ........ docs 14 / 33, temporary probe workflow
Phase 1  Decide scope and mapping .......... variants, new/used, fuel, history start
Phase 2  Fetcher + tests ................... scripts/fetch_<slug>.py, test_fetch_<slug>.py
Phase 3  Workflow .......................... .github/workflows/fetch-<slug>.yml
Phase 4  Backfill the data ................. data/<Country>[_<Variant>].csv, market/
Phase 5  Wire it into the gallery .......... index.html, R/, assets/flags/, footnotes.csv
Phase 6  Groupings ......................... BUILDER_GROUPS (both mirrors), COUNTRY_REGION
Phase 7  Documentation ..................... source doc + 9 living docs
Phase 8  History: backtest + Time-lapse .... dispatch snapshot-builder.yml on the branch
Phase 9  Verify, clean up, PR .............. local checks, remove probes, open the PR
Phase 10 After merge ....................... first render, check the source page
```

---

## Phase 0 — Find and probe the source

1. **Read the bar first**: [14-data-source-gaps.md](14-data-source-gaps.md)
   (direct from the registry or its recognised body, complete for the market,
   free — a free account is acceptable, payment or an ID number is not) and
   the candidate list [33-expansion-candidates.md](33-expansion-candidates.md).
   Prefer record-level registries (one row per vehicle): they give brand and
   model tables for free and can be validated.
2. **Probe from CI, not from the dev sandbox.** The Claude sandbox reaches
   almost nothing; GitHub runners reach almost everything. Pattern:
   - add `scripts/probe_tmp.py` + `.github/workflows/probe-tmp.yml` with
     `on: push: branches: [<your branch>]` (a new `workflow_dispatch`-only
     file cannot be dispatched until it is on the default branch);
   - use `sparse-checkout: scripts` so a probe starts in seconds;
   - to bring files back (raw downloads, generated CSVs), let the probe
     commit them to `probe_out/` on the branch
     (`git add --sparse -f probe_out`); read logs through the GitHub API.
   - Probes are **temporary**: they are removed and the branch history is
     rewritten before the PR (Phase 9).
3. **Record what you find**, success or not, in doc 33 (status line, what was
   probed, what would change a "no"). If no country clears the bar, that
   entry *is* the deliverable.

## Phase 1 — Decide scope and mapping (write it down before coding)

| Decision | Rule | Hong Kong |
|---|---|---|
| Variants | Anchored to EU classes ([09](09-glossary.md)): `Whole` = new M1; `Vans` = N1; `HDV` = N2+N3; `Buses` = M2+M3; `Used` = used vehicles at their first national registration; sub-slices `Private`/`Industry`/`Rental`/`NonRental` | Whole, Used, Vans |
| New vs used | Use the **source's own** classification, never a heuristic | TD status A/B/C1 vs C2 |
| Fuel columns | Only columns the source really reports; no-split → empty, never `0.0` (invariant 4) | BEV, PHEV, EREV, PETROL, DIESEL, OTHERS |
| Hybrids | Real split → PHEV/HEV/MHEV; one combined value → `HEV` column + `hev_split: false` (Türkiye/Ukraine convention); none → state where they sit | no hybrid value: plug-ins classified from the model, full/mild in PETROL |
| History start | The first month the source's definition is stable. Do not splice a series across a definition break (invariant 3) | 2019-11; the older aggregate table has a different "brand new" |
| Validation | An independent published total for the same scope, compared every run if possible | TD table 4.1(e), exact over 80 months |

## Phase 2 — Fetcher and tests

`scripts/fetch_<slug>.py` — copy the closest existing fetcher
(record-level: `fetch_hong_kong.py`, `fetch_ukraine.py`; PDF: `fetch_colombia.py`;
API: `fetch_denmark.py`). Non-negotiables:

- **Line-level upserts** keyed on `(period, variant)`; untouched lines stay
  byte-identical (invariant 2); a row with a foreign `source` is not
  overwritten without `--force`.
- **One `source` string** per fetcher, used for the self-throttle.
- **Self-throttle before downloading**: if every CSV already has the target
  month from this source, exit without heavy HTTP.
- **Governance that fails loudly**: schema drift (missing columns) aborts;
  unknown category values are listed, and abort above a threshold; fuels sum
  to TOTAL; a completeness guard on the newest month (set it loose enough for
  real policy shocks — Hong Kong's is 25 %, with a warning below 50 %);
  cross-check against an independent total if one exists.
- **Step summary** (`GITHUB_STEP_SUMMARY`): the month's table plus everything
  a human must review (new categories, classified models, cross-check).
- **`GITHUB_OUTPUT`**: `changed` and `changed_variants` (JSON list) for the
  render dispatch.
- **Brand + model tables** when the source has brand and model per
  registration: count `(class, brand, model)` with the same class logic as
  the CSV and write `market/<slug>_top.json` through `scripts/market_top.py`
  inside `market_top.guarded()` ([03](03-data-objects.md) §3.16).
- **An offline mode** (`--from-dir` / `--from-agg`) so tests and rebuilds need
  no network.

`scripts/test_fetch_<slug>.py` — plain-Python tests, no network: scope rules,
every mapping (including look-alikes that must *not* match), each published
header layout, the cross-check, the completeness guard, the upsert. If you
classify from names, assert every rule has a test case.

## Phase 3 — Workflow

`.github/workflows/fetch-<slug>.yml` — copy `fetch-hong-kong.yml`:

- header comment: what, where from, publication timing, what a normal and a
  backfill run download, a pointer to the source doc;
- `workflow_dispatch` inputs `variant`, `period`, `backfill`, `force`;
- **cron**: pick a free minute (see the table in [08](08-deploy-ops.md) §8.11);
  a day window if the source publishes predictably, daily otherwise;
- tests gate the fetch; `EndBug/add-and-commit` with `pull: '--rebase
  --autostash'`; **a path with a space** must be a git pathspec glob
  (`data/Hong?Kong*.csv`) because the action splits `add` on whitespace;
- a `render` job that dispatches `render-country.yml` **once** with
  `variants` = the pipe-joined changed variants;
- **run `actionlint`** (GitHub evaluates `${{ }}` even inside comments).

## Phase 4 — Backfill the data into the PR

Run the fetcher's backfill (locally from mirrored files, or on a runner via
the probe) and commit `data/<Country>.csv`, `data/<Country>_<Variant>.csv`
and `market/<slug>_top.json` with the message
`chore: update <Country> data from <source>`. If you can, run it online on a
runner too and diff the result against the offline build.

## Phase 5 — Wire it into the gallery

| File | What | Check |
|---|---|---|
| `index.html` → `SD_COUNTRIES` | `{ country: '<Country>', variants: ['Whole'] }`, alphabetical | `sd_countries` |
| `index.html` → `TZ_COUNTRY` (or `TZ_PREFIX`) | the country's IANA zone(s) → home-country detection | `timezone` |
| `index.html` → `COUNTRY_REGION` | continent (colour in Compare / map) | `region_color` |
| `assets/flags/<slug>.png` | slug exactly as `slug_country()` in `R/render_country.R` builds it: lower case, non-alphanumerics → `_` (`hong_kong`, **not** `hongkong`) | `flag_png` |
| `R/post_text.R` → `.pt_flag` | regional-indicator emoji; backtick names with spaces (`` `Hong Kong` ``) | `flag_emoji` |
| `R/render_schedule.R` → `FLAG`, `LABEL` | keyed by the **workflow** slug (`fetch-hong-kong.yml` → `hong-kong`) | `workflow_docs` |
| `footnotes.csv` | one caveat row per variant (scope, missing splits, policy shocks) | `footnote` (warning) |
| `render-country.yml` | only if the variant name is new — add it to the `variant` options | — |

## Phase 6 — Groupings (the step that gets forgotten)

The Builder, Compare and the Time-lapse GIFs aggregate countries by group.
A country in no group silently never appears in any regional curve.

1. Add the country to its geographic group in **both** mirrors — they must be
   identical, the checker compares them:
   - `index.html` → `BUILDER_GROUPS` (`western_europe`, `northern_europe`,
     `southern_europe`, `eastern_europe`, `north_america`, `south_america`,
     `americas`, `asia`, `oceania`),
   - `scripts/snapshot_builder.py` → `GROUPS_STATIC`.
   Political groups (`eu`, `g7`) only if it is a member. Size groups are
   computed from `weights.csv` — nothing to do.
2. **Membership conventions** (decided 2026-09-25; follow them, the owner
   changes them in a separate PR if wanted): Europe is split the way the
   gallery already did it — post-communist Central/Eastern Europe, the
   Balkans and the Caucasus go to `eastern_europe` (Croatia, Slovenia,
   Bulgaria, Ukraine, Albania, Georgia); Mediterranean countries not in that
   set go to `southern_europe` (Greece, Cyprus, Malta, Türkiye). Everything
   `COUNTRY_REGION` files under Asia goes to `asia` — Israel and Nepal
   included. Australia and New Zealand are `oceania`. A country that fits
   none of these is the one case to ask the owner about; record it in
   `KNOWN_GAPS` in `scripts/check_country_integration.py` meanwhile.
3. **A new group** (as `oceania` was) needs five places: `BUILDER_GROUPS`,
   `GROUPS_STATIC`, an `<option>` in `<select id="builderGroups">`,
   `groupLabels` (index.html) and `GROUP_LABELS`
   (`scripts/build_builder_series.py`). The checker's `[groups]` check
   enforces the last three; `backtest/series/<group>.json` appears on the next
   backtest run.
4. Changing a group changes that group's aggregate curves and GIFs — Phase 8
   regenerates them.

## Phase 7 — Documentation

| Doc | What to add |
|---|---|
| `docs/architecture/NN-source-<slug>.md` (next free number) | front-matter (drives the public source page — copy [41](41-source-hong-kong.md): `country`, `slug`, `method`, `summary`, `source_*`, `variants`, `variant_notes`, `hev_split`/`hev_note`, `caveats`, `market_breakdown`, `fetcher`, `workflow`), then TL;DR, why it clears the bar, record→row, mapping, variants, governance, validation, reading the fit, outputs, **operations + a debugging runbook table** and a sequence diagram |
| `docs/architecture/README.md` | a row in the doc index |
| `02-components.md` §2.7 | a row in the fetch-actions table |
| `03-data-objects.md` | §3.16 row if it writes `market/`; column notes if it adds a new pattern (e.g. EREV writer) |
| `05-flows.md` | add the country to the "never got a lettered flow" list |
| `08-deploy-ops.md` §8.11 | a row in the cron table and the notes on schedule bands |
| `09-glossary.md` | vehicle-scope table row; per-country variant table (if multi-variant); "Variants outside the EU core six" (for `Used`, `Pickups`, …); the variant definition's country list |
| `33-expansion-candidates.md` / `14-data-source-gaps.md` | status update ("BUILT"), and every country you rejected on the way |
| `README.md` (repo root) | rows for the fetcher and the workflow |
| `architecture/bev-gallery-architecture-brief.md` | one line in the workflow list (German) |
| `market/README.md` | a row if it writes `market/<slug>_top.json` |

Generated — **never hand-edit**, CI rebuilds them after merge: `sources/`,
`series/`, `schedule*`, `manifest.json`, `params.csv`, `weights.csv`,
`images/`, `posts/`, `builder_history/`, `backtest/` (Phase 8 writes it
through CI), `docs/architecture/35b-raw-data-quality-todo.md`. If you run
`build_source_pages.py` locally to preview, revert `sources/` afterwards.

## Phase 8 — History: backtest and Time-lapse GIFs

The Time-lapse panel and its GIFs read `backtest/`, which re-fits every
series on data truncated to each month since 2015. A new country is only in
them once it has been fitted into those months. `R/build_backtest.R` does
that automatically for any series that is in **no** month yet — but only when
`snapshot-builder.yml` runs (monthly, 25th, 09:00 UTC, on `master`).

Do it **in the PR** so the country arrives with its history:

1. Push the data and the group changes first.
2. Dispatch **Snapshot Builder curves** (`snapshot-builder.yml`) on **your
   branch** with `backtest_only = true` (Actions UI → Run workflow → branch).
   It fits the new series into every eligible month (≥ 24 rows of data),
   rebuilds `backtest/series/*.json` and re-renders the GIFs, and commits to
   the branch. ~2–5 min for a country with three series.
3. Pull, and check: `python scripts/check_country_integration.py --country
   "<Country>"` (the `backtest` check), and that the group file
   (`backtest/series/asia.json` for Hong Kong) now lists the country.
4. **Know what the GIF will show.** The downloadable GIFs animate the
   **cohort** — countries fittable in *every* frame since `DEFAULT_FROM`
   (2017-01, `scripts/build_backtest_series.py`), so the curve does not move
   just because the gallery gained a country ([02](02-components.md) §2.16).
   A country whose data starts later (Hong Kong: fittable from 2021-10) is in
   the panel's "all countries" view and its group's series from its first
   eligible month, but joins the cohort GIF only if that start is moved —
   an owner decision, not part of adding a country.
5. **If the monthly `master` run lands before your merge**, `backtest/` will
   conflict. Resolve by taking `master`'s version of `backtest/` entirely
   (`git checkout origin/master -- backtest`), commit the merge, and dispatch
   step 2 again — it only fits what is still missing.

## Phase 9 — Verify, clean up, open the PR

Run, and paste the results into the PR:

```bash
python scripts/test_fetch_<slug>.py && python scripts/test_market_top.py
actionlint .github/workflows/fetch-<slug>.yml
python scripts/test_snapshot_builder.py
python scripts/build_series.py --check
python scripts/build_source_pages.py --check && python scripts/build_theme.py --check
python scripts/check_country_integration.py          # must end with 0 error(s)
```

Then remove the probe files (`probe_out/`, `scripts/probe_tmp.py`,
`.github/workflows/probe-tmp.yml`) and rewrite **your own** branch into a few
logical commits (fetcher+tests+workflow · data · integration+docs · history)
so raw probe downloads never reach `master`'s history.

## Phase 10 — After merge

1. Dispatch `render-country.yml` with the country and `variants` =
   `Whole|<Variant>|…` (or let the next scheduled fetch do it).
2. Check `params.csv` has the Whole row (the checker's `params` warning goes
   away), the country appears on the gallery, the world map and the Builder,
   and `sources/<slug>.html` shows the brand/model tables after
   `build-source-pages.yml` has run.
3. Watch the first scheduled fetch run and read its step summary.
