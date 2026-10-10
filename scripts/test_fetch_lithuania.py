#!/usr/bin/env python3
"""Offline tests for scripts/fetch_lithuania.py (no network).

Run:  python scripts/test_fetch_lithuania.py
They gate the fetch in fetch-lithuania.yml: the fuel mapping, both published
layouts of Regitra's fuel table, the totals cross-check parser, the PHEV/HEV
split tiers, the register-snapshot scan and the line-level upsert.
"""
from __future__ import annotations

import io
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_lithuania as fl  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("ok   " if cond else "FAIL ") + name + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def xlsx(rows: list[list]) -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── fuel mapping ───────────────────────────────────────────────────────────

def test_fuel_class():
    cases = {
        "Elektra": "BEV",
        "Benzinas/Elektra": "HYB",
        "Dyzelinas/Elektra": "HYB",
        "Benzinas/Suskystintos naftos dujos/Elektra": "HYB",
        "Benzinas/Dujos/Elektra": "HYB",
        "Etanolis/Elektra": "HYB",
        "Dyzelinas/Kita/Elektra": "HYB",
        "Vandenilis /Elektra": "OTHERS",       # fuel cell — not a hybrid
        "Vandenilis ": "OTHERS",
        "Benzinas": "PETROL",
        "Dyzelinas": "DIESEL",
        "Dyzelinas/Dyzelinas": "DIESEL",      # register typo, still diesel
        "Benzinas/Dujos": "OTHERS",            # bi-fuel LPG is not petrol
        "Benzinas/Suskystintos naftos dujos": "OTHERS",
        "Benzinas/Etanolis": "OTHERS",
        "Gamtinės dujos": "OTHERS",
        "Nenurodyta": "OTHERS",
        "": "OTHERS",
    }
    for label, want in cases.items():
        got = fl.fuel_class(label)
        check(f"fuel_class({label!r}) = {want}", got == want, f"got {got}")
    check("known label", fl.is_known("Benzinas/Suslėgtos gamtinės dujos"))
    check("unknown component flagged", not fl.is_known("Benzinas/Plazma"))
    check("status labels", (fl.status_of("Nauja"), fl.status_of("Naudota"),
                            fl.status_of("Nauja viso"), fl.status_of("IŠ VISO"))
          == ("new", "used", "new", None))


# ── both fuel-table layouts ────────────────────────────────────────────────

def layout_2025() -> bytes:
    return xlsx([
        ["Pirmą kartą įregistruotų Lietuvoje M1 klasės transporto priemonių skaičius "
         "pagal degalų rūšį 2026 m. sausio - vasario mėn."],
        [],
        ["SAVYBĖ", "DEGALŲ RŪŠIS", "MĖNUO", None, "Bendroji suma"],
        [None, None, "2026-01", "2026-02", None],
        ["Naudota", "Benzinas", 10, 20, 30],
        [None, "Benzinas/Elektra", 5, 1, 6],
        [None, "Elektra", 1, None, 1],
        ["Naudota Suma", None, 16, 21, 37],
        ["Nauja", "Benzinas/Elektra", 50, 60, 110],
        [None, "Elektra", 7, 8, 15],
        [None, "Dyzelinas", 3, 2, 5],
        [None, "Vandenilis /Elektra", 1, None, 1],
        ["Nauja Suma", None, 61, 70, 131],
        ["Bendroji suma", None, 77, 91, 168],
    ])


def layout_2024() -> bytes:
    # 2024: months are 1..12 under the header, totals say "viso"; a fuel row
    # whose only value is 1 must not be mistaken for a month header.
    return xlsx([
        ["Pirmą kartą įregistruotų Lietuvoje M1 klasės transporto priemonių skaičius "
         "pagal degalų rūšį 2024 m. sausio-gruodžio mėn."],
        [],
        ["SAVYBĖ", "DEGALŲ RŪŠIS", "MĖNUO"],
        [None, None, 1, 2, 3, 4, 5, 6],
        ["Naudota", "Benzinas", 9, 9, 9, 9, 9, 9],
        [None, "Etanolis", 1, None, None, None, None, None],
        ["Naudota viso", None, 10, 9, 9, 9, 9, 9],
        ["Nauja", "Benzinas/Elektra", 4, 4, 4, 4, 4, 4],
        ["Nauja viso", None, 4, 4, 4, 4, 4, 4],
        ["IŠ VISO", None, 14, 13, 13, 13, 13, 13],
    ])


def test_fuel_table():
    c, s = fl.parse_fuel_table(layout_2025())
    check("2025 layout: months", sorted({p for p, _ in c}) == ["2026-01", "2026-02"])
    check("2025 layout: new Jan", c[("2026-01", "new")] ==
          {"Benzinas/Elektra": 50, "Elektra": 7, "Dyzelinas": 3, "Vandenilis /Elektra": 1})
    check("2025 layout: used Feb skips empty cell", c[("2026-02", "used")] ==
          {"Benzinas": 20, "Benzinas/Elektra": 1})
    check("2025 layout: subtotals", s[("2026-01", "new")] == 61 and s[("2026-02", "used")] == 21)
    cls, unk, _ = fl.classify_month(c[("2026-01", "new")])
    check("classify month", (cls["HYB"], cls["BEV"], cls["DIESEL"], cls["OTHERS"], unk)
          == (50, 7, 3, 1, 0))

    c, s = fl.parse_fuel_table(layout_2024())
    check("2024 layout: months from 1..12 + title year",
          sorted({p for p, _ in c}) == [f"2024-0{i}" for i in range(1, 7)])
    check("2024 layout: lone 1 is data, not a header", c[("2024-01", "used")] ==
          {"Benzinas": 9, "Etanolis": 1})
    check("2024 layout: 'viso' subtotals", s[("2024-01", "used")] == 10 and
          s[("2024-03", "new")] == 4)


def test_totals_table():
    t = fl.parse_totals_table(xlsx([
        ["Mėnuo", "Iš viso naudotų", "Iš jų M1 naudotų", "Iš viso naujų", "Iš jų M1 naujų"],
        ["Sausis", 11490, 10078, 4944, 2836],
        ["Vasaris", 11965, 10324, 5427, 2589],
        ["Kovas"],
        ["Iš viso", 1, 2, 3, 4],
    ]), 2026)
    check("totals table", t == {("2026-01", "used"): 10078, ("2026-01", "new"): 2836,
                                ("2026-02", "used"): 10324, ("2026-02", "new"): 2589})


def test_find_links():
    page = (
        '<a href="https://x/2025/03/5-Pirma-karta-iregistruotu-Lietuvoje-M1-klases-transporto-'
        'priemoniu-skaicius-pagal-degalu-rusi-2026-m.-sausio-rugpjucio-men.xlsx">Pirmą kartą '
        'įregistruotų Lietuvoje M1 klasės transporto priemonių skaičius pagal degalų rūšį 2026 m.</a>'
        '<a href="https://x/2025/03/Pirma-karta-Lietuvoje-iregistruotu-transporto-priemoniu-'
        'skaicius-2026-m-6.xlsx">Pirmą kartą Lietuvoje įregistruotų transporto priemonių skaičius 2026 m.</a>'
        '<a href="https://x/2025/03/1-Lietuvos-Respublikos-keliu-transporto-priemoniu-registre-2026-m.'
        '-pirma-karta-iregistruotu-transporto-priemoniu-skaicius-1-1.xlsx">Lietuvos ... 2026 m.</a>'
    )
    fuel, tot = fl.find_year_files(page)
    check("fuel table link", list(fuel) == [2026] and "degalu-rusi" in fuel[2026])
    check("totals link (not table 1)", list(tot) == [2026] and "/Pirma-karta-Lietuvoje" in tot[2026])
    open_page = ('<a href="https://www.regitra.lt/wp-content/uploads/failai/Atviri_JTP_parko_'
                 'duomenys.zip">juridinių (2026-07-03)</a><a href="https://www.regitra.lt/wp-'
                 'content/uploads/failai/Atviri_TP_parko_duomenys.zip">Atviri įregistruotų kelių '
                 'transporto priemonių parko duomenys (2026-07-03)* (zip)</a>')
    check("fleet link + date", fl.find_fleet(open_page) ==
          ("https://www.regitra.lt/wp-content/uploads/failai/Atviri_TP_parko_duomenys.zip",
           "2026-07-03"))


# ── split tiers ────────────────────────────────────────────────────────────

def test_split():
    store = {"snapshot": {"label": "2026-07-03"},
             "months": {"2026-05|new": {"PHEV": 50, "HEV": 150, "UNK": 3},
                        "2026-05|used": {"PHEV": 10, "HEV": 5, "UNK": 9}}}
    acea = {"source": "ACEA", "PHEV": "543.0", "HEV": "2797.0"}
    p, h, note, prov = fl.split_hybrids("2026-05", "new", 3330, acea, store, {})
    check("tier 1 from an ACEA row", (p, h, prov) == (541, 2789, False) and
          "ACEA PHEV 543 / HEV 2797" in note)
    regitra = {"source": "Regitra", "notes": "Regitra table 5; PHEV/HEV split from ACEA "
                                              "PHEV 543 / HEV 2797"}
    check("tier 1 kept from our own note",
          fl.split_hybrids("2026-05", "new", 3330, regitra, store, {})[:2] == (541, 2789))
    p, h, note, prov = fl.split_hybrids("2026-05", "new", 400, None, store, {})
    check("tier 2 from the snapshot", (p, h, prov) == (100, 300, False) and "OVC 50" in note)
    thin = {"months": {"2026-05|new": {"PHEV": 10, "HEV": 5}}}
    check("tier 2 ignored below the minimum base",
          fl.split_hybrids("2026-05", "new", 100, None, thin, {"2026-04": (1, 3)})[3] is True)
    check("used: every hybrid in HEV, no PHEV (no counted split)",
          fl.split_hybrids("2026-05", "used", 100, None, store, {"2026-04": (1, 3)})
          == (None, 100, fl.USED_HYBRID_NOTE, False))
    check("used: an ACEA-looking row does not split it",
          fl.split_hybrids("2026-05", "used", 100, acea, store, {})[:2] == (None, 100))
    check("used: no hybrids", fl.split_hybrids("2026-05", "used", 0, None, {}, {})[:2] == (None, 0))
    done = {"2026-02": (10, 90), "2026-03": (20, 80), "2026-04": (30, 70), "2025-12": (99, 1)}
    p, h, note, prov = fl.split_hybrids("2026-08", "new", 1000, None, store, done)
    check("tier 3 trailing three months", (p, h, prov) == (200, 800, True) and
          note.startswith("provisional"))
    check("no hybrids", fl.split_hybrids("2026-08", "new", 0, None, {}, {})[:2] == (0, 0))
    try:
        fl.split_hybrids("2026-08", "new", 10, None, {}, {})
        check("no base at all raises NoSplit", False)
    except fl.NoSplit:
        check("no base at all raises NoSplit", True)


# ── register snapshot ──────────────────────────────────────────────────────

def test_fleet():
    hdr = ("MARKE,KOMERCINIS_PAV,KATEGORIJA_KLASE,DEGALAI,HIBRIDINES_TP_KATEGORIJA,"
           "PIRM_REG_DATA,PIRM_REG_DATA_LT\n")
    rows = [
        'TOYOTA,TOYOTA COROLLA,M1,Benzinas/Elektra,NOVC-HEV,2026-05-02,2026-05-02',
        '"VOLKSWAGEN. VW",TIGUAN,M1,Benzinas/Elektra,OVC-HEV,2026-05-03,2026-05-03',
        'TESLA,MODEL Y,M1,Elektra,,2026-05-04,2026-05-04',
        'AUDI,A4,M1,Benzinas/Elektra,UNK,2019-01-01,2026-05-05',     # used import
        'MAN,TGX,N3,Dyzelinas,,2026-05-01,2026-05-01',               # not M1
        'SKODA,OCTAVIA,M1,Dyzelinas,,2026-06-27,2026-06-27',
    ]
    blob = io.BytesIO()
    with zipfile.ZipFile(blob, "w") as z:
        z.writestr("Atviri_TP_parko_duomenys.csv", "﻿" + hdr + "\n".join(rows) + "\n")
    stream, stamp = fl.open_fleet(blob.getvalue())
    split, units, newest = fl.scan_fleet(stream, "2026-01")
    check("snapshot split new", split[("2026-05", "new")] == {"HEV": 1, "PHEV": 1})
    check("snapshot split used UNK", split[("2026-05", "used")] == {"UNK": 1})
    check("snapshot newest date", newest == "2026-06-27")
    check("brand cleaned", ("2026-05", "PHEV", "VOLKSWAGEN", "TIGUAN") in units["new"])
    check("model brand prefix stripped", ("2026-05", "HEV", "TOYOTA", "COROLLA") in units["new"])
    check("used hybrid without category ranked as the combined HEV class",
          ("2026-05", "HEV", "AUDI", "A4") in units["used"])
    check("covered months", fl.covered_months("2026-06-27") == "2026-05" and
          fl.covered_months("2026-01-02") == "2025-12")
    store = fl.build_store(split, newest, "2026-07-03", stamp)
    check("store keeps covered months only", set(store["months"]) == {"2026-05|new", "2026-05|used"})
    try:
        fl.scan_fleet(io.StringIO("MARKE,DEGALAI\nX,Y\n"), "2026-01")
        check("schema drift aborts", False)
    except ValueError:
        check("schema drift aborts", True)


# ── upsert ─────────────────────────────────────────────────────────────────

def test_upsert():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "x.csv"
        head = ",".join(fl.CSV_COLUMNS)
        path.write_bytes((head + "\r\n"
                          "2023-12,monthly,Whole,ACEA,1.0,2.0,3.0,4.0,5.0,6.0,21.0,\r\n"
                          "2024-01,monthly,Whole,ACEA,1.0,2.0,3.0,4.0,5.0,6.0,21.0,\r\n"
                          "2024-02,monthly,Whole,Submit-Data,1.0,2.0,3.0,4.0,5.0,6.0,21.0,\r\n"
                          ).encode())
        c = {"BEV": 2, "PHEV": 2, "HEV": 3, "PETROL": 4, "DIESEL": 5, "OTHERS": 6, "TOTAL": 22}
        ups = {(p, "Whole"): fl.render_line(p, "Whole", c, fl.SOURCE, "n; x")
               for p in ("2024-01", "2024-02", "2024-03")}
        st = fl.upsert_lines(path, ups, force=False)
        text = path.read_bytes().decode()
        check("upsert stats", st == {"added": 1, "updated": 1, "unchanged": 0, "skipped": 1})
        check("CRLF kept", text.count("\r\n") == 5 and "\n\n" not in text)
        check("untouched line byte-identical",
              "2023-12,monthly,Whole,ACEA,1.0,2.0,3.0,4.0,5.0,6.0,21.0,\r\n" in text)
        check("foreign source kept", "2024-02,monthly,Whole,Submit-Data" in text)
        check("ACEA replaced, notes quoted",
              '2024-01,monthly,Whole,Regitra,2.0,2.0,3.0,4.0,5.0,6.0,22.0,n; x' in text)
        check("insert in order", text.strip().splitlines()[-1].startswith("2024-03"))

        used = Path(d) / "used.csv"
        cols = fl.csv_columns("Used")
        check("Used header has no PHEV", "PHEV" not in cols and cols[4:6] == ["BEV", "HEV"])
        u = {"BEV": 2, "PHEV": None, "HEV": 5, "PETROL": 4, "DIESEL": 5, "OTHERS": 6, "TOTAL": 22}
        line = fl.render_line("2024-01", "Used", u, fl.SOURCE, "n")
        check("Used line without PHEV", line == "2024-01,monthly,Used,Regitra,2.0,5.0,4.0,5.0,6.0,22.0,n")
        st = fl.upsert_lines(used, {("2024-01", "Used"): line}, force=False, columns=cols)
        check("Used file created with its own header",
              st["added"] == 1 and used.read_text().splitlines()[0] == ",".join(cols))
        try:
            fl.upsert_lines(path, {("2024-04", "Used"): line}, force=False, columns=cols)
            check("header mismatch aborts", False)
        except SystemExit:
            check("header mismatch aborts", True)


def test_display_names():
    # Real commercial names from the 2026-07-03 register snapshot.
    cases = [("VOLKSWAGEN. VW", "ID.4 PRO 4MOTION 210KW", "VOLKSWAGEN", "ID.4"),
             ("VOLKSWAGEN. VW", "ID. BUZZ PRO LR 210 KW", "VOLKSWAGEN", "ID. BUZZ"),
             ("TOYOTA", "TOYOTA YARIS CROSS", "TOYOTA", "YARIS CROSS"),
             ("HYUNDAI", "TUCSON. ix35", "HYUNDAI", "TUCSON"),
             ("AUDI", "Q5 220KW TFSI E", "AUDI", "Q5"),
             ("LEXUS", "LEXUS NX450H+", "LEXUS", "NX"),
             ("MERCEDES-BENZ", "GLC 200 4MATIC", "MERCEDES-BENZ", "GLC"),
             ("SKODA", "ELROQ 85", "SKODA", "ELROQ"),
             ("MG", "MG HS HYBRID+", "MG", "HS"),
             ("VOLVO", "V60 PLUG IN", "VOLVO", "V60"),
             ("BYD", "BYD SEAL U DM-I", "BYD", "SEAL U"),
             ("LYNK&CO", "LYNK & CO 08", "LYNK & CO", "08")]
    for marke, name, brand, model in cases:
        b = fl.display_brand(marke)
        check(f"brand {marke}", b == brand, b)
        check(f"model {name}", fl.display_model(b, name) == model, fl.display_model(b, name))


if __name__ == "__main__":
    for t in (test_fuel_class, test_fuel_table, test_totals_table, test_find_links,
              test_split, test_fleet, test_upsert, test_display_names):
        t()
    print(f"\n{'FAILED: ' + ', '.join(FAILS) if FAILS else 'all tests passed'}")
    sys.exit(1 if FAILS else 0)
