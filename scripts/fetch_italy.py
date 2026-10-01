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
        pages = find_lcv_pages(http_get(STRUTTURA_INDEX))
        if not pages:
            raise RuntimeError("No 'immatricolazioni-veicoli-commerciali' link on UNRAE index page.")
        print(f"Latest LCV struttura: {pages[0]}")
        pdf_url = find_lcv_pdf_url(http_get(pages[0]))
        if pdf_url is None:
            # Happened for 2025-11/12 and 2026-05: a source gap, not a parse
            # failure.  The next year's comparison column fills the month.
            print(f"::warning::No PDF attached to {pages[0]}; Vans month skipped.")
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
