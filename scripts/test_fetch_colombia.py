#!/usr/bin/env python3
"""Regression tests for scripts/fetch_colombia.py (no network, no poppler).

Run:  python scripts/test_fetch_colombia.py

Covers the two failure modes that cost the fetcher most of 2026:
- discovery: every filename shape ANDI has used for the bulletin so far must
  classify to the right (year, month), and the newest one must win;
- merging: a value the parser could not read is unknown, never 0, and never
  overwrites a value already in the CSV.
"""
import sys
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


def main() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} tests passed")


if __name__ == "__main__":
    main()
