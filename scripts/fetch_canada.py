#!/usr/bin/env python3
"""
Fetch Canada new passenger-car registration data from the Statistics Canada
(StatCan) Web Data Service (WDS) JSON API, cube **20-10-0024 "New motor vehicle
registrations"** (productId ``20100024``), and upsert ``data/Canada.csv``.

Usage
-----
    python scripts/fetch_canada.py [--latest-n N] [--variant all|Whole|Non-Passenger]
                                   [--product-id PID] [--list-members] [--dry-run]

Output files / variants
-----------------------
    data/Canada.csv                <- variant=Whole          (Vehicle type = Passenger cars)
    data/Canada_Non-Passenger.csv  <- variant=Non-Passenger  (Vehicle type = Trucks)

`Whole` is passenger cars (cars proper, which in Canada have collapsed to a
~45-65k/quarter minority as buyers moved to light trucks/SUVs — hence DIESEL is
~0, the diesel passenger car being near-extinct); this matches the historical
data/Canada.csv. `Non-Passenger` is StatCan's "Trucks" Vehicle type, which is a
catch-all for *everything that is not a passenger car* — minivans, SUVs,
pickups, vans, light AND heavy trucks, and buses. It is intentionally NOT named
"Trucks"/"HDV" (which would imply heavy goods vehicles only); the mixed-bag
nature is the point. See the VARIANTS map for the full rationale. Both variants
are unauthenticated reads of the same cube; only the Vehicle type member differs.

Cadence
-------
StatCan cube 20-10-0024 is **quarterly**. The repo's convention (inherited from
the legacy hand-maintained file) records each quarter under its *middle* month:
Q1 -> ``YYYY-02``, Q2 -> ``YYYY-05``, Q3 -> ``YYYY-08``, Q4 -> ``YYYY-11``. We
derive the middle month from the StatCan reference period regardless of whether
StatCan stamps a quarter with its first or last month, via
``((month - 1) // 3) * 3 + 2``. ``time_interval`` is therefore ``quarterly``.

The API (WDS REST)
------------------
Base: https://www150.statcan.gc.ca/t1/wds/rest

We make two calls, no auth:

1. ``getCubeMetadata`` (POST ``[{"productId": 20100024}]``) returns the cube's
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
from datetime import date
from pathlib import Path

import requests

WDS_BASE = "https://www150.statcan.gc.ca/t1/wds/rest"
PRODUCT_ID = 20100024            # cube 20-10-0024 "New motor vehicle registrations"
SOURCE = "150.statcan.gc.ca"
CSV_PATH = "data/Canada.csv"
GEOGRAPHY = "Canada"
DEFAULT_LATEST_N = 16           # 4 years of quarters; StatCan revises recent ones

# Variant -> StatCan "Vehicle type" member. The cube's Vehicle type dimension
# only splits Passenger cars vs Trucks (North American classification), so we
# can't reproduce the EU-category variants (Vans=N1, HDV=N2/N3, Buses=M2/M3)
# the other countries use. Instead we expose StatCan's "Trucks" bucket as its
# own honestly-named catch-all variant: it is *everything that is not a
# passenger car* — minivans, SUVs, pickups, vans, light AND heavy trucks, and
# buses lumped together. It is deliberately NOT called "HDV"/"Trucks", which
# would imply heavy goods vehicles; "Non-Passenger" makes the mixed-bag nature
# clear. It is an orphan variant (not comparable to other countries' HDV/Vans/
# Buses and not in the Builder aggregation), but it renders its own trajectory.
VARIANTS = {
    "Whole": "Passenger cars",
    "Non-Passenger": "Trucks",
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
        for m in pool:
            if "unit" in m["memberNameEn"].lower():
                return m
    for m in pool:
        ml = m["memberNameEn"].strip().lower()
        if ml.startswith("total") or ml.startswith("all") or ml.startswith("units"):
            return m
    return pool[0]


def _leaf_members(members: list) -> list:
    parent_ids = {m["parentMemberId"] for m in members if m.get("parentMemberId")}
    return [m for m in members if m["memberId"] not in parent_ids]


def build_coordinates(meta: dict, vehicle_type: str) -> tuple[list[tuple[str, str]], str]:
    """Return ([(coordinate, column), ...], summary_str).

    Holds Geography=Canada, Vehicle type=<target>, and the total member of every
    other dimension fixed; varies Fuel type across its leaf members.
    """
    dims = sorted(meta["dimension"], key=lambda d: d["dimensionPositionId"])
    n_dims = len(dims)

    fixed: dict[int, int] = {}      # positionId -> memberId
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
            m = _member_by_name(members, vehicle_type, exact=True)
            fixed[pos] = m["memberId"]
            summary_lines.append(f"  dim {pos} {name!r} -> {m['memberNameEn']!r}")
        elif "fuel" in nl:
            fuel_pos = pos
            fuel_leaves = _leaf_members(members)
            mapped = [(lf["memberNameEn"], map_fuel(lf["memberNameEn"])) for lf in fuel_leaves]
            summary_lines.append(f"  dim {pos} {name!r} -> {len(fuel_leaves)} leaves:")
            for nm, col in mapped:
                summary_lines.append(f"      {nm!r} -> {col}")
        else:
            m = _choose_total_member(members, name)
            fixed[pos] = m["memberId"]
            summary_lines.append(f"  dim {pos} {name!r} -> {m['memberNameEn']!r} (total)")

    if fuel_pos is None:
        raise RuntimeError(
            f"no Fuel type dimension in cube; dims: "
            f"{[d['dimensionNameEn'] for d in dims]}"
        )

    coords: list[tuple[str, str]] = []
    for leaf in fuel_leaves:
        positions = []
        for pos in range(1, n_dims + 1):
            if pos == fuel_pos:
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


def collect_rows(session: requests.Session, product_id: int,
                 coords: list[tuple[str, str]], latest_n: int,
                 variant: str) -> dict[str, dict]:
    payload = [
        {"productId": product_id, "coordinate": coord, "latestN": latest_n}
        for coord, _col in coords
    ]
    results = get_data(session, payload)

    periods: dict[str, dict[str, float]] = {}
    for (coord, col), item in zip(coords, results):
        if item.get("status") != "SUCCESS":
            print(f"  WARNING coordinate {coord} ({col}): status={item.get('status')} "
                  f"— skipping ({item.get('object')})")
            continue
        for dp in item["object"].get("vectorDataPoint", []):
            period = refper_to_period(dp["refPer"])
            val = dp.get("value")
            val = 0.0 if val in (None, "") else float(val)
            slot = periods.setdefault(period, {c: 0.0 for c in VALUE_COLUMNS})
            slot[col] += val

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
        vehicle_type = VARIANTS[variant]
        csv_path = variant_csv_path(variant)
        print(f"\n=== variant {variant!r} (Vehicle type = {vehicle_type!r}) -> {csv_path} ===")

        coords, summary = build_coordinates(meta, vehicle_type)
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
