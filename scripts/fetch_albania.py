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
     batchedDataV2 request that targets datasource ``013d0728-…``.  The page's
     cd-p9hqinijec component returns a vehicle_type × fuel_type × count table
     for whatever the Muaji (Month) filter currently has selected.
  3. **Drive the Muaji filter by differencing.**  The Muaji control is a
     multi-select checkbox list with every month selected by default (so the
     initial load is the year-to-date total = our *baseline*).  Its per-row
     "only" single-select link is display:none until a real CSS :hover and
     cannot be force-clicked, so instead we toggle each month OFF one at a time
     in DESCENDING order (latest → earliest), capturing the report after each
     toggle.  Each capture is the *complement* (sum of the months still selected):
         after toggling m_i off →  A_i = sum(months < m_i)
     The true single-month value is the telescoping difference
         m_i = A_{i-1} − A_i,   with A_0 = baseline, A_last = 0
     computed per fuel column (see ``_difference_to_rows``).
     Descending order is intentional: it avoids a Looker Studio pivot label
     inconsistency where fuel-type strings differ across window sizes (e.g.
     "Hybrid Benzinë/Elektrik" present in Jan-May but absent in Feb-May,
     replaced by "Hybrid plug-in, Benzinë/Elektrik"), which causes negative
     per-fuel diffs that get clipped to 0 and corrupt monthly TOTALS.
  4. **Parse** each captured response: vehicle_type × fuel_type × count flat
     table; keep only ``Autoveturë`` rows; aggregate by fuel type.

This was cross-checked against an authoritative monthly car-sales reference:
the differenced 2026 months (Jan 5673, Feb 5905, Mar 6103, Apr 6732, May 6358)
matched it exactly, confirming the toggle semantics and the fuel mapping.

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

        # ── Muaji (Month) filter: collect baseline + per-month complements ──────
        #
        # The Muaji control is an AngularJS Material *multi-select* checkbox list
        # (class "item item-multi selected"; md-checkbox ng-click="toggleItem")
        # with EVERY month selected by default.  A plain row click toggles ONE
        # month OFF.  The per-row "only" single-select link is display:none until a
        # real CSS :hover and cannot be force-clicked (dispatchEvent can't trigger
        # :hover), so single-selecting a month directly is not possible.
        #
        # Instead we read the months from the popup and toggle them OFF one at a
        # time in DESCENDING order (latest→earliest), capturing the report's
        # vehicle×fuel×count after each toggle.  Each capture is the COMPLEMENT
        # (months still selected):
        #     after toggling m_i off →  A_i = sum(months < m_i)
        # True single-month values are recovered by differencing in
        # _difference_to_rows:  m_i = A_{i-1} − A_i, with A_0 = baseline (all on).
        # Descending avoids fuel-label inconsistencies in DPSHTRR's Looker pivot
        # that corrupt TOTALS when computed as large-minus-large-window diffs.
        #
        # Toggling uses Playwright force-click on the visible "<Mon> <YYYY>" label
        # (proven to fire batchedDataV2; force bypasses the ".popup-backdrop
        # intercepts pointer events" actionability error).

        _MONTH_NUM = {
            "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
            "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
            "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
        }

        def _open_muaji() -> bool:
            """Click the Muaji control title to open its month-list popup."""
            for selector in ("text=Muaji", "[aria-label*='Muaji']",
                             "[title*='Muaji']"):
                try:
                    el = page.locator(selector).first
                    if el.is_visible(timeout=2000):
                        el.click(timeout=5000)
                        page.wait_for_timeout(1200)
                        return True
                except Exception:
                    pass
            return False

        _JS_MONTH_LABELS = r"""
() => {
    const re = /^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (20\d\d)$/;
    const out = []; const seen = new Set();
    for (const e of document.querySelectorAll('span,div,label')) {
        if (e.closest('svg')) continue;
        const t = e.textContent.trim();
        if (re.test(t) && !seen.has(t)) { seen.add(t); out.push(t); }
    }
    return JSON.stringify(out);
}
"""

        def _label_to_period(label: str) -> str | None:
            try:
                abbr, yr = label.split()
            except ValueError:
                return None
            num = _MONTH_NUM.get(abbr)
            return f"{yr}-{num}" if num else None

        # Baseline = the all-months-selected state from the initial page load.
        baseline_merged = _merge_slice(initial_start)

        if not _open_muaji():
            if DEBUG:
                try:
                    page.screenshot(path="/tmp/albania_no_muaji.png")
                except Exception:
                    pass
            browser.close()
            raise RuntimeError(
                "[albania] Muaji month control not found on the report page")

        try:
            present_labels = json.loads(page.evaluate(_JS_MONTH_LABELS))
        except Exception:
            present_labels = []
        if DEBUG:
            print(f"[albania][debug] present month labels: {present_labels}")

        # Close the Muaji popup before the toggle loop.  _open_muaji() above
        # opened it to make month labels visible for JS eval; if the toggle
        # loop's first _open_muaji() finds it still open, it will CLOSE it
        # (toggle), causing the subsequent month-label click to land on the
        # wrong element (a chart label, not the filter checkbox) → no response.
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(800)
        except Exception:
            pass

        # (label, period) within the requested year range, descending by period.
        present: list[tuple[str, str]] = []
        for lbl in present_labels:
            p = _label_to_period(lbl)
            if p and year_from <= int(p[:4]) <= year_to:
                present.append((lbl, p))
        present.sort(key=lambda x: x[1], reverse=True)  # descending: latest first
        present_periods = [p for _, p in present]
        print(f"[albania] Muaji months present (descending): {present_periods}")

        if not present:
            browser.close()
            raise RuntimeError(
                "[albania] no month labels found in the Muaji popup")

        # Toggle each present month OFF (descending: latest first) and capture the complement.
        complements: list[tuple[str, dict]] = []
        for lbl, period in present:
            if not _open_muaji():
                if DEBUG:
                    print("[albania][debug] could not re-open Muaji popup")
            cap_before = len(captured)
            try:
                page.get_by_text(lbl, exact=True).first.click(
                    timeout=3000, force=True)
            except Exception as exc:
                if DEBUG:
                    print(f"[albania][debug] toggle {lbl!r} failed: "
                          f"{str(exc)[:120]}")
                continue

            # Poll until the cd-p9hqinijec vehicle×fuel×count subset for this
            # complement actually arrives — NOT merely until the first response.
            # The "main" sub-request often lands a few seconds after the row0/
            # barchart responses; recording too early gives an empty parse (the
            # bug that zeroed Jan/Feb in run 22).  After it appears, wait a short
            # settle so any trailing subset is included, then re-check stability.
            got = False
            wait_deadline = _time.time() + 22
            while _time.time() < wait_deadline:
                page.wait_for_timeout(500)
                if len(captured) <= cap_before:
                    continue
                total = sum(_parse_fuel_counts(
                    _merge_slice(cap_before), quiet=True).values())
                if total > 0:
                    page.wait_for_timeout(2500)   # let trailing subsets settle
                    got = True
                    break

            if got:
                complements.append((period, _merge_slice(cap_before)))
                counts = _parse_fuel_counts(_merge_slice(cap_before), quiet=True)
                print(f"[albania] toggled {lbl} off → complement after {period} "
                      f"= {sum(counts.values())} ({len(captured) - cap_before} "
                      f"responses)")
            elif DEBUG:
                # Expected for January (last in descending order): toggling it
                # empties the selection so the report returns no Autoveturë rows.
                print(f"[albania][debug] no vehicle×fuel data after toggling "
                      f"{lbl!r} (expected for January / final toggle)")

        try:
            page.unroute("**/*", handle_route)
        except Exception:
            pass
        browser.close()

    if capture_error[0]:
        print(f"[albania] WARNING route.fetch() error: {capture_error[0]}")

    print(f"[albania] captured {len(captured)} total batchedDataV2 responses on "
          f"{DATASOURCE_ID}; {len(complements)} month complements")

    return {
        "baseline":         baseline_merged,
        "complements":      complements,
        "present_periods":  present_periods,
    }


# ── Response parsing ─────────────────────────────────────────────────────────

def _parse_fuel_counts(data: dict, quiet: bool = False) -> dict:
    """Aggregate Autoveturë (passenger-car) registrations by gallery fuel column
    from the first qualifying vehicle×fuel×count subset of a batchedDataV2
    response.

    The cd-p9hqinijec 'main' sub-response is a flat table whose three columns are
    vehicle_type (string), fuel_type (string) and Record Count (long).  Column
    order is not fixed, so we detect each by sampling values against known
    vehicle / fuel type sets.  Returns ``{col: int}`` over VALUE_COLS (zeros if
    no qualifying subset is found, e.g. an empty or error response).

    ``quiet`` suppresses debug logging — used while polling for the subset's
    arrival so the log isn't spammed.
    """
    counts = {c: 0 for c in VALUE_COLS}

    for dr in data.get("dataResponse", []):
        err = dr.get("errorStatus")
        if err:
            if DEBUG and not quiet:
                print(f"[albania][debug] API error in response: "
                      f"{err.get('reasonStr', '?')}")
            continue

        for subset in dr.get("dataSubset", []):
            tds  = subset.get("dataset", {}).get("tableDataset", {})
            cols = tds.get("column", [])
            size = tds.get("size", 0)
            if size == 0 or len(cols) < 3:
                continue

            vehicle_idx = fuel_idx = count_idx = None
            for idx, col in enumerate(cols):
                str_vals = col.get("stringColumn", {}).get("values", [])
                lng_vals = col.get("longColumn",   {}).get("values", [])
                if lng_vals and count_idx is None:
                    count_idx = idx
                    continue
                sample = set(str_vals[:25])
                if sample & _VEHICLE_TYPE_HINTS and vehicle_idx is None:
                    vehicle_idx = idx
                elif sample & _FUEL_TYPE_HINTS and fuel_idx is None:
                    fuel_idx = idx

            if vehicle_idx is None or fuel_idx is None or count_idx is None:
                continue

            vehicle_vals = cols[vehicle_idx].get("stringColumn", {}).get("values", [])
            fuel_vals    = cols[fuel_idx   ].get("stringColumn", {}).get("values", [])
            count_vals   = cols[count_idx  ].get("longColumn",   {}).get("values", [])
            null_vehicle = set(cols[vehicle_idx].get("nullIndex", []))
            null_fuel    = set(cols[fuel_idx   ].get("nullIndex", []))
            null_count   = set(cols[count_idx  ].get("nullIndex", []))

            if DEBUG and not quiet:
                print(f"[albania][debug] qualifying subset: size={size} "
                      f"cols={len(cols)} vehicle_idx={vehicle_idx} "
                      f"fuel_idx={fuel_idx} count_idx={count_idx}")
                # Show every unique fuel label that appears in Autoveturë rows
                car_fuel: dict[str, int] = {}
                for i in range(size):
                    veh = vehicle_vals[i] if i < len(vehicle_vals) else ""
                    if veh != VEHICLE_FILTER_VALUE:
                        continue
                    fv = fuel_vals[i] if i < len(fuel_vals) else ""
                    cnt = (int(count_vals[i])
                           if (i not in null_count and i < len(count_vals)) else 0)
                    car_fuel[fv] = car_fuel.get(fv, 0) + cnt
                for fv, cnt in sorted(car_fuel.items()):
                    print(f"[albania][debug]   car fuel {fv!r} → "
                          f"{_fuel_col(fv)} count={cnt}")

            local = {c: 0 for c in VALUE_COLS}
            for i in range(size):
                if i in null_vehicle or i in null_fuel:
                    continue
                if (vehicle_vals[i] if i < len(vehicle_vals) else "") != \
                        VEHICLE_FILTER_VALUE:
                    continue
                fuel  = fuel_vals[i] if i < len(fuel_vals) else ""
                count = (int(count_vals[i])
                         if (i not in null_count and i < len(count_vals)) else 0)
                local[_fuel_col(fuel)] += count

            if DEBUG and not quiet:
                print(f"[albania][debug] fuel counts (subset size={size}): "
                      f"{local} total={sum(local.values())}")
            return local   # first qualifying vehicle×fuel×count subset wins

    return counts


def _difference_to_rows(fetched: dict) -> dict:
    """Recover true single-month gallery rows from the all-months baseline and
    the per-month complement captures.

    With months sorted descending m_k > … > m_1 and A_i = the report total
    after toggling m_i (and all later months) OFF — i.e. the sum over months
    still selected (< m_i) — the single-month value is the telescoping diff
        m_i = A_{i-1} − A_i,   where A_0 = baseline (all months on)
    and A_1 = 0 (toggling January empties the selection → no data).
    This is done per fuel column.
    """
    baseline = _parse_fuel_counts(fetched["baseline"])
    comp = {p: _parse_fuel_counts(m) for p, m in fetched["complements"]}
    present = fetched["present_periods"]            # descending YYYY-MM

    if DEBUG:
        print(f"[albania][debug] baseline (all months): {baseline} "
              f"total={sum(baseline.values())}")
        for p in present:
            if p in comp:
                print(f"[albania][debug] A[{p}] (after toggling {p} off): "
                      f"{comp[p]} total={sum(comp[p].values())}")

    # Guard: toggling the first month (latest, in descending order) OFF must
    # REDUCE the total — this proves the control defaulted to all-months-selected,
    # which differencing relies on.
    if present and present[0] in comp:
        if sum(comp[present[0]].values()) >= sum(baseline.values()):
            raise RuntimeError(
                "[albania] Muaji filter is not all-months-selected by default "
                f"(baseline total={sum(baseline.values())}, after toggling "
                f"{present[0]} off={sum(comp[present[0]].values())}); the "
                "differencing assumption is invalid — aborting to avoid bad data")

    rows: dict = {}
    prev = baseline
    zero = {c: 0 for c in VALUE_COLS}
    for i, p in enumerate(present):
        a = comp.get(p)
        if a is None:
            if i == len(present) - 1:
                a = zero            # earliest month (Jan): empty selection → no capture
            else:
                print(f"[albania] WARNING: missing complement for {p}; cannot "
                      f"difference this and the following month reliably")
                prev = None
                continue
        if prev is None:
            prev = a
            continue

        month = {c: max(0, prev[c] - a[c]) for c in VALUE_COLS}
        row = {
            "period":        p,
            "time_interval": "monthly",
            "variant":       VARIANT,
            "source":        SOURCE,
            "BEV":    month["BEV"],    "PHEV":   month["PHEV"],
            "HEV":    month["HEV"],    "PETROL": month["PETROL"],
            "DIESEL": month["DIESEL"], "OTHERS": month["OTHERS"],
            "TOTAL":  sum(month.values()),
            "notes":  "",
        }
        # Zero optional cols → empty string (gallery convention).
        for col in ("BEV", "PHEV", "HEV", "OTHERS"):
            if row[col] == 0:
                row[col] = ""
        rows[(p, VARIANT)] = row
        prev = a

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

    fetched = _fetch_with_browser_session(args.year_from, args.year_to)
    rows = _difference_to_rows(fetched)

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
