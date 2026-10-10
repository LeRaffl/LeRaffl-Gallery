#!/usr/bin/env python3
"""Regression tests for scripts/fetch_paraguay.py (no network).

Run:  python scripts/test_fetch_paraguay.py

The fetcher's failure modes are silent: a regime counted twice (into a bonded
warehouse AND out of it), a tariff line in the wrong column, a believed
"7.0" quantity or a renamed column would quietly move or multiply cars. These
cases pin the scope (operation × regime × USO × NCM heading), every tariff
subheading's column, the quantity rule, the published header, period
parsing, the governance guards, the line-level upsert and the model
designation used by the top-brands/models table — with real rows from the
customs files (2025-08 and 2026-08).
"""
import csv
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_paraguay as fp  # noqa: E402

# The item-level header, unchanged 2017-01 → 2026-09 (note the trailing
# space in "POSICION ").
HEADER = ["DESPACHO CIFRADO", "OPERACION", "DESTINACION", "REGIMEN", "OFICIALIZACION",
          "CANCELACION", "AÑO", "MES", "ADUANA", "COTIZACION", "MEDIO TRANSPORTE", "CANAL",
          "ITEM", "PAIS ORIGEN", "PAIS PROCEDENCIA/DESTINO", "USO",
          "UNIDAD MEDIDA ESTADISTICA", "CANTIDAD ESTADISTICA", "KILO NETO", "KILO BRUTO",
          "FOB DOLAR", "FLETE DOLAR", "SEGURO DOLAR", "IMPONIBLE DOLAR", "IMPONIBLE GS",
          "AJUSTE A INCLUIR", "AJUSTE A DEDUCIR", "POSICION ", "RUBRO", "DESC CAPITULO",
          "DESC PARTIDA", "DESC POSICION", "MERCADERIA", "MARCA ITEM", "ACUERDO", "DERECHO",
          "ISC", "SERVICIO", "RENTA", "IVA", "OTROS", "TOTAL"]


def row(pos, uso="NUEVO", dest="IC04", op="IMPORTACION", qty="1,0", kg="1500,0",
        brand="TOYOTA", text="UN AUTOMOVIL", year="2026", mes="AGOSTO"):
    vals = {"OPERACION": op, "DESTINACION": dest, "AÑO": year, "MES": mes, "USO": uso,
            "CANTIDAD ESTADISTICA": qty, "KILO NETO": kg, "POSICION ": pos,
            "MERCADERIA": text, "MARCA ITEM": brand, "UNIDAD MEDIDA ESTADISTICA": "UNIDAD"}
    return [vals.get(h, "x") for h in HEADER]


def text_of(rows, header=HEADER):
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_ALL)
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


def agg_of(rows, expect="2026-08"):
    agg = fp.Aggregator()
    fp.add_text(text_of(rows), agg, expect=expect)
    return agg


def test_every_subheading_column():
    cases = {
        "8703.21.00.000A": "PETROL", "8703.22.10.000B": "PETROL", "8703.23.90.000C": "PETROL",
        "8703.24.90.000D": "PETROL", "8703.31.10.000E": "DIESEL", "8703.32.90.000F": "DIESEL",
        "8703.33.90.000M": "DIESEL", "8703.40.00.000G": "HEV", "8703.50.00.000H": "HEV",
        "8703.60.00.000J": "PHEV", "8703.70.00.000K": "PHEV", "8703.80.00.000L": "BEV",
        "8703.90.00.000N": "OTHERS",
    }
    agg = agg_of([row(p) for p in cases])
    c = agg.counts["2026-08"]["Whole"]
    for col in fp.FUELS:
        assert c[col] == sum(1 for v in cases.values() if v == col), (col, c)
    assert c["TOTAL"] == len(cases)
    # Every mapped subheading is exercised here.
    assert {fp.subheading(p) for p in cases} == set(fp.POSITION_FUEL)


def test_scope_not_cars_and_exports():
    agg = agg_of([
        row("8703.10.00.000X"),                       # golf cart: no variant
        row("8704.21.90.000X"),                       # pickup (N1): not 87.03
        row("8711.20.00.000X"),                       # motorcycle
        row("8703.80.00.000L", op="EXPORTACION"),     # re-export
        row("8703.80.00.000L"),
    ])
    c = agg.counts["2026-08"]["Whole"]
    assert c["TOTAL"] == 1 and c["BEV"] == 1, c


def test_new_and_used():
    agg = agg_of([row("8703.22.10.000B", uso="NUEVO"),
                  row("8703.22.10.000B", uso="USADO"),
                  row("8703.22.10.000B", uso="USADO"),
                  row("8703.22.10.000B", uso="REACONDICIONADO")])
    w = agg.counts["2026-08"]
    assert w["Whole"]["TOTAL"] == 1 and w["Used"]["TOTAL"] == 2
    assert agg.unknown_uso[("2026-08", "REACONDICIONADO")] == 1


def test_regimes_counted_once():
    rows = [row("8703.40.00.000G", dest=d) for d in
            ("IC04", "IC09", "IC20", "IC07", "ID04", "ZF2I",           # counted
             "IDA3", "ZF01", "IT04", "IR01", "IFC1", "IML2",           # not counted
             "XX99")]                                                  # unknown
    agg = agg_of(rows)
    assert agg.counts["2026-08"]["Whole"]["TOTAL"] == 6
    assert sum(agg.excluded.values()) == 6
    assert agg.unknown_regime[("2026-08", "XX99")] == 1
    # IDA (into a bonded warehouse) must not be caught by the diplomatic "ID".
    assert fp.regime_counted("IDA3") is False and fp.regime_counted("ID04") is True
    assert fp.regime_counted("ZF01") is False and fp.regime_counted("ZF2I") is True


def test_quantity_rule():
    # Real 2026-08 rows: "7,0" on one used Toyota Vitz (no weight split) and
    # on one new Corolla Cross of 1,435 kg — both are ONE car.
    assert fp.units_of(7.0, 1435.0) == 1
    assert fp.units_of(7.0, 0.0) == 1
    assert fp.units_of(1.0, 1106.0) == 1
    # A genuine multi-unit item carries the weight of all its cars.
    assert fp.units_of(4.0, 4 * 1300.0) == 4
    assert fp.units_of(2.5, 3000.0) == 1          # not an integer
    agg = agg_of([row("8703.23.10.000C", uso="USADO", qty="7,0", kg="1700,0"),
                  row("8703.80.00.000L", qty="3,0", kg="5400,0")])
    w = agg.counts["2026-08"]
    assert w["Used"]["TOTAL"] == 1 and w["Whole"]["BEV"] == 3
    assert agg.qty_fixed["2026-08"] == 1


def test_numbers():
    assert fp.num("1435,0") == 1435.0
    assert fp.num(",0") == 0.0
    assert fp.num("2157429,0") == 2157429.0
    assert fp.num("") == 0.0
    assert fp.subheading("8703.80.00.000L") == "8703.80"
    assert fp.subheading("87038000") == "8703.80"


def test_period_parsing_and_wrong_month_aborts():
    assert fp.period_of_entry("2026", "SEPTIEMBRE") == "2026-09"
    assert fp.period_of_entry("2017", "SETIEMBRE") == "2017-09"
    assert fp.period_of_entry("2026", "AGOSTO") == "2026-08"
    assert fp.period_of_entry("x", "AGOSTO") is None
    try:
        agg_of([row("8703.80.00.000L", mes="JULIO")], expect="2026-08")
    except SystemExit:
        pass
    else:
        raise AssertionError("a row of another month must abort")


def test_schema_drift_aborts():
    bad = [h for h in HEADER if h != "USO"]
    try:
        fp.add_text(text_of([], header=bad), fp.Aggregator())
    except SystemExit as e:
        assert "USO" in str(e)
    else:
        raise AssertionError("missing column must abort")


def test_dir_listing(tmp=None):
    with tempfile.TemporaryDirectory() as d:
        for n in ("2026_AGOSTO_Nivel_Item.csv", "2026_AGOSTO.csv",
                  "2025_SEPTIEMBRE_Nivel_Item.csv.gz", "notes.txt"):
            (Path(d) / n).write_text("x")
        got = fp.list_dir_files(Path(d))
        assert sorted(got) == ["2025-09", "2026-08"], got


def test_month_end():
    assert fp.month_end("2026-08").isoformat() == "2026-09-01T00:00:00+00:00"
    assert fp.month_end("2026-12").isoformat() == "2027-01-01T00:00:00+00:00"


def test_completeness_guard():
    have = {f"2025-{m:02d}": {"TOTAL": "3000"} for m in range(1, 13)}
    assert fp.median_fraction("2026-01", 600, have) < fp.MIN_MONTH_FRACTION
    assert fp.median_fraction("2026-01", 2900, have) > fp.WARN_MONTH_FRACTION
    assert fp.median_fraction("2025-03", 100, have) is None    # < 6 months before


def test_sums():
    agg = agg_of([row("8703.80.00.000L"), row("8703.21.00.000A", uso="USADO")])
    assert fp.check_sums(agg, ["2026-08"]) == []


def test_upsert_line_level():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "Paraguay.csv"
        p.write_text(",".join(fp.CSV_COLUMNS) + "\n"
                     "2026-07,monthly,Whole,Someone else,1.0,0.0,0.0,1.0,0.0,0.0,2.0,\n"
                     "2026-08,monthly,Whole,Someone else,1e3,0.0,0.0,1.0,0.0,0.0,2.0,\n",
                     encoding="utf-8")
        c = fp.empty_counts()
        c.update(BEV=5, TOTAL=5)
        st = fp.upsert_lines(p, {("2026-07", "Whole"): fp.render_line("2026-07", "Whole", c),
                                 ("2026-09", "Whole"): fp.render_line("2026-09", "Whole", c)},
                             force=False)
        assert st == {"added": 1, "updated": 0, "unchanged": 0, "skipped": 1}, st
        lines = p.read_text(encoding="utf-8").splitlines()
        assert lines[2].startswith("2026-08,monthly,Whole,Someone else,1e3"), lines
        assert lines[3].startswith("2026-09,monthly,Whole,DNIT"), lines


def test_model_designation():
    cases = [
        ("BYD", "01) UN STATION WAGON NUEVO MARCA. BYD MODELO: YUAN PLUS INTELIGENT EV "
                "AO 2026 ELECTRICO", "YUAN PLUS INTELIGENT"),
        ("VOLVO", "(1) UNA UNIDAD VEHICULO, MARCA VOLVO, MODELO EX30, ANIO DE FABRICACION "
                  "2026, MODELO ANIO 2027, MOTOR ELECTRICO", "EX30"),
        ("MINI", "LOS DEMAS VEHICULOS, PROPULSADOS UNICAMENTE CON MOTOR ELECTRICO: 01 UN "
                 "AUTOMOVIL MARCA MINI MODELO ACEMAN E CHN A¿O DE FABRICACION 2026",
         "ACEMAN E CHN"),
        ("GREATWALL", "TANK 400 PHEV 4WD", "TANK 400 PHEV"),
        ("CHERY", "UN VEHICULO MARCA CHERY MODELO T7 PRO 1.5 PHEV", "T7 PRO PHEV"),
        ("CHEVROLET", "1 UNID. AUTOMOVIL MARCA CHEVROLET, MOD. ONIX ACTIV HB, 5K48HVR7V",
         "ONIX ACTIV HB"),
        ("TOYOTA", "UNA UNIDAD DE STATION WAGON, MARCA TOYOTA, MODELO COROLLA CROSS, ANIO 2026.-",
         "COROLLA CROSS"),
        ("TOYOTA", "LOS DEMAS VEHICULOS AUTOMOVILES CONCEBIDOS PRINCIPALMENTE PARA EL "
                   "TRANSPORTE DE PERSONAS SIN DETALLE", ""),
    ]
    for brand, text, want in cases:
        got = fp.model_of(brand, text)
        assert got == want, (brand, text, got, want)
    assert fp.display_brand("GREATWALL") == "GREAT WALL"
    assert fp.display_brand("LYNK  CO") == "LYNK & CO"
    assert fp.display_brand("MERCEDES BENZ") == "MERCEDES-BENZ"


def test_reclass_rules():
    cases = [
        # (declared column, description, expected column or None = unchanged)
        ("BEV", "UN VEHICULO MARCA NISSAN MODELO X-TRAIL E-POWER EXCLUSIVE AÑO 2026", "HEV"),
        ("BEV", "NISSAN X-TRAIL EPOWER ADVANCE", "HEV"),
        ("BEV", "UN VEHICULO MARCA LEAPMOTOR MODELO C10 REEV AÑO 2026", "PHEV"),
        ("BEV", "LYNK & CO MODELO MR6521DPHEV100", "PHEV"),
        ("BEV", "BMW MODELO BMW7000AHEV", "HEV"),
        ("HEV", "GREAT WALL NEW H6 PHEV 4X2", "PHEV"),
        ("HEV", "BMW MODELO X5 PHEV XDRIVE45E", "PHEV"),
        ("HEV", "BYD SONG PLUS DM-I", "PHEV"),
        # must NOT move
        ("BEV", "1 UNID. AUTOMOVIL MARCA CHEVROLET, MOD. SPARK EUV, ELECTRICO", None),
        ("BEV", "CHEVROLET CAPTIVA EV PREMIER", None),
        ("BEV", "LOS DEMAS VEHICULOS, PROPULSADOS UNICAMENTE CON MOTOR ELECTRICO: BYD YUAN PLUS EV", None),
        ("BEV", "PORSCHE TAYCAN TURBO S", None),
        ("HEV", "GREAT WALL NEW H6 HEV", None),
        ("HEV", "TOYOTA COROLLA CROSS HYBRID", None),
        ("PHEV", "GREAT WALL TANK 400 PHEV 4WD", None),
        ("PETROL", "TOYOTA COROLLA CROSS HEV", None),          # ICE lines are never moved
        ("PETROL", "BYD SONG PLUS DM-I", None),
    ]
    for fuel, text, want in cases:
        got = fp.reclass(fuel, text)
        assert (got[0] if got else None) == want, (fuel, text, got, want)
    # every rule is exercised by a case above
    hit = set()
    for fuel, text, _ in cases:
        for i, (cols, rx, to, _) in enumerate(fp._RECLASS):
            if fuel in cols and to != fuel and rx.search(fp.norm(text)):
                hit.add(i)
                break
    assert hit == set(range(len(fp._RECLASS))), hit


def test_reclass_and_watch_in_aggregate():
    agg = agg_of([row("8703.80.00.000L", brand="NISSAN", text="MODELO X-TRAIL E-POWER ADVANCE"),
                  row("8703.22.10.000B", brand="TOYOTA", text="MODELO COROLLA CROSS HEV")])
    c = agg.counts["2026-08"]["Whole"]
    assert c["BEV"] == 0 and c["HEV"] == 1 and c["PETROL"] == 1, c
    assert sum(agg.reclassed.values()) == 1 and sum(agg.ice_watch.values()) == 1
    assert ("2026-08", "HEV", "NISSAN", "X-TRAIL E-POWER ADVANCE") in agg.units


def test_used_is_data_only():
    # Used is fetched and committed but never rendered (owner decision 2026-10).
    assert fp.render_list({"Whole", "Used"}) == ["Whole"]
    assert fp.render_list({"Used"}) == []
    assert "Used" in fp.VARIANT_CSV


def test_vin_once_per_month():
    vin = "LGXCEACC8S2156194"
    agg = agg_of([row("8703.80.00.000L", text=f"BYD SEAL CHASIS {vin}"),
                  row("8703.80.00.000L", text=f"BYD SEAL CHASIS {vin}"),
                  row("8703.80.00.000L", text="BYD SEAL CHASIS LGXCEACC8S2156195"),
                  row("8703.80.00.000L", text="BYD SEAL")])
    assert agg.counts["2026-08"]["Whole"]["BEV"] == 3
    assert agg.dup_vin["2026-08"] == 1
    assert fp.vin_of("MODELO X5 XDRIVE50E 2026") is None          # no 17-char token
    assert fp.vin_of("CHASIS WAUZZZ4MXTD003416") == "WAUZZZ4MXTD003416"
    assert fp.vin_of("ABCDEFGHJKLMNPRST") is None                 # letters only


def test_top_units_whole_only():
    agg = agg_of([row("8703.80.00.000L", brand="VOLVO", text="MARCA VOLVO, MODELO EX30, ANIO 2026"),
                  row("8703.80.00.000L", uso="USADO", brand="TESLA", text="MODELO 3"),
                  row("8703.22.10.000B", brand="KIA", text="MODELO PICANTO")])
    keys = {(cls, b, m) for (p, cls, b, m) in agg.units}
    assert ("BEV", "VOLVO", "EX30") in keys
    assert not any(b == "TESLA" for _, b, _ in keys)            # Used is not in the top list
    assert ("PETROL", "KIA", "PICANTO") in keys                  # petrol ranked, with its model
    store = fp.store_months(agg, ["2026-08"])
    assert store["2026-08"][1] == 2                              # Whole total


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
