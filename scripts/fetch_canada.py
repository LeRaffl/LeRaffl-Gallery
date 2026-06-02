#!/usr/bin/env python3
"""
Fetch Canada new passenger-car registration data from the Statistics Canada
(StatCan) Web Data Service (WDS) JSON API, cube **20-10-0025 "New motor vehicle
registrations"** (productId ``20100025``), and upsert ``data/Canada.csv``.

Usage
-----
    python scripts/fetch_canada.py [--latest-n N] [--variant all|Whole|Pickups|Vans]
                                   [--product-id PID] [--list-members] [--dry-run]

Output files / variants
-----------------------
    data/Canada.csv          <- variant=Whole    (Passenger cars + Multi-purpose
                                vehicles = EU class M1)
    data/Canada_Pickups.csv  <- variant=Pickups  (Pickup trucks)
    data/Canada_Vans.csv     <- variant=Vans     (minivans + cargo vans)

Cube 20-10-0025 is a LIGHT-vehicle cube; its Vehicle type members are
``Total, vehicle type | Passenger cars | Multi-purpose vehicles | Pickup trucks
| Vans`` (no heavy trucks, no buses). `Whole` is harmonised to EU class M1 —
Passenger cars + Multi-purpose vehicles (SUVs/crossovers) — so it matches how
every other country in the gallery counts "passenger cars" (which include SUVs).
`Pickups` and `Vans` are Canada-specific extra variants (see the VARIANTS map
for the footnote definitions and why they don't map onto the gallery's EU
Vans/HDV classes). All variants are unauthenticated reads of the same cube.

Coverage / definition change: the Multi-purpose-vehicle fuel split is only
available from ~2017-Q1, so the M1 Whole series starts there. Historically
Canada's Whole was Passenger-cars-only; this pipeline redefines it as M1 and
the pre-2017 passenger-cars-only rows are dropped (a one-time cleanup) to avoid
a definition seam.

Cadence
-------
StatCan cube 20-10-0025 is **quarterly**. The repo's convention (inherited from
the legacy hand-maintained file) records each quarter under its *middle* month:
Q1 -> ``YYYY-02``, Q2 -> ``YYYY-05``, Q3 -> ``YYYY-08``, Q4 -> ``YYYY-11``. We
derive the middle month from the StatCan reference period regardless of whether
StatCan stamps a quarter with its first or last month, via
``((month - 1) // 3) * 3 + 2``. ``time_interval`` is therefore ``quarterly``.

The API (WDS REST)
------------------
Base: https://www150.statcan.gc.ca/t1/wds/rest

We make two calls, no auth:

1. ``getCubeMetadata`` (POST ``[{"productId": 20100025}]``) returns the cube's
   dimensions, each with its members (``memberId``, ``memberNameEn``,
   ``parentMemberId``). We use it to discover, by name, the member IDs for
   Geography=Canada, Vehicle type=<target>, the "total" member of every other
   dimension (Statistics=Units, etc.), and the **leaf** members of the Fuel
   type dimension. Working from the live metadata means we don't hard-code
   numeric member IDs that StatCan could renumber.

2. ``getDataFromCubePidCoordAndLatestNPeriods`` (POST with one request object
   per fuel leaf) returns the latest N quarterly data points per coordinate.

A *coordinate* is 10 dot-separated member IDs in dimension-position order, with
unused trailing positions set to 0. We hold every dimension fixed except Fuel
type, which we vary across the fuel leaves.

Fuel mapping (leaf member name -> canonical column)
---------------------------------------------------
Only **leaf** fuel members are summed (aggregate members such as "All fuel
types" or "Zero-emission vehicles" are parents and are skipped, so nothing is
double-counted). ``TOTAL`` is the sum of the mapped leaves.

    BEV     <- "...battery electric..."
    PHEV    <- "...plug-in hybrid..."        (matched before plain "hybrid")
    HEV     <- "...hybrid..."                 (non-plug-in hybrid electric)
    PETROL  <- "...gasoline..."
    DIESEL  <- "...diesel..."
    OTHERS  <- "...other...", "...fuel cell...", "...hydrogen..."

An unmapped leaf raises (mirrors fetch_sweden.py's DRIV_TO_COL guard) so a new
StatCan fuel category can't silently vanish — the error prints the exact
member name to add to FUEL_RULES.

Invoked by ``.github/workflows/fetch-canada.yml`` (daily 1st-15th). The commit
step is change-gated, so steady-state runs are a no-op even though the script
always re-fetches the latest N quarters (StatCan revises recent quarters).
"""
import argparse
import csv
import os
import re
from datetime import date
from pathlib import Path

import requests

WDS_BASE = "https://www150.statcan.gc.ca/t1/wds/rest"
PRODUCT_ID = 20100025            # cube 20-10-0025 "New motor vehicle registrations"
SOURCE = "150.statcan.gc.ca"
CSV_PATH = "data/Canada.csv"
GEOGRAPHY = "Canada"
DEFAULT_LATEST_N = 16           # 4 years of quarters; StatCan revises recent ones

# Variant -> the StatCan "Vehicle type" member(s) summed into it. Cube
# 20-10-0025 is a LIGHT-vehicle cube: its Vehicle type members are
#   Total, vehicle type | Passenger cars | Pickup trucks |
#   Multi-purpose vehicles | Vans
# (no heavy trucks, no buses — so this is NOT the EU N1/N2/N3/M2/M3 split the
# other countries use). We expose two variants:
# Variant -> the StatCan "Vehicle type" member(s) summed into it. Cube
# 20-10-0025's Vehicle type members (with their StatCan footnote definitions):
#   * Passenger cars          — cars proper (no footnote)
#   * Multi-purpose vehicles  — "sport utility vehicles (SUVs) and Crossovers"
#   * Pickup trucks           — "GVWR 0-14,000 lb (classes 1, 2 and 3)"
#   * Vans                    — "all minivans and cargo vans"
#
# Whole is harmonised to EU class M1 ("passenger cars" as every other country in
# the gallery counts them — which INCLUDES SUVs/crossovers): Passenger cars +
# Multi-purpose vehicles. StatCan splits SUVs out as their own body type, so a
# Passenger-cars-only series (the cube's narrow North-American "cars proper")
# would exclude exactly the segment where Canada's BEVs sit and would not be
# comparable to the M1 series the world map / rankings use.
#
# Pickups and Vans are exposed as their own Canada-specific variants. They do
# NOT map cleanly onto the gallery's EU-anchored Vans(N1)/HDV(N2-N3): pickups
# here run up to 14,000 lb (~6.35 t, into N2), and "Vans" mixes minivans (M1)
# with cargo vans (N1). So they are documented as Canada-specific, not used in
# cross-country Vans/HDV rankings.
#
# DEFINITION CHANGE: historically (legacy sheet / pre-automation) Canada's Whole
# was Passenger cars ONLY. This pipeline redefines Whole as M1 (Passenger cars +
# Multi-purpose vehicles). The MPV fuel split is only available from ~2017, so
# the M1 Whole series starts there; pre-2017 passenger-cars-only rows are
# dropped. See docs/architecture/17-source-canada.md.
VARIANTS = {
    "Whole":   ["Passenger cars", "Multi-purpose vehicles"],   # EU M1
    "Pickups": ["Pickup trucks"],                              # Canada-specific
    "Vans":    ["Vans"],                                       # Canada-specific (minivans + cargo)
}


def variant_csv_path(variant: str) -> str:
    """Whole lives in data/Canada.csv; other variants in data/Canada_<V>.csv."""
    if variant == "Whole":
        return CSV_PATH
    return f"data/Canada_{variant}.csv"


CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL", "notes",
]
VALUE_COLUMNS = ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS"]

# Ordered (substring, column) rules. Order matters: "plug-in hybrid" must be
# tested before plain "hybrid", and the electric variants before generic words.
FUEL_RULES = [
    ("battery electric", "BEV"),
    ("plug-in hybrid", "PHEV"),
    ("plug in hybrid", "PHEV"),
    ("hybrid", "HEV"),
    ("gasoline", "PETROL"),
    ("petrol", "PETROL"),
    ("diesel", "DIESEL"),
    ("fuel cell", "OTHERS"),
    ("hydrogen", "OTHERS"),
    ("other", "OTHERS"),
]

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "LeRaffl-Gallery fetch_canada (+https://github.com/leraffl/leraffl-gallery)",
}


def map_fuel(name: str) -> str:
    n = name.lower()
    for needle, col in FUEL_RULES:
        if needle in n:
            return col
    raise RuntimeError(
        f"unmapped fuel leaf {name!r} — add a rule to FUEL_RULES "
        f"(most new categories go to OTHERS)."
    )


# --------------------------------------------------------------------------- #
# WDS calls
# --------------------------------------------------------------------------- #
def _post(session: requests.Session, path: str, payload) -> list:
    url = f"{WDS_BASE}/{path}"
    r = session.post(url, json=payload, headers=HEADERS, timeout=120)
    r.raise_for_status()
    data = r.json()
    # WDS wraps each request object in a list of {"status", "object"} results.
    if isinstance(data, dict):
        data = [data]
    return data


def get_cube_metadata(session: requests.Session, product_id: int) -> dict:
    print(f"[meta] POST getCubeMetadata productId={product_id}")
    res = _post(session, "getCubeMetadata", [{"productId": product_id}])
    item = res[0]
    if item.get("status") != "SUCCESS":
        raise RuntimeError(f"getCubeMetadata failed: {item}")
    return item["object"]


def get_data(session: requests.Session, requests_payload: list) -> list:
    print(f"[data] POST getDataFromCubePidCoordAndLatestNPeriods "
          f"({len(requests_payload)} coordinates)")
    res = _post(session, "getDataFromCubePidCoordAndLatestNPeriods", requests_payload)
    return res


# --------------------------------------------------------------------------- #
# Metadata -> coordinates
# --------------------------------------------------------------------------- #
def _member_by_name(members: list, target: str, *, exact: bool = True) -> dict:
    tl = target.lower()
    for m in members:
        if m["memberNameEn"].strip().lower() == tl:
            return m
    if not exact:
        for m in members:
            if tl in m["memberNameEn"].strip().lower():
                return m
    names = [m["memberNameEn"] for m in members]
    raise RuntimeError(f"member {target!r} not found; available: {names}")


def _choose_total_member(members: list, dim_name: str) -> dict:
    if len(members) == 1:
        return members[0]
    roots = [m for m in members if not m.get("parentMemberId")]
    pool = roots or members
    nl = dim_name.lower()
    if "statistic" in nl:
        # The cube reports counts under e.g. "Number of vehicles" / "Units"
        # (there can also be a "Dollars" statistic we must avoid).
        for needle in ("number of vehicle", "units", "unit"):
            for m in pool:
                if needle in m["memberNameEn"].lower():
                    return m
    for m in pool:
        ml = m["memberNameEn"].strip().lower()
        if ml.startswith("total") or ml.startswith("all") or ml.startswith("units"):
            return m
    return pool[0]


def _leaf_members(members: list) -> list:
    parent_ids = {m["parentMemberId"] for m in members if m.get("parentMemberId")}
    return [m for m in members if m["memberId"] not in parent_ids]


def build_coordinates(meta: dict, vehicle_types: list[str]) -> tuple[list[tuple[str, str]], str]:
    """Return ([(coordinate, column), ...], summary_str).

    Holds Geography=Canada and the total member of every dimension other than
    Vehicle type and Fuel type fixed, then emits one coordinate for each
    (vehicle member in ``vehicle_types``) x (fuel leaf). A variant that spans
    several vehicle members (e.g. Whole = Passenger cars + Multi-purpose
    vehicles) therefore produces several coordinates per fuel column;
    ``collect_rows`` sums them into that column automatically.
    """
    dims = sorted(meta["dimension"], key=lambda d: d["dimensionPositionId"])
    n_dims = len(dims)

    fixed: dict[int, int] = {}      # positionId -> memberId (non-vehicle, non-fuel dims)
    vehicle_pos: int | None = None
    vehicle_members: list[dict] = []
    fuel_pos: int | None = None
    fuel_leaves: list[dict] = []
    summary_lines = []

    for d in dims:
        pos = d["dimensionPositionId"]
        name = d["dimensionNameEn"]
        nl = name.lower()
        members = d["member"]
        if "geograph" in nl:
            m = _member_by_name(members, GEOGRAPHY)
            fixed[pos] = m["memberId"]
            summary_lines.append(f"  dim {pos} {name!r} -> {m['memberNameEn']!r}")
        elif "vehicle" in nl:
            vehicle_pos = pos
            vehicle_members = [_member_by_name(members, vt, exact=True) for vt in vehicle_types]
            summary_lines.append(
                f"  dim {pos} {name!r} -> {[m['memberNameEn'] for m in vehicle_members]}")
        elif "fuel" in nl:
            fuel_pos = pos
            fuel_leaves = _leaf_members(members)
            summary_lines.append(f"  dim {pos} {name!r} -> {len(fuel_leaves)} leaves:")
            for lf in fuel_leaves:
                summary_lines.append(f"      {lf['memberNameEn']!r} -> {map_fuel(lf['memberNameEn'])}")
        else:
            m = _choose_total_member(members, name)
            fixed[pos] = m["memberId"]
            summary_lines.append(f"  dim {pos} {name!r} -> {m['memberNameEn']!r} (total)")

    if fuel_pos is None or vehicle_pos is None:
        raise RuntimeError(
            f"missing Vehicle type / Fuel type dimension; dims: "
            f"{[d['dimensionNameEn'] for d in dims]}"
        )

    coords: list[tuple[str, str]] = []
    for vm in vehicle_members:
        for leaf in fuel_leaves:
            positions = []
            for pos in range(1, n_dims + 1):
                if pos == vehicle_pos:
                    positions.append(str(vm["memberId"]))
                elif pos == fuel_pos:
                    positions.append(str(leaf["memberId"]))
                else:
                    positions.append(str(fixed[pos]))
            positions += ["0"] * (10 - n_dims)
            coords.append((".".join(positions), map_fuel(leaf["memberNameEn"])))

    return coords, "\n".join(summary_lines)


# --------------------------------------------------------------------------- #
# Data -> rows
# --------------------------------------------------------------------------- #
def refper_to_period(ref_per: str) -> str:
    """'2025-07-01' (StatCan quarter stamp) -> '2025-08' (quarter middle month)."""
    year = int(ref_per[:4])
    month = int(ref_per[5:7])
    middle = ((month - 1) // 3) * 3 + 2     # 1..3->2, 4..6->5, 7..9->8, 10..12->11
    return f"{year}-{middle:02d}"


def _norm_coord(coord: str) -> str:
    """Drop trailing zero (padding) positions so request and echoed coordinates
    compare equal regardless of how WDS pads them: '1.5.2.1.0.0.0.0.0.0' -> '1.5.2.1'."""
    return re.sub(r"(?:\.0)+$", "", coord)


def collect_rows(session: requests.Session, product_id: int,
                 coords: list[tuple[str, str]], latest_n: int,
                 variant: str) -> dict[str, dict]:
    payload = [
        {"productId": product_id, "coordinate": coord, "latestN": latest_n}
        for coord, _col in coords
    ]
    results = get_data(session, payload)

    # WDS does NOT guarantee the response array is in request order, so match
    # each result back to its column via the coordinate it echoes — never by
    # list position (that scrambles fuels across columns).
    coord_to_col = {_norm_coord(coord): col for coord, col in coords}

    periods: dict[str, dict[str, float]] = {}
    matched = 0
    for item in results:
        if item.get("status") != "SUCCESS":
            print(f"  WARNING result status={item.get('status')} — skipping "
                  f"({item.get('object')})")
            continue
        obj = item["object"]
        col = coord_to_col.get(_norm_coord(str(obj.get("coordinate", ""))))
        if col is None:
            print(f"  WARNING unmatched coordinate {obj.get('coordinate')!r} — skipping")
            continue
        matched += 1
        for dp in obj.get("vectorDataPoint", []):
            period = refper_to_period(dp["refPer"])
            val = dp.get("value")
            val = 0.0 if val in (None, "") else float(val)
            slot = periods.setdefault(period, {c: 0.0 for c in VALUE_COLUMNS})
            slot[col] += val
    if matched != len(coords):
        print(f"  WARNING matched {matched}/{len(coords)} coordinates by echoed key")

    rows: dict[str, dict] = {}
    for period, cols in periods.items():
        total = sum(cols.values())
        if total == 0.0:
            continue
        rows[period] = {
            "period": period,
            "time_interval": "quarterly",
            "variant": variant,
            "source": SOURCE,
            **{c: cols[c] for c in VALUE_COLUMNS},
            "TOTAL": total,
            "notes": "",
        }
    return rows


# --------------------------------------------------------------------------- #
# CSV upsert (mirrors fetch_sweden.py)
# --------------------------------------------------------------------------- #
def upsert_csv(csv_path: str, new_rows: dict) -> tuple[int, int]:
    existing: dict = {}
    if os.path.exists(csv_path):
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing[(row["period"], row["variant"])] = row

    added = updated = 0
    for period, new_row in sorted(new_rows.items()):
        variant = new_row["variant"]
        key = (period, variant)
        if key not in existing:
            existing[key] = new_row
            added += 1
            print(f"  + {variant} {period}")
        else:
            old = existing[key]
            for col in VALUE_COLUMNS:
                old_val = float(old.get(col) or 0)
                new_val = float(new_row[col] or 0)
                if old_val > 100 and abs(new_val - old_val) / old_val > 0.5:
                    print(
                        f"  WARNING {variant} {period} {col}: existing={old_val:.0f}, "
                        f"new={new_val:.0f} — diff >50%, please verify"
                    )
            if not new_row.get("notes"):
                new_row["notes"] = old.get("notes", "")
            existing[key] = {**old, **new_row}
            updated += 1

    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for key in sorted(existing.keys(), key=lambda k: (k[1], k[0])):
            writer.writerow(existing[key])

    return added, updated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-n", type=int, default=DEFAULT_LATEST_N,
                        help=f"quarters to fetch per fuel (default {DEFAULT_LATEST_N}). "
                             f"Use a large value once to seed a new variant's full history.")
    parser.add_argument("--variant", default="all", choices=["all", *VARIANTS],
                        help="Which variant(s) to fetch (default: all). "
                             f"Variants: {', '.join(VARIANTS)}.")
    parser.add_argument("--product-id", type=int, default=PRODUCT_ID,
                        help=f"StatCan cube productId (default {PRODUCT_ID}).")
    parser.add_argument("--force", action="store_true",
                        help="Accepted for parity with other fetchers; this fetcher always "
                             "re-fetches the latest N quarters and is commit-gated downstream.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and print, but do not write the CSV.")
    parser.add_argument("--list-members", action="store_true",
                        help="Print every dimension and all its members, then exit. Use this "
                             "to see what the cube exposes (e.g. which Vehicle type members "
                             "exist) without fetching data.")
    args = parser.parse_args()

    session = requests.Session()
    meta = get_cube_metadata(session, args.product_id)

    if args.list_members:
        for d in sorted(meta["dimension"], key=lambda x: x["dimensionPositionId"]):
            print(f"\nDimension {d['dimensionPositionId']}: {d['dimensionNameEn']!r} "
                  f"({len(d['member'])} members)")
            for m in d["member"]:
                indent = "    " if m.get("parentMemberId") else "  "
                print(f"{indent}[{m['memberId']}] {m['memberNameEn']}")
        return

    selected = list(VARIANTS) if args.variant == "all" else [args.variant]
    for variant in selected:
        vehicle_types = VARIANTS[variant]
        csv_path = variant_csv_path(variant)
        print(f"\n=== variant {variant!r} (Vehicle type = {vehicle_types}) -> {csv_path} ===")

        coords, summary = build_coordinates(meta, vehicle_types)
        print("[plan] fixed dimensions and fuel leaves:")
        print(summary)

        rows = collect_rows(session, args.product_id, coords, args.latest_n, variant)
        if not rows:
            print("no non-zero quarters in response")
            continue
        print(f"parsed {len(rows)} quarters ({min(rows)} .. {max(rows)})")

        if args.dry_run:
            for period in sorted(rows):
                r = rows[period]
                print(f"  {period}  " + "  ".join(f"{c}={r[c]:.0f}" for c in VALUE_COLUMNS)
                      + f"  TOTAL={r['TOTAL']:.0f}")
            print("(dry-run: CSV not written)")
            continue

        added, updated = upsert_csv(csv_path, rows)
        print(f"{added} added, {updated} updated -> {csv_path}")


if __name__ == "__main__":
    main()
