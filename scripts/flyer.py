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
    "Combustion + hybrids": "Other powertrains",
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
    plot_w, plot_h = width - left - right, height - top - bottom
    t0, t1 = points[0]["t"], points[-1]["t"]

    def x_of(t: float) -> float:
        return left + plot_w * (t - t0) / ((t1 - t0) or 1)

    def y_of(v: float) -> float:
        return top + plot_h * (1 - max(0.0, min(100.0, v)) / 100)

    parts = [
        f'<text x="{left}" y="12" class="mix-t">Trailing 12-month share by powertrain</text>'
    ]
    base = [0.0] * len(points)
    labels = []
    end = points[-1]
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


def build_compare(country: str, peers: list[tuple[str, float]], width: int,
                  highlights: list[dict] | None = None,
                  subject_slug: str = "", is_region: bool = False,
                  own_share: float | None = None) -> str:
    """Every country in the gallery on one line, this one marked, plus a
    handful of named reference points with flags (Norway, China, EU, …).

    `peers` is (country, 12-month BEV share in percent) under the same
    full-window rule as each brief. Region highlights must already carry
    their weighted headline share. The subject is never also a highlight.
    """
    own = own_share
    if own is None:
        own = next((v for name, v in peers if name == country), None)
    if own is None or len(peers) < 10:
        return ""
    ranked = sorted(peers, key=lambda item: -item[1])
    rank = None
    if not is_region and any(name == country for name, _ in peers):
        rank = [name for name, _ in ranked].index(country) + 1
    values = sorted(v for _, v in peers)
    mid = len(values) // 2
    median = values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2
    left, right, base = 10, 10, 76
    plot = width - left - right
    height = 98

    def x_of(v: float) -> float:
        return left + plot * max(0.0, min(100.0, v)) / 100

    marks = []
    for h in highlights or []:
        if h.get("name") == country:
            continue
        share = h.get("share")
        if share is None or share != share:
            continue
        marks.append(dict(h))

    parts = [f'<line x1="{left}" y1="{base}" x2="{left + plot}" y2="{base}" stroke="#bdb9af"/>']
    for tick in (0, 25, 50, 75, 100):
        anchor = "start" if tick == 0 else "end" if tick == 100 else "middle"
        parts.append(f'<text x="{x_of(tick):.1f}" y="{base + 14}" text-anchor="{anchor}" '
                     f'class="ax">{tick}%</text>')
    for name, v in peers:
        if name != country:
            parts.append(f'<line x1="{x_of(v):.1f}" y1="{base - 8}" x2="{x_of(v):.1f}" '
                         f'y2="{base}" stroke="#8d897c" stroke-opacity=".55" stroke-width="1.3"/>')
    peer_names = {name for name, _ in peers}
    for h in marks:
        if h["name"] not in peer_names:
            x = x_of(h["share"])
            parts.append(f'<line x1="{x:.1f}" y1="{base - 8}" x2="{x:.1f}" '
                         f'y2="{base}" stroke="#8d897c" stroke-width="1.6"/>')

    fw, fh = 18, 12
    # Flags stack upward when their slots would overlap.
    flag_items = ([{"name": country, "share": own, "slug": subject_slug, "subject": True}]
                  + [{**h, "subject": False} for h in marks])
    flag_items.sort(key=lambda n: n["share"])
    placed_flags: list[tuple[float, float]] = []
    for item in flag_items:
        x = x_of(item["share"])
        fy = base - 10 - fh
        while any(abs(px - x) < fw + 2 and abs(py - fy) < fh + 2 for px, py in placed_flags):
            fy -= fh + 4
        item["fx"], item["fy"] = x, fy
        placed_flags.append((x, fy))
        src = mc.flag_src(item.get("slug") or "", item["name"])
        if src:
            parts.append(f'<image href="{esc(src)}" x="{x - fw/2:.1f}" y="{fy:.1f}" '
                         f'width="{fw}" height="{fh}"/>')

    xo = x_of(own)
    parts.append(f'<line x1="{xo:.1f}" y1="{base - 16}" x2="{xo:.1f}" y2="{base + 1}" '
                 'stroke="#2c7a50" stroke-width="3.2"/>')

    def _tw(text: str, heavy: bool = False) -> float:
        return (7.4 if heavy else 6.2) * len(text) + 4

    boxes: list[tuple[float, float, float, float]] = []

    def box_of(text, lx, y, anchor, heavy):
        w = _tw(text, heavy)
        if anchor == "start":
            return (lx, y - 11, lx + w, y + 2)
        if anchor == "end":
            return (lx - w, y - 11, lx, y + 2)
        return (lx - w / 2, y - 11, lx + w / 2, y + 2)

    def free(box, pad=6):
        def ov(a, b):
            return not (a[2] + pad < b[0] or b[2] + pad < a[0]
                        or a[3] + pad < b[1] or b[3] + pad < a[1])
        return box[0] >= 2 and box[2] <= width - 2 and not any(ov(box, b) for b in boxes)

    def draw_label(text, lx, y, anchor, heavy=False):
        box = box_of(text, lx, y, anchor, heavy)
        boxes.append(box)
        klass = "strong" if heavy else "hl"
        parts.append(
            f'<text x="{lx:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
            f'class="{klass}" stroke="#fdfdfc" stroke-width="3" '
            f'paint-order="stroke">{esc(text)}</text>')

    nodes = ([{"name": country, "share": own, "text":
               f"{country} {mc.share(own).replace(' %', '%')}", "heavy": True,
               "x": xo}]
             + [{"name": h["name"], "share": h["share"],
                 "text": f"{h['name']} {h['share']:.0f}%", "heavy": False,
                 "x": x_of(h["share"])} for h in marks])
    nodes.sort(key=lambda n: n["share"])
    # Clusters of points closer than 10 pts share a vertical stack.
    clusters: list[list[dict]] = []
    for n in nodes:
        if clusters and n["share"] - clusters[-1][-1]["share"] < 10:
            clusters[-1].append(n)
        else:
            clusters.append([n])

    slots = [(16, "end"), (16, "start"), (30, "end"), (30, "start"),
             (44, "end"), (44, "start")]
    for cluster in clusters:
        # Subject in a cluster keeps the first row, on the side facing
        # the more open side of the scale (away from the cluster mean).
        mean = sum(n["share"] for n in cluster) / len(cluster)
        ordered = sorted(cluster, key=lambda n: (not n["heavy"], n["share"]))
        used = 0
        for n in ordered:
            placed = False
            # Try preferred side first: away from the cluster centre,
            # or, for an isolated point, away from the edges.
            want_end = n["x"] > x_of(mean) if len(cluster) > 1 else n["x"] > width * 0.55
            cand = (slots[1:] + slots[:1]) if not want_end else slots[:]
            # Isolated points (cluster of 1) prefer a single top row.
            if len(cluster) == 1:
                cand = ([(16, "start"), (16, "end"), (30, "start"), (30, "end")]
                        if not want_end else
                        [(16, "end"), (16, "start"), (30, "end"), (30, "start")])
            for y, anchor in cand:
                lx = n["x"] + (12 if anchor == "start" else -12)
                if free(box_of(n["text"], lx, y, anchor, n["heavy"])):
                    draw_label(n["text"], lx, y, anchor, n["heavy"])
                    placed = True
                    break
            if not placed:
                # Fall back to the next free slot, no dumping on one point.
                for y, anchor in slots:
                    lx = n["x"] + (12 if anchor == "start" else -12)
                    if free(box_of(n["text"], lx, y, anchor, n["heavy"])):
                        draw_label(n["text"], lx, y, anchor, n["heavy"])
                        placed = True
                        break
            if not placed:
                draw_label(n["text"], n["x"], 12, "middle", n["heavy"])

    if is_region:
        label = (f"{country} compared with individual countries by BEV share "
                 f"of new cars, last 12 months.")
        named = [h["name"] for h in marks]
        sub = (f'BEV share of new cars, last 12 months. Each line is one country. '
               f'The group figure is the weighted headline on this brief.')
        if named:
            sub += f' Highlighted: {_and_list(named)}.'
    else:
        label = (f"{country} ranks {ordinal(rank)} of {len(peers)} countries by BEV share.")
        sub = (f'<b>{ordinal(rank)} of {len(peers)}</b> countries by BEV share of '
               f'new cars, last 12 months. Each line is one country; the middle one is at '
               f'{mc.share(median).replace(" %", "%")}.')
        named = [h["name"] for h in marks]
        if named:
            sub += f' Highlighted: {_and_list(named)}.'
    svg = (f'<svg class="fl-svg fl-cmp-svg" width="100%" height="{height}" '
           f'role="img" aria-label="{esc(label)}">{_x_to_pct("".join(parts), width)}</svg>')
    return (
        '<section class="fl-sec fl-cmp"><h2>How it compares</h2>'
        f'<p class="fl-sub">{sub}</p>{svg}</section>')


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
        if mc.ytd_window(rows):
            mix += 18
        mix = max(132, mix)
    mix += spare * 8
    curve = 160 + spare * 14
    if region:
        # Region briefs have no brand block; a short who-gained list should
        # not leave a gap above the footer.
        curve += 28
    if not ttm:
        # No full 12-month window (Malta): no headline, who-gained or
        # compare strip, so the page is half empty. Give it to the charts.
        mix += 40
        curve += 170
    return mix, curve


def build_flyer(fm: dict, rows: list[dict], shift: dict | None, figures: dict,
                state: dict | None, bands: dict | None, theme_href: str,
                peers: list[tuple[str, float]] | None = None,
                market: dict | None = None, brand_mode: str = "chips",
                logo_href: str = "../../assets/brands") -> str:
    country = fm.get("country", "")
    slug = fm.get("slug", "")
    hev_full = fm.get("hev_split") is True
    head, follow = verdict(country, figures, shift)
    through = mc.period_label(rows[-1]["period"], long=True) if rows else ""

    flag = mc.flag_img(slug, country, cls="fl-flag") or fm.get("mark_html") or ""
    where = locator_map.build(fm.get("map_countries") or [country], 150,
                              label=f"Where {country} is" if not fm.get("region")
                              else f"{country}: member countries")

    # Hero: the one number, and the mix over time.
    hero_num = ""
    ttm, latest = figures.get("ttm"), figures.get("latest")
    if ttm:
        delta = ""
        if ttm["delta"] is not None:
            cls = "up" if ttm["delta"] >= 0.05 else "down" if ttm["delta"] <= -0.05 else "flat"
            delta = (f'<div class="fh-delta {cls}">{mc.points(ttm["delta"])} pts · '
                     'last 12 months</div>')
        month = ""
        latest, rng = figures.get("latest"), mc.share_range(rows)
        if latest:
            month += (f'<div class="fh-month">{esc(mc.period_label(latest["row"]["period"]))} '
                      f'alone: <b>{esc(mc.share(latest["share"]))}</b></div>')
        ytd = mc.ytd_window(rows)
        if ytd:
            month += (f'<div class="fh-month fh-ytd">{esc(mc.period_label(ytd["from"]).split()[0])}–'
                      f'{esc(mc.period_label(ytd["to"]))} so far: '
                      f'<b>{esc(mc.share(ytd["share"]))}</b></div>')
        big = mc.share(ttm["share"]).replace(" %", "")
        hero_num = (
            '<div class="fh-num"><div class="fh-kicker">BEV share of new cars</div>'
            f'<div class="fh-big">{esc(big)}<span>%</span></div>'
            f'<div class="fh-what">12 months to {esc(mc.period_label(ttm["end"], long=True))}</div>'
            f'{delta}{month}</div>')
    # Unused named-row slots (the fullest list is 5 + others) go to the charts
    # so a one- or two-brand market does not leave a hole on the sheet.
    # Region briefs have no brand block; give the charts a modest lift.
    if fm.get("region"):
        spare = 0 if fm.get("carriers_html") else 5
    else:
        spare = max(0, 5 - len((market or {}).get("named") or []))
    mix_h, curve_h = hero_chart_heights(figures, rows, spare, bool(fm.get("region")))
    # Without a headline number the mix spans the row; leave room for the map.
    mix_w = 470 if hero_num else (INNER_W - 200 if where else INNER_W)
    mix = build_mix(fm.get("region_mix_points") or mix_points(rows), hev_full, mix_w, mix_h)
    range_line = ""
    rng = mc.share_range(rows)
    if rng:
        range_line = f'<p class="fh-range-line">{esc(mc.range_sentence(rng))}</p>'
    # The locator map takes the room right of the mix: the sheet is laid out
    # wider than A4 and scaled to fit, so a fixed-width mix left it empty.
    loc = f'<div class="fh-loc">{where}</div>' if where else ""
    hero = (f'<div class="fl-hero{" has-loc" if loc else ""}">{hero_num}'
            f'<div class="fh-mix">{mix}</div>{loc}</div>{range_line}'
            if (hero_num or mix or range_line) else "")

    bars = ""
    if shift:
        (b0, b1), (a0, a1) = shift["span"]
        mix_note = fm.get("mix_note") or ""
        note = (f'<p class="fl-sub fl-mixnote">{esc(mix_note)}</p>'
                if mix_note else "")
        # EU brief: ACEA's HEV row (its own window, labelled under the bars).
        bar_shift = shift
        acea_note = ""
        if fm.get("acea_shift_row"):
            bar_shift = {**shift, "rows": list(shift["rows"]) + [fm["acea_shift_row"]]}
            acea_note = fm.get("acea_shift_note") or ""
        bars = (
            '<section><h2>Who gained, who lost</h2>'
            f'<p class="fl-sub">Change in percentage points, '
            f'{esc(mc.vs_prior_phrase(a1))}.</p>{note}'
            f'<div class="fb">{build_bars(bar_shift)}</div>{acea_note}</section>')

    curve = ""
    if fm.get("region_curve"):
        svg, legend = fm["region_curve"](CURVE_W, curve_h, 42)
        side = fm.get("region_curve_side") or ""
        sub = fm.get("region_curve_sub") or (
            "Battery-electric share of new registrations. The line is this "
            "project's fitted model for the group, not an official forecast.")
        if svg:
            curve = (
                '<section class="fl-sec"><h2>Where the curve points</h2>'
                f'<p class="fl-sub">{esc(sub)}</p>'
                f'<div class="fl-curve"><div>{svg}{legend or ""}</div>'
                f'{side}</div></section>')
    elif state:
        svg = mc.build_curve_svg(rows, state, bands, width=CURVE_W, height=curve_h, weak_fit=False)
        if svg and state["quotable"]:
            shown_ci = state["band_ok"] and '"fm-ci">passed' not in build_miles(state).replace(
                '<span class="fm-ci">passed</span>', "", 3) and "–" in build_miles(state)
            band = ('<p class="fm-note">95 % confidence band.</p>' if shown_ci else "")
            if state["rel"]["status"] == "provisional":
                # Same caveat as the source page: the dates still move.
                band += ('<p class="fm-note">Provisional: the 80 % year moved by '
                         f'{state["rel"]["swing"]:.0f} years across recent re-fits.</p>')
            curve = (
                '<section class="fl-sec"><h2>Where the curve points</h2>'
                '<p class="fl-sub">An S-curve fitted to the BEV share so far. It is this '
                "project's model, not an official forecast: a policy change or a stall "
                'is not in it.</p>'
                f'<div class="fl-curve"><div>{svg}{mc.chart_legend(state)}</div>'
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
                f'<div class="fl-curve"><div>{svg}{mc.chart_legend(state)}</div>'
                f'<div class="fm-side"><div class="fm-head">No projection</div>'
                f'<p class="fm-none">{why}</p></div></div></section>')

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
    two = ""
    if bars and facts_html:
        two = f'<div class="fl-sec fl-two">{bars}{facts_html}</div>'
    elif bars or facts_html:
        two = f'<div class="fl-sec fl-one">{bars}{facts_html}</div>'

    source = (fm.get("source_name") or "").split("—")[0].strip()
    brand_src = mstr.brand_source(fm, market)
    url = f"{mc.SITE}/sources/{slug}.html"
    flyer_url = f"{mc.SITE}/sources/flyer/{slug}.html"
    if fm.get("region"):
        url = flyer_url = mc.SITE
        source_line = (
            f'<p><b>Source:</b> {esc(source)}. '
            f'{esc(fm.get("scope_note") or fm.get("coverage_note") or "")}</p>')
        method = '<p>Scopes differ between countries.</p>'
        qr_cap = 'Gallery home'
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
        '<p><b>How to read it.</b> Battery electric (BEV): battery only. Plug-in hybrid: engine '
        'plus a battery charged from the grid. Hybrid: engine plus battery, no plug. '
        'Shares are of new registrations.</p>'
        + source_line + method + '</div>'
        f'<a class="fl-qrbox" href="{esc(flyer_url)}">{build_qr(flyer_url)}'
        f'<span>{qr_cap}</span></a>'
        '<p class="fl-brand"><span class="fl-b1"><b>BEV Trajectory Gallery</b> · @LeRaffl · '
        'charts and text CC BY 4.0</span>'
        '<span>The curve is a model, not a forecast.</span></p>'
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
    compare = build_compare(country, peers or [], INNER_W,
                            highlights=highlights, subject_slug=slug,
                            is_region=bool(fm.get("region")),
                            own_share=own_share)

    kicker = ("Region brief · the shift to battery-electric cars"
              if fm.get("region") else
              "Country brief · the shift to battery-electric cars")
    return FLYER_TEMPLATE.format(
        country=esc(country), theme_href=theme_href, css=FLYER_CSS, flag=flag,
        through=esc(through), head=esc(head), follow=esc(follow), hero=hero,
        two=two, market=fm.get("carriers_html") or mstr.build_block(market, brand_mode, logo_href),
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
.fl-top{display:flex;align-items:center;gap:14px;padding-bottom:12px;border-bottom:2px solid var(--text)}
.fl-flag,.fl-mark{width:54px;height:37px;object-fit:cover;border-radius:2px;box-shadow:0 0 0 1px var(--line);display:block}
.fl-mark{background:#eceae4}
.fl-top h1{font-family:var(--font-display);font-size:30px;line-height:1;margin:0;font-weight:600}
.fl-kick{font-size:11px;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);margin-top:5px}
.fl-date{margin-left:auto;text-align:right;font-size:11px;letter-spacing:.06em;text-transform:uppercase;
  color:var(--muted);line-height:1.5}
.fl-date b{display:block;font-size:15px;letter-spacing:0;text-transform:none;color:var(--text)}
.fl-head{font-family:var(--font-display);font-size:28px;line-height:1.16;font-weight:600;
  margin:14px 0 4px;letter-spacing:-.01em}
.fl-follow{font-family:var(--font-display);font-size:17px;line-height:1.35;margin:0;color:#3a3935;
  min-height:23px}
.fl-hero{display:flex;gap:18px;align-items:flex-start;margin:12px 0 0}
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
.fh-month{font-size:13px;margin-top:6px;color:var(--muted)}
.fh-month b{color:var(--text)}
.fh-range-line{font-size:12.5px;color:var(--muted);line-height:1.45;margin:8px 0 0;max-width:100%}
.fl-acea-note{margin:6px 0 0}
.acea-stale{color:#9a3324;font-weight:600}
.fh-ytd{margin-top:3px}
.fh-mix{flex:1;min-width:0}
.has-loc .fh-mix{flex:none}
.fh-loc{flex:1 1 0;min-width:96px;max-width:240px;margin-left:auto;align-self:center;line-height:0}
.fh-loc svg{display:block;width:100%;height:auto}
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
.fl-sec{margin-top:11px}
.fl-sec h2{font-family:var(--font-display);font-size:18px;margin:0;font-weight:600;border:0;padding:0}
.fl-sub{font-size:11.5px;color:var(--muted);margin:2px 0 8px;line-height:1.4}
.fb-row,.fb-head{display:grid;grid-template-columns:130px 1fr 52px 102px;column-gap:8px}
.fb-head{align-items:end;font-size:9px;line-height:1.2;color:var(--muted);font-weight:600;
  text-align:right;margin-bottom:3px}
.fb-row{align-items:center;font-size:13px;height:20px}
.fb-name{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fb-track{position:relative;height:20px}
.fb-zero{position:absolute;top:0;bottom:0;border-left:1px solid #77746c}
.fb-bar{position:absolute;top:4px;bottom:4px;border-radius:2px;min-width:2px}
.fb-pp{text-align:right;font-weight:700;font-variant-numeric:tabular-nums}
.fb-now{text-align:right;color:var(--muted);font-variant-numeric:tabular-nums}
.fl-curve{display:flex;gap:22px;align-items:flex-start}
.fl-curve .curve{width:100%;height:auto;display:block}
.fl-curve>div:first-child{flex:0 1 """ + str(CURVE_W) + """px;min-width:0}
.fl-curve .fm-side{min-width:200px}
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
.fm-side{flex:1;min-width:0;padding-top:6px}
.fm-head{font-size:11.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);
  margin-bottom:4px}
.fm-row{display:grid;grid-template-columns:52px 62px 1fr;align-items:baseline;
  border-bottom:1px solid var(--line);padding:1px 0}
.fm-lvl{font-size:14px;color:var(--muted)}
.fm-year{font-family:var(--font-display);font-size:24px;font-weight:600;line-height:1;
  font-variant-numeric:tabular-nums}
.fm-ci{font-size:12px;color:var(--muted);text-align:right;font-variant-numeric:tabular-nums}
.fm-past .fm-year{color:#8d897c;font-weight:500}
.fm-note{font-size:10.5px;color:var(--muted);margin:6px 0 0}
.fm-none{font-family:var(--font-display);font-size:15.5px;line-height:1.35;margin:6px 0 0}
.fl-two{display:grid;grid-template-columns:1fr 236px;column-gap:28px}
.fl-facts{display:grid;grid-template-columns:1fr 1fr;column-gap:14px;margin-top:6px}
.ff{padding:6px 0 7px;border-top:1px solid var(--line)}
.ff-n{font-family:var(--font-display);font-size:21px;font-weight:600;line-height:1.1;
  font-variant-numeric:tabular-nums}
.ff-l{font-size:11.5px;margin-top:1px;line-height:1.25}
.ff-s{font-size:10.5px;color:var(--muted);line-height:1.25}
.fl-one .fl-facts{grid-template-columns:repeat(4,1fr)}
.fl-foot{margin-top:auto;padding-top:10px;font-size:10.5px;line-height:1.42;color:var(--muted);
  display:flex;flex-wrap:wrap;column-gap:18px;align-items:flex-end}
.nw{white-space:nowrap}
.fl-foot-text{flex:1;min-width:0}
.fl-qrbox{flex:none;display:block;text-align:center;font-size:8.5px;line-height:1.25;
  color:var(--muted);text-decoration:none;width:84px}
.fl-qr{display:block;margin:0 auto 3px}
.fl-cmp .fl-sub{margin-bottom:0}
.fl-cmp .fl-sub b{color:var(--text)}
.fl-foot p{margin:0 0 3px}
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

def build_index(items: list[dict], theme_href: str) -> str:
    """`items`: country, slug, share, delta, head, through. Highest share first."""
    cards = []
    for n, item in enumerate(sorted(items, key=lambda i: -(i["share"] or -1)), 1):
        flag = ""
        if (mc.REPO / "assets" / "flags" / f"{item['slug']}.png").is_file():
            flag = f'<img src="../../assets/flags/{esc(item["slug"])}.png" alt="">'
        num = mc.share(item["share"]) if item["share"] is not None else "—"
        delta = ""
        if item["delta"] is not None:
            cls = "up" if item["delta"] >= 0.05 else "down" if item["delta"] <= -0.05 else "flat"
            delta = f'<span class="ix-d {cls}">{mc.points(item["delta"])}</span>'
        cards.append(
            f'<a class="ix-card" href="{esc(item["slug"])}.html">'
            f'<span class="ix-rank">{n}</span>{flag}'
            f'<span class="ix-name">{esc(item["country"])}</span>'
            f'<span class="ix-num">{esc(num)}</span>{delta}'
            f'<span class="ix-head">{esc(item["head"])}</span>'
            f'<span class="ix-date">{esc(item["through"])}</span></a>')
    return INDEX_TEMPLATE.format(theme_href=theme_href, css=INDEX_CSS,
                                 n=len(items), cards="".join(cards))


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
@media (max-width:700px){
  .ix-headrow{display:none}
  .ix-card{grid-template-columns:24px 30px 1fr auto auto;row-gap:2px}
  .ix-head{grid-column:3/-1}.ix-date{display:none}
}
"""

INDEX_TEMPLATE = """<!doctype html>
<html lang="en">
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
  <p class="lead" style="font-size:13px;margin-top:18px">BEV share: battery-electric share of new
    registrations over the last 12 months, as each source counts them. "Change, pts": change in
    percentage points, last 12 months vs the 12 months before. Scopes differ between countries; each
    brief names its source.</p>
</div>
</body>
</html>
"""
