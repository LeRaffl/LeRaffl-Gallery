# 38 · Source: ACEA Commercial Vehicles (multi-country, annual)

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
`Vans` / `HDV` / `Buses` variants.

## TL;DR

```
Source:    ACEA "New Commercial Vehicle Registrations" press release (PDF), acea.auto/files/
Auth:      None
Cadence:   ANNUAL ONLY — the January release covering the prior full calendar year.
           ACEA also publishes Q1 / H1 / Q1-Q3 mid-year snapshots, but each is a
           cumulative year-to-date total, not a standalone period, and this fetcher
           deliberately does not ingest them (see § 2, "why annual-only").
Countries: The same 19 markets scripts/fetch_acea.py covers for passenger cars
           (its ALWAYS_COUNTRIES + CONDITIONAL_COUNTRIES): Belgium, Bulgaria, Croatia,
           Cyprus, Czechia, Estonia, Greece, Hungary, Iceland, Latvia, Lithuania,
           Luxembourg, Malta, Norway, Poland, Romania, Slovakia, Slovenia, Switzerland.
Variants:  Vans (N1), HDV (N2+N3, i.e. medium+heavy trucks combined — already how the
           source reports "Total Truck"/"MHCV"), Buses (M2+M3).
Write rule: Conditional for every country (not the always/conditional split fetch_acea.py
           uses for passenger cars): a (country, variant, period) row is written only if
           no row exists yet, or the existing row's source is exactly "ACEA". This is what
           lets the fetcher run over every target country without ever overwriting a
           national HDV/Vans/Buses source (Austria, Luxembourg, Poland today all have one).
Eras:      Through ~2023, "old era" — TOTAL only, no fuel split (5 simple tables: LCV,
           HCV>=16t, MHCV>3.5t, MHBC, Total CV). From ~2024, "new era" — full fuel split
           per variant, but the "electrically chargeable" column combines BEV+PHEV (see § 3).
Parsing:   pdfplumber, but NOT via extract_text()/extract_tables() — both this release and
           fetch_acea.py's car-registration PDF position every character individually with
           `upright=False` (a Word/print-driver export quirk), which breaks pdfplumber's
           default word clustering ("A u s tria", extract_tables() finds nothing). We
           reconstruct lines directly from page.chars: group by rounded vertical position,
           sort left-to-right, and only insert a space where the horizontal gap between
           glyphs is wide enough to be a real word/column boundary. See § 4.
Scripts:   scripts/fetch_acea_cv.py
Workflow:  .github/workflows/fetch-acea-cv.yml
Schedule:  Daily cron, 18th-31st January, 10:15 UTC
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

## 2. Why annual-only

Since roughly 2024, ACEA no longer publishes a genuinely monthly commercial-vehicle release.
Instead it publishes four **cumulative year-to-date** snapshots per year:

| Checkpoint | Published | Covers |
|---|---|---|
| Q1 | ~April | Jan-Mar |
| H1 | ~July/August | Jan-Jun |
| Q1-Q3 | ~October | Jan-Sep |
| Full year | ~January (following year) | Jan-Dec |

A "Q1-Q3 2024" table is Jan-Sep 2024 **cumulative**, not Q3 alone. Treating each release as
a self-contained period would double-, triple- or quadruple-count registrations against
neighbouring releases, corrupting every trailing-window computation downstream: the TTM
share chart, the S-curve fit, and `weights.csv`.

Reconstructing genuine per-quarter deltas (`Q2 = H1 - Q1`, `Q3 = Q1-Q3 - H1`, …) is possible
in principle, but it requires an unbroken chain of consecutive checkpoints per country *and*
durable state that bridges across separate workflow runs (a GitHub Actions job can't read
"what did the H1 release say" without either re-parsing that PDF or persisting the number
somewhere) — machinery this repo has no precedent for. The **full year** release is the one
checkpoint that is always a clean, non-overlapping, self-contained period on its own
(Jan 1 - Dec 31, nothing to subtract), so `scripts/fetch_acea_cv.py` only ever ingests that
one. `time_interval` is written as `yearly` (`period = YYYY-07`, the existing convention —
see [09-glossary.md § Time / period](09-glossary.md)).

`--allow-partial-year` exists on the script purely for local inspection (prints what a Q1/H1/
Q1-Q3 release parses to); it never writes a CSV. If genuine quarterly granularity is wanted
later, it should be built as its own follow-up with its own explicit state file — not bolted
onto this one.

**A subtle but important consequence:** `period = YYYY-07` for a *yearly* row is the exact
same string as `YYYY-07` for a *monthly* July row. For a country whose HDV/Vans/Buses CSV
already has genuine monthly coverage (Luxembourg today), the conditional write rule naturally
protects against this: the existing July row's source isn't `ACEA`, so the yearly write is
skipped — no collision, no silent misattribution, just no backfill for that file (which
already has better data for that year anyway).

## 3. Why the combined "Electrically Chargeable" bucket lands in BEV

The 2024+ ("new era") tables report six fuel columns: **Electrically Chargeable** (footnote:
"Includes battery electric and plug-in hybrids"), **Hybrid Electric** (full+mild hybrid
combined), Others, Petrol, Diesel, Total. There is no separate BEV/PHEV split for commercial
vehicles — ACEA doesn't break it out the way it does for passenger cars.

Our schema has separate `BEV` and `PHEV` columns, and `BEV` is documented project-wide as
"the headline metric" ([09-glossary.md](09-glossary.md)). Leaving both empty would discard a
real, useful plug-in-adoption number; splitting it proportionally would be fabrication. The
chosen convention — consistent with how the glossary already handles a single combined
"Hybrid" bucket (mapped to `HEV`, footnoted) — is to map the combined Electrically Chargeable
figure into `BEV` and leave `PHEV` empty, with an explicit caveat in `footnotes.csv` for every
affected `(country, Vans/HDV/Buses)` row: **`BEV` here is BEV+PHEV combined, not a pure-BEV
count**, so it is not directly comparable to the same country's `Whole` BEV share (which
*is* properly split, since fetch_acea.py's car PDF separates BEV/PHEV/HEV distinctly).

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
JANUARY-DECEMBER columns give both the current and prior year in one file). This sandbox
has no live network access to `acea.auto` (confirmed via the environment's proxy status),
so no further historical years were fetched live. `notes` on every backfilled row cites the
real published URL, `https://www.acea.auto/files/20230125_PRCV_2212_FINAL.pdf`, not the
local upload path used to parse it.

The 2023-2025 gap (and everything before 2021) is **not** backfilled — this repo also holds
one Q1-Q3-2024 and one H1-2026 sample PDF (both new-era, fuel-split), but they are not
adjacent full-year checkpoints and reconstructing a clean annual figure from either without
fabricating data isn't possible (see § 2). They were used only to validate the new-era
parser (`--allow-partial-year`), never to write a row. The live pipeline picks up FY2025 and
every year after it going forward, once `fetch-acea-cv.yml` runs with real network access to
ACEA.

## 6. URL uncertainty (bring-up risk, documented up front)

ACEA has changed this release's filename scheme at least twice: a cryptic date-prefixed name
(`20230125_PRCV_2212_FINAL.pdf`) through ~2023, then `Press_release_commercial_vehicle_
registrations_Q1-Q3_2024.pdf` and `Press_release_commercial_vehicle_registrations-H1_2026.pdf`
— note the inconsistent underscore/hyphen before the period tag — for the 2024+ releases.
There is no confirmed sample of the **full-year** new-era filename in this repo.
`CANDIDATE_URL_TEMPLATES` in `scripts/fetch_acea_cv.py` lists the most plausible guesses,
tried in order; `--pdf-url` overrides them. Expect the first live January run to need a
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
