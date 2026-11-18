#!/usr/bin/env python3
"""Common-window rule and a smoke load of the region flyers."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import region_card as rc
import model_card as mc


def member(name, w, months, share=10):
    rows = [{"period": p, "time_interval": "monthly", "TOTAL": 100, "BEV": share}
            for p in months]
    return {"country": name, "weight": w, "rows": rows}


BASE = ([f"2024-{m:02d}" for m in range(11, 13)]
        + [f"2025-{m:02d}" for m in range(1, 13)]
        + [f"2026-{m:02d}" for m in range(1, 11)])


def test_pick_latest_month_that_covers_80_percent():
    # A+B are 90 % of the weight and run through October; C stops in August.
    A = member("A", 85, BASE)
    B = member("B", 5, BASE)
    C = member("C", 10, [p for p in BASE if p <= "2026-08"])
    t, contrib, cov = rc.pick_common_end([A, B, C])
    assert t == "2026-10"
    assert {m["country"] for m in contrib} == {"A", "B"}
    assert abs(cov - 90.0) < 1e-6


def test_pick_earlier_month_when_latest_misses_the_floor():
    A = member("A", 40, BASE)
    B = member("B", 30, [p for p in BASE if p <= "2026-08"])
    C = member("C", 30, [p for p in BASE if p <= "2026-08"])
    t, contrib, cov = rc.pick_common_end([A, B, C])
    assert t == "2026-08" and len(contrib) == 3 and abs(cov - 100) < 1e-6


def test_pick_max_coverage_when_no_month_reaches_80():
    short = [p for p in BASE if p >= "2026-05"]  # too short for a 12-month window
    A = member("A", 50, BASE)
    B = member("B", 20, BASE)
    C = member("C", 30, short)
    t, contrib, cov = rc.pick_common_end([A, B, C])
    assert t == "2026-10" and len(contrib) == 2 and abs(cov - 70) < 1e-6


def test_empty_cell_is_not_a_zero():
    months = list(BASE)
    rows = [{"period": p, "time_interval": "monthly", "TOTAL": 100,
             "BEV": "" if p == "2026-10" else 10} for p in months]
    m = {"country": "X", "weight": 100, "rows": rows}
    assert rc.window_ending(rows, "2026-10") is None
    assert rc.window_ending(rows, "2026-09") is not None
    t, contrib, cov = rc.pick_common_end([m])
    assert t == "2026-09"


def test_four_requested_regions_load():
    for slug, minimum in (("world", 50), ("eu", 80),
                          ("northern_europe", 80), ("south_america", 80)):
        info = rc.load(slug)
        assert info["share"] is not None and info["t"]
        assert info["coverage"] >= minimum
        assert info["rows"] and info["rows"][-1]["period"] == info["t"]
        # Who-gained BEV matches the headline when the split keeps
        # the same members; a documented subset may differ by less
        # than half a tenth of a point (the printed decimal is unchanged).
        if info["shift"]:
            bev = next(r for r in info["shift"]["rows"] if r["key"] == "BEV")
            if info["mix_members"] == info["contributors"]:
                assert abs(bev["after"] - info["share"]) < 1e-9
                assert abs(bev["delta"] - info["delta"]) < 1e-9
            else:
                assert info["mix_note"]
                assert abs(round(bev["after"], 1) - round(info["share"], 1)) < 1e-9
        assert "in a year" not in info["fm"]["coverage_note"]
        assert "in a year" not in info["fm"]["scope_note"]



def test_carriers_rank_by_weight_times_share():
    # A is heavy but low share; B is light but high share. B should lead.
    months = BASE[-12:]  # 12 months ending 2026-10
    A = member("A", 100, months, share=10)  # contrib 1000
    B = member("B", 20, months, share=80)   # contrib 1600
    C = member("C", 5, months, share=20)    # contrib 100
    t, contrib, _ = rc.pick_common_end([A, B, C])
    rows, total = rc.carrier_rows(contrib, t)
    assert [r["country"] for r in rows] == ["B", "A", "C"]
    assert abs(rows[0]["of_group"] - 100 * 1600 / 2700) < 1e-6
    assert abs(rows[0]["bev_share"] - 80) < 1e-6


def test_northern_europe_has_no_rest_row():
    info = rc.load("northern_europe")
    assert len(info["carriers"]) == 4
    assert info["carriers"][0]["country"] == "Norway"
    html, _ = rc.build_carriers_html(info)
    assert "other members" not in html
    assert "Norway" in html and "Finland" in html
    assert "no confidence band available" in rc.region_legend()


def test_reference_points_include_the_named_set():
    pts = {p["name"]: p for p in rc.reference_points()}
    for name in ("Norway", "China", "EU", "World", "Germany", "USA"):
        assert name in pts, name
        assert pts[name]["share"] > 0
    # Norway should be the high reference, USA the low one of this set.
    assert pts["Norway"]["share"] > 80
    assert pts["USA"]["share"] < 15
    assert pts["World"]["share"] < pts["EU"]["share"] < pts["China"]["share"]


def test_eu_and_northern_europe_split_phev_not_hev():
    for slug in ("eu", "northern_europe"):
        info = rc.load(slug)
        assert info["mix_members"] == info["contributors"]
        assert "PHEV" in info["mix_bands"] and "HEV" not in info["mix_bands"]
        keys = [r["key"] for r in info["shift"]["rows"]]
        assert keys == ["BEV", "PHEV", "REST"]
        # Headline BEV and the mix stack agree, and empty HEV was not a 0.
        bev = next(r for r in info["shift"]["rows"] if r["key"] == "BEV")
        phev = next(r for r in info["shift"]["rows"] if r["key"] == "PHEV")
        rest = next(r for r in info["shift"]["rows"] if r["key"] == "REST")
        assert abs(bev["after"] + phev["after"] + rest["after"] - 100) < 1e-9
        assert abs(bev["after"] - info["share"]) < 1e-9
        assert info["fm"]["region_mix_points"][-1]["PHEV"] is not None
        assert info["fm"]["region_mix_points"][-1]["HEV"] is None
        assert "no HEV series" in (info["mix_note"] or "")
        assert "trailing 12-month share" in rc.region_legend()


def test_world_phev_subset_keeps_printed_bev():
    info = rc.load("world")
    assert "PHEV" in info["mix_bands"] and "HEV" not in info["mix_bands"]
    assert set(info["mix_members"]) < set(info["contributors"])
    for name in ("Colombia", "Malaysia", "Nepal", "Türkiye", "Vietnam"):
        assert name not in info["mix_members"]
        assert name in (info.get("mix_note_long") or info["fm"]["scope_note"])
    bev = next(r for r in info["shift"]["rows"] if r["key"] == "BEV")
    assert abs(round(bev["after"], 1) - round(info["share"], 1)) < 1e-9
    assert "51 of 56" in info["mix_note"]


def test_south_america_splits_hev_not_phev():
    info = rc.load("south_america")
    # Every member has HEV, so hybrid is its own band. Colombia has no
    # PHEV series; dropping it would move BEV, so plug-ins stay in the rest.
    assert info["mix_members"] == info["contributors"]
    assert info["mix_bands"] == ["HEV"]
    keys = [r["key"] for r in info["shift"]["rows"]]
    assert keys == ["BEV", "HEV", "REST"]
    rest = next(r for r in info["shift"]["rows"] if r["key"] == "REST")
    assert rest["label"] == "Everything else"
    assert info["fm"]["region_mix_points"][-1]["HEV"] is not None
    assert info["fm"]["region_mix_points"][-1]["PHEV"] is None
    assert "Colombia" in (info["mix_note"] or "")
    assert "6.9 %" in info["mix_note"] and "6.3 %" in info["mix_note"]


def test_empty_hev_is_unknown_in_window_powertrains():
    months = list(BASE)
    rows = [{"period": p, "time_interval": "monthly", "TOTAL": 100,
             "BEV": 10, "PHEV": 5, "HEV": ""} for p in months]
    win = rc.window_powertrains(rows, "2026-10")
    assert win is not None and abs(win["share"] - 10) < 1e-9
    assert abs(win["phev"] - 5) < 1e-9
    assert win["hev"] is None  # empty is not a 0



def _acea_file(d, rows):
    import csv
    ref = Path(d) / "acea_eu_shares.csv"
    with ref.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["period_from", "period_to", "scope", "BEV_share", "PHEV_share",
                    "HEV_share", "hev_definition", "release", "source_url"])
        for r in rows:
            w.writerow(r)
    return ref


def test_acea_latest_row_and_label():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        ref = _acea_file(d, [
            ("2026-01", "2026-09", "EU", "22.7", "10.1", "36.3", "full and mild hybrids", "", "u9"),
            ("2026-01", "2026-08", "EU", "22.0", "9.9", "36.0", "full and mild hybrids", "", "u8"),
            ("2026-01", "2026-10", "EFTA", "50", "10", "20", "", "", ""),  # other scope
        ])
        a = rc.acea_eu_shares(ref)
        assert (a["to"], a["hev"], a["bev"], a["phev"]) == ("2026-09", 36.3, 22.7, 10.1)
        assert a["period"] == "Jan–Sep 2026", a["period"]
        ok = rc.acea_for_brief("2026-10", ref)
        assert ok["lag"] == 1 and not ok["stale"]
        line = rc.acea_line(ok)
        assert "ACEA, EU · Jan–Sep 2026" in line and "Hybrids (HEV): 36.3" in line
        assert "BEV 22.7" in line and "not in the split above" in line and "ACEA's own figure" in line
        assert "acea-stale" not in line
        assert 'class="sc-acea"' in rc.acea_line(ok, social=True)
        assert rc.acea_line(None) == ""


def test_acea_staleness_guard():
    import contextlib, io, tempfile
    with tempfile.TemporaryDirectory() as d:
        ref = _acea_file(d, [("2026-01", "2026-09", "EU", "22.7", "10.1", "36.3", "", "", "")])
        assert rc.acea_lag_months(rc.acea_eu_shares(ref), "2026-11") == rc.ACEA_MAX_LAG
        assert not rc.acea_for_brief("2026-11", ref)["stale"]
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            old = rc.acea_for_brief("2026-12", ref)
        assert old["stale"] and old["lag"] == 3 and "WARNING" in err.getvalue()
        # On the page, not only in the log.
        assert "Latest ACEA figure, 3 months before the data above" in rc.acea_line(old)
        with contextlib.redirect_stderr(io.StringIO()):
            assert rc.acea_for_brief("2026-10", Path(d) / "missing.csv") is None


def test_repo_acea_figure_is_current():
    # The CI guard: the committed ACEA EU row may lag the EU brief's data by
    # at most ACEA_MAX_LAG months. Fails when the monthly fetch stopped.
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()) as out:
        rc_ = rc.check_acea()
    assert rc_ == 0, out.getvalue()


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} tests passed")
