#!/usr/bin/env python3
"""
Fetch ACEA's quarterly-cumulative Commercial Vehicle press release PDFs and
reconstruct genuine Q1/Q2/Q3/Q4 rows (falling back to a single yearly row
only when no clean quarterly baseline exists yet) into
data/<Country>_<Variant>.csv for the ACEA multi-country roster — a
maintainer-curated 21-country list, not simply scripts/fetch_acea.py's
passenger-car roster (see TARGET_COUNTRIES for exactly why each country
is, or isn't, in scope).

Usage
-----
    python scripts/fetch_acea_cv.py [--checkpoint {Q1,H1,Q1-Q3,FY}] \
        [--year YEAR] [--pdf-url URL_OR_PATH] [--data-dir data] [--force] \
        [--github-output PATH]

* --checkpoint      Which ACEA checkpoint release to fetch. Default: inferred
                     from today's date (see default_checkpoint_and_year()) —
                     Jan-Mar -> FY of last year, Apr-Jun -> Q1, Jul-Sep -> H1,
                     Oct-Dec -> Q1-Q3. This is what fetch-acea-cv.yml relies
                     on for its four quarterly cron windows.
* --year            Calendar year the checkpoint belongs to (default:
                     inferred alongside --checkpoint).
* --pdf-url         Direct URL/path to the checkpoint's PDF. If omitted, a
                     handful of candidate URLs are tried in turn (ACEA has
                     renamed this release's filename pattern more than once;
                     see "URL patterns" below).
* --data-dir        Folder containing data/<Country>_<Variant>.csv.
* --force           Skip the "already have this checkpoint" self-throttle.
* --github-output    Optional path; when set, the list of changed
                     (country, variant) pairs is emitted as
                     `changed_pairs=<json-array-of-objects>` (used by
                     fetch-acea-cv.yml's render matrix).

Invoked by .github/workflows/fetch-acea-cv.yml on four cron windows a year,
one per checkpoint (mid-to-late Jan/Apr/Jul-Aug/Oct — ACEA's observed
publication cadence). Each run self-throttles via a sentinel file (see
already_have_checkpoint()), so once a checkpoint has landed the cheapest
path on later days in that window is "already have it, no HTTP".

Reconstructing quarters from cumulative checkpoints
----------------------------------------------------
Since ~2024 ACEA no longer publishes a genuinely monthly commercial-vehicle
release. Instead it publishes four **cumulative year-to-date** snapshots per
year: Q1 (Jan-Mar, ~April), H1 (Jan-Jun, ~July/August), Q1-Q3 (Jan-Sep,
~October) and the full year (Jan-Dec, ~January of the following year). A
"Q1-Q3 2024" table is Jan-Sep 2024 *cumulative* — not Q3 alone — so writing
each release's total straight into a CSV row would double- (or triple-, or
quadruple-) count registrations against neighbouring releases and corrupt
every trailing-window computation downstream (TTM shares, the S-curve fit,
weights.csv).

Instead this fetcher reconstructs genuine per-quarter deltas: Q1 always
stands alone (nothing precedes it in the year); Q2 = H1 − Q1;
Q3 = Q1-Q3 − H1; Q4 = FY − Q1-Q3. The subtraction baseline for each is
simply the sum of whichever quarters are **already recorded** in the target
CSV for that year — the CSV itself is the durable state that bridges across
separate workflow runs, so no extra state file is needed (see
handle_checkpoint() / existing_quarter_rows()). `time_interval` is written
as `quarterly` (`period` = the middle month of the quarter — Q1->02, Q2->05,
Q3->08, Q4->11 — matching docs/architecture/09-glossary.md § Time / period).

When the necessary baseline isn't on record yet (a brand-new country/variant,
or a checkpoint was missed and the gap hasn't been backfilled), this never
fabricates a multi-quarter blob under a single-quarter label. The one
exception is a **full-year** checkpoint arriving with **no** quarters
recorded at all for that year: that falls back to a single `yearly` row
using the full-year total directly (period = `YYYY-07`) — the same
degraded-but-honest granularity the pre-2024 "old era" always uses, since it
never had a quarterly-checkpoint format to begin with. Every other
insufficient-baseline case is skipped with a clear log message and resolves
on its own once the gap closes (an earlier checkpoint gets backfilled, or
the year's FY release arrives).

Each release also carries a prior-year-same-checkpoint column (e.g. the H1
2026 release also gives H1 2025); this fetcher runs the identical
reconstruction logic on that column too, which is how a Q1 release quietly
refreshes/corrects last year's Q1 as a side effect, and how a country's
first-ever processed year can pick up a bonus second year for free (see the
one-off 2021+2022 backfill in docs/architecture/38-source-acea-cv.md § 5).

Known limitation: revisions don't cascade forward. If Q2 is revised (its
CSV row updated after Q3/Q4 were already computed from the *old* Q2), Q3
and Q4 are not automatically recomputed — they'd need the checkpoint that
originally produced them re-run. In steady-state cron operation checkpoints
only ever move forward in time, so this only bites if an old checkpoint's
PDF is manually re-fetched after later ones already landed for the same
year. Acceptable tradeoff for not needing a full-year replay on every run;
flagged here rather than silently accepted.

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
date-prefixed name through ~2023, then a hyphen before the period tag for H1
but an underscore for Q1-Q3 in the 2024+ releases — confirmed against real
samples of both). There is no confirmed sample of the new-era filename for
Q1 or the full-year checkpoint in this codebase yet —
CANDIDATE_URL_TEMPLATES_BY_CHECKPOINT lists the most plausible guesses per
checkpoint, tried in order. When each checkpoint's live fetch first runs
(from a network egress that can actually reach acea.auto — this repo's
sandbox cannot, see the module's git history for confirmation), expect to
need one `--pdf-url` correction the first time; that is normal bring-up, not
a bug.

Per-country write rule
-----------------------
Every target country is "conditional" (unlike fetch_acea.py's always/
conditional split for passenger cars): a (country, variant, period) row is
only written if no row exists yet for that period, or the existing row's
source is exactly "ACEA" (case-insensitive). This is what lets Poland (the
one in-scope country with its own national HDV/Vans/Buses source, PZPM)
stay in TARGET_COUNTRIES safely — ACEA can never clobber its rows — without
needing a separate exclusion list. See is_acea_source().
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

# NOT simply scripts/fetch_acea.py's 19-country passenger-car roster —
# maintainer-curated per the commercial-vehicle picture specifically
# (2026-09 decision):
#   + Germany, France, Sweden: excluded from fetch_acea.py because they
#     have their own national *passenger-car* ("Whole") source, but they
#     have NO national Vans/HDV/Buses source at all, so ACEA is the only
#     option for those variants here.
#   - Austria, Denmark, Finland, Netherlands, Spain: never in scope — each
#     already has its own national Vans/HDV/Buses fetcher (see
#     02-components.md § 2.7), so ACEA would only ever be redundant.
#   - Luxembourg: deliberately excluded even though it has no Buses source
#     of its own (STATEC covers Whole/Vans/HDV only) — maintainer chose to
#     leave that one gap unfilled rather than mix an ACEA-sourced Buses
#     variant into an otherwise all-STATEC file set.
# Poland stays in scope as a conditional case: PZPM (STATEC-equivalent)
# owns its Vans/HDV/Buses rows, and the per-file conditional-write rule
# below (not a separate exclusion list) is what keeps ACEA from ever
# overwriting them.
TARGET_COUNTRIES = [
    "Belgium", "Bulgaria", "Croatia", "Cyprus", "Czechia", "Estonia",
    "France", "Germany", "Greece", "Hungary", "Iceland", "Latvia",
    "Lithuania", "Malta", "Norway", "Poland", "Romania",
    "Slovakia", "Slovenia", "Sweden", "Switzerland",
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

# Candidate filename patterns per checkpoint, tried in order until one
# returns HTTP 200. See "URL patterns" in the module docstring. Confirmed
# against real samples: H1 uses a HYPHEN before the period tag, Q1-Q3 an
# UNDERSCORE — ACEA is not consistent about this, hence trying both on
# every checkpoint rather than trusting either pattern alone.
CANDIDATE_URL_TEMPLATES_BY_CHECKPOINT = {
    "Q1": [
        "https://www.acea.auto/files/Press_release_commercial_vehicle_registrations-Q1_{year}.pdf",
        "https://www.acea.auto/files/Press_release_commercial_vehicle_registrations_Q1_{year}.pdf",
    ],
    "H1": [
        "https://www.acea.auto/files/Press_release_commercial_vehicle_registrations-H1_{year}.pdf",  # confirmed
        "https://www.acea.auto/files/Press_release_commercial_vehicle_registrations_H1_{year}.pdf",
    ],
    "Q1-Q3": [
        "https://www.acea.auto/files/Press_release_commercial_vehicle_registrations_Q1-Q3_{year}.pdf",  # confirmed
        "https://www.acea.auto/files/Press_release_commercial_vehicle_registrations-Q1-Q3_{year}.pdf",
    ],
    "FY": [
        "https://www.acea.auto/files/Press_release_commercial_vehicle_registrations_{year}.pdf",
        "https://www.acea.auto/files/Press_release_commercial_vehicle_registrations-{year}.pdf",
        "https://www.acea.auto/files/Press_release_commercial_vehicle_registrations_FY_{year}.pdf",
        "https://www.acea.auto/files/Press_release_commercial_vehicle_registrations-FY_{year}.pdf",
    ],
}

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
        if not resp.content.startswith(b"%PDF-"):
            # A wrong-but-plausible URL guess can still come back HTTP 200
            # (observed against acea.auto: a non-existent /files/ path
            # renders a normal HTML page, not a 404) — treat "200 but not a
            # PDF" the same as "not found" so the candidate-template loop in
            # fetch_checkpoint_pdf() falls through to the next guess instead
            # of crashing later inside pdfplumber. Also observed on a
            # confirmed-correct URL (a WAF soft-challenge page served with
            # 200 instead of a hard 403) — the content-type/snippet here is
            # what tells the two cases apart when debugging.
            content_type = resp.headers.get("content-type", "n/a")
            snippet = resp.content[:200].decode("utf-8", errors="replace")
            raise FileNotFoundError(
                f"{url_or_path} returned HTTP 200 but the content isn't a "
                f"PDF (no %PDF- header) — either a wrong URL guess or a WAF "
                f"soft-challenge page. content-type={content_type!r} "
                f"body-snippet={snippet!r}"
            )
        return resp.content
    path = url_or_path.replace("file://", "")
    with open(path, "rb") as f:
        return f.read()


def fetch_checkpoint_pdf(checkpoint: str, year: int, pdf_url: str | None) -> tuple[bytes, str]:
    """Returns (pdf_bytes, source_url_used). Tries --pdf-url verbatim if
    given, otherwise walks CANDIDATE_URL_TEMPLATES_BY_CHECKPOINT[checkpoint]
    until one succeeds."""
    if pdf_url:
        return load_pdf_bytes(pdf_url), pdf_url
    templates = CANDIDATE_URL_TEMPLATES_BY_CHECKPOINT[checkpoint]
    for tmpl in templates:
        url = tmpl.format(year=year)
        try:
            return load_pdf_bytes(url), url
        except FileNotFoundError:
            continue
    raise FileNotFoundError(
        f"None of the candidate URLs for {checkpoint} {year} were found: "
        f"{[t.format(year=year) for t in templates]}. Pass --pdf-url explicitly."
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


# --- Checkpoint / quarter-delta reconstruction -----------------------
#
# ACEA publishes four **cumulative year-to-date** snapshots per year — Q1
# (Jan-Mar, ~April), H1 (Jan-Jun, ~July/August), Q1-Q3 (Jan-Sep, ~October)
# and the full year (Jan-Dec, ~January of the following year). None of
# these except Q1 is a standalone period on its own, so writing a
# checkpoint's total straight into a CSV row would massively overstate
# that "period" and corrupt every trailing-window computation downstream.
#
# Instead we reconstruct genuine quarters: Q1 always stands alone (nothing
# precedes it in the year); Q2 = H1 - Q1; Q3 = Q1-Q3 - H1; Q4 = FY - Q1-Q3.
# The "baseline" for each subtraction is simply the sum of whichever
# quarters are *already recorded* in the CSV for that year — no separate
# state file needed, the CSV itself is the durable record. When the
# necessary baseline isn't there yet (a fresh country/variant, or a missed
# checkpoint), we never fabricate a multi-quarter blob:
#   * a full-year (FY) checkpoint with NO quarters recorded yet falls back
#     to a single `yearly` row using the full-year total directly (this is
#     also the only path the pre-2024 "old era" ever takes, since it never
#     had a quarterly-checkpoint format to begin with);
#   * anything else with a missing earlier quarter is skipped with a clear
#     log message and picked up once the gap is closed.
QUARTER_MONTH = {1: "02", 2: "05", 3: "08", 4: "11"}  # 09-glossary.md § Time/period
CHECKPOINT_QUARTERS = {"Q1": 1, "H1": 2, "Q1-Q3": 3, "FY": 4}


def quarter_period(year: int, q: int) -> str:
    return f"{year}-{QUARTER_MONTH[q]}"


def yearly_period(year: int) -> str:
    return f"{year}-07"


def parse_checkpoint_label(label: str | None) -> tuple[str, int, int] | None:
    """('Q1'|'H1'|'Q1-Q3'|'FY', year, n_quarters), or None if unrecognised.
    A bare 4-digit year (old-era releases; a hypothetical new-era full-year
    release) is treated as 'FY'."""
    if not label:
        return None
    label = label.strip().upper()
    m = re.fullmatch(r"(Q1-Q3|H1|Q1)\s+(\d{4})", label)
    if m:
        name = m.group(1)
        return name, int(m.group(2)), CHECKPOINT_QUARTERS[name]
    m = re.fullmatch(r"(\d{4})", label)
    if m:
        return "FY", int(m.group(1)), 4
    return None


def existing_quarter_rows(by_period: dict[str, dict], year: int) -> dict[int, dict]:
    """{quarter_number: row} for genuinely *quarterly* rows of `year`,
    regardless of source (a real registration count is a real registration
    count no matter who published it — used only as a subtraction baseline;
    write permission is a separate check, see should_write)."""
    out: dict[int, dict] = {}
    for q, mm in QUARTER_MONTH.items():
        row = by_period.get(f"{year}-{mm}")
        if row and (row.get("time_interval") or "") == "quarterly":
            out[q] = row
    return out


def sum_fuel_values(rows: list[dict], fields: list[str]) -> dict[str, float]:
    numeric_fields = [f for f in fields
                      if f not in ("period", "time_interval", "variant", "source", "notes")]
    totals = {f: 0.0 for f in numeric_fields}
    for r in rows:
        for f in numeric_fields:
            v = r.get(f)
            if v not in (None, ""):
                totals[f] += float(v)
    return totals


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


def _build_row(period: str, time_interval: str, fields: list[str],
               fuel_values: dict[str, float], source_url: str, era: str) -> dict:
    row: dict[str, str | float] = {f: "" for f in fields}
    row["period"] = period
    row["time_interval"] = time_interval
    row["source"] = ACEA_SOURCE
    row["notes"] = source_url if era == "new" else (
        f"{source_url} (pre-fuel-split ACEA CV release: TOTAL only)"
    )
    for fuel, val in fuel_values.items():
        if fuel in fields:
            row[fuel] = val
    return row


def handle_checkpoint(data_dir: Path, country: str, variant: str, year: int,
                      n_quarters: int, fuels: dict[str, float],
                      source_url: str, era: str) -> bool:
    """One (country, variant, year) slice of one checkpoint release —
    `fuels` is the CUMULATIVE total from Jan 1 through the end of quarter
    `n_quarters`. Reconstructs a genuine quarterly delta when the
    preceding quarters are already on record, falls back to a yearly row
    when nothing is on record at all for a full-year checkpoint, and
    otherwise skips without writing (see module docstring)."""
    path = data_dir / f"{country}_{variant}.csv"
    fields, rows = load_csv(path)
    original_order = [r["period"] for r in rows]
    by_period = {r["period"]: r for r in rows}
    have = existing_quarter_rows(by_period, year)
    changed = False

    if n_quarters == 1 or all(q in have for q in range(1, n_quarters)):
        target_q = n_quarters
        baseline = sum_fuel_values([have[q] for q in range(1, n_quarters)], fields)
        delta = {f: fuels.get(f, 0.0) - baseline.get(f, 0.0) for f in fuels}
        period = quarter_period(year, target_q)
        existing = by_period.get(period)
        if delta.get("TOTAL", 0.0) < -0.5:
            print(f"    {country} {variant} Q{target_q} {year}: SKIPPED — "
                  f"computed negative TOTAL delta ({delta.get('TOTAL')}); baseline "
                  f"quarters may be wrong, needs manual review")
        elif should_write(existing):
            new_row = _build_row(period, "quarterly", fields, delta, source_url, era)
            new_row["variant"] = variant
            if not row_equals(existing, new_row, fields):
                by_period[period] = new_row
                print(f"    {country} {variant} Q{target_q} {year}: "
                      f"{'added' if existing is None else 'revised'}")
                changed = True
        else:
            print(f"    {country} {variant} Q{target_q} {year}: skipped "
                  f"(existing source={existing.get('source')!r})")
    elif n_quarters == 4 and not have:
        period = yearly_period(year)
        existing = by_period.get(period)
        if should_write(existing):
            new_row = _build_row(period, "yearly", fields, fuels, source_url, era)
            new_row["variant"] = variant
            if not row_equals(existing, new_row, fields):
                by_period[period] = new_row
                print(f"    {country} {variant} {year}: "
                      f"{'added' if existing is None else 'revised'} "
                      f"(yearly fallback, no quarterly baseline)")
                changed = True
        else:
            print(f"    {country} {variant} {year}: yearly-fallback skipped "
                  f"(existing source={existing.get('source')!r})")
    else:
        missing = [q for q in range(1, n_quarters) if q not in have]
        print(f"    {country} {variant} {year}: SKIPPED — checkpoint covers "
              f"{n_quarters} quarter(s) but quarter(s) {missing} aren't recorded "
              f"yet (a missed earlier checkpoint); cannot isolate a clean delta. "
              f"Resolves once the gap is backfilled or the FY release arrives.")

    if changed:
        write_csv(path, fields, list(by_period.values()), original_order=original_order)
    return changed


def already_have_checkpoint(data_dir: Path, year: int, n_quarters: int) -> bool:
    """Cheap self-throttle sentinel: Belgium is present in every observed
    ACEA CV release (unlike Malta, whose data ACEA sometimes omits
    entirely), so it's a safe stand-in for "has this checkpoint landed
    already" without scanning all 19 countries x 3 variants."""
    sentinel = data_dir / f"{TARGET_COUNTRIES[0]}_HDV.csv"
    _, rows = load_csv(sentinel)
    by_period = {r["period"]: r for r in rows}
    have = existing_quarter_rows(by_period, year)
    if n_quarters in have and is_acea_source(have[n_quarters].get("source")):
        return True
    yearly_row = by_period.get(yearly_period(year))
    return bool(yearly_row and is_acea_source(yearly_row.get("source")))


# --- Main ------------------------------------------------------------

def default_checkpoint_and_year(today) -> tuple[str, int]:
    """Which checkpoint is most likely to have just been published, given
    today's date, and the calendar year its window belongs to. Matches
    ACEA's observed publication cadence (see module docstring)."""
    if today.month <= 3:
        return "FY", today.year - 1
    if today.month <= 6:
        return "Q1", today.year
    if today.month <= 9:
        return "H1", today.year
    return "Q1-Q3", today.year


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--checkpoint", choices=sorted(CHECKPOINT_QUARTERS),
                        help="Which checkpoint release to fetch (default: inferred from "
                             "today's date — see default_checkpoint_and_year())")
    parser.add_argument("--year", type=int,
                        help="Calendar year the checkpoint belongs to (default: inferred "
                             "alongside --checkpoint)")
    parser.add_argument("--pdf-url", help="Direct URL/path to the ACEA commercial-vehicle PDF")
    parser.add_argument("--source-note-url",
                        help="URL recorded in the CSV notes column, if different from "
                             "--pdf-url (e.g. --pdf-url is a local file:// backfill copy "
                             "but the row should cite the real acea.auto URL it came from)")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    args = parser.parse_args()

    from datetime import date
    default_checkpoint, default_year = default_checkpoint_and_year(date.today())
    checkpoint = args.checkpoint or default_checkpoint
    if args.year is not None:
        target_year = args.year
    elif args.checkpoint is None:
        target_year = default_year  # fully auto-detected
    else:
        # An explicit --checkpoint was given without --year: pick the
        # sensible year for THAT checkpoint (not necessarily today's
        # auto-detected one), same FY-is-last-year / else-this-year rule.
        target_year = date.today().year - 1 if checkpoint == "FY" else date.today().year
    n_quarters = CHECKPOINT_QUARTERS[checkpoint]
    data_dir = Path(args.data_dir)
    print(f"Target checkpoint: {checkpoint} {target_year} ({n_quarters} quarter(s) cumulative)")

    if not args.force and already_have_checkpoint(data_dir, target_year, n_quarters):
        print(f"Sentinel file already has {checkpoint} {target_year} from ACEA — nothing to do.")
        return 0

    try:
        pdf_bytes, source_url = fetch_checkpoint_pdf(checkpoint, target_year, args.pdf_url)
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
    parsed_checkpoint = parse_checkpoint_label(period_label)
    if parsed_checkpoint is None:
        sys.exit(f"Could not determine the checkpoint/year from the PDF's own period "
                 f"label {period_label!r} — refusing to write unverified data.")
    pdf_checkpoint, pdf_year, pdf_n_quarters = parsed_checkpoint
    if era == "old" and pdf_checkpoint != "FY":
        sys.exit(f"Old-era releases only ever carry a full year — got {period_label!r}.")
    if (pdf_checkpoint, pdf_year) != (checkpoint, target_year):
        sys.exit(f"PDF reports {pdf_checkpoint} {pdf_year} but target was "
                 f"{checkpoint} {target_year} — refusing to write mismatched data. "
                 f"Pass --checkpoint/--year explicitly if the auto-detected target was wrong.")

    changed_pairs: list[dict] = []
    for variant in VARIANTS:
        fuels_by_country = parsed.get(variant, {})
        if not fuels_by_country:
            print(f"WARNING: no data parsed for variant {variant}")
            continue
        for country in TARGET_COUNTRIES:
            country_fuels = fuels_by_country.get(country)
            if country_fuels is None:
                continue
            for year, idx in ((target_year, 0), (target_year - 1, 1)):
                fuels = {f: float(vals[idx]) for f, vals in country_fuels.items()}
                if handle_checkpoint(data_dir, country, variant, year,
                                     pdf_n_quarters, fuels, source_url, era):
                    changed_pairs.append({"country": country, "variant": variant})

    # A (country, variant) can appear twice (current + prior year both
    # changed something) — the render matrix only needs it once.
    changed_pairs = [dict(p) for p in {tuple(sorted(p.items())) for p in changed_pairs}]

    print(f"\nChanged (country, variant) pairs: {changed_pairs}")
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as f:
            f.write(f"changed_pairs={json.dumps(changed_pairs)}\n")
            f.write(f"any_changed={'true' if changed_pairs else 'false'}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
