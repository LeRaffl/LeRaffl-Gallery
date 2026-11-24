#!/usr/bin/env python3
"""Common-window rule and a smoke load of the region flyers."""
import datetime as dt
import math
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



def _seasonal_members():
    # A's volume triples every December; B is flat. The weighted 12-month
    # share then differs from the mean of 12 weighted monthly shares.
    months = [f"2025-{m:02d}" for m in range(1, 13)] + [f"2026-{m:02d}" for m in range(1, 11)]
    def rows(share_of, total_of):
        return [{"period": p, "time_interval": "monthly",
                 "TOTAL": total_of(p), "BEV": share_of(p) * total_of(p) / 100}
                for p in months]
    A = {"country": "A", "weight": 3, "rows": rows(
        lambda p: 40 if p.endswith("-12") else 10,
        lambda p: 3000 if p.endswith("-12") else 1000)}
    B = {"country": "B", "weight": 1, "rows": rows(lambda p: 20, lambda p: 500)}
    return [A, B]


def test_ttm_line_ends_on_the_headline():
    contrib = _seasonal_members()
    rows = rc.synthetic_rows(contrib, "2026-10")
    line = rc.weighted_ttm_series(contrib, rows)
    assert line[-1][0] == "2026-10"
    assert abs(line[-1][1] - rc.weighted_share(contrib, "2026-10")) < 1e-9
    # The old drawn value (mean of 12 monthly weighted shares) is off.
    old = sum(mc._bev_share(r) for r in rows[-12:]) / 12
    assert abs(old - line[-1][1]) > 0.5
    # Every point is the headline rule at its own month-end.
    for period, share in line:
        assert abs(share - rc.weighted_share(contrib, period)) < 1e-9
    # Only month-ends with a full 12-month window for every contributor.
    assert line[0][0] == "2025-12" and len(line) == 11


def test_ttm_line_is_drawn_from_the_weighted_series():
    contrib = _seasonal_members()
    rows = rc.synthetic_rows(contrib, "2026-10")
    line = rc.weighted_ttm_series(contrib, rows)
    svg = rc.build_region_curve_svg(rows, [], [], 600, 300, ttm=line)
    assert svg.count('class="cv-ttm"') == 1
    # Without a weighted series no 12-month line is drawn at all.
    assert 'cv-ttm' not in rc.build_region_curve_svg(rows, [], [], 600, 300)


def test_ttm_line_breaks_at_a_gap():
    pts = [("2025-12", 20.0), ("2026-01", 21.0), ("2026-03", 22.0), ("2026-04", 23.0)]
    rows = [{"period": f"2025-{m:02d}", "time_interval": "monthly", "TOTAL": 100, "BEV": 20}
            for m in range(1, 13)]
    svg = rc.build_region_curve_svg(rows, [], [], 600, 300, ttm=pts)
    assert svg.count('class="cv-ttm"') == 2


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
    # One row per contributing member, never a lumped rest row. The count moves
    # with the data (Iceland joins once it has a full 12-month window).
    assert len(info["carriers"]) == len(info["contributors"]) >= 4
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


def test_eu_and_northern_europe_split_phev_and_hev():
    """Northern Europe: every member has a national HEV split, so the mix and
    who-gained use it. The EU's series is ACEA's own EU27 total (from Oct
    2024; members' sum before), so its split is ACEA's, hybrids included."""
    for slug in ("eu", "northern_europe"):
        info = rc.load(slug)
        assert info["mix_members"] == info["contributors"]
        assert "Denmark" in info["mix_members"]
        assert "PHEV" in info["mix_bands"]
        keys = [r["key"] for r in info["shift"]["rows"]]
        bev = next(r for r in info["shift"]["rows"] if r["key"] == "BEV")
        assert abs(sum(r["after"] for r in info["shift"]["rows"]) - 100) < 1e-9
        assert abs(bev["after"] - info["share"]) < 1e-9
        last = info["fm"]["region_mix_points"][-1]
        assert last["PHEV"] is not None
        assert "trailing 12-month share" in rc.region_legend()
        if slug == "northern_europe":
            assert "HEV" in info["mix_bands"]
            assert keys == ["BEV", "PHEV", "HEV", "REST"]
            # National split: no row borrows ACEA's figure.
            assert all(r.get("source") is None for r in info["shift"]["rows"])
            assert last["HEV"] is not None
            assert abs(sum(last[k] for k in ("BEV", "PHEV", "HEV", "REST")) - 100) < 1e-9
            assert "no HEV series" not in (info["mix_note"] or "")
        else:
            # EU: ACEA's own EU27 total is the series (rc.acea_series), so the
            # whole split is ACEA's: hybrids (full + mild) as their own row,
            # petrol and diesel named, nothing borrowed from a second source.
            assert "HEV" in info["mix_bands"]
            assert keys[:3] == ["BEV", "PHEV", "HEV"] and keys[-1] == "REST"
            assert all(r.get("source") is None for r in info["shift"]["rows"])
            assert info["rows"][-1]["source"] == "ACEA"
            assert last["HEV"] is not None
            assert abs(sum(last[k] for k in ("BEV", "PHEV", "HEV", "REST")) - 100) < 1e-9
            assert not info["fm"]["bars_note"] and not info["fm"]["acea_social"]


def _pt_member(name, w, bev, phev=None, hev=None):
    rows = []
    for p in BASE:
        r = {"period": p, "time_interval": "monthly", "TOTAL": 100, "BEV": bev}
        if phev is not None:
            r["PHEV"] = phev
        if hev is not None:
            r["HEV"] = hev
        rows.append(r)
    return {"country": name, "weight": w, "rows": rows}


def test_phev_subset_is_taken_when_it_keeps_printed_bev():
    # B has no PHEV series. Leaving it out keeps 90% of the weight and the
    # headline BEV, so the split runs on A alone, with A's HEV too.
    A = _pt_member("A", 90, 10, phev=5, hev=20)
    B = _pt_member("B", 10, 10)
    ch = rc.choose_mix_split([A, B], "2026-10", None)
    assert [m["country"] for m in ch["members"]] == ["A"]
    assert ch["bands"] == ["PHEV", "HEV"]
    assert "1 of 2" in ch["note"] and "B" in ch["note_long"]


def test_phev_subset_is_refused_when_it_moves_printed_bev():
    # Same set, but B's BEV differs: the subset would print 10.0% against a
    # 12.0% headline, so the headline set stays and PHEV is not split out.
    A = _pt_member("A", 90, 10, phev=5, hev=20)
    B = _pt_member("B", 10, 30)
    ch = rc.choose_mix_split([A, B], "2026-10", None)
    assert [m["country"] for m in ch["members"]] == ["A", "B"]
    assert ch["bands"] == []
    assert "would move BEV from 12.0% to 10.0%" in ch["note"]


def test_world_phev_subset_keeps_printed_bev():
    # Live data: which branch World takes depends on the month the headline
    # lands on, so check the rule, not one month's outcome.
    info = rc.load("world")
    members, contrib = set(info["mix_members"]), set(info["contributors"])
    assert members <= contrib
    if "PHEV" in info["mix_bands"]:
        bev = next(r for r in info["shift"]["rows"] if r["key"] == "BEV")
        assert abs(round(bev["after"], 1) - round(info["share"], 1)) < 1e-9
        if members < contrib:
            assert f"{len(members)} of {len(contrib)}" in info["mix_note"]
            for name in contrib - members:
                assert name in (info.get("mix_note_long")
                                or info["fm"]["scope_note"])
    else:
        assert members == contrib
        assert "Plug-in hybrid is not split out" in info["mix_note"]


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
    # The note quotes the printed headline and what leaving Colombia out would
    # print instead; the figures move with the data, so tie them to it.
    import re as _re
    assert f"from {info['share']:.1f}%" in info["mix_note"]
    moved = _re.search(r"to (\d+\.\d)%", info["mix_note"])
    assert moved and moved.group(1) != f"{info['share']:.1f}"


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
    # Only the EU may borrow ACEA's HEV row (checked in the loop), and only
    # while a member has no HEV series: Latvia since the CSDD update of
    # 15 Oct 2026. Once every member has one, this flips back to "never";
    # the fallback itself is pinned by test_acea_ttm_window_and_delta.
    eu = rc.load("eu")
    assert seen_acea == ("HEV" not in eu["mix_bands"]), "ACEA fallback and mix bands disagree"


def test_repo_acea_figure_is_current():
    # The CI guard: the committed ACEA EU row may lag the EU brief's data by
    # at most ACEA_MAX_LAG months. Fails when the monthly fetch stopped.
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()) as out:
        rc_ = rc.check_acea()
    assert rc_ == 0, out.getvalue()


# --- Group confidence band (#454) -------------------------------------------

TODAY = dt.date(2026, 11, 21)


def _param(country, data_per="2026-09", v2=2.0, swing="1.5", ttm=0.2):
    return {"country": country, "variant": "Whole", "v1": "-0.001",
            "v2": str(v2), "t0": "2015", "data_per": data_per,
            "ttm_bev_share": str(ttm), "refit_swing": swing}


def _band(data_per="2026-09", v2=2.0, usable=True, reasons=None,
          t=(2020.0, 2021.0, 2022.0), fit=(0.10, 0.20, 0.30),
          lo=(0.08, 0.17, 0.26), hi=(0.12, 0.23, 0.34)):
    return {"schema": 2, "data_per": data_per,
            "fit_params": {"v1": -0.001, "v2": v2, "t0": 2015},
            "quality": {"usable": usable, "reasons": reasons or []},
            "t": list(t), "fit": list(fit), "ci": [list(lo), list(hi)]}


def _const_band(hw_lo, hw_hi, data_per="2026-09", v2=2.0):
    # Constant half-widths on the grid: interpolation is the identity.
    return _band(data_per=data_per, v2=v2, fit=(0.5, 0.5, 0.5),
                 lo=(0.5 - hw_lo,) * 3, hi=(0.5 + hw_hi,) * 3)


def _loader(bands):
    return lambda country: bands.get(country)


def test_group_band_combines_in_quadrature_not_average():
    rows = [_param("A"), _param("B")]
    weights = {"A|whole": 75.0, "B|whole": 25.0}
    bands = {"A": _const_band(0.02, 0.03), "B": _const_band(0.02, 0.03)}
    out = rc.group_band(rows, weights, [2021.0], [20.0],
                        band_loader=_loader(bands), today=TODAY)
    assert out["ok"] and out["coverage"] == 1.0
    # sqrt((0.75*0.02)^2 + (0.25*0.02)^2) = 0.02*sqrt(0.625)
    dlo = 100 * 0.02 * math.sqrt(0.625)
    dhi = 100 * 0.03 * math.sqrt(0.625)
    assert abs(out["lo"][0] - (20.0 - dlo)) < 1e-9
    assert abs(out["hi"][0] - (20.0 + dhi)) < 1e-9
    # A weighted average of half-widths would give 18.0 / 23.0 — wrong class.
    assert abs(out["lo"][0] - 18.0) > 0.05
    assert abs(out["hi"][0] - 23.0) > 0.05


def test_group_band_asymmetric_half_widths_stay_separate():
    rows = [_param("A"), _param("B")]
    weights = {"A|whole": 50.0, "B|whole": 50.0}
    bands = {"A": _const_band(0.01, 0.05), "B": _const_band(0.03, 0.01)}
    out = rc.group_band(rows, weights, [2021.0], [40.0],
                        band_loader=_loader(bands), today=TODAY)
    dlo = 100 * math.sqrt((0.5 * 0.01) ** 2 + (0.5 * 0.03) ** 2)
    dhi = 100 * math.sqrt((0.5 * 0.05) ** 2 + (0.5 * 0.01) ** 2)
    assert abs(out["lo"][0] - (40.0 - dlo)) < 1e-9
    assert abs(out["hi"][0] - (40.0 + dhi)) < 1e-9


def test_group_band_single_member_is_the_file_band():
    out = rc.group_band([_param("A")], {"A|whole": 10.0}, [2021.0], [20.0],
                        band_loader=_loader({"A": _const_band(0.02, 0.03)}),
                        today=TODAY)
    assert out["ok"]
    assert abs(out["lo"][0] - 18.0) < 1e-9
    assert abs(out["hi"][0] - 23.0) < 1e-9


def test_group_band_coverage_floor_and_dilution():
    rows = [_param("A"), _param("B")]
    bands = {"A": _const_band(0.02, 0.02)}  # B has no band file
    ok = rc.group_band(rows, {"A|whole": 80.0, "B|whole": 20.0},
                       [2021.0], [20.0], band_loader=_loader(bands), today=TODAY)
    assert ok["ok"] and abs(ok["coverage"] - 0.8) < 1e-9
    # B keeps its weight in the denominator: A's spread is diluted by 0.8.
    assert abs(ok["lo"][0] - (20.0 - 100 * 0.8 * 0.02)) < 1e-9
    assert ok["excluded"] == [{"label": "B", "why": "no band yet"}]
    bad = rc.group_band(rows, {"A|whole": 79.0, "B|whole": 21.0},
                        [2021.0], [20.0], band_loader=_loader(bands), today=TODAY)
    assert not bad["ok"] and abs(bad["coverage"] - 0.79) < 1e-9


def test_group_band_stale_data_per_is_excluded():
    out = rc.group_band([_param("A", data_per="2026-08")], {"A|whole": 10.0},
                        [2021.0], [20.0],
                        band_loader=_loader({"A": _band(data_per="2026-09")}),
                        today=TODAY)
    assert not out["ok"]
    assert out["excluded"] == [{"label": "A", "why": "band out of date"}]


def test_group_band_v2_drift_two_percent_gate():
    rows = [_param("A", v2=2.0)]
    inside = rc.group_band(rows, {"A|whole": 10.0}, [2021.0], [20.0],
                           band_loader=_loader({"A": _band(v2=2.0 * 1.019)}),
                           today=TODAY)
    assert inside["ok"]
    outside = rc.group_band(rows, {"A|whole": 10.0}, [2021.0], [20.0],
                            band_loader=_loader({"A": _band(v2=2.0 * 1.021)}),
                            today=TODAY)
    assert not outside["ok"]
    assert outside["excluded"][0]["why"] == "band out of date"


def test_group_band_unusable_quality_is_excluded_with_reason():
    for reasons, why in ((["poor fit"], "poor fit"),
                         (["too few rows"], "too few rows")):
        out = rc.group_band([_param("A")], {"A|whole": 10.0}, [2021.0], [20.0],
                            band_loader=_loader({"A": _band(usable=False, reasons=reasons)}),
                            today=TODAY)
        assert not out["ok"]
        assert out["excluded"] == [{"label": "A", "why": why}]


def test_group_band_reliability_gate_and_unknown_swing():
    # Measured unstable fit: excluded as unreliable.
    out = rc.group_band([_param("A", swing="30")], {"A|whole": 10.0},
                        [2021.0], [20.0],
                        band_loader=_loader({"A": _band()}), today=TODAY)
    assert out["excluded"] == [{"label": "A", "why": "unreliable fit"}]
    # Empty swing (the backtest archive writes NA): same gate, precise name.
    out = rc.group_band([_param("A", swing="")], {"A|whole": 10.0},
                        [2021.0], [20.0],
                        band_loader=_loader({"A": _band()}), today=TODAY)
    assert out["excluded"] == [{"label": "A", "why": "no refit swing recorded"}]
    # A no-transition row is not gated by reliability (mirror of
    # rowIsUnreliableFit = !rowHasNoTransition && excluded).
    out = rc.group_band([_param("A", swing="", ttm=0.001)], {"A|whole": 10.0},
                        [2021.0], [20.0],
                        band_loader=_loader({"A": _band()}), today=TODAY)
    assert out["ok"]


def test_group_band_missing_or_old_schema_file():
    out = rc.group_band([_param("A")], {"A|whole": 10.0}, [2021.0], [20.0],
                        band_loader=_loader({}), today=TODAY)
    assert out["excluded"] == [{"label": "A", "why": "no band yet"}]
    old = _band()
    old["schema"] = 1
    out = rc.group_band([_param("A")], {"A|whole": 10.0}, [2021.0], [20.0],
                        band_loader=_loader({"A": old}), today=TODAY)
    assert out["excluded"] == [{"label": "A", "why": "no band yet"}]


def test_group_band_zero_weight_rows_are_skipped():
    out = rc.group_band([_param("A")], {"A|whole": 0.0}, [2021.0], [20.0],
                        band_loader=_loader({"A": _band()}), today=TODAY)
    assert not out["ok"] and out["members"] == 0 and out["coverage"] == 0.0


def test_band_half_widths_interpolation_edges():
    b = _band()
    assert rc._band_half_widths(b, 2019.0) == (0.0, 0.0)  # before first year
    hw = rc._band_half_widths(b, 2020.5)
    assert hw and abs(hw[0] - 0.025) < 1e-12 and abs(hw[1] - 0.025) < 1e-12
    hw = rc._band_half_widths(b, 2025.0)  # past the grid: last value holds
    assert hw and abs(hw[0] - 0.04) < 1e-12 and abs(hw[1] - 0.04) < 1e-12
    b["ci"][1][1] = None  # a null node means no value around it
    assert rc._band_half_widths(b, 2020.5) is None
    malformed = _band()
    malformed["ci"] = [[0.08, 0.17, 0.26]]  # upper edge missing
    assert rc._band_half_widths(malformed, 2021.0) is None


def test_group_band_all_null_grid_claims_nothing():
    b = _band(fit=(0.5, 0.5, 0.5), lo=(None, None, None), hi=(None, None, None))
    out = rc.group_band([_param("A")], {"A|whole": 10.0},
                        [2020.0, 2021.0, 2022.0], [10.0] * 3,
                        band_loader=_loader({"A": b}), today=TODAY)
    assert not out["ok"] and out.get("empty")
    note = rc.band_note(out)
    assert "No confidence band available" in note and "no values" in note


def test_group_band_null_node_gaps_the_year():
    # A null node invalidates both intervals touching it (mirror of
    # bandHalfWidths: interpolation reads both neighbours).
    b = _band(t=(2020.0, 2021.0, 2022.0, 2023.0, 2024.0),
              fit=(0.5,) * 5, lo=(0.48,) * 5, hi=(0.52,) * 5)
    b["ci"][0][2] = None
    years = [2020.0, 2021.0, 2022.0, 2023.0, 2024.0]
    out = rc.group_band([_param("A")], {"A|whole": 10.0},
                        years, [10.0] * 5,
                        band_loader=_loader({"A": b}), today=TODAY)
    assert out["ok"]
    assert out["lo"][0] is not None
    # The null at 2022 kills the intervals [2021,2022] and [2022,2023];
    # 2023.0 already reads the clean interval [2023,2024].
    assert out["lo"][1] is None and out["lo"][2] is None
    assert out["lo"][3] is not None and out["lo"][4] is not None


def test_group_band_nan_curve_year_has_no_band():
    out = rc.group_band([_param("A")], {"A|whole": 10.0},
                        [2020.0, 2021.0], [10.0, float("nan")],
                        band_loader=_loader({"A": _const_band(0.02, 0.02)}),
                        today=TODAY)
    assert out["ok"] and out["lo"][1] is None and out["hi"][1] is None


def test_band_note_states_the_concrete_reason():
    ok = {"ok": True, "excluded": [], "coverage": 1.0, "members": 2}
    assert "95% confidence band" in rc.band_note(ok)
    none = rc.band_note(None)
    assert "not archived" in none
    stale = {"ok": False, "coverage": 0.09, "members": 27,
             "excluded": [{"label": "A", "why": "no refit swing recorded"}] * 26
                         + [{"label": "B", "why": "band out of date"}]}
    note = rc.band_note(stale)
    assert "No confidence band available" in note
    assert "9%" in note and "80% needed" in note
    assert "refit swing" in note
    few = {"ok": False, "coverage": 0.5, "members": 2,
           "excluded": [{"label": "B", "why": "no band yet"}]}
    assert "no confidence band file yet" in rc.band_note(few)


def test_region_curve_svg_draws_band_only_when_ok():
    years = [2020.0 + 0.5 * i for i in range(21)]
    model = [10.0] * len(years)
    band = {"ok": True, "lo": [8.0] * len(years), "hi": [55.0] * len(years)}
    svg = rc.build_region_curve_svg([], years, model, 700, 300, band=band)
    assert 'class="cv-ci"' in svg
    assert ">60<" in svg  # y scale grew to hold the band's upper edge
    plain = rc.build_region_curve_svg([], years, model, 700, 300)
    assert 'class="cv-ci"' not in plain
    assert ">60<" not in plain
    off = rc.build_region_curve_svg([], years, model, 700, 300,
                                    band={"ok": False, "lo": [], "hi": []})
    assert 'class="cv-ci"' not in off


def test_region_legend_band_entry():
    assert "95% confidence band of the curve" in rc.region_legend(band_ok=True)
    assert "no confidence band available" not in rc.region_legend(band_ok=True)
    assert "no confidence band available" in rc.region_legend()
    assert "95% confidence band of the curve" not in rc.region_legend()


def test_region_band_is_gated_on_the_archived_fits():
    # Structural smoke test on the real repo: the band exists as a decision,
    # and it is gated on the frame's own archived fits (never newer than the
    # frame). Whether a band can be stated today depends on the data cadence,
    # so the test pins the contract, not the current outcome.
    import contextlib, io
    with contextlib.redirect_stderr(io.StringIO()):
        info = rc.load("eu")
    band = info["band"]
    assert band is not None, "EU backtest archives are missing"
    bt = rc._load_backtest("eu")
    assert bt is not None
    frame = rc._pick_frame(bt, info["t"])
    assert frame is not None
    fits = rc._frame_fits("eu", frame)
    assert fits is not None
    rows, _ = fits
    assert rows and all((r.get("data_per") or "") <= (frame.get("date") or "")
                        for r in rows)
    svg, legend = info["fm"]["region_curve"](700, 300, 42)
    if band["ok"]:
        assert 'class="cv-ci"' in svg
        assert "95% confidence band of the curve" in legend
    else:
        assert 'class="cv-ci"' not in svg
        note = rc.band_note(band)
        assert "No confidence band available" in note
        assert "80% needed" in note


def _ytd_fixture():
    # A's volume swings (Feb is 10x Jan/Mar); B is flat. The volume-weighted
    # member YTD and the unweighted mean of monthly weighted shares differ.
    A = {"country": "A", "weight": 1, "rows": [
        {"period": "2026-01", "time_interval": "monthly", "TOTAL": 100, "BEV": 10},
        {"period": "2026-02", "time_interval": "monthly", "TOTAL": 1000, "BEV": 100},
        {"period": "2026-03", "time_interval": "monthly", "TOTAL": 100, "BEV": 50},
    ]}
    B = {"country": "B", "weight": 1, "rows": [
        {"period": f"2026-0{m}", "time_interval": "monthly", "TOTAL": 100, "BEV": 20}
        for m in (1, 2, 3)
    ]}
    return [A, B]


def test_weighted_ytd_uses_member_volumes_not_month_mean():
    contrib = _ytd_fixture()
    ytd = rc.weighted_ytd(contrib, "2026-03")
    assert ytd is not None
    # A: 160/1200 = 13.333%, B: 20% -> weight-average 16.667%.
    assert abs(ytd["share"] - (100 * 160 / 1200 + 20) / 2) < 1e-9
    assert ytd["from"] == "2026-01" and ytd["to"] == "2026-03"
    assert ytd["year"] == 2026
    # The pre-fix path (constant-TOTAL synthetic rows + ytd_window) is the
    # unweighted mean of monthly weighted shares: (15 + 15 + 35)/3 = 21.667%.
    old = mc.ytd_window(rc.synthetic_rows(contrib, "2026-03"))
    assert old is not None
    assert abs(old["share"] - 65 / 3) < 1e-9
    assert abs(old["share"] - ytd["share"]) > 1.0  # the bug is material


def test_weighted_ytd_equals_month_mean_when_volumes_are_flat():
    # With constant member volumes the two rules coincide (sanity).
    contrib = [member("A", 3, [f"2026-0{m}" for m in range(1, 7)], share=12),
               member("B", 1, [f"2026-0{m}" for m in range(1, 7)], share=30)]
    ytd = rc.weighted_ytd(contrib, "2026-06")
    old = mc.ytd_window(rc.synthetic_rows(contrib, "2026-06"))
    assert ytd is not None and old is not None
    assert abs(ytd["share"] - old["share"]) < 1e-9
    assert abs(ytd["share"] - (3 * 12 + 1 * 30) / 4) < 1e-9


def test_weighted_ytd_same_set_rule_omits_on_a_missing_month():
    contrib = _ytd_fixture()
    # B lacks February -> no complete Jan..Mar window for every contributor.
    contrib[1]["rows"] = [r for r in contrib[1]["rows"] if r["period"] != "2026-02"]
    assert rc.weighted_ytd(contrib, "2026-03") is None


def test_weighted_ytd_needs_three_months():
    contrib = _ytd_fixture()
    assert rc.weighted_ytd(contrib, "2026-02") is None  # only Jan+Feb
    assert rc.weighted_ytd(contrib, "2026-01") is None


def test_brief_ytd_prefers_region_figure_and_omits_on_none():
    rows = rc.synthetic_rows(_ytd_fixture(), "2026-03")
    weighted = rc.weighted_ytd(_ytd_fixture(), "2026-03")
    # Region: explicit figure wins over the synthetic-row mean.
    assert flyer._brief_ytd({"ytd": weighted}, rows) == weighted
    # Region with no usable window: omit, do NOT fall back to the mean.
    assert flyer._brief_ytd({"ytd": None}, rows) is None
    # Country: no "ytd" key -> derive from own rows.
    assert flyer._brief_ytd({}, rows) == mc.ytd_window(rows)


def test_region_briefs_carry_weighted_ytd():
    for slug in ("eu", "world", "northern_europe", "south_america"):
        info = rc.load(slug)
        fig = info["figures"]
        assert "ytd" in fig, slug
        if info["rows"][-1].get("source") == "ACEA":
            # The EU on ACEA's own total: YTD is that series' own count.
            assert fig["ytd"] == mc.ytd_window(info["rows"]), slug
        else:
            members, _, _ = rc.load_members(slug)
            t, contrib, _ = rc.pick_common_end(members)
            assert t and contrib, slug
            assert fig["ytd"] == rc.weighted_ytd(contrib, t), slug
        # The flyer resolves to the weighted figure, never the synthetic mean.
        assert flyer._brief_ytd(fig, info["rows"]) == fig["ytd"], slug


def test_eu_series_is_acea_total_and_curve_is_the_builder_curve():
    """The EU brief quotes ACEA's EU27 total (the number in ACEA's release)
    and draws the live group curve, the one the Builder tab shows, with the
    95% band combined from the members' live bands."""
    import snapshot_builder as sb
    info = rc.load("eu")
    rows = info["rows"]
    acea = {r["period"]: r for r in rc.acea_monthly_rows()}
    last = rows[-1]
    assert last["source"] == "ACEA" and last["period"] == max(acea)
    # Headline month = ACEA's own BEV / TOTAL for that month.
    assert abs(info["latest"] - 100 * acea[last["period"]]["BEV"]
               / acea[last["period"]]["TOTAL"]) < 1e-9
    # Months before ACEA's first month are the members' sum, consecutive,
    # with HEV unknown (not 0).
    first_acea = min(acea)
    early = [r for r in rows if r["period"] < first_acea]
    assert all(r["source"] == "members" and r["HEV"] is None for r in early)
    idx = [mc.month_index(r["period"]) for r in rows]
    assert all(b - a == 1 for a, b in zip(idx, idx[1:]))
    # Curve: the Builder's group curve from live params/weights.
    params = sb.load_params(rc.REPO / "params.csv")
    weights = sb.load_weights(rc.REPO / "weights.csv")
    countries = sb.resolve_groups(params, weights)["eu"]
    _, bev, _, _, _ = sb.compute_group_curve(countries, params, weights)
    live = rc.live_group_curve("eu")
    assert live["model"] == bev
    state = info["fm"]["curve_state"]
    assert state is live["state"] or state == live["state"]
    if live["band"] and live["band"]["ok"]:
        for c in state["crossings"]:
            lo, hi = c["ci"]
            assert lo is None or lo <= c["fit"]
            assert hi is None or hi >= c["fit"]


def test_acea_series_joins_members_only_on_consecutive_full_months():
    def member(name, months):
        return {"country": name, "weight": 1, "rows": [
            {"period": p, "time_interval": "monthly", "TOTAL": "100", "BEV": "10",
             "PHEV": "5"} for p in months]}
    months = ["2024-06", "2024-07", "2024-08", "2024-09"]
    a = member("A", months)
    b = member("B", ["2024-06", "2024-08", "2024-09"])   # gap in July
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        ref = _acea_monthly(d, ["2024-10", "2024-11"])
        rows = rc.acea_series([a, b], ref)
    periods = [r["period"] for r in rows]
    # July missing for B: the members' run starts after the gap.
    assert periods == ["2024-08", "2024-09", "2024-10", "2024-11"]
    assert rows[0]["BEV"] == 20 and rows[0]["TOTAL"] == 200 and rows[0]["HEV"] is None
    assert rows[-1]["source"] == "ACEA"


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} tests passed")
