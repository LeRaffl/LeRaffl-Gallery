#!/usr/bin/env python3
"""Offline tests for scripts/build_acea_quarterly.py (no network)."""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_acea_quarterly as bq  # noqa: E402


def _xlsx(layout: str) -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for sheet, (cur, prev) in {"BEV": (10, 5), "PHEV": (20, 8), "HEV": (300, 200),
                               "Petrol": (4000, 4500), "Diesel": (900, 1200)}.items():
        ws = wb.create_sheet(sheet)
        ws.append([None, None, None, "Q2", "Q2", "%"])
        ws.append([None, "Units", None, None, "% change"])
        if layout == "old":          # name in C, numbers from D (2018-2020 files)
            ws.append([None, None, "FINLAND", cur, prev, 1.0])
            ws.append([None, None, "CZECH REPUBLIC", cur * 2, prev * 2, 1.0])
            ws.append([None, None, "EUROPEAN UNION", 1, 1, 1.0])
        else:                        # name in B, numbers from C (2021-2022 files)
            ws.append([None, "Finland", cur, prev, 1.0])
            ws.append([None, "% change", 1, 2])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_both_layouts_and_both_columns():
    old = bq.parse_release(_xlsx("old"), "20180905_Fuel_types_Q2_2018_FINAL.xlsx")
    by = {(r["country"], r["quarter"]): r for r in old}
    fi = by[("Finland", "2018-Q2")]
    assert (fi["BEV"], fi["PHEV"], fi["HEV"], fi["PETROL"], fi["DIESEL"]) == (10, 20, 300, 4000, 900)
    assert fi["column"] == "quarter" and by[("Finland", "2017-Q2")]["HEV"] == 200
    assert by[("Czechia", "2018-Q2")]["HEV"] == 600           # Czech Republic -> Czechia
    assert not any(r["country"].upper().startswith("EUROPEAN") for r in old)
    new = bq.parse_release(_xlsx("new"), "20220720_PRPC-fuel_Q2-2022_FINAL.xlsx")
    assert {r["country"] for r in new} == {"Finland"}         # "% change" is no country
    assert [r["quarter"] for r in new] == ["2022-Q2", "2021-Q2"]


def test_release_quarter():
    assert bq.release_quarter("20190207_PRPC_fuel_Q4_2018_FINAL.xlsx") == (2018, 4)
    assert bq.release_quarter("20210723_PRPC-fuel_Q2-2021_FINAL.xlsx") == (2021, 2)


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn_ in tests:
        fn_()
        print(f"ok  {name}")
    print(f"{len(tests)} tests passed")
