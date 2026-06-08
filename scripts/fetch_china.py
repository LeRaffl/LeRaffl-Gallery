#!/usr/bin/env python3
"""
Fetch China vehicle sales data from CPCA and update data/China.csv plus
data/China_Wholesale.csv.

See docs/architecture/24-source-china.md for the high-level playbook (tracks,
the OCR pipeline, the ws-proportional fallback, manual overrides, and the
May-2026 mis-OCR postmortem). This docstring covers the low-level parsing.

Usage
-----
    python scripts/fetch_china.py [--year YEAR] [--month MONTH] \\
        [--url URL] [--id ID] [--html-path PATH] \\
        [--csv PATH] [--wholesale-csv PATH] [--force]

* --year / --month  Override target month (default: previous calendar month).
* --url             Direct URL of the monthly analysis detail page
                    (https://www.cpcaauto.com/newslist.php?types=csjd&id=NNNN).
                    Overrides --id and listing discovery.
* --id              Numeric `id` parameter of the detail page (e.g. 4179 for
                    March 2026). Overrides listing discovery.
* --html-path       Local HTML file of the detail page (for offline testing).
* --csv             Retail target CSV (default: data/China.csv).
* --wholesale-csv   Wholesale target CSV (default: data/China_Wholesale.csv).
* --force           Re-process even if the target period already exists.

Invoked by .github/workflows/fetch-china.yml on a daily cron at 11:00 UTC
from the 1st onward. The script self-throttles via the latest period
already present in each CSV: it exits cleanly when there is nothing new
to fetch.

Data source
-----------
CPCA (全国乘用车市场信息联席会 / China Passenger Car Association) publishes
a monthly market analysis ("【月度分析】YYYY年M月份全国乘用车市场分析") on:

    https://www.cpcaauto.com/news.php?types=csjd&anid=129&nid=24

Each monthly analysis links to a detail page:

    https://www.cpcaauto.com/newslist.php?types=csjd&id=<id>

where <id> is a CPCA-internal sequential ID. The detail page is an HTML
article in Chinese that reports both retail (零售) and wholesale (批发)
aggregates in narrative form, with the headline figures in `XXX.X万辆`
notation.

Two metric tracks
-----------------
CPCA distinguishes two sales tracks:

* **Retail (零售)** — what reaches end consumers in mainland China during
  the calendar month. This is what historical data/China.csv tracks.
* **Wholesale (批发)** — what manufacturers ship to dealers (including
  exports and inventory buildup). Higher than retail by 20-40%; CPCA
  reports it separately. We capture it into data/China_Wholesale.csv
  for a separate downstream model.

The article reports:

    Retail:    全国乘用车市场零售 X万辆          → TOTAL
               新能源乘用车市场零售 Y万辆          → NEV aggregate
               常规燃油乘用车零售 Z万辆           → ICE
    Wholesale: 乘用车厂商批发 X'万辆              → TOTAL
               新能源乘用车批发 Y'万辆             → NEV aggregate
               纯电动批发销量 X'万辆               → BEV
               狭义插混销量 Y'万辆                 → PHEV (narrow PHEV)
               增程式批发 Z'万辆                   → EREV
               常规燃油乘用车批发销量 W'万辆       → ICE

Retail BEV/PHEV/EREV split
--------------------------
CPCA does NOT publish a direct retail-side BEV/PHEV/EREV breakdown in the
monthly analysis article — only the NEV aggregate. We derive the retail
split by applying the wholesale BEV/PHEV/EREV mix to the retail NEV total:

    retail_bev  = retail_nev * (ws_bev  / ws_nev)
    retail_phev = retail_nev * (ws_phev / ws_nev)
    retail_erev = retail_nev * (ws_erev / ws_nev)

This matches the pattern observed in historical data/China.csv rows
(including their non-integer values, e.g. PHEV=344083.04 / EREV=99916.95
in 2024-08).

CSV columns
-----------
Both CSVs share the China column set:

    period,time_interval,variant,source,BEV,PHEV,EREV,OTHERS,ICE,TOTAL,notes

OTHERS is always 0 — CPCA's "常规燃油" already covers HEV + petrol + diesel +
LPG (everything non-NEV). variant is "Whole" for retail and "Wholesale" for
wholesale.

CPCA back-revisions
-------------------
CPCA typically also revises the prior month inside each new release. We
therefore upsert BOTH the target month AND the prior month if the article
text still mentions prior-month numbers — but the prior month is not always
restated in narrative form, so we only overwrite when we can extract a
complete row.

HTTP details
------------
www.cpcaauto.com returns HTTP 403 to bare requests; we send a desktop-Chrome
User-Agent plus a Referer header pointing at the CPCA root, which suffices.
"""
import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

LISTING_URL = "https://www.cpcaauto.com/news.php?types=csjd&anid=129&nid=24"
DETAIL_URL_TMPL = "https://www.cpcaauto.com/newslist.php?types=csjd&id={id}"

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.cpcaauto.com/",
}

CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "EREV", "OTHERS", "ICE", "TOTAL", "notes",
]

RETAIL_SOURCE = (
    "CPCA (PHEV excludes EREV from 2025-01-01 onwards if not specified differently)"
)
WHOLESALE_SOURCE = (
    "CPCA wholesale (PHEV excludes EREV)"
)


def fetch(url: str) -> str:
    resp = requests.get(url, headers=HTTP_HEADERS, timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def find_detail_id(listing_html: str, year: int, month: int) -> int | None:
    """Locate the detail-page id for the given YYYY-MM in the listing HTML.

    Looks for an `<a>` whose text matches "YYYY年M月份全国乘用车市场分析"
    (e.g. "【月度分析】2026年3月份全国乘用车市场分析") and extracts the
    `id=NNNN` from its href.
    """
    soup = BeautifulSoup(listing_html, "html.parser")
    needle = re.compile(rf"{year}\s*年\s*{month}\s*月份全国乘用车市场分析")
    id_pat = re.compile(r"[?&]id=(\d+)")
    for a in soup.find_all("a", href=True):
        if needle.search(a.get_text(strip=True)):
            m = id_pat.search(a["href"])
            if m:
                return int(m.group(1))
    return None


# Narrative extractors. Each regex must match the article body, where
# numbers are written as "XXX.X万辆". The values returned are in absolute
# units (万 = 10,000).

def _wan(num_str: str) -> float:
    return float(num_str) * 10_000


# Each pattern matches a CPCA narrative phrase like
#   "3月狭义插混批发销量47.6万辆"
# where the metric name is followed by 0-8 chars of filler verbs/qualifiers
# (批发, 销量, 达到, 市场, etc.) before the number. We keep the filler tight
# to avoid spanning across sentences.
_NUM = r"([\d.]+)"
_GAP = r"[^\d]{0,8}"

# Retail patterns
RX_RT_TOTAL = re.compile(rf"全国乘用车市场零售{_GAP}{_NUM}万辆")
RX_RT_NEV = re.compile(rf"新能源乘用车{_GAP}零售{_GAP}{_NUM}万辆")
RX_RT_ICE = re.compile(rf"常规燃油(?:乘用)?车{_GAP}零售{_GAP}{_NUM}万辆")

# Wholesale patterns
RX_WS_TOTAL = re.compile(rf"乘用车厂商批发{_GAP}{_NUM}万辆")
RX_WS_NEV = re.compile(rf"新能源乘用车批发{_GAP}{_NUM}万辆")
RX_WS_BEV = re.compile(rf"纯电动批发{_GAP}{_NUM}万辆")
RX_WS_PHEV = re.compile(rf"狭义插混{_GAP}{_NUM}万辆")
RX_WS_EREV = re.compile(rf"增程式批发{_GAP}{_NUM}万辆")
RX_WS_ICE = re.compile(rf"常规燃油(?:乘用)?车批发{_GAP}{_NUM}万辆")


def _grab(pat: re.Pattern, text: str) -> float | None:
    m = pat.search(text)
    return _wan(m.group(1)) if m else None


# ----------------------------------------------------------------------
# OCR of the embedded NEV retail/export table.
#
# CPCA's monthly analysis is rendered server-side as an HTML article that
# embeds ~10 JPG slides (admin/ewebeditor/uploadfile/*.jpg). One of those
# slides — typically around page 6 of the deck — carries a structured
# "新能源市场 - YYYY年M月零售、出口分析表" table with explicit retail and
# export breakdowns by fuel (BEV / PHEV / EREV / NEV). The article narrative
# DOES NOT restate the retail BEV/PHEV/EREV split, so this table is our only
# direct source for those values.
#
# We OCR each candidate image with the Simplified-Chinese model
# (`tesseract -l chi_sim+eng`) at a 6× upscale: although the data cells are
# Latin/numeric, pure `-l eng` mis-segments this teal-banded table and garbles
# the digits (63.7/22.8/8.5/95.0 → "3 45 55.6 7"). The Chinese model anchors
# the table structure so the numbers come out clean. See OCR_CONFIGS for the
# full retry ladder. Decimal points are sometimes dropped by OCR ("57.9" →
# "579"); we recover them by enforcing BEV+PHEV+EREV ≈ NEV on the matched row,
# which also validates that a given OCR config read the right table.
# ----------------------------------------------------------------------

def _have_tesseract() -> bool:
    return shutil.which("tesseract") is not None


def collect_image_urls(html: str, base_url: str | None = None) -> list[str]:
    """Return absolute URLs of all uploaded JPGs embedded in the detail page."""
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    for img in soup.find_all("img", src=True):
        src = img["src"]
        if "upload" not in src.lower():
            continue
        if base_url:
            src = urljoin(base_url, src)
        elif src.startswith("/"):
            src = urljoin("https://www.cpcaauto.com/", src)
        urls.append(src)
    return urls


# OCR configs tried (in order) per slide image until the retail row validates
# against the article NEV total. CPCA's NEV-market table is a teal-banded
# 960×540 JPEG; pure `eng` mis-segments the digit cells and garbles the row
# (e.g. 63.7/22.8/8.5/95.0 → "3 45 55.6 7"). Loading the Simplified-Chinese
# model (chi_sim+eng) lets tesseract segment the table correctly, and a 6×
# upscale gives the small digits enough resolution. We keep 4× chi_sim and the
# legacy 4× eng as cheaper fallbacks; the NEV cross-check rejects any config
# whose output doesn't reconcile, so trying several is safe.
OCR_CONFIGS = [
    (6, "chi_sim+eng"),
    (5, "chi_sim+eng"),
    (4, "chi_sim+eng"),
    (4, "eng"),
]


def _ocr_image_bytes(jpg_bytes: bytes, scale: int = 6, lang: str = "chi_sim+eng") -> str:
    """Run tesseract on a JPG byte string and return the OCR text.

    `scale` upsamples the 960×540 slide before OCR (small digits read far more
    reliably enlarged); `lang` selects the tesseract model(s). Defaults match
    OCR_CONFIGS[0] — the configuration that reads CPCA's NEV table cleanly.
    Returns "" if the requested language pack is missing or tesseract fails.
    """
    from PIL import Image  # lazy import — only needed when OCR runs
    from io import BytesIO

    with tempfile.TemporaryDirectory() as tmp:
        img = Image.open(BytesIO(jpg_bytes))
        big = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
        png_path = Path(tmp) / "page.png"
        out_path = Path(tmp) / "ocr"
        big.save(png_path)
        try:
            subprocess.run(
                [
                    "tesseract", str(png_path), str(out_path),
                    "-l", lang, "--psm", "6",
                    "-c", "preserve_interword_spaces=1",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return ""
        return (Path(str(out_path) + ".txt")).read_text(encoding="utf-8", errors="replace")


def _recover_decimal(tokens: list[str], nev_target: float) -> list[float] | None:
    """Given 4 OCR tokens for BEV / PHEV / EREV / NEV and the expected NEV
    (从 article narrative), recover the implied decimal point on tokens that
    OCR'd without one.

    Tesseract drops decimal points on this layout fairly often: 57.9 → 579,
    23.2 → 232. All values here are 万-units in the 0.1 – 999.9 range, so
    if a token has no decimal and ÷10 makes BEV+PHEV+EREV match NEV, that
    is almost certainly the correct interpretation.
    """
    if len(tokens) != 4:
        return None

    def candidates(tok: str) -> list[float]:
        if "." in tok:
            try:
                return [float(tok)]
            except ValueError:
                return []
        if not tok.isdigit():
            return []
        n = int(tok)
        if n == 0:
            return [0.0]
        # If the integer is "small" (1-2 digits), it could be either
        # X (e.g. 7 → 7.0) or X.Y with the decimal eaten (e.g. 79 → 7.9).
        # Always offer both forms; validation picks the right one.
        out = [float(n)]
        if n >= 10:
            out.append(n / 10.0)
        if n >= 100:
            out.append(n / 100.0)
        return out

    # Sanity: NEV should match the article-provided total.
    nev_cands = candidates(tokens[3])
    best = None
    best_err = None
    import itertools
    for bev, phev, erev, nev in itertools.product(
        candidates(tokens[0]), candidates(tokens[1]),
        candidates(tokens[2]), nev_cands,
    ):
        # NEV row must match the article aggregate within 1万.
        if abs(nev - nev_target) > 1.0:
            continue
        diff = abs((bev + phev + erev) - nev)
        if diff <= 1.0 and (best is None or diff < best_err):
            best = [bev, phev, erev, nev]
            best_err = diff
    return best


def _merge_split_decimals(tokens: list[str], month: int) -> list[str]:
    """Merge OCR-split decimals like ["37", "8"] → "37.8".

    Tesseract occasionally reads the decimal point as inter-word whitespace
    (especially on small 9-pt slide text), splitting "37.8" into two tokens.
    We detect the pattern — plain integer followed by a single-digit integer
    — and rejoin with a literal dot. Tokens that already carry a decimal,
    or that are 2+ digits on the right, are left alone.

    Single-digit tokens equal to the current month are NOT merged: those are
    the export-half month label ("2A" → token "2") between the retail and
    export sub-tables, and must remain a separate token so the caller can
    drop them in the next step.
    """
    out: list[str] = []
    i = 0
    while i < len(tokens):
        cur = tokens[i]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if (
            nxt is not None
            and "." not in cur
            and cur.lstrip("-").isdigit()
            and len(nxt) == 1
            and nxt.isdigit()
            and nxt != str(month)
        ):
            out.append(f"{cur}.{nxt}")
            i += 2
        else:
            out.append(cur)
            i += 1
    return out


def _extract_retail_from_ocr(text: str, month: int, nev_target_wan: float) -> tuple[list[float], str] | None:
    """Scan an OCR text for the target-month retail row.

    Returns (recovered_values, raw_line) or None. recovered_values is a
    [BEV, PHEV, EREV, NEV] list in 万-units.
    """
    # Row labels in the CPCA slide appear in two styles, both rendered as
    # mojibake under -l eng:
    #   "1月份"  / "12月份"            → OCR "1A" / "12A" / "12A8"
    #   "26年1月份" / "25年12月份"    → OCR "261A" / "25412A"
    # The pattern tolerates a greedy leading-digit "year" prefix (regex
    # backtracking lands on the right split) and one trailing junk
    # digit/letter after the "A" (e.g. the "8" in "12A8" — a misread "份").
    month_label = re.compile(
        rf"^\s*(?:\d+\s*年?\s*)?[^\d]{{0,4}}{month}\s*[A-Za-z月][A-Za-z月\d]?"
    )
    for line in text.splitlines():
        m = month_label.match(line)
        if not m:
            continue
        rest = line[m.end():]
        tokens = re.findall(r"-?\d+(?:\.\d+)?%?", rest)
        tokens = [t for t in tokens if not t.endswith("%")]
        tokens = _merge_split_decimals(tokens, month)
        # The export half repeats "<month>月" / "<month>A" mid-line; that
        # leading "<month>" lands in our token stream as a spurious 5th value.
        # Drop any standalone "{month}" that immediately follows the retail half.
        if len(tokens) >= 5 and tokens[4] == str(month):
            tokens = tokens[:4] + tokens[5:]
        if len(tokens) < 8:
            print(f"  DEBUG OCR: month label matched but only {len(tokens)} tokens: {tokens}")
            continue
        recovered = _recover_decimal(tokens[:4], nev_target_wan)
        if recovered is None:
            print(f"  DEBUG OCR: decimal recovery failed — tokens={tokens[:4]}, nev_target={nev_target_wan}")
            continue
        return recovered, line
    return None


def parse_retail_table(
    image_urls: list[str],
    session: requests.Session,
    month: int,
    nev_target_wan: float,
) -> dict | None:
    """OCR each candidate image until we find the NEV market retail+export
    table, then return the retail BEV / PHEV / EREV / NEV for the target
    month — all in absolute units (万 × 10,000).

    Returns None if no image yields a row matching `nev_target_wan` (the
    retail NEV total extracted from the article narrative). Without that
    cross-check we'd risk parsing the wrong table (e.g. wholesale).
    """
    if not _have_tesseract():
        print("WARNING: tesseract not installed — skipping NEV-table OCR")
        return None

    for url in image_urls:
        try:
            resp = session.get(url, headers=HTTP_HEADERS, timeout=30)
            resp.raise_for_status()
        except requests.RequestException:
            continue

        # Try each OCR config until one yields a row that reconciles against
        # the article NEV total. The headers ("BEV PHEV EREV NEV") are styled
        # white-on-teal and OCR poorly regardless, so we rely solely on the
        # NEV cross-check in _recover_decimal to confirm we read the right
        # table — that also makes trying multiple configs safe.
        result = None
        for scale, lang in OCR_CONFIGS:
            text = _ocr_image_bytes(resp.content, scale=scale, lang=lang)
            if not text:
                continue
            result = _extract_retail_from_ocr(text, month, nev_target_wan)
            if result is not None:
                ocr_cfg = f"{scale}x {lang}"
                break
        if result is None:
            continue
        recovered, line = result
        bev_wan, phev_wan, erev_wan, nev_wan = recovered
        print(
            f"OCR matched {url.rsplit('/', 1)[-1]} [{ocr_cfg}] "
            f"row '{line.strip()[:60]}' → "
            f"retail BEV={bev_wan} PHEV={phev_wan} EREV={erev_wan} NEV={nev_wan} (万)"
        )
        return {
            "BEV": bev_wan * 10_000,
            "PHEV": phev_wan * 10_000,
            "EREV": erev_wan * 10_000,
            "NEV": nev_wan * 10_000,
            "source_image": url,
        }

    return None


def parse_detail(html: str) -> dict:
    """Extract retail and wholesale aggregates from a detail-page article.

    Returns a dict:
        {
            "retail":   {"TOTAL": float, "NEV": float, "ICE": float},
            "wholesale":{"TOTAL": float, "NEV": float, "ICE": float,
                         "BEV": float, "PHEV": float, "EREV": float},
        }
    Any missing field stays absent. Raises if the page is clearly not a
    CPCA monthly analysis article.
    """
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    if "乘用车" not in text:
        raise RuntimeError("Detail page is not a CPCA passenger-car analysis")

    retail = {
        "TOTAL": _grab(RX_RT_TOTAL, text),
        "NEV": _grab(RX_RT_NEV, text),
        "ICE": _grab(RX_RT_ICE, text),
    }
    wholesale = {
        "TOTAL": _grab(RX_WS_TOTAL, text),
        "NEV": _grab(RX_WS_NEV, text),
        "ICE": _grab(RX_WS_ICE, text),
        "BEV": _grab(RX_WS_BEV, text),
        "PHEV": _grab(RX_WS_PHEV, text),
        "EREV": _grab(RX_WS_EREV, text),
    }

    # Derive ICE = TOTAL − NEV when the narrative didn't restate it. Older
    # CPCA articles often omit the explicit "常规燃油" sentence.
    for track in (retail, wholesale):
        if track["ICE"] is None and track["TOTAL"] is not None and track["NEV"] is not None:
            track["ICE"] = track["TOTAL"] - track["NEV"]

    return {"retail": retail, "wholesale": wholesale}


def build_rows(
    period: str,
    parsed: dict,
    ocr_retail: dict | None = None,
) -> tuple[dict | None, dict | None]:
    """Build (retail_row, wholesale_row) for a single period.

    Returns None for a track that is missing critical fields.

    Retail BEV/PHEV/EREV come from `ocr_retail` (the CPCA slide-deck NEV
    market table) when available — that's CPCA's only direct retail-side
    breakdown. If OCR is unavailable, we fall back to applying the wholesale
    BEV/PHEV/EREV mix to the article-stated retail NEV total. The fallback
    is documented in the row's `source` field so it's distinguishable from
    a clean OCR pull.
    """
    rt = parsed["retail"]
    ws = parsed["wholesale"]

    retail_row = None
    if rt["TOTAL"] is not None and rt["NEV"] is not None and rt["ICE"] is not None:
        retail_split_source = None
        if ocr_retail is not None:
            rt_bev = ocr_retail["BEV"]
            rt_phev = ocr_retail["PHEV"]
            rt_erev = ocr_retail["EREV"]
            retail_split_source = "ocr"
        else:
            ws_bev, ws_phev, ws_erev = ws["BEV"], ws["PHEV"], ws["EREV"]
            if None not in (ws_bev, ws_phev, ws_erev) and (ws_bev + ws_phev + ws_erev) > 0:
                mix_sum = ws_bev + ws_phev + ws_erev
                rt_bev = rt["NEV"] * ws_bev / mix_sum
                rt_phev = rt["NEV"] * ws_phev / mix_sum
                rt_erev = rt["NEV"] * ws_erev / mix_sum
                retail_split_source = "ws-proportional"
            else:
                rt_bev = rt_phev = rt_erev = None

        source_label = RETAIL_SOURCE
        if retail_split_source == "ws-proportional":
            source_label = RETAIL_SOURCE + " [BEV/PHEV/EREV: ws-proportional]"

        retail_row = {
            "period": period,
            "time_interval": "monthly",
            "variant": "Whole",
            "source": source_label,
            "BEV": rt_bev,
            "PHEV": rt_phev,
            "EREV": rt_erev,
            "OTHERS": 0.0,
            "ICE": rt["ICE"],
            "TOTAL": rt["TOTAL"],
            "notes": "",
            # Internal flag (stripped before CSV write) telling upsert whether
            # the BEV/PHEV/EREV split is authoritative (OCR) or merely a
            # proxy (ws-proportional). The proxy must NOT overwrite an
            # existing CSV row's hand-transcribed split.
            "_split_source": retail_split_source,
        }

    wholesale_row = None
    if all(ws[k] is not None for k in ("TOTAL", "ICE", "BEV", "PHEV", "EREV")):
        wholesale_row = {
            "period": period,
            "time_interval": "monthly",
            "variant": "Wholesale",
            "source": WHOLESALE_SOURCE,
            "BEV": ws["BEV"],
            "PHEV": ws["PHEV"],
            "EREV": ws["EREV"],
            "OTHERS": 0.0,
            "ICE": ws["ICE"],
            "TOTAL": ws["TOTAL"],
            "notes": "",
        }

    return retail_row, wholesale_row


def upsert_csv(csv_path: str, new_rows: list[dict], header_variant: str) -> tuple[int, int]:
    """Upsert rows into csv_path (key = period). Returns (added, updated).

    Warns when an existing value changes by more than 20% — flagging both
    parser drift and the occasional CPCA back-revision that overshoots.
    The file is created with the canonical header if it doesn't exist.
    """
    existing: dict[str, dict] = {}
    line_terminator = "\n"
    if os.path.exists(csv_path):
        # Preserve the existing file's line ending (CRLF vs LF) to keep
        # the diff focused on the new/changed rows.
        with open(csv_path, "rb") as f:
            head = f.read(4096)
        if b"\r\n" in head:
            line_terminator = "\r\n"
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing[row["period"]] = row

    added = updated = 0
    for new_row in sorted(new_rows, key=lambda r: r["period"]):
        period = new_row["period"]
        # Pull and strip the internal _split_source flag before persisting.
        split_source = new_row.pop("_split_source", None)
        if period not in existing:
            existing[period] = new_row
            added += 1
            print(f"  + {period} [{header_variant}]")
        else:
            old = existing[period]
            # When the parser's BEV/PHEV/EREV is only a ws-proportional proxy
            # (OCR failed) AND the existing CSV row already has those columns
            # filled in (hand-transcribed historicals), don't overwrite them.
            # The proxy is less accurate than the user's manual transcription
            # from the CPCA slide image.
            preserve_split = (
                split_source == "ws-proportional"
                and any((old.get(c) or "") not in ("", None) for c in ("BEV", "PHEV", "EREV"))
            )
            merged = {**old, **new_row}
            if preserve_split:
                merged["BEV"] = old.get("BEV", "")
                merged["PHEV"] = old.get("PHEV", "")
                merged["EREV"] = old.get("EREV", "")
                # Keep the existing source label too, so the row stays clean.
                merged["source"] = old.get("source", new_row.get("source", ""))
                print(
                    f"  ~ {period} [{header_variant}] (BEV/PHEV/EREV preserved "
                    f"— OCR unavailable, ws-proportional proxy not applied)"
                )
            else:
                for col in ("BEV", "PHEV", "EREV", "ICE", "TOTAL"):
                    try:
                        old_val = float(old.get(col) or 0)
                        new_val = float(new_row.get(col) or 0)
                    except (TypeError, ValueError):
                        continue
                    if old_val > 0 and abs(new_val - old_val) / old_val > 0.20:
                        print(
                            f"  WARNING {period} [{header_variant}] {col}: "
                            f"existing={old_val:.0f}, new={new_val:.0f} — "
                            f"diff >20%, please verify"
                        )
                print(f"  ~ {period} [{header_variant}]")
            existing[period] = merged
            updated += 1

    # Write with sorted period order. Keep yearly + monthly mixed in
    # whatever order they sort lexically — China.csv historically has both.
    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator=line_terminator)
        writer.writeheader()
        for period in sorted(existing.keys()):
            row = existing[period]
            writer.writerow({c: row.get(c, "") for c in CSV_COLUMNS})

    return added, updated


def latest_period_in(csv_path: str, variant: str) -> str | None:
    """Highest monthly period already present in csv_path for the given variant."""
    if not os.path.exists(csv_path):
        return None
    latest = None
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("variant") != variant or row.get("time_interval") != "monthly":
                continue
            p = row["period"]
            if latest is None or p > latest:
                latest = p
    return latest


def prev_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, help="Target year (default: previous calendar month)")
    parser.add_argument("--month", type=int, help="Target month 1-12 (default: previous calendar month)")
    parser.add_argument("--url", help="Direct detail-page URL")
    parser.add_argument("--id", type=int, help="Detail-page id (?id=NNNN)")
    parser.add_argument("--html-path", help="Local HTML file of detail page (offline)")
    parser.add_argument("--csv", default="data/China.csv", help="Retail CSV path")
    parser.add_argument("--wholesale-csv", default="data/China_Wholesale.csv",
                        help="Wholesale CSV path")
    parser.add_argument("--force", action="store_true",
                        help="Re-process even if target period already exists")
    parser.add_argument("--no-ocr", action="store_true",
                        help="Skip OCR of the NEV market slide (fall back to "
                             "wholesale-proportional retail BEV/PHEV/EREV split)")
    parser.add_argument("--image-dir",
                        help="Local directory of pre-downloaded slide JPGs "
                             "(file: page_*.jpg or any name). Used instead of "
                             "downloading from the live page; useful offline.")
    args = parser.parse_args()

    # Target period: default = previous calendar month
    if args.year and args.month:
        target_year, target_month = args.year, args.month
    else:
        today = date.today()
        target_year, target_month = prev_month(today.year, today.month)
    target_period = f"{target_year}-{target_month:02d}"
    print(f"Target period: {target_period}")

    # Self-throttle: if both CSVs already have this period, exit cleanly
    # unless --force / explicit --url / --id / --html-path was given.
    if not args.force and not (args.url or args.id or args.html_path):
        rt_latest = latest_period_in(args.csv, "Whole")
        ws_latest = latest_period_in(args.wholesale_csv, "Wholesale")
        if rt_latest and rt_latest >= target_period and (
            ws_latest is None or ws_latest >= target_period
        ):
            print(
                f"CSV(s) already contain {target_period} "
                f"(retail latest={rt_latest}, wholesale latest={ws_latest}). "
                f"Nothing to do — pass --force to re-process."
            )
            sys.exit(0)

    # Load detail page HTML
    if args.html_path:
        print(f"Loading local HTML: {args.html_path}")
        html = Path(args.html_path).read_text(encoding="utf-8", errors="replace")
        source_note = f"local:{Path(args.html_path).name}"
    elif args.url:
        print(f"Fetching detail page: {args.url}")
        html = fetch(args.url)
        source_note = args.url
    elif args.id:
        url = DETAIL_URL_TMPL.format(id=args.id)
        print(f"Fetching detail page by id: {url}")
        html = fetch(url)
        source_note = url
    else:
        print(f"Scanning listing for {target_period}: {LISTING_URL}")
        listing_html = fetch(LISTING_URL)
        detail_id = find_detail_id(listing_html, target_year, target_month)
        if detail_id is None:
            print(
                f"No listing entry for {target_year}年{target_month}月份 yet. "
                f"CPCA likely hasn't published the monthly analysis."
            )
            sys.exit(0)
        url = DETAIL_URL_TMPL.format(id=detail_id)
        print(f"Found detail id={detail_id} → {url}")
        html = fetch(url)
        source_note = url

    parsed = parse_detail(html)
    print(f"Retail:    {parsed['retail']}")
    print(f"Wholesale: {parsed['wholesale']}")

    # Pull retail BEV/PHEV/EREV from the embedded NEV-market slide via OCR.
    # CPCA does not restate that split in the article narrative — the slide
    # is the only direct retail source. NEV-total (from the narrative) is
    # passed as the cross-check anchor so we know we OCR'd the right table.
    ocr_retail = None
    if not args.no_ocr and parsed["retail"]["NEV"] is not None:
        nev_target_wan = parsed["retail"]["NEV"] / 10_000  # back to 万-units for OCR row match
        session = requests.Session()
        session.headers.update(HTTP_HEADERS)

        if args.image_dir:
            # OCR each local JPG until one matches the article NEV target.
            for path in sorted(Path(args.image_dir).glob("*.jp*g")):
                img_bytes = path.read_bytes()
                result = None
                for scale, lang in OCR_CONFIGS:
                    text = _ocr_image_bytes(img_bytes, scale=scale, lang=lang)
                    if not text:
                        continue
                    result = _extract_retail_from_ocr(text, target_month, nev_target_wan)
                    if result is not None:
                        ocr_cfg = f"{scale}x {lang}"
                        break
                if result is None:
                    continue
                recovered, line = result
                bev_wan, phev_wan, erev_wan, nev_wan = recovered
                ocr_retail = {
                    "BEV": bev_wan * 10_000,
                    "PHEV": phev_wan * 10_000,
                    "EREV": erev_wan * 10_000,
                    "NEV": nev_wan * 10_000,
                    "source_image": f"file://{path}",
                }
                print(
                    f"OCR matched {path.name} [{ocr_cfg}] row '{line.strip()[:60]}' → "
                    f"retail BEV={bev_wan} PHEV={phev_wan} EREV={erev_wan} NEV={nev_wan} (万)"
                )
                break
        else:
            image_urls = collect_image_urls(html)
            print(f"Embedded slides: {len(image_urls)}")
            ocr_retail = parse_retail_table(image_urls, session, target_month, nev_target_wan)

        if ocr_retail is None:
            print(
                "WARNING: no NEV-market slide matched the article-NEV target — "
                "falling back to wholesale-proportional retail split"
            )

    retail_row, wholesale_row = build_rows(target_period, parsed, ocr_retail)
    if retail_row is None and wholesale_row is None:
        print("ERROR: failed to extract any complete row from the detail page", file=sys.stderr)
        sys.exit(1)

    # Sanity check: NEV + ICE ≈ TOTAL on retail and wholesale.
    for tag, src in (("retail", parsed["retail"]), ("wholesale", parsed["wholesale"])):
        nev, ice, tot = src.get("NEV"), src.get("ICE"), src.get("TOTAL")
        if nev and ice and tot and abs((nev + ice) - tot) / tot > 0.02:
            print(
                f"WARNING [{tag}] NEV ({nev:.0f}) + ICE ({ice:.0f}) = "
                f"{nev + ice:.0f} vs TOTAL {tot:.0f} — >2% discrepancy"
            )

    # Annotate provenance in notes
    if retail_row is not None:
        retail_row["notes"] = source_note
    if wholesale_row is not None:
        wholesale_row["notes"] = source_note

    rt_added = rt_updated = ws_added = ws_updated = 0
    if retail_row is not None:
        rt_added, rt_updated = upsert_csv(args.csv, [retail_row], "retail")
    else:
        print("Retail row skipped (incomplete narrative)")
    if wholesale_row is not None:
        ws_added, ws_updated = upsert_csv(args.wholesale_csv, [wholesale_row], "wholesale")
    else:
        print("Wholesale row skipped (incomplete narrative)")

    print(
        f"\nDone: retail +{rt_added}/~{rt_updated} → {args.csv}; "
        f"wholesale +{ws_added}/~{ws_updated} → {args.wholesale_csv}"
    )


if __name__ == "__main__":
    main()
