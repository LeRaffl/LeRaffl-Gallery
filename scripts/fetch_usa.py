#!/usr/bin/env python3
"""
Fetch USA light-duty vehicle sales data from Argonne National Laboratory (ANL)
and update data/USA.csv.

Usage
-----
    python scripts/fetch_usa.py [--year YEAR] [--month MONTH] \
        [--pdf-url URL_OR_PATH] [--csv PATH] [--force]

* --year / --month  Override the target month (default: previous calendar month).
* --pdf-url         Direct URL/path to the "Total Sales for Website" PDF
                    (leave empty to auto-discover from the ANL reference page).
* --csv             Target CSV (default: data/USA.csv).
* --force           Re-process even if the target period already exists.

Invoked by .github/workflows/fetch-usa.yml on a daily cron from the 10th of
each month onward, plus manual workflow_dispatch. The script self-throttles via
the latest period already present in the CSV, so most invocations are a no-op
until ANL publishes the month we are after. When the CSV changes, the workflow
commits data/USA.csv and triggers render-country.yml for USA.

Data source
-----------
ANL ("Light Duty Electric Drive Vehicles Monthly Sales Updates") publishes a
single "Total Sales for Website_<Month> <Year>.pdf" at
https://www.anl.gov/esia/reference/light-duty-electric-drive-vehicles-monthly-sales-updates-historical-data

Each release contains the FULL monthly history (Dec-2010 onward) in one table:

    Month   BEV     PHEV    HEV     Total LDV
    Apr-26  64,517  18,309  209,456 1,361,970

ANL frequently revises the most recent ~3 months (and occasionally older
months) between releases. Per the project rule we only ever write the most
recent month; older rows are never touched, even if a later ANL release would
adjust them — so the historical rows in data/USA.csv may legitimately differ
from the values in a newer PDF.

Vehicle scope
-------------
Light-Duty Vehicles (LDV): passenger cars + light trucks. Matches the existing
historical rows in data/USA.csv.

CSV layout
----------
Existing data/USA.csv columns:
    period,time_interval,variant,source,BEV,PHEV,HEV,OTHERS,ICE,TOTAL,notes

ANL column        → CSV column
    BEV           → BEV
    PHEV          → PHEV
    HEV           → HEV
    (none)        → OTHERS  (0; ANL does not break out FCV/other)
    Total LDV     → TOTAL
    (derived)     → ICE = TOTAL − BEV − PHEV − HEV − OTHERS

HTTP details
------------
anl.gov hardens against basic User-Agents (returns 403). We identify as a
regular desktop browser via HTTP_HEADERS to avoid this.
"""
import argparse
import csv
import io
import re
import sys
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

ANL_PAGE = (
    "https://www.anl.gov/esia/reference/"
    "light-duty-electric-drive-vehicles-monthly-sales-updates-historical-data"
)

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "OTHERS", "ICE", "TOTAL", "notes",
]

MONTH_ABBR = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

# A data row in the ANL table, e.g. "Apr-26 64,517 18,309 209,456 1,361,970".
# Early rows carry trailing legend text ("Jan-11 103 321 19,540 819,938 BEV …")
# which we ignore by only capturing the first four numbers after the month tag.
_ROW_RE = re.compile(
    r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-(\d{2})\s+"
    r"([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)"
)


def previous_month(today: date) -> tuple[int, int]:
    """Returns (year, month) of the calendar month before `today`."""
    if today.month == 1:
        return today.year - 1, 12
    return today.year, today.month - 1


def latest_period(csv_path: str) -> str | None:
    if not Path(csv_path).exists():
        return None
    with open(csv_path, newline="", encoding="utf-8") as f:
        periods = [row["period"] for row in csv.DictReader(f)]
    return max(periods) if periods else None


def discover_pdf_url() -> str | None:
    """Returns the absolute URL of the latest "Total Sales" PDF, or None."""
    print(f"Scanning {ANL_PAGE} for the Total Sales PDF …")
    resp = requests.get(ANL_PAGE, headers=HTTP_HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    candidates: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(" ", strip=True)
        haystack = f"{href} {text}".lower()
        if ".pdf" not in href.lower():
            continue
        # "Total Sales for Website_April 2026.pdf" — match on the stable
        # "total sales" token (spaces may be URL-encoded as %20).
        if "total" in haystack and "sales" in haystack:
            candidates.append(href)

    if not candidates:
        return None
    href = candidates[0]
    if href.startswith("http"):
        return href
    if href.startswith("//"):
        return "https:" + href
    return "https://www.anl.gov" + (href if href.startswith("/") else "/" + href)


def load_pdf_bytes(url_or_path: str) -> bytes:
    if url_or_path.startswith("http://") or url_or_path.startswith("https://"):
        print(f"Downloading: {url_or_path}")
        resp = requests.get(url_or_path, headers=HTTP_HEADERS, timeout=60)
        resp.raise_for_status()
        return resp.content
    path = url_or_path.replace("file://", "")
    with open(path, "rb") as f:
        return f.read()


def pdf_text(pdf_bytes: bytes) -> str:
    """Concatenate text of every PDF page in order."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def parse_table(text: str) -> dict[str, dict[str, int]]:
    """Parse the monthly LDV table into {period: {BEV, PHEV, HEV, TOTAL}}.

    period is "YYYY-MM"; two-digit years are read as 20YY (the table starts in
    Dec-2010, so there is no 19xx ambiguity).
    """
    out: dict[str, dict[str, int]] = {}
    for line in text.split("\n"):
        m = _ROW_RE.match(line.strip())
        if not m:
            continue
        mon, yy, bev, phev, hev, total = m.groups()
        period = f"20{yy}-{MONTH_ABBR[mon]:02d}"
        out[period] = {
            "BEV": int(bev.replace(",", "")),
            "PHEV": int(phev.replace(",", "")),
            "HEV": int(hev.replace(",", "")),
            "TOTAL": int(total.replace(",", "")),
        }
    return out


def build_row(period: str, vals: dict[str, int]) -> dict:
    bev = float(vals["BEV"])
    phev = float(vals["PHEV"])
    hev = float(vals["HEV"])
    total = float(vals["TOTAL"])
    others = 0.0
    ice = total - bev - phev - hev - others
    return {
        "period": period,
        "time_interval": "monthly",
        "variant": "Whole",
        "source": "ANL",
        "BEV": bev,
        "PHEV": phev,
        "HEV": hev,
        "OTHERS": others,
        "ICE": ice,
        "TOTAL": total,
        "notes": "",
    }


def upsert_row(csv_path: str, period: str, row: dict, force: bool) -> bool:
    """Append `row` for `period` to the CSV (sorted). Returns True if written.

    Returns False without writing if the period already exists and not --force.
    """
    existing: dict[str, dict] = {}
    if Path(csv_path).exists():
        with open(csv_path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                existing[r["period"]] = r

    if period in existing and not force:
        print(f"  Period {period} already in CSV — not overwriting (use --force).")
        return False

    existing[period] = row
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for p in sorted(existing.keys()):
            writer.writerow(existing[p])
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int)
    parser.add_argument("--month", type=int, choices=range(1, 13))
    parser.add_argument("--pdf-url", help="Direct URL/path to the Total Sales PDF")
    parser.add_argument("--csv", default="data/USA.csv")
    parser.add_argument("--force", action="store_true",
                        help="Re-process even if target period already exists")
    args = parser.parse_args()

    # Determine target month (defaults to the calendar month before today)
    if args.year and args.month:
        target_year, target_month = args.year, args.month
    elif args.year or args.month:
        sys.exit("--year and --month must be given together")
    else:
        target_year, target_month = previous_month(date.today())
    target_period = f"{target_year}-{target_month:02d}"
    print(f"Target period: {target_period}")

    # Short-circuit: if already in CSV and not forced, no-op.
    if not args.force:
        latest = latest_period(args.csv)
        if latest and latest >= target_period:
            print(f"Latest period in CSV is {latest} ≥ {target_period} — nothing to do.")
            return 0

    # Resolve the PDF URL
    if args.pdf_url:
        pdf_url = args.pdf_url
    else:
        pdf_url = discover_pdf_url()
        if not pdf_url:
            print("Could not locate the Total Sales PDF on the ANL page. "
                  "Will retry on next scheduled run.")
            return 0
        print(f"Found PDF: {pdf_url}")

    # Parse
    table = parse_table(pdf_text(load_pdf_bytes(pdf_url)))
    if not table:
        sys.exit("Parsed zero rows from the ANL PDF — layout may have changed.")
    print(f"Parsed {len(table)} monthly rows ({min(table)} … {max(table)}).")

    if target_period not in table:
        print(f"Target {target_period} not yet present in the PDF "
              f"(latest is {max(table)}). Will retry on next scheduled run.")
        return 0

    vals = table[target_period]
    ice = vals["TOTAL"] - vals["BEV"] - vals["PHEV"] - vals["HEV"]
    if ice < 0:
        sys.exit(f"Computed ICE is negative ({ice}); parser likely picked wrong "
                 f"values for {target_period}: {vals}")
    print(f"  BEV={vals['BEV']}, PHEV={vals['PHEV']}, HEV={vals['HEV']}, "
          f"TOTAL={vals['TOTAL']}, ICE={ice}")

    row = build_row(target_period, vals)
    if upsert_row(args.csv, target_period, row, args.force):
        print(f"\nWrote {target_period} to {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
