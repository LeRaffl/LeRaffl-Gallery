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
                          ("04", "Volvo EX30"): 50, ("39", "Volvo XC60"): 80},
              "2026-08": {("04", "Tesla Model Y"): 60, ("04", "Mercedes-Benz EQA"): 40}}

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
    assert ff.fuel_class("Bensiini/Sähkö (ei ladattava)") == "OTHER"   # 121d: in Petrol
    assert ff.fuel_class("Yhteensä") is None
    assert ff.split_series("Mercedes-Benz EQA", ["MERCEDES-BENZ", "MERCEDES"]) == ("MERCEDES-BENZ", "EQA")
    brands, models = ff.collect_top(_FakeTraficom(), "2026-08")
    assert sorted(brands) == ["2026-07", "2026-08"]
    jul, jul_total = brands["2026-07"]
    assert jul_total == 730                                  # every fuel, never the Yhteensä code
    assert jul[("BEV", "VOLVO", "")] == 50 and jul[("OTHER", "TOYOTA", "")] == 500
    assert models["2026-07"][0][("BEV", "TESLA", "MODEL Y")] == 70
    top = mt.build_top_monthly("Finland", "S", "2026-08", brands, "u")
    mt.splice_models(top, mt.build_top_monthly("Finland", "S", "2026-08", models, "u"))
    bev = top["classes"]["BEV"]
    assert bev["units"] == 250 and bev["brands"][0]["brand"] == "TESLA"
    assert bev["models"][0] == {"brand": "TESLA", "model": "MODEL Y", "units": 130,
                                "share_of_class": 0.52}
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


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} tests passed")
