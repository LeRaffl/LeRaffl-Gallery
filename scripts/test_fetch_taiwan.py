#!/usr/bin/env python3
"""Regression tests for scripts/fetch_taiwan.py (no network).

Run:  python scripts/test_fetch_taiwan.py

The fetcher's failure modes are silent: a new THB fuel category, a relabelled
id, a look-alike label (電能 vs 電能(增程) vs 汽油(電能)) or a misread ROC date
would quietly move cars between columns or months. These cases pin every
fuel mapping, the ROC calendar, the cell format, the parsers of the database
page and of Display.json (with schema drift), the month checks, the
cross-check against the brand table, the completeness guard, the line-level
upsert, the brand names of the top-brands table and one end-to-end offline
run.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_taiwan as ft  # noqa: E402
import market_top  # noqa: E402

FUEL_CASES = {
    "電能": "BEV",
    "汽油/電能": "PHEV", "柴油/電能": "PHEV", "電能/汽油": "PHEV", "電能/柴油": "PHEV",
    "電能(增程)": "EREV",
    "汽油(油電)": "HEV", "柴油(油電)": "HEV",
    "汽油(電能)": "HEV",          # driven only by the motor, fuel only: e-POWER, not a BEV
    "汽油": "PETROL", "柴油": "DIESEL",
    "液化石油氣": "LPG", "汽油/液化石油氣": "LPG",
}


def test_every_fuel_rule_has_a_case():
    assert set(FUEL_CASES) == set(ft.FUEL_COLUMN), set(FUEL_CASES) ^ set(ft.FUEL_COLUMN)


def test_fuel_mapping():
    for label, col in FUEL_CASES.items():
        c, unknown = ft.to_counts({label: 7, "總計": 7})
        assert c[col] == 7 and c["TOTAL"] == 7 and not unknown, (label, c)
    # full-width parentheses / slash on a page are the same category
    assert ft.norm_label("電能（增程）") == "電能(增程)"
    assert ft.norm_label(" 汽油／電能 ") == "汽油/電能"
    assert ft.norm_label("電能&#x28;增程&#x29;") == "電能(增程)"


def test_unknown_fuel_is_others_and_listed():
    c, unknown = ft.to_counts({"總計": 10, "汽油": 7, "氫能": 3})      # hydrogen: not mapped
    assert c["OTHERS"] == 3 and c["PETROL"] == 7 and unknown == {"氫能": 3}
    c, unknown = ft.to_counts({"總計": 7, "汽油": 7, "氫能": 0})
    assert c["OTHERS"] == 0 and unknown == {}


def test_roc_calendar():
    assert ft.roc_to_period("115-08-00") == "2026-08"
    assert ft.roc_to_period("101-01-00") == "2012-01"
    assert ft.roc_to_period("99-12-00") == "2010-12"
    assert ft.roc_to_period("115-00-00") is None          # a year row
    assert ft.roc_to_period("115-13-00") is None
    assert ft.period_to_roc("2026-08") == "115-08-00"
    assert ft.period_to_roc("2021-01") == "110-01-00"
    for bad in ("2026-08", "115/08", ""):
        try:
            ft.roc_to_period(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_cells():
    assert ft.parse_count("31,361 ") == 31361
    assert ft.parse_count("1,093") == 1093
    assert ft.parse_count("-") == 0 and ft.parse_count("") == 0 and ft.parse_count(None) == 0
    for bad in ("x", "1.5", "…"):
        try:
            ft.parse_count(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_month_helpers():
    assert ft.months_between("2025-11", "2026-02") == ["2025-11", "2025-12", "2026-01", "2026-02"]
    assert ft.shift_month("2026-08", 1 - ft.LOOKBACK_MONTHS) == "2024-09"
    assert ft.shift_month("2026-01", -1) == "2025-12"


PAGE = """
<select id="select-period-start" title="從">
<option value="115-08-00">115&#x5E74;08&#x6708;</option>
<option value="115-07-00">115&#x5E74;07&#x6708;</option>
</select>
<input type="checkbox" class="form-check-input checkbox-set-column" id="c1" value="834" checked>
<label class="form-check-label" for="c1">總計</label>
<input type="checkbox" class="form-check-input checkbox-set-column" id="c2" value="844">
<label class="form-check-label" for="c2">
    小客車
</label>
<input type="checkbox" class="form-check-input checkbox-set-column" id="c3" value="850">
<label for="c3">小貨車</label>
<input type="checkbox" class="checkbox-set-code-list-value form-check-input" id="f0" value="1170">
<label for="f0">總計</label>
<input type="checkbox" class="checkbox-set-code-list-value" id="f1" value="1173">
<label for="f1">電能</label>
<input type="checkbox" class="checkbox-set-code-list-value" id="f2" value="1179">
<label for="f2">電能（增程）</label>
<input type="checkbox" class="other-box" id="o1" value="9"><label for="o1">不是</label>
"""


def test_parse_display_page():
    d = ft.parse_display_page(PAGE)
    assert d["newest"] == "2026-08"
    assert d["columns"] == {"總計": "834", "小客車": "844", "小貨車": "850"}
    assert d["codes"] == {"總計": "1170", "電能": "1173", "電能(增程)": "1179"}
    assert ft.parse_display_page("<html></html>")["newest"] is None


def test_resolve_and_schema_drift():
    d = ft.parse_display_page(PAGE)
    assert ft.resolve(d, ["小客車"], "columns", 104) == {"小客車": "844"}
    try:
        ft.resolve(d, ["大客車"], "columns", 104)
    except SystemExit as e:
        assert "Schema drift" in str(e)
    else:
        raise AssertionError("missing label must abort")


def json_doc(rows, col="844", codes=None):
    codes = codes or {"1170": "總計", "1173": "電能", "1171": "汽油"}
    return {"data": rows,
            "nameMapping": {"columnNameMappings": {col: "小客車"},
                            "codeListMappings": {"78": {"name": "能源別", "nameMappings": codes}}}}


def test_parse_display_json():
    names = {"1170": "總計", "1173": "電能", "1171": "汽油"}
    doc = json_doc([
        {"date": "115-00-00", "Column_844_78.1170": "999 "},                    # year row
        {"date": "115-07-00", "Column_844_78.1170": "1,200 ", "Column_844_78.1173": "200 ",
         "Column_844_78.1171": "1,000 "},
        {"date": "115-08-00", "Column_844_78.1170": "50 ", "Column_844_78.1173": "-",
         "Column_844_78.1171": "50 "}])
    got = ft.parse_display_json(doc, "844", names)
    assert got == {"2026-07": {"總計": 1200, "電能": 200, "汽油": 1000},
                   "2026-08": {"總計": 50, "電能": 0, "汽油": 50}}
    # an id the JSON names differently from the page: schema drift
    try:
        ft.parse_display_json(json_doc([], codes={"1173": "柴油"}), "844", names)
    except SystemExit as e:
        assert "Schema drift" in str(e)
    else:
        raise AssertionError("relabelled id must abort")
    # the API answered for another item: abort
    try:
        ft.parse_display_json(json_doc([{"date": "115-08-00", "Column_850_78.1170": "1 "}]),
                              "844", names)
    except SystemExit as e:
        assert "asked for 844" in str(e)
    else:
        raise AssertionError("wrong item must abort")


def full_cells(**over):
    cells = {f: 0 for f in ft.FUEL_COLUMN}
    cells.update(over)
    cells["總計"] = sum(n for k, n in cells.items() if k != "總計")
    return cells


def test_check_month():
    ok = full_cells(電能=3, 汽油=7)
    assert ft.check_month("2026-08", "Whole", ok) == []
    bad = dict(ok, 總計=11)
    assert "sum to 10" in ft.check_month("2026-08", "Whole", bad)[0]
    gone = dict(ok)
    gone.pop("電能(增程)")
    assert "missing" in ft.check_month("2026-08", "Whole", gone)[0]
    assert "no 總計" in ft.check_month("2026-08", "Whole", {"汽油": 1})[0]


def test_cross_check():
    fuel = {"Whole": {"2026-07": 30000, "2026-08": 25565}, "Vans": {"2026-08": 2000}}
    same = {"Whole": {"2026-07": 30000, "2026-08": 25565}, "Vans": {"2026-08": 2000}}
    n, small, bad = ft.cross_check(fuel, same, ["2026-07", "2026-08"])
    assert (n, small, bad) == (3, [], [])
    near = {"Whole": {"2026-07": 30002, "2026-08": 25565}, "Vans": {"2026-08": 2000}}
    n, small, bad = ft.cross_check(fuel, near, ["2026-07", "2026-08"])
    assert len(small) == 1 and not bad
    far = {"Whole": {"2026-07": 30000, "2026-08": 25000}, "Vans": {}}
    n, small, bad = ft.cross_check(fuel, far, ["2026-07", "2026-08"])
    assert len(bad) == 2 and "no brand-table total" in bad[1]


def test_completeness_guard():
    have = {f"2025-{m:02d}": {"TOTAL": "30000.0"} for m in range(1, 13)}
    assert ft.median_fraction("2026-01", 30000, have) == 1.0
    assert ft.median_fraction("2026-02", 11000, have) < ft.MIN_MONTH_FRACTION
    assert ft.median_fraction("2026-02", 17000, have) > ft.MIN_MONTH_FRACTION   # Lunar New Year
    assert ft.median_fraction("2025-03", 1, have) is None                        # < 6 months before


def test_render_and_upsert_line_level():
    c = ft.empty_counts()
    c.update(BEV=3226, PHEV=284, HEV=10315, PETROL=11361, DIESEL=379, TOTAL=25565)
    line = ft.render_line("2026-08", "Whole", c)
    assert line == ("2026-08,monthly,Whole,THB register via MOTC statistics database,"
                    "3226.0,284.0,0.0,10315.0,11361.0,379.0,0.0,0.0,25565.0,")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "Taiwan.csv"
        untouched = "2021-01,monthly,Whole,hand,1.0,0.0,0.0,0.0,9.0,0.0,0.0,0.0,10.0,"
        p.write_text(",".join(ft.CSV_COLUMNS) + "\n" + untouched + "\n", encoding="utf-8")
        stats = ft.upsert_lines(p, {("2026-08", "Whole"): line}, False)
        assert stats["added"] == 1
        stats = ft.upsert_lines(p, {("2021-01", "Whole"): line.replace("2026-08", "2021-01")},
                                False)
        assert stats["skipped"] == 1                               # foreign source kept
        assert p.read_text(encoding="utf-8").splitlines()[1] == untouched
        stats = ft.upsert_lines(p, {("2026-08", "Whole"): line}, False)
        assert stats == {"added": 0, "updated": 0, "unchanged": 1, "skipped": 0}
        c2 = dict(c, BEV=3200, PETROL=11387)
        assert ft.revisions(p, {("2026-08", "Whole"): ft.render_line("2026-08", "Whole", c2)}) \
            == ["2026-08 Whole: BEV 3226→3200, PETROL 11361→11387"]


def test_display_brand():
    assert ft.display_brand("國瑞") == "Toyota" == ft.display_brand("TOYOTA")
    assert ft.display_brand("三陽") == "Hyundai" == ft.display_brand("HYUNDAI")
    assert ft.display_brand("本田") == "Honda" and ft.display_brand("福特六和") == "Ford"
    assert ft.display_brand("中華") == "China Motor (CMC)"          # not merged
    assert ft.display_brand("TESLA") == "Tesla"
    assert ft.display_brand("MERCEDES-BENZ") == "Mercedes-Benz"
    assert ft.display_brand("BMW") == "BMW" and ft.display_brand("MINI") == "MINI"
    assert ft.display_brand("LANDROVER") == "Land Rover"
    assert ft.display_brand("寶立華") == "寶立華"                   # unknown Chinese name kept


def write_dump(d: Path, months: dict) -> None:
    """A minimal --from-dir dump: two pages and one JSON per table/variant."""
    kinds = {"Whole": ("小客車", "844", "1066"), "Vans": ("小貨車", "850", "1072"),
             "HDV": ("大貨車", "841", "1063"), "Buses": ("大客車", "836", "1058")}
    fuel_ids = {"總計": "1170", **{f: str(1171 + i) for i, f in enumerate(ft.FUEL_COLUMN)}}

    def page(cols, codes):
        out = ['<select id="select-period-start">']
        out += [f'<option value="{ft.period_to_roc(p)}">x</option>' for p in sorted(months, reverse=True)]
        out.append("</select>")
        for i, (lab, cid) in enumerate(cols.items()):
            out.append(f'<input class="checkbox-set-column" id="k{i}" value="{cid}">'
                       f'<label for="k{i}">{lab}</label>')
        for i, (lab, cid) in enumerate(codes.items()):
            out.append(f'<input class="checkbox-set-code-list-value" id="f{i}" value="{cid}">'
                       f'<label for="f{i}">{lab}</label>')
        return "\n".join(out)
    (d / "display_104.html").write_text(page({k[0]: k[1] for k in kinds.values()}, fuel_ids),
                                        encoding="utf-8")
    brand_ids = {"廠牌別總計": "1794", "國瑞": "1795", "TESLA": "1796", "其他": "1797"}
    (d / "display_118.html").write_text(page({k[0]: k[2] for k in kinds.values()}, brand_ids),
                                        encoding="utf-8")
    for v, (kind, fid, bid) in kinds.items():
        rows, brows = [], []
        for p, cells in sorted(months.items()):
            cells = {k: n // (1 if v == "Whole" else 10) for k, n in cells.items()}
            cells["總計"] = sum(n for k, n in cells.items() if k != "總計")
            rows.append({"date": ft.period_to_roc(p),
                         **{f"Column_{fid}_78.{fuel_ids[k]}": f"{n:,} " if n else "-"
                            for k, n in cells.items()}})
            tot = cells["總計"]
            b = {"廠牌別總計": tot, "國瑞": tot // 2, "TESLA": cells["電能"],
                 "其他": tot - tot // 2 - cells["電能"]}
            brows.append({"date": ft.period_to_roc(p),
                          **{f"Column_{bid}_80.{brand_ids[k]}": f"{n:,} " for k, n in b.items()}})
        (d / f"fuel_{v}.json").write_text(json.dumps(json_doc(
            rows, fid, {i: l for l, i in fuel_ids.items()})), encoding="utf-8")
        (d / f"brand_{v}.json").write_text(json.dumps(json_doc(
            brows, bid, {i: l for l, i in brand_ids.items()})), encoding="utf-8")


def test_end_to_end_offline():
    months = {"2026-07": full_cells(電能=3000, 汽油=20000, **{"汽油(油電)": 9000, "電能/汽油": 300}),
              "2026-08": full_cells(電能=3226, 汽油=11361, 柴油=379,
                                    **{"汽油(油電)": 10000, "汽油(電能)": 315, "汽油/電能": 20,
                                       "電能/汽油": 264})}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        dump = tmp / "dump"
        dump.mkdir()
        write_dump(dump, months)
        repo_before, top_before, first_before = ft.REPO, ft.TOP_PATH, ft.FIRST_PERIOD
        argv_before = sys.argv
        ft.REPO, ft.TOP_PATH = tmp, tmp / "market" / "taiwan_top.json"
        ft.FIRST_PERIOD = "2026-07"           # the dump holds two months
        out = tmp / "gh_output"
        try:
            sys.argv = ["fetch_taiwan.py", "--backfill", "--from-dir", str(dump),
                        "--github-output", str(out), "--step-summary", ""]
            assert ft.main() == 0
        finally:
            ft.REPO, ft.TOP_PATH, sys.argv = repo_before, top_before, argv_before
            ft.FIRST_PERIOD = first_before
        lines = (tmp / "data/Taiwan.csv").read_text(encoding="utf-8").splitlines()
        assert lines[0] == ",".join(ft.CSV_COLUMNS)
        aug = dict(zip(ft.CSV_COLUMNS, lines[2].split(",")))
        assert aug["period"] == "2026-08" and aug["BEV"] == "3226.0"
        assert aug["PHEV"] == "284.0" and aug["HEV"] == "10315.0" and aug["TOTAL"] == "25565.0"
        assert (tmp / "data/Taiwan_Buses.csv").exists() and (tmp / "data/Taiwan_HDV.csv").exists()
        gh = out.read_text(encoding="utf-8")
        assert "changed=true" in gh and '"Buses", "HDV", "Vans", "Whole"' in gh
        top = json.loads((tmp / "market/taiwan_top.json").read_text(encoding="utf-8"))
        assert list(top["classes"]) == [market_top.ALL]
        assert top["classes"]["ALL"]["brands"][0]["brand"] == "Toyota"
        # a second run: nothing new, the self-throttle exits before any table query
        for f in dump.glob("*.json"):
            f.unlink()
        sys.argv = ["fetch_taiwan.py", "--from-dir", str(dump), "--github-output", str(out)]
        ft.REPO = tmp
        try:
            assert ft.main() == 0
        finally:
            ft.REPO, sys.argv = repo_before, argv_before
        assert out.read_text(encoding="utf-8").endswith("changed=false\nchanged_variants=[]\n")


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
