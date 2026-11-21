#!/usr/bin/env python3
"""Regression tests for the 0-vs-empty rule in fetch_uruguay.py (#437).

Run with plain Python, no test framework and no network:

    python scripts/test_fetch_uruguay.py

The workbook is built in memory with openpyxl in the 2026 Compilado layout
(title row, a "Combustible" header with the twelve month names, one row per
model, a closing TOTAL row).
"""
import io
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_uruguay as fu  # noqa: E402

MONTHS = fu.SPANISH_MONTHS


def _sheet(wb, name, models):
    """models: list of (fuel code, January units)."""
    ws = wb.create_sheet(name)
    ws.append(["COMPILADO 2026"])
    ws.append(["Nombre_Socio", "Marca", "Modelo", "Combustible", *MONTHS])
    for code, jan in models:
        ws.append(["Socio", "Marca", "Modelo", code, jan] + [0] * 11)
    ws.append(["TOTAL", None, None, None, sum(j for _, j in models)] + [0] * 11)


def _workbook(sheets):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, models in sheets.items():
        _sheet(wb, name, models)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_code_absent_from_whole_workbook_is_empty():
    # No MHEV anywhere (the 2024/2025 taxonomy): OTHERS is not reported.
    wb = _workbook({"AUTOS": [("E", 10), ("N", 50), ("H", 5)],
                    "SUV": [("D", 3), ("PHEV", 2)],
                    "OMNIBUS": [("D", 4)]})
    row = fu.parse_workbook(wb, 2026, "Whole")["2026-01"]
    assert row["OTHERS"] == "", row
    assert row["BEV"] == 10 and row["PETROL"] == 50 and row["PHEV"] == 2
    assert row["TOTAL"] == 70


def test_code_used_elsewhere_is_a_genuine_zero():
    # MHEV is used on AUTOS, so a bus sheet without MHEV rows sold zero, and
    # no petrol bus with petrol listed on AUTOS is a zero too.
    wb = _workbook({"AUTOS": [("E", 10), ("N", 50), ("MHEV", 7)],
                    "SUV": [("D", 3)],
                    "OMNIBUS": [("D", 4), ("E", 1)]})
    whole = fu.parse_workbook(wb, 2026, "Whole")["2026-01"]
    assert whole["OTHERS"] == 7 and whole["HEV"] == "" and whole["PHEV"] == ""
    buses = fu.parse_workbook(wb, 2026, "Buses")["2026-01"]
    assert buses["OTHERS"] == 0.0 and buses["PETROL"] == 0.0, buses
    assert buses["DIESEL"] == 4 and buses["TOTAL"] == 5


def test_upsert_fills_empty_but_keeps_sourced_values():
    import csv
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "Uruguay.csv"
        path.write_text(
            ",".join(fu.CSV_COLUMNS) + "\r\n"
            "2026-01,monthly,Whole,ACAU,10.0,2.0,5.0,50.0,3.0,,70.0,a.xlsx\r\n",
            encoding="utf-8")
        new = {"2026-01": {"period": "2026-01", "time_interval": "monthly",
                           "variant": "Whole", "source": "ACAU", "BEV": 11.0,
                           "PHEV": 2.0, "HEV": 5.0, "PETROL": 50.0, "DIESEL": 3.0,
                           "OTHERS": 0.0, "TOTAL": 71.0}}
        assert fu.upsert_csv(str(path), new, "b.xlsx", force=False) == (0, 1)
        with open(path, newline="", encoding="utf-8") as f:
            row = next(csv.DictReader(f))
        # the empty OTHERS is filled; sourced values and notes stay untouched
        assert row["OTHERS"] == "0.0" and row["BEV"] == "10.0", row
        assert row["notes"] == "a.xlsx"
        assert b"\r\n" in path.read_bytes()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
