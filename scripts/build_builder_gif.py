#!/usr/bin/env python3
"""Render `backtest/series/<group>.json` into an animated GIF.

    python3 scripts/build_builder_gif.py
    python3 scripts/build_builder_gif.py --group world --out /tmp

One GIF per group, written to `backtest/series/<group>.gif` and
**overwritten in place** on every run. It is deliberately not dated: each
rebuild is the same animation with one more frame on the end, so keeping
`timelapse-2026-09.gif` next to `timelapse-2026-10.gif` would store the same
seconds of footage again and again.

Why the backtest and not `builder_history`
------------------------------------------
`builder_history/` cannot reach before the repository exists (2025-09), which
is a dozen frames. The backtest re-fits from the CSVs and reaches 2015, which
is ~140 — and the drift only reads as a story over that span. The two are
different quantities and must never share an animation; this renders the
backtest, and says so in the frame.

Why server-side
---------------
The alternative is encoding in the browser, which means shipping a GIF
encoder to every visitor for a button almost nobody presses — and this repo
already generates and commits its images (`images/`, `posts/`). So the
workflow renders it once and the page simply links to the file.

Why Pillow and not matplotlib
-----------------------------
The chart is three polylines and a pair of axes. Pillow draws that directly,
costs one small dependency instead of matplotlib + numpy, and lets the frame
use the gallery's own palette rather than a plotting library's defaults.

Which country set
-----------------
The **cohort** — the countries present in every snapshot, the panel's
default. The "all countries as of each date" view is honest but mixes two
effects (the model revising, and the gallery gaining countries), so it is not
what should be handed around as a shareable loop. The frame says which set it
is showing.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
SERIES = REPO / "backtest" / "series"

W, H = 880, 520
PAD_L, PAD_R, PAD_T, PAD_B = 62, 22, 84, 72

# The gallery's palette (index.html `:root` + COLORS).
BG      = (253, 253, 252)
INK     = (26, 26, 24)
MUTED   = (85, 83, 76)
GRID    = (228, 226, 221)
C_BEV   = (46, 139, 87)
C_ICE   = (105, 37, 0)
C_PHEV  = (58, 120, 181)

Y_MAX = 100.0
FRAME_MS = 280
HOLD_MS = 2200          # linger on the newest frame before looping

# The backtest is monthly, which is ~140 frames — at a readable frame rate
# that is a minute and a half of footage for something meant to be glanced at.
# Every third month keeps the drift continuous (the curve moves smoothly
# between quarters) and lands the loop around 14 seconds.
DEFAULT_STEP = 3

# Deliberately NOT the fuel palette, and the same ramp the panel uses
# (`TL_THRESH_COLOR` in index.html). Every threshold here is a *BEV*
# crossing, so giving 20% the PHEV blue and 80% the ICE brown would paint
# each marker in the colour of a curve it has nothing to do with — and put a
# blue dotted line across the blue PHEV curve at 20%, and a brown one across
# the brown ICE curve right where ICE itself passes 80%. Darker = higher
# threshold, which is also the order they fall in.
THRESH_COLOUR = {20: (168, 164, 154), 50: (125, 122, 114), 80: (74, 72, 68)}

# Observed data points: a darker shade of each fitted curve's colour. Drawn
# in the same colour they read as a second fitted line; the page's convention
# is points for what was measured and a line for what was modelled. These
# match the panel's OBS table in index.html.
C_OBS_BEV  = (27, 94, 58)
C_OBS_ICE  = (107, 36, 0)
C_OBS_PHEV = (31, 79, 122)

# Drawing all ~46 earlier curves turns the fan into a solid block and loses
# the individual revisions. The same cap the panel uses.
MAX_GHOSTS = 24

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]
FONT_PATHS_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]

# Which series get an animation. Deliberately NOT "all of them": every group
# and spotlight country would be 20 files rewritten every month, for an
# artefact whose job is to be shared, not to be exhaustive. A few blocs worth
# arguing about, plus the countries that come up in single-case discussion.
#
# The panel still scrubs and plays every series -- this list only decides
# which ones also get a downloadable file. `--all` overrides it.
GIF_GROUPS = [
    "world",
    "eu",
    "asia",
    "north_america",
    "country_germany",
    "country_china",
    "country_norway",
    "country_usa",
    "country_japan",
    "country_france",
]


def font(size: int, bold: bool = False):
    for p in (FONT_PATHS_BOLD if bold else FONT_PATHS):
        if Path(p).is_file():
            return ImageFont.truetype(p, size)
    # Never fail the build over a missing font; the chart still reads.
    return ImageFont.load_default()


def pretty_period(p: str | None) -> str:
    if not p or len(p) < 7:
        return ""
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    try:
        return f"{months[int(p[5:7]) - 1]} {p[:4]}"
    except (ValueError, IndexError):
        return p


def project(years: list[float]):
    """Year/share -> pixel mappers for the plot area."""
    x0, x1 = min(years), max(years)
    px0, px1 = PAD_L, W - PAD_R
    py0, py1 = PAD_T, H - PAD_B

    def px(y: float) -> float:
        return px0 + (y - x0) * (px1 - px0) / (x1 - x0)

    def py(v: float) -> float:
        return py1 - (v / Y_MAX) * (py1 - py0)

    return px, py


def polyline(draw, years, ys, px, py, colour, width):
    """Draw a series, breaking the line wherever a value is missing.

    A `None` is an absence, not a zero: the oldest snapshot carries no ICE
    fit at all, and joining across it would draw a curve nobody computed.
    """
    run: list[tuple[float, float]] = []
    for yr, v in zip(years, ys):
        if v is None:
            if len(run) > 1:
                draw.line(run, fill=colour, width=width, joint="curve")
            run = []
        else:
            run.append((px(yr), py(v)))
    if len(run) > 1:
        draw.line(run, fill=colour, width=width, joint="curve")


def year_month(y: float) -> str:
    """A decimal year as `YYYY-MM`, matching `tlYearLabel` in index.html.

    Same convention as the panel: the fraction is days through the year, not
    twelfths, so the label agrees with where the marker is actually drawn.
    Every other surface in this project writes a period as YYYY-MM, and a
    bare rounded year next to a readout showing the decimal reads as the two
    being a year apart.
    """
    yr = int(math.floor(y))
    start = date(yr, 1, 1).toordinal()
    span = date(yr + 1, 1, 1).toordinal() - start
    d = date.fromordinal(int(math.floor(start + (y - yr) * span)))
    return f"{d.year:04d}-{d.month:02d}"


def dotted(draw, pts, colour, dash: int = 3, gap: int = 3, width: int = 1):
    """A dashed straight segment. Pillow has no dash option of its own."""
    (x0, y0), (x1, y1) = pts
    span = max(abs(x1 - x0), abs(y1 - y0))
    if span <= 0:
        return
    step = (dash + gap) / span
    t = 0.0
    while t < 1.0:
        u = min(1.0, t + dash / span)
        draw.line([(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t),
                   (x0 + (x1 - x0) * u, y0 + (y1 - y0) * u)],
                  fill=colour, width=width)
        t += step


def render_frame(doc, idx: int, key: str) -> Image.Image:
    years = doc["years"]
    frames = doc["frames"]
    frame = frames[idx]
    cur = frame.get(key) or frame["all"]

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    px, py = project(years)

    f_title = font(21, bold=True)
    f_sub = font(13)
    f_tick = font(12)
    f_small = font(12)

    # Only name the series this frame actually has. params.csv carried no ICE
    # fit before 2026-01, and a title promising "BEV, ICE & PHEV" over a chart
    # with one line reads as "the other two are at zero" rather than "the
    # other two were never computed".
    present = [k for k in ("bev", "ice", "phev")
               if any(v is not None for v in cur.get(k) or [])]
    names = {"bev": "BEV", "ice": "ICE", "phev": "PHEV"}
    shown = [names[k] for k in present]
    series_txt = (" & ".join([", ".join(shown[:-1]), shown[-1]])
                  if len(shown) > 1 else (shown[0] if shown else ""))

    label = doc.get("label") or doc["group"]
    d.text((PAD_L, 22), f"{label} — {series_txt} share", font=f_title, fill=INK)

    # A spotlight country is a group of one, where "44-country cohort" would
    # be nonsense. Say what it actually is.
    if doc["group"].startswith("country_"):
        set_txt = "single market"
    elif key == "cohort" and "cohort" not in frame:
        # The frame has no cohort counterpart, so `cur` fell back to the
        # all-countries curve above. Say so rather than labelling someone
        # else's data as the cohort -- that mislabel is exactly the
        # composition artefact the cohort exists to remove.
        set_txt = f"{frame.get('n_countries')} countries (no cohort frame)"
    else:
        n = frame.get("n_cohort") if key == "cohort" else frame.get("n_countries")
        set_txt = (f"fixed {n}-country cohort" if key == "cohort"
                   else f"{n} countries as of this date")
    per = pretty_period(frame.get("data_per"))
    if doc.get("kind") == "backtest":
        # In a backtest the estimate date and the data cutoff are the same
        # month by construction, so "as estimated 2020-04 · data through Apr
        # 2020" says one thing twice. The doc's own headline says it once.
        head = doc.get("headline") or "What the model said using data through"
        sub = f"{head} {per or frame['date']}  ·  {set_txt}"
    else:
        sub = f"as estimated {frame['date']}  ·  {set_txt}"
        if per:
            sub += f"  ·  data through {per}"
    d.text((PAD_L, 52), sub, font=f_sub, fill=MUTED)

    # Grid + y ticks
    for v in range(0, 101, 20):
        y = py(v)
        d.line([(PAD_L, y), (W - PAD_R, y)], fill=GRID, width=1)
        d.text((PAD_L - 10, y - 7), f"{v}%", font=f_tick, fill=MUTED, anchor="ra")

    # x ticks every 5 years
    y0, y1 = int(min(years)), int(max(years))
    start = y0 + (-y0) % 5
    for yr in range(start, y1 + 1, 5):
        x = px(yr)
        d.line([(x, PAD_T), (x, H - PAD_B)], fill=GRID, width=1)
        d.text((x, H - PAD_B + 8), str(yr), font=f_tick, fill=MUTED, anchor="ma")

    # Ghost fan: the BEV curve of *earlier* frames, so the drift reads as a
    # shape and the trail builds as the animation plays.
    #
    # Earlier only. Drawing the whole fan on every frame would put a later
    # estimate faintly behind an earlier one -- knowledge that did not exist
    # on the date the frame is labelled with.
    #
    # The checkpoints are fixed positions in the series (every `step`-th
    # frame), shown once the animation has passed them. Sampling `frames[:idx]`
    # with a stride that grows with `idx` would instead swap the entire ghost
    # set out on most frames, so the fan would reshuffle rather than
    # accumulate -- the opposite of a trail. It buys nothing in file size
    # either (measured: 494 KB vs 495 KB), because the three live curves move
    # across the full plot width anyway and Pillow's optimiser works on one
    # bounding box of changed pixels.
    ghost = tuple(round(c + (BG[i] - c) * 0.82) for i, c in enumerate(C_BEV))
    step = max(1, -(-len(frames) // MAX_GHOSTS))
    for f in [frames[i] for i in range(0, idx, step)]:
        g = f.get(key) or f["all"]
        polyline(d, years, g["bev"], px, py, ghost, 1)

    # Thresholds. The horizontals are scaffolding and never move, so they are
    # faint; the verticals slide as the model revises, so they carry the
    # colour and the year. A threshold the model never reaches inside the
    # range gets no vertical at all — drawing one at the edge would show a
    # crossing the model did not predict.
    cross = (frame.get("cross_cohort") if (key == "cohort" and "cohort" in frame)
             else frame.get("cross_all")) or {}
    thresh_labels = []
    for t in doc.get("thresholds") or (20, 50, 80):
        yt = py(float(t))
        d.line([(PAD_L, yt), (W - PAD_R, yt)], fill=GRID, width=1)
        yr = cross.get(str(int(t)))
        if yr is None:
            continue
        x = px(float(yr))
        col = THRESH_COLOUR.get(int(t), THRESH_COLOUR[50])
        # A corner, not a crosshair: the horizontal runs from the axis to the
        # crossing and the vertical drops from there, so the two legs bracket
        # exactly the region "below this threshold, before this year". Drawn
        # dotted and in the threshold's colour, so it never reads as a fourth
        # curve and so the 20/80 legs stay visible where they would otherwise
        # sit invisibly on top of a gridline.
        dotted(d, [(px(min(years)), yt), (x, yt)], col)
        dotted(d, [(x, yt), (x, py(0))], col)
        # At the top of the vertical, not on the axis: the x tick row already
        # carries a number every five years and two numbers in one place read
        # as one wrong number. Here it also sits where the information is.
        # Deferred until after the curves -- the 20% corner is by definition
        # on the BEV curve, so drawing it now would let the curve paint over
        # the year.
        thresh_labels.append(((x + 5, yt - 13), year_month(yr), col))

    polyline(d, years, cur["ice"], px, py, C_ICE, 3)
    polyline(d, years, cur["phev"], px, py, C_PHEV, 3)
    polyline(d, years, cur["bev"], px, py, C_BEV, 3)

    # Observed shares for every frame up to this one, as dots, with the last
    # of each ringed. Not model output: this is what the sources reported.
    # It matters more here than in the panel, because a still travels without
    # a scrubber or a readout -- the rings are the only thing on the image
    # that says where the evidence stopped and the extrapolation started.
    obs_key = ("obs_cohort" if (key == "cohort" and "cohort" in frame)
               else "obs_all")
    for series_key, colour in (("ice", C_OBS_ICE), ("phev", C_OBS_PHEV),
                               ("bev", C_OBS_BEV)):
        pts = []
        for f in frames[:idx + 1]:
            o = f.get(obs_key) or f.get("obs_all") or {}
            v = o.get(series_key)
            per = f.get("data_per") or f.get("date") or ""
            if v is None or len(per) < 7:
                continue
            try:
                yr, mo = int(per[:4]), int(per[5:7])
            except ValueError:
                continue
            pts.append((px(yr + (mo - 1) / 12.0), py(float(v))))
        for cx, cy in pts:
            d.ellipse([cx - 1.6, cy - 1.6, cx + 1.6, cy + 1.6], fill=colour)
        if pts:
            cx, cy = pts[-1]
            d.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], outline=colour, width=2)

    # Threshold year labels last, so nothing paints over them. The 20% corner
    # sits on the BEV curve and now also in its observed dots, so each label
    # gets a background halo to stay readable.
    for pos, txt, col in thresh_labels:
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            d.text((pos[0] + dx, pos[1] + dy), txt, font=f_tick, fill=BG)
        d.text(pos, txt, font=f_tick, fill=col)

    # Legend — only what is on the chart, for the same reason as the title.
    colours = {"bev": C_BEV, "ice": C_ICE, "phev": C_PHEV}
    lx, ly = PAD_L, H - 34
    for k in present:
        d.line([(lx, ly + 7), (lx + 22, ly + 7)], fill=colours[k], width=3)
        d.text((lx + 28, ly), names[k], font=f_small, fill=MUTED)
        lx += 28 + int(d.textlength(names[k], font=f_small)) + 18

    missing = [names[k] for k in ("ice", "phev") if k not in present]
    if missing:
        d.text((lx, ly), f"({'/'.join(missing)} not fitted in this snapshot)",
               font=f_small, fill=MUTED)

    # Frame counter, right-aligned against the legend row
    d.text((W - PAD_R, ly), f"{idx + 1}/{len(frames)}",
           font=f_small, fill=MUTED, anchor="ra")

    # Provenance. This is a model's own output, and the still travels without
    # the page (and its caveat paragraph) around it, so the one limitation a
    # reader cannot recover on their own has to ride along: the past it was
    # fitted on is today's revised past, which flatters it.
    note = "LeRaffl BEV Gallery · fitted model, not a forecast"
    if doc.get("kind") == "backtest":
        note += " · re-fitted on revised data, not clean out-of-sample"
    d.text((PAD_L, H - 16), note, font=font(11), fill=MUTED)
    return img


def build_gif(doc, out_path: Path, key: str) -> int:
    frames = [render_frame(doc, i, key) for i in range(len(doc["frames"]))]
    # Few flat colours, so an adaptive palette keeps this small.
    frames = [f.convert("P", palette=Image.ADAPTIVE, colors=64) for f in frames]
    durations = [FRAME_MS] * len(frames)
    durations[-1] = HOLD_MS
    # disposal=1 (leave the previous frame in place) lets Pillow store only
    # what changed. The axes, grid and ghost fan are identical in every
    # frame, so this roughly halves the file -- 248 KB -> 107 KB for `world`.
    # Verified rather than assumed: every decoded frame is pixel-identical to
    # the source render, so the optimiser is emitting the erase regions the
    # moving curves need.
    frames[0].save(
        out_path, save_all=True, append_images=frames[1:],
        duration=durations, loop=0, optimize=True, disposal=1,
    )
    return out_path.stat().st_size


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--group", action="append",
                   help="Only this group (repeatable). Default: GIF_GROUPS.")
    p.add_argument("--all", action="store_true",
                   help="Render every series, not just the curated list.")
    p.add_argument("--set", default="cohort", choices=("cohort", "all"),
                   help="Country set to animate. Default: cohort.")
    p.add_argument("--step", type=int, default=DEFAULT_STEP,
                   help=f"Keep every Nth frame. Default: {DEFAULT_STEP}.")
    p.add_argument("--src", type=Path, default=SERIES,
                   help="Series directory. Default: backtest/series/")
    p.add_argument("--out", type=Path, default=None,
                   help="Output directory. Default: alongside --src.")
    args = p.parse_args(argv)

    if args.out is None:
        args.out = args.src
    index_path = args.src / "index.json"
    if not index_path.is_file():
        print(f"  ! {index_path} missing — "
              "run scripts/build_backtest_series.py first")
        return 1
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if args.group:
        groups = args.group
    elif args.all:
        groups = index["groups"]
    else:
        groups = [g for g in GIF_GROUPS if g in index["groups"]]
        missing = [g for g in GIF_GROUPS if g not in index["groups"]]
        for g in missing:
            print(f"  ! {g}: in GIF_GROUPS but not in the archive, skipped")

    args.out.mkdir(parents=True, exist_ok=True)
    total = 0
    for g in groups:
        src = args.src / f"{g}.json"
        if not src.is_file():
            print(f"  ! {g}: no series file, skipped")
            continue
        doc = json.loads(src.read_text(encoding="utf-8"))
        if args.step > 1 and len(doc["frames"]) > args.step:
            # Keep the newest frame whatever the stride lands on: the last
            # thing the animation shows has to be the current estimate, not
            # whichever month the arithmetic happened to end on.
            kept = doc["frames"][::args.step]
            if kept[-1] is not doc["frames"][-1]:
                kept.append(doc["frames"][-1])
            doc = dict(doc, frames=kept)
        size = build_gif(doc, args.out / f"{g}.gif", args.set)
        total += size
        print(f"  ✓ {g}.gif — {len(doc['frames'])} frames, {size/1024:.0f} KB")

    print(f"  {len(groups)} GIF(s), {total/1024:.0f} KB total "
          f"({args.set} country set)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
