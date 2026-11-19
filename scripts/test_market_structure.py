"""Classification rules of the BEV market-structure block (mockup)."""
import market_structure as ms
import model_card as mc


def test_rules():
    assert ms.classify([72.9, 7.4, 5.1]) == "dominant"   # Argentina
    assert ms.classify([36.6, 11.5, 9.4]) == "dominant"  # Ecuador: 2× and leader ≥ 25 %
    assert ms.classify([18.6, 8.8, 5.7]) == "ahead"      # Greece: 2× but leader under 25 %
    assert ms.classify([22.5, 10.6, 9.9]) == "ahead"     # Italy
    assert ms.classify([21.2, 19.8, 9.2]) == "close"     # New Zealand: top 3 = 50.2 %
    assert ms.classify([10.7, 10.0, 7.8]) == "spread"    # Netherlands
    assert ms.classify([34.5, 23.4, 5.5]) == "leader"    # Peru
    assert ms.LABEL["ahead"] == "Wide lead"
    assert ms.sentence({"kind": "ahead", "top3": [{"brand": "BYD", "share": 18.6},
                       {"brand": "Tesla", "share": 8.8}], "top3_sum": 33.1}).startswith(
        "BYD leads with 18.6")
    assert "twice the next brand" in ms.sentence(
        {"kind": "ahead", "top3": [{"brand": "Leapmotor", "share": 22.5},
                                   {"brand": "Tesla", "share": 10.6}], "top3_sum": 43.0})


def test_brand_names():
    assert ms.brand_name("TESLA MOTORS") == "Tesla"
    assert ms.brand_name("SKODA") == "Škoda"
    assert ms.brand_name("JMEV") == "JMEV"
    assert ms.brand_name("DONGFENG") == "Dongfeng"
    assert ms.model_name("TESLA", "MODEL Y") == "Tesla Model Y"


def test_others_label():
    assert ms.others_label({"others_n": 5}) == "5 other brands"
    assert ms.others_label({"others_n": 1}) == "1 other brand"
    assert ms.others_label({"others_n": None}) == "other brands"
    assert ms.others_label({}) == "other brands"


def test_growth_phrase():
    assert mc.growth_phrase(855.3) == "×9.6"
    assert mc.growth_phrase(100) == "×2"
    assert mc.growth_phrase(54) == "+54%"
    assert mc.growth_phrase(4.8) == "+4.8%"
    assert mc.growth_phrase(-8.5) == "−8.5%"
    assert mc.growth_phrase(0.01) == "±0%"


def test_share_range_needs_a_full_monthly_window():
    # A gap, an empty BEV cell, or a short tail is unknown — not 0.
    rows = [{"period": f"2026-{m:02d}", "time_interval": "monthly",
             "BEV": 10, "TOTAL": 100} for m in range(1, 12)]
    assert mc.share_range(rows) is None
    rows.append({"period": "2026-12", "time_interval": "monthly", "BEV": "", "TOTAL": 100})
    assert mc.share_range(rows) is None
    rows[-1]["BEV"] = 20
    rng = mc.share_range(rows)
    assert rng is not None
    assert rng["min"] == 10 and rng["max"] == 20 and rng["latest"] == 20
    assert rng["end"] == "2026-12"
    assert rng["min_period"] == "2026-01" and rng["max_period"] == "2026-12"
    assert mc.range_sentence(rng) == (
        "BEV share fluctuated between 10.0% (Jan 2026) and "
        "20.0% (Dec 2026) over the last 12 months.")
    assert mc.vs_prior_phrase("2026-10") == "Nov 2025–Oct 2026 vs the 12 months before"
    assert mc.window_span_label("2026-09") == "Oct 2025–Sep 2026"


def test_curve_horizon():
    assert mc.CURVE_HORIZON_YEARS == 15


def _shares(*pairs):
    return [{"brand": n, "share": s} for n, s in pairs]


def test_select_named_dominant():
    # Leader ≥ 40 %: only the leader, unless #2 (or later) is still ≥ 10 %.
    assert [b["brand"] for b in ms.select_named(_shares(("BYD", 72.9), ("Chevrolet", 7.4), ("BAIC", 5.1)))] == ["BYD"]
    # Malaysia: 41 / 18 / 11 — all three are part of the basic picture.
    assert [b["brand"] for b in ms.select_named(_shares(
        ("Proton", 41.3), ("BYD", 17.7), ("Tesla", 10.7), ("Zeekr", 6.9)))] == ["Proton", "BYD", "Tesla"]
    # 2× lead with the leader ≥ 25 % also counts as dominant.
    assert [b["brand"] for b in ms.select_named(_shares(
        ("Škoda", 35.8), ("Tesla", 13.7), ("Mercedes-Benz", 5.4)))] == ["Škoda", "Tesla"]
    # A 19 % leader that is merely twice #2 is not list-dominant (Greece).
    assert not ms.list_dominant([18.6, 8.8, 5.7])
    assert ms.list_dominant([72.9, 7.4])
    assert ms.list_dominant([36.6, 11.5])
    assert not ms.list_dominant([22.5, 10.6])   # Italy: 2× but under 25 %


def test_select_named_otherwise():
    # Close race: stop once the named share reaches 50 % (New Zealand).
    nz = ms.select_named(_shares(("Tesla", 21.2), ("BYD", 19.8), ("MG", 9.2), ("Kia", 7.4)))
    assert [b["brand"] for b in nz] == ["Tesla", "BYD", "MG"]
    # At least two in a non-dominant market, even if they already cover 50 %+ (Peru).
    pe = ms.select_named(_shares(("BYD", 34.5), ("Volvo", 23.4), ("Geely", 5.5)))
    assert [b["brand"] for b in pe] == ["BYD", "Volvo"]
    # Next brand below ~5 % stops the list (Spain: Leapmotor 4.7).
    es = ms.select_named(_shares(
        ("BYD", 14.7), ("Tesla", 13.0), ("Kia", 7.4), ("Mercedes-Benz", 5.1), ("Leapmotor", 4.7)))
    assert [b["brand"] for b in es] == ["BYD", "Tesla", "Kia", "Mercedes-Benz"]
    # Cap at five (Netherlands).
    nl = ms.select_named(_shares(
        ("Kia", 10.7), ("Tesla", 10.0), ("Škoda", 7.8), ("Volkswagen", 7.2),
        ("Renault", 7.0), ("Volvo", 6.9)))
    assert [b["brand"] for b in nl] == ["Kia", "Tesla", "Škoda", "Volkswagen", "Renault"]


def _sample_ms():
    named = [{"brand": "BYD", "share": 72.9}]
    return {"named": named, "top3": named + [{"brand": "Chevrolet", "share": 7.4},
            {"brand": "BAIC", "share": 5.1}], "others": 27.1, "others_n": None,
            "kind": "dominant", "units": 1000, "from": "2025-10", "to": "2026-09",
            "model": None, "source": ""}


def test_every_row_shows_logo_and_name():
    html = ms.build_bar(_sample_ms(), "logos", "assets/brands", width=702)
    assert "ms-list" in html
    assert "ms-strip" not in html
    assert html.count('class="ms-row') == 2          # leader + other brands
    assert 'class="ms-row ms-rest"' in html
    assert "other brands" in html
    assert "width:100.00%" in html          # scaled to the leading brand
    assert "width:27.10%" not in html       # remainder has no bar
    assert "ms-track-empty" in html
    # Logo and printed name on the same row; no empty name cell, no chip.
    assert "byd." in html.lower()
    assert ">BYD</div>" in html
    assert 'class="ms-name"></div>' not in html
    assert "ms-chip" not in html
    assert "Chevrolet" not in html                   # #2 is 7.4 %, folded into others


def test_no_logo_leaves_a_blank_slot_and_keeps_the_name():
    ms_ = _sample_ms()
    ms_["named"] = [{"brand": "Renault", "share": 22.0}, {"brand": "BYD", "share": 18.0}]
    ms_["others"] = 60.0
    html = ms.build_bar(ms_, "logos", "assets/brands", width=702)
    assert ">Renault</div>" in html
    assert ">BYD</div>" in html
    assert "ms-logo-slot" in html
    assert "ms-chip" not in html


def test_others_row_omitted_when_the_rest_is_zero():
    ms_ = _sample_ms()
    ms_["named"] = [{"brand": "VinFast", "share": 100.0}]
    ms_["others"] = 0.0
    html = ms.build_bar(ms_, "logos", "x", width=702)
    assert "other brands" not in html
    assert html.count('class="ms-row') == 1



def test_bars_are_scaled_to_the_top_brand():
    ms_ = _sample_ms()
    ms_["named"] = [{"brand": "Kia", "share": 11.5},
                    {"brand": "Volkswagen", "share": 11.0},
                    {"brand": "Hyundai", "share": 10.4}]
    ms_["others"] = 50.7
    html = ms.build_bar(ms_, "logos", "assets/brands", width=702)
    assert "width:100.00%" in html          # Kia
    assert "width:95.65%" in html           # 11.0 / 11.5
    assert "width:90.43%" in html           # 10.4 / 11.5
    assert "50.7" in html and "ms-track-empty" in html
    block = ms.build_block(ms_, "logos", "assets/brands")
    assert "scaled to the top brand" in block


def test_generated_stamp_is_reproducible():
    import os
    import datetime as dt
    when = dt.datetime(2026, 11, 17, 21, 38, tzinfo=dt.timezone.utc)
    prev_epoch, prev_at = os.environ.get("SOURCE_DATE_EPOCH"), os.environ.get("GENERATED_AT")
    try:
        os.environ["SOURCE_DATE_EPOCH"] = str(int(when.timestamp()))
        os.environ.pop("GENERATED_AT", None)
        assert mc.generated_stamp() == "2026-11-17 21:38 UTC"
        assert mc.generated_line("2026-10") == (
            "Generated 2026-11-17 21:38 UTC · data through Oct 2026")
        # An explicit `now` wins over the environment, so a caller can pin it.
        other = dt.datetime(2020, 1, 2, 3, 4, tzinfo=dt.timezone.utc)
        assert mc.generated_stamp(now=other) == "2020-01-02 03:04 UTC"
        # GENERATED_AT is used when SOURCE_DATE_EPOCH is unset.
        os.environ.pop("SOURCE_DATE_EPOCH", None)
        os.environ["GENERATED_AT"] = "2026-11-17 21:38 UTC"
        assert mc.generated_stamp() == "2026-11-17 21:38 UTC"
        # A line with no data window still names the moment and the zone.
        assert mc.generated_line("") == "Generated 2026-11-17 21:38 UTC"
    finally:
        if prev_epoch is None:
            os.environ.pop("SOURCE_DATE_EPOCH", None)
        else:
            os.environ["SOURCE_DATE_EPOCH"] = prev_epoch
        if prev_at is None:
            os.environ.pop("GENERATED_AT", None)
        else:
            os.environ["GENERATED_AT"] = prev_at




def test_flag_filename_accepts_hyphen_or_underscore_slugs():
    assert mc.flag_filename("new-zealand", "New Zealand") == "new_zealand.png"
    assert mc.flag_filename("eu", "EU") == "eu.png"
    assert mc.flag_filename("world", "World") == "world.png"
    assert mc.flag_src("netherlands", "Netherlands").endswith("/netherlands.png")


def test_range_chip_has_no_bar_by_default():
    rng = {"min": 25.0, "max": 65.3, "latest": 55.5, "end": "2026-10",
           "min_period": "2026-01", "max_period": "2025-12"}
    html = mc.range_chip(rng)
    assert "rg-bar" not in html
    assert "Jan 2026" in html and "Dec 2025" in html


def test_chart_legend_names_a_missing_band():
    fit = {"quotable": True, "band_ok": False, "rel": {"status": "ok"}}
    html = mc.chart_legend(fit)
    assert "no confidence band available" in html
    assert "95% confidence band" not in html
    ok = {"quotable": True, "band_ok": True, "rel": {"status": "ok"}}
    assert "95% confidence band" in mc.chart_legend(ok)
    assert "no confidence band available" not in mc.chart_legend(ok)
    none = {"quotable": False, "band_ok": False, "rel": {"status": "excluded"}}
    assert "no stable fit yet" in mc.chart_legend(none)
    assert "no confidence band available" not in mc.chart_legend(none)
    assert "trailing 12-month share" in mc.chart_legend(ok)


if __name__ == "__main__":
    test_rules()
    test_brand_names()
    test_others_label()
    test_growth_phrase()
    test_share_range_needs_a_full_monthly_window()
    test_curve_horizon()
    test_select_named_dominant()
    test_select_named_otherwise()
    test_every_row_shows_logo_and_name()
    test_no_logo_leaves_a_blank_slot_and_keeps_the_name()
    test_others_row_omitted_when_the_rest_is_zero()
    test_bars_are_scaled_to_the_top_brand()
    test_generated_stamp_is_reproducible()
    test_flag_filename_accepts_hyphen_or_underscore_slugs()
    test_range_chip_has_no_bar_by_default()
    test_chart_legend_names_a_missing_band()
    print("ok")
