#!/usr/bin/env python3
"""
Fetch Malaysia new passenger-car registration data from data.gov.my OpenAPI
(parquet files, one per calendar year) and upsert data/Malaysia.csv.

Usage
-----
    python scripts/fetch_malaysia.py [--year YYYY] [--force]

Source
------
https://data.gov.my/data-catalogue/cars
Annual parquet files: https://storage.data.gov.my/transportation/cars_<YYYY>.parquet
One row per individual registration event; fuel type in column `fuel`.

Fuel mapping
-----------
The source does not split PHEV from HEV; all hybrids are labelled
`hybrid_petrol` or `hybrid_diesel`. Following the gallery's Türkiye/Georgia/
Colombia convention, the combined hybrid figure is parked in the HEV column
with PHEV/MHEV left empty. The TTM split chart labels this bucket "Hybrid".

    electric              → BEV
    hybrid_petrol         → HEV  (combined HEV+PHEV; source does not split)
    hybrid_diesel         → HEV
    petrol                → PETROL
    diesel                → DIESEL
    greendiesel           → DIESEL  (biodiesel blend, merged with diesel)
    plug_in_hybrid_petrol → PHEV   (newer field, present from ~2024)
    <everything else>     → OTHERS

Convention (single-Hybrid-bucket style, matches Türkiye / Georgia / Colombia)

Top brands / models (market/malaysia_top.json)
-----------------------------------------------
Every row also carries `maker` and `model`, so each run keeps the trailing-
twelve-month top brands and models per electrified class current, in the
country-neutral schema of scripts/market_top.py (the source page renders it).
The window ends at the last complete month; the two yearly parquets always
cover it. Rebuilt whenever missing or behind — including on runs that find
the CSV already current, which then download but leave the CSV alone.
--no-top skips it.

See docs/architecture/23-source-malaysia.md for the full playbook.
"""
import argparse
import csv
import io
import os
from datetime import date
from pathlib import Path

import requests

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_top  # noqa: E402

SOURCE = "data.gov.my"
CSV_PATH = "data/Malaysia.csv"
VARIANT = "Whole"
BASE_URL = "https://storage.data.gov.my/transportation/cars_{year}.parquet"

CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL", "notes",
]

# Fuel → gallery column. Keys are lowercased source values.
FUEL_MAP = {
    "electric":              "BEV",
    "plug_in_hybrid_petrol": "PHEV",
    "plug_in_hybrid_diesel": "PHEV",
    "hybrid_petrol":         "HEV",
    "hybrid_diesel":         "HEV",
    "petrol":                "PETROL",
    "diesel":                "DIESEL",
    "greendiesel":           "DIESEL",
}
# everything else → OTHERS

TOP_PATH = market_top.MARKET_DIR / "malaysia_top.json"
TOP_UNIT = "registrations (brand = maker, model = model as recorded by data.gov.my)"


def download_parquet(year: int, session: requests.Session) -> "pd.DataFrame":
    """Download one year's parquet and return a pandas DataFrame."""
    try:
        import pandas as pd
    except ImportError:
        raise SystemExit("pandas is required: pip install pandas pyarrow")

    url = BASE_URL.format(year=year)
    r = session.get(url, timeout=120)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    import io
    return pd.read_parquet(io.BytesIO(r.content))


def aggregate_to_monthly(df) -> dict:
    """
    Aggregate individual registration rows to monthly totals per gallery column.
    Returns {(period, VARIANT): row_dict}.
    """
    import pandas as pd

    df = df.copy()
    df["date_reg"] = pd.to_datetime(df["date_reg"], errors="coerce")
    df = df[df["date_reg"].notna()].copy()
    df["period"] = df["date_reg"].dt.strftime("%Y-%m")

    fuel_col = "fuel" if "fuel" in df.columns else None
    if fuel_col is None:
        raise RuntimeError("'fuel' column not found in parquet; schema may have changed.")

    df["fuel_lower"] = df[fuel_col].str.lower().str.strip()
    df["gallery_col"] = df["fuel_lower"].map(FUEL_MAP).fillna("OTHERS")

    grouped = df.groupby(["period", "gallery_col"]).size().unstack(fill_value=0)

    rows = {}
    for period, row in grouped.iterrows():
        bev    = int(row.get("BEV",    0))
        phev   = int(row.get("PHEV",   0))
        hev    = int(row.get("HEV",    0))
        petrol = int(row.get("PETROL", 0))
        diesel = int(row.get("DIESEL", 0))
        others = int(row.get("OTHERS", 0))
        total  = bev + phev + hev + petrol + diesel + others

        rows[(period, VARIANT)] = {
            "period":        period,
            "time_interval": "monthly",
            "variant":       VARIANT,
            "source":        SOURCE,
            "BEV":           float(bev)    if bev    else "",
            "PHEV":          float(phev)   if phev   else "",
            "HEV":           float(hev)    if hev    else "",
            "PETROL":        float(petrol) if petrol else "",
            "DIESEL":        float(diesel) if diesel else "",
            "OTHERS":        float(others) if others else "",
            "TOTAL":         float(total),
            "notes":         "",
        }
    return rows


def build_top(frames: list, target: str) -> dict:
    """Top brands/models over the twelve months ending at `target`."""
    import pandas as pd

    window = set(market_top.month_window(target))
    df = pd.concat(frames, ignore_index=True)
    period = pd.to_datetime(df["date_reg"], errors="coerce").dt.strftime("%Y-%m")
    df = df[period.isin(window)]
    period = period[period.isin(window)]
    cls = df["fuel"].str.lower().str.strip().map(FUEL_MAP).fillna("OTHERS")
    brand = df["maker"].map(market_top.clean)
    model = df["model"].map(market_top.clean)
    counts = pd.DataFrame({"p": period, "c": cls, "b": brand, "m": model}).value_counts()
    monthly = {p: (u, int((period == p).sum()))
               for p, u in market_top.per_month(
                   {(p, c, b, m): int(n) for (p, c, b, m), n in counts.items()}).items()}
    return market_top.build_top_monthly("Malaysia", SOURCE, target, monthly, TOP_UNIT)


def refresh_top(frames: list) -> None:
    import pandas as pd

    periods = set()
    for df in frames:
        periods |= set(pd.to_datetime(df["date_reg"], errors="coerce")
                       .dt.strftime("%Y-%m").dropna())
    complete = sorted(p for p in periods if p <= previous_month_period())
    if not complete:
        return
    top = build_top(frames, complete[-1])
    market_top.report(top, TOP_PATH, market_top.write_top(top, TOP_PATH))


def upsert_csv(csv_path: str, new_rows: dict) -> tuple[int, int]:
    existing: dict = {}
    if os.path.exists(csv_path):
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                for c in CSV_COLUMNS:
                    row.setdefault(c, "")
                existing[(row["period"], row["variant"])] = {k: row[k] for k in CSV_COLUMNS}

    added = updated = 0
    for key, new_row in sorted(new_rows.items()):
        if key not in existing:
            existing[key] = new_row
            added += 1
            print(f"  + {key[1]} {key[0]}")
        else:
            existing[key] = {**existing[key], **new_row}
            updated += 1

    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        w.writeheader()
        for key in sorted(existing.keys(), key=lambda k: (k[1], k[0])):
            w.writerow(existing[key])
    return added, updated


def previous_month_period() -> str:
    t = date.today()
    if t.month == 1:
        return f"{t.year - 1}-12"
    return f"{t.year}-{t.month - 1:02d}"


def csv_has_period(csv_path: str, period: str) -> bool:
    if not os.path.exists(csv_path):
        return False
    with open(csv_path, newline="", encoding="utf-8") as f:
        return any(
            r["period"] == period and r["variant"] == VARIANT
            for r in csv.DictReader(f)
        )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, default=None,
                    help="Fetch only this calendar year (default: current + previous).")
    ap.add_argument("--force", action="store_true",
                    help="Skip the 'previous month already present' early-exit.")
    ap.add_argument("--no-top", action="store_true",
                    help="Skip the top brands/models refresh.")
    args = ap.parse_args()

    want_top = (not args.no_top and not args.year
                and not market_top.top_is_current(TOP_PATH, previous_month_period()))
    data_current = not args.force and csv_has_period(CSV_PATH, previous_month_period())
    if data_current and not want_top:
        print(f"CSV already has {previous_month_period()}; nothing to do (use --force to refresh).")
        return

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; LeRaffl-Gallery/1.0)"})

    today = date.today()
    if args.year:
        years = [args.year]
    else:
        # Fetch current + previous year (data for the current year accumulates)
        years = sorted({today.year, today.year - 1})

    all_rows: dict = {}
    frames: list = []
    for year in years:
        print(f"Downloading {year} parquet …")
        df = download_parquet(year, session)
        if df is None:
            print(f"  {year}: not found (404) — skipping.")
            continue
        print(f"  {year}: {len(df):,} registration rows")
        frames.append(df)
        rows = aggregate_to_monthly(df)
        all_rows.update(rows)
        print(f"  {year}: {len(rows)} months aggregated")

    if want_top and frames:
        market_top.guarded(refresh_top, frames)
    if data_current:
        print(f"CSV already has {previous_month_period()}; left untouched (top list only).")
        return

    if not all_rows:
        print("No rows extracted.")
        return

    periods = sorted(p for p, _ in all_rows)
    print(f"Total months: {len(all_rows)} ({periods[0]} .. {periods[-1]})")
    added, updated = upsert_csv(CSV_PATH, all_rows)
    print(f"{added} added, {updated} updated -> {CSV_PATH}")


if __name__ == "__main__":
    main()
