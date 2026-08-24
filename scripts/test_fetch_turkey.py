#!/usr/bin/env python3
"""Regression tests for the TÜİK fuel-table parser in fetch_turkey.py.

Run with plain Python, no test framework and no network:

    python scripts/test_fetch_turkey.py

The interesting cases are all shapes of OCR damage, so the fixtures are
synthetic tesseract word boxes rather than images. The Temmuz 2026 fixture
reproduces the exact damage that took the daily cron red from 2026-08-17
onward, transcribed from the run log of
https://github.com/LeRaffl/LeRaffl-Gallery/actions/runs/32711225618 :

  * the Hibrit row lost its current-month Pay% token, so positional indexing
    read the *next* column's percentage (27,0 % — the Ocak-Temmuz 2025 share)
    as if it were Temmuz 2026's, and the repair heuristic then accused the one
    fuel that was in fact correct;
  * the LPG row carried a stray integer 13, which is the previous-year Pay%
    "1,3" with the decimal comma lost, and the old first-four-tokens cap kept
    it in place of the real 1 252.

Neither is exotic; both are what a low-resolution raster table does to an OCR.
The parser has to survive them without a human.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_turkey as ft  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
CSV = REPO / "data" / "Türkiye.csv"

# --- fixture geometry ------------------------------------------------------
# One row per fuel, and per period a count column with a narrower Pay% column
# to its right. The Pay% columns sit off-centre between two count columns,
# which is what makes assign_columns' tolerance worth testing: a stray integer
# in a Pay% column lands closer to one count anchor than to the other.
ROW_H = 40
COUNT_X = [400, 800, 1200, 1600]
PCT_X = [640, 1040, 1440, 1840]

# Temmuz 2026, as printed in bulletin 58045. Columns:
#   Temmuz 2025, Temmuz 2026, Ocak-Temmuz 2025, Ocak-Temmuz 2026
TEMMUZ = {
    "Toplam":   ([106407, 78761, 614248, 534811], [100.0, 100.0, 100.0, 100.0]),
    "Benzin":   ([44857, 28810, 279989, 219450], [42.2, 36.6, 45.6, 41.0]),
    "Hibrit":   ([27391, 25743, 166042, 170042], [25.7, 32.7, 27.0, 31.8]),
    "Elektrik": ([23623, 15267, 105757, 96438], [22.2, 19.4, 17.2, 18.0]),
    "Dizel":    ([9186, 7689, 56300, 43081], [8.6, 9.7, 9.2, 8.1]),
    "LPG":      ([1350, 1252, 6160, 5800], [1.3, 1.6, 1.0, 1.1]),
}
TEMMUZ_TOTAL = 78761
TEMMUZ_EXPECTED = {"Benzin": 28810, "Hibrit": 25743, "Elektrik": 15267,
                   "Dizel": 7689, "LPG": 1252}


def _word(text, x, y, w=None):
    return {"text": text, "left": x, "top": y, "width": w if w else 22 * len(text),
            "height": 30, "conf": 95.0}


def build_words(table, drop_pcts=(), stray_ints=(), split_thousands=True):
    """Synthesise tesseract word boxes for a fuel table.

    drop_pcts:   [(label, col)] percentages the OCR failed to emit.
    stray_ints:  [(label, x, text)] extra integer tokens at an explicit x.
    """
    words = []
    for r, (label, (counts, pcts)) in enumerate(table.items()):
        y = 200 + r * ROW_H * 3
        words.append(_word(label, 40, y))
        for col, value in enumerate(counts):
            if value is None:
                continue
            x = COUNT_X[col]
            text = f"{value}"
            if split_thousands and value >= 1000:
                # Tesseract splits "78 761" on the thousands separator.
                head, tail = text[:-3], text[-3:]
                words.append(_word(head, x, y))
                words.append(_word(tail, x + 22 * len(head) + 12, y))
            else:
                words.append(_word(text, x, y))
        for col, pct in enumerate(pcts):
            if (label, col) in drop_pcts or pct is None:
                continue
            words.append(_word(f"{pct:.1f}".replace(".", ","), PCT_X[col], y))
        for lbl, x, text in stray_ints:
            if lbl == label:
                words.append(_word(text, x, y))
    words.sort(key=lambda w: (w["top"], w["left"]))
    return words


def col(table, label, index):
    return table[label][0][index]


# --- tests -----------------------------------------------------------------

def test_clean_table_reads_every_column():
    table = ft.parse_table(build_words(TEMMUZ))
    for label, (counts, pcts) in TEMMUZ.items():
        assert table[label][0] == counts, (label, table[label][0], counts)
        assert table[label][1] == pcts, (label, table[label][1], pcts)


def test_temmuz_2026_damage_is_survived():
    """The exact failure of 2026-08-17..24: a dropped Pay% and a stray integer."""
    words = build_words(
        TEMMUZ,
        drop_pcts=[("Hibrit", ft.COL_MONTH)],
        # "1,3" read as "13", sitting in the previous-year Pay% column.
        stray_ints=[("LPG", PCT_X[0], "13")],
    )
    table = ft.parse_table(words)

    # The stray never displaces a real count, and the dropped percentage leaves
    # a hole in its own column instead of shifting the ones behind it.
    assert col(table, "LPG", ft.COL_MONTH) == 1252, table["LPG"]
    assert table["Hibrit"][1][ft.COL_MONTH] is None, table["Hibrit"][1]
    assert table["Hibrit"][1][ft.COL_YTD_PREV] == 27.0, table["Hibrit"][1]

    fuels, repairs = ft.validate_and_repair(table, TEMMUZ_TOTAL)
    assert fuels == TEMMUZ_EXPECTED, fuels
    assert repairs == [], repairs          # nothing was wrong to begin with
    assert sum(fuels.values()) == TEMMUZ_TOTAL


def test_dropped_pct_no_longer_accuses_the_wrong_fuel():
    """Lock in the bug's cause, not just its symptom.

    Indexing Pay% by position made Hibrit's col-2 share (27,0 %) masquerade as
    its col-1 share (32,7 %), which is what made a correct value look like the
    outlier. Column-aligned rows must never let one row's gap change what
    another column means.
    """
    table = ft.parse_table(build_words(TEMMUZ, drop_pcts=[("Hibrit", ft.COL_MONTH)]))
    pcts = [p for p in table["Hibrit"][1] if p is not None]
    assert pcts == [25.7, 27.0, 31.8]                      # what the OCR emitted
    assert table["Hibrit"][1] == [25.7, None, 27.0, 31.8]  # where it belongs


def test_a_genuine_single_digit_misread_is_still_repaired():
    """The Mart 2026 case: one fuel misread, Pay% present, sum short."""
    damaged = {k: (list(v[0]), list(v[1])) for k, v in TEMMUZ.items()}
    damaged["Hibrit"][0][ft.COL_MONTH] = 25243          # 25 743 misread
    table = ft.parse_table(build_words(damaged))
    fuels, repairs = ft.validate_and_repair(table, TEMMUZ_TOTAL)
    assert fuels == TEMMUZ_EXPECTED, fuels
    assert repairs == [("Hibrit", 25243, 25743)], repairs


def test_multi_fuel_damage_still_hard_fails():
    """Two wrong values must not be silently 'repaired' into a plausible row."""
    damaged = {k: (list(v[0]), list(v[1])) for k, v in TEMMUZ.items()}
    damaged["Hibrit"][0][ft.COL_MONTH] = 25243
    damaged["Dizel"][0][ft.COL_MONTH] = 7089
    table = ft.parse_table(build_words(damaged))
    try:
        ft.validate_and_repair(table, TEMMUZ_TOTAL)
    except RuntimeError:
        return
    raise AssertionError("expected multi-fuel damage to be refused")


def test_wrong_table_is_refused():
    """A bulletin also prints the registered stock, under identical labels."""
    stock = {k: ([v * 10 for v in c], p) for k, (c, p) in TEMMUZ.items()}
    table = ft.parse_table(build_words(stock))
    try:
        ft.validate_and_repair(table, TEMMUZ_TOTAL)
    except RuntimeError:
        return
    raise AssertionError("expected the stock table to be refused")


def test_column_anchors_fall_back_without_clean_rows():
    """Every row damaged: geometry still has to come from somewhere."""
    rows = [[(400, 1), (800, 2), (1200, 3)],
            [(400, 4), (1200, 6), (1600, 7)],
            [(800, 9), (1200, 10), (1600, 11)]]
    anchors = ft.column_anchors(rows)
    assert anchors == [400, 800, 1200, 1600], anchors


def test_join_thousands_centres_the_whole_number():
    tokens = [{"text": "78", "left": 400, "top": 0, "width": 44, "height": 30},
              {"text": "761", "left": 456, "top": 0, "width": 66, "height": 30}]
    assert ft.join_thousands(tokens) == [((400 + 522) // 2, 78761)]


def test_ytd_cross_check_accepts_the_real_temmuz_row():
    table = ft.parse_table(build_words(TEMMUZ))
    note = ft.cross_check_ytd(table, str(CSV), 2026, 7, TEMMUZ_EXPECTED, TEMMUZ_TOTAL)
    assert note.startswith("OK on 6/6"), note


def test_ytd_cross_check_catches_a_shifted_column():
    """A row that is internally consistent but wrong still has to fail."""
    table = ft.parse_table(build_words(TEMMUZ))
    wrong = dict(TEMMUZ_EXPECTED)
    wrong["Elektrik"] -= 500
    wrong["Benzin"] += 500          # still sums to the narrative total
    try:
        ft.cross_check_ytd(table, str(CSV), 2026, 7, wrong, TEMMUZ_TOTAL)
    except RuntimeError as e:
        assert "Elektrik" in str(e) and "Benzin" in str(e), e
        return
    raise AssertionError("expected the year-to-date check to reject the row")


def test_ytd_cross_check_skips_an_incomplete_year():
    table = ft.parse_table(build_words(TEMMUZ))
    note = ft.cross_check_ytd(table, str(CSV), 2016, 7, TEMMUZ_EXPECTED, TEMMUZ_TOTAL)
    assert note.startswith("skipped"), note


def test_prev_year_cross_check_reads_the_committed_row():
    table = ft.parse_table(build_words(TEMMUZ))
    ft.cross_check_prev_year(table, str(CSV), 2026, 7)   # raises if it disagrees


def test_markup_path_yields_aligned_columns():
    html = "<table>" + "".join(
        f"<tr><td>{label}</td>"
        + "".join(f"<td>{c}</td><td>{p:.1f}</td>".replace(".", ",")
                  for c, p in zip(counts, pcts))
        + "</tr>"
        for label, (counts, pcts) in TEMMUZ.items()
    ) + "</table>"
    candidates = ft.parse_content_tables(html)
    assert len(candidates) == 1, candidates
    table = candidates[0]
    assert all(len(table[l][0]) == ft.N_COLS for l in TEMMUZ), table
    fuels, _ = ft.validate_and_repair(table, TEMMUZ_TOTAL)
    assert fuels == TEMMUZ_EXPECTED, fuels


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:  # noqa: BLE001 — a test runner reports, it does not raise
            failed += 1
            print(f"FAIL  {t.__name__}: {type(e).__name__}: {e}")
        else:
            print(f"ok    {t.__name__}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
