#!/usr/bin/env python3
"""
Fetch Norway's stock of VANS, TRUCKS and BUSES by fuel from Statistics Norway
and upsert it into ``fleet/fleet_initial.csv`` (variants ``Vans``, ``HDV``,
``Buses``).

The first country whose fleet goes beyond passenger cars: the pilot for
docs/architecture/37-fleet-data-harmonization.md section 8. Norway is the
right pilot because one office publishes everything the model needs per
vehicle class - stock by fuel (here), kilometres by fuel (SSB 12577,
scripts/fetch_fleet_mileage.py) - and the registration side already has
``data/Norway_{Vans,HDV,Buses}.csv`` with fitted curves.

Source
------
SSB table 11823 "Registered vehicles, by region, euro classes, type of fuel"
(open API, no key): https://data.ssb.no/api/v0/en/table/11823 . Whole country,
summed over the euro classes, stock at 31 December, 2016 onwards.

Scope (SSB vehicle group -> variant, EU class)::

    Varebil  "Vans"     -> Vans   N1, goods vehicles up to 3.5 t
    Lastebil "Lorries"  -> HDV    N2 + N3, goods vehicles over 3.5 t
    Buss     "Buses"    -> Buses  M2 + M3

"Combined vehicles" (Kombibil, a class no longer registered, about 7,500 left)
are in neither. The passenger-car rows of the same table are identical to the
existing ``Whole`` rows (checked: 945,182 battery cars at the end of 2025) and
are NOT written here: this script owns only the three variants above.

Mapping (SSB fuel -> column)::

    Electricity                          BEV
    Petrol / Diesel hybrid, chargeable   PHEV
    Petrol / Diesel hybrid, non-charg.   HEV
    Petrol                               PETROL
    Diesel                               DIESEL
    Gas                                  GAS
    Paraffin, Hydrogen, Other fuel       OTHERS
    (sum)                                TOTAL

Annual, idempotent, no render: run by ``refresh-fleet-data.yml``.

Usage
-----
    python scripts/fetch_fleet_norway.py [--file PATH] [--dry-run]
"""
from __future__ import annotations

import argparse
import itertools
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLEET_CSV = ROOT / "fleet" / "fleet_initial.csv"
COUNTRY = "Norway"
SOURCE = "SSB 11823 (31 Dec)"
URL = "https://data.ssb.no/api/v0/en/table/11823"

FLEET_COLUMNS = ["country", "variant", "year", "source", "BEV", "PHEV", "EREV", "HEV", "MHEV",
                 "PETROL", "DIESEL", "GAS", "CNG", "LPG", "FLEXFUEL", "ETHANOL", "OTHERS", "TOTAL", "notes"]
GROUPS = {"Varebil4": "Vans", "Lastebil6": "HDV", "Buss3": "Buses"}
FUELS = {"5": "BEV", "14": "PHEV", "16": "PHEV", "15": "HEV", "17": "HEV",
         "1": "PETROL", "2": "DIESEL", "4": "GAS", "3": "OTHERS", "13": "OTHERS", "6": "OTHERS"}
NOTES = {"Vans": "N1 (SSB Varebil); combined vehicles (Kombibil) not included",
         "HDV": "N2+N3 (SSB Lastebil)", "Buses": "M2+M3 (SSB Buss)"}
QUERY = {"query": [
    {"code": "Region", "selection": {"filter": "item", "values": ["0"]}},
    {"code": "DrivstoffType", "selection": {"filter": "all", "values": ["*"]}},
    {"code": "ContentsCode", "selection": {"filter": "item", "values": list(GROUPS)}},
], "response": {"format": "json-stat2"}}


def parse(doc: dict) -> list[dict]:
    """JSON-stat2 -> one row per (variant, year). A fuel the table does not
    list for a group stays blank; a listed fuel with no vehicles is 0."""
    ids, size = doc["id"], doc["size"]
    order = {k: sorted(doc["dimension"][k]["category"]["index"],
                       key=doc["dimension"][k]["category"]["index"].get) for k in ids}
    cells: dict[tuple, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for n, pos in enumerate(itertools.product(*[range(s) for s in size])):
        key = {k: order[k][p] for k, p in zip(ids, pos)}
        v = doc["value"][n]
        variant, col = GROUPS.get(key.get("ContentsCode")), FUELS.get(key.get("DrivstoffType"))
        if v is None or not variant or not col:
            continue
        cells[(variant, int(key["Tid"]))][col] += v
    rows = []
    for (variant, year), f in sorted(cells.items()):
        total = sum(f.values())
        if total <= 0:
            continue
        row = {c: "" for c in FLEET_COLUMNS}
        row.update(country=COUNTRY, variant=variant, year=year, source=SOURCE,
                   TOTAL=int(round(total)), notes=NOTES[variant],
                   **{c: int(round(v)) for c, v in f.items()})
        rows.append(row)
    return rows


def line(row: dict) -> str:
    return ",".join(str(row[c]) for c in FLEET_COLUMNS)


def upsert(rows: list[dict], path: Path = FLEET_CSV) -> tuple[int, int]:
    """Line-level upsert keyed (country, variant, year). Only this script's
    variants of Norway are touched; every other line is kept byte for byte."""
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    new = {(r["variant"], str(r["year"])): line(r) for r in rows}
    out, seen, changed = [], set(), 0
    for ln in lines:
        c = ln.split(",")
        key = (c[1], c[2]) if len(c) > 3 and c[0] == COUNTRY and c[1] in GROUPS.values() else None
        if key and key in new:
            seen.add(key)
            changed += ln != new[key]
            out.append(new[key])
        else:
            out.append(ln)
    added = [new[k] for k in sorted(new) if k not in seen]
    if added:
        while out and out[-1] == "":
            out.pop()
        out += added + [""]
    result = "\n".join(out)
    if result != text:
        path.write_text(result, encoding="utf-8")
    return changed, len(added)


def fetch() -> dict:
    import requests
    resp = requests.post(URL, json=QUERY, timeout=120)
    resp.raise_for_status()
    return resp.json()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", help="parse a saved SSB 11823 JSON-stat2 response")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    rows = parse(json.loads(Path(args.file).read_text(encoding="utf-8")) if args.file else fetch())
    if not rows:
        raise SystemExit("SSB returned no usable rows: refusing to touch the file")
    for v in GROUPS.values():
        last = max((r for r in rows if r["variant"] == v), key=lambda r: r["year"])
        print(f"{v:6s} {last['year']}: total {last['TOTAL']:,}  BEV {last['BEV']:,}  DIESEL {last['DIESEL']:,}")
    if args.dry_run:
        return 0
    changed, added = upsert(rows)
    print(f"[write] fleet/fleet_initial.csv: {changed} rows updated, {added} added")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
