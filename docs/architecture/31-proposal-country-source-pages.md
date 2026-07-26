# 31 · Proposal: public country source pages

**Status:** Phases 1–3 built (2026-07). Written 2026-07.
**Audience:** the maintainer + whoever implements this later.

## Implementation status

- **Phase 1 — done.** Content model (Option 1: YAML front-matter), template,
  and generator are live.
  - Generator: [`scripts/build_source_pages.py`](../../scripts/build_source_pages.py)
    — reads the front-matter + stub registry + `params.csv` (latest period,
    TTM BEV share) + the per-country CSV tail, fills one theme-aware template,
    and writes `sources/<slug>.html` plus a `sources/index.html` directory
    page. Re-run with `python3 scripts/build_source_pages.py`; validate with
    `--check`.
- **Phase 2 — done.** Front-matter on all 21 documented source docs (every
  `NN-source-*.md` except the gaps doc). The `hev_note` field handles sources
  that park a single combined hybrid bucket in the HEV column (Colombia,
  Malaysia) rather than splitting or folding it.
- **Phase 3 — mostly done.**
  - **Stubs:** brief entries for the 29 remaining gallery countries live in
    [`country_source_stubs.yaml`](country_source_stubs.yaml) (Option 2
    registry, used for the low-content cases). They render as "brief entry"
    pages; a doc wins over a stub on a slug clash so promotion is a delete.
    Total coverage is now **50 countries** (21 full + 29 brief).
  - **CI:** [`build-source-pages.yml`](../../.github/workflows/build-source-pages.yml)
    rebuilds and commits `sources/` on changes to the docs / stub registry /
    generator / `params.csv`, and runs `--check` on pull requests.
  - **Gallery links (section D):** the generator emits `sources/sources.json`
    (country → slug); `index.html` loads it and adds an "ⓘ Source" link to
    each country card, keyed on the base country (variant suffix stripped) and
    shown only when a page exists.

- **Refinement (2026-07).** The headline chip is now the **acquisition
  method**, not a live/planned status — one of `api` / `scrape` / `pdf` /
  `file` / `manual` (a required field on every entry). This replaced the vague
  "live/planned" ticker after an accuracy pass over the classifications:
  - Germany, UK, Australia, Georgia, South Korea, India are **manual** (no
    fetcher; their CSV `source` is the national body, not `ACEA`).
  - Hungary, Norway, Switzerland and the EU cluster are **ACEA/PDF** — grouped
    via `source_group: acea`, which injects one shared "About the ACEA figures"
    explainer instead of repeating it ~18×.
  - National stub sources (KBA, SMMT, ANFAVEA, ANAC, JADA, ANL, TÜİK, …) carry
    a `notes` paragraph so they read as full pages, not one-liners.

- **Data-derived sections (2026-07 cleanup).** The pages used to describe their
  data in prose only, so a page could drift from the CSV it described. Three
  sections are now computed from the committed CSVs at build time and cannot
  go stale:
  - **Variants table** — what each variant counts (`variant_notes`), the span
    held, the row count, and a link to the raw CSV. Variant CSVs are resolved
    by the repo-wide naming rule (`data/<Country>_<Variant>.csv`), with an
    optional `variant_files` override.
  - **"History we hold"** — a segmented coverage bar per variant on a shared
    year axis. Gaps in a bar are real gaps in the series, and mixed-cadence
    seams (Canada's yearly 2011–2016 before the quarterly M1 series) are
    visible rather than buried in prose. The cadence shown is the **observed**
    spacing of the periods; any other `time_interval` labels on the rows are
    listed alongside rather than taken as fact, because 22 CSVs carry
    quarterly/yearly labels on runs of consecutive months.
  - **"Which fuel columns this source fills"** — reported / present-but-zero /
    not-reported per variant, including columns the schema offers but the
    source never populates. This is what makes Finland's empty HEV column read
    as "this source does not split full hybrids" instead of "no hybrids here".

- **Link fields (2026-07 cleanup).** `source_url` is the primary
  human-openable entry point and should be the deepest **stable** page, not a
  bare homepage; `source_links` carries additional curated links. Machine-only
  endpoints (APIs, login-walled portals, relays) deliberately stay out of the
  front-matter and live in the doc body — a reader cannot click them to check
  anything. The generator additionally surfaces the exact upstream document
  the newest stored row came from, lifted from that row's `notes` column, so
  "where did June's number come from" is one click and never hand-maintained.

  Two rules worth keeping: never invent a URL to fill the field (Nepal's
  fiscal-year category slug changes annually, so the page describes the nav
  path instead), and where no public document exists at all, say so — South
  Korea's page states outright that its figures cannot be verified from there.

- **Missing data is stated, not hidden.** A declared variant with no CSV in
  the repo (Latvia `Used`, Switzerland `HDV`, all four of India) renders as
  "not in this repo" with an explanation, and a country with no store at all
  shows "latest period **modelled**" rather than claiming a store it lacks.

Everything in the proposal below is now implemented. What remains is content
work, not system work: promote high-traffic stubs to full source docs, and add
front-matter for any new country as it joins the gallery.

The rest of this document is the original proposal, kept for context.

## The idea

Every country in the gallery should have a human-readable "source page" —
the kind of page a curious visitor (or the maintainer six months later) can
open to answer: *where does this number actually come from, what exactly
does it count, and what should I be careful about?*

The [Netherlands architecture page](https://claude.ai/code/artifact/c83034f4-5639-42b0-aec2-e53619ad5023)
is the visual and tonal template: plain language, a top-to-bottom flow
diagram, a "what broke / how it works" narrative, links to the raw source.
This proposal is about turning that one-off into a **repeatable system** for
all ~40 countries, served from the gallery and linked from each country card.

### What each page should contain

1. **One-line what-it-is** and current status (live / stale / manual).
2. **The raw source** — a real, clickable link to the upstream (statistics
   office table, portal, PDF index) so a visitor can verify the numbers.
3. **A flow diagram** — origin → transport → our store → gallery, in the
   NL page's style.
4. **Definitions & scope** — what "Whole" / "HDV" / "Used" mean *for this
   country*, the column mapping (which upstream fuel labels map to BEV /
   PHEV / PETROL / …), and the vehicle-scope caveat (e.g. NL "HDV" ≈
   *Zware bedrijfsvoertuigen*, not a strict EU N-class).
5. **Caveats** — HEV-not-split, FCEV folded, backfill provenance,
   publication lag, restatement behaviour.
6. **Freshness** — latest month present, cadence.

## What already exists (don't rebuild it)

The raw material is mostly written — it just isn't presentable or linkable.

| Asset | Where | Reuse for |
|---|---|---|
| 22 developer source docs | `docs/architecture/NN-source-*.md` | Definitions, caveats, fragility, flow narrative |
| Semi-structured `## TL;DR` blocks | top of each source doc | **The content model already exists** — fixed fields: `Source`, `Underlying data`, `Auth`, `API`, `Variants`, `HEV`, `Backfill`, `Schedule`, `Scripts`, `Workflow` |
| `params.csv` | repo root | Per-country/variant metadata: `country, variant, source, data_per, ttm_bev_share, …` — gives latest-period + headline share |
| CSV `source` + `notes` columns | `data/<Country>*.csv` | Raw source string + per-row provenance (e.g. PDF URLs) |
| Glossary | `docs/architecture/09-glossary.md` | Shared definitions (vehicle scope, TTM, EREV folding) — link, don't duplicate |
| `14-data-source-gaps.md` | docs | Known-missing / low-confidence countries |

**Gap:** ~18 of ~40 countries have no source doc yet; the 22 that do are
inconsistent in structure past the TL;DR; none is reader-facing or linked.

## Proposed shape

### A. Content model (per-country front-matter)

Add a small structured block the generator can rely on, rather than parsing
free prose. Two options:

- **Option 1 — YAML front-matter** at the top of each `NN-source-*.md`.
  Keeps content next to the existing dev doc; one file per country.
- **Option 2 — a single `country_sources.yaml`** registry. All countries in
  one file; easier to see coverage gaps at a glance.

Recommended: **Option 1** (front-matter), because the prose that fills the
"definitions / caveats" sections already lives in those docs — keep the
structured summary with it. Proposed fields (superset of today's TL;DR):

```yaml
country: Netherlands
status: live            # live | stale | manual | planned
source_name: "RDW via duurzamemobiliteit.databank.nl (Swing 7.1)"
source_url: "https://duurzamemobiliteit.databank.nl/"
underlying: "RDW — Rijksdienst voor het Wegverkeer"
auth: none
cadence: "daily cron, 1st–15th"
variants: [Whole, Used, HDV]
hev_split: false        # drives the "no HEV column" caveat automatically
fcev: "folded into OTHERS"
backfill: "pre-2018 Whole from maintainer Google Sheet"
scope_note: "HDV ≈ Zware bedrijfsvoertuigen, not strict EU N-class"
column_map:
  BEV: BEV
  PHEV: PHEV
  Benzine: PETROL
  Diesel: DIESEL
  "Overig + FCEV": OTHERS
caveats:
  - "RDW doesn't split full hybrids; HEV lands in Petrol/Diesel"
  - "Publication date varies within the first half of the month"
fragility_doc: "docs/architecture/10-source-netherlands.md"
```

Everything the reader page needs is here or derivable; latest-period comes
from `params.csv` / the CSV at build time (not hand-maintained).

### B. Template

Lift the NL page into a single HTML template with slots for: header +
status chip, the flow diagram (a small fixed set of node types —
Origin / Portal / Transport / Fetcher / Store / Gallery — shown or hidden
per country), definitions table, caveats list, freshness footer. Keep the
theme-aware token CSS from the NL page verbatim so all pages share one look
and both light/dark work out of the box.

### C. Generator

A small script (`scripts/build_source_pages.py` or an R equivalent to match
the render stack) that, per country:

1. reads the front-matter + `params.csv` + the CSV tail (latest period),
2. fills the template,
3. writes `site/sources/<country>.html` (or wherever GitHub Pages serves).

Wire it into the existing manifest/pages build so pages regenerate when a
source doc or CSV changes — same trigger model as `render-country.yml`.

### D. Gallery linking

Add a small "ⓘ Source" link on each country card / trajectory page pointing
at `sources/<country>.html`. The link target is deterministic from the
country name, so this is a one-line template change in `index.html` once the
pages exist. Optionally list all of them on a `sources/index.html` directory
page.

## Rollout phases

1. **Template + generator + content model**, proven on 2–3 countries that
   already have rich docs (Netherlands, Denmark, China). Ship the gallery
   link for those.
2. **Backfill front-matter** for the other 19 documented countries (the
   TL;DR blocks convert almost mechanically).
3. **Author stubs** for the ~18 undocumented countries — at minimum
   source_url + variants + one caveat, marked `status: planned` where data
   confidence is low (cross-reference `14-data-source-gaps.md`).

## Open decisions (for whoever picks this up)

- **Language:** English (decided — matches the rest of the repo and the
  gallery's audience).
- **Hosting path:** `sources/<country>.html` under GitHub Pages vs a
  subpath. Needs a look at how `index.html` is currently served.
- **Depth per country:** full NL-style narrative for the hard cases
  (NL, Albania, China) vs a compact one-screen card for the easy ones
  (a clean stats-office API). The template should support both by letting
  sections be optional.
- **Drift:** the generator reads from the source docs, so the docs stay the
  single source of truth — but someone has to keep the front-matter honest
  when a pipeline changes. A CI check that every `NN-source-*.md` has valid
  front-matter would prevent silent rot.

## Why this is worth doing

- **Trust:** a public, linkable "here's exactly where this came from" page
  is the strongest credibility signal a data gallery can have.
- **Maintainability:** the definitions/caveats stop living only in the
  maintainer's head; the next person (or LLM) picks up a country cold.
- **Low marginal cost:** the content model already exists as TL;DR blocks;
  most of the work is the template + generator once, then near-mechanical
  per-country fill.
