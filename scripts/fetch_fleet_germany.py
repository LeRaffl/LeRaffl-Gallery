#!/usr/bin/env python3
"""
Fetch Germany's passenger-car FLEET (stock / Bestand) by drivetrain from the
Kraftfahrt-Bundesamt (KBA) and upsert it into ``fleet/fleet_initial.csv``.

This is the pilot for the harmonized fleet-fetch pattern — see
``docs/architecture/37-fleet-data-harmonization.md`` (§4b for the confirmed
Germany mapping). It is the fleet-side analogue of the ``scripts/fetch_<country>.py``
registration ingesters, but writes the *stock* dataset, is *annual*, and does
**not** trigger a render (fleet charts are computed in the browser).

Source
------
KBA "Bestand an Kraftfahrzeugen nach Umwelt-Merkmalen" (FZ 13), annual XLSX.
Overview page:
  https://www.kba.de/DE/Statistik/Produktkatalog/produkte/Fahrzeuge/fz13_b_uebersicht.html
Files: ``fz13_YYYY.xlsx`` (snapshot 1 January YYYY).

We read **sheet "FZ 13.2.1"** = "Bestand an Personenkraftwagen 2010 bis YYYY nach
Kraftstoffarten" — a clean annual time series with the full fuel split. Every row
sums exactly to the reported total (verified). Column layout (the date/year sits
in the *second* spreadsheet column; column A is blank — hence the 1-based cell
columns below):

    col 2  Jahr            (snapshot 1 Jan; our year = Jahr - 1, "end of year")
    col 3  Benzin          -> PETROL   (from 2017 excl. ethanol; see note)
    col 4  Diesel          -> DIESEL
    col 5  Flüssiggas (LPG) -> LPG
    col 6  Erdgas (CNG)    -> CNG
    col 7  Elektro (BEV)   -> BEV
    col 8  Hybrid insgesamt (incl. plug-in)   \\  HEV = col8 - col9
    col 9  darunter Plug-in -> PHEV           /   (col8 also includes mild hybrids
    col 10 Sonstige        -> OTHERS               -> HEV carries MHEV; flagged)
    col 11 Insgesamt       -> TOTAL

Why FZ 13.2.1 and not FZ 27.9? FZ 27.9 is quarterly but gives ICE only as one
aggregate (no petrol/diesel split). FZ 13.2.1 is annual, splits petrol/diesel and
even LPG/CNG, matches the schema's ``year`` granularity, and reaches back to 2010.

Year convention
---------------
KBA "Jahr Y" is the stock as of 1 January Y. We label it **year Y-1** (stock at
the *end* of year Y-1), matching the maintainer's existing Germany rows exactly
(verified: existing DE 2025 == KBA Jahr 2026). The snapshot date is recorded in
``notes``.

Network
-------
KBA may drop datacenter IPs. Same escape hatches as the registration fetchers:
``KBA_FETCH_RELAY`` (+ optional ``KBA_RELAY_TOKEN``) or ``KBA_PROXY``; otherwise a
direct connection / ambient ``HTTPS_PROXY`` is used.

Usage
-----
    python scripts/fetch_fleet_germany.py [--file PATH] [--url URL] [--dry-run]

``--file`` parses a local xlsx (offline / testing) instead of downloading.
``--dry-run`` prints the parsed rows and the diff without writing the CSV.
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote, urljoin

import openpyxl

REPO_ROOT = Path(__file__).resolve().parent.parent
FLEET_CSV = REPO_ROOT / "fleet" / "fleet_initial.csv"

COUNTRY = "Germany"
VARIANT = "Whole"
SOURCE = "KBA FZ 13.2.1"
SHEET = "FZ 13.2.1"

OVERVIEW_URL = (
    "https://www.kba.de/DE/Statistik/Produktkatalog/produkte/Fahrzeuge/"
    "fz13_b_uebersicht.html"
)
KBA_BASE = "https://www.kba.de"

# Harmonized fleet schema (docs/architecture/37). Keep in sync with the CSV
# header and index.html:loadFleetObserved.
FLEET_COLUMNS = [
    "country", "variant", "year", "source",
    "BEV", "PHEV", "EREV", "HEV", "MHEV",
    "PETROL", "DIESEL", "GAS", "CNG", "LPG", "FLEXFUEL", "ETHANOL",
    "OTHERS", "TOTAL", "notes",
]

DATE_RE = re.compile(r"^\s*(\d{4})\s*$")


# --------------------------------------------------------------------------- #
# Networking (mirrors scripts/fetch_austria.py::_configure_network)
# --------------------------------------------------------------------------- #
def _make_session():
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    session = requests.Session()
    session.headers.update({"User-Agent": "LeRaffl-Gallery/germany-fleet-fetch"})
    session.relay_base = None  # type: ignore[attr-defined]

    relay = os.environ.get("KBA_FETCH_RELAY", "").strip()
    if relay:
        session.relay_base = relay  # type: ignore[attr-defined]
        token = os.environ.get("KBA_RELAY_TOKEN", "").strip()
        if token:
            session.headers["X-Relay-Token"] = token
        print(f"[net] routing via KBA_FETCH_RELAY = "
              f"{re.sub(r'//[^/]+', '//<host>', relay, count=1)}")
    else:
        proxy = os.environ.get("KBA_PROXY", "").strip()
        if proxy:
            session.proxies.update({"http": proxy, "https": proxy})
            print("[net] routing via KBA_PROXY")
        elif os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"):
            print("[net] using HTTPS_PROXY from environment")
        else:
            print("[net] WARNING: no relay/proxy set; connecting directly.")

    retry = Retry(total=5, connect=5, read=3, backoff_factor=3,
                  status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET"])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _get(session, url, **kwargs):
    base = getattr(session, "relay_base", None)
    if base:
        url = base + quote(url, safe="")
    return session.get(url, timeout=60, **kwargs)


def discover_latest_xlsx(session) -> str:
    """Find the newest ``fz13_YYYY.xlsx`` link on the overview page."""
    resp = _get(session, OVERVIEW_URL)
    resp.raise_for_status()
    html = resp.text
    hrefs = re.findall(r'href="([^"]*fz13_\d{4}\.xlsx[^"]*)"', html, re.I)
    if not hrefs:
        raise RuntimeError(
            "No fz13_YYYY.xlsx link found on the overview page "
            f"({OVERVIEW_URL}); the page layout may have changed.")

    def year_of(h: str) -> int:
        m = re.search(r"fz13_(\d{4})\.xlsx", h)
        return int(m.group(1)) if m else 0

    best = max(hrefs, key=year_of)
    return urljoin(KBA_BASE, best.replace("&amp;", "&"))


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def _num(v):
    """Numeric cell -> int; KBA placeholders -> None (unknown) except '-'=0."""
    if isinstance(v, (int, float)):
        return int(round(v))
    if isinstance(v, str) and v.strip() == "-":
        return 0            # "nichts vorhanden" = a measured zero
    return None             # "X" / "." / "/" / blank -> unknown


def parse_fz13_2_1(source) -> list[dict]:
    """Parse sheet FZ 13.2.1 into harmonized fleet rows (one per year)."""
    wb = openpyxl.load_workbook(source, data_only=True)
    if SHEET not in wb.sheetnames:
        raise RuntimeError(f"Sheet {SHEET!r} not found; sheets: {wb.sheetnames}")
    ws = wb[SHEET]

    rows: list[dict] = []
    for i in range(1, ws.max_row + 1):
        jahr_cell = ws.cell(i, 2).value
        m = DATE_RE.match(str(jahr_cell)) if jahr_cell is not None else None
        if not m:
            continue
        jahr = int(m.group(1))
        if jahr < 2000 or jahr > 2100:
            continue

        petrol = _num(ws.cell(i, 3).value)
        diesel = _num(ws.cell(i, 4).value)
        lpg = _num(ws.cell(i, 5).value)
        cng = _num(ws.cell(i, 6).value)
        bev = _num(ws.cell(i, 7).value)
        hyb_total = _num(ws.cell(i, 8).value)
        plugin = _num(ws.cell(i, 9).value)
        others = _num(ws.cell(i, 10).value)
        total = _num(ws.cell(i, 11).value)

        # Hybrid split: PHEV = darunter Plug-in; HEV = the rest of the hybrid
        # bucket (incl. mild hybrids -> mhev_in_hev). If Plug-in is unknown ("X",
        # early years), keep the whole hybrid bucket as a combined HEV value with
        # PHEV empty (the frontend then renders it as a combined "Hybrid" band).
        note_bits = [f"Stand 1.1.{jahr}"]
        if plugin is not None and hyb_total is not None:
            phev = plugin
            hev = hyb_total - plugin
            note_bits.append("HEV incl. MHEV")
        else:
            phev = None
            hev = hyb_total          # combined bucket
            if hyb_total is not None:
                note_bits.append("HEV = combined PHEV+HEV (source did not split)")
        if jahr < 2017:
            note_bits.append("PETROL incl. ethanol (pre-2017)")

        rows.append({
            "country": COUNTRY,
            "variant": VARIANT,
            "year": jahr - 1,                # end-of-year convention
            "source": f"{SOURCE} (Stand 1.1.{jahr})",
            "BEV": bev,
            "PHEV": phev,
            "EREV": None,
            "HEV": hev,
            "MHEV": None,
            "PETROL": petrol,
            "DIESEL": diesel,
            "GAS": None,                     # split into CNG + LPG below
            "CNG": cng,
            "LPG": lpg,
            "FLEXFUEL": None,
            "ETHANOL": None,
            "OTHERS": others,
            "TOTAL": total,
            "notes": "; ".join(note_bits),
        })

    if not rows:
        raise RuntimeError(f"No data rows parsed from sheet {SHEET!r}.")
    rows.sort(key=lambda r: r["year"], reverse=True)
    return rows


# --------------------------------------------------------------------------- #
# Line-level upsert into fleet/fleet_initial.csv
# --------------------------------------------------------------------------- #
def _fmt(v) -> str:
    return "" if v is None else str(v)


def _row_to_line(r: dict) -> str:
    return ",".join(_fmt(r.get(c)) for c in FLEET_COLUMNS)


def upsert(rows: list[dict], csv_path: Path = FLEET_CSV) -> tuple[int, int]:
    """Replace Germany/Whole rows, keeping every other line byte-for-byte."""
    text = csv_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines:
        raise RuntimeError(f"{csv_path} is empty.")
    header = lines[0]
    header_cols = [c.strip() for c in header.split(",")]
    if header_cols != FLEET_COLUMNS:
        raise RuntimeError(
            "fleet CSV header does not match the harmonized schema.\n"
            f"  expected: {FLEET_COLUMNS}\n  found:    {header_cols}\n"
            "Run the schema migration first (docs/architecture/37 §5).")

    kept: list[str] = []
    first_de_idx: int | None = None
    for idx, line in enumerate(lines[1:]):
        if not line.strip():
            continue
        cells = [c.strip() for c in line.split(",")]
        country = cells[0] if cells else ""
        variant = cells[1] if len(cells) > 1 else ""
        if country == COUNTRY and (variant == VARIANT or variant == ""):
            if first_de_idx is None:
                first_de_idx = len(kept)
            continue
        kept.append(line)

    new_block = [_row_to_line(r) for r in rows]
    insert_at = first_de_idx if first_de_idx is not None else len(kept)
    out = [header] + kept[:insert_at] + new_block + kept[insert_at:]
    csv_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return len(new_block), len(kept)


# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", help="parse a local xlsx instead of downloading")
    ap.add_argument("--url", help="override the xlsx download URL")
    ap.add_argument("--dry-run", action="store_true",
                    help="print parsed rows and exit without writing")
    args = ap.parse_args()

    if args.file:
        print(f"[src] parsing local file {args.file}")
        rows = parse_fz13_2_1(args.file)
    else:
        session = _make_session()
        url = args.url or discover_latest_xlsx(session)
        print(f"[src] downloading {url}")
        resp = _get(session, url)
        resp.raise_for_status()
        rows = parse_fz13_2_1(io.BytesIO(resp.content))

    print(f"[parse] {len(rows)} year rows "
          f"({rows[-1]['year']}–{rows[0]['year']})")
    if args.dry_run:
        for r in rows:
            print(_row_to_line(r))
        return

    n_new, n_kept = upsert(rows)
    print(f"[write] {FLEET_CSV.relative_to(REPO_ROOT)}: "
          f"{n_new} Germany rows, {n_kept} other-country lines preserved")


if __name__ == "__main__":
    main()
