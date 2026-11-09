#!/usr/bin/env python3
"""
Fetch average annual mileage per passenger car BY FUEL and upsert it into
``fleet/mileage.csv`` - what the Fleet tab's Energy view multiplies a car by.

Why
---
Energy and emissions are cars x km x consumption. The km used to be five
numbers for the whole world (petrol 11,000, diesel 17,500, battery 14,000 ...).
Statistics offices that measure mileage from odometer readings at inspection
show how far off that was, and how differently fuels are driven::

    Norway 2025 (SSB)   petrol 7,622   diesel 11,196   battery 13,453   all 11,350
    Germany 2025 (KBA)  petrol 8,406                   battery 11,312   all 10,616

A battery car is not driven further because it is electric. In SSB's table by
age (12578), cars up to four years old do 13,812 km as battery cars, 11,594 as
petrol, 14,825 as diesel and 13,927 on average: the gap between the fuels is
mostly AGE. Petrol cars are old, and an old car is driven little (3,768 km at
25 years and over). The page therefore keeps a country's fleet-average km per
car constant in projections and only lets the fuels differ in proportion
(index.html: feMileage) - otherwise electrification would inflate total
driving.

Sources
-------
* **Norway** - Statistics Norway (SSB) table 12577 "Road traffic volumes, by
  vehicle type, type of fuel", vehicle type 15 "All passenger cars", content
  "Average road traffic volumes per vehicle (km)". Open API, no key:
  https://data.ssb.no/api/v0/en/table/12577 . Fetched here.
* **Germany** - Kraftfahrt-Bundesamt "Verkehr in Kilometern (VK)",
  Inlaenderfahrleistung. kba.de is not reachable without the relay, and the
  per-fuel figures are published in a press release and a PDF, so these rows
  are CURATED: they are in the CSV with ``source`` naming the release, and this
  script never touches a row it did not write.

Other countries publish the same thing (Sweden Trafikanalys, the Netherlands
CBS, the UK MOT data, Denmark, Finland); adding one is a new block here plus
its rows. A country without rows uses the ``km_*`` defaults in
``energy_factors.csv``.

Output
------
``fleet/mileage.csv``: ``country, year, fuel, km_per_car, total_mkm, source,
notes``. ``fuel`` is one of ALL, PETROL, DIESEL, BEV, PHEV, HEV (the Energy
view's classes; plug-in and full hybrids are the petrol hybrids, which are
nearly all of them). Upsert keyed (country, year, fuel); rows of other sources
are kept.

Two figures per row, because they are not interchangeable:

* ``km_per_car`` - the office's published average. Its denominator is every
  vehicle that was on the road at some point in the year (and, for SSB, taxis
  and motor homes too), about 7 % more vehicles than the year-end stock in
  ``fleet/fleet_initial.csv``.
* ``total_mkm`` - million km driven by that fuel in the year. Divided by OUR
  year-end stock it gives the km per stock car that makes cars x km equal the
  kilometres actually driven. ``scripts/build_fleet_calibration.py`` does that
  division and the page uses the result; where a fuel has no total, the
  published average is scaled by the ALL row's ratio between the two.

Usage
-----
    python scripts/fetch_fleet_mileage.py [--file PATH] [--dry-run]

``--file`` parses a saved SSB JSON-stat2 response (offline / testing).
"""
from __future__ import annotations

import argparse
import csv
import io
import itertools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "fleet" / "mileage.csv"
COLUMNS = ["country", "year", "fuel", "km_per_car", "total_mkm", "source", "notes"]
FUELS = ["ALL", "PETROL", "DIESEL", "BEV", "PHEV", "HEV"]

SSB_URL = "https://data.ssb.no/api/v0/en/table/12577"
SSB_SOURCE = "SSB 12577 (all passenger cars)"
# SSB fuel code -> our class.
SSB_FUEL = {"0": "ALL", "1": "PETROL", "2": "DIESEL", "18": "BEV", "14": "PHEV", "15": "HEV"}
SSB_VEHICLE = "15"                  # All passenger cars
SSB_CONTENT = "GjsnittKjorelengde"  # Average road traffic volumes per vehicle (km)
SSB_TOTAL = "Kjorelengde"           # Road traffic volumes (million km)
SSB_QUERY = {
    "query": [
        {"code": "Kjoretoytype", "selection": {"filter": "item", "values": [SSB_VEHICLE]}},
        {"code": "DrivstoffType", "selection": {"filter": "item", "values": list(SSB_FUEL)}},
        {"code": "ContentsCode", "selection": {"filter": "item", "values": [SSB_CONTENT, SSB_TOTAL]}},
    ],
    "response": {"format": "json-stat2"},
}
# A per-fuel average on a handful of cars is noise (battery cars in 2005).
MIN_KM, MAX_KM = 1000, 60000


def parse_ssb(doc: dict) -> list[dict]:
    """JSON-stat2 -> rows for Norway. Missing cells (null) are skipped."""
    ids, size = doc["id"], doc["size"]
    order = {k: sorted(doc["dimension"][k]["category"]["index"],
                       key=doc["dimension"][k]["category"]["index"].get) for k in ids}
    avg, total = {}, {}
    for n, pos in enumerate(itertools.product(*[range(s) for s in size])):
        key = {k: order[k][p] for k, p in zip(ids, pos)}
        v = doc["value"][n]
        fuel = SSB_FUEL.get(key.get("DrivstoffType"))
        if v is None or not fuel or key.get("Kjoretoytype") != SSB_VEHICLE:
            continue
        k = (int(key["Tid"]), fuel)
        if key.get("ContentsCode") == SSB_CONTENT:
            avg[k] = v
        elif key.get("ContentsCode") == SSB_TOTAL:
            total[k] = v
    rows = []
    for (year, fuel), v in sorted(avg.items()):
        if not (MIN_KM <= v <= MAX_KM):
            continue
        t = total.get((year, fuel))
        rows.append({"country": "Norway", "year": year, "fuel": fuel,
                     "km_per_car": int(round(v)),
                     "total_mkm": "" if t is None else (f"{t:.1f}".rstrip("0").rstrip(".")),
                     "source": SSB_SOURCE, "notes": ""})
    return rows


def read_existing(path: Path = OUT_PATH) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def upsert(new_rows: list[dict], existing: list[dict], owned_source: str) -> list[dict]:
    """Replace this script's own rows, keep everyone else's. A fetched row
    never overwrites a row of another source with the same key."""
    key = lambda r: (r["country"], int(r["year"]), r["fuel"])  # noqa: E731
    kept = [r for r in existing if r.get("source") != owned_source]
    taken = {key(r) for r in kept}
    out = kept + [r for r in new_rows if key(r) not in taken]
    out.sort(key=lambda r: (r["country"], int(r["year"]), FUELS.index(r["fuel"]) if r["fuel"] in FUELS else 99))
    return out


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(COLUMNS)
    for r in rows:
        w.writerow([r.get(c, "") for c in COLUMNS])
    return buf.getvalue()


def fetch_ssb() -> dict:
    import requests
    resp = requests.post(SSB_URL, json=SSB_QUERY, timeout=120)
    resp.raise_for_status()
    return resp.json()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", help="parse a saved SSB JSON-stat2 response instead of downloading")
    ap.add_argument("--dry-run", action="store_true", help="print a summary, write nothing")
    args = ap.parse_args()

    doc = json.loads(Path(args.file).read_text(encoding="utf-8")) if args.file else fetch_ssb()
    new_rows = parse_ssb(doc)
    if not new_rows:
        raise SystemExit("SSB response held no usable rows: refusing to drop Norway from the file")
    rows = upsert(new_rows, read_existing(), SSB_SOURCE)
    last = max(r["year"] for r in new_rows)
    print(f"Norway: {len(new_rows)} rows, {min(r['year'] for r in new_rows)}-{last}; "
          + ", ".join(f"{r['fuel']} {r['km_per_car']}" for r in new_rows if r["year"] == last))
    if args.dry_run:
        return 0
    out = to_csv(rows)
    if OUT_PATH.exists() and OUT_PATH.read_text(encoding="utf-8") == out:
        print(f"{OUT_PATH.relative_to(ROOT)} already up to date; no change.")
        return 0
    OUT_PATH.write_text(out, encoding="utf-8")
    print(f"Wrote {OUT_PATH.relative_to(ROOT)} ({len(rows)} rows).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
