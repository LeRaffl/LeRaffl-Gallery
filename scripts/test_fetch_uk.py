#!/usr/bin/env python3
"""Regression tests for scripts/fetch_uk.py (no network).

Run:  python scripts/test_fetch_uk.py

SMMT's release is hand-made HTML, and its failure modes are quiet: a row
relabelled ("ALL PETROL"), a misspelled or missing month above the table, a
column added in front of the counts, a "Grand Total" row inside the brand
table. These cases pin every fuel label, each header layout seen since
2024-11, the column-shift checks, the year-to-date and plausibility guards,
the line-level upsert, the brand / top-model tables and the self-throttle.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_uk as fu  # noqa: E402
import market_top  # noqa: E402

# Every SMMT label the fetcher accepts, and the column it lands in.
LABEL_CASES = {
    "BEV": "BEV", "PHEV": "PHEV", "HEV": "HEV",
    "PETROL": "PETROL", "DIESEL": "DIESEL",
    "ALL PETROL": "PETROL", "ALL DIESEL": "DIESEL",
    "MHEV PETROL": "PETROL", "MHEV DIESEL": "DIESEL",
}

# September 2026 as published (and as in data/UK.csv).
SEP26 = [("BEV", 99199, 72775, "36.3%", "28.3%"), ("HEV", 45838, 47865, "-4.2%", "13.1%"),
         ("PHEV", 59563, 38261, "55.7%", "17.0%"), ("PETROL", 131861, 141287, "-6.7%", "37.6%"),
         ("DIESEL", 14057, 12605, "11.5%", "4.0%")]
SEP26_TOTAL = (350518, 312793)


def fuel_html(head: str, years=(2026, 2025), rows=SEP26, total=SEP26_TOTAL) -> str:
    """An SMMT fuel table in the release's own markup."""
    cells = lambda tag, xs: "<tr>" + "".join(f"<{tag}><span>{x}</span></{tag}>" for x in xs) + "</tr>"
    out = ['<table width="528"><tbody>', cells("th", ["", head, "", "", "", ""]),
           cells("th", ["", years[0], years[1], "% change",
                        f"Mkt share &#8217;{years[0] % 100}", f"Mkt share &#8217;{years[1] % 100}"])]
    for label, a, b, pct, share in rows:
        out.append(cells("td", [label, f"{a:,}", f"{b:,}", pct, share, "x"]))
    out.append(cells("td", ["<strong>TOTAL</strong>", f"<strong>{total[0]:,}</strong>",
                            f"{total[1]:,}", "12.1%", "", ""]))
    return "".join(out) + "</tbody></table>"


def table(html: str) -> list:
    return fu.tables_of(html)[0]


# ── labels and header layouts ──────────────────────────────────────────────

def test_every_label_has_a_case():
    assert set(LABEL_CASES) == set(fu.FUEL_LABELS), set(LABEL_CASES) ^ set(fu.FUEL_LABELS)


def test_label_mapping():
    for label, col in LABEL_CASES.items():
        rows = [(col if c == col else c, a, b, p, s) for c, a, b, p, s in SEP26]
        rows = [(label if c == col else c, a, b, p, s) for c, a, b, p, s in rows]
        f = fu.parse_fuel_table(table(fuel_html("September", rows=rows)))
        assert f["cur"][col] == dict((r[0], r[1]) for r in SEP26)[col], label


def test_september_2026_reproduces_the_csv_row():
    f = fu.month_table(fuel_html("September"))
    assert fu.period_of(f) == "2026-09"
    assert fu.validate(f) == []
    assert fu.to_counts(f["cur"]) == {"BEV": 99199, "PHEV": 59563, "HEV": 45838,
                                      "PETROL": 131861, "DIESEL": 14057, "OTHERS": 0,
                                      "TOTAL": 350518}
    assert fu.to_counts(f["prev"])["TOTAL"] == 312793


def test_month_names_tolerate_typos_and_abbreviations():
    assert fu.month_in("Feburary") == 2          # 2025-02 release
    assert fu.month_in("Sept") == 9
    assert fu.month_in("  November ") == 11
    assert fu.month_in("2026 2025 % change Mkt share") is None
    assert fu.month_in("Market share") is None   # not March


def test_ytd_table_is_recognised_and_attached():
    page = fuel_html("September") + fuel_html("Year to date", rows=[
        ("BEV", 454945, 349410, "", ""), ("HEV", 240254, 222649, "", ""),
        ("PHEV", 244761, 172592, "", ""), ("ALL PETROL", 721614, 749771, "", ""),
        ("ALL DIESEL", 77679, 83652, "", "")], total=(1739253, 1578074))
    f = fu.month_table(page)
    assert f["kind"] == "month" and f["ytd"]["kind"] == "ytd"
    assert f["ytd"]["cur"]["PETROL"] == 721614 and f["ytd"]["cur"]["TOTAL"] == 1739253
    assert fu.is_ytd("YEAR-TO-DATE") and fu.is_ytd("Year to date")


def test_header_without_month_needs_the_publication_window():
    page = fuel_html("")                          # 2025-08 / 2026-06 layout
    try:
        fu.month_table(page)
        raise AssertionError("a month-less table without a hint must raise")
    except RuntimeError:
        pass
    f = fu.month_table(page, hint="2026-06")
    assert fu.period_of(f) == "2026-06" and f["month_from"]
    try:
        fu.month_table(page, hint="2025-06")       # year column says 2026
        raise AssertionError("a hint with the wrong year must raise")
    except RuntimeError:
        pass


def test_unknown_row_aborts():
    rows = SEP26 + [("HYDROGEN", 3, 1, "", "")]
    try:
        fu.parse_fuel_table(table(fuel_html("September", rows=rows, total=(350521, 312794))))
        raise AssertionError("an unknown SMMT row must abort")
    except RuntimeError as e:
        assert "HYDROGEN" in str(e)


def test_missing_row_aborts():
    try:
        fu.parse_fuel_table(table(fuel_html("September", rows=SEP26[:4])))
        raise AssertionError("a missing fuel row must abort")
    except RuntimeError as e:
        assert "DIESEL" in str(e)


def test_non_fuel_tables_are_ignored():
    page = ("<table><tr><th>September</th></tr><tr><td>PRIVATE</td><td>149,158</td>"
            "<td>130,955</td></tr><tr><td>Total</td><td>350,518</td><td>1</td></tr></table>")
    assert fu.fuel_tables(page) == []


# ── column-shift and consistency checks ────────────────────────────────────

def test_swapped_year_columns_are_caught():
    swapped = [(c, b, a, p, s) for c, a, b, p, s in SEP26]
    f = fu.parse_fuel_table(table(fuel_html("September", rows=swapped,
                                            total=SEP26_TOTAL[::-1])))
    assert any("columns shifted" in p for p in fu.validate(f))


def test_fuels_above_total_are_caught():
    f = fu.parse_fuel_table(table(fuel_html("September", total=(350000, 312793))))
    assert any("> TOTAL" in p for p in fu.validate(f))
    assert fu.to_counts(f["cur"])["OTHERS"] < 0


def test_summed_rows_skip_the_percentage_check():
    rows = SEP26[:3] + [("PETROL", 120000, 130000, "-9%", "34.2%"),
                        ("MHEV PETROL", 11861, 11287, "5%", "3.4%"), SEP26[4]]
    f = fu.parse_fuel_table(table(fuel_html("September", rows=rows)))
    assert f["cur"]["PETROL"] == 131861 and "PETROL" not in f["share"]
    assert fu.validate(f) == []


# ── checks against the committed history ───────────────────────────────────

def have_from(rows: dict) -> dict:
    out = {}
    for p, (bev, phev, hev, pet, die, tot) in rows.items():
        out[p] = {"period": p, "source": "SMMT", "BEV": str(bev), "PHEV": str(phev),
                  "HEV": str(hev), "PETROL": str(pet), "DIESEL": str(die),
                  "OTHERS": "", "TOTAL": str(tot)}
    return out


def test_ytd_check_exact_and_off():
    f = fu.month_table(fuel_html("February", rows=[
        ("BEV", 20, 1, "", ""), ("PHEV", 10, 1, "", ""), ("HEV", 10, 1, "", ""),
        ("PETROL", 50, 1, "", ""), ("DIESEL", 10, 1, "", "")], total=(100, 5))
        + fuel_html("Year to date", rows=[
            ("BEV", 30, 1, "", ""), ("PHEV", 20, 1, "", ""), ("HEV", 20, 1, "", ""),
            ("PETROL", 110, 1, "", ""), ("DIESEL", 20, 1, "", "")], total=(200, 5)))
    have = have_from({"2026-01": (10, 10, 10, 60, 10, 100)})
    msg, dev = fu.ytd_check(f, have)
    assert dev == 0 and ";" not in msg, msg
    have = have_from({"2026-01": (10, 10, 10, 30, 10, 70)})   # January 30 % lower
    _, dev = fu.ytd_check(f, have)
    assert dev > fu.YTD_ABORT
    _, dev = fu.ytd_check(f, {})
    assert dev is None                                       # skipped, not failed


def test_plausibility_uses_the_same_month_a_year_earlier():
    have = have_from({"2025-09": (1, 1, 1, 1, 1, 312891)})
    assert abs(fu.plausibility("2026-09", 350518, have) - 1.12) < 0.01
    assert fu.plausibility("2026-10", 1, have) is None


def test_process_guards_and_line():
    with tempfile.TemporaryDirectory() as d:
        have = have_from({"2025-09": (72779, 38308, 47885, 141310, 12609, 312891)})
        report: list = []
        line, counts = fu.process("2026-09", "https://x/rel/", fuel_html("September"),
                                  have, False, report)
        assert line == ("2026-09,monthly,Whole,SMMT,99199,59563,45838,131861,14057,0,"
                        "350518,https://x/rel/")
        assert any("restated" in r for r in report)
        have = have_from({"2025-09": (1, 1, 1, 1, 1, 100000)})   # ×3.5
        try:
            fu.process("2026-09", "u", fuel_html("September"), have, False, [])
            raise AssertionError("an implausible TOTAL must abort")
        except RuntimeError:
            pass
        fu.process("2026-09", "u", fuel_html("September"), have, True, [])   # --force
        try:
            fu.process("2026-08", "u", fuel_html("September"), {}, False, [])
            raise AssertionError("a release for another month must abort")
        except RuntimeError:
            pass
        assert Path(d).exists()


# ── CSV upsert (invariant 2) ───────────────────────────────────────────────

CSV_TEXT = ("period,time_interval,variant,source,BEV,PHEV,HEV,PETROL,DIESEL,OTHERS,TOTAL,notes\n"
            "2015-01,monthly,Whole,SMMT,512.0,1203.0,2883.0,0.0,0.0,,164856.0,\n"
            "2026-08,monthly,Whole,SMMT,28063,13707,11940,36048,4478,0,94236,https://a/\n")


def test_upsert_adds_and_keeps_lines_byte_identical():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "UK.csv"
        p.write_text(CSV_TEXT, encoding="utf-8")
        new = "2026-09,monthly,Whole,SMMT,1,1,1,1,1,0,5,u"
        assert fu.upsert_lines(p, {"2026-09": new}, False)["added"] == 1
        assert p.read_text(encoding="utf-8") == CSV_TEXT + new + "\n"
        other = "2026-08,monthly,Whole,SMMT,1,1,1,1,1,0,5,u"
        assert fu.upsert_lines(p, {"2026-08": other}, False)["skipped"] == 1
        assert fu.upsert_lines(p, {"2026-08": other}, True)["updated"] == 1
        assert "2015-01,monthly,Whole,SMMT,512.0,1203.0" in p.read_text(encoding="utf-8")


def test_upsert_rejects_a_foreign_header():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "UK.csv"
        p.write_text("period,variant,BEV\n", encoding="utf-8")
        try:
            fu.upsert_lines(p, {"2026-09": "x"}, False)
            raise AssertionError("a different header must abort")
        except SystemExit:
            pass


# ── brand + top-model tables ───────────────────────────────────────────────

def marque_html(head: str, rows: list, total: int) -> str:
    tr = lambda xs: "<tr>" + "".join(f"<td>{x}</td>" for x in xs) + "</tr>"
    out = ["<table>", tr(["", head, "% Change"]),
           tr(["MARQUE", "2026", "% Market share", "2025", "% Market share"])]
    out += [tr([n, f"{u:,}", "0.1", "1", "0.1", "1"]) for n, u in rows]
    out.append(tr(["Grand Total", f"{total:,}", "100", "1", "100", "1"]))
    return "".join(out) + "</table>"


def top_html(head: str, rows: list) -> str:
    tr = lambda xs: "<tr>" + "".join(f"<td>{x}</td>" for x in xs) + "</tr>"
    return ("<table>" + tr(["", head]) + "".join(tr([i, n, f"{u:,}"])
                                                 for i, (n, u) in enumerate(rows, 1))
            + "</table>")


SMALL = [("BEV", 30, 1, "", ""), ("PHEV", 10, 1, "", ""), ("HEV", 10, 1, "", ""),
         ("PETROL", 40, 1, "", ""), ("DIESEL", 10, 1, "", "")]
MODELS = [("TESLA Model 3", 9), ("MERCEDES-BENZ CLA", 8), ("MG HS", 7), ("FORD Puma", 6),
          ("KIA Sportage", 5)]


def data_page(month_total=100) -> str:
    return (fuel_html("September", rows=SMALL, total=(month_total, 5))
            + fuel_html("Year to date", rows=[(c, 2 * a, 1, "", "") for c, a, *_ in SMALL],
                        total=(2 * month_total, 5))
            + marque_html("September", [("Tesla", 30), ("Bmw", 20), ("Mercedes-Benz", 25),
                                        ("Other British", 5), ("Other Imports", 20)], 100)
            + marque_html("YEAR-TO-DATE", [("Tesla", 50), ("Bmw", 60), ("Mercedes-Benz", 40),
                                           ("Other Imports", 50)], 200)
            + top_html("September", MODELS) + top_html("Year-to-date", MODELS)
            + top_html("", [("BYD SEAL", 3)] * 6))


def test_marque_table_others_and_grand_total():
    m = fu.parse_marque(table(marque_html("September", [("Bmw", 20), ("Other British", 5)], 25)))
    assert m["brands"] == {"BMW": 20} and m["others"] == 5 and m["total"] == 25
    try:
        fu.parse_marque(table(marque_html("September", [("Bmw", 20)], 25)))
        raise AssertionError("brands + others ≠ Grand Total must abort")
    except RuntimeError:
        pass


def test_split_model_against_marque_names():
    names = ["MERCEDES-BENZ", "MG", "MINI"]
    assert fu.split_model("MERCEDES-BENZ A Class", names) == ("MERCEDES-BENZ", "A CLASS")
    assert fu.split_model("MG HS", names) == ("MG", "HS")
    assert fu.split_model("JAECOO 7", names) == ("JAECOO", "7")
    assert fu.split_model("TESLA model Y", names) == ("TESLA", "MODEL Y")


def test_top_file_headline_is_year_to_date():
    top, store = fu.build_uk_top(data_page())
    assert top["as_of"] == "2026-09" and top["window"] == {"from": "2026-01", "to": "2026-09",
                                                          "months": 9}
    c = top["classes"]["ALL"]
    assert top["total_registrations"] == 200 and c["units"] == 200
    assert [b["brand"] for b in c["brands"]] == ["BMW", "TESLA", "MERCEDES-BENZ"]
    assert c["models"][0] == {"brand": "TESLA", "model": "MODEL 3", "units": 9,
                              "share_of_class": 0.045}
    assert set(top["classes"]) == {"ALL"}          # never mixed with fuel classes
    month = top["months"][0]
    assert month["period"] == "2026-09" and month["total_registrations"] == 100
    assert [b["brand"] for b in month["classes"]["ALL"]["brands"]] == ["TESLA", "MERCEDES-BENZ", "BMW"]
    assert "2026-09" in store


def test_top_file_survives_the_month_store_round_trip():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "uk_months.json"
        _, store = fu.build_uk_top(data_page())
        market_top.save_store(path, store, "UK", "SMMT")
        again = market_top.load_store(path)
        assert again == store
        top, _ = fu.build_uk_top(data_page(), again)
        assert top["months"][0]["classes"]["ALL"]["units"] == 100


def test_top_file_rejects_a_marque_total_off_the_fuel_table():
    try:
        fu.build_uk_top(data_page(month_total=101))
        raise AssertionError("marque Grand Total ≠ fuel TOTAL must abort")
    except RuntimeError:
        pass


# ── self-throttle (no network) ─────────────────────────────────────────────

def test_throttle_needs_no_network():
    with tempfile.TemporaryDirectory() as d:
        csvp = Path(d) / "UK.csv"
        csvp.write_text(CSV_TEXT, encoding="utf-8")
        topp = Path(d) / "uk_top.json"
        topp.write_text(json.dumps({"as_of": "2026-08", "months": []}), encoding="utf-8")
        out = Path(d) / "out.txt"
        old_top, old_get = fu.TOP_PATH, fu.http_get
        fu.TOP_PATH = topp
        fu.http_get = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used"))
        try:
            assert fu.main(["--csv", str(csvp), "--period", "2026-08",
                            "--github-output", str(out), "--summary", ""]) == 0
        finally:
            fu.TOP_PATH, fu.http_get = old_top, old_get
        assert out.read_text(encoding="utf-8") == "changed=false\nchanged_variants=[]\n"


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
