#!/usr/bin/env python3
"""
Fetch each fleet country's electricity mix and grid carbon intensity and write
``fleet/grid_mix.csv`` - what the Fleet tab's Energy view charges its electric
cars with.

Why
---
The Energy view used one WORLD average grid (about 480 gCO2e/kWh, 35 % coal)
for every country. That puts Norway's battery cars on a coal-heavy grid: the
real Norwegian figure is about 30 g, the Polish one about 590 g. A per-country
grid is the single biggest correction to the emissions figure.

Source
------
Our World in Data "Energy" dataset (CC BY 4.0), which republishes **Ember's**
Yearly Electricity Data (generation shares and carbon intensity of electricity,
in gCO2e per kWh generated, on Ember's emission factors) with the Energy
Institute Statistical Review as its fallback:

    https://raw.githubusercontent.com/owid/energy-data/master/owid-energy-data.csv

One CSV, open, no key. Annual: run this by hand (or by an agent) once a year,
after Ember's spring release, alongside the yearly fleet refresh. No workflow -
like the stock data, it moves once a year.

Output
------
``fleet/grid_mix.csv``, one row per (country, year) from ``START_YEAR``, for
every country in ``fleet/fleet_initial.csv`` plus ``World`` (the fallback for a
country without a row). Columns::

    country, year, gco2_kwh, coal, gas, oil, nuclear, hydro, wind, solar, bio, other_renew

``gco2_kwh`` is gCO2e per kWh generated; the rest are shares of generation in
percent. A blank share is "not reported", not zero; a row is written only when
it has an intensity AND shares that add up to 100 % (within ``SHARE_TOLERANCE``).

Usage
-----
    python scripts/fetch_grid_mix.py [--file PATH] [--dry-run]

``--file`` parses a saved copy of the OWID CSV (offline / testing).
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLEET_CSV = ROOT / "fleet" / "fleet_initial.csv"
OUT_PATH = ROOT / "fleet" / "grid_mix.csv"
URL = "https://raw.githubusercontent.com/owid/energy-data/master/owid-energy-data.csv"

START_YEAR = 2010
SHARE_TOLERANCE = 1.5   # percentage points the shares may miss 100 by

# Output share column -> OWID column.
SHARES = {
    "coal": "coal_share_elec",
    "gas": "gas_share_elec",
    "oil": "oil_share_elec",
    "nuclear": "nuclear_share_elec",
    "hydro": "hydro_share_elec",
    "wind": "wind_share_elec",
    "solar": "solar_share_elec",
    "bio": "biofuel_share_elec",
    "other_renew": "other_renewables_share_elec_exc_biofuel",
}
INTENSITY = "carbon_intensity_elec"
COLUMNS = ["country", "year", "gco2_kwh", *SHARES]

# Fleet country name -> OWID country name, where they differ.
OWID_NAME = {"Türkiye": "Turkey"}
WORLD = "World"


def fleet_countries(path: Path = FLEET_CSV) -> list[str]:
    with path.open(newline="", encoding="utf-8") as fh:
        return sorted({(r.get("country") or "").strip()
                       for r in csv.DictReader(fh)} - {""})


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def build_rows(owid_rows, countries: list[str], start_year: int = START_YEAR):
    """(rows, skipped) - rows as dicts in COLUMNS order, sorted country, year."""
    wanted = {OWID_NAME.get(c, c): c for c in countries}
    wanted[WORLD] = WORLD
    rows, skipped = [], []
    for r in owid_rows:
        name = (r.get("country") or "").strip()
        if name not in wanted:
            continue
        try:
            year = int(r["year"])
        except (KeyError, ValueError):
            continue
        if year < start_year:
            continue
        intensity = _num(r.get(INTENSITY))
        shares = {k: _num(r.get(col)) for k, col in SHARES.items()}
        total = sum(v for v in shares.values() if v is not None)
        if intensity is None or abs(total - 100) > SHARE_TOLERANCE:
            skipped.append((wanted[name], year,
                            "no intensity" if intensity is None
                            else f"shares add up to {total:.1f} %"))
            continue
        rows.append({"country": wanted[name], "year": year,
                     "gco2_kwh": intensity, **shares})
    rows.sort(key=lambda r: (r["country"] != WORLD, r["country"], r["year"]))
    return rows, skipped


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.1f}"
    return str(v)


def to_csv(rows) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(COLUMNS)
    for r in rows:
        w.writerow([_fmt(r[c]) for c in COLUMNS])
    return buf.getvalue()


def fetch() -> str:
    import requests
    resp = requests.get(URL, timeout=180)
    resp.raise_for_status()
    return resp.text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", help="parse a saved OWID CSV instead of downloading")
    ap.add_argument("--dry-run", action="store_true", help="print a summary, write nothing")
    args = ap.parse_args()

    text = Path(args.file).read_text(encoding="utf-8") if args.file else fetch()
    countries = fleet_countries()
    rows, skipped = build_rows(csv.DictReader(io.StringIO(text)), countries)

    have = {r["country"] for r in rows}
    missing = [c for c in countries if c not in have]
    if WORLD not in have:
        raise SystemExit("no World row in the source: refusing to write a file "
                         "without its fallback")
    for c in missing:
        print(f"WARNING: no grid data for {c}; the page falls back to World",
              file=sys.stderr)
    for c, y, why in skipped:
        print(f"skipped {c} {y}: {why}", file=sys.stderr)

    latest = {}
    for r in rows:
        latest[r["country"]] = r
    print(f"{len(rows)} rows, {len(have)} of {len(countries) + 1} series")
    for c in (WORLD, *countries):
        if c in latest:
            r = latest[c]
            print(f"  {c:16s} {r['year']}  {r['gco2_kwh']:6.1f} gCO2e/kWh")
    if args.dry_run:
        return 0
    out = to_csv(rows)
    if OUT_PATH.exists() and OUT_PATH.read_text(encoding="utf-8") == out:
        print(f"{OUT_PATH.relative_to(ROOT)} already up to date; no change.")
        return 0
    OUT_PATH.write_text(out, encoding="utf-8")
    print(f"Wrote {OUT_PATH.relative_to(ROOT)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
