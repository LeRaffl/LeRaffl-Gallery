#!/usr/bin/env python3
"""
Fetch Poland new registration data from PZPM's public eRegistrations workbook
and upsert per-variant CSVs.

Usage
-----
    python scripts/fetch_poland.py [--variant {whole,vans,hdv,buses,all}] [--force]
    python scripts/fetch_poland.py --xlsx PATH [--period YYYY-MM] [--force]  # parse a local file
        (--period is optional: the reporting month is read from the workbook's
         "Ogółem" sheet header; --period is only a fallback if that is missing.)

Output files (one per PZPM vehicle category; all parsed from the "Ogółem" sheet)
--------------------------------------------------------------------------------
    data/Poland.csv         <- Whole  OSOBOWE                       (passenger cars, M1)
    data/Poland_Vans.csv    <- Vans   SAMOCHODY DOSTAWCZE           (LCV <=3.5t, N1)
    data/Poland_HDV.csv     <- HDV    SAMOCHODY CIĘŻAROWE POW. 3,5T (trucks >3.5t, N2/N3)
    data/Poland_Buses.csv   <- Buses  AUTOBUSY                      (buses, M2/M3)

Source
------
PZPM (Polski Związek Przemysłu Motoryzacyjowego) publishes a monthly
eRegistrations workbook under https://www1.pzpm.org.pl/en/Electromobility/eRegistrations
around the 7th of the following month, based on the Central Register of Vehicles
(CEP). The workbook is "PZPM_eRejestracje - tabele MM.YYYY.xlsx", whose
/content/download/<id>/<id>/file/ IDs change every month, so there is no stable
URL and no API — it must be discovered by scraping.

Discovery is two-level and defensive, because PZPM curates this section by hand
and it is messy: the landing page lists only the newest month(s) and often only
as an "infografika ...pdf" (no table); the machine-readable .xlsx tables live on
per-month sub-pages (…/eRegistrations/JULY-2026) linked from the left nav. Worse,
the page titles / sub-page URLs / even .xlsx filenames are frequently WRONG — the
newest month is sometimes published under the previous month's name, and
duplicate pages exist (JULY twice, APRIL three times). So the period is NEVER
taken from the URL or filename; it is read from the workbook's own "Ogółem" sheet
header ("Czerwiec 2026" -> 2026-06). collect_xlsx_candidates() reads the landing
page plus the newest sub-pages and returns every .xlsx table; each is downloaded,
its true month read from the sheet, and upserted under that month. When no .xlsx
is available yet (PDF-only month), the run is a clean no-op — the ACEA fallback
(scripts/fetch_acea.py) fills that month instead, without overwriting PZPM rows.

Only the workbook's "Ogółem" (Overall) sheet is reliably updated each month — the
other sheets (brand/model rankings, "Paliwa_...") are stale 2023 template tabs
and must NOT be parsed. "Ogółem" gives, per vehicle category, the current month's
count by drive type plus a year-to-date column (the YTD column is ignored here;
only the current month is taken).

The workbook holds ONLY the current month (no per-month history). The Whole
(passenger) history back to 2010 already lives in data/Poland.csv from the ACEA
pipeline; PZPM is the upstream CEP source behind those ACEA numbers (verified:
PZPM OSOBOWE Apr-2026 = ACEA Poland Apr-2026, to the unit). Going forward PZPM
owns the Whole row (source := "PZPM"); the commercial variants start thin
(current month onward) and accumulate over time, mirroring Portugal.

Drive-type -> canonical column (per "Ogółem" row label, ASCII-folded match):
    Benzyna           -> PETROL
    Diesel            -> DIESEL
    Elektryczne       -> BEV
    Hybrydowe plug-in -> PHEV
    Hybrydowe         -> HEV           (exact; full/mild hybrids)
    OTHERS            -> TOTAL - (BEV+PHEV+HEV+PETROL+DIESEL)
                         (residual captures LPG, Wodorowe/FCEV, CNG/LNG, and — for
                          the commercial variants, where PZPM reports a single
                          combined "Hybrydowe / hybrydowe plug-in" figure that
                          can't be split — the hybrids too)

Columns a category does not report separately are written empty ("" = not
reported), not 0 — e.g. Vans/HDV have no PHEV/HEV split, HDV has no PETROL.

Cross-check: ACEA leaves Poland to this workflow (Poland is no longer in
scripts/fetch_acea.py's country list). See docs/architecture/22-source-poland.md.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import urllib.parse
from io import BytesIO
from pathlib import Path

import openpyxl
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# The Polish-language section is the source of truth: PZPM curates it correctly
# (each month's sub-page carries its OWN month name), whereas the English mirror
# is frequently mislabelled (newest month under the previous month's name). The
# workbook's in-sheet month is still the final authority regardless of language.
PAGE_URL = "https://www1.pzpm.org.pl/pl/Elektromobilnosc/eRejestracje"
HOST = "https://www1.pzpm.org.pl"
SOURCE = "PZPM"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"

# Variant -> ("Ogółem" category header, output CSV). The header is matched after
# ASCII-folding + upper-casing, so diacritics (Ę, Ż, Ó, ...) don't matter.
VARIANT_CONFIG = {
    "Whole": {"header": "OSOBOWE",                       "csv": "data/Poland.csv"},
    "Vans":  {"header": "SAMOCHODY DOSTAWCZE",           "csv": "data/Poland_Vans.csv"},
    "HDV":   {"header": "SAMOCHODY CIEZAROWE POW. 3,5T", "csv": "data/Poland_HDV.csv"},
    "Buses": {"header": "AUTOBUSY",                      "csv": "data/Poland_Buses.csv"},
}
# Category headers in "Ogółem" we recognise but intentionally skip (so their
# drive-type sub-rows are not misattributed to the preceding variant).
SKIP_HEADERS = {"SAMOCHODY CIEZAROWE OD 12T", "MOTOCYKLE", "MOTOROWERY"}

# Drive-type row label (ASCII-folded, lower-cased, exact) -> canonical column.
FUEL_MAP = {
    "benzyna": "PETROL",
    "diesel": "DIESEL",
    "elektryczne": "BEV",
    "hybrydowe plug-in": "PHEV",
    "hybrydowe": "HEV",
}

# Polish month name (ASCII-folded, lower-cased) -> month number. Used to read the
# workbook's OWN reporting month out of the "Ogółem" sheet header ("Czerwiec 2026"),
# which is the ONLY trustworthy period signal: PZPM's page titles, sub-page URLs and
# even .xlsx filenames are frequently mislabelled (the newest month is sometimes
# published under the previous month's name, and duplicate pages exist).
POLISH_MONTHS = {
    "styczen": 1, "luty": 2, "marzec": 3, "kwiecien": 4, "maj": 5, "czerwiec": 6,
    "lipiec": 7, "sierpien": 8, "wrzesien": 9, "pazdziernik": 10, "listopad": 11,
    "grudzien": 12,
}
# A single-month header, e.g. "Czerwiec 2026" — NOT the YTD "Styczeń-Czerwiec 2026"
# range (which carries a dash and must not match).
_MONTH_HEADER_RE = re.compile(
    r"^(%s)\s+(20\d\d)$" % "|".join(POLISH_MONTHS), re.IGNORECASE)

CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL", "notes",
]

_FOLD = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


def fold(s: str) -> str:
    """ASCII-fold Polish diacritics and collapse whitespace."""
    return re.sub(r"\s+", " ", (s or "").translate(_FOLD)).strip()


# Workbook filenames carry one of these brand tags.
_TAG_RE = re.compile(r"erejestracje|tabele", re.IGNORECASE)
# We need the machine-readable .xlsx table, NOT the "infografika ...pdf" the
# electromobility page also publishes (parsing a PDF as xlsx crashes openpyxl).
_XLSX_RE = re.compile(r"\.xlsx(\?|$|[^a-z])", re.IGNORECASE)
# "MM.YYYY" / "MM_YYYY" / "MM-YYYY" filename hint (only a hint — see POLISH_MONTHS).
_FNAME_PERIOD_RE = re.compile(r"(\d{2})[._-](\d{4})")
# A month sub-page slug under the eRegistrations/eRejestracje section, e.g.
# ".../eRejestracje/SIERPIEN-2026" (Polish) or ".../eRegistrations/JULY-2026"
# (English). The trailing "[A-Z0-9-]*" tolerates the duplicate-page numeric suffix
# ("LIPIEC-20262"). Both languages are matched so discovery is language-agnostic.
_SUBPAGE_RE = re.compile(
    r"/(?:Elektromobilnosc/eRejestracje|Electromobility/eRegistrations)/"
    r"(?:"
    # Polish month slugs (ASCII-folded, as they appear in URLs):
    r"STYCZEN|LUTY|MARZEC|KWIECIEN|MAJ|CZERWIEC|LIPIEC|SIERPIEN|WRZESIEN|"
    r"PAZDZIERNIK|LISTOPAD|GRUDZIEN|"
    # English month names (the mirror):
    r"JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|"
    r"NOVEMBER|DECEMBER"
    r")[A-Z0-9-]*", re.IGNORECASE)

# How many of the newest month sub-pages to open when hunting for .xlsx tables.
_MAX_SUBPAGES = 6


def _hrefs(html: str) -> list[str]:
    """All href values on a page, in document order, any quoting style."""
    return re.findall(r'href=["\']([^"\']+)["\']', html, re.IGNORECASE)


def _xlsx_links(html: str) -> list[tuple[str | None, str]]:
    """eRejestracje .xlsx links on a page -> [(filename_hint 'YYYY-MM'|None, abs url)]."""
    out: list[tuple[str | None, str]] = []
    for raw in _hrefs(html):
        href = raw.replace("&amp;", "&")
        name = urllib.parse.unquote(href)
        if not (_XLSX_RE.search(name) and _TAG_RE.search(name)):
            continue
        pm = _FNAME_PERIOD_RE.search(name)
        hint = None
        if pm and 1 <= int(pm.group(1)) <= 12:
            hint = f"{int(pm.group(2)):04d}-{int(pm.group(1)):02d}"
        url = urllib.parse.urljoin(HOST, urllib.parse.quote(href, safe="/:?=&%"))
        out.append((hint, url))
    return out


def collect_xlsx_candidates(session: requests.Session) -> list[tuple[str | None, str]]:
    """Find eRejestracje .xlsx tables, newest first.

    The landing page only lists the latest month(s) — and often only as PDF — while
    the machine-readable .xlsx tables live on per-month sub-pages linked from the
    left nav. So: read the landing page's own .xlsx links, then open the newest
    handful of month sub-pages and read theirs. Returns de-duplicated
    (filename_hint, url) pairs; the hint is only for ordering/early-exit — the
    authoritative period is read from each workbook's "Ogółem" sheet after download.
    """
    r = session.get(PAGE_URL, timeout=60)
    r.raise_for_status()
    landing_html = r.text

    candidates: list[tuple[str | None, str]] = list(_xlsx_links(landing_html))

    # Newest month sub-pages, in nav (document) order, de-duplicated by URL.
    subpages: list[str] = []
    seen_sub: set[str] = set()
    for href in _hrefs(landing_html):
        # _SUBPAGE_RE requires a month name after the section, so the bare landing
        # page (no month segment) never matches — only real month sub-pages do.
        if not _SUBPAGE_RE.search(href):
            continue
        url = urllib.parse.urljoin(HOST, href.replace("&amp;", "&"))
        if url not in seen_sub:
            seen_sub.add(url)
            subpages.append(url)
    for sub_url in subpages[:_MAX_SUBPAGES]:
        try:
            sr = session.get(sub_url, headers={"Referer": PAGE_URL}, timeout=60)
            sr.raise_for_status()
        except requests.RequestException as e:
            print(f"  WARNING: sub-page fetch failed ({sub_url}): {e}", file=sys.stderr)
            continue
        candidates.extend(_xlsx_links(sr.text))

    # De-duplicate by URL, keep first (newest) occurrence order.
    seen: set[str] = set()
    unique: list[tuple[str | None, str]] = []
    for hint, url in candidates:
        if url not in seen:
            seen.add(url)
            unique.append((hint, url))
    # Order by filename-hint period (newest first); hint-less links go last.
    unique.sort(key=lambda c: c[0] or "0000-00", reverse=True)

    if not unique:
        _print_no_xlsx_diagnostics(landing_html, subpages)
    return unique


def _print_no_xlsx_diagnostics(landing_html: str, subpages: list[str]) -> None:
    """Explain, on stderr, why no .xlsx was found (page can't be inspected here)."""
    all_hrefs = _hrefs(landing_html)
    looks_gated = bool(re.search(r"just a moment|cf-browser|challenge|enable javascript",
                                 landing_html, re.IGNORECASE))
    tagged = [h for h in all_hrefs if _TAG_RE.search(urllib.parse.unquote(h))]
    print("DIAGNOSTIC: no eRejestracje .xlsx table found on the landing page or the "
          f"{len(subpages)} newest sub-pages.", file=sys.stderr)
    print(f"  landing bytes={len(landing_html)}  total hrefs={len(all_hrefs)}  "
          f"eRejestracje/tabele hrefs={len(tagged)}  subpages_found={len(subpages)}  "
          f"looks_js_gated={looks_gated}", file=sys.stderr)
    for h in tagged[:15]:
        print(f"    tagged href: {h}", file=sys.stderr)
    for s in subpages[:10]:
        print(f"    subpage: {s}", file=sys.stderr)


def download_xlsx(session: requests.Session, url: str) -> bytes:
    r = session.get(url, headers={"Referer": PAGE_URL}, timeout=60)
    r.raise_for_status()
    return r.content


def parse_ogolem(xlsx_bytes: bytes) -> tuple[str | None, dict]:
    """Parse the 'Ogółem' sheet.

    Returns ``(period, result)`` where ``period`` is the workbook's own reporting
    month ('YYYY-MM') read from the sheet header (or ``None`` if not found), and
    ``result`` is ``{variant: {canonical col: value, 'TOTAL': t}}``.
    """
    wb = openpyxl.load_workbook(BytesIO(xlsx_bytes), data_only=True)
    if "Ogółem" not in wb.sheetnames:
        sys.exit(f"'Ogółem' sheet not found; sheets: {wb.sheetnames}")
    ws = wb["Ogółem"]

    header_to_variant = {fold(c["header"]).upper(): v for v, c in VARIANT_CONFIG.items()}
    result: dict[str, dict] = {}
    current = None  # variant currently being read, or None to skip
    period: str | None = None

    for row in ws.iter_rows(values_only=True):
        # The reporting month lives in an early header cell ("Czerwiec 2026").
        if period is None:
            for cell in row:
                if isinstance(cell, str):
                    m = _MONTH_HEADER_RE.match(fold(cell))
                    if m:
                        period = f"{int(m.group(2)):04d}-{POLISH_MONTHS[m.group(1).lower()]:02d}"
                        break

        label_raw = row[1] if len(row) > 1 else None       # col B
        if not isinstance(label_raw, str):
            continue
        label = fold(label_raw)
        upper = label.upper()

        if upper in header_to_variant:                     # category header
            current = header_to_variant[upper]
            total = row[2] if len(row) > 2 else None       # col C = current month
            result[current] = {"TOTAL": float(total) if isinstance(total, (int, float)) else 0.0}
            continue
        if upper in SKIP_HEADERS:                          # out-of-scope category
            current = None
            continue

        col = FUEL_MAP.get(label.lower())
        if current and col:
            val = row[2] if len(row) > 2 else None         # col C = current month
            if isinstance(val, (int, float)):
                result[current][col] = result[current].get(col, 0.0) + float(val)

    return period, result


def to_row(parsed_variant: dict, period: str, variant: str) -> dict | None:
    """Build one canonical CSV row from a parsed category dict."""
    total = parsed_variant.get("TOTAL", 0.0)
    if not total:
        return None
    core_cols = ["BEV", "PHEV", "HEV", "PETROL", "DIESEL"]
    core_sum = sum(parsed_variant.get(c, 0.0) for c in core_cols)
    row = {
        "period": period, "time_interval": "monthly",
        "variant": variant, "source": SOURCE,
        # "" = the category does not report this drive type separately.
        **{c: (parsed_variant[c] if c in parsed_variant else "") for c in core_cols},
        "OTHERS": max(0.0, total - core_sum),
        "TOTAL": total,
        "notes": "",
    }
    return row


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
            for c in ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS"]:
                ov = float(old.get(c) or 0)
                nv = float(new_row[c] or 0)
                if ov > 100 and abs(nv - ov) / ov > 0.5:
                    print(f"  WARNING {key[1]} {key[0]} {c}: existing={ov:.0f}, new={nv:.0f} "
                          f"— diff >50%, please verify")
            if not new_row.get("notes"):
                new_row["notes"] = old.get("notes", "")
            existing[key] = {**old, **new_row}
            updated += 1

    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    # CRLF to match the ACEA-family CSVs (data/Poland.csv, Belgium.csv, ...) so an
    # in-place update is a one-line diff rather than a whole-file re-write.
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\r\n")
        w.writeheader()
        for key in sorted(existing.keys(), key=lambda k: (k[1], k[0])):
            w.writerow(existing[key])
    return added, updated


def csv_has_period(csv_path: str, period: str, variant: str) -> bool:
    if not os.path.exists(csv_path):
        return False
    with open(csv_path, newline="", encoding="utf-8") as f:
        return any(r["period"] == period and r["variant"] == variant for r in csv.DictReader(f))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variant", choices=["whole", "vans", "hdv", "buses", "all"],
                    default="all", help="Which slice to fetch (default: all).")
    ap.add_argument("--xlsx", help="Parse a local workbook instead of scraping the page.")
    ap.add_argument("--period", help="Period 'YYYY-MM' (required with --xlsx).")
    ap.add_argument("--force", action="store_true",
                    help="Skip the 'period already present' early-exit.")
    args = ap.parse_args()

    aliases = {"whole": "Whole", "vans": "Vans", "hdv": "HDV", "buses": "Buses"}
    targets = list(aliases.values()) if args.variant == "all" else [aliases[args.variant]]

    if args.xlsx:
        # Local workbook: trust the sheet's own month, fall back to --period.
        xlsx_bytes = Path(args.xlsx).read_bytes()
        sheet_period, parsed = parse_ogolem(xlsx_bytes)
        period = sheet_period or args.period
        if not period:
            ap.error("--period YYYY-MM is required (workbook carries no month header)")
        if sheet_period and args.period and sheet_period != args.period:
            print(f"WARNING: workbook month {sheet_period} != --period {args.period}; "
                  f"using workbook month {sheet_period}.")
        _apply(period, parsed, targets)
        return

    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    _retry = Retry(total=4, read=4, connect=4, backoff_factor=2,
                   status_forcelist=[500, 502, 503, 504], raise_on_status=False)
    _adapter = HTTPAdapter(max_retries=_retry)
    session.mount("https://", _adapter)
    session.mount("http://", _adapter)

    candidates = collect_xlsx_candidates(session)
    if not candidates:
        # No machine-readable table published yet (PDF-only month, or page churn).
        # Not fatal — leave the CSVs untouched so the workflow stays green; the
        # next run (or the ACEA fallback) fills the month once a table appears.
        print("No eRejestracje .xlsx table available right now; nothing to do.")
        return
    print(f"Found {len(candidates)} candidate .xlsx table(s): "
          + ", ".join(f"{h or '?'}" for h, _ in candidates))

    done_periods: set[str] = set()
    downloaded = 0
    for hint, url in candidates:
        # Early-exit hint (before downloading): if the filename month is already
        # complete in every target CSV and we're not forcing, skip the download.
        if not args.force and hint and all(
                csv_has_period(VARIANT_CONFIG[v]["csv"], hint, v) for v in targets):
            print(f"[hint {hint}] already present in all targets; skipping {url}")
            continue
        try:
            xlsx_bytes = download_xlsx(session, url)
        except requests.RequestException as e:
            print(f"WARNING: download failed ({url}): {e}", file=sys.stderr)
            continue
        downloaded += 1
        try:
            sheet_period, parsed = parse_ogolem(xlsx_bytes)
        except Exception as e:  # not a real xlsx (stray PDF), corrupt file, ...
            print(f"WARNING: could not parse {url}: {e}", file=sys.stderr)
            continue
        period = sheet_period or hint
        if not period:
            print(f"WARNING: no month header in {url} (hint={hint}); skipping.",
                  file=sys.stderr)
            continue
        if sheet_period and hint and sheet_period != hint:
            print(f"NOTE: filename says {hint} but workbook month is {sheet_period} "
                  f"— trusting the workbook.")
        if period in done_periods:
            continue
        done_periods.add(period)
        _apply(period, parsed, targets, force=args.force)
        # Stop once we've pulled a couple of real files (bounds network use).
        if downloaded >= 3 and len(done_periods) >= 2:
            break


def _apply(period: str, parsed: dict, targets: list[str], force: bool = False) -> None:
    """Upsert one workbook's variants for ``period`` into their CSVs."""
    for variant in targets:
        cfg = VARIANT_CONFIG[variant]
        if not force and csv_has_period(cfg["csv"], period, variant):
            print(f"[{variant}] CSV already has {period}; skipping.")
            continue
        row = to_row(parsed.get(variant, {}), period, variant)
        if row is None:
            print(f"[{variant}] no data for {period} in workbook; skipping.")
            continue
        added, updated = upsert_csv(cfg["csv"], {(period, variant): row})
        print(f"[{variant}] {added} added, {updated} updated ({period}) -> {cfg['csv']}")


if __name__ == "__main__":
    main()
