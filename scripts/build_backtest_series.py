#!/usr/bin/env python3
"""Aggregate the backtest fits into per-group series for the Time-lapse UI.

    python3 scripts/build_backtest_series.py
    python3 scripts/build_backtest_series.py --step 3     # quarterly frames

Reads the per-month `backtest/params/<YYYY-MM>.csv` and
`backtest/weights/<YYYY-MM>.csv` written by `R/build_backtest.R`, runs them
through the **same** aggregation `snapshot_builder.py` uses, and writes
`backtest/series/<group>.json` -- the form the Time-lapse panel and
`build_builder_gif.py` read.

Sharing the aggregation is the point: a backtest curve and a snapshot curve
have to be produced identically, or differences between them are differences
in the code rather than in the model.

What this series means
----------------------
"What the model said using data through <month>" -- the fit re-run with the
observations available at that date, reaching back as far as the CSVs do
rather than as far as git does.

Three things it is NOT, all of which a consumer has to state:

1. It is **not** `builder_history/`. That records what the gallery actually
   estimated at the time, bugs and coverage included, and cannot reach before
   2025-09. These are different quantities and must not share a chart.
2. It is **not** clean out-of-sample. `R/build_backtest.R` truncates today's
   revised CSVs; the numbers as first published are not recoverable. The model
   is handed a corrected past, which flatters it.
3. Its coverage **grows** -- 23 fittable series in 2015-01, ~95 by 2026. So a
   world aggregate moves partly because the gallery gained countries. The
   `cohort` set below is the answer to that, exactly as in `builder_history`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import snapshot_builder as sb  # noqa: E402
from build_builder_series import (  # noqa: E402
    grid_for, label_for, sample,
)

REPO = Path(__file__).resolve().parent.parent
BT = REPO / "backtest"
OUT = BT / "series"


# The thresholds the gallery already speaks in (Thresholds tab, and the
# 20->80 span in Durations). Precomputed here rather than in the browser so
# the chart, the readout and any export agree by construction.
THRESHOLDS = (20.0, 50.0, 80.0)


def crossing(years: list[float], ys: list[float | None], pct: float):
    """First year the curve reaches `pct`, linearly interpolated.

    Returns None when it never does inside the plotted range. That is a real
    answer -- in the early frames the model did not think 80% was reachable
    by 2050 at all -- and must not be faked with an endpoint, or the chart
    would show a threshold being met that the model never predicted.
    """
    for i in range(1, len(ys)):
        a, b = ys[i - 1], ys[i]
        if a is None or b is None:
            continue
        if a < pct <= b:
            return round(years[i - 1] + (pct - a) * (years[i] - years[i - 1]) / (b - a), 2)
    return None


def norm(name: str) -> str:
    """Match a country by identity rather than spelling (see #219 / New Zealand)."""
    return "".join(str(name).split()).casefold()


def months_available() -> list[str]:
    pdir, wdir = BT / "params", BT / "weights"
    if not pdir.is_dir():
        return []
    out = []
    for p in sorted(pdir.glob("*.csv")):
        if (wdir / p.name).is_file():
            out.append(p.stem)
    return out


def curves_for(month: str, cohort: list[str] | None):
    """Aggregate one month into {group: (xs, bev, ice, phev)} plus metadata."""
    rows = sb.load_params(BT / "params" / f"{month}.csv")
    weights = sb.load_weights(BT / "weights" / f"{month}.csv")
    groups = sb.resolve_groups(rows, weights)

    if cohort is not None:
        keep = {norm(c) for c in cohort}
        groups = {g: [c for c in cs if norm(c) in keep] for g, cs in groups.items()}

    curves, meta = {}, {}
    for name, countries in groups.items():
        if not countries:
            continue
        xs, bev, ice, phev, m = sb.compute_group_curve(
            countries, rows, weights, sb.DEFAULT_VARIANT)
        if m["n_countries"] == 0:
            continue
        curves[name] = (xs, bev, ice, phev)
        meta[name] = m
    return curves, meta


def cohort_from(months: list[str]) -> list[str]:
    """Countries fittable in *every* month, matched on identity.

    Without this the world curve animates the gallery being built as much as
    the model changing its mind -- the same trap `builder_history` hit, where
    roughly half the apparent drift turned out to be composition.
    """
    seen: list[dict[str, str]] = []
    for mo in months:
        rows = sb.load_params(BT / "params" / f"{mo}.csv")
        weights = sb.load_weights(BT / "weights" / f"{mo}.csv")
        world = sb.resolve_groups(rows, weights)["world"]
        seen.append({norm(c): c for c in world})
    if not seen:
        return []
    keys = set.intersection(*(set(m) for m in seen))
    return sorted(seen[-1][k] for k in keys)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--step", type=int, default=1,
                   help="Keep every Nth month (1 = monthly, 3 = quarterly).")
    p.add_argument("--out", type=Path, default=OUT)
    args = p.parse_args(argv)

    months = months_available()
    if not months:
        print("  ! no backtest/params/*.csv — run R/build_backtest.R first")
        return 1
    if args.step > 1:
        months = months[::args.step]
    print(f"  {len(months)} frames, {months[0]} .. {months[-1]}")

    cohort = cohort_from(months)
    print(f"  cohort: {len(cohort)} countries present in every frame")

    frames_all, frames_coh, metas = {}, {}, {}
    for mo in months:
        ca, ma = curves_for(mo, None)
        cc, mc = curves_for(mo, cohort) if cohort else ({}, {})
        frames_all[mo], frames_coh[mo] = ca, cc
        metas[mo] = (ma, mc)

    groups = sorted(frames_all[months[-1]].keys())
    grid_years = sorted(frames_all[months[-1]][groups[0]][0])
    grid = grid_for(grid_years)

    args.out.mkdir(parents=True, exist_ok=True)
    written = []
    for g in groups:
        frames = []
        for mo in months:
            ma, mc = metas[mo]
            if g not in frames_all[mo]:
                continue
            xs, bev, ice, phev = frames_all[mo][g]
            as_map = lambda ys: dict(zip(xs, ys))  # noqa: E731
            fr = {
                "date": mo,
                "n_countries": ma.get(g, {}).get("n_countries"),
                "total_weight": ma.get(g, {}).get("total_weight"),
                "data_per": mo,
                "all": {"bev": sample(as_map(bev), grid),
                        "ice": sample(as_map(ice), grid),
                        "phev": sample(as_map(phev), grid)},
            }
            fr["cross_all"] = {str(int(t)): crossing(grid, fr["all"]["bev"], t)
                               for t in THRESHOLDS}
            if g in frames_coh.get(mo, {}):
                cxs, cbev, cice, cphev = frames_coh[mo][g]
                cm = lambda ys: dict(zip(cxs, ys))  # noqa: E731
                fr["cohort"] = {"bev": sample(cm(cbev), grid),
                                "ice": sample(cm(cice), grid),
                                "phev": sample(cm(cphev), grid)}
                fr["n_cohort"] = mc.get(g, {}).get("n_countries")
                fr["cohort_weight"] = mc.get(g, {}).get("total_weight")
                fr["cross_cohort"] = {str(int(t)): crossing(grid, fr["cohort"]["bev"], t)
                                      for t in THRESHOLDS}
            frames.append(fr)
        if not frames:
            continue

        doc = {
            "group": g,
            "label": label_for(g),
            "kind": "backtest",
            "headline": "What the model said using data through",
            "caveat": ("Re-fitted from today's revised CSVs truncated to each "
                       "date. The figures as first published are not "
                       "recoverable, so the model is handed a corrected past "
                       "-- read this as an upper bound, not a clean "
                       "out-of-sample test."),
            "years": grid,
            "thresholds": [int(t) for t in THRESHOLDS],
            "n_cohort": len(cohort),
            "frames": frames,
        }
        path = args.out / f"{g}.json"
        path.write_text(json.dumps(doc, ensure_ascii=False,
                                   separators=(",", ":")) + "\n", encoding="utf-8")
        written.append((g, path.stat().st_size))

    (args.out / "index.json").write_text(json.dumps({
        "kind": "backtest",
        "groups": [g for g, _ in written],
        "labels": {g: label_for(g) for g, _ in written},
        "dates": months,
        "years": [grid[0], grid[-1]],
        "n_cohort": len(cohort),
        "cohort": cohort,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    total = sum(s for _, s in written)
    print(f"  ✓ backtest/series/ — {len(written)} groups, {len(months)} frames, "
          f"{total/1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
