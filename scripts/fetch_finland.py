#!/usr/bin/env python3
"""
Fetch Finland first-registration data from the Statistics Finland (Tilastokeskus)
PxWeb API, table StatFin/merek/statfin_merek_pxt_121d.px ("First registrations
of cars by driving power, purpose of use and by possessor, monthly"), and upsert
per-variant CSVs under data/.

Usage
-----
    python scripts/fetch_finland.py [--variant {whole,private,industry,hdv,vans,buses,all}] [--force]

Output files
------------
    data/Finland.csv          <- variant=Whole     (Passenger cars, possessor=Total)
    data/Finland_Private.csv  <- variant=Private   (Passenger cars, possessor=Private person)
    data/Finland_Industry.csv <- variant=Industry  (Passenger cars, possessor=Total − Private person)
    data/Finland_HDV.csv      <- variant=HDV       (Lorries > 3.5 t, possessor=Total)
    data/Finland_Vans.csv     <- variant=Vans      (Vans, possessor=Total)
    data/Finland_Buses.csv    <- variant=Buses     (Buses & coaches, possessor=Total)

API
---
Statistics Finland's PxWeb API is documented at https://pxdata.stat.fi/api1.html.
We POST a JSON query to the table's .px endpoint and request JSON-stat2 output.
The endpoint is public, no auth, stable. Dimension codes were verified against the
table's GET metadata response (the same URL without a body):

    Ajoneuvoluokka  Vehicle class   00 All automobiles, 01 Passenger cars,
                                    02 Vans, 03 Lorries > 3.5 t, 04 Buses & coaches
    Maakunta        Region          MA1 = MAINLAND FINLAND (broadest aggregate; see note)
    Käyttövoima     Driving power   see DRIV_TO_COL below (13 incl. Total)
    Käyttötarkoitus Purpose of use  YH = Total (pinned; we don't split by purpose)
    haltija         Possessor       00 Total, 01 Private person, 02 Enterprise, …
    Kuukausi        Month           YYYYMmm, starts 2014M01
    Tiedot          Information     N = Number

Region note: MA1 ("Mainland Finland") is the broadest aggregate the table exposes.
Åland (Ahvenanmaa) is NOT in this table at all — there is no all-Finland-incl-Åland
total available here. Åland's first registrations are a few hundred/year, immaterial
to the trajectory. See docs/architecture/12-source-finland.md.

Driving-power → canonical column mapping:
    BEV     <- 04 Electricity
    PHEV    <- 39 Petrol/Electricity (plug-in hybrid) + 44 Diesel/Electricity (plug-in hybrid)
    HEV     <- ""  (Finland has NO non-plug-in full-hybrid code; full hybrids fold
                    into Petrol upstream, same blank-HEV situation as Denmark/NL)
    PETROL  <- 01 Petrol
    DIESEL  <- 02 Diesel
    OTHERS  <- 06 Gas + 13 CNG + 38 Petrol/CNG + 40 Petrol/Ethanol + 65 LNG
                + 67 Diesel/LNG + Y Other
    TOTAL   <- sum of the above (we sum the per-fuel cells, NOT the YH "Total" code,
              so TOTAL always equals the breakdown we wrote.)

Industry variant: Statistics Finland has no "industry" possessor bucket. Per the
maintainer's definition, Industry = possessor Total (00) − Private person (01),
computed cell-by-cell (per driving power, per month) so the per-fuel breakdown
stays internally consistent.

The script is invoked by .github/workflows/fetch-finland.yml daily on the
1st–15th at 04:40 UTC. Early-exit per variant skips work once the previous
calendar month is already in the CSV.
"""
import argparse
import csv
import os
from datetime import date
from pathlib import Path

import requests

API_URL = (
    "https://pxdata.stat.fi/PxWeb/api/v1/en/StatFin/merek/statfin_merek_pxt_121d.px"
)
SOURCE = "pxdata.stat.fi (StatFin 121d)"

# Dimension variable codes (exact, incl. non-ASCII — the PxWeb table uses Finnish
# variable codes even on the English endpoint).
DIM_CLASS = "Ajoneuvoluokka"
DIM_REGION = "Maakunta"
DIM_DRIV = "Käyttövoima"
DIM_PURPOSE = "Käyttötarkoitus"
DIM_POSSESSOR = "haltija"
DIM_MONTH = "Kuukausi"

REGION_MAINLAND = "MA1"
PURPOSE_TOTAL = "YH"
POSSESSOR_TOTAL = "00"
POSSESSOR_PRIVATE = "01"

# Driving-power code -> canonical column. Total (YH) is intentionally excluded;
# we sum the per-fuel cells so TOTAL matches the breakdown.
DRIV_TO_COL = {
    "01": "PETROL",
    "02": "DIESEL",
    "04": "BEV",
    "39": "PHEV",   # Petrol/Electricity (plug-in hybrid)
    "44": "PHEV",   # Diesel/Electricity (plug-in hybrid)
    "06": "OTHERS",  # Gas
    "13": "OTHERS",  # Natural gas (CNG)
    "38": "OTHERS",  # Petrol/CNG
    "40": "OTHERS",  # Petrol/Ethanol
    "65": "OTHERS",  # LNG
    "67": "OTHERS",  # Diesel/LNG
    "Y":  "OTHERS",  # Other
}
DRIV_CODES = list(DRIV_TO_COL.keys())

# Variant -> (vehicle-class code, possessor mode, output CSV path).
# possessor mode: "total" -> possessor 00; "private" -> 01;
#                 "industry" -> 00 minus 01 (needs both fetched).
VARIANT_CONFIG = {
    "Whole":    {"vclass": "01", "possessor": "total",    "csv": "data/Finland.csv"},
    "Private":  {"vclass": "01", "possessor": "private",  "csv": "data/Finland_Private.csv"},
    "Industry": {"vclass": "01", "possessor": "industry", "csv": "data/Finland_Industry.csv"},
    "HDV":      {"vclass": "03", "possessor": "total",    "csv": "data/Finland_HDV.csv"},
    "Vans":     {"vclass": "02", "possessor": "total",    "csv": "data/Finland_Vans.csv"},
    "Buses":    {"vclass": "04", "possessor": "total",    "csv": "data/Finland_Buses.csv"},
}

CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "FLEXFUEL",
    "OTHERS", "TOTAL", "notes",
]


def fetch_dataset(vclass: str, possessors: list[str], session: requests.Session) -> dict:
    body = {
        "query": [
            {"code": DIM_CLASS,     "selection": {"filter": "item", "values": [vclass]}},
            {"code": DIM_REGION,    "selection": {"filter": "item", "values": [REGION_MAINLAND]}},
            {"code": DIM_DRIV,      "selection": {"filter": "item", "values": DRIV_CODES}},
            {"code": DIM_PURPOSE,   "selection": {"filter": "item", "values": [PURPOSE_TOTAL]}},
            {"code": DIM_POSSESSOR, "selection": {"filter": "item", "values": possessors}},
            {"code": DIM_MONTH,     "selection": {"filter": "all",  "values": ["*"]}},
        ],
        "response": {"format": "json-stat2"},
    }
    print(f"[fetch] class={vclass} possessors={possessors} months=all")
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


def parse_possessor(dataset: dict, possessor_code: str) -> dict[str, dict[str, float]]:
    """Return {period: {col: value}} for a single possessor slice of the dataset.

    JSON-stat2 stores values row-major in ``id`` order; strides come from ``size``.
    We fix every dimension except driving-power and month at the index of the
    requested possessor (or 0 for singletons), then read each (driving, month) cell.
    """
    order = dataset["id"]
    size = dataset["size"]
    strides = _strides(size)
    values = dataset["value"]
    dim = dataset["dimension"]

    driv_index = dim[DIM_DRIV]["category"]["index"]       # {code: idx}
    month_index = dim[DIM_MONTH]["category"]["index"]
    poss_index = dim[DIM_POSSESSOR]["category"]["index"]

    if possessor_code not in poss_index:
        raise RuntimeError(f"possessor {possessor_code!r} not in response")

    # Fixed index per dimension (driving + month overridden in the loop below).
    fixed = {code: 0 for code in order}
    fixed[DIM_POSSESSOR] = poss_index[possessor_code]

    def cell(driv_idx: int, month_idx: int) -> float:
        idx = dict(fixed)
        idx[DIM_DRIV] = driv_idx
        idx[DIM_MONTH] = month_idx
        flat = sum(strides[i] * idx[order[i]] for i in range(len(order)))
        v = values[flat]
        return 0.0 if v is None else float(v)

    out: dict[str, dict[str, float]] = {}
    for month_code, m_idx in month_index.items():
        period = month_to_period(month_code)
        cols = {"BEV": 0.0, "PHEV": 0.0, "PETROL": 0.0, "DIESEL": 0.0, "OTHERS": 0.0}
        for driv_code, d_idx in driv_index.items():
            col = DRIV_TO_COL.get(driv_code)
            if col is None:
                raise RuntimeError(
                    f"unmapped driving-power code {driv_code!r} "
                    f"(label: {dim[DIM_DRIV]['category']['label'].get(driv_code)!r}) "
                    f"— add it to DRIV_TO_COL."
                )
            cols[col] += cell(d_idx, m_idx)
        out[period] = cols
    return out


def parsed_for_variant(variant: str, session: requests.Session) -> dict[str, dict[str, float]]:
    cfg = VARIANT_CONFIG[variant]
    mode = cfg["possessor"]
    if mode == "total":
        ds = fetch_dataset(cfg["vclass"], [POSSESSOR_TOTAL], session)
        return parse_possessor(ds, POSSESSOR_TOTAL)
    if mode == "private":
        ds = fetch_dataset(cfg["vclass"], [POSSESSOR_PRIVATE], session)
        return parse_possessor(ds, POSSESSOR_PRIVATE)
    if mode == "industry":
        ds = fetch_dataset(cfg["vclass"], [POSSESSOR_TOTAL, POSSESSOR_PRIVATE], session)
        total = parse_possessor(ds, POSSESSOR_TOTAL)
        private = parse_possessor(ds, POSSESSOR_PRIVATE)
        out: dict[str, dict[str, float]] = {}
        for period, tcols in total.items():
            pcols = private.get(period, {})
            out[period] = {
                col: max(0.0, tcols[col] - pcols.get(col, 0.0)) for col in tcols
            }
        return out
    raise ValueError(f"unknown possessor mode {mode!r}")


def to_csv_rows(parsed: dict[str, dict[str, float]], variant: str) -> dict:
    rows: dict = {}
    for period, cols in parsed.items():
        total = sum(cols.values())
        # Skip future/pre-publication months that the API pre-fills as all-zero.
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
        choices=["whole", "private", "industry", "hdv", "vans", "buses", "all"],
        default="all",
        help="Which slice to fetch (default: all)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Skip the 'already current' early-exit check.",
    )
    args = parser.parse_args()

    aliases = {"whole": "Whole", "private": "Private", "industry": "Industry",
               "hdv": "HDV", "vans": "Vans", "buses": "Buses"}
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
        parsed = parsed_for_variant(variant, session)
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
