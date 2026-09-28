#!/usr/bin/env python3
"""Regression tests for scripts/fetch_peru.py (no network).

Run:  python scripts/test_fetch_peru.py

The fetcher's failure modes are silent: a new vehicle class, a renamed body,
a new powertrain value or a mis-decoded Power BI row would quietly move cars
between variants or columns. These cases pin the scope (AAP group × class ×
body → EU class), the powertrain mapping, the decoder of Power BI's
compressed result format (with a real response), the query the API receives,
the "is this month final?" rule, the parser of AAP's printed report table,
the cross-check, the line-level upsert, the display names of the
top-brands/models table, and one end-to-end offline run.
"""
import collections
import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_peru as fp  # noqa: E402


def test_variant_scope():
    cases = [
        (("LIVIANOS", "AUTOMOVIL", "SEDAN"), "Whole"),
        (("LIVIANOS", "AUTOMOVIL", "HATCHBACK"), "Whole"),
        (("LIVIANOS", "AUTOMOVIL", "AUTOMOVIL ELECTRICO"), "Whole"),
        (("LIVIANOS", "STATION WAGON", "STATION WAGON"), "Whole"),
        (("LIVIANOS", "SUV,TODOTERRENOS", "SUV"), "Whole"),
        (("LIVIANOS", "CAMIONETAS", "MULTIPROPOSITO"), "Whole"),   # MPVs: Avanza, Xpander
        (("LIVIANOS", "CAMIONETAS", "PANEL"), "Vans"),             # panel vans
        (("LIVIANOS", "CAMIONETAS", "MICROBUS"), None),            # minibuses, M2
        (("LIVIANOS", "CAMIONETAS", "AMBULANCIA"), None),
        (("LIVIANOS", "CAMIONETAS", None), None),                  # body unknown
        (("LIVIANOS", "PICK UP Y FURGONETAS", "PICK UP"), "Vans"),
        (("LIVIANOS", "PICK UP Y FURGONETAS", "CHASIS CABINADO"), "Vans"),
        (("LIVIANOS", "PICK UP Y FURGONETAS", "FURGON"), "Vans"),
        (("PESADOS", "CAMIONES", "CAMIONES"), None),
        (("PESADOS", "MINIBUS,OMNIBUS", "BUSES Y CHASISES"), None),
        (("MENORES", "MOTOCICLETAS", None), None),
        ((" livianos ", "suv,todoterrenos", "suv"), "Whole"),     # case / spaces
    ]
    for args, want in cases:
        got = fp.variant_for(*args)
        assert got == want, (args, got, want)


def test_fuel_mapping():
    cases = {
        "BEV": "BEV", "PHEV": "PHEV", "HEV": "HEV",
        "GASOLINA": "PETROL", "DIESEL": "DIESEL",
        "GNV": "CNG", "BI-GNV": "CNG", "DUAL GNV": "CNG",
        "GLP": "LPG", "BI-GLP": "LPG", "DUAL GLP": "LPG",
        "GNL": "OTHERS", "BI-GNL": "OTHERS", "DUAL GNL": "OTHERS", "-": "OTHERS",
        "gasolina ": "PETROL",
        # the registry's own old codes are NOT powertrain classes: AAP's
        # `Elect` resolves them; seeing one there means drift
        "ELECTRICO": None, "HIBRIDO": None, "MHEV": None, "HIDROGENO": None,
    }
    for value, want in cases.items():
        assert fp.fuel_class(value) == want, (value, fp.fuel_class(value), want)
    # every FUEL_MAP target is a CSV column
    assert set(fp.FUEL_MAP.values()) <= set(fp.FUELS)
    # mild hybrids: HEV in the CSV, MHEV in the top table when the registry says so
    assert fp.market_class("HEV", "MHEV") == "MHEV"
    assert fp.market_class("HEV", "HEV") == "HEV"
    assert fp.market_class("HEV", "HIBRIDO") == "HEV"          # pre-2025: not separable
    assert fp.market_class("BEV", "ELECTRICO") == "BEV"
    assert fp.market_class("PHEV", "HIBRIDO") == "PHEV"


def test_unclassified():
    for v in (None, "", "(en blanco)", "#N/D"):
        assert fp.is_unclassified(v), v
    for v in ("BEV", "GASOLINA", "-"):
        assert not fp.is_unclassified(v), v


# A real response (2026-08, the preliminary month: `Elect` still empty):
# Grupo × Elect × Sum(nTotal). Row 1 has Elect null (Ø bit 1); rows 2-3
# repeat it (R bit 1).
REAL_DSR = {"results": [{"result": {"data": {"dsr": {"DS": [
    {"N": "DS0", "PH": [{"DM0": [
        {"S": [{"N": "G0", "T": 1, "DN": "D0"}, {"N": "G1", "T": 1, "DN": "D1"},
               {"N": "M0", "T": 4}], "C": [0, 16412], "Ø": 2},
        {"C": [1, 35414], "R": 2},
        {"C": [2, 2009], "R": 2}]}],
     "IC": True, "HAD": True,
     "ValueDicts": {"D0": ["LIVIANOS", "MENORES", "PESADOS"], "D1": []}}]}}}}]}

# Synthetic: repeats of the first column, a null in the middle, inline
# (non-dictionary) values and a count that repeats.
SYNTH_DSR = {"results": [{"result": {"data": {"dsr": {"DS": [
    {"PH": [{"DM0": [
        {"S": [{"N": "G0", "T": 1, "DN": "D0"}, {"N": "G1", "T": 1, "DN": "D1"},
               {"N": "G2", "T": 1}, {"N": "M0", "T": 4}], "C": [0, 0, "YUAN UP", 9]},
        {"C": [1, "SEAGULL", 8], "R": 1},
        {"C": ["EX30"], "R": 1 | 8, "Ø": 2},
        {"C": [1, 1, "XC60", 16]}]}],
     "IC": True,
     "ValueDicts": {"D0": ["BYD", "VOLVO"], "D1": ["BEV", "PHEV"]}}]}}}}]}


def test_decode_dsr():
    assert fp.decode_dsr(REAL_DSR, 3) == [["LIVIANOS", None, 16412],
                                          ["MENORES", None, 35414],
                                          ["PESADOS", None, 2009]]
    assert fp.decode_dsr(SYNTH_DSR, 4) == [["BYD", "BEV", "YUAN UP", 9],
                                           ["BYD", "PHEV", "SEAGULL", 8],
                                           ["BYD", None, "EX30", 8],
                                           ["VOLVO", "PHEV", "XC60", 16]]
    truncated = json.loads(json.dumps(REAL_DSR))
    truncated["results"][0]["result"]["data"]["dsr"]["DS"][0]["IC"] = False
    try:
        fp.decode_dsr(truncated, 3)
    except SystemExit as e:
        assert "incomplete" in str(e)
    else:
        raise AssertionError("an incomplete result must abort")


def test_query_shape():
    q = fp.build_query(fp.DIMS, "2025-12", 11392741)
    assert q["modelId"] == 11392741
    cmd = q["queries"][0]["Query"]["Commands"][0]["SemanticQueryDataShapeCommand"]
    sel = cmd["Query"]["Select"]
    assert [s["Column"]["Property"] for s in sel[:-1]] == fp.DIMS
    assert sel[-1]["Aggregation"]["Function"] == 0                   # Sum
    assert cmd["Binding"]["Primary"]["Groupings"][0]["Projections"] == list(range(len(sel)))
    cond = cmd["Query"]["Where"][0]["Condition"]["And"]
    assert cond["Left"]["Comparison"]["Right"]["Literal"]["Value"] == "datetime'2025-12-01T00:00:00'"
    assert cond["Right"]["Comparison"]["Right"]["Literal"]["Value"] == "datetime'2026-01-01T00:00:00'"
    assert cond["Left"]["Comparison"]["ComparisonKind"] == 2        # >=
    assert cond["Right"]["Comparison"]["ComparisonKind"] == 3       # <


def test_newest_final_month():
    final = {"2026-07", "2026-06"}
    ref = dt.datetime(2026, 9, 2, 15, 3)
    # the refresh month (2026-09) is never a candidate; 2026-08 is preliminary
    assert fp.newest_final_month(lambda p: p in final, ref) == "2026-07"
    assert fp.newest_final_month(lambda p: p in final | {"2026-08"}, ref) == "2026-08"
    assert fp.newest_final_month(lambda p: False, ref) is None
    # no refresh stamp: fall back to today
    assert fp.newest_final_month(lambda p: p in final, None, dt.date(2026, 8, 20)) == "2026-07"
    assert fp.months_between("2025-11", "2026-02") == ["2025-11", "2025-12", "2026-01", "2026-02"]
    assert fp.prev_month("2026-01") == "2025-12"


# Text of the "Evolución mensual" page as pdfplumber extracts it (AAP report
# for August 2026, abridged).
REPORT_TEXT = """Volver al índice
Venta de vehículos
livianos y pesados
Evolución mensual
Total a
Año Ene Feb Mar Abr May Jun Jul Ago Set Oct Nov Dic Total Anual
Agosto
2019 15,367 13,901 13,269 13,633 14,935 12,508 13,309 13,563 14,742 14,174 13,424 15,822 110,485 168,647
2020 15,801 13,890 7,664 - 375 5,260 11,043 12,396 14,561 15,312 14,918 13,870 66,429 125,090
2026 23,069 23,512 22,997 22,441 23,137 25,565 21,767 26,328 188,816
Var. % 25/24 18.4% 0.3% 29.6% 11.8% 20.6% 36.6% 34.5% 27.8% 17.8% 29.1% 32.6% 48.7% 21.6% 25.1%
Fuente: SUNARP - AAP Elaboración: GOA - AAP
77"""


def test_report_table():
    t = fp.parse_report_table(REPORT_TEXT)
    assert t["2019-01"] == 15367 and t["2019-12"] == 15822
    assert t["2020-04"] == 0 and t["2020-05"] == 375
    assert t["2026-08"] == 26328 and "2026-09" not in t
    assert "2019-13" not in t and not any(k.startswith("77") for k in t)
    assert len([k for k in t if k.startswith("2026")]) == 8


def test_cross_check():
    agg = fp.Aggregator()
    agg.add("2026-07", "LIVIANOS", "AUTOMOVIL", "SEDAN", "GASOLINA", "GASOLINA", "KIA", "SOLUTO", 18864)
    agg.add("2026-07", "PESADOS", "CAMIONES", "CAMIONES", "DIESEL", "DIESEL", "HINO", "300", 2903)
    agg.add("2026-07", "MENORES", "MOTOCICLETAS", None, None, None, "HONDA", "XR", 47034)   # not compared
    compared, small, mism = fp.cross_check(agg, ["2026-07"], {"2026-07": 21767})
    assert compared == ["2026-07"] and not small and not mism
    compared, small, mism = fp.cross_check(agg, ["2026-07"], {"2026-07": 21769})
    assert len(small) == 1 and not mism                    # 2 units: tolerated
    compared, small, mism = fp.cross_check(agg, ["2026-07"], {"2026-07": 22000})
    assert len(mism) == 1
    assert fp.cross_check(agg, ["2026-08"], {"2026-07": 1})[0] == []


def test_aggregator():
    agg = fp.Aggregator()
    add = agg.add
    add("2026-07", "LIVIANOS", "SUV,TODOTERRENOS", "SUV", "BEV", "BEV", "VOLVO", "EX30", 3)
    add("2026-07", "LIVIANOS", "SUV,TODOTERRENOS", "SUV", "PHEV", "PHEV", "BYD", "BYD SONG PLUS DM-I", 2)
    add("2026-07", "LIVIANOS", "AUTOMOVIL", "HATCHBACK", "MHEV", "HEV", "SUZUKI", "SWIFT", 4)
    add("2026-07", "LIVIANOS", "SUV,TODOTERRENOS", "SUV", "HEV", "HEV", "TOYOTA", "YARIS CROSS", 5)
    add("2026-07", "LIVIANOS", "CAMIONETAS", "MULTIPROPOSITO", "GASOLINA", "GASOLINA", "TOYOTA", "AVANZA", 6)
    add("2026-07", "LIVIANOS", "CAMIONETAS", "MICROBUS", "DIESEL", "DIESEL", "TOYOTA", "HIACE", 7)
    add("2026-07", "LIVIANOS", "PICK UP Y FURGONETAS", "PICK UP", "DIESEL", "DIESEL", "TOYOTA", "HILUX", 8)
    add("2026-07", "LIVIANOS", "CAMIONETAS", "PANEL", "BI-GNV", "BI-GNV", "CHANGAN", "NEW VAN", 1)
    add("2026-07", "LIVIANOS", "LIMUSINA", "X", "GASOLINA", "GASOLINA", "X", "Y", 1)       # unknown class
    add("2026-07", "LIVIANOS", "AUTOMOVIL", "SEDAN", "HIDROGENO", "HIDROGENO", "TOYOTA", "MIRAI", 1)
    add("2026-07", "PESADOS", "CAMIONES", "CAMIONES", "BEV", "BEV", "JAC", "N", 9)
    add("2026-07", "LIVIANOS", "AUTOMOVIL", "SEDAN", "GASOLINA", "GASOLINA", "KIA", "RIO", 0)  # zero rows ignored
    w, v = agg.counts["2026-07"]["Whole"], agg.counts["2026-07"]["Vans"]
    assert (w["BEV"], w["PHEV"], w["HEV"], w["PETROL"], w["OTHERS"], w["TOTAL"]) == (3, 2, 9, 6, 1, 21)
    assert (v["DIESEL"], v["CNG"], v["TOTAL"]) == (8, 1, 9)
    assert agg.excluded[("2026-07", "CAMIONETAS", "MICROBUS")] == 7
    assert agg.unmapped[("2026-07", "LIMUSINA", "X")] == 1
    assert agg.unknown_fuel[("2026-07", "Whole", "HIDROGENO")] == 1
    assert agg.light["2026-07"] == 38 and agg.light_heavy["2026-07"] == 47
    assert not agg.unclassified["2026-07"]
    assert not fp.check_sums(agg, ["2026-07"])
    agg.add("2026-08", "LIVIANOS", "AUTOMOVIL", "SEDAN", "HIBRIDO", None, "TOYOTA", "COROLLA", 5)
    assert agg.unclassified["2026-08"] == 5
    # month_totals feeds the "detailed rows == month aggregate" self-check
    rows = [["LIVIANOS", "AUTOMOVIL", "SEDAN", "GASOLINA", "GASOLINA", "KIA", "RIO", 3],
            ["LIVIANOS", "AUTOMOVIL", "SEDAN", "HIBRIDO", None, "KIA", "NIRO", 2],
            ["PESADOS", "CAMIONES", "CAMIONES", "DIESEL", "DIESEL", "HINO", "300", 1]]
    assert fp.month_totals(rows) == collections.Counter(
        {("LIVIANOS", "GASOLINA"): 3, ("LIVIANOS", ""): 2, ("PESADOS", "DIESEL"): 1})


def test_top_table():
    agg = fp.Aggregator()
    agg.add("2026-07", "LIVIANOS", "SUV,TODOTERRENOS", "SUV", "BEV", "BEV", "VOLVO", "EX30", 3)
    agg.add("2026-07", "LIVIANOS", "SUV,TODOTERRENOS", "SUV", "ELECTRICO", "BEV", "BIYADI", "BYD YUAN UP", 2)
    agg.add("2026-07", "LIVIANOS", "AUTOMOVIL", "HATCHBACK", "MHEV", "HEV", "SUZUKI", "SWIFT", 4)
    agg.add("2026-07", "LIVIANOS", "SUV,TODOTERRENOS", "SUV", "HEV", "HEV", "TOYOTA", "YARIS CROSS", 5)
    agg.add("2026-07", "LIVIANOS", "AUTOMOVIL", "SEDAN", "GASOLINA", "GASOLINA", "KIA", "SOLUTO", 10)
    agg.add("2026-07", "LIVIANOS", "PICK UP Y FURGONETAS", "PICK UP", "BEV", "BEV", "JAC", "T8", 7)  # Vans
    top = fp.build_top(agg, "2026-07")
    assert top["country"] == "Peru" and top["total_registrations"] == 24
    assert top["classes"]["BEV"]["units"] == 5
    assert top["classes"]["BEV"]["brands"][0] == {"brand": "VOLVO", "units": 3, "share_of_class": 0.6}
    assert top["classes"]["BEV"]["models"][1]["model"] == "YUAN UP"
    assert top["classes"]["BEV"]["models"][1]["brand"] == "BYD"
    assert top["classes"]["MHEV"]["brands"][0]["brand"] == "SUZUKI"
    assert top["classes"]["HEV"]["units"] == 5
    assert "PETROL" not in top["classes"]


def test_display_names():
    cases = [
        (("BYD", "BYD SONG PLUS DM-I"), ("BYD", "SONG PLUS DM-I")),
        (("BIYADI", "BYD SEAGULL"), ("BYD", "SEAGULL")),
        (("MERCEDES BENZ", "GLC"), ("MERCEDES-BENZ", "GLC")),
        (("CHANA", "CS15"), ("CHANGAN", "CS15")),
        (("WULING BAOJUN", "LZW7007EVD2MBMA"), ("BAOJUN", "LZW7007EVD2MBMA")),
        (("VOLVO", "  ex30 "), ("VOLVO", "EX30")),
        (("TOYOTA", "TOYOTA"), ("TOYOTA", "TOYOTA")),        # never stripped to empty
    ]
    for (mk, mo), (wb, wm) in cases:
        got = (fp.display_brand(mk), fp.display_model(mk, mo))
        assert got == (wb, wm), (mk, mo, got)


def test_upsert_line_level():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "Peru.csv"
        c = fp.empty_counts()
        c.update(BEV=10, PHEV=1, PETROL=5, TOTAL=16)
        st = fp.upsert_lines(p, {("2026-07", "Whole"): fp.render_line("2026-07", "Whole", c)}, False)
        assert st["added"] == 1
        foreign = "2026-06,monthly,Whole,someone else,1.0,0.0,0.0,1.0,0.0,0.0,0.0,0.0,2.0,"
        p.write_text(p.read_text().replace("\n", "\n" + foreign + "\n", 1))
        st = fp.upsert_lines(p, {("2026-06", "Whole"): fp.render_line("2026-06", "Whole", c)}, False)
        assert st["skipped"] == 1 and foreign in p.read_text()
        st = fp.upsert_lines(p, {("2026-07", "Whole"): fp.render_line("2026-07", "Whole", c)}, False)
        assert st["unchanged"] == 1
        lines = p.read_text().splitlines()
        assert lines[0] == ",".join(fp.CSV_COLUMNS)
        assert lines[2] == ("2026-07,monthly,Whole,SUNARP via AAP (BI-AAP),"
                            "10.0,1.0,0.0,5.0,0.0,0.0,0.0,0.0,16.0,")


def test_completeness_guard():
    have = {f"2025-{m:02d}": {"TOTAL": "12000"} for m in range(1, 13)}
    assert fp.median_fraction("2026-01", 3000, have) < fp.MIN_MONTH_FRACTION
    assert fp.median_fraction("2026-01", 9000, have) > fp.MIN_MONTH_FRACTION
    assert fp.median_fraction("2025-04", 10, have) is None           # too little history


def _rows(bev, petrol, elect_ok=True):
    e = (lambda v: v) if elect_ok else (lambda v: None)
    return [["LIVIANOS", "SUV,TODOTERRENOS", "SUV", "BEV", e("BEV"), "VOLVO", "EX30", bev],
            ["LIVIANOS", "AUTOMOVIL", "SEDAN", "GASOLINA", e("GASOLINA"), "KIA", "SOLUTO", petrol],
            ["LIVIANOS", "PICK UP Y FURGONETAS", "PICK UP", "DIESEL", e("DIESEL"), "TOYOTA", "HILUX", 50],
            ["PESADOS", "CAMIONES", "CAMIONES", "DIESEL", e("DIESEL"), "HINO", "300", 9]]


def _light_heavy(rows):
    return sum(r[-1] for r in rows if r[0] in ("LIVIANOS", "PESADOS"))


class _Scenario:
    """Runs fetch_peru.main() offline, run after run, in one temp repo."""

    def __init__(self, d: Path):
        self.d = d
        self.out = d / "gh_output"
        self.summary = d / "summary.md"

    def run(self, refreshed, months, report_upto=None, report=None):
        dump = self.d / "dump.json"
        dump.write_text(json.dumps({"refreshed": refreshed, "months": months}))
        if report is None and report_upto is not None:
            report = {p: _light_heavy(r) for p, r in months.items() if p <= report_upto}
        fp.load_report = lambda session, args: ((report, "test-report") if report is not None
                                                else (None, "unreachable"))
        self.out.write_text("")
        self.summary.write_text("")
        sys.argv = ["fetch_peru.py", "--from-json", str(dump), "--github-output",
                    str(self.out), "--step-summary", str(self.summary)]
        rc = fp.main()
        return rc, self.out.read_text(), self.summary.read_text()

    def whole(self):
        p = self.d / "data/Peru.csv"
        return {l.split(",")[0]: l for l in p.read_text().splitlines()[1:]} if p.exists() else {}


def test_end_to_end_offline():
    """The month-finality and revision rules, run after run:
    preliminary and refresh-month data never written; a classified month
    waits for AAP's printed report; a new BI-AAP refresh re-reads everything
    and applies revisions of old months; no report → revisions only; a
    report mismatch aborts."""
    months = {p: _rows(2 + i, 900 + i)
              for i, p in enumerate(fp.months_between("2019-01", "2026-07"))}
    months["2026-08"] = _rows(1, 300, elect_ok=False)                # preliminary cut
    saved = fp.REPO, fp.TOP_PATH, sys.argv, fp.load_report
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        fp.REPO, fp.TOP_PATH = d, d / "market" / "peru_top.json"
        sc = _Scenario(d)
        try:
            # 1. refresh of 2026-09-02, report printed through 2026-06:
            #    July is classified but held, August (preliminary) never written
            rc, out, summ = sc.run("2026-09-02T15:03:09", months, report_upto="2026-06")
            w = sc.whole()
            assert rc == 0 and max(w) == "2026-06" and len(w) == 90, (max(w), len(w))
            assert "2026-07" in summ and "Held back" in summ
            top = json.loads(fp.TOP_PATH.read_text())
            assert top["as_of"] == "2026-06" and top["source_refreshed"] == "2026-09-02T15:03:09"
            # 2. same refresh, report unchanged → waiting, nothing written
            rc, out, summ = sc.run("2026-09-02T15:03:09", months, report_upto="2026-06")
            assert "changed=false" in out and max(sc.whole()) == "2026-06"
            # 3. the July report appears (it already prints August — still not written)
            rc, out, summ = sc.run("2026-09-02T15:03:09", months, report_upto="2026-08")
            w = sc.whole()
            assert max(w) == "2026-07" and "2026-08" not in w
            assert w["2026-07"].startswith("2026-07,monthly,Whole,SUNARP via AAP (BI-AAP),92.0,")
            assert 'changed_variants=["Vans", "Whole"]' in out
            # 4. nothing new → no-op
            rc, out, summ = sc.run("2026-09-02T15:03:09", months, report_upto="2026-08")
            assert "changed=false" in out and summ == ""
            # 5. a new refresh (2026-10-02): August now classified, an old month
            #    re-classified (3 BEVs become petrol, same total), and October
            #    data already present (the refresh month) — never written
            m2 = dict(months)
            m2["2026-08"] = _rows(1, 1000)
            m2["2026-09"] = _rows(5, 800, elect_ok=False)
            m2["2026-10"] = _rows(1, 20)
            old = m2["2025-03"]
            m2["2025-03"] = _rows(old[0][-1] - 3, old[1][-1] + 3)
            rc, out, summ = sc.run("2026-10-02T15:00:00", m2, report_upto="2026-10")
            w = sc.whole()
            assert max(w) == "2026-08" and "2026-10" not in w and "2026-09" not in w
            assert "2025-03 Whole: BEV 76→73, PETROL 974→977" in summ, summ
            assert w["2025-03"].split(",")[4] == "73.0"
            # 6. another refresh with a revision, but the report is unreachable:
            #    the revision is applied, the newly classified September is held
            m3 = dict(m2)
            m3["2026-09"] = _rows(5, 800)
            m3["2025-04"] = _rows(m2["2025-04"][0][-1] + 1, m2["2025-04"][1][-1] - 1)
            rc, out, summ = sc.run("2026-11-03T15:00:00", m3, report_upto=None)
            w = sc.whole()
            assert "2026-09" not in w and w["2025-04"].split(",")[4] == "78.0", w["2025-04"]
            # 7. a report that disagrees with BI-AAP on a month's total aborts
            bad = {p: _light_heavy(r) for p, r in m3.items()}
            bad["2026-05"] += 100
            try:
                sc.run("2026-12-02T15:00:00", m3, report=bad)
            except SystemExit as e:
                assert "Cross-check" in str(e) and "2026-05" in str(e)
            else:
                raise AssertionError("a report mismatch must abort")
        finally:
            fp.REPO, fp.TOP_PATH, sys.argv, fp.load_report = saved


def test_revisions_listing():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "Peru.csv"
        c = fp.empty_counts()
        c.update(BEV=10, PHEV=5, PETROL=85, TOTAL=100)
        fp.upsert_lines(p, {("2025-08", "Whole"): fp.render_line("2025-08", "Whole", c)}, False)
        c2 = dict(c, BEV=15, PHEV=0)
        new = {("2025-08", "Whole"): fp.render_line("2025-08", "Whole", c2),
               ("2025-09", "Whole"): fp.render_line("2025-09", "Whole", c)}   # new, not a revision
        assert fp.revisions(p, new) == ["2025-08 Whole: BEV 10→15, PHEV 5→0"]
        assert fp.revisions(p, {("2025-08", "Whole"): fp.render_line("2025-08", "Whole", c)}) == []


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
