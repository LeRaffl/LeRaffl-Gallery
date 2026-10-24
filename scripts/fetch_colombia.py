#!/usr/bin/env python3
"""
Fetch Colombia new passenger-car registration data from the joint FENALCO/ANDI
monthly "Informe del Sector Automotor" PDF (linked from ANDI's Cámara
Automotriz page) and upsert data/Colombia.csv.

Usage
-----
    python scripts/fetch_colombia.py [--pdf-url URL] [--force] [--dry-run]
                                     [--dump-text] [--debug-dir DIR]
                                     [--no-fenalco-fallback]

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
annual "A DICIEMBRE" one for the same month.

...and then the listing stopped carrying monthlies at all
---------------------------------------------------------
In September 2026 ANDI rewrote that tab into a year-end archive: eight links,
"INFORME FINAL SECTOR AUTOMOTOR 2018…2025", and no monthly file newer than
Dec-2025. The monthly PDFs were not withdrawn — Feb…Aug 2026 still answer 200
at their original /Uploads/ paths — they are just not linked from the page.

So discovery has three legs (`resolve_bulletin`): scrape the listing; if the
newest thing on it is older than the month we came for, look for the month's
PDF embedded in ANDI's own press note (`find_in_andi_news` — the only place
that still links it, and the only way to learn a name with a <ticks> suffix);
then reconstruct the month's /Uploads/ URL from the filename shapes ANDI has
actually used (`monthly_url_candidates`). An unlisted URL is only safe because
of what checks it: it must answer 200 *and* begin with %PDF (one live URL
returns an empty body), and must then parse to a series ending on exactly the
month we asked for, or the run aborts rather than upsert the wrong month.

FENALCO press-text fallback
---------------------------
The September 2026 PDF was never reachable at all: no press note, no
guessable name. FENALCO's post for the month (fenalco.com.co/blog/gremial-4)
keeps its PDF behind a login, but the post *text* is public and states the
month's TOTAL, BEV ("eléctricos") and hybrid ("híbridos") counts — the same
RUNT figures as the boletín (backtested exactly on Jul/Aug 2026).
`fenalco_fallback` uses it only when no PDF for the target month is
reachable: it fills the target month alone, cross-checks the previous month's
post against the CSV first, fails loudly on wording it does not recognise,
and flags the row in `notes` (FENALCO_NOTE). A provisional row does not count
as "already have it" for the early exit, so the daily runs keep looking for
the PDF, and the first bulletin that carries the month overwrites the row.

If no leg reaches the target month: when FENALCO already lists the month the
run fails at once (published, but we cannot get it); otherwise
`require_target_month` exits quietly before the 20th (ANDI publishes over the
first ~3 weeks) and fails the run after it. A fetcher that reports success
while fetching nothing is what hid the 2026 stall for eight months and this
one for three weeks.

Parser
------
Uses `pdftotext -layout` (poppler) to extract the chart-by-chart monthly
series. Each chart's bars are emitted as text lines like
    `ene-25                          966`
and the three series (Pkw total, BEV, Hybrid) appear in order, followed by
a fourth (cargo) that is ignored. The parser groups matches into batches by
detecting (year, month) resets — each batch is one chart — and assigns
Pkw / BEV / Hybrid by position. Numbers use Spanish formatting: `.` is the
thousands separator (`14.558` → 14558).

For a few bars per chart pdftotext puts the value on its own line several
rows *below* the month label (blank lines and chart-title fragments such as
"eléctricos en unidades" or "Variación acumulada : 231,2%" in between). The
old same-line-only regex silently dropped those months — including the
newest one in the Jul-2026 bulletin. `_value_for_label` therefore looks up
to VALUE_LOOKAHEAD_LINES lines down for a number-only line with a number to
the right of the label column, stopping at the next label or a page break.
Column position keeps the YTD totals ("3.178" under "(Ene-jul 2024)", at
column ~11) and the axis ticks out.

Missing values are missing, not zero
------------------------------------
If a value still cannot be located, that month is *unknown* — it never
overwrites a value already in the CSV (a scheduled run once reset two
hand-corrected BEV cells to 0 that way), and a month that is not in the CSV
yet is skipped with a warning instead of being written with BEV=0. The
newest month in the PDF must be complete, otherwise the run fails loud.

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
from urllib.parse import quote, unquote, urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

CAMARA_URL = "https://www.andi.com.co/Home/Camara/4-automotriz"
ANDI_NEWS_URL = "https://www.andi.com.co/Home/Noticias"
FENALCO_INDEX_URL = "https://www.fenalco.com.co/blog/gremial-4"
SOURCE = "andi.com.co + fenalco (datos RUNT)"
CSV_PATH = "data/Colombia.csv"
VARIANT = "Whole"
# Marks a row filled from FENALCO's press text instead of the PDF, and makes it
# provisional (csv_has_final_period). The `source` stays SOURCE — same
# publishers, same RUNT figures — so the chart's "Source:" line does not flip
# for a month or two.
FENALCO_NOTE = "fenalco press text - provisional until the ANDI/FENALCO PDF is reachable"

MONTH_ABBR = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
              "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12}
MONTH_ABBR_BY_NUM = {v: k.upper() for k, v in MONTH_ABBR.items()}
MONTH_FULL_BY_NUM = {
    1: "ENERO", 2: "FEBRERO", 3: "MARZO", 4: "ABRIL", 5: "MAYO", 6: "JUNIO",
    7: "JULIO", 8: "AGOSTO", 9: "SEPTIEMBRE", 10: "OCTUBRE", 11: "NOVIEMBRE", 12: "DICIEMBRE",
}

# ANDI serves every boletín from /Uploads/, and keeps serving it after the page
# stops linking it — see find_unlisted_monthly().
UPLOADS_BASE = "https://www.andi.com.co/Uploads/"

# Day of the month after which a missing boletín stops being "not published
# yet" and becomes a problem worth failing over. ANDI/FENALCO publishes the
# previous month within the first ~3 weeks; the cron polls the 5th–25th.
PUBLICATION_GRACE_DAY = 20

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

# A bar's month label in pdftotext -layout output: "ene-25". Not preceded or
# followed by a letter/digit/hyphen, so "Ene-dic" (YTD labels) and dates don't
# match.
LABEL_RE = re.compile(
    r'(?<![A-Za-z0-9-])(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)-(\d{2})(?![A-Za-z0-9-])',
    re.IGNORECASE,
)
# A bar value: "966" or "14.558" (Spanish thousands separator). Not followed
# by "%" (the "Variación acumulada : 231,2%" line) or more digits/separators.
NUM_RE = re.compile(r'(?<![\d.,])(\d{1,3}(?:\.\d{3})+|\d+)(?![\d.,%])')
# How many lines below an orphan month label to look for its value. In the
# 2026 bulletins the displaced value sits 6 lines down (blank lines in
# between); anything further is the next chart.
VALUE_LOOKAHEAD_LINES = 12
# A line that carries nothing but numbers (a displaced bar value, an axis
# tick, a YTD total) — no letters, no "%", no "(Ene-jul 2026)".
_NUMBER_ONLY_RE = re.compile(r'^[\s\d.]+$')
# The caption under a year-to-date total: "(Ene-dic 2023)", "(Ene-jul 2026)".
# The YTD number sits a few lines above it in the same text box, i.e. at
# (almost) the same column — that alignment is how a YTD total is told apart
# from a displaced bar value when both are to the right of the label.
_YTD_CAPTION_RE = re.compile(r'\(\s*Ene\s*-', re.IGNORECASE)
YTD_CAPTION_LOOKAHEAD_LINES = 8
YTD_CAPTION_COLUMN_TOLERANCE = 8
# A month whose value is more than this many times its larger neighbour is
# not a bar — it is a YTD total or a stray figure the look-ahead grabbed.
# Registrations do not triple month to month in any of the three series.
OUTLIER_FACTOR = 3.0


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


ANY_HREF_RE = re.compile(r'''href\s*=\s*["']([^"']+)["']''', re.IGNORECASE)


def report_listing(text: str) -> None:
    """Print what the Cámara page actually contains, for discovery debugging.

    Deliberately a report and not a raw HTML dump: the page is ~200 KB of
    mostly-irrelevant chrome, and what matters when discovery goes stale is
    (a) every href that mentions a PDF, however it is wrapped, and (b) every
    place the page names a bulletin or a year, so a link that moved behind a
    download handler or a script is still visible in the run log.
    """
    hrefs = ANY_HREF_RE.findall(text)
    pdfish = [h for h in hrefs if ".pdf" in h.lower()]
    automotor = [h for h in pdfish if "AUTOMOTOR" in unquote(html.unescape(h)).upper()]
    print(f"Cámara page: {len(text)} chars, {len(hrefs)} hrefs, "
          f"{len(pdfish)} .pdf, {len(automotor)} naming AUTOMOTOR")
    for h in automotor:
        print(f"    href={h}")
    # Every distinct place the page says AUTOMOTOR, linked or not. A bulletin
    # that moved behind a download handler, a script or a sub-page still shows
    # up here, which is what tells a vanished link apart from an unparsed one.
    hits: list[str] = []
    for m in re.finditer(r"AUTOMOTOR", text, re.IGNORECASE):
        s, e = max(0, m.start() - 200), min(len(text), m.start() + 200)
        snippet = " ".join(text[s:e].split())
        if snippet not in hits:
            hits.append(snippet)
    print(f"  'AUTOMOTOR' contexts ({len(hits)} distinct):")
    for snippet in hits:
        print(f"    …{snippet}…")


def discover_latest_pdf(session: requests.Session, dump_listing: bool = False,
                        debug_dir: str | None = None) -> tuple[str, int, int]:
    """Return (pdf_url, year, month_num) for the freshest 'Informe Sector Automotor' PDF."""
    r = session.get(CAMARA_URL, timeout=30)
    r.raise_for_status()
    if debug_dir:
        d = Path(debug_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / "camara.html").write_text(r.text, encoding="utf-8")
    if dump_listing:
        report_listing(r.text)
    candidates = []
    seen = set()
    rejected: list[str] = []
    for m in HREF_PDF_RE.finditer(r.text):
        href = m.group(1)
        info = classify_pdf_name(_basename(href))
        if info is None:
            rejected.append(_basename(href))
            continue
        year, month, is_monthly = info
        url = urljoin(CAMARA_URL, html.unescape(href))
        if url in seen:
            continue
        seen.add(url)
        candidates.append((year, month, is_monthly, url))
    # A PDF that was on the page but did not classify is the single most
    # useful thing in the log when discovery goes stale — "8 candidates,
    # newest 2025-12" on its own never says whether the new bulletin was
    # missing from the page or merely unrecognised. Print both sides.
    if rejected:
        print(f".pdf links on the page that are not bulletins ({len(rejected)}):")
        for name in rejected:
            print(f"  - {name}")
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


def monthly_url_candidates(year: int, month: int) -> list[str]:
    """/Uploads/ names ANDI has used for one month's boletín, newest shape first."""
    abbr, full = MONTH_ABBR_BY_NUM[month], MONTH_FULL_BY_NUM[month]
    return [UPLOADS_BASE + quote(stem) for stem in (
        # 2026 shape — the one Feb–Aug 2026 are actually served under
        f"{month:02d}. INFORME SECTOR AUTOMOTOR {abbr}{year}_PRENSA.pdf",
        f"{month:02d}. INFORME SECTOR AUTOMOTOR {abbr} {year}_PRENSA.pdf",
        # 2021 shape — full month name
        f"{month:02d}. INFORME SECTOR AUTOMOTOR {full} {year}_PRENSA.pdf",
        f"{month:02d}. INFORME SECTOR AUTOMOTOR {full}{year}_PRENSA.pdf",
        # 2025 shape — "_PRENSA-INDUSTRIA <year>"
        f"{month:02d}. INFORME SECTOR AUTOMOTOR {abbr}_PRENSA-INDUSTRIA {year}.pdf",
    )] + ([UPLOADS_BASE + quote(stem) for stem in (
        # September has two other spellings in Spanish filenames: four-letter
        # SEPT and the "SETIEMBRE" abbreviation SET. Never seen on ANDI yet,
        # but cheap to try — each miss is one 404.
        f"09. INFORME SECTOR AUTOMOTOR SEPT{year}_PRENSA.pdf",
        f"09. INFORME SECTOR AUTOMOTOR SET{year}_PRENSA.pdf",
    )] if month == 9 else [])


# ANDI's press notes: /Home/Noticia/<id>-<slug>, the slug cut at ~40 chars
# ("18083-andi-y-fenalco-en-agosto-de-2026-se-reg"). The note for a month's
# boletín embeds the PDF in an <iframe src="…/Uploads/….pdf">.
NEWS_LINK_RE = re.compile(r'''href\s*=\s*["'](/Home/Noticia/(\d+)-([^"'#?]*))["']''', re.IGNORECASE)
NEWS_SLUG_HINT_RE = re.compile(r"fenalco|automot|vehicul|matricul", re.IGNORECASE)
NEWS_MAX_ARTICLES = 8
EMBEDDED_PDF_RE = re.compile(r'''(?:href|src)\s*=\s*["']([^"']+?\.pdf)(?:[?#][^"']*)?["']''', re.IGNORECASE)


def news_article_links(listing_html: str) -> list[str]:
    """Absolute URLs of press notes whose slug looks like the automotive report, newest id first."""
    seen: dict[int, str] = {}
    for m in NEWS_LINK_RE.finditer(listing_html):
        path, nid, slug = m.group(1), int(m.group(2)), m.group(3)
        if NEWS_SLUG_HINT_RE.search(slug) and nid not in seen:
            seen[nid] = urljoin(ANDI_NEWS_URL, path)
    return [seen[k] for k in sorted(seen, reverse=True)][:NEWS_MAX_ARTICLES]


def bulletin_pdfs_in_article(article_html: str, base_url: str, year: int, month: int) -> list[str]:
    """Bulletin PDF URLs embedded in a press note that classify as exactly (year, month)."""
    found: list[str] = []
    for m in EMBEDDED_PDF_RE.finditer(article_html):
        href = m.group(1)
        info = classify_pdf_name(_basename(href))
        if info and (info[0], info[1]) == (year, month):
            url = urljoin(base_url, html.unescape(href))
            if url not in found:
                found.append(url)
    return found


def find_in_andi_news(session: requests.Session, year: int,
                      month: int) -> tuple[str, bytes] | None:
    """Locate a month's boletín through the ANDI press note that embeds it.

    ANDI announces each boletín in a press note ("ANDI y FENALCO: en agosto de
    2026 se registraron …") with the PDF in an iframe. That is the only place
    the file is still linked since the Cámara page stopped listing monthlies,
    and the only way to learn a name with a per-upload <ticks> suffix
    (Jul-2026, Dec-2025), which no amount of URL guessing can produce.

    Same verification as find_unlisted_monthly: 200 and a body starting with
    %PDF; the caller then requires the series to end on (year, month).
    Network trouble here is reported and skipped — the next leg still runs.
    """
    print(f"Looking for the {year}-{month:02d} boletín in ANDI press notes ({ANDI_NEWS_URL}):")
    try:
        r = session.get(ANDI_NEWS_URL, timeout=30)
        r.raise_for_status()
    except requests.RequestException as exc:
        print(f"  news listing unavailable ({type(exc).__name__}) — skipping this leg")
        return None
    articles = news_article_links(r.text)
    if not articles:
        print("  no automotive-looking press note on the listing")
        return None
    for article in articles:
        try:
            a = session.get(article, timeout=30)
            a.raise_for_status()
        except requests.RequestException as exc:
            print(f"  {type(exc).__name__}: {article}")
            continue
        pdfs = bulletin_pdfs_in_article(a.text, article, year, month)
        if not pdfs:
            print(f"  no {year}-{month:02d} boletín in {article}")
            continue
        for url in pdfs:
            try:
                p = session.get(url, timeout=60)
            except requests.RequestException as exc:
                print(f"  {type(exc).__name__}: {_basename(url)}")
                continue
            if p.status_code == 200 and p.content.startswith(b"%PDF"):
                print(f"  found in {article} ({len(p.content)} bytes): {_basename(url)}")
                return url, p.content
            why = f"HTTP {p.status_code}" if p.status_code != 200 else f"not a PDF ({len(p.content)} bytes)"
            print(f"  embedded but no ({why}): {_basename(url)}")
    return None


def find_unlisted_monthly(session: requests.Session, year: int,
                          month: int) -> tuple[str, bytes] | None:
    """Locate a monthly boletín ANDI still serves but no longer links.

    In September 2026 ANDI rewrote the Cámara page's "BOLETINES DEL SECTOR
    AUTOMOTOR" tab from a list of monthly PDFs into a year-end archive
    (2018–2025). The monthly files were not withdrawn — Feb…Aug 2026 all still
    answer 200 at their original /Uploads/ paths — they are simply unreachable
    from the page (find_in_andi_news covers the press notes that still embed
    them; this covers the rest).

    What makes guessing safe here is the verification, not the guess: a
    candidate counts only if the body really begins with %PDF (one live URL
    answers 200 with an empty body), and the caller additionally requires the
    parsed series to end on the month we asked for. A wrong guess therefore
    fails the run instead of publishing the wrong month's numbers.

    Returns (url, pdf_bytes) for the first candidate that is genuinely that
    PDF. The body comes back with it because verifying a candidate means
    downloading it — re-fetching the same ~1.4 MB afterwards would be waste.
    """
    print(f"Looking for an unlisted {year}-{month:02d} boletín under /Uploads/:")
    for url in monthly_url_candidates(year, month):
        try:
            r = session.get(url, timeout=60)
        except requests.RequestException as exc:
            print(f"  {type(exc).__name__}: {_basename(url)}")
            continue
        if r.status_code == 200 and r.content.startswith(b"%PDF"):
            print(f"  found ({len(r.content)} bytes): {_basename(url)}")
            return url, r.content
        why = f"HTTP {r.status_code}" if r.status_code != 200 else f"not a PDF ({len(r.content)} bytes)"
        print(f"  no ({why}): {_basename(url)}")
    return None


def resolve_bulletin(session: requests.Session, wanted: str, dump_listing: bool = False,
                     debug_dir: str | None = None) -> tuple[str, int, int, bool, bytes | None]:
    """(url, year, month, was_guessed, pdf) for `wanted` (YYYY-MM), else the newest listed one.

    Legs, in order: the Cámara page listing, the PDF embedded in ANDI's press
    note for the month (find_in_andi_news), the reconstructed /Uploads/ names
    (find_unlisted_monthly).

    `was_guessed` marks a URL that did not come from the Cámara listing (press
    note or constructed name); the caller holds those to the stricter check
    that the parsed series must end on exactly `wanted`.
    `pdf` is the already-downloaded body when the search fetched it, else None.
    """
    url, year, month = discover_latest_pdf(session, dump_listing, debug_dir)
    print(f"Latest listed PDF: {year}-{month:02d} -> {url}")
    if f"{year}-{month:02d}" >= wanted:
        return url, year, month, False, None
    wy, wm = int(wanted[:4]), int(wanted[5:])
    for leg in (find_in_andi_news, find_unlisted_monthly):
        alt = leg(session, wy, wm)
        if alt:
            alt_url, pdf = alt
            return alt_url, wy, wm, True, pdf
    return url, year, month, False, None


def require_target_month(wanted: str, got: str, today: date | None = None) -> None:
    """Stop the run when nothing we can reach covers the month we came for.

    Early in the publication window that is ordinary — ANDI/FENALCO publishes
    the previous month over the first ~3 weeks — so the run exits quietly. Once
    the month is overdue it is a real breakage and the run fails, because a
    fetcher that reports success while fetching nothing is how Colombia lost
    eight months in 2026 and another three weeks in September.
    """
    if got >= wanted:
        return
    today = today or date.today()
    msg = (f"No boletín for {wanted} is reachable — the newest one we can get is {got}. "
           f"The Cámara page no longer lists monthly bulletins, no ANDI press note "
           f"embeds it, no known /Uploads/ filename shape for {wanted} answered with "
           f"a PDF, and FENALCO has no post for it either.")
    if today.day < PUBLICATION_GRACE_DAY:
        print(f"{msg}\nIt is only day {today.day} of the month, so this is most likely "
              f"'not published yet'. Nothing to do.")
        raise SystemExit(0)
    print(f"::error title=Colombia boletín for {wanted} not reachable::{msg}")
    raise SystemExit(
        f"{msg}\nIt is day {today.day}; {wanted} is overdue, so this is a breakage, not a wait.\n"
        f"Re-run with dump_listing=true to see what {CAMARA_URL} offers, then either\n"
        f"add the new filename shape to monthly_url_candidates() or pass pdf_url= directly."
    )


# --- FENALCO press-text fallback -------------------------------------------
#
# FENALCO's post for each month ("Informe del Sector Automotor a Septiembre
# 2026") serves the PDF behind /web/login, but its body text is public and
# states the month's three numbers we need. Used only when no PDF for the
# target month is reachable; see fenalco_fallback().

# Post slugs: informe-del-sector-automotor-a-agosto-2026-9088. The motorcycle
# report ("informe-del-sector-motocicletas-…") never matches.
FENALCO_POST_RE = re.compile(
    r'''href\s*=\s*["']((?:https?://[^"'/]*fenalco\.com\.co)?/blog/gremial-4/'''
    r'''informe-del-sector-automotor-a-([a-z]+)(?:-a)?-(\d{4})-(\d+))["']''',
    re.IGNORECASE,
)
# A Spanish count: "33.835", "947".
_ES_INT = r'(\d{1,3}(?:\.\d{3})+|\d+)'
# A sentence ends at a "." that is not a thousands separator.
_SENTENCE_SPLIT_RE = re.compile(r'\.(?!\d)')


def fenalco_post_url(index_html: str, year: int, month: int) -> str | None:
    """The FENALCO post URL for (year, month) on the gremial-4 index, else None."""
    want = MONTH_FULL_BY_NUM[month].lower()
    for m in FENALCO_POST_RE.finditer(index_html):
        name = m.group(2).lower()
        if name == "setiembre":
            name = "septiembre"
        if name == want and int(m.group(3)) == year:
            return urljoin(FENALCO_INDEX_URL, html.unescape(m.group(1)))
    return None


def _html_to_text(fragment: str) -> str:
    no_tags = re.sub(r'<(script|style)\b.*?</\1>', ' ', fragment, flags=re.IGNORECASE | re.DOTALL)
    no_tags = re.sub(r'<[^>]+>', ' ', no_tags)
    return re.sub(r'\s+', ' ', html.unescape(no_tags)).strip()


def _single(values: list[int], what: str, period: str) -> int:
    distinct = sorted(set(values))
    if len(distinct) != 1:
        raise RuntimeError(
            f"FENALCO post for {period}: expected one {what} figure, found {distinct or 'none'} — "
            f"the press-text wording is not recognised. Read the post and adjust "
            f"parse_fenalco_post() before trusting it."
        )
    return distinct[0]


def parse_fenalco_post(page_html: str, year: int, month: int) -> dict:
    """{'TOTAL', 'BEV', 'HEV'} for (year, month) from a FENALCO post page.

    Tight on purpose — every rule below fails the run rather than guess:
      * only the post body (#o_wblog_post_content … #o_wblog_post_footer) is
        read, so teasers of the motorcycle report or other posts never count;
      * the body must name "Informe de Registro de Vehículos a <mes> de <año>";
      * TOTAL comes from "(En|Durante) <mes> [de <año>] se (registraron|
        matricularon) N vehículos nuevos" — the YTD sentence ("Entre enero y
        <mes> …") never matches; every hit must agree;
      * BEV / HEV come from sentences that mention "eléctric…" (resp.
        "híbrid…") but not the other, and end the number with "unidades";
        a combined "eléctricos e híbridos … N unidades" sentence counts for
        neither. Every hit must agree;
      * BEV + HEV must not exceed TOTAL.
    """
    period = f"{year}-{month:02d}"
    start = page_html.find('id="o_wblog_post_content"')
    end = page_html.find('id="o_wblog_post_footer"', start + 1)
    if start < 0 or end < 0:
        raise RuntimeError(f"FENALCO post for {period}: post body markers not found — page layout changed.")
    text = _html_to_text(page_html[start:end])
    mes = MONTH_FULL_BY_NUM[month].lower()
    mes_re = "(?:septiembre|setiembre)" if month == 9 else mes
    if not re.search(rf'Informe de Registro de Veh[íi]culos a {mes_re} de {year}', text, re.IGNORECASE):
        raise RuntimeError(f"FENALCO post for {period}: does not say it reports {mes} {year} — wrong post?")

    totals = [parse_value(m.group(1)) for m in re.finditer(
        rf'(?:En|Durante) {mes_re}(?: de {year})?,? se (?:registraron|matricularon) {_ES_INT} veh[íi]culos nuevos',
        text, re.IGNORECASE)]
    bevs: list[int] = []
    hevs: list[int] = []
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        low = sentence.lower()
        if "motocicleta" in low:
            continue
        has_e, has_h = "eléctric" in low or "electric" in low, "híbrid" in low or "hibrid" in low
        if has_e == has_h:
            continue
        hits = [parse_value(m.group(1)) for m in re.finditer(rf'{_ES_INT}\s+unidades', sentence)]
        (bevs if has_e else hevs).extend(hits)
    total = _single(totals, "TOTAL ('se registraron N vehículos nuevos')", period)
    bev = _single(bevs, "BEV ('eléctricos … N unidades')", period)
    hev = _single(hevs, "hybrid ('híbridos … N unidades')", period)
    if bev + hev > total:
        raise RuntimeError(f"FENALCO post for {period}: BEV+HEV ({bev}+{hev}) exceeds TOTAL ({total}).")
    return {"TOTAL": total, "BEV": bev, "HEV": hev}


def fenalco_row(period: str, values: dict) -> dict:
    return {
        "period": period, "time_interval": "monthly", "variant": VARIANT, "source": SOURCE,
        "BEV": values["BEV"], "PHEV": "", "HEV": values["HEV"],
        "PETROL": "", "DIESEL": "", "FLEXFUEL": "", "OTHERS": "",
        "TOTAL": values["TOTAL"], "ICE": None, "notes": FENALCO_NOTE,
    }


def _previous_period(period: str) -> tuple[int, int]:
    y, m = int(period[:4]), int(period[5:])
    return (y - 1, 12) if m == 1 else (y, m - 1)


# How far the previous month's press-text figures may sit from the CSV before
# we stop trusting the text as a stand-in for the PDF. Same release, same
# RUNT extract — Jul/Aug 2026 match to the unit; a revision in a later
# bulletin moves a count by a handful, a scope change by far more.
FENALCO_CROSSCHECK_TOLERANCE = 0.01


def crosscheck_previous_month(prev: str, parsed: dict, csv_row: dict | None) -> None:
    """Fail unless FENALCO's text for `prev` matches what the CSV has for it."""
    if csv_row is None:
        raise RuntimeError(
            f"Cannot cross-check FENALCO's press text: the CSV has no {prev} row. "
            f"Fill {prev} from a bulletin first (pdf_url=…) — the fallback only ever fills one month.")
    for col in ("TOTAL", "BEV", "HEV"):
        have = _num(csv_row.get(col))
        got = float(parsed[col])
        if have is None:
            raise RuntimeError(f"Cannot cross-check FENALCO's press text: CSV {prev} has no {col}.")
        diff = abs(got - have) / have if have else float(got != have)
        if diff > FENALCO_CROSSCHECK_TOLERANCE:
            raise RuntimeError(
                f"FENALCO press text for {prev} says {col}={got:.0f}, the CSV (from the boletín) has "
                f"{have:.0f} — the text no longer measures what the PDF does. Not using it.")
        if got != have:
            print(f"  note: {prev} {col} press text {got:.0f} vs CSV {have:.0f} (within tolerance)")
    print(f"  cross-check {prev}: press text matches the CSV (TOTAL/BEV/HEV)")


def fenalco_fallback(session: requests.Session, wanted: str, csv_path: str,
                     write: bool) -> bool:
    """Fill `wanted` from FENALCO's public press text. Returns True if handled.

    False means FENALCO does not list the month (or cannot be reached) — the
    caller then applies the usual "not published yet / overdue" rule. When
    FENALCO *does* list the month, every problem from here on is a failure:
    the month is out, and we cannot get it.
    """
    y, m = int(wanted[:4]), int(wanted[5:])
    print(f"No PDF for {wanted} reachable — trying FENALCO's press text ({FENALCO_INDEX_URL}):")
    try:
        r = session.get(FENALCO_INDEX_URL, timeout=30)
        r.raise_for_status()
    except requests.RequestException as exc:
        print(f"  ::warning title=FENALCO index unreachable::{type(exc).__name__} — no fallback this run")
        return False
    post = fenalco_post_url(r.text, y, m)
    if post is None:
        print(f"  FENALCO has no post for {wanted} yet")
        return False
    print(f"  FENALCO lists {wanted}: {post}")
    try:
        values = parse_fenalco_post(session.get(post, timeout=30).text, y, m)
        print(f"  {wanted} press text: TOTAL={values['TOTAL']} BEV={values['BEV']} HEV={values['HEV']}")
        py, pm = _previous_period(wanted)
        prev = f"{py}-{pm:02d}"
        prev_post = fenalco_post_url(r.text, py, pm)
        if prev_post is None:
            raise RuntimeError(f"FENALCO index has no post for {prev}, so the press text cannot be cross-checked.")
        existing = read_csv(csv_path)
        crosscheck_previous_month(prev, parse_fenalco_post(session.get(prev_post, timeout=30).text, py, pm),
                                  existing.get((prev, VARIANT)))
        old = existing.get((wanted, VARIANT))
        if old is not None and FENALCO_NOTE not in (old.get("notes") or ""):
            print(f"  CSV already has {wanted} from a boletín — press text not applied.")
            return True
    except (RuntimeError, requests.RequestException) as exc:
        print(f"::error title=Colombia {wanted} published but not ingestible::{exc}")
        raise SystemExit(
            f"FENALCO lists {wanted} ({post}) but neither a PDF nor its press text could be used:\n  {exc}")
    added, updated, skipped = upsert_csv(csv_path, {(wanted, VARIANT): fenalco_row(wanted, values)}, write=write)
    print(f"::warning title=Colombia {wanted} from FENALCO press text::No PDF reachable; {wanted} "
          f"filled from {post} and flagged in notes. The first bulletin carrying {wanted} overwrites it.")
    print(f"{added} added, {updated} updated, {skipped} skipped -> {csv_path}"
          + ("" if write else " (dry run, nothing written)"))
    return True


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


def _numbers_right_of(line: str, col: int) -> list[tuple[int, int]]:
    """(column, value) of bar values on `line` that start right of column `col`, left to right."""
    return [(m.start(), parse_value(m.group(1))) for m in NUM_RE.finditer(line) if m.start() > col]


def _is_ytd_total(lines: list[str], j: int, col: int) -> bool:
    """True if the number at lines[j][col] has an aligned "(Ene-…)" caption below it."""
    for k in range(j + 1, min(j + 1 + YTD_CAPTION_LOOKAHEAD_LINES, len(lines))):
        m = _YTD_CAPTION_RE.search(lines[k])
        if m and abs(m.start() - col) <= YTD_CAPTION_COLUMN_TOLERANCE:
            return True
    return False


def _value_for_label(lines: list[str], i: int, label_col: int, label_end: int) -> int | None:
    """The bar value belonging to the month label at lines[i][label_col:label_end].

    Normally it is the first number to the right of the label on the same
    line. For a few bars per chart pdftotext puts the value on its own line
    several rows further down (blank lines and stray chart-title fragments in
    between), so fall back to the first number-only line below that carries a
    number right of the label column. Stop at the next month label or a form
    feed (page break = next chart).

    Two distractors live in that window. Axis ticks only occur at the top of
    a chart, after the form feed, so the stop rule handles them. Year-to-date
    totals ("186.222" with "(Ene-dic 2023)" a few lines under it) sit left of
    the labels in the 2026 layout but *right* of them in the 2025 layout, on
    the line straight after an orphan label — they are recognised by the
    caption aligned under them and skipped.
    """
    same_line = _numbers_right_of(lines[i], label_end)
    if same_line:
        return same_line[0][1]
    for j in range(i + 1, min(i + 1 + VALUE_LOOKAHEAD_LINES, len(lines))):
        nxt = lines[j]
        if "\f" in nxt or LABEL_RE.search(nxt):
            return None
        if not nxt.strip() or not _NUMBER_ONLY_RE.match(nxt):
            continue
        for col, val in _numbers_right_of(nxt, label_col):
            if not _is_ytd_total(lines, j, col):
                return val
    return None


def _drop_outliers(batch: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    """Remove months whose value dwarfs both neighbours (a YTD total read as a bar).

    Belt and braces for the caption rule above: whatever the layout does
    next, a monthly count that is more than OUTLIER_FACTOR times the larger
    of its neighbours is not a monthly count. The month becomes unknown.
    """
    if len(batch) < 3:
        return batch
    kept = []
    for idx, (y, m, v) in enumerate(batch):
        neighbours = [batch[k][2] for k in (idx - 1, idx + 1) if 0 <= k < len(batch)]
        if v > OUTLIER_FACTOR * max(neighbours):
            print(f"  WARNING {y}-{m:02d}: {v} is >{OUTLIER_FACTOR:g}x its neighbours {neighbours} — "
                  f"not a monthly bar, treated as unknown")
            continue
        kept.append((y, m, v))
    return kept


def extract_series(text: str) -> list[list[tuple[int, int, int]]]:
    """Group (year, month, value) matches into batches by (year, month) reset.

    Each PDF chart emits its bars in chronological order; a new chart starts
    when the month-year decreases. Returns a list of batches in PDF order.
    Month labels whose value cannot be located are reported and left out —
    downstream they count as unknown, never as 0.
    """
    lines = text.split("\n")
    matches = []
    orphans = []
    for i, line in enumerate(lines):
        for lm in LABEL_RE.finditer(line):
            year = 2000 + int(lm.group(2))
            month = MONTH_ABBR[lm.group(1).lower()]
            val = _value_for_label(lines, i, lm.start(), lm.end())
            if val is None:
                orphans.append(f"{year}-{month:02d} (line {i + 1})")
                continue
            matches.append((year, month, val))
    if orphans:
        print(f"  WARNING no value found for month label(s): {', '.join(orphans)}")

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
    return [_drop_outliers(b) for b in batches]


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


def csv_has_final_period(csv_path: str, period: str) -> bool:
    """True if `period` is in the CSV from a boletín, not just from FENALCO's press text."""
    row = read_csv(csv_path).get((period, VARIANT))
    return row is not None and FENALCO_NOTE not in (row.get("notes") or "")


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
    ap.add_argument("--dump-listing", action="store_true",
                    help="Report what the Cámara Automotriz page contains (PDF hrefs, bulletin/year "
                         "mentions) — for discovery work in CI logs. The full HTML goes to --debug-dir.")
    ap.add_argument("--debug-dir", default=None,
                    help="Save the downloaded PDF and its pdftotext output into this directory.")
    ap.add_argument("--no-fenalco-fallback", action="store_true",
                    help="Do not fall back to FENALCO's press text when no PDF for the month is reachable.")
    args = ap.parse_args()

    # A month filled from FENALCO's press text is provisional: keep looking
    # for the boletín until one carries it.
    if not args.pdf_url and not args.force and not args.dry_run \
            and csv_has_final_period(CSV_PATH, previous_month_period()):
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

    wanted = previous_month_period()
    guessed_url, pdf = False, None
    if args.pdf_url:
        # Manual override: the operator chose this file, so neither the
        # unlisted-URL search nor the target-month rule applies to it.
        url, year, n = args.pdf_url, None, None
        info = classify_pdf_name(_basename(url))
        if info:
            year, n = info[0], info[1]
        print(f"PDF (override): {year}-{n:02d} -> {url}" if year else f"PDF (override): {url}")
    else:
        url, year, n, guessed_url, pdf = resolve_bulletin(
            session, wanted, args.dump_listing, args.debug_dir)
        print(f"Using: {year}-{n:02d} -> {url}")
        if f"{year}-{n:02d}" < wanted and not args.no_fenalco_fallback \
                and fenalco_fallback(session, wanted, CSV_PATH, write=not args.dry_run):
            return
        require_target_month(wanted, f"{year}-{n:02d}")

    if pdf is None:  # not already fetched by the unlisted-URL search
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
        mismatch = (f"newest month in the PDF text is {parsed_periods[-1]}, "
                    f"but the filename says {year}-{n:02d}")
        if guessed_url:
            # This URL was constructed or found outside the Cámara listing,
            # so the filename is our assumption rather than ANDI's statement. If the contents disagree
            # with it, we guessed wrong — publishing the wrong month's numbers
            # under the right label would be far worse than fetching nothing.
            print(f"::error title=Colombia unlisted URL is not the month we asked for::{mismatch}")
            raise SystemExit(
                f"Unlisted URL (press note or constructed) {url}\n  {mismatch}.\n"
                f"Refusing to upsert: the filename no longer identifies the month."
            )
        print(f"  WARNING {mismatch}")

    added, updated, skipped = upsert_csv(CSV_PATH, rows, write=not args.dry_run)
    verb = "would be" if args.dry_run else ""
    print(f"{added} added, {updated} updated, {skipped} skipped {verb} -> {CSV_PATH}"
          + (" (dry run, nothing written)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
