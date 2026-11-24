"""A 1080 x 1350 social card per country and region.

Same figures as the brief and the source page: the 12-month BEV share only
from a full window ending at the latest period (model_card.key_figures), the
S-curve only when the fit passes the reliability gate (model_state
"quotable"), its band only when the band passes too, and the market block
only from a full 12-month BEV brand table (market_structure.load).
"""
from __future__ import annotations

import math
import re

import flyer
import locator_map
import market_structure as mstr
import model_card as mc
from model_card import esc

W, H = 1080, 1350
PAD_X = 60
INNER = W - 2 * PAD_X


def x_range(rows: list[dict], state: dict | None) -> tuple[float, float]:
    """From the first year with a 1 % month (2018 at the latest), at least six
    years before the data end; to the year the fit reaches 90 % when a curve
    is drawn, else about two years after the data."""
    last = mc.month_index(rows[-1]["period"]) / 12
    first = mc.month_index(rows[0]["period"]) // 12
    one = mc.first_year_over(rows, 1.0)
    start = min(one if one is not None else 2018, 2018)
    start = max(first, min(start, math.floor(last) - 6))
    end = math.ceil(last + 2)
    if state and state["quotable"]:
        reach = mc.fit_year(0.9, state["v1"], state["v2"], state["t0"])
        if math.isfinite(reach):
            cap = math.ceil(last + mc.CURVE_HORIZON_YEARS)
            end = max(math.ceil(last + 2), min(cap, math.ceil(reach)))
    return float(start), float(end)


def build_social(fm: dict, rows: list[dict], figures: dict, state: dict | None,
                 bands: dict | None, market: dict | None, mode: str,
                 theme_href: str, logo_href: str,
                 peers: list[tuple[str, float]] | None = None,
                 highlights: list[dict] | None = None,
                 weak_curve: bool = False) -> str:
    country = fm.get("country", "")
    slug = fm.get("slug", "")
    through = mc.period_label(rows[-1]["period"], long=True) if rows else ""
    flag = mc.flag_img(slug, country, cls="sc-flag") or fm.get("mark_html") or ""
    brief_url = f"{mc.SITE}/sources/flyer/{slug}.html"
    qr = f'<div class="sc-qr">{flyer.build_qr(brief_url, size=118)}</div>'
    where = locator_map.build(fm.get("map_countries") or [country], 118,
                              label=f"Where {country} is" if not fm.get("region")
                              else f"{country}: member countries")
    if where:
        qr = f'<div class="sc-loc">{where}</div>' + qr

    ttm = figures.get("ttm")
    latest, rng = figures.get("latest"), mc.share_range(rows)
    hero = ""
    if ttm:
        delta = ""
        if ttm["delta"] is not None:
            cls = "up" if ttm["delta"] >= 0.05 else "down" if ttm["delta"] <= -0.05 else "flat"
            delta = (f'<div class="sc-delta {cls}">{esc(mc.points(ttm["delta"]))} pts · '
                     f'last 12 months</div>')
        glance = []
        if latest:
            glance.append(f'<span class="sc-alone">Single month · {esc(mc.period_label(latest["row"]["period"]))}: '
                          f'<b>{esc(mc.share(latest["share"]))}</b></span>')
        if rng:
            glance.append(f'<span class="sc-range">{esc(mc.range_sentence(rng, short=True))}</span>')
        if fm.get("acea_social"):
            glance.append(fm["acea_social"])
        extra = f'<div class="sc-glance">{"".join(glance)}</div>' if glance else ""
        big = mc.share(ttm["share"]).removesuffix("%")
        hero = (f'<div class="sc-hero"><div class="sc-big">{esc(big)}<span>%</span></div>'
                f'<div class="sc-hcol"><div class="sc-kick">of new cars are battery electric</div>'
                f'<div class="sc-what">12 months to {esc(mc.period_label(ttm["end"], long=True))}'
                f'</div>{delta}{extra}</div></div>')

    market_html, market_h = "", 0
    if fm.get("carriers_social"):
        html, h = fm["carriers_social"]
        market_html = html
        market_h = h
    elif market:
        info: dict = {}
        bar = mstr.build_bar(market, mode, logo_href, width=INNER, base=30, fs=20, row_h=28,
                             gap=3, info=info)
        model = ""
        if market["model"]:
            model = (f'<p class="sc-model">Best-selling model: <b>{esc(market["model"]["name"])}</b>, '
                     f'{esc(mstr._pct(market["model"]["share"]))} of battery-electric cars.</p>')
        market_html = (
            f'<div class="sc-ms"><div class="sc-mshead">Top brands '
            f'<span>· battery-electric registrations, last 12 months, '
            f'of {esc(mc.units(market["units"]))} cars.</span></div>'
            f'<p class="sc-msline"><span class="ms-kind ms-{market["kind"]}">'
            f'{esc(mstr.LABEL[market["kind"]])}</span>{esc(mstr.sentence(market))}'
            f'{esc(mstr.gap_note(market, where="in the brief"))}</p>'
            f'{bar}{model}</div>')
        # heading + sentence + ranked list + model line. Fewer named rows
        # shrink this, and the chart below grows into the space.
        market_h = 14 + 28 + 36 + int(round(info.get("height") or 80)) + (32 if model else 0)

    # Chart fills what is left: 1350 minus padding, header, hero, note,
    # market block and footer (measured from the rendered card).
    # padding + header + compact hero (with glance) + legend + footer
    fixed = 52 + 40 + 98 + 190 + 28 + 50 + 76   # hero 98: one-line range (range_sentence short)
    if fm.get("coverage_note"):
        # Region cards name their coverage in the footer: two lines there.
        fixed += 30
    if fm.get("acea_social") and ttm:
        fixed += 26   # ACEA's EU HEV line in the glance (EU card)
    # One box-plot strip, as on the A4 brief: BEV share, last 12 months.
    cmp_html, cmp_h = "", 0
    if peers:
        if highlights is None:
            try:
                import region_card as _rc
                highlights = _rc.reference_points()
            except Exception:
                highlights = []
        cmp_html, cmp_h = flyer.build_compare_social(
            country, peers, highlights, slug, is_region=bool(fm.get("region")),
            own_share=ttm.get("share") if ttm else None, width=INNER)
    chart_h = int(max(300, H - fixed - market_h - cmp_h - 8))
    curve = ""
    if fm.get("region_curve"):
        svg, legend = fm["region_curve"](INNER, chart_h, 58)
        if svg:
            curve = f'<div class="sc-curve">{svg}{legend or ""}</div>'
    elif state:
        rng = x_range(rows, state)
        svg = mc.build_curve_svg(rows, state, bands, width=INNER, height=chart_h,
                                 weak_fit=weak_curve and not state["quotable"], x_range=rng, left=58,
                                 zoom_weak=True)
        if svg:
            curve = f'<div class="sc-curve">{svg}{mc.chart_legend(state, weak=weak_curve)}</div>'

    source = (fm.get("source_name") or "").split("—")[0].strip()
    brand_src = mstr.brand_source(fm, market)
    short = re.sub(r"\s*\(.*?\)", "", source)
    src = f"Share: {short} · Brands: {brand_src}" if brand_src else f"Source: {source}"
    cov = ""
    if fm.get("coverage_note"):
        # Its own line: appended to the source it wrapped onto three lines.
        cov = f'<div class="sc-cov">{esc(fm["coverage_note"])}</div>'
    url = mc.SITE.replace("https://", "")
    end = rows[-1]["period"] if rows else ""
    gen = mc.generated_line(end)
    return f"""<!doctype html>
<html lang="en" data-theme="light"><head><meta charset="utf-8">
<title>{esc(country)} social card</title>
<link rel="stylesheet" href="{esc(theme_href)}">
<style>{mstr.CSS}{CSS}</style></head>
<body><div class="sc">
  <header class="sc-top">{flag}<div class="sc-name"><h1>{esc(country)}</h1>
    <div class="sc-thr">through {esc(through)}</div></div>{qr}</header>
  {hero}{curve}{cmp_html}{market_html}
  <footer class="sc-foot"><div class="sc-foot-row"><div>{esc(src)}</div>
    <div><b>{esc(url)}</b> · @LeRaffl</div></div>{cov}
    <div class="sc-gen">{esc(gen)}</div></footer>
</div></body></html>"""


CSS = """
html,body{margin:0;background:#fdfdfc}
.sc{width:1080px;height:1350px;box-sizing:border-box;padding:52px 60px 40px;display:flex;
  flex-direction:column;color:#1a1a18;font-family:var(--font-ui),sans-serif;background:#fdfdfc;
  color-scheme:light;overflow:hidden}
.sc-top,.sc-hero,.sc-ms,.sc-foot{flex-shrink:0}
.sc-top{display:flex;align-items:center;gap:22px;padding-bottom:14px;border-bottom:3px solid #1a1a18;
  height:122px;box-sizing:content-box}
.sc-flag,.sc-mark{width:90px;height:60px;object-fit:cover;border-radius:3px;box-shadow:0 0 0 1px #dcd9d2;display:block}
.sc-mark{background:#eceae4}
.sc-name{flex:1;min-width:0}
.sc-top h1{font-family:var(--font-display);font-size:60px;line-height:1;margin:0;font-weight:600}
.sc-thr{font-size:22px;color:#55534c;margin-top:6px}
.sc-qr{flex:none;width:118px;height:118px}
.sc-loc{flex:none;line-height:0}.sc-loc svg{display:block}
.sc-qr svg{display:block}
.sc-hero{margin-top:14px;display:flex;align-items:center;gap:22px;min-height:96px}
.sc-big{font-family:var(--font-display);font-size:104px;line-height:.9;font-weight:600;color:#2c7a50;
  letter-spacing:-.02em;font-variant-numeric:tabular-nums;flex:none}
.sc-big span{font-size:50px;margin-left:4px;letter-spacing:0}
.sc-hcol{flex:1;min-width:0;display:grid;grid-template-columns:1fr auto;column-gap:16px;align-items:center}
.sc-kick{font-size:25px;color:#1a1a18;line-height:1.2;font-weight:600;letter-spacing:-.01em;
  grid-column:1}
.sc-what{font-size:18px;color:#55534c;margin-top:4px;grid-column:1}
.sc-delta{grid-column:2;grid-row:1/3;padding:8px 14px;border-radius:999px;font-size:19px;font-weight:700;
  white-space:nowrap}
.sc-delta.up{background:#dcefe4;color:#1f6a43}.sc-delta.down{background:#f6e0dc;color:#9a3324}
.sc-delta.flat{background:#eceae4;color:#55534c}
.sc-glance{grid-column:1/-1;display:flex;align-items:flex-start;flex-wrap:wrap;gap:4px 16px;margin-top:6px;
  font-size:18px;color:#3a3935;line-height:1.4}
.sc-alone b{font-weight:600;color:#3a3935;font-variant-numeric:tabular-nums}
.sc-range{flex:1 1 100%;font-size:17px;color:#55534c;line-height:1.4}
.sc-acea{flex:1 1 100%;font-size:17px;color:#55534c;line-height:1.4}
.sc-acea b{color:#1a1a18;font-weight:700}
.sc .acea-chip{display:inline-block;padding:0 9px;margin-right:6px;border-radius:999px;background:#eceae4;
  color:#3a3935;font-size:15px;font-weight:700;letter-spacing:.02em}
.sc .acea-stale{color:#9a3324;font-weight:700}
.sc .wc-flag{width:32px;height:21px;max-height:21px;object-fit:cover;border-radius:1px;
  box-shadow:0 0 0 1px #dcd9d2;flex:none}
.sc .wc-list{--ms-logo:36px;--ms-name:180px;--ms-pct:72px;--ms-row:26px}
.sc .wc-head,.sc .wc-row{display:grid;
  grid-template-columns:calc(var(--ms-logo) + 8px + var(--ms-name)) 72px minmax(0,1fr) var(--ms-pct);
  column-gap:12px;align-items:center}
.sc .wc-head{align-items:end;font-size:13px;line-height:1.2;color:#55534c;font-weight:600;
  text-align:right;margin-bottom:6px;height:auto}
.sc .wc-row{height:var(--ms-row);font-size:20px}
.sc .wc-list .wc-row + .wc-row{margin-top:4px}
.sc .wc-bev{text-align:right;font-variant-numeric:tabular-nums;color:#55534c;font-size:18px}
.sc-curve{margin-top:12px;flex-shrink:0}
.sc-cmp{margin-top:14px;flex-shrink:0}
.sc-bx{display:grid;grid-template-columns:300px 1fr;align-items:end}
.sc-bx-l{display:flex;flex-direction:column;font-size:17px;line-height:1.3;color:#77746c;
  padding-bottom:20px}
.sc-bx-l b{color:#1a1a18;font-size:18px}
.sc-bx-own{color:#2c7a50;font-weight:600}
.sc-bx-own b{color:#2c7a50}
.sc-svg text.ax{fill:#77746c;font-size:16px;font-family:var(--font-ui),sans-serif}
.sc-curve .curve{width:960px;display:block;height:auto}
.sc-curve .curve text{font-size:16px;fill:#77746c;font-family:var(--font-ui),sans-serif}
.cv-grid{stroke:#e4e2dd;stroke-width:1}.cv-ci{fill:#3d9a68;fill-opacity:.2}
.cv-fit{fill:none;stroke:#2c7a50;stroke-width:3.2}.cv-weak{stroke-dasharray:9 7;stroke:#8d897c}.cv-pt{fill:#55534c;fill-opacity:.55}
.cv-est{fill:none;stroke:#55534c}.cv-now{stroke:#8d897c;stroke-width:1;stroke-dasharray:2 3}
.cv-step{fill:none;stroke:#3a3935;stroke-width:2.4}.cv-rise{fill:none;stroke:#3a3935;stroke-width:1}
.cv-step-est{stroke-dasharray:4 3}
.cv-ttm{fill:none;stroke:#154a30;stroke-width:3.6;stroke-linejoin:round}
.cv-pt-bg{fill-opacity:.18}
.sc .cv-leg{display:flex;flex-wrap:wrap;align-items:center;gap:6px 16px;margin:6px 0 0 58px;
  font-size:16px;color:#55534c}
.sc .cv-leg-i{display:inline-flex;align-items:center;gap:6px;white-space:nowrap}
.sc .cv-g{display:block;flex:none}
.sc .cv-leg-note{color:#77746c;font-style:italic}
.sc-ms{margin-top:14px}
.sc-mshead{font-size:21px;font-weight:700;margin-bottom:6px}
.sc-mshead span{font-weight:400;color:#55534c;font-size:18px}
.sc-msline{font-family:var(--font-display);font-size:26px;line-height:1.28;margin:0 0 8px}
.sc .ms-kind{font-size:16px;padding:4px 12px;vertical-align:4px}
.sc .ms-row{column-gap:16px}
.sc .ms-id{column-gap:10px}
.sc .ms-name{font-size:20px}
.sc .ms-val{font-size:22px}
.sc .ms-track{border-radius:4px}
.sc .ms-fill{border-radius:4px}
.sc-model{font-size:20px;margin:8px 0 0;color:#3a3935}
.sc-foot{margin-top:auto;padding-top:14px;border-top:3px solid #1a1a18;display:flex;
  flex-direction:column;gap:6px;font-size:18px;color:#55534c}
.sc-foot-row{display:flex;justify-content:space-between;gap:20px}
.sc-foot-row>div:last-child{flex:none;white-space:nowrap}
.sc-foot b{color:#1a1a18}
.sc-cov{font-size:17px;line-height:1.3}
.sc-gen{font-size:15px;color:#77746c}
"""
