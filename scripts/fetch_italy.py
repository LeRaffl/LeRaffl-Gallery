#!/usr/bin/env python3
"""
Fetch Italy new registration data from UNRAE and upsert CSV files.

Variants
--------
  Whole      data/Italy.csv           — PKW whole market (inkl. Noleggio)
  Rental     data/Italy_Rental.csv    — PKW rental fleet = Whole − (al netto del noleggio)
  NonRental  data/Italy_NonRental.csv — PKW al netto del noleggio (Privati + Soc. + Autoimm.)
  Vans       data/Italy_Vans.csv      — LCV (veicoli commerciali leggeri)

Whole + Rental + NonRental all come from the same PKW "Struttura del mercato" PDF,
published on unrae.it/dati-statistici/immatricolazioni around the 1st of each
month. The PDF contains two 'Per alimentazione' tables: the first (whole market)
and the second (al netto del noleggio = fleet excluded).
  NonRental = second block (read directly).
  Rental    = Whole − NonRental (exact).

NOTE on Private/Industry: Italy's PDF does NOT expose a Private/Industry split
comparable to Denmark/Finland.  The only available sub-market split is
Whole vs. al netto del noleggio (rental excluded).  'Rental' here is the
complement: noleggio a lungo + noleggio a breve + autoimm. uso noleggio.
A per-fuel breakdown by juridical person is not available from this source.

Vans comes from UNRAE's LCV "Struttura del mercato" (autocarri ≤ 3,5 t),
on the same index page, slugged immatricolazioni-veicoli-commerciali-<mese>-<anno>,
published around the 10th of each month.  Exact counts per fuel, like the PKW
PDF; July+August come as one PDF with two tables.  The period is read from each
table's title (the slug month lags by one until 2023).  The full history back
to 2017 is built by scripts/backfill_italy_vans.py, which also derives the
monthly values the pre-2025 YTD-only tables imply.

CSV schema (all three files)
-----------------------------
    period,time_interval,variant,source,BEV,PHEV,HEV,PETROL,DIESEL,OTHERS,TOTAL,notes

PKW fuel mapping (from "Per alimentazione" table)
--------------------------------------------------
    PETROL = Benzina
    DIESEL = Diesel
    HEV    = Ibride elettriche (HEV)  (full + mild sum)
    PHEV   = Ibride elettriche plug-in (PHEV+REx)
    BEV    = Elettriche (BEV)
    OTHERS = Gpl + Metano + Idrogeno (FCEV)
    TOTAL  = Totale mercato

Vans fuel mapping (from the LCV "Per alimentazione" table)
----------------------------------------------------------
    PETROL = Benzina
    DIESEL = Diesel
    HEV    = Ibridi elettrici (HEV)    (before 2020-07: Ibrido / Ibride)
    PHEV   = Ibridi elettrici plug-in (PHEV+REx)   (empty before 2020-07)
    BEV    = Elettrici (BEV)          (before 2020-07: Elettrico / Elettriche)
    OTHERS = Gpl + Metano (+ Idrogeno, not listed so far)
    TOTAL  = totale

See docs/architecture/18-source-italy.md for the full pipeline context.

Usage
-----
    python scripts/fetch_italy.py [--variant all|pkw|Whole|Rental|Vans]
                                  [--pdf-url URL --year Y --month M]
                                  [--vans-pdf-url URL]
                                  [--force]
"""
import argparse
import csv
import os
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_top  # noqa: E402

STRUTTURA_INDEX = "https://unrae.it/dati-statistici/immatricolazioni"
SOURCE          = "unrae.it"
USER_AGENT      = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) BEV-Gallery-Bot"

VARIANT_CONFIG: dict[str, dict] = {
    "Whole":     {"csv": "data/Italy.csv",           "pkw": True},
    "Rental":    {"csv": "data/Italy_Rental.csv",    "pkw": True},
    "NonRental": {"csv": "data/Italy_NonRental.csv", "pkw": True},
    "Vans":      {"csv": "data/Italy_Vans.csv",      "pkw": False},
}

IT_MONTHS = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}

CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL", "notes",
]


# ── helpers ────────────────────────────────────────────────────────────────

def previous_month_period() -> str:
    t = date.today()
    if t.month == 1:
        return f"{t.year - 1}-12"
    return f"{t.year}-{t.month - 1:02d}"


def csv_has_period(csv_path: str, period: str, variant: str) -> bool:
    if not os.path.exists(csv_path):
        return False
    with open(csv_path, newline="", encoding="utf-8") as f:
        return any(r["period"] == period and r["variant"] == variant
                   for r in csv.DictReader(f))


def http_get(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    return r.text


def download_pdf(url: str, dest: Path) -> None:
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    r.raise_for_status()
    dest.write_bytes(r.content)


def pdf_to_text(pdf_path: Path) -> str:
    try:
        out = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            check=True, capture_output=True, text=True,
        )
    except FileNotFoundError:
        sys.exit("pdftotext not found. Install poppler-utils.")
    return out.stdout


# ── PKW discovery ─────────────────────────────────────────────────────────

def find_latest_struttura(index_html: str) -> tuple[str, int, int]:
    """Return (detail_url, year, month) of the newest struttura bulletin."""
    pat = re.compile(
        r'href="(https://unrae\.it/dati-statistici/immatricolazioni/\d+/'
        r'struttura-del-mercato-([a-z]+)-(\d{4}))"',
        re.IGNORECASE,
    )
    best: tuple[int, int, str] | None = None
    for url, mese, anno in pat.findall(index_html):
        m = IT_MONTHS.get(mese.lower())
        if not m:
            continue
        key = (int(anno), m)
        if best is None or key > (best[0], best[1]):
            best = (key[0], key[1], url)
    if best is None:
        raise RuntimeError("No 'struttura del mercato' link found on UNRAE index page.")
    return best[2], best[0], best[1]


def find_struttura_pdf_url(detail_html: str) -> str:
    pat = re.compile(
        r'href="(https://unrae\.it/files/[^"]*Struttura del mercato[^"]+\.pdf)"',
        re.IGNORECASE,
    )
    m = pat.search(detail_html)
    if not m:
        raise RuntimeError("No 'Struttura del mercato' PDF link found on detail page.")
    return m.group(1)


# ── PKW parsing ────────────────────────────────────────────────────────────

_NUM = re.compile(r"-?\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+")


def first_int(line: str) -> int:
    """First integer in `line`. UNRAE uses '.' as thousands sep, ',' as decimal."""
    m = _NUM.search(line)
    if not m:
        raise ValueError(f"No number in line: {line!r}")
    tok = m.group(0).replace(".", "")
    if "," in tok:
        tok = tok.split(",", 1)[0]
    return int(tok)


def _parse_alimentazione_block(lines: list[str], start: int, end: int) -> dict:
    """Parse a 'Per alimentazione' table block from PDF lines [start, end)."""
    block = lines[start:end]

    def find_value(prefix: str) -> int:
        for ln in block:
            if ln.lstrip().startswith(prefix):
                return first_int(ln)
        raise RuntimeError(f"Row {prefix!r} not found in 'Per alimentazione' block.")

    petrol = find_value("Benzina")
    diesel = find_value("Diesel")
    gpl    = find_value("Gpl")
    metano = find_value("Metano")
    hev    = find_value("Ibride elettriche (HEV)")
    phev   = find_value("Ibride elettriche plug-in")
    bev    = find_value("Elettriche (BEV)")
    fcev   = find_value("Idrogeno (FCEV)")
    total  = find_value("Totale mercato")

    return {
        "BEV":    bev,
        "PHEV":   phev,
        "HEV":    hev,
        "PETROL": petrol,
        "DIESEL": diesel,
        "OTHERS": gpl + metano + fcev,
        "TOTAL":  total,
    }


def parse_pkw(text: str) -> tuple[dict, dict, dict]:
    """Parse the PKW Struttura del mercato PDF and return (whole, rental, nonrental).

      whole     = first 'Per alimentazione' block (whole market, inkl. Noleggio)
      nonrental = second block = "al netto del noleggio" (Privati + Società + Autoimm.,
                  read directly from the PDF)
      rental    = Whole − NonRental = rental fleet only
                  (noleggio a lungo termine + noleggio a breve + autoimm. uso noleggio)

    Rental is exact — zero rounding error — because both source blocks come from
    the same table.

    The PDF has exactly two 'Per alimentazione' section headers; each ends at
    the following 'Per segmento' header.
    """
    lines = text.splitlines()

    alim_starts = [i for i, ln in enumerate(lines) if "Per alimentazione" in ln]
    if len(alim_starts) < 2:
        raise RuntimeError(
            f"Expected ≥2 'Per alimentazione' blocks in PKW PDF, found {len(alim_starts)}."
        )

    def block_end(start: int) -> int:
        for j in range(start + 1, len(lines)):
            if "Per segmento" in lines[j]:
                return j
        return len(lines)

    whole_cols     = _parse_alimentazione_block(lines, alim_starts[0], block_end(alim_starts[0]))
    nonrental_cols = _parse_alimentazione_block(lines, alim_starts[1], block_end(alim_starts[1]))
    rental_cols    = {k: whole_cols[k] - nonrental_cols[k] for k in whole_cols}
    return whole_cols, rental_cols, nonrental_cols


# ── LCV discovery ─────────────────────────────────────────────────────────
#
# UNRAE publishes a "Struttura del mercato" for autocarri ≤ 3,5 t on the same
# index as the PKW one, slugged immatricolazioni-veicoli-commerciali-<mese>-<anno>
# (July+August share one page: "luglio-agosto", "luglio-e-agosto",
# "luglioagosto"...).  The slug month is NOT the data month — until 2023 the
# page for month M carried data up to M−1 — so the parser takes the period
# from each table's own title, never from the slug.

_LCV_LINK = re.compile(
    r'href="((?:https?://unrae\.it)?/dati-statistici/immatricolazioni/(\d+)/'
    r'immatricolazioni-veicoli-commerciali-[a-z-]*?\d{4})"',
    re.IGNORECASE,
)


def find_lcv_pages(index_html: str) -> list[str]:
    """LCV struttura detail URLs on an index page, newest (highest id) first."""
    found: dict[int, str] = {}
    for url, page_id in _LCV_LINK.findall(index_html):
        if url.startswith("/"):
            url = "https://unrae.it" + url
        found[int(page_id)] = url
    return [found[k] for k in sorted(found, reverse=True)]


LCV_MAX_INDEX_PAGES = 5


def find_latest_lcv_page() -> str | None:
    """Newest LCV struttura page.  Walks the paginated index: once the next
    month's passenger-car tables are out (~1st), the last LCV page has slid
    to page 2 until the next LCV table appears (~10th)."""
    for page in range(1, LCV_MAX_INDEX_PAGES + 1):
        url = STRUTTURA_INDEX + (f"?page={page}" if page > 1 else "")
        pages = find_lcv_pages(http_get(url))
        if pages:
            return pages[0]
    return None


def find_lcv_pdf_url(detail_html: str) -> str | None:
    """The PDF attached to an LCV struttura page; None if the page has none
    (a handful of months were published without an attachment)."""
    m = re.search(r'href="((?:https?://unrae\.it)?/files/[^"]+\.pdf)"', detail_html, re.I)
    if not m:
        return None
    url = m.group(1)
    return "https://unrae.it" + url if url.startswith("/") else url


# ── LCV parsing ────────────────────────────────────────────────────────────
#
# Each 'Per alimentazione' table has, per fuel, either
#   2 counts  [YTD current year, YTD comparison year]                (≤ 2025-01)
#   4 counts  [month cur, month cmp, YTD cur, YTD cmp]               (≥ 2025-02)
# plus %-columns, which are ignored.  Counts are matched to columns by their
# right edge against the 'totale' row, because an empty cell means 0 (Metano
# is often blank) and would otherwise shift every later value.
#
# The comparison year is read from the header, not assumed to be year−1:
# the 2021 tables compare against 2019 (pre-COVID), not 2020.

_LCV_ROWS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^Ibrid[ie] elettric[ih]e? plug-in", re.I),  "PHEV"),
    (re.compile(r"^Ibrid[ie] elettric[ih]e? \(HEV\)", re.I),   "HEV"),
    (re.compile(r"^Ibrid[eo]$", re.I),                         "HEV"),   # ≤ 2020, incl. PHEV
    (re.compile(r"^Elettric[ih]e? \(BEV\)", re.I),             "BEV"),
    (re.compile(r"^Elettric(?:he|o)$", re.I),                  "BEV"),
    (re.compile(r"^Diesel$", re.I),                            "DIESEL"),
    (re.compile(r"^Benzina$", re.I),                           "PETROL"),
    (re.compile(r"^Gpl$", re.I),                               "GPL"),
    (re.compile(r"^Metano$", re.I),                            "METANO"),
    (re.compile(r"^Idrogeno", re.I),                           "H2"),
    (re.compile(r"^totale$"),                                  "TOTAL"),
]
LCV_FUELS = ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "GPL", "METANO", "H2", "TOTAL"]

_LCV_TITLE = re.compile(
    r"IMMATRICOLAZIONI\s*-\s*(?:Gennaio\s*/\s*)?([A-Za-z]+)\s+(\d{4})", re.IGNORECASE)
_LCV_INT   = re.compile(r"(?<![\d,.+-])\d{1,3}(?:\.\d{3})*(?![\d,.])")
_LCV_YEAR  = re.compile(r"(?<![/\d])(20\d\d)(?![/\d])")


def _lcv_label(line: str) -> str:
    return re.split(r"\s{2,}|\s+(?=[+-]?\d)", line.strip())[0]


def parse_lcv_struttura(text: str) -> list[dict]:
    """Parse every 'Per alimentazione' table of an LCV struttura PDF.

    Returns one dict per table:
      year, month   period the table belongs to (from its title)
      cmp_year      comparison year (from its header)
      month_cur     {fuel: count} for that month, or None (YTD-only layout)
      month_cmp     same month of cmp_year, or None
      ytd_cur       January..month of year
      ytd_cmp       January..month of cmp_year
    Fuel dicts use LCV_FUELS; a fuel the table doesn't list is None
    (no PHEV row before 2020-07, no hydrogen row at all so far).
    In January tables month == YTD, so month_cur/month_cmp are filled too.
    Every column must add up exactly to its 'totale'.
    """
    lines = text.splitlines()
    out: list[dict] = []
    for s in [i for i, ln in enumerate(lines) if "Per alimentazione" in ln]:
        title = next((_LCV_TITLE.search(lines[j]) for j in range(s, max(s - 60, -1), -1)
                      if _LCV_TITLE.search(lines[j])), None)
        if not title or title.group(1).lower() not in IT_MONTHS:
            raise RuntimeError(f"LCV: no 'IMMATRICOLAZIONI - <mese> <anno>' title above line {s}.")
        month, year = IT_MONTHS[title.group(1).lower()], int(title.group(2))

        raw: dict[str, str] = {}
        header: list[str] = []
        for ln in lines[s:s + 30]:
            key = next((k for p, k in _LCV_ROWS if p.search(_lcv_label(ln))), None)
            if key is None:
                if not raw:
                    header.append(ln)
                continue
            raw[key] = ln
            if key == "TOTAL":
                break
        if "TOTAL" not in raw:
            raise RuntimeError(f"LCV {year}-{month:02d}: 'totale' row not found.")

        cmp_years = {int(y) for y in _LCV_YEAR.findall(" ".join(header))} - {year}
        if len(cmp_years) != 1:
            raise RuntimeError(f"LCV {year}-{month:02d}: comparison year unclear {cmp_years}.")

        edges = [m.end() for m in _LCV_INT.finditer(raw["TOTAL"])]
        if len(edges) not in (2, 4):
            raise RuntimeError(f"LCV {year}-{month:02d}: expected 2 or 4 counts in 'totale', "
                               f"got {len(edges)}.")
        cols = [{k: None for k in LCV_FUELS} for _ in edges]
        for key, ln in raw.items():
            for c in cols:
                c[key] = 0
            for m in _LCV_INT.finditer(ln):
                j = min(range(len(edges)), key=lambda e: abs(edges[e] - m.end()))
                if abs(edges[j] - m.end()) > 6:
                    raise RuntimeError(f"LCV {year}-{month:02d} {key}: "
                                       f"value {m.group(0)!r} matches no column.")
                cols[j][key] = int(m.group(0).replace(".", ""))
        for c in cols:
            parts = sum(c[k] or 0 for k in LCV_FUELS if k != "TOTAL")
            if parts != c["TOTAL"]:
                raise RuntimeError(f"LCV {year}-{month:02d}: fuels sum to {parts}, "
                                   f"totale {c['TOTAL']}.")

        if len(cols) == 4:
            m_cur, m_cmp, y_cur, y_cmp = cols
        else:
            y_cur, y_cmp = cols
            m_cur, m_cmp = (y_cur, y_cmp) if month == 1 else (None, None)
        out.append({"year": year, "month": month, "cmp_year": cmp_years.pop(),
                    "month_cur": m_cur, "month_cmp": m_cmp,
                    "ytd_cur": y_cur, "ytd_cmp": y_cmp})
    return out


def lcv_to_cols(f: dict) -> dict:
    """Map an LCV fuel dict onto the CSV columns.  OTHERS = Gpl + Metano
    (+ Idrogeno).  PHEV stays empty where the table has no PHEV row (before
    2020-07, 'Ibrido' is the only hybrid line)."""
    return {
        "BEV": f["BEV"], "PHEV": "" if f["PHEV"] is None else f["PHEV"],
        "HEV": f["HEV"], "PETROL": f["PETROL"], "DIESEL": f["DIESEL"],
        "OTHERS": f["GPL"] + f["METANO"] + (f["H2"] or 0),
        "TOTAL": f["TOTAL"],
    }


# ── Top brands / models (market/italy_top.json) ───────────────────────────
#
# UNRAE publishes, next to the struttura, one PDF per month per class:
# "Immatricolazioni BEV per modello" / "PHEV per modello" — every model
# (top 100 since 2026-05) with brand, plus "altre" and "Totale", always
# JANUARY-TO-DATE.  So:
#   single month M   = list(M) − list(M−1)          (January: list(1) itself)
#   trailing 12 at T = list(T) + list(Dec T−1) − list(T, year−1)
# The 12-month headline is computed directly from three lists, not by adding
# up single months, so it is exact even where a month is missing (UNRAE
# published no January 2026 lists) or where a month's difference is distorted
# by a reclassification (Kia Sportage left the PHEV list in May 2026: −3 049).
# Model names are compared on letters and digits only ("ATTO2" = "ATTO 2",
# "N? 4" = "N4"), and a trailing plug-in drive name is dropped ("SEAL U DM-I"
# = "SEAL U": UNRAE added BYD's "DM-I" in the 2026-09 lists); a model's
# negative difference is not ranked, and the class total of the difference
# goes to the unranked rest.  A rename the key still misses would credit the
# new name with its whole year to date in one month; _check_renames aborts
# the refresh on that pattern instead of publishing it.  HEV has only a top-10
# list at UNRAE, so it is not ranked.  Whole only: no table crosses brand
# with the rental channel.  See docs/architecture/18-source-italy.md §10.

TOP_PATH   = market_top.MARKET_DIR / "italy_top.json"
TOP_SLUG   = "italy"
TOP_SOURCE = "UNRAE"
TOP_UNIT   = ("registrations (brand / model as in UNRAE's 'Immatricolazioni BEV / PHEV "
              "per modello' January-to-date lists; single months are differences of "
              "consecutive lists)")
TOP_CLASSES = ("BEV", "PHEV")
TOP_MAX_INDEX_PAGES = 40
# A model that vanishes between two lists with at least this many units to
# date, while a new model of the same brand appears with at least as many, is
# taken for an uncaught rename (2026-09: "ATTO 2" 14 716 → "ATTO 2 DM-I"
# 16 089).  Models crossing rank 100 (§10 M5) have a few dozen units.
TOP_RENAME_MIN = 500

_MODEL_LIST_LINK = re.compile(
    r'href="((?:https?://unrae\.it)?/dati-statistici/immatricolazioni/\d+/'
    r'immatricolazioni-(bev|phev)-per-modello-([a-z]+)-(\d{4}))"', re.IGNORECASE)
_ML_TITLE = re.compile(
    r"FUORISTRADA\s+(BEV|PHEV)\s*-\s*(?:(\d+)\s*mesi|([a-z]+))\s+(\d{4})", re.IGNORECASE)
_ML_TAIL  = re.compile(r"(\d{1,3}(?:\.\d{3})*)\s+\d{1,3},\d+\s*$")
# Ranked rows that are really UNRAE's own catch-alls.
_ML_CATCH_ALL = {"ALTRE ESTERE", "ALTRE NAZIONALI"}
# A plug-in drive name after the model (BYD DM-i / DM-p / DM-o, Geely EM-i):
# the class already says it, and UNRAE adds or drops it between lists.
_ML_DRIVE_SUFFIX = re.compile(r"\s+(?:DM-?[IPO]|EM-?I)\s*$", re.IGNORECASE)


def _strip_drive(model: str) -> str:
    return _ML_DRIVE_SUFFIX.sub("", model)


def _model_key(brand: str, model: str) -> tuple[str, str]:
    return (re.sub(r"[^A-Z0-9]", "", brand.upper()),
            re.sub(r"[^A-Z0-9]", "", _strip_drive(model).upper()))


def _display(s: str) -> str:
    # pdftotext renders the degree sign of "N° 4" (DS) as '?'
    return market_top.clean(_strip_drive(s.replace("?", "°")))


def parse_model_list(text: str) -> dict:
    """One 'Immatricolazioni BEV|PHEV per modello' PDF (January-to-date).

    Returns {"cls", "period", "models": {key: (brand, model, n)}, "rest", "total"}
    where key = _model_key(brand, model).  Models + rest must equal Totale."""
    lines = text.splitlines()
    title = next((_ML_TITLE.search(ln) for ln in lines if _ML_TITLE.search(ln)), None)
    if not title:
        raise RuntimeError("model list: no 'AUTOVETTURE E FUORISTRADA BEV|PHEV - …' title")
    cls, year = title.group(1).upper(), int(title.group(4))
    if title.group(2):
        month = int(title.group(2))
    elif title.group(3).lower() in IT_MONTHS:
        month = IT_MONTHS[title.group(3).lower()]
    else:
        raise RuntimeError(f"model list: unreadable period {title.group(0)!r}")
    models: dict[tuple[str, str], tuple[str, str, int]] = {}
    rest = total = None
    for ln in lines:
        tail = _ML_TAIL.search(ln)
        if not tail:
            continue
        n, head = int(tail.group(1).replace(".", "")), ln.strip().lower()
        if head.startswith("altre"):
            rest = (rest or 0) + n
            continue
        if head.startswith("totale"):
            total = n
            break
        row = re.match(r"\s*\d+\s+(.*)", ln)
        if not row:
            continue
        parts = re.split(r"\s{2,}", row.group(1).strip())
        brand, model = parts[0], parts[1]
        if brand.upper() in _ML_CATCH_ALL:
            rest = (rest or 0) + n
            continue
        key = _model_key(brand, model)
        prev = models.get(key, (brand, model, 0))[2]
        models[key] = (_display(brand), _display(model), prev + n)
    if total is None or rest is None:
        raise RuntimeError(f"model list {cls} {year}-{month:02d}: no 'altre' / 'Totale' row")
    if sum(v[2] for v in models.values()) + rest != total:
        raise RuntimeError(f"model list {cls} {year}-{month:02d}: rows do not add up to {total}")
    return {"cls": cls, "period": f"{year}-{month:02d}", "models": models,
            "rest": rest, "total": total}


def _combine(lists: list[tuple[int, dict]], cls: str) -> tuple[dict, int]:
    """Signed sum of model lists → ({(cls, brand, model): n>0} incl. REST, class total).

    A negative model sum (a rename the key does not catch, a reclassification,
    a model that dropped below the top 100) is not ranked; whatever the ranked
    models do not explain goes to the unranked rest (never below 0)."""
    names: dict = {}
    sums: dict = {}
    total = 0
    for sign, lst in lists:
        total += sign * lst["total"]
        for key, (b, m, n) in lst["models"].items():
            sums[key] = sums.get(key, 0) + sign * n
            if sign > 0 or key not in names:
                names[key] = (b, m)
    units = {(cls, *names[k]): n for k, n in sums.items() if n > 0}
    rest = total - sum(units.values())
    if rest > 0:
        units[(cls, market_top.REST, "")] = rest
    return units, total


def _check_renames(cur: dict, prev: dict) -> None:
    """Raise when a model of `prev` is missing from `cur` while a model of the
    same brand that `prev` lacks has at least its units: a rename _model_key
    does not catch, which the month difference would show as a whole year to
    date.  A model that simply leaves the list (Kia Sportage, §10 M8) passes."""
    gone = {k: v for k, v in prev["models"].items()
            if k not in cur["models"] and v[2] >= TOP_RENAME_MIN}
    new = {k: v for k, v in cur["models"].items() if k not in prev["models"]}
    for gk, (gb, gm, gn) in gone.items():
        for nk, (_, nm, nn) in new.items():
            if nk[0] == gk[0] and nn >= gn:
                raise RuntimeError(
                    f"{cur['cls']} {prev['period']} → {cur['period']}: {gb} {gm!r} ({gn:,}) "
                    f"is gone and {nm!r} ({nn:,}) is new — an unmatched rename? "
                    "Extend _model_key (§10 M6).")


def find_model_lists(wanted: set[str] | None = None) -> dict[tuple[str, str], str]:
    """{(cls, 'YYYY-MM'): page URL} from the paginated UNRAE index.  Walks pages
    until every period in `wanted` (and both classes of it) has been seen, or
    TOP_MAX_INDEX_PAGES; with wanted=None until one month has both classes
    (the newest lists are usually on page 1 or 2)."""
    found: dict[tuple[str, str], str] = {}
    for page in range(1, TOP_MAX_INDEX_PAGES + 1):
        url = STRUTTURA_INDEX + (f"?page={page}" if page > 1 else "")
        for href, cls, mese, anno in _MODEL_LIST_LINK.findall(http_get(url)):
            if mese.lower() not in IT_MONTHS:
                continue
            href = "https://unrae.it" + href if href.startswith("/") else href
            found.setdefault((cls.upper(), f"{anno}-{IT_MONTHS[mese.lower()]:02d}"), href)
        if wanted is None:
            if any(all((c, p) in found for c in TOP_CLASSES) for _, p in found):
                break
            continue
        if all((c, p) in found for p in wanted for c in TOP_CLASSES):
            break
        if found and min(p for _, p in found) < _shift(min(wanted), -1):
            break        # walked past the oldest wanted month (one month of slack:
                         # BEV and PHEV of a month can sit on neighbouring pages)
    return found


def _shift(period: str, months: int) -> str:
    y, m = map(int, period.split("-"))
    m += months
    while m < 1:
        y, m = y - 1, m + 12
    while m > 12:
        y, m = y + 1, m - 12
    return f"{y}-{m:02d}"


def refresh_market_top() -> None:
    """Rebuild market/italy_top.json (+ month store) for the newest month UNRAE
    has published both model lists for.  Downloads only what the store lacks."""
    newest = find_model_lists()
    targets = [p for (c, p) in newest if all((k, p) in newest for k in TOP_CLASSES)]
    if not targets:
        raise RuntimeError("no month with both BEV and PHEV model lists on the UNRAE index")
    target = max(targets)
    totals = market_top.csv_totals(VARIANT_CONFIG["Whole"]["csv"])
    if target not in totals:
        raise RuntimeError(f"data/Italy.csv has no {target} row yet")

    store_path = market_top.MARKET_DIR / f"{TOP_SLUG}_months.json"
    stored = market_top.load_store(store_path)
    window = market_top.month_window(target)
    need_months = [p for p in window if p not in stored]
    ttm = [target] if target.endswith("-12") else \
        [target, f"{int(target[:4]) - 1}-12", _shift(target, -12)]
    wanted = set(ttm) | set(need_months) | {_shift(p, -1) for p in need_months
                                           if not p.endswith("-01")}
    urls = find_model_lists(wanted)

    lists: dict[tuple[str, str], dict] = {}

    def get(cls: str, period: str) -> dict | None:
        if (cls, period) not in lists:
            page = urls.get((cls, period))
            pdf = find_lcv_pdf_url(http_get(page)) if page else None
            if pdf is None:
                return None
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / "list.pdf"
                download_pdf(pdf, path)
                lst = parse_model_list(pdf_to_text(path))
            if (lst["cls"], lst["period"]) != (cls, period):
                raise RuntimeError(f"{page}: PDF is {lst['cls']} {lst['period']}")
            lists[(cls, period)] = lst
        return lists[(cls, period)]

    empty = {"models": {}, "rest": 0, "total": 0}
    fresh: dict[str, tuple[dict, int]] = {}
    for p in need_months:
        units: dict = {}
        for cls in TOP_CLASSES:
            cur = get(cls, p)
            prev = empty if p.endswith("-01") else get(cls, _shift(p, -1))
            if cur is None or prev is None or p not in totals:
                break
            if "period" in prev:
                _check_renames(cur, prev)
            u, _ = _combine([(1, cur), (-1, prev)], cls)
            units.update(u)
        else:
            fresh[p] = (units, totals[p])
    monthly = {**stored, **fresh}
    market_top.save_store(store_path, monthly, "Italy", TOP_SOURCE)

    top = market_top.build_top_monthly("Italy", TOP_SOURCE, target, monthly, TOP_UNIT)
    head_units: dict = {}
    ttm_lists = {cls: [get(cls, p) for p in ttm] for cls in TOP_CLASSES}
    if all(lst is not None for ls in ttm_lists.values() for lst in ls) \
            and all(p in totals for p in window):
        for cls, ls in ttm_lists.items():
            signs = [1] if len(ls) == 1 else [1, 1, -1]
            u, class_total = _combine(list(zip(signs, ls)), cls)
            head_units.update(u)
            csv_class = sum(_csv_class(p, cls) for p in window)
            print(f"  {cls} trailing 12 months: lists {class_total:,} vs data/Italy.csv "
                  f"{csv_class:,} ({(class_total - csv_class) / csv_class:+.2%})")
        ttm_total = sum(totals[p] for p in window)
        head = market_top.build_top("Italy", TOP_SOURCE, target, head_units, ttm_total, TOP_UNIT)
        top["classes"], top["total_registrations"] = head["classes"], ttm_total
        top["window"] = {"from": window[0], "to": window[-1], "months": 12}
    else:
        print("  trailing-12 lists incomplete; headline = sum of the stored single months")
    market_top.report(top, TOP_PATH, market_top.write_top(top, TOP_PATH))


def _csv_class(period: str, cls: str) -> int:
    with open(VARIANT_CONFIG["Whole"]["csv"], newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["period"] == period and r["variant"] == "Whole":
                return int(float(r[cls] or 0))
    return 0


# ── sanity + upsert ────────────────────────────────────────────────────────

def sanity_check(cols: dict, period: str, strict: bool = True) -> None:
    """Verify BEV+PHEV+HEV+PETROL+DIESEL+OTHERS ≈ TOTAL, none negative.
    An empty cell ('', no split in the source) counts as 0 here."""
    parts = [cols[k] or 0 for k in ("BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS")]
    core  = sum(parts)
    total = cols["TOTAL"]
    if total <= 0:
        raise RuntimeError(f"{period}: TOTAL is {total}; refusing to write.")
    if min(parts) < 0:
        raise RuntimeError(f"{period}: negative count in {cols}; refusing to write.")
    # Strict (table-parsed): max(50, 0.5%).  Lenient: max(200, 2%) — unused since
    # Vans moved from the press-release percentages to the struttura table.
    tol = max(50, total * 0.005) if strict else max(200, total * 0.02)
    if abs(core - total) > tol:
        raise RuntimeError(
            f"{period}: sum={core} vs TOTAL={total} (diff={core - total}); "
            f"tolerance={tol:.0f}; refusing to write."
        )


def upsert(csv_path: str, period: str, cols: dict, variant: str,
           notes: str = "") -> tuple[str, dict | None]:
    """Write/replace the row for (period, variant) in csv_path.
    An empty cell ('') in `cols` stays empty — never written as 0.
    Returns ('added'|'updated'|'unchanged', old_row).
    """
    rows: list[dict] = []
    old: dict | None = None
    if os.path.exists(csv_path):
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                for c in CSV_COLUMNS:
                    row.setdefault(c, "")
                if row["period"] == period and row["variant"] == variant:
                    old = row
                else:
                    rows.append(row)

    new_row = {
        "period": period, "time_interval": "monthly", "variant": variant, "source": SOURCE,
        "BEV": cols["BEV"], "PHEV": cols["PHEV"], "HEV": cols["HEV"],
        "PETROL": cols["PETROL"], "DIESEL": cols["DIESEL"],
        "OTHERS": cols["OTHERS"], "TOTAL": cols["TOTAL"], "notes": notes,
    }

    # Preserve existing notes when the script writes empty notes.
    if not new_row["notes"] and old is not None:
        new_row["notes"] = old.get("notes", "")

    status = "added" if old is None else "updated"
    if old is not None:
        for c in ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL"]:
            ov = float(old.get(c) or 0)
            nv = float(new_row[c] or 0)
            if ov > 100 and abs(nv - ov) / ov > 0.1:
                print(f"  WARNING {c}: existing={ov:.0f}, new={nv:.0f} — drift >10%")
        if all(str(old.get(c) or "") == str(new_row[c])
               for c in ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL"]) \
                and old.get("notes", "") == new_row["notes"]:
            status = "unchanged"

    rows.append(new_row)
    rows.sort(key=lambda r: (r["variant"], r["period"]))

    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return status, old


# ── Vans (LCV) ─────────────────────────────────────────────────────────────

PRIOR_YEAR_NOTE = "from the following year's UNRAE table (comparison column)"


def fetch_vans(args: argparse.Namespace, prev: str) -> None:
    """Upsert every month the latest LCV struttura PDF covers.

    A combined July+August PDF yields both months.  Each table's comparison
    column also fills the same month one year earlier, but only if that month
    is missing — the source occasionally publishes a page without its PDF
    (e.g. 2025-11, 2025-12), and the next year's table is the only other copy.
    """
    csv_path = VARIANT_CONFIG["Vans"]["csv"]
    if not args.force and csv_has_period(csv_path, prev, "Vans"):
        print(f"Vans already has {prev}; nothing to do.")
        return

    if args.vans_pdf_url:
        pdf_url = args.vans_pdf_url
        print(f"Using supplied LCV PDF: {pdf_url}")
    else:
        print(f"Fetching index: {STRUTTURA_INDEX}")
        latest = find_latest_lcv_page()
        if latest is None:
            raise RuntimeError("No 'immatricolazioni-veicoli-commerciali' link on the first "
                               f"{LCV_MAX_INDEX_PAGES} UNRAE index pages.")
        print(f"Latest LCV struttura: {latest}")
        pdf_url = find_lcv_pdf_url(http_get(latest))
        if pdf_url is None:
            # Happened for 2025-11/12 and 2026-05: a source gap, not a parse
            # failure.  The next year's comparison column fills the month.
            print(f"::warning::No PDF attached to {latest}; Vans month skipped.")
            return
        print(f"LCV PDF: {pdf_url}")

    with tempfile.TemporaryDirectory() as td:
        pdf_path = Path(td) / "lcv.pdf"
        download_pdf(pdf_url, pdf_path)
        text = pdf_to_text(pdf_path)

    tables = parse_lcv_struttura(text)
    if not tables:
        raise RuntimeError("No 'Per alimentazione' table in the LCV PDF.")
    for t in sorted(tables, key=lambda t: t["month"]):
        if t["month_cur"] is None:
            raise RuntimeError(
                f"LCV {t['year']}-{t['month']:02d}: table is YTD-only (pre-2025 layout); "
                "monthly values need scripts/backfill_italy_vans.py.")
        targets = [(f"{t['year']}-{t['month']:02d}", t["month_cur"], "")]
        if t["cmp_year"] == t["year"] - 1:
            targets.append((f"{t['cmp_year']}-{t['month']:02d}", t["month_cmp"], PRIOR_YEAR_NOTE))
        for period, fuels, note in targets:
            exists = csv_has_period(csv_path, period, "Vans")
            if exists and (note or not args.force):
                if not note:
                    print(f"Vans {period} already in CSV; skipping.")
                continue
            cols = lcv_to_cols(fuels)
            print(f"Parsed Vans {period}: " + " ".join(f"{k}={v}" for k, v in cols.items())
                  + (" (prior-year column)" if note else ""))
            sanity_check(cols, period, strict=True)
            status, _ = upsert(csv_path, period, cols, "Vans", notes=note)
            print(f"Vans {period} {status} -> {csv_path}")


# ── main ───────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--variant", default="all",
        help="Variants to fetch: all | pkw | Whole | Rental | NonRental | Vans  (default: all). "
             "'pkw' is an alias for Whole+Rental+NonRental.",
    )
    ap.add_argument("--force", action="store_true",
                    help="Re-process even if the target period already exists.")
    ap.add_argument("--pdf-url", default="",
                    help="Direct PKW Struttura PDF URL (skips index/detail scraping).")
    ap.add_argument("--vans-pdf-url", default="",
                    help="Direct LCV struttura PDF URL (skips index scraping; "
                         "periods come from the PDF's own titles).")
    ap.add_argument("--year",  type=int, help="Target year  (required with --pdf-url).")
    ap.add_argument("--month", type=int, help="Target month (required with --pdf-url).")
    args = ap.parse_args()

    alias_map = {
        "all": ["Whole", "Rental", "NonRental", "Vans"],
        "pkw": ["Whole", "Rental", "NonRental"],
    }
    variants  = alias_map.get(args.variant, [args.variant])
    for v in variants:
        if v not in VARIANT_CONFIG:
            sys.exit(f"Unknown variant {v!r}. Valid: {list(VARIANT_CONFIG)} plus 'all'/'pkw'.")

    prev         = previous_month_period()
    pkw_variants = [v for v in variants if VARIANT_CONFIG[v]["pkw"]]
    lcv_variants = [v for v in variants if not VARIANT_CONFIG[v]["pkw"]]

    # ── PKW: Whole + Private (one PDF download) ──────────────────────────

    if pkw_variants:
        need_pkw = args.force or any(
            not csv_has_period(VARIANT_CONFIG[v]["csv"], prev, v) for v in pkw_variants
        )
        if not need_pkw:
            print(f"PKW variants {pkw_variants} already have {prev}; nothing to do.")
        else:
            if args.pdf_url:
                if not (args.year and args.month):
                    sys.exit("--pdf-url requires --year and --month.")
                pkw_pdf_url = args.pdf_url
                year, month = args.year, args.month
                print(f"Using supplied PKW PDF: {pkw_pdf_url} -> {year}-{month:02d}")
            else:
                print(f"Fetching index: {STRUTTURA_INDEX}")
                index_html   = http_get(STRUTTURA_INDEX)
                detail_url, year, month = find_latest_struttura(index_html)
                print(f"Latest PKW bulletin: {year}-{month:02d}  ({detail_url})")
                detail_html  = http_get(detail_url)
                pkw_pdf_url  = find_struttura_pdf_url(detail_html)
                print(f"PKW PDF: {pkw_pdf_url}")

            period = f"{year}-{month:02d}"
            if not args.force and all(
                csv_has_period(VARIANT_CONFIG[v]["csv"], period, v) for v in pkw_variants
            ):
                print(f"PKW variants {pkw_variants} already have {period}; nothing to do.")
            else:
                with tempfile.TemporaryDirectory() as td:
                    pdf_path = Path(td) / "struttura.pdf"
                    download_pdf(pkw_pdf_url, pdf_path)
                    text = pdf_to_text(pdf_path)

                whole_cols, rental_cols, nonrental_cols = parse_pkw(text)

                for v, cols in [
                    ("Whole",     whole_cols),
                    ("Rental",    rental_cols),
                    ("NonRental", nonrental_cols),
                ]:
                    if v not in pkw_variants:
                        continue
                    if not args.force and csv_has_period(VARIANT_CONFIG[v]["csv"], period, v):
                        print(f"{v} {period} already in CSV; skipping.")
                        continue
                    print(f"Parsed {v} {period}: BEV={cols['BEV']} PHEV={cols['PHEV']} "
                          f"HEV={cols['HEV']} PETROL={cols['PETROL']} "
                          f"DIESEL={cols['DIESEL']} OTHERS={cols['OTHERS']} "
                          f"TOTAL={cols['TOTAL']}")
                    sanity_check(cols, period, strict=True)
                    status, _ = upsert(VARIANT_CONFIG[v]["csv"], period, cols, v)
                    print(f"{v} {period} {status} -> {VARIANT_CONFIG[v]['csv']}")

    # ── Top brands / models (Whole; never blocks the data, see market_top) ─

    if "Whole" in variants and not market_top.top_is_current(TOP_PATH, prev):
        market_top.guarded(refresh_market_top)

    # ── Vans (LCV): separate LCV struttura PDF ───────────────────────────
    #
    # Runs after PKW, so a Vans failure must not take the PKW rows down with
    # it: the workflow commits only when this script succeeds, which would
    # silently drop a freshly fetched PKW month.  Report the failure via
    # $GITHUB_OUTPUT (vans_failed=true), let the workflow commit PKW anyway,
    # and still exit non-zero so the run shows red.

    if lcv_variants:
        try:
            fetch_vans(args, prev)
        except Exception as e:
            print(f"ERROR Vans: {e}", file=sys.stderr)
            gh_out = os.environ.get("GITHUB_OUTPUT")
            if gh_out:
                with open(gh_out, "a", encoding="utf-8") as f:
                    f.write("vans_failed=true\n")
            raise


if __name__ == "__main__":
    main()
