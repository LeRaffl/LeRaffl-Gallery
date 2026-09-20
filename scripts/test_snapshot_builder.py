#!/usr/bin/env python3
"""Regression tests for scripts/snapshot_builder.py (no network, no I/O).

Run:  python scripts/test_snapshot_builder.py

Guards the mirror against index.html. The script exists only to reproduce the
in-page Builder; every drift between the two has been an off-by-one year that
nothing catches until someone compares a snapshot with the live chart.

Covers:
- #219: an absent `baseline_year` column must not read as "baseline year 0".
  Production params.csv has no such column, so `norm_number('') == 0.0` used to
  send `get_t0_years()` down the baseline branch and return `t0 + 1`.
- the baseline branches still working when a baseline IS present, so the fix
  above did not simply delete the feature;
- `baseline_year_of()` staying out of the finiteness gate — it is NaN for every
  production row, and gating on it would silently empty every snapshot;
- `normalize_base()` agreeing with `normalizeBase()` in index.html, including
  the 'bus' -> 'buses' mapping the page gained in #218.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import snapshot_builder as sb  # noqa: E402

# Shape of a live params.csv row: `baseline_date` present but empty, and no
# `baseline_year` key at all. This is what every production row looks like.
PROD_ROW = {
    "country": "Testland", "variant": "Whole",
    "v1": "-0.01", "v2": "3.0", "t0": "2019",
    "baseline_date": "", "data_per": "2026-08",
}


def test_absent_baseline_is_not_year_zero():
    """#219: the whole bug in one assertion."""
    assert sb.get_t0_years(PROD_ROW) == 2019.0, sb.get_t0_years(PROD_ROW)
    # ...and the raw helper still has the JS quirk it mirrors, so the guard
    # (not a change to norm_number) is what does the work.
    assert sb.norm_number(None) == 0.0
    assert sb.norm_number("") == 0.0
    assert math.isnan(sb.calendar_year_or_nan(""))
    assert math.isnan(sb.calendar_year_or_nan(None))
    assert math.isnan(sb.calendar_year_or_nan(0))
    assert sb.calendar_year_or_nan("2019") == 2019.0


def test_baseline_branches_still_work():
    """A row that really carries a baseline must still be indexed off it."""
    assert sb.get_t0_years({**PROD_ROW, "baseline_year": "2015"}) == 5.0
    assert sb.get_t0_years({**PROD_ROW, "baseline_date": "2015-01-01"}) == 5.0
    # ISO t0 against an ISO baseline -> fractional index year
    got = sb.get_t0_years({**PROD_ROW, "t0": "2019-07-01", "baseline_date": "2015-01-01"})
    assert abs(got - 5.4959) < 1e-3, got


def test_unparseable_t0_is_nan():
    for bad in ("", "abc", None):
        assert math.isnan(sb.get_t0_years({**PROD_ROW, "t0": bad})), bad


def test_baseline_year_of_is_nan_in_production():
    """Must be NaN, and must therefore stay out of compute_group_curve's gate.

    If a future edit puts it back into that gate, every production row is
    dropped and the snapshot comes out empty rather than wrong — which is why
    the gate is asserted here too, not just the NaN.
    """
    assert math.isnan(sb.baseline_year_of(PROD_ROW))
    assert sb.baseline_year_of({**PROD_ROW, "baseline_year": "2015"}) == 2015
    assert sb.baseline_year_of({**PROD_ROW, "baseline_date": "2015-01-01"}) == 2015

    weights = {"Testland|whole": 1000.0}
    xs, bev, _ice, _phev, meta = sb.compute_group_curve(["Testland"], [dict(PROD_ROW)], weights)
    assert meta["n_countries"] == 1, meta
    assert any(v > 0 for v in bev), "production row produced an all-zero curve"


def test_curve_is_on_the_calendar_basis():
    """z = year - t0, not year - t0 - 1. Anchors the #219 fix numerically."""
    row = dict(PROD_ROW)  # v1=-0.01, v2=3, t0=2019
    weights = {"Testland|whole": 1.0}
    xs, bev, _i, _p, _m = sb.compute_group_curve(["Testland"], [row], weights)
    at = dict(zip((round(x, 1) for x in xs), bev))
    # At t0 exactly the curve must sit at 0; one year past t0, z = 1.
    assert at[2019.0] == 0.0, at[2019.0]
    expected = 100.0 * (1 - math.exp(-0.01 * 1 ** 3))
    assert abs(at[2020.0] - expected) < 1e-9, (at[2020.0], expected)


def test_normalize_base_matches_the_page():
    cases = {
        "Whole": "whole", "all": "whole", "Total Market": "whole",
        "HDV": "hdv", "Trucks": "hdv", "heavy-duty": "hdv",
        "bus": "buses", "Buses": "buses", "BUS": "buses",   # #218 mapping
        "Vans": "vans", "Private": "private", "": "",
    }
    for raw, want in cases.items():
        got = sb.normalize_base(raw)
        assert got == want, f"{raw!r} -> {got!r}, want {want!r}"


def test_snapshot_entries_are_basis_stamped():
    """index.json must keep basis_history and stamp every new entry (#219)."""
    import json
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "index.json"
        p.write_text(json.dumps({
            "basis_history": [{"basis": sb.LEGACY_CURVE_BASIS, "through": "2026-09-09"}],
            "snapshots": [{"date": "2026-09-09", "file": "2026-09-09.csv",
                           "basis": sb.LEGACY_CURVE_BASIS, "groups": {}}],
            "updated": "2026-09-09",
        }), encoding="utf-8")

        sb.update_index_json(p, "2026-10-01", "2026-10-01.csv", {"world": {"n_countries": 1}})
        out = json.loads(p.read_text(encoding="utf-8"))

    assert "basis_history" in out, "update_index_json dropped basis_history"
    assert [s["date"] for s in out["snapshots"]] == ["2026-09-09", "2026-10-01"]
    assert out["snapshots"][0]["basis"] == sb.LEGACY_CURVE_BASIS, "rewrote history"
    assert out["snapshots"][-1]["basis"] == sb.CURVE_BASIS
    assert out["updated"] == "2026-10-01"


def main() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} tests passed")


if __name__ == "__main__":
    main()
