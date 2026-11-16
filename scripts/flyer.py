#!/usr/bin/env python3
"""The one-page country flyer, `sources/flyer/<slug>.html`.

The source page documents a series for people who want to check it. The
flyer is for a reader who wants to know, at a glance, how far a country is
on the way to battery-electric cars: one A4 sheet, a verdict in plain words,
the mix over time, who gained and who lost, and where the fitted curve
points. No pipeline detail; that stays on the source page it links to.

Built by `build_source_pages.py` from the same computed figures as the
source page (`model_card.py`), so the two cannot disagree. The sheet has a
fixed A4 size: what the screen shows is what prints.
"""

from __future__ import annotations

import math

import model_card as mc
from model_card import esc

SHEET_W, SHEET_H = 794, 1123          # A4 at 96 dpi
INNER_W = SHEET_W - 2 * 46

# Bottom to top in the mix chart.
MIX_ORDER = (
    ("REST", "Combustion"),
    ("HEV", "Hybrid"),
    ("PHEV", "Plug-in hybrid"),
    ("BEV", "Battery electric"),
)


# --------------------------------------------------------------------------
# The verdict
# --------------------------------------------------------------------------

def one_in(share: float) -> str:
    """'about 1 in 4' for a share in percent."""
    n = round(100 / share)
    return f"about 1 in {n}"


def verdict(country: str, figures: dict, shift: dict | None) -> tuple[str, str]:
    """(headline, follow-up sentence) from the 12-month BEV share and its change."""
    ttm = figures.get("ttm")
    if not ttm:
        return f"{country}: new registrations by powertrain", ""
    s, d = ttm["share"], ttm["delta"]
    if s < 1:
        head = "Fewer than 1 in 100 new cars is battery electric."
    elif s < 45:
        head = f"{one_in(s).capitalize()} new cars is battery electric."
        if round(100 / s) == 2:
            head = "Nearly half of new cars are battery electric."
    elif s < 55:
        head = "About half of new cars are battery electric."
    elif s < 80:
        head = f"Most new cars are battery electric: {s:.0f} in 100."
    else:
        head = f"Almost every new car is battery electric: {s:.0f} in 100."

    if d is None:
        return head, ""
    if d >= 5:
        move = f"The share is rising fast: up {d:.1f} points in a year."
    elif d >= 1:
        move = f"The share is rising: up {d:.1f} points in a year."
    elif d > -1:
        move = "The share has barely moved in a year."
    else:
        move = f"The share fell by {-d:.1f} points in a year."
    where = ""
    if shift:
        others = [r for r in shift["rows"] if r["key"] != "BEV"]
        if d >= 1 and others:
            loser = min(others, key=lambda r: r["delta"])
            if loser["delta"] <= -1:
                where = (f" {loser['label']} lost the most: "
                         f"{-loser['delta']:.1f} points.")
        elif d <= -1 and others:
            winner = max(others, key=lambda r: r["delta"])
            if winner["delta"] >= 1:
                where = (f" {winner['label']} gained the most: "
                         f"{winner['delta']:.1f} points.")
        elif others:
            winner = max(others, key=lambda r: r["delta"])
            if winner["delta"] >= 1:
                where = (f" {winner['label']} gained the most: "
                         f"{winner['delta']:.1f} points.")
    return head, move + where


# --------------------------------------------------------------------------
# Mix over time
# --------------------------------------------------------------------------

def mix_points(rows: list[dict], years: int = 10) -> list[dict]:
    """Trailing-window shares at every period whose window is complete.

    BEV is always there. Plug-ins and hybrids are their own band only where
    the window fills them; otherwise they are inside the rest at that point.
    """
    if not rows:
        return []
    interval = mc.interval_of(rows[-1])
    size, step = {"monthly": (12, 1), "quarterly": (4, 3)}.get(interval, (0, 0))
    if not size:
        return []
    out = []
    for i in range(size - 1, len(rows)):
        window = rows[i - size + 1:i + 1]
        if any(mc.interval_of(r) != interval for r in window):
            continue
        idx = [mc.month_index(r["period"]) for r in window]
        if None in idx or any(b - a != step for a, b in zip(idx, idx[1:])):
            continue
        total, bev = mc._full_sum(window, "TOTAL"), mc._full_sum(window, "BEV")
        if not total or bev is None:
            continue
        point = {"t": idx[-1] / 12, "period": window[-1]["period"],
                 "BEV": 100 * bev / total, "PHEV": None, "HEV": None}
        phev = mc._full_sum(window, "PHEV")
        if phev is not None:
            if not mc._used(window, "EREV"):
                point["PHEV"] = 100 * phev / total
            elif mc._full_sum(window, "EREV") is not None:
                point["PHEV"] = 100 * (phev + mc._full_sum(window, "EREV")) / total
        hev = mc._full_sum(window, "HEV")
        if hev is not None:
            point["HEV"] = 100 * hev / total
        point["REST"] = max(0.0, 100 - point["BEV"] - (point["PHEV"] or 0) - (point["HEV"] or 0))
        out.append(point)
    if len(out) < 13:
        return []
    last = out[-1]["t"]
    return [p for p in out if p["t"] >= last - years]


def build_mix(points: list[dict], hev_full: bool, width: int, height: int) -> str:
    if not points:
        return ""
    left, right, top, bottom = 26, 150, 8, 22
    plot_w, plot_h = width - left - right, height - top - bottom
    t0, t1 = points[0]["t"], points[-1]["t"]

    def x_of(t: float) -> float:
        return left + plot_w * (t - t0) / ((t1 - t0) or 1)

    def y_of(v: float) -> float:
        return top + plot_h * (1 - max(0.0, min(100.0, v)) / 100)

    parts = []
    base = [0.0] * len(points)
    labels = []
    end = points[-1]
    names = dict(MIX_ORDER)
    names["HEV"] = "Full hybrid" if hev_full else "Hybrid"
    if end["HEV"] is None:
        names["REST"] = "Combustion incl. hybrids"
    for key, _ in MIX_ORDER:
        values = [p[key] or 0.0 for p in points]
        if not any(values):
            continue
        upper = [b + v for b, v in zip(base, values)]
        path = [f"M{x_of(points[0]['t']):.1f},{y_of(upper[0]):.1f}"]
        path += [f"L{x_of(p['t']):.1f},{y_of(u):.1f}" for p, u in zip(points[1:], upper[1:])]
        path += [f"L{x_of(p['t']):.1f},{y_of(b):.1f}" for p, b in zip(reversed(points), reversed(base))]
        parts.append(f'<path d="{" ".join(path)} Z" fill="{mc.COLORS[key]}"/>')
        if end[key] and (end[key] >= 0.5 or key == "BEV"):
            labels.append([y_of(base[-1] + values[-1] / 2), key, names[key], end[key]])
        base = upper
    for mark in (0, 50, 100):
        y = y_of(mark)
        parts.append(f'<text x="{left - 5}" y="{y + 3.5:.1f}" text-anchor="end" class="ax">{mark}</text>')
    parts.append(f'<line x1="{left}" y1="{y_of(50):.1f}" x2="{left + plot_w}" '
                 f'y2="{y_of(50):.1f}" stroke="#fff" stroke-opacity=".6"/>')
    year = math.ceil(t0)
    span = t1 - t0
    step = 1 if span <= 6 else 2
    while year <= t1:
        if x_of(year) - left > 12 or year == t0:
            parts.append(f'<text x="{x_of(year):.1f}" y="{height - 6}" text-anchor="middle" '
                         f'class="ax">{year}</text>')
        year += step
    # Direct labels at the right edge, pushed apart so they never overlap.
    labels.sort()
    gap = 15
    for i in range(1, len(labels)):
        labels[i][0] = max(labels[i][0], labels[i - 1][0] + gap)
    over = labels[-1][0] - (top + plot_h - 2) if labels else 0
    if over > 0:
        labels[-1][0] -= over
        for i in range(len(labels) - 2, -1, -1):
            labels[i][0] = min(labels[i][0], labels[i + 1][0] - gap)
    for y, key, name, value in labels:
        x = left + plot_w + 8
        parts.append(f'<rect x="{x}" y="{y - 5:.1f}" width="8" height="8" fill="{mc.COLORS[key]}"/>')
        bold = ' class="strong"' if key == "BEV" else ""
        parts.append(f'<text x="{x + 13}" y="{y + 3:.1f}"{bold}>{esc(name)} '
                     f'{mc.share(value).replace(" %", "%")}</text>')
    label = (f"Share of new registrations by powertrain, trailing twelve months, "
             f"through {mc.period_label(end['period'])}.")
    return (f'<svg class="fl-svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
            f'role="img" aria-label="{esc(label)}">{"".join(parts)}</svg>')


# --------------------------------------------------------------------------
# Blocks
# --------------------------------------------------------------------------

def build_bars(shift: dict, limit: int = 6) -> str:
    rows = shift["rows"]
    if len(rows) > limit:
        # Keep the ones that moved most; BEV always stays.
        keep = sorted(rows, key=lambda r: (r["key"] != "BEV", -abs(r["delta"])))[:limit]
        rows = [r for r in rows if r in keep]
    neg = max([-r["delta"] for r in rows] + [0.0])
    pos = max([r["delta"] for r in rows] + [0.0])
    zero = min(74.0, max(26.0, 100 * neg / ((neg + pos) or 1)))
    scale = min(zero / neg if neg else 1e9, (100 - zero) / pos if pos else 1e9)
    out = []
    for row in rows:
        width = abs(row["delta"]) * scale
        left = zero if row["delta"] >= 0 else zero - width
        out.append(
            f'<div class="fb-row"><span class="fb-name">{esc(row["label"])}</span>'
            f'<span class="fb-track"><i class="fb-zero" style="left:{zero:.2f}%"></i>'
            f'<i class="fb-bar" style="left:{left:.2f}%;width:{width:.2f}%;'
            f'background:{mc.COLORS.get(row["key"], mc.COLORS["REST"])}"></i></span>'
            f'<span class="fb-pp">{mc.points(row["delta"])}</span>'
            f'<span class="fb-now">{mc.share(row["after"])}</span></div>')
    return "".join(out)


def build_miles(state: dict) -> str:
    idx = mc.month_index(state["data_per"])
    today = idx / 12 if idx is not None else math.inf
    rows = []
    for c in state["crossings"]:
        if c["level"] not in (0.2, 0.5, 0.8, 0.9) or not math.isfinite(c["fit"]):
            continue
        past = c["fit"] <= today
        ci = ""
        if c["ci"] and not past:
            ci = f'<span class="fm-ci">{esc(mc._ci_text(c["ci"]))}</span>'
        elif past:
            ci = '<span class="fm-ci">passed</span>'
        rows.append(f'<div class="fm-row{" fm-past" if past else ""}">'
                    f'<span class="fm-lvl">{c["level"] * 100:.0f} %</span>'
                    f'<span class="fm-year">{esc(mc.year_text(c["fit"]))}</span>{ci}</div>')
    return "".join(rows)


def _fact(value: str, label: str, sub: str = "") -> str:
    return (f'<div class="ff"><div class="ff-n">{esc(value)}</div>'
            f'<div class="ff-l">{esc(label)}</div><div class="ff-s">{esc(sub)}</div></div>')


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:—-")
    return cut + "…"


def build_flyer(fm: dict, rows: list[dict], shift: dict | None, figures: dict,
                state: dict | None, bands: dict | None, theme_href: str) -> str:
    country = fm.get("country", "")
    slug = fm.get("slug", "")
    hev_full = fm.get("hev_split") is True
    head, follow = verdict(country, figures, shift)
    through = mc.period_label(rows[-1]["period"], long=True) if rows else ""

    flag = ""
    if slug and (mc.REPO / "assets" / "flags" / f"{slug}.png").is_file():
        flag = f'<img class="fl-flag" src="../../assets/flags/{esc(slug)}.png" alt="">'

    # Hero: the one number, and the mix over time.
    hero_num = ""
    ttm, latest = figures.get("ttm"), figures.get("latest")
    if ttm:
        delta = ""
        if ttm["delta"] is not None:
            cls = "up" if ttm["delta"] >= 0.05 else "down" if ttm["delta"] <= -0.05 else "flat"
            delta = (f'<div class="fh-delta {cls}">{mc.points(ttm["delta"])} points '
                     'in a year</div>')
        month = ""
        if latest:
            month = (f'<div class="fh-month">{esc(mc.row_label(latest["row"]))} alone: '
                     f'<b>{esc(mc.share(latest["share"]))}</b></div>')
        big = mc.share(ttm["share"]).replace(" %", "")
        hero_num = (
            '<div class="fh-num"><div class="fh-kicker">BEV share of new cars</div>'
            f'<div class="fh-big">{esc(big)}<span>%</span></div>'
            f'<div class="fh-what">in the 12 months to {esc(mc.period_label(ttm["end"], long=True))}</div>'
            f'{delta}{month}</div>')
    mix = build_mix(mix_points(rows), hev_full, 470 if hero_num else INNER_W, 170)
    hero = f'<div class="fl-hero">{hero_num}<div class="fh-mix">{mix}</div></div>' if (hero_num or mix) else ""

    bars = ""
    if shift:
        (b0, b1), (a0, a1) = shift["span"]
        bars = (
            '<section class="fl-sec"><h2>Who gained, who lost</h2>'
            f'<p class="fl-sub">Change in share of new registrations, in percentage points: '
            f'{esc(mc.period_label(a0))} to {esc(mc.period_label(a1))} against the year before. '
            'Right: share now.</p>'
            f'<div class="fb">{build_bars(shift)}</div></section>')

    curve = ""
    if state:
        svg = mc.build_curve_svg(rows, state, bands, width=452, height=170)
        if svg:
            if state["flat"]:
                side = ('<p class="fm-none">The transition has not started in the data, '
                        'so the curve gives no dates yet.</p>')
            elif not state["quotable"]:
                side = ('<p class="fm-none">The curve still changes too much from month '
                        'to month to give dates.</p>')
            else:
                band = ('<p class="fm-note">Right column: 95 % confidence interval '
                        'of the curve.</p>' if state["band_ok"] else "")
                side = ('<div class="fm-head">The curve reaches</div>'
                        f'<div class="fm">{build_miles(state)}</div>{band}')
            legend = "Dots: observed share per period. Line: fitted S-curve."
            if state["band_ok"]:
                legend += " Band: 95 % confidence interval."
            curve = (
                '<section class="fl-sec"><h2>Where the curve points</h2>'
                '<p class="fl-sub">An S-curve fitted to the BEV share so far. It is this '
                "project's model, not an official forecast: a policy change or a stall "
                'is not in it.</p>'
                f'<div class="fl-curve"><div>{svg}<p class="fl-legend">{legend}</p></div>'
                f'<div class="fm-side">{side}</div></div></section>')

    facts = []
    volume, record = figures.get("volume"), figures.get("record")
    if volume:
        sub = "last 12 months"
        if volume["growth"] is not None:
            sub += f', {mc.points(volume["growth"])} % in a year'
        facts.append(_fact(mc.units(volume["total"]), "new registrations", sub))
        if volume["bev"] is not None:
            facts.append(_fact(mc.units(volume["bev"]), "of them battery electric", "last 12 months"))
    if record:
        facts.append(_fact(mc.share(record["share"]), "highest BEV share in one period",
                           mc.row_label(record["row"])))
    if shift:
        plug = next((r for r in shift["rows"] if r["key"] == "PHEV"), None)
        bev = next(r for r in shift["rows"] if r["key"] == "BEV")
        if plug and plug["after"] >= 0.05:
            facts.append(_fact(mc.share(bev["after"] + plug["after"]), "with a plug",
                               "BEV + plug-in hybrid, 12 months"))
    facts_html = f'<div class="fl-facts">{"".join(facts[:4])}</div>' if facts else ""

    source = (fm.get("source_name") or "").split("—")[0].strip()
    scope = _clip(mc.footnote(country) or fm.get("scope_note") or "", 150)
    url = f"{mc.SITE}/sources/{slug}.html"
    foot = (
        '<footer class="fl-foot">'
        f'<p><b>Source:</b> {esc(source)}. {esc(scope)}</p>'
        '<p>Scopes differ between countries. Method, definitions and every number: '
        f'<a href="../{esc(slug)}.html">{esc(url.replace("https://", ""))}</a></p>'
        '<p class="fl-brand"><b>BEV Trajectory Gallery</b> · @LeRaffl · charts and text CC BY 4.0'
        f'{" · data through " + esc(through) if through else ""}</p></footer>')

    return FLYER_TEMPLATE.format(
        country=esc(country), theme_href=theme_href, css=FLYER_CSS, flag=flag,
        through=esc(through), head=esc(head), follow=esc(follow), hero=hero,
        bars=bars, curve=curve, facts=facts_html, foot=foot, slug=esc(slug),
        w=SHEET_W, h=SHEET_H)


FLYER_CSS = """
html{background:#e9e7e1}
body{margin:0;background:#e9e7e1;color:var(--text);font-family:var(--font-ui),sans-serif}
.fl-bar{max-width:794px;margin:0 auto;padding:12px 8px;display:flex;gap:12px;align-items:center;
  font-size:13px}
.fl-bar a{color:var(--muted)}
.fl-bar button{margin-left:auto;font:inherit;padding:6px 14px;border-radius:8px;cursor:pointer;
  border:1px solid var(--text);background:var(--text);color:#fff;font-weight:600}
.sheet-box{margin:0 auto 32px}
.sheet{width:794px;height:1123px;box-sizing:border-box;padding:32px 46px 26px;background:#fdfdfc;
  box-shadow:0 2px 18px rgba(0,0,0,.14);display:flex;flex-direction:column;overflow:hidden;
  transform-origin:top left;color-scheme:light;
  --text:#1a1a18;--muted:#55534c;--line:#dcd9d2}
.sheet *{-webkit-print-color-adjust:exact;print-color-adjust:exact}
.fl-top{display:flex;align-items:center;gap:14px;padding-bottom:12px;border-bottom:2px solid var(--text)}
.fl-flag{width:54px;height:37px;object-fit:cover;border-radius:2px;box-shadow:0 0 0 1px var(--line)}
.fl-top h1{font-family:var(--font-display);font-size:30px;line-height:1;margin:0;font-weight:600}
.fl-kick{font-size:11px;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);margin-top:5px}
.fl-date{margin-left:auto;text-align:right;font-size:11px;letter-spacing:.06em;text-transform:uppercase;
  color:var(--muted);line-height:1.5}
.fl-date b{display:block;font-size:15px;letter-spacing:0;text-transform:none;color:var(--text)}
.fl-head{font-family:var(--font-display);font-size:28px;line-height:1.16;font-weight:600;
  margin:14px 0 4px;letter-spacing:-.01em}
.fl-follow{font-family:var(--font-display);font-size:17px;line-height:1.35;margin:0;color:#3a3935;
  min-height:23px}
.fl-hero{display:flex;gap:18px;align-items:flex-end;margin:12px 0 0}
.fh-num{flex:none;width:218px}
.fh-kicker{font-size:11.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);line-height:1.35}
.fh-big{font-family:var(--font-display);font-size:84px;line-height:.98;font-weight:600;color:#2c7a50;
  letter-spacing:-.03em;margin:4px 0 2px;font-variant-numeric:tabular-nums}
.fh-big span{font-size:40px;margin-left:3px;letter-spacing:0}
.fh-what{font-size:13px;color:var(--muted)}
.fh-delta{display:inline-block;margin-top:10px;padding:3px 10px;border-radius:999px;font-size:13px;
  font-weight:700}
.fh-delta.up{background:#dcefe4;color:#1f6a43}
.fh-delta.down{background:#f6e0dc;color:#9a3324}
.fh-delta.flat{background:#eceae4;color:#55534c}
.fh-month{font-size:13px;margin-top:8px;color:var(--muted)}
.fh-month b{color:var(--text)}
.fh-mix{flex:1;min-width:0}
.fl-svg{display:block}
.fl-svg text{font-size:11.5px;fill:#3a3935;font-family:var(--font-ui),sans-serif}
.fl-svg text.ax{fill:#77746c;font-size:10.5px}
.fl-svg text.strong{font-weight:700;fill:#1f6a43}
.fl-sec{margin-top:12px}
.fl-sec h2{font-family:var(--font-display);font-size:18px;margin:0;font-weight:600;border:0;padding:0}
.fl-sub{font-size:11.5px;color:var(--muted);margin:2px 0 8px;line-height:1.4}
.fb-row{display:grid;grid-template-columns:200px 1fr 46px 62px;column-gap:10px;align-items:center;
  font-size:13px;height:21px}
.fb-name{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fb-track{position:relative;height:21px}
.fb-zero{position:absolute;top:0;bottom:0;border-left:1px solid #77746c}
.fb-bar{position:absolute;top:4px;bottom:4px;border-radius:2px;min-width:2px}
.fb-pp{text-align:right;font-weight:700;font-variant-numeric:tabular-nums}
.fb-now{text-align:right;color:var(--muted);font-variant-numeric:tabular-nums}
.fl-curve{display:flex;gap:22px;align-items:flex-start}
.fl-curve .curve{width:452px;height:170px}
.fl-curve .curve text{font-size:10.5px;fill:#77746c;font-family:var(--font-ui),sans-serif}
.cv-grid{stroke:#e4e2dd;stroke-width:1}
.cv-ci{fill:#3d9a68;fill-opacity:.2}
.cv-fit{fill:none;stroke:#2c7a50;stroke-width:2.2}
.cv-weak{stroke-dasharray:5 4;stroke:#8d897c}
.cv-pt{fill:#55534c;fill-opacity:.55}
.cv-est{fill:none;stroke:#55534c}
.cv-now{stroke:#8d897c;stroke-width:1;stroke-dasharray:2 3}
.fl-legend{font-size:10.5px;color:var(--muted);margin:2px 0 0 30px}
.fm-side{flex:1;min-width:0;padding-top:6px}
.fm-head{font-size:11.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);
  margin-bottom:4px}
.fm-row{display:grid;grid-template-columns:52px 62px 1fr;align-items:baseline;
  border-bottom:1px solid var(--line);padding:3px 0}
.fm-lvl{font-size:14px;color:var(--muted)}
.fm-year{font-family:var(--font-display);font-size:24px;font-weight:600;line-height:1;
  font-variant-numeric:tabular-nums}
.fm-ci{font-size:12px;color:var(--muted);text-align:right;font-variant-numeric:tabular-nums}
.fm-past .fm-year{color:#8d897c;font-weight:500}
.fm-note{font-size:10.5px;color:var(--muted);margin:6px 0 0}
.fm-none{font-family:var(--font-display);font-size:16px;line-height:1.35;margin:10px 0 0}
.fl-facts{display:grid;grid-template-columns:repeat(4,1fr);gap:0;margin-top:12px;
  border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.ff{padding:8px 12px 7px;border-left:1px solid var(--line)}
.ff:first-child{border-left:0;padding-left:0}
.ff-n{font-family:var(--font-display);font-size:22px;font-weight:600;line-height:1.1;
  font-variant-numeric:tabular-nums}
.ff-l{font-size:12px;margin-top:2px}
.ff-s{font-size:11px;color:var(--muted)}
.fl-foot{margin-top:auto;padding-top:10px;font-size:10.5px;line-height:1.45;color:var(--muted)}
.fl-foot p{margin:0 0 3px}
.fl-foot a{color:inherit}
.fl-foot b{color:var(--text)}
.fl-brand{margin-top:6px!important;padding-top:6px;border-top:2px solid var(--text);
  color:var(--text);font-size:11px}
@page{size:A4;margin:0}
@media print{
  html,body{background:#fff}
  .fl-bar{display:none}
  .sheet-box{margin:0;width:auto!important;height:auto!important}
  .sheet{box-shadow:none;transform:none!important;width:210mm;height:296mm;zoom:1}
}
"""

FLYER_TEMPLATE = """<!doctype html>
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{country} — the shift to battery-electric cars · BEV Trajectories</title>
<meta name="description" content="{head} {follow}">
<meta property="og:title" content="{country} — the shift to battery-electric cars">
<meta property="og:description" content="{head} {follow}">
<link rel="stylesheet" href="{theme_href}">
<style>{css}</style>
</head>
<body>
<div class="fl-bar"><a href="../{slug}.html">← {country}: sources and method</a>
  <a href="../">All countries</a>
  <button type="button" onclick="window.print()">Save as PDF</button></div>
<div class="sheet-box"><article class="sheet">
  <header class="fl-top">{flag}
    <div><h1>{country}</h1><div class="fl-kick">The shift to battery-electric cars</div></div>
    <div class="fl-date">Data through<b>{through}</b></div></header>
  <p class="fl-head">{head}</p>
  <p class="fl-follow">{follow}</p>
  {hero}
  {bars}
  {curve}
  {facts}
  {foot}
</article></div>
<script>
(function(){{
  var box=document.querySelector('.sheet-box'),sheet=box.firstElementChild;
  function fit(){{
    var s=Math.min(1,(document.documentElement.clientWidth-16)/{w});
    sheet.style.transform=s<1?'scale('+s+')':'';
    box.style.width=({w}*s)+'px';box.style.height=({h}*s)+'px';
  }}
  fit();addEventListener('resize',fit);
}})();
</script>
</body>
</html>
"""
