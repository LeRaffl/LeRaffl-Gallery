#!/usr/bin/env python3
"""
Fetch Albania monthly vehicle-registration data directly from DPSHTRR's public
Looker Studio report and upsert ``data/Albania.csv``.

Usage
-----
    python scripts/fetch_albania.py [--dry-run] [--since YYYY-MM]
                                    [--year-from YYYY] [--year-to YYYY]

How it works
------------
Albania's General Directorate of Road Transport Services (DPSHTRR) publishes
vehicle-registration data **only** through a public Looker Studio report:

    https://lookerstudio.google.com/reporting/407ce08b-d3ce-478e-9bc7-a50125f875f3/page/VPWqB

The Looker ``batchedDataV2`` API rejects anonymous plain-HTTP clients with
``ACCESS / PREFETCH_VALIDATION``.  A real browser session is required because
Google sets the ``RAP_XSRF_TOKEN`` only after JavaScript runs.

We therefore:
  1. Drive a **headless Chromium (Playwright)** to load the public report page,
     which lets Google establish the session.
  2. Intercept the XSRF token + cookies from the first ``batchedDataV2``
     request the page issues.
  3. **Replay** those auth credentials with our own custom payload that
     requests ``(Month × Fuel type × Vehicle type, Record count)`` filtered
     to ``Autoveturë`` (passenger cars).

The native report components only expose aggregated fuel-type breakdowns
(no month dimension); the custom payload is what gives us month-level data.

Note: DPSHTRR publishes a fresh Looker report each calendar year ("year 2026").
Historical data (pre-2026) lives in the bootstrapped CSV rows.  When a new year
starts, update ``REPORT_ID`` / ``PAGE_ID_URL`` below.
See docs/architecture/27-source-albania.md for the full source playbook.

Fuel-type mapping (Lenda Djegese → gallery schema)
---------------------------------------------------
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

All registrations (new AND first registrations of imported used vehicles) are
counted.  Albania has a significant used-car import market so headline figures
differ from new-car-only sources.

Invoked by ``.github/workflows/fetch-albania.yml``. Commit step is
change-gated, so steady-state runs are a no-op.
"""
import argparse
import csv
import json
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

import requests

DEBUG = os.environ.get("ALBANIA_DEBUG") == "1"

# ── Looker Studio report constants ──────────────────────────────────────────
REPORT_ID       = "407ce08b-d3ce-478e-9bc7-a50125f875f3"
PAGE_ID_URL     = "VPWqB"      # "Vehicles by type of fuel or power source"
PAGE_ID_NUM     = "24871631"   # numeric ID used in the batchedDataV2 body
COMPONENT_ID    = "cd-p9hqinijec"
DATASOURCE_ID   = "7705f3ec-84aa-4432-bbed-d61775f98126"
REVISION_NUMBER = 13

# Internal field IDs (reverse-engineered 2026-06-13; bump REVISION_NUMBER if
# DPSHTRR updates their data source and the workflow starts returning empty data)
F_VEHICLE_TYPE = "_73515086_"
F_FUEL_TYPE    = "_818800577_"
F_RECORD_COUNT = "datastudio_record_count_system_field_id_98323387"
F_DATE         = "_3076010_"

REPORT_PAGE_URL = (
    f"https://lookerstudio.google.com/reporting/{REPORT_ID}/page/{PAGE_ID_URL}"
    f"?s=ntCeOqOLBog"
)
API_URL_TEMPLATE = "https://datastudio.google.com/batchedDataV2?appVersion={}"

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
_DE_MONTH = {
    "Jan": "01", "Feb": "02", "Mär": "03", "Apr": "04",
    "Mai": "05", "Jun": "06", "Jul": "07", "Aug": "08",
    "Sep": "09", "Okt": "10", "Nov": "11", "Dez": "12",
}
_EN_MONTH = {
    "January": "01", "February": "02", "March": "03", "April": "04",
    "May": "05", "June": "06", "July": "07", "August": "08",
    "September": "09", "October": "10", "November": "11", "December": "12",
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "Jun": "06",
    "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11",
    "Dec": "12",
}
_RE_DE  = re.compile(r'^(Jan|Feb|Mär|Apr|Mai|Jun|Jul|Aug|Sep|Okt|Nov|Dez)\.?\s+(\d{4})$')
_RE_EN  = re.compile(r'^(January|February|March|April|May|June|July|August|'
                     r'September|October|November|December|Jan|Feb|Mar|Apr|'
                     r'Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+(\d{4})$')
_RE_ISO = re.compile(r'^(\d{4})-(\d{2})(?:-\d{2})?$')
_RE_YMD = re.compile(r'^(\d{4})(\d{2})\d{2}$')
_RE_YM  = re.compile(r'^(\d{4})(\d{2})$')


def _parse_period(s: str) -> str | None:
    s = (s or "").strip()
    m = _RE_DE.match(s)
    if m:
        return f"{m.group(2)}-{_DE_MONTH[m.group(1)]}"
    m = _RE_EN.match(s)
    if m:
        return f"{m.group(2)}-{_EN_MONTH[m.group(1)]}"
    m = _RE_ISO.match(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = _RE_YMD.match(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = _RE_YM.match(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return None


# ── batchedDataV2 payload ────────────────────────────────────────────────────

def _build_payload(year_from: int, year_to: int) -> dict:
    """Custom flat-table request: (Month × Fuel type) × Record count,
    filtered to Autoveturë (passenger cars), date range year_from–year_to."""
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
                "filters": [{
                    "filterInfo": {
                        "type":        "INCLUDE",
                        "operand":     "EQUALS",
                        "expressions": [VEHICLE_FILTER_VALUE],
                        "fieldName":   F_VEHICLE_TYPE,
                    }
                }],
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


# ── Session via headless browser ──────────────────────────────────────────────

def _fetch_with_browser_session(year_from: int, year_to: int) -> dict:
    """Load the public Looker report in headless Chromium, capture the XSRF
    token + cookies from the first batchedDataV2 request the page makes, then
    replay those credentials with our custom (month × fuel) payload."""
    from playwright.sync_api import sync_playwright

    intercepted: dict = {}   # headers from the first outgoing batchedDataV2

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            locale="en-US",
            timezone_id="Europe/Vienna",
            viewport={"width": 1600, "height": 1200},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        def on_request(request):
            if "batchedDataV2" in request.url and not intercepted:
                intercepted["headers"] = dict(request.headers)
                intercepted["url"]     = request.url

        page.on("request", on_request)

        print(f"[albania] browser → {REPORT_PAGE_URL}")
        page.goto(REPORT_PAGE_URL, wait_until="domcontentloaded", timeout=90_000)

        # Wait up to 30 s for the first batchedDataV2 request
        for _ in range(30):
            if intercepted:
                break
            page.wait_for_timeout(1_000)

        if not intercepted:
            page.mouse.wheel(0, 2000)
            page.wait_for_timeout(5_000)

        cookies_raw = context.cookies()
        browser.close()

    if not intercepted:
        raise RuntimeError(
            "No batchedDataV2 request seen during page load — "
            "the report URL may have changed or Google blocked the browser. "
            "Check docs/architecture/27-source-albania.md §8."
        )

    hdrs = intercepted["headers"]
    xsrf = hdrs.get("x-rap-xsrf-token", "")
    if DEBUG:
        print(f"[albania][debug] intercepted XSRF: {xsrf[:20] if xsrf else '(none)'}...")
        print(f"[albania][debug] cookies from context: "
              f"{[c['name'] for c in cookies_raw]}")

    # Re-assemble cookie header for datastudio / lookerstudio domains
    cookie_str = "; ".join(
        f"{c['name']}={c['value']}" for c in cookies_raw
        if any(d in c.get("domain", "")
               for d in ("google.com", "lookerstudio.google.com",
                         "datastudio.google.com"))
    )

    # Use the intercepted URL's appVersion to stay in sync
    api_url = intercepted.get("url", API_URL_TEMPLATE.format("20260607_0101"))

    payload = _build_payload(year_from, year_to)

    post_headers = {
        "content-type":    "application/json",
        "accept":          "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.9",
        "cache-control":   "no-cache",
        "origin":          "https://lookerstudio.google.com",
        "referer":         REPORT_PAGE_URL,
        "cookie":          cookie_str,
    }
    if xsrf:
        post_headers["x-rap-xsrf-token"] = xsrf

    if DEBUG:
        print(f"[albania][debug] POST payload (first 1000 chars):")
        print(json.dumps(payload, ensure_ascii=False)[:1000])

    print(f"[albania] POST {api_url}")
    resp = requests.post(api_url, json=payload, headers=post_headers, timeout=120)
    print(f"[albania] HTTP {resp.status_code} ({len(resp.content)} bytes)")
    resp.raise_for_status()

    text = resp.text
    if text.startswith(")]}'"):
        text = text[4:].lstrip("\n")

    if DEBUG:
        print(f"[albania][debug] raw response body (first 3000 chars):")
        print(text[:3000])

    return json.loads(text)


# ── Response parsing ─────────────────────────────────────────────────────────

def _parse_response(data: dict) -> dict:
    """Parse batchedDataV2 JSON → {(period, VARIANT): gallery_row_dict}."""
    rows: dict = {}

    for dr in data.get("dataResponse", []):
        err = dr.get("errorStatus")
        if err:
            print(f"[albania] API error: code={err.get('code')} "
                  f"reason={err.get('reasonStr')} "
                  f"category={err.get('errorCategoryStr')}")
            continue

        for subset in dr.get("dataSubset", []):
            tds = subset.get("dataset", {}).get("tableDataset", {})
            cols = tds.get("column", [])
            size = tds.get("size", 0)

            if len(cols) < 3 or size == 0:
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

            if DEBUG:
                col_info = tds.get("columnInfo", [])
                names = [c.get("name") for c in col_info]
                print(f"[albania][debug] table: size={size} cols={names}")
                print(f"[albania][debug]   dates[:3]={dates[:3]}")
                print(f"[albania][debug]   fuels[:3]={fuels[:3]}")
                print(f"[albania][debug]   counts[:3]={counts[:3]}")

            for i in range(size):
                if i in null_date or i in null_fuel:
                    continue
                period = _parse_period(dates[i] if i < len(dates) else "")
                if not period:
                    if DEBUG:
                        print(f"[albania][debug]   unparseable date {dates[i]!r}, skip")
                    continue

                fuel  = fuels[i] if i < len(fuels) else ""
                count = int(counts[i]) if (i not in null_count and
                                           i < len(counts)) else 0
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
                        "TOTAL":  0.0, "notes":  "",
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

def upsert_csv(csv_path: str, new_rows: dict, since: str | None) -> tuple[int, int]:
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
                    help="First calendar year to request (default: current year).")
    ap.add_argument("--year-to", type=int, default=datetime.now().year,
                    help="Last calendar year to request (default: current year).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch and parse; print monthly totals; do not write CSV.")
    ap.add_argument("--force", action="store_true",
                    help="Accepted for parity (commit-gated downstream).")
    args = ap.parse_args()

    data = _fetch_with_browser_session(args.year_from, args.year_to)
    rows = _parse_response(data)

    if not rows:
        print("[albania] no data rows parsed — the report may not yet have "
              "data for the requested year, or an API field ID / revisionNumber "
              "may need updating. See docs/architecture/27-source-albania.md §8.",
              file=sys.stderr)
        sys.exit(1)

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
