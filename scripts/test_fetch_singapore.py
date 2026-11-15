#!/usr/bin/env python3
"""Offline test for the Singapore writer (scripts/fetch_singapore.py).

    python scripts/test_fetch_singapore.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_singapore as fs  # noqa: E402


def test_a_fuel_with_no_units_is_written_as_zero_not_empty():
    cols = {c: 0.0 for c in fs.VALUE_COLUMNS}
    cols["BEV"], cols["PETROL"] = 2504.0, 247.0
    row = fs.build_rows({"2026-10": cols}, None)[("2026-10", fs.VARIANT)]
    assert row["DIESEL"] == 0.0 and row["OTHERS"] == 0.0
    assert all(row[c] != "" for c in fs.VALUE_COLUMNS)
    assert row["TOTAL"] == 2751.0


def test_a_month_with_no_vehicles_is_not_written():
    assert fs.build_rows({"2026-11": {c: 0.0 for c in fs.VALUE_COLUMNS}}, None) == {}


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} tests passed")
