#!/usr/bin/env python3
"""
Fetch Albania monthly vehicle-registration data directly from DPSHTRR via the
Looker Studio batchedDataV2 API and upsert ``data/Albania.csv``.

Usage
-----
    python scripts/fetch_albania.py [--dry-run] [--since YYYY-MM]
                                    [--year-from YYYY] [--year-to YYYY]

Primary source
--------------
Albania's General Directorate of Road Transport Services (DPSHTRR) publishes
vehicle registration data via a public Looker Studio report at

    https://www.dpshtrr.al/open-data-dpshtrr-english
    https://datastudio.google.com/reporting/407ce08b-d3ce-478e-9bc7-a50125f875f3/page/VPWqB

We query the Looker Studio batchedDataV2 API directly (no Google account
required for public reports).  The report is a public resource; we obtain an
anonymous session cookie (RAP_XSRF_TOKEN) from the initial page load and use
it for the POST.

Note: The report title is "year 2026".  DPSHTRR appear to publish a fresh
report each calendar year (same datasourceId, but a new Looker report for each
year).  Historical data (pre-2026) therefore lives in the bootstrapped CSV
rows and is not re-fetched.  See docs/architecture/27-source-albania.md for
the full source playbook.

Fuel-type mapping (Lenda Djegese → gallery schema)
---------------------------------------------------
Derived from the DPSHTRR Looker table export (Jan–May 2026):

    Elektrik                            → BEV
    Hybrid plug-in, Benzinë/Elektrik    → PHEV
    Hybrid plug-in, Naftë/Elektrik      → PHEV  (diesel PHEV)
    Hybrid Benzinë/Elektrik             → HEV
    Hybrid Naftë/Elektrik               → HEV   (mild-hybrid diesel)
    Hybrid Benzinë/Gaz/Elektrik         → HEV
    Benzinë                             → PETROL
    Naftë                               → DIESEL
    everything else (LPG, Gas, CNG, …)  → OTHERS

Only Autoveturë (passenger cars) rows are included.
TOTAL = BEV + PHEV + HEV + PETROL + DIESEL + OTHERS.

All registrations (new AND first registrations of imported used vehicles)
are counted.  Albania has a significant used-car import market so headline
figures differ from new-car-only sources.

Invoked by ``.github/workflows/fetch-albania.yml``. Commit step is
change-gated, so steady-state runs are a no-op.
"""
import argparse
import csv
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

import requests

# ── Looker Studio report constants ──────────────────────────────────────────
REPORT_ID       = "407ce08b-d3ce-478e-9bc7-a50125f875f3"
PAGE_ID_URL     = "VPWqB"      # visible in browser address bar
PAGE_ID_NUM     = "24871631"   # numeric ID used inside batchedDataV2 body
COMPONENT_ID    = "cd-p9hqinijec"
DATASOURCE_ID   = "7705f3ec-84aa-4432-bbed-d61775f98126"
REVISION_NUMBER = 13           # revision of DPSHTRR's Looker data source

# Internal field IDs reverse-engineered from batchedDataV2 capture (2026-06-13)
F_VEHICLE_TYPE = "_73515086_"                                        # Lloji
F_FUEL_TYPE    = "_818800577_"                                       # Lenda Djegese
F_RECORD_COUNT = "datastudio_record_count_system_field_id_98323387"  # count
F_DATE         = "_3076010_"                                         # Month

REPORT_PAGE_URL = (
    f"https://datastudio.google.com/reporting/{REPORT_ID}/page/{PAGE_ID_URL}"
    f"?s=ntCeOqOLBog"
)
API_URL = "https://datastudio.google.com/batchedDataV2?appVersion=20260607_0101"

VEHICLE_FILTER_VALUE = "Autoveturë"   # passenger cars only

# ── Gallery schema ───────────────────────────────────────────────────────────
SOURCE      = "dpshtrr.al"
CSV_PATH    = "data/Albania.csv"
VARIANT     = "Whole"
CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL", "notes",
]
VALUE_COLS  = ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS"]

# ── Fuel-type → gallery-column mapping ──────────────────────────────────────
_BEV   = {"Elektrik"}
_PHEV  = {"Hybrid plug-in, Benzinë/Elektrik", "Hybrid plug-in, Naftë/Elektrik"}
_HEV   = {"Hybrid Benzinë/Elektrik", "Hybrid Naftë/Elektrik",
           "Hybrid Benzinë/Gaz/Elektrik"}
_PET   = {"Benzinë"}
_DIE   = {"Naftë"}

def _fuel_col(fuel: str) -> str:
    if fuel in _BEV:  return "BEV"
    if fuel in _PHEV: return "PHEV"
    if fuel in _HEV:  return "HEV"
    if fuel in _PET:  return "PETROL"
    if fuel in _DIE:  return "DIESEL"
    return "OTHERS"


# ── Date-string parsing ──────────────────────────────────────────────────────
# Looker Studio returns dates in various locale-dependent string formats.
_DE_MONTH = {
    "Jan": "01", "Feb": "02", "Mär": "03", "Apr": "04",
    "Mai": "05", "Jun": "06", "Jul": "07", "Aug": "08",
    "Sep": "09", "Okt": "10", "Nov": "11", "Dez": "12",
}
_EN_MONTH = {
    "January": "01", "February": "02", "March": "03", "April": "04",
    "May": "05", "June": "06", "July": "07", "August": "08",
    "September": "09", "October": "10", "November": "11", "December": "12",
}

_RE_DE   = re.compile(r'^(Jan|Feb|Mär|Apr|Mai|Jun|Jul|Aug|Sep|Okt|Nov|Dez)\.?\s+(\d{4})$')
_RE_EN   = re.compile(r'^(January|February|March|April|May|June|July|August|'
                       r'September|October|November|December)\s+(\d{4})$')
_RE_ISO  = re.compile(r'^(\d{4})-(\d{2})-\d{2}$')   # 2026-01-01
_RE_YM   = re.compile(r'^(\d{4})(\d{2})$')            # 202601


def _parse_period(s: str) -> str | None:
    s = s.strip()
    m = _RE_DE.match(s)
    if m:
        return f"{m.group(2)}-{_DE_MONTH[m.group(1)]}"
    m = _RE_EN.match(s)
    if m:
        return f"{m.group(2)}-{_EN_MONTH[m.group(1)]}"
    m = _RE_ISO.match(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = _RE_YM.match(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return None


# ── Session helpers ──────────────────────────────────────────────────────────

def _get_session() -> tuple[requests.Session, str | None]:
    """Load the public Looker Studio page and try to obtain a session token.

    For authenticated Google sessions the RAP_XSRF_TOKEN arrives as a cookie.
    For anonymous sessions (GitHub Actions) it is absent from cookies but may
    be embedded in the page HTML.  If neither source yields a token we proceed
    without one — public Looker reports do not always require XSRF for
    anonymous reads.  The API call will raise on 4xx if auth is needed.
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (compatible; LeRaffl-Gallery fetch_albania; "
            "+https://leraffl.github.io/LeRaffl-Gallery/)"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    })
    print(f"[albania] GET {REPORT_PAGE_URL}")
    resp = session.get(REPORT_PAGE_URL, timeout=60, allow_redirects=True)
    print(f"[albania] page load HTTP {resp.status_code}")
    resp.raise_for_status()

    # 1. Cookie (set for authenticated Google sessions)
    xsrf = session.cookies.get("RAP_XSRF_TOKEN")
    if xsrf:
        print(f"[albania] XSRF token from cookie ({xsrf[:16]}...)")
        return session, xsrf

    # 2. Embedded in page HTML / JavaScript (anonymous sessions)
    for pattern in (
        r'RAP_XSRF_TOKEN["\'][,\s:]+["\']([^"\']{10,})["\']',
        r'"RAP_XSRF_TOKEN"\s*,\s*"([^"]{10,})"',
        r"'RAP_XSRF_TOKEN'\s*,\s*'([^']{10,})'",
    ):
        m = re.search(pattern, resp.text)
        if m:
            xsrf = m.group(1)
            print(f"[albania] XSRF token from page HTML ({xsrf[:16]}...)")
            return session, xsrf

    # 3. Not found — proceed without; let the API call fail naturally on 4xx
    print("[albania] RAP_XSRF_TOKEN not found in cookie or page; "
          "proceeding without XSRF header (public report may not require it).")
    return session, None


# ── batchedDataV2 payload ────────────────────────────────────────────────────

def _build_payload(year_from: int, year_to: int) -> dict:
    """
    Build a flat-table batchedDataV2 request for:
      (Month, Fuel type) × Record Count
    filtered to Autoveturë (passenger cars).
    Date range: year_from-01-01 … year_to-12-31.
    """
    req_id = f"fetch_albania_{uuid.uuid4().hex[:8]}"
    return {
        "dataRequest": [{
            "requestContext": {
                "reportContext": {
                    "reportId":    REPORT_ID,
                    "pageId":      PAGE_ID_NUM,
                    "mode":        1,
                    "componentId": COMPONENT_ID,
                    "displayType": "table",
                },
                "requestMode": 0,
            },
            "datasetSpec": {
                "dataset": [{
                    "datasourceId":      DATASOURCE_ID,
                    "revisionNumber":    REVISION_NUMBER,
                    "parameterOverrides": [],
                }],
                "queryFields": [
                    {
                        "name": "qt_date",
                        "datasetNs": "d0", "tableNs": "t0",
                        "dataTransformation": {"sourceFieldName": F_DATE},
                    },
                    {
                        "name": "qt_fuel",
                        "datasetNs": "d0", "tableNs": "t0",
                        "dataTransformation": {"sourceFieldName": F_FUEL_TYPE},
                    },
                    {
                        "name": "qt_count",
                        "datasetNs": "d0", "tableNs": "t0",
                        "dataTransformation": {"sourceFieldName": F_RECORD_COUNT},
                    },
                ],
                "sortData": [{"name": "qt_date", "sortDir": 1}],
                "includeRowsCount": False,
                "relatedDimensionMask": {
                    "addDisplay": False, "addUniqueId": False, "addLatLong": False,
                },
                "dsFilterOverrides": [],
                "filters": [
                    {
                        "filterInfo": {
                            "type":        "INCLUDE",
                            "operand":     "EQUALS",
                            "expressions": [VEHICLE_FILTER_VALUE],
                            "fieldName":   F_VEHICLE_TYPE,
                        }
                    }
                ],
                "features": [],
                "dateRanges": [{
                    "start": f"{year_from}0101",
                    "end":   f"{year_to}1231",
                }],
                "contextNsCount": 1,
                "dateRangeDimensions": [{
                    "name": "qt_ci4tkhro0d",
                    "datasetNs": "d0", "tableNs": "t0",
                    "dataTransformation": {"sourceFieldName": F_DATE},
                }],
                "calculatedField":       [],
                "needGeocoding":         False,
                "geoFieldMask":          [],
                "multipleGeocodeFields": [],
                "timezone":              "Europe/Vienna",
            },
            "role": "main",
            "retryHints": {
                "useClientControlledRetry": True,
                "isLastRetry":  False,
                "retryCount":   0,
                "originalRequestId": req_id,
            },
        }]
    }


# ── Response parsing ─────────────────────────────────────────────────────────

def _parse_response(data: dict) -> dict:
    """
    Parse batchedDataV2 JSON → {(period, VARIANT): gallery_row_dict}.

    The response has three column arrays (date strings, fuel strings, counts).
    Null entries are tracked via ``nullIndex`` integer arrays.
    """
    rows: dict = {}

    for dr in data.get("dataResponse", []):
        for subset in dr.get("dataSubset", []):
            tds = subset.get("dataset", {}).get("tableDataset", {})
            cols = tds.get("column", [])
            col_info = tds.get("columnInfo", [])
            size = tds.get("size", 0)

            col_names = [c.get("name") for c in col_info]
            print(f"[albania] response subset: cols={col_names}, size={size}")

            if len(cols) < 3 or size == 0:
                print("[albania] empty or malformed subset, skipping")
                continue

            date_col  = cols[0]
            fuel_col  = cols[1]
            count_col = cols[2]

            null_date  = set(date_col.get("nullIndex",  []))
            null_fuel  = set(fuel_col.get("nullIndex",  []))
            null_count = set(count_col.get("nullIndex", []))

            dates  = date_col.get("stringColumn",  {}).get("values", [])
            fuels  = fuel_col.get("stringColumn",  {}).get("values", [])
            counts = count_col.get("longColumn",   {}).get("values", [])

            for i in range(size):
                if i in null_date or i in null_fuel:
                    continue
                period = _parse_period(dates[i])
                if not period:
                    print(f"[albania]   unparseable date {dates[i]!r}, skip")
                    continue

                fuel  = fuels[i]
                count = int(counts[i]) if i not in null_count else 0
                col   = _fuel_col(fuel)
                key   = (period, VARIANT)

                if key not in rows:
                    rows[key] = {
                        "period":        period,
                        "time_interval": "monthly",
                        "variant":       VARIANT,
                        "source":        SOURCE,
                        "BEV":    0.0, "PHEV":   0.0, "HEV":   0.0,
                        "PETROL": 0.0, "DIESEL": 0.0, "OTHERS": 0.0,
                        "TOTAL":  0.0,
                        "notes":  "",
                    }
                rows[key][col] = rows[key].get(col, 0.0) + count

    # Compute TOTAL; zero optional cols → empty string (gallery convention)
    for row in rows.values():
        row["TOTAL"] = sum(row[c] for c in VALUE_COLS)
        for col in ["BEV", "PHEV", "HEV", "OTHERS"]:
            if row[col] == 0.0:
                row[col] = ""

    return rows


# ── CSV upsert ───────────────────────────────────────────────────────────────

def upsert_csv(
    csv_path: str, new_rows: dict, since: str | None
) -> tuple[int, int]:
    existing: dict = {}
    if os.path.exists(csv_path):
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                for c in CSV_COLUMNS:
                    row.setdefault(c, "")
                existing[(row["period"], row["variant"])] = {
                    k: row[k] for k in CSV_COLUMNS
                }

    added = updated = 0
    for key, new_row in sorted(new_rows.items()):
        if since and key[0] < since:
            continue
        if key not in existing:
            existing[key] = new_row
            added += 1
            print(f"  + {key[1]} {key[0]}")
        else:
            if not new_row.get("notes"):
                new_row["notes"] = existing[key].get("notes", "")
            existing[key] = {**existing[key], **new_row}
            updated += 1

    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        w.writeheader()
        for key in sorted(existing.keys(), key=lambda k: (k[1], k[0])):
            w.writerow(existing[key])
    return added, updated


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", default=None,
                    help="Only upsert months >= YYYY-MM (default: all).")
    ap.add_argument("--year-from", type=int, default=datetime.now().year,
                    help="First calendar year to request from the API "
                         "(default: current year). Use 2019 for a full backfill.")
    ap.add_argument("--year-to", type=int, default=datetime.now().year,
                    help="Last calendar year to request from the API "
                         "(default: current year).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch and parse; print monthly totals; do not write CSV.")
    ap.add_argument("--force", action="store_true",
                    help="Accepted for parity (commit-gated downstream).")
    args = ap.parse_args()

    session, xsrf = _get_session()

    payload = _build_payload(args.year_from, args.year_to)
    api_headers = {
        "Content-Type":      "application/json",
        "Accept":            "application/json, text/plain, */*",
        "Accept-Encoding":   "gzip, deflate, br",
        "Accept-Language":   "de-DE,de;q=0.9",
        "Cache-Control":     "no-cache",
        "Origin":            "https://datastudio.google.com",
        "Pragma":            "no-cache",
        "Referer":           REPORT_PAGE_URL,
    }
    if xsrf:
        api_headers["X-RAP-XSRF-TOKEN"] = xsrf

    print(f"[albania] POST {API_URL}")
    resp = session.post(
        API_URL, json=payload, headers=api_headers, timeout=120
    )
    print(f"[albania] HTTP {resp.status_code} ({len(resp.content)} bytes)")
    resp.raise_for_status()

    # Strip the Looker Studio XSSI prefix )]}'\\n
    text = resp.text
    if text.startswith(")]}'"):
        text = text[4:].lstrip("\n")

    data = json.loads(text)
    rows = _parse_response(data)

    if not rows:
        print("[albania] no data rows in response — "
              "the report may only expose current-year data. "
              "Historical rows (pre-current-year) are kept from the bootstrapped CSV.")
        return

    print(f"[albania] parsed {len(rows)} month-variant rows")
    for key in sorted(rows):
        r = rows[key]
        bev  = r["BEV"]  or 0
        phev = r["PHEV"] or 0
        hev  = r["HEV"]  or 0
        print(
            f"  {key[0]}  BEV={bev:.0f}  PHEV={phev:.0f}  HEV={hev:.0f}"
            f"  PETROL={r['PETROL']:.0f}  DIESEL={r['DIESEL']:.0f}"
            f"  OTHERS={r['OTHERS'] or 0:.0f}  TOTAL={r['TOTAL']:.0f}"
        )

    if args.dry_run:
        print("(dry-run: CSV not written)")
        return

    added, updated = upsert_csv(CSV_PATH, rows, args.since)
    print(f"{added} added, {updated} updated -> {CSV_PATH}")


if __name__ == "__main__":
    main()
