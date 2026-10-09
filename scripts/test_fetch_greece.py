#!/usr/bin/env python3
"""Regression tests for scripts/fetch_greece.py (no network).

Run:  python scripts/test_fetch_greece.py

SEAA's files are made for people, not parsers: the press release wraps fuel
labels over two lines, the BEV/PHEV PDFs repeat every model in aggregate
blocks, a volume cell is now and then printed as a percentage, and a month
was once typed with Greek capitals ("ΜΑΥ '23"). These cases pin the file-name
classification, every parser against real files (scripts/fixtures/greece/),
the share-derived split, the provisional-row rule, the source precedence in
the upsert, and one end-to-end run into a scratch CSV.
"""
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_greece as fg  # noqa: E402
import market_top  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "greece"
LIB = fg.DirLibrary(FIX)
PR_AUG26 = "Δελτίο-τύπου-ΣΕΑΑ-για-τις-ταξινομήσεις-Αυγούστου-2026.pdf"
PR_MAY23 = "Δελτίο-τύπου-ΣΕΑΑ-για-τις-ταξινομήσεις-Μαΐου-2023.pdf"


def quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


def test_classify_name():
    cases = [
        ("2026-8-comp.xlsx", ("comp", "2026-08")),
        ("2026-6-comp-1.xlsx", ("comp", "2026-06")),
        ("https://seaa.gr/wp-content/uploads/2026/09/2026-8-BEV.pdf", ("bev", "2026-08")),
        ("2026-7-PHEV.pdf", ("phev", "2026-07")),
        ("2023-12-electric-1.pdf", ("electric", "2023-12")),
        (PR_AUG26, ("pr", "2026-08")),
        (PR_MAY23, ("pr", "2023-05")),
        ("Δελτίο-τύπου-ΣΕΑΑ-για-τις-ταξινομήσεις-Ιουλίου-2026-.pdf", ("pr", "2026-07")),
        ("Δελτίο-τύπου-ΣΕΑΑ-για-τις-ταξινομήσεις-Μαρτίου-2023.pdf", ("pr", "2023-03")),
        ("https://seaa.gr/wp-content/uploads/2026/09/%CE%94%CE%B5%CE%BB%CF%84%CE%AF%CE%BF-"
         "%CF%84%CF%8D%CF%80%CE%BF%CF%85-%CE%A3%CE%95%CE%91%CE%91-%CE%B3%CE%B9%CE%B1-"
         "%CF%84%CE%B9%CF%82-%CF%84%CE%B1%CE%BE%CE%B9%CE%BD%CE%BF%CE%BC%CE%AE%CF%83%CE%B5"
         "%CE%B9%CF%82-%CE%91%CF%85%CE%B3%CE%BF%CF%8D%CF%83%CF%84%CE%BF%CF%85-2026.pdf",
         ("pr", "2026-08")),
    ]
    for name, want in cases:
        assert fg.classify_name(name) == want, (name, fg.classify_name(name), want)
    # look-alikes that must not match
    for name in ("2026-8-seg.pdf", "2026-08-a.pdf", "2026-8-comp.pdf", "2026-8-BEV.xlsx",
                 "Press_release_car_registrations_August_2026.pdf",
                 "Δελτίο-τύπου-ΣΕΑΑ-περιβαλλοντικό-τέλος.pdf",
                 "2020-07-PC-YTD.pdf"):
        assert fg.classify_name(name) is None, name


def test_newest_upload_wins():
    lib = fg.Library()
    lib.add("2026-07-20T10:44", "https://x/2026/07/2026-6-BEV.pdf")
    lib.add("2026-07-20T10:46", "https://x/2026/07/2026-6-BEV-1.pdf")
    lib.add("2026-07-19T00:00", "https://x/2026/07/2026-6-BEV-2.pdf")
    assert lib.url("bev", "2026-06").endswith("2026-6-BEV-1.pdf")


def test_printed_period():
    assert fg.printed_period("BEV VEHICLES YTD AUGUST '26") == "2026-08"
    assert fg.printed_period("Aug. '26") == "2026-08"
    assert fg.printed_period("August. '23") == "2023-08"
    assert fg.printed_period("BEV Vehicles YTD ΜΑΥ '23") == "2023-05"   # Greek capitals
    assert fg.printed_period("DECEMBER ’21") == "2021-12"
    assert fg.printed_period("no month here") is None


def test_greek_month():
    for word, m in (("Ιανουαρίου", 1), ("Μαρτίου", 3), ("Μαΐου", 5), ("Μάιο", 5),
                    ("Αύγουστο", 8), ("Αυγούστου", 8), ("Δεκέμβριο", 12)):
        assert fg.greek_month(word) == m, word


def test_comp():
    assert fg.parse_comp(LIB.read("comp", "2026-08"), "2026-08") == 5153
    assert fg.parse_comp(LIB.read("comp", "2023-05"), "2023-05") == 12957
    try:
        fg.parse_comp(LIB.read("comp", "2026-08"), "2026-07")
    except ValueError:
        pass
    else:
        raise AssertionError("a comp.xlsx for the wrong month must be rejected")


def test_bev_phev_pdfs():
    bev = fg.parse_plugin_pdf(LIB.read("bev", "2026-08"), "bev")
    assert bev.period == "2026-08"
    assert (bev.month, bev.ytd) == ({"BEV": 544}, {"BEV": 6824})
    assert bev.models_ok() and bev.gaps["BEV"] == (544, 544)
    # aggregate blocks (A TOTAL, SUV, …) are skipped: each model once
    assert bev.models["BEV"][("LEAPMOTOR", "T03")] == 12
    assert bev.models_ytd["BEV"][("LEAPMOTOR", "T03")] == 140
    assert bev.models["BEV"][("SMART", "FORTWO")] == 0          # YTD only
    assert sum(bev.models["BEV"].values()) == 544
    phev = fg.parse_plugin_pdf(LIB.read("phev", "2026-08"), "phev")
    assert phev.month == {"PHEV": 279} and phev.models_ok()
    assert phev.models["PHEV"][("BYD", "ATTO 2")] == 49


def test_fuel_index():
    """The fuel word is the last fuel token followed by a number — a model may
    be a number ("500") or end in "PHEV" itself."""
    w = lambda t: [{"text": x} for x in t.split()]
    assert fg._fuel_index(w("FIAT 500 BEV 1 0,56% 12 0,18%")) == 2
    assert fg._fuel_index(w("PEUGEOT 2008 BEV 3 0,55%")) == 2
    assert fg._fuel_index(w("FORD EXPLORER PHEV PHEV 6 4,05%")) == 3
    assert fg._fuel_index(w("SEGMENT 544 100,00%")) is None


def test_shifted_volume_line():
    """2026-03: 'MAZDA MAZDA6 BEV 700,00% 87,50% 300,00%' = 7 YTD, 3 in March."""
    f = quiet(fg.parse_plugin_pdf, LIB.read("bev", "2026-03"), "bev")
    assert f.month == {"BEV": 1015}
    assert f.models["BEV"][("MAZDA", "MAZDA6")] == 3
    assert f.models_ytd["BEV"][("MAZDA", "MAZDA6")] == 7
    assert f.models_ok()


def test_electric_pdf_and_greek_month():
    f = fg.parse_plugin_pdf(LIB.read("electric", "2023-05"), "electric")
    assert f.period == "2023-05"                      # printed as "ΜΑΥ '23"
    assert f.month == {"BEV": 720, "PHEV": 725}
    assert f.ytd == {"BEV": 2575, "PHEV": 2925}
    # 2022–2023 files list models SEAA could not split ("BEV-PHEV"); their
    # model tables then miss the summary and are not used for top lists
    assert not f.models_ok()


def test_press_release_2026():
    pr = fg.parse_press_release(LIB.read("pr", "2026-08"))
    assert pr.period == "2026-08"
    assert (pr.total, pr.bev, pr.phev) == (5159, 546, 279)
    assert pr.shares == {"PETROL": 18.8, "DIESEL": 1.3, "HEV": 59.8, "PHEV": 5.4,
                         "BEV": 10.6, "LPG": 4.1}, pr.shares


def test_press_release_2023():
    pr = fg.parse_press_release(LIB.read("pr", "2023-05"))
    assert pr.period == "2023-05"
    assert pr.total == 12958
    assert pr.bev is None and pr.phev is None        # counts only since 2025-11
    for k in ("PETROL", "DIESEL", "HEV", "LPG"):
        assert k in pr.shares, (k, pr.shares)
    assert "BEV" not in pr.shares                    # only a combined BEV-PHEV share


def test_apportion_and_split():
    assert fg.apportion(10, {"a": 1, "b": 1, "c": 1}) == {"a": 3, "b": 3, "c": 4}   # ties: by name
    assert fg.apportion(7, {"x": 0.5, "y": 0.25, "z": 0.25}) == {"x": 3, "y": 2, "z": 2}
    assert fg.apportion(0, {"a": 1}) == {"a": 0}
    shares = {"PETROL": 18.8, "DIESEL": 1.3, "HEV": 59.8, "PHEV": 5.4, "BEV": 10.6, "LPG": 4.1}
    s = fg.split_from_shares(5153, 544, 279, shares)
    assert sum(s.values()) == 5153 - 544 - 279
    assert abs(s["HEV"] - 3086) <= 10 and abs(s["PETROL"] - 965) <= 10   # ACEA: 3086 / 965
    assert s["OTHERS"] >= 0
    # unusable: a column missing, or shares that do not add up
    assert fg.split_from_shares(5153, 544, 279, {"PETROL": 18.8, "HEV": 59.8}) is None
    bad = dict(shares, HEV=79.8)
    assert fg.split_from_shares(5153, 544, 279, bad) is None


def test_month_rows():
    mo = quiet(fg.load_month, LIB, "2026-08", True)
    row, note = mo.row()
    assert not mo.provisional
    assert (row["BEV"], row["PHEV"], row["TOTAL"]) == (544, 279, 5153)   # = ACEA
    assert sum(row[k] for k in fg.FUELS) == 5153
    assert "derived" in note and "BEV.pdf" in note
    mo = quiet(fg.load_month, LIB, "2023-05", True)
    row, note = mo.row()
    assert (row["BEV"], row["PHEV"], row["TOTAL"]) == (720, 725, 12957)  # = ACEA
    assert "electric.pdf" in note


def test_provisional_from_press_release():
    lib = fg.Library()
    lib.entries[("pr", "2026-08")] = ("d", str(FIX / PR_AUG26))
    lib.read = lambda kind, period: Path(lib.entries[(kind, period)][1]).read_bytes()
    mo = quiet(fg.load_month, lib, "2026-08", True)
    row, note = mo.row()
    assert mo.provisional and note.startswith("provisional")
    assert (row["BEV"], row["PHEV"], row["TOTAL"]) == (546, 279, 5159)
    mo = quiet(fg.load_month, lib, "2026-08", False)
    assert mo.row() is None


def test_cross_check_aborts():
    mo = fg.Month("2026-08")
    mo.total, mo.bev, mo.phev = 5153, 544, 279
    mo.pr = fg.PressRelease()
    mo.pr.total, mo.pr.bev, mo.pr.phev = 5159, 546, 279
    mo.pr.shares = {"BEV": 10.6}
    fg.cross_check(mo)                                # within tolerance
    mo.pr.shares = {"BEV": 16.6}                      # misread share table
    try:
        fg.cross_check(mo)
    except ValueError:
        pass
    else:
        raise AssertionError("a BEV share far from the exact count must abort")


CSV_HEAD = ",".join(fg.COLUMNS) + "\r\n"


def test_upsert_precedence():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "Greece.csv"
        p.write_text(CSV_HEAD
                     + "2021-12,quarterly,Whole,ACEA,229.0,491.0,1703.0,2642.0,988.0,330.0,6385.0,\r\n"
                     + "2026-07,monthly,Whole,ACEA,994.0,1024.0,8478.0,2310.0,113.0,301.0,13220.0,x\r\n"
                     + "2026-08,monthly,Whole,Manual,1.0,1.0,1.0,1.0,1.0,1.0,6.0,\r\n",
                     encoding="utf-8", newline="")
        before = p.read_bytes().decode("utf-8")
        new = {"2026-07": fg.render_line("2026-07", {"BEV": 996, "PHEV": 1025, "TOTAL": 13252}, "n"),
               "2026-08": fg.render_line("2026-08", {"BEV": 544, "PHEV": 279, "TOTAL": 5153}, "n"),
               "2026-09": fg.render_line("2026-09", {"BEV": 1, "PHEV": 1, "TOTAL": 2}, "provisional — x")}
        stats = quiet(fg.upsert_lines, p, new, False)
        assert stats == {"added": 1, "updated": 1, "unchanged": 0, "skipped": 1}, stats
        lines = p.read_bytes().decode("utf-8").splitlines(keepends=True)
        assert lines[1] == before.splitlines(keepends=True)[1]     # untouched, byte for byte
        assert lines[2].startswith("2026-07,monthly,Whole,SEAA,996.0,1025.0,,,,,13252.0,")
        assert lines[2].endswith("\r\n")
        assert ",Manual," in lines[3]                              # foreign source kept
        assert lines[4].startswith("2026-09,") and lines[4].endswith("\r\n")
        # own final row: kept without --force; own provisional row: refreshed
        again = {"2026-07": fg.render_line("2026-07", {"BEV": 1, "PHEV": 1, "TOTAL": 2}, "n"),
                 "2026-09": fg.render_line("2026-09", {"BEV": 2, "PHEV": 2, "TOTAL": 4}, "n")}
        stats = quiet(fg.upsert_lines, p, again, False)
        assert stats["updated"] == 1 and stats["skipped"] == 1, stats


def test_empty_split_is_empty_not_zero():
    line = fg.render_line("2026-08", {"BEV": 544, "PHEV": 279, "TOTAL": 5153}, "n")
    assert line == "2026-08,monthly,Whole,SEAA,544.0,279.0,,,,,5153.0,n"


def test_month_selection():
    have = {"2026-07": {"source": "SEAA", "notes": "SEAA statistics"},
            "2026-08": {"source": "SEAA", "notes": "provisional — x"},
            "2026-06": {"source": "ACEA", "notes": ""},
            "2026-05": {"source": "Manual", "notes": ""}}
    assert not fg.needs_write(have, "2026-07")
    assert fg.needs_write(have, "2026-08")
    assert fg.needs_write(have, "2026-06")
    assert not fg.needs_write(have, "2026-05")
    assert fg.needs_write(have, "2026-09")
    import datetime as dt
    assert fg.target_month(dt.date(2026, 10, 9)) == "2026-09"
    assert fg.target_month(dt.date(2026, 1, 3)) == "2025-12"


def test_end_to_end():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "Greece.csv"
        p.write_text(CSV_HEAD
                     + "2026-08,monthly,Whole,ACEA,544.0,279.0,3086.0,965.0,68.0,211.0,5153.0,acea\r\n",
                     encoding="utf-8", newline="")
        store = Path(d) / "market"
        old = market_top.MARKET_DIR
        market_top.MARKET_DIR = store
        try:
            changed, months = quiet(fg.run, LIB, ["2026-08"], False, True, p)
        finally:
            market_top.MARKET_DIR = old
        assert changed
        row = p.read_text(encoding="utf-8").splitlines()[1].split(",")
        assert row[:5] == ["2026-08", "monthly", "Whole", "SEAA", "544.0"] and row[10] == "5153.0"
        top = json.loads((store / "greece_top.json").read_text(encoding="utf-8"))
        assert top["as_of"] == "2026-08" and top["classes"]["BEV"]["units"] == 544
        assert top["classes"]["PHEV"]["units"] == 279


def main():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} passed")


if __name__ == "__main__":
    main()
