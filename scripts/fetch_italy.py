#!/usr/bin/env python3
"""
Fetch Italy new registration data from UNRAE and upsert CSV files.

Variants
--------
  Whole   data/Italy.csv        — PKW whole market (inkl. Noleggio)
  Rental  data/Italy_Rental.csv — PKW rental fleet = Whole − (al netto del noleggio)
  Vans    data/Italy_Vans.csv   — LCV (veicoli commerciali leggeri)

Whole + Rental come from the same PKW "Struttura del mercato" PDF, published on
unrae.it/dati-statistici/immatricolazioni around the 1st of each month.
The PDF contains two 'Per alimentazione' tables: the first (whole market) and the
second (al netto del noleggio = fleet excluded). Rental = Whole − second block.

NOTE on Private/Industry: Italy's PDF does NOT expose a Private/Industry split
comparable to Denmark/Finland.  The only available sub-market split is
Whole vs. al netto del noleggio (rental excluded).  'Rental' here is the
complement: noleggio a lungo + noleggio a breve + autoimm. uso noleggio.
A per-fuel breakdown by juridical person is not available from this source.

Vans comes from the LCV "Comunicato Stampa" press release PDF, published on
unrae.it/sala-stampa/veicoli-commerciali around the 14th of each month.
⚠  Absolute counts are DERIVED from rounded market-share percentages × total
(e.g. BEV = round(2.9% × 15 205)).  Typical deviation: ±1–5 per fuel type.
The sanity check uses lenient tolerance (max 200, 2%) for Vans rows.

Parsing gotcha — Unicode apostrophe in LCV PDFs:
  The LCV Comunicato Stampa uses the RIGHT SINGLE QUOTATION MARK (U+2019 ')
  in "all'X%" constructions, not the ASCII apostrophe (U+0027 ').  The _LCV_PCT
  patterns match both forms: all['’].  If new months fail to parse GPL,
  check for a different apostrophe variant in the PDF text first.

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

Vans fuel mapping (from Comunicato Stampa prose — percentages × total)
-----------------------------------------------------------------------
    DIESEL = diesel %
    PETROL = benzina %
    HEV    = veicoli ibridi % del totale
    PHEV   = veicoli plug-in %
    BEV    = veicoli BEV %
    OTHERS = Gpl % only (Metano/Idrogeno not reported; negligible for LCV)
    TOTAL  = total registrations stated in text (absolute, not derived)

See docs/architecture/18-source-italy.md for the full pipeline context.

Usage
-----
    python scripts/fetch_italy.py [--variant all|pkw|Whole|Rental|Vans]
                                  [--pdf-url URL --year Y --month M]
                                  [--vans-pdf-url URL --year Y --month M]
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
LCV_INDEX       = "https://unrae.it/sala-stampa/veicoli-commerciali"
SOURCE          = "unrae.it"
USER_AGENT      = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) BEV-Gallery-Bot"

VARIANT_CONFIG: dict[str, dict] = {
    "Whole":  {"csv": "data/Italy.csv",        "pkw": True},
    "Rental": {"csv": "data/Italy_Rental.csv", "pkw": True},
    "Vans":   {"csv": "data/Italy_Vans.csv",   "pkw": False},
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


def parse_pkw(text: str) -> tuple[dict, dict]:
    """Parse the PKW Struttura del mercato PDF and return (whole_cols, rental_cols).

      whole_cols  = first 'Per alimentazione' block (whole market, inkl. Noleggio)
      rental_cols = Whole − (al netto del noleggio) = rental fleet only
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

    whole_cols       = _parse_alimentazione_block(lines, alim_starts[0], block_end(alim_starts[0]))
    netto_nol_cols   = _parse_alimentazione_block(lines, alim_starts[1], block_end(alim_starts[1]))
    rental_cols      = {k: whole_cols[k] - netto_nol_cols[k] for k in whole_cols}
    return whole_cols, rental_cols


# ── LCV discovery ─────────────────────────────────────────────────────────

def find_latest_lcv(index_html: str) -> tuple[str, int, int]:
    """Find the newest 'veicoli commerciali leggeri' press release.

    Returns (detail_url, year, month).  Month is extracted from the URL slug
    (Italian month name embedded in the slug).  Year is inferred: if slug-month
    > today.month, the bulletin belongs to the previous calendar year.
    """
    pat = re.compile(
        r'href="(https://unrae\.it/sala-stampa/veicoli-commerciali/\d+/'
        r'veicoli-commerciali-leggeri-[^"]+)"',
        re.IGNORECASE,
    )
    today = date.today()
    best: tuple[int, int, str] | None = None

    for url in pat.findall(index_html):
        slug = url.split("/")[-1]
        month = None
        for word in slug.replace("-", " ").split():
            if word.lower() in IT_MONTHS:
                month = IT_MONTHS[word.lower()]
                break
        if month is None:
            continue
        year = today.year if month <= today.month else today.year - 1
        key = (year, month)
        if best is None or key > (best[0], best[1]):
            best = (key[0], key[1], url)

    if best is None:
        raise RuntimeError(
            "No 'veicoli commerciali leggeri' link found on UNRAE sala-stampa page."
        )
    return best[2], best[0], best[1]


def find_lcv_pdf_url(detail_html: str) -> str:
    """Find the first PDF link on the LCV detail page."""
    pat = re.compile(r'href="(https://unrae\.it/files/[^"]+\.pdf)"', re.IGNORECASE)
    m = pat.search(detail_html)
    if not m:
        raise RuntimeError("No PDF link found on LCV detail page.")
    return m.group(1)


# ── LCV parsing ────────────────────────────────────────────────────────────
#
# The LCV Comunicato Stampa is narrative prose — there is no structured data
# table.  We extract the current-month market share percentage for each fuel
# type from the "motorizzazioni" paragraph via sentence-scoped regex patterns
# (stopping at '.'), then multiply by the total registration count.
#
# These patterns are inherently fragile: if UNRAE's PR agency changes the
# phrasing, they may need updating.  The sanity check (lenient tolerance)
# guards against silent misparses.

_LCV_PCT: dict[str, re.Pattern] = {
    # "al" = preposition (word-boundary safe); "all'" may use ASCII ' or Unicode '
    # (U+2019 RIGHT SINGLE QUOTATION MARK) depending on the PDF.  We match both.
    "DIESEL": re.compile(
        r"\bdiesel\b[^.]*?(?:\bal\b|all['’])\s*(\d+[,]\d+)\s*%",
        re.IGNORECASE | re.DOTALL,
    ),
    "PETROL": re.compile(
        r"\bbenzina\b[^.]*?(?:\bal\b|all['’])\s*(\d+[,]\d+)\s*%",
        re.IGNORECASE | re.DOTALL,
    ),
    # GPL uses "all'X%" with a Unicode apostrophe; fall back to first % in sentence.
    "GPL": re.compile(
        r"\bgpl\b[^.]*?(\d+[,]\d+)\s*%",
        re.IGNORECASE | re.DOTALL,
    ),
    "PHEV": re.compile(
        r"\bplug.in\b[^.]*?(?:\bal\b|all['’])\s*(\d+[,]\d+)\s*%",
        re.IGNORECASE | re.DOTALL,
    ),
    "BEV": re.compile(
        r"\bbev\b[^.]*?(?:\bal\b|all['’])\s*(\d+[,]\d+)\s*%",
        re.IGNORECASE | re.DOTALL,
    ),
    "HEV": re.compile(
        r"\bibridi?\b[^.]*?(\d+[,]\d+)\s*%\s*del\s+totale",
        re.IGNORECASE | re.DOTALL,
    ),
}

# Primary: "posizionano a 15.205 unità"
_LCV_TOTAL_PRIMARY  = re.compile(r"posizionano\s+a\s+([\d\.]+)\s+unit", re.IGNORECASE)
# Fallback: first 5-digit number (tens of thousands) followed by "unità"
_LCV_TOTAL_FALLBACK = re.compile(r"(\d{2,3}(?:\.\d{3})+)\s+unit",      re.IGNORECASE)


def parse_vans(text: str) -> dict:
    """Parse LCV fuel-type data from Comunicato Stampa prose text.

    Returns absolute counts derived from market-share percentages × total.
    ⚠ Accuracy: ±~5 per fuel category due to percentage rounding.
    OTHERS = derived GPL count; any unclassified fuels (Metano, Idrogeno…)
    are not separately mentioned in the Comunicato Stampa.
    """
    m = _LCV_TOTAL_PRIMARY.search(text)
    if m:
        total = int(m.group(1).replace(".", ""))
    else:
        m2 = _LCV_TOTAL_FALLBACK.search(text)
        if not m2:
            raise RuntimeError("Could not find LCV total registrations in PDF text.")
        total = int(m2.group(1).replace(".", ""))
    if not 5_000 <= total <= 100_000:
        raise RuntimeError(
            f"LCV total {total} outside expected range 5 000–100 000; check PDF."
        )

    pcts: dict[str, float] = {}
    for fuel, pat in _LCV_PCT.items():
        hit = pat.search(text)
        if hit:
            pcts[fuel] = float(hit.group(1).replace(",", "."))
        else:
            print(f"  WARNING Vans: {fuel} percentage not found — defaulting to 0.")
            pcts[fuel] = 0.0

    def pct_to_int(key: str) -> int:
        return round(pcts[key] / 100 * total)

    return {
        "BEV":    pct_to_int("BEV"),
        "PHEV":   pct_to_int("PHEV"),
        "HEV":    pct_to_int("HEV"),
        "PETROL": pct_to_int("PETROL"),
        "DIESEL": pct_to_int("DIESEL"),
        "OTHERS": pct_to_int("GPL"),
        "TOTAL":  total,
    }


# ── sanity + upsert ────────────────────────────────────────────────────────

def sanity_check(cols: dict, period: str, strict: bool = True) -> None:
    """Verify BEV+PHEV+HEV+PETROL+DIESEL+OTHERS ≈ TOTAL."""
    core  = (cols["BEV"] + cols["PHEV"] + cols["HEV"]
             + cols["PETROL"] + cols["DIESEL"] + cols["OTHERS"])
    total = cols["TOTAL"]
    if total <= 0:
        raise RuntimeError(f"{period}: TOTAL is {total}; refusing to write.")
    # Strict (table-parsed): max(50, 0.5%).  Lenient (pct-derived): max(200, 2%).
    tol = max(50, total * 0.005) if strict else max(200, total * 0.02)
    if abs(core - total) > tol:
        raise RuntimeError(
            f"{period}: sum={core} vs TOTAL={total} (diff={core - total}); "
            f"tolerance={tol:.0f}; refusing to write."
        )


def upsert(csv_path: str, period: str, cols: dict, variant: str) -> tuple[str, dict | None]:
    """Write/replace the row for (period, variant) in csv_path.
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
        "OTHERS": cols["OTHERS"], "TOTAL": cols["TOTAL"], "notes": "",
    }

    # Preserve existing notes when the script writes empty notes.
    if not new_row["notes"] and old is not None:
        new_row["notes"] = old.get("notes", "")

    status = "added" if old is None else "updated"
    if old is not None:
        for c in ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL"]:
            ov = float(old.get(c) or 0)
            nv = float(new_row[c])
            if ov > 100 and abs(nv - ov) / ov > 0.1:
                print(f"  WARNING {c}: existing={ov:.0f}, new={nv:.0f} — drift >10%")
        if all(float(old.get(c) or 0) == float(new_row[c])
               for c in ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL"]):
            status = "unchanged"

    rows.append(new_row)
    rows.sort(key=lambda r: (r["variant"], r["period"]))

    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return status, old


# ── main ───────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--variant", default="all",
        help="Variants to fetch: all | pkw | Whole | Private | Vans  (default: all). "
             "'pkw' is an alias for Whole+Private.",
    )
    ap.add_argument("--force", action="store_true",
                    help="Re-process even if the target period already exists.")
    ap.add_argument("--pdf-url", default="",
                    help="Direct PKW Struttura PDF URL (skips index/detail scraping).")
    ap.add_argument("--vans-pdf-url", default="",
                    help="Direct LCV Comunicato Stampa PDF URL (skips sala-stampa scraping).")
    ap.add_argument("--year",  type=int, help="Target year  (required with --pdf-url / --vans-pdf-url).")
    ap.add_argument("--month", type=int, help="Target month (required with --pdf-url / --vans-pdf-url).")
    args = ap.parse_args()

    alias_map = {"all": ["Whole", "Rental", "Vans"], "pkw": ["Whole", "Rental"]}
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

                whole_cols, rental_cols = parse_pkw(text)

                for v, cols in [("Whole", whole_cols), ("Rental", rental_cols)]:
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

    # ── Vans (LCV): separate Comunicato Stampa PDF ───────────────────────

    if lcv_variants:
        need_lcv = args.force or not csv_has_period(
            VARIANT_CONFIG["Vans"]["csv"], prev, "Vans"
        )
        if not need_lcv:
            print(f"Vans already has {prev}; nothing to do.")
        else:
            if args.vans_pdf_url:
                if not (args.year and args.month):
                    sys.exit("--vans-pdf-url requires --year and --month.")
                lcv_pdf_url = args.vans_pdf_url
                year, month = args.year, args.month
                print(f"Using supplied LCV PDF: {lcv_pdf_url} -> {year}-{month:02d}")
            else:
                print(f"Fetching LCV index: {LCV_INDEX}")
                lcv_html    = http_get(LCV_INDEX)
                detail_url, year, month = find_latest_lcv(lcv_html)
                print(f"Latest LCV bulletin: {year}-{month:02d}  ({detail_url})")
                detail_html = http_get(detail_url)
                lcv_pdf_url = find_lcv_pdf_url(detail_html)
                print(f"LCV PDF: {lcv_pdf_url}")

            period = f"{year}-{month:02d}"
            if not args.force and csv_has_period(
                VARIANT_CONFIG["Vans"]["csv"], period, "Vans"
            ):
                print(f"Vans {period} already in CSV; nothing to do.")
            else:
                with tempfile.TemporaryDirectory() as td:
                    pdf_path = Path(td) / "lcv.pdf"
                    download_pdf(lcv_pdf_url, pdf_path)
                    text = pdf_to_text(pdf_path)

                cols = parse_vans(text)
                print(f"Parsed Vans {period}: BEV={cols['BEV']} PHEV={cols['PHEV']} "
                      f"HEV={cols['HEV']} PETROL={cols['PETROL']} DIESEL={cols['DIESEL']} "
                      f"OTHERS={cols['OTHERS']} TOTAL={cols['TOTAL']} (derived from %)")
                sanity_check(cols, period, strict=False)
                status, _ = upsert(VARIANT_CONFIG["Vans"]["csv"], period, cols, "Vans")
                print(f"Vans {period} {status} -> {VARIANT_CONFIG['Vans']['csv']}")


if __name__ == "__main__":
    main()
