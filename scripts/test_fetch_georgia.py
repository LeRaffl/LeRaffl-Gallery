#!/usr/bin/env python3
"""Regression tests for scripts/fetch_georgia.py (no network).

Run:  python scripts/test_fetch_georgia.py

Geostat's API answers JSON, so the failure modes are a renamed or added fuel
category, an empty answer for a quarter the picker already lists, a picker
that changes shape, and a partial upload. These cases pin every category
mapping, the picker parser, the year cross-check, the completeness guard, the
line-level upsert (untouched lines byte-identical, differing rows kept unless
--force), the treemap → brand/model units and the self-throttle — replayed
through --from-dir exactly as an offline debugging run would.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_georgia as fg  # noqa: E402
import market_top  # noqa: E402

# Every Geostat category the fetcher accepts, and the column it lands in.
CATEGORY_CASES = {
    "Electric": "BEV", "Hybrid": "HEV", "Gasoline": "PETROL",
    "Gasoline-gas": "PETROL", "Diesel": "DIESEL", "Gas": "OTHERS", "Others": "OTHERS",
}

# 2026-Q2 as Geostat publishes it (and as in data/Georgia.csv, 2026-05).
Q2_26 = [{"name": "Gasoline", "value": 22349}, {"name": "Hybrid", "value": 11092},
         {"name": "Diesel", "value": 5093}, {"name": "Electric", "value": 3724},
         {"name": "Gasoline-gas", "value": 1034}, {"name": "Gas", "value": 28},
         {"name": "Others", "value": 129}]
Q1_26 = [{"name": "Gasoline", "value": 20019}, {"name": "Hybrid", "value": 8191},
         {"name": "Diesel", "value": 4265}, {"name": "Electric", "value": 2109},
         {"name": "Gasoline-gas", "value": 593}, {"name": "Gas", "value": 33},
         {"name": "Others", "value": 90}]

HEADER = "period,time_interval,variant,source,BEV,HEV,PETROL,DIESEL,OTHERS,TOTAL,notes"
CSV_TEXT = "\n".join([
    HEADER,
    "2025-05,quarterly,Whole,National Statistics Office of Georgia,1907.0,9563.0,25144.0,5637.0,194.0,42445.0,",
    "2025-08,quarterly,Whole,National Statistics Office of Georgia,2150.0,10829.0,28334.0,5049.0,180.0,46542.0,",
    "2025-11,quarterly,Whole,National Statistics Office of Georgia,1805.0,10088.0,24822.0,4847.0,157.0,41719.0,",
]) + "\n"


def picker(*qs):
    return [{"type": "selector", "placeholder": "Year", "selectValues": []},
            {"type": "selector", "placeholder": "Quarter",
             "selectValues": [{"name": "All", "code": "99"}]
             + [{"name": q, "code": q} for q in qs]}]


def add(*lists):
    out = {}
    for l in lists:
        for i in l:
            out[i["name"]] = out.get(i["name"], 0) + i["value"]
    return [{"name": k, "value": v} for k, v in out.items()]


def scale(l, f):
    return [{"name": i["name"], "value": int(i["value"] * f)} for i in l]


def write_dir(d: Path, q1=Q1_26, q2=Q2_26, year=None, tree=True):
    """A --from-dir copy of the API answers for 2025-Q3 … 2026-Q2."""
    q3_25 = scale(Q2_26, 1.07)
    q4_25 = scale(Q2_26, 0.96)
    files = {
        "mobile-text_ratings_2026.json": picker("I", "II"),
        "mobile-text_ratings_2025.json": picker("I", "II", "III", "IV"),
        "mobile_fuels_2025_III.json": q3_25,
        "mobile_fuels_2025_IV.json": q4_25,
        "mobile_fuels_2026_I.json": q1,
        "mobile_fuels_2026_II.json": q2,
        "mobile_fuels_2026_99.json": year if year is not None else add(q1, q2),
    }
    for (y, q), fu in (((2025, "III"), q3_25), ((2025, "IV"), q4_25),
                        ((2026, "I"), q1), ((2026, "II"), q2)):
        total = sum(i["value"] for i in fu)
        if tree:
            files[f"mobile_treemap_{y}_{q}.json"] = {
                "TOYOTA": {"CAMRY": 900, "PRIUS": 500, fg.OTHERS_KA: 600},
                "TESLA": {"MODEL 3": 700, "MODEL Y": 300},
                "BYD": {"SONG PLUS": 200},
                fg.OTHERS_KA: {fg.OTHERS_KA: total - 3200},
            }
    for name, obj in files.items():
        (d / name).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------------------

def test_every_category_maps():
    for name, col in CATEGORY_CASES.items():
        cats = {"Electric": 0, "Hybrid": 0, "Gasoline": 0, "Diesel": 0, name: 7}
        counts = fg.to_counts(cats, "t")
        assert counts[col] == 7, (name, col, counts)
        assert counts["TOTAL"] == 7


def test_q2_2026_reproduces_the_csv_row():
    counts = fg.to_counts(fg.parse_fuels(Q2_26, "t"), "t")
    assert counts == {"BEV": 3724, "HEV": 11092, "PETROL": 23383, "DIESEL": 5093,
                      "OTHERS": 157, "TOTAL": 43449}, counts
    row = {"BEV": "3724", "HEV": "11092", "PETROL": "23383", "DIESEL": "5093",
           "OTHERS": "157", "TOTAL": "43449"}
    assert fg.compare(counts, row) == ""


def test_unknown_or_missing_category_stops():
    for bad in ({"Electric": 1, "Hybrid": 1, "Gasoline": 1, "Diesel": 1, "Hydrogen": 1},
                {"Electric": 1, "Hybrid": 1, "Gasoline": 1}):
        try:
            fg.to_counts(bad, "t")
            raise AssertionError(f"{bad} must stop the run")
        except ValueError:
            pass


def test_look_alike_categories_do_not_match():
    # "Plug-in hybrid" or lower-case names are new categories, not "Hybrid".
    for name in ("Plug-in hybrid", "hybrid", "Electric ", "Gasoline gas"):
        cats = {"Electric": 0, "Hybrid": 0, "Gasoline": 0, "Diesel": 0}
        cats[name] = 1
        if name.strip() in cats and name != name.strip():
            continue  # parse_fuels strips; a trailing space is the same name
        try:
            fg.to_counts(cats, "t")
            raise AssertionError(f"{name!r} must not be mapped silently")
        except ValueError:
            pass


def test_parse_fuels_rejects_malformed():
    assert fg.parse_fuels([], "t") == {}
    for bad in ({"a": 1}, [{"name": "Gasoline"}], [{"name": "Gasoline", "value": -1}],
                [{"name": "Gasoline", "value": 1.5}],
                [{"name": "Gasoline", "value": 1}, {"name": "Gasoline", "value": 2}]):
        try:
            fg.parse_fuels(bad, "t")
            raise AssertionError(f"{bad} must be rejected")
        except ValueError:
            pass


def test_periods():
    assert [fg.period_of(2026, q) for q in fg.QUARTERS] == \
        ["2026-02", "2026-05", "2026-08", "2026-11"]
    assert fg.quarter_of("2025-11") == (2025, "IV")
    assert fg.parse_quarter_arg("2026-Q3") == (2026, "III")
    assert fg.prev_quarter(2026, "I") == (2025, "IV")
    assert sorted([(2025, "IV"), (2026, "I"), (2025, "III")], key=fg.qkey) == \
        [(2025, "III"), (2025, "IV"), (2026, "I")]


def test_picker_parse_and_shape_change():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        (p / "mobile-text_ratings_2026.json").write_text(json.dumps(picker("I", "II")))
        (p / "mobile-text_ratings_2027.json").write_text(json.dumps(picker()))
        (p / "mobile-text_ratings_2024.json").write_text(json.dumps([{"placeholder": "Year"}]))
        src = fg.Source(from_dir=d)
        assert src.quarters(2026) == ["I", "II"]
        assert src.quarters(2027) == []
        try:
            src.quarters(2024)
            raise AssertionError("a picker without a Quarter selector must stop")
        except RuntimeError:
            pass


def test_completeness_guard():
    year_ago = {c: "100" for c in fg.FUELS}
    year_ago["TOTAL"] = "1000"
    assert fg.completeness({"TOTAL": 400}, year_ago)[0] == "abort"
    assert fg.completeness({"TOTAL": 600}, year_ago)[0] == "warn"
    assert fg.completeness({"TOTAL": 900}, year_ago)[0] == "ok"
    assert fg.completeness({"TOTAL": 900}, None) == ("ok", None)


def test_treemap_units():
    tree = {"TOYOTA": {"CAMRY": 900, fg.OTHERS_KA: 100}, fg.OTHERS_KA: {fg.OTHERS_KA: 50}}
    u = fg.treemap_units(tree, 1100, "t")
    assert u[(market_top.ALL, "TOYOTA", "CAMRY")] == 900
    assert u[(market_top.ALL, "TOYOTA", "")] == 100           # brand total, no model
    assert u[(market_top.ALL, market_top.REST, "")] == 50 + 50  # others + unlisted rest
    try:
        fg.treemap_units(tree, 500, "t")
        raise AssertionError("a treemap larger than the quarter must stop")
    except ValueError:
        pass


def run_main(d, csvp, *extra):
    old_top = fg.TOP_PATH
    fg.TOP_PATH = Path(d) / "georgia_top.json"
    try:
        return fg.main(["--csv", str(csvp), "--from-dir", d, "--today", "2026-10-09",
                        "--summary", "", "--github-output", str(Path(d) / "out.txt"), *extra])
    finally:
        fg.TOP_PATH = old_top


def test_end_to_end_adds_quarters_and_keeps_lines():
    with tempfile.TemporaryDirectory() as d:
        write_dir(Path(d))
        csvp = Path(d) / "Georgia.csv"
        csvp.write_text(CSV_TEXT, encoding="utf-8")
        rc = run_main(d, csvp)
        assert rc == 0
        lines = csvp.read_text(encoding="utf-8").splitlines()
        # untouched history byte-identical (".0" floats kept)
        assert lines[1:4] == CSV_TEXT.splitlines()[1:4], lines
        assert lines[-1] == ("2026-05,quarterly,Whole,National Statistics Office of Georgia,"
                             "3724,11092,23383,5093,157,43449,"), lines[-1]
        assert lines[-2].startswith("2026-02,quarterly,Whole,"), lines[-2]
        out = (Path(d) / "out.txt").read_text()
        assert "changed=true" in out and '["Whole"]' in out
        top = json.loads((Path(d) / "georgia_top.json").read_text(encoding="utf-8"))
        assert top["as_of"] == "2026-05"
        assert top["window"] == {"from": "2025-07", "to": "2026-06", "months": 12}
        assert top["quarters"] == ["2025-Q3", "2025-Q4", "2026-Q1", "2026-Q2"]
        assert list(top["classes"]) == ["ALL"]
        assert top["classes"]["ALL"]["brands"][0]["brand"] == "TOYOTA"
        assert top["classes"]["ALL"]["units"] == top["total_registrations"]


def test_differing_row_is_kept_unless_force():
    with tempfile.TemporaryDirectory() as d:
        write_dir(Path(d))
        csvp = Path(d) / "Georgia.csv"
        bad = CSV_TEXT + ("2026-05,quarterly,Whole,https://automobile.geostat.ge/en/automobiles/"
                          "rating,3700,11092,23383,5093,157,43425,typo\n")
        csvp.write_text(bad, encoding="utf-8")
        run_main(d, csvp, "--no-top")
        assert "3700" in csvp.read_text(encoding="utf-8")
        run_main(d, csvp, "--no-top", "--force", "--quarter", "2026-Q2")
        text = csvp.read_text(encoding="utf-8")
        assert "3700" not in text and ",3724,11092," in text


def test_year_crosscheck_stops():
    with tempfile.TemporaryDirectory() as d:
        write_dir(Path(d), year=scale(add(Q1_26, Q2_26), 1.01))
        csvp = Path(d) / "Georgia.csv"
        csvp.write_text(CSV_TEXT, encoding="utf-8")
        assert run_main(d, csvp, "--no-top") == 1
        assert csvp.read_text(encoding="utf-8") == CSV_TEXT


def test_partial_quarter_stops():
    with tempfile.TemporaryDirectory() as d:
        half = scale(Q2_26, 0.3)
        write_dir(Path(d), q2=half)
        csvp = Path(d) / "Georgia.csv"
        csvp.write_text(CSV_TEXT, encoding="utf-8")
        assert run_main(d, csvp, "--no-top") == 1
        assert "2026-05" not in csvp.read_text(encoding="utf-8")


def test_self_throttle_one_request():
    with tempfile.TemporaryDirectory() as d:
        write_dir(Path(d))
        csvp = Path(d) / "Georgia.csv"
        csvp.write_text(CSV_TEXT, encoding="utf-8")
        run_main(d, csvp)                   # brings CSV and top file up to date
        # now only the picker may be read: remove every other answer
        for f in Path(d).glob("mobile_*.json"):
            f.unlink()
        before = csvp.read_text(encoding="utf-8")
        assert run_main(d, csvp) == 0
        assert csvp.read_text(encoding="utf-8") == before


def test_upsert_rejects_foreign_header():
    with tempfile.TemporaryDirectory() as d:
        csvp = Path(d) / "Georgia.csv"
        csvp.write_text("period,time_interval,variant,source,BEV,TOTAL,notes\n", encoding="utf-8")
        try:
            fg.upsert_lines(csvp, {"2026-05": "x"}, False)
            raise AssertionError("a different header must stop the write")
        except SystemExit:
            pass


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
