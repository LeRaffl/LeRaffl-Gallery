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

4. **Observed age bands.** ``fleet/fleet_age.csv`` (Eurostat) says what share
   of each country's stock is under 5, 5-10, 10-20 and over 20 years old. Where
   it exists the page starts from it instead of inferring the age structure.
   ``fleet/registrations_history.csv`` (Eurostat, from 1970) extends the
   ``COMBUSTION`` registration series backwards past what ``data/`` holds.

5. **Mileage.** ``fleet/mileage.csv`` holds what statistics offices publish:
   km per vehicle and total km by fuel. Their per-vehicle average is over every
   vehicle on the road at some point in the year, about 7 % more vehicles than
   the year-end stock here, so the page needs **km per stock car**: total km
   divided by the stock in ``fleet/fleet_initial.csv``. Where a fuel has no
   published total, its published average is scaled by the ratio the ALL row
   shows between the two. ``mileage_default`` (top level) is the median over
   the countries that report petrol and diesel separately: what a country
   without figures of its own is given.

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
AGE_CSV = ROOT / "fleet" / "fleet_age.csv"
REG_HISTORY_CSV = ROOT / "fleet" / "registrations_history.csv"
MILEAGE_CSV = ROOT / "fleet" / "mileage.csv"

MAX_GAP = 6                      # longest hole in a registration history that is interpolated
KM_MIN, KM_MAX = 1000, 60000     # a km-per-car figure outside this is a scope mismatch
# mileage.csv fuel -> key of the stock row (read_stock) it is divided by.
MILEAGE_STOCK = {"ALL": "TOTAL", "PETROL": "PETROL", "DIESEL": "DIESEL",
                 "BEV": "BEV", "PHEV": "PHEV+", "HEV": "HEV+", "HYBRID": "HYBRID+"}
MILEAGE_MIN_YEAR = 2021          # mileage older than this is not published
REL_MIN, REL_MAX = 0.4, 1.8      # a fuel's km per car, relative to the country's all-car figure

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


# Vehicle classes beyond passenger cars (`Whole`). A country's block for one of
# them sits under its `variants` key and is built the same way from the stock
# rows of that variant and data/<Country>_<Variant>.csv.
VARIANTS = ("Vans", "HDV", "Buses")


def read_stock(path: Path = FLEET_CSV, variant: str = "Whole") -> dict[str, dict[int, dict]]:
    """country -> year -> {fuel: value|None, 'TOTAL': value}, for one variant."""
    out: dict[str, dict[int, dict]] = defaultdict(dict)
    with path.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if (r.get("variant") or "Whole").strip() != variant:
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
            row["HEV+"] = (row["HEV"] or 0) + (row["MHEV"] or 0)
            row["HYBRID+"] = row["PHEV+"] + row["HEV+"]
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


def read_registrations(country: str, data_dir: Path = DATA_DIR, variant: str = "Whole"):
    """(per-year sums, rows newest-last) for a country's series of one variant
    (``data/<Country>.csv`` for passenger cars, ``data/<Country>_<Variant>.csv``
    otherwise).

    Per-year sums cover COMPLETE calendar years only. A class is None for a
    year when any row of that year leaves one of its columns blank where the
    column exists - a partial sum would understate registrations and inflate
    attrition. A class whose column the file does not have at all is None too.
    """
    stem = DATA_STEM.get(country, country)
    path = data_dir / (f"{stem}.csv" if variant == "Whole" else f"{stem}_{variant}.csv")
    if not path.exists():
        return {}, []
    with path.open(newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh)
                if (r.get("variant") or "Whole").strip() == variant
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


def _rows(path: Path | None) -> list[dict]:
    if not path or not Path(path).exists():
        return []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def read_age_bands(path: Path | None = AGE_CSV) -> dict[str, dict[str, list[float]]]:
    """country -> year -> shares of the stock [under 5, 5-10, 10-20, over 20 years].

    The two youngest published bands are merged: their boundary is not applied
    uniformly (Germany's "under 2" holds about 2.7 years of registrations).
    """
    out: dict[str, dict[str, list[float]]] = defaultdict(dict)
    for r in _rows(path):
        v = [num(r.get(k)) for k in ("lt2", "y2_5", "y5_10", "y10_20", "gt20")]
        if any(x is None for x in v) or sum(v) <= 0:
            continue
        bands = [v[0] + v[1], v[2], v[3], v[4]]
        out[r["country"]][str(int(r["year"]))] = [round(b / sum(bands), 4) for b in bands]
    return out


def read_registration_history(path: Path | None = REG_HISTORY_CSV) -> dict[str, dict[int, float]]:
    """country -> year -> all new passenger cars, short gaps interpolated."""
    raw: dict[str, dict[int, float]] = defaultdict(dict)
    for r in _rows(path):
        v = num(r.get("new_registrations"))
        if v:
            raw[r["country"]][int(r["year"])] = v
    out = {}
    for country, s in raw.items():
        ys = sorted(s)
        full = dict(s)
        for lo, hi in zip(ys, ys[1:]):
            if 1 < hi - lo <= MAX_GAP:
                for y in range(lo + 1, hi):
                    full[y] = s[lo] + (s[hi] - s[lo]) * (y - lo) / (hi - lo)
        out[country] = full
    return out


def extend_combustion(ages: dict, history: dict[int, float]) -> None:
    """Prepend the long Eurostat history to a country's COMBUSTION series.

    Only for years BEFORE the first year the country's own data covers, and
    only as far back as the two series join without a hole. Those years are
    all new cars rather than combustion cars only, which before the 2010s is
    the same number to within a percent or two.
    """
    own = ages.get("COMBUSTION")
    if not own or not history:
        return
    first = min(int(y) for y in own)
    y, older = first - 1, {}
    while y in history:
        older[str(y)] = round(history[y])
        y -= 1
    if older:
        ages["COMBUSTION"] = {**dict(sorted(older.items())), **own}


def mileage(country: str, stock: dict[int, dict], rows: list[dict]) -> dict | None:
    """km per car of the YEAR-END STOCK, by fuel, for the latest usable year.

    A year is usable when it has a published total for all cars and a stock
    row, and is not older than ``MILEAGE_MIN_YEAR``: a figure from the
    pandemic year, from before the battery fleet, or from a series that has
    ended (the UK's stops in 2020) is worse than the cross-country default.
    Per-fuel figures are published only within ``REL_MIN``..``REL_MAX`` of the
    country's own all-car figure: outside that, the fuel classes of the km and
    of the stock do not match.
    """
    by_year: dict[int, dict[str, dict]] = defaultdict(dict)
    for r in rows:
        if r.get("country") == country and r.get("fuel") in MILEAGE_STOCK:
            by_year[int(r["year"])][r["fuel"]] = r
    for year in sorted((y for y in by_year if y >= MILEAGE_MIN_YEAR), reverse=True):
        fuels, st = by_year[year], stock.get(year)
        every = fuels.get("ALL")
        if not st or not every or not num(every.get("total_mkm")) or not st.get("TOTAL"):
            continue
        all_km = num(every["total_mkm"]) * 1e6 / st["TOTAL"]
        if not KM_MIN <= all_km <= KM_MAX:
            continue
        # How much larger the office's vehicle base is than our stock.
        basis = all_km / num(every["km_per_car"]) if num(every.get("km_per_car")) else None
        out = {"year": year, "source": every.get("source", ""), "ALL": round(all_km)}
        derived = []
        for fuel, key in MILEAGE_STOCK.items():
            r = fuels.get(fuel)
            if fuel == "ALL" or not r:
                continue
            cars, total, avg = st.get(key), num(r.get("total_mkm")), num(r.get("km_per_car"))
            if total and cars and cars >= MIN_STOCK:
                km = total * 1e6 / cars
            elif avg and basis and fuel != "HYBRID":
                km = avg * basis
                derived.append(fuel)
            else:
                continue
            if not (KM_MIN <= km <= KM_MAX and REL_MIN * all_km <= km <= REL_MAX * all_km):
                if fuel in derived:
                    derived.remove(fuel)
                continue
            out[fuel] = round(km)
        # Full and plug-in hybrids reported together: one figure for both,
        # unless the source has them apart.
        combined = out.pop("HYBRID", None)
        if combined is not None:
            shared = [f for f in ("PHEV", "HEV") if f not in out]
            for f in shared:
                out[f] = combined
            if shared:
                out["hybrids_combined"] = shared
        if derived:
            out["scaled_from_average"] = derived
        if basis:
            out["basis_ratio"] = round(basis, 3)
        return out
    return None


def mileage_default(countries: dict) -> dict | None:
    """What a country without figures of its own is given: per class, the
    median over the countries that report petrol and diesel separately."""
    have = {c: e["mileage"] for c, e in countries.items()
            if "PETROL" in e.get("mileage", {}) and "DIESEL" in e["mileage"]}
    if len(have) < MIN_YEARS:
        return None
    out = {"countries": sorted(have)}
    for cls in ("ALL", "PETROL", "DIESEL", "BEV", "PHEV", "HEV"):
        vals = [m[cls] for m in have.values() if cls in m]
        if len(vals) >= MIN_YEARS:
            out[cls] = round(statistics.median(vals))
    return out


def build(fleet_csv: Path = FLEET_CSV, data_dir: Path = DATA_DIR,
          age_csv: Path | None = AGE_CSV, history_csv: Path | None = REG_HISTORY_CSV,
          mileage_csv: Path | None = MILEAGE_CSV) -> dict:
    stock = read_stock(fleet_csv)
    bands, history, km_rows = read_age_bands(age_csv), read_registration_history(history_csv), _rows(mileage_csv)
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
            extend_combustion(ages, history.get(country, {}))
            entry["reg_by_year"] = ages
        if country in bands:
            entry["age_bands"] = dict(sorted(bands[country].items()))
        km = mileage(country, stock[country], km_rows)
        if km:
            entry["mileage"] = km
        if entry:
            countries[country] = entry
    # Other vehicle classes: the same stock-flow identity, inflow mix and
    # registration history, per (country, variant) that has stock rows.
    for variant in VARIANTS:
        for country, years in sorted(read_stock(fleet_csv, variant).items()):
            reg, rows = read_registrations(country, data_dir, variant)
            block = {}
            a = attrition(years, reg)
            if a:
                block["attrition"] = a
            m = inflow_mix(rows)
            if m:
                block["inflow_mix"] = m
            ages = reg_by_year(reg)
            if ages:
                block["reg_by_year"] = ages
            if block:
                countries.setdefault(country, {}).setdefault("variants", {})[variant] = block
    return {
        "generated_by": "scripts/build_fleet_calibration.py",
        "note": ("Generated from fleet/fleet_initial.csv and data/<Country>.csv. "
                 "Do not hand-edit. attrition.rate = median net exit share of the "
                 "passenger-car stock per year (scrappage + exports - used imports); "
                 "inflow_mix = split of the non-plug-in side of the last 12 months "
                 "of registrations; reg_by_year = yearly registrations used as the "
                 "age profile of the stock (COMBUSTION = TOTAL - BEV - PHEV - HEV, "
                 "extended backwards with all new cars from fleet/registrations_history.csv); "
                 "age_bands = observed shares of the stock under 5 / 5-10 / 10-20 / over 20 "
                 "years (fleet/fleet_age.csv); mileage = km per car of the year-end stock "
                 "(fleet/mileage.csv totals divided by the stock)."),
        "window_years": WINDOW,
        "min_years": MIN_YEARS,
        **({"mileage_default": d} if (d := mileage_default(countries)) else {}),
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
