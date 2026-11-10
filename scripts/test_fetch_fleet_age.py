#!/usr/bin/env python3
"""Regression tests for scripts/fetch_fleet_age.py and scripts/fit_fleet_survival.py
(no network).

Run:  python scripts/test_fetch_fleet_age.py

Pins the JSON-stat decoding of the two Eurostat tables, the row gates, and -
because a fit that cannot recover a known answer proves nothing - that the
survival fit returns the shape and scale a synthetic fleet was built with.
"""
import csv
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_fleet_age as fa  # noqa: E402
import fit_fleet_survival as fs  # noqa: E402

checks = []


def check(ok, msg):
    checks.append((bool(ok), msg))


def jsonstat(dims, cells):
    ids = list(dims)
    size = [len(dims[k]) for k in ids]

    def flat(key):
        f = 0
        for k, s, v in zip(ids, size, key):
            f = f * s + dims[k].index(v)
        return str(f)
    return {"id": ids, "size": size,
            "dimension": {k: {"category": {"index": {v: i for i, v in enumerate(dims[k])}}} for k in ids},
            "value": {flat(k): v for k, v in cells.items()}}


AGE_DIMS = {"freq": ["A"], "unit": ["NR"], "age": ["TOTAL", *fa.BANDS], "geo": ["DE", "FI", "PL", "SE"], "time": ["2024", "2025"]}
cells = {}
for geo, year, vals, total in [("DE", "2025", [10, 20, 30, 30, 10], 100), ("FI", "2025", [5, 10, 20, 30, 35], 100),
                               ("PL", "2025", [5, 5, 10, 40, 40], 100),            # not a fleet country
                               ("SE", "2025", [10, 20, 30, 30, 10], 150)]:         # bands miss TOTAL by a third
    cells[("A", "NR", "TOTAL", geo, year)] = total
    for b, v in zip(fa.BANDS, vals):
        cells[("A", "NR", b, geo, year)] = v
cells[("A", "NR", "Y_LT2", "DE", "2024")] = 12                                    # one band only
ages = fa.age_rows(jsonstat(AGE_DIMS, cells))
check([(r["country"], r["year"]) for r in ages] == [("Finland", 2025), ("Germany", 2025)],
      f"complete, consistent rows of fleet countries only: {[(r['country'], r['year']) for r in ages]}")
check(ages[0]["gt20"] == 35 and ages[0]["total"] == 100 and ages[0]["source"] == fa.AGE_SOURCE, "bands land in their columns")

REG_DIMS = {"freq": ["A"], "unit": ["NR"], "mot_nrg": ["TOTAL", "PET"], "engine": ["TOTAL", "CC_LT1400"], "geo": ["DE", "PL"], "time": ["1970", "1975", "2025"]}
regs = fa.reg_rows(jsonstat(REG_DIMS, {
    ("A", "NR", "TOTAL", "TOTAL", "DE", "1970"): 2107123, ("A", "NR", "TOTAL", "TOTAL", "DE", "2025"): 2857591,
    ("A", "NR", "PET", "TOTAL", "DE", "2025"): 800000, ("A", "NR", "TOTAL", "CC_LT1400", "DE", "2025"): 500000,
    ("A", "NR", "TOTAL", "TOTAL", "PL", "2025"): 500000, ("A", "NR", "TOTAL", "TOTAL", "DE", "1975"): 0}))
check([(r["country"], r["year"], r["new_registrations"]) for r in regs] == [("Germany", 1970, 2107123), ("Germany", 2025, 2857591)],
      "registration history = TOTAL x TOTAL only; gaps stay gaps (no zero, no interpolation)")
text = fa.to_csv(ages, fa.AGE_COLUMNS)
check(text.splitlines()[0] == ",".join(fa.AGE_COLUMNS) and len(text.splitlines()) == 3, "CSV header and one line per row")

# --- the fit recovers a known survival curve ---------------------------------
TRUE_SHAPE, TRUE_SCALE = 2.6, 19.0
reg = {y: 100000 + 500 * (y - 1960) for y in range(1960, 2026)}
synthetic = {}
for y in range(2016, 2026):
    synthetic[y] = {b: sum(reg[y - a] * math.exp(-((a + 0.5) / TRUE_SCALE) ** TRUE_SHAPE) for a in range(lo, min(hi, y - 1959)))
                    for b, (lo, hi) in fs.BANDS.items()}
fit = fs.fit_country(synthetic, reg)
check(fit and abs(fit["shape"] - TRUE_SHAPE) < 0.11 and abs(fit["scale"] - TRUE_SCALE) < 0.51,
      f"fit recovers shape {TRUE_SHAPE} / scale {TRUE_SCALE}: got {fit and (fit['shape'], fit['scale'])}")
check(fit and fit["rmse"] < 1e-3 and fit["rmse_shape_4"] > fit["rmse"], "a perfect curve fits with ~zero error, a wrong shape with more")
check(fs.fit_country({2025: synthetic[2025], 2024: synthetic[2024]}, reg) is None, "fewer than three stock years: no fit")
check(fs.fit_country(synthetic, {y: v for y, v in reg.items() if y > 2005}) is None, "without 30 years of registrations: no fit")
check(fs.default_shape([{"shape": 2.0, "usable": True}, {"shape": 3.0, "usable": True}, {"shape": 9.0, "usable": False}]) == 2.5,
      "default shape = median of the usable fits only")

# --- the committed files ------------------------------------------------------
with fa.AGE_PATH.open(newline="", encoding="utf-8") as fh:
    live = list(csv.DictReader(fh))
check(len({r["country"] for r in live}) >= 20, "age bands cover at least 20 fleet countries")
check(all(abs(sum(int(r[c]) for c in fa.BANDS.values()) - int(r["total"])) <= fa.BAND_TOLERANCE * int(r["total"]) for r in live),
      "the five bands add up to the total on every row")
share = {(r["country"], r["year"]): int(r["gt20"]) / int(r["total"]) for r in live}
check(share[("Finland", "2025")] > 0.3 > 0.15 > share[("Switzerland", "2025")], "Finland's fleet is far older than Switzerland's")
with fa.REG_PATH.open(newline="", encoding="utf-8") as fh:
    hist = list(csv.DictReader(fh))
check(min(int(r["year"]) for r in hist) <= 1975 and all(int(r["new_registrations"]) > 0 for r in hist), "registration history reaches the 1970s, no zeros")
with fs.OUT_PATH.open(newline="", encoding="utf-8") as fh:
    fits = list(csv.DictReader(fh))
usable = [float(r["shape"]) for r in fits if r["usable"] == "yes"]
check(len(usable) >= 5 and 2.0 <= statistics.median(usable) <= 3.5, f"usable fits put the shape between 2 and 3.5: {usable}")
check(all(float(r["rmse"]) < fs.MAX_RMSE for r in fits if r["usable"] == "yes"), "every usable fit is a decent fit")

bad = [msg for ok, msg in checks if not ok]
for msg in bad:
    print("FAIL:", msg)
print(f"{len(checks) - len(bad)}/{len(checks)} passed")
sys.exit(1 if bad else 0)
