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
# Small rendering helpers
# --------------------------------------------------------------------------

def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def pct(value) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


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


def build_definitions(fm: dict) -> str:
    rows = []

    def row(label, value_html):
        rows.append(f"<tr><th>{esc(label)}</th><td>{value_html}</td></tr>")

    method = fm.get("method")
    if method:
        row("Acquisition",
            f'{esc(METHOD_LABELS.get(method, method))} — {esc(METHOD_DESC.get(method, ""))}')

    variants = fm.get("variants") or []
    row("Variants", ", ".join(esc(v) for v in variants) or "—")

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


def build_page(fm: dict, params: dict, is_stub: bool = False) -> str:
    country = fm.get("country", "Unknown")
    whole = params.get((country, "Whole")) or {}
    latest_period = whole.get("data_per", "—")
    ttm = pct(whole.get("ttm_bev_share"))
    variants = fm.get("variants") or []

    last_row = latest_csv_row(fm.get("data_file", ""))
    csv_period = last_row.get("period") if last_row else latest_period
    csv_source = last_row.get("source") if last_row else fm.get("source_name", "")

    src_url = fm.get("source_url", "")
    source_link = (
        f'<a class="source-btn" href="{esc(src_url)}">'
        f'{esc(fm.get("source_name", "source"))} ↗</a>' if src_url
        else esc(fm.get("source_name", "—")))

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

    return TEMPLATE.format(
        css=BASE_CSS,
        country=esc(country),
        method_chip=method_chip(fm.get("method", "")),
        banner=banner,
        summary=esc(fm.get("summary", "")),
        latest_period=esc(latest_period),
        ttm=esc(ttm),
        n_variants=len(variants),
        source_link=source_link,
        notes=build_notes(fm),
        flow=build_flow(fm),
        definitions=build_definitions(fm),
        group_note=build_group_note(fm),
        caveats=build_caveats(fm),
        csv_period=esc(csv_period),
        csv_source=esc(csv_source) or "—",
        cadence=esc(fm.get("cadence") or "—"),
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
    <div class="stat"><div class="n">{latest_period}</div><div class="l">Latest month</div></div>
    <div class="stat"><div class="n">{ttm}</div><div class="l">TTM BEV share (Whole)</div></div>
    <div class="stat"><div class="n">{n_variants}</div><div class="l">Variants</div></div>
  </div>

  {notes}

  <h2>Raw source</h2>
  <p>Verify the numbers at the upstream:</p>
  <p>{source_link}</p>

  <h2>How the data flows</h2>
  {flow}

  <h2>Definitions &amp; scope</h2>
  {definitions}

  {group_note}

  {caveats}

  <div class="footer">
    <p><strong>Freshness.</strong> Latest period in our store: <code>{csv_period}</code>.
       Cadence: {cadence}.<br>
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
        built.append({
            "country": fm.get("country", "Unknown"),
            "slug": fm["slug"],
            "method": fm.get("method", ""),
            "summary": fm.get("summary", ""),
            "latest_period": whole.get("data_per", "—"),
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
