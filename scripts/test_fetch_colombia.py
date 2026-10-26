#!/usr/bin/env python3
"""Regression tests for scripts/fetch_colombia.py (no network, no poppler).

Run:  python scripts/test_fetch_colombia.py

Covers the two failure modes that cost the fetcher most of 2026:
- discovery: every filename shape ANDI has used for the bulletin so far must
  classify to the right (year, month), and the newest one must win;
- merging: a value the parser could not read is unknown, never 0, and never
  overwrites a value already in the CSV.

And the two legs added when the September 2026 PDF was nowhere to be found:
ANDI press-note discovery and the FENALCO press-text fallback, both against
real pages saved in scripts/fixtures/colombia/.
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_colombia as fc  # noqa: E402

FILENAME_CASES = {
    # 2025 shape: month abbr + "_PRENSA-INDUSTRIA <YYYY>_<ticks>"
    "/Uploads/12.%20INFORME%20SECTOR%20AUTOMOTOR%20DIC_PRENSA-INDUSTRIA%202025_639034007525631477.pdf": (2025, 12, True),
    # 2026 shape: month abbr glued to the year, no ticks
    "/Uploads/02.%20INFORME%20SECTOR%20AUTOMOTOR%20FEB2026_PRENSA.pdf": (2026, 2, True),
    # literal spaces instead of %20
    "/Uploads/07. INFORME SECTOR AUTOMOTOR JUL2026_PRENSA.pdf": (2026, 7, True),
    # 2021 shape: full month name
    "/Uploads/06.%20INFORME%20SECTOR%20AUTOMOTOR%20JUNIO%202021_PRENSA.pdf": (2021, 6, True),
    # annual report (different layout; must sort below a monthly file)
    "/Uploads/INFORME%20DEL%20SECTOR%20AUTOMOTOR%20A%20DICIEMBRE%202022.pdf": (2022, 12, False),
    # four-letter September, lower case, absolute URL with query string
    "https://www.andi.com.co/Uploads/09.%20informe%20sector%20automotor%20sept%202025_prensa.pdf": (2025, 9, True),
    # not the bulletin
    "/Uploads/Otro%20documento%202026.pdf": None,
    "/Uploads/INFORME%20SECTOR%20AUTOMOTOR.pdf": None,
}


def test_classify():
    for href, expected in FILENAME_CASES.items():
        got = fc.classify_pdf_name(fc._basename(href))
        assert got == expected, f"{href}: got {got}, expected {expected}"


def test_discovery_picks_newest_monthly():
    page = """
    <a href="/Uploads/12.%20INFORME%20SECTOR%20AUTOMOTOR%20DIC_PRENSA-INDUSTRIA%202025_639034007525631477.pdf">Dic 2025</a>
    <a href='/Uploads/07. INFORME SECTOR AUTOMOTOR JUL2026_PRENSA.pdf'>Jul 2026</a>
    <a href="https://www.andi.com.co/Uploads/02.%20INFORME%20SECTOR%20AUTOMOTOR%20FEB2026_PRENSA.pdf?x=1">Feb 2026</a>
    <a href="/Uploads/INFORME%20DEL%20SECTOR%20AUTOMOTOR%20A%20DICIEMBRE%202022.pdf">Anual 2022</a>
    <a href="/Uploads/07. INFORME SECTOR AUTOMOTOR JUL2026_PRENSA.pdf">Jul 2026 again</a>
    """

    class FakeSession:
        def get(self, *_a, **_k):
            class R:
                text = page

                def raise_for_status(self):
                    pass
            return R()

    url, year, month = fc.discover_latest_pdf(FakeSession())
    assert (year, month) == (2026, 7), (year, month)
    assert url == "https://www.andi.com.co/Uploads/07. INFORME SECTOR AUTOMOTOR JUL2026_PRENSA.pdf", url


def test_monthly_url_candidates_lead_with_the_2026_shape():
    urls = fc.monthly_url_candidates(2026, 8)
    # The shape Feb–Aug 2026 are actually served under must be tried first.
    assert urls[0] == ("https://www.andi.com.co/Uploads/"
                       "08.%20INFORME%20SECTOR%20AUTOMOTOR%20AGO2026_PRENSA.pdf"), urls[0]
    # and every candidate must classify back to the month we asked for
    for u in urls:
        assert fc.classify_pdf_name(fc._basename(u)) == (2026, 8, True), u


class _FakeResponse:
    def __init__(self, status, body):
        self.status_code, self.content = status, body


def test_find_unlisted_monthly_rejects_a_200_that_is_not_a_pdf():
    # One live /Uploads/ URL answers 200 with an empty body; it must not win.
    served = {fc.monthly_url_candidates(2026, 8)[0]: _FakeResponse(200, b""),
              fc.monthly_url_candidates(2026, 8)[1]: _FakeResponse(200, b"%PDF-1.7 ...")}

    class FakeSession:
        def get(self, url, **_k):
            return served.get(url, _FakeResponse(404, b"<html>"))

    url, body = fc.find_unlisted_monthly(FakeSession(), 2026, 8)
    assert url == fc.monthly_url_candidates(2026, 8)[1], url
    # the verified body comes back so main() need not re-download it
    assert body.startswith(b"%PDF"), body


def test_find_unlisted_monthly_returns_none_when_nothing_is_published():
    class FakeSession:
        def get(self, *_a, **_k):
            return _FakeResponse(404, b"<html>")

    assert fc.find_unlisted_monthly(FakeSession(), 2026, 9) is None


def test_target_month_reached_is_silent():
    fc.require_target_month("2026-08", "2026-08", date(2026, 9, 25))  # must not raise


def test_target_month_missing_early_in_the_window_exits_quietly():
    # Day 9: ANDI simply has not published August yet. Not a failure.
    try:
        fc.require_target_month("2026-08", "2025-12", date(2026, 9, 9))
    except SystemExit as exc:
        assert exc.code == 0, exc.code
    else:
        raise AssertionError("expected a quiet SystemExit(0)")


def test_target_month_missing_when_overdue_fails_loudly():
    # Day 25: August is overdue, so the run must go red rather than green.
    try:
        fc.require_target_month("2026-08", "2025-12", date(2026, 9, 25))
    except SystemExit as exc:
        assert exc.code != 0, exc.code
        assert "2026-08" in str(exc) and "overdue" in str(exc), exc
    else:
        raise AssertionError("expected a failing SystemExit")


def test_annual_loses_tie_to_monthly():
    cands = sorted([(2026, 12, False, "annual"), (2026, 12, True, "monthly")], reverse=True)
    assert cands[0][3] == "monthly"


def test_merge_keeps_existing_when_unknown():
    old = {"period": "2025-07", "variant": "Whole", "BEV": "1565.0", "HEV": "7636.0",
           "ICE": "14671.0", "TOTAL": "23872.0"}
    row, warnings = fc.merge_row(old, {"period": "2025-07", "TOTAL": 23872, "BEV": None, "HEV": 7636})
    # unknown BEV -> the CSV's 1565 survives, ICE is recomputed from it, no warning
    assert row["BEV"] == 1565.0 and row["ICE"] == 14671.0 and not warnings, (row, warnings)


def test_merge_never_downgrades_to_zero():
    old = {"period": "2023-11", "variant": "Whole", "BEV": "457", "HEV": "2900.0",
           "ICE": "15140.0", "TOTAL": "18497.0"}
    row, warnings = fc.merge_row(old, {"period": "2023-11", "TOTAL": 18497, "BEV": 0, "HEV": 2900})
    assert row["BEV"] == 457.0 and row["ICE"] == 18497 - 457 - 2900, row
    assert warnings and "keeping the CSV value" in warnings[0], warnings


def test_merge_skips_new_month_with_gap():
    row, warnings = fc.merge_row(None, {"period": "2026-07", "TOTAL": 30000, "BEV": None, "HEV": 9000})
    assert row is None and warnings, (row, warnings)


def test_merge_new_month_complete():
    row, warnings = fc.merge_row(None, {"period": "2026-07", "TOTAL": 30000, "BEV": 4870, "HEV": 9410,
                                        "variant": "Whole", "time_interval": "monthly", "source": fc.SOURCE,
                                        "PHEV": "", "PETROL": "", "DIESEL": "", "FLEXFUEL": "",
                                        "OTHERS": "", "ICE": None, "notes": ""})
    assert row["ICE"] == 30000 - 4870 - 9410 and row["BEV"] == 4870.0 and not warnings, (row, warnings)


def test_merge_updates_existing_value():
    old = {"period": "2026-05", "variant": "Whole", "BEV": "5001.0", "HEV": "8926.0",
           "ICE": "14209.0", "TOTAL": "28136.0"}
    row, warnings = fc.merge_row(old, {"period": "2026-05", "TOTAL": 28140, "BEV": 5003, "HEV": 8926})
    assert row["TOTAL"] == 28140.0 and row["BEV"] == 5003.0 and row["ICE"] == 28140 - 5003 - 8926
    assert not warnings, warnings


def test_assemble_requires_complete_newest_month():
    batches = [[(2026, 5, 100), (2026, 6, 110)], [(2026, 5, 10)], [(2026, 5, 20), (2026, 6, 22)]]
    try:
        fc.assemble_rows(batches)
    except RuntimeError as e:
        assert "2026-06" in str(e) and "BEV" in str(e), e
    else:
        raise AssertionError("expected assemble_rows to reject an incomplete newest month")


def test_assemble_marks_gaps_as_none():
    batches = [[(2026, 5, 100), (2026, 6, 110)], [(2026, 6, 11)], [(2026, 5, 20), (2026, 6, 22)]]
    rows = fc.assemble_rows(batches)
    assert rows[("2026-05", "Whole")]["BEV"] is None
    assert rows[("2026-06", "Whole")]["BEV"] == 11


def test_extract_series_batches_on_reset():
    text = """
    Vehículos nuevos
    ene-25        20.000
    feb-25        21.500
    Eléctricos
    ene-25        1.000
    feb-25           966
    Híbridos
    ene-25        5.000
    feb-25        5.500
    19.724 (Ene-dic 2025)
    """
    b = fc.extract_series(text)
    assert [len(x) for x in b] == [2, 2, 2], b
    assert b[0][0] == (2025, 1, 20000) and b[1][1] == (2025, 2, 966)


# Verbatim shape of the Jul-2026 bulletin's BEV chart as pdftotext -layout
# renders it: axis ticks first, YTD totals at column ~11 with their
# "(Ene-jul YYYY)" caption, chart-title fragments far right, and two bars
# (mar-25, jul-26) whose value sits six lines below the label.
BEV_CHART_2026 = (
    "\f                                        0\n"
    "                                            1.000\n"
    "                                                    2.000\n"
    "                               ene-24        217\n"
    "                               feb-24         395\n"
    "           3.178\n"
    "                                                                             Vehículos Nuevos\n"
    "       (Ene-jul 2024)\n"
    "                               mar-24         380\n"
    "                               feb-25                       1.095\n"
    "                               mar-25\n"
    "                                                                    eléctricos en unidades\n"
    "\n"
    "\n"
    "\n"
    "\n"
    "                                                               1.385\n"
    "                               abr-25                         1.286\n"
    "           29.347\n"
    "                               may-26                                    5.001\n"
    "        (Ene-jul 2026)\n"
    "                               jun-26                                    4.935\n"
    "                                jul-26\n"
    "Variación acumulada : 231,2%\n"
    "\n"
    "\n"
    "\n"
    "\n"
    "                                                                          4.870\n"
    "\f                                        0\n"
    "                              ene-24                        1.997\n"
)


def test_extract_series_value_below_label():
    b = fc.extract_series(BEV_CHART_2026)
    assert len(b) == 2, b
    bev = dict(((y, m), v) for y, m, v in b[0])
    assert bev[(2024, 1)] == 217 and bev[(2024, 3)] == 380
    assert bev[(2025, 3)] == 1385, bev          # value 6 lines below the label
    assert bev[(2026, 7)] == 4870, bev          # newest month, value after the "%" line
    assert bev[(2026, 5)] == 5001 and bev[(2026, 6)] == 4935
    assert 3178 not in bev.values() and 29347 not in bev.values()  # YTD totals stay out
    assert b[1] == [(2024, 1, 1997)]            # page break starts the next chart


# Verbatim shape of the Dec-2025 bulletin's total chart: here the YTD total
# ("186.222" with "(Ene-dic 2023)" aligned under it) sits RIGHT of the label
# column, on the line straight after an orphan label, and the real bar value
# ("11.581") comes five lines later at a different column.
TOTAL_CHART_2025 = (
    "                                          nov-23                           18.497\n"
    "                                           dic-23                            19.856\n"
    "                                          ene-24\n"
    "                                                                                                  186.222\n"
    "\n"
    "\n"
    "\n"
    "\n"
    "                                                                11.581\n"
    "                                                                                               (Ene-dic 2023)\n"
    "\n"
    "                                          feb-24                             15.597\n"
    "                                          nov-25                                   23.791\n"
    "                                           dic-25\n"
    "                                                                                                                                                254.205\n"
    "\n"
    "\n"
    "\n"
    "\n"
    "                                                                                                    30.135\n"
    "                                                                                                                                              (Ene-dic 2025)\n"
    "\f           BOLETÍN\n"
)


def test_extract_series_skips_ytd_total_right_of_label():
    b = fc.extract_series(TOTAL_CHART_2025)
    assert len(b) == 1, b
    total = dict(((y, m), v) for y, m, v in b[0])
    assert total[(2024, 1)] == 11581, total     # not the 186.222 YTD above it
    assert total[(2025, 12)] == 30135, total    # not the 254.205 YTD above it
    assert total[(2023, 11)] == 18497 and total[(2024, 2)] == 15597


def test_outlier_month_becomes_unknown():
    # a YTD total that slipped through the caption rule dwarfs its neighbours
    batch = [(2023, 11, 18497), (2023, 12, 19856), (2024, 1, 186222), (2024, 2, 15597)]
    assert fc._drop_outliers(batch) == [(2023, 11, 18497), (2023, 12, 19856), (2024, 2, 15597)]
    # a genuine doubling (mar-26 BEV) is not an outlier
    batch = [(2026, 1, 1758), (2026, 2, 2508), (2026, 3, 5083), (2026, 4, 5192)]
    assert fc._drop_outliers(batch) == batch
    # short batches are left alone
    assert fc._drop_outliers([(2026, 1, 1), (2026, 2, 100)]) == [(2026, 1, 1), (2026, 2, 100)]


def test_extract_series_orphan_is_left_out():
    text = (
        "                               jun-26        4.935\n"
        "                                jul-26\n"
        "Variación acumulada : 231,2%\n"
        "                               ene-24        1.997\n"   # next label -> stop looking
    )
    b = fc.extract_series(text)
    assert b == [[(2026, 6, 4935)], [(2024, 1, 1997)]], b


# --- ANDI press-note discovery + FENALCO press-text fallback ----------------
# Fixtures: real pages saved 2026-10-24 (scripts/fixtures/colombia/, anonymous
# CSRF tokens redacted). No network.

FIX = Path(__file__).resolve().parent / "fixtures" / "colombia"
FENALCO_POSTS = {
    (2026, 9): "fenalco_informe-del-sector-automotor-a-septiembre-2026-9171.html",
    (2026, 8): "fenalco_informe-del-sector-automotor-a-agosto-2026-9088.html",
    (2026, 7): "fenalco_informe-del-sector-automotor-a-julio-2026-9021.html",
}


def _fix(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


class _Resp:
    """requests.Response stand-in with .text, .content and raise_for_status()."""

    def __init__(self, status: int, body):
        self.status_code = status
        self.content = body.encode("utf-8") if isinstance(body, str) else body
        self.text = body if isinstance(body, str) else body.decode("latin-1")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise fc.requests.HTTPError(f"HTTP {self.status_code}")


class _MapSession:
    def __init__(self, served: dict):
        self.served, self.calls = served, []

    def get(self, url, timeout=None):
        self.calls.append(url)
        return self.served.get(url, _Resp(404, "<html>not found</html>"))


def _fenalco_site(posts=FENALCO_POSTS, index=None) -> dict:
    idx = index if index is not None else _fix("fenalco_blog_gremial-4.html")
    served = {fc.FENALCO_INDEX_URL: _Resp(200, idx)}
    for (y, m), name in posts.items():
        served[fc.fenalco_post_url(idx, y, m)] = _Resp(200, _fix(name))
    return served


def _csv_with(tmp: Path, rows: list[str]) -> str:
    path = tmp / "Colombia.csv"
    path.write_text(",".join(fc.CSV_COLUMNS) + "\n" + "".join(r + "\n" for r in rows), encoding="utf-8")
    return str(path)


AUG_ROW = "2026-08,monthly,Whole,andi.com.co + fenalco (datos RUNT),4542.0,,9195.0,,,,,13387.0,27124.0,"


def test_fenalco_press_text_backtest_matches_the_boletin():
    # Jul/Aug 2026 came from the PDF; the press text must give the same numbers.
    assert fc.parse_fenalco_post(_fix(FENALCO_POSTS[(2026, 8)]), 2026, 8) == \
        {"TOTAL": 27124, "BEV": 4542, "HEV": 9195}
    assert fc.parse_fenalco_post(_fix(FENALCO_POSTS[(2026, 7)]), 2026, 7) == \
        {"TOTAL": 28633, "BEV": 4870, "HEV": 9410}
    csv_rows = fc.read_csv(str(Path(__file__).resolve().parent.parent / "data" / "Colombia.csv"))
    for (y, m), name in ((k, v) for k, v in FENALCO_POSTS.items() if k != (2026, 9)):
        row = csv_rows[(f"{y}-{m:02d}", "Whole")]
        got = fc.parse_fenalco_post(_fix(name), y, m)
        assert {c: float(row[c]) for c in ("TOTAL", "BEV", "HEV")} == {c: float(v) for c, v in got.items()}, (y, m)


def test_fenalco_press_text_september_2026():
    # "Durante septiembre se registraron 33.835 vehículos nuevos" — not the
    # YTD "Entre enero y septiembre … 247.212".
    assert fc.parse_fenalco_post(_fix(FENALCO_POSTS[(2026, 9)]), 2026, 9) == \
        {"TOTAL": 33835, "BEV": 5895, "HEV": 11261}


def test_fenalco_post_rejects_the_wrong_month():
    try:
        fc.parse_fenalco_post(_fix(FENALCO_POSTS[(2026, 9)]), 2026, 10)
    except RuntimeError as exc:
        assert "does not say it reports octubre 2026" in str(exc), exc
    else:
        raise AssertionError("a September post parsed as October")


def test_fenalco_post_fails_loudly_on_unknown_wording():
    page = _fix(FENALCO_POSTS[(2026, 9)]).replace("5.895 unidades", "5.895 vehículos")
    try:
        fc.parse_fenalco_post(page, 2026, 9)
    except RuntimeError as exc:
        assert "expected one BEV" in str(exc) and "found none" in str(exc), exc
    else:
        raise AssertionError("missing BEV wording went unnoticed")
    # Two different TOTAL statements: refuse rather than pick one.
    page = _fix(FENALCO_POSTS[(2026, 7)]).replace(
        "En julio de 2026 se registraron 28.633", "En julio de 2026 se registraron 28.600")
    try:
        fc.parse_fenalco_post(page, 2026, 7)
    except RuntimeError as exc:
        assert "expected one TOTAL" in str(exc) and "found [28600, 28633]" in str(exc), exc
    else:
        raise AssertionError("conflicting totals went unnoticed")


def test_fenalco_combined_ev_sentence_counts_for_neither():
    page = _fix(FENALCO_POSTS[(2026, 9)]).replace(
        'id="o_wblog_post_footer"',
        '>Los vehículos eléctricos e híbridos sumaron 17.156 unidades. <div id="o_wblog_post_footer"')
    assert fc.parse_fenalco_post(page, 2026, 9) == {"TOTAL": 33835, "BEV": 5895, "HEV": 11261}


def test_fenalco_index_finds_car_posts_only():
    idx = _fix("fenalco_blog_gremial-4.html")
    assert fc.fenalco_post_url(idx, 2026, 9).endswith("/informe-del-sector-automotor-a-septiembre-2026-9171")
    assert fc.fenalco_post_url(idx, 2026, 8).endswith("/informe-del-sector-automotor-a-agosto-2026-9088")
    assert fc.fenalco_post_url(idx, 2026, 10) is None
    assert fc.fenalco_post_url(idx, 2026, 6) is None  # only Jun *2025* is on the page


def test_fenalco_fallback_fills_only_the_target_month_and_flags_it():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = _csv_with(Path(tmp), [AUG_ROW])
        assert fc.fenalco_fallback(_MapSession(_fenalco_site()), "2026-09", path, write=True)
        rows = fc.read_csv(path)
        assert sorted(rows) == [("2026-08", "Whole"), ("2026-09", "Whole")]
        sep = rows[("2026-09", "Whole")]
        assert (sep["TOTAL"], sep["BEV"], sep["HEV"], sep["ICE"]) == ("33835.0", "5895.0", "11261.0", "16679.0")
        assert sep["PHEV"] == "" and sep["notes"] == fc.FENALCO_NOTE and sep["source"] == fc.SOURCE
        assert rows[("2026-08", "Whole")]["notes"] == ""  # previous month untouched
        # Provisional: the early exit must keep looking for the PDF.
        assert fc.csv_has_period(path, "2026-09") and not fc.csv_has_final_period(path, "2026-09")
        assert fc.csv_has_final_period(path, "2026-08")


def test_fenalco_fallback_dry_run_writes_nothing():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = _csv_with(Path(tmp), [AUG_ROW])
        before = Path(path).read_text(encoding="utf-8")
        assert fc.fenalco_fallback(_MapSession(_fenalco_site()), "2026-09", path, write=False)
        assert Path(path).read_text(encoding="utf-8") == before


def test_fenalco_fallback_month_not_listed_defers_to_the_day_rule():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = _csv_with(Path(tmp), [AUG_ROW])
        assert fc.fenalco_fallback(_MapSession(_fenalco_site()), "2026-10", path, write=True) is False
        assert fc.fenalco_fallback(_MapSession({}), "2026-09", path, write=True) is False  # index 404


def test_fenalco_fallback_fails_early_when_cross_check_disagrees():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        # CSV says Aug TOTAL 20.000 — e.g. a passenger-car-only scope. The text
        # would then not measure the same thing: fail, whatever the day.
        path = _csv_with(Path(tmp), [AUG_ROW.replace("27124.0", "20000.0")])
        try:
            fc.fenalco_fallback(_MapSession(_fenalco_site()), "2026-09", path, write=True)
        except SystemExit as exc:
            assert "TOTAL=27124" in str(exc.code), exc.code
        else:
            raise AssertionError("cross-check mismatch went unnoticed")
        assert ("2026-09", "Whole") not in fc.read_csv(path)


def test_fenalco_fallback_fails_early_when_the_month_is_listed_but_unparseable():
    import tempfile
    site = _fenalco_site()
    idx = _fix("fenalco_blog_gremial-4.html")
    site[fc.fenalco_post_url(idx, 2026, 9)] = _Resp(200, "<html>login required</html>")
    with tempfile.TemporaryDirectory() as tmp:
        path = _csv_with(Path(tmp), [AUG_ROW])
        try:
            fc.fenalco_fallback(_MapSession(site), "2026-09", path, write=True)
        except SystemExit as exc:
            assert exc.code not in (0, None) and "FENALCO lists 2026-09" in str(exc.code), exc.code
        else:
            raise AssertionError("published-but-unreadable month did not fail")


def test_fenalco_fallback_needs_the_previous_month_in_the_csv():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = _csv_with(Path(tmp), [])
        try:
            fc.fenalco_fallback(_MapSession(_fenalco_site()), "2026-09", path, write=True)
        except SystemExit as exc:
            assert "CSV has no 2026-08 row" in str(exc.code), exc.code
        else:
            raise AssertionError("fallback ran without a cross-check")


def test_boletin_overwrites_a_provisional_press_text_row():
    old = {c: "" for c in fc.CSV_COLUMNS}
    old.update(period="2026-09", time_interval="monthly", variant="Whole", source=fc.SOURCE,
               BEV="5895.0", HEV="11261.0", ICE="16679.0", TOTAL="33835.0", notes=fc.FENALCO_NOTE)
    new = {"period": "2026-09", "time_interval": "monthly", "variant": "Whole", "source": fc.SOURCE,
           "BEV": 5890, "PHEV": "", "HEV": 11265, "PETROL": "", "DIESEL": "", "FLEXFUEL": "",
           "OTHERS": "", "TOTAL": 33835, "ICE": None, "notes": ""}
    row, _ = fc.merge_row(old, new)
    assert row["notes"] == ""
    assert (row["BEV"], row["HEV"], row["ICE"]) == (5890.0, 11265.0, 16680.0)


def test_andi_news_finds_the_embedded_boletin_and_skips_motorcycles():
    listing = _fix("andi_noticias.html")
    articles = fc.news_article_links(listing)
    assert [a.rsplit("/", 1)[-1][:5] for a in articles] == ["18084", "18083"], articles
    aug_pdf = "https://www.andi.com.co/Uploads/08.%20INFORME%20SECTOR%20AUTOMOTOR%20AGO2026_PRENSA.pdf"
    served = {fc.ANDI_NEWS_URL: _Resp(200, listing),
              articles[0]: _Resp(200, _fix("andi_noticia_18084.html")),   # motorcycles report
              articles[1]: _Resp(200, _fix("andi_noticia_18083.html")),   # cars report
              aug_pdf: _Resp(200, b"%PDF-1.7 ...")}
    s = _MapSession(served)
    assert fc.find_in_andi_news(s, 2026, 8) == (aug_pdf, b"%PDF-1.7 ...")
    assert not any("Motocicletas" in c for c in s.calls), s.calls
    # September: no press note embeds it (the real state on 2026-10-24).
    assert fc.find_in_andi_news(_MapSession(served), 2026, 9) is None


def test_andi_news_rejects_an_embedded_url_that_is_not_a_pdf():
    listing = _fix("andi_noticias.html")
    articles = fc.news_article_links(listing)
    aug_pdf = "https://www.andi.com.co/Uploads/08.%20INFORME%20SECTOR%20AUTOMOTOR%20AGO2026_PRENSA.pdf"
    served = {fc.ANDI_NEWS_URL: _Resp(200, listing),
              articles[1]: _Resp(200, _fix("andi_noticia_18083.html")),
              aug_pdf: _Resp(200, b"")}
    assert fc.find_in_andi_news(_MapSession(served), 2026, 8) is None
    assert fc.find_in_andi_news(_MapSession({}), 2026, 8) is None  # listing down: leg skipped


def test_andi_news_catches_a_ticked_name_guessing_cannot():
    ticked = "https://www.andi.com.co/Uploads/09.%20INFORME%20SECTOR%20AUTOMOTOR%20SEP2026_PRENSA_639300000000000000.pdf"
    listing = '<a href="/Home/Noticia/18110-andi-y-fenalco-en-septiembre-de-2026">x</a>'
    article = f'<iframe src="{ticked}"></iframe>'
    served = {fc.ANDI_NEWS_URL: _Resp(200, listing),
              "https://www.andi.com.co/Home/Noticia/18110-andi-y-fenalco-en-septiembre-de-2026": _Resp(200, article),
              ticked: _Resp(200, b"%PDF-1.7 sep")}
    assert ticked not in fc.monthly_url_candidates(2026, 9)
    assert fc.find_in_andi_news(_MapSession(served), 2026, 9) == (ticked, b"%PDF-1.7 sep")


def test_resolve_bulletin_tries_press_notes_before_guessing():
    camara = '<a href="/Uploads/INFORME%20FINAL%20SECTOR%20AUTOMOTOR%20DICIEMBRE%202025.pdf">x</a>'
    aug_pdf = "https://www.andi.com.co/Uploads/08.%20INFORME%20SECTOR%20AUTOMOTOR%20AGO2026_PRENSA.pdf"
    listing = _fix("andi_noticias.html")
    served = {fc.CAMARA_URL: _Resp(200, camara), fc.ANDI_NEWS_URL: _Resp(200, listing),
              fc.news_article_links(listing)[1]: _Resp(200, _fix("andi_noticia_18083.html")),
              aug_pdf: _Resp(200, b"%PDF-1.7 aug")}
    s = _MapSession(served)
    assert fc.resolve_bulletin(s, "2026-08") == (aug_pdf, 2026, 8, True, b"%PDF-1.7 aug")
    assert not any(u in s.calls for u in fc.monthly_url_candidates(2026, 8)[1:]), s.calls


def test_monthly_url_candidates_try_both_september_spellings():
    names = [fc._basename(u) for u in fc.monthly_url_candidates(2026, 9)]
    assert "09. INFORME SECTOR AUTOMOTOR SEP2026_PRENSA.pdf" == names[0]
    assert "09. INFORME SECTOR AUTOMOTOR SEPT2026_PRENSA.pdf" in names
    assert "09. INFORME SECTOR AUTOMOTOR SET2026_PRENSA.pdf" in names
    assert not any("SEPT" in fc._basename(u) for u in fc.monthly_url_candidates(2026, 8))


def main() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} tests passed")


if __name__ == "__main__":
    main()
