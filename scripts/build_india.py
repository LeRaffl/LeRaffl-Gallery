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
# Kept short: this string is the chart's on-image source line (see footnote length).
SOURCE_MONTHLY = "vahan.parivahan.gov.in (VAHAN4; M1: MOTOR CAR/CAB/LUXURY CAB)"
SOURCE_YEARLY = "vahan.parivahan.gov.in (VAHAN4 annual; M1: MOTOR CAR/CAB/LUXURY CAB)"

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


def year_from_title(rows) -> int | None:
    """Year from a '... For All State (YYYY)' title (the month-wise export)."""
    for r in rows[:4]:
        for c in (r or []):
            if isinstance(c, str):
                m = re.search(r"\((\d{4})\)", c)
                if m:
                    return int(m.group(1))
    return None


def find_year_column(rows) -> tuple[int | None, int | None]:
    """A bare 4-digit year used as a value-column header (the annual export:
    'Fuel Wise Calendar Year Data', title year is blank, the year sits in the
    single data column's header). Returns (year, column_index)."""
    for r in rows[:6]:
        for ci, c in enumerate(r or []):
            if c is not None and re.fullmatch(r"\s*\d{4}\s*", str(c)):
                return int(str(c).strip()), ci
    return None, None


def _sum_fuels(data_rows, value_ci: int) -> dict[str, int]:
    """Sum one value column across the fuel rows, mapped onto gallery columns."""
    cols: dict[str, int] = {}
    for r in data_rows:
        if not r or len(r) <= max(1, value_ci):
            continue
        label = r[1]
        if not isinstance(label, str) or not label.strip():
            continue
        if label.strip().upper() in ("FUEL", "TOTAL", "S NO"):
            continue
        val = parse_int(r[value_ci])
        if val:
            col = map_fuel(label)
            cols[col] = cols.get(col, 0) + val
    return cols


def parse_workbook(path: str) -> dict[tuple[int, int], tuple[str, dict[str, int]]]:
    """Return {(year, month): (interval, {column: count})}.

    Handles both VAHAN export shapes:
    * "Fuel Month Wise"        -> one column per month  (interval 'monthly').
    * "Fuel Wise Calendar Year" -> a single annual column headed by the year
      (interval 'yearly'), anchored mid-year (month 7) so period_to_year places
      it at the calendar year's centre of mass. Used for the older years that
      VAHAN only exposes as an annual total.
    """
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))

    hdr_idx = next((i for i, r in enumerate(rows)
                    if r and any(isinstance(c, str) and c.strip().upper() == "JAN" for c in r)), None)

    out: dict[tuple[int, int], tuple[str, dict[str, int]]] = {}
    if hdr_idx is not None:
        year = year_from_title(rows)
        if year is None:
            raise SystemExit(f"{path}: month-wise file but no (YYYY) in the title")
        header = rows[hdr_idx]
        col_month = {ci: MONTHS[c.strip().upper()] for ci, c in enumerate(header)
                     if isinstance(c, str) and c.strip().upper() in MONTHS}
        for ci, month in col_month.items():
            cols = _sum_fuels(rows[hdr_idx + 1:], ci)
            if cols:
                out[(year, month)] = ("monthly", cols)
    else:
        year, ci = find_year_column(rows)
        if year is None:
            raise SystemExit(f"{path}: neither a month header (JAN...) nor an annual year column found")
        yhdr = next(i for i, r in enumerate(rows)
                    if r and any(c is not None and str(c).strip() == str(year) for c in r))
        cols = _sum_fuels(rows[yhdr + 1:], ci)
        if cols:
            out[(year, 7)] = ("yearly", cols)
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

    # key (year, month) -> {"interval": str, "cols": {col: count}}
    data: dict[tuple[int, int], dict] = {}
    for path in files:
        for key, (interval, cols) in parse_workbook(path).items():
            if key >= cutoff:
                continue  # incomplete current month (and any future stray)
            bucket = data.setdefault(key, {"interval": interval, "cols": {}})
            bucket["interval"] = interval
            for c, v in cols.items():
                bucket["cols"][c] = bucket["cols"].get(c, 0) + v

    # A monthly year always wins over an annual total for the same year (should
    # a yearly file ever overlap a month-wise one).
    monthly_years = {y for (y, _m), e in data.items() if e["interval"] == "monthly"}
    for key in [k for k, e in data.items() if e["interval"] == "yearly" and k[0] in monthly_years]:
        del data[key]

    periods = sorted(data)
    if not periods:
        raise SystemExit("no complete periods to write")
    monthly_periods = [k for k in periods if data[k]["interval"] == "monthly"]
    provisional = set(monthly_periods[-PROVISIONAL_TAIL:])  # only the newest real months

    header = ["period", "time_interval", "variant", "source", *COLUMNS, "TOTAL", "notes"]
    lines = [",".join(header)]
    for (y, m) in periods:
        entry = data[(y, m)]
        interval, cols = entry["interval"], entry["cols"]
        total = sum(cols.values())
        source = SOURCE_MONTHLY if interval == "monthly" else SOURCE_YEARLY
        note = PROVISIONAL_NOTE if (y, m) in provisional else ""
        row = [
            f"{y:04d}-{m:02d}", interval, VARIANT, f'"{source}"',
            *[fmt(cols.get(c, 0)) for c in COLUMNS],
            fmt(total),
            note,
        ]
        lines.append(",".join(row))

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    n_yearly = len(periods) - len(monthly_periods)
    print(f"wrote {args.out}: {len(periods)} periods "
          f"({len(monthly_periods)} monthly + {n_yearly} yearly) "
          f"{periods[0][0]}-{periods[0][1]:02d}..{periods[-1][0]}-{periods[-1][1]:02d} "
          f"(dropped >= {cutoff[0]}-{cutoff[1]:02d}; provisional={sorted(provisional)})",
          file=sys.stderr)


if __name__ == "__main__":
    main()
