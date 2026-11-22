#!/usr/bin/env python3
"""Regression tests for scripts/fetch_indonesia.py (no network).

Run:  python scripts/test_fetch_indonesia.py

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


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} tests passed")


if __name__ == "__main__":
    main()
