#!/usr/bin/env python3
"""
Fetch Vietnam's monthly new passenger-car sales from three publishers and
upsert data/Vietnam.csv (Whole).

Why three sources
-----------------
No single body counts the whole Vietnamese car market. The association VAMA
(Vietnam Automobile Manufacturers' Association) publishes its members' sales
plus an import estimate ("total industry"), but the two biggest non-members
publish their own figures:

  VAMA        members by model + total-industry estimate incl. non-member CBU
              imports — a cover letter (PDF) and a "Detail" sheet (PDF)
              http://vama.org.vn/en/sales-report.html  (plain http: https resets)
  VinFast     domestic deliveries, every model battery-electric — press
              release on vingroup.net (~10th), the same figure as VinFast's
              SEC Form 6-K (EDGAR blocks GitHub runners, so it is a manual
              cross-check, not a fetch path)
  TC Group    Hyundai (Hyundai Thanh Cong) sales by model incl. a commercial-
              vehicle line — press release on thanhcong.vn (~10th)

Vietnam's media "whole market" figure is VAMA total industry + VinFast +
Hyundai (all vehicle types). The gallery's Whole series is the passenger-car
part of that sum — the scope closest to EU M1.

Components → CSV (docs/architecture/64-source-vietnam.md §3)
-------------------------------------------------------------
Every month's raw figures are kept in data/raw/vietnam/components.csv (one row
per month, all three sources, with the URL of each). data/Vietnam.csv is
derived from it — only for months where all three are present:

  BEV    = VinFast + VAMA BEV block + BEV models VAMA files in its PC block
  HEV    = VAMA Hybrid block − mild-hybrid models + hybrid models VAMA files
           in its PC block (Land Cruiser Hybrid)
  MHEV   = Suzuki XL7 Hybrid / Ertiga Hybrid (12 V mild hybrids in VAMA's
           Hybrid block)
  ICE    = VAMA PC block − the PC-block exceptions above
           + Hyundai (TC total − TC commercial vehicles)
           + VinFast ICE (Fadil / Lux, history to 2022 only)
  OTHERS = non-member imports: VAMA total-industry PC − members (PC + Hybrid
           + BEV). Fuel unknown (BYD, Mercedes, ...), so never BEV/PHEV.
  PHEV   = empty (no source splits it; never written as 0)
  TOTAL  = the sum = VAMA total-industry PC + VinFast + Hyundai passenger

History (2021-01 .. 2024-08) was assembled once from VAMA's archive, the
VinFast and TC releases and VinFast's SEC filings; it lives in the same
components file. Before 2024 VAMA had no Hybrid block, so HEV / MHEV are
empty there (inside ICE). Months whose VinFast figure is a yearly residual
(vinfast_kind=estimate) are labelled `monthly_est` (a monthly row estimated
from annual data: counted as monthly, drawn hollow), see the source page.

The PC-block exceptions and the mild hybrids come from the Detail sheet. VAMA
has uploaded the previous month's Detail under a new month's name (2025-05,
2026-02); the sheet's own "Sales - <Month> <YYYY>" header is checked, and a
wrong sheet is never used: the month's model figures are then derived from
the neighbours' year-to-date columns (YTD[M+1] − M+1 − YTD[M−1]) as soon as
M+1 is out, and until then the whole Hybrid block stays HEV (noted).

VinFast revises silently: the next month's year-to-date figure is checked
against the stored months; a gap is booked to the previous month (same
calendar year, exact figures only) and noted.

Also writes market/vietnam_top.json (BEV / HEV / MHEV brands and models) and
market/vietnam_all_top.json (every powertrain, ALL — VAMA has no fuel per
non-member brand, so non-member imports are one pooled row).

Usage
-----
  python scripts/fetch_vietnam.py                   # newest month (M−1 of today)
  python scripts/fetch_vietnam.py --period 2026-09
  python scripts/fetch_vietnam.py --vinfast-url URL # article / 6-K by hand
  python scripts/fetch_vietnam.py --rebuild         # CSV + tops from components only
  python scripts/fetch_vietnam.py --dry-run

Manual fallbacks (any source): fill the month's columns in
data/raw/vietnam/components.csv by hand (vinfast_kind=manual etc.) and run
--rebuild; the fetcher never overwrites a value marked manual.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import difflib
import html as htmllib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote, urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_top  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
CSV_PATH = REPO / "data" / "Vietnam.csv"
COMPONENTS = REPO / "data" / "raw" / "vietnam" / "components.csv"
SOURCE = "VAMA + VinFast + TC Group"
FIRST_PERIOD = "2021-01"      # history from here: docs/architecture/64-source-vietnam.md §2a
HYBRID_FROM = "2024-01"       # VAMA's Hybrid block starts; before it hybrids sit in PC (→ ICE)
COUNTRY = "Vietnam"
TOP_SLUG = "vietnam"          # BEV / HEV / MHEV
ALL_SLUG = "vietnam_all"      # every powertrain (ALL)

CSV_COLUMNS = ["period", "time_interval", "variant", "source", "BEV", "PHEV", "HEV",
               "MHEV", "ICE", "OTHERS", "TOTAL", "notes"]
COMP_COLUMNS = [
    "period",
    "vama_ti", "vama_ti_pc", "vama_ti_cv", "vama_ti_spv",
    "vama_members_pc", "vama_members_hybrid", "vama_members_bev",
    "vama_mhev", "vama_hev_in_pc", "vama_bev_in_pc", "vama_detail",
    "vinfast", "vinfast_ice", "vinfast_ytd", "vinfast_kind", "vinfast_models",
    "tc_total", "tc_commercial", "hyundai_models",
    "src_vama", "src_vinfast", "src_tc", "note",
]

VAMA_BASE = "http://vama.org.vn"
VAMA_LIST = VAMA_BASE + "/en/sales-report.html"
VINGROUP = "https://vingroup.net"
VINGROUP_LISTS = ([f"{VINGROUP}/tin-tuc-su-kien/cong-nghe-cong-nghiep"]
                  + [f"{VINGROUP}/tin-tuc-su-kien/cong-nghe-cong-nghiep/{i}" for i in range(2, 5)]
                  + [f"{VINGROUP}/tin-tuc-su-kien"]
                  + [f"{VINGROUP}/tin-tuc-su-kien/tat-ca/{i}" for i in range(2, 9)])
TC_LISTS = ["https://thanhcong.vn/tin-tuc"] + [f"https://thanhcong.vn/tin-tuc/page/{i}" for i in range(2, 5)]
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36 LeRaffl-Gallery (+https://github.com/LeRaffl/LeRaffl-Gallery)")

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]
NUM = r"(\d{1,3}(?:[.,]\d{3})+|\d+)"


def num(s: str) -> int:
    return int(re.sub(r"[.,\s]", "", s))


def month_of(word: str) -> int | None:
    """English month name, abbreviation or typo ("Deember") → 1..12."""
    w = word.strip().lower().rstrip(".")
    for i, m in enumerate(MONTHS):
        if w == m or (len(w) >= 3 and m.startswith(w)):
            return i + 1
    best = difflib.get_close_matches(w, MONTHS, n=1, cutoff=0.75)
    return MONTHS.index(best[0]) + 1 if best else None


def prev_period(p: str) -> str:
    y, m = map(int, p.split("-"))
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def next_period(p: str) -> str:
    y, m = map(int, p.split("-"))
    return f"{y + 1}-01" if m == 12 else f"{y}-{m + 1:02d}"


def default_target(today: dt.date | None = None) -> str:
    t = today or (dt.datetime.utcnow() + dt.timedelta(hours=7)).date()   # Asia/Ho_Chi_Minh
    return prev_period(f"{t.year}-{t.month:02d}")


def html_text(h: str) -> str:
    h = re.sub(r"<(script|style)\b.*?</\1>", " ", h, flags=re.S | re.I)
    h = re.sub(r"<br\s*/?>|</p>|</div>|</h\d>|</li>|</tr>", ". ", h, flags=re.I)
    t = htmllib.unescape(re.sub(r"<[^>]+>", " ", h))
    t = re.sub(r"\s+", " ", t).replace(" .", ".")
    return re.sub(r"(\.\s*){2,}", ". ", t).strip()


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def make_session():
    import requests
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "vi,en;q=0.8"})
    return s


def get(session, url: str, timeout: int = 60, tries: int = 3):
    last = None
    for i in range(tries):
        try:
            r = session.get(url, timeout=timeout)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 * (i + 1))
    print(f"  ! {url}: {type(last).__name__}: {last}")
    return None


def load(session, ref: str) -> bytes | None:
    """URL or local path → bytes."""
    if re.match(r"https?://", ref):
        r = get(session, ref, timeout=120)
        return r.content if r is not None else None
    p = Path(ref)
    return p.read_bytes() if p.exists() else None


# --------------------------------------------------------------------------
# VAMA
# --------------------------------------------------------------------------

def vama_listing(page_html: str, base: str = VAMA_BASE) -> dict[str, dict]:
    """{period: {"cover": url, "detail": url, "title": str}} from the sales-
    report page. An item is a "Sales report <Month> <YYYY>" title link (the
    cover letter) followed by its attachments; the month comes from the title
    (fuzzy — VAMA has typed "Deember") and, failing that, from the
    attachments' names."""
    out: dict[str, dict] = {}
    cur = None
    for m in re.finditer(r'<a[^>]+href="([^"]+\.pdf)"[^>]*>(.*?)</a>', page_html, re.S | re.I):
        href = urljoin(base + "/", htmllib.unescape(m.group(1)))
        text = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))).strip()
        t = re.match(r"Sales report\s+([A-Za-z]+)\.?\s+(\d{4})$", text, re.I)
        if t and "cover" in unquote(href).lower():
            mo = month_of(t.group(1))
            cur = {"cover": href, "title": text, "period": f"{t.group(2)}-{mo:02d}" if mo else None}
            if cur["period"]:
                out.setdefault(cur["period"], {}).update(cover=href, title=text)
            continue
        if cur is None or text.lower() == "download":
            continue
        name = unquote(href.rsplit("/", 1)[-1])
        a = re.search(r"sales report\s+([A-Za-z]+)\s+(\d{4})\s*-\s*(.+?)\.pdf$", name, re.I)
        if not a:
            continue
        if cur["period"] is None:
            mo = month_of(a.group(1))
            cur["period"] = f"{a.group(2)}-{mo:02d}" if mo else None
        kind = a.group(3).strip().lower()
        if cur["period"] and kind == "detail":
            cur["detail"] = href
        if cur["period"]:
            out.setdefault(cur["period"], {}).update({k: v for k, v in cur.items() if k != "period"})
    return out


def pdf_text(data: bytes) -> str:
    """pdftotext -layout (poppler) — the cover letter's bold totals come apart
    in pdfplumber's text, poppler keeps them whole."""
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(data)
        f.flush()
        return subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True,
                              text=True, check=True).stdout


def parse_cover(text: str) -> dict:
    """VAMA cover letter → total industry (and its PC / CV / SPV split) and the
    members' PC, BEV and Hybrid subtotals for the month."""
    t = re.sub(r"\s+", " ", text)
    out: dict = {}
    m = re.search(r"The ([A-Za-z]+) (\d{4}) industry (?:is|was) at", t)
    if m and month_of(m.group(1)):
        out["period"] = f"{m.group(2)}-{month_of(m.group(1)):02d}"
    m = re.search(r"Total industry (?:is|was) at " + NUM + r" units,? of which " + NUM +
                  r" ?units were Passenger Cars?[;,]? " + NUM + r" ?units were Commercial Vehicles?,? and "
                  + NUM + r" ?units were Special[- ]Purpose Vehicles?", t, re.I)
    if not m:   # Vietnamese-only months (2024-06): "đạt N xe, bao gồm xe N du lịch; N xe thương mại và N xe chuyên dụng"
        m = re.search(r"toàn thị trường đạt " + NUM + r" xe,? bao gồm (?:xe )?" + NUM + r" (?:xe )?du lịch[;,]? "
                      + NUM + r" xe thương mại và " + NUM + r" xe chuyên dụng", t, re.I)
    if m:
        out["ti"], out["ti_pc"], out["ti_cv"], out["ti_spv"] = map(num, m.groups())
    sec = None
    for line in text.splitlines():
        s = line.strip()
        if re.match(r"^(I\s+)?Passenger cars \(PC\)$", s):
            sec = "members_pc"
        elif re.match(r"^(II\s+)?Commercial vehicles", s):
            sec = "cv"
        elif re.match(r"^(III\s+)?Special[- ]Purpose Vehicles", s, re.I):
            sec = "spv"
        elif re.match(r"^(IV|V)\s+BEV$", s):
            sec = "members_bev"
        elif re.match(r"^(IV|V)\s+Hybrid$", s):
            sec = "members_hybrid"
        elif s.startswith("Subtotal") and sec and sec not in out:
            vals = [0 if x in ("-", "–") else num(x) for x in s.split()[1:]
                    if re.fullmatch(r"-|–|" + NUM, x)]
            if len(vals) >= 4:
                out[sec] = vals[3]          # North, Central, South, TOTAL (month), …YTD
    out.pop("cv", None)
    out.pop("spv", None)
    # The headline total has carried typos (2024-11: "40,200" for 44,200);
    # the PC / CV / SPV split is what the series uses, so trust their sum.
    if all(k in out for k in ("ti", "ti_pc", "ti_cv", "ti_spv")):
        s = out["ti_pc"] + out["ti_cv"] + out["ti_spv"]
        if s != out["ti"]:
            out["ti_note"] = f"cover letter says total industry {out['ti']:,}; PC+CV+SPV = {s:,} used"
            out["ti"] = s
    return out


# Detail sheet -------------------------------------------------------------

PC_CLASSES = {"sedan", "suv", "crossover", "cross-over", "mpv", "hatchback", "others",
              "peugeot", "convertible"}
MAKER_BRAND = {"THACO KIA": "KIA", "THACO MAZDA": "MAZDA", "THACO PREMIUM": "PEUGEOT",
               "TCIEV": "NISSAN", "MEKONG AUTO": "MEKONG"}
# 12 V "Smart Hybrid Vehicle by Suzuki" — mild hybrids VAMA lists in its Hybrid block.
MHEV_MODEL = re.compile(r"^(XL7|ERTIGA) HYBRID", re.I)
HYBRID_NAME = re.compile(r"\bhybrid\b|\bHEV\b|e:HEV", re.I)
BEV_NAME = re.compile(r"mach-?e|\be-tron\b|\bEQ[ABCES]\b|\bbZ4X\b|\bioniq\b|\bEV\d\b|\biX\d?\b|\bi[457]\b", re.I)


def _lines(words, tol=2.5):
    out = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        for ln in out[-3:]:
            if abs(ln[0] - w["top"]) <= tol:
                ln[1].append(w)
                break
        else:
            out.append([w["top"], [w]])
    return [sorted(ln[1], key=lambda w: w["x0"]) for ln in out]


def _cells(words, gap=6):
    out = []
    for w in words:
        if out and w["x0"] - out[-1][-1]["x1"] <= gap:
            out[-1].append(w)
        else:
            out.append([w])
    return [" ".join(w["text"] for w in c) for c in out]


def parse_detail(data: bytes) -> dict:
    """VAMA "Detail" sheet → {"period", "rows": [{maker, model, cls, month, ytd}],
    "subtotals": {maker: month}}. Columns are found from the per-page header
    (North / Central / South / Total for the month, then the same for the
    year to date); the month figure is the row's Total."""
    import pdfplumber
    rows, subtotals, period = [], collections.Counter(), None
    numre = re.compile(r"^\d{1,3}(?:[.,]\d{3})+$|^\d+$")
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for pg in pdf.pages:
            if period is None:
                m = re.search(r"Sales\s*-\s*([A-Za-z]+)\s+(\d{4})", pg.extract_text() or "")
                if m and month_of(m.group(1)):
                    period = f"{m.group(2)}-{month_of(m.group(1)):02d}"
            # drop the page footer, which overlaps one row in small print
            pg = pg.filter(lambda o: o.get("object_type") != "char" or o.get("size", 0) < 7.5)
            x_num = x_ytd = None
            for lw in _lines(pg.extract_words()):
                tx = [w["text"] for w in lw]
                if tx.count("North") >= 2 and tx.count("Total") >= 2:
                    norths = sorted(w["x0"] for w in lw if w["text"] == "North")
                    totals = sorted(w["x1"] for w in lw if w["text"] == "Total")
                    x_num, x_ytd = norths[0] - 18, (totals[0] + norths[1]) / 2
                    continue
                if x_num is None:
                    continue
                text = [w for w in lw if w["x0"] < x_num]
                if not text:
                    continue
                cs = _cells(text)
                nums = [num(w["text"]) for w in lw if x_num <= w["x0"] < x_ytd and numre.match(w["text"])]
                ytd = [num(w["text"]) for w in lw if w["x0"] >= x_ytd and numre.match(w["text"])]
                month = max(nums) if nums else 0
                if any(re.search(r"sub-?total", c, re.I) for c in cs):
                    subtotals[cs[0]] += month
                    continue
                if cs and re.search(r"seats?$", cs[-1], re.I):
                    cs.pop()
                if len(cs) < 2 or re.fullmatch(r"\d+|[IVX]+", cs[0]):
                    continue
                rows.append({"maker": cs[0], "model": cs[1], "cls": " ".join(cs[2:]),
                             "month": month, "ytd": max(ytd) if ytd else 0})
    return {"period": period, "rows": rows, "subtotals": dict(subtotals)}


def classify(row: dict) -> str | None:
    """Detail row → BEV / HEV / MHEV / ICE (a passenger car) or None (CV, SPV)."""
    cls, model = row["cls"].strip().lower(), row["model"]
    if cls == "bev":
        return "BEV"
    if cls == "hybrid":
        return "MHEV" if MHEV_MODEL.match(model) else "HEV"
    if cls in PC_CLASSES:
        if BEV_NAME.search(model):
            return "BEV"
        if HYBRID_NAME.search(model):
            return "HEV"
        return "ICE"
    return None


def brand_model(row: dict) -> tuple[str, str]:
    maker = market_top.clean(row["maker"])
    brand = MAKER_BRAND.get(maker, maker)
    model = market_top.clean(re.sub(r"\s*\((?:CBU|CKD|\d{4})\)\s*$", "", row["model"], flags=re.I))
    if model in ("XE KHÁC", "OTHERS", "PEUGEOT", brand):
        model = ""                     # "other models" / brand-only lines
    return brand, market_top.strip_brand(brand, model)


def exceptions(units: dict) -> dict:
    """The model-derived component figures from a month's detail units."""
    return {
        "vama_mhev": sum(n for (c, _, _), n in units.items() if c == "MHEV"),
        "vama_hev_in_pc": sum(n for (c, b, m), n in units.items() if c == "HEV" and "#pc" in m),
        "vama_bev_in_pc": sum(n for (c, b, m), n in units.items() if c == "BEV" and "#pc" in m),
    }


def detail_units(rows: list[dict], key: str = "month") -> dict:
    """{(class, brand, model): n} for the passenger-car rows. Tags rows that sit in VAMA's PC block yet
    are hybrid / battery-electric by name ("#pc" suffix, stripped later), so
    the components can book them out of ICE."""
    out: collections.Counter = collections.Counter()
    for r in rows:
        c = classify(r)
        if not c:
            continue
        b, m = brand_model(r)
        if c in ("HEV", "BEV") and r["cls"].strip().lower() in PC_CLASSES:
            m += "#pc"
        out[(c, b, m)] += r[key]
    return dict(out)


def derive_units_from_ytd(prev: dict | None, nxt: dict, period: str) -> dict:
    ytd_next = detail_units(nxt["rows"], "ytd")
    mon_next = detail_units(nxt["rows"], "month")
    ytd_prev = detail_units(prev["rows"], "ytd") if prev and period[5:] != "01" else {}
    out = {}
    for k in set(ytd_next) | set(ytd_prev):
        v = ytd_next.get(k, 0) - mon_next.get(k, 0) - ytd_prev.get(k, 0)
        if v > 0:
            out[k] = v
    return out


# --------------------------------------------------------------------------
# VinFast
# --------------------------------------------------------------------------

VF_MODELS = [  # (regex, display) — VF 5 / Herio Green and VF 2 / Minio Green
    (r"VF\s?MPV\s?7", "VF MPV 7"),            # are the same car under two names
    (r"VF\s?5\s*/\s*Herio Green|VF\s?5\b|Herio Green", "VF 5 / HERIO GREEN"),
    (r"VF\s?2\s*/\s*Minio Green|VF\s?2\b|Minio Green", "VF 2 / MINIO GREEN"),
    (r"VF\s?3\b", "VF 3"), (r"VF\s?6\b", "VF 6"), (r"VF\s?7\b", "VF 7"),
    (r"VF\s?8\b", "VF 8"), (r"VF\s?9\b", "VF 9"),
    (r"Limo Green", "LIMO GREEN"), (r"Nerio Green", "NERIO GREEN"),
    (r"EC Van", "EC VAN"), (r"Lạc Hồng|Lac Hong", "LẠC HỒNG"),
]
_VF_RE = re.compile("|".join(f"(?P<m{i}>{p})" for i, (p, _) in enumerate(VF_MODELS)), re.I)
_UNIT_RE = re.compile(NUM + r"\s+(?:(?!\d\d)[\w/]+\s+){0,3}?(?:xe|chiếc|vehicles?|units)\b", re.I)
# Year-to-date sentences: cut at a "bringing the total to" clause, then drop
# what still refers to the year / the period as a whole.
_CUT = re.compile(r"nâng tổng|nâng lũy kế|nâng luỹ kế|, bringing", re.I)
_CUMUL = re.compile(r"lũy kế|luỹ kế|từ đầu năm|tính chung|\d+ tháng đầu năm|cả năm|cumulativ|"
                    r"year to date|year-to-date|for the first|for the full year|during the period|"
                    r"during the year|in the first", re.I)


def parse_vinfast(text: str) -> dict:
    """VinFast monthly press release (vingroup.net, Vietnamese) or the 6-K
    text (English) → {"period", "units", "exact", "ytd", "models": {name: n}}."""
    t = re.sub(r"\s+", " ", text)
    out: dict = {}
    m = (re.search(r"bàn giao (hơn |gần )?" + NUM + r" (?:ô tô|xe)[^.]{0,80}?tháng (\d{1,2})/(\d{4})", t, re.I)
         or None)
    if m:
        out.update(units=num(m.group(2)), exact=not m.group(1), period=f"{m.group(4)}-{int(m.group(3)):02d}")
    else:
        m = re.search(r"deliveries of (more than |over |approximately )?" + NUM +
                      r" electric vehicles[^.]{0,80}?(?:in|for) ([A-Z][a-z]+) (\d{4})", t)
        if m and month_of(m.group(3)):
            out.update(units=num(m.group(2)), exact=not m.group(1),
                       period=f"{m.group(4)}-{month_of(m.group(3)):02d}")
    m = (re.search(r"Lũy kế[^.]{0,80}?(?:tổng cộng|đạt|bán ra)[^.\d]{0,30}" + NUM + r" xe", t, re.I)
         or re.search(r"(?:Cumulatively|Year to date|For the first [^,]{3,30}|For the full year \d{4})"
                      r"[^.]{0,120}?total of " + NUM, t, re.I))
    if m:
        out["ytd"] = num(m.group(1))
    if "units" in out:
        out["models"] = vinfast_models(t, out["units"])
    return out


def vinfast_models(t: str, total: int) -> dict:
    models: collections.Counter = collections.Counter()
    for sent in re.split(r"\.\s+(?=[A-ZÀ-ỸĐ“\"])", t):
        cut = _CUT.search(sent)
        if cut:
            sent = sent[:cut.start()]
        if _CUMUL.search(sent):
            continue
        events = []
        for m in _VF_RE.finditer(sent):
            name = next(VF_MODELS[int(k[1:])][1] for k, v in m.groupdict().items() if v)
            events.append((m.start(), "m", name))
        for m in _UNIT_RE.finditer(sent):
            n = num(m.group(1))
            if n != total and n >= 10:
                events.append((m.start(), "n", n))
        pend_m, pend_n = [], []
        for _, kind, v in sorted(events):
            if kind == "m":
                if pend_m and pend_m[-1] == v:
                    continue
                if pend_n:
                    models[v] += pend_n.pop(0)
                else:
                    pend_m.append(v)
            else:
                if pend_m:
                    models[pend_m.pop(0)] += v
                else:
                    pend_n.append(v)
    if sum(models.values()) > total:
        print(f"  ! VinFast model figures add up to {sum(models.values()):,} > {total:,} — not used")
        return {}
    return dict(models)


def vingroup_article_links(page_html: str) -> list[str]:
    links = re.findall(r'href="([^"]*/bai-viet/\d+/[^"]+)"', page_html)
    return [urljoin(VINGROUP + "/", h) for h in dict.fromkeys(links)
            if re.search(r"vinfast", h) and re.search(r"ban-giao|doanh-so|ban-ra", h)]


# --------------------------------------------------------------------------
# TC Group (Hyundai)
# --------------------------------------------------------------------------

def tc_article_links(page_html: str, period: str) -> list[str]:
    y, m = period.split("-")
    pat = re.compile(r'href="(https://thanhcong\.vn/tin-tuc/[^"]*ban-hang[^"]*thang-' + str(int(m))
                     + r'-(?:nam-)?' + y + r'[^"]*\.html)"')
    return list(dict.fromkeys(pat.findall(page_html)))


def parse_tc(page_html: str, period: str) -> dict:
    """TC Group monthly release → {"total", "commercial", "models": {...},
    "prev_models": {...}}. The table (when there is one) has the previous
    month, this month and the year to date as its last three columns; rows
    with no CBU/CKD cell are one cell short, so columns count from the end."""
    out: dict = {}
    mon = int(period[5:])
    for tab in re.findall(r"<table.*?</table>", page_html, re.S | re.I):
        rows = []
        for tr in re.findall(r"<tr.*?</tr>", tab, re.S | re.I):
            cells = [re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
                     for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)]
            if cells:
                rows.append(cells)
        hdr = next((r for r in rows if r and r[0].lower().startswith("mẫu xe")), None)
        if not hdr:
            continue
        here = hdr[-2]
        hm = re.search(r"(\d{1,2})\s*(?:/|–|-)\s*(\d{4})", here)
        if not hm or int(hm.group(1)) != mon:
            continue
        models, prev = {}, {}
        for r in rows[rows.index(hdr) + 1:]:
            if len(r) < 4 or not re.fullmatch(NUM, r[-2] or "x"):
                continue
            name = r[0].strip()
            cur, pre = num(r[-2]), (num(r[-3]) if re.fullmatch(NUM, r[-3] or "x") else None)
            key = name.upper()
            if key.startswith("TỔNG"):
                out["total"] = cur
                out["prev_total"] = pre
            elif "THƯƠNG MẠI" in key:
                out["commercial"] = cur
                out["prev_commercial"] = pre
            else:
                model = "" if key.startswith("MẪU KHÁC") else market_top.strip_brand("HYUNDAI", market_top.clean(name))
                models[model] = models.get(model, 0) + cur
                if pre is not None:
                    prev[model] = prev.get(model, 0) + pre
        out["models"], out["prev_models"] = models, prev
        break
    if "total" not in out or "commercial" not in out:
        t = html_text(page_html)
        tot = (re.search(r"tổng (?:doanh số|số xe)[^.]{0,120}?(?:tháng " + str(mon) + r"\b|trong tháng)[^.]{0,80}?"
                         r"(?:đạt|là)\s+" + NUM + r"\s*xe", t, re.I)
               or re.search(r"tổng (?:doanh số|số xe)[^.]{0,120}?(?:đạt|là)\s+" + NUM + r"\s*xe", t, re.I))
        com = re.search(r"xe thương mại[^.]{0,200}?(?:đạt|doanh số|ghi nhận)\D{0,40}?" + NUM + r"\s*xe", t, re.I)
        if tot and "total" not in out:
            out["total"] = num(tot.group(1))
        if com and "commercial" not in out:
            out["commercial"] = num(com.group(1))
    return out


# --------------------------------------------------------------------------
# Components file
# --------------------------------------------------------------------------

def read_components(path: Path = COMPONENTS) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as f:
        return {r["period"]: r for r in csv.DictReader(f)}


def write_components(comp: dict[str, dict], path: Path = COMPONENTS) -> bool:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COMP_COLUMNS, lineterminator="\n", extrasaction="ignore")
    w.writeheader()
    for p in sorted(comp):
        w.writerow({k: comp[p].get(k, "") for k in COMP_COLUMNS})
    text = buf.getvalue()
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def _i(row: dict, k: str) -> int:
    v = (row.get(k) or "").strip()
    return int(float(v)) if v else 0


def _f(row: dict, k: str) -> float:
    v = (row.get(k) or "").strip()
    return float(v) if v else 0.0


def _fmt(x: float) -> str:
    """One decimal like every other row; two where a period-average needs it (3948.75)."""
    s = f"{x:.2f}"
    return s[:-1] if s.endswith("0") else s


def complete(row: dict) -> bool:
    return all((row.get(k) or "").strip() for k in
               ("vama_ti_pc", "vama_members_pc", "vama_members_hybrid", "vinfast", "tc_total", "tc_commercial"))


def compose(row: dict) -> dict:
    """One components row → one Vietnam.csv row (see module docstring).

    History rows (2021-01 … 2024-08, assembled once): VinFast
    still sold ICE cars until Nov 2022 (`vinfast_ice`, booked to ICE), and
    VAMA had no Hybrid block before HYBRID_FROM — hybrids sat in its PC block,
    so HEV / MHEV stay empty (inside ICE). A VinFast `estimate` is a yearly
    figure minus the published months, spread evenly: the row is labelled
    `monthly_est` (monthly, estimated from annual data — counted as a month,
    drawn hollow); VAMA and Hyundai in it are still the real monthly figures."""
    vf, vf_ice = _f(row, "vinfast"), _f(row, "vinfast_ice")
    bev = vf - vf_ice + _i(row, "vama_members_bev") + _i(row, "vama_bev_in_pc")
    mhev = _i(row, "vama_mhev")
    hev = _i(row, "vama_members_hybrid") - mhev + _i(row, "vama_hev_in_pc")
    hyundai = _i(row, "tc_total") - _i(row, "tc_commercial")
    ice = (_i(row, "vama_members_pc") - _i(row, "vama_hev_in_pc") - _i(row, "vama_bev_in_pc")
           + hyundai + vf_ice)
    others = (_i(row, "vama_ti_pc") - _i(row, "vama_members_pc") - _i(row, "vama_members_hybrid")
              - _i(row, "vama_members_bev"))
    total = bev + hev + mhev + ice + others
    assert abs(total - (_i(row, "vama_ti_pc") + vf + hyundai)) < 1e-6, row["period"]
    if min(bev, hev, mhev, ice, others) < 0:
        raise ValueError(f"{row['period']}: negative component {bev, hev, mhev, ice, others}")
    split_hybrids = row["period"] >= HYBRID_FROM
    notes = []
    kind = row.get("vinfast_kind", "")
    if kind == "rounded":
        notes.append(f"VinFast rounded ('more than {vf:,.0f}')")
    elif kind == "revised":
        notes.append("VinFast revised from next month's YTD")
    elif kind == "manual":
        notes.append("VinFast entered by hand")
    if row.get("vama_detail") == "pending":
        notes.append("VAMA detail sheet wrong/missing: mild hybrids not split from HEV yet")
    elif row.get("vama_detail") == "derived":
        notes.append("model split derived from neighbouring months' YTD (VAMA detail sheet mislabelled)")
    if not split_hybrids:
        notes.append("no VAMA Hybrid block before 2024: HEV/MHEV inside ICE")
    if row.get("note"):
        notes.append(row["note"])
    return {"period": row["period"], "time_interval": "monthly_est" if kind == "estimate" else "monthly",
            "variant": "Whole", "source": SOURCE,
            "BEV": _fmt(bev), "PHEV": "", "HEV": _fmt(hev) if split_hybrids else "",
            "MHEV": _fmt(mhev) if split_hybrids else "",
            "ICE": _fmt(ice), "OTHERS": _fmt(others), "TOTAL": _fmt(total),
            "notes": "; ".join(notes)}


def write_csv(comp: dict[str, dict], path: Path = CSV_PATH) -> list[str]:
    """Rewrite data/Vietnam.csv from the components; returns changed periods."""
    old = {}
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            old = {r["period"]: r for r in csv.DictReader(f)}
    new = {p: compose(r) for p, r in comp.items() if p >= FIRST_PERIOD and complete(r)}
    changed = sorted(p for p in new if old.get(p) != new[p])
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, lineterminator="\n")
    w.writeheader()
    for p in sorted(new):
        w.writerow(new[p])
    if not path.exists() or path.read_text(encoding="utf-8") != buf.getvalue():
        path.write_text(buf.getvalue(), encoding="utf-8")
    return changed


def apply_vinfast_revision(comp: dict[str, dict], period: str) -> str | None:
    """VinFast restates months silently; its year-to-date figure is the
    anchor. If YTD[M] − units[M] differs from YTD[M−1] as stored, the gap is
    booked to M−1 (same year, exact figures only) and noted."""
    cur, prev = comp.get(period), comp.get(prev_period(period))
    if not cur or not prev or period[5:] == "01":
        return None
    if not (cur.get("vinfast_ytd") and prev.get("vinfast_ytd") and cur.get("vinfast")):
        return None
    if prev.get("vinfast_kind") in ("rounded", "manual", "estimate"):
        return None
    implied = _i(cur, "vinfast_ytd") - _i(cur, "vinfast")
    if implied == _i(prev, "vinfast_ytd"):
        return None
    pp = comp.get(prev_period(prev["period"]))
    base = _i(pp, "vinfast_ytd") if pp and prev["period"][5:] != "01" else 0
    if prev["period"][5:] != "01" and not (pp and pp.get("vinfast_ytd")):
        return None
    new_units = implied - base
    msg = (f"VinFast {prev['period']}: {_i(prev, 'vinfast'):,} → {new_units:,} "
           f"(YTD {period} {_i(cur, 'vinfast_ytd'):,} − {_i(cur, 'vinfast'):,})")
    prev.update(vinfast=str(new_units), vinfast_ytd=str(implied), vinfast_kind="revised")
    return msg


# --------------------------------------------------------------------------
# Top lists
# --------------------------------------------------------------------------

def parse_models(s: str) -> dict[str, int]:
    out = {}
    for part in (s or "").split("|"):
        if ":" in part:
            k, v = part.rsplit(":", 1)
            out[k.strip()] = int(v)
    return out


def fmt_models(d: dict[str, int]) -> str:
    return "|".join(f"{k}:{v}" for k, v in sorted(d.items(), key=lambda kv: (-kv[1], kv[0])))


def month_units(row: dict, vama_units: dict | None) -> tuple[dict, dict]:
    """(electrified units, ALL units) for one month: VAMA detail rows (or the
    blocks when the sheet is missing), VinFast and Hyundai models, the pooled
    non-member imports and Lexus / BMW-MINI (separate VAMA sheets) as REST."""
    el: collections.Counter = collections.Counter()
    al: collections.Counter = collections.Counter()
    members = _i(row, "vama_members_pc") + _i(row, "vama_members_hybrid") + _i(row, "vama_members_bev")
    counted = 0
    if vama_units:
        for (c, b, m), n in vama_units.items():
            m = m.replace("#pc", "")
            if c != "ICE":
                el[(c, b, m)] += n
            al[("ALL", b, m)] += n
            counted += n
    else:
        el[("HEV", market_top.REST, "")] += _i(row, "vama_members_hybrid")
        el[("BEV", market_top.REST, "")] += _i(row, "vama_members_bev")
    al[("ALL", market_top.REST, "")] += max(0, members - counted)
    vf, vfm = _i(row, "vinfast") - _i(row, "vinfast_ice"), parse_models(row.get("vinfast_models", ""))
    if sum(vfm.values()) > vf:          # revised down after the release: scale
        f = vf / sum(vfm.values())
        vfm = {k: int(v * f) for k, v in vfm.items()}
    for k, v in vfm.items():
        el[("BEV", "VINFAST", k)] += v
        al[("ALL", "VINFAST", k)] += v
    el[("BEV", "VINFAST", "")] += vf - sum(vfm.values())
    al[("ALL", "VINFAST", "")] += vf - sum(vfm.values())
    hy = _i(row, "tc_total") - _i(row, "tc_commercial")
    hym = parse_models(row.get("hyundai_models", ""))
    if sum(hym.values()) > hy:
        hym = {}
    for k, v in hym.items():
        al[("ALL", "HYUNDAI", k)] += v
    al[("ALL", "HYUNDAI", "")] += hy - sum(hym.values())
    others = _i(row, "vama_ti_pc") - members
    al[("ALL", "OTHER IMPORTS (ALL BRANDS)", "")] += others
    return ({k: v for k, v in el.items() if v}, {k: v for k, v in al.items() if v})


TOP_UNIT = ("sales (VAMA member models; VinFast and Hyundai from their own releases; "
            "non-member imports are one row; Lexus and BMW/MINI, filed by VAMA in separate "
            "sheets, count in the totals only)")


def refresh_tops(comp: dict[str, dict], vama_units: dict[str, dict | None]) -> None:
    """Re-store the months in `vama_units` (period → detail units or None)."""
    csv_rows = {p: compose(r) for p, r in comp.items() if complete(r)}
    fresh_el, fresh_all = {}, {}
    for p, vu in vama_units.items():
        if p not in csv_rows:
            continue
        total = int(float(csv_rows[p]["TOTAL"]))
        el, al = month_units(comp[p], vu)
        fresh_el[p], fresh_all[p] = (el, total), (al, total)
    if fresh_el:
        market_top.refresh_from_store(COUNTRY, SOURCE, TOP_UNIT, TOP_SLUG, fresh_el)
        market_top.refresh_from_store(COUNTRY, SOURCE, TOP_UNIT, ALL_SLUG, fresh_all)


def update_store_brand(slug: str, period: str, brand: str, units: dict) -> None:
    """Replace one brand's rows of a stored month (VinFast revision, Hyundai
    models from the next release) without re-reading the VAMA sheets."""
    path = market_top.MARKET_DIR / f"{slug}_months.json"
    store = market_top.load_store(path)
    if period not in store:
        return
    u, total = store[period]
    u = {k: v for k, v in u.items() if k[1] != brand}
    u.update({k: v for k, v in units.items() if k[1] == brand})
    store[period] = (u, total)
    market_top.save_store(path, store, COUNTRY, SOURCE)


# --------------------------------------------------------------------------
# Fetch one month
# --------------------------------------------------------------------------

def fetch_vama(session, period: str, listing: dict, args) -> tuple[dict, dict | None, str]:
    """→ (component fields, detail dict or None, note)."""
    item = listing.get(period, {})
    cover_ref = args.vama_cover or item.get("cover")
    if not cover_ref:
        return {}, None, "VAMA: not published yet"
    data = load(session, cover_ref)
    if not data:
        return {}, None, f"VAMA: cover letter not readable ({cover_ref})"
    cov = parse_cover(pdf_text(data))
    if cov.get("period") and cov["period"] != period:
        raise SystemExit(f"VAMA cover letter {cover_ref} is for {cov['period']}, not {period} — not writing")
    need = ("ti", "ti_pc", "members_pc", "members_hybrid")
    if any(k not in cov for k in need):
        raise SystemExit(f"VAMA cover letter: could not read {[k for k in need if k not in cov]} — layout changed?")
    fields = {"vama_ti": cov["ti"], "vama_ti_pc": cov["ti_pc"], "vama_ti_cv": cov["ti_cv"],
              "vama_ti_spv": cov["ti_spv"], "vama_members_pc": cov["members_pc"],
              "vama_members_hybrid": cov["members_hybrid"], "vama_members_bev": cov.get("members_bev", 0),
              "src_vama": cover_ref}  # made URL-only by the caller
    note = cov.get("ti_note", "")
    detail = None
    det_ref = args.vama_detail or item.get("detail")
    if det_ref:
        d = load(session, det_ref)
        if d:
            detail = parse_detail(d)
            detail["ref"] = det_ref
            if detail["period"] != period:
                print(f"  ! VAMA detail sheet for {period} says {detail['period']} — not used")
                detail["wrong"] = True
    return fields, detail, note


def check_detail(fields: dict, units: dict, period: str) -> None:
    hy = sum(n for (c, _, m), n in units.items() if c in ("HEV", "MHEV") and "#pc" not in m)
    if hy != int(fields["vama_members_hybrid"]):
        print(f"::warning title=Vietnam {period}::VAMA detail Hybrid rows {hy:,} ≠ cover letter "
              f"{int(fields['vama_members_hybrid']):,} (cover letter used for the series)")


def find_vinfast(session, period: str, args) -> tuple[dict, str]:
    refs = [args.vinfast_url] if args.vinfast_url else []
    if not refs:
        for lst in VINGROUP_LISTS:
            r = get(session, lst, timeout=40, tries=2)
            if r is None:
                continue
            refs += [u for u in vingroup_article_links(r.text) if u not in refs]
            if any(re.search(rf"thang-{int(period[5:])}(?:-|$)", u) for u in refs):
                break
    for ref in refs:
        data = load(session, ref)
        if not data:
            continue
        txt = data.decode("utf-8", "replace")
        if "<" in txt[:2000]:
            txt = html_text(txt)
        v = parse_vinfast(txt)
        if v.get("period") == period and v.get("units"):
            return v, ref
    return {}, ""


def find_tc(session, period: str, args) -> tuple[dict, str]:
    refs = [args.tc_url] if args.tc_url else []
    if not refs:
        for lst in TC_LISTS:
            r = get(session, lst, timeout=40, tries=2)
            if r is None:
                continue
            refs += [u for u in tc_article_links(r.text, period) if u not in refs]
            if refs:
                break
    for ref in refs:
        data = load(session, ref)
        if not data:
            continue
        v = parse_tc(data.decode("utf-8", "replace"), period)
        if v.get("total") and v.get("commercial") is not None:
            return v, ref
    return {}, ""


def src_of(ref: str, old: str = "") -> str:
    """Only URLs go into the components file: a local file passed by hand
    keeps the recorded URL, or is noted as a manual input."""
    if re.match(r"https?://", ref or ""):
        return ref
    return old or f"manual input ({Path(ref).name})"


def emit(args, changed: list[str]) -> int:
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")
            f.write(f"changed_variants={json.dumps(['Whole'] if changed else [])}\n")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--period", default="", help="Target month YYYY-MM (default: last month)")
    ap.add_argument("--force", action="store_true", help="Re-fetch a month that is already complete")
    ap.add_argument("--rebuild", action="store_true",
                    help="No network: rewrite data/Vietnam.csv from the components file")
    ap.add_argument("--dry-run", action="store_true", help="Fetch and print, write nothing")
    ap.add_argument("--vama-cover", default="", help="VAMA cover letter URL/path (skip the listing)")
    ap.add_argument("--vama-detail", default="", help="VAMA Detail sheet URL/path")
    ap.add_argument("--vinfast-url", default="", help="VinFast release URL/path (article or 6-K text)")
    ap.add_argument("--tc-url", default="", help="TC Group release URL/path")
    ap.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    args = ap.parse_args(argv)

    comp = read_components()
    if args.rebuild:
        changed = write_csv(comp)
        print(f"Rebuilt {CSV_PATH.relative_to(REPO)} from components: changed {changed or 'nothing'}")
        return emit(args, changed)

    period = args.period or default_target()
    row = dict(comp.get(period) or {"period": period})
    if complete(row) and not args.force:
        print(f"{period} already complete in the components file; nothing to do (--force to re-fetch).")
        return emit(args, [])
    print(f"Target period: {period}")
    session = make_session()

    # VAMA -----------------------------------------------------------------
    listing = {}
    if not args.vama_cover:
        for page in (VAMA_LIST, VAMA_LIST + "?Page=2"):
            r = get(session, page, timeout=60)
            if r is not None:
                for p, v in vama_listing(r.text).items():
                    listing.setdefault(p, v)
    fields, detail, vnote = fetch_vama(session, period, listing, args)
    vama_units = {}
    if fields:
        fields["src_vama"] = src_of(fields["src_vama"], row.get("src_vama", ""))
        row.update({k: str(v) for k, v in fields.items()})
        if detail and not detail.get("wrong"):
            units = detail_units(detail["rows"])
            check_detail(fields, units, period)
            row.update({k: str(v) for k, v in exceptions(units).items()}, vama_detail="ok")
            vama_units[period] = units
        else:
            row.update(vama_mhev="0", vama_hev_in_pc="0", vama_bev_in_pc="0", vama_detail="pending")
            vama_units[period] = None
        print(f"  VAMA: TI PC {row['vama_ti_pc']}, members PC {row['vama_members_pc']}, "
              f"hybrid {row['vama_members_hybrid']}, BEV {row['vama_members_bev']}, "
              f"MHEV {row['vama_mhev']}, detail {row['vama_detail']}")
        # a pending previous month can now be derived from this sheet's YTD
        prev = comp.get(prev_period(period))
        if detail and not detail.get("wrong") and prev and prev.get("vama_detail") == "pending":
            pp, pdet = prev_period(prev["period"]), None
            if prev["period"][5:] != "01":
                ref = listing.get(pp, {}).get("detail")
                raw = load(session, ref) if ref else None
                pdet = parse_detail(raw) if raw else None
                if not pdet or pdet["period"] != pp:
                    pdet = None
            if prev["period"][5:] == "01" or pdet:
                units = derive_units_from_ytd(pdet, detail, prev["period"])
                prev.update({k: str(v) for k, v in exceptions(units).items()}, vama_detail="derived")
                vama_units[prev["period"]] = units
                print(f"  VAMA {prev['period']}: model split derived from YTD (MHEV {prev['vama_mhev']})")
    else:
        print(f"  {vnote}")
    if vnote and fields:
        row["note"] = "; ".join(x for x in (row.get("note", ""), vnote) if x and vnote not in row.get("note", ""))

    # VinFast --------------------------------------------------------------
    if row.get("vinfast_kind") != "manual":
        vf, ref = find_vinfast(session, period, args)
        if vf:
            row.update(vinfast=str(vf["units"]), vinfast_ytd=str(vf.get("ytd", "")),
                       vinfast_kind="exact" if vf.get("exact") else "rounded",
                       vinfast_models=fmt_models(vf.get("models", {})),
                       src_vinfast=src_of(ref, row.get("src_vinfast", "")))
            print(f"  VinFast: {vf['units']:,} (YTD {vf.get('ytd')}), models {vf.get('models')}")
        else:
            print("  VinFast: release not found yet (vingroup.net) — enter it by hand if it does not appear")

    # TC Group -------------------------------------------------------------
    hyundai_prev = False
    tc, ref = find_tc(session, period, args)
    if tc:
        row.update(tc_total=str(tc["total"]), tc_commercial=str(tc["commercial"]),
                   hyundai_models=fmt_models(tc.get("models", {})),
                   src_tc=src_of(ref, row.get("src_tc", "")))
        print(f"  TC Group: total {tc['total']:,}, commercial {tc['commercial']:,}")
        # a month whose release had no model table takes it from this
        # release's previous-month column
        prev = comp.get(prev_period(period))
        if prev and tc.get("prev_models") and not prev.get("hyundai_models"):
            pm = tc["prev_models"]
            if sum(pm.values()) <= _i(prev, "tc_total") - _i(prev, "tc_commercial"):
                prev["hyundai_models"] = fmt_models(pm)
                hyundai_prev = True
    else:
        print("  TC Group: release not found yet (thanhcong.vn)")

    comp[period] = row
    msg = apply_vinfast_revision(comp, period)
    if msg:
        print(f"::notice title=VinFast revision::{msg}")
    if args.dry_run:
        print(json.dumps(row, ensure_ascii=False, indent=1))
        return emit(args, [])
    write_components(comp)
    if not complete(row):
        missing = [k for k in ("vama_ti_pc", "vinfast", "tc_total") if not row.get(k)]
        print(f"{period} incomplete (missing {missing}) — components saved, data/Vietnam.csv unchanged.")
        return emit(args, [])
    changed = write_csv(comp)
    print(f"data/Vietnam.csv: changed {changed or 'nothing'}")
    prevp = prev_period(period)
    if (msg or hyundai_prev) and prevp not in vama_units:
        # VinFast / Hyundai rows of the previous month changed: patch its stored month
        el, al = month_units(comp[prevp], None)
        update_store_brand(TOP_SLUG, prevp, "VINFAST", el)
        update_store_brand(ALL_SLUG, prevp, "VINFAST", al)
        update_store_brand(ALL_SLUG, prevp, "HYUNDAI", al)
    market_top.guarded(refresh_tops, comp, vama_units)
    return emit(args, changed)


if __name__ == "__main__":
    sys.exit(main())
