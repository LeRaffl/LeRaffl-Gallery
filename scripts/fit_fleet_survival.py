#!/usr/bin/env python3
"""
Fit the Weibull survival curve of passenger cars per country and write
``fleet/survival_fit.csv`` - the evidence behind the Fleet tab's default
"Weibull shape".

Question
--------
The Fleet tab lets every car leave the fleet along S(age) = exp(-(age/scale)^shape).
The scale is calibrated per country (docs/architecture/37 section 7). The shape
- how sharply the chance of leaving rises with age - was 3.0 by convention and
had never been checked. This checks it against data.

Method
------
For a country, registrations[Y - a] x S(a + 0.5) is how many cars of age a
should still be in the stock at the end of year Y. Summed over the ages of a
band, that is comparable with what Eurostat observes
(``fleet/fleet_age.csv``: under 5, 5-10, 10-20, over 20 years; the two youngest
published bands are merged because their boundary is not applied uniformly).
Registrations come from ``fleet/registrations_history.csv`` (from 1970), with
gaps of up to ``MAX_GAP`` years interpolated; a stock year is used only when
the 30 years before it are covered.

Shape and scale are fitted by least squares on the band shares of the observed
stock, over all usable years, on a grid. The curve is a NET survival in the
registry: it absorbs exports of used cars (which is why Belgium and Luxembourg
come out with a shape near 1.5: their cars leave young, by export, not old, by
scrappage) and cannot describe a registry fed by used imports at all.

Which fits count
----------------
A fit says something about how cars age out only where the national registry
is mostly made of cars first registered there and scrapped there. ``usable`` is
therefore true only when

* the fit is decent (``rmse`` below ``MAX_RMSE``),
* the shape is not pinned to the edge of the grid, and
* the country's observed net attrition is at least ``MIN_ATTRITION`` a year
  and at most ``MAX_ATTRITION`` (fleet/fleet_calibration.json): below, used
  imports hide scrappage; above, exports dominate.

The default shape in index.html is the median over the usable fits, rounded to
one decimal. ``rmse_shape_2`` / ``_3`` / ``_4`` show how much (little) the fit
degrades at a fixed shape with the scale re-fitted: the answer to "is 3 good
enough".

Usage
-----
    python scripts/fit_fleet_survival.py            # rewrite fleet/survival_fit.csv
    python scripts/fit_fleet_survival.py --check     # exit 1 if it would change
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGE_PATH = ROOT / "fleet" / "fleet_age.csv"
REG_PATH = ROOT / "fleet" / "registrations_history.csv"
CAL_PATH = ROOT / "fleet" / "fleet_calibration.json"
OUT_PATH = ROOT / "fleet" / "survival_fit.csv"

# Band -> ages (in whole years at the end of the stock year) it covers.
BANDS = {"lt5": (0, 5), "y5_10": (5, 10), "y10_20": (10, 20), "gt20": (20, 70)}
HISTORY_NEEDED = 30   # years of registrations required before a stock year
MAX_GAP = 6           # longest hole in the registration series that is interpolated
SHAPES = [round(1.0 + 0.1 * i, 1) for i in range(0, 71)]      # 1.0 .. 8.0
SCALES = [8.0 + 0.5 * i for i in range(0, 105)]               # 8 .. 60 years
MAX_RMSE = 0.03
MIN_ATTRITION, MAX_ATTRITION = 0.02, 0.06
COLUMNS = ["country", "years", "shape", "scale", "mean_life", "rmse",
           "rmse_shape_2", "rmse_shape_3", "rmse_shape_4",
           "share_gt20_observed", "share_gt20_fitted", "net_attrition", "usable"]


def read_ages(path: Path = AGE_PATH) -> dict[str, dict[int, dict]]:
    out: dict[str, dict[int, dict]] = defaultdict(dict)
    with path.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            n = lambda k: float(r[k])  # noqa: E731
            out[r["country"]][int(r["year"])] = {
                "lt5": n("lt2") + n("y2_5"), "y5_10": n("y5_10"),
                "y10_20": n("y10_20"), "gt20": n("gt20")}
    return out


def read_registrations(path: Path = REG_PATH) -> dict[str, dict[int, float]]:
    """country -> year -> new cars, with short gaps interpolated and the years
    before the first one on record (if it is 1992 or earlier) held at its level."""
    raw: dict[str, dict[int, float]] = defaultdict(dict)
    with path.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            raw[r["country"]][int(r["year"])] = float(r["new_registrations"])
    out = {}
    for country, s in raw.items():
        ys = sorted(s)
        full = {}
        for y in range(1940, ys[-1] + 1):
            if y in s:
                full[y] = s[y]
            elif y < ys[0]:
                if ys[0] <= 1992:
                    full[y] = s[ys[0]]
            else:
                lo = max(v for v in ys if v < y)
                hi = min(v for v in ys if v > y)
                if hi - lo <= MAX_GAP:
                    full[y] = s[lo] + (s[hi] - s[lo]) * (y - lo) / (hi - lo)
        out[country] = full
    return out


def fit_country(ages: dict[int, dict], reg: dict[int, float]) -> dict | None:
    obs = [(y, row) for y, row in sorted(ages.items())
           if all((y - a) in reg for a in range(HISTORY_NEEDED))]
    if len(obs) < 3:
        return None

    def rmse(shape, scale):
        e, n = 0.0, 0
        for y, row in obs:
            total = sum(row.values())
            for band, (lo, hi) in BANDS.items():
                p = sum(reg.get(y - a, 0.0) * math.exp(-((a + 0.5) / scale) ** shape)
                        for a in range(lo, hi))
                e += ((p - row[band]) / total) ** 2
                n += 1
        return math.sqrt(e / n)

    def best_scale(shape):
        return min((rmse(shape, sc), sc) for sc in SCALES)

    by_shape = {k: best_scale(k) for k in SHAPES}
    shape = min(by_shape, key=lambda k: by_shape[k][0])
    err, scale = by_shape[shape]
    y, row = obs[-1]
    total = sum(row.values())
    fitted_old = sum(reg.get(y - a, 0.0) * math.exp(-((a + 0.5) / scale) ** shape)
                     for a in range(*BANDS["gt20"]))
    return {"years": f"{obs[0][0]}-{obs[-1][0]}", "shape": shape, "scale": scale,
            "mean_life": scale * math.gamma(1 + 1 / shape), "rmse": err,
            "rmse_shape_2": by_shape[2.0][0], "rmse_shape_3": by_shape[3.0][0],
            "rmse_shape_4": by_shape[4.0][0],
            "share_gt20_observed": row["gt20"] / total, "share_gt20_fitted": fitted_old / total}


def build() -> list[dict]:
    ages, regs = read_ages(), read_registrations()
    cal = json.loads(CAL_PATH.read_text(encoding="utf-8"))["countries"] if CAL_PATH.exists() else {}
    rows = []
    for country in sorted(ages):
        f = fit_country(ages[country], regs.get(country, {}))
        if not f:
            continue
        att = cal.get(country, {}).get("attrition", {}).get("rate")
        usable = (f["rmse"] < MAX_RMSE and SHAPES[0] < f["shape"] < SHAPES[-1]
                  and att is not None and MIN_ATTRITION <= att <= MAX_ATTRITION)
        rows.append({"country": country, **f, "net_attrition": att, "usable": usable})
    return rows


def default_shape(rows: list[dict]) -> float | None:
    usable = [r["shape"] for r in rows if r["usable"]]
    return round(statistics.median(usable), 1) if usable else None


def to_csv(rows: list[dict]) -> str:
    def fmt(c, v):
        if v is None:
            return ""
        if c == "usable":
            return "yes" if v else "no"
        if c in ("shape", "scale", "mean_life"):
            return f"{v:.1f}"
        if isinstance(v, float):
            return f"{v:.4f}"
        return str(v)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(COLUMNS)
    for r in rows:
        w.writerow([fmt(c, r[c]) for c in COLUMNS])
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="exit 1 if the file would change")
    args = ap.parse_args()
    rows = build()
    text = to_csv(rows)
    usable = [r for r in rows if r["usable"]]
    print(f"{len(rows)} countries fitted, {len(usable)} usable: "
          + ", ".join(f"{r['country']} {r['shape']:.1f}" for r in usable))
    print(f"median shape over usable fits: {default_shape(rows)}")
    old = OUT_PATH.read_text(encoding="utf-8") if OUT_PATH.exists() else None
    if args.check:
        if old == text:
            print(f"OK: {OUT_PATH.relative_to(ROOT)} is up to date")
            return 0
        print(f"STALE: {OUT_PATH.relative_to(ROOT)}; run scripts/fit_fleet_survival.py", file=sys.stderr)
        return 1
    if old != text:
        OUT_PATH.write_text(text, encoding="utf-8")
        print(f"Wrote {OUT_PATH.relative_to(ROOT)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
