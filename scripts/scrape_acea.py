#!/usr/bin/env python3
"""Scrape monthly ACEA new-car-registration figures into data/markets/<slug>.csv.

Usage
-----
  # Pull March 2026 from acea.auto and upsert into the canonical CSVs
  python scripts/scrape_acea.py 2026 03

  # Use a local PDF instead of fetching (offline / URL drift fallback)
  python scripts/scrape_acea.py 2026 03 --pdf data/raw/Press_release_car_registrations_March_2026.pdf

  # Limit to a subset of countries
  python scripts/scrape_acea.py 2026 03 --include france,germany

  # Print the parsed rows but don't touch the CSVs
  python scripts/scrape_acea.py 2026 03 --dry-run

Notes
-----
The ACEA monthly press release ships a "NEW CAR REGISTRATIONS BY MARKET
AND POWER SOURCE" table on (currently) page 3. This scraper extracts:

  Country | BEV | PHEV | HEV | OTHERS | PETROL | DIESEL | TOTAL

for the named month, derives the period label "<YEAR>M<MONTH>", and
upserts one row per (period, category) into data/markets/<slug>.csv. The
canonical CSV format is preserved exactly so downstream R code reads it
without changes.

By default we touch only countries whose existing CSV lists "ACEA" in
the source string and where ACEA is the *primary* source. Override with
--include / --exclude / --all when needed.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import io
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

import pdfplumber
import requests
from requests import HTTPError


REPO_ROOT = Path(__file__).resolve().parent.parent
MARKETS_DIR = REPO_ROOT / "data" / "markets"
INDEX_CSV   = MARKETS_DIR / "_index.csv"

ACEA_URL_TEMPLATE = "https://www.acea.auto/files/Press_release_car_registrations_{month_name}_{year}.pdf"

# Country names as they appear in the PDF table → slug used for the CSV.
# The scraper recognises every market the press release reports on; whether
# we actually upsert into a given country's CSV depends on the CLI filters
# below.
PDF_COUNTRY_TO_SLUG: Dict[str, str] = {
    "Austria": "austria",
    "Belgium": "belgium",
    "Bulgaria": "bulgaria",
    "Croatia": "croatia",
    "Cyprus": "cyprus",
    "Czechia": "czechia",
    "Denmark": "denmark",
    "Estonia": "estonia",
    "Finland": "finland",
    "France": "france",
    "Germany": "germany",
    "Greece": "greece",
    "Hungary": "hungary",
    "Ireland": "ireland",
    "Italy": "italy",
    "Latvia": "latvia",
    "Lithuania": "lithuania",
    "Luxembourg": "luxembourg",
    "Malta": "malta",
    "Netherlands": "netherlands",
    "Poland": "poland",
    "Portugal": "portugal",
    "Romania": "romania",
    "Slovakia": "slovakia",
    "Slovenia": "slovenia",
    "Spain": "spain",
    "Sweden": "sweden",
    "Iceland": "iceland",
    "Norway": "norway",
    "Switzerland": "switzerland",
    "United Kingdom": "uk",
}

# Skip the rolled-up table rows.
PDF_AGGREGATE_LABELS = {"EUROPEAN UNION", "EFTA", "EU + EFTA + UK"}

# Default include list: countries whose CSVs are predominantly ACEA-driven.
# Mixed-source countries (Czechia, Norway, Spain, Switzerland, ...) are
# included because the user occasionally swaps in ACEA for them.
DEFAULT_INCLUDE = {
    "belgium", "bulgaria", "croatia", "cyprus", "czechia", "estonia",
    "france", "greece", "hungary", "iceland", "ireland", "latvia",
    "lithuania", "luxembourg", "malta", "norway", "poland", "romania",
    "slovakia", "slovenia", "spain", "switzerland",
}

# Map source CSV columns - upper case to match downstream load_data.R.
PDF_COLUMNS = ["BEV", "PHEV", "HEV", "OTHER", "PETROL", "DIESEL", "TOTAL"]

NO_DATA_MARKERS = {"ꟷ", "—", "–", "-", ""}


class PdfUnavailableError(RuntimeError):
    """Raised when the expected ACEA source PDF does not exist yet."""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("year",  type=int, help="four-digit year, e.g. 2026")
    p.add_argument("month", type=int, help="month number, 1..12")
    p.add_argument("--pdf", type=Path, default=None,
                   help="local PDF path (skip the URL fetch)")
    p.add_argument("--url", type=str, default=None,
                   help="explicit PDF URL (overrides ACEA_URL_TEMPLATE)")
    p.add_argument("--missing-ok", action="store_true",
                   help="exit successfully when the source PDF is not yet available")
    p.add_argument("--include", type=str, default=None,
                   help="comma-separated slug list to upsert (default: pure-ACEA markets)")
    p.add_argument("--exclude", type=str, default="",
                   help="comma-separated slug list to skip")
    p.add_argument("--all", action="store_true",
                   help="upsert every country in PDF_COUNTRY_TO_SLUG that has a CSV")
    p.add_argument("--dry-run", action="store_true",
                   help="parse and print, don't touch any CSV")
    return p.parse_args()


def fetch_pdf(url: str) -> bytes:
    print(f"[fetch] {url}")
    r = requests.get(url, timeout=60)
    try:
        r.raise_for_status()
    except HTTPError as exc:
        if r.status_code == 404:
            raise PdfUnavailableError(
                f"ACEA PDF not found at {url}. The requested period may not "
                "have been published yet; pass --url or --pdf when using a "
                "different source."
            ) from exc
        raise
    return r.content


def parse_first_value(cell_line: str) -> Optional[float]:
    """A table cell looks like '349 217 +60.8' (current prev pct), or
    '0 0' (when both are zero, ACEA omits the pct), or 'ꟷ ꟷ' for missing
    data. We only ever want the first number — the current-month figure."""
    tokens = (cell_line or "").strip().split()
    if not tokens:
        return None
    first = tokens[0]
    if first in NO_DATA_MARKERS:
        return None
    cleaned = first.replace(",", "").replace("\xa0", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_market_rows(pdf_source) -> Dict[str, Dict[str, Optional[float]]]:
    """Extract one row per country from the by-market table on the relevant
    page. Uses pdfplumber's table extraction so column boundaries are taken
    from the PDF's own grid lines — this is much more robust than splitting
    the rendered text by whitespace, which falls over whenever ACEA omits
    a percentage cell (e.g. when both current and prior month are 0)."""
    open_arg = io.BytesIO(pdf_source) if isinstance(pdf_source, bytes) else str(pdf_source)
    rows: Dict[str, Dict[str, Optional[float]]] = {}

    # The 7 numeric columns sit at fixed indices in the extracted table:
    # column 0 holds the country names, columns 1/4/7/10/13/16/19 hold
    # BEV / PHEV / HEV / OTHER / PETROL / DIESEL / TOTAL. The two cells
    # between each pair are merged spans that pdfplumber returns as None.
    NUMERIC_COL_IDX = [1, 4, 7, 10, 13, 16, 19]

    with pdfplumber.open(open_arg) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if "NEW CAR REGISTRATIONS BY MARKET" not in text:
                continue
            # The press release has two by-market tables, MONTHLY and
            # YEAR-TO-DATE. We only want the monthly one.
            if "MONTHLY" not in text or "YEAR TO DATE" in text:
                continue
            for table in page.extract_tables():
                for tr in table:
                    if not tr or not tr[0]:
                        continue
                    countries = [c.strip() for c in tr[0].split("\n") if c.strip()]
                    if not countries:
                        continue
                    # Skip aggregate-only rows
                    if all(c in PDF_AGGREGATE_LABELS for c in countries):
                        continue
                    # Per numeric column, split the cell text into per-country lines
                    col_lines: List[List[str]] = []
                    for idx in NUMERIC_COL_IDX:
                        cell = tr[idx] if idx < len(tr) else ""
                        col_lines.append((cell or "").split("\n"))
                    # Pair up countries with their values
                    for i, country in enumerate(countries):
                        if country in PDF_AGGREGATE_LABELS or country not in PDF_COUNTRY_TO_SLUG:
                            continue
                        values = {}
                        for col_name, lines in zip(PDF_COLUMNS, col_lines):
                            line = lines[i] if i < len(lines) else ""
                            values[col_name] = parse_first_value(line)
                        rows[country] = values
    if not rows:
        raise RuntimeError("Could not find the per-market table in the PDF")
    return rows


def slugs_in_index() -> set[str]:
    if not INDEX_CSV.exists():
        return set()
    out: set[str] = set()
    with INDEX_CSV.open() as f:
        for r in csv.DictReader(f):
            out.add(r["slug"])
    return out


def resolve_targets(args: argparse.Namespace) -> List[str]:
    have_csv = slugs_in_index()
    if args.all:
        candidates = set(PDF_COUNTRY_TO_SLUG.values())
    elif args.include:
        candidates = {s.strip() for s in args.include.split(",") if s.strip()}
    else:
        candidates = set(DEFAULT_INCLUDE)
    excluded = {s.strip() for s in args.exclude.split(",") if s.strip()}
    targets = (candidates - excluded) & have_csv
    return sorted(targets)


def upsert_csv(csv_path: Path, period: str, year_frac: float,
               values: Dict[str, Optional[float]], source: str) -> int:
    """Insert/replace the period's rows for this country. Returns rows touched."""
    existing: List[Dict[str, str]] = []
    if csv_path.exists():
        with csv_path.open() as f:
            existing = list(csv.DictReader(f))
    # Drop any rows for this period — they get rebuilt below.
    existing = [r for r in existing if r["period"] != period]

    new_rows: List[Dict[str, str]] = []
    for cat, val in values.items():
        if val is None:
            continue
        new_rows.append({
            "period": period,
            "interval": "monthly",
            "year": f"{year_frac:.6f}".rstrip("0").rstrip("."),
            "category": cat,
            "registrations": (f"{int(val)}" if float(val).is_integer() else f"{val}"),
            "source": source,
        })

    combined = existing + new_rows
    # Preserve a stable per-row ordering: by year then category alpha.
    def sort_key(r: Dict[str, str]):
        try:
            yf = float(r["year"])
        except ValueError:
            yf = float("inf")
        return (yf, r["category"])
    combined.sort(key=sort_key)

    fieldnames = ["period", "interval", "year", "category", "registrations", "source"]
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(combined)

    return len(new_rows)


def main() -> int:
    args = parse_args()
    if not (1 <= args.month <= 12):
        sys.exit("month must be 1..12")

    if args.pdf:
        pdf_source = args.pdf.read_bytes()
    else:
        url = args.url or ACEA_URL_TEMPLATE.format(
            month_name=calendar.month_name[args.month],
            year=args.year,
        )
        try:
            pdf_source = fetch_pdf(url)
        except PdfUnavailableError as exc:
            if args.missing_ok:
                print(f"[skip] {exc}")
                print("\nDone. 0 CSV(s) updated.")
                return 0
            sys.exit(str(exc))

    rows = extract_market_rows(pdf_source)
    print(f"[parse] recognised {len(rows)} market rows in the PDF table")

    targets = resolve_targets(args)
    print(f"[targets] {len(targets)} CSV(s) will be touched: {', '.join(targets)}")

    period = f"{args.year}M{args.month:02d}"
    year_frac = (args.year - 1) + (args.month - 1) / 12

    touched = 0
    for country, values in rows.items():
        slug = PDF_COUNTRY_TO_SLUG.get(country)
        if slug not in targets:
            continue
        csv_path = MARKETS_DIR / f"{slug}.csv"
        if not csv_path.exists():
            print(f"[skip] {country} ({slug}): {csv_path} does not exist")
            continue
        if args.dry_run:
            print(f"[dry] {country:>15s} → {slug}: {values}")
            continue
        n = upsert_csv(csv_path, period, year_frac, values, source="ACEA")
        print(f"[ok ] {country:>15s} → {slug}.csv: {n} rows for {period}")
        touched += 1

    print(f"\nDone. {touched} CSV(s) updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
