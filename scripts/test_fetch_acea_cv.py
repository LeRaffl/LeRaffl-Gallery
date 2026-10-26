#!/usr/bin/env python3
"""Regression tests for scripts/fetch_acea_cv.py (no network).

Run:  python scripts/test_fetch_acea_cv.py

The release URL changes shape from year to year, so the fetcher walks a list
of candidate URLs. acea.auto answers a candidate that doesn't exist with a
404 on some days and a 520 on others; on 2026-10-24 a 520 on the first Q1-Q3
guess failed the run before the third guess (the shape confirmed in 2025)
was tried. These cases pin that every "not this URL" answer falls through to
the next candidate, and that a release that isn't out yet is a green no-op.

Quarters are reconstructed as `checkpoint - quarters on record`, and ACEA
restates fuels between releases, so a fuel can come out negative (#355:
29 cells in 17 files). The carry-back cases pin that no negative is
written, every row still sums, and every year-to-date sum stays ACEA's.
"""
import contextlib
import io
import sys
import tempfile
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_acea_cv as fc  # noqa: E402

PDF = b"%PDF-1.7\n..."


def quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


class FakeResponse:
    def __init__(self, status, content=b""):
        self.status_code = status
        self.content = content
        self.headers = {"content-type": "application/pdf" if content == PDF else "text/html"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Server Error")


@contextlib.contextmanager
def acea_answers(by_url, default):
    """GET url -> by_url.get(url, default) (homepage warmup included)."""
    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout=None):
            return by_url.get(url, default)

    real = requests.Session
    requests.Session = FakeSession
    try:
        yield
    finally:
        requests.Session = real


def candidates(checkpoint, year):
    return [t.format(year=year) for t in fc.CANDIDATE_URL_TEMPLATES_BY_CHECKPOINT[checkpoint]]


def test_a_520_falls_through_to_the_next_candidate():
    urls = candidates("Q1-Q3", 2026)
    answers = {urls[0]: FakeResponse(520), urls[1]: FakeResponse(404), urls[2]: FakeResponse(200, PDF)}
    with acea_answers(answers, FakeResponse(404)):
        pdf, url = quiet(fc.fetch_checkpoint_pdf, "Q1-Q3", 2026, None)
    assert pdf == PDF and url == urls[2], url


def test_nothing_published_is_not_found():
    for default in (FakeResponse(404), FakeResponse(520), FakeResponse(200, b"<html></html>")):
        with acea_answers({}, default):
            try:
                quiet(fc.fetch_checkpoint_pdf, "Q1-Q3", 2026, None)
            except FileNotFoundError:
                continue
        raise AssertionError(f"HTTP {default.status_code} everywhere did not end as not-found")


def test_main_waits_green_when_the_release_is_not_out():
    real_argv = sys.argv
    with tempfile.TemporaryDirectory() as d:
        sys.argv = ["fetch_acea_cv.py", "--checkpoint", "Q1-Q3", "--year", "2026", "--data-dir", d]
        try:
            with acea_answers({}, FakeResponse(520)):
                assert quiet(fc.main) == 0
            # A 520 on an explicit --pdf-url (a URL, so no candidate walk) too.
            sys.argv += ["--pdf-url", candidates("Q1-Q3", 2026)[2]]
            with acea_answers({}, FakeResponse(503)):
                assert quiet(fc.main) == 0
        finally:
            sys.argv = real_argv


HEADER = "period,time_interval,variant,source,BEV,PHEV,HEV,PETROL,DIESEL,OTHERS,TOTAL,notes"
FUELS = ("BEV", "HEV", "PETROL", "DIESEL", "OTHERS")


def acea_row(period, bev, hev, petrol, diesel, others, total, variant="Buses", source="ACEA"):
    return (f"{period},quarterly,{variant},{source},{bev},,{hev},{petrol},{diesel},"
            f"{others},{total},https://example/{period}.pdf")


def read_rows(path):
    import csv
    with open(path, newline="", encoding="utf-8") as f:
        return {r["period"]: r for r in csv.DictReader(f)}


def ytd(rows, year, upto):
    months = ("02", "05", "08", "11")[:upto]
    return {f: sum(float(rows[f"{year}-{m}"][f] or 0) for m in months) for f in FUELS + ("TOTAL",)}


def assert_clean(rows):
    for p, r in rows.items():
        vals = {f: float(r[f]) for f in FUELS + ("TOTAL",) if r[f] not in ("", None)}
        assert all(v >= 0 for v in vals.values()), (p, vals)
        assert abs(sum(v for f, v in vals.items() if f != "TOTAL") - vals["TOTAL"]) < 0.5, (p, vals)


def test_carry_back_cyprus_buses_2023():
    # Q3 had BEV 19 / HEV 21; the FY release restates them into petrol/diesel.
    q3 = {"period": "2023-08", "source": "ACEA", "BEV": "19.0", "HEV": "21.0",
          "PETROL": "0.0", "DIESEL": "45.0", "OTHERS": "0.0", "TOTAL": "85.0", "notes": "u"}
    delta = {"BEV": -19.0, "HEV": -21.0, "PETROL": 26.0, "DIESEL": 27.0, "OTHERS": 0.0, "TOTAL": 13.0}
    delta, revised, moves = fc.carry_back_deficits(delta, {3: q3}, 4)
    assert delta == {"BEV": 0.0, "HEV": 0.0, "PETROL": 26.0, "DIESEL": 27.0, "OTHERS": 0.0,
                     "TOTAL": 53.0}, delta
    r = revised[3]
    assert (r["BEV"], r["HEV"], r["TOTAL"]) == (0.0, 0.0, 45.0), r
    assert moves == [("BEV", 3, 19.0), ("HEV", 3, 21.0)], moves
    assert "moved to Q4" in r["notes"] and q3["TOTAL"] == "85.0"   # input not mutated


def test_carry_back_reaches_further_back_and_keeps_number_style():
    q1 = {"source": "ACEA", "BEV": "5", "TOTAL": "100"}
    q2 = {"source": "ACEA", "BEV": "3", "TOTAL": "100"}
    delta, revised, moves = fc.carry_back_deficits({"BEV": -6.0, "TOTAL": 50.0}, {1: q1, 2: q2}, 3)
    assert delta == {"BEV": 0.0, "TOTAL": 56.0}, delta
    assert (revised[2]["BEV"], revised[2]["TOTAL"]) == ("0", "97"), revised[2]
    assert (revised[1]["BEV"], revised[1]["TOTAL"]) == ("2", "97"), revised[1]
    assert moves == [("BEV", 2, 3.0), ("BEV", 1, 3.0)], moves


def test_carry_back_never_touches_another_sources_row():
    q1 = {"source": "PZPM", "BEV": "10", "TOTAL": "100"}
    assert fc.carry_back_deficits({"BEV": -4.0, "TOTAL": 20.0}, {1: q1}, 2) is None
    # nothing negative: nothing to do
    assert fc.carry_back_deficits({"BEV": 4.0, "TOTAL": 20.0}, {1: q1}, 2) == (
        {"BEV": 4.0, "TOTAL": 20.0}, {}, [])


def test_handle_checkpoint_writes_no_negative_and_keeps_acea_ytd():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "Cyprus_Buses.csv"
        path.write_text("\n".join([
            HEADER,
            acea_row("2023-02", "0.0", "0.0", "0.0", "14.0", "0.0", "14.0"),
            acea_row("2023-05", "0.0", "0.0", "0.0", "140.0", "0.0", "140.0"),
            acea_row("2023-08", "19.0", "21.0", "0.0", "45.0", "0.0", "85.0"),
        ]) + "\n", encoding="utf-8")
        fy = {"BEV": 0.0, "HEV": 0.0, "PETROL": 26.0, "DIESEL": 226.0, "OTHERS": 0.0, "TOTAL": 252.0}
        assert quiet(fc.handle_checkpoint, Path(d), "Cyprus", "Buses", 2023, 4, fy,
                     "https://example/fy.pdf", "new")
        rows = read_rows(path)
        assert_clean(rows)
        assert ytd(rows, 2023, 4) == fy, ytd(rows, 2023, 4)
        assert ytd(rows, 2023, 2) == {"BEV": 0, "HEV": 0, "PETROL": 0, "DIESEL": 154, "OTHERS": 0,
                                      "TOTAL": 154}                      # H1 untouched
        assert float(rows["2023-08"]["TOTAL"]) == 45 and float(rows["2023-11"]["TOTAL"]) == 53
        assert "restatement carried back" in rows["2023-11"]["notes"]
        # Re-running the same release changes nothing.
        assert not quiet(fc.handle_checkpoint, Path(d), "Cyprus", "Buses", 2023, 4, fy,
                         "https://example/fy.pdf", "new")


def test_repair_fixes_existing_negatives_and_nothing_else():
    with tempfile.TemporaryDirectory() as d:
        bad = Path(d) / "France_HDV.csv"
        bad.write_text("\r\n".join([
            HEADER,
            acea_row("2023-02", "403.0", "0.0", "0.0", "11086.0", "809.0", "12298.0", "HDV"),
            acea_row("2023-05", "-208.0", "0.0", "0.0", "13573.0", "995.0", "14360.0", "HDV"),
            acea_row("2023-08", "107.0", "0.0", "5.0", "10810.0", "719.0", "11641.0", "HDV"),
        ]) + "\r\n", encoding="utf-8")
        before = read_rows(bad)
        clean = Path(d) / "Sweden_Vans.csv"
        clean_text = HEADER + "\n" + acea_row("2024-05", "1", "2", "3", "4", "5", "15", "Vans") + "\n"
        clean.write_text(clean_text, encoding="utf-8")
        legacy = Path(d) / "Belgium_legacy.csv"
        legacy_text = HEADER + "\n" + acea_row("2023-05", "-1.0", "0", "0", "2", "0", "1", "HDV") + "\n"
        legacy.write_text(legacy_text, encoding="utf-8")

        pairs = quiet(fc.repair_negative_quarters, Path(d))
        assert pairs == [{"country": "France", "variant": "HDV"}], pairs
        rows = read_rows(bad)
        assert_clean(rows)
        assert ytd(rows, 2023, 3) == ytd(before, 2023, 3)
        assert (rows["2023-02"]["BEV"], rows["2023-02"]["TOTAL"]) == ("195.0", "12090.0")
        assert (rows["2023-05"]["BEV"], rows["2023-05"]["TOTAL"]) == ("0.0", "14568.0")
        assert rows["2023-08"] == before["2023-08"]                       # untouched row
        assert b"\r\n" in bad.read_bytes()                                 # line endings kept
        assert clean.read_text(encoding="utf-8") == clean_text            # no negatives: untouched
        assert legacy.read_text(encoding="utf-8") == legacy_text          # archives are frozen


def main():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} passed")


if __name__ == "__main__":
    main()
