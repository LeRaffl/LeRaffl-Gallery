#!/usr/bin/env python3
"""
Fetch Greek new passenger-car registrations from SEAA (Σύνδεσμος Εισαγωγέων
Αντιπροσώπων Αυτοκινήτων — the importers' association) and upsert
data/Greece.csv (variant Whole).

Source
------
SEAA processes ELSTAT's primary registration data every month and publishes,
free and without login, on its WordPress site (seaa.gr/registrations/,
seaa.gr/passenger-car-registrations-comparisons/, seaa.gr/seaa-press-releases/):

  <Y>-<M>-comp.xlsx         passenger cars (PC + taxis) by brand: the month's
                            exact TOTAL                        (since 2020-07)
  <Y>-<M>-BEV.pdf           new battery-electric PCs by segment, brand and
  <Y>-<M>-PHEV.pdf          model / new plug-in hybrids, ditto   (since 2024-01)
  <Y>-<M>-electric.pdf      both in one file                 (2021-12..2023-12)
  Δελτίο-τύπου-ΣΕΑΑ-για-τις-ταξινομήσεις-<μήνα>-<Y>.pdf
                            the monthly press release: the fuel split as
                            SHARES with one decimal (petrol, diesel, HEV,
                            PHEV, BEV, LPG, until 2022 also CNG), and since
                            2025-11 a preliminary BEV / PHEV / TOTAL count

Every upload is listed by the WordPress REST API
(https://seaa.gr/wp-json/wp/v2/media), so the fetcher finds files by name
instead of scraping pages. SEAA's figures are what ACEA publishes for Greece:
TOTAL, BEV and PHEV agree to the unit in 50 of 56 months 2022-01..2026-08, and
two of the others are ACEA errors SEAA corrects
(docs/architecture/53-source-greece.md §4).

Month → row
-----------
  TOTAL                  comp.xlsx, row TOTAL, the month column       exact
  BEV, PHEV              BEV.pdf / PHEV.pdf (electric.pdf before 2024),
                         the month column of the summary line          exact
  HEV, PETROL, DIESEL,   press-release shares × (TOTAL − BEV − PHEV),
  OTHERS                 largest-remainder rounded so the row sums to
                         TOTAL; OTHERS = LPG + CNG + whatever the shares
                         leave out                                     derived

The shares carry one decimal and are the press release's, not the final
statistics', so a derived column is not a count: typically about 5 cars off,
at most 15 in 9 months out of 10, at most 50 (0.4 % of the month). ACEA
publishes SEAA's counted split about a week later; then HEV/PETROL/DIESEL
are ACEA's and OTHERS = TOTAL minus the rest (source "SEAA / ACEA"). The
merge (scripts/acea_split.py) runs in whichever fetcher comes second: here,
when the month already has an ACEA (or SEAA / ACEA) row, its split is kept;
in fetch_acea.py, on a SEAA row. It is refused when ACEA's TOTAL/BEV/PHEV
are not SEAA's month (ACEA's wrong 2022-12 and 2023-07).

BEV, PHEV and TOTAL are never derived. A month whose press release is
missing or whose shares do not add up gets BEV/PHEV/TOTAL only (until ACEA's
split arrives), the other columns empty (no split ≠ zero, invariant 4).

Provisional rows: the press release (published first, ~10th–24th) has
carried preliminary BEV/PHEV/TOTAL counts since 2025-11. When the statistics
files are not out yet, the fetcher writes the month from the press release
alone and says "provisional" in `notes`; the next run that finds the
statistics files replaces it (an own provisional row is always refreshed).

Scope: SEAA's "PC and taxi cars" — new M1 passenger cars incl. taxis, the
same scope as ACEA's Greece figure. Whole is written from WHOLE_FROM (2022-01,
the first full month SEAA publishes exact BEV/PHEV counts for); the quarterly
ACEA rows before it stay as they are (invariant 3). A row from ACEA for a
month SEAA covers is replaced (SEAA supersedes ACEA for Greece, ACEA keeps it
only as a fallback — scripts/fetch_acea.py's conditional list); any other
foreign source is never overwritten.

Governance (every real run)
---------------------------
* BEV/PHEV counts come from each PDF's summary line, never from its model
  table; the model lines are summed and compared with it, and a month whose
  lines are more than max(3, 3 %) off is left out of the top lists (SEAA's
  2022–2023 tables miss a few lines; a layout change shows up here first);
* the file's printed month ("AUGUST '26", "Aug. '26") must be the month the
  file name claims;
* the press-release shares must add up to 100 % ± 1.5 (else: not used);
* cross-checks, logged and summarised (abort above 3 %): press-release
  preliminary counts vs the statistics files, and the PR's BEV share × TOTAL
  vs the exact BEV count;
* a new month below 25 % of the trailing-12 median TOTAL is not written
  (warning below 50 %; Greece's August is legitimately ~45 %);
* fuels sum to TOTAL for every row written.

Also writes market/greece_top.json (+ greece_months.json): the top BEV and
PHEV brands and models, read off the same PDFs.

Usage
-----
    python scripts/fetch_greece.py                  # newest month(s) missing
    python scripts/fetch_greece.py --period 2026-07 # one month
    python scripts/fetch_greece.py --backfill       # every month from 2022-01
    python scripts/fetch_greece.py --from-dir DIR   # offline: files saved with
                                                    # their original names
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import io
import json
import os
import re
import statistics
import sys
import time
import unicodedata
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import acea_split  # noqa: E402
import market_top  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
CSV_PATH = REPO / "data" / "Greece.csv"
SOURCE = "SEAA"
MERGED = acea_split.MERGED_SOURCE["Greece"]   # SEAA + ACEA's counted split
OWN = (SOURCE, MERGED)
SUPERSEDES = ("ACEA",)            # foreign sources SEAA may replace
VARIANT = "Whole"
COLUMNS = ["period", "time_interval", "variant", "source", "BEV", "PHEV", "HEV",
           "PETROL", "DIESEL", "OTHERS", "TOTAL", "notes"]
FUELS = ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS"]
DERIVED = ("HEV", "PETROL", "DIESEL", "OTHERS")

WHOLE_FROM = "2022-01"
MEDIA_API = "https://seaa.gr/wp-json/wp/v2/media"
MEDIA_PAGES_RECENT = 3            # newest 300 uploads: plenty for a monthly run
SHARE_TOLERANCE = 1.5             # percentage points the shares may miss 100 by
CROSS_ABORT = 0.03                # relative gap that aborts a cross-check
COMPLETENESS_ABORT = 0.25         # × trailing-12 median TOTAL
COMPLETENESS_WARN = 0.50
HTTP_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124 Safari/537.36 "
                   "LeRaffl-Gallery fetch_greece.py"),
    "Accept-Language": "el,en;q=0.8",
}
TOP_SLUG = "greece"
TOP_UNIT = ("new passenger cars incl. taxis (brand = SEAA's make, model = SEAA's "
            "'Range'; BEV and PHEV tables only)")

# Greek month stems after accent stripping — they match the genitive of the
# press-release file name (Αυγούστου) and the accusative of its subject line
# (Αύγουστο). "μαρτ" must be tried before "μαι".
GREEK_MONTHS = ["ιανουαρ", "φεβρουαρ", "μαρτ", "απριλ", "μαι", "ιουν", "ιουλ",
                "αυγουστ", "σεπτεμβρ", "οκτωβρ", "νοεμβρ", "δεκεμβρ"]
EN_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP",
             "OCT", "NOV", "DEC"]


# ── names, periods ─────────────────────────────────────────────────────────

def norm(s: str) -> str:
    """Lower case, accents stripped, Unicode dashes → '-'."""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[‐-―−]", "-", s).lower()


def period_of(y: int | str, m: int | str) -> str:
    return f"{int(y):04d}-{int(m):02d}"


def next_month(p: str) -> str:
    y, m = int(p[:4]), int(p[5:7])
    return period_of(y + m // 12, m % 12 + 1)


def months_between(a: str, b: str) -> list[str]:
    out, p = [], a
    while p <= b:
        out.append(p)
        p = next_month(p)
    return out


def greek_month(text: str) -> int | None:
    t = norm(text)
    for i, stem in enumerate(GREEK_MONTHS):
        if t.startswith(stem):
            return i + 1
    return None


def classify_name(name: str) -> tuple[str, str] | None:
    """File name → (kind, period) for the files the fetcher reads, else None.
    kind ∈ comp | bev | phev | electric | pr."""
    n = norm(urllib.parse.unquote(name.rsplit("/", 1)[-1]))
    m = re.search(r"(?<!\d)(\d{4})-(\d{1,2})-(comp|bev|phev|electric)(?:-\d+)?"
                  r"\.(xlsx|pdf)$", n)
    if m:
        kind, ext = m.group(3), m.group(4)
        if (kind == "comp") != (ext == "xlsx"):
            return None
        return kind, period_of(m.group(1), m.group(2))
    m = re.search(r"δελτιο-τυπου-σεαα-για-τις-ταξινομησεις-([^-\d]+)-(\d{4})", n)
    if m:
        mon = greek_month(m.group(1))
        if mon:
            return "pr", period_of(m.group(2), mon)
    return None


# ── the file library (network or a local mirror) ──────────────────────────

class Library:
    """{(kind, period): newest file}. Several uploads of one name exist
    (SEAA re-uploads as -1, -2 …); the newest upload wins."""

    def __init__(self):
        self.entries: dict[tuple[str, str], tuple[str, str]] = {}   # → (date, ref)

    def add(self, date: str, ref: str) -> None:
        key = classify_name(ref)
        if key and (key not in self.entries or date >= self.entries[key][0]):
            self.entries[key] = (date, ref)

    def has(self, kind: str, period: str) -> bool:
        return (kind, period) in self.entries

    def periods(self, kind: str) -> list[str]:
        return sorted(p for k, p in self.entries if k == kind)

    def read(self, kind: str, period: str) -> bytes:
        raise NotImplementedError

    def url(self, kind: str, period: str) -> str:
        return self.entries[(kind, period)][1]


class DirLibrary(Library):
    def __init__(self, root: Path):
        super().__init__()
        for f in sorted(root.rglob("*")):
            if f.is_file():
                self.add(f.name, str(f))

    def read(self, kind, period):
        return Path(self.entries[(kind, period)][1]).read_bytes()


class WebLibrary(Library):
    def __init__(self, pages: int | None):
        super().__init__()
        import requests
        self.s = requests.Session()
        self.s.headers.update(HTTP_HEADERS)
        page = 1
        while pages is None or page <= pages:
            r = self._get(MEDIA_API, params={"per_page": 100, "page": page,
                                             "_fields": "date,source_url",
                                             "orderby": "date", "order": "desc"})
            if r.status_code == 400:          # past the last page
                break
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            for m in batch:
                self.add(m.get("date") or "", m.get("source_url") or "")
            page += 1
        print(f"SEAA media index: {page - 1} page(s), "
              f"{len(self.entries)} relevant files")

    def _get(self, url, **kw):
        for attempt in range(4):
            try:
                r = self.s.get(url, timeout=90, **kw)
                if r.status_code < 500:
                    return r
            except Exception as e:  # noqa: BLE001 — retried, then re-raised
                if attempt == 3:
                    raise
                print(f"  retry {url}: {e}")
            time.sleep(5 * (attempt + 1))
        r.raise_for_status()
        return r

    def read(self, kind, period):
        url = self.url(kind, period)
        p = urllib.parse.urlsplit(url)
        url = urllib.parse.urlunsplit((p.scheme, p.netloc,
                                       urllib.parse.quote(urllib.parse.unquote(p.path)),
                                       p.query, ""))
        r = self._get(url)
        r.raise_for_status()
        return r.content


# ── parsers ────────────────────────────────────────────────────────────────

def _int(s: str) -> int:
    return int(s.replace(".", "").replace(",", ""))


def _pct(s: str) -> float:
    return float(s.replace("%", "").replace(",", "."))


# Greek capitals that look like Latin ones — SEAA once typed "ΜΑΥ '23".
HOMOGLYPHS = str.maketrans("ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ", "ABEZHIKMNOPTYX")


def printed_period(text: str) -> str | None:
    """'AUGUST '26' / "Aug. '26" / "August. '23" → '2026-08'."""
    text = text.upper().translate(HOMOGLYPHS)
    m = re.search(r"\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\.?\s*"
                  r"['’‘](\d{2})\b", text.upper())
    if not m:
        return None
    return period_of(2000 + int(m.group(2)), EN_MONTHS.index(m.group(1)) + 1)


def parse_comp(data: bytes, period: str) -> int:
    """comp.xlsx → the month's TOTAL (row 'TOTAL', the first month column)."""
    import openpyxl
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    ws = wb.worksheets[0]
    head = None
    for row in ws.iter_rows(max_row=40, values_only=True):
        cells = ["" if c is None else str(c).strip() for c in row]
        if len(cells) > 2 and cells[1].upper() == "BRAND":
            head = cells
            continue
        if head and len(cells) > 2 and cells[1].upper() == "TOTAL":
            got = printed_period(head[2])
            if got != period:
                raise ValueError(f"comp.xlsx for {period} prints {head[2]!r}")
            return int(float(row[2]))
    raise ValueError(f"comp.xlsx for {period}: no Brand header / TOTAL row")


def _pdf_lines(data: bytes) -> list[list[dict]]:
    """Every text line of a PDF as a list of words (text, x0, x1), top to
    bottom. Words are joined into a line when their tops are within 3 pt —
    SEAA's right-aligned number columns sit a point lower than the labels."""
    import pdfplumber
    out = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            line: list[dict] = []
            for w in sorted(page.extract_words(), key=lambda w: (w["top"], w["x0"])):
                if line and w["top"] - line[0]["top"] > 3:
                    out.append(sorted(line, key=lambda w: w["x0"]))
                    line = []
                line.append(w)
            if line:
                out.append(sorted(line, key=lambda w: w["x0"]))
    return out


def _pdf_text(data: bytes) -> str:
    import pdfplumber
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


NUM = r"\d{1,3}(?:\.\d{3})*|\d+"
SUMMARY_RE = re.compile(rf"^SEGMENT\s+({NUM})\s+([\d,]+)%(?:\s+({NUM})\s+([\d,]+)%)?$")
SEG_RE = re.compile(rf"^([A-Z][A-Z0-9/\- ]*?)\s+({NUM})\s+[\d,]+%(?:\s+({NUM})\s+[\d,]+%)?$")

AGGREGATE_SEGMENTS = {"SUV"}      # plus every "<X> TOTAL"
MODEL_GAP = 0.03                  # model lines vs summary, see models_ok()


class PlugInFile:
    """One BEV / PHEV / electric PDF: per class the month and YTD totals, and
    the units per (brand, model) summed over the base segments."""

    def __init__(self):
        self.month: dict[str, int] = {}
        self.ytd: dict[str, int] = {}
        self.models: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
        self.models_ytd: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
        self.period: str | None = None
        self.gaps: dict[str, tuple[int, int]] = {}   # class → (model sum, summary)

    def models_ok(self) -> bool:
        """SEAA's model lines do not always add up to its own summary (a
        model listed as "BEV-PHEV", a line missing). The month's counts come
        from the summary either way; the model table is used for the top
        lists only when it is within MODEL_GAP of it."""
        return all(abs(got - want) <= max(3, MODEL_GAP * want)
                   for got, want in self.gaps.values())


FUEL_TOKENS = {"BEV", "PHEV", "EREV", "BEV-PHEV"}
NUMBER_RE = re.compile(r"^[\d.,]+%?$")


def _fuel_index(words: list[dict]) -> int | None:
    """Index of a model line's fuel-type word: the last fuel word followed by
    a number (a model may itself end in "PHEV": "EXPLORER PHEV PHEV 6 4,05%",
    or be a number: "FIAT 500 BEV 1 0,56%")."""
    for i in range(len(words) - 2, 1, -1):
        if words[i]["text"] in FUEL_TOKENS and NUMBER_RE.match(words[i + 1]["text"]):
            return i
    return None


def _range_column(lines: list[list[dict]]) -> float:
    """Left edge of the model ("Range") column. Its header word is centred,
    the values are left-aligned, so it is read off the data: the most common
    left edge of a word between the make and the fuel type."""
    xs = collections.Counter()
    for words in lines:
        fi = _fuel_index(words)
        if fi is None:
            continue
        for w in words[1:fi]:
            xs[round(w["x0"])] += 1
    if not xs:
        return float("inf")
    return float(xs.most_common(1)[0][0])


def _volume(token: str) -> int:
    """A volume cell. SEAA's sheet occasionally formats a volume as a
    percentage (7 printed as "700,00%"); the column says it is a volume."""
    if token.endswith("%"):
        return round(_pct(token) / 100)
    return _int(token)


def parse_plugin_pdf(data: bytes, kind: str) -> PlugInFile:
    """kind 'bev' / 'phev' (one class per file) or 'electric' (both).

    Detail blocks are "Segment <name> <ytd> <%> <month> <%>" followed by a
    "Make: Range: Fuel Type: Volume: % Volume: %" header and one line per
    model. Columns are told apart by x position: make / range / fuel by the
    header words' left edges, the four number columns by the nearest header
    word centre. Blocks named "… TOTAL" and "SUV" repeat the base segments
    and are skipped, so every model is counted once (the sum check below
    proves it)."""
    out = PlugInFile()
    cls = {"bev": "BEV", "phev": "PHEV"}.get(kind)
    segment = None
    after_seg_header = False
    cols = None
    summary_done: set[str] = set()
    lines = _pdf_lines(data)
    range_x = _range_column(lines)
    for words in lines:
        text = norm(" ".join(w["text"] for w in words)).upper()
        if out.period is None:
            out.period = printed_period(text)
        m = re.match(r"^(BEV|PHEV) VEHICLES\b", text)
        if m:
            cls = m.group(1)
            continue
        if text.startswith("SEGMENT TOTAL MARKET SHARE"):
            after_seg_header = True
            segment = cols = None
            continue
        m = SUMMARY_RE.match(text)
        if m and cls and cls not in summary_done:
            out.ytd[cls] = _int(m.group(1))
            out.month[cls] = _int(m.group(3)) if m.group(3) else 0
            summary_done.add(cls)
            continue
        if after_seg_header:
            # the segment line, possibly after a page footer/header
            m = SEG_RE.match(text)
            if m:
                segment = m.group(1).strip()
                after_seg_header = False
                continue
            if not text.startswith("MAKE:"):
                continue
            after_seg_header = False
        if text.startswith("MAKE:"):
            nums = [(w["x0"] + w["x1"]) / 2 for w in words
                    if norm(w["text"]).upper().rstrip(":") in ("VOLUME", "%")]
            if len(nums) != 4:
                raise ValueError(f"{kind}: unexpected column header {text!r}")
            cols = nums
            continue
        if segment is None or cols is None:
            continue
        anchors = cols
        fi = _fuel_index(words)
        if fi is None or words[fi]["text"] not in ("BEV", "PHEV", "EREV"):
            continue          # not a model line, or one SEAA labels "BEV-PHEV"
        make = " ".join(w["text"] for w in words[:fi] if w["x0"] < range_x - 2)
        model = " ".join(w["text"] for w in words[:fi] if w["x0"] >= range_x - 2)
        rest = words[fi:]
        if not make or not model:
            raise ValueError(f"{kind}: cannot split make / model in {text!r}")
        slots: dict[int, str] = {}
        for w in rest[1:]:
            c = (w["x0"] + w["x1"]) / 2
            slot = min(range(4), key=lambda i: abs(anchors[i] - c))
            if slot in slots:
                raise ValueError(f"{kind}: two values in one column: {text!r}")
            slots[slot] = w["text"]
        if 0 not in slots:
            # a volume cell printed as a percentage shifts the line to the
            # right ("700,00% 87,50% 300,00%" = 7, 87.5 %, 3): read by order
            slots = dict(enumerate(w["text"] for w in rest[1:5]))
            print(f"  {kind}: shifted model line read by order: {text!r}")
        fuel = "PHEV" if rest[0]["text"] == "EREV" else rest[0]["text"]
        if segment.endswith("TOTAL") or segment in AGGREGATE_SEGMENTS:
            continue
        key = (market_top.clean(make), market_top.clean(model))
        out.models_ytd[fuel][key] += _volume(slots[0])
        out.models[fuel][key] += _volume(slots[2]) if 2 in slots else 0
    if not out.month:
        raise ValueError(f"{kind}: no summary line found")
    for c in out.month:
        got = sum(out.models[c].values())
        out.gaps[c] = (got, out.month[c])
    return out


FUEL_ANCHORS = [   # (pattern on the normalised line, column) — order matters
    (r"^plug in υβριδικα|^\(?phev\)?$|^plug-in", "PHEV"),
    (r"^επαναφορτιζομενα|bev-phev", None),           # combined BEV+PHEV: ignored
    (r"^αμιγως ηλεκτρικα|^ηλεκτρικα \(bev\)|^ηλεκτρικα$", "BEV"),
    (r"^υβριδικα \(hev\)|^υβριδικα$", "HEV"),
    (r"^βενζινη", "PETROL"),
    (r"^πετρελαιο", "DIESEL"),
    (r"^υγραεριο", "LPG"),
    (r"^φυσικο αεριο", "CNG"),
]
PCT_RE = re.compile(r"(\d{1,3},\d)%")


class PressRelease:
    def __init__(self):
        self.period: str | None = None
        self.total: int | None = None
        self.bev: int | None = None
        self.phev: int | None = None
        self.shares: dict[str, float] = {}


def parse_press_release(data: bytes) -> PressRelease:
    t = _pdf_text(data)
    out = PressRelease()
    m = re.search(r"Θέμα:.*?κατά\s+(?:τον|το|την)\s+(\S+)\s+(\d{4})", t)
    if m and greek_month(m.group(1)):
        out.period = period_of(m.group(2), greek_month(m.group(1)))
    m = re.search(rf"Καινούργια\s*(?:επιβατικά\s*)?({NUM})\s", t)
    if m:
        out.total = _int(m.group(1))
    m = re.search(rf"(?m)^\s*BEV\s+({NUM})\s", t)
    if m:
        out.bev = _int(m.group(1))
    m = re.search(rf"(?m)^\s*PHEV\s+({NUM})\s", t)
    if m:
        out.phev = _int(m.group(1))
    # the fuel table: from the petrol line to the EU paragraph / the footnote
    lines = t.splitlines()
    start = next((i for i, l in enumerate(lines) if norm(l).startswith("βενζινη")), None)
    if start is None:
        return out
    current = None
    for line in lines[start:]:
        n = norm(line).strip()
        if n.startswith("σε επιπεδο εε") or n.startswith("*"):
            break
        for pat, col in FUEL_ANCHORS:
            if re.search(pat, n):
                current = col if col else "_skip"
                break
        pm = PCT_RE.search(line)
        if pm and current and current not in out.shares:
            out.shares[current] = _pct(pm.group(1))
    out.shares.pop("_skip", None)
    return out


# ── building rows ──────────────────────────────────────────────────────────

def apportion(remainder: int, weights: dict[str, float]) -> dict[str, int]:
    """Largest-remainder split of `remainder` in proportion to `weights`."""
    tot = sum(weights.values())
    if remainder <= 0 or tot <= 0:
        return {k: 0 for k in weights}
    raw = {k: remainder * w / tot for k, w in weights.items()}
    out = {k: int(v) for k, v in raw.items()}
    rest = remainder - sum(out.values())
    for k in sorted(weights, key=lambda k: (raw[k] - out[k], k), reverse=True)[:rest]:
        out[k] += 1
    return out


def split_from_shares(total: int, bev: int, phev: int,
                      shares: dict[str, float]) -> dict[str, int] | None:
    """The non-plug-in remainder (TOTAL − BEV − PHEV) split by the press-release
    shares, or None when they are unusable (a column missing, or the shares
    plus the plug-in share miss 100 % by more than SHARE_TOLERANCE). The
    plug-in share comes from the exact counts — older releases print only a
    combined BEV-PHEV share."""
    if not total or any(k not in shares for k in ("PETROL", "DIESEL", "HEV")):
        return None
    plug_share = 100 * (bev + phev) / total
    rest_share = 100 - plug_share
    core = {k: shares[k] for k in ("HEV", "PETROL", "DIESEL")}
    listed = sum(core.values()) + shares.get("LPG", 0) + shares.get("CNG", 0)
    if abs(listed - rest_share) > SHARE_TOLERANCE:
        return None
    core["OTHERS"] = max(0.0, rest_share - sum(core.values()))
    return apportion(total - bev - phev, core)


class Month:
    def __init__(self, period: str):
        self.period = period
        self.total: int | None = None
        self.bev: int | None = None
        self.phev: int | None = None
        self.plugin: PlugInFile | None = None
        self.pr: PressRelease | None = None
        self.provisional = False
        self.checks: list[str] = []

    def row(self) -> tuple[dict, str] | None:
        if self.total is None or self.bev is None or self.phev is None:
            return None
        row = {"BEV": self.bev, "PHEV": self.phev, "TOTAL": self.total}
        split = (split_from_shares(self.total, self.bev, self.phev, self.pr.shares)
                 if self.pr else None)
        src = ("SEAA press release (provisional)" if self.provisional else
               "SEAA statistics: TOTAL comp.xlsx, BEV/PHEV "
               + ("electric.pdf" if self.period < "2024-01" else "BEV.pdf/PHEV.pdf"))
        if split:
            row.update(split)
            note = (f"{src}; HEV/PETROL/DIESEL/OTHERS derived from the press-release "
                    "fuel shares (1 decimal), OTHERS = LPG+CNG+rest")
        else:
            note = f"{src}; no usable fuel shares — HEV/PETROL/DIESEL/OTHERS empty"
        if self.provisional:
            note = "provisional — " + note
        return row, note


def load_month(lib: Library, period: str, allow_provisional: bool) -> Month:
    mo = Month(period)
    if lib.has("pr", period):
        pr = parse_press_release(lib.read("pr", period))
        if pr.period and pr.period != period:
            raise ValueError(f"press release filed as {period} is about {pr.period}")
        mo.pr = pr
    if lib.has("comp", period):
        mo.total = parse_comp(lib.read("comp", period), period)
    files = [k for k in ("bev", "phev") if lib.has(k, period)]
    if len(files) < 2 and lib.has("electric", period):
        files = ["electric"]
    for k in files:
        f = parse_plugin_pdf(lib.read(k, period), k)
        if f.period != period:
            raise ValueError(f"{k} file for {period} prints {f.period}")
        if mo.plugin is None:
            mo.plugin = f
        else:
            mo.plugin.month.update(f.month)
            mo.plugin.ytd.update(f.ytd)
            mo.plugin.models.update(f.models)
            mo.plugin.models_ytd.update(f.models_ytd)
            mo.plugin.gaps.update(f.gaps)
    if mo.plugin and {"BEV", "PHEV"} <= set(mo.plugin.month):
        mo.bev, mo.phev = mo.plugin.month["BEV"], mo.plugin.month["PHEV"]
    if (mo.total is None or mo.bev is None) and allow_provisional and mo.pr \
            and None not in (mo.pr.total, mo.pr.bev, mo.pr.phev):
        mo.total, mo.bev, mo.phev = mo.pr.total, mo.pr.bev, mo.pr.phev
        mo.provisional = True
    if mo.plugin:
        for c, (got, want) in sorted(mo.plugin.gaps.items()):
            if got != want:
                mo.checks.append(f"{c} model lines sum to {got:,}, summary {want:,}"
                                 + ("" if mo.plugin.models_ok() else
                                    " — model table not used for the top lists"))
    cross_check(mo)
    return mo


def _gap(a: int, b: int) -> float:
    return abs(a - b) / max(b, 1)


def cross_check(mo: Month) -> None:
    """Independent figures for the same month; a gap above CROSS_ABORT aborts."""
    pr = mo.pr
    if pr and not mo.provisional and mo.total:
        for name, prelim, final in (("TOTAL", pr.total, mo.total),
                                    ("BEV", pr.bev, mo.bev), ("PHEV", pr.phev, mo.phev)):
            if prelim is None or final is None:
                continue
            mo.checks.append(f"{name}: press release {prelim:,} vs statistics {final:,}")
            if final > 200 and _gap(prelim, final) > CROSS_ABORT:
                raise ValueError(f"{mo.period}: press-release {name} {prelim:,} vs "
                                 f"statistics {final:,} — more than {CROSS_ABORT:.0%} apart")
        if "BEV" in pr.shares and mo.bev and mo.bev > 200:
            implied = round(pr.shares["BEV"] / 100 * mo.total)
            mo.checks.append(f"BEV share {pr.shares['BEV']}% × TOTAL = {implied:,} vs {mo.bev:,}")
            if abs(implied - mo.bev) > max(0.0006 * mo.total + 2, CROSS_ABORT * mo.bev):
                raise ValueError(f"{mo.period}: BEV share × TOTAL = {implied} vs "
                                 f"exact {mo.bev} — the share table was misread")


# ── CSV line-level upsert (invariant 2) ────────────────────────────────────

def fmt(v) -> str:
    return "" if v is None else f"{float(v):.1f}"


def render_line(period: str, row: dict, notes: str, source: str = SOURCE) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="").writerow(
        [period, "monthly", VARIANT, source]
        + [fmt(row.get(k)) for k in FUELS + ["TOTAL"]] + [notes])
    return buf.getvalue()


def _fields(line: str) -> list[str]:
    return next(csv.reader([line.rstrip("\r\n")]))


def csv_rows(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {r["period"]: r for r in csv.DictReader(f)
                if (r.get("variant") or VARIANT) == VARIANT}


def may_replace(old: dict, force: bool) -> bool:
    src = (old.get("source") or "").strip()
    if src in SUPERSEDES:
        return True
    if src not in OWN:
        return False
    return force or (old.get("notes") or "").startswith("provisional")


def upsert_lines(path: Path, updates: dict[str, str], force: bool) -> dict[str, int]:
    """Replace/insert only the given periods' lines; every other line is
    written back byte for byte."""
    if path.exists():
        with open(path, encoding="utf-8", newline="") as f:
            text = f.read()
    else:
        text = ",".join(COLUMNS) + "\n"
    eol = "\r\n" if "\r\n" in text else "\n"
    raw = text.splitlines(keepends=True)
    header, lines = raw[0], [l for l in raw[1:] if l.strip()]
    if header.rstrip("\r\n").split(",") != COLUMNS:
        sys.exit(f"{path}: unexpected header {header!r} — expected {COLUMNS}")
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += eol
    stats = {"added": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    for period, new in sorted(updates.items()):
        index = {(_fields(l)[0], _fields(l)[2]): i for i, l in enumerate(lines)}
        if (period, VARIANT) in index:
            i = index[(period, VARIANT)]
            old = lines[i]
            olddict = dict(zip(COLUMNS, _fields(old)))
            if old.rstrip("\r\n") == new:
                stats["unchanged"] += 1
            elif not may_replace(olddict, force):
                stats["skipped"] += 1
                print(f"  {period}: kept the {olddict.get('source')!r} row")
            else:
                lines[i] = new + old[len(old.rstrip("\r\n")):]
                stats["updated"] += 1
        else:
            at = next((i for i, l in enumerate(lines) if _fields(l)[0] > period),
                      len(lines))
            lines.insert(at, new + eol)
            stats["added"] += 1
    if stats["added"] or stats["updated"]:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(header + "".join(lines))
    return stats


# ── month selection & guards ───────────────────────────────────────────────

def target_month(today: dt.date) -> str:
    """The newest month SEAA can have published: the previous calendar month."""
    first = today.replace(day=1)
    prev = first - dt.timedelta(days=1)
    return period_of(prev.year, prev.month)


def needs_write(have: dict[str, dict], period: str) -> bool:
    r = have.get(period)
    if r is None:
        return True
    return (r.get("source") or "").strip() in SUPERSEDES or (
        (r.get("source") or "").strip() in OWN
        and (r.get("notes") or "").startswith("provisional"))


def completeness(have: dict[str, dict], period: str, total: int) -> tuple[float, str]:
    prev = []
    p = period
    for _ in range(12):
        y, m = int(p[:4]), int(p[5:7])
        p = period_of(y - (m == 1), 12 if m == 1 else m - 1)
        try:
            prev.append(float(have[p]["TOTAL"]))
        except (KeyError, TypeError, ValueError):
            pass
    if len(prev) < 6:
        return 1.0, "too little history to judge"
    med = statistics.median(prev)
    return total / med, f"{total:,} vs trailing-12 median {med:,.0f}"


# ── top brands / models ────────────────────────────────────────────────────

def refresh_top(months: list[Month]) -> None:
    fresh = {}
    for mo in months:
        if mo.plugin is None or mo.total is None or mo.provisional \
                or not mo.plugin.models_ok():
            continue
        units = collections.Counter()
        for cls in ("BEV", "PHEV"):
            for (brand, model), n in mo.plugin.models[cls].items():
                if n:
                    units[(cls, brand, model)] += n
        fresh[mo.period] = (dict(units), mo.total)
    if fresh:
        market_top.refresh_from_store("Greece", SOURCE, TOP_UNIT, TOP_SLUG, fresh)


# ── main ───────────────────────────────────────────────────────────────────

def summary(months: list[Month], written: dict[str, str]) -> None:
    out = os.environ.get("GITHUB_STEP_SUMMARY")
    lines = ["### Greece — SEAA", "",
             "| month | BEV | PHEV | HEV* | PETROL* | DIESEL* | OTHERS* | TOTAL | written |",
             "|---|---|---|---|---|---|---|---|---|"]
    for mo in months[-6:]:
        r = mo.row()
        if not r:
            continue
        row, _ = r
        cells = " | ".join("" if row.get(k) is None else f"{row[k]:,}"
                           for k in FUELS + ["TOTAL"])
        lines.append(f"| {mo.period}{' (prov.)' if mo.provisional else ''} | {cells} | "
                     f"{'yes' if mo.period in written else 'no'} |")
    lines += ["", "\\* derived from the press-release shares (replaced by ACEA's counts where a check below says so).", ""]
    for mo in months[-3:]:
        for c in mo.checks:
            lines.append(f"- {mo.period} {c}")
    text = "\n".join(lines) + "\n"
    print(text)
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(text)


def run(lib: Library, periods: list[str], force: bool, allow_provisional: bool,
        csv_path: Path = CSV_PATH) -> tuple[bool, list[Month]]:
    have = csv_rows(csv_path)
    months, updates = [], {}
    for p in periods:
        if not (lib.has("comp", p) or lib.has("pr", p)):
            print(f"  {p}: nothing published yet")
            continue
        mo = load_month(lib, p, allow_provisional)
        months.append(mo)
        r = mo.row()
        if r is None:
            print(f"  {p}: incomplete (TOTAL {mo.total}, BEV {mo.bev}, PHEV {mo.phev}) "
                  "— not written")
            continue
        row, note = r
        source = SOURCE
        old = have.get(p)
        if old and (old.get("source") or "").strip() in ("ACEA", MERGED):
            merged = acea_split.merge(row, old)
            if merged:
                row.update(merged[0])
                source = MERGED
                note = (("provisional — " if mo.provisional else "")
                        + acea_split.NOTE.format(nat="SEAA" + (" press release"
                                                                if mo.provisional else "")))
                mo.checks.append(f"HEV/PETROL/DIESEL from the {old['source']} row ({merged[1]})")
            else:
                mo.checks.append(acea_split.why_not(row, old))
        assert sum(row[k] for k in FUELS if row.get(k) is not None) == row["TOTAL"] \
            or any(row.get(k) is None for k in DERIVED), (p, row)
        ratio, why = completeness(have, p, row["TOTAL"])
        if ratio < COMPLETENESS_ABORT and not force:
            sys.exit(f"{p} looks incomplete ({why}) — not written; --force overrides")
        if ratio < COMPLETENESS_WARN:
            print(f"::warning title=Greece {p} unusually low::{why}")
        updates[p] = render_line(p, row, note, source)
    changed = False
    if updates:
        for p in sorted(updates)[-3:]:
            print(f"  {updates[p]}")
        stats = upsert_lines(csv_path, updates, force)
        print(f"  {csv_path.relative_to(REPO) if csv_path.is_relative_to(REPO) else csv_path}: {stats}")
        changed = bool(stats["added"] or stats["updated"])
    market_top.guarded(refresh_top, months)
    summary(months, updates)
    return changed, months


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--period", help="YYYY-MM: only this month")
    ap.add_argument("--backfill", action="store_true",
                    help=f"every month from {WHOLE_FROM} to the newest published")
    ap.add_argument("--force", action="store_true",
                    help="ignore the self-throttle and the completeness guard; "
                         "rewrite own rows (never a foreign source other than ACEA)")
    ap.add_argument("--no-provisional", action="store_true",
                    help="do not write a month from the press release alone")
    ap.add_argument("--from-dir", type=Path,
                    help="read files from a local mirror instead of seaa.gr")
    ap.add_argument("--today", help="YYYY-MM-DD, for tests and replays")
    ap.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    args = ap.parse_args()

    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    target = target_month(today)
    have = csv_rows(CSV_PATH)
    if args.period:
        periods = [args.period]
    elif args.backfill:
        periods = months_between(WHOLE_FROM, target)
    else:
        newest = max((p for p, r in have.items() if (r.get("source") or "") in OWN),
                     default=None)
        start = next_month(newest) if newest else WHOLE_FROM
        periods = sorted({p for p in months_between(min(start, target), target)}
                         | {p for p in have if needs_write(have, p) and p >= WHOLE_FROM})
        if not args.force and not any(needs_write(have, p) for p in periods):
            print(f"Greece.csv already has {target} from {SOURCE} — nothing to do.")
            return emit(args, False)

    lib = DirLibrary(args.from_dir) if args.from_dir else \
        WebLibrary(None if (args.backfill or args.period) else MEDIA_PAGES_RECENT)
    if not args.force and not args.period:
        periods = [p for p in periods if needs_write(have, p)]
    changed, _ = run(lib, periods, args.force, not args.no_provisional)
    if not changed:
        print("No changes.")
    return emit(args, changed)


def emit(args, changed: bool) -> int:
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")
            f.write(f"changed_variants={json.dumps([VARIANT] if changed else [])}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
