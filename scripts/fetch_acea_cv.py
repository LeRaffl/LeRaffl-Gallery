#!/usr/bin/env python3
"""
Fetch ACEA's annual Commercial Vehicle press release PDF and upsert
Vans / HDV / Buses rows into data/<Country>_<Variant>.csv for the ACEA
multi-country roster (the same 19 EU/EFTA markets scripts/fetch_acea.py
covers for passenger cars).

Usage
-----
    python scripts/fetch_acea_cv.py [--year YEAR] [--pdf-url URL_OR_PATH] \
        [--data-dir data] [--force] [--allow-partial-year] \
        [--github-output PATH]

* --year               Target calendar year whose FULL-YEAR figures to fetch
                        (default: previous calendar year — ACEA publishes the
                        prior year's commercial-vehicle wrap-up press release
                        in mid-to-late January).
* --pdf-url            Direct URL/path to a Press_release_commercial_vehicle
                        PDF. If omitted, a handful of candidate URLs are
                        tried in turn (ACEA has renamed this release's
                        filename pattern at least twice; see "URL patterns"
                        below).
* --data-dir           Folder containing data/<Country>_<Variant>.csv.
* --force              Skip the "already up-to-date" self-throttle.
* --allow-partial-year Parse a partial-year release (H1 / Q1-Q3) and print
                        what would be extracted, but never write it to a
                        CSV. Debug/inspection only — see "Why annual-only"
                        below for why partial-year checkpoints are never
                        committed.
* --github-output       Optional path; when set, the list of
                        "<Country> (<Variant>)" pairs actually written is
                        emitted as `changed_pairs=<json-array-of-objects>`
                        (used by fetch-acea-cv.yml's render matrix).

Invoked by .github/workflows/fetch-acea-cv.yml on a daily cron in the back
half of January (ACEA typically publishes the full-year commercial-vehicle
wrap-up between the 20th and 29th). The script self-throttles by reading the
latest year on record for every target (country, variant) file, so once a
year's data has landed the cheapest path is "already at target, no HTTP".

Why annual-only
----------------
Since ~2024 ACEA no longer publishes a genuinely monthly commercial-vehicle
release. Instead it publishes four **cumulative year-to-date** snapshots per
year: Q1 (~April), H1 (~July/August), Q1-Q3 (~October) and the full year
(~January of the following year). A "Q1-Q3 2024" table is Jan-Sep 2024
*cumulative* — not Q3 alone — so treating each release as a self-contained
period would double- (or triple-, or quadruple-) count registrations against
neighbouring releases and would corrupt every trailing-window computation
downstream (TTM shares, the S-curve fit, weights.csv).

Reconstructing genuine per-quarter deltas (Q2 = H1 − Q1, Q3 = Q1-Q3 − H1, …)
is possible in principle, but requires an unbroken chain of consecutive
checkpoints per country *and* durable state to bridge across separate
workflow runs — machinery this repo doesn't have a precedent for, and that
a first version doesn't need. The **full year** release is the one checkpoint
that is always a clean, non-overlapping, self-contained period on its own
(Jan 1 - Dec 31, nothing to subtract), so this fetcher only ever ingests
that one. `time_interval` is written as `yearly` (`period` = `YYYY-07`,
matching the existing yearly convention — see docs/architecture/09-glossary.md
§ Time / period). This is the harmonized long-term shape: one clean,
correct row per country/variant/year, forever, rather than a fragile
quarterly-delta pipeline that only a maintainer with a spreadsheet could
debug when a checkpoint is missed. If genuine quarterly granularity is
wanted later, it should be built as its own follow-up with its own explicit
state file, not bolted on here.

Two report eras
----------------
* **Old era** (through ~2023, e.g. the Dec-2022 / FY-2022 release parsed
  here): five simple tables — LCV (Vans), HCV≥16t, MHCV>3.5t (Vans/HDV/Buses
  map onto LCV/MHCV/MHBC respectively), MHBC, Total CV. Each has only a
  DECEMBER block and a JANUARY-DECEMBER block, Units + % change, no fuel
  split at all. We read the JANUARY-DECEMBER "Units" pair (current year,
  prior year) and leave every fuel column empty (TOTAL only) — per the
  project's "no-split fuel column -> leave empty, never 0.0" invariant.
* **New era** (from ~2024, e.g. the Q1-Q3-2024 / H1-2026 releases parsed
  here): five tables — Van, Medium Truck, Heavy Truck, Total Truck, Bus —
  each with a full fuel-column grid: ELECTRICALLY CHARGEABLE (BEV+PHEV
  combined — ACEA does not split plug-in hybrids out of this bucket for
  commercial vehicles), HYBRID ELECTRIC (full+mild hybrid combined),
  OTHERS, PETROL, DIESEL, TOTAL, each as a (current-period, prior-period)
  pair. Van -> Vans, Total Truck -> HDV (already N2+N3 combined, matching
  the project's HDV definition), Bus -> Buses. The combined
  "electrically chargeable" figure is written into the BEV column (PHEV
  stays empty) so the variant still has a usable plug-in-adoption curve;
  this is a documented approximation, not a true BEV-only count — see
  footnotes.csv and docs/architecture/38-source-acea-cv.md.

Country-name drift between eras: the old era spells it "Czech Republic",
the new era "Czechia" — normalised via NAME_ALIASES below.

URL patterns
------------
ACEA has changed this release's filename scheme at least twice (a cryptic
date-prefixed name through ~2023, then two different underscore/hyphen
variants for the H1 and Q1-Q3 2024+ releases). There is no confirmed sample
of the new-era filename for a **full-year** release in this codebase yet —
CANDIDATE_URL_TEMPLATES lists the most plausible guesses, tried in order.
When the live fetch first runs (from a network egress that can actually
reach acea.auto — this repo's sandbox cannot, see the module's git history
for confirmation), expect to need one `--pdf-url` correction; that is normal
bring-up, not a bug.

Per-country write rule
-----------------------
Every target country is "conditional" (unlike fetch_acea.py's always/
conditional split for passenger cars): a (country, variant, period) row is
only written if no row exists yet for that period, or the existing row's
source is exactly "ACEA" (case-insensitive). This is what lets this fetcher
run safely across every target country without ever clobbering a national
HDV/Vans/Buses source that already exists for the same file (Austria,
Luxembourg, Poland today) — see is_acea_source().
"""
import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

import pdfplumber
import requests

# --- Constants ------------------------------------------------------------

# The same 19-country ACEA roster scripts/fetch_acea.py maintains for
# passenger cars (its ALWAYS_COUNTRIES + CONDITIONAL_COUNTRIES). Countries
# with their own national HDV/Vans/Buses source (Austria, Luxembourg,
# Poland today) are simply skipped by the per-file conditional-write rule
# below — no separate exclusion list needed.
TARGET_COUNTRIES = [
    "Belgium", "Bulgaria", "Croatia", "Cyprus", "Czechia", "Estonia",
    "Greece", "Hungary", "Iceland", "Latvia", "Lithuania",
    "Luxembourg", "Malta", "Norway", "Poland", "Romania",
    "Slovakia", "Slovenia", "Switzerland",
]

# Old-era PDFs spell some countries differently than the new-era ones (and
# differently than our TARGET_COUNTRIES / data/ filenames).
NAME_ALIASES = {
    "CZECH REPUBLIC": "Czechia",
    "SLOVAK REPUBLIC": "Slovakia",
}

VARIANTS = ("Vans", "HDV", "Buses")

# Heading text (normalised: upper-cased, whitespace-collapsed) that
# identifies each variant's table in each era. Matched with `in`, not
# equality, since the real headings carry footnote-marker digits and extra
# words ("NEW VAN1 2 REGISTRATIONS", "LIGHT COMMERCIAL VEHICLES (LCV) UP TO
# 3.5T1 EUROPEAN UNION2 + EFTA + UK", ...).
NEW_ERA_HEADINGS = {
    "Vans": "NEW VAN",
    "HDV": "TOTAL NEW TRUCK",
    "Buses": "NEW BUS",
}
OLD_ERA_HEADINGS = {
    "Vans": "LIGHT COMMERCIAL VEHICLES (LCV)",
    "HDV": "MEDIUM AND HEAVY COMMERCIAL VEHICLES (MHCV)",
    "Buses": "MEDIUM AND HEAVY BUSES",  # "... & COACHES (MHBC) OVER 3.5T"
}

# New-era column order (left to right) in the fuel-split grid. ACEA's
# "ELECTRICALLY CHARGEABLE" bucket combines BEV+PHEV (footnote: "Includes
# battery electric and plug-in hybrids") -- there is no separate PHEV
# figure for commercial vehicles, so it is written into our BEV column and
# PHEV is left empty. See the module docstring and
# docs/architecture/38-source-acea-cv.md.
NEW_ERA_FUEL_ORDER = ("BEV", "HEV", "OTHERS", "PETROL", "DIESEL", "TOTAL")

STANDARD_CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS",
    "TOTAL", "notes",
]

ACEA_SOURCE = "ACEA"

DASH_GLYPHS = ("ꟷ", "–", "—", "−", "─")

ACEA_HOMEPAGE = "https://www.acea.auto/"

# Candidate filename patterns for the full-year release, tried in order
# until one returns HTTP 200. See "URL patterns" in the module docstring.
CANDIDATE_URL_TEMPLATES = [
    "https://www.acea.auto/files/Press_release_commercial_vehicle_registrations_{year}.pdf",
    "https://www.acea.auto/files/Press_release_commercial_vehicle_registrations-{year}.pdf",
    "https://www.acea.auto/files/Press_release_commercial_vehicle_registrations_FY_{year}.pdf",
    "https://www.acea.auto/files/Press_release_commercial_vehicle_registrations-FY_{year}.pdf",
]

# Same bot-detection workaround as scripts/fetch_acea.py.
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
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

_INT_RE = re.compile(r"^-?\d{1,3}(?:,\d{3})*$")


def _normalise_country(name: str) -> str:
    name = name.strip()
    return NAME_ALIASES.get(name.upper(), name)


def _normalise_header(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip().upper()


def _tokenize_ints(s: str, n_expected: int) -> list[int] | None:
    """Read exactly `n_expected` integers from a line/cell, tolerating dash
    glyphs (-> 0), stand-alone +/- signs and percentage tokens (dropped)."""
    ints: list[int] = []
    for t in s.split():
        if t in DASH_GLYPHS:
            ints.append(0)
            continue
        if "." in t or t in ("+", "-"):
            continue
        if _INT_RE.match(t):
            ints.append(int(t.replace(",", "")))
    if len(ints) != n_expected:
        return None
    return ints


# --- PDF download -----------------------------------------------------

class PDFAccessDenied(RuntimeError):
    pass


def load_pdf_bytes(url_or_path: str) -> bytes:
    if url_or_path.startswith("http://") or url_or_path.startswith("https://"):
        print(f"Downloading: {url_or_path}")
        session = requests.Session()
        session.headers.update(HTTP_HEADERS)
        try:
            session.get(ACEA_HOMEPAGE, timeout=30)
        except requests.RequestException as e:
            print(f"  homepage warmup request failed: {e}")
        resp = session.get(url_or_path, timeout=60)
        if resp.status_code == 404:
            raise FileNotFoundError(url_or_path)
        if resp.status_code == 403:
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


def fetch_annual_pdf(year: int, pdf_url: str | None) -> tuple[bytes, str]:
    """Returns (pdf_bytes, source_url_used). Tries --pdf-url verbatim if
    given, otherwise walks CANDIDATE_URL_TEMPLATES until one succeeds."""
    if pdf_url:
        return load_pdf_bytes(pdf_url), pdf_url
    last_err: Exception | None = None
    for tmpl in CANDIDATE_URL_TEMPLATES:
        url = tmpl.format(year=year)
        try:
            return load_pdf_bytes(url), url
        except FileNotFoundError as e:
            last_err = e
            continue
    raise FileNotFoundError(
        f"None of the candidate URLs for {year} were found: "
        f"{[t.format(year=year) for t in CANDIDATE_URL_TEMPLATES]}. "
        f"Pass --pdf-url explicitly."
    )


# --- Text extraction ---------------------------------------------------
#
# Both report eras turn out to render their country/data rows with each
# character individually positioned and flagged `upright=False` (a Word- or
# LibreOffice-print-driver quirk, not a real rotation — the glyphs display
# normally). pdfplumber's own extract_text()/extract_tables() word-clustering
# assumes upright text and falls apart on this: extract_tables() finds
# nothing at all, and extract_text() inserts a spurious space between almost
# every letter ("A u s tria") while still (correctly, as it happens) keeping
# one country per line. Rather than fight pdfplumber's clustering, we
# reconstruct lines directly from page.chars: group by (rounded) vertical
# position, sort each group left-to-right, and only insert a space where the
# horizontal gap between consecutive glyphs is wide enough to be a real
# word/column boundary rather than normal kerning. This is what
# scripts/fetch_acea.py's own "April 2026 switched to Word's PDF export"
# workaround was reaching for — this PDF family needed the character-level
# version of that workaround.
_LINE_GAP_TOLERANCE_PT = 1.2  # word/column boundary threshold, in points
_LINE_TOP_TOLERANCE_PT = 1.0  # chars within this many points of top merge into one line


def page_lines(page) -> list[str]:
    chars = page.chars
    if not chars:
        return []
    buckets: list[list] = []  # [top, [chars]]
    for c in sorted(chars, key=lambda c: c["top"]):
        bucket = next((b for b in buckets
                      if abs(b[0] - c["top"]) <= _LINE_TOP_TOLERANCE_PT), None)
        if bucket is None:
            buckets.append([c["top"], [c]])
        else:
            bucket[1].append(c)
    lines = []
    for _, row_chars in sorted(buckets, key=lambda b: b[0]):
        row_chars.sort(key=lambda c: c["x0"])
        buf: list[str] = []
        prev_x1 = None
        for c in row_chars:
            if prev_x1 is not None and c["x0"] - prev_x1 > _LINE_GAP_TOLERANCE_PT:
                buf.append(" ")
            buf.append(c["text"])
            prev_x1 = c["x1"]
        lines.append("".join(buf))
    return lines


def page_text(page) -> str:
    return "\n".join(page_lines(page))


# --- New-era parsing (fuel-split, current+prior period pairs) -------------

def _new_era_candidate_names() -> set[str]:
    return set(TARGET_COUNTRIES) | {"Germany", "France", "Sweden", "United Kingdom"}


def _parse_new_era_page(text: str) -> dict[str, tuple[int, ...]]:
    """Returns {country: (curr0, prev0, ..., curr5, prev5)} for the 6
    NEW_ERA_FUEL_ORDER blocks — one country per line, 12 integers after
    the name."""
    countries: dict[str, tuple[int, ...]] = {}
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        for name in _new_era_candidate_names():
            if not line.startswith(name + " "):
                continue
            ints = _tokenize_ints(line[len(name):], 12)  # 6 fuels x (curr, prev)
            if ints is not None:
                countries[name] = tuple(ints)
            break
    return countries


def parse_new_era(pdf) -> tuple[dict[str, dict[str, dict[str, tuple[int, int]]]], str | None]:
    """Returns ({variant: {country: {fuel: (curr, prev)}}}, period_label)."""
    result: dict[str, dict[str, dict[str, tuple[int, int]]]] = {}
    period_label = None

    for variant, heading in NEW_ERA_HEADINGS.items():
        for page in pdf.pages:
            text = page_text(page)
            tnorm = text.upper()
            if heading not in tnorm:
                continue
            found = _parse_new_era_page(text)
            if not found:
                continue
            if period_label is None:
                # The column-header line reads e.g. "H1 2026 H1 2025
                # % change ..." (partial year) or "2026 2025 % change ..."
                # (a full year release carries no H1/Q1-Q3/FY prefix).
                for line in text.split("\n"):
                    m = re.match(r"^(H1|Q1-Q3|Q1|Q3|FY)?\s*(\d{4})\s+\1?\s*\d{4}\s+%\s*change",
                                 line.strip(), re.IGNORECASE)
                    if m:
                        prefix = (m.group(1) or "").upper()
                        period_label = f"{prefix} {m.group(2)}".strip()
                        break
            result[variant] = {
                country: dict(zip(NEW_ERA_FUEL_ORDER,
                                  [(vals[i * 2], vals[i * 2 + 1]) for i in range(6)]))
                for country, vals in found.items()
            }
            break
    return result, period_label


# --- Old-era parsing (TOTAL only, DECEMBER + JANUARY-DECEMBER blocks) -----

_OLD_ERA_ALL_NAMES = None  # populated lazily; see _old_era_candidate_names()


def _old_era_candidate_names() -> set[str]:
    global _OLD_ERA_ALL_NAMES
    if _OLD_ERA_ALL_NAMES is None:
        _OLD_ERA_ALL_NAMES = (set(TARGET_COUNTRIES)
                              | {"Czech Republic", "Slovak Republic"}
                              | {"Germany", "France", "Sweden",
                                 "United Kingdom", "Ireland", "Italy",
                                 "Netherlands", "Denmark", "Finland",
                                 "Portugal", "Spain"})
    return _OLD_ERA_ALL_NAMES


def _parse_old_era_text(text: str) -> dict[str, tuple[int, int]]:
    """Returns {country: (ytd_curr, ytd_prev)} from one page's text layer.
    Each data line is "<Country><footnote digits?> <month_curr> <month_prev>
    <%chg> <ytd_curr> <ytd_prev> <%chg>"; tokenising drops the %chg tokens
    (they contain '.'), leaving exactly 4 integers."""
    countries: dict[str, tuple[int, int]] = {}
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        for name in _old_era_candidate_names():
            # Footnote markers ("Ireland3", "Italy4") sit directly after
            # the name with no space, so match on the name prefix and let
            # the digit(s) fall into the first %chg-style token dropped
            # below only if they're not immediately followed by a digit
            # that's actually part of the first real number.
            if line == name or line.startswith(name + " ") or \
               re.match(re.escape(name) + r"\d+\s", line):
                rest = line[len(name):]
                rest = re.sub(r"^\d+", "", rest)  # strip a footnote digit
                ints = _tokenize_ints(rest, 4)  # month_curr, month_prev, ytd_curr, ytd_prev
                if ints is not None:
                    countries[_normalise_country(name)] = (ints[2], ints[3])
                break
    return countries


def parse_old_era(pdf) -> tuple[dict[str, dict[str, dict[str, tuple[int, int]]]], str | None]:
    result: dict[str, dict[str, dict[str, tuple[int, int]]]] = {}
    period_label = None

    for variant, heading in OLD_ERA_HEADINGS.items():
        for page in pdf.pages:
            text = page_text(page)
            tnorm = text.upper()
            if heading not in tnorm:
                continue
            if "JANUARY-DECEMBER" not in tnorm and "JANUARY - DECEMBER" not in tnorm:
                continue  # a monthly (non-December) release — not our target
            found = _parse_old_era_text(text)
            if not found:
                continue
            if period_label is None:
                m = re.search(r"JANUARY-DECEMBER\D*(\d{4})", tnorm)
                m2 = re.search(r"\b(20\d{2})\b", text)
                period_label = (m.group(1) if m else (m2.group(1) if m2 else None))
            result[variant] = {c: {"TOTAL": v} for c, v in found.items()}
            break
    return result, period_label


def detect_era(pdf) -> str:
    for page in pdf.pages[:5]:
        if "ELECTRICALLY CHARGEABLE" in page_text(page).upper():
            return "new"
    return "old"


# --- CSV helpers (same shape as scripts/fetch_acea.py) --------------------

def detect_line_ending(path: Path) -> str:
    if not path.exists():
        return "\r\n"
    with open(path, "rb") as f:
        head = f.read(4096)
    return "\r\n" if b"\r\n" in head else "\n"


def load_csv(path: Path) -> tuple[list[str], list[dict]]:
    if not path.exists():
        return list(STANDARD_CSV_COLUMNS), []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fields = list(reader.fieldnames or STANDARD_CSV_COLUMNS)
    return fields, rows


def write_csv(path: Path, fields: list[str], rows: list[dict],
              original_order: list[str] | None = None) -> None:
    line_ending = detect_line_ending(path)
    by_period = {r["period"]: r for r in rows}
    if original_order:
        ordered: list[dict] = []
        seen: set[str] = set()
        for p in original_order:
            if p in by_period and p not in seen:
                ordered.append(by_period[p])
                seen.add(p)
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
    return (src or "").strip().upper() == "ACEA"


def latest_year_across(data_dir: Path) -> int | None:
    best: int | None = None
    for country in TARGET_COUNTRIES:
        for variant in VARIANTS:
            path = data_dir / f"{country}_{variant}.csv"
            _, rows = load_csv(path)
            for r in rows:
                if (r.get("source") or "").strip().upper() != ACEA_SOURCE.upper():
                    continue
                p = r.get("period") or ""
                if re.match(r"^\d{4}-07$", p):
                    y = int(p[:4])
                    if best is None or y > best:
                        best = y
    return best


def build_row(period: str, fields: list[str], fuels: dict[str, tuple[int, int]] | None,
              use_prev: bool, source_url: str, era: str) -> dict:
    idx = 1 if use_prev else 0
    row: dict[str, str | float] = {f: "" for f in fields}
    row["period"] = period
    row["time_interval"] = "yearly"
    row["source"] = ACEA_SOURCE
    row["notes"] = source_url if era == "new" else (
        f"{source_url} (pre-fuel-split ACEA CV release: TOTAL only)"
    )
    if fuels is None:
        return row
    for fuel, vals in fuels.items():
        if fuel in fields:
            row[fuel] = float(vals[idx])
    return row


def should_write(existing_row: dict | None) -> bool:
    if existing_row is None:
        return True
    return is_acea_source(existing_row.get("source"))


def row_equals(existing: dict | None, new: dict, fields: list[str]) -> bool:
    if existing is None:
        return False
    if (existing.get("time_interval") or "") != new["time_interval"]:
        return False
    if (existing.get("source") or "") != new["source"]:
        return False
    numeric_fields = [f for f in fields
                      if f not in ("period", "time_interval", "variant", "source", "notes")]
    for f in numeric_fields:
        try:
            a = float(existing.get(f) or 0.0) if existing.get(f) not in (None, "") else None
            b = float(new.get(f) or 0.0) if new.get(f) not in (None, "") else None
        except (TypeError, ValueError):
            return False
        if a != b:
            return False
    return True


def update_variant_file(data_dir: Path, country: str, variant: str,
                        target_year: int, fuels_curr: dict[str, tuple[int, int]] | None,
                        source_url: str, era: str) -> bool:
    path = data_dir / f"{country}_{variant}.csv"
    fields, rows = load_csv(path)
    original_order = [r["period"] for r in rows]
    by_period = {r["period"]: r for r in rows}
    changed = False

    for year, use_prev in ((target_year, False), (target_year - 1, True)):
        period = f"{year}-07"
        existing = by_period.get(period)
        if not should_write(existing):
            print(f"    {country} {variant} {period}: skipped "
                  f"(existing source={existing.get('source')!r})")
            continue
        new_row = build_row(period, fields, fuels_curr, use_prev, source_url, era)
        new_row["variant"] = variant
        if row_equals(existing, new_row, fields):
            continue
        by_period[period] = new_row
        action = "added" if existing is None else "updated"
        print(f"    {country} {variant} {period}: {action}")
        changed = True

    if changed:
        write_csv(path, fields, list(by_period.values()), original_order=original_order)
    return changed


# --- Main ------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, help="Target calendar year (default: previous year)")
    parser.add_argument("--pdf-url", help="Direct URL/path to the ACEA annual CV PDF")
    parser.add_argument("--source-note-url",
                        help="URL recorded in the CSV notes column, if different from "
                             "--pdf-url (e.g. --pdf-url is a local file:// backfill copy "
                             "but the row should cite the real acea.auto URL it came from)")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--allow-partial-year", action="store_true",
                        help="Parse an H1/Q1-Q3 release for inspection; never writes a CSV")
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    args = parser.parse_args()

    from datetime import date
    target_year = args.year or (date.today().year - 1)
    data_dir = Path(args.data_dir)

    if not args.force:
        latest = latest_year_across(data_dir)
        if latest is not None and latest >= target_year:
            print(f"All ACEA-sourced CV files already at year {latest} >= {target_year} — "
                  f"nothing to do.")
            return 0

    try:
        pdf_bytes, source_url = fetch_annual_pdf(target_year, args.pdf_url)
    except FileNotFoundError as e:
        print(f"PDF not available yet: {e}. Will retry next scheduled run.")
        return 0
    except PDFAccessDenied as e:
        sys.exit(str(e))

    source_url = args.source_note_url or source_url

    tmp_pdf = Path("/tmp/_acea_cv_latest.pdf")
    tmp_pdf.write_bytes(pdf_bytes)

    with pdfplumber.open(str(tmp_pdf)) as pdf:
        era = detect_era(pdf)
        print(f"Detected era: {era}")
        if era == "new":
            parsed, period_label = parse_new_era(pdf)
        else:
            parsed, period_label = parse_old_era(pdf)

    print(f"Parsed period label: {period_label!r}")
    is_full_year = bool(period_label) and re.fullmatch(r"\d{4}", (period_label or "").strip())
    if not is_full_year:
        print(f"Release {period_label!r} is not a full-year (JANUARY-DECEMBER) release — "
              f"partial-year YTD checkpoints are never committed (see module docstring, "
              f"'Why annual-only').")
        if args.allow_partial_year:
            for variant, countries in parsed.items():
                print(f"  [inspect] {variant}: {sorted(countries.keys())}")
        if args.github_output:
            with open(args.github_output, "a", encoding="utf-8") as f:
                f.write("changed_pairs=[]\n")
                f.write("any_changed=false\n")
        return 0

    changed_pairs: list[dict] = []
    for variant in VARIANTS:
        fuels_by_country = parsed.get(variant, {})
        if not fuels_by_country:
            print(f"WARNING: no data parsed for variant {variant}")
            continue
        for country in TARGET_COUNTRIES:
            fuels = fuels_by_country.get(country)
            if fuels is None:
                continue
            if update_variant_file(data_dir, country, variant, target_year,
                                   fuels, source_url, era):
                changed_pairs.append({"country": country, "variant": variant})

    print(f"\nChanged (country, variant) pairs: {changed_pairs}")
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as f:
            f.write(f"changed_pairs={json.dumps(changed_pairs)}\n")
            f.write(f"any_changed={'true' if changed_pairs else 'false'}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
