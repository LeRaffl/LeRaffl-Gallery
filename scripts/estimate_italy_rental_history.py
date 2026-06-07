#!/usr/bin/env python3
"""
Estimate the historical Rental / NonRental split for Italy for the periods
that predate the first UNRAE 'al netto del noleggio' bulletin (2019-06).

Why estimates
-------------
UNRAE 'struttura del mercato' PDFs before 2019-06 do NOT contain the rental
("al netto del noleggio") breakdown, so no *real* Rental/NonRental split
exists for 2015-01 .. 2019-05.  We approximate it by applying the per-fuel
rental SHARE observed in the earliest real data — 2019-06 .. 2019-12, the
closest pre-COVID window — to the historical Whole figures in Italy.csv:

    Rental_est[fuel]    = round(Whole[fuel] * share[fuel])
    NonRental_est[fuel] = Whole[fuel] - Rental_est[fuel]

so that Rental + NonRental == Whole exactly for every populated column.

Reference per-fuel shares (computed at runtime from 2019-H2 actuals; the
values below are for reference):
    BEV 39.8%  PHEV 42.4%  HEV 18.5%  PETROL 11.8%  DIESEL 33.4%  OTHERS 8.4%
    TOTAL 20.3%

Two regimes
-----------
* 2017-02 .. 2019-05 — Italy.csv carries the full real fuel breakdown, so
  every fuel is estimated and Rental TOTAL = sum of the fuel rentals.
* 2015-01 .. 2017-01 — Italy.csv only carries BEV/PHEV/HEV (themselves a
  rough earlier backfill) plus TOTAL; petrol/diesel/others are blank.  Those
  rows are mirrored: the three populated fuels are estimated per share and
  TOTAL is estimated with the overall rental share; the rest stay blank.

Every row written here is tagged in the notes column.  Real values
(2019-06 onward) are never touched.

Usage
-----
    python scripts/estimate_italy_rental_history.py
    python scripts/estimate_italy_rental_history.py --dry-run
"""
import argparse
import csv
from pathlib import Path

WHOLE_CSV     = "data/Italy.csv"
RENTAL_CSV    = "data/Italy_Rental.csv"
NONRENTAL_CSV = "data/Italy_NonRental.csv"

FUELS   = ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS"]
NUMERIC = FUELS + ["TOTAL"]
CSV_COLUMNS = ["period", "time_interval", "variant", "source", *NUMERIC, "notes"]

# First UNRAE bulletin carrying the rental ("al netto del noleggio") section.
FIRST_REAL = "2019-06"
# Reference window for per-fuel rental shares: earliest real data, pre-COVID.
REF_WINDOW = [f"2019-{m:02d}" for m in range(6, 13)]

NOTE = "est: Whole x rental-share(2019-H2); no pre-2019-06 UNRAE rental data"


def _load(path: str, variant: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("variant") == variant:
                out[r["period"]] = r
    return out


def _to_int(s: str) -> int:
    s = (s or "").strip()
    if s == "":
        return 0
    if "." in s or "," in s:
        return int(round(float(s.replace(",", "."))))
    return int(s)


def _is_blank(s: str) -> bool:
    return (s or "").strip() == ""


def compute_shares(whole: dict, rental: dict) -> dict:
    """Per-fuel rental share = sum(Rental)/sum(Whole) over the reference window."""
    sw = {c: 0 for c in NUMERIC}
    sr = {c: 0 for c in NUMERIC}
    for p in REF_WINDOW:
        if p in whole and p in rental:
            for c in NUMERIC:
                sw[c] += _to_int(whole[p][c])
                sr[c] += _to_int(rental[p][c])
    return {c: (sr[c] / sw[c] if sw[c] else 0.0) for c in NUMERIC}


def estimate_rows(whole_row: dict, period: str, share: dict) -> tuple[dict, dict]:
    """Return (rental_row, nonrental_row) estimated from a Whole row."""
    full = not _is_blank(whole_row.get("PETROL", ""))

    rental_cols: dict[str, object] = {}
    nonrental_cols: dict[str, object] = {}

    for c in FUELS:
        if _is_blank(whole_row.get(c, "")):
            rental_cols[c] = ""
            nonrental_cols[c] = ""
        else:
            w = _to_int(whole_row[c])
            r = round(w * share[c])
            rental_cols[c] = r
            nonrental_cols[c] = w - r

    if full:
        # Real, complete breakdown → TOTAL is the sum of the fuel estimates.
        r_total = sum(rental_cols[c] for c in FUELS)
        n_total = sum(nonrental_cols[c] for c in FUELS)
    else:
        # Partial source (2015-2016) → use the overall rental share on TOTAL.
        w_total = _to_int(whole_row["TOTAL"])
        r_total = round(w_total * share["TOTAL"])
        n_total = w_total - r_total
    rental_cols["TOTAL"] = r_total
    nonrental_cols["TOTAL"] = n_total

    common = {
        "period": period,
        "time_interval": whole_row.get("time_interval", "monthly"),
        "source": whole_row.get("source", "unrae.it"),
        "notes": NOTE,
    }
    rental_row = {**common, "variant": "Rental", **rental_cols}
    nonrental_row = {**common, "variant": "NonRental", **nonrental_cols}
    return rental_row, nonrental_row


def _merge_write(path: str, variant: str, new_rows: dict, dry_run: bool) -> int:
    """Insert new_rows (period->row) into the CSV, never overwriting existing
    periods. Returns the number of rows added."""
    rows: list[dict] = []
    existing: set[str] = set()
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            for c in CSV_COLUMNS:
                row.setdefault(c, "")
            rows.append(row)
            if row.get("variant") == variant:
                existing.add(row["period"])

    added = 0
    for p, row in sorted(new_rows.items()):
        if p in existing:
            continue
        rows.append(row)
        added += 1

    rows.sort(key=lambda r: (r.get("variant", ""), r["period"]))

    if not dry_run:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
    return added


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would be written; do not modify files.")
    args = ap.parse_args()

    whole  = _load(WHOLE_CSV, "Whole")
    rental = _load(RENTAL_CSV, "Rental")

    share = compute_shares(whole, rental)
    print("Per-fuel rental shares from 2019-H2 actuals:")
    for c in NUMERIC:
        print(f"  {c:7s} {share[c]*100:5.1f}%")

    targets = sorted(p for p in whole if p < FIRST_REAL and p not in rental)
    print(f"\n{len(targets)} period(s) to estimate: {targets[0]} .. {targets[-1]}")

    new_rental: dict[str, dict] = {}
    new_nonrental: dict[str, dict] = {}
    for p in targets:
        r_row, n_row = estimate_rows(whole[p], p, share)
        new_rental[p] = r_row
        new_nonrental[p] = n_row

    # Show a couple of samples.
    for p in (targets[0], "2017-02" if "2017-02" in new_rental else targets[-1], targets[-1]):
        r = new_rental[p]
        print(f"  {p}  Rental BEV={r['BEV']} PHEV={r['PHEV']} HEV={r['HEV']} "
              f"PETROL={r['PETROL']} DIESEL={r['DIESEL']} OTHERS={r['OTHERS']} "
              f"TOTAL={r['TOTAL']}")

    n_r = _merge_write(RENTAL_CSV, "Rental", new_rental, args.dry_run)
    n_n = _merge_write(NONRENTAL_CSV, "NonRental", new_nonrental, args.dry_run)
    verb = "Would add" if args.dry_run else "Added"
    print(f"\n{verb} {n_r} Rental and {n_n} NonRental estimated row(s).")


if __name__ == "__main__":
    main()
