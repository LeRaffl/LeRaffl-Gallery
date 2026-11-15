#!/usr/bin/env python3
"""Regression tests for scripts/fetch_fleet_norway.py (no network).

Run:  python scripts/test_fetch_fleet_norway.py

Pins the SSB 11823 decoding (vehicle groups to variants, fuels to columns,
euro classes summed), the upsert that must never touch a passenger-car row or
another country, and the committed rows.
"""
import csv
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_fleet_norway as fn  # noqa: E402

checks = []


def check(ok, msg):
    checks.append((bool(ok), msg))


def ssb(cells):
    """JSON-stat2 with SSB's dimensions; cells[(fuel, group, year)] = value."""
    dims = {"Region": ["0"], "DrivstoffType": ["1", "2", "5", "14", "16", "15", "4", "13", "6"],
            "ContentsCode": ["Personbil1", "Varebil4", "Lastebil6", "Buss3", "Kombibil5"], "Tid": ["2024", "2025"]}
    ids = list(dims)
    values = [cells.get((f, g, y)) for f in dims["DrivstoffType"] for g in dims["ContentsCode"] for y in dims["Tid"]]
    return {"id": ids, "size": [len(dims[k]) for k in ids],
            "dimension": {k: {"category": {"index": {v: i for i, v in enumerate(dims[k])}}} for k in ids},
            "value": values}


rows = fn.parse(ssb({("2", "Lastebil6", "2025"): 59017, ("5", "Lastebil6", "2025"): 2576, ("4", "Lastebil6", "2025"): 2259,
                     ("13", "Lastebil6", "2025"): 5, ("6", "Lastebil6", "2025"): 5, ("16", "Lastebil6", "2025"): 3,
                     ("2", "Varebil4", "2025"): 452033, ("14", "Varebil4", "2025"): 100, ("16", "Varebil4", "2025"): 50,
                     ("15", "Varebil4", "2025"): 7, ("1", "Varebil4", "2025"): 0,
                     ("5", "Personbil1", "2025"): 945182, ("2", "Kombibil5", "2025"): 6504}))
by = {(r["variant"], r["year"]): r for r in rows}
check(set(by) == {("HDV", 2025), ("Vans", 2025)}, f"lorries -> HDV, vans -> Vans; cars and combined vehicles are not written: {sorted(by)}")
h = by[("HDV", 2025)]
check((h["BEV"], h["DIESEL"], h["GAS"], h["OTHERS"], h["PHEV"]) == (2576, 59017, 2259, 10, 3) and h["TOTAL"] == 63865,
      f"fuels land in their columns, hydrogen + other in OTHERS, TOTAL is the sum: {h}")
check(h["PETROL"] == "" and h["HEV"] == "", "a fuel with no cell stays blank (not zero)")
v = by[("Vans", 2025)]
check(v["PHEV"] == 150 and v["HEV"] == 7 and v["PETROL"] == 0, "petrol and diesel plug-ins are summed; a reported zero is 0")
check(all(r["country"] == "Norway" and r["source"] == fn.SOURCE and r["notes"] for r in rows), "rows carry country, source and scope note")

header = ",".join(fn.FLEET_COLUMNS)
d = Path(tempfile.mkdtemp()) / "fleet.csv"
before = [header, "Norway,Whole,2025,,945182,,,,,676614,942780,,,,,,22,,", "Sweden,HDV,2025,x,1,,,,,,2,,,,,,,3,",
          "Norway,HDV,2025,old,1,,,,,,2,,,,,,,3,stale", ""]
d.write_text("\n".join(before), encoding="utf-8")
changed, added = fn.upsert(rows, d)
after = d.read_text(encoding="utf-8").split("\n")
check((changed, added) == (1, 1), f"one row replaced, one added: {(changed, added)}")
check(after[1] == before[1] and after[2] == before[2], "the passenger-car row and another country's row are untouched, byte for byte")
check(after[3] == fn.line(h) and fn.line(v) in after and after[-1] == "", "own row replaced in place, new row appended, file ends with a newline")
check(fn.upsert(rows, d) == (0, 0) and d.read_text(encoding="utf-8").split("\n") == after, "a second run changes nothing")

with fn.FLEET_CSV.open(newline="", encoding="utf-8") as fh:
    live = [r for r in csv.DictReader(fh) if r["country"] == "Norway" and r["variant"] != "Whole"]
check({r["variant"] for r in live} == {"Vans", "HDV", "Buses"} and len(live) >= 27, "committed: three classes, 2016 onwards")
check(all(abs(sum(int(r[c] or 0) for c in fn.FLEET_COLUMNS[4:17]) - int(r["TOTAL"])) == 0 for r in live), "committed: the fuels add up to TOTAL on every row")
last = {r["variant"]: r for r in sorted(live, key=lambda r: int(r["year"]))}
check(int(last["Vans"]["TOTAL"]) > int(last["HDV"]["TOTAL"]) > int(last["Buses"]["TOTAL"]) > 5000, "committed: vans > trucks > buses, as in any fleet")

bad = [msg for ok, msg in checks if not ok]
for msg in bad:
    print("FAIL:", msg)
print(f"{len(checks) - len(bad)}/{len(checks)} passed")
sys.exit(1 if bad else 0)
