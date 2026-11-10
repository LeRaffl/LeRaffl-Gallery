#!/usr/bin/env python3
"""
Fetch how far passenger cars are driven, BY FUEL, and upsert it into
``fleet/mileage.csv`` - what the Fleet tab's Energy view multiplies a car by.

Why
---
Energy and emissions are cars x km x consumption. The km used to be five
numbers for the whole world (petrol 11,000, diesel 17,500, battery 14,000 ...).
Statistics offices that measure mileage from odometer readings at inspection
show how far off that was, how much countries differ, and how differently the
fuels are driven (km per car of the year-end stock, 2024)::

    Norway    petrol  8,309   diesel 13,127   battery 14,041   all 12,308
    Sweden    petrol 10,358   diesel 16,415   battery 15,521   all 13,291
    France    petrol  8,820   diesel 13,317   battery 11,872   all 11,532
    Germany   petrol  9,466   diesel 16,645                    all 12,042
    Estonia   petrol  4,962   diesel 10,471   battery  9,834   all  7,388

A battery car is not driven further because it is electric. In SSB's table by
age (12578), cars up to four years old do 13,812 km as battery cars, 11,594 as
petrol, 14,825 as diesel and 13,927 on average: the gap between the fuels is
mostly AGE. Petrol cars are old, and an old car is driven little (3,768 km at
25 years and over). The page therefore keeps a country's fleet-average km per
car constant in projections and only lets the fuels differ in proportion
(index.html: buildFleetEnergy) - otherwise electrification would inflate total
driving.

Sources
-------
* **Eurostat** (open API, JSON-stat 2.0), million vehicle-km of passenger cars:

  - ``road_tf_vehage`` "Road traffic performance on national and foreign
    territory by age of vehicle, type of vehicle and motor energy" - vehicles
    registered in the reporting country, wherever they drive. Age TOTAL, by
    fuel: petrol, diesel, electricity, and the hybrids (full and plug-in
    together). The preferred table.
  - ``road_tf_veh`` "Road traffic performance by category of vehicle
    registration and traffic" - all passenger cars only, for countries the
    first table lacks: ``TER_REGNAT`` (the same concept), else
    ``TERNAT_REGNAT`` (national vehicles on national territory, which leaves
    out their km abroad). ``TERNAT_REG`` is never used: it counts foreign
    vehicles on national roads, which is traffic, not what the national fleet
    drives.

  Countries report the fuel classes unevenly, and a petrol figure that
  silently includes the hybrids would be divided by the wrong stock. A
  country's per-fuel rows are therefore written only when the table shows
  that petrol and diesel are NOT everything: either electricity is reported
  on its own, or the reported fuels add up to visibly less than the total
  (``FUELS_COMPLETE``). Otherwise only the ALL row is written.

* **Norway** - Statistics Norway (SSB) table 12577 "Road traffic volumes, by
  vehicle type, type of fuel", vehicle type 15 "All passenger cars". Open API:
  https://data.ssb.no/api/v0/en/table/12577 . A year newer than Eurostat and
  with plug-in and full hybrids apart. Where both sources have a row, the
  national one is kept: this script's Eurostat rows never replace a row of
  another source, and the two agree to the kilometre for 2024.

A country without rows uses the cross-country median the build derives from
this file (``fleet_calibration.json``: ``mileage_default``).

Output
------
``fleet/mileage.csv``: ``country, year, fuel, km_per_car, total_mkm, source,
notes``. ``fuel`` is one of ALL, PETROL, DIESEL, BEV, PHEV, HEV, HYBRID (the
Energy view's classes; HYBRID is full and plug-in hybrids together, where the
source does not separate them). Upsert keyed (country, year, fuel).

Two figures per row, because they are not interchangeable:

* ``total_mkm`` - million km driven by that fuel in the year. Divided by OUR
  year-end stock it gives the km per stock car that makes cars x km equal the
  kilometres actually driven. ``scripts/build_fleet_calibration.py`` does that
  division and the page uses the result.
* ``km_per_car`` - an office's own published average, where there is one
  (SSB). Its denominator is every vehicle on the road at some point in the
  year, about 8 % more vehicles than the year-end stock, so it is kept for
  reference and only used, scaled, where a fuel has no total.

Usage
-----
    python scripts/fetch_fleet_mileage.py [--ssb-file P] [--vehage-file P] [--veh-file P] [--dry-run]

The ``--*-file`` options parse saved responses (offline / testing).
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
FUELS = ["ALL", "PETROL", "DIESEL", "BEV", "PHEV", "HEV", "HYBRID"]

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
EUROSTAT_API = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{}?format=JSON&lang=EN"
VEHAGE_TABLE, VEH_TABLE = "road_tf_vehage", "road_tf_veh"
VEHAGE_SOURCE = "Eurostat road_tf_vehage (national vehicles, national and foreign territory)"
VEH_SOURCES = {  # regisveh code -> source label, in order of preference
    "TER_REGNAT": "Eurostat road_tf_veh (national vehicles, national and foreign territory)",
    "TERNAT_REGNAT": "Eurostat road_tf_veh (national vehicles, national territory only)",
}
EUROSTAT_SOURCES = {VEHAGE_SOURCE, *VEH_SOURCES.values()}
# road_tf_vehage fuel code -> our class. The two hybrid codes are summed.
VEHAGE_FUEL = {"PET": "PETROL", "DIE": "DIESEL", "ELC": "BEV",
               "ELC_PET_HYB_PI": "HYBRID", "ELC_DIE_HYB_PI": "HYBRID"}
VEHAGE_ALL_FUELS = ["PET", "DIE", "ELC", "ELC_PET_HYB_PI", "ELC_DIE_HYB_PI", "PET_ETH_FLX",
                    "CNG", "LPG", "BIFUEL_PET_LPG", "BIFUEL_PET_CNG", "OTH"]
# Petrol + diesel + whatever else is reported may reach this share of the
# total and still be read as "the other drivetrains are counted elsewhere".
FUELS_COMPLETE = 0.97
EUROSTAT_FROM = 2015

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


def _decode(doc: dict) -> tuple[list[str], dict[tuple, float]]:
    """JSON-stat 2.0 -> (dimension ids, {(code per dimension): value})."""
    ids, size = doc["id"], doc["size"]
    names = [{pos: code for code, pos in doc["dimension"][k]["category"]["index"].items()} for k in ids]
    out = {}
    for flat, v in doc["value"].items():
        if v is None:
            continue
        f, pos = int(flat), []
        for s in reversed(size):
            pos.append(f % s)
            f //= s
        out[tuple(names[i][p] for i, p in enumerate(reversed(pos)))] = v
    return ids, out


def _mkm(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def parse_vehage(doc: dict, geo: dict) -> list[dict]:
    """road_tf_vehage -> rows: ALL for every country-year, the fuels only where
    the table shows petrol and diesel are not hiding the other drivetrains."""
    ids, cells = _decode(doc)
    i = {k: ids.index(k) for k in ("mot_nrg", "age", "vehicle", "geo", "time")}
    by: dict[tuple, dict[str, float]] = {}
    for key, v in cells.items():
        if key[i["vehicle"]] == "CAR" and key[i["age"]] == "TOTAL" and key[i["geo"]] in geo:
            by.setdefault((geo[key[i["geo"]]], int(key[i["time"]])), {})[key[i["mot_nrg"]]] = v
    rows = []
    for (country, year), f in sorted(by.items()):
        total = f.get("TOTAL")
        if not total or total <= 0 or year < EUROSTAT_FROM:
            continue
        rows.append({"country": country, "year": year, "fuel": "ALL", "km_per_car": "",
                     "total_mkm": _mkm(total), "source": VEHAGE_SOURCE, "notes": ""})
        reported = sum(f.get(c, 0) for c in VEHAGE_ALL_FUELS)
        separate = f.get("ELC", 0) > 0 or reported < FUELS_COMPLETE * total
        if not separate:
            continue   # petrol / diesel may include the hybrids: ALL only
        classes: dict[str, float] = {}
        for code, cls in VEHAGE_FUEL.items():
            if f.get(code, 0) > 0:
                classes[cls] = classes.get(cls, 0) + f[code]
        for cls in ("PETROL", "DIESEL", "BEV", "HYBRID"):
            if cls in classes:
                rows.append({"country": country, "year": year, "fuel": cls, "km_per_car": "",
                             "total_mkm": _mkm(classes[cls]), "source": VEHAGE_SOURCE,
                             "notes": "full and plug-in hybrids together" if cls == "HYBRID" else ""})
    return rows


def parse_veh(doc: dict, geo: dict) -> list[dict]:
    """road_tf_veh -> ALL rows (passenger cars, all fuels), one per country-year,
    from the best registration concept that country reports."""
    ids, cells = _decode(doc)
    i = {k: ids.index(k) for k in ("mot_nrg", "regisveh", "vehicle", "geo", "time")}
    best: dict[tuple, tuple[int, str, float]] = {}
    order = list(VEH_SOURCES)
    for key, v in cells.items():
        concept = key[i["regisveh"]]
        if (key[i["vehicle"]] != "CAR" or key[i["mot_nrg"]] != "TOTAL" or concept not in VEH_SOURCES
                or key[i["geo"]] not in geo or v <= 0 or int(key[i["time"]]) < EUROSTAT_FROM):
            continue
        k = (geo[key[i["geo"]]], int(key[i["time"]]))
        rank = order.index(concept)
        if k not in best or rank < best[k][0]:
            best[k] = (rank, concept, v)
    return [{"country": c, "year": y, "fuel": "ALL", "km_per_car": "", "total_mkm": _mkm(v),
             "source": VEH_SOURCES[concept],
             "notes": "km abroad not included" if concept == "TERNAT_REGNAT" else ""}
            for (c, y), (_, concept, v) in sorted(best.items())]


def read_existing(path: Path = OUT_PATH) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def upsert(new_rows: list[dict], existing: list[dict], owned_sources) -> list[dict]:
    """Replace this script's own rows, keep everyone else's. A fetched row
    never overwrites a row of another source with the same key, and among the
    new rows the first one for a key wins (callers pass the preferred source
    first)."""
    owned = {owned_sources} if isinstance(owned_sources, str) else set(owned_sources)
    key = lambda r: (r["country"], int(r["year"]), r["fuel"])  # noqa: E731
    out = [r for r in existing if r.get("source") not in owned]
    taken = {key(r) for r in out}
    for r in new_rows:
        if key(r) not in taken:
            taken.add(key(r))
            out.append(r)
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


def fetch_eurostat(table: str) -> dict:
    import requests
    resp = requests.get(EUROSTAT_API.format(table), timeout=180)
    resp.raise_for_status()
    return resp.json()


def main() -> int:
    from fetch_fleet_age import GEO

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ssb-file", help="saved SSB 12577 JSON-stat2 response")
    ap.add_argument("--vehage-file", help="saved Eurostat road_tf_vehage JSON")
    ap.add_argument("--veh-file", help="saved Eurostat road_tf_veh JSON")
    ap.add_argument("--dry-run", action="store_true", help="print a summary, write nothing")
    args = ap.parse_args()
    load = lambda f, get: json.loads(Path(f).read_text(encoding="utf-8")) if f else get()  # noqa: E731

    ssb = parse_ssb(load(args.ssb_file, fetch_ssb))
    vehage = parse_vehage(load(args.vehage_file, lambda: fetch_eurostat(VEHAGE_TABLE)), GEO)
    veh = parse_veh(load(args.veh_file, lambda: fetch_eurostat(VEH_TABLE)), GEO)
    if not ssb or not vehage:
        raise SystemExit("a source returned no usable rows: refusing to drop its countries from the file")
    # Order = precedence: national office, then the by-fuel table, then totals only.
    rows = upsert(ssb + vehage + veh, read_existing(), {SSB_SOURCE, *EUROSTAT_SOURCES})
    countries = sorted({r["country"] for r in rows})
    with_fuels = sorted({r["country"] for r in rows if r["fuel"] in ("PETROL", "DIESEL")})
    print(f"{len(rows)} rows, {len(countries)} countries; by fuel: {', '.join(with_fuels)}")
    print("totals only: " + ", ".join(c for c in countries if c not in with_fuels))
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
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
