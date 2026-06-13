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
vehicle-registration data **only** through a public Looker Studio report (Shqip
version):

    https://lookerstudio.google.com/reporting/233df2cc-6bd4-45fc-bf9b-e8ee4f83293e/page/VPWqB

The report's ``batchedDataV2`` API rejects anonymous plain-HTTP clients with
``ACCESS / PREFETCH_VALIDATION`` and also rejects any custom payload whose
query fingerprint was not pre-registered by the page during load
(``PREFETCH_VALIDATION``).  Custom queries are fundamentally impossible.

We therefore:
  1. Drive a **headless Chromium (Playwright)** to load the Albanian DPSHTRR
     report page, which lets Google establish the session and fires the page's
     OWN batchedDataV2 requests.
  2. **Intercept** (route.fetch → forward unchanged, record response) every
     batchedDataV2 request that targets datasource ``013d0728-…``.
  3. **Iterate the Muaji (Month) filter**: click each month option in the
     dropdown, wait for the updated batchedDataV2 response, and record the
     (period, response) pair.
  4. **Parse** each captured response: vehicle_type × fuel_type × count flat
     table; keep only ``Autoveturë`` rows; aggregate by fuel type.

Note: the English DPSHTRR report (407ce08b-…) cannot be used — its
batchedDataV2 responses fail with SNAPSHOT_WITH_NON_REAGGREGATABLE because the
component body sets ``createSnapshot:true``.  The Albanian report (233df2cc-…)
does NOT set that flag and works correctly.

Note: DPSHTRR publishes a fresh Looker report each calendar year ("year 2026").
Historical data (pre-2026) lives in the bootstrapped CSV rows.  When a new year
starts, update ``REPORT_ID`` / ``REVISION_NUMBER`` below.
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
from datetime import datetime
from pathlib import Path

DEBUG = os.environ.get("ALBANIA_DEBUG") == "1"

# ── Looker Studio report constants ──────────────────────────────────────────
# Albanian report (Shqip) at dpshtrr.al — "Mjete sipas Lëndës Djegëse" page.
# Unlike the English report, this one does NOT use createSnapshot:true, so
# batchedDataV2 responses succeed without SNAPSHOT_WITH_NON_REAGGREGATABLE.
# The Muaji (Month) dimension filter lets us iterate month-by-month.
REPORT_ID       = "233df2cc-6bd4-45fc-bf9b-e8ee4f83293e"
PAGE_ID_URL     = "VPWqB"      # "Mjete sipas Lëndës Djegëse"
PAGE_ID_NUM     = "24871631"   # numeric pageId in batchedDataV2 body
COMPONENT_ID    = "cd-p9hqinijec"
DATASOURCE_ID   = "013d0728-f5d3-4599-8899-cfb3f02fa77e"
REVISION_NUMBER = 16

# Internal field IDs (reverse-engineered 2026-06-13; bump REVISION_NUMBER if
# DPSHTRR updates their data source and the workflow starts returning empty data)
F_VEHICLE_TYPE = "_73515086_"
F_FUEL_TYPE    = "_818800577_"
F_RECORD_COUNT = "datastudio_record_count_system_field_id_98323387"
F_DATE         = "_3076010_"

# Direct URL — no sharing token needed for the Albanian public report
REPORT_PAGE_URL = (
    f"https://lookerstudio.google.com/reporting/{REPORT_ID}/page/{PAGE_ID_URL}"
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

def _fuel_col(fuel: str) -> str:
    if fuel in _BEV:  return "BEV"
    if fuel in _PHEV: return "PHEV"
    if fuel in _HEV:  return "HEV"
    if fuel in _PET:  return "PETROL"
    if fuel in _DIE:  return "DIESEL"
    return "OTHERS"


# ── Known vehicle types (used for column-type detection) ─────────────────────
_VEHICLE_TYPE_HINTS = {
    "Autoveturë", "Kamion", "Autobus", "Motoçikletë", "Rimorkio",
    "Traktor", "Çikëlomotor", "Miniautobuz",
}
# Known fuel types (used for column-type detection)
_FUEL_TYPE_HINTS = {
    "Elektrik", "Benzinë", "Naftë", "Hybrid Benzinë/Elektrik",
    "Hybrid Naftë/Elektrik", "Hybrid plug-in, Benzinë/Elektrik",
    "Hybrid plug-in, Naftë/Elektrik", "Hybrid Benzinë/Gaz/Elektrik",
}


# ── Session via headless browser ──────────────────────────────────────────────

def _fetch_with_browser_session(year_from: int, year_to: int) -> list[tuple[str, dict]]:
    """
    Load the Albanian DPSHTRR Looker Studio report in headless Chromium,
    intercept every batchedDataV2 response on datasource ``DATASOURCE_ID``,
    and iterate the Muaji (Month) filter to collect per-month data.

    Returns a list of ``(period, merged_data_dict)`` pairs, where
    ``period`` is YYYY-MM and ``merged_data_dict`` is a batchedDataV2
    response JSON object (with ``dataResponse`` list) collected while
    that month's filter was active.

    Falls back to returning the initial YTD aggregate (assigned to the
    current calendar month) when the Muaji filter cannot be located.
    """
    from playwright.sync_api import sync_playwright
    import time as _time

    captured: list[dict] = []
    capture_error: list[Exception | None] = [None]

    _re_datasource = re.compile(r'"datasourceId":"([^"]+)"')
    _re_component  = re.compile(r'"componentId":"([^"]+)"')
    _re_display    = re.compile(r'"displayType":"([^"]+)"')

    def handle_route(route):
        req = route.request
        if "batchedDataV2" not in req.url:
            try:
                route.continue_()
            except Exception:
                pass
            return

        body = req.post_data or ""
        m_ds   = _re_datasource.search(body)
        m_comp = _re_component.search(body)
        m_disp = _re_display.search(body)
        datasource  = m_ds.group(1)   if m_ds   else ""
        component   = m_comp.group(1) if m_comp else ""
        displaytype = m_disp.group(1) if m_disp else ""

        try:
            resp = route.fetch()
            text = resp.text()
            if datasource == DATASOURCE_ID:
                captured.append({
                    "component":    component,
                    "displayType":  displaytype,
                    "datasourceId": datasource,
                    "body":         body,
                    "text":         text,
                })
                if DEBUG:
                    print(f"[albania][debug] captured component={component} "
                          f"displayType={displaytype} body_len={len(body)} "
                          f"resp_len={len(text)}")
            route.fulfill(response=resp)
        except Exception as exc:
            capture_error[0] = exc
            try:
                route.continue_()
            except Exception:
                pass

    def _merge_slice(start_idx: int) -> dict:
        """Merge captured[start_idx:] into one dataResponse dict."""
        merged: dict = {"dataResponse": []}
        for cap in captured[start_idx:]:
            text = cap["text"]
            if text.startswith(")]}'"):
                text = text[4:].lstrip("\n")
            try:
                obj = json.loads(text)
            except Exception:
                continue
            merged["dataResponse"].extend(obj.get("dataResponse", []))
        return merged

    result_pairs: list[tuple[str, dict]] = []

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
        page.route("**/*", handle_route)

        # Phase 1: direct navigation to Albanian report page
        print(f"[albania] browser → {REPORT_PAGE_URL}")
        page.goto(REPORT_PAGE_URL, wait_until="load", timeout=90_000)

        if DEBUG:
            print(f"[albania][debug] phase-1 landed: {page.url}")
            cookies = context.cookies()
            print(f"[albania][debug] cookies: {[c['name'] for c in cookies]}")

        # Phase 2: navigate to datastudio.google.com domain if still on
        # lookerstudio.google.com (redirect may not happen automatically)
        current_url = page.url
        if PAGE_ID_URL not in current_url:
            direct_url = (
                f"https://datastudio.google.com/reporting/{REPORT_ID}"
                f"/page/{PAGE_ID_URL}"
            )
            print(f"[albania] phase-2 → {direct_url}")
            page.goto(direct_url, wait_until="domcontentloaded", timeout=60_000)
            if DEBUG:
                print(f"[albania][debug] phase-2 landed: {page.url}")

        # Wait for initial page load + batchedDataV2 responses
        print("[albania] waiting 35s for initial load…")
        initial_start = len(captured)
        deadline = _time.time() + 35
        while _time.time() < deadline:
            page.wait_for_timeout(500)

        initial_end = len(captured)
        print(f"[albania] initial capture: {initial_end - initial_start} "
              f"responses on {DATASOURCE_ID}")

        if DEBUG:
            print(f"[albania][debug] page title: {page.title()!r}")
            print(f"[albania][debug] page url:   {page.url!r}")
            try:
                page.screenshot(path="/tmp/albania_initial.png")
                print("[albania][debug] screenshot → /tmp/albania_initial.png")
            except Exception:
                pass
            for idx, cap in enumerate(captured):
                print(f"[albania][debug] capture #{idx}: "
                      f"component={cap['component']} "
                      f"displayType={cap['displayType']} "
                      f"body_len={len(cap['body'])} "
                      f"resp_len={len(cap['text'])}")
                print(f"[albania][debug]   resp[:2000]: {cap['text'][:2000]!r}")

        # ── Muaji (Month) filter iteration ────────────────────────────────────
        #
        # The Muaji control is a Looker "list" filter.  Clicking its title opens a
        # popup (CANVAS-CONTROL-EDITOR) whose rows are labelled "<Mon> <YYYY>" in
        # the browser locale (en-US → "Jan 2026", "Feb 2026", … "May 2026"), each
        # with an "only" single-select link and a Record Count.
        #
        # We select one month at a time using the row's "only" link (single-select,
        # so no need to clear a previous selection), then wait for cd-p9hqinijec to
        # re-fire with that month's vehicle×fuel×count data.
        #
        # Clicking is done with force=True: the option text resolves to an element
        # behind the .popup-backdrop, which otherwise makes Playwright report
        # "popup-backdrop intercepts pointer events".  force=True skips that
        # actionability check (we know the element is the intended target).

        # English abbreviated month labels as rendered by the en-US canvas control.
        _MONTH_ABBR = [
            ("Jan", "01"), ("Feb", "02"), ("Mar", "03"), ("Apr", "04"),
            ("May", "05"), ("Jun", "06"), ("Jul", "07"), ("Aug", "08"),
            ("Sep", "09"), ("Oct", "10"), ("Nov", "11"), ("Dec", "12"),
        ]

        def _open_muaji() -> bool:
            """Click the Muaji control title to open its month-list popup."""
            for selector in (
                "text=Muaji",
                "[aria-label*='Muaji']",
                "[title*='Muaji']",
            ):
                try:
                    el = page.locator(selector).first
                    if el.is_visible(timeout=2000):
                        el.click(timeout=5000)
                        page.wait_for_timeout(1500)
                        if DEBUG:
                            print(f"[albania][debug] opened Muaji via {selector!r}")
                        return True
                except Exception:
                    pass
            return False

        for year in range(year_from, year_to + 1):
            months_to_try = [
                (f"{abbr} {year}", f"{year}-{num}") for abbr, num in _MONTH_ABBR
            ]

            if not _open_muaji():
                if DEBUG:
                    print("[albania][debug] Muaji control not found")
                    try:
                        page.screenshot(path="/tmp/albania_no_muaji.png")
                    except Exception:
                        pass
                ytd = _merge_slice(initial_start)
                if ytd["dataResponse"]:
                    fallback_period = datetime.now().strftime("%Y-%m")
                    result_pairs.append((fallback_period, ytd))
                    print(f"[albania] WARNING: Muaji control not found; "
                          f"using YTD data as period={fallback_period}")
                continue

            if DEBUG:
                # Dump the Muaji popup's clickable month rows so we can see the
                # exact markup (tag/class/role/text) and refine selectors.
                try:
                    rows = page.evaluate(r"""
                        () => {
                            const out = [];
                            const re = /\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+20\d\d\b/;
                            const all = document.querySelectorAll(
                                'canvas-control-editor *, .popup-backdrop ~ * *'
                            );
                            for (const e of all) {
                                if (e.closest('svg')) continue;
                                const own = Array.from(e.childNodes)
                                    .filter(n => n.nodeType === 3)
                                    .map(n => n.textContent).join('').trim();
                                if (re.test(own)) {
                                    out.push({
                                        tag: e.tagName,
                                        cls: (e.className||'').toString().substring(0,60),
                                        role: e.getAttribute('role') || '',
                                        text: own.substring(0, 40)
                                    });
                                }
                                if (out.length >= 25) break;
                            }
                            return JSON.stringify(out);
                        }
                    """)
                    print(f"[albania][debug] muaji rows: {rows[:2000]}")
                except Exception as exc:
                    print(f"[albania][debug] muaji row dump failed: {exc}")
                try:
                    page.screenshot(path="/tmp/albania_muaji_open.png")
                except Exception:
                    pass

            months_found = 0

            for month_label, period in months_to_try:
                cap_before = len(captured)

                # Make sure the popup is open before each selection.
                if month_label != months_to_try[0][0]:
                    if not _open_muaji():
                        if DEBUG:
                            print("[albania][debug] could not re-open Muaji popup")
                        break

                # Try to click the month row.  Prefer the row's "only" link
                # (single-select); fall back to the row label itself.
                clicked = False
                for target in (
                    page.get_by_text(month_label, exact=True),
                    page.get_by_text(month_label, exact=False),
                ):
                    try:
                        loc = target.first
                        if loc.count() == 0:
                            continue
                        loc.click(timeout=3000, force=True)
                        clicked = True
                        break
                    except Exception as exc:
                        if DEBUG:
                            print(f"[albania][debug] click {month_label!r} "
                                  f"failed: {str(exc)[:120]}")

                if not clicked:
                    if DEBUG:
                        print(f"[albania][debug] {month_label!r} not clickable")
                    continue

                # Wait up to 15 s for a fresh batchedDataV2 response.
                got_data = False
                wait_deadline = _time.time() + 15
                while _time.time() < wait_deadline:
                    page.wait_for_timeout(500)
                    if len(captured) > cap_before:
                        page.wait_for_timeout(2000)   # let batch complete
                        got_data = True
                        break

                if got_data:
                    merged = _merge_slice(cap_before)
                    result_pairs.append((period, merged))
                    months_found += 1
                    print(f"[albania] month {month_label} → {period} "
                          f"({len(captured) - cap_before} new responses)")
                elif DEBUG:
                    print(f"[albania][debug] no data after clicking {month_label!r}")

            if months_found == 0:
                if DEBUG:
                    print("[albania][debug] no month options clicked; YTD fallback")
                    try:
                        page.screenshot(path="/tmp/albania_no_months.png")
                    except Exception:
                        pass
                ytd = _merge_slice(initial_start)
                if ytd["dataResponse"]:
                    fallback_period = datetime.now().strftime("%Y-%m")
                    result_pairs.append((fallback_period, ytd))
                    print(f"[albania] WARNING: no month options clicked; "
                          f"using YTD data as period={fallback_period}")
            else:
                print(f"[albania] month iteration: {months_found} months for {year}")

        try:
            page.unroute("**/*", handle_route)
        except Exception:
            pass
        browser.close()

    if capture_error[0]:
        print(f"[albania] WARNING route.fetch() error: {capture_error[0]}")

    print(f"[albania] captured {len(captured)} total batchedDataV2 responses "
          f"on {DATASOURCE_ID}")

    if not result_pairs:
        raise RuntimeError(
            "[albania] no data collected — page may not have loaded correctly, "
            f"or datasource {DATASOURCE_ID} is not reachable from this network"
        )

    return result_pairs


# ── Response parsing ─────────────────────────────────────────────────────────

def _parse_response(data: dict, period: str) -> dict:
    """Parse a single batchedDataV2 response captured while month ``period``
    was active in the Muaji filter.

    The Albanian cd-p9hqinijec 'main' sub-response returns a flat table:
        vehicle_type (string) × fuel_type (string) × count (long)

    Column order is not fixed — we detect each column by sampling its string
    values against known vehicle / fuel type sets.  Only rows where
    vehicle_type == ``VEHICLE_FILTER_VALUE`` (Autoveturë) are kept.
    """
    rows: dict = {}

    for dr in data.get("dataResponse", []):
        err = dr.get("errorStatus")
        if err:
            code    = err.get("code", "?")
            reason  = err.get("reasonStr", "?")
            cat     = err.get("errorCategoryStr", "?")
            print(f"[albania] API error: code={code} reason={reason} "
                  f"category={cat}")
            continue

        for subset in dr.get("dataSubset", []):
            tds  = subset.get("dataset", {}).get("tableDataset", {})
            cols = tds.get("column", [])
            size = tds.get("size", 0)

            if size == 0 or len(cols) < 2:
                continue

            # ── Detect column roles by sampling values ──────────────────────
            vehicle_idx = None
            fuel_idx    = None
            count_idx   = None

            for idx, col in enumerate(cols):
                str_vals = col.get("stringColumn", {}).get("values", [])
                lng_vals = col.get("longColumn",   {}).get("values", [])

                if lng_vals and count_idx is None:
                    count_idx = idx
                    continue

                sample = set(str_vals[:20])
                if sample & _VEHICLE_TYPE_HINTS and vehicle_idx is None:
                    vehicle_idx = idx
                elif sample & _FUEL_TYPE_HINTS and fuel_idx is None:
                    fuel_idx = idx

            if DEBUG:
                col_info = tds.get("columnInfo", [])
                names = [c.get("name") for c in col_info]
                print(f"[albania][debug] subset size={size} cols={names} "
                      f"vehicle_idx={vehicle_idx} fuel_idx={fuel_idx} "
                      f"count_idx={count_idx}")

            if vehicle_idx is None or fuel_idx is None or count_idx is None:
                if DEBUG:
                    print("[albania][debug]   skipped (column roles not detected)")
                continue

            vehicle_vals = cols[vehicle_idx].get("stringColumn", {}).get("values", [])
            fuel_vals    = cols[fuel_idx   ].get("stringColumn", {}).get("values", [])
            count_vals   = cols[count_idx  ].get("longColumn",   {}).get("values", [])

            null_vehicle = set(cols[vehicle_idx].get("nullIndex", []))
            null_fuel    = set(cols[fuel_idx   ].get("nullIndex", []))
            null_count   = set(cols[count_idx  ].get("nullIndex", []))

            for i in range(size):
                if i in null_vehicle or i in null_fuel:
                    continue
                vehicle = vehicle_vals[i] if i < len(vehicle_vals) else ""
                if vehicle != VEHICLE_FILTER_VALUE:
                    continue

                fuel  = fuel_vals[i] if i < len(fuel_vals) else ""
                count = (int(count_vals[i])
                         if (i not in null_count and i < len(count_vals))
                         else 0)
                col_name = _fuel_col(fuel)
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
                rows[key][col_name] = rows[key].get(col_name, 0.0) + count

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

    month_pairs = _fetch_with_browser_session(args.year_from, args.year_to)

    rows: dict = {}
    for period, data in month_pairs:
        period_rows = _parse_response(data, period)
        rows.update(period_rows)

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
