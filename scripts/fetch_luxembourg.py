#!/usr/bin/env python3
"""
Fetch Luxembourg new-vehicle registration data from lustat.statec.lu (STATEC's
.Stat Suite SDMX endpoint) and upsert per-variant CSVs under data/.

Usage
-----
    python scripts/fetch_luxembourg.py [--variant {whole,vans,hdv,all}] [--force]

Output files
------------
    data/Luxembourg.csv       <- variant=Whole (VEHICLE_TYPE=CAR)
    data/Luxembourg_Vans.csv  <- variant=Vans  (VEHICLE_TYPE=VAN)
    data/Luxembourg_HDV.csv   <- variant=HDV   (VEHICLE_TYPE=TRUCK+BUS+ROADTRAC)

All three slices come from dataflow DF_D6122 — "Number of new road vehicles
registrations by type of vehicle and fuel" (agency LU1, version 1.1), filtered
to OPERATION=N (new registration). The script is invoked by
.github/workflows/fetch-luxembourg.yml on a daily cron (1st-15th) and via manual
workflow_dispatch. When it produces changes, the workflow commits each touched
CSV and triggers render-country.yml for the corresponding variant.

Full pipeline context — SDMX key layout, the MOTOR_ENERGY hierarchy trap, the
fuel mapping, why Used Imports is NOT available, schedule and maintenance
recipes — lives in docs/architecture/21-source-luxembourg.md. Read that before
changing VARIANTS, MOTOR_ENERGY_LEAVES, or the column mapping.

Brief recap (so the script reads on its own):

* lustat.statec.lu serves SDMX 2.1 REST. We hit the data endpoint with an
  SDMX-CSV (labels=id) Accept header and dimensionAtObservation=AllDimensions,
  so every observation row carries its full dimension key — easy to parse with
  csv.DictReader, no JSON pivot walking.
* The DSD (DSD_VEH) has 13 dimensions. We pin REF_AREA=LU, FREQ=M, MEASURE=VEH,
  OPERATION=N, VEHICLE_TYPE per variant, and request the MOTOR_ENERGY leaf codes
  explicitly. Everything else is left open and resolves to _Z (not applicable).
* MOTOR_ENERGY hierarchy trap: if you leave MOTOR_ENERGY blank the API also
  returns the _T total AND the parent aggregates ELC_PET_HYB / ELC_DIE_HYB
  (each = its PLUGIN + NOTPLUGIN children), so hybrids get counted twice. We
  dodge this by requesting only the LEAF codes (MOTOR_ENERGY_LEAVES).
* Fuel mapping (lustat code -> canonical column):
      ELC                                       -> BEV
      ELC_PET_HYB_PLUGIN + ELC_DIE_HYB_PLUGIN   -> PHEV
      ELC_PET_HYB_NOTPLUGIN + ELC_DIE_HYB_NOTPLUGIN -> HEV
      PET                                       -> PETROL
      DIE                                       -> DIESEL
      OTH + NONE                                -> OTHERS
* Upsert preserves unchanged historical rows verbatim (same source/notes); it
  only rewrites a period when a fuel count actually differs. That keeps the
  curated 2010+ history (some of it ACEA-sourced) stable and restates only the
  months where lustat now disagrees.
"""
import argparse
import csv
import os
from datetime import date
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# SDMX data endpoint. dimensionAtObservation=AllDimensions => flat one-row-per-obs
# SDMX-CSV; labels=id keeps machine codes (LU, ELC, ...) instead of localised text.
BASE = "https://lustat.statec.lu/rest/data/LU1,DF_D6122,1.1/"

# DSD_VEH dimension order. The data key is these 13 fields joined by ".".
DIMENSIONS = [
    "REF_AREA", "FREQ", "MEASURE", "VEHICLE_TYPE", "MOTOR_CAPACITY", "BRAND",
    "MASS", "MOTOR_ENERGY", "AGE_CL", "OPERATION", "COLOR", "LENGTHREG",
    "TABLE_ID",
]

# Leaf fuel codes only — see the MOTOR_ENERGY hierarchy-trap note in the module
# docstring. Requesting these explicitly excludes _T and the ELC_*_HYB parents.
MOTOR_ENERGY_LEAVES = [
    "ELC",
    "ELC_PET_HYB_PLUGIN", "ELC_DIE_HYB_PLUGIN",
    "ELC_PET_HYB_NOTPLUGIN", "ELC_DIE_HYB_NOTPLUGIN",
    "PET", "DIE", "OTH", "NONE",
]

# Each variant: which VEHICLE_TYPE code(s) to pull and where to write it.
# Whole keeps the canonical filename (no suffix) — that's the convention for the
# country's "default" slice and what the gallery's world-map + aggregates pick up.
VARIANTS = {
    "Whole": {"vehicle_types": ["CAR"],                    "csv": "data/Luxembourg.csv"},
    "Vans":  {"vehicle_types": ["VAN"],                    "csv": "data/Luxembourg_Vans.csv"},
    "HDV":   {"vehicle_types": ["TRUCK", "BUS", "ROADTRAC"], "csv": "data/Luxembourg_HDV.csv"},
}

# Short, stable source string (matches the pattern other countries use:
# pxdata.stat.fi, duurzamemobiliteit.databank.nl, ...). The dataflow id goes in
# the per-row `notes` column for debugging.
SOURCE = "lustat.statec.lu"

# Canonical columns for Luxembourg CSVs (no FLEXFUEL — matches the existing
# data/Luxembourg.csv layout).
CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL", "notes",
]

# Fuel columns compared when deciding whether an existing row changed.
FUEL_COLUMNS = ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL"]

HTTP_HEADERS = {
    "Accept": "application/vnd.sdmx.data+csv;labels=id",
    "User-Agent": "LeRaffl-Gallery/1.0 (BEV trajectory gallery; lustat fetcher)",
}


def build_key(vehicle_types: list[str]) -> str:
    """Build the SDMX data key for the given VEHICLE_TYPE code(s).

    Multiple vehicle types (HDV) are combined with '+' in the one dimension
    position; the API returns a separate observation row per type, which the
    parser sums per period.
    """
    fixed = {
        "REF_AREA": "LU",
        "FREQ": "M",
        "MEASURE": "VEH",
        "VEHICLE_TYPE": "+".join(vehicle_types),
        "MOTOR_ENERGY": "+".join(MOTOR_ENERGY_LEAVES),
        "OPERATION": "N",
    }
    return ".".join(fixed.get(d, "") for d in DIMENSIONS)


def fetch_variant(variant: str, session: requests.Session) -> list[dict]:
    """Return the full SDMX-CSV observation rows (one dict per observation)."""
    key = build_key(VARIANTS[variant]["vehicle_types"])
    url = f"{BASE}{key}?dimensionAtObservation=AllDimensions"
    print(f"[{variant}] GET {url}")
    r = session.get(url, headers=HTTP_HEADERS, timeout=60)
    r.raise_for_status()
    return list(csv.DictReader(r.text.splitlines()))


def parse_rows(rows: list[dict], variant: str) -> dict[str, dict]:
    """Aggregate observation rows into canonical {period: csv_row} dicts.

    Sums the MOTOR_ENERGY leaf codes into the six fuel buckets, summing across
    VEHICLE_TYPE codes too (HDV = TRUCK+BUS+ROADTRAC). Months whose every fuel
    is zero (TOTAL==0) are dropped — lustat occasionally carries an all-zero
    current month before the real figures land.
    """
    agg: dict[str, dict[str, float]] = {}
    for row in rows:
        period = row["TIME_PERIOD"]
        code = row["MOTOR_ENERGY"]
        value = float(row["OBS_VALUE"] or 0)
        bucket = agg.setdefault(period, {c: 0.0 for c in FUEL_COLUMNS})
        if code == "ELC":
            bucket["BEV"] += value
        elif code in ("ELC_PET_HYB_PLUGIN", "ELC_DIE_HYB_PLUGIN"):
            bucket["PHEV"] += value
        elif code in ("ELC_PET_HYB_NOTPLUGIN", "ELC_DIE_HYB_NOTPLUGIN"):
            bucket["HEV"] += value
        elif code == "PET":
            bucket["PETROL"] += value
        elif code == "DIE":
            bucket["DIESEL"] += value
        elif code in ("OTH", "NONE"):
            bucket["OTHERS"] += value
        else:
            print(f"[{variant}] WARNING unmapped MOTOR_ENERGY code {code!r} ({value})")

    out: dict[str, dict] = {}
    for period, fuels in agg.items():
        total = sum(fuels[c] for c in ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS"])
        if total == 0.0:
            continue
        out[period] = {
            "period": period,
            "time_interval": "monthly",
            "variant": variant,
            "source": SOURCE,
            "BEV": fuels["BEV"],
            "PHEV": fuels["PHEV"],
            "HEV": fuels["HEV"],
            "PETROL": fuels["PETROL"],
            "DIESEL": fuels["DIESEL"],
            "OTHERS": fuels["OTHERS"],
            "TOTAL": total,
            "notes": "DF_D6122 OPERATION=N",
        }
    return out


def _num(v) -> float:
    return float(v) if v not in (None, "") else 0.0


def row_changed(old: dict, new: dict) -> bool:
    """True if any fuel count differs (rounded to whole vehicles)."""
    return any(round(_num(old.get(c))) != round(_num(new[c])) for c in FUEL_COLUMNS)


def upsert_csv(csv_path: str, new_rows: dict[str, dict]) -> tuple[int, int]:
    """Upsert by period. Preserves unchanged historical rows verbatim (keeps
    their original source/notes); only rewrites a period whose fuel counts
    changed. Returns (added, updated). Warns on >50% deltas."""
    existing: dict[str, dict] = {}
    if os.path.exists(csv_path):
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing[row["period"]] = row

    added = updated = 0
    for period, new_row in sorted(new_rows.items()):
        if period not in existing:
            existing[period] = new_row
            added += 1
            print(f"  + {period}")
            continue
        old = existing[period]
        if not row_changed(old, new_row):
            continue  # identical — leave the curated row untouched
        for col in ["BEV", "PHEV", "PETROL", "DIESEL"]:
            ov, nv = _num(old.get(col)), _num(new_row[col])
            if ov > 100 and abs(nv - ov) / ov > 0.5:
                print(f"  WARNING {period} {col}: existing={ov:.0f}, new={nv:.0f} "
                      f"— diff >50%, please verify")
        existing[period] = {**old, **new_row}
        updated += 1
        print(f"  ~ {period}")

    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n",
                                extrasaction="ignore")
        writer.writeheader()
        for period in sorted(existing.keys()):
            writer.writerow(existing[period])

    return added, updated


def previous_month_period() -> str:
    """YYYY-MM for the calendar month before today (UTC)."""
    today = date.today()
    if today.month == 1:
        return f"{today.year - 1}-12"
    return f"{today.year}-{today.month - 1:02d}"


def csv_has_period(csv_path: str, period: str) -> bool:
    if not os.path.exists(csv_path):
        return False
    with open(csv_path, newline="", encoding="utf-8") as f:
        return any(row["period"] == period for row in csv.DictReader(f))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--variant", choices=["whole", "vans", "hdv", "all"], default="all",
        help="Which slice to fetch (default: all)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Skip the 'already current' early-exit check.",
    )
    args = parser.parse_args()

    aliases = {"whole": "Whole", "vans": "Vans", "hdv": "HDV"}
    targets = list(aliases.values()) if args.variant == "all" else [aliases[args.variant]]

    # Early exit per variant: skip those whose CSV already has last month's row.
    # lustat publishes around the 6th of the following month, so we poll daily
    # until the row materialises, then idempotent re-fetches produce no diff.
    if not args.force:
        prev = previous_month_period()
        current = [v for v in targets if csv_has_period(VARIANTS[v]["csv"], prev)]
        for v in current:
            print(f"[{v}] CSV already has {prev}; skipping (use --force to re-fetch).")
        targets = [v for v in targets if v not in current]
        if not targets:
            print("All requested variants are current; nothing to do.")
            return

    session = requests.Session()
    # Retry connection/read errors with exponential backoff (handles transient
    # network-unreachable failures on GitHub Actions runners).
    retry = Retry(connect=3, read=2, backoff_factor=2, raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)

    for variant in targets:
        rows = parse_rows(fetch_variant(variant, session), variant)
        print(f"[{variant}] parsed {len(rows)} non-zero months "
              f"({min(rows, default='—')} .. {max(rows, default='—')})")
        if not rows:
            continue
        added, updated = upsert_csv(VARIANTS[variant]["csv"], rows)
        print(f"[{variant}] {added} added, {updated} updated -> {VARIANTS[variant]['csv']}")


if __name__ == "__main__":
    main()
