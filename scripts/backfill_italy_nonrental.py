#!/usr/bin/env python3
"""
Backfill data/Italy_NonRental.csv by deriving NonRental = Whole − Rental
from the existing Italy.csv and Italy_Rental.csv.

NonRental is the "al netto del noleggio" block of the UNRAE PDF: Privati +
Società ed Enti + Autoimmatricolazioni (excluding the ~1 % "uso noleggio"
sub-slice).  fetch_italy.py reads this block directly going forward; for
historical months we can recover it without re-downloading any PDFs because
both source variants are already in the repo and the subtraction is exact.

Any period present in BOTH Italy.csv (Whole) and Italy_Rental.csv (Rental)
yields an exact NonRental row. Periods missing from either source are skipped.

Usage
-----
    python scripts/backfill_italy_nonrental.py
    python scripts/backfill_italy_nonrental.py --force      # re-write all
    python scripts/backfill_italy_nonrental.py --dry-run
"""
import argparse
import csv
import os
import sys
from pathlib import Path

WHOLE_CSV     = "data/Italy.csv"
RENTAL_CSV    = "data/Italy_Rental.csv"
NONRENTAL_CSV = "data/Italy_NonRental.csv"

NUMERIC = ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL"]
CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    *NUMERIC, "notes",
]


def _load(path: str, variant: str) -> dict[str, dict]:
    if not os.path.exists(path):
        sys.exit(f"Missing source CSV: {path}")
    out: dict[str, dict] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("variant") == variant:
                out[row["period"]] = row
    return out


def _to_int(s: str) -> int:
    """Convert a CSV numeric cell to int. Empty cells (quarterly backfill rows
    where PETROL/DIESEL/OTHERS are blank) become 0."""
    s = (s or "").strip()
    if s == "":
        return 0
    # Handle fractional values from the 2015–2016 quarterly backfill (PHEV/HEV).
    if "." in s or "," in s:
        return int(round(float(s.replace(",", "."))))
    return int(s)


def derive_row(whole: dict, rental: dict, period: str) -> dict:
    cols = {c: _to_int(whole[c]) - _to_int(rental[c]) for c in NUMERIC}
    if cols["TOTAL"] <= 0:
        raise RuntimeError(f"{period}: derived TOTAL is {cols['TOTAL']}; refusing.")
    for c in NUMERIC:
        if cols[c] < 0:
            raise RuntimeError(
                f"{period}: derived {c}={cols[c]} (negative) — "
                f"Whole={whole[c]} Rental={rental[c]}"
            )
    return {
        "period": period,
        "time_interval": whole.get("time_interval", "monthly"),
        "variant": "NonRental",
        "source": whole.get("source", "unrae.it"),
        **{c: cols[c] for c in NUMERIC},
        "notes": "",
    }


def _load_existing_periods(path: str) -> set[str]:
    if not os.path.exists(path):
        return set()
    with open(path, newline="", encoding="utf-8") as f:
        return {r["period"] for r in csv.DictReader(f)
                if r.get("variant") == "NonRental"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force",   action="store_true",
                    help="Re-derive and overwrite periods already in the target CSV.")
    ap.add_argument("--dry-run", action="store_true",
                    help="List periods to derive; do not write.")
    args = ap.parse_args()

    whole  = _load(WHOLE_CSV,  "Whole")
    rental = _load(RENTAL_CSV, "Rental")

    common = sorted(set(whole) & set(rental))
    missing_rental = sorted(set(whole) - set(rental))
    if missing_rental:
        print(f"  ({len(missing_rental)} period(s) in Whole have no Rental row — "
              f"skipped; e.g. {missing_rental[:3]})")

    existing = _load_existing_periods(NONRENTAL_CSV)
    todo = [p for p in common if args.force or p not in existing]

    if not todo:
        print("Italy_NonRental.csv is already up to date for all common periods.")
        return

    print(f"{len(todo)} period(s) to derive:")
    for p in todo[:10]:
        print(f"  {p}")
    if len(todo) > 10:
        print(f"  … and {len(todo) - 10} more")

    if args.dry_run:
        return

    # Load + merge.
    rows: list[dict] = []
    seen_periods: set[str] = set()
    if os.path.exists(NONRENTAL_CSV):
        with open(NONRENTAL_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                for c in CSV_COLUMNS:
                    row.setdefault(c, "")
                if row.get("variant") == "NonRental" and row["period"] in todo:
                    continue  # will be replaced
                rows.append(row)
                seen_periods.add((row.get("variant", ""), row["period"]))

    for p in todo:
        new_row = derive_row(whole[p], rental[p], p)
        rows.append(new_row)

    rows.sort(key=lambda r: (r.get("variant", ""), r["period"]))

    Path(NONRENTAL_CSV).parent.mkdir(parents=True, exist_ok=True)
    with open(NONRENTAL_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(todo)} row(s) to {NONRENTAL_CSV}.")


if __name__ == "__main__":
    main()
