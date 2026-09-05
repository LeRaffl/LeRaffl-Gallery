#!/usr/bin/env python3
"""
Fetch Chile vehicle registration data from ANAC and update data/Chile.csv.

Usage
-----
    python scripts/fetch_chile.py [--year YEAR] [--month MONTH] \
        [--mercado-url URL] [--emisiones-url URL] [--csv PATH] [--force]

* --year / --month  Override the target month (default: previous calendar month).
* --mercado-url     Direct URL/path to the Mercado Automotor PDF.
* --emisiones-url   Direct URL/path to the Cero y Bajas Emisiones PDF.
* --csv             Target CSV (default: data/Chile.csv).
* --force           Re-process even if the target period already exists.

Invoked by .github/workflows/fetch-chile.yml on a daily cron from the 14th of
each month onward, plus manual workflow_dispatch. When the CSV changes, the
workflow commits data/Chile.csv and triggers render-country.yml for Chile.

Data source
-----------
ANAC (Asociación Nacional Automotriz de Chile) publishes two monthly PDFs at
https://www.anac.cl/category/estudio-de-mercado/ :

  1. "Informe Mercado Automotor"            → provides TOTAL (livianos y medianos)
  2. "Informe Cero y Bajas Emisiones"       → provides BEV, PHEV, HEV

Both PDFs for a given month are usually published a few weeks into the
following month, but NOT necessarily at the same time. We only write a CSV
row when both are available for the target month (no partial writes).

Vehicle scope
-------------
"Livianos y medianos" = passenger cars + SUVs + pickups + light commercial
vehicles up to 3.860 kg GVWR (livianos < 2.700 kg, medianos 2.700–3.859 kg)
per DS N°241/2014 del MTT. Trucks (camiones) and buses appear in the same
PDFs in separate sections; we explicitly do NOT ingest them. See
docs/architecture/09-glossary.md § Vehicle scope per source.

Parsing strategy
----------------
* Mercado Automotor: locate the first standalone "Total Mes" label in the
  text; the headline integer on the line immediately above is the monthly
  total for livianos y medianos. ANAC's narrative phrasing varies between
  reports, so the bar-chart label is more stable.

* Cero y Bajas Emisiones: the report contains a summary table

      Tipo Vehículo              Acum <Month> YEAR    Var% Acum    <Month>    Var% Mes
      Eléctricos                 1.802                61,3 %       1.008      168,8%
      Híbrido Enchufables        1.610                318,2 %      766        410,7%
      Híbrido Convencional       3.665                97,1 %       1.812      164,5%
      Microhíbridos              4.833                74,1 %       2.307      97,9%

  For each labelled row we extract the 3rd column (monthly value):
      Eléctricos          → BEV
      Híbrido Enchufables → PHEV
      Híbrido Convencional → HEV
  Microhíbridos (MHEV) is NOT broken out — it falls into the ICE bucket via
  the implicit subtraction TOTAL − BEV − PHEV − HEV − OTHERS.

CSV layout
----------
Existing data/Chile.csv columns:
    period,time_interval,variant,source,BEV,PHEV,HEV,PETROL,DIESEL,OTHERS,ICE,TOTAL,notes

For new rows we set:
    BEV, PHEV, HEV  ← from emisiones PDF
    PETROL, DIESEL, OTHERS  ← 0
    TOTAL  ← from mercado PDF
    ICE    ← TOTAL − BEV − PHEV − HEV − OTHERS (captures gasoline+diesel+MHEV)
    notes  ← "<mercado_url> | <emisiones_url>"

Per the user's rule we only ever write the most recent month; older rows are
never touched, even if a later report would adjust them.

HTTP details
------------
ANAC's WordPress hardens against basic User-Agents — we identify as a regular
desktop browser via HTTP_HEADERS to avoid 403s.
"""
import argparse
import csv
import io
import re
import sys
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

ANAC_PAGE = "https://www.anac.cl/category/estudio-de-mercado/"

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
}

CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS",
    "ICE", "TOTAL", "notes",
]

SPANISH_MONTHS = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}

# Labels in the emisiones summary table → CSV column.
# ANAC periodically renames rows; list all known variants so the parser
# survives minor label changes.  The first match per csv_key wins.
EMISIONES_LABELS = {
    # Original labels (pre-2026)
    "Eléctricos": "BEV",
    "Híbrido Enchufables": "PHEV",
    "Híbrido Convencional": "HEV",
    # Variants seen / anticipated from May-2026 report narrative
    "100% Eléctricos": "BEV",
    "Eléctrico Puro": "BEV",
    "Eléctrico": "BEV",
    "Híbridos Enchufables": "PHEV",
    "Híbrido Enchufable": "PHEV",
    "Híbridos Convencionales": "HEV",
    "Híbrido Convencionales": "HEV",
}

# Row pattern after stripping the label: <int> <pct>% <int> <pct>%
# Captures (acumulado, monthly). Integers may carry "1.234" thousand separators;
# percentages use comma decimals ("61,3 %") and we tolerate "0 %" with no decimal.
_EMISIONES_ROW = re.compile(
    r"^(\d{1,3}(?:\.\d{3})*)\s+"
    r"-?\d+(?:[,.]\d+)?\s*%\s+"
    r"(\d{1,3}(?:\.\d{3})*)\s+"
    r"-?\d+(?:[,.]\d+)?\s*%"
)


# --- New Power-BI table format (seen from Julio-2026) -----------------------
# ANAC rebuilt the report around Power BI exports. The old single summary table
# is gone; the monthly numbers now live in per-technology "Tipo Tecnología" /
# "Segmentos" tables whose rows carry a parenthetical technology code followed
# by:  <acumulado> <var%acum>%  <mes> <var%mes>% . We key on the code — those
# codes (BEV / PHEV / P-REEV) are far more stable than ANAC's ever-changing row
# labels and narrative verbs — and requiring a digit right after the code skips
# prose mentions such as "vehículos 100% eléctricos (BEV) sumaron 6.206 unidades".
#
#   Eléctricos (BEV) 6.206 105,4 % 781 61,0%
#   Híbrido Enchufable (PHEV) 4.429 219,6 % 618 220,2%
#   Eléct. de Rango Ext. Enchufable (P-REEV) 778 2.582,8 % 36
#
# The 3rd column (<mes>) is the monthly value. P-REEV is folded into PHEV to
# match the historical "Híbrido Enchufables" definition (781+618+36 = 1.435,
# the report's enchufables monthly total).
_TECH_CODE_RE = re.compile(
    r"\((BEV|PHEV|P-?REEV)\)\s+"          # technology code
    r"\d{1,3}(?:\.\d{3})*\s+"             # acumulado (ignored)
    r"-?[\d.]+(?:,\d+)?\s*%\s+"           # var% acumulado
    r"(\d{1,3}(?:\.\d{3})*)"              # <mes> monthly value (captured)
)

# Grand-total of a Power-BI ranking table, e.g. the trailing column of
# "Total 18 100,0% 1.004 100,0% 41 100,0% 1.063 100,0%" → 1.063. Anchored at
# end of line so the last (grand-total) column wins; tolerant of the glued
# "1.063100,0%" spacing pypdf sometimes emits.
_GRAND_TOTAL_RE = re.compile(r"(\d{1,3}(?:\.\d{3})*)\s*100,0?\s*%\s*$")


def _parse_tech_table(text: str) -> dict[str, int]:
    """Extract monthly BEV / PHEV (incl. P-REEV) from the new per-technology
    tables. Returns whatever it can find (may be empty)."""
    found: dict[str, int] = {}
    for m in _TECH_CODE_RE.finditer(text):
        code = m.group(1).replace("-", "").upper()   # BEV / PHEV / PREEV
        found.setdefault(code, int(m.group(2).replace(".", "")))
    out: dict[str, int] = {}
    if "BEV" in found:
        out["BEV"] = found["BEV"]
    if "PHEV" in found:
        out["PHEV"] = found["PHEV"] + found.get("PREEV", 0)
    return out


def _parse_convencional_monthly(text: str) -> int | None:
    """Extract the monthly HEV (+REEV) total from the Power-BI report.

    The new format has no summary row for convencionales; the only clean
    monthly figure is the grand total of the *monthly* per-brand ranking
    "RANKING DE VENTAS POR MARCA - HÍBRIDOS CONVENCIONALES - <Month> <Year>"
    (as opposed to its "... - ACUMULADO A <Month>" twin). We arm on that
    header and read the next "Total …" grand-total row.
    """
    armed = False
    for line in text.split("\n"):
        s = line.strip()
        u = s.upper()
        if "POR MARCA" in u and "HÍBRIDOS CONVENCIONALES" in u:
            armed = "ACUMULADO" not in u
            continue
        if armed and s.startswith("Total"):
            m = _GRAND_TOTAL_RE.search(s)
            return int(m.group(1).replace(".", "")) if m else None
    return None


def previous_month(today: date) -> tuple[int, int]:
    """Returns (year, month) of the calendar month before `today`."""
    if today.month == 1:
        return today.year - 1, 12
    return today.year, today.month - 1


def latest_period(csv_path: str) -> str | None:
    if not Path(csv_path).exists():
        return None
    with open(csv_path, newline="", encoding="utf-8") as f:
        periods = [row["period"] for row in csv.DictReader(f)]
    return max(periods) if periods else None


def discover_pdfs(year: int, month: int) -> tuple[str | None, str | None]:
    """Returns (mercado_url, emisiones_url) for the given year/month, or None each."""
    month_name = SPANISH_MONTHS[month]
    print(f"Scanning {ANAC_PAGE} for {month_name} {year} PDFs …")
    resp = requests.get(ANAC_PAGE, headers=HTTP_HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Filenames seen in the wild:
    #   04-ANAC-Mercado-Automotor-Abril-2026.pdf            (canonical)
    #   04-ANAC-Mercado-Automotor-Abril-202634.pdf          (with version suffix)
    #   03-ANAC-Informe-Cero-y-Bajas-Emisiones-Marzo-2026.pdf
    #   02-ANAC-Informe-Cero-y-Bajas-Emisiones-Febrero-202677.pdf
    # The leading "NN-" is the month number; trailing "<digits>" after the
    # year is a versioning quirk.
    mercado_re = re.compile(
        rf"ANAC-Mercado-Automotor-{month_name}-{year}\d*\.pdf",
        re.IGNORECASE,
    )
    emisiones_re = re.compile(
        rf"ANAC-Informe-Cero-y-Bajas-Emisiones-{month_name}-{year}\d*\.pdf",
        re.IGNORECASE,
    )

    mercado_url = emisiones_url = None
    for a in soup.find_all("a", href=True):
        # ANAC occasionally renders hrefs with leading whitespace/newlines
        # (seen in the wild: "\nhttps://www.anac.cl/wp-content/..."). Without
        # this strip(), startswith("http") returns False and we'd prepend
        # the host, producing "https://www.anac.cl\nhttps://..." → requests
        # then raises ConnectionError on host 'www.anac.cl%0ahttps'.
        href = a["href"].strip()
        if mercado_url is None and mercado_re.search(href):
            mercado_url = href if href.startswith("http") else "https://www.anac.cl" + href
        if emisiones_url is None and emisiones_re.search(href):
            emisiones_url = href if href.startswith("http") else "https://www.anac.cl" + href

    return mercado_url, emisiones_url


def load_pdf_bytes(url_or_path: str) -> bytes:
    if url_or_path.startswith("http://") or url_or_path.startswith("https://"):
        print(f"Downloading: {url_or_path}")
        resp = requests.get(url_or_path, headers=HTTP_HEADERS, timeout=60)
        resp.raise_for_status()
        return resp.content
    path = url_or_path.replace("file://", "")
    with open(path, "rb") as f:
        return f.read()


def pdf_text(pdf_bytes: bytes) -> str:
    """Concatenate text of every PDF page in order.

    pypdf's reading-order extraction collapses multi-column chart layouts —
    the bar-chart headline numbers come out glued to their labels
    (e.g. "27.572Total Mes"), which the parsers below match explicitly.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


# Headline bar-chart value: "27.572Total Mes" or "27.572 Total Mes".
# ANAC reports always present livianos y medianos before camiones and buses,
# so the FIRST occurrence in reading order is the figure we want.
_TOTAL_MES_RE = re.compile(r"(\d{1,3}(?:\.\d{3})+)\s*Total\s*Mes")


def parse_mercado_total(text: str) -> int:
    """Extract monthly TOTAL (livianos y medianos) from Mercado Automotor PDF."""
    m = _TOTAL_MES_RE.search(text)
    if not m:
        raise RuntimeError(
            "Could not locate 'Total Mes' headline in Mercado Automotor PDF"
        )
    return int(m.group(1).replace(".", ""))


# Fallback: YTD-cumulative figures from the narrative intro of the new PDF format.
# ANAC removed the summary table in mid-2026; the numbers now appear only in prose.
# PHEV_raw + EREV_raw are summed into the single "PHEV" CSV column because earlier
# data combined both categories under "Híbrido Enchufables".
_NARRATIVE_RE: dict[str, re.Pattern] = {
    "BEV":      re.compile(r"con ([\d.]+) unidades vendidas a \w+", re.IGNORECASE),
    "PHEV_raw": re.compile(r"h[íi]bridos? enchufables? sumaron ([\d.]+) unidades", re.IGNORECASE),
    "EREV_raw": re.compile(r"el[eé]ctricos? de rango extendido enchufables? contabilizaron ([\d.]+) unidades", re.IGNORECASE),
    "HEV":      re.compile(r"h[íi]bridos? convencionales? acumularon ([\d.]+) unidades", re.IGNORECASE),
}


def _ytd_from_csv(csv_path: str, year: str, before_period: str) -> dict[str, int]:
    """Sum BEV/PHEV/HEV for months in `year` that come before `before_period`."""
    totals: dict[str, int] = {"BEV": 0, "PHEV": 0, "HEV": 0}
    if not Path(csv_path).exists():
        return totals
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            p = row.get("period", "")
            if p.startswith(year) and p < before_period:
                for col in ("BEV", "PHEV", "HEV"):
                    try:
                        totals[col] += int(float(row.get(col) or 0))
                    except (ValueError, TypeError):
                        pass
    return totals


def parse_emisiones(text: str, period: str = "", csv_path: str = "") -> dict[str, int]:
    """Extract BEV/PHEV/HEV monthly counts from Cero y Bajas Emisiones PDF.

    Strategies are tried in order and their results merged, because ANAC keeps
    reshaping the report:

      1. Legacy summary table (pre-2026): rows beginning with an EMISIONES_LABELS
         label, monthly value = 2nd integer of the <int> <pct>% <int> <pct>% tail.
      2. New Power-BI tables (Julio-2026 onward): monthly BEV / PHEV(+P-REEV) from
         the code-keyed "Tipo Tecnología" rows, and monthly HEV from the grand
         total of the monthly "POR MARCA - HÍBRIDOS CONVENCIONALES" ranking.
      3. Narrative fallback: YTD-cumulative figures from the intro prose minus the
         previous months' totals read from the CSV file.

    These are monthly-direct where possible (strategies 1–2) so a missing prior
    month in the CSV does not corrupt the result the way the YTD subtraction can.
    """
    result: dict[str, int] = {}

    # --- Strategy 1: legacy summary table ---
    for line in text.split("\n"):
        stripped = line.strip()
        for label, csv_key in EMISIONES_LABELS.items():
            if csv_key in result:
                continue
            if stripped.startswith(label):
                rest = stripped[len(label):].strip()
                m = _EMISIONES_ROW.match(rest)
                if m:
                    result[csv_key] = int(m.group(2).replace(".", ""))
                    break

    # --- Strategy 2: new Power-BI tables ---
    if {"BEV", "PHEV"} - result.keys():
        for k, v in _parse_tech_table(text).items():
            result.setdefault(k, v)
    if "HEV" not in result:
        hev = _parse_convencional_monthly(text)
        if hev is not None:
            result["HEV"] = hev

    missing = set(EMISIONES_LABELS.values()) - set(result.keys())
    if not missing:
        return result

    # --- Narrative fallback ---
    if period and csv_path:
        # pypdf sprinkles line breaks and double spaces mid-sentence (e.g.
        # "híbridos \nconvencionales acumularon", "sumaron 2.955 \nunidades"),
        # which broke the single-space narrative patterns. Collapse every run of
        # whitespace to one space before matching the prose.
        norm = re.sub(r"\s+", " ", text)
        cum: dict[str, int] = {}
        for key, pat in _NARRATIVE_RE.items():
            m = pat.search(norm)
            if m:
                cum[key] = int(m.group(1).replace(".", ""))
        # PHEV+EREV → single "PHEV" column for CSV backwards-compat
        if "PHEV_raw" in cum:
            cum["PHEV"] = cum.pop("PHEV_raw") + cum.pop("EREV_raw", 0)
        if {"BEV", "PHEV", "HEV"} <= cum.keys():
            year = period[:4]
            prev = _ytd_from_csv(csv_path, year, period)
            monthly = {k: max(0, cum[k] - prev[k]) for k in ("BEV", "PHEV", "HEV")}
            print(f"  (narrative fallback) YTD cumulative from PDF: {cum}")
            print(f"  (narrative fallback) YTD cumulative Jan–prev from CSV: {prev}")
            print(f"  (narrative fallback) Monthly = {monthly}")
            return monthly

    # --- Give up: dump the full text for diagnosis ---
    # Print the whole extraction (not sampled windows) so the next format change
    # can be diagnosed straight from the workflow log without re-fetching the PDF.
    char_count = len(text)
    body = text if char_count else "(empty — PDF may be image-based)"
    print(
        f"\n=== Emisiones PDF text dump ({char_count} chars) ===\n"
        f"{body}\n"
        f"=== end dump ===\n"
    )
    raise RuntimeError(
        f"Could not extract {sorted(missing)} from Cero y Bajas Emisiones PDF. "
        f"See text dump above to diagnose format change."
    )


def upsert_row(csv_path: str, period: str, row: dict, force: bool) -> bool:
    """Append `row` for `period` to the CSV (sorted). Returns True if written.

    Returns False without writing if the period already exists and not --force.
    """
    existing: dict[str, dict] = {}
    if Path(csv_path).exists():
        with open(csv_path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                existing[r["period"]] = r

    if period in existing and not force:
        print(f"  Period {period} already in CSV — not overwriting (use --force).")
        return False

    existing[period] = row
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for p in sorted(existing.keys()):
            writer.writerow(existing[p])
    return True


def build_row(period: str, total: int, fuels: dict[str, int],
              mercado_url: str, emisiones_url: str) -> dict:
    bev = float(fuels["BEV"])
    phev = float(fuels["PHEV"])
    hev = float(fuels["HEV"])
    ice = float(total) - bev - phev - hev
    return {
        "period": period,
        "time_interval": "monthly",
        "variant": "Whole",
        "source": "ANAC",
        "BEV": bev,
        "PHEV": phev,
        "HEV": hev,
        "PETROL": 0.0,
        "DIESEL": 0.0,
        "OTHERS": 0.0,
        "ICE": ice,
        "TOTAL": float(total),
        "notes": f"{mercado_url} | {emisiones_url}",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int)
    parser.add_argument("--month", type=int, choices=range(1, 13))
    parser.add_argument("--mercado-url", help="Direct URL/path to Mercado Automotor PDF")
    parser.add_argument("--emisiones-url", help="Direct URL/path to Cero y Bajas Emisiones PDF")
    parser.add_argument("--csv", default="data/Chile.csv")
    parser.add_argument("--force", action="store_true",
                        help="Re-process even if target period already exists")
    args = parser.parse_args()

    # Determine target month (defaults to the calendar month before today)
    if args.year and args.month:
        target_year, target_month = args.year, args.month
    elif args.year or args.month:
        sys.exit("--year and --month must be given together")
    else:
        target_year, target_month = previous_month(date.today())
    target_period = f"{target_year}-{target_month:02d}"
    print(f"Target period: {target_period} ({SPANISH_MONTHS[target_month]} {target_year})")

    # Short-circuit: if already in CSV and not forced, no-op.
    if not args.force:
        latest = latest_period(args.csv)
        if latest and latest >= target_period:
            print(f"Latest period in CSV is {latest} ≥ {target_period} — nothing to do.")
            return 0

    # Resolve PDF URLs
    if args.mercado_url and args.emisiones_url:
        mercado_url = args.mercado_url
        emisiones_url = args.emisiones_url
    elif args.mercado_url or args.emisiones_url:
        sys.exit("--mercado-url and --emisiones-url must be given together "
                 "(or both omitted to auto-discover)")
    else:
        mercado_url, emisiones_url = discover_pdfs(target_year, target_month)
        if not mercado_url or not emisiones_url:
            missing = []
            if not mercado_url: missing.append("Mercado Automotor")
            if not emisiones_url: missing.append("Cero y Bajas Emisiones")
            print(f"PDFs not yet published for {target_period}: missing {missing}. "
                  "Will retry on next scheduled run.")
            return 0
        print(f"Found Mercado:    {mercado_url}")
        print(f"Found Emisiones:  {emisiones_url}")

    # Parse
    mercado_text = pdf_text(load_pdf_bytes(mercado_url))
    total = parse_mercado_total(mercado_text)
    print(f"Parsed TOTAL: {total}")

    emisiones_text = pdf_text(load_pdf_bytes(emisiones_url))
    fuels = parse_emisiones(emisiones_text, period=target_period, csv_path=args.csv)
    print(f"Parsed fuels: BEV={fuels['BEV']}, PHEV={fuels['PHEV']}, HEV={fuels['HEV']}")

    # Sanity: ICE must be non-negative
    ice = total - fuels["BEV"] - fuels["PHEV"] - fuels["HEV"]
    if ice < 0:
        sys.exit(f"Computed ICE is negative ({ice}); parser likely picked wrong values. "
                 f"TOTAL={total}, fuels={fuels}")
    print(f"Computed ICE:  {ice}")

    row = build_row(target_period, total, fuels, mercado_url, emisiones_url)
    if upsert_row(args.csv, target_period, row, args.force):
        print(f"\nWrote {target_period} to {args.csv}")
    else:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
