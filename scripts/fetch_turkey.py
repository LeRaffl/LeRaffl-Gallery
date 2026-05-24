#!/usr/bin/env python3
"""
Fetch Türkiye vehicle registration data from TÜİK and update data/Türkiye.csv.

Usage
-----
    python scripts/fetch_turkey.py [--year YEAR] [--month MONTH] \
        [--press-id ID] [--pdf-url URL] [--pdf-path PATH] \
        [--csv PATH] [--force]

* --year / --month  Override the target month (default: previous calendar month).
* --press-id        TÜİK bulletin Sayı (e.g. 58042 for Nisan 2026).
* --pdf-url         Direct URL to the press PDF (mutually exclusive with --press-id).
* --pdf-path        Local path to a press PDF (for offline testing / re-runs).
* --csv             Target CSV (default: data/Türkiye.csv).
* --force           Re-process even if the target period already exists.

Invoked by .github/workflows/fetch-turkey.yml on a daily cron from the 15th of
each month onward, plus manual workflow_dispatch. When the CSV changes, the
workflow commits data/Türkiye.csv and triggers render-country.yml for Türkiye.

Data source
-----------
TÜİK (Türkiye İstatistik Kurumu — Turkish Statistical Institute) publishes
"Motorlu Kara Taşıtları" *(Motor Land Vehicles)* monthly bulletins on their
Veri Portalı *(Data Portal)*:

    https://veriportali.tuik.gov.tr/tr/press/<id>

where <id> is a TÜİK-wide sequential bulletin number (e.g. 58041 = Mart 2026,
58042 = Nisan 2026, ~32 days apart but with many other TÜİK bulletins in
between). Each press release is a 5-page bulletin in Turkish, with the fuel
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

4. Three layers of validation on the parsed col-1 numbers:
       (a) OCR Toplam[col 1] == narrative monthly_total       (hard fail)
       (b) Sum(Benzin..LPG, col 1) == Toplam[col 1]            (auto-repair if off)
       (c) Each fuel's count/Toplam == OCR'd Pay % (col 1) ±0.05 %  (used to
           identify the single wrong fuel during repair)

   Auto-repair: if (b) fails by `diff` and exactly one fuel's count is >0.05 %
   off from its OCR'd Pay %, set that fuel = Toplam - sum(others) and re-check
   the implied Pay % matches OCR'd Pay % to within 0.05 %. This catches single-
   digit OCR misreads (observed in dev: "27 715" instead of "27 775" for Mart
   2026 Hibrit, caused by a low-res rasterised image — see "Issues hit").
   Multi-fuel mismatches hard-fail rather than silently mis-correct.

5. Defence in depth: also cross-check OCR'd Toplam[col 0] (the previous-year
   same-month total) against the corresponding row already present in
   data/Türkiye.csv. This catches column-shift bugs that would otherwise pass
   (a)-(c).

Auto-discovery (intentionally not implemented yet)
--------------------------------------------------
The Veri Portalı is a React SPA: the press page URL returns an empty
``<div id="root"></div>`` shell and the data is hydrated client-side via an
undocumented JSON API. Plain HTML scraping would only see the shell, and we
haven't reverse-engineered the API. For now the workflow accepts the
``press_id`` (or a direct ``pdf_url``) via workflow_dispatch and the script
hard-requires one of them; the daily cron only does the self-throttle check
and exits cleanly when no ID is supplied. The maintainer manually dispatches
once per month when the new bulletin appears (footnoted in each bulletin:
"Bu konu ile ilgili bir sonraki haber bülteninin yayımlanma tarihi ... 'dır").

Following the project rule we only ever write the most recent month; older
rows are never touched even if a later bulletin would adjust them.

CI dependencies
---------------
Beyond Python (pypdf), the script shells out to:
    * pdfimages   (poppler-utils)  — extract embedded raster tables
    * convert     (imagemagick)    — upscale 4× before OCR
    * tesseract   (+ tesseract-ocr-tur) — OCR the table image

These are all installed in the fetch-turkey.yml workflow step.
"""
import argparse
import csv
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import date
from pathlib import Path

from pypdf import PdfReader

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
    """Concatenate every page's text via pypdf for narrative parsing."""
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
    convention TÜİK uses for everything ≥ 1 000. Returns [(left_x, value)]
    in column order.

    Gap threshold = ``max(60, height)`` px (the upscale step blows the image
    up 4×, so a small ~15 px gap at native becomes ~60 px after resize).
    """
    out: list[tuple[int, int]] = []
    cur = ""
    cur_left: int | None = None
    last_right: int | None = None
    last_height: int | None = None
    for t in int_tokens:
        gap = (t["left"] - last_right) if last_right is not None else 9999
        same_line = last_height is None or abs(t["height"] - last_height) <= 8
        if cur and gap <= max(60, t["height"]) and same_line and len(t["text"]) == 3:
            cur += t["text"]
        else:
            if cur:
                out.append((cur_left, int(cur)))
            cur = t["text"]
            cur_left = t["left"]
        last_right = t["left"] + t["width"]
        last_height = t["height"]
    if cur:
        out.append((cur_left, int(cur)))
    return out


def extract_row_values(row_words: list[dict]) -> tuple[list[int], list[float]]:
    """Split a row's words into count tokens and Pay% tokens, both in column order."""
    ints = [w for w in row_words if _is_int(w["text"])]
    pcts = [w for w in row_words if _is_pct(w["text"])]
    counts = [v for _, v in join_thousands(ints)]
    pct_vals = [float(w["text"].replace(",", ".")) for w in pcts]
    return counts, pct_vals


def parse_table(words: list[dict]) -> dict[str, tuple[list[int], list[float]]]:
    """Return {fuel_label: (counts_in_col_order, pcts_in_col_order)}."""
    anchors = row_y_anchors(words)
    rows = group_by_row(words, anchors)
    table: dict[str, tuple[list[int], list[float]]] = {}
    for label in FUEL_TO_CSV:
        if label in rows:
            table[label] = extract_row_values(rows[label])
        else:
            table[label] = ([], [])
    return table


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
    # First-four-tokens cap: the OCR sometimes emits a stray trailing integer
    # (e.g. a fragment of a percentage), giving a row 5+ counts when there are
    # only 4 real columns. The four columns we care about are always the first.
    counts = {l: vs[:4] for l, (vs, _) in table.items()}
    pcts = {l: ps[:4] for l, (_, ps) in table.items()}

    if len(counts.get("Toplam", [])) < 2:
        raise RuntimeError(f"Toplam row has < 2 columns: {counts.get('Toplam')}")
    toplam_c1 = counts["Toplam"][1]
    if toplam_c1 != narr_total:
        raise RuntimeError(
            f"OCR Toplam col 1 = {toplam_c1} != narrative monthly total = {narr_total}. "
            "Either we OCR'd the wrong column, or the bulletin's table contents "
            "disagree with its own narrative (would surface a data-publication bug)."
        )

    fuel_labels = ["Benzin", "Hibrit", "Elektrik", "Dizel", "LPG"]
    fuel_counts: dict[str, int | None] = {
        l: (counts[l][1] if len(counts[l]) > 1 else None) for l in fuel_labels
    }
    missing = [l for l, v in fuel_counts.items() if v is None]
    if missing:
        raise RuntimeError(f"Missing col-1 OCR values for: {missing}")

    s = sum(fuel_counts.values())
    repairs: list[tuple] = []
    if s == toplam_c1:
        return {l: int(v) for l, v in fuel_counts.items()}, repairs

    diff = toplam_c1 - s
    # Identify the wrong fuel via Pay% cross-check on col 1.
    fuel_pct = {l: (pcts[l][1] if len(pcts[l]) > 1 else None) for l in fuel_labels}
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

    counts = {l: vs[:4] for l, (vs, _) in table.items()}
    fields = {
        "Toplam":   ("TOTAL",  float(prev_row["TOTAL"])),
        "Benzin":   ("PETROL", float(prev_row["PETROL"])),
        "Hibrit":   ("HEV",    float(prev_row["HEV"])),
        "Elektrik": ("BEV",    float(prev_row["BEV"])),
        "Dizel":    ("DIESEL", float(prev_row["DIESEL"])),
        "LPG":      ("OTHERS", float(prev_row["OTHERS"])),
    }
    mismatches = []
    for tr_label, (csv_col, expected) in fields.items():
        if not counts.get(tr_label):
            continue
        ocr = counts[tr_label][0]
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
    print(f"  Prev-year cross-check OK against CSV row {prev_period}.")


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
    args = parser.parse_args()

    # Target month: previous calendar month unless overridden.
    if args.year and args.month:
        target_year, target_month = args.year, args.month
    elif args.year or args.month:
        sys.exit("--year and --month must be given together")
    else:
        target_year, target_month = previous_month(date.today())
    target_period = f"{target_year}-{target_month:02d}"
    print(f"Target period: {target_period} ({MONTHS_TR_BY_NUM[target_month]} {target_year})")

    # Self-throttle: skip if CSV already covers the target.
    if not args.force:
        latest = latest_period(args.csv)
        if latest and latest >= target_period:
            print(f"Latest period in CSV is {latest} ≥ {target_period} — nothing to do.")
            return 0

    # Decide PDF source. The auto-discovery story is documented in the module
    # docstring; without one of these inputs we can't proceed.
    sources = [args.pdf_path, args.pdf_url, args.press_id]
    if sum(1 for s in sources if s) == 0:
        print(
            "No --press-id, --pdf-url, or --pdf-path supplied. The Veri Portalı "
            "is an SPA and we don't yet auto-discover bulletin IDs — dispatch "
            "this workflow manually with the press_id input once TÜİK publishes "
            "the new bulletin (footnoted in the previous one as "
            "'Bu konu ile ilgili bir sonraki haber bülteninin yayımlanma tarihi …')."
        )
        return 0
    if sum(1 for s in sources if s) > 1:
        sys.exit("Pass only one of --press-id, --pdf-url, --pdf-path")

    if args.pdf_path:
        pdf_src = args.pdf_path
    elif args.pdf_url:
        pdf_src = args.pdf_url
    else:
        pdf_src = TUIK_PRESS_URL.format(id=args.press_id)

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

        print(f"  Parsed col-1 values: Toplam={narr['monthly_total']}, "
              + ", ".join(f"{l}={v}" for l, v in fuels.items()))

        source_url = (args.pdf_url
                      or (TUIK_PRESS_URL.format(id=args.press_id) if args.press_id else "")
                      or pdf_src)
        row = build_row(target_period, fuels, narr["monthly_total"], source_url)
        if upsert_row(args.csv, target_period, row, args.force):
            print(f"\nWrote {target_period} to {args.csv}")
        else:
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
