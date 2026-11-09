#!/usr/bin/env python3
"""
Build ``fleet/fleet_calibration.json`` - what the Fleet tab's projection is
calibrated against, derived only from data this repo already holds.

The Fleet tab projects a country's vehicle stock forward from the last observed
year. Three things about that projection used to be global guesses and are in
fact observable per country, by lining the stock series in
``fleet/fleet_initial.csv`` up against the registration series in
``data/<Country>.csv``:

1. **Net attrition.** Stock is a balance::

       stock[Y] = stock[Y-1] + new_registrations[Y] - net_exits[Y]

   so ``net_exits[Y] / stock[Y-1]`` is the share of the fleet that left during
   year Y. "Net" is literal: scrappage and exports minus used imports and
   re-registrations. It is therefore low or negative where used imports are
   large (Lithuania, Romania, New Zealand) and high where a country exports its
   young used cars (Luxembourg, Belgium, Germany). It is the registry's
   behaviour, not a statement about how long a car physically lasts.
   The published rate is the MEDIAN of the last ``WINDOW`` stock years that have
   a full registration year, and is only published with ``MIN_YEARS`` of them.

2. **Inflow mix on the combustion side.** The S-curve model gives the BEV share
   and the "ICE" share of future registrations, where ICE is everything that is
   not BEV / PHEV / EREV (``R/data.R``) - so it contains full hybrids, petrol,
   diesel and gas. How that side splits is taken from the last 12 months of
   registrations, and only where the source reports its own petrol / diesel
   split (an empty column is "not broken out", never zero - AGENTS.md
   invariant 4).

3. **Age structure.** BEV, PHEV and HEV stock is far younger than a mature
   fleet, and a fleet that grew fast (China) is younger than one that has been
   replaced at a steady pace for decades (Germany). The age profile is
   therefore taken from the yearly registrations instead of assumed:
   ``reg_by_year`` holds them per class, ``COMBUSTION`` being everything that
   is neither a plug-in nor a full hybrid. The page turns them into an age
   distribution for whichever year the projection starts from.

Usage
-----
    python scripts/build_fleet_calibration.py           # rewrite the JSON
    python scripts/build_fleet_calibration.py --check    # exit 1 if it would change
    python scripts/build_fleet_calibration.py --report   # print the table, write nothing

The output is generated: never hand-edit it. See
``docs/architecture/37-fleet-data-harmonization.md`` section 7.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLEET_CSV = ROOT / "fleet" / "fleet_initial.csv"
DATA_DIR = ROOT / "data"
OUT_PATH = ROOT / "fleet" / "fleet_calibration.json"

WINDOW = 5      # stock years the published attrition rate is the median of
MIN_YEARS = 3   # ...and how many of them must exist for a rate to be published
MIN_STOCK = 2000  # a per-fuel rate on fewer cars than this is noise

# Fleet country name -> registration file stem, where they differ.
DATA_STEM = {"United Kingdom": "UK"}

STOCK_FUELS = ["BEV", "PHEV", "EREV", "HEV", "MHEV", "PETROL", "DIESEL", "GAS",
               "CNG", "LPG", "FLEXFUEL", "ETHANOL", "OTHERS"]
# Registration columns folded into the classes the fleet model carries.
REG_FOLD = {"BEV": ["BEV"], "PHEV": ["PHEV", "EREV"], "HEV": ["HEV", "MHEV"],
            "PETROL": ["PETROL"], "DIESEL": ["DIESEL"]}
AGE_CLASSES = ["BEV", "PHEV", "HEV", "COMBUSTION"]


def num(x):
    """A CSV cell as float; blank / non-numeric is None (unknown, not zero)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def read_stock(path: Path = FLEET_CSV) -> dict[str, dict[int, dict]]:
    """country -> year -> {fuel: value|None, 'TOTAL': value}. Passenger cars only."""
    out: dict[str, dict[int, dict]] = defaultdict(dict)
    with path.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if (r.get("variant") or "Whole").strip() != "Whole":
                continue
            country = (r.get("country") or "").strip()
            try:
                year = int(r["year"])
            except (KeyError, ValueError):
                continue
            row = {k: num(r.get(k)) for k in STOCK_FUELS}
            total = num(r.get("TOTAL"))
            if not total:
                total = sum(v for v in row.values() if v)
            row["TOTAL"] = total
            # The fleet model's classes, folded the way the page folds them.
            row["PHEV+"] = (row["PHEV"] or 0) + (row["EREV"] or 0)
            out[country][year] = row
    return out


def months_covered(rows_in_year: list[dict]) -> int:
    """How many months of a calendar year a set of registration rows covers.

    Both encodings occur in data/: one row per quarter / year, and a quarterly
    or yearly figure spread over monthly rows that keep the coarse label.
    """
    by_interval = defaultdict(int)
    for r in rows_in_year:
        ti = (r.get("time_interval") or "monthly").strip().lower()
        if ti == "annual":
            ti = "yearly"
        if ti.startswith("monthly"):
            ti = "monthly"
        by_interval[ti] += 1
    q, y = by_interval.get("quarterly", 0), by_interval.get("yearly", 0)
    return (by_interval.get("monthly", 0)
            + q * (3 if q <= 4 else 1)
            + y * (12 if y <= 1 else 1))


def read_registrations(country: str, data_dir: Path = DATA_DIR):
    """(per-year sums, rows newest-last) for a country's passenger-car series.

    Per-year sums cover COMPLETE calendar years only. A class is None for a
    year when any row of that year leaves one of its columns blank where the
    column exists - a partial sum would understate registrations and inflate
    attrition. A class whose column the file does not have at all is None too.
    """
    path = data_dir / f"{DATA_STEM.get(country, country)}.csv"
    if not path.exists():
        return {}, []
    with path.open(newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh)
                if (r.get("variant") or "Whole").strip() == "Whole"
                and len((r.get("period") or "")) >= 7]
    rows.sort(key=lambda r: r["period"])
    cols = set(rows[0].keys()) if rows else set()
    by_year: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        by_year[int(r["period"][:4])].append(r)

    def class_sum(rs, members, need_all=False):
        present = [m for m in members if m in cols]
        if not present or (need_all and len(present) < len(members)):
            return None
        # The leading member must be reported on every row; the folded-in
        # extras (EREV, MHEV) may be blank where the source has none.
        if any(num(r.get(present[0])) is None for r in rs):
            return None
        return sum(num(r.get(m)) or 0 for r in rs for m in present)

    years = {}
    for y, rs in by_year.items():
        if months_covered(rs) != 12:
            continue
        rec = {k: class_sum(rs, members) for k, members in REG_FOLD.items()}
        rec["TOTAL"] = class_sum(rs, ["TOTAL"])
        # Everything that is neither a plug-in nor a full hybrid. Where the
        # source has no hybrid column those cars are in here, which is also
        # where such a country's stock keeps them.
        if rec["TOTAL"] is not None and rec["BEV"] is not None:
            rec["COMBUSTION"] = max(0.0, rec["TOTAL"] - rec["BEV"]
                                    - (rec["PHEV"] or 0) - (rec["HEV"] or 0))
        years[y] = rec
    return years, rows


def attrition(stock: dict[int, dict], reg: dict[int, dict]) -> dict | None:
    """Net attrition of the whole fleet and, where observable, per fuel."""
    def series(stock_key, reg_key):
        out = {}
        for y in sorted(stock):
            a, b, r = stock.get(y - 1), stock[y], reg.get(y)
            if not a or not r:
                continue
            s0, s1, inflow = a.get(stock_key), b.get(stock_key), r.get(reg_key)
            if not s0 or s1 is None or inflow is None or s0 < MIN_STOCK:
                continue
            out[y] = (s0 + inflow - s1) / s0
        return out

    def recent(s):
        if not s:
            return None
        last = max(s)
        vals = {y: v for y, v in s.items() if y > last - WINDOW}
        return vals if len(vals) >= MIN_YEARS else None

    total = recent(series("TOTAL", "TOTAL"))
    if not total:
        return None
    out = {
        "rate": round(statistics.median(total.values()), 4),
        "n": len(total),
        "from": min(total), "to": max(total),
        "by_year": {str(y): round(v, 4) for y, v in sorted(total.items())},
    }
    by_fuel = {}
    for label, (sk, rk) in {"BEV": ("BEV", "BEV"), "PHEV": ("PHEV+", "PHEV"),
                            "PETROL": ("PETROL", "PETROL"),
                            "DIESEL": ("DIESEL", "DIESEL")}.items():
        vals = recent(series(sk, rk))
        # A per-fuel figure beyond +-50 % a year is a scope mismatch between
        # the stock and the registration series, not attrition: leave it out.
        if vals and abs(statistics.median(vals.values())) <= 0.5:
            by_fuel[label] = round(statistics.median(vals.values()), 4)
    if by_fuel:
        out["by_fuel"] = by_fuel
    return out


def inflow_mix(rows: list[dict]) -> dict | None:
    """Split of the combustion side over the latest 12 months of registrations.

    Shares of ``TOTAL - BEV - PHEV - EREV`` (the model's "ICE"): HEV (incl.
    MHEV where the source has that column), PETROL, DIESEL and the remainder
    (gas, flex-fuel, unclassified). None unless the source reports its own
    petrol AND diesel split for the whole window.
    """
    # Each row covers the months since the row before it: 1 for monthly data
    # (and for a coarse figure spread over monthly rows), 3 for one row per
    # quarter. The window must be exactly the latest 12 months.
    def month_index(r):
        return int(r["period"][:4]) * 12 + int(r["period"][5:7])

    window, covered = [], 0
    for i in range(len(rows) - 1, 0, -1):
        step = month_index(rows[i]) - month_index(rows[i - 1])
        if step not in (1, 3):
            return None   # a gap, or yearly rows: not a clean 12-month window
        window.append(rows[i])
        covered += step
        if covered >= 12:
            break
    if covered != 12:
        return None
    cols = set(window[0].keys())
    if "PETROL" not in cols or "DIESEL" not in cols:
        return None
    if any(num(r.get(k)) is None for r in window for k in ("PETROL", "DIESEL", "TOTAL", "BEV")):
        return None
    s = lambda k: sum(num(r.get(k)) or 0 for r in window)  # noqa: E731
    ice = s("TOTAL") - s("BEV") - s("PHEV") - s("EREV")
    if ice <= 0:
        return None
    hev = min(s("HEV") + s("MHEV"), ice)
    petrol, diesel = s("PETROL"), s("DIESEL")
    scale = min(1.0, (ice - hev) / (petrol + diesel)) if petrol + diesel > 0 else 0.0
    petrol, diesel = petrol * scale, diesel * scale
    others = max(0.0, ice - hev - petrol - diesel)
    periods = sorted(r["period"] for r in window)
    return {
        "window": f"{periods[0]}..{periods[-1]}",
        "HEV": round(hev / ice, 4), "PETROL": round(petrol / ice, 4),
        "DIESEL": round(diesel / ice, 4), "OTHERS": round(others / ice, 4),
    }


def reg_by_year(reg: dict[int, dict]) -> dict:
    out = {}
    for k in AGE_CLASSES:
        vals = {str(y): round(r[k]) for y, r in sorted(reg.items())
                if r.get(k) is not None and r[k] > 0}
        if vals:
            out[k] = vals
    return out


def build(fleet_csv: Path = FLEET_CSV, data_dir: Path = DATA_DIR) -> dict:
    stock = read_stock(fleet_csv)
    countries = {}
    for country in sorted(stock):
        reg, rows = read_registrations(country, data_dir)
        entry = {}
        a = attrition(stock[country], reg)
        if a:
            entry["attrition"] = a
        m = inflow_mix(rows)
        if m:
            entry["inflow_mix"] = m
        ages = reg_by_year(reg)
        if ages:
            entry["reg_by_year"] = ages
        if entry:
            countries[country] = entry
    return {
        "generated_by": "scripts/build_fleet_calibration.py",
        "note": ("Generated from fleet/fleet_initial.csv and data/<Country>.csv. "
                 "Do not hand-edit. attrition.rate = median net exit share of the "
                 "passenger-car stock per year (scrappage + exports - used imports); "
                 "inflow_mix = split of the non-plug-in side of the last 12 months "
                 "of registrations; reg_by_year = yearly registrations used as the "
                 "age profile of the stock (COMBUSTION = TOTAL - BEV - PHEV - HEV)."),
        "window_years": WINDOW,
        "min_years": MIN_YEARS,
        "countries": countries,
    }


def dumps(doc: dict) -> str:
    return json.dumps(doc, indent=1, ensure_ascii=False, sort_keys=False) + "\n"


def report(doc: dict) -> None:
    print(f"{'country':18s} {'attr':>7s} {'n':>2s} {'years':>9s}   "
          f"{'BEV':>7s} {'PETROL':>7s} {'DIESEL':>7s}   inflow mix (HEV/P/D/oth)")
    for c, e in doc["countries"].items():
        a, m = e.get("attrition"), e.get("inflow_mix")
        f = (a or {}).get("by_fuel", {})
        cell = lambda v: f"{v:7.4f}" if v is not None else "      -"  # noqa: E731
        print(f"{c:18s} {cell(a['rate'] if a else None)} "
              f"{(a or {}).get('n', ''):>2} "
              f"{(str(a['from']) + '-' + str(a['to'])[2:]) if a else '':>9s}   "
              f"{cell(f.get('BEV'))} {cell(f.get('PETROL'))} {cell(f.get('DIESEL'))}   "
              + (f"{m['HEV']:.2f}/{m['PETROL']:.2f}/{m['DIESEL']:.2f}/{m['OTHERS']:.2f}"
                 if m else "-"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the file on disk differs from a fresh build")
    ap.add_argument("--report", action="store_true",
                    help="print the calibration table and write nothing")
    args = ap.parse_args()

    doc = build()
    if args.report:
        report(doc)
        return 0
    text = dumps(doc)
    old = OUT_PATH.read_text(encoding="utf-8") if OUT_PATH.exists() else None
    if args.check:
        if old == text:
            print(f"OK: {OUT_PATH.relative_to(ROOT)} is up to date "
                  f"({len(doc['countries'])} countries)")
            return 0
        print(f"STALE: {OUT_PATH.relative_to(ROOT)} differs from a fresh build.\n"
              "       Run: python scripts/build_fleet_calibration.py", file=sys.stderr)
        return 1
    if old == text:
        print(f"{OUT_PATH.relative_to(ROOT)} already up to date; no change.")
        return 0
    OUT_PATH.write_text(text, encoding="utf-8")
    print(f"Wrote {OUT_PATH.relative_to(ROOT)} ({len(doc['countries'])} countries).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
