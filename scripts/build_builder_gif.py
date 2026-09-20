#!/usr/bin/env python3
"""Render `builder_history/series/<group>.json` into an animated GIF.

    python3 scripts/build_builder_gif.py
    python3 scripts/build_builder_gif.py --group world --out /tmp

One GIF per group, written to `builder_history/series/<group>.gif` and
**overwritten in place** on every run. It is deliberately not dated: each
rebuild is the same animation with one more frame on the end, so keeping
`timelapse-2026-09.gif` next to `timelapse-2026-10.gif` would store the same
seconds of footage again and again.

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
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
SERIES = REPO / "builder_history" / "series"

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
FRAME_MS = 650
HOLD_MS = 1800          # linger on the newest frame before looping

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]
FONT_PATHS_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]

LABELS = {
    "world": "World", "eu": "EU", "g7": "G7",
    "western_europe": "Western Europe", "northern_europe": "Northern Europe",
    "southern_europe": "Southern Europe", "eastern_europe": "Eastern Europe",
    "north_america": "North America", "south_america": "South America",
    "americas": "Americas", "asia": "Asia",
    "small_markets": "Small markets", "medium_markets": "Medium markets",
    "big_markets": "Big markets",
}


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

    label = LABELS.get(doc["group"], doc["group"])
    d.text((PAD_L, 22), f"{label} — {series_txt} share", font=f_title, fill=INK)

    n = frame.get("n_cohort") if key == "cohort" else frame.get("n_countries")
    set_txt = (f"fixed {n}-country cohort" if key == "cohort"
               else f"{n} countries as of this date")
    per = pretty_period(frame.get("data_per"))
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

    # Ghost fan: every other frame's BEV, so the drift reads as a shape.
    ghost = tuple(round(c + (BG[i] - c) * 0.82) for i, c in enumerate(C_BEV))
    for j, f in enumerate(frames):
        if j == idx:
            continue
        g = f.get(key) or f["all"]
        polyline(d, years, g["bev"], px, py, ghost, 1)

    polyline(d, years, cur["ice"], px, py, C_ICE, 3)
    polyline(d, years, cur["phev"], px, py, C_PHEV, 3)
    polyline(d, years, cur["bev"], px, py, C_BEV, 3)

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

    # Provenance. This is a model's own output, and the still travels
    # without the page around it, so it has to say so.
    d.text((PAD_L, H - 16),
           "LeRaffl BEV Gallery · fitted model, not a forecast",
           font=font(11), fill=MUTED)
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
                   help="Only this group (repeatable). Default: all.")
    p.add_argument("--set", default="cohort", choices=("cohort", "all"),
                   help="Country set to animate. Default: cohort.")
    p.add_argument("--out", type=Path, default=SERIES,
                   help="Output directory. Default: builder_history/series/")
    args = p.parse_args(argv)

    index_path = SERIES / "index.json"
    if not index_path.is_file():
        print("  ! builder_history/series/index.json missing — "
              "run scripts/build_builder_series.py first")
        return 1
    index = json.loads(index_path.read_text(encoding="utf-8"))
    groups = args.group or index["groups"]

    args.out.mkdir(parents=True, exist_ok=True)
    total = 0
    for g in groups:
        src = SERIES / f"{g}.json"
        if not src.is_file():
            print(f"  ! {g}: no series file, skipped")
            continue
        doc = json.loads(src.read_text(encoding="utf-8"))
        size = build_gif(doc, args.out / f"{g}.gif", args.set)
        total += size
        print(f"  ✓ {g}.gif — {len(doc['frames'])} frames, {size/1024:.0f} KB")

    print(f"  {len(groups)} GIF(s), {total/1024:.0f} KB total "
          f"({args.set} country set)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
