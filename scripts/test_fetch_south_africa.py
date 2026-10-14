#!/usr/bin/env python3
"""Offline tests for scripts/fetch_south_africa.py (no network).

    python scripts/test_fetch_south_africa.py

Covers: both NEV-table header layouts naamsa has used ("2020 2021 …",
"FY2020 …", "Year 2020 …" with the quarter labels on the same line), the
section-7 sales sentence, the column-sum check, the PHEV/HEV row-swap repair
(the Q4-2025 review's defect) and its tolerance, the middle-month periods,
ICE = TOTAL − NEV, the line-level upsert (foreign rows kept, restatements of
our own rows applied), the self-throttle's file-name parser and the
completeness guard.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_south_africa as f  # noqa: E402

SALES = """
   2026 Second quarter aggregate industry new passenger car sales at 109,236 units recorded an
   increase of 14,913 units, or a gain of 15,8% compared to the 94,323 new passenger cars sold during
   the corresponding quarter of 2025. Aggregate industry commercial vehicle sales during the second
   quarter of 2026, at 43,883 units, recorded an increase of 3,185 units, or a gain of 7,8% compared to
   the 40,698 units sold during the second quarter of 2026.
"""
TABLE_A = """
                              Year     Year     Year     Year     Year     Year
                                                                                    Q2:2025    Q2:2026
                              2020     2021     2022     2023     2024     2025

     Traditional hybrid        155      627     4,070    6,485   13,616    12,818    2,834      3,912
     Plug-in hybrid            77       51       122     368       738     2,810      547       3,346
     Electric                  92       218      502     929      1,257    1,088      294       1,353
     Total NEVs                324      896     4,694   7,782    15,611   16,716     3,675      8,611
"""
TABLE_FY = """
                                  FY2020           FY2021        FY2022         FY2023          FY2024          Q1:2024      Q1:2025

    Plug-in hybrid                           77           51            122           368              738            141        241
    Traditional hybrid                     155          627          4,070          6,485            13,616          2,587      2,970
    Electric                                 92         218             502           929             1,257           330        276
    Total NEVs                             324          896          4,694         7,782             15,611          3,058      3,487
"""
SALES_Q1_25 = SALES.replace("2026 Second", "2025 First").replace("109,236", "101,776") \
    .replace("94,323", "84,775").replace("43,883", "42,256").replace("40,698", "45,960")

fails = 0


def check(cond, msg):
    global fails
    if not cond:
        fails += 1
        print("FAIL:", msg)


def test_parse_layout_a():
    r = f.parse_review(SALES + TABLE_A)
    check(r["quarter"] == (2026, 2), r["quarter"])
    check(r["totals"][(2026, 2)] == 109236 + 43883, r["totals"])
    check(r["totals"][(2025, 2)] == 94323 + 40698, r["totals"])
    check(r["nev"][(2026, 2)] == {"BEV": 1353, "PHEV": 3346, "HEV": 3912}, r["nev"])
    check(r["nev"][(2025, 2)] == {"BEV": 294, "PHEV": 547, "HEV": 2834}, r["nev"])
    check(sorted(r["annual"]) == [2020, 2021, 2022, 2023, 2024, 2025], r["annual"])
    check(r["annual"][2025]["PHEV"] == 2810, r["annual"])


def test_parse_layout_fy():
    r = f.parse_review(SALES_Q1_25 + TABLE_FY)
    check(r["quarter"] == (2025, 1), r["quarter"])
    check(sorted(r["annual"]) == [2020, 2021, 2022, 2023, 2024], r["annual"])
    check(r["nev"][(2024, 1)] == {"BEV": 330, "PHEV": 141, "HEV": 2587}, r["nev"])


def test_column_sum_guard():
    bad = TABLE_A.replace("3,675      8,611", "3,675      8,612")
    try:
        f.parse_review(SALES + bad)
        check(False, "column-sum mismatch not caught")
    except ValueError:
        pass


def test_missing_sales_sentence():
    try:
        f.parse_review(TABLE_A)
        check(False, "missing sales sentence not caught")
    except ValueError:
        pass


def test_swap_repair():
    q = {(2025, 1): {"BEV": 276, "PHEV": 241, "HEV": 2970},
         (2025, 2): {"BEV": 294, "PHEV": 547, "HEV": 2834},
         (2025, 3): {"BEV": 232, "PHEV": 996, "HEV": 3559},
         (2025, 4): {"BEV": 286, "PHEV": 3452, "HEV": 1026}}   # as printed in Q4-2025
    log = []
    f.reconcile(q, {2025: {"BEV": 1088, "PHEV": 2810, "HEV": 12818}}, log)
    check(q[(2025, 4)] == {"BEV": 286, "PHEV": 1026, "HEV": 3452}, q[(2025, 4)])
    check(any("swapped back" in l for l in log), log)


def test_no_swap_when_consistent():
    q = {(2024, k): {"BEV": 1, "PHEV": 2, "HEV": 3} for k in (1, 2, 3, 4)}
    log = []
    f.reconcile(q, {2024: {"BEV": 4, "PHEV": 8, "HEV": 12}}, log)
    check(q[(2024, 4)] == {"BEV": 1, "PHEV": 2, "HEV": 3} and not log, (q, log))


def test_unfixable_gap_is_logged_not_changed():
    q = {(2024, k): {"BEV": 100, "PHEV": 200, "HEV": 300} for k in (1, 2, 3, 4)}
    log = []
    f.reconcile(q, {2024: {"BEV": 400, "PHEV": 900, "HEV": 1200}}, log)
    check(q[(2024, 1)]["PHEV"] == 200 and any("kept as published" in l for l in log), log)


def test_build_rows_newest_wins_and_period():
    old = f.parse_review(SALES_Q1_25 + TABLE_FY)
    old["nev"][(2025, 2)] = {"BEV": 1, "PHEV": 1, "HEV": 1}   # an older, superseded value
    old["totals"][(2025, 2)] = 1
    new = f.parse_review(SALES + TABLE_A)
    rows = f.build_rows([old, new], [])
    check(set(rows) >= {"2024-02", "2025-02", "2025-05", "2026-05"}, sorted(rows))
    check(rows["2025-05"][1]["BEV"] == 294, rows["2025-05"])
    c = f.counts_of(rows["2026-05"][1])
    check(c["ICE"] == 153119 - 1353 - 3346 - 3912 and c["TOTAL"] == 153119, c)


def test_period_of():
    check([f.period_of(2026, q) for q in (1, 2, 3, 4)] ==
          ["2026-02", "2026-05", "2026-08", "2026-11"], "middle months")


def test_quarter_from_name():
    cases = {
        "https://x/20260820-naamsa-2nd-Quarter-2026-Review-of-Business-Conditions.pdf": (2026, 2),
        "https://x/20260217-naamsa-4th-Quarter-2025-Review-of-Business-Conditions.pdf": (2025, 4),
        "https://x/20251119-naamsa-Quarter-3-2025-Review-of-Business-Conditions.pdf": (2025, 3),
        "https://x/20250220-naamsa-Q4-Review-of-Business-Conditions-2024.pdf": (2024, 4),
        "https://x/20240521-naamsa-Q1-2024-Review-of-Business-Conditions-2024.pdf": (2024, 1),
        "https://x/20260527-SIGNED-naamsa-1st-Quarter-2026-Review-of-Business-Conditions.pdf": (2026, 1),
    }
    for name, want in cases.items():
        check(f.quarter_from_name(name) == want, (name, f.quarter_from_name(name)))


def test_upsert():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.csv"
        hdr = ",".join(f.CSV_COLUMNS)
        foreign = "2025-02,quarterly,Whole,hand,1,1,1,1,4,"
        own = "2025-05,quarterly,Whole,naamsa.net,1,1,1,1,4,"
        p.write_text(f"{hdr}\n{foreign}\n{own}\n", encoding="utf-8")
        v = {"BEV": 2, "PHEV": 2, "HEV": 2, "TOTAL": 10}
        upd = {per: f.render_line(per, "quarterly", v, "") for per in ("2025-02", "2025-05", "2025-08")}
        st = f.upsert_lines(p, upd, force=False)
        check(st["skipped"] == ["2025-02"] and st["updated"] == ["2025-05"]
              and st["added"] == ["2025-08"], st)
        text = p.read_text(encoding="utf-8")
        check(foreign in text, "foreign row must stay byte-identical")
        check("2025-05,quarterly,Whole,naamsa.net,2,2,2,4,10," in text, text)
        st = f.upsert_lines(p, upd, force=True)
        check(st["updated"] == ["2025-02"], st)


def test_completeness_guard():
    rows = {"2025-05": ("quarterly", {"TOTAL": 100000}, ""),
            "2026-05": ("quarterly", {"TOTAL": 50000}, "")}
    try:
        f.completeness(rows, "2026-05", [], force=False)
        check(False, "completeness guard did not fire")
    except SystemExit:
        pass
    f.completeness(rows, "2026-05", [], force=True)


def test_bootstrap_rows_sum():
    for p, (iv, v, note) in f.BOOTSTRAP_ROWS.items():
        c = f.counts_of(v)
        check(c["ICE"] > 0 and iv == "yearly" and p.endswith("-06"), (p, c))
        check("not M1" in note, note)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    if fails:
        print(f"{fails} failure(s)")
        sys.exit(1)
    print("all South Africa fetcher tests passed")
