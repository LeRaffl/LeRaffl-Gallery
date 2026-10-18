#!/usr/bin/env python3
"""
Fetch USA light-duty vehicle sales data from Argonne National Laboratory (ANL)
and update data/USA.csv.

Usage
-----
    python scripts/fetch_usa.py [--year YEAR] [--month MONTH] \
        [--months N] [--pdf-url URL_OR_PATH] [--csv PATH] [--force]

* --year / --month  Override the cutoff month (default: previous calendar
                    month). Only PDF rows up to and including this month are
                    considered.
* --months          How many trailing months to (re)write (default: 3).
* --pdf-url         Direct URL/path to the "Total Sales for Website" PDF
                    (leave empty to auto-discover from the ANL reference page).
* --csv             Target CSV (default: data/USA.csv).
* --force           Rewrite the trailing window even if values are unchanged.

Invoked by .github/workflows/fetch-usa.yml on a daily cron from the 10th of
each month onward, plus manual workflow_dispatch. When the CSV changes, the
workflow commits data/USA.csv and triggers render-country.yml for USA.

Data source
-----------
ANL ("Light Duty Electric Drive Vehicles Monthly Sales Updates") publishes a
single "Total Sales for Website_<Month> <Year>.pdf" at
https://www.anl.gov/esia/reference/light-duty-electric-drive-vehicles-monthly-sales-updates-historical-data

Each release contains the FULL monthly history (Dec-2010 onward) in one table:

    Month   BEV     PHEV    HEV     Total LDV
    Apr-26  64,517  18,309  209,456 1,361,970

ANL frequently revises the most recent ~2 months — and, as a 2026-10 audit
showed, sometimes whole years (2023-08 … 2025-08 had drifted by up to ~19k
BEVs/month). Every run re-writes a trailing window of the last `--months`
(default 3) months: new months are appended, recently-revised months are
corrected in place. Rows older than the window are not rewritten, but they ARE
compared with the PDF and every drifted row is reported as a ::warning so a
full refresh (`--months 0`, workflow input `months=0`) can be triggered. The
CSV is only rewritten when at least one value actually changed.

Sanity checks (validate_table) run on the whole parsed table before anything
is written: no gaps between the first and last month, no negative values,
BEV+PHEV+HEV <= Total LDV, Total LDV within a plausible band. A violation
aborts the run (exit 1) so a broken parse never reaches the CSV. Soft
anomalies (a BEV/PHEV/HEV value identical in two consecutive months, the PDF
lagging the cutoff by more than 2 months) are printed as ::warning only — an
identical value can be genuine (Sep-2025 HEV = Aug-2025's stale CSV value was
the case that prompted this; the PDF itself was fine).

Vehicle scope
-------------
Light-Duty Vehicles (LDV) as ANL defines them: GVWR <= 10,000 lb — passenger
cars + light trucks INCLUDING pickups, SUVs and vans (not EPA's 8,500 lb). These
are new-vehicle SALES compiled by ANL from Wards Auto (reference since
Oct-2019), not registrations. ANL publishes no car/light-truck split of the
table (only the HEV headline on its web page), so there is no Pickups/cars-only
variant. The PDF's "PEV Sales by Size" box (YTD, plug-ins only) is not used.

CSV layout
----------
Existing data/USA.csv columns:
    period,time_interval,variant,source,BEV,PHEV,HEV,OTHERS,ICE,TOTAL,notes

ANL column        → CSV column
    BEV           → BEV
    PHEV          → PHEV
    HEV           → HEV
    (none)        → OTHERS  (0; the PDF has no FCEV column — FCEVs, a few
                             dozen a month per ANL's web page, stay inside the
                             ICE residual; see docs/architecture/62-source-usa.md)
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


# Plausibility band for a month of US light-duty sales (observed 2010-2026:
# ~0.7 M in Apr-2020 … ~1.8 M). Wide on purpose: it catches a mis-parsed
# column (e.g. a cumulative or a share), not a weak month.
TOTAL_MIN, TOTAL_MAX = 500_000, 2_500_000


def _next_period(period: str) -> str:
    y, m = int(period[:4]), int(period[5:])
    return f"{y + (m == 12)}-{(m % 12) + 1:02d}"


def validate_table(table: dict[str, dict[str, int]]) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for the parsed ANL table.

    errors   — the parse cannot be trusted; nothing must be written.
    warnings — worth a look, but can be genuine data.
    """
    errors: list[str] = []
    warnings: list[str] = []
    if not table:
        return ["parsed zero rows"], warnings
    periods = sorted(table)
    p = periods[0]
    while p < periods[-1]:
        p = _next_period(p)
        if p not in table:
            errors.append(f"{p}: month missing from the PDF table (gap)")
    for p in periods:
        v = table[p]
        if any(v[k] < 0 for k in ("BEV", "PHEV", "HEV", "TOTAL")):
            errors.append(f"{p}: negative value {v}")
        if v["BEV"] + v["PHEV"] + v["HEV"] > v["TOTAL"]:
            errors.append(f"{p}: BEV+PHEV+HEV exceeds Total LDV {v}")
        if not TOTAL_MIN <= v["TOTAL"] <= TOTAL_MAX:
            errors.append(f"{p}: Total LDV {v['TOTAL']:,} outside "
                          f"{TOTAL_MIN:,}-{TOTAL_MAX:,}")
    for a, b in zip(periods, periods[1:]):
        for k in ("BEV", "PHEV", "HEV"):
            if table[a][k] == table[b][k] and table[a][k] > 1000:
                warnings.append(f"{b}: {k} identical to {a} ({table[b][k]:,})")
    return errors, warnings


def drifted_rows(csv_path: str, table: dict[str, dict[str, int]],
                 skip: set[str]) -> list[str]:
    """Periods (outside `skip`) whose CSV values differ from the PDF."""
    if not Path(csv_path).exists():
        return []
    out = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            p = r["period"]
            if p in skip or p not in table:
                continue
            for k in ("BEV", "PHEV", "HEV", "TOTAL"):
                try:
                    cur = float(r.get(k) or "nan")
                except ValueError:
                    cur = float("nan")
                if cur != table[p][k]:
                    out.append(p)
                    break
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


_NUMERIC_FIELDS = ("BEV", "PHEV", "HEV", "OTHERS", "ICE", "TOTAL")


def _row_unchanged(existing: dict, new: dict) -> bool:
    """True if the existing CSV row already carries `new`'s numeric values.

    Legacy rows may store OTHERS as "" — treated as a mismatch so the value
    is normalised to 0.0 on the next write.
    """
    for field in _NUMERIC_FIELDS:
        raw = existing.get(field, "")
        try:
            cur = float(raw) if raw not in ("", None) else None
        except ValueError:
            cur = None
        if cur != new[field]:
            return False
    return True


def upsert_window(csv_path: str, rows: dict[str, dict], force: bool) -> list[str]:
    """Upsert each period in `rows` into the CSV (sorted). Returns periods written.

    A period is written if it is new, its numeric values changed, or --force is
    set. The file is only rewritten when at least one period was written.
    """
    existing: dict[str, dict] = {}
    if Path(csv_path).exists():
        with open(csv_path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                existing[r["period"]] = r

    changed: list[str] = []
    for period, row in rows.items():
        old = existing.get(period)
        if old is None or force or not _row_unchanged(old, row):
            if not row.get("notes") and old is not None:
                row["notes"] = old.get("notes", "")
            existing[period] = row
            changed.append(period)

    if not changed:
        return []

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for p in sorted(existing.keys()):
            writer.writerow(existing[p])
    return sorted(changed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int)
    parser.add_argument("--month", type=int, choices=range(1, 13))
    parser.add_argument("--months", type=int, default=3,
                        help="How many trailing months to (re)write (default: 3)")
    parser.add_argument("--pdf-url", help="Direct URL/path to the Total Sales PDF")
    parser.add_argument("--csv", default="data/USA.csv")
    parser.add_argument("--save-pdf", metavar="PATH",
                        help="Also write the downloaded PDF (and its extracted text "
                             "as PATH.txt) for inspection / CI artifacts")
    parser.add_argument("--force", action="store_true",
                        help="Rewrite the trailing window even if values are unchanged")
    args = parser.parse_args()
    if args.months < 0:
        sys.exit("--months must be >= 0 (0 = refresh the full history)")

    # Determine the cutoff month (defaults to the calendar month before today).
    # Only PDF rows up to and including this month are considered.
    if args.year and args.month:
        cutoff_year, cutoff_month = args.year, args.month
    elif args.year or args.month:
        sys.exit("--year and --month must be given together")
    else:
        cutoff_year, cutoff_month = previous_month(date.today())
    cutoff_period = f"{cutoff_year}-{cutoff_month:02d}"
    print(f"Cutoff period: {cutoff_period} (writing up to {args.months} trailing months)")

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
    pdf_bytes = load_pdf_bytes(pdf_url)
    text = pdf_text(pdf_bytes)
    if args.save_pdf:
        Path(args.save_pdf).write_bytes(pdf_bytes)
        Path(args.save_pdf + ".txt").write_text(text, encoding="utf-8")
        print(f"Saved PDF to {args.save_pdf} (+ .txt)")
    table = parse_table(text)
    if not table:
        sys.exit("Parsed zero rows from the ANL PDF — layout may have changed.")
    print(f"Parsed {len(table)} monthly rows ({min(table)} … {max(table)}).")
    errors, warnings = validate_table(table)
    for w in warnings:
        print(f"::warning title=USA ANL sanity::{w}")
    if errors:
        for e in errors:
            print(f"::error title=USA ANL sanity::{e}")
        sys.exit(f"{len(errors)} sanity check(s) failed — CSV not touched.")

    eligible = sorted(p for p in table if p <= cutoff_period)
    if not eligible:
        print(f"No PDF rows at or before {cutoff_period} yet — nothing to do.")
        return 0
    if cutoff_period not in table:
        print(f"Note: {cutoff_period} not yet in the PDF (latest eligible is "
              f"{eligible[-1]}); refreshing the trailing window instead.")

    window = eligible if args.months == 0 else eligible[-args.months:]
    rows: dict[str, dict] = {}
    for period in window:
        vals = table[period]
        ice = vals["TOTAL"] - vals["BEV"] - vals["PHEV"] - vals["HEV"]
        if ice < 0:
            sys.exit(f"Computed ICE is negative ({ice}); parser likely picked wrong "
                     f"values for {period}: {vals}")
        rows[period] = build_row(period, vals)
        print(f"  {period}: BEV={vals['BEV']}, PHEV={vals['PHEV']}, "
              f"HEV={vals['HEV']}, TOTAL={vals['TOTAL']}, ICE={ice}")

    lag = (cutoff_year * 12 + cutoff_month) - (int(eligible[-1][:4]) * 12
                                               + int(eligible[-1][5:]))
    if lag > 2:
        print(f"::warning title=USA ANL stale::latest PDF month {eligible[-1]} is "
              f"{lag} months behind the cutoff {cutoff_period}")

    drift = drifted_rows(args.csv, {p: table[p] for p in eligible}, set(window))
    if drift:
        print(f"::warning title=USA ANL revisions::{len(drift)} row(s) outside the "
              f"window differ from the current PDF ({drift[0]} … {drift[-1]}); "
              f"run the workflow with months=0 to refresh the full history")

    changed = upsert_window(args.csv, rows, args.force)
    if changed:
        print(f"\nWrote {len(changed)} row(s) to {args.csv}: {', '.join(changed)}")
    else:
        print("\nWindow already matches the PDF — CSV unchanged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
