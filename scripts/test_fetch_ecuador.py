#!/usr/bin/env python3
"""Regression tests for scripts/fetch_ecuador.py (no network).

Run:  python scripts/test_fetch_ecuador.py

The fetcher's failure modes are silent: a vehicle counted once per
processing instead of once, a January inflated by vehicles already counted in
December, an e-POWER counted as BEV, a hybrid kept in PETROL because the
invoice said GASOLINA, a date format the parser does not know (the files have
used six), or a renamed column would quietly move or multiply cars. These
cases pin every header layout 2017-2026 and both encodings, every date
spelling, the one-count-per-vehicle and lookback rules, each description
rule and fuel code (with look-alikes that must NOT match), the class →
variant scope, month completeness, the AEADE bulletin parser and cross-check
tolerances, the line-level upsert and the model display names — with real
rows from the SRI files.
"""
import csv
import datetime as dt
import gzip
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_ecuador as fe  # noqa: E402

# Real headers, as published (encodings: cp1252 for 2017-2025, UTF-8 + BOM for 2026).
H2017 = ("Código Vehículo 1;Sub Categoria 1;Marca;Modelo;País;Año Modelo;Tipo;Clase;Sub Clase;"
         "Cilindraje;Tipo Combustible;Tipo Servicio;Codigo Color 1;Codigo Color 2;Forma de "
         "Adquisición;Mes Adquisición;Codigo Canton;Descripcion Cantón;Mes  registro venta;Valor Avaluo")
H2018 = ("CODIGO SUB CATEGORIA;CODIGO VEHICULO;TIPO TRANSACCIÓN;MARCA;MODELO;PAIS;AÑO MODELO;CLASE;"
         "SUB CLASE;TIPO;AVALÚO;FECHA PROCESO (MM/DD/AA);TIPO SERVICIO;CILINDRAJE;TIPO COMBUSTIBLE;"
         "FECHA COMPRA (MM/DD/AA);CANTON;COLOR 1;COLOR 2")
H2021 = ("CATEGORÍA;CÓDIGO DE VEHÍCULO;TIPO TRANSACCIÓN;MARCA;MODELO;PAIS;AÑO MODELO;CLASE;SUB CLASE;"
         "TIPO;AVALÚO;FECHA PROCESO (DD/MM/AA);TIPO SERVICIO;CILINDRAJE;TIPO COMBUSTIBLE;FECHA COMPRA "
         "(DD/MM/AA);CANTON;COLOR 1;COLOR 2;PERSONA NATURAL - SOCIEDAD;")
H2025 = ("CATEGORÍA;CÓDIGO DE VEHÍCULO;TIPO TRANSACCIÓN;MARCA;MODELO;PAIS;AÑO MODELO;CLASE;SUB CLASE;"
         "TIPO;AVALUO;FECHA PROCESO (DD/MM/AAAA);TIPO SERVICIO;CILINDRAJE;TIPO COMBUSTIBLE;FECHA COMPRA "
         "(DD/MM/AAAA);CANTÓN;COLOR 1;COLOR 2;PERSONA NATURAL - JURIDICA")
H2026 = ("CATEGORÍA;CÓDIGO DE VEHÍCULO;TIPO TRANSACCIÓN;MARCA;MODELO;PAÍS;AÑO MODELO;CLASE;SUB CLASE;"
         "TIPO;AVALÚO;FECHA PROCESO (DD/MM/AAAA);TIPO SERVICIO;CILINDRAJE;TIPO COMBUSTIBLE;FECHA COMPRA "
         "(DD/MM/AAAA);CANTÓN;COLOR 1;COLOR 2;PERSONA NATURAL - JURÍDICA")


def row(code, date, model="CX-5 CORE AC 2.0 5P 4X2 TA", cls="JEEP", fuel="GASOLINA",
        make="MAZDA"):
    """A 2025/2026-layout row."""
    return ";".join(["999798", code, "COMPRA LOCAL", make, model, "JAPÓN", "2026", cls, cls,
                     "LIVIANO", "29999,00", date, "PAR", "1998", fuel, date, "QUITO", "BLA", "",
                     "NATURAL"])


def year_text(rows, header=H2026):
    return "\n".join([header] + rows) + "\n"


def parse(rows, year=2026, header=H2026):
    return fe.YearFile.parse(year_text(rows, header), year)


# ── dates and headers ──────────────────────────────────────────────────────

def test_every_date_spelling():
    cases = {
        "28/12/2018 21:50": dt.date(2018, 12, 28),        # 2018 (header says MM/DD/AA)
        "27/12/2019 22:46:06": dt.date(2019, 12, 27),     # 2019
        "27-Nov-20": dt.date(2020, 11, 27),               # 2020, English abbreviation
        "29-Ago-20": dt.date(2020, 8, 29),                # 2020, Spanish
        "30-Sept-20": dt.date(2020, 9, 30),               # 2020, four letters
        "2-dic-21": dt.date(2021, 12, 2),                 # 2021-2023, lower case
        "9/12/2024": dt.date(2024, 12, 9),                # 2024
        "17/9/2025": dt.date(2025, 9, 17),                # 2025, unpadded
        "24/06/2026": dt.date(2026, 6, 24),               # 2026
    }
    for s, want in cases.items():
        assert fe.parse_date(s) == want, (s, fe.parse_date(s))
    for bad in ("", "2026-06-24", "31/02/2026", "12/Foo/26", "x"):
        assert fe.parse_date(bad) is None, bad


def test_every_header_layout_and_encoding():
    r18 = ("284463;6687138;COMPRA LOCAL;GREAT WALL;HAVAL M4 AC 1.5 5P 4X2 TM;ECUADOR;2019;JEEP;JEEP;"
           "LIVIANO;17990;28/12/2018 21:50;PAR;1497;GASOLINA;28/12/2018 0:00;21701;PLO;")
    yf = fe.YearFile.parse(fe.decode(year_text([r18], H2018).encode("cp1252")), 2018)
    assert yf.first["6687138"][:2] == (dt.date(2018, 12, 28), "GREAT WALL")
    r21 = ("487526;7927017;COMPRA LOCAL;MACK;GR64BX AC 12.8 2P 6X4 TM DIESEL;ESTADOS UNIDOS;2022;"
           "VOLQUETA;VOLQUETA;PESADO;164000;16-dic-21;PAR;12800;DIESEL;15-dic-21;10927;BLA;BLA;SOCIEDAD;")
    yf = fe.YearFile.parse(fe.decode(year_text([r21], H2021).encode("cp1252")), 2021)
    assert yf.first["7927017"][3] == "VOLQUETA"
    r25 = ("104856;10033955;COMPRA LOCAL;SCANIA;K410 CB AC 12.7 2P 4X2 TM DIESEL;BRASIL;2026;OMNIBUS;"
           "BUS;PESADO;240000;20/11/2025;PAR;12742;DIESEL;29/10/2025;21701;NEG;;NATURAL")
    yf = fe.YearFile.parse(fe.decode(year_text([r25], H2025).encode("cp1252")), 2025)
    assert yf.first["10033955"][0] == dt.date(2025, 11, 20)
    raw = ("﻿" + year_text([row("10867259", "24/06/2026")])).encode("utf-8")
    yf = fe.YearFile.parse(fe.decode(raw), 2026)
    assert "10867259" in yf.first
    assert fe.decode(gzip.compress(raw)) == fe.decode(raw)


def test_2017_is_lookback_only():
    r17 = ("6225675;256790;CHEVROLET;D-MAX CRDI 3.0 CD 4X2 TM DIESEL;ECUADOR;2018;LIVIANO;CAMIONETA;"
           "DOBLE CABINA;2999;DIESEL;PAR;BLA;;COMPRA LOCAL;12;12401;SANTA ELENA;12;29990")
    yf = fe.YearFile.parse(year_text([r17], H2017), 2017, need_date=False)
    assert yf.codes == {"6225675"} and not yf.first and not yf.dated
    try:
        fe.YearFile.parse(year_text([r17], H2017), 2017, need_date=True)
    except SystemExit as e:
        assert "FECHA PROCESO" in str(e)
    else:
        raise AssertionError("a file without processing date must not be written")


def test_schema_drift_aborts():
    for drop in ("MARCA", "CLASE", "TIPO COMBUSTIBLE", "MODELO", "CÓDIGO DE VEHÍCULO"):
        header = ";".join(h for h in H2026.split(";") if h != drop)
        try:
            fe.resolve_columns(header.split(";"), need_date=True)
        except SystemExit:
            continue
        raise AssertionError(f"missing {drop} must abort")


def test_bad_dates_counted():
    yf = parse([row("1", "24/06/2026"), row("2", "24-13-2026"), row("3", "01/01/2025")])
    assert set(yf.first) == {"1"} and yf.bad_dates == 2
    assert abs(yf.bad_date_share() - 2 / 3) < 1e-9


# ── one count per vehicle, lookback ────────────────────────────────────────

def test_vehicle_counted_once_at_first_processing():
    # Real pattern: 10000328 processed 28/01, then five times 30-31/03 (2026 file).
    rows = [row("10000328", d) for d in ("31/03/2026", "28/01/2026", "30/03/2026", "31/03/2026")]
    yf = parse(rows)
    agg = fe.count_years({2026: yf}, [2026])
    assert agg.counts["2026-01"]["Whole"]["TOTAL"] == 1
    assert "2026-03" not in agg.allseg


def test_lookback_two_years():
    y24 = parse([row("A", "15/11/2024")], 2024)
    y25 = parse([row("B", "20/12/2025")], 2025)
    y26 = parse([row("A", "10/01/2026"), row("B", "05/01/2026"), row("C", "07/01/2026")])
    agg = fe.count_years({2024: y24, 2025: y25, 2026: y26}, [2026])
    assert agg.counts["2026-01"]["Whole"]["TOTAL"] == 1          # only C
    assert agg.lookback_hits["2026-01"] == 2
    # Three years back is outside the lookback: counted again.
    y23 = parse([row("D", "01/06/2023")], 2023)
    y26b = parse([row("D", "02/02/2026")])
    agg = fe.count_years({2023: y23, 2026: y26b}, [2026])
    assert agg.counts["2026-02"]["Whole"]["TOTAL"] == 1


def test_backfill_and_monthly_agree():
    files = {2023: parse([row("X", "03/03/2023")], 2023),
             2024: parse([row("X", "05/01/2024"), row("Y", "28/12/2024")], 2024),
             2025: parse([row("Y", "02/01/2025"), row("Z", "02/01/2025")], 2025),
             2026: parse([row("Z", "09/01/2026"), row("W", "09/01/2026")])}
    full = fe.count_years(files, [2024, 2025, 2026])
    monthly = fe.count_years(files, [2025, 2026])
    for p in ("2025-01", "2026-01"):
        assert full.counts[p] == monthly.counts[p], p
    assert full.counts["2025-01"]["Whole"]["TOTAL"] == 1         # Z (Y counted 2024)
    assert full.counts["2026-01"]["Whole"]["TOTAL"] == 1         # W


# ── fuel and scope ─────────────────────────────────────────────────────────

def test_description_rules():
    cases = [
        # (model, invoice fuel code, column)
        ("X-TRAIL EPOWER EXCLUSIVE AC 5P 4X4 TA EV", "ELECTRICO", "HEV"),
        ("KICKS E-POWER AC 5P 4X2 TA EV", "ELECTRICO", "HEV"),
        ("COROLLA CROSS MID AC 1.8 5P 4X2 TA HYBRID", "GASOLINA", "HEV"),
        ("FRONX ISG GLX AC 1.5 5P 4X2 TM HYBRID", "GASOLINA", "HEV"),
        ("SHARK DMO GS AC 1.5 CD 4X4 TA HYBRID", "ELECTRICO", "HEV"),
        ("TIGGO 7 DISTINGUISHED PHEV AC 1.5 5P 4X2 TA HYBRID", "HIBRIDO_GASOLINA_BATERIAS", "HEV"),
        ("YUAN PRO GS AC 5P 4X2 TA EV", "GASOLINA", "BEV"),
        ("E30X HGS AC 5P 4X2 TA EV", "HIBRIDO_GASOLINA_BATERIAS", "BEV"),
        ("HFC1073EV2 N55 AC 2P 4X2 TA EV CN", "ELECTRICO", "BEV"),
        ("HUNTER AC 1.9 CD 4X4 TM DIESEL", "ELECTRICO", "DIESEL"),
        ("FC9JL7Z-BB9HFAA 5.1 4X2 TM DIESEL CN", "DIESEL", "DIESEL"),
        # look-alikes that must NOT trigger a description rule
        ("RANGE ROVER EVOQUE AC 2.0 5P 4X4 TA", "GASOLINA", "PETROL"),
        ("EV18 AC 2P 4X2 TA", "GASOLINA", "PETROL"),                 # EV not at the end
        ("CHEVROLET SPARK AC 1.2 5P 4X2 TM", "ELECTRICO", "BEV"),    # code decides
        ("ESCAPE PLATINUM HEV AC 2.5 5P 4X4 TA", "HIBRIDO_GASOLINA_BATERIAS", "HEV"),
        ("HYBRID LINE AC 2.0 5P 4X2 TA", "GASOLINA", "PETROL"),      # HYBRID not at the end
        ("D-MAX DIESEL PLUS AC 2.0 CD", "GASOLINA", "PETROL"),
        ("POWERTRAIN AC 2.0 5P", "DIESEL", "DIESEL"),                 # not E-POWER
    ]
    for model, code, want in cases:
        got, _ = fe.fuel_column(model, code)
        assert got == want, (model, code, got)
    # every rule has a case above
    for rx, col, _ in fe.DESCRIPTION_RULES:
        assert any(__import__("re").search(rx, fe.norm(m)) for m, _, _ in cases), rx


def test_every_fuel_code():
    want = {"GASOLINA": "PETROL", "DIESEL": "DIESEL", "ELECTRICO": "BEV",
            "HIBRIDO_GASOLINA_BATERIAS": "HEV", "HIBRIDO_DIESEL_BATERIAS": "HEV",
            "DUAL_GAS_GASOLINA": "OTHERS", "GAS_NATURAL_COMPRIMIDO": "OTHERS",
            "GAS_LICUADO_PETROLEO": "OTHERS", "ALCOHOL": "OTHERS", "OTROS": "OTHERS",
            "SOLAR": "OTHERS", "NO_UTILIZA": "OTHERS"}
    assert set(want) == set(fe.FUEL_CODE)
    for code, col in want.items():
        assert fe.fuel_column("SOMETHING AC 1.5 5P 4X2 TM", code) == (col, None), code
    assert fe.fuel_column("SOMETHING AC 1.5 5P 4X2 TM", "HIDROGENO") == (None, None)


def test_class_scope():
    rows = [row("1", "05/08/2026", cls="AUTOMOVIL"), row("2", "05/08/2026", cls="JEEP"),
            row("3", "05/08/2026", cls="CAMIONETA", fuel="DIESEL"),
            row("4", "05/08/2026", cls="CAMION", fuel="DIESEL"),
            row("5", "05/08/2026", cls="OMNIBUS", fuel="DIESEL"),
            row("6", "05/08/2026", cls="TRAILER", fuel="DIESEL"),
            row("7", "05/08/2026", cls="MOTOCICLETA"),
            row("8", "05/08/2026", cls="TRICIMOTO")]
    agg = fe.count_years({2026: parse(rows)}, [2026])
    c = agg.counts["2026-08"]
    assert c["Whole"]["TOTAL"] == 2 and c["Vans"]["TOTAL"] == 1 and c["Vans"]["DIESEL"] == 1
    assert agg.allseg["2026-08"]["TOTAL"] == 7                    # AEADE scope: no motorcycles
    assert agg.unknown_class[("2026-08", "TRICIMOTO")] == 1
    assert agg.other_class[("2026-08", "TRAILER")] == 1
    uc, uf = fe.unknown_shares(agg, "2026-08")
    assert abs(uc - 1 / 7) < 1e-9 and uf == 0


def test_unknown_fuel_counted_as_others_and_listed():
    agg = fe.count_years({2026: parse([row("1", "05/08/2026", fuel="HIDROGENO")])}, [2026])
    assert agg.counts["2026-08"]["Whole"]["OTHERS"] == 1
    assert agg.unknown_fuel[("2026-08", "HIDROGENO")] == 1
    assert fe.unknown_shares(agg, "2026-08")[1] == 1.0


def test_reclassed_listed_for_review():
    rows = [row("1", "05/08/2026", model="X-TRAIL EPOWER ADVANCE AC 5P 4X4 TA EV",
                fuel="ELECTRICO", make="NISSAN"),
            row("2", "05/08/2026", model="YUAN PRO GS AC 5P 4X2 TA EV", fuel="ELECTRICO",
                make="BYD")]
    agg = fe.count_years({2026: parse(rows)}, [2026])
    assert agg.counts["2026-08"]["Whole"]["HEV"] == 1 and agg.counts["2026-08"]["Whole"]["BEV"] == 1
    assert [k[2:4] for k in agg.reclassed] == [("ELECTRICO", "HEV")]    # the BYD agrees, not listed
    assert ("2026-08", "BEV", "BYD", "YUAN PRO") in agg.units


def test_sums():
    agg = fe.count_years({2026: parse([row(str(i), "05/08/2026") for i in range(5)])}, [2026])
    assert fe.check_sums(agg, ["2026-08"]) == []
    agg.counts["2026-08"]["Whole"]["BEV"] += 1
    assert fe.check_sums(agg, ["2026-08"])


# ── months ─────────────────────────────────────────────────────────────────

def test_complete_months_and_expected_target():
    agg = fe.count_years({2026: parse([row("1", "31/07/2026"), row("2", "01/08/2026"),
                                        row("3", "02/09/2026")])}, [2026])
    stamps = {2026: dt.datetime(2026, 9, 4, 22, 33)}            # the real Aug regeneration
    assert fe.complete_months(agg, stamps, offline=False) == ["2026-07", "2026-08"]
    assert fe.complete_months(agg, stamps, offline=True) == ["2026-07", "2026-08", "2026-09"]
    assert fe.expected_target(2026, stamps[2026]) == "2026-08"
    assert fe.expected_target(2025, dt.datetime(2026, 1, 13)) == "2025-12"
    assert fe.expected_target(2027, dt.datetime(2027, 1, 20)) == "2026-12"
    assert fe.expected_target(2026, None) is None
    assert fe.month_after("2025-12") == dt.datetime(2026, 1, 1)


def test_completeness_guard():
    have = {f"2025-{m:02d}": {"TOTAL": "8000"} for m in range(1, 13)}
    assert fe.median_fraction("2026-01", 2000, have) == 0.25
    assert fe.median_fraction("2026-01", 2000, {}) is None


# ── AEADE bulletin ─────────────────────────────────────────────────────────

AUG_2026 = """LOS SUV LIDERAN LAS PREFERENCIAS DEL COMPRADOR
Segmento Ago 25 Ago 26 Ene-Ago 25 Ene-Ago 26 Var Ene-Ago 26/25 Var Ago 26/25
SUV 5.381 8.262 38.366 55.479 44.6% 53.5%
CAMIONETA 1.790 2.341 13.975 18.706 33.9% 30.8%
AUTOMOVIL 1.609 2.471 12.786 17.513 37% 53.6%
Total 8.780 13.074 65.127 91.698 40.8% 48.9%
Energía Ago 25 Ago 26 Ene-Ago 25 Ene-Ago 26
GASOLINA 5.689 6.407 41.620 50.769
DIESEL 2.727 3.532 22.088 28.570
HIBRIDO 1.512 3.308 11.195 20.538
ELECTRICO BEV 336 2.034 2.213 8.401
Total 10.264 15.281 77.116 108.278
ELECTRICO BEV 7,8%
HIBRIDO 19,0%
"""
JAN_2026 = """Energía Ene 25 Ene 26
GASOLINA 4.487 5.892
DIESEL 2.371 2.930
HIBRIDO 1.237 1.908
ELECTRICO BEV 181 612
Total 8.276 11.342
ELECTRICO BEV 5,4%
"""
FEB_2026 = """Energía Feb 25 Feb 26 Ene-Feb 25 Ene-Feb 26
GASOLINA 4,511 5,481 8,998 11,373
ELECTRICO BEV 281 661 462 1,273
Total 8,342 10,890 16,618 22,232
ELECTRICO BEV 5.7%
"""
MAY_2025_GARBLED = """Energía May 24 May 25 Ene-May 24 Ene-May 25
DIESEL 2.373 3.338 12.979 13.371
ELECTRICO BEV 113 267 492 1.192
GASOLINA 5.034 5.284 29.434 2244..335621
HIBRIDO 993 1.450 5.754 6.399
Total 8.513 10.339 48.659 4455..332134
"""


def test_bulletin_tables():
    t = fe.parse_bulletin(AUG_2026)
    assert t["2026-08"] == {"PETROL": 6407, "DIESEL": 3532, "HEV": 3308, "BEV": 2034,
                            "TOTAL": 15281, "WHOLE": 10733}
    assert t["2025-08"]["WHOLE"] == 1609 + 5381
    assert t["ytd:2026-08"]["TOTAL"] == 108278
    t = fe.parse_bulletin(JAN_2026)
    assert t == {"2025-01": {"PETROL": 4487, "DIESEL": 2371, "HEV": 1237, "BEV": 181, "TOTAL": 8276},
                 "2026-01": {"PETROL": 5892, "DIESEL": 2930, "HEV": 1908, "BEV": 612, "TOTAL": 11342}}
    t = fe.parse_bulletin(FEB_2026)                              # comma thousands
    assert t["2026-02"]["TOTAL"] == 10890 and t["ytd:2026-02"]["BEV"] == 1273
    t = fe.parse_bulletin(MAY_2025_GARBLED)                     # overlapped text in a PDF
    assert t["2025-05"]["TOTAL"] == 10339 and "TOTAL" not in t["ytd:2025-05"]
    assert fe.parse_bulletin("no table here") == {}


def test_bulletin_month_from_file_name():
    assert fe.bulletin_month("Boletin-de-Prensa-Agosto-2026.pdf") == "2026-08"
    assert fe.bulletin_month("Boletin-de-Prensa-Septiembre-2025-1.pdf") == "2025-09"
    assert fe.bulletin_month("Boletin-de-Prensa-Noviembre-2025_vf.pdf") == "2025-11"
    assert fe.bulletin_month("BOLETIN-DE-VENTAS-2020-PARA-PRENSA-ENERO-2021.pdf") == "2021-01"
    assert fe.bulletin_month("ESTATUTOS-AEADE_2016.pdf") is None


def _agg_with(total, bev, whole, period="2026-08"):
    agg = fe.Aggregator()
    agg.allseg[period].update({"TOTAL": total, "BEV": bev, "PETROL": total - bev})
    agg.counts[period]["Whole"]["TOTAL"] = whole
    return agg


def test_cross_check_tolerances():
    table = fe.parse_bulletin(AUG_2026)
    ok = _agg_with(15189, 2031, 10658)                           # the real 2026-08 counts
    lines, problems, flagged = fe.cross_check(ok, table, ["2026-08"])
    assert not problems and not flagged and len(lines) == 3
    warn = _agg_with(14600, 2034, 10733)                         # -4.5 %: flagged, written
    _, problems, flagged = fe.cross_check(warn, table, ["2026-08"])
    assert not problems and len(flagged) == 1
    broken = _agg_with(10000, 1200, 7000)                        # a partial file
    _, problems, _ = fe.cross_check(broken, table, ["2026-08"])
    assert len(problems) == 3
    small = fe.parse_bulletin(JAN_2026)                          # BEV: ±15 units always pass
    agg = _agg_with(8276, 195, 5500, "2025-01")
    _, problems, flagged = fe.cross_check(agg, small, ["2025-01"])
    assert not problems and not flagged
    _, problems, _ = fe.cross_check(_agg_with(15189, 2031, 10658), table, ["2026-07"])
    assert not problems                                          # month not in this run


# ── output ─────────────────────────────────────────────────────────────────

def test_upsert_line_level():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "Ecuador.csv"
        foreign = "2017-12,monthly,Whole,someone else,1,2,3,4,0,10,"
        untouched = "2018-01,monthly,Whole,SRI new-vehicle register (open data),1.0,327.0,8407.0,133.0,0.0,8868.0,"
        p.write_text(",".join(fe.CSV_COLUMNS) + "\n" + foreign + "\n" + untouched + "\n",
                     encoding="utf-8")
        c = dict(fe.empty_counts(), BEV=5, PETROL=5, TOTAL=10)
        stats = fe.upsert_lines(p, {("2026-08", "Whole"): fe.render_line("2026-08", "Whole", c),
                                    ("2017-12", "Whole"): fe.render_line("2017-12", "Whole", c)},
                                force=False)
        assert stats == {"added": 1, "updated": 0, "unchanged": 0, "skipped": 1}
        lines = p.read_text(encoding="utf-8").splitlines()
        assert lines[1] == foreign and lines[2] == untouched
        assert lines[3] == "2026-08,monthly,Whole,SRI new-vehicle register (open data),5.0,0.0,5.0,0.0,0.0,10.0,"
        assert fe.revisions(p, {("2018-01", "Whole"): fe.render_line("2018-01", "Whole", c)})


def test_csv_columns_have_no_phev():
    # One combined hybrid figure → HEV, and no PHEV column (hev_split false).
    assert "PHEV" not in fe.CSV_COLUMNS and "HEV" in fe.FUELS
    assert fe.RENDERED_VARIANTS == ("Whole", "Vans")


def test_model_display_names():
    cases = [
        ("BYD", "YUAN PRO GS AC 5P 4X2 TA EV", "YUAN PRO"),
        ("BYD", "SEAGULL FWD GS 5S AC 5P 4X2 TA EV", "SEAGULL"),
        ("BYD", "SEAGULL 400KM AC 5P 4X2 TA EV", "SEAGULL"),
        ("CHERY", "TIGGO 4 PRO COMFORT AC 1.5 5P 4X2 TA HYBRID", "TIGGO 4"),
        ("CHEVROLET", "SPARK EUV AC 5P 4X2 TA EV", "SPARK EUV"),
        ("KIA", "EV5 AIR AC 5P 4X2 TA EV", "EV5"),
        ("NISSAN", "X-TRAIL EPOWER EXCLUSIVE AC 5P 4X4 TA EV", "X-TRAIL"),
        ("NETA", "NETA V AC 5P 4X2 TA EV", "NETA V"),
        ("GREAT WALL", "HAVAL H6 B01 SUPREME AC 1.5 5P 4X2 TA HYBRID", "HAVAL H6"),
        ("TOYOTA", "NEW RAV4 LE AC 2.5 5P 4X2 TA HYBRID", "RAV4"),
        ("RAM", "RAM DT 1500 BIGHORN ETORQUE CREW CAB AC 3.6 CD 4X4 TA HYBRID", "RAM DT"),
    ]
    for make, model, want in cases:
        assert fe.display_model(make, model) == want, (model, fe.display_model(make, model))
    assert fe.display_brand("MERCEDES BENZ") == "MERCEDES-BENZ"
    assert fe.display_brand("URVANE MOVILITY") == "URVANE MOBILITY"


def test_offline_dir_listing():
    with tempfile.TemporaryDirectory() as d:
        for n in ("SRI_Vehiculos_Nuevos_2025.csv", "SRI_Vehiculos_Nuevos_2026.csv.gz", "notes.txt"):
            (Path(d) / n).write_text("x")
        assert sorted(fe.list_dir_files(Path(d))) == [2025, 2026]


def test_top_units_whole_only():
    rows = [row("1", "05/08/2026", model="YUAN PRO GS AC 5P 4X2 TA EV", make="BYD", fuel="ELECTRICO"),
            row("2", "05/08/2026", model="RIDDARA RD6 AC CD 4X4 TA EV", make="GEELY",
                cls="CAMIONETA", fuel="ELECTRICO")]
    agg = fe.count_years({2026: parse(rows)}, [2026])
    assert set(agg.units) == {("2026-08", "BEV", "BYD", "YUAN PRO")}
    top = fe.build_top(agg, "2026-08")
    assert top["classes"]["BEV"]["models"][0]["model"] == "YUAN PRO"
    assert top["total_registrations"] == 1


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
