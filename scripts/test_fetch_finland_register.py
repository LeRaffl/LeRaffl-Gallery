"""Register shadow for Finland. No network, no CSV write."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_finland_register as fn


def test_fuel_bucket_splits_full_hybrid_out_of_petrol():
    assert fn.fuel_bucket("01", "true", "02") == "HEV"
    assert fn.fuel_bucket("01", "true", "01") == "PHEV"
    assert fn.fuel_bucket("04", "false", "") == "BEV"
    assert fn.fuel_bucket("01", "false", "") == "PETROL"
    assert fn.fuel_bucket("02", "false", "") == "DIESEL"
    # An unclassified hybrid is not a silent HEV.
    assert fn.fuel_bucket("01", "true", "03") == "OTHERS"


def test_dates_are_not_iso():
    assert fn.registration_period("15.09.2026") == "2026-09"
    assert fn.registration_period("2026-09-15") is None
    assert fn.use_period("20260915") == "2026-09"
    assert fn.use_period("15.09.2026") is None


def test_cohort_keeps_used_imports_out_of_whole():
    assert fn.cohort("M1", "2026-09", "2026-09") == "whole"
    assert fn.cohort("M1G", "2026-09", "2026-09") == "whole"
    assert fn.cohort("M1", "2026-09", "2024-03") == "used"
    assert fn.cohort("M1", "2026-09", None) is None
    assert fn.cohort("M1", "2026-09", "2026-10") is None
    assert fn.cohort("N1", "2026-09", "2026-09") is None


def test_enrich_keeps_statfin_total_and_refuses_a_negative_residual():
    statfin = {"TOTAL": 7566, "BEV": 3644, "PHEV": 911, "DIESEL": 300, "OTHERS": 0}
    ok = fn.enrich_statfin(statfin, {"HEV": 1800, "PETROL": 800})
    assert ok["TOTAL"] == 7566 and ok["BEV"] == 3644 and ok["PHEV"] == 911
    assert ok["DIESEL"] == 300 and ok["HEV"] == 1800 and ok["PETROL"] == 800
    assert ok["OTHERS"] == 111
    assert fn.enrich_statfin(statfin, {"HEV": 2712, "PETROL": 1}) is None
    # A month StatFin has not published yet is a refusal, not a crash.
    assert fn.enrich_statfin(None, {"HEV": 1, "PETROL": 1}) is None


def test_fill_window_keeps_the_thinned_years_on_acea():
    """Register HEV before 2025-01 sits on a thinned cohort (about -15% in
    2014) and would understate the hybrid share against a full StatFin
    total. Those months stay with ACEA."""
    assert fn.in_fill_window("2025-01")
    assert fn.in_fill_window("2026-09")
    assert not fn.in_fill_window("2024-12")
    assert not fn.in_fill_window("2014-06")


def test_count_rows_splits_whole_and_used_for_one_month():
    rows = [
        {"ajoneuvoluokka": "M1", "ensirekisterointipvm": "15.09.2026",
         "kayttoonottopvm": "20260915", "kayttovoima": "01",
         "sahkohybridi": "true", "sahkohybridinluokka": "02"},
        {"ajoneuvoluokka": "M1", "ensirekisterointipvm": "15.09.2026",
         "kayttoonottopvm": "20240301", "kayttovoima": "04",
         "sahkohybridi": "false", "sahkohybridinluokka": ""},
        {"ajoneuvoluokka": "M1", "ensirekisterointipvm": "2026-09-15",
         "kayttoonottopvm": "20260915", "kayttovoima": "01",
         "sahkohybridi": "false", "sahkohybridinluokka": ""},
    ]
    counted = fn.count_rows(rows, "2026-09")
    assert counted["whole"]["HEV"] == 1
    assert counted["used"]["BEV"] == 1
    assert sum(counted["whole"].values()) == 1


def test_tally_keeps_every_month_in_one_pass():
    rows = [
        {"ajoneuvoluokka": "M1", "ensirekisterointipvm": "15.06.2026",
         "kayttoonottopvm": "20260615", "kayttovoima": "01",
         "sahkohybridi": "true", "sahkohybridinluokka": "02"},
        {"ajoneuvoluokka": "M1G", "ensirekisterointipvm": "02.09.2026",
         "kayttoonottopvm": "20220101", "kayttovoima": "04",
         "sahkohybridi": "false", "sahkohybridinluokka": ""},
    ]
    tallied = fn.tally(rows)
    assert tallied["2026-06"]["whole"]["HEV"] == 1
    assert tallied["2026-09"]["used"]["BEV"] == 1
    assert "2026-06" not in tallied or "used" not in tallied["2026-06"] or not tallied["2026-06"]["used"]


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    failed = 0
    for name, fn_ in tests:
        try:
            fn_()
        except Exception as exc:
            failed += 1
            print(f"FAIL {name}: {exc}")
        else:
            print(f"ok  {name}")
    print(f"{len(tests) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
