#!/usr/bin/env python3
"""Offline tests for scripts/fetch_latvia.py (no network): synthetic
workbooks in CSDD's layouts, the fuel mapping, the cross-checks, the
line-level upsert and the link discovery.

Run: python scripts/test_fetch_latvia.py
"""
from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_latvia as F  # noqa: E402

FAILS = []


def check(name, got, want):
    if got != want:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")


def xlsx(sheets: dict[str, list[list]]) -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


MONTHS = ["Janvāris", "Februāris", "Marts", "Aprīlis", "Maijs", "Jūnijs", "Jūlijs",
          "Augusts", "Septembris", "Oktobris", "Novembris", "Decembris", "kopā"]


def headline_book(cars_sep: int) -> bytes:
    # current-year sheet: month names start in column C; history sheet: column B
    cur = [[None], ["CSDD PIRMOREIZ REĢISTRĒTO TRANSPORTLĪDZEKĻU SKAITS 2026. GADA MĒNEŠOS"], [None],
           [None, None] + MONTHS,
           ["Kravas", None, 5, 5, 5, 5, 5, 5, 5, 5, 3],
           ["Vieglie ", None, 9, 9, 9, 9, 9, 9, 9, 9, cars_sep],
           ["Autobusi", None, 1, 1, 1, 1, 1, 1, 1, 1, 1],
           ["Kopā:", None, 99, 99, 99, 99, 99, 99, 99, 99, 99]]
    hist = [[None], ["CSDD PIRMOREIZ REĢISTRĒTO TRANSPORTLĪDZEKĻU SKAITS 2025. GADA MĒNEŠOS"], [None],
            [None] + MONTHS,
            ["Kravas"] + [7] * 12 + [84],
            ["Vieglie "] + [11] * 12 + [132],
            ["Autobusi"] + [2] * 12 + [24]]
    return xlsx({"2026": cur, "2001_2025": hist})


CAR_HDR = ["GADS", "MENESIS", "MARKA", "MODELIS", "IG", "DEGVIELA", "JAUNS", "TURETAJS",
           "KOPAA", "VECUMS_SUM", "MM", "MMG"]


def cars_book(extra=()) -> bytes:
    rows = [CAR_HDR,
            [2026, 9, "TESLA", "MODEL Y", 2026, "Elektrība", "Jauns", "FP", 2],
            [2026, 9, "VW", "TIGUAN", 2026, "Elektrība un benzīns", "Jauns", "JP", 1],
            [2026, 9, "TOYOTA", "YARIS CROSS", 2026, "Benzīns", "Jauns", "JP", 3],
            [2026, 9, "SKODA", "OCTAVIA", 2026, "Dīzeļdegviela", "Jauns", "FP", 1],
            [2026, 9, "DACIA", "SANDERO", 2026, "Sašķidrinātā gāze (LPG)", "Jauns", "FP", 1],
            [2026, 9, "BMW", "X5 XDRIVE45E", 2021, "Elektrība un benzīns", "Lietots", "FP", 2],
            [2026, 9, "AUDI", "A6", 2015, "Dīzeļdegviela", "Lietots", "JP", 4],
            [2026, 9, "AUDI", "Q4", 2026, "Elektrība", "180 dienas", "JP", 1],
            [2026, 8, "TESLA", "MODEL 3", 2026, "Elektrība", "Jauns", "FP", 5],   # other month
            *extra]
    return xlsx({"DATI": rows, "PIVOT": [[1]]})


LORRY_HDR = ["GADS", "MENESIS", "TIPS", "TL_TIPS", "KATEGORIJA", "MARKA", "MODELIS", "IG",
             "ENERGIJAS_AVOTS", "M_TILPUMS", "JAUDA", "AUTOBUSA_KLASE", "SEDVIETAS",
             "STAVVIETAS", "TURETAJS", "JAUNS", "X", "Y", "Z", "VECUMS_SUM", "KOPAA"]


def lorry_book() -> bytes:
    def r(cat, fuel, status, n):
        row = [None] * len(LORRY_HDR)
        row[0], row[1], row[4], row[8], row[15], row[20] = 2026, 9, cat, fuel, status, n
        return row
    rows = [LORRY_HDR,
            r("N1", "Elektrība", "Jauns", 1), r("N1G", "Dīzeļdegviela", "Jauns", 1),
            r("N3", "Dīzeļdegviela", "Jauns", 1), r("N2", "Saspiestā gāze (CNG)", "Lietots", 1),
            r("M3", "Elektrība", "Jauns", 1), r("M1", "Benzīns", "Jauns", 7)]
    return xlsx({"DATI": rows})


def test_fuel_class():
    cases = {"Elektrība": "BEV", "Elektrība un benzīns": "PHEV",
             "ELEKTRĪBA UN DĪZEĻDEGVIELA": "PHEV", "Benzīns": "PETROL",
             "Dīzeļdegviela": "DIESEL", "Sašķidrinātā gāze (LPG)": "OTHERS",
             "Saspiestā gāze (CNG)": "OTHERS", "Ūdeņradis": "OTHERS", "Neuzdots": "OTHERS",
             " Benzīns ": "PETROL", "Etanols": None, "": None}
    for fuel, want in cases.items():
        check(f"fuel_class({fuel!r})", F.fuel_class(fuel), want)


def test_headline():
    h = F.parse_headline(headline_book(10))
    check("2026-01 cars (column C layout)", h["2026-01"]["cars"], 9)
    check("2026-09 cars", h["2026-09"]["cars"], 10)
    check("2026-10 absent", "2026-10" in h, False)
    check("2025-12 cars (column B layout)", h["2025-12"], {"cars": 11, "lorries": 7, "buses": 2})


def test_build_months():
    h = F.parse_headline(headline_book(16))
    m = F.build_months(cars_book(), lorry_book(), h, {"2026-09"})["2026-09"]
    rows = m["rows"]
    check("Whole", rows["Whole"], {"BEV": 2, "PHEV": 1, "PETROL": 3, "DIESEL": 1,
                                   "OTHERS": 1, "TOTAL": 8})
    check("Private", rows["Private"]["TOTAL"], 4)
    check("Industry", rows["Industry"]["TOTAL"], 4)
    check("Used (Lietots + 180 dienas)", rows["Used"], {"BEV": 1, "PHEV": 2, "PETROL": 0,
                                                       "DIESEL": 4, "OTHERS": 0, "TOTAL": 7})
    check("Vans", rows["Vans"]["TOTAL"], 2)
    check("HDV (new only)", rows["HDV"]["TOTAL"], 1)
    check("Buses", rows["Buses"], {"BEV": 1, "PHEV": 0, "PETROL": 0, "DIESEL": 0,
                                   "OTHERS": 0, "TOTAL": 1})
    check("checks", [(g, r) for _, g, r in m["checks"]], [(15, 16), (4, 3), (1, 1)])
    check("cars xcheck passes within 3", F.check_failures(m["checks"]), [])
    check("soft checks reported", len(F.check_failures(m["checks"], hard_only=False)), 0)
    check("units brand", m["units"][("BEV", "TESLA", "MODEL Y")], 2)
    check("VW folded", m["units"][("PHEV", "VOLKSWAGEN", "TIGUAN")], 1)
    check("used units", m["used_units"][("PHEV", "BMW", "X5 XDRIVE45E")], 2)
    check("no unknown", m["unknown"], {})
    h2 = F.parse_headline(headline_book(40))
    m2 = F.build_months(cars_book(), lorry_book(), h2, {"2026-09"})["2026-09"]
    check("cars xcheck fails", len(F.check_failures(m2["checks"])), 1)


def test_unknown_values():
    extra = [[2026, 9, "X", "Y", 2026, "Etanols", "Jauns", "FP", 1],
             [2026, 9, "X", "Y", 2026, "Benzīns", "Jauns", "XX", 1],
             [2026, 9, "X", "Y", 2026, "Benzīns", "Demo", "FP", 1]]
    m = F.build_months(cars_book(extra), lorry_book(), {}, {"2026-09"})["2026-09"]
    check("unknown fuel → OTHERS", m["rows"]["Whole"]["OTHERS"], 2)
    check("unknown listed", m["unknown"]["Whole"], (2, ["fuel Etanols", "status Demo"]))
    check("unknown keeper", m["unknown"]["Private"], (1, ["keeper XX"]))


def test_find_files():
    page = ('<style>.a{}</style><ul><li><a href="/cck?Itemid=327&amp;id=4473&amp;task=download&amp;xi=0">'
            '<span><svg><style>.svg{}</style></svg></span> Pirmoreiz reģistrēto TL skaits </span>'
            '<span>&lt; 1 Mb</span></a></li>'
            '<li><a href="/cck?id=4473&amp;xi=1">Reģistrēto, tehniskā kārtībā esošo TL skaits</a></li>'
            '<li><a href="/cck?id=4473&amp;xi=7"><span>Pirmoreiz reģistrēto vieglo automobiļu skaits'
            '</span><span>68.2 Mb</span></a></li>'
            '<li><a href="/cck?id=4473&amp;xi=8">Pirmoreiz reģistrēto autobusu un kravas automobiļu skaits'
            ' <span>23.6 Mb</span></a></li>'
            '<li><a href="/cck?id=4473&amp;xi=6">Pirmoreiz reģistrēto un tranzīta jaunu M1, N1 automobiļu skaits</a></li></ul>')
    got = F.find_files(page)
    check("find_files keys", sorted(got), ["cars", "headline", "lorries"])
    check("cars url", got["cars"], "https://www.csdd.lv/cck?id=4473&xi=7")
    check("headline url", got["headline"].endswith("xi=0"), True)


def test_relayed():
    url = "https://www.csdd.lv/cck?id=4473&xi=7"
    check("direct", F.relayed(url, ""), url)
    check("relay", F.relayed(url, "https://relay.example/fetch?url="),
          "https://relay.example/fetch?url=https%3A%2F%2Fwww.csdd.lv%2Fcck%3Fid%3D4473%26xi%3D7")
    for bare in ("https://relay.example", "https://relay.example/"):
        check(f"bare relay {bare}", F.relayed(url, bare),
              "https://relay.example/fetch?url=https%3A%2F%2Fwww.csdd.lv%2Fcck%3Fid%3D4473%26xi%3D7")


def test_upsert():
    cols = F.csv_columns()
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "Latvia.csv"
        keep = "2014-12,monthly,Whole,ACEA,1.0,0.0,,1.0,1.0,0.0,3.0,"
        acea = "2015-01,monthly,Whole,ACEA,2.0,1.0,,387.0,734.0,15.0,1139.0,"
        mine = "2015-02,monthly,Whole,Someone else,1.0,1.0,,1.0,1.0,0.0,4.0,"
        p.write_bytes(("\n".join([",".join(cols), keep, acea, mine]) + "\n").encode())
        row = {"BEV": 2, "PHEV": 1, "PETROL": 387, "DIESEL": 734, "OTHERS": 15, "TOTAL": 1139}
        ups = {(per, "Whole"): F.render_line(per, "Whole", row, "n")
               for per in ("2015-01", "2015-02", "2015-03")}
        st = F.upsert_lines(p, ups, False)
        check("upsert stats", st, {"added": 1, "updated": 1, "unchanged": 0, "skipped": 1})
        lines = p.read_bytes().decode().split("\n")
        check("untouched line byte-identical", lines[1], keep)
        check("ACEA replaced, HEV empty", lines[2],
              "2015-01,monthly,Whole,CSDD,2.0,1.0,,387.0,734.0,15.0,1139.0,n")
        check("foreign kept", lines[3], mine)
        check("inserted in order", lines[4].startswith("2015-03,"), True)
        st = F.upsert_lines(p, ups, False)
        check("idempotent", st["added"] + st["updated"], 0)


def test_acea_note():
    old = {"source": "ACEA", "time_interval": "monthly", "TOTAL": "1139.0", "BEV": "2.0",
           "PHEV": "1.0", "HEV": "", "PETROL": "387.0", "DIESEL": "734.0", "OTHERS": "15.0"}
    same = {"BEV": 2, "PHEV": 1, "PETROL": 387, "DIESEL": 734, "OTHERS": 15, "TOTAL": 1139}
    check("acea equal", F.acea_note(old, same), "; = ACEA")
    diff = dict(same, OTHERS=17, TOTAL=1141)
    check("acea diff", F.acea_note(old, diff),
          "; replaces ACEA (TOTAL 1139, +2; ACEA had OTHERS 15 / TOTAL 1139)")
    check("acea quarterly", F.acea_note({"source": "ACEA", "time_interval": "quarterly",
                                         "TOTAL": "1"}, same), "; replaces ACEA quarterly row")
    check("own row", F.acea_note({"source": F.SOURCE}, same), "")


def test_months():
    check("month_range", F.month_range("2025-11", "2026-02"),
          ["2025-11", "2025-12", "2026-01", "2026-02"])
    check("previous_month jan", F.previous_month(__import__("datetime").date(2026, 1, 5)), "2025-12")
    have = {f"2025-{m:02d}": {"time_interval": "monthly", "TOTAL": "1000"} for m in range(1, 13)}
    check("median fraction", F.median_fraction("2026-01", 200, have), 0.2)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    if FAILS:
        print("FAILED:\n  " + "\n  ".join(FAILS))
        sys.exit(1)
    print("test_fetch_latvia: all tests passed")
