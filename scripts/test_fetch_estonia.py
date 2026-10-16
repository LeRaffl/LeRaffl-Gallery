#!/usr/bin/env python3
"""Offline tests for scripts/fetch_estonia.py (no network).

Run: python scripts/test_fetch_estonia.py
"""
from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_estonia as F  # noqa: E402

FAILS = []


def check(name, got, want):
    if got != want:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")


# ── powertrain mapping ─────────────────────────────────────────────────────

def test_fuel_class():
    cases = [
        (("ELEKTER", ""), "BEV"),
        (("ELEKTER", "NOVC_FCHV"), "OTHERS"),          # fuel cell: never BEV
        (("ELEKTER", "OVC_FCHV"), "OTHERS"),
        (("VESINIK", ""), "OTHERS"),
        (("BENSIIN_HYBRIID", "OVC_HEV"), "PHEV"),
        (("DIISEL_HYBRIID", "OVC_HEV"), "PHEV"),
        (("BENSIIN_HYBRIID", "NOVC_HEV"), "HEV"),
        (("DIISEL_HYBRIID", "NOVC_HEV"), "HEV"),       # mild-hybrid diesels
        (("BENSIIN_HYBRIID", ""), "HEV"),              # no category recorded
        (("BENSIIN HÜBRIID", ""), "HEV"),              # 2021 spelling
        (("BENSIIN", ""), "PETROL"),
        (("BENSIIN_KATALYSAATOR", ""), "PETROL"),
        (("BENSIIN KAT", ""), "PETROL"),
        (("DIISEL", ""), "DIESEL"),
        (("CNG", ""), "OTHERS"),
        (("GAAS", ""), "OTHERS"),
        (("", ""), "OTHERS"),
        (("ELEKTRI", ""), "OTHERS"),                   # look-alike, not ELEKTER
    ]
    for (e, h), want in cases:
        check(f"fuel_class({e!r},{h!r})", F.fuel_class(e, h), want)
    check("used_class hybrid", F.used_class("DIISEL HÜBRIID"), "HEV")
    check("engine_code kat", F.engine_code("bensiin kat"), "BENSIIN_KATALYSAATOR")
    check("is_known new spelling", F.is_known("BENSIIN HÜBRIID", "NOVC_HEV"), True)
    check("is_known unknown", F.is_known("WANKEL", ""), False)
    check("owner folded", F.owner_code("Füüsiline"), "FYYSILINE")
    check("owner 2024 spelling", F.owner_code("FYYSILINE"), F.PRIVATE_OWNER)


def test_num():
    check("num nbsp", F.num("3\xa0005"), 3005)
    check("num float", F.num(12.0), 12)
    check("num text", F.num("Kokku"), None)
    check("num None", F.num(None), None)


# ── workbook fixtures ──────────────────────────────────────────────────────

HDR_2026 = ["Kategooria", "Mark", "Mudel", "Tüüp", "Kere nimetus", "Keretüüp", "Esm reg aasta",
            "Kütusekombinatsioon", "Mootori tüüp", "Mootori võimsus", "Mootori maht", "Heitmenorm",
            "Hübriidi tüüp", "CO2_NEDC", "CO2_WLTP", "Istekohti", "Maakond", "Linn",
            "Tüüp (isik)", "Arv"]
HDR_2024 = ["Kategooria", "Mark", "Mudel", "Kere nimetus", "Keretüüp", "Year of ESMANE_REG_KP",
            "Kütusekombinatsioon", "MOOTORI_TYYP", "MOOTORI_VOIMSUS", "HYBRIIDI_TYYP",
            "V.KAS/OM MAAKOND", "V.KAS/OM TYYP", "tk"]
HDR_2021 = ["Kategooria", "Mark", "Mudel", "Keretüüp", "Esm reg aasta", "Mootori tüüp",
            "Mootori võimsus", "Hübriidi tüüp", "Maakond", "Linn", "Tüüp", "Arv"]


def rec(hdr, **kw):
    row = [None] * len(hdr)
    names = {"cat": 0, "brand": 1, "model": 2}
    for k, v in kw.items():
        if k in names:
            row[names[k]] = v
    ie = next(i for i, c in enumerate(hdr) if c.lower().startswith("mootori") and
              ("tüüp" in c.lower() or "tyyp" in c.lower()))
    ih = next(i for i, c in enumerate(hdr) if c.lower().startswith(("hübriid", "hybriid")))
    row[ie], row[ih] = kw.get("engine"), kw.get("hybrid")
    row[-2], row[-1] = kw.get("owner", "JURIIDILINE"), kw.get("n", 1)
    return row


def new_sheet(hdr):
    rows = [["Liiklusregistris esmaselt registreeritud uued sõidukid"], [], hdr]
    rows += [
        rec(hdr, cat="M1", brand="TOYOTA", model="BZ4X", engine="ELEKTER", n=3, owner="FÜÜSILINE"),
        rec(hdr, cat="M1", brand="ŠKODA", model="KODIAQ", engine="BENSIIN_HYBRIID", hybrid="OVC_HEV", n=2),
        rec(hdr, cat="M1G", brand="TOYOTA", model="RAV4", engine="BENSIIN_HYBRIID", hybrid="NOVC_HEV", n=4),
        rec(hdr, cat="M1", brand="VOLKSWAGEN, VW", model="TIGUAN", engine="DIISEL", n=1, owner="RIIGI"),
        rec(hdr, cat="M1", brand="KIA", model="SPORTAGE", engine="BENSIIN_KATALYSAATOR", n=5,
            owner="FÜÜSILINE"),
        rec(hdr, cat="N1", brand="FORD", model="TRANSIT", engine="DIISEL", n=6),
        rec(hdr, cat="N1G", brand="TOYOTA", model="HILUX", engine="DIISEL_HYBRIID", hybrid="NOVC_HEV", n=1),
        rec(hdr, cat="N3", brand="SCANIA", model="R", engine="CNG", n=2),
        rec(hdr, cat="M3", brand="SOLARIS", model="URBINO", engine="ELEKTER", n=1),
        rec(hdr, cat="L3e", brand="BMW", model="R", engine="BENSIIN", n=9),     # not counted
    ]
    rows.append(["Kokku"] + [None] * (len(hdr) - 2) + ["3\xa0005"])         # total row skipped
    return rows


FUEL_SHEET = [
    ["Liiklusregistris esmaselt registreeritud ( sh uued) sõidukid"], ["September"],
    ["Kategooria", "Mootori tüüp", "Esmaselt registreeritud sõidukite arv", "neist uued sõidukid"],
    ["L3e", "BENSIIN", 30, 9],
    ["M1", "BENSIIN_HYBRIID", 10, 2],
    ["M1", "BENSIIN_KATALYSAATOR", 12, 5],
    ["M1", "DIISEL", 20, 1],
    ["M1", "ELEKTER", 7, 3],
    ["M1G", "BENSIIN_HYBRIID", 6, 4, 55, 15],        # trailing category sums ignored
    ["M3", "ELEKTER", 1, 1, 1, 1],
    ["N1", "DIISEL", 8, 6], ["N1G", "DIISEL_HYBRIID", 1, 1], ["N3", "CNG", 3, 2, 12, 9],
]


def headline(cars_all=55, cars_new=15, lorries_new=9, buses_new=1):
    return [["2026.aasta esmased registreerimised "], ["September"],
            [None, "Sõiduautod", "Veoautod", "Bussid", "Haagised ", "KOKKU"],
            ["Kokku", cars_all, 12, 1, 3, 71], ["sh uued", cars_new, lorries_new, buses_new, 1, 26],
            ["neist uued omanik era ", 8, 0, 0, 0, 8]]


def workbook(hdr=HDR_2026, **kw):
    import openpyxl
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in (("Uued sõidukid", new_sheet(hdr)), ("Kytus_esm_ ( sh uued) ", FUEL_SHEET),
                       ("Esm(üldtabel) ", headline(**kw))):
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_layouts():
    for label, hdr in (("2026", HDR_2026), ("2024", HDR_2024), ("2021", HDR_2021)):
        m = F.build_month(F.read_sheets(workbook(hdr)))
        r = m["rows"]
        check(f"{label} Whole", {k: r["Whole"][k] for k in F.FUELS + ["TOTAL"]},
              {"BEV": 3, "PHEV": 2, "HEV": 4, "PETROL": 5, "DIESEL": 1, "OTHERS": 0, "TOTAL": 15})
        check(f"{label} Private", r["Private"]["TOTAL"], 8)
        check(f"{label} Industry", r["Industry"]["TOTAL"], 7)
        check(f"{label} Private+Industry=Whole",
              {k: r["Private"][k] + r["Industry"][k] for k in F.FUELS},
              {k: r["Whole"][k] for k in F.FUELS})
        check(f"{label} Vans", (r["Vans"]["DIESEL"], r["Vans"]["HEV"], r["Vans"]["TOTAL"]), (6, 1, 7))
        check(f"{label} HDV", (r["HDV"]["OTHERS"], r["HDV"]["TOTAL"]), (2, 2))
        check(f"{label} Buses", (r["Buses"]["BEV"], r["Buses"]["TOTAL"]), (1, 1))
        check(f"{label} checks pass", F.check_failures(m["checks"]), [])
        check(f"{label} owner RIIGI known", m["unknown"], {})
        check(f"{label} brand VW", ("BEV", "TOYOTA", "BZ4X") in m["units"]
              and ("DIESEL", "VOLKSWAGEN", "TIGUAN") in m["units"], True)
    # Used = first − new by engine, hybrids combined, no PHEV column
    m = F.build_month(F.read_sheets(workbook()))
    u = m["rows"]["Used"]
    check("Used", u, {"BEV": 4, "HEV": 10, "PETROL": 7, "DIESEL": 19, "OTHERS": 0, "TOTAL": 40})
    check("Used has no PHEV column", "PHEV" in F.VARIANT_FUELS["Used"], False)


def test_crosscheck():
    m = F.build_month(F.read_sheets(workbook(cars_new=16)))   # off by one: within tolerance
    check("xcheck tolerance", F.check_failures(m["checks"]), [])
    m = F.build_month(F.read_sheets(workbook(cars_new=40)))
    check("xcheck fails", len(F.check_failures(m["checks"])) >= 1, True)
    m = F.build_month(F.read_sheets(workbook(cars_all=80)))
    check("xcheck first regs", any("Kokku" in b for b in F.check_failures(m["checks"])), True)


def test_schema_drift():
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.title = "Sõidu-uus"
    buf = io.BytesIO()
    wb.save(buf)
    try:
        F.build_month(F.read_sheets(buf.getvalue()))
        FAILS.append("missing sheet did not raise")
    except ValueError:
        pass
    hdr = [c for c in HDR_2026 if not c.startswith("Hübriid")]
    try:
        F.parse_new([hdr, ["M1"] + [None] * (len(hdr) - 2) + [1]])
        FAILS.append("missing hybrid column did not raise")
    except ValueError:
        pass


def test_find_workbooks():
    page = ('<a href="/sites/default/files/documents/2026-10/INFOLEHT-092026.xlsx">Infoleht 09-2026 '
            '( esmaste ja uute sõidukite statistika) | 552 KB | xlsx</a>'
            '<a href="/sites/x/infoleht-1219_statistika.xls">Infoleht 12-19 (esmaste ja uute)</a>'
            '<a href="/sites/x/Infoleht%2010-2025%20%28esmaste%29.xls">Infoleht 10-2025 (esmaste)</a>'
            '<a href="/sites/x/omanik.xlsx">Omanikuvahetused 2016</a>'
            '<a href="/sites/x/INFOLEHT-012024.pdf">Infoleht 01-2024</a>')
    got = F.find_workbooks(page)
    check("find_workbooks", sorted(got), ["2019-12", "2025-10", "2026-09"])
    check("absolute url", got["2026-09"].startswith("https://www.transpordiamet.ee/sites/"), True)


def test_upsert():
    cols = F.csv_columns("Whole")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "Estonia.csv"
        keep = "2020-11,quarterly,Whole,ACEA,48.0,9.0,254.0,768.0,707.0,61.0,1849.0,"
        acea = "2021-01,quarterly,Whole,ACEA,31.0,14.0,480.0,847.0,473.0,62.0,1909.0,"
        mine = "2021-02,monthly,Whole,Someone else,1.0,1.0,1.0,1.0,1.0,0.0,5.0,"
        p.write_bytes(("\r\n".join([",".join(cols), keep, acea, mine]) + "\r\n").encode())
        row = {"BEV": 1, "PHEV": 0, "HEV": 0, "PETROL": 1, "DIESEL": 0, "OTHERS": 0, "TOTAL": 2}
        ups = {("2021-01", "Whole"): F.render_line("2021-01", "Whole", row, "n"),
               ("2021-02", "Whole"): F.render_line("2021-02", "Whole", row, "n"),
               ("2021-03", "Whole"): F.render_line("2021-03", "Whole", row, "n")}
        st = F.upsert_lines(p, ups, False, cols)
        check("upsert stats", st, {"added": 1, "updated": 1, "unchanged": 0, "skipped": 1})
        lines = p.read_bytes().decode().split("\r\n")
        check("untouched line byte-identical", lines[1], keep)
        check("foreign kept", lines[3], mine)
        check("ACEA replaced", lines[2].startswith("2021-01,monthly,Whole,Transpordiamet"), True)
        check("inserted in order", lines[4].startswith("2021-03,"), True)
        st = F.upsert_lines(p, ups, False, cols)
        check("idempotent", st["added"] + st["updated"], 0)
    used = F.render_line("2021-01", "Used", {"BEV": 1, "HEV": 2, "PETROL": 3, "DIESEL": 4,
                                             "OTHERS": 0, "TOTAL": 10}, "x")
    check("Used line", used, "2021-01,monthly,Used,Transpordiamet,1.0,2.0,3.0,4.0,0.0,10.0,x")


def test_acea_note():
    old = {"source": "ACEA", "time_interval": "monthly", "TOTAL": "1479.0", "BEV": "174.0",
           "PHEV": "112.0", "HEV": "773.0", "PETROL": "275.0", "DIESEL": "145.0", "OTHERS": "0.0"}
    check("acea note", F.acea_note(old, 1486),
          "; replaces ACEA (TOTAL 1479, +7; BEV 174 / PHEV 112 / HEV 773 / PETROL 275 / DIESEL 145 / OTHERS 0)")
    check("acea quarterly", F.acea_note({"source": "ACEA", "time_interval": "quarterly",
                                         "TOTAL": "1"}, 5), "; replaces ACEA quarterly row")
    check("no note for own row", F.acea_note({"source": F.SOURCE}, 5), "")
    first = F.row_notes("base", old, 1486)
    check("first write keeps ACEA", first, "base" + F.acea_note(old, 1486))
    check("rewrite keeps the trail",
          F.row_notes("new base", {"source": F.SOURCE, "notes": first}, 1490),
          "new base" + F.acea_note(old, 1486))
    check("own row without trail", F.row_notes("b", {"source": F.SOURCE, "notes": "x"}, 1), "b")
    check("brand alias", F.display_brand("SKODA"), "ŠKODA")


def test_median_guard():
    have = {f"2025-{m:02d}": {"time_interval": "monthly", "TOTAL": "1000"} for m in range(1, 13)}
    check("median fraction", F.median_fraction("2026-01", 200, have), 0.2)
    check("median short history", F.median_fraction("2025-03", 200,
                                                    {"2025-01": have["2025-01"]}), None)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    if FAILS:
        print("FAILED:\n  " + "\n  ".join(FAILS))
        sys.exit(1)
    print("test_fetch_estonia: all tests passed")
