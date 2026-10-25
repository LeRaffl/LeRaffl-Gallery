#!/usr/bin/env python3
"""Regression tests for scripts/fetch_acea_cv.py (no network).

Run:  python scripts/test_fetch_acea_cv.py

The release URL changes shape from year to year, so the fetcher walks a list
of candidate URLs. acea.auto answers a candidate that doesn't exist with a
404 on some days and a 520 on others; on 2026-10-24 a 520 on the first Q1-Q3
guess failed the run before the third guess (the shape confirmed in 2025)
was tried. These cases pin that every "not this URL" answer falls through to
the next candidate, and that a release that isn't out yet is a green no-op.
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


def main():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} passed")


if __name__ == "__main__":
    main()
