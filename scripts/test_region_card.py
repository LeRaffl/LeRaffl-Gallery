#!/usr/bin/env python3
"""Common-window rule and a smoke load of the region flyers."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import region_card as rc
import model_card as mc
import flyer  # noqa: E402


def member(name, w, months, share=10):
    rows = [{"period": p, "time_interval": "monthly", "TOTAL": 100, "BEV": share}
            for p in months]
    return {"country": name, "weight": w, "rows": rows}


BASE = ([f"2024-{m:02d}" for m in range(11, 13)]
        + [f"2025-{m:02d}" for m in range(1, 13)]
        + [f"2026-{m:02d}" for m in range(1, 11)])


def test_pick_latest_month_that_covers_80_percent():
    # A+B are 90% of the weight and run through October; C stops in August.
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
    # 50% year for the compare box plot: the same fitted-curve rule as each brief.
    assert pts["Norway"]["year50"] < pts["Germany"]["year50"] < pts["USA"]["year50"]
    assert pts["EU"]["year50"] == flyer.year_at_50(rc.load("eu")["fm"]["curve_state"])


def test_region_brief_compares_as_box_plots():
    import build_source_pages as bsp
    entries, _ = bsp.collect_entries()
    params = bsp.load_params()
    brief, social, _ = rc.build("eu", "t.css", peers=bsp.flyer_peers(entries, params),
                                peer_years=bsp.flyer_peer_years(entries, params),
                                peer_years_80=bsp.flyer_peer_years(entries, params, level=0.8))
    assert "<h2>How it compares" in brief and brief.count('class="fl-bx"') == 3
    assert "would be" in brief and "Fitted curve reaches 50%" in brief
    assert "Fitted curve reaches 80%" in brief
    assert "fl-two-wide" in brief and brief.find("Who carries it") < brief.find("Where the curve points")
    assert social.count('class="sc-bx"') == 1 and "Fitted curve" not in social
    assert brief.count("a model, not a forecast") == 0
    assert "not an actual forecast" in brief
    assert "The curve is a model, not a forecast." not in brief
    assert "<b>Abbreviations:</b>" in brief


def test_eu_and_northern_europe_split_phev_not_hev():
    for slug in ("eu", "northern_europe"):
        info = rc.load(slug)
        assert info["mix_members"] == info["contributors"]
        assert "PHEV" in info["mix_bands"] and "HEV" not in info["mix_bands"]
        keys = [r["key"] for r in info["shift"]["rows"]]
        # National split has no HEV; the EU brief adds ACEA's (its own source).
        assert keys == (["BEV", "PHEV", "HEV", "REST"] if slug == "eu" else ["BEV", "PHEV", "REST"])
        assert all(r.get("source") == "ACEA" for r in info["shift"]["rows"] if r["key"] == "HEV")
        # Headline BEV and the mix stack agree, and empty HEV was not a 0.
        bev = next(r for r in info["shift"]["rows"] if r["key"] == "BEV")
        phev = next(r for r in info["shift"]["rows"] if r["key"] == "PHEV")
        rest = next(r for r in info["shift"]["rows"] if r["key"] == "REST")
        assert abs(sum(r["after"] for r in info["shift"]["rows"]) - 100) < 1e-9
        # The mix stack (three-way) still matches: rest + ACEA HEV = its rest.
        mix_rest = 100 - bev["after"] - phev["after"]
        hev = sum(r["after"] for r in info["shift"]["rows"] if r["key"] == "HEV")
        assert abs(rest["after"] + hev - mix_rest) < 1e-9
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
    assert "6.9%" in info["mix_note"] and "6.3%" in info["mix_note"]


def test_empty_hev_is_unknown_in_window_powertrains():
    months = list(BASE)
    rows = [{"period": p, "time_interval": "monthly", "TOTAL": 100,
             "BEV": 10, "PHEV": 5, "HEV": ""} for p in months]
    win = rc.window_powertrains(rows, "2026-10")
    assert win is not None and abs(win["share"] - 10) < 1e-9
    assert abs(win["phev"] - 5) < 1e-9
    assert win["hev"] is None  # empty is not a 0



def _acea_monthly(d, months, hev=30, total=100, skip=()):
    import csv
    ref = Path(d) / "acea_eu_monthly.csv"
    with ref.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["period", "scope", "BEV_units", "PHEV_units", "HEV_units", "TOTAL_units"])
        for p in months:
            if p in skip:
                continue
            h = hev(p) if callable(hev) else hev
            w.writerow([p, "EU", 20, 10, h, total])
    return ref


M24 = [f"2024-{m:02d}" for m in range(10, 13)] + [f"2025-{m:02d}" for m in range(1, 13)] \
    + [f"2026-{m:02d}" for m in range(1, 10)]


def test_acea_ttm_window_and_delta():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        # 30% before Oct 2025, 36% from then on: +6 pts on the 12 months before.
        ref = _acea_monthly(d, M24, hev=lambda p: 36 if p >= "2025-10" else 30)
        a = rc.acea_eu_ttm(ref)
        assert a["end"] == "2026-09" and a["span"] == (("2024-10", "2025-09"), ("2025-10", "2026-09"))
        assert abs(a["hev"] - 36) < 1e-9 and abs(a["hev_delta"] - 6) < 1e-9
        assert a["window"] == "Oct 2025–Sep 2026", a["window"]
        ok = rc.acea_for_brief("2026-10", ref)
        assert ok["lag"] == 1 and not ok["stale"]
        shift = {"rows": [
            {"key": "BEV", "label": "Battery electric", "before": 16, "after": 24, "delta": 8},
            {"key": "PHEV", "label": "Plug-in hybrid", "before": 9, "after": 10, "delta": 1},
            {"key": "REST", "label": "Combustion + hybrids", "before": 75, "after": 66, "delta": -9}]}
        four = rc.with_acea_hev(shift, ok)
        assert [r["key"] for r in four["rows"]] == ["BEV", "PHEV", "HEV", "REST"]
        hev, rest = four["rows"][2], four["rows"][3]
        assert hev["source"] == "ACEA" and abs(hev["after"] - 36) < 1e-9 and abs(hev["before"] - 30) < 1e-9
        assert rest["label"] == "Petrol, diesel & other" and "hybrid" not in rest["label"].lower()
        assert abs(rest["after"] - 30) < 1e-9 and abs(rest["before"] - 45) < 1e-9
        assert abs(sum(r["delta"] for r in four["rows"])) < 1e-9
        assert rc.acea_bars_note(ok) == "HEV from ACEA, BEV and PHEV from national data."
        # A split that already has HEV, or no ACEA figure: left alone.
        assert rc.with_acea_hev(four, ok) is four and rc.with_acea_hev(shift, None) is shift
        line = rc.acea_line(ok, social=True)
        assert "ACEA, EU · Oct 2025–Sep 2026" in line and "Hybrids (HEV): 36.0" in line
        assert rc.acea_line(None) == "" and rc.acea_bars_note(None) == ""


def test_acea_full_window_rule():
    import contextlib, io, tempfile
    with tempfile.TemporaryDirectory() as d:
        # A hole in the prior 12 months: no figure at all, not a partial window.
        ref = _acea_monthly(d, M24, skip={"2025-02"})
        assert rc.acea_eu_ttm(ref) is None
        with contextlib.redirect_stderr(io.StringIO()):
            assert rc.acea_for_brief("2026-10", ref) is None
        # 23 months only.
        ref = _acea_monthly(d, M24[1:])
        assert rc.acea_eu_ttm(ref) is None


def test_acea_staleness_guard():
    import contextlib, io, tempfile
    with tempfile.TemporaryDirectory() as d:
        ref = _acea_monthly(d, M24)
        assert rc.acea_lag_months(rc.acea_eu_ttm(ref), "2026-11") == rc.ACEA_MAX_LAG
        assert not rc.acea_for_brief("2026-11", ref)["stale"]
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            old = rc.acea_for_brief("2026-12", ref)
        assert old["stale"] and old["lag"] == 3 and "WARNING" in err.getvalue()
        # On the page, not only in the log.
        assert "Latest ACEA month is 3 months before the data above" in rc.acea_bars_note(old)


def test_acea_ytd_file_still_reads():
    a = rc.acea_eu_shares()
    assert a and a["period"].startswith("Jan–"), a


def test_every_region_split_adds_up():
    # One split, one denominator: ±0 pts and 100%. On the EU brief that
    # includes ACEA's HEV row (the rest is 100 − BEV − PHEV − HEV).
    import contextlib, io, re
    import flyer
    seen_acea = False
    for slug in rc.REGION_LABELS:
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                info = rc.load(slug)
            except RuntimeError:
                continue
        shift = info["shift"]
        if not shift:
            continue
        rows = flyer.split_rows(shift)
        assert abs(sum(r["delta"] for r in rows)) < 0.05, (slug, rows)
        assert abs(sum(r["after"] for r in rows) - 100) < 0.05, (slug, rows)
        assert abs(sum(r["before"] for r in rows) - 100) < 0.05, (slug, rows)
        if any(r.get("source") == "ACEA" for r in rows):
            seen_acea = True
            assert slug == "eu" and [r["key"] for r in rows] == ["BEV", "PHEV", "HEV", "REST"]
            assert "hybrid" not in rows[-1]["label"].lower()
            assert info["fm"]["bars_note"].startswith("HEV from ACEA, BEV and PHEV from national data.")
        # BEV in the split is the headline BEV whenever the split runs on
        # the headline member set.
        if info["mix_members"] == info["contributors"]:
            assert abs(rows[0]["after"] - info["share"]) < 1e-6, slug
        html = flyer.build_bars(shift)
        pp = [0.0 if t == "±0" else float(t.replace("−", "-"))
              for t in re.findall(r'class="fb-pp">([^<]*)<', html)]
        now = [float(t.replace("%", "")) for t in re.findall(r'class="fb-now">([^<]*)<', html)]
        tol = 0.05 * len(pp) + 1e-9
        assert abs(sum(pp)) <= tol and abs(sum(now) - 100) <= tol, (slug, pp, now)
    assert seen_acea, "EU brief lost its ACEA HEV row"


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
