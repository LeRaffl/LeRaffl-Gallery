#!/usr/bin/env python3
"""
Fetch Brazil vehicle registration data from ANFAVEA and update data/Brazil.csv.

Usage
-----
    python scripts/fetch_brazil.py [--year YEAR | --from YYYY-MM --to YYYY-MM] [--csv PATH]

* --year  Fetch Jan–Dec of that year (backfill / re-sync one year).
* --from / --to  Explicit month window (inclusive). Both default to the
          window described under "Default window" below.
* --csv   Target CSV (default: data/Brazil.csv).

This script is invoked by .github/workflows/fetch-brazil.yml on a monthly
cron (10th, 08:50 UTC) and via manual workflow_dispatch. When it produces
changes, the workflow commits data/Brazil.csv and triggers render-country.yml
for Brazil.

Data source
-----------
ANFAVEA (Associação Nacional dos Fabricantes de Veículos Automotores) used to
publish one Excel workbook per year (`siteautoveiculos<YEAR>.xlsx`) on
/site/edicoes-em-excel/. With the 2026-09 site relaunch that page redirects
to the interactive "Central de Dados" (https://anfavea.com.br/site/central-de-dados/)
and the workbooks are gone. The dashboard is a WordPress front end that POSTs
its query to admin-ajax.php and gets back a rendered HTML table:

    POST /site/wp-admin/admin-ajax.php
      action=anfavea_dashboard1, nonce=<from the page>, dashboard=dashboard1,
      tipo_dado=emplacamento, dimensao_emplacamento=combustivel,
      categorias[]=total_leves, combustivel_filter[]=todos,
      agregacao=mensal, inicio=YYYY-MM, fim=YYYY-MM
    → {"success": true, "data": {"table_html": "<table>…</table>", …}}

`nonce` is WordPress's anti-CSRF token; it is embedded in the page as
`var anfaveaData = {…,"nonce":"…"}` and we scrape it fresh on every run.
`total_leves` = Automóveis + Comerciais Leves, the same scope the old
workbook's sheet "III. Emplacamento Combustível" (first block) had. Trucks
and buses (`total_pesados`) are not ingested. The underlying registrations
are Renavam / Senatran; the fuel series in the database starts in 2017.

The table has one row per month ("2026 - AGO"), one column per fuel
("TOTAL LEVES - ELÉTRICO"), a TOTAL column and a closing TOTAL row. Every
number cell carries its raw integer in `data-valor-export`, so we never parse
the pt-BR display format ("27.251").

Column mapping (Portuguese → CSV column)
----------------------------------------
    ELÉTRICO          → BEV
    HÍBRIDO PLUG-IN   → PHEV
    HÍBRIDO           → HEV         (regular non-plug-in hybrids)
    GASOLINA          → PETROL
    DIESEL            → DIESEL
    FLEX FUEL         → FLEXFUEL    (Brazil-specific: gasoline + ethanol)
    ETANOL            → OTHERS      (pure-ethanol cars; the old workbook had
                                     no such row, so OTHERS was always 0 before
                                     2026-09 — tiny volumes, ICE side)
    sum of all above  → TOTAL       (checked against ANFAVEA's own TOTAL column)

An unknown fuel label aborts the run rather than being silently dropped, so a
new ANFAVEA category shows up as a red workflow instead of a shrinking TOTAL.

Default window
--------------
From January of the year that was current two months ago up to the current
month, i.e. the running year — plus, in January and February, the whole
previous year so that December and ANFAVEA's year-end revisions still land.
Months the database doesn't have yet are simply absent from the response, and
months where every fuel is zero are skipped.

Upsert + plausibility check
---------------------------
Existing rows in data/Brazil.csv are keyed by `period` (YYYY-MM). For each
month parsed:

  * If the period is missing, we append a new row.
  * If it exists, we overwrite the row (ANFAVEA revises the running year),
    but emit a WARNING to stdout if any fuel-type value moved by more than
    50% versus the previous value — a cheap guard against parser drift or
    upstream relabeling.

Rows are read and written back as strings, so untouched rows stay
byte-identical. The `notes` field on touched rows records the provenance.

HTTP details
------------
ANFAVEA's server rejects the default python-requests User-Agent, so we send
desktop-Chrome headers (see HTTP_HEADERS below) on both requests.
"""
import argparse
import csv
import os
import re
import sys
import unicodedata
from datetime import date, timedelta

import requests
from bs4 import BeautifulSoup

DASHBOARD_PAGE = "https://anfavea.com.br/site/central-de-dados/"
AJAX_URL = "https://anfavea.com.br/site/wp-admin/admin-ajax.php"
PROVENANCE = "anfavea.com.br/site/central-de-dados (emplacamento por combustível)"

# ANFAVEA's server rejects the default python-requests UA,
# so we identify as a regular desktop browser.
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}
CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "FLEXFUEL",
    "OTHERS", "TOTAL", "notes",
]
FUEL_COLUMNS = ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "FLEXFUEL", "OTHERS"]

# Maps ANFAVEA fuel labels (accents stripped, upper case) → CSV column names
FUEL_MAP = {
    "ELETRICO": "BEV",
    "HIBRIDO PLUG-IN": "PHEV",
    "HIBRIDO": "HEV",
    "GASOLINA": "PETROL",
    "DIESEL": "DIESEL",
    "FLEX FUEL": "FLEXFUEL",
    "ETANOL": "OTHERS",
}

MONTH_ABR = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN",
             "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]


def _norm(text: str) -> str:
    """Upper-case, accent-free, single-spaced label."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.upper().split())


def default_window(today: date) -> tuple[str, str]:
    start_year = (today - timedelta(days=60)).year
    return f"{start_year}-01", f"{today.year}-{today.month:02d}"


def get_nonce(session: requests.Session) -> str:
    """Scrape WordPress's anti-CSRF nonce off the dashboard page."""
    resp = session.get(DASHBOARD_PAGE, timeout=30)
    resp.raise_for_status()
    m = re.search(r'anfaveaData\s*=\s*\{[^}]*"nonce"\s*:\s*"([0-9a-f]+)"', resp.text)
    if not m:
        raise RuntimeError(f"Could not find the anfaveaData nonce on {DASHBOARD_PAGE}")
    return m.group(1)


def fetch_table_html(session: requests.Session, nonce: str, start: str, end: str) -> str:
    """Run the dashboard's 'emplacamento por combustível' query for
    Automóveis + Comerciais Leves and return the rendered table HTML."""
    fields = [
        ("action", "anfavea_dashboard1"),
        ("nonce", nonce),
        ("dashboard", "dashboard1"),
        ("tipo_dado", "emplacamento"),
        ("dimensao_emplacamento", "combustivel"),
        ("categorias[]", "total_leves"),
        ("combustivel_filter[]", "todos"),
        ("procedencia", ""),
        ("por_empresa", "0"),
        ("por_marca", "0"),
        ("empresa", ""),
        ("marca", ""),
        ("agregacao", "mensal"),
        ("inicio", start),
        ("fim", end),
    ]
    print(f"Querying ANFAVEA Central de Dados: {start} … {end}")
    resp = session.post(AJAX_URL, data=fields, timeout=60,
                        headers={"Referer": DASHBOARD_PAGE})
    resp.raise_for_status()
    payload = resp.json()
    data = payload.get("data")
    if not payload.get("success") or not isinstance(data, dict) or "table_html" not in data:
        raise RuntimeError(f"ANFAVEA query failed: {str(payload)[:500]}")
    return data["table_html"]


def _cell_value(cell) -> float:
    """Raw integer of a number cell: `data-valor-export` on the <td> or on
    the <strong> inside it, falling back to the pt-BR display text."""
    tagged = cell if cell.has_attr("data-valor-export") else cell.find(attrs={"data-valor-export": True})
    raw = tagged["data-valor-export"] if tagged is not None else cell.get_text(strip=True).replace(".", "")
    raw = raw.strip()
    return float(raw) if raw not in ("", "-") else 0.0


def parse_period(label: str) -> str | None:
    """'2026 - AGO' → '2026-08'; the closing 'TOTAL' row → None."""
    m = re.fullmatch(r"(\d{4})\s*-\s*([A-Z]{3})", _norm(label))
    if not m or m.group(2) not in MONTH_ABR:
        return None
    return f"{m.group(1)}-{MONTH_ABR.index(m.group(2)) + 1:02d}"


def parse_table(html: str) -> dict[str, dict]:
    """
    Parse the fuel table into {period: row_dict} for every month that has at
    least one non-zero fuel value.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        raise RuntimeError("ANFAVEA response has no <table>")
    header = [th.get_text(" ", strip=True) for th in table.find("thead").find_all("th")]

    # "TOTAL LEVES - ELÉTRICO" → column BEV; the last "TOTAL" is ANFAVEA's sum.
    col_map: dict[int, str] = {}
    total_idx = None
    for i, label in enumerate(header[1:], start=1):
        name = _norm(label)
        if name == "TOTAL":
            total_idx = i
            continue
        fuel = name.rsplit(" - ", 1)[-1]
        if fuel not in FUEL_MAP:
            raise RuntimeError(f"Unknown ANFAVEA fuel column {label!r} — extend FUEL_MAP")
        col_map[i] = FUEL_MAP[fuel]
    if not col_map:
        raise RuntimeError(f"No fuel columns in ANFAVEA table header: {header}")
    print(f"Fuel columns found: {[header[i] for i in col_map]}")

    result: dict[str, dict] = {}
    for tr in table.find("tbody").find_all("tr"):
        cells = tr.find_all(["td", "th"])
        period = parse_period(cells[0].get_text(" ", strip=True))
        if period is None:
            continue
        values = dict.fromkeys(FUEL_COLUMNS, 0.0)
        for i, col in col_map.items():
            values[col] += _cell_value(cells[i])
        if all(v == 0.0 for v in values.values()):
            continue
        row: dict = {
            "period": period,
            "time_interval": "monthly",
            "variant": "Whole",
            "source": "ANFAVEA",
            **values,
        }
        row["TOTAL"] = sum(values.values())
        if total_idx is not None:
            reported = _cell_value(cells[total_idx])
            if reported != row["TOTAL"]:
                raise RuntimeError(
                    f"{period}: fuel columns sum to {row['TOTAL']:.0f} but ANFAVEA's "
                    f"TOTAL is {reported:.0f} — table layout changed?"
                )
        result[period] = row
    return result


def upsert_csv(csv_path: str, new_rows: dict[str, dict], provenance: str) -> tuple[int, int]:
    """
    Upsert new_rows into csv_path by the 'period' key.
    Returns (added, updated) counts. Warns on implausible changes (>50% delta).
    """
    existing: dict[str, dict] = {}
    if os.path.exists(csv_path):
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing[row["period"]] = row

    added = updated = 0
    for period, new_row in sorted(new_rows.items()):
        new_row["notes"] = provenance
        if period not in existing:
            existing[period] = new_row
            added += 1
            print(f"  + {period}")
        else:
            old = existing[period]
            for col in FUEL_COLUMNS:
                old_val = float(old.get(col) or 0)
                new_val = float(new_row[col])
                if old_val > 0 and abs(new_val - old_val) / old_val > 0.5:
                    print(
                        f"  WARNING {period} {col}: existing={old_val:.0f}, "
                        f"new={new_val:.0f} — diff >{50}%, please verify"
                    )
            existing[period] = {**old, **new_row}
            updated += 1
            print(f"  ~ {period}")

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for period in sorted(existing.keys()):
            writer.writerow(existing[period])

    return added, updated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, help="Fetch Jan–Dec of this year")
    parser.add_argument("--from", dest="start", help="First month, YYYY-MM")
    parser.add_argument("--to", dest="end", help="Last month, YYYY-MM")
    parser.add_argument("--csv", default="data/Brazil.csv",
                        help="Path to Brazil CSV (default: data/Brazil.csv)")
    args = parser.parse_args()

    start, end = default_window(date.today())
    if args.year:
        start, end = f"{args.year}-01", f"{args.year}-12"
    start, end = args.start or start, args.end or end
    for v in (start, end):
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", v):
            parser.error(f"expected YYYY-MM, got {v!r}")

    session = requests.Session()
    session.headers.update(HTTP_HEADERS)
    html = fetch_table_html(session, get_nonce(session), start, end)

    new_rows = parse_table(html)
    if not new_rows:
        print("No data in the requested window. Nothing to update.")
        sys.exit(0)
    print(f"Parsed {len(new_rows)} months: {sorted(new_rows.keys())}")

    added, updated = upsert_csv(args.csv, new_rows, PROVENANCE)
    print(f"\nDone: {added} rows added, {updated} rows updated → {args.csv}")


if __name__ == "__main__":
    main()
