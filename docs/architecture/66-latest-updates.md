# 66 — Latest updates on the home page

The home tab (`#about`) has a **Latest updates** section under the hero chart:
what changed in the *content* of the Gallery, newest first. Chart re-renders
are deliberately left out; a new PNG is not news, a new month of figures is.

It is generated, not maintained: nobody writes a changelog entry.

## What it shows

Two columns (stacked on phones), five rows each (three on phones), "Show N
more" opens up to twenty:

| Column | One row is | Comes from |
|---|---|---|
| **New figures** | one country on one day (UTC): new month(s), new country, new series (variant), new fuel column, or revised figures; the variants touched, the source, links to **Numbers** (`#rawdata?c=<Country>`) and the **Source** page (`sources/<slug>.html`) | the diffs of `data/<Country>[_<Variant>].csv` |
| **On the site** | one merged pull request's `Release:` line, linking the PR | the PR body, the same line the monthly release note uses |

Kinds, in the `kind` field of each data entry:

| `kind` | When | Headline |
|---|---|---|
| `country` | `data/<Country>.csv` (the headline series) appears as a new file | "New country", detail = variants and the history span |
| `series` | `data/<Country>_<Variant>.csv` appears as a new file | "New series: Vans" |
| `data` | a `(period, variant)` key appears only on the `+` side of the diff | "Oct 2026 data" (the newest period of the headline series if it moved, else of the series that moved furthest; quarterly reads "Q3 2026", yearly "2022") |
| `fields` | the header gains a fuel column and nothing else is new | "FCEV added" |
| `revised` | keys on both sides of the diff only | "Figures revised", detail = number of periods |

A `data` row also says how many earlier periods were revised and which
columns were added, if any.

## How it is built

`scripts/build_updates.py` writes `sources/updates.json`:

1. `git log --first-parent --diff-merges=first-parent -p -U0 --since=<60 days> -- data/*.csv`.
   CSV writes are line-level upserts keyed on `(period, variant)`
   (`R/upsert.R`, AGENTS.md invariant 2), so the diff is exact: one changed
   row is one `-`/`+` pair, one new month one `+` line.
2. Per commit and file the keys are classified (above), then folded into one
   bucket per UTC day and country.
3. The source name is read from the fetcher's commit subject
   (`chore: update <Country> data from <source>`); a PR number from a squash
   subject (`… (#461)`) or a merge commit. Flag and source-page slug come from
   `sources/schedule.json`, which the same workflow builds one step earlier.
4. `gh pr list --state merged --search merged:>=<60 days>` gives the PR
   bodies; every line that **starts** with `Release:` becomes a site entry
   (AGENTS.md, "Conventions").
5. Merge with the previous `sources/updates.json`: fresh entries win inside
   the window, older ones are carried over, at most 80 entries are kept.

Rules that keep the feed honest:

- **Not news:** a `_legacy` series; a commit without parents (the repository
  root or the boundary of a shallow clone, where every file looks new); a
  commit that creates the headline file of more than three countries at once
  (a bulk import or restructure).
- **A new column is not a revision.** Adding `FCEV` rewrites every old row;
  the row says "FCEV added", not "117 earlier periods revised".
- **One story, told once.** A pull request that only revises rows (a
  re-classification such as "HEV for Finland") is dropped from *New figures*
  when its `Release:` line is in *On the site*, which explains it better.
- **Fails soft.** Without `gh` or a token the site entries of the previous
  feed are kept; with a shallow checkout the older data entries are kept; if
  the script fails, the workflow warns and the page keeps the committed feed.
  Without any feed the page hides the section.

## When it updates

`build-source-pages.yml` runs the script after `build_schedule.py` and commits
`sources/updates.json` with the rest of `sources/`. That job runs after every
render (dispatched by `build-manifest.yml`), daily at 04:37 UTC, and on pushes
to its generators, so a new month shows up within minutes of its charts, and a
merged PR's `Release:` line by the next run at the latest. The checkout is
`fetch-depth: 0` with `filter: blob:none`: full history, but only the
`data/*.csv` blobs of the last 60 days are downloaded, on demand. Pull-request
runs only run the tests and keep the shallow default checkout.

Run locally (full clone): `python3 scripts/build_updates.py` (add `--no-gh`
to skip the PR half, `--stdout` to only print). Tests:
`scripts/test_build_updates.py`.

## Schema

```json
{
  "generated": "2026-11-22",
  "window_days": 60,
  "entries": [
    { "date": "2026-11-21", "time": "2026-11-21T19:27:54Z", "type": "data",
      "kind": "data", "country": "Türkiye", "flag": "🇹🇷", "slug": "turkiye",
      "headline": "Oct 2026 data", "detail": "Cars",
      "variants": ["Whole"], "source": "TÜİK", "commit": "6069026164f2" },
    { "date": "2026-11-21", "time": "2026-11-21T15:26:59Z", "type": "site",
      "kind": "site", "headline": "Finland's charts now show hybrids …",
      "title": "feat(fi): HEV for Finland …", "pr": 461 }
  ]
}
```

`pr` is optional on data entries. Generated, do not hand-edit (AGENTS.md
invariant 1 covers all of `sources/`). To change wording or rules, edit the
script, run it, and extend the test.
