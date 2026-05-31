#!/usr/bin/env python3
"""
Fetch Colombia new passenger-car registration data from the joint FENALCO/ANDI
monthly "Informe del Sector Automotor" PDF (linked from ANDI's Cámara
Automotriz page) and upsert data/Colombia.csv.

Usage
-----
    python scripts/fetch_colombia.py [--pdf-url URL] [--force]

Source
------
ANDI's Cámara Automotriz (Cámara 4) page lists each month's "Informe del
Sector Automotor" PDF (prefix "N. INFORME SECTOR AUTOMOTOR <MMM>_PRENSA-
INDUSTRIA <YYYY>_<ticks>.pdf"; the underlying figures are sourced from RUNT,
Colombia's official vehicle registry — the same registry behind ANDEMOS's
gated dashboards). Each monthly PDF carries the previous ~3 years of MONTHLY
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

Parser
------
Uses `pdftotext -layout` (poppler) to extract the chart-by-chart monthly
series. Each chart's bars are emitted as text lines like
    `ene-25                          966`
and the three series (Pkw total, BEV, Hybrid) appear in order. The parser
groups matches into batches by detecting (year, month) resets — each batch
is one chart — and assigns Pkw / BEV / Hybrid by position. Numbers use
Spanish formatting: `.` is the thousands separator (`14.558` → 14558).

Discovery
---------
The Cámara Automotriz page (https://www.andi.com.co/Home/Camara/4-automotriz)
embeds the PDF download links. We regex-pick the URL with the highest
(year, month-number) from the "N. INFORME SECTOR AUTOMOTOR …" pattern. The
URL hash changes per upload, so direct construction isn't possible — always
scrape the listing.

See docs/architecture/18-source-colombia.md for the full playbook.
"""
import argparse
import csv
import os
import re
import subprocess
from datetime import date
from pathlib import Path

import requests

CAMARA_URL = "https://www.andi.com.co/Home/Camara/4-automotriz"
SOURCE = "andi.com.co + fenalco (datos RUNT)"
CSV_PATH = "data/Colombia.csv"
VARIANT = "Whole"

MONTH_ABBR = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
              "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12}

CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "FLEXFUEL",
    "OTHERS", "ICE", "TOTAL", "notes",
]

# Pattern: e.g. "12. INFORME SECTOR AUTOMOTOR DIC_PRENSA-INDUSTRIA 2025_<ticks>.pdf"
# (URL-encoded as %20 between words). Captures (month_num, month_abbr, year).
# The MMM is captured (not just the numeric prefix) so we can validate the
# two agree — humans uploading sometimes mistype one or the other.
PDF_FILENAME_RE = re.compile(
    r'/Uploads/(\d{1,2})\.%20INFORME%20SECTOR%20AUTOMOTOR%20([A-Z]{3})_PRENSA-INDUSTRIA%20(\d{4})_\d+\.pdf',
    re.IGNORECASE,
)

# Matches lines like "ene-25        966" in pdftotext -layout output.
MONTH_VALUE_RE = re.compile(
    r'\b(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)-(\d{2})\s+([\d.]+)\b'
)


def discover_latest_pdf(session: requests.Session) -> tuple[str, int, int]:
    """Return (pdf_url, year, month_num) for the freshest 'Informe Sector Automotor' PDF."""
    r = session.get(CAMARA_URL, timeout=30)
    r.raise_for_status()
    candidates = []
    for m in PDF_FILENAME_RE.finditer(r.text):
        n = int(m.group(1))
        # n is the month-number prefix (1..12); the MMM abbr should agree
        mmm_n = MONTH_ABBR.get(m.group(2).lower())
        year = int(m.group(3))
        if mmm_n and mmm_n == n:
            candidates.append((year, n, m.group(0)))
    if not candidates:
        raise RuntimeError(
            "No 'INFORME SECTOR AUTOMOTOR <N>. ... _PRENSA-INDUSTRIA <YYYY>_<ticks>.pdf' "
            "links found on the Cámara Automotriz page — its layout may have changed."
        )
    candidates.sort(reverse=True)  # latest (year, month) first
    year, n, path = candidates[0]
    url = "https://www.andi.com.co" + path
    return url, year, n


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
    rows: dict = {}
    for period, total in pkw_m.items():
        b = bev_m.get(period, 0)
        h = hev_m.get(period, 0)
        ice = max(0, total - b - h)
        rows[(period, VARIANT)] = {
            "period": period, "time_interval": "monthly", "variant": VARIANT, "source": SOURCE,
            "BEV": float(b), "PHEV": "", "HEV": float(h),
            "PETROL": "", "DIESEL": "", "FLEXFUEL": "", "OTHERS": "",
            "TOTAL": float(total), "ICE": float(ice), "notes": "",
        }
    return rows


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
            old = existing[key]
            for c in ["BEV", "HEV", "ICE", "TOTAL"]:
                ov = float(old.get(c) or 0)
                nv = float(new_row[c] or 0)
                if ov > 100 and abs(nv - ov) / ov > 0.5:
                    print(f"  WARNING {key[1]} {key[0]} {c}: existing={ov:.0f}, new={nv:.0f} "
                          f"— diff >50%, please verify")
            existing[key] = {**old, **new_row}
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
        return any(r["period"] == period and r["variant"] == VARIANT for r in csv.DictReader(f))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf-url", default=None,
                    help="Skip discovery and use this PDF URL directly.")
    ap.add_argument("--force", action="store_true",
                    help="Skip the 'previous month already present' early-exit.")
    args = ap.parse_args()

    if not args.pdf_url and not args.force and csv_has_period(CSV_PATH, previous_month_period()):
        print(f"CSV already has {previous_month_period()}; nothing to do (use --force or --pdf-url).")
        return

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})

    if args.pdf_url:
        url, year, n = args.pdf_url, None, None
    else:
        url, year, n = discover_latest_pdf(session)
        print(f"Latest PDF: {year}-{n:02d} -> {url}")

    pdf = download_pdf(url, session)
    text = pdf_to_text(pdf)
    batches = extract_series(text)
    print(f"Parsed {len(batches)} monthly series in PDF "
          f"({', '.join(str(len(b)) for b in batches[:4])} rows)")

    rows = assemble_rows(batches)
    if not rows:
        print("No rows extracted.")
        return
    periods = sorted(p for p, _ in rows)
    print(f"Total months: {len(rows)} ({periods[0]} .. {periods[-1]})")
    added, updated = upsert_csv(CSV_PATH, rows)
    print(f"{added} added, {updated} updated -> {CSV_PATH}")


if __name__ == "__main__":
    main()
