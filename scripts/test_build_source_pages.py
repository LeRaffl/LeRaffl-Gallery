#!/usr/bin/env python3
"""Offline tests for the source-page generator's reconciliation section
(`reconciliation:` front-matter tables and the `checks_file:` check table,
scripts/build_source_pages.py). No network, writes nothing to the repo.

    python scripts/test_build_source_pages.py
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_source_pages as bsp  # noqa: E402

TABLE = {
    "title": "From the headline to the charted total",
    "lead": "Lead text.",
    "rows": [
        ["Published national total", "62,590"],
        ["− commercial vehicles", "−9,807"],
        ["= Whole", "51,013"],
        {"cells": ["Police 2025", "624,300"], "url": "https://example.org/p",
         "note": "15 Dec – 14 Dec"},
    ],
    "note": "Under the table.",
}


def test_no_reconciliation_renders_nothing():
    assert bsp.build_reconciliation({}) == ""
    assert bsp.validate_reconciliation({}, "x") == []


def test_table_renders_rows_bold_result_numbers_and_links():
    html = bsp.build_reconciliation({"reconciliation": TABLE})
    assert "<h2>Why other figures differ</h2>" in html
    assert "<h3>From the headline to the charted total</h3>" in html
    assert '<p class="fig-lead">Lead text.</p>' in html
    assert '<th>Step</th><th class="num">Units</th>' in html  # default head
    assert '<tr class="strong"><td>= Whole</td><td class="num">51,013</td></tr>' in html
    assert '<td class="num">−9,807</td>' in html
    assert '<a href="https://example.org/p">Police 2025</a>' in html
    assert '<div class="dim rnote">15 Dec – 14 Dec</div>' in html
    assert '<p class="fig-note">Under the table.</p>' in html
    assert html.count("<tr") == 5  # head + 4 rows


def test_list_of_tables_custom_head_and_heading():
    fm = {"reconciliation_heading": "Reconciliation",
          "reconciliation": [TABLE, {"title": "Second", "head": ["Figure", "Theirs", "Ours", "Why"],
                                     "rows": [["CSGT 2025", "624,300", "592,798", "registrations, not sales"]]}]}
    html = bsp.build_reconciliation(fm)
    assert "<h2>Reconciliation</h2>" in html and "<h3>Second</h3>" in html
    assert '<td>registrations, not sales</td>' in html  # text stays left-aligned
    assert '<td class="num">592,798</td>' in html
    assert bsp.validate_reconciliation(fm, "x") == []


def test_text_is_escaped():
    html = bsp.build_reconciliation({"reconciliation": {"title": "<b>", "rows": [["a & b", "<i>"]]}})
    assert "<h3>&lt;b&gt;</h3>" in html
    assert "a &amp; b" in html and "&lt;i&gt;" in html


def test_numeric_detection():
    for v in ("62,590", "−9,807", "+5.3 %", "23,627 · 2,171 · 113", "0", "±100", "51,013 ✓"):
        assert bsp._NUMERIC.match(v), v
    for v in ("VAMA", "2025-07", "about 5 %", "−2 % to +10 %"):
        assert not bsp._NUMERIC.match(v), v


def test_validation_catches_shape_errors():
    bad = {"reconciliation": [{"rows": [["only one cell"], "not a row"]}, "x"],
           "checks_file": "market/x_checks.csv"}
    probs = bsp.validate_reconciliation(bad, "doc.md")
    assert any("has no title" in p for p in probs)
    assert any("row 1 has 1 cells, head has 2" in p for p in probs)
    assert any("row 2 is neither a list nor a mapping" in p for p in probs)
    assert any("reconciliation[1] is not a mapping" in p for p in probs)
    assert any("checks_file must be a .json path" in p for p in probs)
    assert bsp.validate_reconciliation({"reconciliation": "text"}, "d")[0].endswith(
        "must be a table or a list of tables")
    assert any("has no rows" in p for p in bsp.validate_reconciliation(
        {"reconciliation": {"title": "t"}}, "d"))


def test_checks_file_renders_and_missing_file_is_silent():
    doc = {"as_of": "2026-09", "checks": [
        {"period": "2026-09", "check": "Media total (VnEconomy)", "url": "https://e.org/a",
         "ours": 62590, "theirs": 62590, "gap": 0, "gap_pct": 0.0,
         "tolerance": "0", "status": "pass"},
        {"period": "2025-07", "check": "Media total", "ours": 46819, "theirs": 46830,
         "gap": -11, "gap_pct": -0.02, "tolerance": "0", "status": "warn",
         "note": "article used VinFast 11,490"},
        {"period": "2026-H1", "check": "Police registrations", "ours": 343126,
         "theirs": None, "status": "missing", "tolerance": "−2 % … +15 %"},
    ]}
    with tempfile.TemporaryDirectory() as tmp:
        old = bsp.REPO
        try:
            bsp.REPO = Path(tmp)
            (Path(tmp) / "market").mkdir()
            (Path(tmp) / "market" / "x_checks.json").write_text(json.dumps(doc))
            html = bsp.build_reconciliation({"checks_file": "market/x_checks.json"})
            assert bsp.build_reconciliation({"checks_file": "market/none.json"}) == ""
        finally:
            bsp.REPO = old
    assert "Checked through <code>2026-09</code>" in html
    assert '<a href="https://e.org/a">Media total (VnEconomy)</a>' in html
    assert '<td class="num">62,590</td>' in html
    assert "−11" in html and "(−0.02%)" in html
    assert "chk--ok" in html and "chk--warn" in html and "chk--miss" in html
    assert "article used VinFast 11,490" in html
    assert '<td class="num">—</td>' in html  # missing reference figure


def test_page_places_section_after_how_it_works():
    fm = {"country": "Testland", "slug": "testland", "source_name": "S",
          "variants": ["Whole"], "method": "pdf", "notes": ["How."],
          "reconciliation": TABLE}
    page = bsp.build_page(fm, {})
    assert page.index("<h2>How it works</h2>") < page.index("<h2>Why other figures differ</h2>")
    assert "table.recon{" in page
    assert 'class="poster"' not in page
    assert "<h1>Testland" in page


def _germany_through_october_2026() -> str:
    """Germany's CSV cut at 2026-10, so the pinned numbers below do not move
    when the next month is fetched."""
    lines = (bsp.REPO / "data" / "Germany.csv").read_text(encoding="utf-8").splitlines()
    kept = [lines[0]] + [ln for ln in lines[1:] if ln[:7] <= "2026-10"]
    tmp = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
    tmp.write("\n".join(kept) + "\n")
    tmp.close()
    return tmp.name


def test_germany_shift_matches_the_published_window():
    data_file = _germany_through_october_2026()
    shift = bsp.combustion_shift({"data_file": data_file, "hev_split": True})
    assert shift is not None
    assert shift["end"] == "2026-10"
    assert abs(shift["dB"] - 9.4068) < 0.01
    assert abs(shift["dI"] + 10.0114) < 0.01
    assert bsp._shift_line(shift) == (
        "Combustion lost 10 points. Battery electric took 9.4 of them."
    )
    points = bsp.mix_series({"data_file": data_file})
    assert points is not None
    assert points[-1]["period"] == "2026-10"
    assert abs(points[-1]["BEV"] - shift["b1"]) < 0.01
    assert points[0]["period"] < "2018-01"


def test_repo_front_matter_still_valid():
    entries, problems = bsp.collect_entries()
    assert not problems, problems
    assert entries


# --- model card (scripts/model_card.py) ------------------------------------

import datetime as dt  # noqa: E402

import model_card as mc  # noqa: E402


def _rows(n, start=(2024, 1), interval="monthly", **cols):
    """n periods; each column is a function of the row number."""
    out = []
    step = 3 if interval == "quarterly" else 1
    for i in range(n):
        idx = start[0] * 12 + start[1] - 1 + i * step
        row = {"period": f"{idx // 12}-{idx % 12 + 1:02d}", "time_interval": interval,
               "variant": "Whole"}
        for name, fn in cols.items():
            value = fn(i)
            row[name] = "" if value is None else str(value)
        out.append(row)
    return out


def test_card_shift_sums_to_zero_and_splits_only_full_columns():
    rows = _rows(24, TOTAL=lambda i: 100, BEV=lambda i: 10 if i < 12 else 20,
                 PHEV=lambda i: 5, HEV=lambda i: 10,
                 PETROL=lambda i: 60 if i < 12 else 50, DIESEL=lambda i: 15)
    shift = mc.powertrain_shift(rows, hev_full=True)
    keys = [r["key"] for r in shift["rows"]]
    assert keys == ["BEV", "PHEV", "HEV", "PETROL", "DIESEL"]  # no empty residual
    assert abs(sum(r["delta"] for r in shift["rows"])) < 1e-9
    by = {r["key"]: r for r in shift["rows"]}
    assert by["BEV"]["delta"] == 10 and by["PETROL"]["delta"] == -10
    assert by["HEV"]["label"] == "Full hybrid"
    assert shift["span"] == (("2024-01", "2024-12"), ("2025-01", "2025-12"))
    assert "Lost share: Petrol 10.0." in mc.shift_sentence(shift)


def test_card_shift_empty_cell_is_unknown_not_zero():
    # One empty PETROL cell: petrol and diesel fall back into the residual.
    rows = _rows(24, TOTAL=lambda i: 100, BEV=lambda i: 10, HEV=lambda i: 10,
                 PETROL=lambda i: None if i == 3 else 60, DIESEL=lambda i: 20)
    shift = mc.powertrain_shift(rows)
    assert [r["key"] for r in shift["rows"]] == ["BEV", "HEV", "REST"]
    assert shift["rows"][-1]["label"] == "Combustion and anything not split out"
    # An empty BEV or TOTAL cell means no picture at all.
    rows[5]["BEV"] = ""
    assert mc.powertrain_shift(rows) is None
    assert mc.build_shift(None) == ""


def test_card_shift_needs_a_gapless_single_cadence_tail():
    rows = _rows(24, TOTAL=lambda i: 100, BEV=lambda i: 10)
    assert mc.powertrain_shift(rows) is not None
    assert mc.powertrain_shift(rows[:20]) is None
    assert mc.powertrain_shift(rows[:10] + rows[11:] + _rows(1, start=(2026, 1), TOTAL=lambda i: 100, BEV=lambda i: 1)) is None
    quarterly = _rows(8, interval="quarterly", TOTAL=lambda i: 100, BEV=lambda i: i)
    shift = mc.powertrain_shift(quarterly)
    assert shift["interval"] == "quarterly"
    assert shift["span"][0] == ("2023-11", "2024-10")


def test_card_shift_refuses_overlapping_columns():
    rows = _rows(24, TOTAL=lambda i: 100, BEV=lambda i: 10, HEV=lambda i: 50,
                 MHEV=lambda i: 45)
    assert mc.powertrain_shift(rows) is None


def test_card_fit_gate_mirrors_fit_core():
    today = dt.date(2026, 11, 16)
    good = {"v1": "-6.48e-5", "v2": "3.1", "t0": "2011", "data_per": "2026-10",
            "ttm_bev_share": "0.27", "refit_swing": "1.7"}
    assert mc.fit_reliability(good, today)["status"] == "ok"
    assert mc.fit_reliability({**good, "refit_swing": "9"}, today)["status"] == "provisional"
    assert mc.fit_reliability({**good, "refit_swing": "Inf"}, today)["reasons"] == ["unsettled"]
    assert mc.fit_reliability({**good, "data_per": "2025-01"}, today)["reasons"] == ["stale"]
    assert "collapsed" in mc.fit_reliability({**good, "v1": "-1e-30", "v2": "32"}, today)["reasons"]
    assert mc.has_no_transition({**good, "ttm_bev_share": "0.004"})
    assert not mc.has_no_transition(good)
    assert abs(mc.fit_year(0.5, -6.481759365635e-05, 3.1016795876, 2011) - 2030.92) < 0.05


def test_card_dates_only_from_a_reliable_fit_and_a_usable_band():
    today = dt.date(2026, 11, 16)
    good = {"v1": "-6.48e-5", "v2": "3.1", "t0": "2011", "data_per": "2026-10",
            "ttm_bev_share": "0.27", "refit_swing": "1.7", "model_date": "2026-11-04"}
    band = {"data_per": "2026-10", "quality": {"usable": True, "reasons": []},
            "crossing": [{"share": 0.5, "fit": 2030.9, "ci": [2028.9, 2035.7]},
                         {"share": 0.9, "fit": 2040.3, "ci": [2034.3, None]}]}
    state = mc.model_state(good, band, today)
    assert state["quotable"] and state["band_ok"]
    half = next(c for c in state["crossings"] if c["level"] == 0.5)
    assert mc._ci_text(half["ci"]) == "2028–2035"
    assert mc._ci_text((2034.3, None)) == "2034 or later"
    html = mc.build_model("X", [], state, band, [])
    assert "95 % confidence interval" in html and "not an official forecast" in html
    # Unusable band: years stay, the interval goes.
    weak = mc.model_state(good, {**band, "quality": {"usable": False, "reasons": ["short"]}}, today)
    assert weak["quotable"] and not weak["band_ok"]
    assert "No confidence interval is shown" in mc.build_model("X", [], weak, band, [])
    # A band built for an older month is not this curve's band.
    assert not mc.model_state(good, {**band, "data_per": "2026-09"}, today)["band_ok"]
    # Excluded fit: no dates at all.
    bad = mc.model_state({**good, "refit_swing": "Inf"}, band, today)
    assert not bad["quotable"] and bad["crossings"] == []
    assert "not reliable enough" in mc.build_model("X", [], bad, band, [])
    assert mc.model_state(None, band) is None


def test_card_slug_mirrors_slug_country():
    assert mc.band_slug("Hong Kong") == "hong_kong"
    assert mc.band_slug("Türkiye") == "tuerkiye"
    assert mc.band_slug("Germany", "Vans") == "germany_vans"


def test_card_formatting():
    assert mc.share(0.44) == "0.44 %" and mc.share(27.19) == "27.2 %"
    assert mc.points(0.02) == "±0" and mc.points(-2.46) == "−2.5"
    assert mc.units(2_970_000) == "2.97 M" and mc.units(808679) == "808,679"
    assert mc.period_label("2026-10", long=True) == "October 2026"


# --- flyer (scripts/flyer.py) -----------------------------------------------

import flyer  # noqa: E402


def test_flyer_verdict_says_how_far_and_which_way():
    def fig(share, delta):
        return {"ttm": {"share": share, "delta": delta, "end": "2026-10"}}
    assert flyer.verdict("X", fig(27.2, 9.4), None) == (
        "About 1 in 4 new cars is battery electric.",
        "The share is rising fast: up 9.4 points in a year.")
    assert flyer.verdict("X", fig(0.4, 0.0), None) == (
        "Fewer than 1 in 100 new cars is battery electric.",
        "The share has barely moved in a year.")
    assert flyer.verdict("X", fig(95.0, 2.0), None)[0].startswith("Almost every new car")
    assert flyer.verdict("X", fig(62.0, -3.0), None) == (
        "Most new cars are battery electric: 62 in 100.",
        "The share fell by 3.0 points in a year.")
    assert flyer.verdict("X", {}, None) == ("X: new registrations by powertrain", "")
    # The follow-up names the biggest mover as a fact, not as a cause.
    shift = {"rows": [{"key": "BEV", "label": "Battery electric", "delta": 1.9},
                      {"key": "PETROL", "label": "Petrol", "delta": -4.0},
                      {"key": "CNG", "label": "CNG", "delta": 2.8}]}
    assert flyer.verdict("X", fig(5.9, 1.9), shift)[1].endswith("Petrol lost the most: 4.0 points.")


def test_flyer_mix_keeps_unknown_columns_out_of_their_own_band():
    rows = _rows(30, TOTAL=lambda i: 100, BEV=lambda i: 10 + i,
                 HEV=lambda i: None if i < 6 else 10)
    points = flyer.mix_points(rows)
    assert len(points) == 19 and points[-1]["period"] == "2026-06"
    assert points[0]["HEV"] is None and points[-1]["HEV"] == 10
    assert points[-1]["PHEV"] is None
    assert abs(points[-1]["BEV"] + points[-1]["HEV"] + points[-1]["REST"] - 100) < 1e-9
    assert flyer.mix_points(rows[:20]) == []          # too short to draw


def test_flyer_page_builds_without_data():
    html = flyer.build_flyer({"country": "Nowhere", "slug": "nowhere"}, [], None, {}, None, None, "t.css")
    assert "Nowhere" in html and "fl-foot" in html


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} tests passed")
