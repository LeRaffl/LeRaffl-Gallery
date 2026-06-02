#!/usr/bin/env python3
"""
Fetch Denmark vehicle registration data from the Statistics Denmark
(Danmarks Statistik) public StatBank API, table BIL53, and upsert
per-variant CSVs under data/.

Usage
-----
    python scripts/fetch_denmark.py [--variant {whole,private,industry,hdv,vans,all}] [--force]

Output files
------------
    data/Denmark.csv          <- variant=Whole     (Passenger cars,   terms=Total)
    data/Denmark_Private.csv  <- variant=Private   (Passenger cars,   terms=In households)
    data/Denmark_Industry.csv <- variant=Industry  (Passenger cars,   terms=In industries)
    data/Denmark_HDV.csv      <- variant=HDV       (Lorries total,    terms=Total)
    data/Denmark_Vans.csv     <- variant=Vans      (Vans total,       terms=Total)

API
---
Statbank exposes BIL53 at https://api.statbank.dk/v1/data via POST JSON.
The endpoint is public, undocumented-but-stable, and returns JSON-stat v1
(``format: "JSONSTAT"``).  Dimension codes verified against
/v1/tableinfo/BIL53 (lang=en):

    OMRÅDE   region          000 = All Denmark
    BILTYPE  type of vehicle 4000101002 Passenger cars, 4000102000 Vans,
                             4000103000 Lorries
    BRUG     terms of use    1000 Total, 1100 In households, 1200 In industries
    DRIV     propellant      20205 Petrol, 20210 Diesel, 20215 LPG, 20220 N-gas,
                             20225 Electricity, 20230 Kerosene, 20231 Hydrogen,
                             20256 Ethanol, 20258 Ethanol (yes, listed twice
                             — different sub-categories, both fold into OTHERS),
                             20232 Pluginhybrid, 20235 Other propellant
    Tid      time            YYYYMmm, starts 2018M01

Propellant mapping to the canonical CSV columns:
    BEV     <- 20225 Electricity
    PHEV    <- 20232 Pluginhybrid
    HEV     <- ""       (Statbank does not split HEV; folded into Petrol/Diesel)
    PETROL  <- 20205 Petrol
    DIESEL  <- 20210 Diesel
    OTHERS  <- 20215 + 20220 + 20230 + 20231 + 20256 + 20258 + 20235
    TOTAL   <- sum of the above (we do NOT use 20200 "Total propellant"
              because we want a TOTAL that matches the row we actually wrote.)

The script is invoked by .github/workflows/fetch-denmark.yml daily on the
1st–15th of each month at 05:15 UTC. Early-exit per variant skips work once
the previous calendar month is already in the CSV, so the polling stops
naturally once Statbank publishes the new month.
"""
import argparse
import csv
import json
import os
import sys
from datetime import date
from pathlib import Path

import requests

API_URL = "https://api.statbank.dk/v1/data"
SOURCE = "api.statbank.dk (BIL53)"

# Variant -> (BILTYPE code, BRUG code, output CSV path).
VARIANT_CONFIG = {
    "Whole":    {"biltype": "4000101002", "brug": "1000", "csv": "data/Denmark.csv"},
    "Private":  {"biltype": "4000101002", "brug": "1100", "csv": "data/Denmark_Private.csv"},
    "Industry": {"biltype": "4000101002", "brug": "1200", "csv": "data/Denmark_Industry.csv"},
    "HDV":      {"biltype": "4000103000", "brug": "1000", "csv": "data/Denmark_HDV.csv"},
    "Vans":     {"biltype": "4000102000", "brug": "1000", "csv": "data/Denmark_Vans.csv"},
}

# Propellant code -> canonical column. Multiple codes can map to OTHERS.
DRIV_TO_COL = {
    "20205": "PETROL",
    "20210": "DIESEL",
    "20225": "BEV",
    "20232": "PHEV",
    "20215": "OTHERS",
    "20220": "OTHERS",
    "20230": "OTHERS",
    "20231": "OTHERS",
    "20256": "OTHERS",
    "20258": "OTHERS",
    "20235": "OTHERS",
}
DRIV_CODES = list(DRIV_TO_COL.keys())

CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "FLEXFUEL",
    "OTHERS", "TOTAL", "notes",
]


def fetch_variant(variant: str, session: requests.Session) -> dict:
    cfg = VARIANT_CONFIG[variant]
    body = {
        "table": "BIL53",
        "format": "JSONSTAT",
        "lang": "en",
        "variables": [
            {"code": "OMRÅDE",  "values": ["000"]},
            {"code": "BILTYPE", "values": [cfg["biltype"]]},
            {"code": "BRUG",    "values": [cfg["brug"]]},
            {"code": "DRIV",    "values": DRIV_CODES},
            {"code": "Tid",     "values": ["*"]},
        ],
    }
    print(f"[{variant}] POST {API_URL}  BILTYPE={cfg['biltype']} BRUG={cfg['brug']}")
    r = session.post(API_URL, json=body, timeout=60)
    r.raise_for_status()
    return r.json()["dataset"]


def tid_to_period(tid: str) -> str:
    """'2018M01' -> '2018-01'."""
    if len(tid) != 7 or tid[4] != "M":
        raise ValueError(f"Unrecognised Tid label: {tid!r}")
    return f"{tid[:4]}-{tid[5:7]}"


def parse_dataset(data: dict, variant: str) -> dict[str, dict[str, float]]:
    """JSON-stat value array -> {period: {col: float}}.

    JSON-stat v1 stores values row-major in ``dimension.id`` order.
    Strides are computed from ``dimension.size``; for each (driv_idx, tid_idx)
    we read value[stride_driv*driv_idx + stride_tid*tid_idx]. The leading
    singleton dims (OMRÅDE, BILTYPE, BRUG, ContentsCode) contribute zero offset.
    """
    dim = data["dimension"]
    order = dim["id"]
    sizes = dim["size"]
    values = data["value"]

    strides = []
    stride = 1
    for sz in reversed(sizes):
        strides.insert(0, stride)
        stride *= sz

    driv_pos = order.index("DRIV")
    tid_pos  = order.index("Tid")
    stride_driv = strides[driv_pos]
    stride_tid  = strides[tid_pos]
    # Base offset: singleton dims always pick index 0, so contribute nothing.

    driv_index = dim["DRIV"]["category"]["index"]   # {code: idx}
    tid_index  = dim["Tid"]["category"]["index"]

    out: dict[str, dict[str, float]] = {}
    for tid_code, tid_idx in tid_index.items():
        period = tid_to_period(tid_code)
        cols = {"BEV": 0.0, "PHEV": 0.0, "PETROL": 0.0, "DIESEL": 0.0, "OTHERS": 0.0}
        for driv_code, driv_idx in driv_index.items():
            col = DRIV_TO_COL.get(driv_code)
            if col is None:
                # Defensive: if Statbank adds a new propellant code we haven't
                # mapped, surface it loudly rather than silently dropping it.
                raise RuntimeError(
                    f"[{variant}] unmapped DRIV code {driv_code!r} "
                    f"(label: {data['dimension']['DRIV']['category']['label'].get(driv_code)!r}) "
                    f"— add it to DRIV_TO_COL."
                )
            flat = stride_driv * driv_idx + stride_tid * tid_idx
            v = values[flat]
            if v is None:
                v = 0.0
            cols[col] += float(v)
        out[period] = cols
    return out


def to_csv_rows(parsed: dict[str, dict[str, float]], variant: str) -> dict:
    rows: dict = {}
    for period, cols in parsed.items():
        total = sum(cols.values())
        # Skip future months Statbank pre-fills as all-zero. A real zero-month
        # is implausible for DK (passenger-car totals never go to 0).
        if total == 0.0:
            continue
        rows[period] = {
            "period": period,
            "time_interval": "monthly",
            "variant": variant,
            "source": SOURCE,
            "BEV":      cols["BEV"],
            "PHEV":     cols["PHEV"],
            "HEV":      "",
            "PETROL":   cols["PETROL"],
            "DIESEL":   cols["DIESEL"],
            "FLEXFUEL": "",
            "OTHERS":   cols["OTHERS"],
            "TOTAL":    total,
            "notes":    "",
        }
    return rows


def upsert_csv(csv_path: str, new_rows: dict) -> tuple[int, int]:
    """Upsert by (period, variant). Returns (added, updated). Warns on >50% delta."""
    existing: dict = {}
    if os.path.exists(csv_path):
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing[(row["period"], row["variant"])] = row

    added = updated = 0
    for key, new_row in sorted(new_rows.items()):
        if key not in existing:
            existing[key] = new_row
            added += 1
            print(f"  + {key[1]} {key[0]}")
        else:
            old = existing[key]
            for col in ["BEV", "PHEV", "PETROL", "DIESEL", "OTHERS"]:
                old_val = float(old.get(col) or 0)
                new_val = float(new_row[col] or 0)
                if old_val > 100 and abs(new_val - old_val) / old_val > 0.5:
                    print(
                        f"  WARNING {key[1]} {key[0]} {col}: existing={old_val:.0f}, "
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


def previous_month_period() -> str:
    today = date.today()
    if today.month == 1:
        return f"{today.year - 1}-12"
    return f"{today.year}-{today.month - 1:02d}"


def csv_has_period_for_variant(csv_path: str, period: str, variant: str) -> bool:
    if not os.path.exists(csv_path):
        return False
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["period"] == period and row["variant"] == variant:
                return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--variant",
        choices=["whole", "private", "industry", "hdv", "vans", "all"],
        default="all",
        help="Which slice to fetch (default: all)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Skip the 'already current' early-exit check.",
    )
    args = parser.parse_args()

    aliases = {"whole": "Whole", "private": "Private", "industry": "Industry",
               "hdv": "HDV", "vans": "Vans"}
    targets = list(aliases.values()) if args.variant == "all" else [aliases[args.variant]]

    if not args.force:
        prev = previous_month_period()
        current = [
            v for v in targets
            if csv_has_period_for_variant(VARIANT_CONFIG[v]["csv"], prev, v)
        ]
        targets = [v for v in targets if v not in current]
        for v in current:
            print(f"[{v}] CSV already has {prev}; skipping (use --force to re-fetch).")
        if not targets:
            print("All requested variants are current; nothing to do.")
            return

    session = requests.Session()
    for variant in targets:
        data = fetch_variant(variant, session)
        parsed = parse_dataset(data, variant)
        rows = to_csv_rows(parsed, variant)
        if not rows:
            print(f"[{variant}] no non-zero months in response")
            continue
        print(f"[{variant}] parsed {len(rows)} months "
              f"({min(rows)} .. {max(rows)})")
        keyed = {(p, variant): r for p, r in rows.items()}
        added, updated = upsert_csv(VARIANT_CONFIG[variant]["csv"], keyed)
        print(f"[{variant}] {added} added, {updated} updated "
              f"-> {VARIANT_CONFIG[variant]['csv']}")


if __name__ == "__main__":
    main()
