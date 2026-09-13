#!/usr/bin/env python3
"""Regression tests for scripts/fetch_southafrica.py (no network, no poppler).

Run:  python scripts/test_fetch_southafrica.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_southafrica as sa  # noqa: E402

Q2_2026_TABLE = """
   The following table reveals the diversity of drivetrain sales in the South African NEV landscape from
   2020 through to 2026 Q2

                              Year     Year     Year     Year     Year     Year
                                                                                    Q2:2025    Q2:2026
                              2020     2021     2022     2023     2024     2025

     Traditional hybrid        155      627     4,070    6,485   13,616    12,818    2,834      3,912

     Plug-in hybrid            77       51       122     368       738     2,810      547       3,346

     Electric                  92       218      502     929      1,257    1,088      294       1,353

     Total NEVs                324      896     4,694   7,782    15,611   16,716     3,675      8,611
"""

Q2_2026_PROSE = """
   2026 Second quarter aggregate industry new passenger car sales at 109,236 units recorded an
   increase of 14,913 units, or a gain of 15,8% compared to the 94,323 new passenger cars sold during
   the corresponding quarter of 2025. Aggregate industry commercial vehicle sales during the second
   quarter of 2026, at 43,883 units, recorded an increase of 3,185 units, or a gain of 7,8% compared to the
   40,698 units sold during the second quarter of 2026.
"""

Q1_2026_PROSE_LIGATURE = """
   2026 First quarter aggregate industry new passenger car sales at 114,482 units recorded an increase
   of 12,706 units. Aggregate industry commercial vehicle sales during the ;rst quarter of
   2026, at 47,464 units, recorded an increase of 5,108 units.
"""

INDUSTRY = """
INDUSTRY VEHICLE SALES, PRODUCTION, EXPORT AND IMPORT DATA : 2017 - 2027

                                            2017           2018           2019            2020           2021           2022          2023    2024       2025       2026       2027
CARS
TOTAL AGGREGATE MARKET                        557719         552221         536 486        380 065        464 322        529 335    531 557    516 103    597 338    656 000    702 000
"""


def test_classify():
    assert sa.classify_pdf(
        "https://naamsa.net/wp-content/uploads/2026/08/20260820-naamsa-2nd-Quarter-2026-Review-of-Business-Conditions.pdf"
    ) == "qbr"
    assert sa.classify_pdf(
        "https://naamsa.net/wp-content/uploads/2026/08/20260817-Industry-Vehicle-Sales-2017-2027-Actual-and-Projections-updated.pdf"
    ) == "industry"
    assert sa.classify_pdf(
        "https://naamsa.net/wp-content/uploads/2026/09/20260901-naamsa-August-2026-New-Vehicle-Sales-Media-Release.pdf"
    ) is None
    assert sa.classify_pdf(
        "https://naamsa.net/wp-content/uploads/2024/05/20240527-naamsa-CEO-Confidence-Index-1st-Quarter-2024-and-next-6-months.pdf"
    ) is None


def test_nev_table():
    rows = sa.parse_nev_table(Q2_2026_TABLE)
    assert rows["2020-06"]["BEV"] == 92 and rows["2020-06"]["time_interval"] == "yearly"
    assert rows["2025-06"]["HEV"] == 12818
    q2_25 = rows["2025-05"]
    assert q2_25["time_interval"] == "quarterly" and q2_25["BEV"] == 294
    q2_26 = rows["2026-05"]
    assert q2_26["PHEV"] == 3346 and q2_26["HEV"] == 3912 and q2_26["BEV"] == 1353
    assert sa.checksum_ok(q2_26)


def test_quarter_total():
    got = sa.parse_quarter_total(Q2_2026_PROSE)
    assert got == ("2026-05", 109236 + 43883), got
    got = sa.parse_quarter_total(Q1_2026_PROSE_LIGATURE)
    assert got == ("2026-02", 114482 + 47464), got


def test_industry_totals():
    # 2026/2027 are skipped as current-or-future (today is 2026).
    totals = sa.parse_industry_totals(INDUSTRY)
    assert totals[2020] == 380065
    assert totals[2025] == 597338
    assert 2026 not in totals
    assert 2027 not in totals


def test_build_rows_no_yearly_quarterly_overlap():
    nev = sa.parse_nev_table(Q2_2026_TABLE)
    qtot = {"2025-05": 134859, "2026-05": 153119}
    ytot = {2020: 380065, 2021: 464322, 2022: 529335, 2023: 531557,
            2024: 516103, 2025: 597338}
    rows = sa.build_rows(nev, qtot, ytot)
    assert "2020-06" in rows and rows["2020-06"]["time_interval"] == "yearly"
    assert "2023-06" in rows
    assert "2024-06" in rows  # no 2024 quarter in this fixture, keep the year
    assert "2025-06" not in rows  # quarterly series starts 2025-05
    assert "2025-05" in rows and rows["2025-05"]["TOTAL"] == 134859
    ice = 153119 - 1353 - 3346 - 3912
    assert rows["2026-05"]["ICE"] == ice
    assert rows["2026-05"]["notes"].startswith("2026 NEV coverage")


def test_empty_not_zero_passthrough():
    # ICE is a real remainder, not a dummy 0 petrol column.
    nev = sa.parse_nev_table(Q2_2026_TABLE)
    rows = sa.build_rows(nev, {"2026-05": 153119}, {})
    assert "PETROL" not in rows["2026-05"]
    assert rows["2026-05"]["ICE"] > 0


def test_repair_q4_phev_hev_swap():
    # Q4-2025 PDF prints PHEV/HEV quarter columns swapped.
    nev = {
        "2025-06": {"BEV": 1088, "PHEV": 2810, "HEV": 12818,
                    "NEV_TOTAL": 16716, "time_interval": "yearly"},
        "2025-11": {"BEV": 286, "PHEV": 3452, "HEV": 1026,
                    "NEV_TOTAL": 4764, "time_interval": "quarterly"},
    }
    sa.repair_swapped_quarter_hybrids(nev)
    assert nev["2025-11"]["PHEV"] == 1026
    assert nev["2025-11"]["HEV"] == 3452
    assert sa.checksum_ok(nev["2025-11"])


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"{len(tests)} tests passed")
