#!/usr/bin/env python3
"""Regression tests for scripts/fetch_indonesia.py (no network).

Run:  python scripts/test_fetch_indonesia.py

Also covers Jan-Okt 2026 layout drift (origin-text overflow into the
January band, parenthetical negatives, EV as a BEV synonym, and the
rightward shift of PU/TRUCK category labels) without committing the
copyrighted source PDF.

Focus: the 0-vs-empty writer defect (#438). `fuels.get(f, 0)` used to
default every FUEL_KEY to 0 regardless of whether the PDF's fuel table ever
listed that category for the section/variant, so "no BEV row this month"
and "no fuel-type table at all" were both written as BEV=0 — indistinguishable
from a genuine reported zero. These tests pin:
  * a PDF with no FUEL column anywhere aborts before any CSV write
    (validate()'s existing "nothing to parse" exit);
  * a variant whose fuel table never lists a given category (e.g. no HEV
    model row anywhere in the PDF) writes that cell empty, not 0;
  * a category that *is* listed, with 0 units some months and >0 in others,
    writes a real "0" for the zero months (a reported zero stays a zero);
  * OTHERS is always written as a number (0 included) since it is our own
    catch-all bucket, not a category the PDF can omit.
"""
import sys
from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_indonesia as fi  # noqa: E402


def months_dict(*month_fuel_pairs):
    """{month: {fuel: units}} from (month, fuel, units) triples."""
    out = defaultdict(lambda: defaultdict(int))
    for mi, fuel, v in month_fuel_pairs:
        out[mi][fuel] += v
    return out


def test_no_fuel_table_aborts_before_any_write():
    """validate() must reject a PDF whose sheets never carry a FUEL column
    before build_series/upsert_csv ever run — the proposed fix's item 1."""
    parsed = fi.ParsedPdf()
    parsed.coverage = (2, 2026)
    parsed.sections_without_fuel_column = 7   # every sheet title matched, none had FUEL
    # parsed.sections stays empty: no section ever got a fuel column
    try:
        fi.validate(parsed)
    except SystemExit as e:
        assert "no BEV/PHEV/HEV/petrol/diesel split" in str(e)
        assert "nothing to parse" in str(e)
    else:
        raise AssertionError("a PDF with no FUEL column anywhere must abort")


def test_partial_section_missing_fuel_column_also_aborts():
    """If some sections parsed a fuel column and others did not, the
    mixed-edition case must still fail loudly rather than silently write 0s
    for the sections that lack a column (defense in depth beyond the
    all-sections check above)."""
    parsed = fi.ParsedPdf()
    parsed.coverage = (1, 2026)
    parsed.sections_without_fuel_column = 1
    # SEDAN parsed fine; 4X2/4X4/BUS/PU_TRUCK/DOUBLE_CABIN/LCGC never
    # entered parsed.sections because process_region bailed early for them.
    parsed.sections["SEDAN"][1]["PETROL"] = 100
    parsed.printed["SEDAN"] = [100] + [0] * 11
    try:
        fi.validate(parsed)
    except SystemExit:
        pass
    else:
        raise AssertionError("missing sections must abort, not default to 0")


def _make_parsed_with_categories():
    """A minimal ParsedPdf: 2 covered months, Whole built from SEDAN alone.
    SEDAN's fuel table lists PETROL and BEV (BEV is 0 in month 1, >0 in
    month 2) but never lists HEV/PHEV/DIESEL — those never had a model row."""
    parsed = fi.ParsedPdf()
    parsed.coverage = (2, 2026)
    parsed.sections["SEDAN"] = months_dict((1, "PETROL", 500), (2, "PETROL", 400),
                                            (2, "BEV", 10))
    # BEV had a model row in both months (0 units in month 1), so it is
    # "present" even though month 1's contribution rounds to nothing above.
    parsed.fuel_categories["SEDAN"] = {"PETROL", "BEV"}
    for k in ("4X2", "4X4", "LCGC", "BUS", "PU_TRUCK", "DOUBLE_CABIN"):
        parsed.sections[k] = defaultdict(lambda: defaultdict(int))
        parsed.fuel_categories[k] = set()
    return parsed


def test_missing_category_written_empty_present_category_written_zero():
    parsed = _make_parsed_with_categories()
    series = fi.build_series(parsed)
    variant, months, categories = series[""]
    assert variant == "Whole"
    assert categories == {"PETROL", "BEV"}

    with TemporaryDirectory() as d:
        path = Path(d) / "Indonesia.csv"
        changes = fi.upsert_csv(path, variant, months, categories, 2026, "GAIKINDO",
                                 "Wholesales Jan-Feb 2026", force=False)
        assert [p for p, _ in changes] == ["2026-01", "2026-02"]
        import csv
        with open(path, newline="") as f:
            rows = {r["period"]: r for r in csv.DictReader(f)}
        jan, feb = rows["2026-01"], rows["2026-02"]
        # PETROL was in the table every month -> real numbers, including the
        # reported zero for BEV in January.
        assert jan["PETROL"] == "500" and jan["BEV"] == "0"
        assert feb["PETROL"] == "400" and feb["BEV"] == "10"
        # HEV/PHEV/DIESEL never appeared in SEDAN's fuel table -> empty, not "0"
        for f in ("HEV", "PHEV", "DIESEL"):
            assert jan[f] == "" and feb[f] == "", (f, jan[f], feb[f])
        # OTHERS is our own catch-all: always a number even with no row at all
        assert jan["OTHERS"] == "0" and feb["OTHERS"] == "0"
        assert jan["TOTAL"] == "500" and feb["TOTAL"] == "410"


def test_empty_to_zero_transition_is_an_update_not_noop():
    """A later PDF edition that finally lists a previously-missing category
    (empty -> a real number, possibly 0) must register as a change, so a
    --force or natural revision run actually rewrites the cell."""
    with TemporaryDirectory() as d:
        path = Path(d) / "Indonesia.csv"
        header = ",".join(fi.CSV_COLUMNS) + "\n"
        old_row = "2026-01,monthly,Whole,GAIKINDO,0,0,,500,0,0,500,Wholesales Jan 2026\n"
        path.write_text(header + old_row, encoding="utf-8")
        months = months_dict((1, "PETROL", 500), (1, "HEV", 3))
        changes = fi.upsert_csv(path, "Whole", months, {"PETROL", "HEV"}, 2026,
                                 "GAIKINDO", "Wholesales Jan 2026", force=False)
        assert changes == [("2026-01", "updated")]


def test_parse_cell_ignores_origin_overflow():
    """'South Korea' can sit inside the January band on the 2-page layout."""
    assert fi.parse_cell(["Korea", "2"]) == 2
    assert fi.parse_cell(["Korea", "-"]) == 0
    assert fi.parse_cell(["Korea"]) == 0
    # split numbers still reassemble
    assert fi.parse_cell(["3", "80"]) == 380
    assert fi.parse_cell(["1", ".044"]) == 1044
    assert fi.parse_cell(["-"]) == 0
    assert fi.parse_cell([]) == 0


def test_parse_cell_parenthetical_negative():
    """GAIKINDO writes returns/adjustments as '( 1)' or '(1)'."""
    assert fi.parse_cell(["(", "1)"]) == -1
    assert fi.parse_cell(["(", "1", ")"]) == -1
    assert fi.parse_cell(["(12)"]) == -12
    # cell_or_zero must not treat -1 as missing
    assert fi.cell_or_zero(-1) == -1
    assert fi.cell_or_zero(None) == 0
    assert fi.cell_or_zero(0) == 0


def test_ev_fuel_token_maps_to_bev():
    """Mazda 6e (and similar) print EV in the FUEL column, not BEV."""
    assert fi.FUEL_COLUMN["EV"] == "BEV"
    assert fi.FUEL_COLUMN["BEV"] == "BEV"


def _row(top, *pairs):
    """pairs: (text, x0) — enough for pu_label_x_max / pu_segment_label."""
    words = [{"text": t, "x0": x, "x1": x + 4, "top": top} for t, x in pairs]
    return {"top": top, "words": words, "text": " ".join(t for t, _ in pairs)}


def test_pu_label_x_max_reads_brand_header():
    """Cutoff follows the BRAND header so both layouts share one rule."""
    # Jan-Okt 2026 two-page positions (measured)
    new_layout = [_row(10, ("CATEGORY", 209.1), ("BRAND", 250.6), ("MODEL/TYPE", 291.2))]
    assert fi.pu_label_x_max(new_layout) == 250.6
    # Pre-Okt 3-page layout as documented: labels at x0 < 190, so BRAND
    # starts at or right of 190. A typical gap: CATEGORY then BRAND at 200.
    old_layout = [_row(10, ("CATEGORY", 160.0), ("BRAND", 200.0), ("MODEL/TYPE", 240.0))]
    assert fi.pu_label_x_max(old_layout) == 200.0
    assert fi.pu_label_x_max([]) == fi.PU_LABEL_X_MAX == 240


def test_pu_segment_label_new_layout_coordinates():
    """Jan-Okt 2026: label starts ~197 (past the old 190 cutoff); MERCEDES
    sits slightly left of the BRAND header and must not enter the label."""
    rows = [
        _row(10, ("CATEGORY", 209.1), ("BRAND", 250.6)),
        _row(20, ("PICK", 196.6), ("UP", 200.4), ("GVW", 219.2),
             ("<", 223.2), ("5", 224.7), ("Ton", 225.9),
             ("DAIHATSU", 249.4)),
        _row(30, ("TRUCK", 197.1), ("GVW", 218.4), ("5", 222.5),
             ("-", 223.7), ("10", 224.7), ("Ton", 226.6),
             ("MERCEDES", 245.6)),
    ]
    xmax = fi.pu_label_x_max(rows)
    pick = fi.pu_segment_label(rows, 15, 25, xmax)
    truck = fi.pu_segment_label(rows, 25, 35, xmax)
    assert pick == "PICK UP GVW < 5 Ton"
    assert truck == "TRUCK GVW 5 - 10 Ton"
    assert "DAIHATSU" not in pick and "MERCEDES" not in truck
    # the old hardcoded 190 cutoff would have missed both labels
    assert fi.pu_segment_label(rows, 15, 25, 190) == ""


def test_pu_segment_label_old_layout_coordinates():
    """3-page layout as the previous cutoff assumed: label words at
    x0 < 190, brand column from x=200. A cutoff of 240 would have
    swallowed the brand; the header-derived edge plus the token filter
    must not."""
    rows = [
        _row(10, ("CATEGORY", 160.0), ("BRAND", 200.0)),
        _row(20, ("PICK", 150.0), ("UP", 158.0), ("GVW", 170.0),
             ("<", 178.0), ("5", 182.0), ("Ton", 186.0),
             ("DAIHATSU", 205.0)),
        _row(30, ("TRUCK", 152.0), ("GVW", 168.0), ("5", 176.0),
             ("-", 180.0), ("10", 184.0), ("Ton", 188.0),
             ("HINO", 205.0)),
        # a brand that starts *left* of a naive 240 fallback
        _row(40, ("GVW", 168.0), (">", 176.0), ("24", 180.0),
             ("Ton", 186.0), ("TOYOTA", 202.0)),
    ]
    xmax = fi.pu_label_x_max(rows)
    assert xmax == 200.0
    assert fi.pu_segment_label(rows, 15, 25, xmax) == "PICK UP GVW < 5 Ton"
    assert fi.pu_segment_label(rows, 25, 35, xmax) == "TRUCK GVW 5 - 10 Ton"
    assert fi.pu_segment_label(rows, 35, 45, xmax) == "GVW > 24 Ton"
    # 240 would still be safe here only because of the token filter
    assert "TOYOTA" not in fi.pu_segment_label(rows, 35, 45, 240)
    assert "DAIHATSU" not in fi.pu_segment_label(rows, 15, 25, 240)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} tests passed")


if __name__ == "__main__":
    main()
