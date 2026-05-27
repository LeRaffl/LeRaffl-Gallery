#!/usr/bin/env python3
"""
One-off backfill: import pre-2018 Denmark "Whole" history from the
maintainer's Google Sheet into data/Denmark.csv.

Why this exists
---------------
Statbank table BIL53 only carries the propellant breakdown from 2018-01
onwards. The maintainer manually compiled Denmark passenger-car BEV /
PHEV / ICE / OTHERS / TOTAL from older statbank.dk releases and ACEA
press notes back to 2014-01 in a Google Sheet:
https://docs.google.com/spreadsheets/d/1n6QacQ7BIWMa9-vQpbDuuwkquSzYk7XIRbXzjcIsnyg/

Without this backfill, fitting the Weibull on Statbank-only data would
shift Denmark's baseline year (`t0` = floor min year) from 2014 to 2018.

Scope: only the `registrations` tab (variant=Whole) has pre-2018 rows;
the `registrations_private` and `registrations_industry` tabs both start
2018-01, matching the API, so this script does not touch
data/Denmark_Private.csv or data/Denmark_Industry.csv.

The sheet's pre-2018 rows have BEV / PHEV / ICE / OTHERS / TOTAL but no
Petrol/Diesel split — combined ICE only. We write BEV / PHEV / OTHERS /
TOTAL into the CSV and leave PETROL / DIESEL / HEV / FLEXFUEL blank, so
the renderer recovers ICE from (TOTAL − BEV − PHEV) the same way it does
for Netherlands pre-2018.

Idempotent: existing (period, variant=Whole) rows are left untouched;
only periods < 2018-01 that are missing get added.

Usage
-----
    python scripts/backfill_denmark_pre2018.py [--csv data/Denmark.csv]
"""
import argparse
import csv
import os
import re
import urllib.request
from pathlib import Path

SHEET_ID = "1n6QacQ7BIWMa9-vQpbDuuwkquSzYk7XIRbXzjcIsnyg"
SHEET_URL = (
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
    "/gviz/tq?tqx=out:csv&sheet=registrations"
)
CUTOFF = "2018-01"
SOURCE_LABEL = "api.statbank.dk (BIL53) — pre-2018 via maintainer sheet"

CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "FLEXFUEL",
    "OTHERS", "TOTAL", "notes",
]

PERIOD_RE = re.compile(r"(\d{4})M(\d{2})")


def parse_period(s: str) -> str | None:
    m = PERIOD_RE.match(s.strip())
    return f"{m.group(1)}-{m.group(2)}" if m else None


def parse_num(s: str) -> float | str:
    """European formatting in the sheet: thousands '.', decimal ','.

    '16.242' -> 16242.0; '0,67' -> 0.67; '' -> ''.
    """
    s = s.strip()
    if not s:
        return ""
    return float(s.replace(".", "").replace(",", "."))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default="data/Denmark.csv")
    args = parser.parse_args()

    print(f"Fetching Sheet tab 'registrations' from {SHEET_URL}")
    text = urllib.request.urlopen(SHEET_URL).read().decode("utf-8")
    rows = list(csv.reader(text.splitlines()))
    header, *data_rows = rows
    col = {name: i for i, name in enumerate(header)}

    sheet_rows: dict[str, dict] = {}
    for r in data_rows:
        period = parse_period(r[col["YYYYMMM"]])
        if not period or period >= CUTOFF:
            continue
        sheet_rows[period] = {
            "period": period,
            "time_interval": "monthly",
            "variant": "Whole",
            "source": SOURCE_LABEL,
            "BEV":      parse_num(r[col["BEV"]]),
            "PHEV":     parse_num(r[col["PHEV"]]),
            "HEV":      "",
            "PETROL":   "",
            "DIESEL":   "",
            "FLEXFUEL": "",
            "OTHERS":   parse_num(r[col["OTHERS"]]),
            "TOTAL":    parse_num(r[col["TOTAL"]]),
            "notes":    "backfill: pre-2018 from maintainer google sheet",
        }
    print(f"Sheet pre-{CUTOFF} rows: {len(sheet_rows)}")

    existing: dict[tuple[str, str], dict] = {}
    if os.path.exists(args.csv):
        with open(args.csv, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing[(row["period"], row["variant"])] = row

    added = skipped = 0
    for period, new_row in sheet_rows.items():
        key = (period, "Whole")
        if key in existing:
            skipped += 1
            continue
        existing[key] = new_row
        added += 1

    print(f"Added {added} new rows; left {skipped} existing rows untouched.")

    Path(args.csv).parent.mkdir(parents=True, exist_ok=True)
    with open(args.csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for key in sorted(existing.keys(), key=lambda k: (k[1], k[0])):
            writer.writerow(existing[key])
    print(f"Wrote {args.csv}")


if __name__ == "__main__":
    main()
