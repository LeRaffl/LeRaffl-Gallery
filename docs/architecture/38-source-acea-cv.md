# 38 · Source: ACEA Commercial Vehicles (multi-country, quarterly)

> This doc intentionally carries **no YAML front-matter** block. Every other
> `NN-source-<country>.md` doc's front-matter feeds `scripts/build_source_pages.py`,
> which assumes one country per doc (`data_file` = one CSV, `variant_file()` derives
> `data/<Country>_<Variant>.csv` from it). This fetcher covers 19 countries at once, so
> forcing it into that single-country schema would either crash the generator or produce a
> nonsensical `sources/acea-cv.html` page. `build_source_pages.py`'s own docstring sanctions
> this: "A doc with no front-matter is skipped." Each affected country's *own*
> `NN-source-<country>.md` page (where one exists) should reference this doc for its
> Vans/HDV/Buses provenance instead of duplicating the explanation.

`scripts/fetch_acea.py` (Flow K, [05-flows.md](05-flows.md)) ingests ACEA's **monthly car**
press release for passenger cars (`Whole`). ACEA separately publishes a **Commercial Vehicle**
press release — vans, trucks and buses — that fetcher deliberately does not touch (its own
docstring: "Light commercial vehicles are published in a separate ACEA press release that we
don't ingest"). This fetcher is that separate release, finally wired up, covering the same
19-country ACEA roster (`fetch_acea.py`'s `ALWAYS_COUNTRIES + CONDITIONAL_COUNTRIES`) with
`Vans` / `HDV` / `Buses` variants — and reconstructing genuine `Q1`/`Q2`/`Q3`/`Q4` rows out of
a source that only ever publishes cumulative running totals.

## TL;DR

```
Source:    ACEA "New Commercial Vehicle Registrations" press release (PDF), acea.auto/files/
Auth:      None
Cadence:   ACEA publishes four CUMULATIVE year-to-date checkpoints a year — Q1 (~April),
           H1 (~July/August), Q1-Q3 (~October), full year (~January). This fetcher
           reconstructs genuine, non-overlapping Q1/Q2/Q3/Q4 quarters from them (see § 2)
           and falls back to a single yearly row only when no quarterly baseline exists
           yet for that (country, variant, year).
Countries: The same 19 markets scripts/fetch_acea.py covers for passenger cars
           (its ALWAYS_COUNTRIES + CONDITIONAL_COUNTRIES): Belgium, Bulgaria, Croatia,
           Cyprus, Czechia, Estonia, Greece, Hungary, Iceland, Latvia, Lithuania,
           Luxembourg, Malta, Norway, Poland, Romania, Slovakia, Slovenia, Switzerland.
           (Malta is sometimes missing from a given release — "Data for Malta not
           available" — so its coverage is patchier than the rest.)
Variants:  Vans (N1), HDV (N2+N3, i.e. medium+heavy trucks combined — already how the
           source reports "Total Truck"/"MHCV"), Buses (M2+M3).
Write rule: Conditional for every country (not the always/conditional split fetch_acea.py
           uses for passenger cars): a (country, variant, period) row is written only if
           no row exists yet, or the existing row's source is exactly "ACEA". This is what
           lets the fetcher run over every target country without ever overwriting a
           national HDV/Vans/Buses source (Austria, Luxembourg, Poland today all have one).
Eras:      Through ~2023, "old era" — TOTAL only, no fuel split (5 simple tables: LCV,
           HCV>=16t, MHCV>3.5t, MHBC, Total CV), and only ever usable as a yearly figure
           (see § 5). From ~2024, "new era" — full fuel split per variant, cumulative
           checkpoints, genuine quarters reconstructed from them (see § 2); the
           "electrically chargeable" column combines BEV+PHEV (see § 3).
Parsing:   pdfplumber, but NOT via extract_text()/extract_tables() — both this release and
           fetch_acea.py's car-registration PDF position every character individually with
           `upright=False` (a Word/print-driver export quirk), which breaks pdfplumber's
           default word clustering ("A u s tria", extract_tables() finds nothing). We
           reconstruct lines directly from page.chars: group by rounded vertical position,
           sort left-to-right, and only insert a space where the horizontal gap between
           glyphs is wide enough to be a real word/column boundary. See § 4.
Scripts:   scripts/fetch_acea_cv.py
Workflow:  .github/workflows/fetch-acea-cv.yml
Schedule:  Four cron windows, one per checkpoint — mid-late Jan (FY), mid-late Apr (Q1),
           late Jul + early Aug (H1), late Oct (Q1-Q3). See 08-deploy-ops.md § 8.11.
```

## 1. Why this exists

`docs/architecture/05-flows.md` § Flow K already documents that ACEA's monthly car PDF
covers ~25 markets but is deliberately scoped to passenger cars only — "Light commercial
vehicles are published in a separate ACEA press release that we don't ingest." That gap is
what this fetcher closes: most of the ACEA roster (Belgium, Bulgaria, Croatia, Cyprus,
Iceland, Latvia, Lithuania, Malta, Romania, Slovakia, Slovenia, Norway, Switzerland, …) had
**no** `Vans`/`HDV`/`Buses` data at all before this — those variants existed only for
countries with a national commercial-vehicle source (Austria, Denmark, Finland, Ireland,
Italy, Luxembourg, Netherlands, Poland, Portugal, Spain, Thailand, Uruguay, Albania,
Indonesia, Canada).

## 2. Reconstructing genuine quarters from cumulative checkpoints

Since roughly 2024, ACEA no longer publishes a genuinely monthly commercial-vehicle release.
Instead it publishes four **cumulative year-to-date** snapshots per year:

| Checkpoint | Published | Covers | Quarters cumulative |
|---|---|---|---|
| Q1 | ~April | Jan-Mar | 1 |
| H1 | ~July/August | Jan-Jun | 2 |
| Q1-Q3 | ~October | Jan-Sep | 3 |
| Full year | ~January (following year) | Jan-Dec | 4 |

A "Q1-Q3 2024" table is Jan-Sep 2024 **cumulative**, not Q3 alone. Writing each release's
total straight into a CSV row would double-, triple- or quadruple-count registrations against
neighbouring releases, corrupting every trailing-window computation downstream: the TTM share
chart, the S-curve fit, and `weights.csv`.

So instead, `scripts/fetch_acea_cv.py` reconstructs genuine per-quarter deltas:

```
Q1 = Q1 checkpoint total                 (nothing precedes it in the year)
Q2 = H1 checkpoint total      − Q1
Q3 = Q1-Q3 checkpoint total   − (Q1 + Q2)
Q4 = full-year checkpoint total − (Q1 + Q2 + Q3)
```

The subtraction baseline for each is simply the sum of whichever quarters are **already
recorded** in the target CSV for that year (`existing_quarter_rows()` /
`handle_checkpoint()`) — the CSV itself is the durable state that bridges across separate
workflow runs, so no extra state file was needed. `time_interval` is written as `quarterly`
(`period` = the quarter's middle month — Q1→02, Q2→05, Q3→08, Q4→11 — the existing
convention, see [09-glossary.md § Time / period](09-glossary.md)).

**When the necessary baseline isn't on record yet**, nothing gets fabricated under a
single-quarter label:

- A **full-year checkpoint arriving with no quarters recorded at all** for that year falls
  back to a single `yearly` row using the full-year total directly (`period = YYYY-07`) —
  the same degraded-but-honest granularity the pre-2024 "old era" always uses (it never had
  a quarterly-checkpoint format to begin with — see § 5).
- **Anything else** (a checkpoint arrives but an earlier quarter is missing — a cron window
  was skipped, or this is the very first checkpoint processed for a country and it isn't Q1)
  is skipped with a clear log message and resolves on its own once the gap closes.

Each release also carries a **prior-year-same-checkpoint column** (e.g. the H1 2026 release
also gives H1 2025 for comparison). This fetcher runs the identical reconstruction on that
column too — for free, this is how a Q1 release quietly refreshes/corrects last year's Q1,
and how a country's first-ever processed year can pick up a bonus second year (exactly how
the one-off 2021+2022 backfill worked from a single FY2022 PDF — see § 5).

**Known limitation — revisions don't cascade forward.** If Q2 is revised (its row updated
after Q3/Q4 were already computed from the *old* Q2), Q3 and Q4 are not automatically
recomputed; they'd need their originating checkpoint re-run. In steady-state cron operation
checkpoints only ever move forward in time, so this only bites if an old checkpoint's PDF is
manually re-fetched after later ones already landed for the same year. Accepted tradeoff —
full-year replay on every run wasn't worth the complexity for what should be a rare case.

**Bootstrap timeline for right now (2026).** This pipeline didn't exist for the Q1 2026 or
H1 2026 windows, so — barring a manual backfill dispatch once the live fetch can actually
reach ACEA — 2026 has no quarterly baseline. The Q1-Q3 2026 checkpoint (~late October) will
still skip with a gap warning; the first data most countries get is the **FY2026** yearly
fallback in January 2027. True `Q1`/`Q2`/`Q3`/`Q4` granularity starts cleanly from **Q1
2027** onward. (A maintainer who can dispatch this workflow with real network access can
shortcut that by fetching `--checkpoint Q1 --year 2026` and `--checkpoint H1 --year 2026`
now, since both are already-published historical releases — that back-fills real Q1 and Q2
2026 immediately instead of waiting for the yearly fallback.)

**A subtle but important consequence of using `period = YYYY-07` for the yearly fallback:**
that string is identical to `YYYY-07` for a *monthly* July row. For a country whose
HDV/Vans/Buses CSV already has genuine monthly coverage (Luxembourg's Vans/HDV today), the
conditional write rule naturally protects against this: the existing July row's source isn't
`ACEA`, so the yearly write is skipped — no collision, no silent misattribution, just no
backfill for that file (which already has better data for that year anyway).

## 3. Why the combined "Electrically Chargeable" bucket lands in BEV — and is labelled "EV"

The 2024+ ("new era") tables report six fuel columns: **Electrically Chargeable** (footnote:
"Includes battery electric and plug-in hybrids"), **Hybrid Electric** (full+mild hybrid
combined), Others, Petrol, Diesel, Total. There is no separate BEV/PHEV split for commercial
vehicles — ACEA doesn't break it out the way it does for passenger cars.

Our schema has separate `BEV` and `PHEV` columns, and `BEV` is documented project-wide as
"the headline metric" ([09-glossary.md](09-glossary.md)). Leaving both empty would discard a
real, useful plug-in-adoption number; splitting it proportionally would be fabrication. The
chosen convention — consistent with how the glossary already handles a single combined
"Hybrid" bucket (mapped to `HEV`, footnoted) — is to map the combined Electrically Chargeable
figure into the `BEV` **column** and leave `PHEV` empty.

Unlike the "Hybrid" precedent, though, the *displayed* legend/axis/post-text label is not
left as the misleading "BEV" — every chart and post for these Vans/HDV/Buses rows shows
**"EV"** instead, computed from the row's `source` column at render time
(`bev_label_val` in `R/render_country.R`, threaded into `R/plots.R` (`bev_label(meta)`),
`R/data.R` (`compute_ttm_long(df, bev_label=...)`) and `R/post_text.R`
(`bev_label` parameter on `build_post_text`/`build_ttm_post_text`/`.pt_triplet_lines`)). The
gate is `source == "ACEA" && variant %in% c("Vans","HDV","Buses")` — deliberately **not**
just `source == "ACEA"`, because that alone would also catch the passenger-car ACEA countries
whose `Whole` series properly splits BEV/PHEV via `scripts/fetch_acea.py` and must keep
saying "BEV". The underlying CSV **column** is still literally named `BEV` everywhere (schema
column names never change); only the human-facing text differs. `footnotes.csv` carries the
same caveat in writing on every affected `(country, Vans/HDV/Buses)` row: this **"EV" figure
is BEV+PHEV combined, not a pure-BEV count**, so it is not directly comparable to the same
country's `Whole` BEV share (which *is* properly split).

## 4. Parsing: the `upright=False` text layer

Both this release and (per `scripts/fetch_acea.py`'s own docstring) the ACEA car-registration
PDF are generated by a pipeline that positions every glyph individually and marks it
`upright=False` even though the text displays normally — a known Word/print-driver export
quirk, not an actual page rotation. pdfplumber's default clustering assumes upright text:
`extract_tables()` finds nothing at all on these pages, and `extract_text()` inserts a
spurious space between almost every letter ("`A u s tria`"), even though it happens to still
keep one country per line.

`scripts/fetch_acea_cv.py`'s `page_lines()` sidesteps this by reading `page.chars` directly:
group characters by rounded vertical position (`_LINE_TOP_TOLERANCE_PT = 1.0`pt) into lines,
sort each line left-to-right, and only insert a space where the horizontal gap between
consecutive glyphs (`_LINE_GAP_TOLERANCE_PT = 1.2`pt) is wide enough to be a real word or
column boundary rather than normal kerning. This reconstructs exactly the same clean
"`Country <N integers>`" line every other ACEA-family parser expects, and is used for *both*
report eras (the old, pre-2024 releases turn out to have the identical `upright=False`
quirk, confirmed against a real Dec-2022 sample — see § 5).

Once reconstructed, the actual integer parsing mirrors `scripts/fetch_acea.py`'s
`_parse_country_pairs`: tokenise on whitespace, drop percentage tokens (contain `.`) and
stand-alone signs, treat the dash glyphs `ꟷ – — − ─` as `0`, and require an exact integer
count (12 for the new-era 6-fuel×(current,prior) grid, 4 for the old-era single
TOTAL×(current,prior) + month block).

## 5. Backfill (one-off, per AGENTS.md "one-off data scrape from the past is acceptable")

Two calendar years — **2021 and 2022** — were seeded from a single locally supplied
FY2022 PDF (`20230125_PRCV_2212_FINAL.pdf`, the old pre-fuel-split format's
JANUARY-DECEMBER columns give both the current and prior year in one file). Since the old
era never had a quarterly-checkpoint format, both years land as `yearly` rows (TOTAL only —
no fuel split existed yet), via the same fallback path a "no baseline yet" full-year
checkpoint always takes. This sandbox has no live network access to `acea.auto` (confirmed
via the environment's proxy status), so no further historical years were fetched live.
`notes` on every backfilled row cites the real published URL,
`https://www.acea.auto/files/20230125_PRCV_2212_FINAL.pdf`, not the local upload path used
to parse it.

The 2023-2025 gap (and everything before 2021) is **not** backfilled from this session. This
repo also holds one Q1-Q3-2024 and one H1-2026 sample PDF (both new-era, fuel-split) — they
were used to validate the new-era parser and the quarterly-delta reconstruction logic
end-to-end (with synthetic sequential test data, since the two real samples aren't adjacent
checkpoints and can't be safely combined), but neither wrote a row on its own: a lone Q1-Q3
or H1 checkpoint with no recorded Q1/Q2 baseline correctly hits the "gap" skip path, not the
yearly fallback (that's reserved for full-year checkpoints only). See § 2's bootstrap
timeline for how 2026+ closes this gap going forward.

## 6. URL uncertainty (bring-up risk, documented up front)

ACEA has changed this release's filename scheme at least twice: a cryptic date-prefixed name
(`20230125_PRCV_2212_FINAL.pdf`) through ~2023, then a **hyphen** before the period tag for
H1 (`Press_release_commercial_vehicle_registrations-H1_2026.pdf`, confirmed) but an
**underscore** for Q1-Q3 (`Press_release_commercial_vehicle_registrations_Q1-Q3_2024.pdf`,
confirmed) in the 2024+ releases — ACEA is not internally consistent about this. There is no
confirmed sample of the new-era filename for the **Q1** or **full-year** checkpoints in this
repo yet. `CANDIDATE_URL_TEMPLATES_BY_CHECKPOINT` in `scripts/fetch_acea_cv.py` lists the
most plausible guesses per checkpoint (both hyphen and underscore variants), tried in order;
`--pdf-url` overrides them. Expect the first live run of each checkpoint to need one
`--pdf-url` correction — that is normal bring-up, not a bug, and is exactly why the
`workflow_dispatch` inputs exist.

## See also

- [09-glossary.md § Variant definitions](09-glossary.md#variant-definitions-canonical) — the
  `HDV`/`Vans`/`Buses` canonical meanings this fetcher targets.
- [05-flows.md § Flow K](05-flows.md#flow-k--acea-ingest) — the sibling passenger-car ACEA
  fetcher this one was deliberately kept separate from.
- `scripts/fetch_acea.py` — the passenger-car fetcher; its module docstring is the reference
  for the always-list/conditional-list distinction this fetcher does *not* use (every country
  here is conditional).
