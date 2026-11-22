#!/usr/bin/env python3
"""PROPOSAL, not run: petrol/diesel for Denmark's 2014-2017 Whole rows from BIL51.

data/Denmark.csv's 48 rows 2014-01 .. 2017-12 came from the maintainer's
sheet with BEV, PHEV, OTHERS and TOTAL only; PETROL and DIESEL are blank.
Statistics Denmark's StatBank table BIL51 ("New registrations of passenger
cars by ownership, propellant and time", 2011M01 on, same public API as
BIL53) has the same months with the full propellant split. Its TOTAL, BEV
(Electricity) and PHEV (Hybrid/petrol + Hybrid/diesel, the plug-ins; they
equal BIL53's Pluginhybrid in every month from 2018-01) match all 48 rows
exactly.

This writes BIL51's petrol and diesel into those rows when, and only when,
both cells are blank and BIL51's TOTAL / BEV / PHEV equal the row's. TOTAL,
BEV, PHEV and OTHERS are not touched. OTHERS stays the sheet's, which is a
few cars below BIL51's in 22 of the 48 months (largest gap 28 cars,
2017-09), so those rows sum up to 28 cars short of TOTAL - inside
build_series.py's 3% reconcile tolerance. Each written row says so in notes.

Why it matters: denmark_hev.ready() blocks the HEV split while these rows
have no combustion split (build_series.py would drop them once any row has
HEV). Run only with the owner's yes:

    python scripts/backfill_denmark_bil51.py            # dry run, prints the diff
    python scripts/backfill_denmark_bil51.py --write    # line-level write
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "Denmark.csv"
API_URL = "https://api.statbank.dk/v1/data"
OTHER_CODES = ("20215", "20220", "20230", "20231", "20256", "20258")
NOTE = "PETROL/DIESEL api.statbank.dk (BIL51), filled {day}"


def fetch_bil51() -> dict:
    body = {"table": "BIL51", "format": "JSONSTAT", "lang": "en",
            "variables": [{"code": "EJER", "values": ["1000"]},
                          {"code": "DRIV", "values": ["*"]},
                          {"code": "Tid", "values": ["*"]}]}
    r = requests.post(API_URL, json=body, timeout=60)
    r.raise_for_status()
    return r.json()["dataset"]


def parse_bil51(ds: dict) -> dict[str, dict[str, float]]:
    """JSON-stat v1 -> {period: {TOTAL, BEV, PHEV, PETROL, DIESEL, OTHERS}}."""
    dim = ds["dimension"]
    order, sizes, values = dim["id"], dim["size"], ds["value"]
    strides, stride = [], 1
    for sz in reversed(sizes):
        strides.insert(0, stride)
        stride *= sz
    s_driv, s_tid = strides[order.index("DRIV")], strides[order.index("Tid")]
    driv = dim["DRIV"]["category"]["index"]
    out = {}
    for tid, ti in dim["Tid"]["category"]["index"].items():
        def g(code):
            return float(values[s_driv * driv[code] + s_tid * ti] or 0) if code in driv else 0.0
        out[f"{tid[:4]}-{tid[5:7]}"] = {
            "TOTAL": g("20200"), "BEV": g("20225"),
            "PHEV": g("20233") + g("20234"),
            "PETROL": g("20205"), "DIESEL": g("20210"),
            "OTHERS": sum(g(c) for c in OTHER_CODES),
        }
    return out


def plan(csv_path: Path, bil51: dict) -> dict[str, dict]:
    """{period: {"PETROL", "DIESEL", "gap"}} for rows that may be filled."""
    todo = {}
    with open(csv_path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["variant"] != "Whole" or r["period"] >= "2018-01":
                continue
            if (r.get("PETROL") or "").strip() or (r.get("DIESEL") or "").strip():
                continue
            b = bil51.get(r["period"])
            if b is None or any(abs(float(r[k] or 0) - b[k]) > 0.5
                                for k in ("TOTAL", "BEV", "PHEV")):
                print(f"  {r['period']}: BIL51 does not match TOTAL/BEV/PHEV — left blank")
                continue
            gap = float(r["TOTAL"]) - sum(float(r[k] or 0) for k in ("BEV", "PHEV", "OTHERS")) \
                - b["PETROL"] - b["DIESEL"]
            todo[r["period"]] = {"PETROL": b["PETROL"], "DIESEL": b["DIESEL"], "gap": gap}
    return todo


def write(csv_path: Path, todo: dict[str, dict], day: str) -> None:
    lines = csv_path.read_text(encoding="utf-8").splitlines(keepends=True)
    header = next(csv.reader([lines[0]]))
    out = [lines[0]]
    for line in lines[1:]:
        rec = dict(zip(header, next(csv.reader([line]))))
        upd = todo.get(rec["period"]) if rec["variant"] == "Whole" else None
        if upd is None:
            out.append(line)
            continue
        rec["PETROL"], rec["DIESEL"] = f"{upd['PETROL']:.1f}", f"{upd['DIESEL']:.1f}"
        extra = NOTE.format(day=day)
        rec["notes"] = f"{rec['notes']}; {extra}" if rec.get("notes") else extra
        buf = io.StringIO()
        csv.writer(buf, lineterminator="\n").writerow([rec.get(h, "") for h in header])
        out.append(buf.getvalue())
    csv_path.write_text("".join(out), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", type=Path, default=CSV_PATH)
    ap.add_argument("--write", action="store_true", help="write (default: dry run)")
    args = ap.parse_args()
    todo = plan(args.csv, parse_bil51(fetch_bil51()))
    for p, u in sorted(todo.items()):
        short = "" if abs(u["gap"]) < 0.5 else f"  (row {u['gap']:.0f} short of TOTAL: OTHERS)"
        print(f"  {p}: PETROL {u['PETROL']:.0f}, DIESEL {u['DIESEL']:.0f}{short}")
    print(f"{len(todo)} rows {'written' if args.write else 'would be written (dry run)'}")
    if args.write and todo:
        write(args.csv, todo, date.today().isoformat())
    return 0


if __name__ == "__main__":
    sys.exit(main())
