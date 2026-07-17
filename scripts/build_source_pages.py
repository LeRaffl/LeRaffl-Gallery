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
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs" / "architecture"
PARAMS = REPO / "params.csv"
OUT_DIR = REPO / "sources"
GH_BLOB = "https://github.com/LeRaffl/LeRaffl-Gallery/blob/master"

STATUS_LABELS = {
    "live": "Live",
    "stale": "Stale",
    "manual": "Manual",
    "planned": "Planned",
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
    path = REPO / data_file
    if not path.exists():
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


def status_chip(status: str) -> str:
    label = STATUS_LABELS.get(status, status or "—")
    return f'<span class="chip chip--{esc(status)}">{esc(label)}</span>'


def gh_link(path: str) -> str:
    if not path:
        return "—"
    return f'<a href="{GH_BLOB}/{esc(path)}"><code>{esc(path)}</code></a>'


# --------------------------------------------------------------------------
# Page building
# --------------------------------------------------------------------------

def build_flow(fm: dict) -> str:
    """A simple top-to-bottom origin → gallery pipeline, per country."""
    src_name = esc(fm.get("source_name", "Source"))
    src_url = fm.get("source_url", "")
    src_html = f'<a href="{esc(src_url)}">{src_name}</a>' if src_url else src_name

    stages = [
        ("Origin", esc(fm.get("underlying", "—"))),
        ("Source / API", src_html),
        ("Fetcher", gh_link(fm.get("fetcher", "")) + (
            f' · {gh_link(fm.get("workflow", ""))}' if fm.get("workflow") else "")),
        ("Store", gh_link(fm.get("data_file", ""))),
        ("Gallery", '<a href="../">BEV Trajectories gallery</a>'),
    ]
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

    hev = fm.get("hev_split")
    row("HEV (full hybrids)",
        "split into its own column" if hev
        else "not split by the source — folds into the combustion totals")

    if fm.get("fcev"):
        row("FCEV", esc(fm["fcev"]))
    if fm.get("backfill") and fm["backfill"] != "none":
        row("Backfill", esc(fm["backfill"]))
    row("Auth", esc(fm.get("auth", "—")))

    return '<table class="defs">' + "".join(rows) + "</table>"


def build_caveats(fm: dict) -> str:
    caveats = fm.get("caveats") or []
    if not caveats:
        return ""
    items = "".join(f"<li>{esc(c)}</li>" for c in caveats)
    return f'<section><h2>Caveats</h2><ul class="caveats">{items}</ul></section>'


def build_page(fm: dict, params: dict) -> str:
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

    return TEMPLATE.format(
        css=BASE_CSS,
        country=esc(country),
        status_chip=status_chip(fm.get("status", "")),
        summary=esc(fm.get("summary", "")),
        latest_period=esc(latest_period),
        ttm=esc(ttm),
        n_variants=len(variants),
        source_link=source_link,
        flow=build_flow(fm),
        definitions=build_definitions(fm),
        caveats=build_caveats(fm),
        csv_period=esc(csv_period),
        csv_source=esc(csv_source),
        cadence=esc(fm.get("cadence", "—")),
        fragility_link=gh_link(fm.get("fragility_doc", "")),
    )


def build_index(pages: list[dict]) -> str:
    cards = []
    for p in sorted(pages, key=lambda x: x["country"]):
        cards.append(
            f'<a class="dir-card" href="{esc(p["slug"])}.html">'
            f'<div class="dir-top">{esc(p["country"])}{status_chip(p["status"])}</div>'
            f'<div class="dir-sub">{esc(p["summary"])}</div>'
            f'<div class="dir-meta">Latest {esc(p["latest_period"])}'
            f' · TTM BEV {esc(p["ttm"])}</div></a>')
    return INDEX_TEMPLATE.format(css=BASE_CSS, cards="".join(cards), n=len(pages))


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
  font-weight:700;letter-spacing:.03em;background:var(--chip-bg);color:var(--accent)}
.chip--live{background:var(--ok-bg);color:var(--ok-tx)}
.chip--stale,.chip--planned{background:var(--warn-bg);color:var(--warn-tx)}
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
  <h1>{country} {status_chip}</h1>
  <p class="lead">{summary}</p>

  <div class="stats">
    <div class="stat"><div class="n">{latest_period}</div><div class="l">Latest month</div></div>
    <div class="stat"><div class="n">{ttm}</div><div class="l">TTM BEV share (Whole)</div></div>
    <div class="stat"><div class="n">{n_variants}</div><div class="l">Variants</div></div>
  </div>

  <h2>Raw source</h2>
  <p>Verify the numbers at the upstream:</p>
  <p>{source_link}</p>

  <h2>How the data flows</h2>
  {flow}

  <h2>Definitions &amp; scope</h2>
  {definitions}

  {caveats}

  <div class="footer">
    <p><strong>Freshness.</strong> Latest period in our store: <code>{csv_period}</code>.
       Cadence: {cadence}.<br>
       Row source string: <code>{csv_source}</code></p>
    <p>Full pipeline notes (for developers): {fragility_link}</p>
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
  <p class="lead">Where each country's numbers come from, what they count, and
     what to be careful about. {n} of ~40 countries documented so far.</p>
  <div class="dir-grid">{cards}</div>
</div>
</body>
</html>
"""


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> int:
    params = load_params()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    built = []
    for doc in sorted(DOCS.glob("*-source-*.md")):
        fm = read_front_matter(doc)
        if not fm or not fm.get("slug"):
            continue
        page = build_page(fm, params)
        (OUT_DIR / f"{fm['slug']}.html").write_text(page, encoding="utf-8")

        whole = params.get((fm.get("country"), "Whole")) or {}
        built.append({
            "country": fm.get("country", "Unknown"),
            "slug": fm["slug"],
            "status": fm.get("status", ""),
            "summary": fm.get("summary", ""),
            "latest_period": whole.get("data_per", "—"),
            "ttm": pct(whole.get("ttm_bev_share")),
        })
        print(f"  ✓ sources/{fm['slug']}.html  ({fm.get('country')})")

    if not built:
        print("No documented countries found (no front-matter).", file=sys.stderr)
        return 1

    (OUT_DIR / "index.html").write_text(build_index(built), encoding="utf-8")
    print(f"  ✓ sources/index.html  ({len(built)} countries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
