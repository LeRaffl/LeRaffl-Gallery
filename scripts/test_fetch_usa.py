#!/usr/bin/env python3
"""Regression tests for scripts/fetch_usa.py (no network).

Run:  python scripts/test_fetch_usa.py

The ANL fetcher fails quietly: a shifted PDF column, a lost month or a row
that never gets revised again would go straight into the chart. These cases
pin the row parser against lines copied from the real "Total Sales for
Website" PDF (Aug-2026 release, text as pypdf extracts it), the sanity checks
(gap, negative, sum > total, total band, repeated values), the drift report
for rows outside the rewrite window, the upsert (OTHERS "" normalised to 0,
ICE derived), and one end-to-end offline run of main().
"""
import contextlib
import csv
import io
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_usa as fu  # noqa: E402

# Verbatim lines from the Aug-2026 PDF text layer (legend text trails the
# early rows; thousands separators; irregular spacing).
PDF_TEXT = """LDV Total Sales of PEV and HEV by Month (updated through August 2026)
Month BEV PHEV HEV Total LDV Note:
Dec-10 19 326          28,592     1,144,840      PEV Plug-in Elec
Jan-11 103 321          19,540     819,938         BEV Battery Elec
Jul-25 126,356 22,998 172,269 1,389,685
Aug-25 148,234 27,597 187,113 1,466,105
Sep-25 140,579 20,040 150,988 1,241,581
Oct-25 83,292 12,441 173,481 1,281,615
Nov-25 54,634 12,346 175,814 1,279,378
PEV Sales by Size (updated through August 2026)
Pickup 26,388 3.39%
Total 778,185 100.0%
"""

# The same release without the two early rows: a gap-free table for main().
RECENT_TEXT = "\n".join(l for l in PDF_TEXT.splitlines()
                         if not l.startswith(("Dec-10", "Jan-11")))


def _table(**over):
    t = {"2025-07": dict(BEV=126356, PHEV=22998, HEV=172269, TOTAL=1389685),
         "2025-08": dict(BEV=148234, PHEV=27597, HEV=187113, TOTAL=1466105),
         "2025-09": dict(BEV=140579, PHEV=20040, HEV=150988, TOTAL=1241581)}
    t.update(over)
    return t


def test_parse_real_lines():
    t = fu.parse_table(PDF_TEXT)
    assert sorted(t) == ["2010-12", "2011-01", "2025-07", "2025-08",
                         "2025-09", "2025-10", "2025-11"], sorted(t)
    assert t["2010-12"] == dict(BEV=19, PHEV=326, HEV=28592, TOTAL=1144840)
    assert t["2011-01"]["TOTAL"] == 819938          # legend text ignored
    assert t["2025-08"] == dict(BEV=148234, PHEV=27597, HEV=187113, TOTAL=1466105)
    assert "Pickup" not in str(t)                    # size box not parsed


def test_validate_clean_table():
    errors, warnings = fu.validate_table(_table())
    assert errors == [] and warnings == [], (errors, warnings)


def test_validate_gap():
    t = _table()
    del t["2025-08"]
    errors, _ = fu.validate_table(t)
    assert errors == ["2025-08: month missing from the PDF table (gap)"], errors


def test_validate_gap_across_year():
    t = {"2025-11": dict(BEV=1, PHEV=1, HEV=1, TOTAL=1_000_000),
         "2026-01": dict(BEV=1, PHEV=1, HEV=1, TOTAL=1_000_000)}
    errors, _ = fu.validate_table(t)
    assert errors == ["2025-12: month missing from the PDF table (gap)"], errors


def test_validate_sum_exceeds_total():
    errors, _ = fu.validate_table(_table(**{"2025-09": dict(
        BEV=900_000, PHEV=200_000, HEV=200_000, TOTAL=1_241_581)}))
    assert len(errors) == 1 and "exceeds Total LDV" in errors[0], errors


def test_validate_total_band():
    # A share or a YTD figure landing in the Total column must abort.
    errors, _ = fu.validate_table(_table(**{"2025-09": dict(
        BEV=1, PHEV=1, HEV=1, TOTAL=12_500_000)}))
    assert len(errors) == 1 and "outside" in errors[0], errors


def test_validate_negative():
    errors, _ = fu.validate_table(_table(**{"2025-09": dict(
        BEV=-5, PHEV=1, HEV=1, TOTAL=1_000_000)}))
    assert any("negative" in e for e in errors), errors


def test_validate_repeated_value_is_warning_only():
    t = _table(**{"2025-09": dict(BEV=140579, PHEV=20040, HEV=187113, TOTAL=1241581)})
    errors, warnings = fu.validate_table(t)
    assert errors == []
    assert warnings == ["2025-09: HEV identical to 2025-08 (187,113)"], warnings


def test_build_row_derives_ice_and_zero_others():
    r = fu.build_row("2025-08", _table()["2025-08"])
    assert r["OTHERS"] == 0.0
    assert r["ICE"] == 1466105 - 148234 - 27597 - 187113
    assert r["source"] == "ANL" and r["variant"] == "Whole"


def _write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fu.CSV_COLUMNS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return {r["period"]: r for r in csv.DictReader(f)}


def test_upsert_normalises_empty_others():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "USA.csv"
        row = fu.build_row("2025-11", dict(BEV=54634, PHEV=12346, HEV=175814,
                                           TOTAL=1279378))
        legacy = {k: str(v) for k, v in row.items()}
        legacy["OTHERS"] = ""
        _write_csv(p, [legacy])
        assert fu.upsert_window(str(p), {"2025-11": dict(row)}, False) == ["2025-11"]
        assert _read(p)["2025-11"]["OTHERS"] == "0.0"
        # second run is a no-op
        assert fu.upsert_window(str(p), {"2025-11": dict(row)}, False) == []


def test_drifted_rows_outside_window():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "USA.csv"
        t = _table()
        stale = fu.build_row("2025-08", dict(BEV=148769, PHEV=26004, HEV=150988,
                                             TOTAL=1467250))   # the pre-fix row
        _write_csv(p, [fu.build_row("2025-07", t["2025-07"]), stale,
                       fu.build_row("2025-09", t["2025-09"])])
        assert fu.drifted_rows(str(p), t, skip={"2025-09"}) == ["2025-08"]
        assert fu.drifted_rows(str(p), t, skip={"2025-08", "2025-09"}) == []


def _run_main(csv_path, *extra):
    argv = ["fetch_usa.py", "--pdf-url", "fixture.pdf", "--csv", str(csv_path),
            "--year", "2025", "--month", "11", *extra]
    with mock.patch.object(fu, "load_pdf_bytes", return_value=b""), \
         mock.patch.object(fu, "pdf_text", return_value=RECENT_TEXT), \
         mock.patch.object(sys, "argv", argv), \
         contextlib.redirect_stdout(io.StringIO()):
        return fu.main()


def test_main_end_to_end_window_and_full_refresh():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "USA.csv"
        assert _run_main(p) == 0                         # default: last 3 months
        assert sorted(_read(p)) == ["2025-09", "2025-10", "2025-11"]
        assert _run_main(p, "--months", "0") == 0        # full history
        rows = _read(p)
        assert sorted(rows) == ["2025-07", "2025-08", "2025-09", "2025-10",
                                "2025-11"]
        for r in rows.values():
            tot = float(r["TOTAL"])
            parts = sum(float(r[k]) for k in ("BEV", "PHEV", "HEV", "OTHERS", "ICE"))
            assert parts == tot, r


def test_main_aborts_on_gap_without_writing():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "USA.csv"
        broken = RECENT_TEXT.replace("Aug-25 148,234 27,597 187,113 1,466,105\n", "")
        argv = ["fetch_usa.py", "--pdf-url", "x.pdf", "--csv", str(p),
                "--year", "2025", "--month", "11"]
        with mock.patch.object(fu, "load_pdf_bytes", return_value=b""), \
             mock.patch.object(fu, "pdf_text", return_value=broken), \
             mock.patch.object(sys, "argv", argv), \
             contextlib.redirect_stdout(io.StringIO()):
            try:
                fu.main()
                raise AssertionError("expected SystemExit")
            except SystemExit as e:
                assert "sanity" in str(e.code)
        assert not p.exists()


def test_repo_csv_is_consistent():
    p = Path(__file__).resolve().parent.parent / "data" / "USA.csv"
    rows = _read(p)
    periods = sorted(rows)
    cur = periods[0]
    for nxt in periods[1:]:
        cur = fu._next_period(cur)
        assert cur == nxt, f"gap before {nxt}"
    for r in rows.values():
        assert r["OTHERS"] not in ("", None), r["period"]
        parts = sum(float(r[k]) for k in ("BEV", "PHEV", "HEV", "OTHERS", "ICE"))
        assert parts == float(r["TOTAL"]), r["period"]


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
