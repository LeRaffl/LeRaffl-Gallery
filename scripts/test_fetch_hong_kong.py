#!/usr/bin/env python3
"""Regression tests for scripts/fetch_hong_kong.py (no network).

Run:  python scripts/test_fetch_hong_kong.py

The fetcher's failure modes are silent: a renamed column, a new status code,
a new fuel string or a plug-in rule that is too wide would quietly move cars
between variants or columns. These cases pin the scope (vehicle class × TD
first-registration status × gross weight), the fuel mapping and every
plug-in rule (with real model strings from the TD files, including the
look-alikes that must NOT match), the published header layouts, the
cross-check against TD table 4.1(e), period parsing, the line-level upsert
and the display names used by the top-brands/models table.
"""
import csv
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_hong_kong as fh  # noqa: E402

# The three header layouts seen on the portal (2019-11 → 2026-07).
HDR_2019 = ["Vehicle Class", "Vehicle Make", "Vehicle Model", "Fuel Type",
            "Cylinder Capacity Of Engine (c.c.)", "Body Type",
            "First Registration Vehicle Status", "Permitted Gross Vehicle Weight",
            "Number Of Passenger Seats", "Taxable Value (HK$)", "Year Of Manufacture", ""]
HDR_NOTE = ["Vehicle Class", "Vehicle Make", "Vehicle Model", "Fuel Type",
            "Cylinder Capacity Of Engine (c.c.)", "Rated Power (kW)", "Body Type",
            "First Registration Vehicle Status (Note)", "Permitted Gross Vehicle Weight",
            "Number Of Passenger Seats", "Taxable Value (HK$)", "Year Of Manufacture"]
HDR_2026 = ["Vehicle Class", "Vehicle Make", "Vehicle Model", "Fuel Type",
            "Cylinder Capacity Of Engine (c.c.)", "Rated Power (kW)", "Body Type",
            "First Registration Vehicle Status", "Permitted Gross Vehicle Weight ",
            "Number Of Passenger Seats ", "Taxable Value (HK$)", "Year Of Manufacture"]


def rec(hdr, vclass, make, model, fuel, status, gvw="-", yom="2026"):
    vals = {"Vehicle Class": vclass, "Vehicle Make": make, "Vehicle Model": model,
            "Fuel Type": fuel, "Year Of Manufacture": yom}
    out = []
    for h in hdr:
        k = fh.norm_header(h)
        if k == "FIRST REGISTRATION VEHICLE STATUS":
            out.append(status)
        elif k == "PERMITTED GROSS VEHICLE WEIGHT":
            out.append(gvw)
        else:
            out.append(next((v for kk, v in vals.items() if fh.norm_header(kk) == k), "-"))
    return out


def text_of(hdr, rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(hdr)
    w.writerows(rows)
    return "﻿" + buf.getvalue()


def test_variant_scope():
    cases = [
        (("Private Car", "A", None), "Whole"),
        (("Private Car", "B", None), "Whole"),
        (("Private Car", "C1", None), "Whole"),
        (("Private Car", "C2", None), "Used"),
        (("Private Car", "D", None), None),       # own-use import: new or used
        (("Private Car", "F", None), None),       # government auction
        (("Taxi", "A", None), None),              # own vehicle class, not Whole
        (("LGV", "A", 3.5), "Vans"),
        (("LGV", "E", 3.3), "Vans"),              # assembled in HK on a new chassis
        (("LGV", "A", 3.51), None),               # N2
        (("LGV", "C2", 3.0), None),               # used LGV
        (("LGV", "A", None), None),               # weight not parsable
        (("MGV", "A", 3.0), None),
        (("Motorcycle", "A", None), None),
    ]
    for (vc, st, w), want in cases:
        got = fh.variant_for(vc, st, w)
        assert got == want, f"{vc}/{st}/{w}: {got} != {want}"


# (make, model, fuel, yom) → column. Real strings from the TD files.
FUEL_CASES = [
    ("TESLA", "MODEL Y RWD", "Electric", "2026", "BEV"),
    ("BYD", "ATTO 3", "Electric", "2026", "BEV"),
    ("TOYOTA", "ALPHARD", "Petrol", "2026", "PETROL"),     # hybrid or not: no flag → PETROL
    ("TOYOTA", "VOXY HYBRID", "Petrol", "2020", "PETROL"),  # full hybrid stays PETROL
    ("SUZUKI", "SOLIO 2WD CVT MILD HYBRID", "Petrol", "2024", "PETROL"),
    ("MASERATI", "LEVANTE GT HYBRID", "Petrol", "2023", "PETROL"),  # 48 V mild hybrid
    ("HYUNDAI", "IONIQ HYBRID", "Petrol", "2020", "PETROL"),
    ("TOYOTA", "COMFORT", "LPG", "2020", "OTHERS"),
    ("HONDA", "FREED", "Hydrogen", "2026", "OTHERS"),
    ("ISUZU", "D-MAX", "Diesel", "2022", "DIESEL"),
    # plug-ins
    ("GAC", "GAC E9 PHEV GL", "Petrol", "2026", "PHEV"),
    ("GAC", "E9 GX", "Petrol", "2025", "PHEV"),
    ("BYD", "BYD SEALION 6", "Petrol", "2026", "PHEV"),
    ("BYD", "SEAL U DM-I", "Petrol", "2025", "PHEV"),
    ("BYD", "SEAL UDM-I", "Petrol", "2025", "PHEV"),
    ("DENZA", "DENZA B5 PREMIUM", "Petrol", "2026", "PHEV"),
    ("FORTHING", "FRIDAY REEV", "Petrol", "2026", "EREV"),
    ("JAECOO", "JAECOO7 PHEV", "Petrol", "2026", "PHEV"),
    ("MITSUBISHI", "OUTLANDER PHEV 2.4", "Petrol", "2020", "PHEV"),
    ("TOYOTA", "PRIUS PHV S GR SPORT", "Petrol", "2019", "PHEV"),
    ("TOYOTA", "ALPHARD PLUG-IN EXECUTIVE LOUNGE", "Petrol", "2025", "PHEV"),
    ("PORSCHE", "CAYENNE E-HYBRID COUPE", "Petrol", "2024", "PHEV"),
    ("VOLVO", "XC90 T8 INSCRIPTION", "Petrol", "2020", "PHEV"),
    ("MERCEDES BENZ", "MERCEDES-AMG C63 S E PERFORMANCE (W206)", "Petrol", "2024", "PHEV"),
    ("MERCEDES BENZ", "MERCEDES-AMG E 53 HYBRID 4MATIC+ (W214)", "Petrol", "2025", "PHEV"),
    ("MERCEDES BENZ", "GLC300E 4MATIC", "Petrol", "2024", "PHEV"),
    ("MERCEDES BENZ", "S500 E L AMG LINE EXECUTIVE A", "Petrol", "2016", "PHEV"),
    ("LANDROVER", "RRS P440E DYN SE", "Petrol", "2023", "PHEV"),
    ("LANDROVER", "DEFENDER 110 P300E X-DYN SE", "Petrol", "2025", "PHEV"),
    ("B.M.W.", "530E SALOON - SPORT (G30)", "Petrol", "2019", "PHEV"),
    ("B.M.W.", "745LE XDRIVE SALOON (G12)", "Petrol", "2020", "PHEV"),
    ("B.M.W.", "XM (G09)", "Petrol", "2023", "PHEV"),
    ("BMW I", "I8 ROADSTER (I15)", "Petrol", "2019", "PHEV"),
    ("MINI", "MINI COOPER S E COUNTRYMAN ALL4 AUTOMATIC (F60)", "Petrol", "2020", "PHEV"),
    ("BENTLEY", "BENTAYGA HYBRID", "Petrol", "2021", "PHEV"),
    ("FERRARI", "296 GTB", "Petrol", "2023", "PHEV"),
    ("FERRARI", "296GTB", "Petrol", "2023", "PHEV"),
    ("FERRARI", "SF90 STRADALE", "Petrol", "2021", "PHEV"),
    ("LAMBORGHINI", "URUS SE", "Petrol", "2025", "PHEV"),
    ("LAMBORGHINI", "REVUELTO", "Petrol", "2024", "PHEV"),
    ("MCLAREN", "ARTURA COUPE", "Petrol", "2023", "PHEV"),
    # not in the HK files yet — standard plug-in designations, kept ready
    ("VOLKSWAGEN", "GOLF GTE", "Petrol", "2026", "PHEV"),
    ("AUDI", "Q5 55 TFSI E QUATTRO", "Petrol", "2026", "PHEV"),
    ("JEEP", "WRANGLER UNLIMITED 4XE", "Petrol", "2026", "PHEV"),
    ("LEXUS", "NX450H+", "Petrol", "2026", "PHEV"),
    # look-alikes that must stay combustion
    ("MERCEDES BENZ", "190E 2.5-16 AUTO", "Petrol", "1989", "PETROL"),   # E = Einspritzung
    ("MERCEDES BENZ", "300E", "Petrol", "1992", "PETROL"),
    ("MERCEDES BENZ", "E200 EXCLUSIVE LINE (W214)", "Petrol", "2025", "PETROL"),
    ("MERCEDES BENZ", "C200 ESTATE AMG EDITION (S206)", "Petrol", "2024", "PETROL"),
    ("MERCEDES BENZ", "GLE450 4M (V167)", "Petrol", "2022", "PETROL"),
    ("MERCEDES BENZ", "V260 AVANTGARDE EL FACELIFT", "Petrol", "2023", "PETROL"),
    ("B.M.W.", "740LIA SALOON SE (G12)", "Petrol", "2020", "PETROL"),
    ("B.M.W.", "X5 XDRIVE40IA 7-SEATER XLINE (G05)", "Petrol", "2022", "PETROL"),
    ("LANDROVER", "DEFENDER 110 P400 SE 7S", "Petrol", "2022", "PETROL"),  # MHEV
    ("LAMBORGHINI", "URUS S 4.0 - 5 SEATS", "Petrol", "2024", "PETROL"),
    ("FERRARI", "ROMA", "Petrol", "2023", "PETROL"),
    ("VOLVO", "XC90 T6 INSCRIPTION", "Petrol", "2019", "PETROL"),
    ("VOLVO", "XC90 B5 MOMENTUM SE", "Petrol", "2021", "PETROL"),
    ("LOTUS", "EMIRA TURBO SE", "Petrol", "2025", "PETROL"),
    ("DFSK", "580", "Petrol", "2021", "PETROL"),
    ("MG", "MG3 HYBRID+", "Petrol", "2025", "PETROL"),                  # full hybrid
    ("JAGUAR", "E-PACE S P200", "Petrol", "2020", "PETROL"),
    ("NISSAN", "NOTE E-POWER", "Petrol", "2021", "PETROL"),            # series hybrid, no plug
    ("HONDA", "STEPWGN E:HEV SPADA", "Petrol", "2023", "PETROL"),
]


def test_fuel_and_plugin_rules():
    for make, model, fuel, yom, want in FUEL_CASES:
        got = fh.fuel_class(fuel, make, model, fh.parse_year(yom))
        assert got == want, f"{make} {model} ({fuel}, {yom}): {got} != {want}"
    assert fh.fuel_class("Solar", "X", "Y", 2026) is None
    # an Electric record is BEV whatever the name says
    assert fh.fuel_class("Electric", "BYD", "SEAL U DM-I", 2026) == "BEV"


def test_every_rule_is_exercised():
    """Each PHEV_RULES entry must be hit by at least one case above, so a rule
    nobody tests cannot sneak in."""
    hit = set()
    for make, model, fuel, yom, want in FUEL_CASES:
        if want in ("PHEV", "EREV"):
            r = fh.plugin_class(make, model, fh.parse_year(yom))
            hit.add(r[1])
    missing = [why for _, _, _, _, why in fh.PHEV_RULES if why not in hit]
    assert not missing, f"rules without a test case: {missing}"


def test_headers_and_aggregation():
    agg = fh.Aggregator()
    for hdr, p in ((HDR_2019, "2019-11"), (HDR_NOTE, "2023-06"), (HDR_2026, "2026-07")):
        rows = [
            rec(hdr, "Private Car", "TESLA", "MODEL Y RWD", "Electric", "A"),
            rec(hdr, "Private Car", "GAC", "GAC E9 PHEV GL", "Petrol", "A"),
            rec(hdr, "Private Car", "TOYOTA", "ALPHARD", "Petrol", "C1"),
            rec(hdr, "Private Car", "TOYOTA", "ALPHARD", "Petrol", "C2"),
            rec(hdr, "Private Car", "TOYOTA", "ALPHARD", "Petrol", "D"),
            rec(hdr, "LGV", "MAXUS", "EDELIVER 3", "Electric", "A", gvw="3.5"),
            rec(hdr, "LGV", "ISUZU", "NPR", "Diesel", "A", gvw="5.5"),
            rec(hdr, "Taxi", "TOYOTA", "COMFORT", "LPG", "A"),
        ]
        n = fh.add_text(p, text_of(hdr, rows), agg)
        assert n == 8, (p, n)
        w, u, v = (agg.counts[p][k] for k in ("Whole", "Used", "Vans"))
        assert (w["BEV"], w["PHEV"], w["PETROL"], w["TOTAL"]) == (1, 1, 1, 3), w
        assert (u["PETROL"], u["TOTAL"]) == (1, 1), u
        assert (v["BEV"], v["TOTAL"]) == (1, 1), v
        assert agg.pc_status[(p, "A")] == 2 and agg.pc_status_el[(p, "A")] == 1
        assert agg.excluded[(p, "PRIVATE CAR", "D")] == 1
        assert agg.excluded[(p, "LGV", "A")] == 1
    assert fh.check_sums(agg, ["2019-11", "2023-06", "2026-07"]) == []


def test_schema_drift_aborts():
    bad = ["Vehicle Class", "Vehicle Make", "Model", "Fuel Type",
           "First Registration Vehicle Status", "Permitted Gross Vehicle Weight",
           "Year Of Manufacture"]
    try:
        fh.add_text("2026-07", text_of(bad, [["Private Car", "X", "Y", "Petrol", "A", "-", "2026"]]),
                    fh.Aggregator())
    except SystemExit as e:
        assert "schema drift" in str(e)
    else:
        raise AssertionError("missing column must abort")


def test_unknown_status_and_fuel_reported():
    agg = fh.Aggregator()
    agg.add("2026-07", "Private Car", "X", "Y", "Solar", "A", "-", "2026")
    agg.add("2026-07", "Private Car", "X", "Y", "Petrol", "G", "-", "2026")
    assert agg.unknown_fuel[("2026-07", "SOLAR")] == 1
    assert agg.counts["2026-07"]["Whole"]["OTHERS"] == 1
    assert agg.unknown_status[("2026-07", "PRIVATE CAR", "G")] == 1


def test_period_parsing():
    assert fh.period_of("particulars_of_first_registered_vehicle_jul_2026_eng.csv") == "2026-07"
    assert fh.period_of("particulars_of_first_registered_vehicle_sept_2020_eng.csv") == "2020-09"
    assert fh.period_of("Particulars of first registered vehicles(English) - March 2026") == "2026-03"
    assert fh.period_of("Particulars of first registered vehicles(English) - Nov 2019") == "2019-11"
    assert fh.period_of("dataspec.pdf") is None


TABLE41E = """﻿"YR_MTH","VEHICLE_CLASS_CODE","MAKE","FIRST_REG_STATUS","FIRST_REG_STATUS_REV","FUEL_TYPE_CODE","BODY_TYPE_CODE","FIRST_REG"
"201812","1","TESLA","Brand new","","ELECTRIC","4",50
"202607","1","TESLA","","A","ELECTRIC","4",1
"202607","1","GAC","","A","PETROL","6",1
"202607","1","TOYOTA","","C1","PETROL","6",1
"202607","1","TOYOTA","","C2","PETROL","6",{c2}
"""


def test_cross_check():
    agg = fh.Aggregator()
    fh.add_text("2026-07", text_of(HDR_2026, [
        rec(HDR_2026, "Private Car", "TESLA", "MODEL Y RWD", "Electric", "A"),
        rec(HDR_2026, "Private Car", "GAC", "E9 GX", "Petrol", "A"),
        rec(HDR_2026, "Private Car", "TOYOTA", "ALPHARD", "Petrol", "C1"),
        rec(HDR_2026, "Private Car", "TOYOTA", "ALPHARD", "Petrol", "C2"),
    ]), agg)
    compared, small, mism = fh.cross_check(agg, ["2026-07"], TABLE41E.format(c2=1))
    assert compared == ["2026-07"] and not small and not mism
    compared, small, mism = fh.cross_check(agg, ["2026-07"], TABLE41E.format(c2=3))
    assert len(small) == 1 and not mism, (small, mism)    # 1 vs 3: within 2 units
    compared, small, mism = fh.cross_check(agg, ["2026-07"], TABLE41E.format(c2=40))
    assert len(mism) == 1, mism
    # months the table does not have yet are not compared
    assert fh.cross_check(agg, ["2026-08"], TABLE41E.format(c2=1))[0] == []


def test_completeness_guard():
    have = {f"2025-{m:02d}": {"TOTAL": "4000"} for m in range(1, 13)}
    # June 2026 after the EV-tax deadline ran at ~49 % of the median: written
    assert not fh.looks_incomplete("2026-01", 1910, have)
    assert fh.median_fraction("2026-01", 1910, have) < fh.WARN_MONTH_FRACTION
    # a quarter of a normal month: treated as a broken upload
    assert fh.looks_incomplete("2026-01", 900, have)
    # too little history to judge
    assert not fh.looks_incomplete("2025-04", 10, have)


def test_upsert_line_level():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "Hong Kong.csv"
        c = fh.empty_counts()
        c.update(BEV=10, PHEV=1, PETROL=5, TOTAL=16)
        st = fh.upsert_lines(p, {("2026-07", "Whole"): fh.render_line("2026-07", "Whole", c)}, False)
        assert st["added"] == 1
        foreign = "2026-06,monthly,Whole,someone else,1.0,0.0,0.0,1.0,0.0,0.0,2.0,"
        p.write_text(p.read_text().replace("\n", "\n" + foreign + "\n", 1))
        st = fh.upsert_lines(p, {("2026-06", "Whole"): fh.render_line("2026-06", "Whole", c)}, False)
        assert st["skipped"] == 1 and foreign in p.read_text()
        lines = p.read_text().splitlines()
        assert lines[0] == ",".join(fh.CSV_COLUMNS)
        assert lines[2] == "2026-07,monthly,Whole,Transport Department (data.gov.hk)," \
                           "10.0,1.0,0.0,5.0,0.0,0.0,16.0,"


def test_display_names():
    cases = [
        (("TESLA", "MODEL Y LONG RANGE DUAL MOTOR ALL WHEEL DRIVE"), ("TESLA", "MODEL Y")),
        (("TESLA", "MODEL 3 RWD"), ("TESLA", "MODEL 3")),
        (("BYD", "BYD SEALION 7"), ("BYD", "SEALION 7")),
        (("ZEEKR", "7X PLATINUM"), ("ZEEKR", "7X")),
        (("ZEEKR", "009 DELUXE"), ("ZEEKR", "009")),
        (("XPENG", "G6 580 PRO RWD (F30R)"), ("XPENG", "G6")),
        (("GAC", "GAC E9 PHEV GL"), ("GAC", "E9")),
        (("B.M.W.", "IX1 EDRIVE20 XLINE (U11)"), ("BMW", "IX1 EDRIVE20")),
        (("M.G.", "MG ZS EV"), ("MG", "ZS")),
        (("MERCEDES BENZ", "EQB 250+ FACELIFT (X243)"), ("MERCEDES-BENZ", "EQB 250+")),
        (("MERCEDES BENZ", "MERCEDES-AMG E 53 HYBRID 4MATIC+ (W214)"),
         ("MERCEDES-BENZ", "AMG E 53 HYBRID")),
    ]
    for (mk, mo), (wb, wm) in cases:
        assert (fh.display_brand(mk), fh.display_model(mk, mo)) == (wb, wm), \
            (mk, mo, fh.display_brand(mk), fh.display_model(mk, mo))


def test_top_only_whole_and_electrified():
    agg = fh.Aggregator()
    agg.add("2026-07", "Private Car", "TESLA", "MODEL Y RWD", "Electric", "A", "-", "2026")
    agg.add("2026-07", "Private Car", "TESLA", "MODEL Y LONG RANGE DUAL MOTOR ALL WHEEL DRIVE",
            "Electric", "A", "-", "2026")
    agg.add("2026-07", "Private Car", "GAC", "E9 GX", "Petrol", "A", "-", "2026")
    agg.add("2026-07", "Private Car", "TOYOTA", "ALPHARD", "Petrol", "A", "-", "2026")
    agg.add("2026-07", "Private Car", "BYD", "ATTO 3", "Electric", "C2", "-", "2024")  # Used
    top = fh.build_top(agg, "2026-07")
    assert top["total_registrations"] == 4
    assert top["classes"]["BEV"]["units"] == 2
    assert top["classes"]["BEV"]["models"][0] == {
        "brand": "TESLA", "model": "MODEL Y", "units": 2, "share_of_class": 1.0}
    assert top["classes"]["PHEV"]["brands"][0]["brand"] == "GAC"
    assert "PETROL" not in top["classes"]


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
