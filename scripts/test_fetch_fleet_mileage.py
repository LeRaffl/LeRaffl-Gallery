#!/usr/bin/env python3
"""Regression tests for scripts/fetch_fleet_mileage.py (no network).

Run:  python scripts/test_fetch_fleet_mileage.py

Pins the SSB JSON-stat decoding (fuel codes, the two contents, missing cells),
the upsert rule that protects curated rows of other sources, and the committed
file the Energy view's kilometres come from.
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_fleet_mileage as fm  # noqa: E402

checks = []


def check(ok, msg):
    checks.append((bool(ok), msg))


def ssb(cells, years=("2024", "2025")):
    """Tiny JSON-stat2 document in SSB's dimension order; cells[(fuel, content, year)] = value."""
    dims = {"Kjoretoytype": ["15"], "DrivstoffType": ["0", "1", "18", "13"],
            "ContentsCode": [fm.SSB_TOTAL, fm.SSB_CONTENT], "Tid": list(years)}
    ids = list(dims)
    values = [cells.get((f, c, y)) for f in dims["DrivstoffType"] for c in dims["ContentsCode"] for y in dims["Tid"]]
    return {"id": ids, "size": [len(dims[k]) for k in ids],
            "dimension": {k: {"category": {"index": {v: i for i, v in enumerate(dims[k])}}} for k in ids},
            "value": values}


doc = ssb({("0", fm.SSB_CONTENT, "2025"): 11350, ("0", fm.SSB_TOTAL, "2025"): 36091.1,
           ("1", fm.SSB_CONTENT, "2025"): 7622, ("1", fm.SSB_TOTAL, "2025"): 5987.0,
           ("18", fm.SSB_CONTENT, "2025"): 13453, ("18", fm.SSB_TOTAL, "2025"): 13227,
           ("18", fm.SSB_CONTENT, "2024"): 250,                       # a handful of cars: noise
           ("13", fm.SSB_CONTENT, "2025"): 9000})                     # hydrogen: not a class we carry
rows = fm.parse_ssb(doc)
by = {(r["year"], r["fuel"]): r for r in rows}
check(set(by) == {(2025, "ALL"), (2025, "PETROL"), (2025, "BEV")}, f"fuel codes map to our classes; nulls, noise and other fuels dropped: {sorted(by)}")
check(by[(2025, "BEV")]["km_per_car"] == 13453 and by[(2025, "BEV")]["total_mkm"] == "13227", "average and total land in their own columns")
check(by[(2025, "ALL")]["total_mkm"] == "36091.1" and by[(2025, "PETROL")]["total_mkm"] == "5987", "totals keep their decimals, no trailing zeros")
check(all(r["country"] == "Norway" and r["source"] == fm.SSB_SOURCE for r in rows), "rows are Norway's and carry the SSB source")

curated = [{"country": "Germany", "year": "2025", "fuel": "BEV", "km_per_car": "11312", "total_mkm": "", "source": "KBA", "notes": "n"},
           {"country": "Norway", "year": "2025", "fuel": "BEV", "km_per_car": "1", "total_mkm": "", "source": "hand", "notes": ""},
           {"country": "Norway", "year": "2019", "fuel": "ALL", "km_per_car": "999", "total_mkm": "", "source": fm.SSB_SOURCE, "notes": ""}]
merged = fm.upsert(rows, curated, fm.SSB_SOURCE)
key = {(r["country"], int(r["year"]), r["fuel"]): r for r in merged}
check(key[("Germany", 2025, "BEV")]["source"] == "KBA", "a curated row of another country is kept")
check(key[("Norway", 2025, "BEV")]["source"] == "hand", "a fetched row never overwrites another source's row with the same key")
check(("Norway", 2019, "ALL") not in key, "this script's own stale rows are replaced, not accumulated")
check([r["country"] for r in merged] == sorted(r["country"] for r in merged), "output is sorted by country")
text = fm.to_csv(merged)
check(text.splitlines()[0] == ",".join(fm.COLUMNS) and fm.to_csv(fm.upsert(rows, merged, fm.SSB_SOURCE)) == text, "writing is idempotent")

# --- the committed file ------------------------------------------------------
with fm.OUT_PATH.open(newline="", encoding="utf-8") as fh:
    live = list(csv.DictReader(fh))
latest = {}
for r in live:
    latest[(r["country"], r["fuel"])] = r
check({"Norway", "Germany"} <= {r["country"] for r in live}, "Norway (fetched) and Germany (curated) are both in the file")
check(all(r["fuel"] in fm.FUELS for r in live), "only known fuel classes")
check(all(r["km_per_car"] == "" or fm.MIN_KM <= float(r["km_per_car"]) <= fm.MAX_KM for r in live), "per-car averages are plausible")
check(all(r["km_per_car"] or r["total_mkm"] for r in live), "every row carries an average or a total")
check(all(r["source"] for r in live), "every row names its source")
no = lambda f: float(latest[("Norway", f)]["km_per_car"])  # noqa: E731
check(no("PETROL") < no("ALL") < no("BEV"), "Norway: petrol cars are driven least, battery cars most (the point of the file)")

bad = [msg for ok, msg in checks if not ok]
for msg in bad:
    print("FAIL:", msg)
print(f"{len(checks) - len(bad)}/{len(checks)} passed")
sys.exit(1 if bad else 0)
