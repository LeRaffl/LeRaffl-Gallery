#!/usr/bin/env python3
"""Post-ready snippets of a country brief: one section per image.

The brief (`flyer.py`) and the social card (`social_card.py`) are the two
finished pieces. A thread needs more than two images, and the sections of the
brief are exactly the right ones. This module lays one section out as its own
1080 px wide image: flag, country and data month on top, the section, the
source and the Gallery address below. Nothing is cropped from a rendered page:
every section comes from the same builder functions the brief uses, so a
changed brief changes its snippets, and every figure is the brief's figure.

Roles (what a snippet shows). A role is only offered when the data behind it
exists, the same gates the brief applies:

    mix     verdict + the one number + the mix over time
    shift   who gained, who lost + in numbers
    brands  top brands (only where `market/<slug>_top.json` exists)
    share   box plot: BEV share, last 12 months, against all countries
    year50  box plot: year the fitted curve reaches 50 %
    year80  box plot: year the fitted curve reaches 80 %

Not here on purpose: the fitted curve itself (`curve`). It joins when the
Gallery has a version of it that stands alone.

Rendering to PNG is `export_post_kit.py`; this module only builds HTML.
"""
from __future__ import annotations

import re

import flyer
import market_structure as mstr
import model_card as mc
import social_card
from model_card import esc

W = 1080
PAD = 48
# The brief is laid out for 702 px of content. A snippet shows the same
# markup larger, so the smallest brief text (11.5 px) is about 18 px on a
# 1080 px image, which stays readable when a phone shows it 390 pt wide.
ZOOM = 1.6
INNER = round((W - 2 * PAD) / ZOOM)

ROLES = ("mix", "shift", "brands", "share", "year50", "year80")

LABEL = {
    "mix": "mix over time",
    "shift": "who gained, who lost",
    "brands": "top brands",
    "share": "BEV share against all countries",
    "year50": "year the curve reaches 50 %",
    "year80": "year the curve reaches 80 %",
}


def _strip(ctx: dict, role: str) -> dict | None:
    """The one box-plot strip a rank role shows, or None."""
    country, slug = ctx["country"], ctx["slug"]
    want = {"share": "share", "year50": "year", "year80": "year"}[role]
    y50 = role == "year50"
    y80 = role == "year80"
    strips, _, _ = flyer.compare_strips(
        country, ctx["peers"], ctx["highlights"], slug, False,
        (ctx["figures"].get("ttm") or {}).get("share"),
        peer_years=ctx["peer_years"] if y50 else None,
        own_year=flyer.year_at_50(ctx["state"]) if y50 else None,
        peer_years_80=ctx["peer_years_80"] if y80 else None,
        own_year_80=flyer.year_at_80(ctx["state"]) if y80 else None,
        own_ci=flyer.year_ci(ctx["state"], 0.5) if y50 else None,
        own_ci_80=flyer.year_ci(ctx["state"], 0.8) if y80 else None)
    # A year strip alone keeps its own year axis (the shared axis only
    # exists when both year strips are drawn together).
    return next((s for s in strips if s.get("kind") == want), None)


def _rank_section(ctx: dict, role: str) -> str:
    m = _strip(ctx, role)
    if not m:
        return ""
    n = m["stats"]["n"]
    if role == "share":
        sub = f"Box = middle half of the {n} countries in the Gallery."
    else:
        sub = (f"Box = middle half of the {n} countries in the Gallery with a fitted curve. "
               "The years come from the project's model, not from a forecast.")
    strip = flyer._box_strip(m, INNER - flyer.CMP_LABEL_W, k=1.12)
    return ('<section class="fl-sec fl-cmp"><h2>How it compares</h2>'
            f'<p class="fl-sub">{sub}</p>'
            f'<div class="fl-cmp-strips">{strip}</div></section>')


def section(ctx: dict, role: str) -> str:
    """The HTML of one role, or '' when the data does not support it."""
    figures, rows, fm = ctx["figures"], ctx["rows"], ctx["fm"]
    if role == "mix":
        if not figures.get("ttm"):
            return ""
        head, follow = flyer.verdict(ctx["country"], figures, ctx["shift"])
        points = flyer.mix_points(rows)
        mix_h = flyer.hero_chart_heights(figures, rows, 0, False)[0] + 90
        mix = flyer.build_mix(points, fm.get("hev_split") is True, INNER, mix_h)
        if not mix:
            return ""
        return (f'<p class="fl-head">{esc(head)}</p><p class="fl-follow">{esc(follow)}</p>'
                f'<div class="fl-hero">{flyer.hero_number(figures, rows)}'
                f'<div class="fh-mix">{mix}</div></div>')
    if role == "shift":
        bars = flyer.bars_section(ctx["shift"], fm)
        if not bars:
            return ""
        facts = flyer.facts_section(fm, figures, ctx["shift"])
        two, _ = flyer.two_block(fm, bars, facts, "")
        n = facts.count('class="ff"')
        return two.replace('class="fl-facts"', f'class="fl-facts fl-n{n}"') if n else two
    if role == "brands":
        return mstr.build_block(ctx["market"], ctx["brand_mode"], ctx["logo_href"]) if ctx["market"] else ""
    if role in ("share", "year50", "year80"):
        return _rank_section(ctx, role)
    raise ValueError(f"unknown role {role!r}")


def available(ctx: dict) -> list[str]:
    """Roles this country can fill, in thread order."""
    return [r for r in ROLES if section(ctx, r)]


def scope_line(text: str, limit: int = 260) -> str:
    """The scope note as whole sentences up to `limit` characters. The first
    sentence is the scope itself, so it is always kept; if it alone is too
    long it is cut at a word, as the brief does."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    kept = ""
    for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z(])", text):
        nxt = f"{kept} {sentence}".strip()
        if len(nxt) > limit:
            break
        kept = nxt
    return kept or flyer._clip(text, limit)


def _source_lines(ctx: dict, role: str) -> tuple[str, str]:
    fm, market = ctx["fm"], ctx["market"]
    source = (fm.get("source_name") or "").split("—")[0].strip()
    brand_src = mstr.brand_source(fm, market)
    if role == "brands" and brand_src:
        src = f"Brands: {brand_src}"
    elif brand_src and role == "mix":
        src = f"Source: {source}"
    else:
        src = f"Source: {source}"
    scope = scope_line(mc.footnote(ctx["country"]) or fm.get("scope_note") or "")
    return src, scope


def build_page(ctx: dict, role: str, theme_href: str) -> str:
    """The full HTML page for one snippet, or '' when the role is empty."""
    body = section(ctx, role)
    if not body:
        return ""
    fm, rows = ctx["fm"], ctx["rows"]
    country, slug = ctx["country"], ctx["slug"]
    through = mc.period_label(rows[-1]["period"], long=True) if rows else ""
    flag = mc.flag_img(slug, country, cls="sc-flag") or fm.get("mark_html") or ""
    brief_url = f"{mc.SITE}/sources/flyer/{slug}.html"
    qr = f'<div class="sc-qr">{flyer.build_qr(brief_url, size=96)}</div>'
    src, scope = _source_lines(ctx, role)
    cov = f'<div class="sc-cov">{esc(scope)}</div>' if scope else ""
    url = mc.SITE.replace("https://", "")
    gen = mc.generated_line(rows[-1]["period"] if rows else "")
    return f"""<!doctype html>
<html lang="en" data-theme="light" data-role="{esc(role)}"><head><meta charset="utf-8">
<title>{esc(country)} · {esc(LABEL[role])}</title>
<link rel="stylesheet" href="{esc(theme_href)}">
<style>{mstr.CSS}{flyer.FLYER_CSS}{social_card.CSS}{CSS}</style></head>
<body><div class="kit" id="kit">
  <header class="sc-top">{flag}<div class="sc-name"><h1>{esc(country)}</h1>
    <div class="sc-thr">through {esc(through)}</div></div>{qr}</header>
  <main class="kit-body"><div class="kit-zoom">{body}</div></main>
  <footer class="sc-foot"><div class="sc-foot-row"><div>{esc(src)}</div>
    <div><b>{esc(url)}</b> · @LeRaffl</div></div>{cov}
    <div class="sc-gen">BEV Trajectory Gallery · charts and text CC BY 4.0 · {esc(gen)}</div></footer>
</div>
<script>
// The exporter reads the height from here and sizes the screenshot to it.
(function(){{
  function mark(){{document.documentElement.dataset.h=Math.ceil(document.getElementById('kit').getBoundingClientRect().height);}}
  mark();
  if(document.fonts&&document.fonts.ready)document.fonts.ready.then(mark);
}})();
</script>
</body></html>"""


CSS = f"""
html,body{{margin:0;background:#fdfdfc}}
.kit{{width:{W}px;box-sizing:border-box;padding:{PAD}px {PAD}px 34px;background:#fdfdfc;color:#1a1a18;
  font-family:var(--font-ui),sans-serif;color-scheme:light;
  --text:#1a1a18;--muted:#55534c;--line:#dcd9d2}}
.kit *{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
.kit .sc-top{{height:96px}}
.kit .sc-qr{{width:96px;height:96px}}
.kit-body{{padding:22px 0 26px}}
.kit-zoom{{width:{INNER}px;zoom:{ZOOM}}}
.kit-zoom > section:first-child,.kit-zoom > .fl-sec:first-child{{margin-top:0}}
.kit .sc-foot{{margin-top:0}}
/* the brief's hero and who-gained are side by side on A4; a phone image
   stacks them so the number can be as large as the chart is wide */
.kit .fl-head{{margin-top:0}}
.kit .fl-hero{{flex-direction:column;gap:6px;margin-top:14px}}
.kit .fh-num{{width:auto}}
.kit .fh-mix{{width:100%}}
.kit .fl-two{{grid-template-columns:1fr;row-gap:12px}}
.kit .fl-two .fl-facts,.kit .fl-one .fl-facts{{grid-template-columns:repeat(2,1fr);column-gap:18px}}
.kit .fl-facts.fl-n3{{grid-template-columns:repeat(3,1fr)}}
.kit .fl-two .fb-row,.kit .fl-two .fb-head{{grid-template-columns:130px 1fr 44px 92px;column-gap:6px}}
"""
