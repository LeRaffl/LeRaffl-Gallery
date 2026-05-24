#!/usr/bin/env python3
"""
One-off backfill: import pre-2018 Netherlands "Whole" history from the
maintainer's Google Sheet into data/Netherlands.csv.

Why this exists
---------------
The Swing dataset on duurzamemobiliteit.databank.nl only goes back to 2018-01,
but the maintainer has tracked Netherlands BEV registrations monthly since
2011 in a separate Google Sheet
(https://docs.google.com/spreadsheets/d/1tT_Ja3de_S528_JeSBkj74q-lfEIekE5-GRm9_pWgUo/).
Without this backfill, fitting the regression on Swing-only data would shift
the curve's baseline year (`t0` = floor min year) from 2010 to 2018 and visibly
change the published Netherlands trajectory.

Scope: only the "Netherlands" tab (variant = Whole) has pre-2018 data — the
"Netherlands (HDV)" and "Netherlands (Used Imports)" sheet tabs both start
2018-01 which matches Swing, so this script does not touch those variants.
(Per-variant CSVs live in data/Netherlands_Used.csv and data/Netherlands_HDV.csv;
this backfill only writes to data/Netherlands.csv, the Whole-variant file.)

Idempotent: existing (period, variant=Whole) rows in data/Netherlands.csv are
left untouched. Only periods strictly before 2018-01 that are missing get
added.

The pre-2018 rows have BEV / PHEV / TOTAL only — PETROL/DIESEL/OTHERS were not
broken out in the source data at the time. The renderer's BEV/PHEV/ICE math
uses (TOTAL - BEV - PHEV - EREV) for ICE share, so this still produces the
correct trajectory; only the TTM stacked-share plot is affected (it will
simply have no pre-2018 history, because compute_ttm_long requires every
present fuel column to have a complete 12-month rolling window).

Usage
-----
    python scripts/backfill_netherlands_pre2018.py [--csv data/Netherlands.csv]

Re-running is safe: the existing CSV is untouched except for the newly added
pre-2018 rows.
"""
import argparse
import csv
import os
import re
import urllib.request
from pathlib import Path

SHEET_ID = "1tT_Ja3de_S528_JeSBkj74q-lfEIekE5-GRm9_pWgUo"
SHEET_URL = (
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
    "/gviz/tq?tqx=out:csv&sheet=Netherlands"
)
CUTOFF = "2018-01"  # rows with period >= CUTOFF come from the Swing scraper
SOURCE_LABEL = "duurzamemobiliteit.databank.nl (RDW) — pre-2018 via maintainer sheet"

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
    """NL formatting: thousands '.', decimal ','. Empty -> ''."""
    s = s.strip()
    if not s:
        return ""
    return float(s.replace(".", "").replace(",", "."))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default="data/Netherlands.csv")
    args = parser.parse_args()

    print(f"Fetching Sheet tab 'Netherlands' from {SHEET_URL}")
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
            "BEV": parse_num(r[col["BEV"]]),
            "PHEV": parse_num(r[col["PHEV"]]),
            "HEV": parse_num(r[col["HEV"]]),
            "PETROL": parse_num(r[col["PETROL"]]),
            "DIESEL": parse_num(r[col["DIESEL"]]),
            "FLEXFUEL": "",
            "OTHERS": parse_num(r[col["OTHERS"]]),
            "TOTAL": parse_num(r[col["TOTAL"]]),
            "notes": "backfill: pre-2018 from maintainer google sheet",
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
