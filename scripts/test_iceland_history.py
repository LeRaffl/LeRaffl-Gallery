#!/usr/bin/env python3
"""Pin Iceland's 2018 history: no HEV/PETROL/DIESEL/OTHERS split was reported.

Run:  python scripts/test_iceland_history.py

data/Iceland.csv 2018-01..2018-12 came from the bulk import with TOTAL in the
hundreds or low thousands but only BEV and PHEV filled; the combustion split
columns were stored as 0.0. A 0 claims "zero petrol cars" and, inside the
strict TTM window, drags the early 2019 shares (Other read 75 % in 2019-01).
The cells are empty instead (AGENTS.md invariant 4). 2019 onward carries a
rescaled class split and is not touched here.
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPLIT = ("HEV", "PETROL", "DIESEL", "OTHERS")


def _whole():
    with (ROOT / "data" / "Iceland.csv").open(newline="", encoding="utf-8") as f:
        return {r["period"]: r for r in csv.DictReader(f) if r["variant"] == "Whole"}


def test_2018_split_is_unreported_not_zero():
    rows = _whole()
    months = [f"2018-{m:02d}" for m in range(1, 13)]
    for p in months:
        assert p in rows, f"{p} missing"
        for c in SPLIT:
            assert rows[p][c] == "", f"{p} {c} = {rows[p][c]!r}, expected empty"
        assert rows[p]["TOTAL"] != "" and rows[p]["BEV"] != "" and rows[p]["PHEV"] != ""


def test_2019_onward_keeps_its_split():
    rows = _whole()
    assert float(rows["2019-01"]["PETROL"]) > 100
    assert float(rows["2019-12"]["PETROL"]) > 0


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {name}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
