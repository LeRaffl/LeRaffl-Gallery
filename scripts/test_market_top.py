#!/usr/bin/env python3
"""Offline tests for the top brands / models summaries (scripts/market_top.py
and the Spain / Malaysia fetchers that feed it). No network.

    python scripts/test_market_top.py
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_top as mt  # noqa: E402


def test_build_top_ranks_and_scopes():
    units = {("BEV", "BYD", "DOLPHIN"): 30, ("BEV", "TESLA", "MODEL Y"): 50,
             ("BEV", "TESLA", "MODEL 3"): 20, ("HEV", "TOYOTA", "YARIS"): 40,
             ("PETROL", "SEAT", "IBIZA"): 860, ("OTHERS", "DACIA", "SANDERO GLP"): 0}
    top = mt.build_top("X", "SRC", "2026-08", units, 1000, "u")
    assert top["window"] == {"from": "2025-09", "to": "2026-08", "months": 12}
    assert list(top["classes"]) == ["BEV", "HEV"]            # ICE never listed
    bev = top["classes"]["BEV"]
    assert bev["units"] == 100 and bev["share_of_market"] == 0.1
    assert bev["brands"][0] == {"brand": "TESLA", "units": 70, "share_of_class": 0.7}
    assert [m["model"] for m in bev["models"]] == ["MODEL Y", "DOLPHIN", "MODEL 3"]


def test_ties_are_order_independent_and_file_is_stable():
    a = {("PHEV", "B", "M1"): 5, ("PHEV", "A", "M2"): 5}
    b = dict(reversed(list(a.items())))
    ta, tb = (mt.build_top("X", "S", "2026-01", u, 10, "u") for u in (a, b))
    assert mt.dumps(ta) == mt.dumps(tb)
    assert [x["brand"] for x in ta["classes"]["PHEV"]["brands"]] == ["A", "B"]
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.json"
        assert mt.write_top(ta, p) is True
        assert mt.write_top(tb, p) is False                   # unchanged → no write
        assert mt.top_as_of(p) == "2026-01"
    assert mt.top_as_of(Path("/nonexistent/x.json")) is None


def test_clean_and_guarded():
    assert mt.clean("  model   y ") == "MODEL Y" and mt.clean(None) == ""
    assert mt.strip_brand("BYD", "BYD DOLPHIN SURF") == "DOLPHIN SURF"
    assert mt.strip_brand("MG", "MGS5") == "MGS5"             # not a word prefix
    assert mt.strip_brand("KIA", "KIA") == "KIA"

    def boom():
        raise KeyError("maker")
    mt.guarded(boom)                                          # must not raise


def test_build_top_monthly_windows_and_months():
    monthly = {
        "2026-08": ({("BEV", "TESLA", "MODEL Y"): 5, ("BEV", "BYD", "SEAL"): 1,
                     ("PETROL", "SEAT", "IBIZA"): 94}, 100),
        "2026-07": ({("BEV", "BYD", "SEAL"): 4}, 50),
        "2025-08": ({("BEV", "BYD", "SEAL"): 99}, 999),        # outside the window
    }
    top = mt.build_top_monthly("X", "S", "2026-08", monthly, "u")
    # Only two of twelve months exist: the window says so instead of "12".
    assert top["window"] == {"from": "2026-07", "to": "2026-08", "months": 2}, top["window"]
    assert top["total_registrations"] == 150
    assert top["classes"]["BEV"]["brands"][0] == {"brand": "BYD", "units": 5,  # tie → A-Z
                                                  "share_of_class": 0.5}
    assert [m["period"] for m in top["months"]] == ["2026-08", "2026-07"]   # newest first
    aug = top["months"][0]
    assert aug["total_registrations"] == 100
    assert aug["classes"]["BEV"]["share_of_market"] == 0.06
    assert "PETROL" not in aug["classes"]
    # A gap inside the covered span is listed, never silently bridged.
    gap = mt.build_top_monthly("X", "S", "2026-08",
                               {"2026-08": monthly["2026-08"],
                                "2026-05": monthly["2026-07"]}, "u")
    assert gap["window"]["missing"] == ["2026-06", "2026-07"]
    assert gap["window"]["months"] == 2


def test_brand_only_source_has_no_models():
    top = mt.build_top_monthly("X", "S", "2026-08",
                               {"2026-08": ({("BEV", "TOYOTA", ""): 3,
                                             ("HEV", "TOYOTA", ""): 7}, 20)}, "u")
    assert top["classes"]["BEV"]["models"] == []
    assert top["classes"]["HEV"]["brands"][0]["units"] == 7


def test_month_store_roundtrip_and_prune():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "x_months.json"
        months = {f"2025-{m:02d}": ({("BEV", "A", "M"): m, ("PETROL", "A", "P"): 50}, 100 + m)
                  for m in range(1, 13)}
        months.update({f"2026-{m:02d}": ({("HEV", "B", ""): m}, 10 * m) for m in range(1, 7)})
        assert mt.save_store(path, months, "X", "S") is True
        assert mt.save_store(path, months, "X", "S") is False           # byte-stable
        back = mt.load_store(path)
        assert sorted(back) == sorted(months)[-mt.STORE_MONTHS:]
        assert back["2025-12"] == ({("BEV", "A", "M"): 12}, 112)       # ICE rows dropped, total kept
        assert back["2026-06"] == ({("HEV", "B", ""): 6}, 60)
        json.loads(path.read_text())                                  # still valid JSON
    assert mt.load_store(Path("/nonexistent/x.json")) == {}


def test_top_is_current():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.json"
        mt.write_top(mt.build_top("X", "S", "2026-08", {}, 1, "u"), p)
        assert not mt.top_is_current(p, "2026-08")                   # no months yet
        mt.write_top(mt.build_top_monthly("X", "S", "2026-08",
                                          {"2026-08": ({}, 1)}, "u"), p)
        assert mt.top_is_current(p, "2026-08")
        assert not mt.top_is_current(p, "2026-09")


def _dgt_record(tipo, nu, cat_elec, prop, marca, modelo, clave="1"):
    import fetch_spain as fs
    rec = [" "] * fs.RECORD_LEN

    def put(name, val):
        a, b = fs._slice(name)
        rec[a:b] = list(val.ljust(b - a)[: b - a])
    put("FEC_MATRICULA", "01082026")
    put("COD_TIPO", tipo)
    put("IND_NUEVO_USADO", nu)
    put("CATEGORIA_VEHICULO_ELECTRICO", cat_elec)
    put("COD_PROPULSION_ITV", prop)
    put("MARCA_ITV", marca)
    put("MODELO_ITV", modelo)
    put("CLAVE_TRAMITE", clave)
    return "".join(rec)


def test_spain_aggregate_models():
    import fetch_spain as fs
    lines = ["Fichero de microdatos (banner line)",
             _dgt_record("40", "N", "BEV", "2", "TESLA", "MODEL Y"),
             _dgt_record("40", "N", "BEV", "2", "TESLA", "MODEL  Y "),   # same model
             _dgt_record("40", "N", "BEV", "2", "TESLA", "TESLA MODEL Y"),  # brand repeated
             _dgt_record("25", "N", "PHEV", "0", "BYD", "SEAL U DM-I"),
             _dgt_record("40", "N", "", "0", "SEAT", "IBIZA"),
             _dgt_record("40", "U", "BEV", "2", "TESLA", "MODEL 3"),      # used → out
             _dgt_record("50", "N", "BEV", "2", "SILENCE", "S01")]        # moto → out
    txt = ("\n".join(lines) + "\n").encode("latin-1")
    units, total = fs.aggregate_models(txt)
    assert total == 5, total
    assert units == {("BEV", "TESLA", "MODEL Y"): 3, ("PHEV", "BYD", "SEAL U DM-I"): 1,
                     ("PETROL", "SEAT", "IBIZA"): 1}, units
    # The total must equal what aggregate() writes to data/Spain.csv (scaled
    # past its 2,000-record corruption guard).
    big = ("\n".join([lines[0]] + lines[1:] * 600) + "\n").encode("latin-1")
    counts = fs.aggregate(big, "2026-08", ["Whole"])["Whole"]
    big_units, big_total = fs.aggregate_models(big)
    assert big_total == counts["TOTAL"] == 3000
    for cls in ("BEV", "PHEV", "PETROL"):
        assert sum(n for (c, _, _), n in big_units.items() if c == cls) == counts[cls]


def test_spain_latest_dgt_period():
    import fetch_spain as fs
    rows = [{"period": "2026-07", "variant": "Whole", "source": "DGT"},
            {"period": "2026-08", "variant": "Whole", "source": "DGT"},
            {"period": "2026-09", "variant": "Whole", "source": "ACEA"}]
    assert fs.latest_dgt_period(rows) == "2026-08"
    assert fs.latest_dgt_period([]) is None


def test_malaysia_build_top():
    try:
        import pandas as pd
    except ImportError:
        print("   (pandas missing — Malaysia test skipped)")
        return
    import fetch_malaysia as fm
    df = pd.DataFrame({
        "date_reg": ["2026-08-03", "2026-08-09", "2025-09-01", "2025-08-31", "2026-08-10", "2026-02-02"],
        "maker":    ["BYD", "byd ", "Proton", "BYD", "Toyota", "Proton"],
        "model":    ["Atto 3", "ATTO 3", "e.MAS 7", "Atto 3", "Vios", "Saga"],
        "fuel":     ["electric", "Electric", "electric", "electric", "hybrid_petrol", "petrol"],
    })
    top = fm.build_top([df], "2026-08")
    assert top["total_registrations"] == 5                  # 2025-08 is outside
    assert [m["period"] for m in top["months"]] == ["2026-08", "2026-02", "2025-09"]
    assert top["months"][0]["total_registrations"] == 3
    assert top["months"][0]["classes"]["BEV"]["units"] == 2
    bev = top["classes"]["BEV"]
    assert bev["units"] == 3 and bev["brands"][0] == {"brand": "BYD", "units": 2,
                                                       "share_of_class": 0.6667}
    assert bev["models"][0]["model"] == "ATTO 3"
    assert top["classes"]["HEV"]["units"] == 1 and "PETROL" not in top["classes"]
    json.dumps(top)                                          # numpy ints would fail here


def test_japan_maker_rows():
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        print("   (openpyxl missing — Japan test skipped)")
        return
    import fetch_japan as fj
    sample = Path(__file__).resolve().parent.parent / "data" / "202605081028169165.xlsx"
    if not sample.exists():
        print("   (JADA sample workbook missing — Japan test skipped)")
        return
    months = fj.parse_xlsx_makers(sample.read_bytes())
    assert sorted(months) == ["2026-01", "2026-02", "2026-03", "2026-04"]
    units, total = months["2026-04"]
    # Same numbers as the 乗用車計 row that data/Japan.csv carries for 2026-04.
    fuels = fj.parse_xlsx(sample.read_bytes(), 2026, 4)
    assert total == fuels["TOTAL"] == 223369
    for cls in ("BEV", "PHEV", "HEV"):
        assert sum(n for (c, _, _), n in units.items() if c == cls) == fuels[cls]
    assert units[("BEV", "IMPORTS (ALL BRANDS)", "")] == 2761
    assert units[("BEV", "TOYOTA", "")] == 1957
    top = mt.build_top_monthly("Japan", "JADA", "2026-04", months, fj.TOP_UNIT)
    assert top["window"]["months"] == 4 and top["classes"]["BEV"]["models"] == []


def test_singapore_makes_via_store():
    import fetch_singapore as fsg
    assert fsg.make_of("bmw ad") == "BMW"
    assert fsg.make_of("mercedes  benz parallel importer") == "MERCEDES BENZ"
    try:
        fsg.make_of("bmw xyz")
        raise AssertionError("unknown importer type must stop the refresh")
    except ValueError:
        pass
    makes = {("2026-08", "BEV", "byd ad"): 300, ("2026-08", "BEV", "byd pi"): 20,
             ("2026-08", "BEV", "tesla ad"): 100, ("2026-08", "PETROL", "toyota ad"): 580,
             ("2026-07", "HEV", "toyota ad"): 50}
    periods = {"2026-08": {"BEV": 420.0, "PETROL": 580.0}, "2026-07": {"HEV": 50.0}}
    old = mt.MARKET_DIR
    with tempfile.TemporaryDirectory() as d:
        mt.MARKET_DIR = Path(d)
        try:
            fsg.refresh_top(makes, periods)
            top = json.loads((Path(d) / "singapore_top.json").read_text())
            store = mt.load_store(Path(d) / "singapore_months.json")
            # A later half-year PDF only restates newer months: older ones stay.
            fsg.refresh_top({("2026-09", "BEV", "byd ad"): 7}, {"2026-09": {"BEV": 7.0}})
            top2 = json.loads((Path(d) / "singapore_top.json").read_text())
        finally:
            mt.MARKET_DIR = old
    assert top["total_registrations"] == 1050 and top["window"]["months"] == 2
    assert top["classes"]["BEV"]["brands"][0] == {"brand": "BYD", "units": 320,
                                                  "share_of_class": 0.7619}
    assert store["2026-08"][1] == 1000 and ("PETROL", "TOYOTA", "") not in store["2026-08"][0]
    assert top2["as_of"] == "2026-09" and top2["window"]["months"] == 3
    assert top2["classes"]["BEV"]["units"] == 427


def _acau_workbook(model_header="Modelo"):
    import io
    import openpyxl
    import fetch_uruguay as fu
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    sheets = {"AUTOS": [("BYD", "BYD DOLPHIN", "E", 10, 12), ("TOYOTA", "COROLLA", "H", 5, 0),
                        ("SUZUKI", "SWIFT", "MHEV", 2, 3), ("FIAT", "CRONOS", "N", 30, 20)],
              "SUV": [("BYD", "SONG PRO", "PHEV", 4, 1), ("BYD", "YUAN PRO", "e", 6, 8)]}
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        ws.append([None])
        ws.append(["COMPILADO 2026"])
        ws.append(["Nombre_Socio", "Marca", model_header, "Combustible"] + fu.SPANISH_MONTHS)
        for b, m, f, jan, feb in rows:
            ws.append(["SOCIO SA", b, m, f, jan, feb] + [0] * 10)
        ws.append(["TOTAL", None, None, None, sum(r[3] for r in rows),
                   sum(r[4] for r in rows)] + [0] * 10)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_uruguay_models():
    try:
        import openpyxl  # noqa: F401
        import bs4  # noqa: F401
    except ImportError:
        print("   (openpyxl/bs4 missing — Uruguay test skipped)")
        return
    import fetch_uruguay as fu
    months = fu.parse_models(_acau_workbook(), 2026)
    assert sorted(months) == ["2026-01", "2026-02"]
    jan, jan_total = months["2026-01"]
    assert jan_total == 57                     # = the Whole TOTAL the CSV gets
    assert jan[("BEV", "BYD", "DOLPHIN")] == 10           # brand prefix stripped
    assert jan[("BEV", "BYD", "YUAN PRO")] == 6           # lower-case code 'e'
    assert jan[("MHEV", "SUZUKI", "SWIFT")] == 2
    assert ("HEV", "TOYOTA", "COROLLA") not in months["2026-02"][0]   # zero → absent
    try:
        fu.parse_models(_acau_workbook("Version"), 2026)
        raise AssertionError("a missing model column must stop the refresh")
    except RuntimeError as e:
        assert "brand/model column" in str(e)


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} tests passed")
