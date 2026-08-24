#!/usr/bin/env python3
"""
Fetch Türkiye vehicle registration data from TÜİK and update data/Türkiye.csv.

Usage
-----
    python scripts/fetch_turkey.py [--year YEAR] [--month MONTH] \
        [--press-id ID] [--pdf-url URL] [--pdf-path PATH] \
        [--csv PATH] [--force] [--dry-run] [--no-ytd-check]

* --year / --month  Override the target month (default: previous calendar month).
* --press-id        TÜİK bulletin Sayı (e.g. 58042 for Nisan 2026).
* --pdf-url         Direct URL to the press PDF (mutually exclusive with --press-id).
* --pdf-path        Local path to a press PDF (for offline testing / re-runs).
* --csv             Target CSV (default: data/Türkiye.csv).
* --force           Re-process even if the target period already exists.
* --dry-run         Parse and validate, print the row, write nothing. Re-reading an
                    already-committed month this way is the regression test for a
                    parser change: it must reproduce what is in the CSV.
* --no-ytd-check    Skip the year-to-date cross-check (see validation, step 4e).

Invoked by .github/workflows/fetch-turkey.yml on a daily cron from the 15th of
each month onward, plus manual workflow_dispatch. When the CSV changes, the
workflow commits data/Türkiye.csv and triggers render-country.yml for Türkiye.

Data source
-----------
TÜİK (Türkiye İstatistik Kurumu — Turkish Statistical Institute) publishes
"Motorlu Kara Taşıtları" *(Motor Land Vehicles)* monthly bulletins on their
Veri Portalı *(Data Portal)*:

    https://veriportali.tuik.gov.tr/tr/press/<id>

where <id> identifies the bulletin. The ids are NOT chronological: observed
values are 58041=Mart 2026, 58042=Nisan 2026, 58043=Haziran 2026,
58044=Mayıs 2026, 58051=Ocak 2026 — one contiguous block for this series, in
arbitrary order within it. Each press release is a 5-page bulletin in Turkish, with the fuel
breakdown on page 4 ("Trafiğe kaydı yapılan otomobillerin yakıt cinslerine
göre dağılımı, <Month> <Year>" — "Distribution of automobiles registered to
traffic by fuel type, <Month> <Year>").

Vehicle scope
-------------
Otomobil only (passenger cars). The bulletin reports all motor land vehicle
categories (otomobil, motosiklet, kamyonet, traktör, kamyon, minibüs, otobüs,
özel amaçlı taşıt — passenger car, motorcycle, light commercial pickup,
tractor, truck, minibus, bus, special-purpose vehicle), but only otomobil is
broken down by fuel type and matches the historical data/Türkiye.csv scope.

Fuel mapping (TÜİK → CSV column)
--------------------------------
    Benzin    (gasoline)       → PETROL
    Hibrit    (hybrid)         → HEV    (TÜİK doesn't split PHEV from HEV —
                                         see glossary "Hybrid (capital,
                                         no qualifier)" entry)
    Elektrik  (electric)       → BEV
    Dizel     (diesel)         → DIESEL
    LPG       (autogas)        → OTHERS
    Toplam    (total)          → TOTAL

data/Türkiye.csv carries NO PHEV column — Türkiye is one of the two
sources (with Georgia) that reports a single combined Hybrid bucket.

CSV layout (existing)
---------------------
    period,time_interval,variant,source,BEV,HEV,PETROL,DIESEL,OTHERS,TOTAL,notes

Parsing strategy
----------------
The bulletins are rendered server-side as PDFs with the data table embedded
as a **raster image** (not text). pypdf / pdftotext extract only the narrative
paragraphs, not the table cells. We therefore:

1. Read the PDF text with pypdf to pull the authoritative monthly TOTAL and
   YTD TOTAL from narrative sentences:
     "<Month> ayında X bin Y adet otomobilin trafiğe kaydı yapıldı"
     "Ocak-<Month> döneminde trafiğe kaydı yapılan Z bin W adet otomobilin"
   These give us the month identification and a ground-truth TOTAL to verify
   against the OCR'd table.

2. Extract embedded images with `pdfimages -all`, OCR each with tesseract
   (Turkish language pack), and find the image that contains all six fuel-row
   labels (Toplam / Benzin / Hibrit / Elektrik / Dizel / LPG).

3. From the matching image's TSV bounding boxes, group words by their y-center
   (one row per label), then for each row split into integer tokens (Sayı,
   counts) vs decimal tokens (Pay %, percentage). The four count columns are:
       col 0: <Month> <PrevYear>      (e.g. Nisan 2025)
       col 1: <Month> <Year>          (e.g. Nisan 2026)   ← what we want
       col 2: Ocak-<Month> <PrevYear> (YTD prev year)
       col 3: Ocak-<Month> <Year>     (YTD this year)
   Thousand-separated counts like "81 907" get split by the tokenizer into
   two integer tokens; we re-join consecutive integer tokens whose continuation
   is exactly three digits (= a thousand-group separator).

   Which column a value belongs to is decided by its x-position against
   per-column anchors, never by its index in the row. Rows that came out with
   exactly four tokens vote for where the columns are; damaged rows are then
   read against that geometry. This matters because the OCR routinely drops or
   invents one token in a row, and under positional indexing a single dropped
   token silently shifts every column after it — Temmuz 2026 failed exactly so
   (see "Issues hit"). A missing value now reads as None in its own column and
   nothing else moves.

4. Layers of validation on the parsed col-1 numbers:
       (a) OCR Toplam[col 1] == narrative monthly_total       (hard fail)
       (b) Sum(Benzin..LPG, col 1) == Toplam[col 1]            (auto-repair if off)
       (c) Each fuel's count/Toplam == OCR'd Pay % (col 1) ±0.05 %  (used to
           identify the single wrong fuel during repair)
       (d) OCR'd col 0 (previous-year same month) == that row in the CSV
       (e) col 3 (Ocak-<Month> this year) minus the months the CSV already
           holds for this year == the col-1 values just parsed   (hard fail)

   Auto-repair: if (b) fails by `diff` and exactly one fuel's count is >0.05 %
   off from its OCR'd Pay %, set that fuel = Toplam - sum(others) and re-check
   the implied Pay % matches OCR'd Pay % to within 0.05 %. This catches single-
   digit OCR misreads (observed in dev: "27 715" instead of "27 775" for Mart
   2026 Hibrit, caused by a low-res rasterised image — see "Issues hit").
   Multi-fuel mismatches hard-fail rather than silently mis-correct.

   (d) and (e) are the two that make an unattended write defensible, because
   they are exact and they check the bulletin against our own committed history
   rather than against itself. (e) in particular re-derives all six numbers from
   a different pair of cells than the ones parsed: the same month, read twice,
   from two directions. (c) can never be more than a ±0.05 pp argument with a
   rounded one-decimal percentage — TÜİK prints 9,7 % where 7 689 / 78 761 is
   9,76 % — so it identifies suspects and does not gate.

   (e) skips itself when the CSV's year is incomplete, and hard-fails on
   disagreement, which is also what a TÜİK revision to an already-committed
   month looks like from here. --no-ytd-check exists for that case, once a
   human has looked. It is not something a scheduled run should ever pass.

Auto-discovery
--------------
The Veri Portalı is a React SPA — the press page URL returns an empty
``<div id="root"></div>`` shell — but it is backed by a JSON API:

    GET /api/tr/press/<id>   ->  {"data": {"id", "number", "date", "title",
                                           "period", "content"}, ...}

`title` ("Motorlu Kara Taşıtları") and `period` ("Haziran 2026") identify a
bulletin exactly. There is no listing endpoint to query — /api/tr/press,
.../list, /presses, /search, /categories and /themes all 404 — so
scripts/tuik_discover.py walks ids outward from the newest one recorded in the
CSV's source column and matches on both fields. Since the series sits in one
contiguous id block, the usual case costs a single request, and the anchor
re-derives itself each month with no id hard-coded anywhere.

`content` is the whole bulletin as HTML. The fuel table is a raster image
there too ("Benzin" appears nowhere in the markup), but the images are inline
data URIs, so they are decoded straight out of the JSON and OCR'd — no PDF is
downloaded at any point on this path. parse_content_tables() still tries real
markup first, in case TÜİK ever emits a table.

There is no known id -> PDF mapping. --pdf-url / --pdf-path remain for feeding
a PDF in by hand; --press-id on its own cannot reach one and says so.

Following the project rule we only ever write the most recent month; older
rows are never touched even if a later bulletin would adjust them.

CI dependencies
---------------
Beyond Python (pypdf, requests), the script shells out to:
    * convert     (imagemagick)    — upscale 4/6/8× before OCR
    * tesseract   (+ tesseract-ocr-tur) — OCR the table image
    * pdfimages   (poppler-utils)  — only for the --pdf-url/--pdf-path route

These are all installed in the fetch-turkey.yml workflow step.
"""
import argparse
import csv
import os
import re
import statistics
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TUIK_PRESS_URL = "https://veriportali.tuik.gov.tr/tr/press/{id}"

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}

CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "HEV", "PETROL", "DIESEL", "OTHERS",
    "TOTAL", "notes",
]

MONTHS_TR = {
    "Ocak": 1, "Şubat": 2, "Mart": 3, "Nisan": 4, "Mayıs": 5, "Haziran": 6,
    "Temmuz": 7, "Ağustos": 8, "Eylül": 9, "Ekim": 10, "Kasım": 11, "Aralık": 12,
}
MONTHS_TR_BY_NUM = {v: k for k, v in MONTHS_TR.items()}

# Row labels in the fuel table → CSV column (no PHEV — see docstring).
FUEL_TO_CSV = {
    "Toplam":   "TOTAL",
    "Benzin":   "PETROL",
    "Hibrit":   "HEV",
    "Elektrik": "BEV",
    "Dizel":    "DIESEL",
    "LPG":      "OTHERS",
}

# OCR sometimes garbles single characters in the row labels — keep a tolerance
# list per canonical label. Spotted in the wild on a low-res Mart 2026 sample:
# "Elektrik" came out as "Elekirik" / "Elekftrik". Add aliases as needed.
LABEL_ALIASES = {
    "Toplam":   ["Toplam"],
    "Benzin":   ["Benzin"],
    "Hibrit":   ["Hibrit"],
    "Elektrik": ["Elektrik", "Elekirik", "Elekftrik", "Elekfrik"],
    "Dizel":    ["Dizel"],
    "LPG":      ["LPG"],
}

# Narrative sentence patterns. Both forms allow "X bin Y" (Turkish for X*1000+Y)
# with optional "X bin" prefix (e.g. "81 bin 907" = 81 907; "907" alone = 907).
NARR_MONTHLY_RE = re.compile(
    r"(" + "|".join(MONTHS_TR.keys()) + r")\s+ay[ıi]nda\s+"
    r"(?:(\d+)\s*bin\s+)?(\d+)\s+adet\s+otomobilin\s+trafiğe\s+kaydı\s+yapıldı"
)
NARR_YTD_RE = re.compile(
    r"Ocak-(" + "|".join(MONTHS_TR.keys()) + r")\s+döneminde\s+trafiğe\s+kaydı\s+yapılan\s+"
    r"(?:(\d+)\s*bin\s+)?(\d+)\s+adet\s+otomobilin"
)

# Pay (%) tokens: "100,0", "34,6", "0,9" — comma decimal, no thousand-sep.
_PCT_RE = re.compile(r"\d+[.,]\d+")

# The fuel table carries four data periods, each printed twice — once as a count
# (Sayı) and once as a share (Pay %). Every parsed row is normalised to exactly
# these four slots, with None where the OCR delivered nothing, so a column index
# always means the same period no matter what the OCR dropped or invented.
N_COLS = 4
COL_MONTH_PREV = 0   # <Month> <PrevYear>
COL_MONTH = 1        # <Month> <Year>          ← the month being ingested
COL_YTD_PREV = 2     # Ocak-<Month> <PrevYear>
COL_YTD = 3          # Ocak-<Month> <Year>


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def turkish_number(thousands: str | None, rest: str) -> int:
    """Convert TÜİK's 'X bin Y' (X thousand Y) phrasing to int.

    Examples: ('81', '907') → 81907; (None, '907') → 907.
    """
    return (int(thousands) if thousands else 0) * 1000 + int(rest)


def previous_month(today: date) -> tuple[int, int]:
    if today.month == 1:
        return today.year - 1, 12
    return today.year, today.month - 1


def latest_period(csv_path: str) -> str | None:
    if not Path(csv_path).exists():
        return None
    with open(csv_path, newline="", encoding="utf-8") as f:
        periods = [row["period"] for row in csv.DictReader(f)]
    return max(periods) if periods else None


def load_pdf_bytes(url_or_path: str) -> bytes:
    if url_or_path.startswith("http://") or url_or_path.startswith("https://"):
        import requests  # lazy import — only needed for live runs
        print(f"Downloading: {url_or_path}")
        resp = requests.get(url_or_path, headers=HTTP_HEADERS, timeout=60)
        resp.raise_for_status()
        return resp.content
    path = url_or_path.replace("file://", "")
    with open(path, "rb") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Narrative parsing
# ---------------------------------------------------------------------------

def pdf_text(pdf_path: str) -> str:
    """Concatenate every page's text via pypdf for narrative parsing.

    pypdf is imported here rather than at module scope: the HTML bulletin path
    is the one that actually runs, and it never opens a PDF. Keeping the import
    lazy lets the parser and its tests be exercised without the dependency.
    """
    from pypdf import PdfReader

    return "\n".join((p.extract_text() or "") for p in PdfReader(pdf_path).pages)


def parse_narrative(text: str) -> dict:
    """Pull authoritative TOTAL and YTD-TOTAL from a press PDF's narrative."""
    out: dict = {}
    m = NARR_MONTHLY_RE.search(text)
    if m:
        out["month_name"] = m.group(1)
        out["month_num"] = MONTHS_TR[m.group(1)]
        out["monthly_total"] = turkish_number(m.group(2), m.group(3))
    m = NARR_YTD_RE.search(text)
    if m:
        out["ytd_month_name"] = m.group(1)
        out["ytd_total"] = turkish_number(m.group(2), m.group(3))
    return out


# ---------------------------------------------------------------------------
# OCR pipeline
# ---------------------------------------------------------------------------

def extract_images(pdf_path: str, out_dir: Path) -> list[Path]:
    """Extract every embedded image with pdfimages. Returns sorted paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["pdfimages", "-all", pdf_path, str(out_dir / "img")],
        check=True, capture_output=True,
    )
    return sorted(out_dir.glob("img-*"))


def ocr_tsv(image_path: Path, upscale: int = 4) -> list[dict]:
    """Upscale → OCR with tesseract → return word boxes from TSV output.

    Upscaling is necessary because some bulletins embed the fuel table as a
    ~98 dpi PPM (Mart 2026 sample) which tesseract reads with single-digit
    misreads at native size. 4× resize + Mitchell filter is consistently
    enough to recover them on the samples we've tested.
    """
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        png = td / "up.png"
        subprocess.run(
            ["convert", str(image_path), "-resize", f"{upscale * 100}%",
             "-density", "600", "-filter", "Mitchell", str(png)],
            check=True, capture_output=True,
        )
        base = td / "out"
        subprocess.run(
            ["tesseract", str(png), str(base), "-l", "tur", "tsv"],
            check=True, capture_output=True,
        )
        words: list[dict] = []
        with open(str(base) + ".tsv", encoding="utf-8") as f:
            header = next(f).rstrip("\n").split("\t")
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) != len(header):
                    continue
                d = dict(zip(header, parts))
                if not d.get("text") or d["text"].strip() == "":
                    continue
                words.append({
                    "text": d["text"],
                    "left": int(d["left"]),
                    "top": int(d["top"]),
                    "width": int(d["width"]),
                    "height": int(d["height"]),
                    "conf": float(d["conf"]),
                })
    return words


def iter_fuel_table_images(image_paths: list[Path], upscales=(4, 6, 8)):
    """Yield (path, words) for EVERY image whose OCR shows all six fuel labels.

    find_table_image() stops at the first hit, which is fine when there is only
    one such image. A bulletin has two — the month's registrations by fuel and
    the registered stock at month end — and they carry identical row labels, so
    first-match can land on the wrong one and take the whole run down with it.
    Yielding all of them lets the caller keep the table whose Toplam agrees
    with the narrative monthly total.

    Each image is offered at several upscale factors. A single factor is one
    roll of the dice on a low-resolution source: the Haziran 2026 table OCR'd
    at 4x produced a row sum that missed Toplam, and the repair heuristic then
    tried to pin the difference on LPG (1155, implying 1.6% against an OCR'd
    Pay% of 0.9%) — a misread elsewhere in the column, not in LPG. Re-reading
    the same image larger is the cheapest way out, and validation downstream
    decides which attempt was actually right.
    """
    needed = set(FUEL_TO_CSV.keys())
    for p in image_paths:
        for scale in upscales:
            try:
                words = ocr_tsv(p, upscale=scale)
            except subprocess.CalledProcessError:
                continue
            texts = {w["text"] for w in words}
            seen = {c for c, aliases in LABEL_ALIASES.items()
                    if any(a in texts for a in aliases)}
            if needed.issubset(seen):
                yield f"{p.name}@{scale}x", words


def find_table_image(image_paths: list[Path]) -> tuple[Path, list[dict]] | None:
    """Among a PDF's images, return the one that OCRs to contain all six fuel
    row labels (allowing for the OCR-alias variants in LABEL_ALIASES).
    """
    needed = set(FUEL_TO_CSV.keys())
    for p in image_paths:
        try:
            words = ocr_tsv(p, upscale=4)
        except subprocess.CalledProcessError:
            continue
        texts = {w["text"] for w in words}
        seen = {c for c, aliases in LABEL_ALIASES.items()
                if any(a in texts for a in aliases)}
        if needed.issubset(seen):
            return p, words
    return None


def row_y_anchors(words: list[dict]) -> dict[str, int]:
    """Return {canonical_label: y_center} for each fuel row, using its label word.

    A "row" in the table is identified by its leftmost text cell (Toplam,
    Benzin, …). We take the y-center of that cell as the row anchor; data
    cells are then assigned to the closest anchor.
    """
    anchors: dict[str, int] = {}
    for canon, aliases in LABEL_ALIASES.items():
        for w in words:
            if w["text"] in aliases and canon not in anchors:
                anchors[canon] = w["top"] + w["height"] // 2
                break
    return anchors


def group_by_row(words: list[dict], anchors: dict[str, int],
                 tol_factor: float = 0.6) -> dict[str, list[dict]]:
    """Assign each word to its closest row anchor within a y-tolerance.

    tolerance = max(median_word_height * tol_factor + 5, ...) — chosen wide
    enough to absorb the sub/super-script jitter that tesseract emits but
    tight enough to keep header-row words out of the data rows.
    """
    heights = sorted(w["height"] for w in words if w["height"] > 0)
    median_h = heights[len(heights) // 2] if heights else 50
    tol = int(median_h * tol_factor) + 5

    rows: dict[str, list[dict]] = defaultdict(list)
    for w in words:
        center = w["top"] + w["height"] // 2
        best_label, best_d = None, tol + 1
        for label, ly in anchors.items():
            d = abs(center - ly)
            if d <= tol and d < best_d:
                best_label, best_d = label, d
        if best_label is not None:
            rows[best_label].append(w)
    for r in rows:
        rows[r].sort(key=lambda w: w["left"])
    return rows


def _is_int(t: str) -> bool:
    return t.isdigit()


def _is_pct(t: str) -> bool:
    return bool(_PCT_RE.fullmatch(t))


def join_thousands(int_tokens: list[dict]) -> list[tuple[int, int]]:
    """Re-join consecutive 3-digit continuation tokens into single integers.

    Tesseract emits "81 907" as two tokens ("81", "907") because of the
    thousand-separator whitespace. We rejoin when (a) the horizontal gap is
    small, (b) the line-heights are similar (= same line), and (c) the
    continuation token is exactly three digits long — that's the format
    convention TÜİK uses for everything ≥ 1 000. Returns [(x_centre, value)]
    in column order, the centre spanning the whole joined number.

    Gap threshold = ``max(60, height)`` px (the upscale step blows the image
    up 4×, so a small ~15 px gap at native becomes ~60 px after resize).
    """
    out: list[tuple[int, int]] = []
    cur = ""
    cur_left: int | None = None
    last_right: int | None = None
    last_height: int | None = None

    def flush() -> None:
        if cur:
            out.append(((cur_left + last_right) // 2, int(cur)))

    for t in int_tokens:
        gap = (t["left"] - last_right) if last_right is not None else 9999
        same_line = last_height is None or abs(t["height"] - last_height) <= 8
        if cur and gap <= max(60, t["height"]) and same_line and len(t["text"]) == 3:
            cur += t["text"]
        else:
            flush()
            cur = t["text"]
            cur_left = t["left"]
        last_right = t["left"] + t["width"]
        last_height = t["height"]
    flush()
    return out


def extract_row_values(row_words: list[dict]) -> tuple[list[tuple[int, int]],
                                                       list[tuple[int, float]]]:
    """Split a row's words into count and Pay% tokens, each [(x_centre, value)].

    Positions are carried through rather than discarded, because position — not
    order in the list — is what identifies a column once the OCR has dropped or
    invented a token somewhere in the row.
    """
    ints = [w for w in row_words if _is_int(w["text"])]
    pcts = [w for w in row_words if _is_pct(w["text"])]
    counts = join_thousands(ints)
    pct_vals = [(w["left"] + w["width"] // 2, float(w["text"].replace(",", ".")))
                for w in pcts]
    return counts, pct_vals


def column_anchors(rows_tokens: list[list[tuple[int, float]]],
                   n: int = N_COLS) -> list[float] | None:
    """Derive the x-centre of each of the ``n`` data columns from the rows.

    Rows that produced exactly ``n`` tokens are unambiguous, so they vote: the
    anchor for column *i* is the median x of their *i*-th token. A row that lost
    or gained a token cannot vote, but it can still be read afterwards, because
    values are then matched to columns by position instead of by their index in
    the row — which is the entire point. A dropped token leaves a hole in the
    row it belongs to, rather than shifting every later column by one.

    Falls back to splitting the pooled x-centres at their ``n-1`` largest gaps
    when no two rows survived intact. Returns None if even that cannot produce
    ``n`` non-empty groups; the caller then treats the row as unread rather than
    guessing.
    """
    clean = [t for t in rows_tokens if len(t) == n]
    if len(clean) >= 2:
        return [statistics.median([t[i][0] for t in clean]) for i in range(n)]

    xs = sorted(x for t in rows_tokens for x, _ in t)
    if len(xs) < n:
        return None
    splits = sorted(sorted(range(1, len(xs)), key=lambda i: xs[i] - xs[i - 1],
                           reverse=True)[:n - 1])
    bounds = [0] + splits + [len(xs)]
    groups = [xs[bounds[i]:bounds[i + 1]] for i in range(n)]
    if any(not g for g in groups):
        return None
    return [statistics.median(g) for g in groups]


def assign_columns(tokens: list[tuple[int, float]],
                   anchors: list[float] | None) -> list:
    """Place ``[(x, value)]`` into one slot per anchor, by nearest anchor.

    Two guards make this safe against the OCR's usual mischief. A token further
    than 45 % of the column spacing from every anchor is dropped — that is how a
    Pay% whose decimal comma was lost ("1,3" read as "13") stays out of the
    counts, sitting as it does in the percentage column between two count
    columns. And when two tokens claim one slot, the closer to the anchor wins,
    so a real value at the column centre beats a stray at its edge.
    """
    slots: list = [None] * (len(anchors) if anchors else N_COLS)
    if not anchors:
        return slots
    spacing = min((b - a) for a, b in zip(anchors, anchors[1:])) if len(anchors) > 1 else None
    tol = spacing * 0.45 if spacing else float("inf")
    best: list[float | None] = [None] * len(anchors)
    for x, value in tokens:
        i = min(range(len(anchors)), key=lambda j: abs(x - anchors[j]))
        d = abs(x - anchors[i])
        if d > tol:
            continue
        if best[i] is None or d < best[i]:
            slots[i], best[i] = value, d
    return slots


def parse_table(words: list[dict]) -> dict[str, tuple[list, list]]:
    """Return {fuel_label: (counts, pcts)}, each a fixed N_COLS list.

    A slot is None where the OCR gave us nothing for that column, so callers can
    index by column meaning (COL_MONTH and friends) instead of hoping the row
    came out complete.
    """
    rows = group_by_row(words, row_y_anchors(words))
    per_row = {label: (extract_row_values(rows[label]) if label in rows else ([], []))
               for label in FUEL_TO_CSV}
    count_anchors = column_anchors([c for c, _ in per_row.values()])
    pct_anchors = column_anchors([p for _, p in per_row.values()])
    return {label: (assign_columns(c, count_anchors), assign_columns(p, pct_anchors))
            for label, (c, p) in per_row.items()}


# ---------------------------------------------------------------------------
# Validation + auto-repair
# ---------------------------------------------------------------------------

def validate_and_repair(table: dict[str, tuple[list[int], list[float]]],
                        narr_total: int) -> tuple[dict[str, int], list[tuple]]:
    """Sanity-check the column-1 (current month) values and auto-repair a
    single OCR digit error if the sum disagrees with the Toplam.

    Returns ``(fuel_counts, repairs)`` where ``fuel_counts`` is the validated
    {label: int} for col 1 (including the corrected value, if any) and
    ``repairs`` is a list of ``(label, before, after)`` describing any fixes
    applied. Raises ``RuntimeError`` on unrecoverable mismatch.
    """
    # Rows arrive column-aligned and fixed-length (see parse_table), so a column
    # index means the same period in every row and a gap reads as None instead
    # of pulling the next column into its place.
    counts = {l: c for l, (c, _) in table.items()}
    pcts = {l: p for l, (_, p) in table.items()}

    toplam_c1 = counts.get("Toplam", [None] * N_COLS)[COL_MONTH]
    if toplam_c1 is None:
        raise RuntimeError(
            f"Toplam row has no current-month column: {counts.get('Toplam')}")
    if toplam_c1 != narr_total:
        raise RuntimeError(
            f"OCR Toplam col 1 = {toplam_c1} != narrative monthly total = {narr_total}. "
            "Either we OCR'd the wrong column, or the bulletin's table contents "
            "disagree with its own narrative (would surface a data-publication bug)."
        )

    fuel_labels = ["Benzin", "Hibrit", "Elektrik", "Dizel", "LPG"]
    fuel_counts: dict[str, int | None] = {l: counts[l][COL_MONTH] for l in fuel_labels}
    missing = [l for l, v in fuel_counts.items() if v is None]
    if missing:
        raise RuntimeError(f"Missing col-1 OCR values for: {missing}")

    s = sum(fuel_counts.values())
    repairs: list[tuple] = []
    if s == toplam_c1:
        return {l: int(v) for l, v in fuel_counts.items()}, repairs

    diff = toplam_c1 - s
    # Identify the wrong fuel via Pay% cross-check on the current-month column.
    # A fuel whose Pay% the OCR missed stays out of the line-up entirely rather
    # than being judged against another column's percentage.
    fuel_pct = {l: pcts[l][COL_MONTH] for l in fuel_labels}
    suspects: list[tuple[float, str]] = []
    for l in fuel_labels:
        if fuel_pct[l] is None:
            continue
        expected_ratio = fuel_pct[l] / 100.0
        actual_ratio = fuel_counts[l] / toplam_c1
        err = abs(actual_ratio - expected_ratio) * 100  # percentage points
        suspects.append((err, l))
    suspects.sort(reverse=True)
    if not suspects:
        raise RuntimeError(
            f"Sum mismatch diff={diff} and no Pay% available for repair"
        )
    worst_err, worst_l = suspects[0]
    if worst_err < 0.05:
        # No fuel is far enough from its Pay% to be the obvious culprit;
        # the OCR errors are probably multi-fuel and we can't safely repair.
        raise RuntimeError(
            f"Sum mismatch diff={diff} but no fuel deviates from its Pay% > 0.05% "
            f"(worst: {worst_l} err={worst_err:.3f} pp). Likely multiple OCR "
            "errors — re-fetch the PDF at higher DPI or inspect manually."
        )
    repaired = toplam_c1 - sum(v for l, v in fuel_counts.items() if l != worst_l)
    repaired_pct = round(repaired / toplam_c1 * 100, 1)
    if fuel_pct[worst_l] is not None and abs(repaired_pct - fuel_pct[worst_l]) > 0.05:
        raise RuntimeError(
            f"Sum repair failed Pay% cross-check: would set {worst_l}={repaired} "
            f"(implies {repaired_pct}%) but OCR Pay% = {fuel_pct[worst_l]}%"
        )
    repairs.append((worst_l, fuel_counts[worst_l], repaired))
    fuel_counts[worst_l] = repaired
    return {l: int(v) for l, v in fuel_counts.items()}, repairs


def _csv_float(row: dict, col: str) -> float | None:
    """One CSV cell as a number, or None where the row leaves it blank.

    The early history is hand-curated and sparse — the 2016 rows carry a TOTAL
    and a BEV/HEV estimate but no PETROL/DIESEL/OTHERS at all — so a cross-check
    that assumed every cell parses would crash on exactly the months it was
    supposed to be lenient about.
    """
    raw = (row.get(col) or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def cross_check_prev_year(table: dict[str, tuple[list[int], list[float]]],
                          csv_path: str, target_year: int, target_month: int) -> None:
    """Defence-in-depth: OCR col 0 (prev-year-same-month) must match existing CSV.

    If we mis-identified which OCR column is "current month" — e.g. because the
    label-row parsing wandered — this check will catch it long before we
    overwrite the CSV with garbage. The previous year's row must already be in
    the CSV for this to fire; if it isn't, we log and skip the check rather
    than blocking (the historical CSV is hand-curated and may have gaps).
    """
    prev_period = f"{target_year - 1}-{target_month:02d}"
    if not Path(csv_path).exists():
        return
    prev_row = None
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["period"] == prev_period:
                prev_row = r
                break
    if prev_row is None:
        print(f"  Skipping prev-year cross-check: no {prev_period} row in CSV.")
        return

    counts = {l: c for l, (c, _) in table.items()}
    mismatches, checked = [], 0
    for tr_label, csv_col in FUEL_TO_CSV.items():
        ocr = counts.get(tr_label, [None] * N_COLS)[COL_MONTH_PREV]
        expected = _csv_float(prev_row, csv_col)
        if ocr is None or expected is None:
            continue
        checked += 1
        if abs(ocr - expected) > 0.5:  # CSV stores floats; OCR is int
            mismatches.append((tr_label, csv_col, ocr, expected))
    if mismatches:
        details = ", ".join(
            f"{tr}({col})={ocr}≠{exp:.0f}" for tr, col, ocr, exp in mismatches
        )
        raise RuntimeError(
            f"Prev-year cross-check failed for {prev_period}: {details}. "
            "OCR may have mis-identified the column layout — refusing to write."
        )
    print(f"  Prev-year cross-check OK against CSV row {prev_period} "
          f"({checked}/{len(FUEL_TO_CSV)} rows).")


def cross_check_ytd(table: dict[str, tuple[list, list]], csv_path: str,
                    target_year: int, target_month: int,
                    fuels: dict[str, int], monthly_total: int) -> str:
    """Re-derive the month from the bulletin's year-to-date column, and demand a match.

    Column 3 is Ocak-<Month> <Year>: the running total for the year in progress.
    Subtract the months this CSV already holds for that year and exactly one
    month is left — the one being ingested. That gives a second, independent
    reading of all six numbers, taken from different cells of the table than the
    ones just parsed, and validated against our own committed history rather
    than against the bulletin alone.

    It is the strongest guard available here because it is exact arithmetic: the
    Pay% cross-check can only ever be a ±0.05 pp affair against a rounded
    one-decimal percentage, whereas this either reconciles to the unit or does
    not. Both readings agreeing on all six rows is what makes an ingest
    trustworthy without a human looking at the bulletin.

    Skipped (returning a note) when the CSV's year is incomplete, since the
    subtraction would then be meaningless. Raises on disagreement: either the
    OCR misread a column, or TÜİK revised a month we have already committed —
    and both want a human, not a silent write.
    """
    prior = [f"{target_year}-{m:02d}" for m in range(1, target_month)]
    if not Path(csv_path).exists():
        return "skipped (no CSV yet)"
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = {r["period"]: r for r in csv.DictReader(f)}
    absent = [p for p in prior if p not in rows]
    if absent:
        return f"skipped ({len(absent)} earlier month(s) missing: {', '.join(absent)})"

    # Only genuinely monthly rows may be summed. The oldest part of the series
    # is annual figures spread across twelve identical rows, and adding those up
    # would compare the bulletin against a number TÜİK never published.
    interpolated = [p for p in prior if rows[p].get("time_interval") != "monthly"]
    if interpolated:
        return (f"skipped ({len(interpolated)} earlier row(s) are not monthly: "
                f"{', '.join(interpolated)})")

    read_now = dict(fuels)
    read_now["Toplam"] = monthly_total
    counts = {l: c for l, (c, _) in table.items()}
    mismatches, checked, unusable = [], 0, []
    for tr_label, csv_col in FUEL_TO_CSV.items():
        ytd = counts.get(tr_label, [None] * N_COLS)[COL_YTD]
        if ytd is None or tr_label not in read_now:
            continue
        history = [_csv_float(rows[p], csv_col) for p in prior]
        if any(v is None for v in history):
            unusable.append(csv_col)     # blank cells earlier in the year
            continue
        checked += 1
        implied = ytd - sum(history)
        if abs(implied - read_now[tr_label]) > 0.5:
            mismatches.append((tr_label, csv_col, implied, read_now[tr_label]))
    if not checked:
        return "skipped (no year-to-date column usable)"
    if mismatches:
        details = ", ".join(
            f"{tr}({col}): YTD implies {imp:.0f} but month column read {got}"
            for tr, col, imp, got in mismatches
        )
        raise RuntimeError(
            f"Year-to-date cross-check failed for {target_year}-{target_month:02d}: "
            f"{details}. Either the OCR misread a column, or TÜİK has revised a "
            "month already committed to the CSV. Inspect the bulletin before "
            "writing; --no-ytd-check bypasses this once you have."
        )
    note = (f"OK on {checked}/{len(FUEL_TO_CSV)} rows against "
            f"{len(prior)} committed month(s)")
    if unusable:
        note += f"; {', '.join(unusable)} skipped (blank earlier in the year)"
    return note


# ---------------------------------------------------------------------------
# CSV upsert (preserves CRLF, matching the existing file)
# ---------------------------------------------------------------------------

def upsert_row(csv_path: str, period: str, row: dict, force: bool) -> bool:
    """Insert or replace one row keyed by period. Returns True if file changed.

    Line-ending detection: data/Türkiye.csv is CRLF on disk (committed that
    way historically). Without the sniff, csv.DictWriter would rewrite the
    whole file as LF on the first ingest — same gotcha that bit us on Japan
    and Uruguay. See Flow J / Flow L "Issues hit during development".
    """
    existing: dict[str, dict] = {}
    line_ending = "\n"
    if Path(csv_path).exists():
        with open(csv_path, "rb") as fb:
            head = fb.read(4096)
        if b"\r\n" in head:
            line_ending = "\r\n"
        with open(csv_path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                existing[r["period"]] = r

    if period in existing and not force:
        print(f"  Period {period} already in CSV — not overwriting (use --force).")
        return False

    existing[period] = row
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator=line_ending)
        writer.writeheader()
        for p in sorted(existing.keys()):
            writer.writerow(existing[p])
    return True


# ---------------------------------------------------------------------------
# HTML bulletin parsing (preferred over the PDF/OCR path)
# ---------------------------------------------------------------------------
#
# The API record's `content` field is the complete bulletin as HTML. Where the
# PDF ships the fuel table as a raster image — the sole reason this script ever
# needed pdfimages + tesseract + a digit-level auto-repair heuristic — the HTML
# carries it as real markup, so it can simply be read.
#
# The parser deliberately emits the SAME shape as parse_table(), namely
# {label: (counts, pcts)} in column order, so every existing guard
# (validate_and_repair, cross_check_prev_year, the narrative Toplam check)
# applies unchanged to whichever path produced the numbers.

_TAG_RE = re.compile(r"<[^>]+>")
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.I | re.S)
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.I | re.S)
_B64_RE = re.compile(r'src="data:image/[^"]*"')
# Turkish counts use a space or a dot as the thousands separator ("81 907",
# "81.907"); percentages use a comma decimal ("34,6"). Keeping the two apart is
# what lets a row be split into counts vs Pay(%) exactly like the OCR path.
_INT_CELL_RE = re.compile(r"^\d{1,3}(?:[ . ]\d{3})*$|^\d+$")
_PCT_CELL_RE = re.compile(r"^\d+,\d+$")


def _pad_columns(values: list) -> list:
    """Trim/pad an in-order list of cell values to exactly N_COLS slots."""
    return (list(values) + [None] * N_COLS)[:N_COLS]


def _cell_text(fragment: str) -> str:
    """Strip tags/entities from one cell and normalise whitespace."""
    import html as _html
    text = _html.unescape(_TAG_RE.sub(" ", fragment))
    return " ".join(text.replace(" ", " ").split())


def html_to_text(content_html: str) -> str:
    """De-tagged bulletin text, for the narrative regexes."""
    import html as _html
    return " ".join(_html.unescape(
        _TAG_RE.sub(" ", _B64_RE.sub("", content_html))).split())


_DATA_URI_RE = re.compile(r'src="data:image/[^;]+;base64,([^"]+)"')


def extract_images_from_html(content_html: str, out_dir: Path) -> list[Path]:
    """Decode every base64 data-URI image in the bulletin HTML to a file.

    The fuel table is a raster image in the HTML exactly as it is in the PDF —
    "Benzin" appears nowhere in the markup. But the HTML embeds those images
    inline as data URIs, so the whole OCR pipeline can run without ever
    downloading a PDF, and without needing an id->PDF mapping we do not have.

    The declared mime type is not trustworthy (TÜİK labels JPEG payloads as
    image/png), so the extension comes from the magic bytes instead.
    """
    import base64
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, blob in enumerate(_DATA_URI_RE.findall(content_html)):
        try:
            raw = base64.b64decode(blob, validate=False)
        except Exception:
            continue
        if raw.startswith(b"\xff\xd8\xff"):
            ext = ".jpg"
        elif raw.startswith(b"\x89PNG"):
            ext = ".png"
        else:
            ext = ".bin"
        p = out_dir / f"html-img-{i:03d}{ext}"
        p.write_bytes(raw)
        paths.append(p)
    return paths


def parse_content_tables(content_html: str) -> list[dict[str, tuple[list[int], list[float]]]]:
    """Every table in the bulletin that carries all six fuel-row labels.

    A bulletin contains more than one fuel breakdown — newly registered
    vehicles for the month, and the total registered stock at month end — and
    both use the same row labels. Rather than guess, return each candidate and
    let the caller keep the one whose Toplam matches the narrative monthly
    total; a wrong pick then fails loudly instead of writing plausible garbage.
    """
    stripped = _B64_RE.sub('src=""', content_html)
    candidates = []
    for table_html in re.findall(r"<table[^>]*>(.*?)</table>", stripped, re.I | re.S):
        table: dict[str, tuple[list[int], list[float]]] = {}
        for row_html in _ROW_RE.findall(table_html):
            cells = [_cell_text(c) for c in _CELL_RE.findall(row_html)]
            cells = [c for c in cells if c]
            if not cells:
                continue
            label = next((canon for canon, aliases in LABEL_ALIASES.items()
                          if cells[0] in aliases), None)
            if label is None:
                continue
            counts = [int(c.replace(" ", "").replace(".", "").replace(" ", ""))
                      for c in cells[1:] if _INT_CELL_RE.match(c)]
            pcts = [float(c.replace(",", ".")) for c in cells[1:] if _PCT_CELL_RE.match(c)]
            if counts:
                # Real markup has one cell per column in document order, so the
                # first N_COLS cells are the columns; pad so that downstream code
                # can index by column meaning exactly as it does for the OCR path.
                table[label] = (_pad_columns(counts), _pad_columns(pcts))
        if all(label in table for label in FUEL_TO_CSV):
            candidates.append(table)
    return candidates


def build_row(period: str, fuels: dict[str, int], toplam: int,
              source_url: str) -> dict:
    return {
        "period": period,
        "time_interval": "monthly",
        "variant": "Whole",
        "source": "TUIK",
        "BEV":    float(fuels["Elektrik"]),
        "HEV":    float(fuels["Hibrit"]),
        "PETROL": float(fuels["Benzin"]),
        "DIESEL": float(fuels["Dizel"]),
        "OTHERS": float(fuels["LPG"]),
        "TOTAL":  float(toplam),
        "notes":  source_url,
    }


# Recon is a heavyweight diagnostic (crawls ~40 SPA chunks). It earns its keep
# when the portal changes shape, but a discovery miss is the normal state of
# every cron run before the bulletin is published, so keep it opt-in.
RECON_ON_MISS = os.environ.get("TUIK_RECON") == "1"


def ingest_from_html(record: dict, args, target_year: int, target_month: int,
                     target_period: str, pdf_fallback: bool = False) -> int | None:
    """Write the CSV row straight from the API's HTML bulletin.

    Returns an exit code when the HTML path reached a verdict, or None to let
    the caller fall back to the PDF pipeline. ``pdf_fallback`` says whether that
    fallback can actually reach a bulletin; when it cannot, a table that fails
    validation ends the run here, with the reason it failed.
    """
    content = str(record.get("content") or "")
    if not content:
        return None

    text = html_to_text(content)
    narr = parse_narrative(text)
    if not narr.get("month_num"):
        print("[html] no narrative sentence found in the bulletin HTML")
        return None

    # Same gate as the PDF path: refuse to write if the bulletin is not the
    # month we asked for. `period` already matched during discovery, so this
    # is belt and braces against a record whose prose disagrees with its label.
    if narr["month_num"] != target_month:
        sys.exit(f"Bulletin month is {narr['month_name']} ({narr['month_num']}) "
                 f"but target month is {MONTHS_TR_BY_NUM[target_month]} "
                 f"({target_month}). Refusing to write.")

    # Candidate tables, cheapest source first. Markup would be ideal, but TÜİK
    # ships the fuel table as a raster image in the HTML just as it does in the
    # PDF ("Benzin" appears nowhere in the markup), so in practice the images
    # carry it. They are inline data URIs, so this still needs no PDF.
    candidates = [("markup", t) for t in parse_content_tables(content)]
    print(f"[html] narrative monthly_total={narr['monthly_total']}, "
          f"{len(candidates)} candidate table(s) from markup")

    with tempfile.TemporaryDirectory() as td:
        if not candidates:
            imgs = extract_images_from_html(content, Path(td) / "imgs")
            print(f"[html] OCR fallback: {len(imgs)} inline image(s) "
                  f"({sum(p.stat().st_size for p in imgs) // 1024} KB)")
            for origin, words in iter_fuel_table_images(imgs):
                print(f"[html]   {origin} has all six fuel labels")
                candidates.append((origin, parse_table(words)))

        if not candidates:
            print("[html] no fuel table found in markup or images")
            return None

        # A bulletin carries several fuel breakdowns (this month's
        # registrations, and the registered stock at month end) under identical
        # labels. Keep the one whose Toplam agrees with the narrative total;
        # anything else is the wrong table and would look entirely plausible.
        # Every check runs per candidate, so a table that fails one of them
        # costs us that candidate and not the run — the next upscale may read
        # the same image cleanly.
        rejections: list[str] = []
        for origin, table in candidates:
            try:
                fuels, repairs = validate_and_repair(table, narr["monthly_total"])
                for label, before, after in repairs:
                    print(f"  REPAIR: {label} {before} → {after}")
                cross_check_prev_year(table, args.csv, target_year, target_month)
                if args.no_ytd_check:
                    print("  Year-to-date cross-check disabled (--no-ytd-check).")
                else:
                    print("  Year-to-date cross-check: " + cross_check_ytd(
                        table, args.csv, target_year, target_month,
                        fuels, narr["monthly_total"]))
            except Exception as e:
                rejections.append(f"{origin}: {e}")
                print(f"[html] candidate {origin} rejected: {e}")
                for label, (counts, pcts) in table.items():
                    print(f"[html]     {label:9s} counts={counts} pcts={pcts}")
                continue
            print(f"[html] accepted {origin}: "
                  + ", ".join(f"{l}={v}" for l, v in fuels.items()))
            source_url = TUIK_PRESS_URL.format(id=args.press_id)
            row = build_row(target_period, fuels, narr["monthly_total"], source_url)
            if args.dry_run:
                print(f"\n[dry-run] would write {target_period} to {args.csv}: "
                      + ", ".join(f"{k}={row[k]:.0f}" for k in
                                  ("BEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL")))
                return 0
            if upsert_row(args.csv, target_period, row, args.force):
                print(f"\nWrote {target_period} to {args.csv} (from HTML bulletin)")
            return 0

    # Every candidate failed a check. Unless there is a real PDF to try, say so
    # here rather than returning None: without one the caller can only exit on a
    # message about PDFs, which is what buried the actual cause in the Temmuz
    # 2026 runs — the log blamed the missing id->PDF mapping for what was an
    # OCR validation failure.
    print(f"[html] all {len(candidates)} candidate table(s) failed validation:")
    for r in rejections:
        print(f"[html]   {r}")
    if pdf_fallback:
        return None
    sys.exit(
        f"Found the {MONTHS_TR_BY_NUM[target_month]} {target_year} bulletin "
        f"(press id {args.press_id}) but could not read its fuel table with "
        "confidence. Refusing to write a row that did not validate."
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int)
    parser.add_argument("--month", type=int, choices=range(1, 13))
    parser.add_argument("--press-id", type=int,
                        help="TÜİK bulletin Sayı (numeric id); fetched from veriportali.tuik.gov.tr/tr/press/<id>")
    parser.add_argument("--pdf-url", help="Direct URL to a press PDF")
    parser.add_argument("--pdf-path", help="Local path to a press PDF (offline testing)")
    parser.add_argument("--csv", default="data/Türkiye.csv")
    parser.add_argument("--force", action="store_true",
                        help="Re-process even if target period already exists")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and validate but never write the CSV. Use it to "
                             "re-read an already-committed month and confirm the "
                             "parser still reproduces it.")
    parser.add_argument("--no-ytd-check", action="store_true",
                        help="Skip the year-to-date cross-check. Only for the case "
                             "where TÜİK has revised a month already in the CSV and "
                             "the divergence has been checked by hand.")
    args = parser.parse_args()

    # Target month: previous calendar month unless overridden. Whether it was
    # named explicitly decides how loudly a discovery miss is reported below.
    explicit_month = bool(args.year and args.month)
    if explicit_month:
        target_year, target_month = args.year, args.month
    elif args.year or args.month:
        sys.exit("--year and --month must be given together")
    else:
        target_year, target_month = previous_month(date.today())
    target_period = f"{target_year}-{target_month:02d}"
    print(f"Target period: {target_period} ({MONTHS_TR_BY_NUM[target_month]} {target_year})")

    # Self-throttle: skip if CSV already covers the target. A dry run is asking
    # to re-read a month we already have, so it must not throttle itself out.
    if not args.force and not args.dry_run:
        latest = latest_period(args.csv)
        if latest and latest >= target_period:
            print(f"Latest period in CSV is {latest} ≥ {target_period} — nothing to do.")
            return 0

    # Decide PDF source. An explicit --pdf-path / --pdf-url / --press-id always
    # wins; with none of them we try to auto-discover the bulletin for the
    # target month (see scripts/tuik_discover.py for why that is not trivial).
    sources = [args.pdf_path, args.pdf_url, args.press_id]
    if sum(1 for s in sources if s) > 1:
        sys.exit("Pass only one of --press-id, --pdf-url, --pdf-path")

    discovered = None
    if sum(1 for s in sources if s) == 0:
        import tuik_discover

        discovered = tuik_discover.discover(target_year, target_month, verbose=True)
        if not discovered or not (discovered.pdf_url or discovered.press_id):
            # Dump the recon so a genuine portal change is diagnosable straight
            # from the run log instead of needing a local repro (which the
            # sandbox can't do — *.tuik.gov.tr is blocked by egress policy).
            print("Auto-discovery found no bulletin for "
                  f"{MONTHS_TR_BY_NUM[target_month]} {target_year}.")
            if RECON_ON_MISS:
                import requests
                tuik_discover.recon(requests.Session(), target_year, target_month)
            # A miss means two different things. On the daily cron, targeting
            # last month by default, it is the ordinary state before TÜİK
            # publishes — exit 0 and try again tomorrow. But when a month was
            # named explicitly, someone asked for that bulletin, and "could not
            # find it" is a failure however calmly it prints. Exiting 0 there
            # made a backfill that never looked at anything read as a green run.
            if explicit_month:
                sys.exit(
                    f"No bulletin found for {MONTHS_TR_BY_NUM[target_month]} "
                    f"{target_year}, which was requested explicitly. Discovery "
                    "scans a bounded id window around the newest press id in "
                    "the CSV; a month far outside that window needs --press-id "
                    "or --pdf-url. Set recon=true for the portal dump."
                )
            return 0
        args.press_id = discovered.press_id

        # Preferred path: the discovered record already carries the bulletin as
        # HTML, so the numbers can be read directly — no PDF download, no
        # pdfimages, no OCR, no digit-level repair heuristic.
        if discovered.record:
            rc = ingest_from_html(discovered.record, args, target_year,
                                  target_month, target_period,
                                  pdf_fallback=bool(discovered.pdf_url))
            if rc is not None:
                return rc
            print("[html] could not use the HTML bulletin; falling back to PDF")

    if args.pdf_path:
        pdf_src = args.pdf_path
    elif args.pdf_url:
        pdf_src = args.pdf_url
    elif discovered and discovered.pdf_url:
        pdf_src = discovered.pdf_url
    else:
        # Long-standing bug, fixed here: this branch used to hand
        # TUIK_PRESS_URL to load_pdf_bytes(). That URL serves the SPA shell,
        # so pypdf got "<!doc" as its PDF header and died with
        # PdfStreamError — meaning --press-id could never have worked on its
        # own. It was never noticed because the workflow was only ever
        # dispatched without an id. There is no id->PDF mapping known, so say
        # so instead of downloading HTML and calling it a PDF.
        sys.exit(
            f"--press-id {args.press_id} alone cannot locate a PDF: "
            f"{TUIK_PRESS_URL.format(id=args.press_id)} serves the SPA shell, "
            "not the bulletin. Pass --pdf-url (or --pdf-path) for the PDF "
            "route, or let auto-discovery use the HTML bulletin instead."
        )

    # Materialise the PDF to a local file (pdfimages/pypdf both want a path).
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        if args.pdf_path:
            pdf_local = pdf_src
        else:
            pdf_local = str(td / "bulletin.pdf")
            with open(pdf_local, "wb") as f:
                f.write(load_pdf_bytes(pdf_src))

        text = pdf_text(pdf_local)
        narr = parse_narrative(text)
        if not narr.get("month_num"):
            sys.exit(f"Could not find '<Month> ayında … otomobilin trafiğe kaydı yapıldı' "
                     f"in the PDF narrative. Wrong PDF?")
        print(f"Narrative: month={narr['month_name']} ({narr['month_num']}), "
              f"monthly_total={narr['monthly_total']}, ytd_total={narr.get('ytd_total')}")

        # Sanity: narrative month must match target. Catches "user passed
        # the wrong press-id" before we write a row to the wrong period.
        if narr["month_num"] != target_month:
            sys.exit(
                f"Bulletin month is {narr['month_name']} ({narr['month_num']}) "
                f"but target month is {MONTHS_TR_BY_NUM[target_month]} "
                f"({target_month}). Refusing to write."
            )

        imgs = extract_images(pdf_local, td / "imgs")
        found = find_table_image(imgs)
        if not found:
            sys.exit(
                "Could not find an embedded image whose OCR contains all six "
                "fuel-row labels. The bulletin layout may have changed."
            )
        img_path, words = found
        print(f"Table image: {img_path.name}")
        table = parse_table(words)

        fuels, repairs = validate_and_repair(table, narr["monthly_total"])
        if repairs:
            for label, before, after in repairs:
                print(f"  REPAIR: {label} {before} → {after} (sum-check + Pay% cross-check)")
        cross_check_prev_year(table, args.csv, target_year, target_month)
        if args.no_ytd_check:
            print("  Year-to-date cross-check disabled (--no-ytd-check).")
        else:
            print("  Year-to-date cross-check: " + cross_check_ytd(
                table, args.csv, target_year, target_month,
                fuels, narr["monthly_total"]))

        print(f"  Parsed col-1 values: Toplam={narr['monthly_total']}, "
              + ", ".join(f"{l}={v}" for l, v in fuels.items()))

        source_url = (args.pdf_url
                      or (TUIK_PRESS_URL.format(id=args.press_id) if args.press_id else "")
                      or pdf_src)
        row = build_row(target_period, fuels, narr["monthly_total"], source_url)
        if args.dry_run:
            print(f"\n[dry-run] would write {target_period} to {args.csv}: "
                  + ", ".join(f"{k}={row[k]:.0f}" for k in
                              ("BEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL")))
            return 0
        if upsert_row(args.csv, target_period, row, args.force):
            print(f"\nWrote {target_period} to {args.csv}")
        else:
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
