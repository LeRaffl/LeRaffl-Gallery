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
    for v in ("62,590", "−9,807", "+5.3%", "23,627 · 2,171 · 113", "0", "±100", "51,013 ✓"):
        assert bsp._NUMERIC.match(v), v
    for v in ("VAMA", "2025-07", "about 5%", "−2% to +10%"):
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
         "theirs": None, "status": "missing", "tolerance": "−2% … +15%"},
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



def test_hero_chart_fills_the_number_column():
    rows = _rows(18, TOTAL=lambda i: 100, BEV=lambda i: 10 + i)
    figures = {"ttm": {"share": 24.1, "delta": 7.2, "end": "2026-10"},
               "latest": {"row": {"period": "2026-10"}, "share": 30.7}}
    mix, curve = flyer.hero_chart_heights(figures, rows, spare=0)
    assert mix >= 180 and mix > 132
    mix0, _ = flyer.hero_chart_heights({"ttm": {"share": 10, "delta": None, "end": "2026-10"}},
                                       [], spare=0)
    assert mix0 >= 132
    _, curve_r = flyer.hero_chart_heights(figures, rows, spare=0, region=True)
    assert curve_r > curve


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


def test_card_rows_are_read_in_period_order():
    # Malta's CSV appends a late block after older rows; file order would
    # make an older month the "latest" and break the 24-month tail.
    import csv as _csv
    rows = _rows(26, TOTAL=lambda i: 100, BEV=lambda i: i)
    shuffled = rows[:10] + rows[20:] + rows[10:20]
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, dir=mc.REPO,
                                     encoding="utf-8", newline="") as fh:
        writer = _csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(shuffled + [{**rows[0], "variant": "Vans"}])
        name = Path(fh.name).name
    try:
        got = mc.whole_rows(name)
        assert [r["period"] for r in got] == [r["period"] for r in rows]
        assert mc.powertrain_shift(got) is not None
        assert [r["variant"] for r in mc.series_rows(name, "Vans")] == ["Vans"]
    finally:
        (mc.REPO / name).unlink()


def test_card_ttm_only_from_a_full_window_at_the_latest_period():
    rows = _rows(14, TOTAL=lambda i: 100, BEV=lambda i: 10)
    window = mc.ttm_window(rows)
    assert window["share"] == 10 and window["end"] == rows[-1]["period"]
    # A gap or an empty BEV cell inside the last 12 months: unknown, and no
    # fallback to an older window or to params.csv.
    assert mc.ttm_window(rows[:5] + rows[6:]) is None
    rows[-3]["BEV"] = ""
    assert mc.ttm_window(rows) is None
    figures = mc.key_figures(rows, None, {"ttm_bev_share": "0.5", "data_per": "2025-02"},
                             {"weight": "1200"})
    assert "ttm" not in figures and "volume" not in figures


def test_card_latest_table_shows_an_empty_bev_cell_as_unknown():
    # A month published with a total but no fuel split yet (Indonesia's PDF
    # can arrive like that) must neither crash the build nor read as 0 %.
    rows = _rows(13, TOTAL=lambda i: 100, BEV=lambda i: None if i == 12 else 10)
    html = mc.build_latest_table(rows, hev_full=False)
    newest = html.split("<tr>")[2]
    assert newest.count(">—<") == 3 and "0.0" not in newest


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
    assert "95% confidence band" in html and "not an official forecast" in html
    # Unusable band: years stay, the interval goes.
    weak = mc.model_state(good, {**band, "quality": {"usable": False, "reasons": ["short"]}}, today)
    assert weak["quotable"] and not weak["band_ok"]
    assert "No confidence band is shown" in mc.build_model("X", [], weak, band, [])
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
    assert mc.share(0.44) == "0.44%" and mc.share(27.19) == "27.2%"
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
        "Nov 2025–Oct 2026 vs the 12 months before: BEV up 9.4 points.")
    assert flyer.verdict("X", fig(0.4, 0.0), None) == (
        "Fewer than 1 in 100 new cars is battery electric.",
        "Nov 2025–Oct 2026 vs the 12 months before: BEV barely moved.")
    assert flyer.verdict("X", fig(95.0, 2.0), None)[0].startswith("Almost every new car")
    assert flyer.verdict("X", fig(62.0, -3.0), None) == (
        "Most new cars are battery electric: 62 in 100.",
        "Nov 2025–Oct 2026 vs the 12 months before: BEV down 3.0 points.")
    assert flyer.verdict("X", {}, None) == ("X: new registrations by powertrain", "")
    # The follow-up names the biggest mover as a fact, not as a cause.
    shift = {"rows": [{"key": "BEV", "label": "Battery electric", "delta": 1.9},
                      {"key": "PETROL", "label": "Petrol", "delta": -4.0},
                      {"key": "CNG", "label": "CNG", "delta": 2.8}]}
    assert flyer.verdict("X", fig(5.9, 1.9), shift)[1] == (
        "Nov 2025–Oct 2026 vs the 12 months before: BEV up 1.9 points, petrol down 4.0.")
    # A residual "everything else" row only mirrors BEV; it is not named.
    residual = {"rows": [{"key": "BEV", "label": "Battery electric", "delta": 3.7},
                         {"key": "REST", "label": "Everything else", "delta": -3.7}]}
    follow = flyer.verdict("X", fig(20.2, 3.7), residual)[1]
    assert follow == "Nov 2025–Oct 2026 vs the 12 months before: BEV up 3.7 points."
    assert "everything else" not in follow.lower()


def test_flyer_mix_keeps_unknown_columns_out_of_their_own_band():
    rows = _rows(30, TOTAL=lambda i: 100, BEV=lambda i: 10 + i,
                 HEV=lambda i: None if i < 6 else 10)
    points = flyer.mix_points(rows)
    assert len(points) == 19 and points[-1]["period"] == "2026-06"
    assert points[0]["HEV"] is None and points[-1]["HEV"] == 10
    assert points[-1]["PHEV"] is None
    assert abs(points[-1]["BEV"] + points[-1]["HEV"] + points[-1]["REST"] - 100) < 1e-9
    assert flyer.mix_points(rows[:20]) == []          # too short to draw


def test_flyer_mix_never_calls_a_rest_with_plug_ins_combustion():
    full = _rows(30, TOTAL=lambda i: 100, BEV=lambda i: 10, PHEV=lambda i: 5, HEV=lambda i: 10)
    assert ">Combustion 75.0%<" in flyer.build_mix(flyer.mix_points(full), False, 470, 146)
    no_plug = _rows(30, TOTAL=lambda i: 100, BEV=lambda i: 10, HEV=lambda i: 10)
    svg = flyer.build_mix(flyer.mix_points(no_plug), False, 470, 146)
    assert ">Everything else 80.0%<" in svg and ">Combustion" not in svg
    assert 'class="fl-mix"' in svg and 'mix-plot' in svg


def test_flyer_says_when_the_dates_are_provisional():
    rows = _rows(30, start=(2024, 1), TOTAL=lambda i: 1000, BEV=lambda i: 100 + 10 * i)
    param = {"v1": "-6.48e-5", "v2": "3.1", "t0": "2011", "data_per": "2026-06",
             "ttm_bev_share": "0.27", "refit_swing": "9"}
    state = mc.model_state(param, None, dt.date(2026, 7, 1))
    assert state["quotable"] and state["rel"]["status"] == "provisional"
    html = flyer.build_flyer({"country": "X", "slug": "x"}, rows, None, {}, state, None, "t.css")
    assert "Provisional: the 80% year moved by 9 years" in html
    ok = mc.model_state({**param, "refit_swing": "1"}, None, dt.date(2026, 7, 1))
    assert "Provisional" not in flyer.build_flyer({"country": "X", "slug": "x"}, rows, None, {},
                                                  ok, None, "t.css")


def test_flyer_page_builds_without_data():
    html = flyer.build_flyer({"country": "Nowhere", "slug": "nowhere"}, [], None, {}, None, None, "t.css")
    assert "Nowhere" in html and "fl-foot" in html
    assert "<b>Abbreviations:</b>" in html and "How to read it." not in html
    assert "The curve is a model, not a forecast." not in html


def test_flyer_offers_pdf_and_png_export():
    """The A4 brief can be saved as a PDF (print dialog) or as a PNG of the
    same white sheet. The toolbar is hidden in print; the PNG script lives
    next to theme.css and is not on the social card."""
    html = flyer.build_flyer({"country": "Nowhere", "slug": "nowhere"}, [], None, {}, None, None, "t.css")
    assert 'onclick="window.print()"' in html and "Save as PDF" in html
    assert "Download PNG" in html and 'class="fl-png"' in html
    assert 'class="fl-exports"' in html
    assert 'src="../../assets/flyer-png.js"' in html
    # print hides the whole bar (both buttons, the links, later also nav)
    assert "@media print{" in html
    assert ".fl-bar{display:none}" in html.split("@media print{")[1].split("</style>")[0]
    js = (bsp.REPO / "assets" / "flyer-png.js").read_text(encoding="utf-8")
    assert "modern-screenshot 4.7.0" in js
    assert "domToPng" in js
    assert "#fdfdfc" in js and "SCALE = 2" in js
    assert "pinTransformOrigins" in js
    # social cards are exported as images; a button would be baked in
    entries, _ = bsp.collect_entries()
    fm = next(fm for fm, _ in entries if fm.get("country") == "Ireland")
    social = bsp.build_social_page(fm, bsp.load_params(), bsp.flyer_peers(entries, bsp.load_params()))
    assert "Download PNG" not in social and "flyer-png.js" not in social
    assert "Save as PDF" not in social


def test_flyer_qr_compare_and_fractions():
    qr = flyer.build_qr("https://example.org/x")
    assert qr.startswith("<svg") and "QR code: https://example.org/x" in qr
    assert qr == flyer.build_qr("https://example.org/x")           # byte-stable
    peers = [(f"C{i}", float(i)) for i in range(1, 21)]
    html = flyer.build_compare("C18", peers, 700)
    assert "<b>3rd of 20</b>" in html and "Typical share: 10.5%" in html
    assert "Middle half of countries: between 6% and 15%." in html
    assert "25%:" not in html and "75%:" not in html
    assert "Box = middle half of the 20 countries in the Gallery" in html
    assert "the lines reach" not in html   # whisker/lines explanation dropped
    assert "BEV share, last 12 months" in html and "Fitted curve reaches 50%" not in html
    assert flyer.build_compare("Nowhere", peers, 700) == ""
    assert flyer.build_compare("C1", peers[:5], 700) == ""       # too few to compare
    # Named highlights, minus the subject, appear as flagged ticks and in the legend.
    html = flyer.build_compare(
        "C18", peers, 700,
        highlights=[{"name": "C20", "slug": "c20", "share": 20.0},
                    {"name": "C18", "slug": "c18", "share": 18.0},
                    {"name": "C5", "slug": "c5", "share": 5.0}])
    assert "Flags:" not in html   # the flag legend sentence was dropped; ticks remain
    assert "<title>C20</title>" in html and html.count("<title>C18</title>") == 1
    assert "C18 18.0%" in html
    # The 50 % year strip: earliest first, only with the subject's own year.
    years = [(f"C{i}", 2020.0 + i) for i in range(1, 21)]
    html = flyer.build_compare("C18", peers, 700, peer_years=years)
    assert "Fitted curve reaches 50%" in html and "C18 2038 · <b>18th of 20</b>" in html
    assert "Years:" not in html   # years explanation dropped
    assert "Typical 50% year: 2030" in html
    no_year = [(n, y) for n, y in years if n != "C18"]
    assert "Fitted curve reaches 50%" not in flyer.build_compare("C18", peers, 700,
                                                                 peer_years=no_year)
    # 80 % year strip, same omission rule, and both together.
    years80 = [(f"C{i}", 2025.0 + i) for i in range(1, 21)]
    html = flyer.build_compare("C18", peers, 700, peer_years=years, peer_years_80=years80)
    assert "Fitted curve reaches 80%" in html and "C18 2043 · <b>18th of 20</b>" in html
    assert "50 % 20, 80 % 20" not in html  # same N, one clause
    assert "Years:" not in html   # years explanation dropped
    # 50 % and 80 % share one year axis; the 50 % box sits further left.
    strips, _, _ = flyer.compare_strips("C18", peers, peer_years=years, peer_years_80=years80)
    y50, y80 = [s for s in strips if s.get("kind") == "year"]
    assert y50["axis"] == y80["axis"]
    assert y50["axis"][0] <= 2021 and y50["axis"][1] >= 2045
    assert y50["own"]["value"] < y80["own"]["value"]
    assert y50["ticks"] == [] and y80.get("shared_ticks")
    assert 'class="fl-svg fl-cmp-axis"' in html
    assert html.count(">2020<") == 1 and html.count(">2045<") == 1
    assert "Year scale, 2020 to 2045" in html
    no80 = [(n, y) for n, y in years80 if n != "C18"]
    html = flyer.build_compare("C18", peers, 700, peer_years=years, peer_years_80=no80)
    assert "Fitted curve reaches 50%" in html and "Fitted curve reaches 80%" not in html
    assert "fl-cmp-axis" not in html          # a single year strip keeps its own ticks
    # A region is placed among the countries, not ranked as one.
    html = flyer.build_compare("Group", peers, 700, is_region=True, own_share=12.5,
                               peer_years=years, own_year=2029.5,
                               peer_years_80=years80, own_year_80=2034.2)
    assert "would be 9th of 20" in html and "Group 2029 · would be 10th of 20" in html
    assert "Group 2034 · would be 10th of 20" in html
    html, h = flyer.build_compare_social("C18", peers, [{"name": "C5", "slug": "c5", "share": 5.0}])
    assert "sc-bx" in html and "<b>3rd of 20</b>" in html and h > 0
    assert "Fitted curve" not in html
    assert flyer.build_compare_social("Nowhere", peers) == ("", 0)
    assert [flyer.ordinal(n) for n in (1, 2, 3, 4, 11, 12, 21, 22)] == [
        "1st", "2nd", "3rd", "4th", "11th", "12th", "21st", "22nd"]
    fig = lambda s: {"ttm": {"share": s, "delta": None, "end": "2026-10"}}  # noqa: E731
    assert flyer.verdict("X", fig(39.9), None)[0] == "About 2 in 5 new cars are battery electric."
    assert flyer.verdict("X", fig(33.0), None)[0] == "About 1 in 3 new cars is battery electric."
    assert flyer.verdict("X", fig(50.3), None)[0] == "About half of new cars are battery electric."


def test_box_stats_quartiles_and_ranks():
    st = flyer.box_stats([5, 1, 3, 2, 4])
    assert (st["min"], st["q1"], st["median"], st["q3"], st["max"], st["n"]) == (1, 2, 3, 4, 5, 5)
    st = flyer.box_stats([float(i) for i in range(1, 21)])           # type-7 quartiles
    assert (st["q1"], st["median"], st["q3"]) == (5.75, 10.5, 15.25)
    assert flyer.box_stats([1, 2, float("nan"), 3, 4]) is None       # fewer than 5 real values
    assert flyer._rank_of(30, [10, 30, 50], higher_first=True) == 2
    assert flyer._rank_of(2030, [2025, 2030, 2040], higher_first=False) == 2
    state = {"quotable": True, "crossings": [{"level": 0.2, "fit": 2024.1},
                                             {"level": 0.5, "fit": 2031.4}]}
    assert flyer.year_at_50(state) == 2031.4
    assert flyer.year_at_50({**state, "quotable": False}) is None
    assert flyer.year_at_50({"quotable": True, "crossings": [
        {"level": 0.5, "fit": float("inf")}]}) is None
    state80 = {"quotable": True, "crossings": [{"level": 0.5, "fit": 2031.4},
                                               {"level": 0.8, "fit": 2038.2}]}
    assert flyer.year_at_80(state80) == 2038.2
    assert flyer.year_at(state80, 0.8) == 2038.2
    assert flyer.year_at_80({**state80, "quotable": False}) is None
    assert flyer.year_at_80(state) is None


def test_compare_years_follow_the_quotable_fit_rule():
    entries, _ = bsp.collect_entries()
    params = bsp.load_params()
    years = dict(bsp.flyer_peer_years(entries, params))
    years80 = dict(bsp.flyer_peer_years(entries, params, level=0.8))
    assert len(years) >= 10
    assert len(years80) >= 10
    for fm, _ in entries:
        fm = bsp.apply_group_defaults(fm)
        state = mc.model_state(params.get((fm["country"], "Whole")), mc.load_bands(fm["country"]))
        assert (fm["country"] in years) == (flyer.year_at_50(state) is not None)
        assert (fm["country"] in years80) == (flyer.year_at_80(state) is not None)


def test_flyer_draws_no_curve_for_a_fit_without_dates():
    rows = _rows(30, TOTAL=lambda i: 1000, BEV=lambda i: 5 + i)
    bad = mc.model_state({"v1": "-1e-30", "v2": "32", "t0": "2011", "data_per": "2026-06",
                          "ttm_bev_share": "0.02", "refit_swing": "1"}, None,
                         dt.date(2026, 7, 1))
    assert not bad["quotable"]
    assert "cv-fit" in mc.build_curve_svg(rows, bad, None)                      # source page: dashed
    assert "cv-fit" not in mc.build_curve_svg(rows, bad, None, weak_fit=False)  # brief: none


def _shown_sums(html):
    import re
    def num(t):
        return 0.0 if t == "±0" else float(t.replace("−", "-").replace("%", ""))
    pp = [num(x) for x in re.findall(r'class="fb-pp">([^<]*)<', html)]
    now = [num(x) for x in re.findall(r'class="fb-now">([^<]*)<', html)]
    return pp, now


def test_every_country_split_adds_up():
    # "Who gained, who lost": the rows are one split of one denominator, so
    # the changes sum to 0 and the shares to 100 % (rounding only), also
    # after the brief folds rows past its limit into one.
    import flyer
    import model_card as mc
    entries, _ = bsp.collect_entries()
    checked = 0
    for fm, _stub in entries:
        fm = bsp.apply_group_defaults(fm)
        shift = mc.powertrain_shift(mc.whole_rows(fm.get("data_file")),
                                    fm.get("hev_split") is True)
        if not shift:
            continue
        checked += 1
        rows = flyer.split_rows(shift)
        name = fm.get("country")
        assert abs(sum(r["delta"] for r in rows)) < 0.05, (name, rows)
        assert abs(sum(r["after"] for r in rows) - 100) < 0.05, (name, rows)
        pp, now = _shown_sums(flyer.build_bars(shift))
        assert len(pp) == len(rows)
        tol = 0.05 * len(rows) + 1e-9   # each printed value rounds by ≤ 0.05
        assert abs(sum(pp)) <= tol and abs(sum(now) - 100) <= tol, (name, pp, now)
    assert checked > 20, checked


def test_split_rows_fold_instead_of_drop():
    import flyer
    rows = [{"key": k, "label": k, "before": b, "after": a, "delta": a - b}
            for k, b, a in (("BEV", 10, 20), ("PHEV", 5, 6), ("HEV", 10, 12), ("PETROL", 50, 40),
                            ("DIESEL", 20, 17), ("LPG", 4, 4.5), ("REST", 1, 0.5))]
    shown = flyer.split_rows({"rows": rows})
    assert len(shown) == 6 and shown[-1]["key"] == "REST"
    assert abs(sum(r["delta"] for r in shown)) < 1e-9
    assert abs(sum(r["after"] for r in shown) - 100) < 1e-9


def test_social_page_uses_the_brief_figures():
    import re
    entries, _ = bsp.collect_entries()
    fm = next(fm for fm, _ in entries if fm.get("country") == "Ireland")
    params = bsp.load_params()
    html = bsp.build_social_page(fm, params, bsp.flyer_peers(entries, params))
    assert "sources/flyer/ireland.html" in html      # QR resolves to the brief
    assert "sc-qr" in html
    assert not re.search(r"\d %", html)              # repo percent convention
    assert "%%" not in html                          # hero sign appended once
    assert re.search(r'sc-big">[\d.]+<span>%</span>', html)


def test_region_pages_written_with_own_qr():
    import flyer
    entries, _ = bsp.collect_entries()
    params = bsp.load_params()
    peers = bsp.flyer_peers(entries, params)
    old = bsp.OUT_DIR
    with tempfile.TemporaryDirectory() as tmp:
        bsp.OUT_DIR = Path(tmp)
        try:
            (bsp.OUT_DIR / "flyer").mkdir()
            items = bsp.build_regions(peers)
            slugs = {i["slug"] for i in items}
            assert {"eu", "world"} <= slugs, slugs
            eu = (bsp.OUT_DIR / "flyer" / "eu.html").read_text(encoding="utf-8")
            assert "sources/flyer/eu.html" in eu     # QR resolves to itself, not home
            assert "%%" not in eu
            assert (bsp.OUT_DIR / "flyer" / "eu_social.html").is_file()
            assert (bsp.OUT_DIR / "flyer" / "world_social.html").is_file()
            idx = flyer.build_index([bsp.flyer_summary(fm, params) for fm, _ in entries],
                                    "../../assets/theme.css", regions=items)
            assert "Region briefs" in idx and 'href="eu.html"' in idx
        finally:
            bsp.OUT_DIR = old


def test_hero_percent_sign_once():
    import re
    entries, _ = bsp.collect_entries()
    fm = next(fm for fm, _ in entries if fm.get("country") == "Ireland")
    params = bsp.load_params()
    html = bsp.build_flyer_page(fm, params)
    assert "%%" not in html
    assert re.search(r'fh-big">[\d.]+<span>%</span>', html)


def test_hero_windows_are_labelled():
    """The three 'current' numbers must be unmistakably different windows:
    the hero is the 12-month average, the single month and year-to-date are
    labelled secondary lines — not a second bold 'current' share competing
    with the hero (the ambiguity a reader hit on the Ireland brief)."""
    entries, _ = bsp.collect_entries()
    fm = next(fm for fm, _ in entries if fm.get("country") == "Ireland")
    params = bsp.load_params()
    a4 = bsp.build_flyer_page(fm, params)
    assert "12 months to" in a4
    assert "Single month ·" in a4
    assert "Year to date ·" in a4
    assert "alone:" not in a4 and "so far:" not in a4
    social = bsp.build_social_page(fm, params, bsp.flyer_peers(entries, params))
    # the big number reads as a plain-language sentence, no BEV jargon hook
    assert "of new cars are battery electric" in social
    assert "Single month ·" in social


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} tests passed")
