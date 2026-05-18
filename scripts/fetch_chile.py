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

# Labels in the emisiones summary table → CSV column
EMISIONES_LABELS = {
    "Eléctricos": "BEV",
    "Híbrido Enchufables": "PHEV",
    "Híbrido Convencional": "HEV",
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
        href = a["href"]
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


def parse_emisiones(text: str) -> dict[str, int]:
    """Extract BEV/PHEV/HEV monthly counts from Cero y Bajas Emisiones PDF.

    Looks for lines that begin (after whitespace strip) with one of the
    fuel-type labels, then extracts the 2nd integer (= monthly column)
    from the trailing `<int> <pct>% <int> <pct>%` pattern.
    """
    result: dict[str, int] = {}
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

    missing = set(EMISIONES_LABELS.values()) - set(result.keys())
    if missing:
        raise RuntimeError(
            f"Could not extract {sorted(missing)} from Cero y Bajas Emisiones PDF"
        )
    return result


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
    fuels = parse_emisiones(emisiones_text)
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
