#!/usr/bin/env python3
"""
Fetch Colombia new passenger-car registration data from the joint FENALCO/ANDI
monthly "Informe del Sector Automotor" PDF (linked from ANDI's Cámara
Automotriz page) and upsert data/Colombia.csv.

Usage
-----
    python scripts/fetch_colombia.py [--pdf-url URL] [--force] [--dry-run]
                                     [--dump-text] [--debug-dir DIR]

Source
------
ANDI's Cámara Automotriz (Cámara 4) page lists each month's "Informe del
Sector Automotor" PDF. The underlying figures are sourced from RUNT,
Colombia's official vehicle registry — the same registry behind ANDEMOS's
gated dashboards. Each monthly PDF carries the previous ~3 years of MONTHLY
time series for total passenger-car registrations, BEV ("eléctricos"), and
hybrids ("híbridos", a single combined bucket — Colombia does not split PHEV
vs HEV in this report).

Convention (Türkiye / Georgia style "single Hybrid bucket")
-----------------------------------------------------------
    BEV       <- eléctricos (battery electric)
    HEV       <- híbridos    (combined hybrids — labelled "Hybrid" in posts)
    PHEV/MHEV <- (not split by source; left empty)
    ICE       <- TOTAL − BEV − HEV   (sum of petrol / diesel / other,
                                       no further split available)
    PETROL / DIESEL / FLEXFUEL / OTHERS — empty (not split by source)
    TOTAL     <- passenger-car total (Pkw)

Discovery
---------
The Cámara Automotriz page (https://www.andi.com.co/Home/Camara/4-automotriz)
embeds the PDF download links. ANDI has renamed the files more than once —
observed shapes so far:

    /Uploads/12.%20INFORME%20SECTOR%20AUTOMOTOR%20DIC_PRENSA-INDUSTRIA%202025_<ticks>.pdf   (2025)
    /Uploads/02.%20INFORME%20SECTOR%20AUTOMOTOR%20FEB2026_PRENSA.pdf                        (2026)
    /Uploads/06.%20INFORME%20SECTOR%20AUTOMOTOR%20JUNIO%202021_PRENSA.pdf                   (2021)
    /Uploads/INFORME%20DEL%20SECTOR%20AUTOMOTOR%20A%20DICIEMBRE%202022.pdf                  (annual)

A strict regex on the 2025 shape is what stalled the fetcher for all of 2026
(the scheduled run kept re-reading the Dec-2025 PDF as "latest"). Discovery
therefore no longer pins a filename template: every `.pdf` href whose
URL-decoded basename contains INFORME + SECTOR + AUTOMOTOR is a candidate,
the month comes from the first Spanish month token (abbreviation or full
name) and the year from the first standalone 4-digit year. Candidates are
sorted by (year, month), with a "_PRENSA" monthly file preferred over an
annual "A DICIEMBRE" one for the same month. The per-upload ticks hash makes
URLs unguessable — always scrape the listing.

Parser
------
Uses `pdftotext -layout` (poppler) to extract the chart-by-chart monthly
series. Each chart's bars are emitted as text lines like
    `ene-25                          966`
and the three series (Pkw total, BEV, Hybrid) appear in order. The parser
groups matches into batches by detecting (year, month) resets — each batch
is one chart — and assigns Pkw / BEV / Hybrid by position. Numbers use
Spanish formatting: `.` is the thousands separator (`14.558` → 14558).

Missing values are missing, not zero
------------------------------------
On some bars pdftotext puts the value on a different line from the month
label, so a series can come back without a value for a month. Such a month
is treated as *unknown* — it never overwrites a value already in the CSV
(a scheduled run once reset two hand-corrected BEV cells to 0 that way), and
a month that is not in the CSV yet is skipped with a warning instead of
being written with BEV=0. The newest month in the PDF must be complete,
otherwise the run fails loud.

See docs/architecture/18-source-colombia.md for the full playbook.
"""
import argparse
import csv
import html
import os
import re
import subprocess
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

CAMARA_URL = "https://www.andi.com.co/Home/Camara/4-automotriz"
SOURCE = "andi.com.co + fenalco (datos RUNT)"
CSV_PATH = "data/Colombia.csv"
VARIANT = "Whole"

MONTH_ABBR = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
              "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12}

# Full Spanish month names as they appear in older filenames ("JUNIO 2021").
# Looked up after stripping to the first three letters, which is unambiguous
# for Spanish month names (SEPTIEMBRE / SETIEMBRE both start with SE-, so
# "SET" is added explicitly).
MONTH_NAME_RE = re.compile(
    r'(?<![A-Z])(ENERO|FEBRERO|MARZO|ABRIL|MAYO|JUNIO|JULIO|AGOSTO|SEPTIEMBRE|SETIEMBRE|'
    r'OCTUBRE|NOVIEMBRE|DICIEMBRE|ENE|FEB|MAR|ABR|MAY|JUN|JUL|AGO|SEPT|SEP|SET|OCT|NOV|DIC)(?![A-Z])'
)
YEAR_RE = re.compile(r'(?<!\d)(20\d{2})(?!\d)')
NUM_PREFIX_RE = re.compile(r'^\s*(\d{1,2})\s*\.')

CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "FLEXFUEL",
    "OTHERS", "ICE", "TOTAL", "notes",
]

# Every href that ends in .pdf (query strings tolerated). The basename is
# filtered afterwards, once URL-decoded, so both "%20" and literal-space
# hrefs are handled.
HREF_PDF_RE = re.compile(r'''href\s*=\s*["']([^"']+?\.pdf)(?:[?#][^"']*)?["']''', re.IGNORECASE)

# Matches lines like "ene-25        966" in pdftotext -layout output.
# Restricted to NON-NEWLINE whitespace so we don't accidentally pair a month-
# token with a value on a later line — different poppler versions break lines
# slightly differently, and on some versions the YTD-cumulative labels (e.g.
# "19.724  (Ene-dic 2025)") sit close enough to a month-token across a newline
# to be mis-paired. Same-line-only is the safer invariant.
MONTH_VALUE_RE = re.compile(
    r'\b(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)-(\d{2})[ \t]+([\d.]+)\b'
)


def _basename(href: str) -> str:
    """URL-decode + HTML-unescape an href and return its last path segment."""
    decoded = unquote(html.unescape(href))
    return decoded.rsplit("/", 1)[-1]


def classify_pdf_name(name: str):
    """Return (year, month, is_monthly) for an 'Informe Sector Automotor' filename, else None.

    `name` is the decoded basename. Returns None for PDFs that are not the
    bulletin, or where no month/year can be read.
    """
    upper = name.upper()
    if not ("INFORME" in upper and "SECTOR" in upper and "AUTOMOTOR" in upper):
        return None
    m_month = MONTH_NAME_RE.search(upper)
    m_year = YEAR_RE.search(upper)
    if not (m_month and m_year):
        return None
    month = MONTH_ABBR["sep" if m_month.group(1)[:3] == "SET" else m_month.group(1)[:3].lower()]
    year = int(m_year.group(1))
    m_prefix = NUM_PREFIX_RE.match(upper)
    if m_prefix and int(m_prefix.group(1)) != month:
        # ANDI's numeric prefix and the month token disagree — a human typo on
        # upload. The month token has been the reliable one so far; keep the
        # candidate but say so, the post-parse cross-check catches the rest.
        print(f"  WARNING numeric prefix {m_prefix.group(1)} != month {month} in '{name}' — trusting the month token")
    # Annual "INFORME DEL SECTOR AUTOMOTOR A DICIEMBRE 2022.pdf" has a
    # different layout; prefer the monthly "_PRENSA" file on ties.
    is_monthly = "PRENSA" in upper
    return year, month, is_monthly


def discover_latest_pdf(session: requests.Session) -> tuple[str, int, int]:
    """Return (pdf_url, year, month_num) for the freshest 'Informe Sector Automotor' PDF."""
    r = session.get(CAMARA_URL, timeout=30)
    r.raise_for_status()
    candidates = []
    seen = set()
    for m in HREF_PDF_RE.finditer(r.text):
        href = m.group(1)
        info = classify_pdf_name(_basename(href))
        if info is None:
            continue
        year, month, is_monthly = info
        url = urljoin(CAMARA_URL, html.unescape(href))
        if url in seen:
            continue
        seen.add(url)
        candidates.append((year, month, is_monthly, url))
    if not candidates:
        raise RuntimeError(
            "No 'INFORME SECTOR AUTOMOTOR' PDF links found on the Cámara Automotriz "
            "page — its layout may have changed. Inspect the page HTML for the "
            "bulletin links and update discovery in scripts/fetch_colombia.py."
        )
    candidates.sort(reverse=True)  # latest (year, month) first, monthly before annual
    print(f"Bulletin PDFs on the Cámara page ({len(candidates)}), newest first:")
    for year, month, is_monthly, url in candidates[:6]:
        print(f"  {year}-{month:02d} {'monthly' if is_monthly else 'annual '} {_basename(url)}")
    year, month, _, url = candidates[0]
    return url, year, month


def download_pdf(url: str, session: requests.Session) -> bytes:
    r = session.get(url, timeout=60)
    r.raise_for_status()
    if not r.content.startswith(b"%PDF"):
        raise RuntimeError(f"Downloaded file is not a PDF: {url}")
    return r.content


def pdf_to_text(pdf_bytes: bytes) -> str:
    """Run `pdftotext -layout` reading stdin and return stdout text."""
    out = subprocess.run(
        ["pdftotext", "-layout", "-", "-"],
        input=pdf_bytes, capture_output=True, check=True,
    )
    return out.stdout.decode("utf-8", errors="replace")


def parse_value(s: str) -> int:
    """'14.558' -> 14558 (Spanish thousands separator)."""
    return int(s.replace(".", ""))


def extract_series(text: str) -> list[list[tuple[int, int, int]]]:
    """Group (year, month, value) matches into batches by (year, month) reset.

    Each PDF chart emits its bars in chronological order; a new chart starts
    when the month-year decreases. Returns a list of batches in PDF order.
    """
    matches = []
    for m in MONTH_VALUE_RE.finditer(text):
        year = 2000 + int(m.group(2))
        month = MONTH_ABBR[m.group(1)]
        val = parse_value(m.group(3))
        matches.append((year, month, val))

    batches: list[list[tuple[int, int, int]]] = []
    current: list[tuple[int, int, int]] = []
    last = (0, 0)
    for ym in matches:
        if (ym[0], ym[1]) < last:
            batches.append(current)
            current = []
        current.append(ym)
        last = (ym[0], ym[1])
    if current:
        batches.append(current)
    return batches


def assemble_rows(batches: list) -> dict:
    """From batches [Pkw, BEV, Hybrid, Carga?], build {(period, variant): row}.

    Position-based assignment assumes the chart order Pkw → BEV → Hybrid as
    published. Sanity-check it with a magnitude assertion (Pkw must dominate) —
    if ANDI ever reorders the charts we want to fail loud, not silently
    mis-attribute series.

    A month whose BEV or Hybrid bar did not come through pdftotext gets
    ``None`` in that cell (unknown), never 0 — `upsert_csv` decides what to
    do with it. The newest month in the PDF must be complete.
    """
    if len(batches) < 3:
        raise RuntimeError(
            f"Expected at least 3 monthly series in the PDF (Pkw / BEV / Hybrid); "
            f"got {len(batches)}. PDF layout may have changed."
        )
    # Pkw is always the largest series (BEV and Hybrid are subsets), so its
    # peak value must dominate the other two. If the chart order ever changes,
    # this assertion fires instead of us silently mis-attributing series.
    maxes = [max(v for _, _, v in b) for b in batches[:3]]
    if not (maxes[0] >= maxes[1] and maxes[0] >= maxes[2]):
        raise RuntimeError(
            f"Chart order looks off: max values per batch = {maxes}; "
            f"expected the first batch (Pkw) to be the largest. PDF layout may have changed."
        )
    pkw, bev, hev = batches[0], batches[1], batches[2]

    def to_map(b):
        return {f"{y}-{m:02d}": v for (y, m, v) in b}

    pkw_m, bev_m, hev_m = to_map(pkw), to_map(bev), to_map(hev)
    newest = max(set(pkw_m) | set(bev_m) | set(hev_m))
    for label, series in (("TOTAL", pkw_m), ("BEV", bev_m), ("HEV", hev_m)):
        if newest not in series:
            raise RuntimeError(
                f"[{newest}] the newest month in the PDF has no {label} value — "
                f"pdftotext split the label from its bar. Inspect the PDF text "
                f"(run with --dump-text) and tighten the parser before publishing."
            )
    rows: dict = {}
    for period, total in pkw_m.items():
        b = bev_m.get(period)
        h = hev_m.get(period)
        # Definitional invariant: BEV and Hybrid are subsets of TOTAL, so their
        # sum cannot exceed it. If it does, the parser picked up a YTD label
        # or some other non-monthly value — fail loud rather than publish a
        # nonsense BEV-share.
        if (b or 0) + (h or 0) > total:
            raise RuntimeError(
                f"[{period}] BEV+HEV ({b}+{h}={(b or 0) + (h or 0)}) exceeds TOTAL ({total}) — "
                f"parser likely picked up a YTD label as a monthly value. "
                f"Inspect the PDF text around {period}."
            )
        rows[(period, VARIANT)] = {
            "period": period, "time_interval": "monthly", "variant": VARIANT, "source": SOURCE,
            "BEV": b, "PHEV": "", "HEV": h,
            "PETROL": "", "DIESEL": "", "FLEXFUEL": "", "OTHERS": "",
            "TOTAL": total, "ICE": None, "notes": "",
        }
    return rows


def _num(v) -> float | None:
    """CSV cell -> float, '' -> None."""
    if v is None or v == "":
        return None
    return float(v)


def merge_row(old: dict | None, new: dict) -> tuple[dict | None, list[str]]:
    """Combine a parsed row with the existing CSV row for the same period.

    Returns (row_to_write, warnings). ``None`` means "leave the CSV alone":
    a new month with an unknown BEV/HEV cell is not written at all — a gap
    in the chart is honest, BEV=0 is not.
    """
    warnings: list[str] = []
    total = float(new["TOTAL"])
    bev = None if new["BEV"] is None else float(new["BEV"])
    hev = None if new["HEV"] is None else float(new["HEV"])
    old_bev = _num(old.get("BEV")) if old else None
    old_hev = _num(old.get("HEV")) if old else None

    # Unknown in the PDF text -> keep whatever the CSV already has.
    if bev is None and old_bev is not None:
        bev = old_bev
    if hev is None and old_hev is not None:
        hev = old_hev
    # A parsed 0 on a month that already carries a real count is the same
    # parser gap wearing a different hat — never downgrade a value to 0.
    if bev == 0 and old_bev:
        warnings.append(f"BEV parsed as 0 but CSV has {old_bev:.0f} — keeping the CSV value")
        bev = old_bev
    if hev == 0 and old_hev:
        warnings.append(f"HEV parsed as 0 but CSV has {old_hev:.0f} — keeping the CSV value")
        hev = old_hev
    if bev is None or hev is None:
        if old:
            return None, warnings  # existing row stays as it is
        warnings.append("BEV/HEV missing in the PDF text and no existing row — month skipped")
        return None, warnings

    if old:
        for col, ov, nv in (("BEV", old_bev, bev), ("HEV", old_hev, hev),
                            ("TOTAL", _num(old.get("TOTAL")), total)):
            if ov and ov > 100 and abs(nv - ov) / ov > 0.5:
                warnings.append(f"{col}: existing={ov:.0f}, new={nv:.0f} — diff >50%, please verify")

    row = {**(old or {}), **new}
    row["BEV"] = float(bev)
    row["HEV"] = float(hev)
    row["TOTAL"] = float(total)
    row["ICE"] = float(max(0.0, total - bev - hev))
    return row, warnings


def read_csv(csv_path: str) -> dict:
    existing: dict = {}
    if os.path.exists(csv_path):
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                for c in CSV_COLUMNS:
                    row.setdefault(c, "")
                existing[(row["period"], row["variant"])] = {k: row[k] for k in CSV_COLUMNS}
    return existing


def upsert_csv(csv_path: str, new_rows: dict, write: bool = True) -> tuple[int, int, int]:
    """Merge parsed rows into the CSV. Returns (added, updated, skipped)."""
    existing = read_csv(csv_path)

    added = updated = skipped = 0
    for key, new_row in sorted(new_rows.items()):
        old = existing.get(key)
        merged, warnings = merge_row(old, new_row)
        for w in warnings:
            print(f"  WARNING {key[1]} {key[0]} {w}")
        if merged is None:
            skipped += 1
            continue
        if old is None:
            added += 1
            print(f"  + {key[1]} {key[0]}")
        elif any(str(merged[c]) != str(old[c]) for c in ("BEV", "HEV", "ICE", "TOTAL")):
            updated += 1
            print(f"  ~ {key[1]} {key[0]}")
        existing[key] = merged

    if write:
        Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
            w.writeheader()
            for key in sorted(existing.keys(), key=lambda k: (k[1], k[0])):
                w.writerow(existing[key])
    return added, updated, skipped


def previous_month_period() -> str:
    t = date.today()
    if t.month == 1:
        return f"{t.year - 1}-12"
    return f"{t.year}-{t.month - 1:02d}"


def csv_periods(csv_path: str) -> list[str]:
    if not os.path.exists(csv_path):
        return []
    with open(csv_path, newline="", encoding="utf-8") as f:
        return sorted(r["period"] for r in csv.DictReader(f) if r["variant"] == VARIANT)


def csv_has_period(csv_path: str, period: str) -> bool:
    return period in csv_periods(csv_path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf-url", default=None,
                    help="Skip discovery and use this PDF URL directly.")
    ap.add_argument("--force", action="store_true",
                    help="Skip the 'previous month already present' early-exit.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Discover, download and parse, print what would change, but do not write the CSV.")
    ap.add_argument("--dump-text", action="store_true",
                    help="Print the full `pdftotext -layout` output to stdout (for parser work in CI logs).")
    ap.add_argument("--debug-dir", default=None,
                    help="Save the downloaded PDF and its pdftotext output into this directory.")
    args = ap.parse_args()

    if not args.pdf_url and not args.force and not args.dry_run \
            and csv_has_period(CSV_PATH, previous_month_period()):
        print(f"CSV already has {previous_month_period()}; nothing to do (use --force or --pdf-url).")
        return

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
    # andi.com.co intermittently drops the connection mid-handshake, which
    # surfaced as a hard `RemoteDisconnected` on the very first GET and failed
    # the whole scheduled run. Retry connect/read errors and the usual
    # transient status codes with backoff (same shape as fetch_austria.py).
    session.mount("https://", HTTPAdapter(max_retries=Retry(
        total=5,
        connect=5,
        read=3,
        backoff_factor=3,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )))

    if args.pdf_url:
        url, year, n = args.pdf_url, None, None
        info = classify_pdf_name(_basename(url))
        if info:
            year, n = info[0], info[1]
    else:
        url, year, n = discover_latest_pdf(session)
    print(f"Latest PDF: {year}-{n:02d} -> {url}" if year else f"PDF: {url}")

    periods = csv_periods(CSV_PATH)
    if year and periods:
        pdf_period = f"{year}-{n:02d}"
        latest_csv = periods[-1]
        if pdf_period < latest_csv and not args.pdf_url:
            # Normal between publications is "PDF == latest CSV month". Two or
            # more months behind means discovery is probably picking a stale
            # file — the exact failure this fetcher stalled on for months.
            months_behind = (int(latest_csv[:4]) - year) * 12 + int(latest_csv[5:]) - n
            msg = (f"Newest bulletin on the Cámara page is {pdf_period} but the CSV already "
                   f"runs to {latest_csv} ({months_behind} month(s) ahead)")
            if months_behind >= 2:
                print(f"::warning title=Colombia discovery may be stale::{msg}")
            print(f"{msg} — re-reading it anyway (existing values are never downgraded).")

    pdf = download_pdf(url, session)
    text = pdf_to_text(pdf)
    if args.debug_dir:
        d = Path(args.debug_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / "bulletin.pdf").write_bytes(pdf)
        (d / "bulletin.txt").write_text(text, encoding="utf-8")
        print(f"Saved PDF + pdftotext output to {d}/")
    if args.dump_text:
        print("----- BEGIN pdftotext -layout -----")
        print(text)
        print("----- END pdftotext -layout -----")

    batches = extract_series(text)
    print(f"Parsed {len(batches)} monthly series in PDF "
          f"({', '.join(str(len(b)) for b in batches[:4])} rows)")
    for i, b in enumerate(batches[:4]):
        print(f"  batch {i}: {len(b)} months, first={b[0]} last={b[-1]}")

    rows = assemble_rows(batches)
    if not rows:
        print("No rows extracted.")
        return
    parsed_periods = sorted(p for p, _ in rows)
    print(f"Total months: {len(rows)} ({parsed_periods[0]} .. {parsed_periods[-1]})")
    if year and parsed_periods[-1] != f"{year}-{n:02d}":
        print(f"  WARNING newest month in the PDF text is {parsed_periods[-1]}, "
              f"but the filename says {year}-{n:02d}")

    added, updated, skipped = upsert_csv(CSV_PATH, rows, write=not args.dry_run)
    verb = "would be" if args.dry_run else ""
    print(f"{added} added, {updated} updated, {skipped} skipped {verb} -> {CSV_PATH}"
          + (" (dry run, nothing written)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
