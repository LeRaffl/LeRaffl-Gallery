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
    assert list(top["classes"]) == ["BEV", "HEV", "PETROL"]  # OTHERS never listed
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
    # PETROL is ranked in the month that has it, but kept out of the headline:
    # July has no PETROL rows (a month stored before combustion was counted).
    assert aug["classes"]["PETROL"]["brands"][0] == {"brand": "SEAT", "units": 94,
                                                     "share_of_class": 1.0}
    assert "PETROL" not in top["classes"]
    assert top["schema"] == mt.SCHEMA
    # A gap inside the covered span is listed, never silently bridged.
    gap = mt.build_top_monthly("X", "S", "2026-08",
                               {"2026-08": monthly["2026-08"],
                                "2026-05": monthly["2026-07"]}, "u")
    assert gap["window"]["missing"] == ["2026-06", "2026-07"]
    assert gap["window"]["months"] == 2


def test_combustion_ranked_like_electrified():
    """PETROL / DIESEL get rankings when passed; OTHERS only counts in the total."""
    top = mt.build_top_monthly("X", "S", "2026-08",
                               {"2026-08": ({("BEV", "TESLA", "MODEL Y"): 10,
                                             ("PETROL", "TOYOTA", "YARIS"): 30,
                                             ("PETROL", "KIA", "PICANTO"): 10,
                                             ("DIESEL", "FORD", "RANGER"): 20,
                                             ("OTHERS", "DACIA", "SANDERO LPG"): 30}, 100)}, "u")
    assert list(top["classes"]) == ["BEV", "PETROL", "DIESEL"]
    assert top["classes"]["PETROL"]["share_of_market"] == 0.4
    assert top["classes"]["PETROL"]["models"][0] == {"brand": "TOYOTA", "model": "YARIS",
                                                     "units": 30, "share_of_class": 0.75}
    assert top["classes"]["DIESEL"]["brands"] == [{"brand": "FORD", "units": 20,
                                                   "share_of_class": 1.0}]


def test_genuine_zero_diesel_month_keeps_diesel_in_headline():
    """A month with petrol but no diesel was counted (a real zero, Uruguay
    2026-02); only a month without any combustion row is a store gap."""
    monthly = {"2026-02": ({("BEV", "A", ""): 5, ("PETROL", "B", ""): 50}, 60),
               "2026-03": ({("BEV", "A", ""): 5, ("PETROL", "B", ""): 40,
                            ("DIESEL", "C", ""): 3}, 50)}
    top = mt.build_top_monthly("X", "S", "2026-03", monthly, "u")
    assert top["classes"]["DIESEL"]["units"] == 3 and top["classes"]["PETROL"]["units"] == 90
    gap = dict(monthly, **{"2026-01": ({("BEV", "A", ""): 5}, 30)})   # stored before
    top = mt.build_top_monthly("X", "S", "2026-03", gap, "u")
    assert "PETROL" not in top["classes"] and "DIESEL" not in top["classes"]
    assert "DIESEL" in top["months"][0]["classes"]


def test_erev_ranked_inside_phev():
    """PHEV's incl_erev ranks PHEV + EREV from the raw units (a brand's EREV
    outside the EREV top list still counts); EREV models are flagged."""
    units = {("PHEV", "BYD", "SEAL U"): 10, ("PHEV", "LEAPMOTOR", "C10"): 1,
             ("EREV", "LEAPMOTOR", "C10"): 6, ("EREV", "DEEPAL", "S05"): 3}
    top = mt.build_top("X", "S", "2026-08", units, 100, "u", top_brands=1, top_models=3)
    assert top["classes"]["PHEV"]["units"] == 11 and top["classes"]["EREV"]["units"] == 9
    both = top["classes"]["PHEV"]["incl_erev"]
    assert both["units"] == 20 and both["share_of_market"] == 0.2
    assert both["brands"] == [{"brand": "BYD", "units": 10, "share_of_class": 0.5}]
    assert both["models"][1] == {"brand": "LEAPMOTOR", "model": "C10", "units": 7,
                                 "share_of_class": 0.35, "erev": True}
    assert "erev" not in both["models"][0]
    assert "incl_erev" not in mt.build_top("X", "S", "2026-08", {("PHEV", "A", "B"): 1},
                                           1, "u")["classes"]["PHEV"]


def test_brand_only_source_has_no_models():
    top = mt.build_top_monthly("X", "S", "2026-08",
                               {"2026-08": ({("BEV", "TOYOTA", ""): 3,
                                             ("HEV", "TOYOTA", ""): 7}, 20)}, "u")
    assert top["classes"]["BEV"]["models"] == []
    assert top["classes"]["HEV"]["brands"][0]["units"] == 7


def test_month_store_roundtrip_and_prune():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "x_months.json"
        months = {f"2025-{m:02d}": ({("BEV", "A", "M"): m, ("PETROL", "A", "P"): 5,
                                     ("OTHERS", "A", "Q"): 50}, 100 + m)
                  for m in range(1, 13)}
        months.update({f"2026-{m:02d}": ({("HEV", "B", ""): m}, 10 * m) for m in range(1, 7)})
        assert mt.save_store(path, months, "X", "S") is True
        assert mt.save_store(path, months, "X", "S") is False           # byte-stable
        back = mt.load_store(path)
        assert sorted(back) == sorted(months)[-mt.STORE_MONTHS:]
        assert back["2025-12"] == ({("BEV", "A", "M"): 12, ("PETROL", "A", "P"): 5},
                                   112)                                # OTHERS dropped, total kept
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
        old = json.loads(p.read_text())
        del old["schema"]                                             # written before PETROL / DIESEL
        p.write_text(json.dumps(old))
        assert not mt.top_is_current(p, "2026-08")


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
             _dgt_record("40", "U", "BEV", "2", "TESLA", "MODEL 3"),      # used import
             _dgt_record("25", "U", "HEV", "0", "TOYOTA", "C-HR"),         # used import
             _dgt_record("40", "U", "BEV", "2", "NISSAN", "LEAF", clave="9"),  # re-plate → out
             _dgt_record("50", "N", "BEV", "2", "SILENCE", "S01")]        # moto → out
    txt = ("\n".join(lines) + "\n").encode("latin-1")
    out = fs.aggregate_models(txt)
    units, total = out["Whole"]
    assert total == 5, total
    assert units == {("BEV", "TESLA", "MODEL Y"): 3, ("PHEV", "BYD", "SEAL U DM-I"): 1,
                     ("PETROL", "SEAT", "IBIZA"): 1}, units
    assert out["Used"] == ({("BEV", "TESLA", "MODEL 3"): 1, ("HEV", "TOYOTA", "C-HR"): 1}, 2)
    # Each total must equal what aggregate() writes to that variant's CSV
    # (scaled past its 2,000-record corruption guard).
    big = ("\n".join([lines[0]] + lines[1:] * 600) + "\n").encode("latin-1")
    counts = fs.aggregate(big, "2026-08", ["Whole", "Used"])
    for v, (big_units, big_total) in fs.aggregate_models(big).items():
        assert big_total == counts[v]["TOTAL"], v
        for cls in ("BEV", "PHEV", "HEV", "PETROL"):
            assert sum(n for (c, _, _), n in big_units.items() if c == cls) == counts[v][cls]


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
    sample = Path(__file__).resolve().parent / "fixtures" / "202605081028169165.xlsx"
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
    assert fsg.make_of("alfa romeo amd") == "ALFA ROMEO"              # M03's real code
    assert fsg.make_of("mercedes  benz parallel importer") == "MERCEDES BENZ"
    try:
        fsg.make_of("bmw xyz")
        raise AssertionError("unknown importer type must stop the refresh")
    except ValueError:
        pass
    makes = {("2026-08", "BEV", "byd amd"): 300, ("2026-08", "BEV", "byd pi"): 20,
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
    assert store["2026-08"][1] == 1000 and store["2026-08"][0][("PETROL", "TOYOTA", "")] == 580
    # July has no PETROL row, so the headline leaves petrol out; August shows it.
    assert "PETROL" not in top["classes"]
    assert top["months"][0]["classes"]["PETROL"]["brands"][0]["brand"] == "TOYOTA"
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


class _FakeTraficom:
    """Two PxWeb tables shaped like Traficom's: makes with Maakunta + Vuosi +
    Kuukausi, model series with Alue + a single YYYYMmm month variable."""
    FUELS = [("YH", "Yhteensä"), ("01", "Bensiini"), ("04", "Sähkö"),
             ("39", "Bensiini/Sähkö (ladattava hybridi)"), ("41", "Bensiini/Sähkö (ei ladattava)")]
    # month -> {(fuel code, make): n}
    MAKES = {"2026-07": {("04", "Tesla"): 100, ("04", "Volvo"): 50, ("39", "Volvo"): 80,
                         ("01", "Toyota"): 300, ("41", "Toyota"): 200},
             "2026-08": {("04", "Tesla"): 60, ("04", "Mercedes-Benz"): 40, ("01", "Skoda"): 400}}
    SERIES = {"2026-07": {("04", "Tesla Model Y"): 70, ("04", "Tesla Model 3"): 30,
                          ("04", "Volvo EX30"): 50, ("39", "Volvo XC60"): 80,
                          ("01", "Toyota Corolla"): 300, ("41", "Toyota Yaris"): 200},
              "2026-08": {("04", "Tesla Model Y"): 60, ("04", "Mercedes-Benz EQA"): 40,
                          ("01", "Skoda Octavia"): 400}}

    def table(self, *words):
        return "makes" if "merkki" in words else "series"

    def meta(self, url):
        fuel = {"code": "Käyttövoima", "text": "Käyttövoima",
                "values": [c for c, _ in self.FUELS], "valueTexts": [t for _, t in self.FUELS]}
        if url == "makes":
            makes = sorted({m for d in self.MAKES.values() for _, m in d})
            return {"variables": [
                {"code": "Maakunta", "text": "Maakunta", "values": ["SSS", "01"],
                 "valueTexts": ["KOKO MAA", "Uusimaa"]},
                {"code": "Merkki", "text": "Merkki", "values": makes, "valueTexts": makes},
                fuel,
                {"code": "Vuosi", "text": "Vuosi", "values": ["2025", "2026"], "valueTexts": ["2025", "2026"]},
                {"code": "Kuukausi", "text": "Kuukausi", "values": [f"{m:02d}" for m in range(1, 13)],
                 "valueTexts": [f"{m:02d}" for m in range(1, 13)]}]}
        series = sorted({m for d in self.SERIES.values() for _, m in d})
        return {"variables": [
            {"code": "Alue", "text": "Alue", "values": ["X"], "valueTexts": ["Alue"], "elimination": True},
            {"code": "Mallisarja", "text": "Mallisarja", "values": series, "valueTexts": series},
            fuel,
            {"code": "Kuukausi", "text": "Kuukausi", "values": ["2026M07", "2026M08"],
             "valueTexts": ["2026M07", "2026M08"]}]}

    def query(self, url, items):
        sel = {i["code"]: i["selection"]["values"] for i in items}
        if url == "makes":
            period = f"{sel['Vuosi'][0]}-{sel['Kuukausi'][0]}"
            data, key = self.MAKES.get(period, {}), "Merkki"
        else:
            p = sel["Kuukausi"][0]
            data, key = self.SERIES.get(f"{p[:4]}-{p[5:]}", {}), "Mallisarja"
        assert "Alue" not in sel                         # eliminable → left out
        if url == "makes":
            assert sel["Maakunta"] == ["SSS"]            # pinned to the whole country
        names = sorted({m for _, m in data}) or ["none"]
        fuels = sel["Käyttövoima"]
        assert "YH" not in fuels
        fl = dict(self.FUELS)
        return {"id": [key, "Käyttövoima"], "size": [len(names), len(fuels)],
                "dimension": {key: {"category": {"index": {n: i for i, n in enumerate(names)},
                                                 "label": {n: n for n in names}}},
                              "Käyttövoima": {"category": {"index": fuels,
                                                           "label": {f: fl[f] for f in fuels}}}},
                "value": [data.get((f, n), None) for n in names for f in fuels]}


def test_finland_traficom():
    import fetch_finland as ff
    assert ff.fuel_class("Sähkö") == "BEV"
    assert ff.fuel_class("Diesel/Sähkö (ladattava hybridi)") == "PHEV"
    assert ff.fuel_class("Bensiini/Sähkö (ei ladattava)") == "PETROL"  # 121d: in Petrol
    assert ff.fuel_class("Bensiini") == "PETROL" and ff.fuel_class("Diesel") == "DIESEL"
    assert "DIESEL" not in ff.TOP_CLASSES                    # Traficom's diesel ≠ StatFin's
    assert ff.fuel_class("Bensiini/CNG") == "OTHER"
    assert ff.fuel_class("Yhteensä") is None
    assert ff.split_series("Mercedes-Benz EQA", ["MERCEDES-BENZ", "MERCEDES"]) == ("MERCEDES-BENZ", "EQA")
    brands, models = ff.collect_top(_FakeTraficom(), "2026-08")
    assert sorted(brands) == ["2026-07", "2026-08"]
    jul, jul_total = brands["2026-07"]
    assert jul_total == 730                                  # every fuel, never the Yhteensä code
    assert jul[("BEV", "VOLVO", "")] == 50 and jul[("PETROL", "TOYOTA", "")] == 500
    assert models["2026-07"][0][("BEV", "TESLA", "MODEL Y")] == 70
    top = mt.build_top_monthly("Finland", "S", "2026-08", brands, "u")
    mt.splice_models(top, mt.build_top_monthly("Finland", "S", "2026-08", models, "u"))
    bev = top["classes"]["BEV"]
    assert bev["units"] == 250 and bev["brands"][0]["brand"] == "TESLA"
    assert bev["models"][0] == {"brand": "TESLA", "model": "MODEL Y", "units": 130,
                                "share_of_class": 0.52}
    assert top["classes"]["PETROL"]["models"][0] == {"brand": "SKODA", "model": "OCTAVIA",
                                                     "units": 400, "share_of_class": 0.4444}
    aug = top["months"][0]
    assert aug["period"] == "2026-08" and aug["classes"]["BEV"]["models"][1]["model"] == "EQA"
    # A model table that disagrees with the makes drops only the designations.
    bad = _FakeTraficom()
    bad.SERIES = {"2026-07": {("04", "Tesla Model Y"): 10}}
    b2, m2 = ff.collect_top(bad, "2026-08")
    assert m2 == {} and b2["2026-07"][1] == 730
    # Scope check against the CSV: a BEV mismatch publishes nothing.
    with tempfile.TemporaryDirectory() as d:
        csvp = Path(d) / "F.csv"
        csvp.write_text("period,variant,BEV,TOTAL\n2026-07,Whole,150,730\n")
        ff.check_against_csv(brands, str(csvp))
        csvp.write_text("period,variant,BEV,TOTAL\n2026-07,Whole,300,730\n")
        try:
            ff.check_against_csv(brands, str(csvp))
            raise AssertionError("BEV mismatch must stop the refresh")
        except RuntimeError:
            pass


def _de2_ods(months: dict) -> bytes:
    """A minimal DE2 .ods: one sheet per month with Tabelle 2, 7 and 14."""
    import io
    import zipfile
    import fetch_austria as fa
    T = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
    X = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"

    def row(*cells):
        return ("<table:table-row>" + "".join(
            f"<table:table-cell><text:p>{c}</text:p></table:table-cell>" for c in cells)
            + "</table:table-row>")
    sheets = []
    for name, (fuels, t7, t14) in months.items():
        rows = [row("Tabelle 2: Pkw-Neuzulassungen nach Kraftstoffart bzw. Energiequelle")]
        rows += [row(k, v) for k, v in fuels.items()] + [row("Q: STATISTIK AUSTRIA")]
        for num, t in ((7, t7), (14, t14)):
            rows.append(row(f"Tabelle {num}: Pkw-Neuzulassungen nach TOP 10 Marken und Typen mit Elektroantrieb"))
            rows.append(row("Marke", "Monat", "Anteil in %"))
            rows += [row(b, n, "1.0") for b, n in t["brands"]]
            rows.append(row("Sonstige Pkw mit Elektroantrieb", t["rest_b"]))
            rows.append(row("Marke/Type", "", ""))
            rows += [row(m, n, "1.0") for m, n in t["types"]]
            rows.append(row("Sonstige Pkw mit Elektroantrieb", t["rest_t"]))
            rows.append(row("Pkw mit Elektroantrieb insgesamt", t["total"]))
            rows.append(row("Q: STATISTIK AUSTRIA, Kfz-Statistik"))
        sheets.append(f'<table:table table:name="{name}">' + "".join(rows) + "</table:table>")
    xml = (f'<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
           f'xmlns:table="{T}" xmlns:text="{X}"><office:body><office:spreadsheet>'
           + "".join(sheets) + "</office:spreadsheet></office:body></office:document-content>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("content.xml", xml)
    assert fa.L_TOTAL == "Pkw insgesamt"
    return buf.getvalue()


def test_austria_top_bev():
    import fetch_austria as fa

    def fuels(bev, total):
        return {"Benzin": total - bev - 30, "Diesel": 10, "Elektro": bev,
                "Benzin/Elektro (hybrid)": 20, "darunter Benzin/Elektro (hybrid) – Plug-In": 5,
                "Diesel/Elektro (hybrid)": 0, "darunter Diesel/Elektro (hybrid) – Plug-In": 0,
                "Pkw insgesamt": total}
    jul7 = {"brands": [("BMW", 50), ("BYD", 30)], "rest_b": 20,
            "types": [("BMW X1", 40), ("BYD ATTO", 25)], "rest_t": 35, "total": 100}
    aug7 = {"brands": [("BYD", 60), ("TESLA", 40)], "rest_b": 50,
            "types": [("TESLA MODEL Y", 40), ("BYD SEALION", 30)], "rest_t": 80, "total": 150}
    aug14 = {"brands": [("BYD", 90), ("BMW", 70), ("TESLA", 45)], "rest_b": 45,
             "types": [("TESLA MODEL Y", 45), ("BMW X1", 44)], "rest_t": 161, "total": 250}
    ods = _de2_ods({"Juli": (fuels(100, 1000), jul7, jul7),
                    "August": (fuels(150, 900), aug7, aug14)})
    top = fa.build_austria_top(ods, 2026)
    assert top["window"] == {"from": "2026-01", "to": "2026-08", "months": 2}
    assert top["total_registrations"] == 1900
    bev = top["classes"]["BEV"]
    assert bev["units"] == 250                                # the YTD table, rest included
    assert [b["brand"] for b in bev["brands"]] == ["BYD", "BMW", "TESLA"]  # never "Sonstige"
    assert bev["models"][0] == {"brand": "TESLA", "model": "MODEL Y", "units": 45,
                                "share_of_class": 0.18}
    aug = top["months"][0]
    assert aug["period"] == "2026-08" and aug["classes"]["BEV"]["units"] == 150
    assert aug["classes"]["BEV"]["models"][1]["model"] == "SEALION"
    # A Tabelle 7 total that disagrees with Tabelle 2's Elektro stops the refresh.
    bad = _de2_ods({"August": (fuels(149, 900), aug7, aug14)})
    try:
        fa.build_austria_top(bad, 2026)
        raise AssertionError("Tabelle 7 vs Tabelle 2 mismatch must raise")
    except RuntimeError:
        pass


class _FakeSimi:
    ENGINE = [{"value": "03", "name": "Electric"}, {"value": "16", "name": "Petrol/Plug-In Electric Hybrid"},
              {"value": "15", "name": "Diesel/Plug-In Electric Hybrid"}, {"value": "01", "name": "Petrol"},
              {"value": "08", "name": "Petrol Electric (Hybrid)"}]
    COLS = {"2026-07": {"BEV": 100.0, "PHEV": 40.0, "HEV": 0.0, "PETROL": 360.0},
            "2026-08": {"BEV": 50.0, "PHEV": 0.0, "HEV": 10.0, "PETROL": 140.0}}

    def __init__(self):
        self.calls = []

    def fetch_month(self, variant, y, m):
        return dict(self.COLS.get(f"{y}-{m:02d}", {}))

    def partial(self, variant, y, m, props, extra=None):
        if props == "engineTypes":
            return {"engineTypes": self.ENGINE}
        codes = sorted(o["value"] for o in (extra or {}).get("engine_types", []))
        self.calls.append((f"{y}-{m:02d}", codes))
        k = 1 if m == 7 else 2                                # August: half the cars
        if codes == ["03"]:
            return {"carsByMake": {"datasets": [
                        {"label": "Tesla", "units": [{"count": 60 // k}]},
                        {"label": "KIA", "units": [{"count": 30 // k}]}]},
                    "carsByModel": {"datasets": [
                        {"labels": {"make": "TESLA", "model": "MODEL Y"}, "units": [{"count": 60 // k}]}]}}
        return {"carsByMake": {"datasets": [{"label": "TOYOTA", "units": [{"count": 5}]}]},
                "carsByModel": {"datasets": []}}


def test_ireland_top():
    import fetch_ireland as fi
    c = _FakeSimi()
    makes, models = fi.collect_top(c, ["2026-07", "2026-08"])
    assert ("2026-07", ["15", "16"]) in c.calls           # both plug-in codes in one filter
    jul, total = makes["2026-07"]
    assert total == 500
    assert jul[("BEV", "TESLA", "")] == 60 and jul[("BEV", mt.REST, "")] == 10
    assert models["2026-07"][0][("BEV", mt.REST, "")] == 40
    top = mt.build_top_monthly("Ireland", "S", "2026-08", makes, "u")
    mt.splice_models(top, mt.build_top_monthly("Ireland", "S", "2026-08", models, "u"))
    bev = top["classes"]["BEV"]
    assert bev["units"] == 150 and bev["brands"][0]["brand"] == "TESLA"
    assert all(b["brand"] for b in bev["brands"])          # the rest is never ranked
    assert bev["models"][0]["model"] == "MODEL Y" and bev["models"][0]["units"] == 90
    try:
        fi.with_rest({("BEV", "X", ""): 11}, "BEV", 10, "makes")
        raise AssertionError("listed > total must raise")
    except RuntimeError:
        pass


def test_netherlands_rdw_top():
    import fetch_netherlands as fn
    # class = the CSV's split: BEV electricity-only, PHEV OVC-HEV, petrol incl.
    # full hybrids (unsplit, like Swing's Benzine), rest — diesel too — unranked
    assert fn.powertrain_class([("Elektriciteit", "")]) == "BEV"
    assert fn.powertrain_class([("Benzine", "OVC-HEV"), ("Elektriciteit", "OVC-HEV")]) == "PHEV"
    assert fn.powertrain_class([("Benzine", "NOVC-HEV"), ("Elektriciteit", "NOVC-HEV")]) == "PETROL"
    assert fn.powertrain_class([("Benzine", "")]) == "PETROL"
    assert fn.powertrain_class([("Diesel", "")]) == ""           # motorhomes, not Swing's diesel
    assert fn.powertrain_class([("Benzine", ""), ("LPG", "")]) == ""
    assert fn.powertrain_class([("Waterstof", "NOVC-FCHV"), ("Elektriciteit", "NOVC-FCHV")]) == ""
    assert fn.powertrain_class([]) == ""
    assert fn.next_month("2025-12") == "2026-01" and fn.next_month("2026-06") == "2026-07"
    # display names: brand aliases, prefix, engine / power / trim codes
    dm = fn.display_model
    assert dm("VOLKSWAGEN", "ID.4 PRO 210KW") == "ID.4"
    assert dm("VOLKSWAGEN", "ID. BUZZ PRO LR 210 KW") == "ID. BUZZ"
    assert dm("BMW", "IX3 50 XDRIVE") == "IX3" and dm("BMW", "330E XDRIVE") == "330E"
    assert dm("MERCEDES-BENZ", "CLA 250+") == "CLA" and dm("MERCEDES-BENZ", "GLC 400 4MATIC WITH EQ TE") == "GLC"
    assert dm("AUDI", "Q4 SPORTBACK 45 E-TRON") == "Q4 E-TRON" and dm("AUDI", "Q3 SB 200KW TFSI E") == "Q3"
    assert dm("SKODA", "ELROQ 85") == "ELROQ" and dm("SKODA", "ENYAQ RS") == "ENYAQ"
    assert dm("RENAULT", "RENAULT 5 E-TECH ELECTRIC") == "5" and dm("TESLA", "Model Y") == "MODEL Y"
    assert dm("MG", "MG4 EV URBAN") == "4" and dm("MG", "MG S5 EV") == "S5"
    assert dm("MINI", "COUNTRYMAN SE ALL4") == "COUNTRYMAN" and dm("HYUNDAI", "IONIQ5 N") == "IONIQ 5 N"
    assert dm("PEUGEOT", "3008") == "3008" and dm("BYD", "BYD SEAL U DM-I") == "SEAL U"
    assert dm("LEXUS", "LEXUS RZ350E") == "RZ" and dm("LYNK&CO", "LYNK & CO 01") == "01"
    assert fn.display_brand("DS AUTOMOBILES") == "DS" and fn.display_brand("Lynk&Co") == "LYNK & CO"

    # month aggregation over a fake RDW: scope filter is in the query, the class
    # comes from the fuel table, the total counts every plate
    cars = [{"kenteken": "AA1", "merk": "TESLA", "handelsbenaming": "MODEL Y"},
            {"kenteken": "AA2", "merk": "TESLA", "handelsbenaming": "MODEL Y"},
            {"kenteken": "AA3", "merk": "VOLVO", "handelsbenaming": "XC60"},
            {"kenteken": "AA4", "merk": "TOYOTA", "handelsbenaming": "TOYOTA YARIS"},
            {"kenteken": "AA5", "merk": "KIA", "handelsbenaming": "EV3"}]   # no fuel row
    fuel = [{"kenteken": "AA1", "brandstof_omschrijving": "Elektriciteit"},
            {"kenteken": "AA2", "brandstof_omschrijving": "Elektriciteit"},
            {"kenteken": "AA3", "brandstof_omschrijving": "Benzine",
             "klasse_hybride_elektrisch_voertuig": "OVC-HEV"},
            {"kenteken": "AA3", "brandstof_omschrijving": "Elektriciteit",
             "klasse_hybride_elektrisch_voertuig": "OVC-HEV"},
            {"kenteken": "AA4", "brandstof_omschrijving": "Benzine"}]
    seen = []

    def fake_get(session, resource, params):
        seen.append((resource, params))
        if resource == fn.RDW_VEHICLES:
            return cars[params["$offset"]:params["$offset"] + params["$limit"]]
        return [r for r in fuel if f"'{r['kenteken']}'" in params["$where"]]
    real = fn.rdw_get
    fn.rdw_get = fake_get
    try:
        units, total = fn.aggregate_month(None, "2026-06")
    finally:
        fn.rdw_get = real
    assert total == 5
    assert units == {("BEV", "TESLA", "MODEL Y"): 2, ("PHEV", "VOLVO", "XC60"): 1,
                     ("PETROL", "TOYOTA", "YARIS"): 1}
    where = seen[0][1]["$where"]
    assert "2026-06-01" in where and "2026-07-01" in where and "export_indicator='Nee'" in where
    # Whole: admitted in the month; Used: admitted before it (a used import)
    assert "datum_eerste_toelating_dt >= '2026-06-01'" in where
    seen.clear()
    fn.rdw_get = fake_get
    try:
        u_units, u_total = fn.aggregate_month(None, "2026-06", "Used")
    finally:
        fn.rdw_get = real
    used_where = seen[0][1]["$where"]
    assert "datum_eerste_toelating_dt < '2026-06-01'" in used_where
    assert "datum_eerste_toelating_dt >= '2026-06-01'" not in used_where
    assert "datum_eerste_tenaamstelling_in_nederland_dt >= '2026-06-01'" in used_where
    assert (u_units, u_total) == (units, total)          # same fake plates, same class logic
    # one top file + month store per variant, slugs feed market_top's paths
    assert fn.TOP_SLUGS == {"Whole": "netherlands", "Used": "netherlands_used"}
    assert set(fn.TOP_UNITS) == set(fn.TOP_SLUGS) and "used" in fn.TOP_UNITS["Used"]
    top = mt.build_top_monthly("Netherlands", "S", "2026-06", {"2026-06": (units, total)}, "u")
    assert top["classes"]["BEV"]["models"][0]["units"] == 2
    assert top["classes"]["PHEV"]["brands"][0]["brand"] == "VOLVO"

    # scope check: small deviations pass, a scope change aborts the refresh
    mt.check_scope({"2026-05": 1010, "2026-06": 1000, "2026-07": 5},
                   {"2026-05": 1000, "2026-06": 1000})          # 2026-07: not in the CSV
    try:
        mt.check_scope({"2026-06": 1200}, {"2026-06": 1000})
        raise AssertionError("a 20 % deviation must raise")
    except RuntimeError:
        pass


def test_israel_top():
    import fetch_israel as fi
    # manufacturer: Hebrew "<brand> <country>", cut off at 14 characters, punctuation-blind
    b = fi.display_brand
    assert b("טויוטה יפן") == b("טויוטה צרפת") == "TOYOTA"
    assert b("מרצדס בנץ גרמנ") == "MERCEDES-BENZ" and b("בי ווי די סין") == "BYD"
    assert b("מ.ג סין") == "MG" and b("ב מ וו ארהב\"") == "BMW" and b("גי.אי.סי סין") == "GAC"
    assert b("ג'אקו סין") == "JAECOO" and b("ג'אק סין") == "JAC"      # longest stem wins
    assert b("פולקסווגן-ספרד") == "VOLKSWAGEN" and b("קיה ד. קוריאה") == "KIA"
    assert b("לינק אנד קו") == "LYNK & CO" and b("רובר אנגליה") == "LAND ROVER"
    assert b("איויאיסי סין") == "איויאיסי סין"                          # unknown: shown, not merged
    # commercial name: brand prefix, glued digits, drive / trim words
    m = fi.display_model
    assert m("JAECOO", "JAECOO7 PHEV") == m("JAECOO", "JAECOO 7 PHEV") == "7"
    assert m("CHERY", "TIGGO8PRO PHEV") == m("CHERY", "TIGGO8 PRO PHEV") == "TIGGO 8"
    assert m("LYNK & CO", "LYNKCO08 PHEV") == "08" and m("MG", "MG4") == "4"
    assert m("BYD", "BYD SEAL U") == "SEAL U" and m("HYUNDAI", "IONIQ5") == "IONIQ 5"
    assert m("TOYOTA", "RAV 4 HYBRID") == m("TOYOTA", "RAV4 HSD") == "RAV4"
    assert m("LEXUS", "LEXUS NX450PHEV") == "NX" and m("BMW", "X5 XDRIVE 50E") == "X5"
    assert m("MERCEDES-BENZ", "GLC300E COUPE") == "GLC" and m("MERCEDES-BENZ", "E300DE") == "E"
    assert m("AUDI", "Q8 55 TFSIE") == "Q8" and m("TESLA", "MODEL Y") == "MODEL Y"
    assert m("LAND ROVER", "R. ROVER SPORT") == "RANGE ROVER SPORT"
    assert m("BYD", "ATTO 3 EVO") == m("BYD", "ATTO 3") == "ATTO 3"
    assert m("X", "", "PFH11S") == "PFH11S"                            # falls back to the type code

    # one column function for the CSV counts and the tables
    exact = {(1, 2, 2024, "GLX"): "HEV", (1, 3, 2024, "GLX"): "PHEV"}
    votes = {(1, 2, 2024): {"HEV": 3}, (1, 3, 2024): {"PHEV": 1}}

    def rec(fuel, degem=2, trim="GLX", **kw):
        return {fi.FUEL_FIELD: fuel, "tozeret_cd": 1, "degem_cd": degem,
                "shnat_yitzur": 2024, "ramat_gimur": trim, **kw}
    col = lambda r: fi.column_of(r, exact, votes)                      # noqa: E731
    assert col(rec("בנזין")) == ("HEV", "trim")                        # HEV hidden in petrol
    assert col(rec("בנזין", trim="OTHER")) == ("HEV", "majority")
    assert col(rec("בנזין", degem=9)) == ("PETROL", "unmatched")
    assert col(rec("בנזין", degem=3)) == ("PHEV", "trim")
    assert col(rec("חשמל")) == ("BEV", "") and col(rec("")) == ("OTHERS", "")
    assert col(rec('גפ"מ'))[0] == col(rec('גפמ"'))[0] == "OTHERS"      # both LPG spellings
    assert col(rec("מימן"))[0] is None

    # month_units: same records, ranked classes only, every record in the total
    recs = [rec("חשמל", tozeret_nm="טסלה סין", kinuy_mishari="MODEL Y"),
            rec("חשמל", tozeret_nm="טסלה גרמניה", kinuy_mishari="MODEL Y"),
            rec("בנזין", tozeret_nm="טויוטה יפן", kinuy_mishari="RAV4 HYBRID"),
            rec("בנזין", degem=9, tozeret_nm="סוזוקי יפן", kinuy_mishari="SWIFT")]
    seen = []
    real = fi.ds_all_records
    fi.ds_all_records = lambda res, fields, filters=None: seen.append((fields, filters)) or recs
    try:
        units, total = fi.month_units("2026-05", (exact, votes))
    finally:
        fi.ds_all_records = real
    assert total == 4
    assert units == {("BEV", "TESLA", "MODEL Y"): 2, ("HEV", "TOYOTA", "RAV4"): 1,
                     ("PETROL", "SUZUKI", "SWIFT"): 1}
    assert seen[0][1] == {fi.DATE_FIELD: "2026-5", fi.SCOPE_FIELD: "P"}    # unpadded month, P scope
    assert {"tozeret_nm", "kinuy_mishari"} <= set(seen[0][0])


def test_portugal_brand_tables():
    import fetch_portugal as fp

    def chart(series, rows):
        return {"thisyear": [str(x) for x in series],
                "result_table": [{"Marca": b, "Mensal": str(m), "Acumulado": str(a)}
                                 for b, m, a in rows]}
    charts = {
        "": chart([100, 120], [("TESLA", 20, 30), ("KIA", 100, 190)]),
        "7": chart([10, 12], [("TESLA", 8, 15), ("KIA", 4, 7)]),
        "14": chart([3, 4], [("BMW", 3, 4), ("VOLVO", 1, 3)]),
        "15": chart([1, 1], [("BMW", 1, 2)]),
        "17": chart([20, 25], [("TOYOTA", 25, 40), ("KIA", 0, 5)]),
        "18": chart([0, 0], []),
        "1": chart([50, 60], [("SEAT", 50, 90), ("KIA", 10, 20)]),
        "2": chart([5, 6], [("PEUGEOT", 6, 11)]),
    }
    real = fp.fetch_chart
    fp.fetch_chart = lambda session, cat, code: charts[code]
    try:
        coll = fp.collect_brands(None, 2026)
        assert coll["period"] == "2026-02" and coll["months"] == 2
        assert coll["ytd_total"] == 220 and coll["month_total"] == 120
        assert coll["month"][("PHEV", "BMW", "")] == 4          # 14 + 15 add up
        assert coll["ytd"][("BEV", "TESLA", "")] == 15 and coll["ytd"][("HEV", "TOYOTA", "")] == 40
        assert coll["ytd"][("PETROL", "SEAT", "")] == 90 and coll["month"][("DIESEL", "PEUGEOT", "")] == 6
        # brand tables must add up to the fuel series — a missing brand aborts
        charts["7"] = chart([10, 12], [("TESLA", 8, 15)])
        try:
            fp.collect_brands(None, 2026)
            raise AssertionError("an incomplete brand table must raise")
        except RuntimeError:
            pass
        charts["7"] = chart([10, 12], [("TESLA", 8, 15), ("KIA", 4, 7)])
        # before the year's first month is out there is nothing to rank
        charts[""] = {"thisyear": [], "result_table": []}
        assert fp.collect_brands(None, 2027) is None
        charts[""] = chart([100, 120], [])
        coll = fp.collect_brands(None, 2026)
    finally:
        fp.fetch_chart = real
    # headline = year to date; single months come from the store and accumulate
    stored = {"2026-01": ({("BEV", "TESLA", ""): 7}, 100),
              "2026-02": (coll["month"], coll["month_total"])}
    top = fp.build_top_portugal(coll, stored)
    assert top["window"] == {"from": "2026-01", "to": "2026-02", "months": 2}
    assert top["total_registrations"] == 220
    assert top["classes"]["BEV"]["units"] == 22 and top["classes"]["BEV"]["brands"][0]["brand"] == "TESLA"
    assert [m["period"] for m in top["months"]] == ["2026-02", "2026-01"]
    assert top["classes"]["BEV"]["models"] == []                  # brands only
    # the year-to-date headline has petrol from the start; January was stored without it
    assert top["classes"]["PETROL"]["brands"][0] == {"brand": "SEAT", "units": 90,
                                                     "share_of_class": 0.8182}
    assert "PETROL" in top["months"][0]["classes"] and "PETROL" not in top["months"][1]["classes"]


def _italy_list(cls: str, period_label: str, rows: list, rest: int) -> str:
    """A 'Immatricolazioni BEV|PHEV per modello' page in UNRAE's layout
    (thousands with '.', percentages with ',')."""
    total = sum(n for _, _, n in rows) + rest

    def num(n: int) -> str:
        return f"{n:,}".replace(",", ".")

    def pct(n: int) -> str:
        return f"{n / total * 100:.1f}".replace(".", ",")
    lines = [f"        IMMATRICOLAZIONI AUTOVETTURE E FUORISTRADA {cls} - {period_label}", "",
             "n.   marca           modello                       totale   quote%"]
    lines += [f"{i:>2} {b:<16}{m:<28}{num(n):>9}{pct(n):>9}" for i, (b, m, n) in enumerate(rows, 1)]
    lines += [f"    altre{'':<39}{num(rest):>9}{pct(rest):>9}",
              f"    Totale{'':<38}{num(total):>9}    100,0"]
    return "\n".join(lines) + "\n"


def test_italy_model_lists():
    import fetch_italy as fi
    jul = fi.parse_model_list(_italy_list("PHEV", "7 mesi 2026", [
        ("BYD", "SEAL U", 9700), ("BYD", "ATTO2", 14279), ("DS", "N? 4", 80),
        ("KIA", "SPORTAGE", 3049), ("ALTRE ESTERE", "ALTRI TIPI", 40)], 400))
    aug = fi.parse_model_list(_italy_list("PHEV", "8 mesi 2026", [
        ("BYD", "SEAL U", 11177), ("BYD", "ATTO 2", 14716), ("DS", "N4", 86)], 1500))
    assert (jul["cls"], jul["period"], aug["period"]) == ("PHEV", "2026-07", "2026-08")
    assert jul["rest"] == 440                    # UNRAE's own catch-all row is rest
    assert jul["models"][fi._model_key("DS", "N 4")][:2] == ("DS", "N° 4")
    month, total = fi._combine([(1, aug), (-1, jul)], "PHEV")
    assert total == aug["total"] - jul["total"]
    # renamed models are matched on letters and digits only
    assert month[("PHEV", "BYD", "ATTO 2")] == 437 and month[("PHEV", "DS", "N4")] == 6
    assert month[("PHEV", "BYD", "SEAL U")] == 1477
    # a model that left the list (reclassified) is not ranked with a negative count
    assert not any(k[2] == "SPORTAGE" for k in month)
    assert all(n > 0 for n in month.values())
    jan = fi.parse_model_list(_italy_list("BEV", "gennaio 2026", [("TESLA", "MODEL Y", 5)], 1))
    assert jan["period"] == "2026-01" and jan["total"] == 6
    try:
        fi.parse_model_list(_italy_list("BEV", "gennaio 2026", [("TESLA", "MODEL Y", 5)], 1)
                            .replace("    6", "    7"))
        raise AssertionError("rows not adding up to Totale must raise")
    except RuntimeError:
        pass


def test_ecuador_top():
    import fetch_ecuador as fe
    header = ("CATEGORÍA;CÓDIGO DE VEHÍCULO;TIPO TRANSACCIÓN;MARCA;MODELO;PAÍS;AÑO MODELO;CLASE;"
              "SUB CLASE;TIPO;AVALÚO;FECHA PROCESO (DD/MM/AAAA);TIPO SERVICIO;CILINDRAJE;"
              "TIPO COMBUSTIBLE;FECHA COMPRA (DD/MM/AAAA);CANTÓN;COLOR 1;COLOR 2;"
              "PERSONA NATURAL - JURÍDICA")

    def r(code, make, model, cls, fuel, date="05/08/2026"):
        return ";".join(["1", code, "COMPRA LOCAL", make, model, "CHINA POPULAR", "2026", cls,
                         cls, "LIVIANO", "1", date, "PAR", "0", fuel, date, "QUITO", "BLA", "",
                         "NATURAL"])
    rows = [r("1", "BYD", "YUAN PRO GS AC 5P 4X2 TA EV", "JEEP", "ELECTRICO"),
            r("2", "BYD", "YUAN PRO GS AC 5P 4X2 TA EV", "JEEP", "ELECTRICO", "06/08/2026"),
            r("2", "BYD", "YUAN PRO GS AC 5P 4X2 TA EV", "JEEP", "ELECTRICO", "20/08/2026"),
            r("3", "NISSAN", "X-TRAIL EPOWER EXCLUSIVE AC 5P 4X4 TA EV", "JEEP", "ELECTRICO"),
            r("4", "SUZUKI", "FRONX ISG GLX AC 1.5 5P 4X2 TM HYBRID", "JEEP", "GASOLINA"),
            r("5", "KIA", "SOLUTO AC 1.4 4P 4X2 TM", "AUTOMOVIL", "GASOLINA"),
            r("6", "RIDDARA", "RD6 PRO AC CD 4X2 TA EV", "CAMIONETA", "ELECTRICO"),
            r("7", "DFSK", "E5 S508 SUPREME AC 1.5 5P 4X2 TA HYBRID", "JEEP",
              "HIBRIDO_GASOLINA_BATERIAS")]
    yf = fe.YearFile.parse("\n".join([header] + rows), 2026)
    top = fe.build_top(fe.count_years({2026: yf}, [2026]), "2026-08")
    assert top["total_registrations"] == 6                  # Whole only, vehicle "2" once
    assert list(top["classes"]) == ["BEV", "PHEV", "HEV", "PETROL"]   # E5: plug-in by rule
    assert top["classes"]["PHEV"]["models"][0]["model"] == "E5 S508"
    assert top["classes"]["PETROL"]["models"][0]["model"] == "SOLUTO"
    bev, hev = top["classes"]["BEV"], top["classes"]["HEV"]
    assert bev["units"] == 2 and bev["models"][0]["model"] == "YUAN PRO"
    assert {m["model"] for m in hev["models"]} == {"X-TRAIL", "FRONX"}   # e-POWER is a hybrid
    assert not any(b["brand"] == "RIDDARA" for b in bev["brands"])       # a pickup: Vans


def test_taiwan_all_powertrains():
    # THB publishes brands without a fuel split: one ALL class, no electrified
    # class; the local maker merges into its marque; 其他 (others) counts
    # towards the total but is never ranked.
    import fetch_taiwan as ftw
    brands = {"2026-08": {"廠牌別總計": 100, "國瑞": 30, "TOYOTA": 20, "TESLA": 25,
                          "LEXUS": 15, "其他": 10},
              "2026-07": {"廠牌別總計": 50, "國瑞": 20, "TESLA": 30}}
    top = ftw.build_top(brands, {"2026-08": 100, "2026-07": 50}, "2026-08")
    assert list(top["classes"]) == ["ALL"]
    cls = top["classes"]["ALL"]
    assert cls["units"] == 150 and cls["share_of_market"] == 1.0
    assert [(b["brand"], b["units"]) for b in cls["brands"]] == [
        ("Toyota", 70), ("Tesla", 55), ("Lexus", 15)]
    assert cls["brands"][0]["share_of_class"] == round(70 / 150, 4)
    assert cls["models"] == []                                 # brand-only source
    assert top["window"] == {"from": "2026-07", "to": "2026-08", "months": 2}
    assert [m["period"] for m in top["months"]] == ["2026-08", "2026-07"]
    # a brand the code list lacks (2026-06 →): in the total, never ranked
    gap = ftw.build_top({"2026-08": {"廠牌別總計": 100, "國瑞": 60, "TESLA": 25}},
                        {"2026-08": 100}, "2026-08")
    assert gap["classes"]["ALL"]["units"] == 100
    assert [b["brand"] for b in gap["classes"]["ALL"]["brands"]] == ["Toyota", "Tesla"]
    assert ftw.unlisted({"廠牌別總計": 100, "國瑞": 60, "TESLA": 25}) == 15
    assert ftw.unlisted({"廠牌別總計": 85, "國瑞": 60, "TESLA": 25}) == 0
    # electrified files are unchanged by the extra class
    assert mt._classes({("BEV", "X", "Y"): 3}, 10, 10, 10).keys() == {"BEV"}


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} tests passed")
