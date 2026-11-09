#!/usr/bin/env python3
"""Regression tests for scripts/fetch_grid_mix.py (no network).

Run:  python scripts/test_fetch_grid_mix.py

Pins the OWID -> fleet/grid_mix.csv mapping (country names, the World
fallback, the row gates) and sanity-checks the committed file, which the
Fleet tab's emissions figure depends on for every country.
"""
import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_grid_mix as fg  # noqa: E402

checks = []


def check(ok, msg):
    checks.append((bool(ok), msg))


def owid(country, year, intensity, **shares):
    base = {col: "" for col in fg.SHARES.values()}
    for k, v in shares.items():
        base[fg.SHARES[k]] = str(v)
    return {"country": country, "year": str(year), fg.INTENSITY: "" if intensity is None else str(intensity), **base}


SRC = [
    owid("World", 2024, 471.08, coal=34, gas=22, oil=3, nuclear=9, hydro=14, wind=8, solar=7, bio=2.5, other_renew=0.5),
    owid("Norway", 2024, 29.66, gas=1, hydro=89, wind=10),
    owid("Norway", 2009, 20.0, hydro=100),                        # before START_YEAR
    owid("Turkey", 2024, 474.7, coal=35, gas=20, hydro=20, wind=11, solar=8, other_renew=6),
    owid("Germany", 2024, None, coal=21, gas=16, oil=4, hydro=5, wind=29, solar=15, bio=10),   # no intensity
    owid("Germany", 2023, 362.9, coal=26, gas=15),                # shares do not add up
    owid("Poland", 2024, 608.2, coal=57, gas=12, wind=15, solar=10, bio=6),                    # not a fleet country
]
rows, skipped = fg.build_rows(SRC, ["Norway", "Türkiye", "Germany"])
by = {(r["country"], r["year"]): r for r in rows}

check(rows[0]["country"] == "World", "World sorts first")
check(("Norway", 2024) in by and by[("Norway", 2024)]["gco2_kwh"] == 29.66, "a fleet country is kept with its intensity")
check(("Norway", 2009) not in by, "years before START_YEAR are dropped")
check(("Türkiye", 2024) in by, "OWID 'Turkey' is written under the fleet name 'Türkiye'")
check(("Poland", 2024) not in by, "a country outside the fleet list is not written")
check(("Germany", 2024) not in by and ("Germany", 2023) not in by,
      "rows without an intensity, or whose shares miss 100 %, are skipped")
check({(c, y) for c, y, _ in skipped} == {("Germany", 2024), ("Germany", 2023)}, "...and reported as skipped")
check(by[("Norway", 2024)]["coal"] is None, "an unreported share stays blank, not zero")

text = fg.to_csv(rows)
parsed = list(csv.DictReader(io.StringIO(text)))
check(list(parsed[0].keys()) == fg.COLUMNS, "CSV header = COLUMNS")
nor = next(r for r in parsed if r["country"] == "Norway")
check(nor["gco2_kwh"] == "29.7" and nor["coal"] == "" and nor["hydro"] == "89.0", f"one decimal, blank stays blank: {nor}")

# --- the committed file ------------------------------------------------------
with fg.OUT_PATH.open(newline="", encoding="utf-8") as fh:
    live = list(csv.DictReader(fh))
countries = {r["country"] for r in live}
fleet = set(fg.fleet_countries())
check("World" in countries, "committed file has the World fallback")
check(not (fleet - countries), f"every fleet country has grid rows (missing: {sorted(fleet - countries)})")
check(all(0 < float(r["gco2_kwh"]) < 1200 for r in live), "intensities are in gCO2e/kWh, 0..1200")
tot = lambda r: sum(float(r[k] or 0) for k in fg.SHARES)  # noqa: E731
check(all(abs(tot(r) - 100) <= fg.SHARE_TOLERANCE + 0.5 for r in live), "shares add up to 100 % on every row")
latest = {}
for r in live:
    latest[r["country"]] = r
check(float(latest["Norway"]["gco2_kwh"]) < 80 < 300 < float(latest["China"]["gco2_kwh"]),
      "hydro Norway is far cleaner than coal-heavy China (the point of the file)")
check(all(int(r["year"]) >= 2023 for r in latest.values()), "every series reaches a recent year")

bad = [msg for ok, msg in checks if not ok]
for msg in bad:
    print("FAIL:", msg)
print(f"{len(checks) - len(bad)}/{len(checks)} passed")
sys.exit(1 if bad else 0)
