#!/usr/bin/env python3
"""Regression tests for scripts/fetch_uruguay.py (no network).

Run:  python scripts/test_fetch_uruguay.py

Covers the empty-vs-zero distinction for fuel columns that some Compilado
years don't break out at all (e.g. 2024/2025 have no "MHEV" code, so OTHERS
must come back empty for those years' months, not a fake 0.0), and that a
fuel column present with an explicit zero stays a real 0.0.
"""
import io
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_uruguay as fu  # noqa: E402


def _make_sheet(ws, title, rows):
    """Write a minimal AUTOS/SUV-shaped sheet: title row, header row with
    full Spanish month names, one data row per (code, monthly_values) in
    `rows`, and a TOTAL row summing them."""
    ws.append([title])
    ws.append([None])
    ws.append([None])
    ws.append(["Nombre_Socio", "Marca", "Modelo", "Combustible", *fu.SPANISH_MONTHS])
    totals = [0.0] * 12
    for code, vals in rows:
        ws.append(["ACME", "ACME", "MODEL", code, *vals])
        for j in range(12):
            totals[j] += vals[j]
    ws.append(["TOTAL", None, None, None, *totals])


def _workbook(year, rows_by_sheet):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in rows_by_sheet.items():
        ws = wb.create_sheet(name)
        _make_sheet(ws, f"COMPILADO {year}", rows)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_missing_code_leaves_column_empty():
    # No MHEV row anywhere → OTHERS must be empty, not 0.0 (the 2024/2025 case).
    jan = [1.0] + [0.0] * 11
    rows = {
        "AUTOS": [("E", jan), ("N", jan), ("D", jan)],
        "SUV": [("N", jan)],
    }
    out = fu.parse_workbook(_workbook(2024, rows), 2024)
    row = out["2024-01"]
    assert row["OTHERS"] == "", row["OTHERS"]
    assert row["BEV"] == 1.0 and row["PETROL"] == 2.0 and row["DIESEL"] == 1.0
    assert row["TOTAL"] == 4.0


def test_explicit_zero_code_stays_zero():
    # MHEV row present with an all-zero January → OTHERS is a real 0.0 that month.
    jan = [1.0] + [0.0] * 11
    zero = [0.0] * 12
    rows = {
        "AUTOS": [("E", jan), ("N", jan), ("MHEV", zero)],
        "SUV": [("N", jan)],
    }
    out = fu.parse_workbook(_workbook(2026, rows), 2026)
    row = out["2026-01"]
    assert row["OTHERS"] == 0.0
    assert row["TOTAL"] == 3.0


def test_code_present_in_one_sheet_only_still_counts_as_reported():
    # MHEV only has a row in SUV, none in AUTOS — the Whole variant sums
    # both sheets, so OTHERS must be reported (0.0), not left empty, because
    # the code is known to this workbook.
    jan_e = [1.0] + [0.0] * 11
    jan_m = [2.0] + [0.0] * 11
    rows = {
        "AUTOS": [("N", jan_e)],
        "SUV": [("N", jan_e), ("MHEV", jan_m)],
    }
    out = fu.parse_workbook(_workbook(2026, rows), 2026)
    row = out["2026-01"]
    assert row["OTHERS"] == 2.0
    assert row["TOTAL"] == 4.0


def test_unknown_code_folds_into_others_and_counts_as_present():
    jan = [1.0] + [0.0] * 11
    rows = {
        "AUTOS": [("N", jan), ("GNC", jan)],   # unknown code → OTHERS, with presence
        "SUV": [("N", jan)],
    }
    out = fu.parse_workbook(_workbook(2026, rows), 2026)
    row = out["2026-01"]
    assert row["OTHERS"] == 1.0
    assert row["TOTAL"] == 3.0


def test_all_zero_month_still_skipped():
    zero = [0.0] * 12
    rows = {
        "AUTOS": [("N", zero)],
        "SUV": [("N", zero)],
    }
    out = fu.parse_workbook(_workbook(2026, rows), 2026)
    assert out == {}


def test_sheet_total_mismatch_raises():
    jan = [1.0] + [0.0] * 11
    rows = {"AUTOS": [("N", jan)], "SUV": [("N", jan)]}
    wb_bytes = _workbook(2026, rows)
    wb = openpyxl.load_workbook(io.BytesIO(wb_bytes))
    ws = wb["AUTOS"]
    # Corrupt the TOTAL row's January cell so it no longer matches the sum.
    for r in ws.iter_rows():
        if r[0].value == "TOTAL":
            r[4].value = 999.0
    buf = io.BytesIO()
    wb.save(buf)
    try:
        fu.parse_workbook(buf.getvalue(), 2026)
    except RuntimeError as e:
        assert "TOTAL row" in str(e)
    else:
        raise AssertionError("mismatched TOTAL row must raise")


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
