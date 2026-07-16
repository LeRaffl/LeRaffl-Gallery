#!/usr/bin/env python3
"""
Fetch Indonesia vehicle wholesales data from GAIKINDO and update
data/Indonesia.csv (+ Pickups / HDV / Buses variant CSVs).

Usage
-----
    python scripts/fetch_indonesia.py [--pdf-path PATH] [--download-url URL] \
        [--csv-dir DIR] [--force]

* --pdf-path      Parse a local PDF instead of logging in (offline testing).
* --download-url  Direct portal download URL (skips file discovery, not login).
* --csv-dir       Directory holding the Indonesia*.csv files (default: data).
* --force         Re-process even if the newest period already exists.

Invoked by .github/workflows/fetch-indonesia.yml on a daily cron from the
10th of each month onward, plus manual workflow_dispatch. When a CSV changes,
the workflow commits it and triggers render-country.yml for Indonesia.

Data source
-----------
GAIKINDO (Gabungan Industri Kendaraan Bermotor Indonesia) publishes monthly
cumulative wholesales PDFs ("Wholesales Jan-Jun 2026") on its ProjectSend
portal https://files.gaikindo.or.id/ . The public file list
(list-files.php) carries titles only; downloading needs a client login:
username in INDONESIA_GAIKINDO_USER (default "LeRaffl"), password in
INDONESIA_GAIKINDO_PW (GitHub Actions secret). Login is a plain POST of
{csrf_token, do=login, username, password} to index.php — no captcha.

Each cumulative file restates all year-to-date months (revisions included),
so every run rewrites all covered months of the current year.

PDF layout
----------
The PDF is an Excel paste-up: 3 A3 pages, ~1.56 pt font, seven per-model
sheets with a fixed section structure (validated against the printed
section-total rows, so any format drift fails loudly):

    1. SEDAN TYPE SALES               → Whole (passenger cars)
    2. 4X2 TYPE SALES                 → Whole
    3. 4X4 TYPE SALES                 → Whole
    4. BUS SALES                      → Buses
    5. PICK UP/TRUCK SALES            → Pickups (GVW < 5 t) / HDV (≥ 5 t)
    6. DOUBLE CABIN SALES             → Pickups
    7. AFFORDABLE ENERGY SAVING CARS  → Whole (LCGC)

"Whole" = GAIKINDO's own PASSENGER CAR definition (sedan, 4x2, 4x4, KBM
Hemat Energi & Terjangkau) — the same scope robbieandrew.github.io used for
the pre-2026 rows in data/Indonesia.csv, so the series is continuous.
See docs/architecture/09-glossary.md § Vehicle scope per source.

Parsing strategy
----------------
pdfplumber word extraction with tight tolerances (default tolerances merge
whole rows at this font size). Per sheet: month columns come from the
JAN..DEC header row, the fuel column from the FUEL header. Values are
right-aligned and sometimes split into several tokens ("3 00" = 300), so
tokens are concatenated per column band. Rows wrap vertically (long tyre
texts); value fragments without a fuel cell are re-attached to the nearest
fuel row. FUEL is one of G/D/BEV/HEV/PHEV; "-" and rarities (e.g. CNG
tractor heads) go to OTHERS.

Validation (hard failure on any mismatch):
  * per section × month: sum of model rows == printed "<SECTION> SALES TOTAL"
  * PASSENGER CAR / COMMERCIAL VEHICLE / DOMESTIC summary rows == aggregates
  * Pickups + HDV == PICK UP/TRUCK section total

CSV layout
----------
period,time_interval,variant,source,BEV,PHEV,HEV,PETROL,DIESEL,OTHERS,TOTAL,notes
  G → PETROL, D → DIESEL, BEV/HEV/PHEV → same-named columns,
  everything else → OTHERS. TOTAL = sum of the six fuel columns.
  source = "GAIKINDO", notes = portal file title.
"""
import argparse
import csv
import io
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import pdfplumber
import requests
from bs4 import BeautifulSoup

PORTAL = "https://files.gaikindo.or.id/"
FILE_LIST_PAGES = ["manage-files.php", "my-files.php", "my_files.php"]

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL", "notes",
]

FUEL_COLUMN = {"G": "PETROL", "D": "DIESEL", "BEV": "BEV", "HEV": "HEV", "PHEV": "PHEV"}
FUEL_KEYS = ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS"]

MONTH_NAMES = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
               "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

# portal titles use English or Indonesian month abbreviations
TITLE_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Mei": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Agu": 8, "Sep": 9, "Oct": 10, "Okt": 10,
    "Nov": 11, "Dec": 12, "Des": 12,
}

# sheet title (text before the `JAN-XXX YYYY marker) → canonical section key.
# Order matters: the LCGC title contains "4X2", so test it first.
SECTION_PATTERNS = [
    (re.compile(r"AFFORDABLE\s*ENERGY"), "LCGC"),
    (re.compile(r"PICK\s*UP\s*/?\s*TRUCK"), "PU_TRUCK"),
    (re.compile(r"DOUBLE\s*CABIN"), "DOUBLE_CABIN"),
    (re.compile(r"SEDAN"), "SEDAN"),
    (re.compile(r"4\s*X\s*4"), "4X4"),
    (re.compile(r"4\s*X\s*2"), "4X2"),
    (re.compile(r"^BUS\b"), "BUS"),
]
ALL_SECTIONS = {"SEDAN", "4X2", "4X4", "BUS", "PU_TRUCK", "DOUBLE_CABIN", "LCGC"}

# sheet titles end with a back-ticked date marker pasted from Excel: `JAN-JUN 2026
TITLE_RE = re.compile(
    r"^(?:\d\s*\.\s*)?([A-Z0-9 /X&,()]+?)\s+`\s*JAN\s*-\s*([A-Z]{3})\s+(\d{4})\s*$"
)
SUMMARY_RE = re.compile(
    r"^(PASSENGER CAR|COMMERCIAL VEHICLE|DOMESTIC)\s+(?:VEHICLE\s+)?SALES\s+TOTAL\b"
)

# ---------------------------------------------------------------- PDF parsing


def cluster_rows(words, tol=0.8):
    """Group words into visual rows by their top coordinate."""
    rows = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if rows and abs(w["top"] - rows[-1]["top"]) < tol:
            rows[-1]["words"].append(w)
        else:
            rows.append({"top": w["top"], "words": [w]})
    for r in rows:
        r["words"].sort(key=lambda w: w["x0"])
        r["text"] = " ".join(w["text"] for w in r["words"])
    return rows


def canon_section(title_body):
    t = title_body.upper()
    for pat, key in SECTION_PATTERNS:
        if pat.search(t):
            return key
    return None


def parse_cell(tokens):
    """Concatenate the tokens of one column band into an int; '-'/empty = 0."""
    joined = "".join(tokens).replace(".", "").replace(",", "").strip()
    if joined in ("", "-"):
        return 0
    if not re.fullmatch(r"\d+", joined):
        return None
    return int(joined)


def find_month_bands(rows):
    """Locate the JAN..DEC header row; return 12 (lo, hi) x-bands + header y."""
    for r in rows:
        centers = {}
        for w in r["words"]:
            if w["text"] in MONTH_NAMES and w["text"] not in centers:
                centers[w["text"]] = (w["x0"] + w["x1"]) / 2
        if len(centers) == 12:
            cx = [centers[m] for m in MONTH_NAMES]
            bands = []
            for i in range(12):
                lo = (cx[i - 1] + cx[i]) / 2 if i > 0 else cx[0] - 10
                hi = (cx[i] + cx[i + 1]) / 2 if i < 11 else cx[11] + 7
                bands.append((lo, hi))
            return bands, r["top"]
    return None, None


def find_fuel_x(rows):
    for r in rows:
        for w in r["words"]:
            if w["text"] == "FUEL":
                return (w["x0"] + w["x1"]) / 2
    return None


def month_values(row_words, bands):
    """Return 12 ints (None where a band's tokens are not numeric)."""
    per_band = [[] for _ in bands]
    for w in row_words:
        cx = (w["x0"] + w["x1"]) / 2
        for i, (lo, hi) in enumerate(bands):
            if lo <= cx < hi:
                per_band[i].append(w["text"])
                break
    return [parse_cell(toks) for toks in per_band]


class ParsedPdf:
    def __init__(self):
        # sections[key][month 1-12][fuel column] = units
        self.sections = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        self.printed = {}        # section key -> printed monthly totals
        self.summary = {}        # PASSENGER CAR / COMMERCIAL VEHICLE / DOMESTIC
        self.pu_segments = []    # (label_text, {month: {fuel: units}}) for PU_TRUCK
        self.coverage = None     # (last covered month, year)
        self.unknown_fuels = defaultdict(int)
        self.warnings = []


def process_region(rows, key, parsed):
    """One pasted sheet (or its continuation on the next page)."""
    bands, hdr_top = find_month_bands(rows)
    fuel_cx = find_fuel_x(rows)
    if bands is None or fuel_cx is None:
        parsed.warnings.append(f"{key}: month header or FUEL column not found")
        return

    fuel_rows, orphans, cumulative_tops = [], [], []
    for r in rows:
        if r["top"] <= hdr_top + 3.5:      # title + 3-line column header block
            continue
        vals = month_values(r["words"], bands)

        m = SUMMARY_RE.match(r["text"])
        if m:
            if any(vals):
                parsed.summary[m.group(1)] = [v or 0 for v in vals]
            continue

        # tokens left of the month columns decide the row type; TOTAL rows
        # must be classified before fuel detection because the "TOTAL" label
        # of some sheets ends exactly inside the fuel column band
        left_text = " ".join(w["text"] for w in r["words"] if w["x1"] < bands[0][0])
        if re.search(r"\bCUMULATIVE\b", left_text):
            cumulative_tops.append(r["top"])
            continue
        if re.search(r"\bTOTAL\b", left_text):
            if "SALES" in left_text:
                parsed.printed[key] = [v or 0 for v in vals]
            continue                     # subsection totals: no data, no orphan

        fuel = None
        for w in r["words"]:
            cx = (w["x0"] + w["x1"]) / 2
            if abs(cx - fuel_cx) < 4 and re.fullmatch(r"[A-Z]{1,5}", w["text"]):
                fuel = FUEL_COLUMN.get(w["text"])
                if fuel is None:
                    parsed.unknown_fuels[w["text"]] += 1
                    fuel = "OTHERS"
                break
            if abs(cx - fuel_cx) < 2.5 and w["text"] == "-":
                fuel = "OTHERS"
                break

        if fuel:
            if any(v is None for v in vals):
                parsed.warnings.append(f"{key}: unparseable cell in {r['text'][:70]!r}")
            fuel_rows.append({"top": r["top"], "fuel": fuel,
                              "vals": [v or 0 for v in vals]})
        elif any(vals) and not any(v is None for v in vals):
            orphans.append({"top": r["top"], "vals": vals, "text": r["text"]})

    # wrapped rows: value fragments sit on their own visual row slightly
    # above/below the fuel cell — re-attach to the nearest fuel row
    for o in orphans:
        best = min(fuel_rows, key=lambda fr: abs(fr["top"] - o["top"]), default=None)
        if best is not None and abs(best["top"] - o["top"]) <= 1.8:
            best["vals"] = [a + b for a, b in zip(best["vals"], o["vals"])]
        else:
            parsed.warnings.append(f"{key}: dropped orphan row {o['text'][:70]!r}")

    for fr in fuel_rows:
        for mi, v in enumerate(fr["vals"], 1):
            if v:
                parsed.sections[key][mi][fr["fuel"]] += v

    if key == "PU_TRUCK":
        segment_pu_truck(rows, fuel_rows, cumulative_tops, parsed)


def segment_pu_truck(rows, fuel_rows, cumulative_tops, parsed):
    """Split the PICK UP/TRUCK sheet into GVW subsections.

    Subsections end with a CUMULATIVE row; the label ("PICK UP GVW < 5 Ton",
    "TRUCK GVW 5 - 10 Ton", ...) sits vertically centered in the leftmost
    category column (x0 < 190).
    """
    boundaries = sorted(cumulative_tops)
    for i, hi in enumerate(boundaries):
        lo = boundaries[i - 1] if i else 0
        seg_fuel = [fr for fr in fuel_rows if lo < fr["top"] <= hi]
        if not seg_fuel:
            continue
        label_words = [
            w["text"]
            for r in rows if lo < r["top"] <= hi
            for w in r["words"] if w["x0"] < 190
        ]
        label = " ".join(label_words)
        months = defaultdict(lambda: defaultdict(int))
        for fr in seg_fuel:
            for mi, v in enumerate(fr["vals"], 1):
                if v:
                    months[mi][fr["fuel"]] += v
        parsed.pu_segments.append((label, months))


def parse_pdf(pdf_bytes):
    parsed = ParsedPdf()
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            words = page.extract_words(x_tolerance=0.7, y_tolerance=0.4)
            rows = cluster_rows(words)
            regions = []
            for i, r in enumerate(rows):
                m = TITLE_RE.match(r["text"])
                if not m:
                    continue
                key = canon_section(m.group(1))
                if key is None:
                    parsed.warnings.append(f"unmatched sheet title: {r['text']!r}")
                    continue
                cov = (MONTH_NAMES.index(m.group(2)) + 1, int(m.group(3)))
                if parsed.coverage is None:
                    parsed.coverage = cov
                elif parsed.coverage != cov:
                    raise SystemExit(f"inconsistent sheet coverage: {cov} vs {parsed.coverage}")
                regions.append((i, key))
            for ri, (start, key) in enumerate(regions):
                end = regions[ri + 1][0] if ri + 1 < len(regions) else len(rows)
                process_region(rows[start:end], key, parsed)
    return parsed


# ---------------------------------------------------------------- validation


def month_total(fuels):
    return sum(fuels.values())


def validate(parsed):
    """Cross-check every layer against the printed totals; exit on mismatch."""
    last_month, year = parsed.coverage
    errors = []

    missing = ALL_SECTIONS - set(parsed.sections)
    if missing:
        errors.append(f"sections missing from PDF: {sorted(missing)}")
    for key in sorted(ALL_SECTIONS & set(parsed.sections)):
        printed = parsed.printed.get(key)
        if printed is None:
            errors.append(f"{key}: printed section-total row not found")
            continue
        for mi in range(1, last_month + 1):
            got = month_total(parsed.sections[key][mi])
            if got != printed[mi - 1]:
                errors.append(f"{key} {year}-{mi:02d}: parsed {got} != printed {printed[mi - 1]}")

    aggregates = {
        "PASSENGER CAR": ("SEDAN", "4X2", "4X4", "LCGC"),
        "COMMERCIAL VEHICLE": ("BUS", "PU_TRUCK", "DOUBLE_CABIN"),
    }
    for name, keys in aggregates.items():
        printed = parsed.summary.get(name)
        if printed is None:
            errors.append(f"summary row {name!r} not found")
            continue
        for mi in range(1, last_month + 1):
            got = sum(month_total(parsed.sections[k][mi]) for k in keys)
            if got != printed[mi - 1]:
                errors.append(f"{name} {year}-{mi:02d}: parsed {got} != printed {printed[mi - 1]}")

    if "DOMESTIC" in parsed.summary:
        for mi in range(1, last_month + 1):
            pc = parsed.summary.get("PASSENGER CAR", [0] * 12)[mi - 1]
            cv = parsed.summary.get("COMMERCIAL VEHICLE", [0] * 12)[mi - 1]
            dom = parsed.summary["DOMESTIC"][mi - 1]
            if pc + cv != dom:
                errors.append(f"DOMESTIC {year}-{mi:02d}: PC {pc} + CV {cv} != {dom}")
    else:
        errors.append("summary row 'DOMESTIC' not found")

    # Pickups/HDV segments must add up to the whole PU_TRUCK section
    pu = [seg for seg in parsed.pu_segments if re.search(r"PICK\s*UP", seg[0])]
    if not pu:
        errors.append("no PICK UP subsection found in PU_TRUCK sheet")
    for mi in range(1, last_month + 1):
        seg_sum = sum(month_total(m[mi]) for _, m in parsed.pu_segments)
        sec = month_total(parsed.sections["PU_TRUCK"][mi])
        if seg_sum != sec:
            errors.append(f"PU_TRUCK segments {year}-{mi:02d}: {seg_sum} != section {sec}")

    if errors:
        for e in errors:
            print(f"VALIDATION: {e}", file=sys.stderr)
        raise SystemExit(f"PDF validation failed with {len(errors)} error(s)")

    for w in parsed.warnings:
        print(f"warning: {w}")
    for tok, n in parsed.unknown_fuels.items():
        print(f"warning: unknown fuel type {tok!r} in {n} row(s) -> OTHERS")


# ---------------------------------------------------------------- aggregation


def build_series(parsed):
    """Map sections to the four output series; returns
    {csv_suffix: (variant, {month: {fuel: units}})}."""
    last_month, _ = parsed.coverage

    def merge(sources):
        out = defaultdict(lambda: defaultdict(int))
        for months in sources:
            for mi, fuels in months.items():
                if mi > last_month:
                    continue
                for f, v in fuels.items():
                    out[mi][f] += v
        return out

    pickups = [m for label, m in parsed.pu_segments if re.search(r"PICK\s*UP", label)]
    trucks = [m for label, m in parsed.pu_segments if not re.search(r"PICK\s*UP", label)]

    return {
        "": ("Whole", merge([parsed.sections[k] for k in ("SEDAN", "4X2", "4X4", "LCGC")])),
        "_Pickups": ("Pickups", merge(pickups + [parsed.sections["DOUBLE_CABIN"]])),
        "_HDV": ("HDV", merge(trucks)),
        "_Buses": ("Buses", merge([parsed.sections["BUS"]])),
    }


# ---------------------------------------------------------------- CSV upsert


def upsert_csv(csv_path, variant, months, year, source, note, force):
    """Rewrite the covered periods; returns list of (period, action) changes."""
    rows = []
    if csv_path.exists():
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames != CSV_COLUMNS:
                raise SystemExit(f"{csv_path}: unexpected columns {reader.fieldnames}")
            rows = list(reader)

    existing = {r["period"]: r for r in rows}
    changes = []
    for mi in sorted(months):
        period = f"{year}-{mi:02d}"
        fuels = months[mi]
        new = {
            "period": period, "time_interval": "monthly", "variant": variant,
            "source": "GAIKINDO", "notes": note,
        }
        for f in FUEL_KEYS:
            new[f] = str(fuels.get(f, 0))
        new["TOTAL"] = str(sum(fuels.get(f, 0) for f in FUEL_KEYS))
        old = existing.get(period)
        if old is None:
            rows.append(new)
            changes.append((period, "added"))
        elif any(_num(old[f]) != _num(new[f]) for f in FUEL_KEYS + ["TOTAL"]) \
                or old["source"] != new["source"]:
            rows[rows.index(old)] = new
            changes.append((period, "updated"))
        elif force:
            rows[rows.index(old)] = new
            changes.append((period, "rewritten"))

    if changes:
        rows.sort(key=lambda r: r["period"])
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    return changes


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------ portal access


def portal_login(sess):
    user = os.environ.get("INDONESIA_GAIKINDO_USER", "LeRaffl")
    pw = os.environ.get("INDONESIA_GAIKINDO_PW")
    if not pw:
        raise SystemExit("INDONESIA_GAIKINDO_PW is not set")
    r = sess.get(PORTAL, timeout=30)
    r.raise_for_status()
    m = re.search(r'name="csrf_token" value="([0-9a-f]+)"', r.text)
    if not m:
        raise SystemExit("login page: csrf_token not found (layout changed?)")
    r = sess.post(PORTAL + "index.php", timeout=30, data={
        "csrf_token": m.group(1), "do": "login",
        "username": user, "password": pw,
    })
    r.raise_for_status()
    check = sess.get(PORTAL + FILE_LIST_PAGES[0], timeout=30)
    if 'name="password"' in check.text and "csrf_token" in check.text:
        raise SystemExit("portal login failed (still seeing the login form)")
    print(f"logged in to {PORTAL} as {user}")


def discover_wholesales(sess):
    """Find the newest 'Wholesales Jan-XXX YYYY' file; returns (title, url)."""
    title_re = re.compile(r"Wholesales\s+Jan\s*[-–]\s*([A-Za-z]{3})\s+(\d{4})")
    candidates = []
    for page in FILE_LIST_PAGES:
        r = sess.get(PORTAL + page, params={"search": "wholesales"}, timeout=30)
        if r.status_code != 200:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for tr in soup.find_all("tr"):
            m = title_re.search(tr.get_text(" ", strip=True))
            if not m or m.group(1) not in TITLE_MONTHS:
                continue
            link = next((a["href"] for a in tr.find_all("a", href=True)
                         if "download" in a["href"].lower()), None)
            if link:
                title = f"Wholesales Jan-{m.group(1)} {m.group(2)}"
                url = requests.compat.urljoin(PORTAL, link)
                candidates.append(((int(m.group(2)), TITLE_MONTHS[m.group(1)]), title, url))
        if candidates:
            print(f"file list via {page}: {len(candidates)} wholesales candidate(s)")
            break
    if not candidates:
        raise SystemExit("no 'Wholesales Jan-XXX YYYY' file found on the portal "
                         f"(tried {', '.join(FILE_LIST_PAGES)})")
    candidates.sort()
    (year, month), title, url = candidates[-1]
    return title, url, year, month


def download_pdf(sess, url):
    r = sess.get(url, timeout=120)
    r.raise_for_status()
    if not r.content.startswith(b"%PDF"):
        raise SystemExit(f"download from {url} is not a PDF "
                         f"(content-type {r.headers.get('content-type')})")
    print(f"downloaded {len(r.content) / 1024:.0f} KB")
    return r.content


# ----------------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--pdf-path")
    ap.add_argument("--download-url")
    ap.add_argument("--csv-dir", default="data")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    csv_dir = Path(args.csv_dir)

    if args.pdf_path:
        pdf_bytes = Path(args.pdf_path).read_bytes()
    else:
        sess = requests.Session()
        sess.headers.update(HTTP_HEADERS)
        portal_login(sess)
        if args.download_url:
            url = args.download_url
        else:
            title, url, year, month = discover_wholesales(sess)
            print(f"newest portal file: {title}")
            latest = f"{year}-{month:02d}"
            indonesia = csv_dir / "Indonesia.csv"
            if not args.force and indonesia.exists():
                with open(indonesia, newline="") as f:
                    if any(r["period"] == latest and r["source"] == "GAIKINDO"
                           for r in csv.DictReader(f)):
                        print(f"{latest} already ingested; nothing to do")
                        return 0
        pdf_bytes = download_pdf(sess, url)

    parsed = parse_pdf(pdf_bytes)
    if parsed.coverage is None:
        raise SystemExit("no sheet titles found in PDF (format changed?)")
    last_month, year = parsed.coverage
    print(f"parsed PDF: months 1..{last_month} of {year}")
    validate(parsed)
    note = f"Wholesales Jan-{MONTH_NAMES[last_month - 1].title()} {year}"

    changed_any = False
    for suffix, (variant, months) in build_series(parsed).items():
        path = csv_dir / f"Indonesia{suffix}.csv"
        changes = upsert_csv(path, variant, months, year, "GAIKINDO", note, args.force)
        if changes:
            changed_any = True
            summary = ", ".join(f"{p} {a}" for p, a in changes)
            print(f"{path}: {summary}")
        else:
            print(f"{path}: unchanged")
    if not changed_any:
        print("all CSVs already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
