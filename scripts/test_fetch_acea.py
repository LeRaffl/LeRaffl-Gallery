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
        assert set(parsed) == set(fa.ALL_COUNTRIES + fa.SPLIT_ONLY_COUNTRIES), \
            set(fa.ALL_COUNTRIES + fa.SPLIT_ONLY_COUNTRIES) - set(parsed)
        assert parsed["Bulgaria"] == bulgaria, parsed["Bulgaria"]
        for country, v in parsed.items():
            if country == "Malta":
                continue  # ACEA's own Malta row is off by one (see main())
            for i in (0, 1):
                parts = sum(v[k][i] for k in ("BEV", "PHEV", "HEV", "OTHERS", "PETROL", "DIESEL"))
                assert parts == v["TOTAL"][i], (month, country, i)


def test_eu_ytd_row():
    april = FIX / "Press_release_car_registrations_April_2026.pdf"
    units, label = quiet(fa.parse_eu_ytd, str(april))
    assert label == "Jan-Apr", label
    assert units == {"BEV": 746899, "PHEV": 364067, "HEV": 1447864, "OTHERS": 87970,
                     "PETROL": 854843, "DIESEL": 292637, "TOTAL": 3794280}, units
    assert fa.release_date(str(april)) == "2026-05-27"
    # March 2026 draws the year-to-date table as rotated glyphs: pdfplumber
    # has no line for the row, poppler's pdftotext -layout does. Without
    # pdftotext: no guess, no write.
    import shutil
    march = quiet(fa.parse_eu_rows, str(FIX / "Press_release_car_registrations_March_2026.pdf"))
    assert march["month"]["TOTAL"] == 1158316 and march["month_method"] == "pdfplumber text"
    if shutil.which("pdftotext"):
        assert march["ytd_method"] == "pdftotext -layout", march
        assert march["ytd"] == {"BEV": 546937, "PHEV": 268344, "HEV": 1089421, "OTHERS": 62848,
                                "PETROL": 636502, "DIESEL": 218565, "TOTAL": 2822616}
        assert march["ytd_label"] == "Jan-Mar"
    else:
        assert "ytd" not in march

    url = "https://www.acea.auto/files/Press_release_car_registrations_April_2026.pdf"
    row = fa.eu_reference_row(units, "2026-04", url, "ab" * 32, date(2026, 5, 28), "2026-05-27")
    assert (row["period_from"], row["period_to"], row["scope"]) == ("2026-01", "2026-04", "EU")
    assert (row["BEV_share"], row["PHEV_share"], row["HEV_share"]) == ("19.7", "9.6", "38.2"), row
    # Parts that do not add up to TOTAL are refused.
    assert fa.eu_reference_row({**units, "TOTAL": 1000}, "2026-04", url, "", date(2026, 5, 28)) is None

    with tempfile.TemporaryDirectory() as d:
        ref = Path(d) / "acea_eu_shares.csv"
        assert not fa.eu_reference_has(ref, "2026-04")
        assert fa.update_eu_reference(ref, row)
        first = ref.read_bytes()
        assert fa.eu_reference_has(ref, "2026-04")
        # A re-run a day later with the same units leaves the bytes alone.
        again = fa.eu_reference_row(units, "2026-04", url, "ab" * 32, date(2026, 5, 29), "2026-05-27")
        assert not fa.update_eu_reference(ref, again)
        assert ref.read_bytes() == first
        # A later month is added, older rows keep their bytes.
        may = fa.eu_reference_row({k: v * 2 for k, v in units.items()}, "2026-05", url,
                                  "cd" * 32, date(2026, 6, 25), "2026-06-24")
        assert fa.update_eu_reference(ref, may)
        lines = ref.read_text().splitlines()
        assert lines[0] == ",".join(fa.EU_REFERENCE_FIELDS)
        assert lines[1] == first.decode().splitlines()[1]
        assert lines[2].startswith("2026-01,2026-05,EU,")
        # A revised figure for the same month replaces that row only.
        rev = fa.eu_reference_row({**units, "OTHERS": units["OTHERS"] + 10,
                                   "TOTAL": units["TOTAL"] + 10},
                                  "2026-04", url, "ef" * 32, date(2026, 6, 25))
        assert fa.update_eu_reference(ref, rev)
        rows = list(csv.DictReader(ref.open()))
        assert [r["period_to"] for r in rows] == ["2026-04", "2026-05"]
        assert rows[0]["TOTAL_units"] == str(units["TOTAL"] + 10)
        assert rows[0]["published"] == "2026-05-27"


def _ytd(period, total, hev, src="u"):
    units = {"BEV": total // 5, "PHEV": total // 10, "HEV": hev, "OTHERS": 0,
             "DIESEL": total // 10}
    units["PETROL"] = total - sum(units.values())
    units["TOTAL"] = total
    r = {"scope": "EU", "period_to": period, "source_url": src}
    r.update({f"{k}_units": str(v) for k, v in units.items()})
    return r


def test_eu_month_rows_from_ytd_differences():
    ytd = [_ytd("2026-01", 100, 30, "jan"), _ytd("2026-02", 210, 66, "feb"),
           _ytd("2026-06", 600, 200, "jun"), _ytd("2026-08", 800, 260, "aug")]
    (jan,) = fa.eu_month_rows(ytd, "2026-01")
    assert (jan["method"], jan["HEV_units"], jan["TOTAL_units"]) == ("ytd_january", "30", "100")
    (feb,) = fa.eu_month_rows(ytd, "2026-02", {"HEV": 35, "TOTAL": 111})
    assert (feb["method"], feb["HEV_units"], feb["TOTAL_units"]) == ("ytd_diff", "36", "110")
    assert (feb["source_url"], feb["minus_source_url"]) == ("feb", "jan")
    assert (feb["table_HEV_units"], feb["table_TOTAL_units"]) == ("35", "111")
    # No July release (summer break): August from its own monthly table,
    # July = YTD(Aug) − YTD(Jun) − August, so July + August stay exact.
    aug_table = {"BEV": 20, "PHEV": 10, "HEV": 25, "OTHERS": 0, "PETROL": 35,
                 "DIESEL": 10, "TOTAL": 100}
    jul, aug = fa.eu_month_rows(ytd, "2026-08", aug_table)
    assert (jul["period"], jul["method"], jul["HEV_units"], jul["TOTAL_units"]) == \
        ("2026-07", "ytd_diff_less_next_month", "35", "100")
    assert (aug["period"], aug["method"], aug["HEV_units"]) == ("2026-08", "monthly_table", "25")
    # Without the monthly table, or two releases missing: nothing, not a guess.
    assert fa.eu_month_rows(ytd, "2026-08") == []
    assert fa.eu_month_rows(ytd, "2026-06") == []
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "m.csv"
        assert fa.update_eu_monthly(path, [jan, feb])
        first = path.read_bytes()
        assert not fa.update_eu_monthly(path, [feb])
        assert path.read_bytes() == first
        assert fa.update_eu_monthly(path, [jul, aug])
        assert [r["period"] for r in csv.DictReader(path.open())] == \
            ["2026-01", "2026-02", "2026-07", "2026-08"]


def test_repo_eu_monthly_matches_ytd_file():
    # The committed monthly file is exactly what the YTD rows give, and the
    # months of each year add up to that year's latest year-to-date row.
    root = Path(__file__).resolve().parent.parent / "reference"
    ytd = list(csv.DictReader((root / "acea_eu_shares.csv").open(encoding="utf-8")))
    months = {r["period"]: r for r in csv.DictReader((root / "acea_eu_monthly.csv").open(encoding="utf-8"))}
    for r in ytd:
        for want in fa.eu_month_rows(ytd, r["period_to"]):
            got = months[want["period"]]
            for f in fa.EU_FUELS:
                assert got[f"{f}_units"] == want[f"{f}_units"], (want["period"], f)
    for r in ytd:
        y = r["period_to"][:4]
        ms = [m for p, m in months.items() if p[:4] == y and p <= r["period_to"]]
        if len(ms) == int(r["period_to"][5:]):
            for f in fa.EU_FUELS:
                assert sum(int(m[f"{f}_units"]) for m in ms) == int(r[f"{f}_units"]), (r["period_to"], f)


def test_repo_eu_reference_file():
    # The committed file has the header main() writes, so the first
    # automatic run does not rewrite the rows it already has.
    ref = Path(__file__).resolve().parent.parent / "reference" / "acea_eu_shares.csv"
    with ref.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == fa.EU_REFERENCE_FIELDS, reader.fieldnames
        rows = list(reader)
    assert rows and all(r["scope"] == "EU" for r in rows)
    for r in rows:
        total = int(r["TOTAL_units"])
        for k in ("BEV", "PHEV", "HEV"):
            assert r[f"{k}_share"] == f"{100 * int(r[f'{k}_units']) / total:.1f}", (r, k)
        assert r["source_url"].startswith("https://www.acea.auto/files/"), r["source_url"]


def main():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} passed")


# --- SPLIT_ONLY countries (Denmark/Finland, Greece pattern) ----------------

_SPLIT_FIELDS = ["period", "time_interval", "variant", "source", "BEV", "PHEV",
                 "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL", "notes"]
_SPLIT_PARSED = {"BEV": (17784, 15000), "PHEV": (23, 400), "HEV": (1427, 900),
                 "OTHERS": (46, 30), "PETROL": (515, 2500), "DIESEL": (276, 700),
                 "TOTAL": (20025, 19000)}


def _split_csv(tmp, country, source, total=20063.0, bev=17777.0, phev=22.0,
               petrol=1665.0, diesel=599.0, header_only=False):
    p = Path(tmp) / f"{country}.csv"
    with p.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=_SPLIT_FIELDS)
        w.writeheader()
        if not header_only:
            w.writerow({"period": "2026-09", "time_interval": "monthly",
                        "variant": "Whole", "source": source, "BEV": str(bev),
                        "PHEV": str(phev), "HEV": "", "PETROL": str(petrol),
                        "DIESEL": str(diesel), "OTHERS": "", "TOTAL": str(total),
                        "notes": "https://example.org/national"})
    return p


def test_split_only_merges_acea_split_onto_national_row():
    """Denmark's merge mode: HEV is ACEA's count; petrol/diesel ratio-scale
    the national combustion residual (TOTAL-BEV-PHEV-OTHERS-HEV) by ACEA's
    own petrol:diesel ratio, because statbank BIL53 and ACEA revise the
    same register independently and the strict counted-split gate (used
    for Greece/Finland) refuses too many months on Denmark's small PHEV
    counts. Expected math: residual 20063-17777-22-0=2264, minus HEV 1427
    = 837, split 515:276 -> petrol round(837*515/791)=545, diesel=292."""
    with tempfile.TemporaryDirectory() as tmp:
        p = _split_csv(tmp, "Denmark", "api.statbank.dk (BIL53)")
        changed = quiet(fa.update_country, Path(tmp), "Denmark",
                        _SPLIT_PARSED, "2026-09", URL)
        assert changed
        row = next(csv.DictReader(p.open(encoding="utf-8")))
        assert float(row["HEV"]) == 1427 and float(row["PETROL"]) == 545
        assert float(row["DIESEL"]) == 292
        assert float(row["PETROL"]) + float(row["DIESEL"]) + float(row["HEV"]) == 2264
        # national totals stay national
        assert float(row["TOTAL"]) == 20063 and float(row["BEV"]) == 17777
        assert float(row["PHEV"]) == 22
        assert row["source"] == "api.statbank.dk (BIL53) / ACEA"
        assert "ACEA" in row["notes"]
        # Denmark's note must describe the ratio-scaled split, not the
        # strict counted split (Greece/Finland) — regression guard for the
        # note-selection bug where every country got acea_split.NOTE.
        assert "ratio" in row["notes"]
        assert "counted" in row["notes"]  # HEV is still counted


def test_split_only_never_creates_a_row():
    with tempfile.TemporaryDirectory() as tmp:
        p = _split_csv(tmp, "Denmark", "api.statbank.dk (BIL53)", header_only=True)
        changed = quiet(fa.update_country, Path(tmp), "Denmark",
                        _SPLIT_PARSED, "2026-09", URL)
        assert not changed
        assert list(csv.DictReader(p.open(encoding="utf-8"))) == []


def test_split_only_refuses_a_scope_mismatch():
    with tempfile.TemporaryDirectory() as tmp:
        p = _split_csv(tmp, "Denmark", "api.statbank.dk (BIL53)",
                       total=35529.0, bev=18858.0, phev=6050.0)
        changed = quiet(fa.update_country, Path(tmp), "Denmark",
                        _SPLIT_PARSED, "2026-09", URL)
        assert not changed
        row = next(csv.DictReader(p.open(encoding="utf-8")))
        assert row["HEV"] == "" and row["source"] == "api.statbank.dk (BIL53)"


def test_netherlands_latvia_are_not_split_candidates():
    import acea_split
    for c in ("Netherlands", "Latvia"):
        assert c not in fa.SPLIT_ONLY_COUNTRIES
        assert c not in acea_split.NATIONAL_SOURCE
    assert not fa.should_write("Netherlands", "current",
                               {"source": "duurzamemobiliteit.databank.nl (RDW)"})
    assert not fa.should_write("Latvia", "current", {"source": "CSDD"})


if __name__ == "__main__":
    main()
