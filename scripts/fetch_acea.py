#!/usr/bin/env python3
"""
Fetch ACEA monthly car-registrations PDF and upsert per-country rows into
the data/<Country>.csv files we maintain.

Usage
-----
    python scripts/fetch_acea.py [--year YEAR] [--month MONTH] \
        [--pdf-url URL_OR_PATH] [--data-dir data] [--force] \
        [--github-output PATH]

* --year / --month   Target month (default: previous calendar month).
* --pdf-url          Direct URL/path to a Press_release_car_registrations PDF.
                     If omitted, the canonical ACEA URL for the target month is
                     constructed and tried.
* --data-dir         Folder containing data/<Country>.csv (default: ./data).
* --force            Skip the "already up-to-date" short-circuit; the per-row
                     write rules still apply.
* --github-output    Optional path; when set, the list of countries whose CSV
                     was actually modified is written there as
                     `changed_countries=<json-array>` (used by fetch-acea.yml).

Invoked by .github/workflows/fetch-acea.yml on a daily cron from the 16th of
each month onward (ACEA typically publishes the previous month's PDF around
the 22nd–25th). The script self-throttles by reading the latest period from
every always-list CSV; the cheapest path is "all CSVs already at target, no
HTTP". When something changes, the workflow commits the modified CSVs in one
commit and then a sequential matrix job renders each affected country.

Data source
-----------
ACEA (European Automobile Manufacturers' Association) publishes monthly press
releases at https://www.acea.auto/files/Press_release_car_registrations_<Month>_<Year>.pdf
(e.g. Press_release_car_registrations_March_2026.pdf). The link is stable;
only Month and Year change.

The PDF has 6 pages. Page 3 carries the MONTHLY by-market-and-power-source
table; page 4 the YEAR-TO-DATE table. We always parse the MONTHLY table
because:
  * the monthly table includes one columns block for the target month (e.g.
    March 2026) **and** one for the prior-year same month (March 2025), giving
    us the prior-year correction the maintainer wants — no YTD parsing needed.
  * YTD totals are derived; the source month-by-month columns are authoritative.

Column order in the monthly table — stable across releases:
    BATTERY ELECTRIC | PLUG-IN HYBRID | HYBRID ELECTRIC¹ | OTHERS² | PETROL | DIESEL | TOTAL
Note this differs from our CSV order (BEV, PHEV, HEV, PETROL, DIESEL, OTHERS,
TOTAL — OTHERS sits between DIESEL and TOTAL). The parser reads pairs in the
PDF order and writes by fuel name, so CSV column order is independent.

Parsing approach
----------------
Through March 2026, ACEA's PDF generator emitted explicit table cell rules
and pdfplumber.extract_tables() returned a clean country-by-fuel grid. From
April 2026 ACEA switched to Microsoft Word's PDF export, which lays the
same data down without those cell rules — extract_tables() returns nothing
on the country pages. extract_text() however still yields one tidy line
per country, so we parse that text directly: split on whitespace, drop
percentage tokens (anything with a ".") and stand-alone signs, then read
off 14 integers as 7 (current_year, prior_year) pairs.

Cell formatting quirks
----------------------
* Both year columns of a fuel section can read "0 0" with the YoY % omitted
  (Bulgaria OTHERS, Estonia OTHERS, Cyprus OTHERS, …). The 14-int contract
  still holds — the next fuel's values just follow without an intervening %.
* Some countries report a dash glyph (U+A7F7 "ꟷ", or a regular em/en-dash)
  instead of "0" — Latvia HEV, Romania PHEV historically. Treated as 0 by
  the parser, per the maintainer's instruction.
* pdfplumber's text extraction can occasionally split a count across
  whitespace (e.g. "184" → "18 4"). That would land 15 integers on the line
  instead of 14; the parser returns None for that country and main() logs
  it as a missing country so the maintainer notices.

Per-country write rules
-----------------------
The maintainer enumerated two lists:

* "Always" list — always overwrite the current-month row, source := "ACEA":
    Belgium, Bulgaria, Croatia, Cyprus, Czechia, Estonia, France, Greece,
    Hungary, Iceland, Latvia, Lithuania, Malta, Romania, Slovakia, Slovenia

* "Conditional" list — only touch a row if the existing source is exactly
  "ACEA" (case-insensitive, after stripping whitespace), or no row exists:
    Luxembourg, Norway, Spain, Switzerland

Denmark, Finland, Netherlands, Poland and Sweden appear on ACEA's PDF but are
intentionally out of scope here — the maintainer pulls those from national
databases that also carry variants ACEA doesn't expose (Private / Industry /
Used / HDV / Vans / Buses). Poland comes from PZPM's CEP-based eRegistrations
workbook (scripts/fetch_poland.py), which is the upstream source behind ACEA's
Poland numbers and additionally carries Vans/HDV/Buses. Sweden additionally has
a non-standard CSV schema (FLEXFUEL column).

For the prior-year correction (e.g. the March 2025 column of a March 2026
file) the rule from the maintainer is identical to the conditional rule
**for both lists**: overwrite only if the existing row's source is exactly
"ACEA"; if the source field is empty (some old rows have no source) or
non-ACEA, leave the row alone — the maintainer wants those flagged for
manual data-quality review rather than blindly overwritten.

Other countries on the PDF (Austria, Germany, Ireland, Italy, Portugal,
United Kingdom, EU/EFTA aggregates) are also intentionally skipped — those
are handled by separate per-country workflows that aren't built yet.
"""
import argparse
import csv
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

import pdfplumber
import requests

# --- Constants ------------------------------------------------------------

ALWAYS_COUNTRIES = [
    "Belgium", "Bulgaria", "Croatia", "Cyprus", "Czechia", "Estonia",
    "France", "Greece", "Hungary", "Iceland", "Latvia", "Lithuania",
    "Malta", "Romania", "Slovakia", "Slovenia",
]
CONDITIONAL_COUNTRIES = [
    "Luxembourg", "Norway", "Spain", "Switzerland",
]
# Intentionally NOT in scope: Denmark, Finland, Netherlands, Poland, Sweden.
# The maintainer pulls those from national databases that also carry variants
# ACEA doesn't expose (Private / Industry / Used / HDV / Vans / Buses), so the
# national pipeline is the preferred source and ACEA would only muddy the water.
# Poland: PZPM eRegistrations (scripts/fetch_poland.py) — the CEP-based upstream
# behind ACEA's Poland numbers. Sweden additionally has a non-standard schema
# (FLEXFUEL column) that ACEA can't fill. Each is handled by its own workflow.
ALL_COUNTRIES = ALWAYS_COUNTRIES + CONDITIONAL_COUNTRIES

ENGLISH_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

ACEA_URL_TEMPLATE = (
    "https://www.acea.auto/files/"
    "Press_release_car_registrations_{month_name}_{year}.pdf"
)

ACEA_HOMEPAGE = "https://www.acea.auto/"

# ACEA's edge (Cloudflare-style WAF) 403s requests that don't look like a
# real browser. A bare UA/Accept/Referer set used to work but stopped working
# from GitHub Actions runners — they now need the modern Chrome client-hints
# and Sec-Fetch-* headers, plus a session that carries cookies set by a prior
# GET to the homepage. Without the warmup, the PDF request 403s with no
# x-deny-reason header (vs. host_not_allowed for an IP allowlist hit).
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "application/pdf;q=0.95,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": ACEA_HOMEPAGE,
    "Sec-Ch-Ua": (
        '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"'
    ),
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

# Standard CSV column order (matches the existing Belgium/France/… files).
STANDARD_CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS",
    "TOTAL", "notes",
]

# Source string for rows we write/overwrite.
ACEA_SOURCE = "ACEA"

# Dash glyphs the PDF uses in place of "0".
DASH_GLYPHS = ("ꟷ", "–", "—", "−")

# Column order in the MONTHLY country-by-fuel grid (PDF layout, left to
# right). We read 7 (current-year, prior-year) integer pairs per data line
# in this order — the keys here are our internal CSV column names.
PDF_FUEL_ORDER = ("BEV", "PHEV", "HEV", "OTHERS", "PETROL", "DIESEL", "TOTAL")

# Header tokens (normalised — whitespace stripped, footnotes "1"/"2" trimmed,
# upper-cased) and the CSV fuel key they correspond to. Only used by the
# legacy extract_tables() fallback parser.
HEADER_TO_FUEL = {
    "BATTERYELECTRIC": "BEV",
    "PLUG-INHYBRID": "PHEV",
    "HYBRIDELECTRIC": "HEV",
    "OTHERS": "OTHERS",
    "PETROL": "PETROL",
    "DIESEL": "DIESEL",
    "TOTAL": "TOTAL",
}

# --- Date helpers ---------------------------------------------------------

def previous_month(today: date) -> tuple[int, int]:
    if today.month == 1:
        return today.year - 1, 12
    return today.year, today.month - 1


def prev_year_period(period: str) -> str:
    y, m = period.split("-")
    return f"{int(y) - 1}-{m}"


# --- CSV helpers ---------------------------------------------------------

def detect_line_ending(path: Path) -> str:
    """Returns '\\r\\n' if the file is CRLF (matches Belgium et al.), else '\\n'."""
    if not path.exists():
        return "\r\n"  # match the convention used by the existing ACEA CSVs
    with open(path, "rb") as f:
        head = f.read(4096)
    return "\r\n" if b"\r\n" in head else "\n"


def load_csv(path: Path) -> tuple[list[str], list[dict]]:
    """Returns (fieldnames, rows). New file → default schema + empty rows."""
    if not path.exists():
        return list(STANDARD_CSV_COLUMNS), []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fields = list(reader.fieldnames or STANDARD_CSV_COLUMNS)
    return fields, rows


def write_csv(path: Path, fields: list[str], rows: list[dict],
              original_order: list[str] | None = None) -> None:
    """Write `rows` keyed by `period`. If `original_order` is given (list of
    periods from the file as it was on disk), rows are emitted in that order
    and any *new* periods are sorted and appended at the end. This keeps the
    diff minimal when the historical file isn't strictly period-sorted — the
    Belgium/France/… files have a few prior-year correction rows inserted
    out of order, and we don't want to noisily resort them on every run.
    """
    line_ending = detect_line_ending(path)
    by_period = {r["period"]: r for r in rows}
    if original_order:
        ordered: list[dict] = []
        seen: set[str] = set()
        for p in original_order:
            if p in by_period and p not in seen:
                ordered.append(by_period[p])
                seen.add(p)
        # New periods: append in sorted order at the end.
        new_periods = sorted(set(by_period.keys()) - seen)
        for p in new_periods:
            ordered.append(by_period[p])
    else:
        ordered = [by_period[p] for p in sorted(by_period.keys())]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator=line_ending)
        writer.writeheader()
        for r in ordered:
            writer.writerow({k: r.get(k, "") for k in fields})


def is_acea_source(src: str | None) -> bool:
    """True iff the existing row's source column is exactly "ACEA" (case-insensitive)."""
    return (src or "").strip().upper() == "ACEA"


def latest_period_across(data_dir: Path, countries: list[str]) -> str | None:
    """Returns the maximum period in any of the given country CSVs."""
    best: str | None = None
    for name in countries:
        path = data_dir / f"{name}.csv"
        _, rows = load_csv(path)
        for r in rows:
            p = r.get("period") or ""
            if p and (best is None or p > best):
                best = p
    return best


# --- PDF download ---------------------------------------------------------

class PDFAccessDenied(RuntimeError):
    """403 from ACEA — bot detection or IP allowlist hit. Not retryable."""


def load_pdf_bytes(url_or_path: str) -> bytes:
    if url_or_path.startswith("http://") or url_or_path.startswith("https://"):
        print(f"Downloading: {url_or_path}")
        session = requests.Session()
        session.headers.update(HTTP_HEADERS)
        # Warm up the session: a GET to the homepage lets ACEA's edge set the
        # session cookies its WAF expects on subsequent /files/*.pdf requests.
        # Failures here are non-fatal — surface only the PDF response status.
        try:
            session.get(ACEA_HOMEPAGE, timeout=30)
        except requests.RequestException as e:
            print(f"  homepage warmup request failed: {e}")
        resp = session.get(url_or_path, timeout=60)
        if resp.status_code == 404:
            # Truly not yet published. ACEA usually publishes the previous
            # month's PDF between the 22nd and 25th of the following month,
            # so 404s during the early cron days are expected.
            print("  HTTP 404 — PDF not published yet.")
            raise FileNotFoundError(url_or_path)
        if resp.status_code == 403:
            # 403 means we're blocked, not "not yet published". Two known
            # variants from ACEA's edge:
            #   * `x-deny-reason: host_not_allowed` — IP allowlist hit.
            #   * no x-deny-reason header — Cloudflare-style WAF/bot block.
            # Both are configuration problems, not a "retry tomorrow"
            # situation. Raise loudly so the workflow turns red and the
            # maintainer sees it (rather than the cron silently no-op'ing
            # every day until someone notices the data is stale).
            raise PDFAccessDenied(
                f"HTTP 403 from {url_or_path} "
                f"(x-deny-reason={resp.headers.get('x-deny-reason', 'n/a')}). "
                f"ACEA is blocking this runner; download the PDF from a "
                f"browser and re-run with --pdf-url path/to/file.pdf."
            )
        resp.raise_for_status()
        return resp.content
    path = url_or_path.replace("file://", "")
    with open(path, "rb") as f:
        return f.read()


# --- PDF parsing ---------------------------------------------------------

_INT_RE = re.compile(r"^-?\d{1,3}(?:,\d{3})*$")


def _parse_country_pairs(rest: str) -> list[tuple[int, int]] | None:
    """Read 7 (current_year, prior_year) integer pairs from one data line
    (everything after the country name).

    Each fuel section reads "<curr> <prev> <±pct>" left to right, except
    when both <curr> and <prev> are 0 — then the percentage token is
    omitted ("0 0" with the next fuel's value immediately following).
    We tokenise on whitespace, drop tokens containing "." (percentages),
    drop stand-alone +/- signs, and require exactly 14 integers.

    Dash glyphs ("ꟷ", "–", "—", "−") substitute for "0" in some country
    rows (Latvia HEV, Romania PHEV historically) and are treated as 0.
    """
    ints: list[int] = []
    for t in rest.split():
        if t in DASH_GLYPHS:
            ints.append(0)
            continue
        if "." in t or t in ("+", "-"):
            continue  # percentage value or stand-alone sign
        if _INT_RE.match(t):
            ints.append(int(t.replace(",", "")))
    if len(ints) != 14:
        return None
    return [(ints[i * 2], ints[i * 2 + 1]) for i in range(7)]


def _dump_pdf_diagnostics(pdf) -> None:
    """Print what pdfplumber sees for every page/table candidate. Called on
    parser failure so we can iterate on layout changes (e.g. April 2026
    switched from the old PDF generator to Microsoft Word, which renders
    table cell boundaries differently)."""
    print("DIAGNOSTIC: tables pdfplumber found")
    for pi, page in enumerate(pdf.pages):
        tables = page.extract_tables() or []
        print(f"  page {pi}: {len(tables)} table(s)")
        for ti, cand in enumerate(tables):
            rows = len(cand) if cand else 0
            cols = len(cand[0]) if cand and cand[0] else 0
            print(f"    table {ti}: rows={rows}, cols={cols}")
            for ri, row in enumerate(cand[:3] if cand else []):
                preview = " | ".join((c or "").replace("\n", "\\n")[:40] for c in row)
                print(f"      row[{ri}]: {preview}")

    # Word-generated PDFs frequently have data that extract_tables misses
    # because the cell boundaries aren't explicit rules. Dump per-page text
    # and try alternate extract_tables strategies so we can see country
    # names and pick the strategy that actually returns a country-by-fuel
    # grid.
    print("DIAGNOSTIC: per-page extract_text() (first 1500 chars)")
    for pi, page in enumerate(pdf.pages):
        text = (page.extract_text() or "")
        print(f"  --- page {pi}: {len(text)} chars ---")
        for line in text[:1500].split("\n"):
            print(f"    {line}")

    print("DIAGNOSTIC: alternate extract_tables strategies (table counts only)")
    strategies = {
        "text/text": {"vertical_strategy": "text", "horizontal_strategy": "text"},
        "text/lines": {"vertical_strategy": "text", "horizontal_strategy": "lines"},
        "lines/text": {"vertical_strategy": "lines", "horizontal_strategy": "text"},
    }
    for sname, settings in strategies.items():
        print(f"  -- strategy={sname}")
        for pi, page in enumerate(pdf.pages):
            try:
                tables = page.extract_tables(table_settings=settings) or []
            except Exception as e:
                print(f"    page {pi}: error: {e}")
                continue
            if not tables:
                continue
            for ti, cand in enumerate(tables):
                rows = len(cand) if cand else 0
                cols = len(cand[0]) if cand and cand[0] else 0
                header_preview = ""
                if cand and cand[0]:
                    header_preview = " | ".join(
                        (c or "").replace("\n", "\\n")[:25] for c in cand[0][:8]
                    )
                print(f"    page {pi} table {ti}: rows={rows}, cols={cols} | {header_preview}")


def _normalise_header(s: str | None) -> str:
    """Strip whitespace and trailing footnote digits; upper-case."""
    if not s:
        return ""
    return re.sub(r"\s+", "", s).rstrip("123").upper()


def _parse_cell(s: str) -> tuple[int, int] | None:
    """Parse a fuel-section cell into (current_year, prior_year) integers,
    or None if the cell doesn't yield at least two integers.

    Cell content forms observed in the legacy (pre-April 2026) PDF layout:
        '113 105 +7.6'   → (113, 105)        normal section
        '0 0'            → (0, 0)            both zero, YoY omitted
        'ꟷ ꟷ'           → (0, 0)            dash glyph means 0
        '5 0'            → (5, 0)            prior-year zero, YoY omitted
        '153 1 15,200.0' → (153, 1)          large YoY split across spaces

    Returning None (rather than raising) lets _parse_via_tables skip the
    country gracefully so the dispatcher can fall back to diagnostics
    instead of crashing on a single bad cell.
    """
    ints: list[int] = []
    for t in s.split():
        if t in DASH_GLYPHS:
            ints.append(0)
            continue
        if "." in t or t in ("+", "-"):
            continue
        if _INT_RE.match(t):
            ints.append(int(t.replace(",", "")))
    if len(ints) < 2:
        return None
    return ints[0], ints[1]


def _dump_pdf_diagnostics(pdf) -> None:
    """Print what pdfplumber sees for every page/table candidate. Called on
    parser failure so we can iterate on layout changes (e.g. April 2026
    switched from the old PDF generator to Microsoft Word, which renders
    table cell boundaries differently)."""
    print("DIAGNOSTIC: tables pdfplumber found")
    for pi, page in enumerate(pdf.pages):
        tables = page.extract_tables() or []
        print(f"  page {pi}: {len(tables)} table(s)")
        for ti, cand in enumerate(tables):
            rows = len(cand) if cand else 0
            cols = len(cand[0]) if cand and cand[0] else 0
            print(f"    table {ti}: rows={rows}, cols={cols}")
            for ri, row in enumerate(cand[:3] if cand else []):
                preview = " | ".join((c or "").replace("\n", "\\n")[:40] for c in row)
                print(f"      row[{ri}]: {preview}")


def parse_monthly_table(pdf_path: str) -> tuple[dict[str, dict[str, tuple[int, int]]], str | None]:
    """Returns ({country: {fuel: (curr, prev)}}, period_label).

    Works on the April 2026+ Word-generated PDFs where extract_tables()
    returns nothing on the country pages. Each country renders as a single
    line carrying 14 integers (7 fuel sections × {current, prior}); we
    tokenise and read off pairs in the documented PDF column order.
    """
    wanted = set(ALL_COUNTRIES)
    for page in pdf.pages:
        text = page.extract_text() or ""
        if "BY MARKET AND POWER SOURCE" not in text:
            continue
        if "YEAR TO DATE" in text or "MONTHLY" not in text:
            continue  # YTD page — same country list but cumulative

        # Period label from "April April % change" + "2026 2025 26/25".
        mm = re.search(r"\b([A-Z][a-z]+)\s+[A-Z][a-z]+\s+% change\b", text)
        ym = re.search(r"\b(\d{4})\s+\d{4}\s+\d{2}/\d{2}\b", text)
        period_label = (f"{mm.group(1)} {ym.group(1)}"
                        if mm and ym else None)

        countries: dict[str, dict[str, tuple[int, int]]] = {}
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            for country in wanted:
                # `country + " "` so "Slovenia 100…" doesn't match
                # "Slovakia " (or vice versa).
                if not line.startswith(country + " "):
                    continue
                pairs = _parse_country_pairs(line[len(country):])
                if pairs is not None:
                    countries[country] = dict(zip(PDF_FUEL_ORDER, pairs))
                break

        if countries:
            return countries, period_label

    return {}, None


def _parse_via_tables(pdf) -> tuple[dict[str, dict[str, tuple[int, int]]], str | None]:
    """Legacy parser: read the country grid via extract_tables().

    Kept as a fallback for the pre-April-2026 PDF generator that emitted
    explicit table cell rules. On those files extract_tables() returns a
    country-by-fuel grid with country names newline-joined in column 0 and
    fuel values newline-joined in each fuel column.
    """
    wanted = set(ALL_COUNTRIES)
    for page in pdf.pages:
        for cand in (page.extract_tables() or []):
            if not cand or len(cand) < 3:
                continue
            header_norm = [_normalise_header(c) for c in cand[0]]
            if "BATTERYELECTRIC" not in header_norm or "TOTAL" not in header_norm:
                continue
            # MONTHLY vs YTD lives in the sub-header row.
            sub = " ".join((cand[1][i] or "") for i in range(len(cand[1])))
            sub_compact = re.sub(r"\s+", " ", sub)
            if "Jan-" in sub_compact or "Jan -" in sub_compact:
                continue  # YTD
            m = re.search(r"([A-Z][a-z]+)\D+(\d{4})", sub_compact)
            period_label = f"{m.group(1)} {m.group(2)}" if m else None

            fuel_col: dict[str, int] = {}
            for ci, cell in enumerate(cand[0]):
                key = HEADER_TO_FUEL.get(_normalise_header(cell))
                if key and key not in fuel_col:
                    fuel_col[key] = ci
            if set(HEADER_TO_FUEL.values()) - set(fuel_col.keys()):
                continue  # header malformed, try next candidate

            countries: dict[str, dict[str, tuple[int, int]]] = {}
            for row in cand[1:]:
                names = [n.strip() for n in (row[0] or "").split("\n") if n.strip()]
                if not names or all(
                    n.upper() in {"EUROPEAN UNION", "EFTA", "EU + EFTA + UK"}
                    for n in names
                ):
                    continue
                fuel_lines = {
                    fuel: (row[ci] or "").split("\n")
                    for fuel, ci in fuel_col.items()
                }
                for i, country in enumerate(names):
                    if country not in wanted:
                        continue
                    parsed: dict[str, tuple[int, int]] = {}
                    incomplete = False
                    for fuel in HEADER_TO_FUEL.values():
                        lines = fuel_lines[fuel]
                        cell = _parse_cell(lines[i]) if i < len(lines) else None
                        if cell is None:
                            incomplete = True
                            break
                        parsed[fuel] = cell
                    if not incomplete:
                        countries[country] = parsed

            if countries:
                return countries, period_label

    return {}, None


def parse_monthly_table(pdf_path: str) -> tuple[dict[str, dict[str, tuple[int, int]]], str | None]:
    """Returns ({country: {fuel: (curr, prev)}}, period_label).

    Tries the text-layer parser first (works on April 2026+ Word PDFs and
    is generator-agnostic). If that yields no countries — most likely
    because pdfplumber's extract_text() laid the page out unexpectedly —
    falls back to the legacy extract_tables() parser (works on pre-April
    PDFs with explicit cell rules). Only when both paths come up empty
    do we dump diagnostics and raise.
    """
    with pdfplumber.open(pdf_path) as pdf:
        countries, period_label = _parse_via_text(pdf)
        if countries:
            return countries, period_label

        print("text-layer parser found no countries; falling back to "
              "extract_tables()")
        countries, period_label = _parse_via_tables(pdf)
        if countries:
            return countries, period_label

        _dump_pdf_diagnostics(pdf)
        raise RuntimeError("Could not locate the MONTHLY country grid in the PDF")


# --- Row construction & decision logic ------------------------------------

def build_row(period: str, parsed: dict[str, tuple[int, int]], use_prev: bool,
              fields: list[str], source_url: str) -> dict:
    """Build a CSV row dict for `period` from a parsed-country fuel map.

    `use_prev=False` writes the (current-year) value, `True` the prior-year one.
    Schema is inferred from `fields` so non-standard columns (Sweden FLEXFUEL)
    are preserved as 0.0.
    """
    idx = 1 if use_prev else 0
    val = {fuel: float(vals[idx]) for fuel, vals in parsed.items()}
    row: dict[str, str | float] = {f: "" for f in fields}
    row["period"] = period
    row["time_interval"] = "monthly"
    row["variant"] = "Whole"
    row["source"] = ACEA_SOURCE
    row["notes"] = source_url
    for fuel in ("BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL"):
        if fuel in fields:
            row[fuel] = val.get(fuel, 0.0)
    # Any extra columns (e.g. FLEXFUEL for Sweden) default to 0.0 — ACEA
    # doesn't break those out.
    for f in fields:
        if f not in row or row[f] == "":
            if f in ("period", "time_interval", "variant", "source", "notes"):
                continue
            row[f] = 0.0
    return row


def should_write(country: str, row_kind: str, existing_row: dict | None) -> bool:
    """Decision matrix per maintainer's instructions.

    row_kind:
      * 'current'       — the target period itself (e.g. 2026-03)
      * 'previous_year' — same month, prior year (e.g. 2025-03)
    """
    if row_kind == "current" and country in ALWAYS_COUNTRIES:
        return True  # always-list current month: unconditional overwrite
    # Every other case: write iff no row exists OR existing source == "ACEA".
    if existing_row is None:
        return True
    return is_acea_source(existing_row.get("source"))


def row_equals(existing: dict | None, new: dict, fields: list[str]) -> bool:
    """True if `existing` already carries the same payload as `new`.

    A row is considered equal when all numeric fuel columns and TOTAL match
    (compared as floats with a tiny tolerance), and source/time_interval/variant
    agree. `notes` is allowed to differ — the URL changes month to month.
    """
    if existing is None:
        return False
    if (existing.get("time_interval") or "") != new["time_interval"]:
        return False
    if (existing.get("variant") or "") != new["variant"]:
        return False
    if (existing.get("source") or "") != new["source"]:
        return False
    numeric_fields = [f for f in fields
                      if f not in ("period", "time_interval", "variant", "source", "notes")]
    for f in numeric_fields:
        try:
            a = float(existing.get(f) or 0.0)
            b = float(new.get(f) or 0.0)
        except (TypeError, ValueError):
            return False
        if abs(a - b) > 0.5:  # float ≈ integer-counts → 0.5 is safe slack
            return False
    return True


# --- Per-country update ---------------------------------------------------

def update_country(data_dir: Path, country: str,
                   parsed: dict[str, tuple[int, int]],
                   target_period: str, source_url: str) -> bool:
    """Apply the write rules to one country. Returns True if the CSV changed."""
    path = data_dir / f"{country}.csv"
    fields, rows = load_csv(path)
    original_order = [r["period"] for r in rows]
    by_period = {r["period"]: r for r in rows}
    changed = False

    for kind, period, use_prev in (
        ("current", target_period, False),
        ("previous_year", prev_year_period(target_period), True),
    ):
        existing = by_period.get(period)
        if not should_write(country, kind, existing):
            print(f"    {country} {period} ({kind}): skipped "
                  f"(existing source={existing.get('source')!r})")
            continue
        new_row = build_row(period, parsed, use_prev=use_prev,
                            fields=fields, source_url=source_url)
        if row_equals(existing, new_row, fields):
            # No-op: already at the desired state.
            continue
        by_period[period] = new_row
        action = "added" if existing is None else "updated"
        print(f"    {country} {period} ({kind}): {action}")
        changed = True

    if changed:
        write_csv(path, fields, list(by_period.values()),
                  original_order=original_order)
    return changed


# --- Main ----------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int)
    parser.add_argument("--month", type=int, choices=range(1, 13))
    parser.add_argument("--pdf-url", help="Direct URL/path to ACEA monthly PDF")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--force", action="store_true",
                        help="Skip the latest-period short-circuit")
    parser.add_argument("--force-render", action="store_true",
                        help="Recovery mode: skip fetch/parse entirely and "
                             "emit changed_countries=ALL_COUNTRIES for the "
                             "workflow's render matrix. Use after a "
                             "stale-checkout render run lost the renders "
                             "while the data commit succeeded.")
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"),
                        help="Write `changed_countries=<json>` here (workflow output)")
    args = parser.parse_args()

    # Recovery shortcut: skip everything, just emit the country list so the
    # render matrix fans out. No data writes, no PDF download. The render
    # workflow re-reads each CSV from the current branch tip.
    if args.force_render:
        print(f"--force-render: skipping fetch/parse, dispatching render "
              f"matrix for {len(ALL_COUNTRIES)} countries.")
        if args.github_output:
            with open(args.github_output, "a", encoding="utf-8") as f:
                f.write(f"changed_countries={json.dumps(list(ALL_COUNTRIES))}\n")
                f.write("any_changed=true\n")
        return 0

    # Target month
    if args.year and args.month:
        target_year, target_month = args.year, args.month
    elif args.year or args.month:
        sys.exit("--year and --month must be given together")
    else:
        target_year, target_month = previous_month(date.today())
    target_period = f"{target_year}-{target_month:02d}"
    month_name = ENGLISH_MONTHS[target_month - 1]
    print(f"Target period: {target_period} ({month_name} {target_year})")

    data_dir = Path(args.data_dir)

    # Self-throttle: if every always-list country already has the target period,
    # we don't need to hit ACEA at all. We compare against MAX so partial
    # back-fills (e.g. a country missing one historical month) don't block us.
    if not args.force:
        max_period = latest_period_across(data_dir, ALWAYS_COUNTRIES)
        if max_period and max_period >= target_period:
            print(f"All always-list CSVs already at {max_period} ≥ {target_period} — "
                  f"nothing to do.")
            return 0

    # PDF source
    pdf_url = args.pdf_url or ACEA_URL_TEMPLATE.format(
        month_name=month_name, year=target_year)
    try:
        pdf_bytes = load_pdf_bytes(pdf_url)
    except FileNotFoundError:
        print("PDF not available yet — will retry next scheduled run.")
        return 0
    except PDFAccessDenied as e:
        # Hard fail: the runner is blocked, not the PDF missing. Cron retries
        # from the same IP won't help — the maintainer needs to download the
        # PDF manually and re-dispatch with the pdf_url input.
        sys.exit(str(e))
    except requests.HTTPError as e:
        print(f"Could not fetch {pdf_url}: {e}. Pass --pdf-url manually.")
        return 0

    # pdfplumber needs a file path or buffer
    tmp_pdf = Path("/tmp/_acea_latest.pdf")
    tmp_pdf.write_bytes(pdf_bytes)

    parsed_all, period_label = parse_monthly_table(str(tmp_pdf))
    if period_label:
        print(f"Parsed table for: {period_label}")
        # Verify the PDF's month matches what was requested. A mismatch
        # usually means --pdf-url was pointed at a different month's release.
        expected_label = f"{month_name} {target_year}"
        if period_label != expected_label:
            sys.exit(f"PDF reports {period_label!r} but target is "
                     f"{expected_label!r} — refusing to write mismatched data.")
    print(f"Countries parsed: {sorted(parsed_all.keys())}")

    missing = set(ALL_COUNTRIES) - set(parsed_all.keys())
    if missing:
        print(f"WARNING: countries missing from PDF: {sorted(missing)}")

    # Per-country sanity: component sum should match TOTAL. We warn but don't
    # fail — Malta has been observed off-by-1 in ACEA's source data.
    for country, fuels in parsed_all.items():
        for idx_name, idx in (("curr", 0), ("prev", 1)):
            s = sum(fuels[f][idx] for f in ("BEV", "PHEV", "HEV",
                                            "OTHERS", "PETROL", "DIESEL"))
            total = fuels["TOTAL"][idx]
            if s != total:
                print(f"  sanity {country} {idx_name}: components={s} TOTAL={total} "
                      f"(Δ={s - total})")

    changed: list[str] = []
    for country in ALL_COUNTRIES:
        if country not in parsed_all:
            continue
        if update_country(data_dir, country, parsed_all[country], target_period, pdf_url):
            changed.append(country)

    print(f"\nCountries with CSV changes: {changed}")

    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as f:
            f.write(f"changed_countries={json.dumps(changed)}\n")
            f.write(f"any_changed={'true' if changed else 'false'}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
