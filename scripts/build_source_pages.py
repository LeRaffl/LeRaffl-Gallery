#!/usr/bin/env python3
"""Generate public, reader-facing country "source pages" for the gallery.

Each `docs/architecture/NN-source-*.md` may carry a YAML front-matter block
(the structured content model from proposal doc 31). This script reads that
front-matter plus live facts from `params.csv` and the per-country data CSV,
fills a single theme-aware HTML template, and writes one page per country to
`sources/<slug>.html` — plus a `sources/index.html` directory page.

The pages are served straight from the repo by GitHub Pages, so the generated
HTML is committed. Re-run this whenever a source doc's front-matter or the
underlying CSV changes:

    python3 scripts/build_source_pages.py

Design notes:
- Front-matter is the single source of truth for definitions/caveats; latest
  period and TTM BEV share are read at build time (never hand-maintained).
- A doc with no front-matter is skipped, so this can roll out country by
  country without touching the ~18 docs that don't have a block yet.
"""

from __future__ import annotations

import csv
import html
import json
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs" / "architecture"
PARAMS = REPO / "params.csv"
STUBS = DOCS / "country_source_stubs.yaml"
OUT_DIR = REPO / "sources"
GH_BLOB = "https://github.com/LeRaffl/LeRaffl-Gallery/blob/master"

# Every entry (doc front-matter or stub) must carry these before it can
# become a page — the --check mode enforces it in CI.
REQUIRED_FIELDS = ("country", "slug", "source_name", "variants", "method")

# How the data is acquired — the page's headline label (replaces the old
# live/planned status). One of these five buckets per country.
METHOD_LABELS = {
    "api": "API",
    "scrape": "Scrape",
    "pdf": "PDF",
    "file": "File",
    "manual": "Manual",
}
METHOD_DESC = {
    "api": "pulled from a structured API / query endpoint",
    "scrape": "scraped from a web portal or dashboard",
    "pdf": "parsed from a published PDF",
    "file": "downloaded as a data file (XLSX / Parquet / ODS / zip)",
    "manual": "entered by hand from the published source",
}


# --------------------------------------------------------------------------
# Reading inputs
# --------------------------------------------------------------------------

def read_front_matter(path: Path) -> dict | None:
    """Return the parsed YAML front-matter of a markdown file, or None."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    block = text[3:end]
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError as exc:  # malformed block — surface, don't guess
        print(f"  ! {path.name}: front-matter parse error: {exc}", file=sys.stderr)
        return None
    return data if isinstance(data, dict) else None


def load_params() -> dict[tuple[str, str], dict]:
    """Map (country, variant) -> param row (for data_per + ttm_bev_share)."""
    out: dict[tuple[str, str], dict] = {}
    if not PARAMS.exists():
        return out
    with PARAMS.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out[(row["country"], row["variant"])] = row
    return out


def latest_csv_row(data_file: str) -> dict | None:
    """Return the last data row of a per-country CSV (by file order)."""
    if not data_file:
        return None
    path = REPO / data_file
    if not path.is_file():
        return None
    last = None
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("period"):
                last = row
    return last


# --------------------------------------------------------------------------
# Reading the per-variant CSVs
#
# Everything below is derived from the committed CSVs at build time, never
# hand-maintained: coverage spans, cadence, and which fuel columns a source
# actually populates. That way the page cannot drift from the data it
# describes — if the pipeline changes what it writes, the page changes with it.
# --------------------------------------------------------------------------

# Canonical fuel columns in display order. Not every country writes all of
# them; the matrix below reports exactly which ones carry values.
FUEL_COLUMNS = [
    "BEV", "PHEV", "EREV", "HEV",
    "PETROL", "DIESEL", "FLEXFUEL", "ICE", "OTHERS",
]

CADENCE_ORDER = {"monthly": 0, "quarterly": 1, "annual": 2, "yearly": 2}


def variant_file(fm: dict, variant: str) -> str | None:
    """Repo-relative CSV path for a variant, by the repo-wide naming rule.

    `Whole` lives in the country's base file; every other variant is the same
    path with `_<Variant>` before the extension (data/Canada_Pickups.csv,
    data/Thailand_3-Wheelers.csv, …). Explicit `variant_files` entries in the
    front-matter win, for anything that ever breaks the convention.
    """
    explicit = (fm.get("variant_files") or {}).get(variant)
    if explicit:
        return explicit
    base = fm.get("data_file")
    if not base or not base.endswith(".csv"):
        return None
    if variant == "Whole":
        return base
    return f"{base[:-4]}_{variant}.csv"


def read_variant_facts(path: str | None) -> dict | None:
    """Coverage, cadence and populated-column facts for one variant CSV."""
    if not path:
        return None
    fp = REPO / path
    if not fp.is_file():
        return None

    periods: list[str] = []
    cadences: set[str] = set()
    filled: dict[str, int] = {c: 0 for c in FUEL_COLUMNS}
    nonzero: dict[str, int] = {c: 0 for c in FUEL_COLUMNS}
    present: set[str] = set()

    with fp.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        present = {c for c in (reader.fieldnames or []) if c in FUEL_COLUMNS}
        for row in reader:
            period = (row.get("period") or "").strip()
            if not period:
                continue
            periods.append(period)
            cadences.add((row.get("time_interval") or "").strip().lower())
            for col in present:
                raw = (row.get(col) or "").strip()
                if raw == "":
                    continue
                filled[col] += 1
                try:
                    if float(raw) != 0:
                        nonzero[col] += 1
                except ValueError:
                    pass

    if not periods:
        return None

    periods.sort()
    labelled = sorted((c for c in cadences if c),
                      key=lambda c: CADENCE_ORDER.get(c, 9))
    observed, uniform = observed_cadence(periods)
    return {
        "path": path,
        "periods": periods,
        "first": periods[0],
        "last": periods[-1],
        "rows": len(periods),
        # What the periods actually do, and what the rows claim. These
        # disagree in a few CSVs (blocks of consecutive months carrying
        # time_interval=quarterly), so the page reports the observed spacing
        # and says when the label contradicts it, rather than repeating a
        # label the data does not support.
        "cadence": [observed] if observed else labelled,
        "labelled": labelled,
        # True when the rows claim a cadence the spacing does not support.
        "cadence_mismatch": bool(
            observed and uniform and set(labelled) - {observed}),
        "present": present,
        "filled": filled,
        "nonzero": nonzero,
    }


def observed_cadence(periods: list[str]) -> tuple[str | None, bool]:
    """(cadence, uniform) inferred from how the period labels are spaced.

    `uniform` is True when nearly every step matches the dominant one — i.e.
    the series really is one cadence throughout, so any *other* time_interval
    label on its rows is a mislabel rather than a genuine cadence change.
    """
    xs = sorted({year_of(p) for p in periods})
    if len(xs) < 2:
        return None, False
    gaps = [round((b - a) * 12) for a, b in zip(xs, xs[1:])]
    dominant = max(set(gaps), key=gaps.count)
    uniform = gaps.count(dominant) / len(gaps) >= 0.9
    return {1: "monthly", 3: "quarterly", 12: "yearly"}.get(dominant), uniform


def collect_variant_facts(fm: dict) -> list[tuple[str, dict | None]]:
    """(variant, facts) in declared order; facts is None when there is no CSV.

    A declared variant with no file under `data/` is not an error — a few
    series (Latvia Used, Switzerland HDV, all of India) are still rendered
    from the maintainer's local pipeline and were never committed. Carrying
    the `None` through means the page can say that out loud instead of
    quietly showing one fewer row than the variant count promises.
    """
    return [(v, read_variant_facts(variant_file(fm, v)))
            for v in (fm.get("variants") or [])]


def year_of(period: str) -> float:
    """Fractional year for a period label (YYYY, YYYY-MM), for the timeline."""
    try:
        year = int(period[:4])
    except (ValueError, TypeError):
        return 0.0
    if len(period) >= 7 and period[4] == "-":
        try:
            return year + (int(period[5:7]) - 1) / 12.0
        except ValueError:
            return float(year)
    return float(year)


def contiguous_runs(periods: list[str], cadence: list[str]) -> list[tuple[float, float]]:
    """Group sorted periods into runs, splitting where the series has a gap.

    A "gap" is a jump larger than ~2 expected steps, so a normal monthly or
    quarterly rhythm stays one run while a real hole in the history (or a
    cadence seam like Canada's yearly→quarterly switch) shows as a break.
    """
    if not periods:
        return []
    step = 1.0 if (cadence and cadence[0] in ("annual", "yearly")) else (
        0.25 if (cadence and cadence[0] == "quarterly") else 1 / 12.0)
    tol = step * 2.5

    xs = [year_of(p) for p in periods]
    runs: list[tuple[float, float]] = []
    start = prev = xs[0]
    for x in xs[1:]:
        if x - prev > tol:
            runs.append((start, prev + step))
            start = x
        prev = x
    runs.append((start, prev + step))
    return runs


# --------------------------------------------------------------------------
# Small rendering helpers
# --------------------------------------------------------------------------

def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def pct(value) -> str:
    """Format a 0..1 share as a percentage, or "—" if it isn't one.

    A share outside [0, 1] cannot be real, so it is suppressed rather than
    published. This is not hypothetical: `params.csv` currently carries
    `ttm_bev_share = 2019` for both Nepal variants — a stray year in the
    share column — which would otherwise render as "201900.0%".
    """
    try:
        share = float(value)
    except (TypeError, ValueError):
        return "—"
    if not 0.0 <= share <= 1.0:
        return "—"
    return f"{share * 100:.1f}%"


def method_chip(method: str) -> str:
    label = METHOD_LABELS.get(method, method or "—")
    title = METHOD_DESC.get(method, "")
    return (f'<span class="chip chip--{esc(method)}" title="{esc(title)}">'
            f'{esc(label)}</span>')


def gh_link(path: str) -> str:
    if not path:
        return "—"
    return f'<a href="{GH_BLOB}/{esc(path)}"><code>{esc(path)}</code></a>'


# --------------------------------------------------------------------------
# Page building
# --------------------------------------------------------------------------

def build_flow(fm: dict) -> str:
    """A simple top-to-bottom origin → gallery pipeline, per country.

    Nodes with no content are dropped, so a stub entry that only knows its
    origin and source still renders a coherent (shorter) diagram.
    """
    src_name = esc(fm.get("source_name", "Source"))
    src_url = fm.get("source_url", "")
    src_html = f'<a href="{esc(src_url)}">{src_name}</a>' if src_url else src_name

    fetcher_html = ""
    if fm.get("fetcher"):
        fetcher_html = gh_link(fm["fetcher"]) + (
            f' · {gh_link(fm["workflow"])}' if fm.get("workflow") else "")

    stages = [
        ("Origin", esc(fm["underlying"]) if fm.get("underlying") else ""),
        ("Source / API", src_html if fm.get("source_name") else ""),
        ("Fetcher", fetcher_html),
        ("Store", gh_link(fm["data_file"]) if fm.get("data_file") else ""),
        ("Gallery", '<a href="../">BEV Trajectories gallery</a>'),
    ]
    stages = [(t, s) for t, s in stages if s]

    nodes = []
    for i, (title, sub) in enumerate(stages):
        if i:
            nodes.append('<div class="flow-arrow" aria-hidden="true">▼</div>')
        nodes.append(
            f'<div class="flow-node"><div class="flow-title">{esc(title)}</div>'
            f'<div class="flow-sub">{sub}</div></div>')
    return '<div class="flow">' + "".join(nodes) + "</div>"


def build_coverage(variant_facts: list[tuple[str, dict | None]]) -> str:
    """Timeline of what history we actually hold, one row per variant.

    Single-hue segmented bars on a shared year axis: the segments are the
    contiguous runs, so a gap in the history reads as a gap in the bar. This
    is the one thing about a source that prose consistently fails to convey —
    "2014-01 onward" hides a hole, a bar does not.
    """
    variant_facts = [(v, f) for v, f in variant_facts if f]
    if not variant_facts:
        return ""

    lo = min(year_of(f["first"]) for _, f in variant_facts)
    hi = max(year_of(f["last"]) for _, f in variant_facts) + 1
    if hi - lo < 1:
        hi = lo + 1

    label_w, right_pad, row_h, bar_h = 118, 58, 26, 12
    plot_w = 470
    height = len(variant_facts) * row_h + 30
    width = label_w + plot_w + right_pad

    def x_of(year: float) -> float:
        return label_w + (year - lo) / (hi - lo) * plot_w

    # Year gridlines at a readable density (never more than ~10 labels).
    span = hi - lo
    step = 1
    for candidate in (1, 2, 5, 10, 20):
        if span / candidate <= 10:
            step = candidate
            break
    first_tick = int(lo) + ((-int(lo)) % step)

    parts = [
        f'<svg class="cov" viewBox="0 0 {width} {height}" width="100%" '
        f'height="{height}" role="img" '
        f'aria-label="History held per variant, by year">']

    for tick in range(first_tick, int(hi) + 1, step):
        x = x_of(tick)
        parts.append(
            f'<line class="cov-grid" x1="{x:.1f}" y1="6" x2="{x:.1f}" '
            f'y2="{len(variant_facts) * row_h + 8}"/>')
        parts.append(
            f'<text class="cov-tick" x="{x:.1f}" '
            f'y="{len(variant_facts) * row_h + 24}" '
            f'text-anchor="middle">{tick}</text>')

    for i, (variant, facts) in enumerate(variant_facts):
        y = 10 + i * row_h
        parts.append(
            f'<text class="cov-label" x="0" y="{y + bar_h - 2}">{esc(variant)}</text>')
        for a, b in contiguous_runs(facts["periods"], facts["cadence"]):
            xa, xb = x_of(a), x_of(min(b, hi))
            parts.append(
                f'<rect class="cov-bar" x="{xa:.1f}" y="{y}" '
                f'width="{max(xb - xa, 1.5):.1f}" height="{bar_h}" rx="3">'
                f'<title>{esc(variant)}: {esc(facts["first"])} → '
                f'{esc(facts["last"])}</title></rect>')
        cadence = "/".join(facts["cadence"]) or "—"
        parts.append(
            f'<text class="cov-meta" x="{label_w + plot_w + 6}" '
            f'y="{y + bar_h - 2}">{esc(cadence)}</text>')

    parts.append("</svg>")

    notes = ", ".join(
        f"{esc(v)} {esc(f['first'])}–{esc(f['last'])} ({f['rows']} rows)"
        for v, f in variant_facts)

    # Where a CSV also carries other time_interval labels, say so in the
    # caption rather than beside the bar, where it would overflow.
    mixed = {c for _, f in variant_facts
             for c in f["labelled"] if c not in f["cadence"]}
    if mixed:
        notes += (". Some rows additionally carry a <code>time_interval</code> of "
                  + "/".join(f"<code>{esc(c)}</code>" for c in sorted(mixed))
                  + "; the cadence shown is the spacing the periods actually have")

    return (
        '<section><h2>History we hold</h2>'
        '<p class="fig-lead">Every bar is the span actually present in our '
        'stored CSV — breaks in a bar are real gaps in the series, not '
        'rendering. Cadence is shown on the right.</p>'
        f'{"".join(parts)}'
        f'<p class="fig-note">{notes}.</p></section>')


# Glyphs for the fuel-column matrix. Labelled, never colour-alone.
_CELL_FULL = ('<span class="cell cell--yes" title="{t}">'
              '<span aria-hidden="true">●</span><span class="sr">reported</span></span>')
_CELL_ZERO = ('<span class="cell cell--zero" title="{t}">'
              '<span aria-hidden="true">◐</span><span class="sr">always zero</span></span>')
_CELL_NONE = ('<span class="cell cell--no" title="{t}">'
              '<span aria-hidden="true">·</span><span class="sr">not reported</span></span>')


def build_column_matrix(variant_facts: list[tuple[str, dict | None]]) -> str:
    """Which fuel columns each variant actually carries values for.

    The single most misread thing about this dataset: a blank column does not
    mean "no such cars", it means "this source does not split them out"
    (Finland's full hybrids sit inside Petrol; Thailand reports one aggregate
    ICE). Showing filled / always-zero / absent per column makes that legible
    without reading the caveats.
    """
    variant_facts = [(v, f) for v, f in variant_facts if f]
    if not variant_facts:
        return ""

    # Columns the CSV schema *offers*, not just the ones with values — a
    # column that exists and stays empty (Finland's HEV) is precisely what a
    # reader needs to see, so it must not be optimised away.
    cols = [c for c in FUEL_COLUMNS
            if any(c in f["present"] for _, f in variant_facts)]
    if not cols:
        return ""

    head = "".join(f"<th>{esc(c)}</th>" for c in cols)
    body = []
    for variant, facts in variant_facts:
        cells = []
        for col in cols:
            if col not in facts["present"] or not facts["filled"][col]:
                cells.append(_CELL_NONE.format(
                    t=f"{col}: no values in {facts['path']}"))
            elif not facts["nonzero"][col]:
                cells.append(_CELL_ZERO.format(
                    t=f"{col}: present but zero in every row"))
            else:
                share = facts["filled"][col] / facts["rows"] * 100
                cells.append(_CELL_FULL.format(
                    t=f"{col}: values in {facts['filled'][col]} of "
                      f"{facts['rows']} rows ({share:.0f}%)"))
        body.append(f"<tr><th>{esc(variant)}</th>"
                    + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")

    return (
        '<section><h2>Which fuel columns this source fills</h2>'
        '<p class="fig-lead">A blank column almost never means "no such cars" — '
        'it means this source does not split them out, and those vehicles are '
        'counted inside another column. Check the caveats for where they land.</p>'
        f'<div class="scroll"><table class="matrix"><tr><th></th>{head}</tr>'
        f'{"".join(body)}</table></div>'
        '<p class="fig-note">'
        '<span class="cell cell--yes" aria-hidden="true">●</span> reported &nbsp; '
        '<span class="cell cell--zero" aria-hidden="true">◐</span> column exists '
        'but is zero in every row &nbsp; '
        '<span class="cell cell--no" aria-hidden="true">·</span> not reported by '
        'this source. Hover a cell for the row count.</p></section>')


def build_variants_table(fm: dict, variant_facts: list[tuple[str, dict | None]]) -> str:
    """One row per variant: what it counts, what we hold, and the raw CSV."""
    if not variant_facts:
        return ""
    notes = fm.get("variant_notes") or {}
    rows = []
    for variant, facts in variant_facts:
        if facts is None:
            held = ('<span class="dim">not in this repo</span>')
            raw = ('<span class="dim">rendered from the maintainer\'s local '
                   'pipeline; the series was never committed here</span>')
        else:
            held = (f'{esc(facts["first"])} – {esc(facts["last"])}<br>'
                    f'<span class="dim">{facts["rows"]} rows</span>')
            raw = gh_link(facts["path"])
        rows.append(
            f'<tr><th>{esc(variant)}</th>'
            f'<td>{esc(notes.get(variant, "—"))}</td>'
            f'<td class="nowrap">{held}</td>'
            f'<td>{raw}</td></tr>')
    return (
        '<section><h2>Variants</h2>'
        '<p class="fig-lead">Each variant is its own series with its own CSV. '
        'Not every variant is charted in the gallery — the CSV is the '
        'authoritative record either way.</p>'
        '<div class="scroll"><table class="vars">'
        '<tr><th>Variant</th><th>What it counts</th><th>Held</th>'
        '<th>Raw data</th></tr>'
        f'{"".join(rows)}</table></div></section>')


def build_definitions(fm: dict) -> str:
    rows = []

    def row(label, value_html):
        rows.append(f"<tr><th>{esc(label)}</th><td>{value_html}</td></tr>")

    method = fm.get("method")
    if method:
        row("Acquisition",
            f'{esc(METHOD_LABELS.get(method, method))} — {esc(METHOD_DESC.get(method, ""))}')

    col_map = fm.get("column_map") or {}
    if col_map:
        pairs = "".join(
            f'<div class="map-pair"><code>{esc(k)}</code>'
            f'<span class="map-arrow">→</span><code>{esc(v)}</code></div>'
            for k, v in col_map.items())
        row("Column mapping", f'<div class="map">{pairs}</div>')

    if fm.get("scope_note"):
        row("Vehicle scope", esc(fm["scope_note"]))

    # HEV handling. `hev_note` overrides the boolean-derived text for the
    # cases where neither "split" nor "folds into combustion" is accurate
    # (e.g. a single combined hybrid bucket parked in the HEV column). A
    # stub with neither field simply omits the row rather than guessing.
    if fm.get("hev_note"):
        row("HEV (full hybrids)", esc(fm["hev_note"]))
    elif "hev_split" in fm:
        row("HEV (full hybrids)",
            "split into its own column" if fm.get("hev_split")
            else "not split by the source — folds into the combustion totals")

    if fm.get("fcev"):
        row("FCEV", esc(fm["fcev"]))
    if fm.get("backfill") and fm["backfill"] != "none":
        row("Backfill", esc(fm["backfill"]))
    if fm.get("auth"):
        row("Auth", esc(fm["auth"]))

    return '<table class="defs">' + "".join(rows) + "</table>"


def build_caveats(fm: dict) -> str:
    caveats = fm.get("caveats") or []
    if not caveats:
        return ""
    items = "".join(f"<li>{esc(c)}</li>" for c in caveats)
    return f'<section><h2>Caveats</h2><ul class="caveats">{items}</ul></section>'


def build_notes(fm: dict) -> str:
    """Optional free prose ('How it works') for the expanded national entries."""
    notes = fm.get("notes") or []
    if isinstance(notes, str):
        notes = [notes]
    if not notes:
        return ""
    paras = "".join(f"<p>{esc(p)}</p>" for p in notes)
    return f'<section><h2>How it works</h2>{paras}</section>'


# One shared explainer for every ACEA-fed country, injected by the generator
# so the ~18 ACEA pages don't repeat the same paragraph in the registry.
ACEA_GROUP_NOTE = (
    '<section><h2>About the ACEA figures</h2>'
    "<p>This country's monthly total comes from ACEA's Europe-wide "
    "<em>new-car-registrations</em> press release — one PDF covering the EU, "
    "EFTA and the UK, parsed into per-country rows. It is an <strong>industry-"
    "association aggregate</strong>, not a direct national-registry feed: it "
    "counts registrations reported through ACEA, is published with a lag "
    "(usually the third to fourth week of the following month), and carries only "
    "the fuel split ACEA itself reports. Where a national registry is the richer "
    "source of record (e.g. Norway's OFV, Switzerland's BFS), we still ingest the "
    "ACEA figure here for consistency across the cluster.</p></section>")


def build_group_note(fm: dict) -> str:
    return ACEA_GROUP_NOTE if fm.get("source_group") == "acea" else ""


# Facts that are true of every ACEA-fed country because they are properties of
# the press release itself, not of the country. Defaulted here rather than
# copy-pasted into 18 registry entries — an entry can still override any of
# them, and country-specific caveats are appended to (not replaced by) these.
ACEA_GROUP_DEFAULTS = {
    "scope_note": ("New passenger cars only. ACEA publishes a single figure per "
                   "country per month — there is no van, truck or bus variant, "
                   "and no private/company split."),
    "hev_split": True,
    "fcev": "not broken out — folded into ACEA's OTHERS column.",
}

ACEA_GROUP_CAVEATS = [
    "An industry-association aggregate, not a national-registry feed — see the "
    "note above for what that means for completeness and timing.",
    "The six fuel columns are the ones ACEA itself prints (battery electric, "
    "plug-in hybrid, hybrid electric, others, petrol, diesel). OTHERS is a "
    "reported column, not a residual we compute, and it is where LPG, CNG and "
    "hydrogen end up.",
    "Each release also restates the same month a year earlier, so a prior-year "
    "figure can be corrected retroactively.",
]


def apply_group_defaults(fm: dict) -> dict:
    """Fill in the facts that follow from the source group, not the country."""
    if fm.get("source_group") != "acea":
        return fm
    fm = dict(fm)
    for key, value in ACEA_GROUP_DEFAULTS.items():
        fm.setdefault(key, value)
    fm["caveats"] = ACEA_GROUP_CAVEATS + list(fm.get("caveats") or [])
    return fm


URL_RE = re.compile(r"https?://[^\s|,]+")


def build_sources_section(fm: dict, last_row: dict | None) -> str:
    """Everything a reader needs to go and check the numbers themselves.

    Three tiers, in decreasing directness:
      1. the exact document the newest stored row came from, lifted straight
         out of that row's `notes` (so it is never stale),
      2. curated deep links from `source_links` — the publication page, the
         dataset, the PDF, whatever a human can actually open,
      3. the headline `source_url`.

    Machine-only endpoints (APIs, login-walled portals, relays) deliberately
    stay out of here — they live in the developer doc linked at the foot of
    the page, because they are not something a reader can click and verify.
    """
    src_url = fm.get("source_url", "")
    if src_url:
        lead = "<p>Go and check the numbers yourself:</p>"
        primary = (f'<a class="source-btn" href="{esc(src_url)}">'
                   f'{esc(fm.get("source_name", "source"))} ↗</a>')
    else:
        # No link means no independent check is possible. That is worth
        # saying out loud rather than rendering a button that does nothing.
        lead = ('<p><strong>We cannot point you at a document for this '
                'country.</strong> The figures are attributed to the source '
                'below, but the exact published page has not been confirmed, '
                'so this is the one country whose numbers you cannot verify '
                'from here.</p>')
        primary = (f'<span class="source-btn source-btn--dead">'
                   f'{esc(fm.get("source_name", "—"))}</span>')

    extra = []
    for link in (fm.get("source_links") or []):
        if not isinstance(link, dict) or not link.get("url"):
            continue
        note = f' <span class="dim">— {esc(link["note"])}</span>' if link.get("note") else ""
        extra.append(
            f'<li><a href="{esc(link["url"])}">{esc(link.get("label", link["url"]))}</a>'
            f'{note}</li>')

    # The per-row `notes` column carries the exact upstream document for many
    # countries (the ACEA press release, the DGT zip, the CPCA article …).
    # Surfacing it makes "where did June's number come from" a one-click answer.
    live = ""
    if last_row:
        found = URL_RE.search(last_row.get("notes") or "")
        if found:
            url = found.group(0)
            live = (
                f'<p class="live-src">Newest stored month '
                f'(<code>{esc(last_row.get("period", ""))}</code>) was read from '
                f'<a href="{esc(url)}">this exact document ↗</a>.</p>')

    extra_html = f'<ul class="srclist">{"".join(extra)}</ul>' if extra else ""
    unauth = ('<p class="dim">Access to the machine endpoint behind this page '
              'needs credentials — the developer doc at the foot of the page '
              'has the details.</p>' if fm.get("auth") and fm["auth"] != "none"
             else "")

    return (
        '<h2>Raw source</h2>'
        f'{lead}'
        f'<p>{primary}</p>{extra_html}{live}{unauth}')


def build_page(fm: dict, params: dict, is_stub: bool = False) -> str:
    fm = apply_group_defaults(fm)
    country = fm.get("country", "Unknown")
    whole = params.get((country, "Whole")) or {}
    latest_period = whole.get("data_per", "—")
    ttm = pct(whole.get("ttm_bev_share"))
    variants = fm.get("variants") or []

    last_row = latest_csv_row(fm.get("data_file", ""))
    csv_period = last_row.get("period") if last_row else latest_period
    csv_source = last_row.get("source") if last_row else fm.get("source_name", "")

    variant_facts = collect_variant_facts(fm)

    # With no CSV in the repo there is nothing "held" — the only period we
    # know is the one the fitted model carries. Label it as such instead of
    # claiming a store that doesn't exist (see India).
    has_store = last_row is not None
    period_label = "Latest period held" if has_store else "Latest period modelled"
    freshness = (f'Latest period in our store: <code>{esc(csv_period)}</code>.'
                 if has_store else
                 'No data file for this country in the repository — the period '
                 f'below is the one the fitted model carries: '
                 f'<code>{esc(csv_period)}</code>.')

    # A brief-entry banner only where the page really is thin — i.e. a stub
    # with no expanded prose. Once a stub gets `notes`, it reads as a full
    # page and the banner would be misleading.
    banner = ""
    if is_stub and not fm.get("notes") and fm.get("source_group") != "acea":
        banner = ('<div class="banner">Brief entry — a fuller write-up is still '
                  'to come. Use the source link to verify the figures.</div>')

    # Only full (documented) entries carry a developer pipeline doc to link.
    dev_note = (f'<p>Full pipeline notes (for developers): '
                f'{gh_link(fm["fragility_doc"])}</p>'
                if fm.get("fragility_doc") else "")

    # The stored data and the fitted model can be a step apart (a month
    # arrives before the next render). Say so rather than showing one number
    # and letting the reader assume it covers both.
    model_note = ""
    if has_store and latest_period and latest_period != "—" and latest_period != csv_period:
        model_note = (f'Curves in the gallery are fitted through '
                      f'<code>{esc(latest_period)}</code>.<br>')

    return TEMPLATE.format(
        css=BASE_CSS,
        country=esc(country),
        method_chip=method_chip(fm.get("method", "")),
        banner=banner,
        summary=esc(fm.get("summary", "")),
        latest_period=esc(latest_period),
        ttm=esc(ttm),
        n_variants=len(variants),
        sources=build_sources_section(fm, last_row),
        notes=build_notes(fm),
        flow=build_flow(fm),
        definitions=build_definitions(fm),
        variants_table=build_variants_table(fm, variant_facts),
        coverage=build_coverage(variant_facts),
        matrix=build_column_matrix(variant_facts),
        group_note=build_group_note(fm),
        caveats=build_caveats(fm),
        csv_period=esc(csv_period),
        csv_source=esc(csv_source) or "—",
        cadence=esc(fm.get("cadence") or "—"),
        period_label=period_label,
        freshness=freshness,
        model_note=model_note,
        dev_note=dev_note,
    )


def build_index(pages: list[dict]) -> str:
    cards = []
    for p in sorted(pages, key=lambda x: x["country"]):
        cards.append(
            f'<a class="dir-card" href="{esc(p["slug"])}.html">'
            f'<div class="dir-top">{esc(p["country"])}{method_chip(p["method"])}</div>'
            f'<div class="dir-sub">{esc(p["summary"])}</div>'
            f'<div class="dir-meta">Latest {esc(p["latest_period"])}'
            f' · TTM BEV {esc(p["ttm"])}</div></a>')
    n_full = sum(1 for p in pages if not p.get("is_stub"))
    return INDEX_TEMPLATE.format(
        css=BASE_CSS, cards="".join(cards), n=len(pages), n_full=n_full)


# --------------------------------------------------------------------------
# Templates (theme-aware: dark to match the gallery, light override for
# standalone viewing)
# --------------------------------------------------------------------------

BASE_CSS = """
:root{
  --bg:#0b0c10; --panel:#0f1525; --border:#1f2a44; --text:#e9eef2;
  --muted:#9fb3d1; --accent:#7cc4ff; --accent2:#00e5ff;
  --ok-bg:rgba(60,180,120,.18); --ok-tx:#bff5d8;
  --warn-bg:rgba(220,80,80,.18); --warn-tx:#ffb4b4;
  --chip-bg:#101a33;
}
@media (prefers-color-scheme: light){
  :root{
    --bg:#f5f7fb; --panel:#ffffff; --border:#d8e0ee; --text:#111827;
    --muted:#51607a; --accent:#1763b8; --accent2:#0a7ea4;
    --ok-bg:rgba(30,140,90,.14); --ok-tx:#0d5a38;
    --warn-bg:rgba(200,60,60,.12); --warn-tx:#8a1f1f;
    --chip-bg:#eef2fb;
  }
}
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:var(--bg);color:var(--text);
  font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Arial,sans-serif;
  line-height:1.55}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.9em}
.wrap{max-width:820px;margin:0 auto;padding:28px 18px 64px}
.back{display:inline-block;margin-bottom:18px;color:var(--muted);font-size:14px}
h1{font-size:28px;margin:0 0 6px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}
h2{font-size:18px;margin:34px 0 12px;border-bottom:1px solid var(--border);padding-bottom:6px}
.lead{color:var(--muted);font-size:16px;margin:0 0 22px}
.chip{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;
  font-weight:700;letter-spacing:.03em;background:var(--chip-bg);color:var(--accent);
  border:1px solid transparent}
/* Acquisition-method chips — tinted background reads on both themes; text is a
   mid-tone that stays legible over light and dark. */
.chip--api{background:rgba(56,139,222,.16);color:#3b8fdd;border-color:rgba(56,139,222,.4)}
.chip--scrape{background:rgba(139,92,246,.16);color:#9a7cf0;border-color:rgba(139,92,246,.4)}
.chip--pdf{background:rgba(224,122,63,.18);color:#e07a3f;border-color:rgba(224,122,63,.42)}
.chip--file{background:rgba(46,168,120,.16);color:#33b07c;border-color:rgba(46,168,120,.42)}
.chip--manual{background:rgba(180,140,40,.18);color:#c99a2e;border-color:rgba(180,140,40,.45)}
.banner{background:var(--chip-bg);border:1px solid var(--border);border-radius:10px;
  padding:12px 14px;margin:0 0 20px;font-size:14px;color:var(--muted)}
.stats{display:flex;gap:14px;flex-wrap:wrap;margin:0 0 8px}
.stat{flex:1 1 140px;background:var(--panel);border:1px solid var(--border);
  border-radius:12px;padding:14px 16px}
.stat .n{font-size:22px;font-weight:700}
.stat .l{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.source-btn{display:inline-block;margin:6px 0 4px;padding:10px 16px;border-radius:10px;
  background:var(--panel);border:1px solid var(--border);font-weight:600}
.flow{display:flex;flex-direction:column;align-items:stretch;gap:2px;margin:8px 0}
.flow-node{background:var(--panel);border:1px solid var(--border);border-radius:10px;
  padding:10px 14px}
.flow-title{font-weight:700;font-size:13px;color:var(--accent)}
.flow-sub{font-size:14px;color:var(--text)}
.flow-arrow{text-align:center;color:var(--muted);font-size:14px;line-height:1}
table.defs{width:100%;border-collapse:collapse}
table.defs th,table.defs td{text-align:left;vertical-align:top;padding:9px 10px;
  border-bottom:1px solid var(--border);font-size:15px}
table.defs th{width:190px;color:var(--muted);font-weight:600}
.map{display:flex;flex-direction:column;gap:4px}
.map-pair{display:flex;align-items:center;gap:8px}
.map-arrow{color:var(--muted)}
.caveats{margin:0;padding-left:20px}
.caveats li{margin:6px 0}
.footer{margin-top:34px;padding-top:16px;border-top:1px solid var(--border);
  color:var(--muted);font-size:14px}
.dir-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px}
.dir-card{display:block;background:var(--panel);border:1px solid var(--border);
  border-radius:12px;padding:16px}
.dir-card:hover{border-color:var(--accent)}
.dir-top{display:flex;justify-content:space-between;align-items:center;gap:8px;
  font-weight:700;font-size:17px;color:var(--text);margin-bottom:6px}
.dir-sub{color:var(--muted);font-size:14px;min-height:40px}
.dir-meta{margin-top:8px;font-size:13px;color:var(--accent)}

/* --- shared bits for the data-derived sections ------------------------- */
.dim{color:var(--muted)}
.nowrap{white-space:nowrap}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);
  white-space:nowrap}
/* Wide content scrolls inside its own box; the page never scrolls sideways. */
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
.fig-lead{color:var(--muted);font-size:14px;margin:0 0 12px}
.fig-note{color:var(--muted);font-size:13px;margin:10px 0 0}
.srclist{margin:6px 0 0;padding-left:20px;font-size:15px}
.srclist li{margin:4px 0}
.live-src{font-size:14px;margin:12px 0 0}
.source-btn--dead{color:var(--muted);font-weight:600}

/* Coverage timeline — one hue, no legend needed (a single series). */
.cov{display:block;margin:6px 0 0;max-width:100%}
.cov-bar{fill:var(--accent);opacity:.85}
.cov-grid{stroke:var(--border);stroke-width:1}
.cov-label{fill:var(--text);font-size:12px;font-weight:600}
.cov-tick,.cov-meta{fill:var(--muted);font-size:11px}

/* Fuel-column matrix — glyph + tooltip, never colour alone. */
table.vars,table.matrix{width:100%;border-collapse:collapse;font-size:14px}
table.vars th,table.vars td,table.matrix th,table.matrix td{
  text-align:left;vertical-align:top;padding:8px 10px;
  border-bottom:1px solid var(--border)}
table.vars th,table.matrix th{color:var(--muted);font-weight:600}
table.matrix td{text-align:center}
table.matrix th:first-child{white-space:nowrap}
.cell{font-size:15px;line-height:1}
.cell--yes{color:var(--ok-tx)}
.cell--zero{color:var(--muted)}
.cell--no{color:var(--muted);opacity:.55}
@media (prefers-color-scheme: light){
  .cell--yes{color:#0d5a38}
}
"""

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{country} — data source · BEV Trajectories</title>
<meta name="description" content="{summary}">
<style>{css}</style>
</head>
<body>
<div class="wrap">
  <a class="back" href="./">← All sources</a>
  <h1>{country} {method_chip}</h1>
  {banner}
  <p class="lead">{summary}</p>

  <div class="stats">
    <div class="stat"><div class="n">{csv_period}</div><div class="l">{period_label}</div></div>
    <div class="stat"><div class="n">{ttm}</div><div class="l">TTM BEV share (Whole)</div></div>
    <div class="stat"><div class="n">{n_variants}</div><div class="l">Variants</div></div>
  </div>

  {notes}

  {sources}

  <h2>How the data flows</h2>
  {flow}

  <h2>Definitions &amp; scope</h2>
  {definitions}

  {variants_table}

  {coverage}

  {matrix}

  {group_note}

  {caveats}

  <div class="footer">
    <p><strong>Freshness.</strong> {freshness}
       Update cadence: {cadence}.<br>
       {model_note}
       Row source string: <code>{csv_source}</code></p>
    {dev_note}
  </div>
</div>
</body>
</html>
"""

INDEX_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Data sources — BEV Trajectories</title>
<meta name="description" content="Where each country's BEV registration data comes from.">
<style>{css}</style>
</head>
<body>
<div class="wrap">
  <a class="back" href="../">← Back to gallery</a>
  <h1>Data sources</h1>
  <p class="lead">Where each country's numbers come from, how they're acquired,
     what they count, and what to be careful about. {n} countries, each tagged by
     acquisition method — API, Scrape, PDF, File or Manual.</p>
  <div class="dir-grid">{cards}</div>
</div>
</body>
</html>
"""


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def load_stubs() -> list[dict]:
    """Brief entries from the stub registry, if the file exists."""
    if not STUBS.exists():
        return []
    data = yaml.safe_load(STUBS.read_text(encoding="utf-8")) or {}
    stubs = data.get("stubs") or []
    return [s for s in stubs if isinstance(s, dict)]


def collect_entries() -> tuple[list[tuple[dict, bool]], list[str]]:
    """Gather (front-matter, is_stub) entries and any validation problems.

    Documented docs win over stubs on a slug clash, so a country can be
    promoted from the registry to a full doc without a manual cleanup step.
    """
    problems: list[str] = []
    entries: list[tuple[dict, bool]] = []
    seen: dict[str, str] = {}  # slug -> where it came from

    def check(fm: dict, where: str):
        missing = [f for f in REQUIRED_FIELDS if not fm.get(f)]
        if missing:
            problems.append(f"{where}: missing {', '.join(missing)}")

    for doc in sorted(DOCS.glob("*-source-*.md")):
        fm = read_front_matter(doc)
        if not fm or not fm.get("slug"):
            continue
        check(fm, doc.name)
        seen[fm["slug"]] = doc.name
        entries.append((fm, False))

    for stub in load_stubs():
        where = f"country_source_stubs.yaml:{stub.get('slug', '?')}"
        check(stub, where)
        slug = stub.get("slug")
        if slug in seen:
            problems.append(
                f"{where}: slug '{slug}' already documented in {seen[slug]} — "
                f"remove the stub")
            continue
        if slug:
            seen[slug] = where
        entries.append((stub, True))

    return entries, problems


def main() -> int:
    check_only = "--check" in sys.argv
    params = load_params()
    entries, problems = collect_entries()

    if problems:
        print("Front-matter / stub problems:", file=sys.stderr)
        for p in problems:
            print(f"  ! {p}", file=sys.stderr)
        return 1
    if not entries:
        print("No entries found (no front-matter, no stubs).", file=sys.stderr)
        return 1
    if check_only:
        print(f"OK — {len(entries)} valid entries.")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    built = []
    for fm, is_stub in entries:
        page = build_page(fm, params, is_stub=is_stub)
        (OUT_DIR / f"{fm['slug']}.html").write_text(page, encoding="utf-8")
        whole = params.get((fm.get("country"), "Whole")) or {}
        # Same rule as the page itself: the directory card shows what we
        # actually hold, falling back to the model's period only if the CSV
        # is missing.
        last_row = latest_csv_row(fm.get("data_file", ""))
        built.append({
            "country": fm.get("country", "Unknown"),
            "slug": fm["slug"],
            "method": fm.get("method", ""),
            "summary": fm.get("summary", ""),
            "latest_period": (last_row or {}).get("period")
                             or whole.get("data_per", "—"),
            "ttm": pct(whole.get("ttm_bev_share")),
            "is_stub": is_stub,
        })

    (OUT_DIR / "index.html").write_text(build_index(built), encoding="utf-8")

    # A country → slug map the gallery loads to add "ⓘ Source" links to each
    # country card. Keyed by the country name so index.html can look it up
    # from a card's (variant-stripped) country label.
    slug_map = {b["country"]: b["slug"] for b in built}
    (OUT_DIR / "sources.json").write_text(
        json.dumps(slug_map, ensure_ascii=False, indent=0, sort_keys=True),
        encoding="utf-8")

    n_full = sum(1 for b in built if not b["is_stub"])
    print(f"  ✓ {len(built)} pages ({n_full} full, {len(built) - n_full} stub) "
          f"+ sources/index.html + sources/sources.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
