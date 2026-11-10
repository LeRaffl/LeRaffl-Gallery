#!/usr/bin/env python3
"""
Fetch how OLD each country's passenger-car stock is, and how many cars it
registered per year back to 1970, from Eurostat. Writes

    fleet/fleet_age.csv               stock by age band, per country and year
    fleet/registrations_history.csv   new passenger cars per year, per country

Why
---
How many cars leave a fleet next year depends on how old the fleet is. The
Fleet tab used to assume an age structure; these two tables let it start from
the observed one, and they are also what the survival curve's shape is fitted
against (``scripts/fit_fleet_survival.py``).

The spread is large: 36 % of Finland's cars are over 20 years old, 9 % of
Switzerland's. And the registration series in ``data/<Country>.csv`` reach
back 10 to 20 years, while half of a fleet is older than that.

Sources (Eurostat dissemination API, JSON-stat 2.0, open, no key)
-----------------------------------------------------------------
* ``road_eqs_carage`` "Passenger cars by age": stock at 31 December in five
  bands - under 2, 2 to 5, 5 to 10, 10 to 20, over 20 years. 2013 onwards.
* ``road_eqr_carmot`` "New passenger cars by type of motor energy and engine
  size": TOTAL x TOTAL, i.e. all new passenger cars per year, from 1970.

Rules
-----
* An age row is written only when all five bands are reported and they add up
  to the table's own TOTAL within ``BAND_TOLERANCE``.
* The registration history is written as published, gaps included. A missing
  year is not interpolated here; readers decide (a blank is not a zero).
* The band boundaries are not applied identically everywhere: for Germany and
  Austria the "under 2" band holds roughly 2.7 years of registrations, and the
  "2 to 5" band correspondingly less. Readers should merge the two youngest
  bands; the sum is consistent.

Annual. Run by hand or by ``fetch-fleet-eurostat.yml`` (monthly; idempotent).

Usage
-----
    python scripts/fetch_fleet_age.py [--age-file PATH --reg-file PATH] [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGE_PATH = ROOT / "fleet" / "fleet_age.csv"
REG_PATH = ROOT / "fleet" / "registrations_history.csv"
API = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{}?format=JSON&lang=EN"
AGE_TABLE, REG_TABLE = "road_eqs_carage", "road_eqr_carmot"
AGE_SOURCE = "Eurostat road_eqs_carage (31 Dec)"
REG_SOURCE = "Eurostat road_eqr_carmot"

# Eurostat band code -> column.
BANDS = {"Y_LT2": "lt2", "Y2-5": "y2_5", "Y5-10": "y5_10", "Y10-20": "y10_20", "Y_GT20": "gt20"}
AGE_COLUMNS = ["country", "year", *BANDS.values(), "total", "source"]
REG_COLUMNS = ["country", "year", "new_registrations", "source"]
BAND_TOLERANCE = 0.02   # share of TOTAL the five bands may miss it by

# Eurostat geo code -> fleet country name (fleet/fleet_initial.csv). Every
# fleet country Eurostat covers, whichever source its stock by fuel comes from.
GEO = {
    "AL": "Albania", "AT": "Austria", "BE": "Belgium", "BG": "Bulgaria", "CH": "Switzerland",
    "CY": "Cyprus", "CZ": "Czechia", "DE": "Germany", "DK": "Denmark", "EE": "Estonia",
    "ES": "Spain", "FI": "Finland", "FR": "France", "GE": "Georgia", "HR": "Croatia",
    "HU": "Hungary", "IE": "Ireland", "IT": "Italy", "LT": "Lithuania", "LU": "Luxembourg",
    "LV": "Latvia", "MT": "Malta", "NL": "Netherlands", "NO": "Norway", "PT": "Portugal",
    "RO": "Romania", "SE": "Sweden", "SI": "Slovenia", "TR": "Türkiye", "UK": "United Kingdom",
}


def decode(doc: dict) -> dict[tuple, float]:
    """JSON-stat 2.0 -> {(category per dimension, in doc['id'] order): value}."""
    ids, size = doc["id"], doc["size"]
    names = []
    for k in ids:
        index = doc["dimension"][k]["category"]["index"]
        names.append({pos: code for code, pos in index.items()})
    out = {}
    for flat, v in doc["value"].items():
        if v is None:
            continue
        f, pos = int(flat), []
        for s in reversed(size):
            pos.append(f % s)
            f //= s
        out[tuple(names[i][p] for i, p in enumerate(reversed(pos)))] = v
    return out


def age_rows(doc: dict, geo: dict = GEO) -> list[dict]:
    ids = doc["id"]
    ia, ig, it = ids.index("age"), ids.index("geo"), ids.index("time")
    cells: dict[tuple, dict] = {}
    for key, v in decode(doc).items():
        if key[ig] in geo:
            cells.setdefault((geo[key[ig]], int(key[it])), {})[key[ia]] = v
    rows = []
    for (country, year), c in sorted(cells.items()):
        if any(b not in c for b in BANDS):
            continue
        bands = sum(c[b] for b in BANDS)
        total = c.get("TOTAL", bands)
        if total <= 0 or abs(bands - total) > BAND_TOLERANCE * total:
            continue
        rows.append({"country": country, "year": year,
                     **{col: int(round(c[b])) for b, col in BANDS.items()},
                     "total": int(round(total)), "source": AGE_SOURCE})
    return rows


def reg_rows(doc: dict, geo: dict = GEO) -> list[dict]:
    ids = doc["id"]
    im, ie, ig, it = ids.index("mot_nrg"), ids.index("engine"), ids.index("geo"), ids.index("time")
    rows = []
    for key, v in decode(doc).items():
        if key[im] == "TOTAL" and key[ie] == "TOTAL" and key[ig] in geo and v > 0:
            rows.append({"country": geo[key[ig]], "year": int(key[it]),
                         "new_registrations": int(round(v)), "source": REG_SOURCE})
    rows.sort(key=lambda r: (r["country"], r["year"]))
    return rows


def to_csv(rows: list[dict], columns: list[str]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(columns)
    for r in rows:
        w.writerow([r[c] for c in columns])
    return buf.getvalue()


def fetch(table: str) -> dict:
    import requests
    resp = requests.get(API.format(table), timeout=180)
    resp.raise_for_status()
    return resp.json()


def write(path: Path, text: str) -> None:
    if path.exists() and path.read_text(encoding="utf-8") == text:
        print(f"{path.relative_to(ROOT)} already up to date; no change.")
        return
    path.write_text(text, encoding="utf-8")
    print(f"Wrote {path.relative_to(ROOT)}.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--age-file", help="saved road_eqs_carage JSON (offline / testing)")
    ap.add_argument("--reg-file", help="saved road_eqr_carmot JSON (offline / testing)")
    ap.add_argument("--dry-run", action="store_true", help="print a summary, write nothing")
    args = ap.parse_args()

    load = lambda f, t: json.loads(Path(f).read_text(encoding="utf-8")) if f else fetch(t)  # noqa: E731
    ages = age_rows(load(args.age_file, AGE_TABLE))
    regs = reg_rows(load(args.reg_file, REG_TABLE))
    if not ages or not regs:
        raise SystemExit("Eurostat returned no usable rows: refusing to empty the files")
    print(f"age bands: {len(ages)} rows, {len({r['country'] for r in ages})} countries; "
          f"registrations: {len(regs)} rows, {len({r['country'] for r in regs})} countries, "
          f"{min(r['year'] for r in regs)}-{max(r['year'] for r in regs)}")
    if args.dry_run:
        return 0
    write(AGE_PATH, to_csv(ages, AGE_COLUMNS))
    write(REG_PATH, to_csv(regs, REG_COLUMNS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
