# 38 · Source: ACEA Commercial Vehicles (multi-country, quarterly)

> This doc intentionally carries **no YAML front-matter** block. Every other
> `NN-source-<country>.md` doc's front-matter feeds `scripts/build_source_pages.py`,
> which assumes one country per doc (`data_file` = one CSV, `variant_file()` derives
> `data/<Country>_<Variant>.csv` from it). This fetcher covers 21 countries at once, so
> forcing it into that single-country schema would either crash the generator or produce a
> nonsensical `sources/acea-cv.html` page. `build_source_pages.py`'s own docstring sanctions
> this: "A doc with no front-matter is skipped." Each affected country's *own*
> `NN-source-<country>.md` page (where one exists) should reference this doc for its
> Vans/HDV/Buses provenance instead of duplicating the explanation.

`scripts/fetch_acea.py` (Flow K, [05-flows.md](05-flows.md)) ingests ACEA's **monthly car**
press release for passenger cars (`Whole`). ACEA separately publishes a **Commercial Vehicle**
press release — vans, trucks and buses — that fetcher deliberately does not touch (its own
docstring: "Light commercial vehicles are published in a separate ACEA press release that we
don't ingest"). This fetcher is that separate release, finally wired up, with
`Vans` / `HDV` / `Buses` variants — and reconstructing genuine `Q1`/`Q2`/`Q3`/`Q4` rows out of
a source that only ever publishes cumulative running totals.

**Its roster is not simply `fetch_acea.py`'s passenger-car list** — see § 1a.

## TL;DR

```
Source:    ACEA "New Commercial Vehicle Registrations" press release (PDF), acea.auto/files/
Auth:      None
Cadence:   ACEA publishes four CUMULATIVE year-to-date checkpoints a year — Q1 (~April),
           H1 (~July/August), Q1-Q3 (~October), full year (~January). This fetcher
           reconstructs genuine, non-overlapping Q1/Q2/Q3/Q4 quarters from them (see § 2)
           and falls back to a single yearly row only when no quarterly baseline exists
           yet for that (country, variant, year).
Countries: 16, maintainer-curated (2026-10) — NOT simply fetch_acea.py's passenger-car
           roster. See § 1a for the full reasoning:
           Bulgaria, Croatia, Cyprus, France, Germany, Greece,
           Hungary, Iceland, Lithuania, Malta, Norway, Poland, Romania, Slovakia,
           Slovenia, Sweden. (Switzerland and Czechia until 2026-09; Latvia, Estonia and
           Belgium until 2026-10 — CSDD register, [58](58-source-latvia.md), Transpordiamet
           workbook, [57](57-source-estonia.md), and DIV files, [59](59-source-belgium.md)
           — see § 1a.)
           (Malta is sometimes missing from a given release — "Data for Malta not
           available" — so its coverage is patchier than the rest.)
Variants:  Vans (N1), HDV (N2+N3, i.e. medium+heavy trucks combined — already how the
           source reports "Total Truck"/"MHCV"), Buses (M2+M3).
Write rule: Conditional for every country (not the always/conditional split fetch_acea.py
           uses for passenger cars): a (country, variant, period) row is written only if
           no row exists yet, or the existing row's source is exactly "ACEA". Poland
           (the one in-scope country with a national HDV/Vans/Buses source, PZPM) relies
           on exactly this rule to stay safely in scope — ACEA can never overwrite it.
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
what this fetcher closes: most of the roster below had **no** `Vans`/`HDV`/`Buses` data at
all before this — those variants existed only for countries with a national
commercial-vehicle source (Austria, Denmark, Finland, Ireland, Italy, Luxembourg,
Netherlands, Poland, Portugal, Spain, Thailand, Uruguay, Albania, Indonesia, Canada).

## 1a. Why the roster isn't just fetch_acea.py's passenger-car list

`scripts/fetch_acea.py` scopes its `ALWAYS_COUNTRIES + CONDITIONAL_COUNTRIES` to countries
that have **no better national source for passenger cars**. That's the wrong test for
commercial vehicles — a country can have an excellent national `Whole` feed and *still* have
no national Vans/HDV/Buses source at all, or vice versa. `TARGET_COUNTRIES` in
`scripts/fetch_acea_cv.py` is curated against the commercial-vehicle picture specifically
(maintainer decision, 2026-09):

- **Germany, France, Sweden are IN**, even though each has its own national passenger-car
  source (KBA, SDES, SCB respectively) and is therefore *excluded* from `fetch_acea.py`.
  None of the three has any national Vans/HDV/Buses feed, so ACEA is the only source for
  those variants — the passenger-car sourcing question is simply irrelevant here.
- **Austria, Denmark, Finland, Netherlands, Spain are OUT** — never in scope. Each already
  has its own national Vans/HDV/Buses fetcher (`02-components.md` § 2.7), so an ACEA row
  would only ever be redundant, and (since ACEA and a national registry rarely agree to the
  unit) a needless source-quality downgrade if it ever *did* get written.
- **Switzerland is OUT since 2026-10.** ASTRA's register extracts
  (`scripts/fetch_switzerland.py`, [46](46-source-switzerland.md)) carry monthly Vans / HDV /
  Buses with a real BEV/PHEV split, matched to these ACEA checkpoints (BEV+PHEV within ±10 per
  checkpoint, Vans FY 2025 −31). The quarterly rows this fetcher wrote are parked byte for byte in
  `data/Switzerland_legacy.csv`.
- **Czechia is OUT since 2026-10.** The RSV register extract
  (`scripts/fetch_czechia.py`, [51](51-source-czechia.md)) carries monthly Vans / HDV /
  Buses with a BEV/PHEV split back to 2016 (Buses within a few vehicles of these ACEA
  checkpoints, HDV about −1%, Vans about −2.5%). The quarterly rows this fetcher wrote
  are parked byte for byte in `data/Czechia_legacy.csv`.
- **Latvia is OUT since 2026-10.** CSDD's first-registration records
  (`scripts/fetch_latvia.py`, [58](58-source-latvia.md)) carry monthly Vans / HDV / Buses
  with BEV and PHEV separate back to 2015. Against these checkpoints: Vans equal in
  2023-Q1/Q2 and 0–13% below in 2024–2026 with the same electric count (ACEA's "BEV" is
  BEV + PHEV), HDV equal where ACEA's quarters are sound, Buses within 0–6 a quarter. The
  rows this fetcher wrote are parked in `data/Latvia_legacy.csv`.
- **Estonia is OUT since 2026-10.** Transpordiamet's monthly «Infoleht» workbook
  (`scripts/fetch_estonia.py`, [57](57-source-estonia.md)) carries monthly Vans / HDV /
  Buses with a counted BEV/PHEV/HEV split from 2021-01. Against these checkpoints: Vans
  within −1 … +3% (ACEA's "BEV" = our BEV + PHEV), HDV within a few vehicles a quarter,
  Buses equal or within 1–5. The rows this fetcher wrote are parked in
  `data/Estonia_legacy.csv`.
- **Belgium is OUT since 2026-10.** The FPS Mobility's monthly DIV registration files
  (`scripts/fetch_belgium.py`, [59](59-source-belgium.md)) carry monthly Vans / HDV / Buses
  with BEV and PHEV separate back to 2013. DIV is ACEA's source for commercial vehicles too:
  the checkpoints agree within about 1% (Vans 2026-Q2 18,605 / 18,585), except the quarter
  holding DIV's short 2025-04 file (3–5% low). The rows this fetcher wrote are parked in
  `data/Belgium_legacy.csv`.
- **Greece stays IN.** Its passenger cars moved to SEAA in 2026-10
  (`scripts/fetch_greece.py`, [53](53-source-greece.md)), but SEAA and ELSTAT publish vans,
  trucks and buses without a fuel split, so these checkpoints remain the only electric
  figure for Greek commercial vehicles.
- **Luxembourg is OUT**, deliberately, even though STATEC (its national source) covers only
  `Whole`/`Vans`/`HDV` and has no `Buses` variant of its own. An earlier version of this
  fetcher filled exactly that one gap with an ACEA-sourced `Luxembourg_Buses.csv`; the
  maintainer chose to leave it unfilled instead, to keep every Luxembourg CSV attributable
  to one source family rather than mixing STATEC and ACEA in the same country's file set.
- **Poland stays IN**, as the one deliberate exception to "has a national source → excluded":
  PZPM owns Poland's Vans/HDV/Buses rows, but instead of an exclusion list this fetcher
  relies on its normal conditional-write rule (§ TL;DR) to guarantee ACEA can never
  overwrite them. Kept in scope mainly so a future gap in PZPM's own coverage (it already
  happens for `Whole`, see `22-source-poland.md`) has an ACEA fallback ready.

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

**Fuel restatements are carried back, not written as negatives (#355).** Between releases
ACEA moves vehicles between fuels, and each release's prior-year column rewrites last year's
quarter, so one fuel's `checkpoint − quarters on record` can go negative while TOTAL is
fine. Example, Cyprus Buses 2023: Q3 BEV 19 / HEV 21, and the FY release says the year had
none, which used to land in Q4 as BEV −19 / HEV −21 (`R/data.R` then plots a share below
zero). `carry_back_deficits()` sets such a fuel to 0 and takes the deficit off the same fuel
in the nearest earlier quarter(s) of the year, moving the same number of vehicles from that
quarter's TOTAL to this one's. Cyprus becomes Q3 BEV 0 / HEV 0 / TOTAL 45 and Q4 TOTAL 53.
Nothing goes negative, every row still sums, and every year-to-date sum per fuel and in
TOTAL is exactly ACEA's; both rows say so in `notes`. Earlier quarters that are not `ACEA`
rows are never touched: then the quarter is skipped like a negative TOTAL. The 29 negatives
written before this rule (17 files, 2022–2025) were repaired once with
`fetch_acea_cv.py --repair-negatives`, which applies the same rule to the stored rows
(year sums unchanged; `*_legacy.csv` archives left frozen).

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
HDV/Vans/Buses CSV already has genuine monthly coverage (Poland's, via PZPM), the
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

A guess that doesn't exist is answered with a 404 on some days and a **520** on others (the
same erratic "not here" answers `fetch_acea.py` documents for passenger cars, #244). Any
HTTP error on a candidate therefore moves on to the next one, and a run that finds none of
them is a green "not published yet" no-op. Before 2026-10 only a 404 did: on 2026-10-24 a 520
on the first Q1-Q3 guess failed the run before it reached the third guess, the shape confirmed
in 2025. A 403 still fails the run. `scripts/test_fetch_acea_cv.py` (offline) pins this
and gates the workflow.

## See also

- [09-glossary.md § Variant definitions](09-glossary.md#variant-definitions-canonical) — the
  `HDV`/`Vans`/`Buses` canonical meanings this fetcher targets.
- [05-flows.md § Flow K](05-flows.md#flow-k--acea-ingest) — the sibling passenger-car ACEA
  fetcher this one was deliberately kept separate from.
- `scripts/fetch_acea.py` — the passenger-car fetcher; its module docstring is the reference
  for the always-list/conditional-list distinction this fetcher does *not* use (every country
  here is conditional).

## What the BEV column means: `series_meta.csv`

The "is this BEV or BEV+PHEV (EV)?" question is answered in one place,
`R/series_meta.R`, **per period** and from the data:

- A row is "EV" (combined BEV+PHEV) when its `(source, variant)` is registered
  in `EV_COMBINED_SOURCES` (ACEA, Vans/HDV/Buses) **and** the row has no PHEV /
  EREV value of its own. Everything else is pure BEV. The registry is needed
  only because "PHEV empty" alone can't distinguish ACEA's folded figure from a
  pure-BEV source that just doesn't publish PHEV (Poland's PZPM).
- A real split source (e.g. KBA for Germany, with PHEV filled) therefore reads
  "BEV" for its periods without touching any code; a mixed series such as
  Poland (ACEA quarters = EV, PZPM months = BEV) is labelled by its latest
  period, and `ev_basis_change` records where the basis switched.
- `render_country.R` feeds the result to the charts (`meta$bev_label`,
  `meta$has_phev_split`), to the post text (`has_phev_split_latest`) and to the
  TTM legend (hybrid bands without data are not listed), and upserts one row
  per series into `series_meta.csv`. The frontend reads `ev_combined_any` from
  that file for the `*` in Builder/Compare (no more footnote string matching).
- `hev_in_ice` only documents today's behaviour; the ICE definition is
  deliberately not unified.
- `scripts/build_series_meta.R` seeds/repairs the file offline.

To onboard a new combined-bucket source, add it to `EV_COMBINED_SOURCES`.
