#!/usr/bin/env python3
"""
Fetch Albania monthly vehicle-registration data directly from DPSHTRR's public
Looker Studio report and upsert ``data/Albania.csv``.

Usage
-----
    python scripts/fetch_albania.py [--dry-run] [--since YYYY-MM]

Primary source
--------------
Albania's General Directorate of Road Transport Services (DPSHTRR) publishes
vehicle-registration data **only** through a public Looker Studio report:

    https://www.dpshtrr.al/open-data-dpshtrr-english
    https://datastudio.google.com/reporting/407ce08b-d3ce-478e-9bc7-a50125f875f3/page/VPWqB

There is no raw CSV/XLSX export and the dpshtrr.al site blocks automated
clients (403).  The Looker ``batchedDataV2`` JSON API that backs the report
rejects anonymous plain-HTTP requests with an ``ACCESS / PREFETCH_VALIDATION``
error — the data is gated behind a session that Google's front-end JavaScript
establishes in a real browser.

We therefore drive a **headless Chromium (Playwright)**: it loads the public
report exactly as a human visitor would, Google sets up the session, and we
**intercept** the ``batchedDataV2`` responses the report itself issues.  This
means we do *not* hand-craft the query (no field IDs, no revisionNumber, no
componentId to keep in sync) — we read whatever the report's own table returns
and pick out the (Month, Fuel type, Record count) figures for passenger cars
(``Autoveturë``).

Note: DPSHTRR publish a fresh Looker report each calendar year (the current one
is titled "year 2026").  Historical data (pre-2026) lives in the bootstrapped
CSV rows and is not re-fetched.  When a new year starts, update ``REPORT_ID`` /
``PAGE_ID_URL`` below.  See docs/architecture/27-source-albania.md for the full
source playbook.

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
from datetime import datetime
from pathlib import Path

DEBUG = os.environ.get("ALBANIA_DEBUG") == "1"

# ── Looker Studio report constants ──────────────────────────────────────────
REPORT_ID   = "407ce08b-d3ce-478e-9bc7-a50125f875f3"
PAGE_ID_URL = "VPWqB"      # "Vehicles by type of fuel or power source"

REPORT_PAGE_URL = (
    f"https://lookerstudio.google.com/reporting/{REPORT_ID}/page/{PAGE_ID_URL}"
    f"?s=ntCeOqOLBog"
)

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

# All fuel labels we expect — used to recognise the "fuel" column heuristically.
_ALL_FUEL = _BEV | _PHEV | _HEV | _PET | _DIE

# Known vehicle-type labels — used to recognise the "vehicle type" column.
_VEHICLE_TYPES = {
    "Autoveturë", "Motoçikletë", "Kamion", "Autobus", "Rimorkio",
    "Gjysmërimorkio", "Traktor", "Mjet pune", "Autoveture",
}


def _fuel_col(fuel: str) -> str:
    if fuel in _BEV:  return "BEV"
    if fuel in _PHEV: return "PHEV"
    if fuel in _HEV:  return "HEV"
    if fuel in _PET:  return "PETROL"
    if fuel in _DIE:  return "DIESEL"
    return "OTHERS"


# ── Date-string parsing ──────────────────────────────────────────────────────
# Looker returns dates in various locale-dependent string formats.
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
_RE_ISO = re.compile(r'^(\d{4})-(\d{2})(?:-\d{2})?$')   # 2026-01-01 or 2026-01
_RE_YMD = re.compile(r'^(\d{4})(\d{2})\d{2}$')          # 20260101
_RE_YM  = re.compile(r'^(\d{4})(\d{2})$')               # 202601


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


# ── Headless-browser fetch (Playwright) ──────────────────────────────────────

def fetch_via_browser(report_url: str) -> list[dict]:
    """Load the public report in headless Chromium and capture every
    ``batchedDataV2`` response body it issues.  Returns the parsed JSON dicts."""
    from playwright.sync_api import sync_playwright

    captured: list[dict] = []

    def _decode(body: bytes) -> dict | None:
        try:
            text = body.decode("utf-8", "replace")
        except Exception:
            return None
        if text.startswith(")]}'"):
            text = text[4:].lstrip("\n")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

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

        def on_response(response):
            if "batchedDataV2" not in response.url:
                return
            try:
                body = response.body()
            except Exception:
                return
            data = _decode(body)
            if data is None:
                if DEBUG:
                    print(f"[albania][debug] batchedDataV2 response "
                          f"({len(body)} bytes) — could not decode JSON")
                return
            captured.append(data)
            if DEBUG:
                print(f"[albania][debug] captured batchedDataV2 response "
                      f"#{len(captured)} ({len(body)} bytes)")

        page.on("response", on_response)

        print(f"[albania] browser → {report_url}")
        page.goto(report_url, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(5_000)

        # Looker lazy-loads components as they scroll into view, so walk the
        # whole page to trigger every chart's batchedDataV2 request.
        for _ in range(14):
            page.mouse.wheel(0, 1400)
            page.wait_for_timeout(1_500)
        page.keyboard.press("End")
        page.wait_for_timeout(2_000)

        # Settle: wait until no new responses arrive for ~6s (cap ~40s).
        last, stable = len(captured), 0
        for _ in range(20):
            page.wait_for_timeout(2_000)
            if len(captured) == last:
                stable += 1
                if stable >= 3 and last > 0:
                    break
            else:
                last, stable = len(captured), 0

        if DEBUG:
            print(f"[albania][debug] final page url: {page.url}")
        browser.close()

    print(f"[albania] captured {len(captured)} batchedDataV2 response(s)")
    if DEBUG:
        for i, data in enumerate(captured, 1):
            blob = json.dumps(data, ensure_ascii=False)
            print(f"[albania][debug] ===== response #{i} raw ({len(blob)} chars) =====")
            print(blob[:8000])
    return captured


def _has_table_rows(captured: list[dict]) -> bool:
    for data in captured:
        for dr in data.get("dataResponse", []):
            for subset in dr.get("dataSubset", []):
                tds = subset.get("dataset", {}).get("tableDataset", {})
                if tds.get("size", 0):
                    return True
    return False


# ── Response parsing ─────────────────────────────────────────────────────────

def _col_values(col: dict) -> tuple[str, list]:
    """Return (kind, values) for a batchedDataV2 column."""
    if "stringColumn" in col:
        return "string", col["stringColumn"].get("values", [])
    if "longColumn" in col:
        return "long", col["longColumn"].get("values", [])
    if "doubleColumn" in col:
        return "double", col["doubleColumn"].get("values", [])
    if "nullIndex" in col and not (set(col) - {"nullIndex"}):
        return "null", []
    return "other", []


def _classify_columns(parsed):
    """Given a list of (kind, values, nulls) tuples, return indices for
    (date_idx, fuel_idx, count_idx, vehicle_idx) — any may be None."""
    date_idx = fuel_idx = count_idx = vehicle_idx = None

    for i, (kind, vals, _nulls) in enumerate(parsed):
        sample = [v for v in vals[:50] if v not in (None, "")]
        if kind == "string":
            # vehicle-type column?
            if vehicle_idx is None and any(v in _VEHICLE_TYPES for v in sample):
                vehicle_idx = i
                continue
            # fuel column?
            if fuel_idx is None and any(v in _ALL_FUEL for v in sample):
                fuel_idx = i
                continue
            # date column?
            if date_idx is None and sample and \
               sum(_parse_period(v) is not None for v in sample) >= max(1, len(sample) // 2):
                date_idx = i
                continue
        elif kind in ("long", "double"):
            if count_idx is None:
                count_idx = i

    return date_idx, fuel_idx, count_idx, vehicle_idx


def parse_captured(captured: list[dict]) -> dict:
    """Walk every captured batchedDataV2 response, find the table that carries
    (Month, Fuel, Count) for passenger cars, and aggregate into gallery rows."""
    rows: dict = {}
    seen_any_table = False

    for data in captured:
        # Surface explicit Looker access/validation errors for diagnosis.
        for dr in data.get("dataResponse", []):
            err = dr.get("errorStatus")
            if err and DEBUG:
                print(f"[albania][debug] errorStatus: {json.dumps(err)}")

            for subset in dr.get("dataSubset", []):
                tds = subset.get("dataset", {}).get("tableDataset", {})
                cols = tds.get("column", [])
                size = tds.get("size", 0)
                if not cols or not size:
                    continue
                seen_any_table = True

                parsed = []
                for c in cols:
                    kind, vals = _col_values(c)
                    parsed.append((kind, vals, set(c.get("nullIndex", []))))

                date_idx, fuel_idx, count_idx, vehicle_idx = _classify_columns(parsed)

                if DEBUG:
                    info = tds.get("columnInfo", [])
                    names = [ci.get("name") for ci in info]
                    kinds = [k for k, _v, _n in parsed]
                    print(f"[albania][debug] table size={size} "
                          f"names={names} kinds={kinds} "
                          f"→ date={date_idx} fuel={fuel_idx} "
                          f"count={count_idx} vehicle={vehicle_idx}")
                    for j, (k, v, _n) in enumerate(parsed):
                        print(f"[albania][debug]   col{j} {k}: {v[:6]}")

                if date_idx is None or fuel_idx is None or count_idx is None:
                    continue   # not the table we want

                dkind, dates, dnull = parsed[date_idx]
                fkind, fuels, fnull = parsed[fuel_idx]
                ckind, counts, cnull = parsed[count_idx]
                if vehicle_idx is not None:
                    _vk, vehicles, vnull = parsed[vehicle_idx]
                else:
                    vehicles, vnull = None, set()

                for i in range(size):
                    if i in dnull or i in fnull:
                        continue
                    if vehicles is not None:
                        if i in vnull or i >= len(vehicles):
                            continue
                        if vehicles[i] != VEHICLE_FILTER_VALUE:
                            continue
                    if i >= len(dates) or i >= len(fuels):
                        continue
                    period = _parse_period(dates[i])
                    if not period:
                        continue
                    fuel = fuels[i]
                    count = 0
                    if i not in cnull and i < len(counts):
                        try:
                            count = int(float(counts[i]))
                        except (TypeError, ValueError):
                            count = 0

                    col = _fuel_col(fuel)
                    key = (period, VARIANT)
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

    if not seen_any_table:
        print("[albania] no table data in any captured response.")

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
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch and parse; print monthly totals; do not write CSV.")
    ap.add_argument("--force", action="store_true",
                    help="Accepted for parity (commit-gated downstream).")
    # Accepted for backward-compat with the workflow; ignored under interception.
    ap.add_argument("--year-from", type=int, default=None, help=argparse.SUPPRESS)
    ap.add_argument("--year-to", type=int, default=None, help=argparse.SUPPRESS)
    args = ap.parse_args()

    captured = fetch_via_browser(REPORT_PAGE_URL)
    rows = parse_captured(captured)

    if not rows:
        print("[albania] no data rows parsed — the report layout or share "
              "token may have changed, or this year's report is not yet "
              "published. Historical rows are kept from the existing CSV.",
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
