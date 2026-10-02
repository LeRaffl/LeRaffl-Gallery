#!/usr/bin/env python3
"""Regression tests for scripts/fetch_switzerland.py (no network).

Run:  python scripts/test_fetch_switzerland.py

The fetcher's failure modes are silent: a new Fahrzeugart, a renamed fuel
code or a hybrid without a hybrid code would quietly move vehicles between
variants or columns, and a wrong month rule would drift the series away from
ACEA. These cases pin the scope (EU class × Fahrzeugart → variant), the fuel
mapping incl. the PHEV/HEV fallback, the snapshot's "complete to" month, the
ACEA month rule (late registrations flow into the next written month, never
from another source's rows), the line-level upsert, the ACEA cross-check
tolerances, the top-list model names, and one end-to-end tally of a file.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_switzerland as fs  # noqa: E402


def getter(**kw):
    return lambda k: kw.get(k, "")


def test_variant_scope():
    cases = [
        (dict(Fahrzeugklasse="M1", Fahrzeugart="Personenwagen"), "Whole"),
        (dict(Fahrzeugklasse="", Fahrzeugart="Personenwagen"), "Whole"),        # no EU class on file
        (dict(Fahrzeugklasse="M1", Fahrzeugart="Leichter Motorwagen"), None),   # campers: M1, not cars
        (dict(Fahrzeugklasse="M1", Fahrzeugart="Schwerer Motorwagen"), None),
        (dict(Fahrzeugklasse="N1", Fahrzeugart="Lieferwagen"), "Vans"),
        (dict(Fahrzeugklasse="N1", Fahrzeugart="Leichter Motorwagen"), None),
        (dict(Fahrzeugklasse="N1", Fahrzeugart="Arbeitsmaschine"), None),
        (dict(Fahrzeugklasse="N2", Fahrzeugart="Lastwagen"), "HDV"),
        (dict(Fahrzeugklasse="N3", Fahrzeugart="Sattelschlepper"), "HDV"),
        (dict(Fahrzeugklasse="N3", Fahrzeugart="Arbeitsmaschine"), None),       # cranes, mixers' chassis
        (dict(Fahrzeugklasse="M3", Fahrzeugart="Gelenkbus", Gesamtgewicht="29000"), "Buses"),
        (dict(Fahrzeugklasse="M2", Fahrzeugart="Gesellschaftswagen", Gesamtgewicht="5000"), "Buses"),
        (dict(Fahrzeugklasse="M2", Fahrzeugart="Kleinbus", Gesamtgewicht="3500"), None),  # ACEA: buses > 3.5 t
        (dict(Fahrzeugklasse="L3", Fahrzeugart="Motorrad"), "2-Wheelers"),
        (dict(Fahrzeugklasse="L1", Fahrzeugart="Kleinmotorrad"), "2-Wheelers"),
        (dict(Fahrzeugklasse="L5", Fahrzeugart="Dreirädr. Motorfahrzeug"), None),
        (dict(Fahrzeugklasse="L7", Fahrzeugart="Kleinmotorfahrzeug"), None),    # quads
        (dict(Fahrzeugklasse="O2", Fahrzeugart="Sachentransportanhänger"), None),
        (dict(Fahrzeugklasse="T1", Fahrzeugart="Landwirt. Traktor"), None),
    ]
    for kw, want in cases:
        assert fs.variant_of(getter(**kw)) == want, (kw, want)
    assert fs.used_variant_of(getter(Fahrzeugklasse="M1", Fahrzeugart="Personenwagen")) == "Used"
    assert fs.used_variant_of(getter(Fahrzeugklasse="N1", Fahrzeugart="Lieferwagen")) is None


def test_fuel_mapping():
    cases = [
        (dict(Treibstoff_Code="E"), "BEV"),
        (dict(Treibstoff_Code="R"), "PHEV"),                                    # range extender
        (dict(Treibstoff_Code="C", Hybridcode="OVC-HEV"), "PHEV"),
        (dict(Treibstoff_Code="C", Hybridcode="OVC-HEV", **{"El-Verbrauch": ""}), "PHEV"),
        (dict(Treibstoff_Code="C", Hybridcode="NOVC-HEV"), "HEV"),               # full + mild
        (dict(Treibstoff_Code="F", Hybridcode="NOVC-HEV"), "HEV"),
        # national type approval: no hybrid code → electric consumption / CO2
        (dict(Treibstoff_Code="C", Hybridcode="N/A", **{"El-Verbrauch": "17,2"}), "PHEV"),
        (dict(Treibstoff_Code="C", Hybridcode="N/A", **{"CO2-WLTP": "22"}), "PHEV"),
        (dict(Treibstoff_Code="C", Hybridcode="N/A", **{"CO2-WLTP": "118"}), "HEV"),
        (dict(Treibstoff_Code="C", Hybridcode="N/A", **{"CO2-WLTP": "0"}), "HEV"),   # missing CO2
        (dict(Treibstoff_Code="C", Hybridcode="N/A", **{"El-Verbrauch": "0,0"}), "HEV"),
        (dict(Treibstoff_Code="C", CO2="45"), "PHEV"),                          # pre-2022 files
        (dict(Treibstoff_Code="B"), "PETROL"),
        (dict(Treibstoff_Code="P"), "PETROL"),
        (dict(Treibstoff_Code="D"), "DIESEL"),
        (dict(Treibstoff_Code="X", Hybridcode="NOVC-FCHV"), "OTHERS"),          # hydrogen
        (dict(Treibstoff_Code="Z"), "OTHERS"),                                  # LPG / petrol
        (dict(Treibstoff_Code="Y"), "OTHERS"),                                  # CNG / petrol
        (dict(Treibstoff="Elektrisch"), "BEV"),                                 # label fallback
        (dict(Treibstoff="Elektrisch mit RE (Range Extender)"), "PHEV"),
        (dict(Treibstoff="Benzin / Elektrisch", Hybridcode="NOVC-HEV"), "HEV"),
    ]
    for kw, want in cases:
        assert fs.fuel_of(getter(**kw)) == want, (kw, want)


def test_periods():
    assert fs.neuzu_period(getter(Erstinverkehrsetzung_Jahr="2026",
                                  Erstinverkehrsetzung_Monat="06")) == "2026-06"
    assert fs.neuzu_period(getter(Erstinverkehrsetzung_Jahr="2026",
                                  Erstinverkehrsetzung_Monat="6")) == "2026-06"
    assert fs.neuzu_period(getter()) is None
    # used imports: the first SWISS registration, not the one abroad
    assert fs.gebr_period(getter(Erstinverkehrsetzung_Jahr="2019", Erstinverkehrsetzung_Monat="03",
                                 Ersterfassung_Jahr="2026", Ersterfassung_Monat="08")) == "2026-08"


def test_last_complete_month():
    d = fs.parse_date
    assert fs.last_complete_month(d("01.10.2026"), d("30.09.2026")) == "2026-09"
    # mid-month snapshot: the month it is in is not complete yet
    assert fs.last_complete_month(d("16.10.2026"), d("15.10.2026")) == "2026-09"
    # January files still hold the previous year
    assert fs.last_complete_month(d("16.01.2026"), d("15.01.2026")) == "2025-12"
    assert fs.last_complete_month(d("01.01.2027"), d("31.12.2026")) == "2026-12"
    # GEBR carries only the data date
    assert fs.last_complete_month(d("01.10.2026"), None) == "2026-09"
    assert fs.last_complete_month(None, None) is None
    assert fs.parse_date("garbage") is None


def test_snapshot_meta():
    header = ["Fahrzeugklasse", "Datenstand", "Neuzulassungen_von", "Neuzulassungen_bis"]
    row = ["M1", "01.10.2026", "01.01.2026", "30.09.2026"]
    ds, bis = fs.snapshot_meta(header, row)
    assert fs.last_complete_month(ds, bis) == "2026-09"


def tally_with(variant, months):
    t = fs.Tally()
    for p, c in months.items():
        t.counts[variant][p].update(c)
    return t


def row(source, **c):
    r = {"source": source, "time_interval": "monthly"}
    r.update({k: str(float(c.get(k, 0))) for k in fs.FUELS})
    r["TOTAL"] = str(float(sum(c.values())))
    return r


def test_flow_late_registrations_move_forward():
    # Snapshot after September: Jan and Aug have since gained late entries.
    t = tally_with("Whole", {"2026-01": {"BEV": 105, "PETROL": 50},
                             "2026-08": {"BEV": 200, "PETROL": 102},
                             "2026-09": {"BEV": 300, "PETROL": 100}})
    have = {"2026-01": row("ASTRA", BEV=100, PETROL=50),
            "2026-08": row("ASTRA", BEV=200, PETROL=100)}
    out = fs.flow_months(t, "Whole", have, "2026-09")
    # months 02..07 are missing (zero in the snapshot) -> written as empty
    # months; the first missing month absorbs the late registrations.
    assert list(out)[0] == "2026-02"
    c, flow = out["2026-02"]
    assert flow == 7 and c["BEV"] == 5 and c["PETROL"] == 2
    c, flow = out["2026-09"]
    assert flow == 0 and c["BEV"] == 300 and c["TOTAL"] == 400


def test_flow_only_against_own_rows():
    # Jan..Aug from ACEA/BFS: their gap to the register is not carried.
    t = tally_with("Whole", {"2026-08": {"PHEV": 2000, "HEV": 5000},
                             "2026-09": {"PHEV": 2300, "HEV": 7000}})
    have = {f"2026-{m:02d}": row("ACEA", PHEV=1800, HEV=5300) for m in range(1, 9)}
    out = fs.flow_months(t, "Whole", have, "2026-09")
    assert list(out) == ["2026-09"]
    c, flow = out["2026-09"]
    assert flow == 0 and c["PHEV"] == 2300 and c["HEV"] == 7000


def test_flow_nothing_to_do():
    t = tally_with("Whole", {"2026-09": {"BEV": 1}})
    have = {f"2026-{m:02d}": row("ASTRA", BEV=1) for m in range(1, 10)}
    assert fs.flow_months(t, "Whole", have, "2026-09") == {}


def test_flow_never_negative():
    # a written month the register later corrected *down*
    t = tally_with("Vans", {"2026-01": {"DIESEL": 90}, "2026-02": {"DIESEL": 5}})
    have = {"2026-01": row("ASTRA", DIESEL=100)}
    c, flow = fs.flow_months(t, "Vans", have, "2026-02")["2026-02"]
    assert flow == -10 and c["DIESEL"] == 0 and c["TOTAL"] == 0


def test_flow_january_starts_fresh():
    # December of last year is not differenced into January.
    t = tally_with("Whole", {"2027-01": {"BEV": 10}})
    have = {"2026-12": row("ASTRA", BEV=999)}
    c, flow = fs.flow_months(t, "Whole", have, "2027-01")["2027-01"]
    assert flow == 0 and c["BEV"] == 10


def test_exact_months_never_revises():
    t = tally_with("Used", {"2025-01": {"BEV": 9}, "2025-02": {"BEV": 4}})
    have = {"2025-01": row("ASTRA", BEV=8)}
    assert fs.exact_months(t, "Used", have, ["2025-01", "2025-02"], False) == \
        {"2025-02": {**{k: 0 for k in fs.FUELS}, "BEV": 4, "TOTAL": 4}}
    assert set(fs.exact_months(t, "Used", have, ["2025-01", "2025-02"], True)) == \
        {"2025-01", "2025-02"}


def test_upsert_lines_is_line_level():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "Switzerland.csv"
        header = ",".join(fs.CSV_COLUMNS)
        old = [
            "2010-01,monthly,Whole,pxweb.bfs.admin.ch / ACEA,10.0,2.0,307.0,12561.0,6295.0,106.0,19281.0,",
            "2026-05,quarterly,Whole,https://automobile.example,3724,11092,23383,5093,157,1.5e3,43449,PETROL = a+b",
        ]
        p.write_text("\n".join([header] + old) + "\n", encoding="utf-8")
        c = {"BEV": 1, "PHEV": 2, "HEV": 3, "PETROL": 4, "DIESEL": 5, "OTHERS": 0, "TOTAL": 15}
        new = fs.render_line("2026-09", "Whole", c)
        st = fs.upsert_lines(p, {("2026-09", "Whole"): new}, False)
        assert st["added"] == 1
        lines = p.read_text(encoding="utf-8").splitlines()
        assert lines[1:3] == old          # untouched bytes, incl. 1.5e3 and int formatting
        assert lines[3] == "2026-09,monthly,Whole,ASTRA,1.0,2.0,3.0,4.0,5.0,0.0,15.0,"
        # a foreign row is never replaced without force
        foreign = fs.render_line("2010-01", "Whole", c)
        assert fs.upsert_lines(p, {("2010-01", "Whole"): foreign}, False)["skipped"] == 1
        assert p.read_text(encoding="utf-8").splitlines()[1] == old[0]
        # re-writing the same line is a no-op
        assert fs.upsert_lines(p, {("2026-09", "Whole"): new}, False)["unchanged"] == 1


def test_upsert_keeps_crlf_and_order():
    # Switzerland.csv came from the ACEA pipeline: CRLF, one LF line written
    # by hand, and history out of period order. Adding a month must change
    # exactly one line.
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "Switzerland.csv"
        header = ",".join(fs.CSV_COLUMNS)
        body = (header + "\r\n"
                + "2022-08,monthly,Whole,BFS,1,1,1,1,1,0,5,\r\n"
                + "2022-07,monthly,Whole,BFS,1,1,1,1,1,0,5,\r\n"       # out of order
                + "2026-07,monthly,Whole,ACEA,1,1,1,1,1,0,5,derived\n"  # LF
                + "2026-08,monthly,Whole,ACEA,1,1,1,1,1,0,5,\r\n")
        p.write_bytes(body.encode())
        c = {"BEV": 1, "PHEV": 0, "HEV": 0, "PETROL": 0, "DIESEL": 0, "OTHERS": 0, "TOTAL": 1}
        fs.upsert_lines(p, {("2026-09", "Whole"): fs.render_line("2026-09", "Whole", c),
                            ("2026-06", "Whole"): fs.render_line("2026-06", "Whole", c)}, False)
        got = p.read_bytes().decode()
        new9 = fs.render_line("2026-09", "Whole", c) + "\r\n"
        new6 = fs.render_line("2026-06", "Whole", c) + "\r\n"
        lines = body.splitlines(keepends=True)
        want = "".join(lines[:3] + [new6] + lines[3:] + [new9])
        assert got == want, got


def test_acea_deltas():
    ours = {"BEV": 4843, "PHEV": 1903, "HEV": 5981, "PETROL": 2566, "DIESEL": 754, "TOTAL": 16047}
    assert fs.acea_deltas(ours, dict(ours)) == []
    near = dict(ours, BEV=4900, TOTAL=16104)          # +1.2 % BEV, +0.4 % total
    assert fs.acea_deltas(near, ours) == []
    off = dict(ours, PHEV=2100, TOTAL=16244)          # +10 % PHEV, +1.2 % total
    issues = fs.acea_deltas(off, ours)
    assert any(i.startswith("TOTAL") for i in issues) and any(i.startswith("PHEV") for i in issues)
    tiny = {"BEV": 10, "PHEV": 0, "HEV": 0, "PETROL": 0, "DIESEL": 0, "TOTAL": 10}
    assert fs.acea_deltas(dict(tiny, BEV=10), dict(tiny, BEV=10)) == []


def test_model_name():
    cases = [
        (dict(Typ1="Model Y", Typ2="Model", Typ3="Y"), "MODEL Y"),
        (dict(Typ1="ENYAQ 85X", Typ2="ENYAQ", Typ3="85X"), "ENYAQ"),           # trim
        (dict(Typ1="X1 xDrive30e", Typ2="X1", Typ3="xDrive30e"), "X1"),
        (dict(Typ1="GLC 400 4MATIC", Typ2="GLC", Typ3="400"), "GLC"),
        (dict(Typ1="5 E-TECH ELECTRIC", Typ2="5", Typ3="E-TECH"), "5"),         # RENAULT 5
        (dict(Typ1="2 HYBRID", Typ2="2", Typ3="HYBRID"), "2"),                  # MAZDA 2
        (dict(Typ1="208 MHEV", Typ2="208", Typ3="MHEV"), "208"),                # a model number
        (dict(Marke="MG", Typ1="MG4 Electric", Typ2="MG4", Typ3="Electric"), "4"),  # = MG "4 EV"
        (dict(Marke="MG", Typ1="4 EV", Typ2="4", Typ3="EV"), "4"),
        (dict(Marke="MG", Typ1="ZS Hybrid", Typ2="ZS", Typ3="Hybrid"), "ZS"),
        (dict(Typ1="EX30", Typ2="EX30", Typ3=""), "EX30"),
        (dict(Typ1="ID.3 Pro", Typ2="ID.", Typ3="3"), "ID. 3"),
        (dict(Typ1="SEAL U DM-i", Typ2="SEAL", Typ3="U"), "SEAL U"),            # families
        (dict(Typ1="SEAL 6 DM-i", Typ2="SEAL", Typ3="6"), "SEAL 6"),
        (dict(Typ1="Ioniq 5", Typ2="Ioniq", Typ3="5"), "IONIQ 5"),
        (dict(Typ1="RR Evoque PHEV", Typ2="RR", Typ3="Evoque"), "RR EVOQUE"),
        (dict(Typ1="RR P550e PHEV", Typ2="RR", Typ3="P550e"), "RR"),            # engine code
        (dict(Typ1="AMG GLC 63", Typ2="AMG", Typ3="GLC"), "AMG GLC"),
        (dict(Typ1="Clio", Typ2="", Typ3=""), "CLIO"),
    ]
    # market_top.clean() upper-cases, so one model typed two ways counts once
    for kw, want in cases:
        assert fs.model_name(getter(**kw)) == want, (kw, want)


def test_tally_file_end_to_end():
    header = ["Fahrzeugklasse", "Fahrzeugart", "Marke", "Typ1", "Typ2", "Typ3",
              "Gesamtgewicht", "Treibstoff_Code", "Treibstoff", "Hybridcode",
              "El-Verbrauch", "CO2-WLTP", "Erstinverkehrsetzung_Jahr",
              "Erstinverkehrsetzung_Monat", "Datenstand", "Neuzulassungen_bis"]
    rows = [
        ["M1", "Personenwagen", "TESLA", "Model Y", "Model", "Y", "2400", "E", "Elektrisch", "", "16,2", "0", "2026", "09"],
        ["M1", "Personenwagen", "BYD", "SEAL U DM-i", "SEAL", "U", "2400", "C", "Benzin / Elektrisch", "N/A", "15,0", "70", "2026", "09"],
        ["M1", "Personenwagen", "OPEL", "Corsa F 1.2 MHEV", "Corsa", "F", "1600", "C", "Benzin / Elektrisch", "N/A", "", "116", "2026", "08"],
        ["M1", "Leichter Motorwagen", "FIAT", "Ducato", "Ducato", "", "3500", "D", "Diesel", "", "", "220", "2026", "09"],
        ["N1", "Lieferwagen", "VW", "Transporter", "Transporter", "", "3000", "D", "Diesel", "", "", "190", "2026", "09"],
        ["M3", "Gelenkbus", "MAN", "Lion's City", "Lion's", "City", "29000", "E", "Elektrisch", "", "", "0", "2026", "09"],
        ["L3", "Motorrad", "BMW", "R 1300 GS", "R", "1300", "465", "B", "Benzin", "", "", "", "2026", "09"],
    ]
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "NEUZU.txt"
        body = ["\t".join(header)] + ["\t".join(r + ["01.10.2026", "30.09.2026"]) for r in rows]
        p.write_text("\n".join(body) + "\n", encoding="utf-8")
        t = fs.tally_file(p, "NEUZU", keep_models=True)
    assert t.rows == 7 and t.complete_to == "2026-09"
    sep = t.month("Whole", "2026-09")
    assert sep["BEV"] == 1 and sep["PHEV"] == 1 and sep["TOTAL"] == 2, sep
    assert t.month("Whole", "2026-08")["HEV"] == 1
    assert t.month("Vans", "2026-09")["DIESEL"] == 1
    assert t.month("Buses", "2026-09")["BEV"] == 1
    assert t.month("2-Wheelers", "2026-09")["PETROL"] == 1
    assert t.models["Whole"]["2026-09"][("BEV", "TESLA", "MODEL Y")] == 1
    assert t.models["Whole"]["2026-09"][("PHEV", "BYD", "SEAL U")] == 1
    assert "Vans" not in t.models                       # top lists: Whole and Used only


def test_tally_used_imports():
    header = ["Fahrzeugklasse", "Fahrzeugart", "Marke", "Typ1", "Typ2", "Typ3",
              "Treibstoff_Code", "Hybridcode", "Erstinverkehrsetzung_Jahr",
              "Erstinverkehrsetzung_Monat", "Ersterfassung_Jahr", "Ersterfassung_Monat",
              "Datenstand"]
    rows = [
        ["M1", "Personenwagen", "TESLA", "Model 3", "Model", "3", "E", "", "2022", "05", "2026", "09"],
        ["", "Personenwagen", "BMW", "330e", "330e", "", "B", "OVC-HEV", "2023", "01", "2026", "08"],
        ["N1", "Lieferwagen", "VW", "Transporter", "Transporter", "", "D", "", "2020", "02", "2026", "09"],
    ]
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "GEBR.txt"
        p.write_text("\n".join(["\t".join(header)]
                               + ["\t".join(r + ["01.10.2026"]) for r in rows]) + "\n",
                     encoding="utf-8")
        t = fs.tally_file(p, "GEBR", keep_models=True)
    assert t.complete_to == "2026-09"
    # dated by the first SWISS registration (Ersterfassung), not the one abroad
    assert t.month("Used", "2026-09")["BEV"] == 1 and t.month("Used", "2026-09")["TOTAL"] == 1
    assert t.month("Used", "2026-08")["PETROL"] == 1     # fuel B wins; hybrid code only for C/F
    assert t.models["Used"]["2026-09"][("BEV", "TESLA", "MODEL 3")] == 1
    assert "2022-05" not in t.counts["Used"]


def test_title_line_before_header():
    # GEBR-2020.txt / GEBR-2021.txt open with a title line; a parser that
    # takes line 1 as the header silently counts nothing (it did: two years
    # of used imports were missing after the first backfill).
    header = ["Fahrzeugklasse", "Fahrzeugart", "Marke", "Typ2", "Treibstoff_Code",
              "Ersterfassung_Jahr", "Ersterfassung_Monat"]
    title = "Gebrauchtfahrzeuge aus dem Ausland, erste Zulassung in der Schweiz " \
            "von 01.01.2021 bis 01.01.2022" + "\t" * 6
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "GEBR-2021.txt"
        p.write_text("\r\n".join([title, "\t".join(header),
                                   "M1\tPersonenwagen\tVW\tGolf\tE\t2021\t03"]) + "\r\n",
                     encoding="utf-8")
        t = fs.tally_file(p, "GEBR")
    assert t.month("Used", "2021-03")["BEV"] == 1
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "broken.txt"
        p.write_text("no header here\n" * 12, encoding="utf-8")
        try:
            fs.tally_file(p, "GEBR")
        except RuntimeError:
            pass
        else:
            raise AssertionError("a file without a header must fail loudly")


def test_selected_variants():
    class A:
        variant = "all"
    assert fs.selected(A) == list(fs.VARIANT_CSV)
    A.variant = "Vans, HDV,2-Wheelers"
    assert fs.selected(A) == ["Vans", "HDV", "2-Wheelers"]
    A.variant = "Vans,Trucks"
    try:
        fs.selected(A)
    except SystemExit:
        pass
    else:
        raise AssertionError("unknown variant accepted")


def test_download_retries_dropped_connections():
    import requests

    class Resp:
        status_code, headers = 200, {"content-type": "text/plain"}

        def raise_for_status(self):
            pass

        def iter_content(self, n):
            yield b"Fahrzeugklasse\tFahrzeugart\n"

    class Session:
        calls = 0

        def get(self, url, **kw):
            Session.calls += 1
            if Session.calls < 3:
                raise requests.ConnectionError("Remote end closed connection")
            return Resp()

    waits = []
    sleep, fs.time.sleep = fs.time.sleep, waits.append
    try:
        p = fs.download(Session(), "https://example/NEUZU.txt")
        assert p.read_bytes().startswith(b"Fahrzeugklasse") and waits == [10, 30]
        p.unlink()
        Session.calls = -10      # never recovers: the last error propagates
        try:
            fs.download(Session(), "https://example/NEUZU.txt")
        except requests.ConnectionError:
            pass
        else:
            raise AssertionError("gave up silently")
    finally:
        fs.time.sleep = sleep


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
