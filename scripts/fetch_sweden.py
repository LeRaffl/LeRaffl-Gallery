#!/usr/bin/env python3
"""
Fetch Sweden new passenger-car registration data from the Statistics Sweden
(SCB) PxWeb API, table TK1001A/PersBilarDrivMedel (a.k.a. TAB3277, "New
registrations of passenger cars by region and by type of fuel"), and upsert
data/Sweden.csv.

Usage
-----
    python scripts/fetch_sweden.py [--force]

Output file
-----------
    data/Sweden.csv   <- variant=Whole (Region 00 = Sweden, all fuels)

Sweden has a single variant: this table doesn't split by possessor or vehicle
class (passenger cars only). So there is no Private/Industry/HDV/Vans/Buses
split like Denmark/Finland — just the whole-country passenger-car series.

API
---
SCB's PxWeb v1 API (classic PxWeb, same platform family as Finland's
pxdata.stat.fi). We POST a JSON query and request json-stat2. Public, no auth.
Endpoint and codes verified against the table's GET metadata:

    Region        00 = Sweden (national total; county/municipality codes unused)
    Drivmedel     fuel — see DRIV_TO_COL below (8 codes)
    ContentsCode  TK1001AA = Number
    Tid           YYYYMmm, starts 2006M01 (2002–2005 excluded upstream: the
                  vehicle register lacked the second-fuel field, so hybrids
                  couldn't be reported — see the table's Obs note)

Fuel → canonical column mapping (Sweden splits HEV and ethanol natively,
unlike Denmark/Finland):
    BEV       <- 120 electricity
    PHEV      <- 140 plug-in hybrid
    HEV       <- 130 electric hybrid           (non-plug-in full hybrid — Sweden
                                                reports this separately!)
    PETROL    <- 100 petrol
    DIESEL    <- 110 diesel
    FLEXFUEL  <- 150 ethanol/ethanol flexifuel (its own TTM slice; folds into
                                                the brown ICE line in the
                                                BEV/PHEV/ICE three-curve)
    OTHERS    <- 160 gas/gas flex + 190 other fuels
    TOTAL     <- sum of the above

The renderer handles FLEXFUEL and HEV with their own colours/slices in the TTM
stacked-shares plot, and folds everything except BEV/PHEV(/EREV) into ICE for
the three-curve — so no special renderer handling is needed.

The script is invoked by .github/workflows/fetch-sweden.yml daily on the
1st–15th at 05:50 UTC. Early-exit skips work once the previous calendar month
is already in the CSV.
"""
import argparse
import csv
import os
from datetime import date
from pathlib import Path

import requests

API_URL = (
    "https://api.scb.se/OV0104/v1/doris/en/ssd/START/TK/TK1001/TK1001A/PersBilarDrivMedel"
)
SOURCE = "statistikdatabasen.scb.se"
CSV_PATH = "data/Sweden.csv"
VARIANT = "Whole"

REGION_SWEDEN = "00"

# Fuel code -> canonical column. Multiple codes can map to OTHERS.
DRIV_TO_COL = {
    "100": "PETROL",
    "110": "DIESEL",
    "120": "BEV",
    "130": "HEV",       # electric hybrid (non-plug-in)
    "140": "PHEV",      # plug-in hybrid
    "150": "FLEXFUEL",  # ethanol/ethanol flexifuel
    "160": "OTHERS",    # gas/gas flex
    "190": "OTHERS",    # other fuels
}
DRIV_CODES = list(DRIV_TO_COL.keys())

CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "FLEXFUEL",
    "OTHERS", "TOTAL", "notes",
]


def fetch_dataset(session: requests.Session) -> dict:
    body = {
        "query": [
            {"code": "Region",    "selection": {"filter": "item", "values": [REGION_SWEDEN]}},
            {"code": "Drivmedel", "selection": {"filter": "item", "values": DRIV_CODES}},
            {"code": "Tid",       "selection": {"filter": "all",  "values": ["*"]}},
        ],
        "response": {"format": "json-stat2"},
    }
    print(f"[fetch] POST {API_URL}  region={REGION_SWEDEN} months=all")
    r = session.post(API_URL, json=body, timeout=120)
    r.raise_for_status()
    return r.json()


def _strides(size: list[int]) -> list[int]:
    strides = []
    stride = 1
    for sz in reversed(size):
        strides.insert(0, stride)
        stride *= sz
    return strides


def month_to_period(month_code: str) -> str:
    """'2026M04' -> '2026-04'."""
    if len(month_code) != 7 or month_code[4] != "M":
        raise ValueError(f"Unrecognised month code: {month_code!r}")
    return f"{month_code[:4]}-{month_code[5:7]}"


def parse_dataset(dataset: dict) -> dict[str, dict[str, float]]:
    """JSON-stat2 value array -> {period: {col: float}}.

    Row-major in ``id`` order; strides from ``size``. All dimensions except
    Drivmedel and Tid are singletons (index 0); we read each (fuel, month) cell.
    """
    order = dataset["id"]
    size = dataset["size"]
    strides = _strides(size)
    values = dataset["value"]
    dim = dataset["dimension"]

    driv_index = dim["Drivmedel"]["category"]["index"]
    month_index = dim["Tid"]["category"]["index"]

    fixed = {code: 0 for code in order}

    def cell(driv_idx: int, month_idx: int) -> float:
        idx = dict(fixed)
        idx["Drivmedel"] = driv_idx
        idx["Tid"] = month_idx
        flat = sum(strides[i] * idx[order[i]] for i in range(len(order)))
        v = values[flat]
        return 0.0 if v is None else float(v)

    out: dict[str, dict[str, float]] = {}
    for month_code, m_idx in month_index.items():
        period = month_to_period(month_code)
        cols = {"BEV": 0.0, "PHEV": 0.0, "HEV": 0.0, "PETROL": 0.0,
                "DIESEL": 0.0, "FLEXFUEL": 0.0, "OTHERS": 0.0}
        for driv_code, d_idx in driv_index.items():
            col = DRIV_TO_COL.get(driv_code)
            if col is None:
                raise RuntimeError(
                    f"unmapped fuel code {driv_code!r} "
                    f"(label: {dim['Drivmedel']['category']['label'].get(driv_code)!r}) "
                    f"— add it to DRIV_TO_COL."
                )
            cols[col] += cell(d_idx, m_idx)
        out[period] = cols
    return out


def to_csv_rows(parsed: dict[str, dict[str, float]]) -> dict:
    rows: dict = {}
    for period, cols in parsed.items():
        total = sum(cols.values())
        if total == 0.0:
            continue
        rows[period] = {
            "period": period,
            "time_interval": "monthly",
            "variant": VARIANT,
            "source": SOURCE,
            "BEV":      cols["BEV"],
            "PHEV":     cols["PHEV"],
            "HEV":      cols["HEV"],
            "PETROL":   cols["PETROL"],
            "DIESEL":   cols["DIESEL"],
            "FLEXFUEL": cols["FLEXFUEL"],
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
            for col in ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "FLEXFUEL", "OTHERS"]:
                old_val = float(old.get(col) or 0)
                new_val = float(new_row[col] or 0)
                if old_val > 100 and abs(new_val - old_val) / old_val > 0.5:
                    print(
                        f"  WARNING {key[1]} {key[0]} {col}: existing={old_val:.0f}, "
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


def previous_month_period() -> str:
    today = date.today()
    if today.month == 1:
        return f"{today.year - 1}-12"
    return f"{today.year}-{today.month - 1:02d}"


def csv_has_period(csv_path: str, period: str) -> bool:
    if not os.path.exists(csv_path):
        return False
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["period"] == period and row["variant"] == VARIANT:
                return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true",
        help="Skip the 'already current' early-exit check.",
    )
    args = parser.parse_args()

    if not args.force and csv_has_period(CSV_PATH, previous_month_period()):
        print(f"CSV already has {previous_month_period()}; nothing to do "
              f"(use --force to re-fetch).")
        return

    session = requests.Session()
    dataset = fetch_dataset(session)
    parsed = parse_dataset(dataset)
    rows = to_csv_rows(parsed)
    if not rows:
        print("no non-zero months in response")
        return
    print(f"parsed {len(rows)} months ({min(rows)} .. {max(rows)})")
    keyed = {(p, VARIANT): r for p, r in rows.items()}
    added, updated = upsert_csv(CSV_PATH, keyed)
    print(f"{added} added, {updated} updated -> {CSV_PATH}")


if __name__ == "__main__":
    main()
