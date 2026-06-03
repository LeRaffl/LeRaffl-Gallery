#!/usr/bin/env python3
"""
Backfill data/Italy_Rental.csv with historical data from UNRAE struttura PDFs.

fetch_italy.py only ever processes the latest bulletin.  This script
discovers ALL struttura-del-mercato bulletins on the UNRAE website,
compares them against what is already in Italy_Rental.csv, and processes
every missing month.

The rental value is derived the same way as in fetch_italy.py:
    Rental = Whole − (al netto del noleggio)
Both numbers come from the same PDF, so the subtraction is exact.

The "al netto del noleggio" section was first included in UNRAE struttura
bulletins in early 2017.  Older PDFs that lack the second 'Per alimentazione'
block are skipped with a WARNING; they will never carry rental data.

Discovery strategy
------------------
1. Fetch the main index page (STRUTTURA_INDEX).
2. Collect every struttura-del-mercato link.
3. If the page contains a "paginazione" / next-page indicator, follow it.
4. Optionally fall back to trying /dati-statistici/immatricolazioni?anno=YYYY
   for years below the lowest year found on the index page.

Usage
-----
    python scripts/backfill_italy_rental.py
    python scripts/backfill_italy_rental.py --from-year 2019
    python scripts/backfill_italy_rental.py --force           # re-parse all
    python scripts/backfill_italy_rental.py --dry-run         # list missing, no writes
"""
import argparse
import csv
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

STRUTTURA_INDEX = "https://unrae.it/dati-statistici/immatricolazioni"
SOURCE          = "unrae.it"
USER_AGENT      = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) BEV-Gallery-Bot"
RENTAL_CSV      = "data/Italy_Rental.csv"
THROTTLE_S      = 2.0  # seconds between PDF downloads

IT_MONTHS = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}

CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL", "notes",
]


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def http_get(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    return r.text


def download_pdf(url: str, dest: Path) -> None:
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    r.raise_for_status()
    dest.write_bytes(r.content)


def pdf_to_text(pdf_path: Path) -> str:
    try:
        out = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            check=True, capture_output=True, text=True,
        )
    except FileNotFoundError:
        sys.exit("pdftotext not found. Install poppler-utils.")
    return out.stdout


# ── Discovery ─────────────────────────────────────────────────────────────────

# Match both absolute (https://unrae.it/...) and relative (/dati-statistici/...)
# URLs — historical pages returned by ?anno= filters use relative hrefs.
_STRUTTURA_LINK = re.compile(
    r'href="((?:https?://unrae\.it)?/dati-statistici/immatricolazioni/\d+/'
    r'struttura-del-mercato-([a-z]+)-(\d{4}))"',
    re.IGNORECASE,
)
# Extract the highest page number from any pagination link on the index page.
_MAX_PAGE = re.compile(
    r'href="[^"]*(?:immatricolazioni)[^"]*[?&](?:page|p)=(\d+)[^"]*"',
    re.IGNORECASE,
)


def _parse_struttura_links(html: str) -> list[tuple[str, int, int]]:
    """Return [(detail_url, year, month), ...] for all struttura links in html.
    Relative URLs are normalized to absolute https://unrae.it/... form.
    """
    results = []
    for url, mese, anno in _STRUTTURA_LINK.findall(html):
        m = IT_MONTHS.get(mese.lower())
        if m:
            if url.startswith("/"):
                url = "https://unrae.it" + url
            results.append((url, int(anno), m))
    return results


def discover_all_bulletins(from_year: int) -> list[tuple[str, int, int]]:
    """
    Return sorted list of (detail_url, year, month) for every struttura bulletin
    available on the UNRAE website, back to `from_year`.

    Strategy: the UNRAE index paginates with ?page=N.  The first page reveals
    the maximum page number via its pagination links (e.g. [...][182][183]).
    We iterate ALL pages 1..max_page sequentially so nothing is missed.
    Throttle: 0.5 s between page requests (light on UNRAE's server).
    """
    found: dict[tuple[int, int], str] = {}

    def _scrape(url: str) -> str:
        html = http_get(url)
        for detail_url, year, month in _parse_struttura_links(html):
            if year >= from_year:
                found.setdefault((year, month), detail_url)
        return html

    # Page 1 — also used to discover the total page count.
    print(f"  Fetching page 1 …")
    html1 = _scrape(STRUTTURA_INDEX)

    max_page = max((int(n) for n in _MAX_PAGE.findall(html1)), default=1)
    print(f"  Pagination: {max_page} page(s) total.")

    for page in range(2, max_page + 1):
        url = f"https://unrae.it/dati-statistici/immatricolazioni?page={page}"
        print(f"  Fetching page {page}/{max_page} …", end="\r", flush=True)
        _scrape(url)
        time.sleep(0.5)

    if max_page > 1:
        print()  # newline after the \r progress line

    sorted_results = sorted(found.items())
    return [(url, year, month) for (year, month), url in sorted_results]


# ── PDF parsing (mirrors fetch_italy.py) ─────────────────────────────────────

_NUM = re.compile(r"-?\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+")


def _first_int(line: str) -> int:
    m = _NUM.search(line)
    if not m:
        raise ValueError(f"No number in line: {line!r}")
    tok = m.group(0).replace(".", "")
    if "," in tok:
        tok = tok.split(",", 1)[0]
    return int(tok)


def _parse_alimentazione_block(lines: list[str], start: int, end: int) -> dict:
    block = lines[start:end]

    def find_value(*prefixes: str, required: bool = True) -> int:
        for pfx in prefixes:
            for ln in block:
                if ln.lstrip().startswith(pfx):
                    return _first_int(ln)
        if required:
            raise RuntimeError(
                f"Row {prefixes[0]!r} not found in 'Per alimentazione' block."
            )
        return 0  # UNRAE omits rows with 0 registrations

    # Older UNRAE PDFs (pre-2021) used different row labels.
    # Primary names are current; fallbacks cover historical variants.
    return {
        "BEV":    find_value("Elettriche (BEV)", "Elettrici"),
        "PHEV":   find_value("Ibride elettriche plug-in", "Plug-in"),
        "HEV":    find_value("Ibride elettriche (HEV)", "Ibride elettriche", "Ibride"),
        "PETROL": find_value("Benzina"),
        "DIESEL": find_value("Diesel"),
        "OTHERS": (find_value("Gpl", required=False)
                   + find_value("Metano", required=False)
                   + find_value("Idrogeno (FCEV)", required=False)),
        "TOTAL":  find_value("Totale mercato", "Totale"),
    }


def _parse_pkw(text: str) -> tuple[dict, dict] | None:
    """
    Returns (whole_cols, rental_cols) or None if the PDF lacks the
    'al netto del noleggio' section (pre-2017 format).
    """
    lines = text.splitlines()
    alim_starts = [i for i, ln in enumerate(lines) if "Per alimentazione" in ln]

    if len(alim_starts) < 2:
        return None  # older PDF without rental section

    def block_end(start: int) -> int:
        for j in range(start + 1, len(lines)):
            if "Per segmento" in lines[j]:
                return j
        return len(lines)

    try:
        whole_cols     = _parse_alimentazione_block(lines, alim_starts[0], block_end(alim_starts[0]))
        netto_nol_cols = _parse_alimentazione_block(lines, alim_starts[1], block_end(alim_starts[1]))
    except RuntimeError as exc:
        raise RuntimeError(f"PDF parse error: {exc}") from exc

    rental_cols = {k: whole_cols[k] - netto_nol_cols[k] for k in whole_cols}
    return whole_cols, rental_cols


def _find_struttura_pdf_url(detail_html: str) -> str:
    pat = re.compile(
        r'href="(https://unrae\.it/files/[^"]*Struttura del mercato[^"]+\.pdf)"',
        re.IGNORECASE,
    )
    m = pat.search(detail_html)
    if not m:
        raise RuntimeError("No 'Struttura del mercato' PDF link found on detail page.")
    return m.group(1)


def _sanity_check(cols: dict, period: str) -> None:
    core  = (cols["BEV"] + cols["PHEV"] + cols["HEV"]
             + cols["PETROL"] + cols["DIESEL"] + cols["OTHERS"])
    total = cols["TOTAL"]
    if total <= 0:
        raise RuntimeError(f"{period}: TOTAL is {total}; refusing to write.")
    tol = max(50, total * 0.005)
    if abs(core - total) > tol:
        raise RuntimeError(
            f"{period}: sum={core} vs TOTAL={total} (diff={core - total}); "
            f"tolerance={tol:.0f}"
        )


# ── CSV helpers ───────────────────────────────────────────────────────────────

def _load_existing_periods(csv_path: str) -> set[str]:
    if not os.path.exists(csv_path):
        return set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        return {r["period"] for r in csv.DictReader(f) if r.get("variant") == "Rental"}


def _upsert(csv_path: str, period: str, cols: dict) -> str:
    rows: list[dict] = []
    old = None
    if os.path.exists(csv_path):
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                for c in CSV_COLUMNS:
                    row.setdefault(c, "")
                if row["period"] == period and row["variant"] == "Rental":
                    old = row
                else:
                    rows.append(row)

    new_row = {
        "period": period, "time_interval": "monthly", "variant": "Rental",
        "source": SOURCE,
        "BEV": cols["BEV"], "PHEV": cols["PHEV"], "HEV": cols["HEV"],
        "PETROL": cols["PETROL"], "DIESEL": cols["DIESEL"],
        "OTHERS": cols["OTHERS"], "TOTAL": cols["TOTAL"], "notes": "",
    }
    if not new_row["notes"] and old is not None:
        new_row["notes"] = old.get("notes", "")

    status = "added" if old is None else "updated"
    rows.append(new_row)
    rows.sort(key=lambda r: r["period"])

    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return status


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-year", type=int, default=2017,
                    help="Earliest year to attempt (default: 2017).")
    ap.add_argument("--force", action="store_true",
                    help="Re-parse and overwrite periods already in the CSV.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Discover missing periods and print them; do not download PDFs.")
    ap.add_argument("--csv", default=RENTAL_CSV,
                    help=f"Path to Italy_Rental.csv (default: {RENTAL_CSV}).")
    args = ap.parse_args()

    print(f"Discovering UNRAE struttura bulletins from {args.from_year} onwards …")
    bulletins = discover_all_bulletins(from_year=args.from_year)
    if not bulletins:
        sys.exit("No bulletins discovered — check network / UNRAE website structure.")

    print(f"Found {len(bulletins)} bulletin(s) on UNRAE website.")

    existing = _load_existing_periods(args.csv)
    to_process = [
        (detail_url, year, month)
        for detail_url, year, month in bulletins
        if args.force or f"{year}-{month:02d}" not in existing
    ]

    if not to_process:
        print("Italy_Rental.csv is already up to date for all discovered bulletins.")
        return

    print(f"{len(to_process)} month(s) to process:")
    for _, y, m in to_process:
        print(f"  {y}-{m:02d}")

    if args.dry_run:
        print("Dry-run mode — no downloads.")
        return

    added = updated = skipped = errors = 0

    for detail_url, year, month in to_process:
        period = f"{year}-{month:02d}"
        print(f"\n── {period} ──")
        try:
            detail_html = http_get(detail_url)
            pdf_url     = _find_struttura_pdf_url(detail_html)
            print(f"  PDF: {pdf_url}")

            time.sleep(THROTTLE_S)

            with tempfile.TemporaryDirectory() as td:
                pdf_path = Path(td) / "struttura.pdf"
                download_pdf(pdf_url, pdf_path)
                text = pdf_to_text(pdf_path)

            result = _parse_pkw(text)
            if result is None:
                print(f"  SKIP {period}: PDF has no 'al netto del noleggio' section "
                      f"(pre-2017 format).")
                skipped += 1
                continue

            whole_cols, rental_cols = result
            _sanity_check(rental_cols, period)

            print(f"  Rental {period}: BEV={rental_cols['BEV']}  "
                  f"PHEV={rental_cols['PHEV']}  HEV={rental_cols['HEV']}  "
                  f"PETROL={rental_cols['PETROL']}  DIESEL={rental_cols['DIESEL']}  "
                  f"OTHERS={rental_cols['OTHERS']}  TOTAL={rental_cols['TOTAL']}")

            status = _upsert(args.csv, period, rental_cols)
            print(f"  → {status} {args.csv}")
            if status == "added":
                added += 1
            else:
                updated += 1

        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR {period}: {exc}")
            errors += 1

    print(f"\nDone. added={added}  updated={updated}  skipped={skipped}  errors={errors}")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
