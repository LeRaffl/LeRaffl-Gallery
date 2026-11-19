#!/usr/bin/env python3
"""Offline tests for scripts/backfill_acea_split.py. No network.

    python scripts/test_backfill_acea_split.py

Fixtures: Press_release_car_registrations_September_2024.pdf and
_October_2024.pdf (scripts/fixtures/) are a deliberately mismatched pair —
September's YTD page is clean text, October's needs the positional
parser, and September's own MONTHLY page is the one that drove the
original build (see scripts/test_fetch_acea.py's March/April fixtures for
the post-April-2026 Word layout instead).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backfill_acea_split as bf  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
SEP = FIX / "Press_release_car_registrations_September_2024.pdf"
OCT = FIX / "Press_release_car_registrations_October_2024.pdf"


def test_country_key_ignores_spacing_and_case():
    assert bf._country_key("Denmark") == bf._country_key("D e n m a r k")
    assert bf._country_key("Denmark") == bf._country_key("denmark")
    assert bf._country_key("Denmark") != bf._country_key("Finland")


def _full(bev, phev, hev, others, petrol, diesel, total):
    return {"BEV": bev, "PHEV": phev, "HEV": hev, "OTHERS": others,
            "PETROL": petrol, "DIESEL": diesel, "TOTAL": total}


def test_ytd_subtract_basic():
    hi = {"Denmark": _full((100, 80), (10, 8), (20, 16), (0, 0), (300, 250), (50, 40), (1000, 900))}
    lo = {"Denmark": _full((60, 50), (6, 5), (12, 10), (0, 0), (180, 150), (30, 25), (600, 550))}
    got = bf._ytd_subtract(hi, lo)
    assert got["Denmark"]["BEV"] == (40, 30)
    assert got["Denmark"]["TOTAL"] == (400, 350)


def test_ytd_subtract_refuses_a_negative_result():
    hi = {"Denmark": _full((10, 80), (10, 8), (20, 16), (0, 0), (300, 250), (50, 40), (1000, 900))}
    lo = {"Denmark": _full((60, 50), (6, 5), (12, 10), (0, 0), (180, 150), (30, 25), (600, 550))}
    assert bf._ytd_subtract(hi, lo) is None  # hi < lo for BEV: not a later cumulative


def test_ytd_subtract_skips_a_country_missing_a_fuel():
    hi = {"Denmark": _full((100, 80), (10, 8), (20, 16), (0, 0), (300, 250), (50, 40), (1000, 900)),
          "Finland": {"BEV": (50, 40)}}  # missing the other six fuels
    lo = {"Denmark": _full((60, 50), (6, 5), (12, 10), (0, 0), (180, 150), (30, 25), (600, 550)),
          "Finland": {"BEV": (20, 15)}}
    got = bf._ytd_subtract(hi, lo)
    assert set(got) == {"Denmark"}


def test_september_2024_ytd_via_clean_text():
    """September's YTD page parses on the text layer — no fallback needed."""
    got = bf.parse_ytd_markets_full(SEP, bf.COUNTRIES)
    assert set(got) == set(bf.COUNTRIES)
    # Jan-Sep 2024 Denmark, read straight off the release in the fixture.
    assert got["Denmark"]["TOTAL"] == (126298, 123980)
    assert got["Denmark"]["HEV"] == (22778, 22726)
    assert got["Finland"]["TOTAL"] == (55500, 68578)


def test_october_2024_ytd_needs_the_positional_parser():
    """October's YTD page has neither clean text nor table-cell rules —
    only the positional (run-fragmented) layout recovers it."""
    got = bf.parse_ytd_markets_full(OCT, bf.COUNTRIES)
    assert set(got) == set(bf.COUNTRIES)
    assert got["Denmark"]["TOTAL"] == (140707, 137211)
    assert got["Finland"]["TOTAL"] == (61436, 75029)


def test_september_monthly_table_is_unparseable_the_direct_way():
    """The case this whole fallback exists for: fetch_acea.py's own
    monthly-table parser (built for the post-April-2026 Word layout)
    cannot read this release at all."""
    import fetch_acea as fa
    try:
        parsed, _ = fa.parse_monthly_table(str(SEP), countries=bf.COUNTRIES)
    except Exception:
        parsed = {}
    assert not parsed


def test_derived_september_matches_the_two_ytd_tables():
    """2024-09 = Oct YTD − Sep YTD, both already fixtures — no network,
    unlike ytd_diff_month() which fetches live releases."""
    sep = bf.parse_ytd_markets_full(SEP, bf.COUNTRIES)
    oct_ = bf.parse_ytd_markets_full(OCT, bf.COUNTRIES)
    got = bf._ytd_subtract(oct_, sep)
    assert got["Denmark"]["TOTAL"] == (14409, 13231)
    assert got["Denmark"]["HEV"] == (2104, 1988)
    assert got["Finland"]["TOTAL"] == (5936, 6451)


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} tests passed")