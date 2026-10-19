#!/usr/bin/env python3
"""Regression tests for scripts/fetch_acea.py (no network).

Run:  python scripts/test_fetch_acea.py

acea.auto answers a release that isn't out yet with a 404, a 403 or an HTML
page served as HTTP 200, depending on the day (issue #244, module docstring
"What a download can return"). These cases pin how each answer is
classified, when waiting for the release turns into a failed run, that a
non-PDF page never reaches pdfplumber, and the parser against the two real
releases in scripts/fixtures/ (March 2026: old generator, April 2026:
Word export).
"""
import contextlib
import csv
import io
import sys
import tempfile
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_acea as fa  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
URL = "https://www.acea.auto/files/Press_release_car_registrations_September_2026.pdf"
HTML = b"<!DOCTYPE html>\n<html><head><title>ACEA</title></head><body></body></html>"


def quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


def raises(exc, fn, *a, **k):
    try:
        quiet(fn, *a, **k)
    except exc as e:
        return e
    raise AssertionError(f"{fn.__name__} did not raise {exc.__name__}")


class FakeResponse:
    def __init__(self, status, content=b"", headers=None):
        self.status_code = status
        self.content = content
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Server Error")


@contextlib.contextmanager
def acea_answers(resp):
    """Every GET (homepage warmup and PDF) returns `resp`."""
    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout=None):
            return resp

    real = requests.Session
    requests.Session = FakeSession
    try:
        yield
    finally:
        requests.Session = real


def scratch_csv(d, country, periods):
    with open(Path(d) / f"{country}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(fa.STANDARD_CSV_COLUMNS)
        for p, src in periods:
            w.writerow([p, "monthly", "Whole", src, 1, 1, 1, 1, 1, 0, 5, ""])


def test_download_classification():
    with acea_answers(FakeResponse(200, b"%PDF-1.7\n...", {"content-type": "application/pdf"})):
        assert quiet(fa.load_pdf_bytes, URL).startswith(b"%PDF-")
    with acea_answers(FakeResponse(404)):
        e = raises(FileNotFoundError, fa.load_pdf_bytes, URL)
        assert not isinstance(e, fa.NotAPDF)
    # The #244 page: HTTP 200, HTML body. Must never reach pdfplumber.
    with acea_answers(FakeResponse(200, HTML, {"content-type": "text/html; charset=UTF-8"})):
        e = raises(fa.NotAPDF, fa.load_pdf_bytes, URL)
        assert isinstance(e, FileNotFoundError)
        assert "text/html" in str(e) and "DOCTYPE" in str(e)
    with acea_answers(FakeResponse(403)):
        assert raises(fa.PDFAccessDenied, fa.load_pdf_bytes, URL).allowlist is False
    with acea_answers(FakeResponse(403, headers={"x-deny-reason": "host_not_allowed"})):
        assert raises(fa.PDFAccessDenied, fa.load_pdf_bytes, URL).allowlist is True
    with acea_answers(FakeResponse(520, HTML)):
        raises(requests.HTTPError, fa.load_pdf_bytes, URL)


def test_wait_or_fail():
    not_a_pdf = fa.NotAPDF("200 but no PDF")
    with tempfile.TemporaryDirectory() as d:
        dd = Path(d)
        scratch_csv(d, "Bulgaria", [("2026-07", "ACEA"), ("2026-08", "ACEA")])
        ru = fa.release_unavailable
        # Before the overdue day: every "not there" answer waits.
        for err in (not_a_pdf, FileNotFoundError("404"), fa.PDFAccessDenied("403"),
                    requests.ConnectionError("reset")):
            assert quiet(ru, err, dd, "2026-09", True, date(2026, 10, 18)) == 0
            assert quiet(ru, err, dd, "2026-09", True, date(2026, 10, 27)) == 0
        # From the overdue day on, the same answer fails the run.
        e = raises(SystemExit, ru, not_a_pdf, dd, "2026-09", True, date(2026, 10, 28))
        assert "2026-09" in str(e.code) and "2026-10-28" in str(e.code)
        raises(SystemExit, ru, fa.PDFAccessDenied("403"), dd, "2026-09", True, date(2026, 11, 2))
        # An IP allowlist block fails at once.
        deny = fa.PDFAccessDenied("403 host_not_allowed", allowlist=True)
        raises(SystemExit, ru, deny, dd, "2026-09", True, date(2026, 10, 16))
        # December's release is due in January of the next year.
        assert quiet(ru, not_a_pdf, dd, "2026-12", False, date(2027, 1, 27)) == 0
        raises(SystemExit, ru, not_a_pdf, dd, "2026-12", False, date(2027, 1, 28))
        # The month before the target never landed: a scheduled run names it ...
        e = raises(SystemExit, ru, not_a_pdf, dd, "2026-10", True, date(2026, 11, 18))
        assert "2026-09" in str(e.code)
        # ... a manual run for one month doesn't judge the month before it.
        assert quiet(ru, not_a_pdf, dd, "2026-10", False, date(2026, 11, 18)) == 0
        # Only an ACEA row counts as landed (Czechia's register writes first).
        scratch_csv(d, "Czechia", [("2026-09", "RSV")])
        raises(SystemExit, ru, not_a_pdf, dd, "2026-10", True, date(2026, 11, 18))
        scratch_csv(d, "Czechia", [("2026-09", "ACEA")])
        assert quiet(ru, not_a_pdf, dd, "2026-10", True, date(2026, 11, 18)) == 0


def test_prev_month_period():
    assert fa.prev_month_period("2026-10") == "2026-09"
    assert fa.prev_month_period("2026-01") == "2025-12"


def run_main(argv, resp):
    """fetch_acea.main() with `argv`, every HTTP GET answered by `resp`."""
    real_argv = sys.argv
    sys.argv = ["fetch_acea.py", *argv]
    try:
        with acea_answers(resp):
            return quiet(fa.main)
    finally:
        sys.argv = real_argv


def test_main_does_not_crash_on_the_244_page():
    with tempfile.TemporaryDirectory() as d:
        scratch_csv(d, "Bulgaria", [("2098-12", "ACEA")])
        before = (Path(d) / "Bulgaria.csv").read_bytes()
        # A month far ahead is never overdue, so this is the "wait" path.
        page = FakeResponse(200, HTML, {"content-type": "text/html"})
        assert run_main(["--year", "2099", "--month", "1", "--data-dir", d], page) == 0
        assert (Path(d) / "Bulgaria.csv").read_bytes() == before


def test_main_fails_loudly_on_a_broken_pdf():
    with tempfile.TemporaryDirectory() as d:
        broken = FakeResponse(200, b"%PDF-1.7\nnot really a pdf\n")
        e = raises(SystemExit, run_main,
                   ["--year", "2099", "--month", "1", "--data-dir", d, "--force"], broken)
        assert "pdfplumber cannot open" in str(e.code)


def test_parse_fixtures():
    for month, bulgaria in (
        ("March", {"BEV": (349, 217), "PHEV": (82, 39), "HEV": (231, 112), "OTHERS": (0, 0),
                   "PETROL": (3310, 3436), "DIESEL": (509, 416), "TOTAL": (4481, 4220)}),
        ("April", {"BEV": (456, 144), "PHEV": (83, 38), "HEV": (284, 176), "OTHERS": (4, 3),
                   "PETROL": (3356, 3124), "DIESEL": (559, 522), "TOTAL": (4742, 4007)}),
    ):
        pdf = FIX / f"Press_release_car_registrations_{month}_2026.pdf"
        parsed, label = quiet(fa.parse_monthly_table, str(pdf))
        assert label == f"{month} 2026", label
        assert set(parsed) == set(fa.ALL_COUNTRIES), set(fa.ALL_COUNTRIES) - set(parsed)
        assert parsed["Bulgaria"] == bulgaria, parsed["Bulgaria"]
        for country, v in parsed.items():
            if country == "Malta":
                continue  # ACEA's own Malta row is off by one (see main())
            for i in (0, 1):
                parts = sum(v[k][i] for k in ("BEV", "PHEV", "HEV", "OTHERS", "PETROL", "DIESEL"))
                assert parts == v["TOTAL"][i], (month, country, i)


def main():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} passed")


if __name__ == "__main__":
    main()
