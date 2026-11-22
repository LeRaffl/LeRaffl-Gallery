#!/usr/bin/env python3
"""One-time: HEV for Denmark's Whole rows 2022-01 .. latest ACEA month.

Statistics Denmark has no code for non-plug hybrids; scripts/denmark_hev.py
splits Statbank's petrol + diesel by ACEA's HEV:petrol:diesel shares from
the month ACEA publishes on. This fills the history the same way, from:

  2022-01 .. 2022-12   ACEA's quarterly fuel releases
                       (reference/acea_country_quarterly.csv): each month
                       gets its quarter's shares, an estimate
  2023-01 ..           ACEA's monthly releases
                       (reference/acea_denmark_hev.csv, written by
                       scripts/extract_acea_denmark.py): a month's own
                       shares, or a two-month span's where one release is
                       missing (an estimate)

Why 2022: ACEA's Danish HEV counts mild hybrids from 2022-Q1 on. That
quarter HEV jumps from 1,875 to 7,741 while HEV + petrol + diesel stays at
about 22,900, and diesel halves: hybrids were re-booked, the market did
not move. Before 2022 ACEA's figure is a different quantity, so 2014-2021
keep HEV blank (unknown) and their hybrids stay inside petrol/diesel.

TOTAL, BEV, PHEV and OTHERS stay Statbank's; HEV + PETROL + DIESEL equals
Statbank's petrol + diesel exactly, and Statbank's own petrol and diesel
stay in notes. A span is used only if ACEA's TOTAL (quarters: HEV + petrol
+ diesel) and BEV match Statbank's for the same months (the gates of
denmark_hev.py; quarters 3% on the pool). Rows that already have a split
are never touched. Line-level writes (AGENTS.md invariant 2).

    python scripts/backfill_denmark_hev.py            # dry run
    python scripts/backfill_denmark_hev.py --write
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import denmark_hev as dh  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
QUARTERLY = ROOT / "reference" / "acea_country_quarterly.csv"
MONTHLY = ROOT / "reference" / "acea_denmark_hev.csv"
POOL_TOLERANCE = 0.03


def quarter_months(q: str) -> list[str]:
    y, n = q.split("-Q")
    return [f"{y}-{3 * (int(n) - 1) + i:02d}" for i in (1, 2, 3)]


def span_months(lo: str, hi: str) -> list[str]:
    y, m = int(lo[:4]), int(lo[5:])
    out = []
    while f"{y}-{m:02d}" <= hi:
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def units(quarterly: Path = QUARTERLY, monthly: Path = MONTHLY) -> list[dict]:
    """[{months, label, basis, acea}] from 2022-01 on, oldest first."""
    out = []
    with open(quarterly, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["country"] != "Denmark" or not r["quarter"].startswith("2022-"):
                continue
            out.append({"months": quarter_months(r["quarter"]), "label": r["quarter"],
                        "basis": "quarter",
                        "acea": {k: float(r[k]) for k in ("BEV", "HEV", "PETROL", "DIESEL")}})
    with open(monthly, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            ms = span_months(r["from"], r["to"])
            out.append({"months": ms, "label": r["from"] if len(ms) == 1 else f"{r['from']}..{r['to']}",
                        "basis": r["basis"],
                        "acea": {k: float(r[k]) for k in ("BEV", "HEV", "PETROL", "DIESEL", "TOTAL")}})
    return sorted(out, key=lambda u: u["months"][0])


def gate(unit: dict, rows: dict[str, dict]) -> str | None:
    """None if ACEA's span is Statbank's months, else why not."""
    a = unit["acea"]
    sb = {k: sum(dh._f(rows[p], k) for p in unit["months"]) for k in ("TOTAL", "BEV")}
    sb_pool = sum(dh.pool(rows[p]) for p in unit["months"])
    if abs(a["BEV"] - sb["BEV"]) > max(5.0, dh.ACEA_BEV_TOLERANCE * sb["BEV"]):
        return f"BEV {a['BEV']:.0f} vs Statbank {sb['BEV']:.0f}"
    if "TOTAL" in a:
        if abs(a["TOTAL"] - sb["TOTAL"]) > dh.ACEA_TOTAL_TOLERANCE * sb["TOTAL"]:
            return f"TOTAL {a['TOTAL']:.0f} vs Statbank {sb['TOTAL']:.0f}"
    else:
        a_pool = a["HEV"] + a["PETROL"] + a["DIESEL"]
        if abs(a_pool - sb_pool) > POOL_TOLERANCE * sb_pool:
            return f"HEV+petrol+diesel {a_pool:.0f} vs Statbank petrol+diesel {sb_pool:.0f}"
    return None


def plan(csv_path: Path = dh.CSV_PATH, quarterly: Path = QUARTERLY,
         monthly: Path = MONTHLY) -> dict[str, dict]:
    """{period: {HEV, PETROL, DIESEL, notes}} for the rows to fill."""
    rows = dh.whole_rows(csv_path)
    todo: dict[str, dict] = {}
    for u in units(quarterly, monthly):
        if u["months"][0] < dh.HEV_FILL_FROM:
            continue
        missing = [p for p in u["months"] if p not in rows]
        if missing:
            print(f"  {u['label']}: no Statbank row for {', '.join(missing)} — skipped")
            continue
        why = gate(u, rows)
        if why:
            print(f"  {u['label']}: not merged ({why})")
            continue
        a = u["acea"]
        h, p, d = a["HEV"], a["PETROL"], a["DIESEL"]
        if h + p + d <= 0:
            continue
        for period in u["months"]:
            row = rows[period]
            if dh.split_kind(row) is not None or not dh._blank(row, "HEV"):
                continue                       # never over an existing split
            base = (dh.ACEA_NOTE if u["basis"] == "month"
                    else dh.HISTORY_NOTE.format(span=u["label"]))
            todo[period] = {**dh.split_pool(dh.pool(row), h / (h + p + d), d / (h + p + d)),
                            "notes": dh.note(base, row)}
    return todo


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", type=Path, default=dh.CSV_PATH)
    ap.add_argument("--write", action="store_true", help="write (default: dry run)")
    args = ap.parse_args()
    if not dh.ready(args.csv):
        return 1
    todo = plan(args.csv)
    for p, u in sorted(todo.items()):
        kind = "estimate" if u["notes"].startswith(dh.HISTORY_PREFIX) else "ACEA month"
        print(f"  {p}: HEV {u['HEV']:.0f}, PETROL {u['PETROL']:.0f}, DIESEL {u['DIESEL']:.0f} ({kind})")
    print(f"{len(todo)} rows {'written' if args.write else 'would be written (dry run)'}")
    if args.write and todo:
        dh.write_split(args.csv, todo)
        newest = dh.estimate_newest(args.csv)
        if newest:
            print(f"  newest month(s) {', '.join(newest)}: previous month's shares (estimate)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
