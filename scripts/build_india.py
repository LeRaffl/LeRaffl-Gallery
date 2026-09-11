#!/usr/bin/env python3
"""
India (VAHAN) builder — turns the hand-pulled raw dashboard exports in
``data/raw/india/`` into the gallery series ``data/India.csv``.

Unlike most countries India has no reachable API (see ``fetch_india.py`` —
VAHAN resets foreign connections), so the maintainer exports the VAHAN4
dashboard "Fuel × Month Wise" table to Excel by hand, one file per calendar
year, filtered to the passenger-car (EU M1) vehicle classes. This script is
the deterministic other half: it reads those workbooks and upserts them into
``data/India.csv``.

The exact dashboard recipe (which vehicle classes, which filters) lives in
``data/raw/india/README.md`` so the pull is reproducible. Keep the two in sync.

Design notes
------------
* **Fuel mapping** collapses VAHAN's ~20 fuel labels onto the gallery fuel
  columns via an ordered set of rules (``FUEL_RULES``). Order matters: the
  electrified signal (PHEV → BEV → HEV) wins over the alt-fuel signal
  (LPG/CNG) which wins over the base fuel (DIESEL/PETROL). So
  ``PETROL(E20)/HYBRID/CNG`` is HEV, ``PETROL/CNG`` is CNG, ``PETROL(E20)`` is
  PETROL. See the table in the README.
* **Current (incomplete) month is dropped.** VAHAN updates daily, so the
  running month is a fraction of a month and would read as a cliff in the
  series (and poison the TTM window). We only keep months strictly before the
  current calendar month — the same "one month back" rule France/Chile/China
  use. Re-running after month-end picks the month up automatically.
* **Recent months are provisional.** VAHAN keeps backfilling the last couple of
  completed months for weeks as RTOs enter data late. Those rows are flagged in
  ``notes`` and converge upward on the next re-pull (the upsert overwrites the
  same ``(period, variant)`` key).
* **Monthly TOTAL is computed** as the sum of every fuel cell in that month —
  the workbook's own ``TOTAL`` column is a per-fuel *annual* sum (wrong axis)
  and is ignored.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import os
import re
import sys

import openpyxl

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
RAW_DIR = os.path.join(REPO, "data", "raw", "india")
OUT_CSV = os.path.join(REPO, "data", "India.csv")

VARIANT = "Whole"
SOURCE = ("vahan.parivahan.gov.in (VAHAN4 dashboard, Fuel x Month Wise; "
          "Vehicle Class = MOTOR CAR + MOTOR CAB + LUXURY CAB = EU M1)")

# Number of trailing kept months flagged provisional (VAHAN daily backfill).
PROVISIONAL_TAIL = 2
PROVISIONAL_NOTE = "provisional (VAHAN daily backfill; revised upward on re-pull)"

# Gallery fuel columns India actually uses, in canonical schema order.
COLUMNS = ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "CNG", "LPG", "FLEXFUEL", "OTHERS"]

# Ordered (predicate on UPPERCASED label) -> target column. First match wins.
def _has(*subs):
    return lambda s: any(x in s for x in subs)

FUEL_RULES = [
    (_has("PLUG-IN HYBRID"),            "PHEV"),   # PLUG-IN HYBRID EV
    (_has("PURE EV", "ELECTRIC(BOV)"),  "BEV"),    # both battery-only labels
    (_has("HYBRID"),                    "HEV"),    # STRONG HYBRID EV, */HYBRID, DIESEL/HYBRID
    (_has("LPG"),                       "LPG"),    # LPG ONLY, PETROL/LPG, PETROL(E20)/LPG
    (_has("CNG"),                       "CNG"),    # CNG ONLY, PETROL/CNG, PETROL(E20)/CNG
    (_has("FLEX-FUEL", "ETHANOL"),      "FLEXFUEL"),
    (_has("DIESEL"),                    "DIESEL"),
    (_has("PETROL"),                    "PETROL"),
    # LNG, NOT APPLICABLE, SOLAR, FUEL CELL HYDROGEN, PETROL/METHANOL -> OTHERS
]

MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)}


def map_fuel(label: str) -> str:
    s = label.strip().upper()
    for pred, col in FUEL_RULES:
        if pred(s):
            return col
    return "OTHERS"


def parse_int(cell) -> int:
    if cell is None:
        return 0
    if isinstance(cell, (int, float)):
        return int(round(cell))
    s = str(cell).strip().replace(",", "")
    if s in ("", "-"):
        return 0
    return int(round(float(s)))


def year_from_title(ws) -> int | None:
    for row in ws.iter_rows(min_row=1, max_row=3, values_only=True):
        for c in row:
            if c and isinstance(c, str):
                m = re.search(r"\((\d{4})\)", c)
                if m:
                    return int(m.group(1))
    return None


def parse_workbook(path: str) -> dict[tuple[int, int], dict[str, int]]:
    """Return {(year, month): {column: count}} summed across mapped fuels."""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    year = year_from_title(ws)
    if year is None:
        raise SystemExit(f"{path}: could not find (YYYY) in the title rows")

    rows = list(ws.iter_rows(values_only=True))
    # month header row = the one containing 'JAN'
    hdr_idx = next((i for i, r in enumerate(rows)
                    if r and any(isinstance(c, str) and c.strip().upper() == "JAN" for c in r)), None)
    if hdr_idx is None:
        raise SystemExit(f"{path}: no month header row (JAN...) found")
    header = rows[hdr_idx]
    col_month = {ci: MONTHS[c.strip().upper()] for ci, c in enumerate(header)
                 if isinstance(c, str) and c.strip().upper() in MONTHS}

    out: dict[tuple[int, int], dict[str, int]] = {}
    for r in rows[hdr_idx + 1:]:
        if not r or len(r) < 3:
            continue
        label = r[1]
        if not isinstance(label, str) or not label.strip():
            continue
        if label.strip().upper() in ("FUEL", "TOTAL", "S NO"):
            continue
        col = map_fuel(label)
        for ci, month in col_month.items():
            val = parse_int(r[ci]) if ci < len(r) else 0
            if val == 0:
                continue
            out.setdefault((year, month), {})[col] = out.setdefault((year, month), {}).get(col, 0) + val
    return out


def load_existing(path: str) -> dict[tuple[str, str], list[str]]:
    """Existing rows keyed on (period, variant) -> raw split fields."""
    if not os.path.exists(path):
        return {}
    rows: dict[tuple[str, str], list[str]] = {}
    with open(path, encoding="utf-8") as f:
        header = f.readline()  # noqa: F841 (kept implicitly; we always rewrite header)
        for line in f:
            fields = _split_csv(line.rstrip("\n"))
            if len(fields) < 3:
                continue
            rows[(fields[0], fields[2])] = fields
    return rows


def _split_csv(line: str) -> list[str]:
    out, cur, q = [], [], False
    for ch in line:
        if ch == '"':
            q = not q
        elif ch == "," and not q:
            out.append("".join(cur)); cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def fmt(n: int) -> str:
    return f"{float(n):.1f}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=OUT_CSV)
    ap.add_argument("--asof", help="override 'today' as YYYY-MM-DD (testing)")
    args = ap.parse_args()

    today = dt.date.fromisoformat(args.asof) if args.asof else dt.date.today()
    cutoff = (today.year, today.month)  # drop this month and anything >=

    files = sorted(glob.glob(os.path.join(RAW_DIR, "*.xlsx")))
    if not files:
        raise SystemExit(f"no .xlsx in {RAW_DIR}")

    data: dict[tuple[int, int], dict[str, int]] = {}
    for path in files:
        for key, cols in parse_workbook(path).items():
            if key >= cutoff:
                continue  # incomplete current month (and any future stray)
            bucket = data.setdefault(key, {})
            for c, v in cols.items():
                bucket[c] = bucket.get(c, 0) + v

    periods = sorted(data)
    if not periods:
        raise SystemExit("no complete months to write")
    provisional = set(periods[-PROVISIONAL_TAIL:]) if len(periods) >= PROVISIONAL_TAIL else set(periods)

    header = ["period", "time_interval", "variant", "source", *COLUMNS, "TOTAL", "notes"]
    lines = [",".join(header)]
    for (y, m) in periods:
        cols = data[(y, m)]
        total = sum(cols.values())
        note = PROVISIONAL_NOTE if (y, m) in provisional else ""
        row = [
            f"{y:04d}-{m:02d}", "monthly", VARIANT, f'"{SOURCE}"',
            *[fmt(cols.get(c, 0)) for c in COLUMNS],
            fmt(total),
            note,
        ]
        lines.append(",".join(row))

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"wrote {args.out}: {len(periods)} months "
          f"{periods[0][0]}-{periods[0][1]:02d}..{periods[-1][0]}-{periods[-1][1]:02d} "
          f"(dropped >= {cutoff[0]}-{cutoff[1]:02d}; provisional tail={sorted(provisional)})",
          file=sys.stderr)


if __name__ == "__main__":
    main()
