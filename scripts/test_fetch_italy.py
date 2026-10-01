#!/usr/bin/env python3
"""Regression tests for the UNRAE LCV (Vans) struttura parser in fetch_italy.py
and the history assembly in backfill_italy_vans.py.

Run with plain Python, no test framework and no network:

    python scripts/test_fetch_italy.py

The fixtures are pdftotext -layout output of real UNRAE PDFs, trimmed to the
title and the 'Per alimentazione' table: the combined July+August 2026 PDF
(monthly + YTD layout, with blank cells) and the April 2021 page (YTD-only
layout, compared against 2019 rather than 2020).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backfill_italy_vans as bf  # noqa: E402
import fetch_italy as fi  # noqa: E402

JUL_AUG_2026 = """\
                                                                                  IMMATRICOLAZIONI - Agosto 2026
                                                                                         Var. %                 quote %                                                  Var. %             quote %
                                                                 agosto                                                                   gennaio/agosto
                 Per alimentazione                                                       agosto                  agosto                                              gennaio/agosto      gennaio/agosto
                                                            2026 (°)         2025      2026/2025            2026 (°)    2025             2026 (°)             2025     2026/2025        2026 (°)    2025
Benzina                                                         281           422              -33,4            3,4        5,3             4.252             5.022             -15,3          3,6         4,0
Diesel                                                        6.402         6.452               -0,8           76,4       80,4            92.958           100.192              -7,2         78,0        80,3
Gpl                                                             105           195              -46,2            1,3        2,4             2.453             3.125             -21,5          2,1         2,5
Metano                                                            1             3              -66,7            0,0        0,0                17                47             -63,8          0,0         0,0
Ibridi elettrici (HEV)                                          880           611              +44,0           10,5        7,6            12.466             9.919             +25,7         10,5         8,0
                                     benzina+elettrica          599           427              +40,3            7,2        5,3             9.208             6.193             +48,7          7,7         5,0
                                       diesel+elettrica         281           184              +52,7            3,4        2,3             3.258             3.726             -12,6          2,7         3,0
Ibridi elettrici plug-in (PHEV+REx)                             118           110               +7,3            1,4        1,4             2.596               981            +164,6          2,2         0,8
                                     benzina+elettrica          117           110               +6,4            1,4        1,4             2.588               980            +164,1          2,2         0,8
                                       diesel+elettrica           1                                -            0,0        0,0                 8                 1            +700,0          0,0         0,0
Elettrici (BEV)                                                 589            232            +153,9            7,0        2,9             4.399             5.456             -19,4          3,7         4,4
Totale ECV (BEV+PHEV+REx)                                       707            342            +106,7            8,4        4,3             6.995             6.437              +8,7          5,9         5,2
totale                                                        8.376         8.025                +4,4         100,0      100,0          119.141            124.742              -4,5        100,0       100,0

                                                                                  IMMATRICOLAZIONI - Luglio 2026
                                                                                         Var. %                 quote %                                                 Var. %               quote %
                                                                  luglio                                                                  gennaio/luglio
                 Per alimentazione                                                        luglio                  luglio                                             gennaio/luglio       gennaio/luglio
                                                            2026 (°)         2025      2026/2025            2026 (°)     2025            2026 (°)             2025    2026/2025         2026 (°)     2025
Benzina                                                          654          768              -14,8            4,1        4,3             3.971             4.600             -13,7          3,6         3,9
Diesel                                                        12.213       13.829              -11,7           76,7       78,2            86.556            93.740              -7,7         78,1        80,3
Gpl                                                              229          639              -64,2            1,4        3,6             2.348             2.930             -19,9          2,1         2,5
Metano                                                             2                               -            0,0        0,0                16                44             -63,6          0,0         0,0
Ibridi elettrici (HEV)                                         1.727        1.294              +33,5           10,8        7,3            11.586             9.308             +24,5         10,5         8,0
                                     benzina+elettrica         1.280          832              +53,8            8,0        4,7             8.609             5.766             +49,3          7,8         4,9
                                       diesel+elettrica          447          462               -3,2            2,8        2,6             2.977             3.542             -16,0          2,7         3,0
Ibridi elettrici plug-in (PHEV+REx)                              315          242              +30,2            2,0        1,4             2.478               871            +184,5          2,2         0,7
                                     benzina+elettrica           314          242              +29,8            2,0        1,4             2.471               870            +184,0          2,2         0,7
                                       diesel+elettrica            1                               -            0,0        0,0                 7                 1            +600,0          0,0         0,0
Elettrici (BEV)                                                  781          919              -15,0            4,9        5,2             3.810             5.224             -27,1          3,4         4,5
Totale ECV (BEV+PHEV+REx)                                      1.096        1.161               -5,6            6,9        6,6             6.288             6.095              +3,2          5,7         5,2
totale                                                        15.921       17.691               -10,0         100,0      100,0          110.765            116.717               -5,1       100,0       100,0
"""

APR_2021 = """\
                                    IMMATRICOLAZIONI - Gennaio/Marzo 2021
                                                                                                   Var. %           quote %
                                                              gennaio/marzo
                 Per alimentazione                                                          gennaio/marzo        gennaio/marzo
                                                           2021 (°)           2019             2021/2020          2021 (°)         2019
Benzina                                                        1.451         2.421                     -40,1          3,2            5,2
Diesel                                                        39.558        40.544                      -2,4         86,4           87,9
Gpl                                                            1.052         1.032                      +1,9          2,3            2,2
Metano                                                           876         1.859                     -52,9          1,9            4,0
Ibridi elettrici (HEV)                                         2.410            38                   +6242,1          5,3            0,1
                                   benzina+elettrica           1.135            38                   +2886,8          2,5            0,1
                                     diesel+elettrica          1.275             0                         -          2,8            0,0
Ibridi elettrici plug-in (PHEV+REx)                               43             0                         -          0,1            0,0
                                   benzina+elettrica              43             0                         -          0,1            0,0
                                     diesel+elettrica              0             0                       0,0          0,0            0,0
Elettrici (BEV)                                                  405           227                     +78,4          0,9            0,5
Totale ECV (BEV+PHEV+REx)                                        448           227                     +97,4          1,0            0,5
totale                                                        45.795        46.121                      -0,7        100,0          100,0
"""

TOTALS_2026 = """\
mese                                 2026                 2025            var.%

gennaio                            14.276               15.070              -5,3
febbraio                           15.265               15.309              -0,3
luglio                             15.921               17.691             -10,0
agosto                              8.390                 8.025            +4,6
Totale                          119.152              124.742               -4,5
"""


def test_combined_bulletin_monthly_layout() -> None:
    tables = {t["month"]: t for t in fi.parse_lcv_struttura(JUL_AUG_2026)}
    assert sorted(tables) == [7, 8]
    jul = tables[7]
    assert (jul["year"], jul["cmp_year"]) == (2026, 2025)
    assert fi.lcv_to_cols(jul["month_cur"]) == {
        "BEV": 781, "PHEV": 315, "HEV": 1727, "PETROL": 654,
        "DIESEL": 12213, "OTHERS": 229 + 2, "TOTAL": 15921}
    # Blank Metano cell in the 2025 column is 0, and does not shift HEV/PHEV/BEV.
    assert jul["month_cmp"]["METANO"] == 0
    assert jul["month_cmp"]["BEV"] == 919 and jul["month_cmp"]["TOTAL"] == 17691
    assert jul["ytd_cur"]["TOTAL"] == 110765 and jul["ytd_cmp"]["METANO"] == 44
    assert tables[8]["month_cur"]["TOTAL"] == 8376


def test_ytd_only_layout_reads_comparison_year() -> None:
    (t,) = fi.parse_lcv_struttura(APR_2021)
    assert (t["year"], t["month"], t["cmp_year"]) == (2021, 3, 2019)   # not 2020
    assert t["month_cur"] is None and t["month_cmp"] is None
    assert t["ytd_cur"]["TOTAL"] == 45795 and t["ytd_cmp"]["BEV"] == 227


def test_column_sum_mismatch_raises() -> None:
    broken = JUL_AUG_2026.replace("1.727        1.294", "1.728        1.294")
    try:
        fi.parse_lcv_struttura(broken)
    except RuntimeError as e:
        assert "sum to" in str(e), e
    else:
        raise AssertionError("expected a sum mismatch")


def test_lcv_to_cols_keeps_missing_phev_empty() -> None:
    f = dict.fromkeys(fi.LCV_FUELS, 1) | {"PHEV": None, "H2": None, "TOTAL": 6}
    cols = fi.lcv_to_cols(f)
    assert cols["PHEV"] == "" and cols["OTHERS"] == 2
    fi.sanity_check(cols, "2018-01")


def test_sanity_check_rejects_negative() -> None:
    cols = {"BEV": -1, "PHEV": 0, "HEV": 0, "PETROL": 0, "DIESEL": 101, "OTHERS": 0, "TOTAL": 100}
    try:
        fi.sanity_check(cols, "2024-11")
    except RuntimeError as e:
        assert "negative" in str(e)
    else:
        raise AssertionError("expected a negative-count error")


def test_monthly_totals_table() -> None:
    t = bf.parse_monthly_totals(TOTALS_2026)
    assert t[(2026, 8)] == 8390 and t[(2025, 7)] == 17691 and (2026, 3) not in t


def _ytd_table(month_name: str, year: int, cur: dict, cmp_: dict) -> str:
    """A YTD-only table in the 2021 layout, counts right-aligned."""
    lines = [f"                                    IMMATRICOLAZIONI - Gennaio/{month_name} {year}",
             "                 Per alimentazione",
             f"                                                           {year} (°)           {year - 1}"]
    for label in cur:
        lines.append(f"{label:<52}{cur[label]:>14,}{cmp_[label]:>14,}".replace(",", "."))
    return "\n".join(lines) + "\n"


def _ytd(bev: int, diesel: int, gpl: int) -> dict:
    rows = {"Benzina": 10, "Diesel": diesel, "Gpl": gpl, "Metano": 1,
            "Ibridi elettrici (HEV)": 20, "Ibridi elettrici plug-in (PHEV+REx)": 3,
            "Elettrici (BEV)": bev}
    return rows | {"totale": sum(rows.values())}


def test_assemble_skips_misprinted_ytd() -> None:
    # UNRAE's own Jan-Oct 2024 table moved 1500 from Diesel to GPL; the
    # consolidated copy in next year's comparison column is right.
    sep, oct_cons, nov = _ytd(300, 9000, 400), _ytd(340, 10000, 450), _ytd(380, 11000, 500)
    oct_misprint = _ytd(340, 8500, 1950)
    later = _ytd(1, 1, 1)                     # 2025 values, irrelevant here
    texts = [
        _ytd_table("Settembre", 2024, sep, sep),
        _ytd_table("Ottobre", 2024, oct_misprint, oct_misprint),
        _ytd_table("Novembre", 2024, nov, nov),
        _ytd_table("Settembre", 2025, later, sep),
        _ytd_table("Ottobre", 2025, later, oct_cons),
        "mese   2025   2024   var.%\nottobre   1   1.090\nnovembre   1   1.090\nTotale  2  2\n",
    ]
    series = bf.assemble(texts)
    for period in ("2024-10", "2024-11"):
        f, note = series[period]
        assert (f["BEV"], f["DIESEL"], f["GPL"], f["TOTAL"]) == (40, 1000, 50, 1090), (period, f)
        assert note == bf.NOTE_YTD


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
