#!/usr/bin/env python3
"""Offline tests for scripts/backfill_hev_history.py (no network)."""
import csv
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backfill_hev_history as bh  # noqa: E402

HEAD = "period,time_interval,variant,source,BEV,PHEV,HEV,PETROL,DIESEL,OTHERS,TOTAL,notes\n"


def test_acea_split_keeps_the_row_and_its_sum():
    row = {"period": "2019-02", "TOTAL": "1000", "BEV": "10", "PHEV": "20", "OTHERS": "30",
           "PETROL": "640", "DIESEL": "290"}
    q = {"quarter": "2019-Q1", "HEV": "100", "PETROL": "600", "DIESEL": "300"}
    est = bh.acea_estimate(row, q, 0)
    assert est["HEV"] == round(940 * 0.1) and est["DIESEL"] == round(940 * 0.3)
    assert est["HEV"] + est["PETROL"] + est["DIESEL"] == 940            # pool kept
    assert est["notes"].startswith(bh.HISTORY_PREFIX) and "2019-Q1" in est["notes"]


def test_acea_hev_only_quarter_uses_the_quarter_pool_and_the_months_ratio():
    row = {"period": "2016-02", "TOTAL": "1000", "BEV": "0", "PHEV": "0", "OTHERS": "0",
           "PETROL": "600", "DIESEL": "400"}
    q = {"quarter": "2016-Q1", "HEV": "30", "PETROL": "", "DIESEL": ""}
    est = bh.acea_estimate(row, q, 3000)                                   # 1 % of the pool
    assert est["HEV"] == 10 and est["DIESEL"] == round(990 * 0.4) and est["PETROL"] == 990 - 396
    assert "petrol:diesel as in the month" in est["notes"]


def test_register_share_splits_the_published_petrol():
    row = {"PETROL": "2000"}
    est = bh.register_estimate(row, {"HEV": "300", "PETROL": "700"}, "StatFin",
                               "Traficom register", "fi_register_fuel_split.csv")
    assert est == {"HEV": 600.0, "PETROL": 1400.0, "notes": est["notes"]}
    assert "StatFin petrol" in est["notes"] and "fi_register_fuel_split.csv" in est["notes"]
    assert bh.register_estimate(row, {"HEV": "0", "PETROL": "0"}, "s", "r", "f") is None
    # Petrol blank but diesel published: nothing to split, never a zero.
    assert bh.register_estimate({"PETROL": "", "DIESEL": "50"}, {"HEV": "3", "PETROL": "7"},
                                "s", "r", "f") is None


def test_register_total_share_when_the_source_has_no_combustion_split():
    """Netherlands before 2018: BEV, PHEV, TOTAL only, the plug-ins smoothed
    over the year. HEV is TOTAL times the register's HEV share of all the
    month's cars; petrol and diesel stay blank (invariant 4)."""
    row = {"TOTAL": "10000", "BEV": "100", "PHEV": "900", "PETROL": "", "DIESEL": "", "OTHERS": ""}
    reg = {"plates": "8000", "HEV": "400", "PETROL": "5000", "DIESEL": "1500", "OTHERS": "200"}
    est = bh.register_estimate(row, reg, "Swing", "RDW register (with_exports cohort)",
                               "nl_register_fuel_split.csv")
    assert set(est) == {"HEV", "notes"} and est["HEV"] == 500.0
    assert est["notes"].startswith(bh.HISTORY_PREFIX) and "petrol/diesel unsplit" in est["notes"]
    # Without a plates column the fuel buckets are the month's cars.
    no_plates = {k: v for k, v in reg.items() if k != "plates"}
    assert bh.register_estimate(row, no_plates, "s", "r", "f")["HEV"] == round(10000 * 400 / 7100)
    assert bh.register_estimate(dict(row, TOTAL=""), reg, "s", "r", "f") is None


def test_run_touches_only_blank_hev_rows_line_level():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        data = tmp / "Testland.csv"
        lines = ["2019-01,monthly,Whole,S,10.0,20.0,,640.0,290.0,30.0,1000.0,",
                 "2019-02,monthly,Whole,S,10.0,20.0,90.0,550.0,290.0,30.0,1000.0,counted",
                 "2019-03,monthly,Whole,S,10.0,20.0,,640.0,290.0,30.0,1000.0,keep me"]
        data.write_text(HEAD + "\n".join(lines) + "\n", encoding="utf-8")
        split = tmp / "split.csv"
        split.write_text("period,cohort,HEV,PETROL\n2019-01,a,100,300\n2019-02,a,1,1\n"
                         "2019-03,a,50,450\n2019-03,b,1,1\n", encoding="utf-8")
        filled = bh.run("Testland", "register", "2019-01", "2019-12", split, "a", data)
        text = data.read_text(encoding="utf-8").splitlines()
    assert sorted(filled) == ["2019-01", "2019-03"]
    assert text[2] == lines[1]                                             # counted row untouched
    rows = {r["period"]: r for r in csv.DictReader(text)}
    assert rows["2019-01"]["HEV"] == "160.0" and rows["2019-01"]["PETROL"] == "480.0"
    assert rows["2019-03"]["HEV"] == "64.0" and rows["2019-03"]["notes"].endswith("; keep me")


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn_ in tests:
        fn_()
        print(f"ok  {name}")
    print(f"{len(tests)} tests passed")
