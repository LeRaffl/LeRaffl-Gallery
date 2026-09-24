#!/usr/bin/env python3
"""Regression tests for scripts/fetch_ukraine.py (no network).

Run:  python scripts/test_fetch_ukraine.py

The fetcher's failure modes are silent: a renamed column, a new operation
code or a new fuel string would quietly move cars between variants or
columns. These cases pin the scope (operation codes × vehicle kind × gross
weight), the fuel mapping, both published header layouts (2013–2025 and the
2026 merged op column), the month-completeness rule and the line-level
upsert. All strings are real values from the MIA register.
"""
import csv
import io
import sys
import tempfile
import zipfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_ukraine as fu  # noqa: E402

M1, N = "ЛЕГКОВИЙ", "ВАНТАЖНИЙ"

HDR_2025 = ["PERSON", "REG_ADDR_KOATUU", "OPER_CODE", "OPER_NAME", "D_REG", "DEP_CODE",
            "DEP", "BRAND", "MODEL", "VIN", "MAKE_YEAR", "COLOR", "KIND", "BODY",
            "PURPOSE", "FUEL", "CAPACITY", "OWN_WEIGHT", "TOTAL_WEIGHT", "N_REG_NEW"]
HDR_2026 = ["PERSON", "CD.OPER_CODE||'-'||CD.OPERAS", "D_REG", "DEP", "BRAND", "MODEL",
            "VIN", "MAKE_YEAR", "COLOR", "KIND", "PURPOSE", "BODY", "FUEL", "CAPACITY",
            "POWER_KWT", "OWN_WEIGHT", "TOTAL_WEIGHT"]


def rec_2025(op, name, d, brand, model, kind, fuel, person="P", tw="2000"):
    r = dict.fromkeys(HDR_2025, "")
    r.update(PERSON=person, OPER_CODE=str(op), OPER_NAME=name, D_REG=d, BRAND=brand,
             MODEL=model, KIND=kind, FUEL=fuel, TOTAL_WEIGHT=tw)
    return [r[h] for h in HDR_2025]


def rec_2026(op, name, d, brand, model, kind, fuel, person="P", tw="2000"):
    r = dict.fromkeys(HDR_2026, "")
    r.update({"PERSON": person, "CD.OPER_CODE||'-'||CD.OPERAS": f"{op} - {name}",
              "D_REG": d, "BRAND": brand, "MODEL": model, "KIND": kind, "FUEL": fuel,
              "TOTAL_WEIGHT": tw})
    return [r[h] for h in HDR_2026]


N105 = "ПЕРВИННА РЕЄСТРАЦІЯ НОВОГО ТЗ ПРИДБАНОГО В ТОРГОВЕЛЬНІЙ ОРГАНІЗАЦІЇ, ЯКИЙ ВВЕЗЕНО З-ЗА КОРДОНУ"
N100 = "ПЕРВИННА РЕЄСТРАЦIЯ Б/В ТЗ ПРИДБАНОГО В ТОРГОВЕЛЬНІЙ ОРГАНІЗАЦІЇ, ЯКИЙ ВВЕЗЕНО З-ЗА КОРДОНУ"
N315 = "ПЕРЕРЕЄСТРАЦІЯ ТЗ НА НОВ. ВЛАСН. ПО ДОГОВОРУ УКЛАДЕНОМУ В ТСЦ"
N69 = "РЕЄСТРАЦІЯ НОВИХ ТЗ ПО АКТУ ПРИЙОМУ-ПЕРЕДАЧІ (ДОД. 6)"


def test_fuel_map():
    cases = {
        "ЕЛЕКТРО": "BEV",
        "ЕЛЕКТРО АБО БЕНЗИН": "HEV",
        "ЕЛЕКТРО АБО ДИЗЕЛЬНЕ ПАЛИВО": "HEV",
        "БЕНЗИН, ГАЗ АБО ЕЛЕКТРО": "HEV",
        "ГАЗ ТА ЕЛЕКТРО": "HEV",
        "БЕНЗИН": "PETROL",
        " дизельне  паливо ": "DIESEL",          # whitespace / case tolerant
        "БЕНЗИН АБО ГАЗ": "OTHERS",
        "ГАЗ": "OTHERS",
        "": "OTHERS",
        "НЕ ВИЗНАЧЕНО": "OTHERS",
    }
    for fuel, want in cases.items():
        assert fu.fuel_class(fuel) == want, (fuel, fu.fuel_class(fuel), want)
    assert fu.fuel_class("ВОДЕНЬ АБО ЩОСЬ НОВЕ") is None     # unknown → reported


def test_scope():
    assert fu.variants_for(105, M1, "le3500", "P") == ["Whole", "Private"]
    assert fu.variants_for(99, M1, "le3500", "J") == ["Whole", "Industry"]
    assert fu.variants_for(72, M1, "?", "") == ["Whole"]            # blank PERSON
    assert fu.variants_for(100, M1, "le3500", "P") == ["Used"]
    assert fu.variants_for(70, M1, "le3500", "J") == ["Used"]
    assert fu.variants_for(172, M1, "le3500", "P") == ["Used"]
    assert fu.variants_for(315, M1, "le3500", "P") == []            # change of owner
    assert fu.variants_for(69, M1, "le3500", "P") == []             # acceptance act
    assert fu.variants_for(105, N, "le3500", "J") == ["Vans"]       # N1
    assert fu.variants_for(105, N, "gt3500", "J") == []             # N2/N3
    assert fu.variants_for(105, N, "?", "J") == []                  # no weight → not N1
    assert fu.variants_for(100, N, "le3500", "J") == []             # used van
    assert fu.variants_for(105, "АВТОБУС", "le3500", "J") == []
    assert fu.weight_bucket("3500") == "le3500"
    assert fu.weight_bucket("3501") == "gt3500"
    assert fu.weight_bucket("") == "?" and fu.weight_bucket("0") == "?"


def test_parsers():
    assert fu.parse_op("105") == (105, "")
    assert fu.parse_op("100 - ПЕРВИННА РЕЄСТРАЦIЯ Б/В ТЗ") == (100, "ПЕРВИННА РЕЄСТРАЦIЯ Б/В ТЗ")
    assert fu.parse_op("х") == (None, "")
    assert fu.parse_period("22.08.25") == "2025-08"
    assert fu.parse_period("01.01.2019") == "2019-01"
    assert fu.parse_period("2020-03-15") == "2020-03"
    assert fu.parse_day("31.08.26") == date(2026, 8, 31)
    assert fu.parse_day("junk") is None


def test_complete_through():
    assert fu.complete_through(date(2026, 8, 31)) == "2026-08"
    assert fu.complete_through(date(2026, 8, 29)) == "2026-07"    # partial August
    assert fu.complete_through(date(2025, 12, 31)) == "2025-12"
    assert fu.complete_through(date(2026, 1, 15)) == "2025-12"
    assert fu.complete_through(None) is None


def test_both_header_layouts_and_scope_end_to_end():
    rows25 = [HDR_2025,
              rec_2025(105, N105, "03.08.25", "BYD", "SONG PLUS", M1, "ЕЛЕКТРО", "P"),
              rec_2025(105, N105, "04.08.25", "TOYOTA", "RAV-4 HYBRID", M1, "ЕЛЕКТРО АБО БЕНЗИН", "J"),
              rec_2025(100, N100, "04.08.25", "TESLA", "MODEL 3", M1, "ЕЛЕКТРО", "P"),
              rec_2025(315, N315, "05.08.25", "SKODA", "OCTAVIA", M1, "БЕНЗИН", "P"),
              rec_2025(105, N105, "06.08.25", "RENAULT", "MASTER", N, "ДИЗЕЛЬНЕ ПАЛИВО", "J", "3500"),
              rec_2025(105, N105, "06.08.25", "MAN", "TGX", N, "ДИЗЕЛЬНЕ ПАЛИВО", "J", "40000"),
              rec_2025(69, N69, "07.08.25", "SKODA", "KODIAQ", M1, "БЕНЗИН", "J"),
              rec_2025(105, N105, "31.07.18", "LADA", "VESTA", M1, "БЕНЗИН", "P")]   # before 2018-09
    rows26 = [HDR_2026,
              rec_2026(105, N105, "31.08.26", "ZEEKR", "7X", M1, "ЕЛЕКТРО", "P"),
              rec_2026(99, "ПЕРВИННА РЕЄСТРАЦІЯ НОВОГО ТЗ … ВИГОТОВЛЕНО В УКРАЇНІ",
                       "12.08.26", "SKODA", "KODIAQ", M1, "БЕНЗИН", "J")]
    agg = fu.Aggregator()
    n, newest, bad = fu.add_rows(iter(rows25), agg)
    assert (n, bad) == (8, 0) and newest == date(2025, 8, 7)
    n, newest, bad = fu.add_rows(iter(rows26), agg)
    assert (n, bad, newest) == (2, 0, date(2026, 8, 31))
    a = agg.counts["2025-08"]
    assert a["Whole"] == {"BEV": 1, "HEV": 1, "PETROL": 0, "DIESEL": 0, "OTHERS": 0, "TOTAL": 2}
    assert a["Private"]["TOTAL"] == 1 and a["Industry"]["TOTAL"] == 1
    assert a["Used"]["BEV"] == 1 and a["Used"]["TOTAL"] == 1
    assert a["Vans"] == {"BEV": 0, "HEV": 0, "PETROL": 0, "DIESEL": 1, "OTHERS": 0, "TOTAL": 1}
    assert "2018-07" not in agg.counts                               # before the code set
    b = agg.counts["2026-08"]
    assert b["Whole"]["TOTAL"] == 2 and b["Industry"]["PETROL"] == 1
    # op 69 ("new vehicles by acceptance act") is not counted but reported
    assert any(k[1] == 69 for k in agg.unmapped_ops), agg.unmapped_ops
    assert fu.check_consistency(agg, ["2025-08", "2026-08"]) == []
    assert agg.units[("2025-08", "BEV", "BYD", "SONG PLUS")] == 1


def test_schema_drift_is_fatal():
    for hdr in (["PERSON", "D_REG", "KIND"],                               # no op column
                [h for h in HDR_2025 if h != "FUEL"]):                     # no fuel column
        try:
            fu.resolve_columns(hdr)
        except SystemExit:
            continue
        raise AssertionError(f"accepted {hdr}")


def test_zip_member_encodings():
    for enc in ("utf-8", "cp1251"):
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(HDR_2025)
        w.writerow(rec_2025(105, N105, "03.08.25", "BYD", "SEAL", M1, "ЕЛЕКТРО"))
        zb = io.BytesIO()
        with zipfile.ZipFile(zb, "w") as z:
            z.writestr("reestrtz31.08.2025.csv", buf.getvalue().encode(enc))
        z = zipfile.ZipFile(io.BytesIO(zb.getvalue()))
        rows = list(fu.iter_member(z, "reestrtz31.08.2025.csv"))
        assert rows[1][fu.resolve_columns(rows[0])["FUEL"]] == "ЕЛЕКТРО", enc


def test_consistency_catches_a_lost_person_split():
    agg = fu.Aggregator()
    agg.add("2026-01", 105, "", M1, "le3500", "БЕНЗИН", "P", "X", "Y")
    agg.counts["2026-01"]["Private"]["TOTAL"] -= 1
    assert fu.check_consistency(agg, ["2026-01"])


def test_upsert_is_line_level():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "Ukraine.csv"
        c = {"BEV": 5, "HEV": 3, "PETROL": 10, "DIESEL": 2, "OTHERS": 0, "TOTAL": 20}
        l1 = fu.render_line("2026-07", "Whole", c)
        assert l1 == "2026-07,monthly,Whole,MIA HSC (data.gov.ua),5.0,3.0,10.0,2.0,0.0,20.0,"
        assert fu.upsert_lines(p, {("2026-07", "Whole"): l1}, False)["added"] == 1
        before = p.read_text(encoding="utf-8")
        s = fu.upsert_lines(p, {("2026-07", "Whole"): l1}, False)
        assert s["unchanged"] == 1 and p.read_text(encoding="utf-8") == before
        foreign = l1.replace("MIA HSC (data.gov.ua)", "manual")
        p.write_text(before.replace(l1, foreign), encoding="utf-8")
        assert fu.upsert_lines(p, {("2026-07", "Whole"): l1}, False)["skipped"] == 1
        assert fu.upsert_lines(p, {("2026-07", "Whole"): l1}, True)["updated"] == 1


def test_market_top_uses_csv_classes():
    agg = fu.Aggregator()
    for m in ("2025-09", "2026-08"):
        agg.add(m, 105, "", M1, "le3500", "ЕЛЕКТРО", "P", "BYD", "BYD SONG PLUS")
        agg.add(m, 105, "", M1, "le3500", "ЕЛЕКТРО АБО БЕНЗИН", "P", "TOYOTA", "CAMRY")
        agg.add(m, 105, "", M1, "le3500", "БЕНЗИН", "P", "SKODA", "OCTAVIA")
    agg.add("2025-08", 105, "", M1, "le3500", "ЕЛЕКТРО", "P", "TESLA", "MODEL Y")  # outside
    top = fu.build_top(agg, "2026-08")
    assert top["total_registrations"] == 6
    assert top["classes"]["BEV"]["models"][0] == {"brand": "BYD", "model": "SONG PLUS",
                                                  "units": 2, "share_of_class": 1.0}
    assert top["classes"]["HEV"]["units"] == 2 and "PETROL" not in top["classes"]


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} tests passed")
