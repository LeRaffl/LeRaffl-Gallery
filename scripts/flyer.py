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

import segno

import locator_map
import market_structure as mstr
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


SHORT_LABEL = {
    "Plug-in hybrid incl. range extenders": "Plug-in hybrid + EREV",
    "Petrol, diesel and other combustion": "Combustion",
    "Combustion and anything not split out": "Combustion, not split",
}


def _short(row: dict) -> str:
    return SHORT_LABEL.get(row["label"], row["label"])


def _clause(row: dict) -> str:
    """'petrol down 9.4' / 'CNG up 2.8' for the verdict follow-up."""
    name = _short(row)
    if not name.isupper():
        name = name[0].lower() + name[1:]
    delta = row["delta"]
    way = "up" if delta > 0 else "down"
    return f"{name} {way} {abs(delta):.1f}"


def verdict(country: str, figures: dict, shift: dict | None) -> tuple[str, str]:
    """(headline, follow-up sentence) from the 12-month BEV share and its change."""
    ttm = figures.get("ttm")
    if not ttm:
        return f"{country}: new registrations by powertrain", ""
    s, d = ttm["share"], ttm["delta"]
    if s < 1:
        head = "Fewer than 1 in 100 new cars is battery electric."
    elif s < 37.5:
        head = f"{one_in(s).capitalize()} new cars is battery electric."
    elif s < 45:
        head = "About 2 in 5 new cars are battery electric."
    elif s < 55:
        head = "About half of new cars are battery electric."
    elif s < 80:
        head = f"Most new cars are battery electric: {s:.0f} in 100."
    else:
        head = f"Almost every new car is battery electric: {s:.0f} in 100."

    if d is None:
        return head, ""
    period = mc.vs_prior_phrase(ttm["end"])
    if abs(d) < 0.15:
        move = f"{period}: BEV barely moved."
    elif d > 0:
        move = f"{period}: BEV up {d:.1f} points."
    else:
        move = f"{period}: BEV down {abs(d):.1f} points."
    if shift:
        # "Everything else" only mirrors the BEV change; skip it.
        others = [r for r in shift["rows"] if r["key"] not in ("BEV", "REST")]
        if others:
            # Biggest counter-move as a fact in the same sentence.
            loser = min(others, key=lambda r: r["delta"])
            winner = max(others, key=lambda r: r["delta"])
            extra = ""
            if d >= 0.15 and loser["delta"] <= -1:
                extra = f", {_clause(loser)}"
            elif d <= -0.15 and winner["delta"] >= 1:
                extra = f", {_clause(winner)}"
            elif abs(d) < 0.15:
                mover = loser if abs(loser["delta"]) >= abs(winner["delta"]) else winner
                if abs(mover["delta"]) >= 1:
                    extra = f", {_clause(mover)}"
            if extra:
                move = move.rstrip(".") + extra + "."
    return head, move


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
    """Stacked trailing-share chart. An HTML grid, not a fixed-width SVG: the
    plot column is fluid, so it fills the hero after fitIn lays the sheet
    out wider than A4; the axis and the direct labels stay a fixed size."""
    if not points:
        return ""
    left, right, top, bottom = 26, 164, 20, 22
    end = points[-1]
    # The direct labels sit right of the plot; a long one ("Combustion +
    # hybrids 65.3%") was clipped at the edge. Reserve what the longest needs
    # (about 6.2 px a character at 11.5 px, plus swatch and gap).
    longest = max(len(n) for n in ("Battery electric", "Plug-in hybrid", "Full hybrid",
                                   "Combustion + hybrids" if end.get("HEV") is None
                                   and end.get("PHEV") is not None else "Combustion"))
    right = max(right, int((longest + 6) * 6.2) + 22)
    plot_h = height - top - bottom
    t0, t1 = points[0]["t"], points[-1]["t"]

    def x_pct(t: float) -> float:
        return 100.0 * (t - t0) / ((t1 - t0) or 1)

    def y_of(v: float) -> float:
        return top + plot_h * (1 - max(0.0, min(100.0, v)) / 100)

    plot, axis, years, labels_out = [], [], [], []
    base = [0.0] * len(points)
    labels = []
    names = dict(MIX_ORDER)
    names["HEV"] = "Full hybrid" if hev_full else "Hybrid"
    if end["PHEV"] is None:
        # Plug-ins are not split out at this point, so the rest holds them
        # too (Malaysia, Nepal fill PHEV only in part; Türkiye, Georgia,
        # Ukraine have no PHEV column). Calling that "Combustion" is wrong.
        names["REST"] = "Everything else"
    elif end["HEV"] is None:
        names["REST"] = "Combustion + hybrids"
    for key, _ in MIX_ORDER:
        values = [p[key] or 0.0 for p in points]
        if not any(values):
            continue
        upper = [b + v for b, v in zip(base, values)]
        path = [f"M{x_pct(points[0]['t']):.2f},{y_of(upper[0]):.1f}"]
        path += [f"L{x_pct(p['t']):.2f},{y_of(u):.1f}" for p, u in zip(points[1:], upper[1:])]
        path += [f"L{x_pct(p['t']):.2f},{y_of(b):.1f}" for p, b in zip(reversed(points), reversed(base))]
        plot.append(f'<path d="{" ".join(path)} Z" fill="{mc.COLORS[key]}"/>')
        if end[key] and (end[key] >= 0.5 or key == "BEV"):
            labels.append([y_of(base[-1] + values[-1] / 2), key, names[key], end[key]])
        base = upper
    for mark in (0, 50, 100):
        y = y_of(mark)
        axis.append(f'<text x="{left - 5}" y="{y + 3.5:.1f}" text-anchor="end" class="ax">{mark}</text>')
    plot.append(f'<line x1="0" y1="{y_of(50):.1f}" x2="100" y2="{y_of(50):.1f}" '
                'stroke="#fff" stroke-opacity=".6"/>')
    year = math.ceil(t0)
    span = t1 - t0
    step = 1 if span <= 6 else 2
    while year <= t1:
        xp = x_pct(year)
        if xp > 3 or year == t0 or abs(year - t0) < 1e-9:
            anchor = "start" if xp < 2 else "end" if xp > 98 else "middle"
            years.append(f'<text x="{xp:.2f}%" y="{height - 6}" text-anchor="{anchor}" '
                         f'class="ax">{year}</text>')
        year += step
    # Direct labels at the right edge, pushed apart so they never overlap.
    labels.sort()
    gap = 15
    if labels:
        for i in range(1, len(labels)):
            labels[i][0] = max(labels[i][0], labels[i - 1][0] + gap)
        over = labels[-1][0] - (top + plot_h - 2)
        if over > 0:
            labels[-1][0] -= over
            for i in range(len(labels) - 2, -1, -1):
                labels[i][0] = min(labels[i][0], labels[i + 1][0] - gap)
    for y, key, name, value in labels:
        labels_out.append(f'<rect x="8" y="{y - 5:.1f}" width="8" height="8" fill="{mc.COLORS[key]}"/>')
        bold = ' class="strong"' if key == "BEV" else ""
        labels_out.append(f'<text x="21" y="{y + 3:.1f}"{bold}>{esc(name)} '
                          f'{mc.share(value)}</text>')
    label = (f"Share of new registrations by powertrain, trailing twelve months, "
             f"through {mc.period_label(end['period'])}.")
    title = '<text x="0" y="12" class="mix-t">Trailing 12-month share by powertrain</text>'
    return (
        f'<div class="fl-mix" style="--mix-lab:{right}px;height:{height}px" '
        f'role="img" aria-label="{esc(label)}">'
        f'<svg class="fl-svg mix-y" viewBox="0 0 {left} {height}" width="{left}" height="{height}" '
        f'aria-hidden="true">{"".join(axis)}</svg>'
        f'<div class="mix-mid">'
        f'<svg class="fl-svg mix-plot" viewBox="0 0 100 {height}" preserveAspectRatio="none" '
        f'aria-hidden="true">{"".join(plot)}</svg>'
        f'<svg class="fl-svg mix-years" aria-hidden="true">{title}{"".join(years)}</svg>'
        f'</div>'
        f'<svg class="fl-svg mix-lab" viewBox="0 0 {right} {height}" width="{right}" height="{height}" '
        f'aria-hidden="true">{"".join(labels_out)}</svg>'
        f'</div>')



# --------------------------------------------------------------------------
# Blocks
# --------------------------------------------------------------------------

def split_rows(shift: dict, limit: int = 6) -> list[dict]:
    """The rows the bars show. Past `limit`, the smallest movers fold into
    one residual row instead of being dropped, so the shown rows still add
    up to 100 % and ±0 points (powertrain_shift builds them that way)."""
    rows = list(shift["rows"])
    if len(rows) <= limit:
        return rows
    keep = sorted(rows, key=lambda r: (r["key"] != "BEV", -abs(r["delta"])))[:limit - 1]
    folded = [r for r in rows if r not in keep]
    rest = next((r for r in folded if r["key"] == "REST"), None)
    merged = {"key": "REST", "label": (rest or {}).get("label") or "Other fuels"}
    if len(folded) > 1 or rest is None:
        merged["label"] = "Other fuels"
    for k in ("before", "after", "delta"):
        merged[k] = sum(r[k] for r in folded)
    return [r for r in rows if r in keep] + [merged]


def build_bars(shift: dict, limit: int = 6) -> str:
    rows = split_rows(shift, limit)
    neg = max([-r["delta"] for r in rows] + [0.0])
    pos = max([r["delta"] for r in rows] + [0.0])
    zero = min(74.0, max(26.0, 100 * neg / ((neg + pos) or 1)))
    scale = min(zero / neg if neg else 1e9, (100 - zero) / pos if pos else 1e9)
    out = []
    for row in rows:
        width = abs(row["delta"]) * scale
        left = zero if row["delta"] >= 0 else zero - width
        out.append(
            f'<div class="fb-row"><span class="fb-name">'
            f'{esc(SHORT_LABEL.get(row["label"], row["label"]))}</span>'
            f'<span class="fb-track"><i class="fb-zero" style="left:{zero:.2f}%"></i>'
            f'<i class="fb-bar" style="left:{left:.2f}%;width:{width:.2f}%;'
            f'background:{mc.COLORS.get(row["key"], mc.COLORS["REST"])}"></i></span>'
            f'<span class="fb-pp">{mc.points(row["delta"])}</span>'
            f'<span class="fb-now">{mc.share(row["after"])}</span></div>')
    head = ('<div class="fb-head"><span></span><span></span>'
            '<span>Change, pts</span><span>Share, last 12 months</span></div>')
    return head + "".join(out)


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
                    f'<span class="fm-lvl">{c["level"] * 100:.0f}%</span>'
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


def build_qr(url: str, size: int = 68) -> str:
    """The link as a QR code, drawn as one SVG path (no image file)."""
    matrix = [list(row) for row in segno.make(url, error="l", micro=False).matrix]
    n = len(matrix)
    quiet = 2
    path = "".join(f"M{x + quiet},{y + quiet}h1v1h-1z"
                   for y, row in enumerate(matrix) for x, dark in enumerate(row) if dark)
    side = n + 2 * quiet
    return (f'<svg class="fl-qr" viewBox="0 0 {side} {side}" width="{size}" height="{size}" '
            f'role="img" aria-label="QR code: {esc(url)}" shape-rendering="crispEdges">'
            f'<rect width="{side}" height="{side}" fill="#fff"/><path d="{path}" fill="#1a1a18"/></svg>')


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def box_stats(values: list[float]) -> dict | None:
    """Five-number summary: min, quartiles (linear interpolation between
    order statistics, the common "type 7" rule), median and max."""
    vals = sorted(v for v in values if v is not None and math.isfinite(v))
    n = len(vals)
    if n < 5:
        return None

    def q(p: float) -> float:
        pos = (n - 1) * p
        lo = int(math.floor(pos))
        hi = min(lo + 1, n - 1)
        return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)

    return {"n": n, "min": vals[0], "q1": q(0.25), "median": q(0.5),
            "q3": q(0.75), "max": vals[-1]}


def year_at(state: dict | None, level: float = 0.5) -> float | None:
    """Year the brief's own fitted curve reaches `level` (None when the brief
    quotes no year: no quotable fit, or a curve that never gets there)."""
    if not state or not state.get("quotable"):
        return None
    target = round(level, 3)
    for c in state.get("crossings") or []:
        if round(c.get("level", 0), 3) == target:
            y = c.get("fit")
            return y if y is not None and math.isfinite(y) else None
    return None


def year_ci(state: dict | None, level: float = 0.5):
    """The 95 % band of the year the curve reaches `level`, as (lo, hi) where
    an open end is None, or None when the brief prints no band (no usable
    band file, or no quotable fit). Same gate as the brief's own table."""
    if not state or not state.get("quotable") or not state.get("band_ok"):
        return None
    target = round(level, 3)
    for c in state.get("crossings") or []:
        if round(c.get("level", 0), 3) == target and c.get("ci"):
            return tuple(c["ci"])
    return None


def year_at_50(state: dict | None) -> float | None:
    return year_at(state, 0.5)


def year_at_80(state: dict | None) -> float | None:
    return year_at(state, 0.8)


CMP_LABEL_W = 176          # left column of each box-plot strip, px


def _box_strip(metric: dict, width: float, k: float = 1.0, cls: str = "fl") -> str:
    """One slim box plot: whiskers lowest to highest country, box = middle
    half, line = median; a grey tick per country, flags for the reference
    markets, the subject in green."""
    lo, hi = metric["axis"]
    stats = metric["stats"]
    # Enough inset that end-tick labels can sit on the tick (middle-anchored)
    # without clipping, and every strip uses the same left edge.
    left, right = 22 * k, 22 * k
    plot = width - left - right
    flag_rows = (13 * k, 1 * k)
    fw, fh = 15 * k, 10 * k
    box_top, box_h = 27 * k, 11 * k
    mid = box_top + box_h / 2
    rug_top, rug_bot = box_top + box_h + 2 * k, box_top + box_h + 8 * k
    # Tick labels need a line under the rug; year strips that share a
    # scale below keep only a tight follow, so the boxes stay in line.
    tick_space = 13 * k if metric.get("ticks") else 3 * k
    ci = metric.get("ci")
    ci_y = rug_bot + 6 * k
    ci_space = 9 * k if ci else 0
    height = round(rug_bot + ci_space + tick_space)

    def x_of(v: float) -> float:
        v = max(lo, min(hi, v))
        return left + plot * (v - lo) / (hi - lo)

    p = []
    # Rug: one grey tick per ranked country.
    for _, v in metric["values"]:
        x = x_of(v)
        p.append(f'<line x1="{x:.1f}" y1="{rug_top:.1f}" x2="{x:.1f}" y2="{rug_bot:.1f}" '
                 f'stroke="#8d897c" stroke-opacity=".6" stroke-width="{1.1 * k:.2f}"/>')
    # Whiskers, box, median.
    x0, x1 = x_of(stats["min"]), x_of(stats["max"])
    q1, q3, md = x_of(stats["q1"]), x_of(stats["q3"]), x_of(stats["median"])
    grey = f'stroke="#8d897c" stroke-width="{k:.2f}"'
    p.append(f'<line x1="{x0:.1f}" y1="{mid:.1f}" x2="{q1:.1f}" y2="{mid:.1f}" {grey}/>')
    p.append(f'<line x1="{q3:.1f}" y1="{mid:.1f}" x2="{x1:.1f}" y2="{mid:.1f}" {grey}/>')
    for x in (x0, x1):
        p.append(f'<line x1="{x:.1f}" y1="{box_top + 3 * k:.1f}" x2="{x:.1f}" '
                 f'y2="{box_top + box_h - 3 * k:.1f}" {grey}/>')
    p.append(f'<rect x="{q1:.1f}" y="{box_top:.1f}" width="{max(q3 - q1, 1):.1f}" '
             f'height="{box_h:.1f}" fill="#ebe8e1" {grey}/>')
    p.append(f'<line x1="{md:.1f}" y1="{box_top:.1f}" x2="{md:.1f}" '
             f'y2="{box_top + box_h:.1f}" stroke="#3b3a36" stroke-width="{2 * k:.2f}"/>')
    # The subject's own 95 % band: a green span under the rug, capped where
    # the band ends and open (no cap, runs to the axis edge) where it does not.
    if ci:
        c_lo, c_hi = ci
        gx0 = x_of(c_lo) if c_lo is not None else x_of(lo)
        gx1 = x_of(c_hi) if c_hi is not None else x_of(hi)
        gsw = 3.2 * k
        p.append(f'<line x1="{gx0:.1f}" y1="{ci_y:.1f}" x2="{gx1:.1f}" y2="{ci_y:.1f}" '
                 f'stroke="#2c7a50" stroke-opacity=".45" stroke-width="{gsw:.2f}">'
                 f'<title>95% band</title></line>')
        for cx, cv in ((gx0, c_lo), (gx1, c_hi)):
            if cv is not None:
                p.append(f'<line x1="{cx:.1f}" y1="{ci_y - 3.5 * k:.1f}" x2="{cx:.1f}" '
                         f'y2="{ci_y + 3.5 * k:.1f}" stroke="#2c7a50" stroke-width="{1.6 * k:.2f}"/>')
    # Decade guides on a shared year scale (labels live on the axis row).
    for tick, _text in metric.get("guides") or []:
        x = x_of(tick)
        p.append(f'<line x1="{x:.1f}" y1="{box_top - 2 * k:.1f}" x2="{x:.1f}" '
                 f'y2="{rug_bot:.1f}" stroke="#8d897c" stroke-opacity=".22" '
                 f'stroke-width="{0.8 * k:.2f}"/>')
    # Axis labels, all middle-anchored so 0% and 2020 sit on the same inset.
    for tick, text in metric.get("ticks") or []:
        p.append(f'<text x="{x_of(tick):.1f}" y="{height - 2}" text-anchor="middle" '
                 f'class="ax">{esc(text)}</text>')

    # Flags: the subject first, on the lower row; others avoid it, moving
    # up a row (or, if both rows are taken there, staying as a bare tick).
    taken: list[tuple[float, int]] = []
    items = ([{**metric["own"], "subject": True}]
             + [{**h, "subject": False} for h in metric["marks"]])
    subject_parts: list[str] = []
    for item in items:
        out = subject_parts if item["subject"] else p
        x = x_of(item["value"])
        row = next((r for r in range(len(flag_rows))
                    if not any(abs(px - x) < fw + 2 and pr == r for px, pr in taken)), None)
        src = mc.flag_src(item.get("slug") or "", item["name"])
        colour, sw = (("#2c7a50", 3.2 * k) if item["subject"] else ("#3b3a36", 1.4 * k))
        top = (flag_rows[row] + fh + k) if (row is not None and src) else box_top - 6 * k
        out.append(f'<line x1="{x:.1f}" y1="{top:.1f}" x2="{x:.1f}" y2="{rug_bot:.1f}" '
                   f'stroke="{colour}" stroke-width="{sw:.2f}"><title>{esc(item["name"])}</title></line>')
        if row is not None and src:
            taken.append((x, row))
            out.append(f'<image href="{esc(src)}" x="{x - fw / 2:.1f}" y="{flag_rows[row]:.1f}" '
                       f'width="{fw:.1f}" height="{fh:.1f}"/>')
    p.extend(subject_parts)     # the green mark sits on top of any neighbour
    svg = (f'<svg class="{cls}-svg {cls}-cmp-svg" width="100%" height="{height}" role="img" '
           f'aria-label="{esc(metric["aria"])}">{_x_to_pct("".join(p), width)}</svg>')
    q = metric.get("q_line") or ""
    q_html = f'<span>{q}</span>' if q else ""
    ci_html = (f'<span class="{cls}-bx-ci">{metric["ci_line"]}</span>'
               if metric.get("ci_line") else "")
    tight = "" if metric.get("ticks") else f" {cls}-bx-l-tight"
    return (f'<div class="{cls}-bx"><div class="{cls}-bx-l{tight}"><b>{metric["title"]}</b>'
            f'<span class="{cls}-bx-own">{metric["own_line"]}</span>{ci_html}'
            f'<span>{metric["mid_line"]}</span>{q_html}</div>{svg}</div>')


def _unify_year_axes(strips: list[dict]) -> None:
    """Put every year strip on the 80 %-scale (the wider of the two).

    The 50 % box then sits further left on a comparable timeline. Tick
    labels move to a shared axis under the last year strip; faint guides
    stay on both plots so the block reads as one scale.
    """
    years = [s for s in strips if s.get("kind") == "year"]
    if len(years) < 2:
        return
    vals: list[float] = []
    for s in years:
        vals.extend(v for _, v in s["values"])
        vals.append(s["own"]["value"])
        vals.extend(m["value"] for m in s["marks"])
        vals.extend(e for e in (s.get("ci") or ()) if e is not None and math.isfinite(e))
    lo = 5 * math.floor(min(vals) / 5)
    hi = max(5 * math.ceil(max(vals) / 5), lo + 20)
    ticks = [(float(t), str(t)) for t in range(lo, hi + 1, 5)
             if t % 10 == 0 or t in (lo, hi)]
    axis = (float(lo), float(hi))
    for s in years:
        s["axis"] = axis
        s["ticks"] = []
        s["guides"] = ticks
    years[-1]["shared_ticks"] = ticks


def _year_axis_row(axis: tuple[float, float], ticks: list[tuple[float, str]],
                   width: float, k: float = 1.0) -> str:
    """One year scale under the year strips, same inset as the plots."""
    lo, hi = axis
    left, right = 22 * k, 22 * k
    plot = width - left - right
    height = 14 * k

    def x_of(v: float) -> float:
        v = max(lo, min(hi, v))
        return left + plot * (v - lo) / (hi - lo)

    p = [f'<line x1="{x_of(lo):.1f}" y1="1.5" x2="{x_of(hi):.1f}" y2="1.5" '
         f'stroke="#8d897c" stroke-width="{k:.2f}"/>']
    for tick, text in ticks:
        x = x_of(tick)
        p.append(f'<line x1="{x:.1f}" y1="0" x2="{x:.1f}" y2="4.5" '
                 f'stroke="#8d897c" stroke-width="{k:.2f}"/>')
        p.append(f'<text x="{x:.1f}" y="{height - 1}" text-anchor="middle" '
                 f'class="ax">{esc(text)}</text>')
    lo_s, hi_s = f"{lo:.0f}", f"{hi:.0f}"
    svg = (f'<svg class="fl-svg fl-cmp-axis" width="100%" height="{height}" '
           f'role="img" aria-label="Year scale, {lo_s} to {hi_s}">'
           f'{_x_to_pct("".join(p), width)}</svg>')
    return f'<div class="fl-cmp-axis-l" aria-hidden="true"></div>{svg}'


def _rank_of(own: float, values: list[float], higher_first: bool) -> int:
    """1 + the number of countries strictly ahead of `own`."""
    ahead = sum(1 for v in values if (v > own if higher_first else v < own))
    return ahead + 1


def compare_strips(country: str, peers: list[tuple[str, float]],
                   highlights: list[dict] | None = None,
                   subject_slug: str = "", is_region: bool = False,
                   own_share: float | None = None,
                   peer_years: list[tuple[str, float]] | None = None,
                   own_year: float | None = None,
                   peer_years_80: list[tuple[str, float]] | None = None,
                   own_year_80: float | None = None,
                   own_ci: tuple | None = None,
                   own_ci_80: tuple | None = None) -> tuple[list[dict], list[str], int]:
    """The Gallery's rankings as slim box plots across every ranked country:
    BEV share of new cars over the last 12 months, and the years the fitted
    S-curve reaches 50 % and 80 % (the Thresholds ranking). The subject is
    marked in green; Norway, China, EU, World, Germany and USA are flags.

    `peers` is (country, 12-month BEV share in percent) under the same
    full-window rule as each brief; `peer_years` / `peer_years_80` are
    (country, fitted year) for every brief that quotes that threshold.
    Region highlights carry their weighted headline share and their own
    curve's years. The subject is never also a highlight. A year strip is
    left out when the subject quotes no year at that threshold, or fewer
    than 10 countries do.
    """
    own = own_share
    if own is None:
        own = next((v for name, v in peers if name == country), None)
    if own is None or len(peers) < 10:
        return [], [], 0
    if not is_region and not any(name == country for name, _ in peers):
        return [], [], 0
    named: list[str] = []

    def marks_for(key: str) -> list[dict]:
        out = []
        for h in highlights or []:
            v = h.get(key)
            if h.get("name") == country or v is None or v != v or not math.isfinite(v):
                continue
            out.append({"name": h["name"], "slug": h.get("slug", ""), "value": v})
            if h["name"] not in named:
                named.append(h["name"])
        return out

    def place(rank: int, n: int) -> str:
        if is_region:
            return f"would be {ordinal(rank)} of {n}"
        return f"<b>{ordinal(rank)} of {n}</b>"

    pct = lambda v: mc.share(v).replace(" %", "%")  # noqa: E731
    shares = [v for _, v in peers]
    s_stats = box_stats(shares)
    s_rank = _rank_of(own, shares, higher_first=True)
    strips = [{
        "title": "BEV share, last 12 months",
        "own_line": f"{esc(country)} {pct(own)} · {place(s_rank, len(peers))}",
        "mid_line": f"Median: {pct(s_stats['median'])}",
        "q_line": f"25%: {pct(s_stats['q1'])}  ·  75%: {pct(s_stats['q3'])}",
        "values": peers, "stats": s_stats, "axis": (0.0, 100.0),
        "ticks": [(t, f"{t:.0f}%") for t in (0, 25, 50, 75, 100)],
        "own": {"name": country, "slug": subject_slug, "value": own},
        "kind": "share",
        "marks": marks_for("share"),
        "aria": (f"{country}: BEV share {pct(own)}, "
                 f"{'would be ' if is_region else ''}{ordinal(s_rank)} of {len(peers)} countries."),
    }]

    def add_year_strip(title: str, mark_key: str, peer_list, own_y, level_label: str,
                       ci=None) -> int:
        years = [(n, y) for n, y in (peer_list or []) if y is not None and math.isfinite(y)]
        y = own_y
        if y is None and not is_region:
            y = next((v for n, v in years if n == country), None)
        y_stats = box_stats([v for _, v in years]) if len(years) >= 10 else None
        if y is None or not math.isfinite(y) or not y_stats:
            return len(years)
        ends = [e for e in (ci or ()) if e is not None and math.isfinite(e)]
        lo = 5 * math.floor(min([y_stats["min"], y] + ends) / 5)
        hi = max(5 * math.ceil(max([y_stats["max"], y] + ends) / 5), lo + 20)
        y_rank = _rank_of(y, [v for _, v in years], higher_first=False)
        strips.append({
            "title": title,
            "own_line": (f"{esc(country)} {mc.year_text(y)} · "
                         f"{place(y_rank, len(years))}"),
            "mid_line": f"Median: {mc.year_text(y_stats['median'])}",
            "q_line": (f"25%: {mc.year_text(y_stats['q1'])}  ·  "
                       f"75%: {mc.year_text(y_stats['q3'])}"),
            "values": years, "stats": y_stats, "axis": (float(lo), float(hi)),
            "ticks": [(float(t), str(t)) for t in range(lo, hi + 1, 5)
                      if t % 10 == 0 or t in (lo, hi)],
            "kind": "year",
            "ci": tuple(ci) if ci else None,
            "ci_line": (f"Range: {mc._ci_text(ci)}" if ci else ""),
            "own": {"name": country, "slug": subject_slug, "value": y},
            "marks": marks_for(mark_key),
            "aria": (f"{country}: fitted curve reaches {level_label} in "
                     f"{mc.year_text(y)}, "
                     f"{'would be ' if is_region else ''}{ordinal(y_rank)} of "
                     f"{len(years)} countries, earliest first."),
        })
        return len(years)

    n_years = add_year_strip("Fitted curve reaches 50%", "year50",
                             peer_years, own_year, "50%", own_ci)
    add_year_strip("Fitted curve reaches 80%", "year80",
                   peer_years_80, own_year_80, "80%", own_ci_80)
    _unify_year_axes(strips)
    return strips, named, n_years


def build_compare(country: str, peers: list[tuple[str, float]], width: int,
                  highlights: list[dict] | None = None,
                  subject_slug: str = "", is_region: bool = False,
                  own_share: float | None = None,
                  peer_years: list[tuple[str, float]] | None = None,
                  own_year: float | None = None,
                  peer_years_80: list[tuple[str, float]] | None = None,
                  own_year_80: float | None = None) -> str:
    """The A4 "How it compares" section: the strips of compare_strips."""
    strips, named, n_years = compare_strips(
        country, peers, highlights, subject_slug, is_region, own_share,
        peer_years, own_year, peer_years_80, own_year_80)
    if not strips:
        return ""
    plot_w = width - CMP_LABEL_W
    body = "".join(_box_strip(m, plot_w, k=1.12) for m in strips)
    last_year = next((m for m in reversed(strips) if m.get("shared_ticks")), None)
    if last_year:
        body += _year_axis_row(last_year["axis"], last_year["shared_ticks"], plot_w, k=1.12)
    n = strips[0]["stats"]["n"]
    sub = f"Box = middle half of the {n} countries in the Gallery."
    if is_region:
        sub += " The group figure is this brief's weighted headline."
    return ('<section class="fl-sec fl-cmp"><h2>How it compares</h2>'
            f'<p class="fl-sub">{sub}</p>'
            f'<div class="fl-cmp-strips">{body}</div></section>')


def build_compare_social(country: str, peers: list[tuple[str, float]],
                         highlights: list[dict] | None = None, subject_slug: str = "",
                         is_region: bool = False, own_share: float | None = None,
                         width: int = 960, label_w: int = 300) -> tuple[str, int]:
    """The mini card's single strip: BEV share, last 12 months, as on the A4
    brief. Returns (html, height in px) or ("", 0)."""
    strips, _, _ = compare_strips(country, peers, highlights, subject_slug,
                                  is_region, own_share)
    if not strips:
        return "", 0
    m = dict(strips[0])
    m["mid_line"] = f"Box = middle half of {len(peers)} countries"
    m["q_line"] = ""
    k = 1.7
    html = _box_strip(m, width - label_w, k=k, cls="sc")
    return f'<div class="sc-cmp">{html}</div>', round((27 + 11 + 8 + 13) * k) + 14


def _x_to_pct(svg: str, width: float) -> str:
    """Horizontal positions as a share of the width, so the strip spans the
    column however wide the sheet is laid out (the brief is laid out wider
    than A4 and scaled to fit). Text and flags keep their pixel size; a flag
    is wrapped in a nested <svg> placed at its centre."""
    import re

    def pct(v: str) -> str:
        return f"{100 * float(v) / width:.3f}%"

    def image(m: re.Match) -> str:
        x, w = float(m.group(1)), float(m.group(3))
        rest = m.group(0).replace(f'x="{m.group(1)}"', f'x="{-w / 2:.1f}"', 1)
        return f'<svg x="{pct(str(x + w / 2))}" overflow="visible">{rest}</svg>'

    svg = re.sub(r'<image [^>]*?x="([-\d.]+)" y="([-\d.]+)" width="([\d.]+)"[^>]*/>', image, svg)
    svg = re.sub(r'(<rect\b[^>]*?) x="([-\d.]+)"([^>]*?) width="([\d.]+)"',
                 lambda m: f'{m.group(1)} x="{pct(m.group(2))}"{m.group(3)} width="{pct(m.group(4))}"',
                 svg)
    svg = re.sub(r'(<(?:line|text)\b[^>]*?) (x1|x2|x)="([-\d.]+)"',
                 lambda m: f'{m.group(1)} {m.group(2)}="{pct(m.group(3))}"', svg)
    # a second pass for the second coordinate on the same line element
    svg = re.sub(r'(<line\b[^>]*?) (x2)="([-\d.]+)"',
                 lambda m: f'{m.group(1)} {m.group(2)}="{pct(m.group(3))}"', svg)
    return svg


def _and_list(names: list[str]) -> str:
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f" and {names[-1]}"


# The curve is drawn this wide. The sheet is laid out wider than A4 and
# scaled to fit, so the old 452 px left the milestone table half empty;
# on a page that fits unscaled the chart shrinks with its column.
CURVE_W = 540

# Stated once per page, under "Where the curve points". Not repeated in
# the chart legend or the footer.
CURVE_MODEL_NOTE = (
    "An S-curve fitted to the BEV share so far. This is the project's model, "
    "not an actual forecast; it does not include policy changes and is based "
    "only on historical data.")
CURVE_MODEL_NOTE_GROUP = (
    "An S-curve fitted to the group's BEV share so far. This is the project's "
    "model, not an actual forecast; it does not include policy changes and is "
    "based only on historical data.")


def _brief_ytd(figures: dict, rows: list[dict]) -> dict | None:
    """YTD figure for the hero. Region briefs carry an explicit weighted YTD
    in figures["ytd"] (None ⇒ omit, #458); country briefs derive it from their
    own BEV/TOTAL rows via mc.ytd_window."""
    if "ytd" in figures:
        return figures["ytd"]
    return mc.ytd_window(rows)


def hero_chart_heights(figures: dict, rows: list[dict], spare: int = 0,
                       region: bool = False) -> tuple[int, int]:
    """The mix fills the number column; leftover brand-row slots go to both charts.

    The hero used to pin the mix at 132 px and align it to the bottom, which
    left a hole beside the big share. Size the mix to that column so the
    plot grows, not the padding.
    """
    ttm = figures.get("ttm")
    mix = 132
    if ttm:
        mix = 118
        if ttm.get("delta") is not None:
            mix += 32
        if figures.get("latest"):
            mix += 20
        if _brief_ytd(figures, rows):
            mix += 18
        mix = max(132, mix)
    # Compare is now three strips and the locator sits in the title row,
    # so leftover brand slots only get a modest lift (not a hole, and not
    # a shrink on a full page).
    # The mix is fluid in width; a little extra height keeps the plot from
    # becoming a wide ribbon once it fills the hero. Spare is modest now
    # that the mid-row holds brands / who-carries beside who-gained.
    mix += 24 + spare * 2
    curve = 160 + spare * 4
    if region:
        # Region briefs have no brand block; a short who-gained list should
        # not leave a gap above the footer.
        curve += 12
    if not ttm:
        # No full 12-month window (Malta): no headline, who-gained or
        # compare strip, so the page is half empty. Give it to the charts.
        mix += 40
        curve += 170
    return mix, curve


def hero_number(figures: dict, rows: list[dict]) -> str:
    """The brief's hero column: the 12-month BEV share and what sits under it."""
    hero_num = ""
    ttm = figures.get("ttm")
    if ttm:
        delta = ""
        if ttm["delta"] is not None:
            cls = "up" if ttm["delta"] >= 0.05 else "down" if ttm["delta"] <= -0.05 else "flat"
            delta = (f'<div class="fh-delta {cls}">{mc.points(ttm["delta"])} pts · '
                     'last 12 months</div>')
        month = ""
        latest, rng = figures.get("latest"), mc.share_range(rows)
        if latest:
            month += (f'<div class="fh-month">Single month · {esc(mc.period_label(latest["row"]["period"]))}: '
                      f'<b>{esc(mc.share(latest["share"]))}</b></div>')
        ytd = _brief_ytd(figures, rows)
        if ytd:
            month += (f'<div class="fh-month fh-ytd">Year to date · {esc(mc.period_label(ytd["from"]).split()[0])}–'
                      f'{esc(mc.period_label(ytd["to"]))}: '
                      f'<b>{esc(mc.share(ytd["share"]))}</b></div>')
        big = mc.share(ttm["share"]).removesuffix("%")
        hero_num = (
            '<div class="fh-num"><div class="fh-kicker">BEV share of new cars</div>'
            f'<div class="fh-big">{esc(big)}<span>%</span></div>'
            f'<div class="fh-what">12 months to {esc(mc.period_label(ttm["end"], long=True))}</div>'
            f'{delta}{month}</div>')
    return hero_num


def bars_section(shift: dict | None, fm: dict) -> str:
    """The 'Who gained, who lost' section: change in points per powertrain."""
    bars = ""
    if shift:
        (b0, b1), (a0, a1) = shift["span"]
        # EU brief: HEV from ACEA replaces the "full hybrid is kept in …" note.
        mix_note = fm.get("bars_note") or fm.get("mix_note") or ""
        note = (f'<p class="fl-sub fl-mixnote">{esc(mix_note)}</p>'
                if mix_note else "")
        # EU brief: ACEA's HEV row (its own window, labelled under the bars).

        bars = (
            '<section><h2>Who gained, who lost</h2>'
            f'<p class="fl-sub">Change in percentage points, '
            f'{esc(mc.vs_prior_phrase(a1))}.</p>{note}'
            f'<div class="fb">{build_bars(shift)}</div></section>')
    return bars


def facts_section(fm: dict, figures: dict, shift: dict | None) -> str:
    """The 'In numbers' section: up to four plain facts."""
    facts = []
    volume, record = figures.get("volume"), figures.get("record")
    # Region totals are weights, not a count of registrations; omit count facts.
    if fm.get("region"):
        volume = None
    if volume:
        sub = "last 12 months"
        if volume["growth"] is not None:
            sub += f', {mc.growth_phrase(volume["growth"])} vs the 12 months before'
        facts.append(_fact(mc.units(volume["total"]), "new registrations", sub))
        if volume["bev"] is not None:
            facts.append(_fact(mc.units(volume["bev"]), "of them battery electric", "last 12 months"))
    if shift and shift.get("bev_before") and not fm.get("region"):
        # Battery-electric volume, 12 months against the 12 before: both
        # windows complete, so no single month can swing it.
        growth = 100 * (shift["bev_after"] / shift["bev_before"] - 1)
        facts.append(_fact(mc.growth_phrase(growth), "battery-electric registrations",
                           "vs the 12 months before"))
    # Regions have no comparable registration count, and a "with a plug"
    # tile would steal width from the who-gained labels.
    if shift and not fm.get("region"):
        plug = next((r for r in shift["rows"] if r["key"] == "PHEV"), None)
        bev = next(r for r in shift["rows"] if r["key"] == "BEV")
        if plug and plug["after"] >= 0.05:
            facts.append(_fact(mc.share(bev["after"] + plug["after"]), "with a plug",
                               "BEV + plug-in hybrid, 12 months"))
    facts_html = (f'<section><h2>In numbers</h2><div class="fl-facts">{"".join(facts[:4])}'
                  '</div></section>') if facts else ""
    return facts_html


def two_block(fm: dict, bars: str, facts_html: str, market_html: str) -> tuple[str, str]:
    """Who-gained beside In-numbers (or beside a region's 'Who carries it').
    Returns (the two-column block, the market block still to place below)."""
    # Region "Who carries it" sits beside who-gained. Country brand lists
    # stay full width: in a narrow column the 0–100 % bars collapse to slivers.
    two = ""
    if bars and market_html and fm.get("region"):
        two = f'<div class="fl-sec fl-two fl-two-wide">{bars}{market_html}</div>'
        market_html = ""
    elif bars and facts_html:
        two = f'<div class="fl-sec fl-two">{bars}{facts_html}</div>'
    elif bars or facts_html:
        two = f'<div class="fl-sec fl-one">{bars}{facts_html}</div>'
    return two, market_html


def build_flyer(fm: dict, rows: list[dict], shift: dict | None, figures: dict,
                state: dict | None, bands: dict | None, theme_href: str,
                peers: list[tuple[str, float]] | None = None,
                market: dict | None = None, brand_mode: str = "logos",
                logo_href: str = "../../assets/brands",
                peer_years: list[tuple[str, float]] | None = None,
                peer_years_80: list[tuple[str, float]] | None = None,
                weak_curve: bool = False) -> str:
    country = fm.get("country", "")
    slug = fm.get("slug", "")
    hev_full = fm.get("hev_split") is True
    head, follow = verdict(country, figures, shift)
    through = mc.period_label(rows[-1]["period"], long=True) if rows else ""

    flag = mc.flag_img(slug, country, cls="fl-flag") or fm.get("mark_html") or ""
    # Locator lives in the title row, like the social card: room enough
    # for a readable Europe / Asia / world map without squeezing the mix.
    MAP_H = 92
    where = locator_map.build(fm.get("map_countries") or [country], MAP_H,
                              label=f"Where {country} is" if not fm.get("region")
                              else f"{country}: member countries")

    # Hero: the one number, and the mix over time.
    hero_num = hero_number(figures, rows)
    # Unused named-row slots (the fullest list is 5 + others) go to the charts
    # so a one- or two-brand market does not leave a hole on the sheet.
    # Region briefs have no brand block; give the charts a modest lift.
    if fm.get("region"):
        spare = 0 if fm.get("carriers_html") else 5
    else:
        spare = max(0, 5 - len((market or {}).get("named") or []))
    mix_h, curve_h = hero_chart_heights(figures, rows, spare, bool(fm.get("region")))
    # Number column is 236 px, hero gap 18 px; the mix takes the rest.
    mix_w = (INNER_W - 236 - 18) if hero_num else INNER_W
    mix = build_mix(fm.get("region_mix_points") or mix_points(rows), hev_full, mix_w, mix_h)
    range_line = ""
    rng = mc.share_range(rows)
    if rng:
        range_line = f'<p class="fh-range-line">{esc(mc.range_sentence(rng))}</p>'
    loc = f'<div class="fl-loc">{where}</div>' if where else ""
    hero = (f'<div class="fl-hero">{hero_num}'
            f'<div class="fh-mix">{mix}</div></div>{range_line}'
            if (hero_num or mix or range_line) else "")

    bars = bars_section(shift, fm)

    curve = ""
    if fm.get("region_curve"):
        builder = fm["region_curve"]
        # A4 already states the model caveat in the section sub; the mini
        # card still gets it in the legend (the default).
        try:
            svg, legend = builder(CURVE_W, curve_h, 42, False)
        except TypeError:
            svg, legend = builder(CURVE_W, curve_h, 42)
        side = fm.get("region_curve_side") or ""
        sub = fm.get("region_curve_sub") or CURVE_MODEL_NOTE_GROUP
        if svg:
            curve = (
                '<section class="fl-sec"><h2>Where the curve points</h2>'
                f'<p class="fl-sub">{esc(sub)}</p>'
                f'<div class="fl-curve"><div>{svg}{legend or ""}</div>'
                f'{side}</div></section>')
    elif state:
        svg = mc.build_curve_svg(rows, state, bands, width=CURVE_W, height=curve_h,
                                 weak_fit=weak_curve and not state["quotable"],
                                 zoom_weak=True)
        if svg and state["quotable"]:
            shown_ci = state["band_ok"] and '"fm-ci">passed' not in build_miles(state).replace(
                '<span class="fm-ci">passed</span>', "", 3) and "–" in build_miles(state)
            band = ('<p class="fm-note">95% confidence band.</p>' if shown_ci else "")
            if state["rel"]["status"] == "provisional":
                # Same caveat as the source page: the dates still move.
                band += ('<p class="fm-note">Provisional: the 80% year moved by '
                         f'{state["rel"]["swing"]:.0f} years across recent re-fits.</p>')

            curve = (
                '<section class="fl-sec"><h2>Where the curve points</h2>'
                f'<p class="fl-sub">{esc(CURVE_MODEL_NOTE)}</p>'
                f'<div class="fl-curve"><div>{svg}{mc.chart_legend(state, model_note=False)}</div>'
                '<div class="fm-side"><div class="fm-head">The curve reaches</div>'
                f'<div class="fm">{build_miles(state)}</div>{band}</div></div></section>')
        elif svg:
            why = ("The share is still too low and too flat to fit a curve that means "
                   "anything." if state["flat"] else
                   "A curve can be fitted, but it is not stable enough yet to give dates.")
            curve = (
                '<section class="fl-sec"><h2>The BEV share so far</h2>'
                '<p class="fl-sub">Battery-electric share of new registrations in each period, '
                'in percent.</p>'
                f'<div class="fl-curve"><div>{svg}{mc.chart_legend(state, weak=weak_curve)}</div>'
                f'<div class="fm-side"><div class="fm-head">No projection</div>'
                f'<p class="fm-none">{why}</p></div></div></section>')

    facts_html = facts_section(fm, figures, shift)
    market_html = fm.get("carriers_html") or mstr.build_block(market, brand_mode, logo_href)
    two, market_html = two_block(fm, bars, facts_html, market_html)

    source = (fm.get("source_name") or "").split("—")[0].strip()
    brand_src = mstr.brand_source(fm, market)
    url = f"{mc.SITE}/sources/{slug}.html"
    flyer_url = f"{mc.SITE}/sources/flyer/{slug}.html"
    if fm.get("region"):
        url = flyer_url = f"{mc.SITE}/sources/flyer/{slug}.html"
        source_line = (
            f'<p><b>Source:</b> {esc(source)}. '
            f'{esc(fm.get("scope_note") or fm.get("coverage_note") or "")}</p>')
        method = '<p>Scopes differ between countries.</p>'
        qr_cap = 'Current edition<br>and all countries'
    else:
        scope = _clip(mc.footnote(country) or fm.get("scope_note") or "", 140)
        source_line = f'<p><b>Source:</b> {esc(source)}.'
        if brand_src:
            source_line += f' Brands: {esc(brand_src)}.'
        if scope:
            source_line += f' {esc(scope)}'
        source_line += '</p>'
        method = ('<p>Scopes differ between countries. Method and every number: '
                  f'<a class="nw" href="../{esc(slug)}.html">{esc(url.replace("https://", ""))}</a></p>')
        qr_cap = 'Current edition<br>and all countries'
    foot = (
        '<footer class="fl-foot"><div class="fl-foot-text">'
        '<p><b>Abbreviations:</b> Battery electric (BEV): battery only. Plug-in hybrid: engine '
        'plus a battery charged from the grid. Hybrid: engine plus battery, no plug. '
        'Shares are of new registrations.</p>'
        + source_line + method + '</div>'
        f'<a class="fl-qrbox" href="{esc(flyer_url)}">{build_qr(flyer_url)}'
        f'<span>{qr_cap}</span></a>'
        '<p class="fl-brand"><span class="fl-b1"><b>BEV Trajectory Gallery</b> · @LeRaffl · '
        'charts and text CC BY 4.0</span></p>'
        f'<p class="fl-gen">{esc(mc.generated_line(rows[-1]["period"] if rows else ""))}</p>'
        '</footer>')
    highlights = fm.get("compare_highlights")
    if highlights is None:
        try:
            import region_card as _rc
            highlights = _rc.reference_points()
        except Exception:
            highlights = []
    own_share = (figures.get("ttm") or {}).get("share")
    curve_state = state if state is not None else fm.get("curve_state")
    compare = build_compare(country, peers or [], INNER_W,
                            highlights=highlights, subject_slug=slug,
                            is_region=bool(fm.get("region")),
                            own_share=own_share, peer_years=peer_years,
                            own_year=year_at_50(curve_state),
                            peer_years_80=peer_years_80,
                            own_year_80=year_at_80(curve_state))

    kicker = ("Region brief · the shift to battery-electric cars"
              if fm.get("region") else
              "Country brief · the shift to battery-electric cars")
    return FLYER_TEMPLATE.format(
        country=esc(country), theme_href=theme_href, css=FLYER_CSS, flag=flag,
        through=esc(through), head=esc(head), follow=esc(follow), hero=hero,
        loc=loc, two=two, market=market_html,
        curve=curve, foot=foot, compare=compare, slug=esc(slug),
        kicker=esc(kicker), w=SHEET_W, h=SHEET_H)


FLYER_CSS = mstr.CSS + """
html{background:#e9e7e1}
body{margin:0;background:#e9e7e1;color:var(--text);font-family:var(--font-ui),sans-serif}
.fl-bar{max-width:794px;margin:0 auto;padding:12px 8px;display:flex;gap:12px;align-items:center;
  font-size:13px}
.fl-bar a{color:var(--muted)}
.fl-bar button{margin-left:auto;font:inherit;padding:6px 14px;border-radius:8px;cursor:pointer;
  border:1px solid var(--text);background:var(--text);color:#fff;font-weight:600}
.sheet-box{margin:0 auto 32px}
.sheet{width:794px;height:1123px;box-sizing:border-box;padding:32px 46px 26px;background:#fdfdfc;
  box-shadow:0 2px 18px rgba(0,0,0,.14);overflow:hidden;
  transform-origin:top left;color-scheme:light;
  --text:#1a1a18;--muted:#55534c;--line:#dcd9d2}
.sheet-in{width:100%;min-height:100%;display:flex;flex-direction:column;transform-origin:top left}
.sheet *{-webkit-print-color-adjust:exact;print-color-adjust:exact}
.fl-top{display:flex;align-items:center;gap:14px;padding-bottom:10px;border-bottom:2px solid var(--text)}
.fl-flag,.fl-mark{width:54px;height:37px;object-fit:cover;border-radius:2px;box-shadow:0 0 0 1px var(--line);display:block}
.fl-mark{background:#eceae4}
.fl-top h1{font-family:var(--font-display);font-size:30px;line-height:1;margin:0;font-weight:600}
.fl-kick{font-size:11px;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);margin-top:5px}
.fl-loc{flex:none;margin-left:auto;line-height:0}
.fl-loc svg{display:block;height:92px;width:auto}
.fl-date{margin-left:auto;text-align:right;font-size:11px;letter-spacing:.06em;text-transform:uppercase;
  color:var(--muted);line-height:1.5}
.fl-loc + .fl-date{margin-left:0}
.fl-date b{display:block;font-size:15px;letter-spacing:0;text-transform:none;color:var(--text)}
.fl-head{font-family:var(--font-display);font-size:28px;line-height:1.16;font-weight:600;
  margin:10px 0 2px;letter-spacing:-.01em}
.fl-follow{font-family:var(--font-display);font-size:17px;line-height:1.35;margin:0;color:#3a3935;
  min-height:23px}
.fl-hero{display:flex;gap:18px;align-items:flex-start;margin:8px 0 0}
.fh-num{flex:none;width:236px}
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
.fh-month{font-size:12.5px;margin-top:6px;color:var(--muted)}
.fh-month b{color:#3a3935;font-weight:500}
.fh-range-line{font-size:12.5px;color:var(--muted);line-height:1.45;margin:6px 0 0;max-width:100%}
.acea-stale{color:#9a3324;font-weight:600}
.fh-ytd{margin-top:3px}
.fh-mix{flex:1;min-width:0}
.fh-mix .fl-mix,.fl-mix{width:100%;display:grid;
  grid-template-columns:26px minmax(0,1fr) var(--mix-lab,164px);align-items:stretch}
.mix-mid{position:relative;min-width:0;height:100%}
.mix-mid > svg{position:absolute;inset:0;width:100%;height:100%;display:block}
.mix-y,.mix-lab{display:block;overflow:visible}

.fh-mix svg text.mix-t{font-size:10.5px;fill:#3a3935;font-weight:600;
  font-family:var(--font-ui),system-ui,sans-serif}
.fl-mixnote{margin-top:.15em;color:#55534c}
.fl-svg{display:block}
.fl-svg text{font-size:11.5px;fill:#3a3935;font-family:var(--font-ui),sans-serif}
.fl-svg text.ax{fill:#77746c;font-size:10.5px}
.fl-svg text.strong{font-weight:700;fill:#1f6a43}
.fl-svg text.hl{fill:#3a3935;font-size:9.5px}
.wc-flag{display:block;width:22px;height:15px;object-fit:cover;border-radius:1px;
  box-shadow:0 0 0 1px var(--line);flex:none}
.wc-bev{text-align:right;font-variant-numeric:tabular-nums;color:#55534c;font-size:12px}
.wc-list{--ms-logo:24px;--ms-name:120px;--ms-pct:56px;--ms-row:20px}
.wc-head,.wc-row{display:grid;grid-template-columns:calc(var(--ms-logo) + 8px + var(--ms-name)) 56px minmax(0,1fr) var(--ms-pct);
  column-gap:10px;align-items:center}
.wc-head{align-items:end;font-size:9px;line-height:1.2;color:var(--muted);font-weight:600;
  text-align:right;margin-bottom:4px;height:auto}
.wc-row{height:var(--ms-row);font-size:13px}
.wc-list .wc-row + .wc-row{margin-top:3px}
.fl-sec{margin-top:8px}
.fl-sec h2{font-family:var(--font-display);font-size:18px;margin:0;font-weight:600;border:0;padding:0}
.fl-sub{font-size:11.5px;color:var(--muted);margin:2px 0 8px;line-height:1.4}
.fb-row,.fb-head{display:grid;grid-template-columns:142px 1fr 52px 102px;column-gap:8px}
.fb-head{align-items:end;font-size:9px;line-height:1.2;color:var(--muted);font-weight:600;
  text-align:right;margin-bottom:3px}
.fb-row{align-items:center;font-size:13px;height:20px}
.fb-name{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fb-track{position:relative;height:20px}
.fb-zero{position:absolute;top:0;bottom:0;border-left:1px solid #77746c}
.fb-bar{position:absolute;top:4px;bottom:4px;border-radius:2px;min-width:2px}
.fb-pp{text-align:right;font-weight:700;font-variant-numeric:tabular-nums}
.fb-now{text-align:right;color:var(--muted);font-variant-numeric:tabular-nums}
.fl-curve{display:grid;grid-template-columns:minmax(0,1fr) 250px;column-gap:22px;align-items:stretch}
.fl-curve .curve{width:100%;height:auto;display:block}
.fl-curve>div:first-child{min-width:0}
.fl-curve .curve text{font-size:10.5px;fill:#77746c;font-family:var(--font-ui),sans-serif}
.cv-grid{stroke:#e4e2dd;stroke-width:1}
.cv-ci{fill:#3d9a68;fill-opacity:.2}
.cv-fit{fill:none;stroke:#2c7a50;stroke-width:2.2}
.cv-weak{stroke-dasharray:5 4;stroke:#8d897c}
.cv-pt{fill:#55534c;fill-opacity:.55}
.cv-est{fill:none;stroke:#55534c}
.cv-step{fill:none;stroke:#3a3935;stroke-width:1.4;stroke-linejoin:miter}
.cv-step-est{stroke-dasharray:3 2}
.cv-rise{fill:none;stroke:#3a3935;stroke-width:.8}
.cv-ttm{fill:none;stroke:#154a30;stroke-width:2;stroke-linejoin:round}
.cv-pt-bg{fill-opacity:.18}
.cv-now{stroke:#8d897c;stroke-width:1;stroke-dasharray:2 3}
.fl-legend{font-size:10.5px;color:var(--muted);margin:2px 0 0 30px}
.cv-leg{display:flex;flex-wrap:wrap;align-items:center;gap:2px 10px;margin:3px 0 0 28px;
  font-size:10.5px;color:var(--muted)}
.cv-leg-i{display:inline-flex;align-items:center;gap:4px;white-space:nowrap}
.cv-g{display:block;flex:none}
.cv-leg-note{font-style:italic}
.fm-side{min-width:0;padding-top:0;display:flex;flex-direction:column}
.fm-head{font-size:11.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);
  margin-bottom:4px}
.fm{flex:1;display:flex;flex-direction:column;justify-content:space-evenly}
.fm-row{display:grid;grid-template-columns:48px 86px 1fr;column-gap:8px;align-items:center;
  border-bottom:1px solid var(--line);padding:6px 0;flex:1}
.fm-lvl{font-size:14px;color:var(--muted)}
.fm-year{font-family:var(--font-display);font-size:24px;font-weight:600;line-height:1;
  font-variant-numeric:tabular-nums}
.fm-ci{font-size:12px;color:var(--muted);text-align:right;font-variant-numeric:tabular-nums}
.fm-past .fm-year{color:#8d897c;font-weight:500}
.fm-note{font-size:10.5px;color:var(--muted);margin:6px 0 0}
.fm-none{font-family:var(--font-display);font-size:15.5px;line-height:1.35;margin:6px 0 0}
.fl-two{display:grid;grid-template-columns:1fr 236px;column-gap:28px}
.fl-two-wide{grid-template-columns:1fr 1fr;column-gap:22px}
.fl-two-wide .wc-list h2{font-size:16px}
.fl-two-wide .fb-row,.fl-two-wide .fb-head{grid-template-columns:110px 1fr 44px 72px;column-gap:6px}
.fl-facts{display:grid;grid-template-columns:1fr 1fr;column-gap:14px;margin-top:6px}
.ff{padding:6px 0 7px;border-top:1px solid var(--line)}
.ff-n{font-family:var(--font-display);font-size:21px;font-weight:600;line-height:1.1;
  font-variant-numeric:tabular-nums}
.ff-l{font-size:11.5px;margin-top:1px;line-height:1.25}
.ff-s{font-size:10.5px;color:var(--muted);line-height:1.25}
.fl-one .fl-facts{grid-template-columns:repeat(4,1fr)}
.fl-foot{margin-top:auto;padding-top:10px;font-size:11px;line-height:1.5;color:var(--muted);
  display:flex;flex-wrap:wrap;column-gap:18px;align-items:flex-end}
.nw{white-space:nowrap}
.fl-foot-text{flex:1;min-width:0}
.fl-qrbox{flex:none;display:block;text-align:center;font-size:8.5px;line-height:1.25;
  color:var(--muted);text-decoration:none;width:84px}
.fl-qr{display:block;margin:0 auto 3px}
.fl-cmp .fl-sub{margin-bottom:2px}
.fl-cmp-strips{display:grid;grid-template-columns:176px minmax(0,1fr);align-items:end;row-gap:2px}
.fl-bx{display:contents}
.fl-bx-l{display:flex;flex-direction:column;font-size:11.5px;line-height:1.32;color:var(--muted);
  padding-bottom:8px}
.fl-bx-l-tight{padding-bottom:2px}
.fl-cmp-axis-l{min-height:0}
.fl-cmp-axis{display:block;margin-top:0}
.fl-bx-l b{color:var(--text);font-size:12px}
.fl-bx-own{color:#2c7a50;font-weight:600}
.fl-bx-own b{color:#2c7a50}
.fl-cmp-svg text.ax{font-size:11.5px}
.fl-cmp .fl-sub b{color:var(--text)}
.fl-foot p{margin:0 0 5px}
.fl-foot a{color:inherit}
.fl-foot b{color:var(--text)}
.fl-brand{flex-basis:100%;margin:6px 0 0!important;padding-top:6px;border-top:2px solid var(--text);
  color:var(--text);font-size:11px;display:flex;justify-content:space-between}
.fl-brand span{color:var(--muted)}
.fl-brand .fl-b1{color:var(--text)}
.fl-gen{flex-basis:100%;margin:2px 0 0!important;font-size:9.5px;color:var(--muted);letter-spacing:.01em}
@page{size:A4;margin:0}
@media print{
  html,body{background:#fff}
  .fl-bar{display:none}
  .sheet-box{margin:0;width:auto!important;height:auto!important}
  .sheet{box-shadow:none;transform:none!important}
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
<div class="fl-bar"><a href="./">← All country briefs</a>
  <a href="../{slug}.html">{country}: sources and method</a>
  <button type="button" onclick="window.print()">Save as PDF</button></div>
<div class="sheet-box"><article class="sheet"><div class="sheet-in">
  <header class="fl-top">{flag}
    <div><h1>{country}</h1><div class="fl-kick">{kicker}</div></div>
    {loc}
    <div class="fl-date">Data through<b>{through}</b></div></header>
  <p class="fl-head">{head}</p>
  <p class="fl-follow">{follow}</p>
  {hero}
  {two}
  {market}
  {curve}
  {compare}
  {foot}
</div></article></div>
<script>
(function(){{
  var box=document.querySelector('.sheet-box'),sheet=box.firstElementChild,inn=sheet.firstElementChild;
  // Fonts differ between machines. If the content is taller than the sheet,
  // shrink it as a whole so the page never loses its footer.
  function fitIn(){{
    // The largest scale at which the whole page fits. Laid out wider (100/z %)
    // the text wraps less, so the first guess have/height leaves a gap above
    // the footer; a short bisection closes it.
    var cs=getComputedStyle(sheet),have=sheet.clientHeight-parseFloat(cs.paddingTop)-parseFloat(cs.paddingBottom),z=1;
    inn.style.transform='';inn.style.width='';inn.style.minHeight='0';
    function fits(k){{inn.style.width=(100/k)+'%';return inn.scrollHeight*k<=have+0.5;}}
    if(!fits(1)){{
      var lo=Math.min(1,have/inn.scrollHeight)*0.9,hi=1;
      for(var i=0;i<12&&!fits(lo);i++)lo*=0.9;
      for(var j=0;j<10;j++){{var m=(lo+hi)/2;if(fits(m))lo=m;else hi=m;}}
      z=lo;
    }}
    if(z<1){{inn.style.width=(100/z)+'%';inn.style.minHeight=(100/z)+'%';inn.style.transform='scale('+z+')';}}
    else{{inn.style.width='';inn.style.minHeight='';}}
    sheet.dataset.fit=z.toFixed(3);
  }}
  function fit(){{
    var s=Math.min(1,(document.documentElement.clientWidth-16)/{w});
    sheet.style.transform=s<1?'scale('+s+')':'';
    box.style.width=({w}*s)+'px';box.style.height=({h}*s)+'px';
  }}
  fitIn();fit();addEventListener('resize',fit);
  if(document.fonts&&document.fonts.ready)document.fonts.ready.then(fitIn);
}})();
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------
# The directory of all briefs, sources/flyer/index.html
# --------------------------------------------------------------------------

def build_index(items: list[dict], theme_href: str,
                regions: list[dict] | None = None) -> str:
    """`items`: country, slug, share, delta, head, through. Highest share first.
    `regions`: the same fields for the group briefs, listed below the countries."""
    cards = []
    for n, item in enumerate(sorted(items, key=lambda i: -(i["share"] or -1)), 1):
        src = mc.flag_src(item["slug"], item["country"])
        flag = (f'<img src="{esc(src)}" alt="">' if src
                else '<span class="ix-noflag"></span>')
        num = mc.share(item["share"]) if item["share"] is not None else "—"
        if item["delta"] is not None:
            cls = "up" if item["delta"] >= 0.05 else "down" if item["delta"] <= -0.05 else "flat"
            delta = f'<span class="ix-d {cls}">{mc.points(item["delta"])}</span>'
        else:
            delta = '<span class="ix-d-none"></span>'
        cards.append(
            f'<a class="ix-card" href="{esc(item["slug"])}.html">'
            f'<span class="ix-rank">{n}</span>{flag}'
            f'<span class="ix-name">{esc(item["country"])}</span>'
            f'<span class="ix-num">{esc(num)}</span>{delta}'
            f'<span class="ix-head">{esc(item["head"])}</span>'
            f'<span class="ix-date">{esc(item["through"])}</span></a>')
    region_html = ""
    if regions:
        rcards = []
        for item in sorted(regions, key=lambda i: -(i["share"] or -1)):
            src = mc.flag_src(item["slug"], item["country"])
            flag = (f'<img src="{esc(src)}" alt="">' if src
                    else '<span class="ix-noflag"></span>')
            num = mc.share(item["share"]) if item["share"] is not None else "—"
            if item["delta"] is not None:
                cls = "up" if item["delta"] >= 0.05 else "down" if item["delta"] <= -0.05 else "flat"
                delta = f'<span class="ix-d {cls}">{mc.points(item["delta"])}</span>'
            else:
                delta = '<span class="ix-d-none"></span>'
            rcards.append(
                f'<a class="ix-card" href="{esc(item["slug"])}.html">'
                f'<span class="ix-rank"></span>{flag}'
                f'<span class="ix-name">{esc(item["country"])}</span>'
                f'<span class="ix-num">{esc(num)}</span>{delta}'
                f'<span class="ix-head">{esc(item["head"])}</span>'
                f'<span class="ix-date">{esc(item["through"])}</span></a>')
        region_html = (
            '<h2 class="ix-h2">Region briefs</h2>'
            '<p class="lead">The same sheet for groups of countries, weighted from the '
            'member sources over one common 12-month window. Scopes differ between '
            'members; each brief names the countries that carry the figure.</p>'
            '<div class="ix-headrow"><span></span><span></span><span>Region</span>'
            '<span class="r">BEV share</span><span>Change, pts</span><span>In one sentence</span>'
            '<span class="r">Data through</span></div>' + "".join(rcards))
    return INDEX_TEMPLATE.format(theme_href=theme_href, css=INDEX_CSS,
                                 n=len(items), cards="".join(cards), regions=region_html)


INDEX_CSS = """
.wrap{max-width:980px;margin:0 auto;padding:28px 18px 64px}
.back{display:inline-block;margin-bottom:18px;color:var(--muted);font-size:14px}
h1{font-size:30px;margin:0 0 8px}
.lead{color:var(--muted);font-size:16px;margin:0 0 22px;max-width:44em}
.ix-headrow,.ix-card{display:grid;grid-template-columns:30px 34px minmax(110px,1.1fr) 78px 64px 3fr 82px;
  column-gap:12px;align-items:center}
.ix-headrow{font-size:12px;color:var(--muted);letter-spacing:.05em;text-transform:uppercase;
  padding:0 8px 6px;border-bottom:1.5px solid var(--text)}
.ix-card{padding:9px 8px;border-bottom:1px solid var(--line);color:var(--text);font-size:15px}
.ix-card:hover{background:var(--accent-wash);text-decoration:none}
.ix-rank{color:var(--muted);font-size:13px;text-align:right;font-variant-numeric:tabular-nums}
.ix-card img{width:30px;height:20px;object-fit:cover;border-radius:2px;box-shadow:0 0 0 1px var(--line)}
.ix-name{font-weight:600}
.ix-num{font-family:var(--font-display);font-size:19px;font-weight:600;text-align:right;
  font-variant-numeric:tabular-nums}
.ix-d{font-size:12.5px;font-weight:700;padding:1px 8px;border-radius:999px;justify-self:start;
  font-variant-numeric:tabular-nums}
.ix-d.up{background:#dcefe4;color:#1f6a43}.ix-d.down{background:#f6e0dc;color:#9a3324}
.ix-d.flat{background:#eceae4;color:#55534c}
.ix-head{color:var(--muted);font-size:14px}
.ix-date{color:var(--muted);font-size:12.5px;text-align:right;white-space:nowrap}
.r{text-align:right}
.ix-h2{font-size:22px;margin:36px 0 8px}
@media (max-width:700px){
  .ix-headrow{display:none}
  .ix-card{grid-template-columns:24px 30px 1fr auto auto;row-gap:2px}
  .ix-head{grid-column:3/-1}.ix-date{display:none}
}
"""

INDEX_TEMPLATE = """<!doctype html>
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Country briefs — the shift to battery-electric cars · BEV Trajectories</title>
<meta name="description" content="One page per country: how far the shift to battery-electric cars has come, who gained, who lost, and where the curve points.">
<link rel="stylesheet" href="{theme_href}">
<style>{css}</style>
</head>
<body>
<div class="wrap">
  <a class="back" href="../">← Data sources</a>
  <h1>Country briefs</h1>
  <p class="lead">One page per country on the shift to battery-electric cars: where it stands,
    who gained and who lost, and where the fitted curve points. Each brief is a single A4
    sheet that saves as PDF, rebuilt whenever new data arrives. {n} countries, highest
    battery-electric share first.</p>
  <div class="ix-headrow"><span></span><span></span><span>Country</span>
    <span class="r">BEV share</span><span>Change, pts</span><span>In one sentence</span>
    <span class="r">Data through</span></div>
  {cards}
  {regions}
  <p class="lead" style="font-size:13px;margin-top:18px">BEV share: battery-electric share of new
    registrations over the last 12 months, as each source counts them. "Change, pts": change in
    percentage points, last 12 months vs the 12 months before. Scopes differ between countries; each
    brief names its source.</p>
</div>
</body>
</html>
"""
