#!/usr/bin/env python3
"""Offline tests for scripts/fetch_belgium.py (no network): synthetic CSVs
in DIV's layout, the fuel and use-group mapping, the governance guards, the
month discovery, the line-level upsert and the ACEA note.

Run: python scripts/test_fetch_belgium.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_belgium as F  # noqa: E402

FAILS = []


def check(name, got, want):
    if got != want:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")


def row(month, plate, new, keeper, use, fuel, n):
    return ",".join([f"{month}-28 23:59:59", plate, new, keeper, "'-",
                     use, use, use, use, fuel, fuel, fuel, fuel, str(n)])


def blob(rows) -> bytes:
    return ("\ufeff" + ",".join(F.HEADER) + "\n" + "\n".join(rows) + "\n").encode("utf-8")


VAT, NAT = "Legal Person (VAT)", "Natural/Legal Person"
SAMPLE = [
    row("2026-02", "New Plate", "New vehicle", VAT, "Passenger car", "Electricity", 100),
    row("2026-02", "Plate reused", "New vehicle", NAT, "Passenger car", "Electricity", 10),
    row("2026-02", "New Plate", "New vehicle", NAT, "Passenger car", "Plug-in Hybrid Petrol", 20),
    row("2026-02", "New Plate", "New vehicle", NAT, "Passenger car", "Hybrid Petrol", 30),
    row("2026-02", "New Plate", "New vehicle", VAT, "Passenger car", "Hybrid Gasoil", 5),
    row("2026-02", "New Plate", "New vehicle", NAT, "Passenger car", "Petrol", 40),
    row("2026-02", "New Plate", "New vehicle", VAT, "Passenger car", "Gasoil", 7),
    row("2026-02", "New Plate", "New vehicle", NAT, "Passenger car", "", 3),
    row("2026-02", "New Plate", "New vehicle", NAT, "Passenger car", "LPG", 2),
    row("2026-02", "Plate reused", "Used vehicle", NAT, "Passenger car", "Petrol", 999),
    row("2026-02", "New Plate", "New vehicle", VAT, "Light goods vehicle", "Gasoil", 50),
    row("2026-02", "New Plate", "New vehicle", VAT, "Lorry", "Gasoil", 8),
    row("2026-02", "New Plate", "New vehicle", VAT, "Tractor unit for semitrailer", "Electricity", 2),
    row("2026-02", "New Plate", "New vehicle", VAT, "Bus", "Electricity", 4),
    row("2026-02", "New Plate", "New vehicle", VAT, "Trailer", "", 77),
    row("2026-02", "New Plate", "New vehicle", NAT, "Motor caravan", "Gasoil", 6),
]


def test_fuel_class():
    for f, want in [("Electricity", "BEV"), ("Plug-in Hybrid Petrol", "PHEV"),
                    ("Plug-in Hybrid Gasoil", "PHEV"), ("Plug-in Hybrid LPG", "PHEV"),
                    ("Hybrid Petrol", "HEV"), ("Hybrid Gasoil", "HEV"), ("Hybrid LPG", "HEV"),
                    ("Petrol", "PETROL"), ("Gasoil", "DIESEL"), ("CNG", "OTHERS"),
                    ("Hydrogen", "OTHERS"), ("", "OTHERS"), ("Steam", None)]:
        check(f"fuel {f!r}", F.fuel_class(f), want)


def test_parse_file():
    m = F.parse_file(blob(SAMPLE), {"2026-02"})["2026-02"]
    w = m["rows"]["Whole"]
    check("Whole", (w["BEV"], w["PHEV"], w["HEV"], w["PETROL"], w["DIESEL"], w["OTHERS"], w["TOTAL"]),
          (110, 20, 35, 40, 7, 5, 217))
    check("Private TOTAL", m["rows"]["Private"]["TOTAL"], 105)
    check("Industry TOTAL", m["rows"]["Industry"]["TOTAL"], 112)
    check("Private + Industry = Whole",
          m["rows"]["Private"]["TOTAL"] + m["rows"]["Industry"]["TOTAL"], w["TOTAL"])
    check("Vans", m["rows"]["Vans"]["DIESEL"], 50)
    check("HDV lorry + tractor", (m["rows"]["HDV"]["TOTAL"], m["rows"]["HDV"]["BEV"]), (10, 2))
    check("Buses", m["rows"]["Buses"]["BEV"], 4)
    check("used cars counted aside", m["used_cars"], 999)
    check("no unknowns", m["unknown"], {})


def test_guards():
    try:
        F.parse_file(blob(SAMPLE), {"2026-03"})
        FAILS.append("wrong month not rejected")
    except ValueError:
        pass
    bad = blob(SAMPLE).replace(b"N Rowcount", b"Count")
    try:
        F.parse_file(bad)
        FAILS.append("schema drift not rejected")
    except ValueError:
        pass
    m = F.parse_file(blob(SAMPLE + [
        row("2026-02", "New Plate", "New vehicle", NAT, "Passenger car", "Steam", 9),
        row("2026-02", "New Plate", "New vehicle", NAT, "Hovercraft", "Petrol", 4),
        row("2026-02", "New Plate", "New vehicle", "Martian", "Passenger car", "Petrol", 1)]))["2026-02"]
    n, labels = m["unknown"]["Whole"]
    check("unknown Whole", (n, labels), (13, ["fuel Steam", "use group Hovercraft"]))
    check("unknown keeper", m["unknown"]["Private"], (1, ["keeper Martian"]))
    check("unknown fuel lands in OTHERS", m["rows"]["Whole"]["OTHERS"], 5 + 9 + 0)


def test_months_to_read():
    have = {"2026-06": {"source": "DIV"}, "2026-07": {"source": "DIV"},
            "2026-08": {"source": "ACEA"}}
    check("normal", F.months_to_read(have, "2026-09", False),
          ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09"])
    check("empty", F.months_to_read({}, "2025-02", False), ["2025-01", "2025-02"])
    check("backfill starts at the first monthly file",
          F.months_to_read(have, "2025-02", True), ["2025-01", "2025-02"])
    check("url", F.month_url("2026-08"),
          F.BASE_URL + "202608_Immatriculations-Inschrijvingen.csv")


def test_upsert():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "Belgium.csv"
        hdr = ",".join(F.csv_columns())
        p.write_bytes((hdr + "\r\n"
                       "2026-01,monthly,Whole,ACEA,1.0,1.0,1.0,1.0,1.0,1.0,6.0,x\r\n"
                       "2026-03,monthly,Whole,Mobilit,1.0,1.0,1.0,1.0,1.0,1.0,6.0,y\r\n").encode())
        c = dict(F.zero(), BEV=5, TOTAL=5)
        ups = {(p_, "Whole"): F.render_line(p_, "Whole", c, "n") for p_ in ("2026-01", "2026-02", "2026-03")}
        st = F.upsert_lines(p, ups, force=False)
        check("upsert stats", st, {"added": 1, "updated": 1, "unchanged": 0, "skipped": 1})
        lines = p.read_bytes().decode().split("\r\n")
        check("order + CRLF kept", [l[:7] for l in lines[1:4]], ["2026-01", "2026-02", "2026-03"])
        check("foreign row kept", lines[3].endswith(",y"), True)


def test_acea_note():
    c = {"BEV": 10, "PHEV": 2, "HEV": 3, "PETROL": 4, "DIESEL": 1, "OTHERS": 0, "TOTAL": 20}
    old = {"source": "ACEA", "time_interval": "monthly", "BEV": "10", "PHEV": "2", "HEV": "3",
           "PETROL": "4", "DIESEL": "1", "OTHERS": "0", "TOTAL": "20"}
    check("equal", F.acea_note(old, c), "; = ACEA")
    check("differs", F.acea_note(dict(old, TOTAL="18", HEV="1"), c),
          "; replaces ACEA (TOTAL 18, +2; ACEA had HEV 1 / TOTAL 18)")
    check("quarterly", F.acea_note(dict(old, time_interval="quarterly"), c),
          "; replaces ACEA quarterly row")
    check("not ACEA", F.acea_note(None, c), "")
    check("acea check flag", F.acea_check("2025-04", {"TOTAL": 80}, dict(old, TOTAL="100")).endswith("CHECK"), True)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    if FAILS:
        print("FAILED:\n  " + "\n  ".join(FAILS))
        sys.exit(1)
    print("test_fetch_belgium: all tests passed")
