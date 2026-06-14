#!/usr/bin/env python3
"""
Fetch Albania monthly vehicle-registration data directly from DPSHTRR's public
Looker Studio report and upsert one CSV per variant: Whole →
``data/Albania.csv``, others → ``data/Albania_<Variant>.csv``.

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
     table; aggregate by fuel type for every registered VARIANT in one pass.

This was cross-checked against an authoritative monthly car-sales reference:
the differenced 2026 months (Jan 5673, Feb 5905, Mar 6103, Apr 6732, May 6358)
matched it exactly, confirming the toggle semantics and the fuel mapping.

Note: the English DPSHTRR report (407ce08b-…) cannot be used — its
batchedDataV2 responses fail with SNAPSHOT_WITH_NON_REAGGREGATABLE because the
component body sets ``createSnapshot:true``.  The Albanian report (233df2cc-…)
does NOT set that flag and works correctly.

Note: DPSHTRR publishes a *separate* Looker report each calendar year, each with
its own report ID, datasource ID and revision.  These live in the ``YEAR_REPORTS``
registry below; only the report ID and page slug are needed per year (datasource,
component and revision are auto-detected from the page's own intercepted
requests).  When a new year starts, add one ``{year: (report_id, slug)}`` entry.
Pre-2026 Whole rows are bootstrapped from Andrew's mirror; HDV/Buses/2-Wheelers
were backfilled directly from the per-year reports (2020–2024; 2025 excluded —
its snapshots are corrupt, see docs §11).
See docs/architecture/27-source-albania.md for the full source playbook.

Fuel-type mapping (Lenda Djegese → gallery schema)
---------------------------------------------------
    Elektrik                             → BEV
    Hybrid plug-in, Benzinë/Elektrik     → PHEV
    Hybrid plug-in, Naftë/Elektrik       → PHEV  (diesel PHEV)
    Hybrid Benzinë/Elektrik              → HEV
    Hybrid Naftë/Elektrik                → HEV   (mild-hybrid diesel)
    Hybrid Benzinë/Gaz/Elektrik          → HEV
    Benzinë                              → PETROL
    Naftë                                → DIESEL
    everything else (LPG, Gas, CNG, …)   → OTHERS
Each of the above also accepts the ASCII-ified form without "ë" (Benzine, Nafte)
since the batchedDataV2 API sometimes strips Albanian diacritics from fuel labels.

Vehicle variants produced (EU class in parentheses)
----------------------------------------------------
    Whole       Autoveturë              M1     passenger cars
    HDV         Kamion                  N2+N3  trucks / lorries
    Buses       Autobus                 M2+M3  buses & coaches
    2-Wheelers  Motor + Ciklomotorr …   L      motorcycles & mopeds
The actual DPSHTRR pivot uses "Motor"/"MOTORË" (not the textbook
"Motoçikletë") and "Ciklomotorr …" (not "Çikëlomotor"); see VARIANTS below
for the full L-category string set.  There is NO dedicated N1 (van) category
in the pivot, so the gallery's Vans variant is not produced.  Reports ≤2022
use ALL CAPS labels, ≥2023 use mixed case; VARIANTS carries both forms.
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

# ── Per-year Looker Studio report registry ───────────────────────────────────
# DPSHTRR publishes a new Looker report each calendar year.  Each entry is
# (report_id, page_id_url) for the Albanian Shqip report's vehicle-fuel page.
# All years use page slug VPWqB ("Mjete sipas Lëndës Djegëse").
# DATASOURCE_ID is NOT hardcoded here: the intercept captures all batchedDataV2
# and relies on _parse_fuel_counts structural validation to select the right one.
# 2019 is omitted: its report has a different layout with no Muaji multiselect.
YEAR_REPORTS: dict[int, tuple[str, str]] = {
    2020: ("70f605d5-f454-4776-af73-fdbbcd757bbb", "VPWqB"),
    2021: ("3c73a68e-3df5-4ad4-b210-274b9d274d36", "VPWqB"),
    2022: ("bb9de550-a4cd-45ce-84d5-ec9fa5af028f", "VPWqB"),
    2023: ("78d2f17c-8f62-4b3a-872e-141c0ffecd53", "VPWqB"),
    2024: ("5d405a90-3508-4e91-abec-85ea46cd9426", "VPWqB"),
    2025: ("8d58f55d-117f-4c4e-939a-2b42188966f4", "VPWqB"),
    2026: ("233df2cc-6bd4-45fc-bf9b-e8ee4f83293e", "VPWqB"),
    # When a new year starts: add an entry here.
}

# ── Variant → Albanian vehicle-type mapping (EU class) ───────────────────────
# Each gallery variant maps to one or more Albanian vehicle-type strings that
# appear in the vehicle_type column of the pivot response.
# The VPWqB pivot uses MIXED-CASE labels (Autoveturë, Kamion, Motor) for every
# year 2020-2026 — confirmed in the 2020-2024 backfill.  The ALL-CAPS forms
# (AUTOVETURË …) were only seen on the abandoned overview page and are kept
# defensively in case a future report reverts.
VARIANTS: dict[str, set[str]] = {
    "Whole": {"Autoveturë", "AUTOVETURË"},                 # M1
    "HDV":   {"Kamion",     "KAMION"},                     # N2+N3 rigid trucks
    "Buses": {"Autobus",    "AUTOBUS"},                    # M2+M3
    "2-Wheelers": {                                        # L-category
        "Motor",        "MOTORË",                          # L3/L4 motorcycles (bulk)
        "Motor me kosh",                                   # L4 with sidecar
        "Motor me tre rrota, simetrike",                   # L5 symmetric tricycle
        "Motor me katër rrota, i lehtë",                   # L6e light quadricycle
        "Motor me katër rrota, jo i lehtë",               # L7e heavy quadricycle
        "Ciklomotorr me dy rrota",                         # L1/L2 moped 2-wheel
        "Ciklomotorr me tre rrota",                        # L2e moped 3-wheel
    },
}

# ── Gallery schema ───────────────────────────────────────────────────────────
SOURCE      = "dpshtrr.al"
CSV_PATH    = "data/Albania.csv"
CSV_COLUMNS = [
    "period", "time_interval", "variant", "source",
    "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS", "TOTAL", "notes",
]
VALUE_COLS  = ["BEV", "PHEV", "HEV", "PETROL", "DIESEL", "OTHERS"]

# ── Fuel-type → gallery-column mapping ──────────────────────────────────────
# The VPWqB pivot for every year 2020-2026 uses MIXED-CASE labels
# (Naftë, Benzinë, Elektrik, Hybrid Benzinë/Elektrik) — verified across the
# 2020-2024 backfill dry-run.  The ALL-CAPS forms (NAFTË, BENZINË+ELEKTRIK …)
# were only ever seen on the abandoned overview page (CU40B), never in this
# pivot; they are retained defensively in case a future report reverts.
# Matching is case-INSENSITIVE: DPSHTRR is inconsistent even within mixed case
# (e.g. "Hybrid plug-in, naftë/Elektrik" with a lowercase n appears alongside
# the capitalised form), so all comparisons casefold both sides.
# Additionally, the batchedDataV2 API has been observed returning ASCII-ified
# labels (Benzine/Nafte without ë) while the report UI shows the correct Albanian
# diacritic — both forms are included in every set so PHEVs/HEVs cannot slip into
# OTHERS due to encoding mismatches.
_BEV  = {"Elektrik",  "ELEKTRIK"}
_PHEV = {
    "Hybrid plug-in, Benzinë/Elektrik", "Hybrid plug-in, Naftë/Elektrik",   # ≥2023 with ë
    "Hybrid plug-in, Benzine/Elektrik", "Hybrid plug-in, Nafte/Elektrik",   # ≥2023 without ë (API may ASCII-ify)
    "BENZINË+ELEKTRIK+HYBRID",          "NAFTË+ELEKTRIK+HYBRID",             # legacy
}
_HEV  = {
    "Hybrid Benzinë/Elektrik", "Hybrid Naftë/Elektrik",                      # ≥2023 with ë
    "Hybrid Benzine/Elektrik", "Hybrid Nafte/Elektrik",                      # ≥2023 without ë
    "Hybrid Benzinë/Gaz/Elektrik",                                            # ≥2023
    "Hybrid Benzine/Gaz/Elektrik",                                            # without ë
    "BENZINË+ELEKTRIK",        "NAFTË+ELEKTRIK",                             # legacy
    "BENZINË+GAZ+ELEKTRIK",                                                   # legacy
}
_PET  = {"Benzinë",   "BENZINË",  "Benzine"}                                 # without ë defensive
_DIE  = {"Naftë",     "NAFTË",    "Nafte"}                                   # without ë defensive
# Everything else → OTHERS: LPG (Benzinë/GPL, Gaz i lëngshëm, BENZINË+GAZ, GAZ),
# CNG (Metan), NUK KA, unknown.

# Casefolded lookup tables (built once) so casing inconsistencies map correctly.
_FUEL_COL_BY_CF = {f.casefold(): col for col, s in (
    ("BEV", _BEV), ("PHEV", _PHEV), ("HEV", _HEV), ("PETROL", _PET), ("DIESEL", _DIE),
) for f in s}

def _fuel_col(fuel: str) -> str:
    return _FUEL_COL_BY_CF.get(fuel.casefold(), "OTHERS")


# ── Known vehicle types (used for column-type detection) ─────────────────────
# Includes both ALL CAPS (≤2022) and mixed-case (≥2023) forms.
_VEHICLE_TYPE_HINTS = {
    "Autoveturë", "AUTOVETURË",
    "Kamion",     "KAMION",
    "Autobus",    "AUTOBUS",
    "Motor",      "MOTORË",
    "Motor me kosh", "Motor me tre rrota, simetrike",
    "Motor me katër rrota, i lehtë", "Motor me katër rrota, jo i lehtë",
    "Ciklomotorr me dy rrota", "Ciklomotorr me tre rrota",
    "Tërheqës",   "TËRHEQËS",
    "Gjysëmrimorkio", "GJYSËM RIMORKIO",
    "Automjet për transport të përzier",  "AUTOMJET PËR TRANSPORT TË P...",
    "Automjet për transport të veçantë",
    "Automjet për përdorim të veçantë",
    "Traktor bujqësor, me rrota",         "MAKINA BUJQËSORE",
}
# Known fuel types (used for column-type detection); both ≥2023 and ≤2022 forms.
_FUEL_TYPE_HINTS = {
    "Elektrik", "Benzinë", "Naftë",
    "Benzine", "Nafte",                                                       # without ë
    "Hybrid Benzinë/Elektrik", "Hybrid Naftë/Elektrik",
    "Hybrid Benzine/Elektrik", "Hybrid Nafte/Elektrik",                      # without ë
    "Hybrid plug-in, Benzinë/Elektrik", "Hybrid plug-in, Naftë/Elektrik",
    "Hybrid plug-in, Benzine/Elektrik", "Hybrid plug-in, Nafte/Elektrik",   # without ë
    "Hybrid Benzinë/Gaz/Elektrik", "Hybrid Benzine/Gaz/Elektrik",
    "ELEKTRIK", "BENZINË", "NAFTË",
    "BENZINË+ELEKTRIK", "NAFTË+ELEKTRIK", "BENZINË+GAZ+ELEKTRIK",
    "BENZINË+GAZ", "GAZ", "NUK KA",
}


# ── Session via headless browser ──────────────────────────────────────────────

def _fetch_with_browser_session(year: int) -> dict:
    """
    Load the year-specific Albanian DPSHTRR Looker Studio report in headless
    Chromium, intercept all batchedDataV2 responses, and iterate the Muaji
    (Month) filter to collect per-month vehicle×fuel pivot data.

    All batchedDataV2 responses are captured (no datasource-ID filter); the
    structural check in _parse_fuel_counts selects the qualifying pivot subset.

    Returns ``{"baseline": …, "complements": […], "present_periods": […]}``.
    """
    if year not in YEAR_REPORTS:
        raise ValueError(
            f"[albania] no report registered for year {year}; "
            f"add an entry to YEAR_REPORTS. Known years: {sorted(YEAR_REPORTS)}")
    report_id, page_id_url = YEAR_REPORTS[year]
    report_url = (
        f"https://lookerstudio.google.com/reporting/{report_id}/page/{page_id_url}"
    )

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
            # Capture ALL batchedDataV2 responses — datasource ID varies per year
            # and is not hardcoded.  _parse_fuel_counts validates structure.
            captured.append({
                "component":    component,
                "displayType":  displaytype,
                "datasourceId": datasource,
                "body":         body,
                "text":         text,
            })
            if DEBUG:
                print(f"[albania][debug] captured ds={datasource[:16]}… "
                      f"component={component} displayType={displaytype} "
                      f"body_len={len(body)} resp_len={len(text)}")
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

        # Phase 1: direct navigation to year-specific Albanian report page
        print(f"[albania] [{year}] browser → {report_url}")
        page.goto(report_url, wait_until="load", timeout=90_000)

        if DEBUG:
            print(f"[albania][debug] phase-1 landed: {page.url}")
            cookies = context.cookies()
            print(f"[albania][debug] cookies: {[c['name'] for c in cookies]}")

        # Phase 2: navigate to datastudio.google.com domain if still on
        # lookerstudio.google.com (redirect may not happen automatically)
        current_url = page.url
        if page_id_url not in current_url:
            direct_url = (
                f"https://datastudio.google.com/reporting/{report_id}"
                f"/page/{page_id_url}"
            )
            print(f"[albania] [{year}] phase-2 → {direct_url}")
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
        print(f"[albania] [{year}] initial capture: {initial_end - initial_start} "
              f"batchedDataV2 responses")

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
            if p and int(p[:4]) == year:
                present.append((lbl, p))
        present.sort(key=lambda x: x[1], reverse=True)  # descending: latest first
        present_periods = [p for _, p in present]
        print(f"[albania] [{year}] Muaji months present (descending): {present_periods}")

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
                    _merge_slice(cap_before), VARIANTS["Whole"],
                    quiet=True).values())
                if total > 0:
                    page.wait_for_timeout(2500)   # let trailing subsets settle
                    got = True
                    break

            if got:
                complements.append((period, _merge_slice(cap_before)))
                counts = _parse_fuel_counts(
                    _merge_slice(cap_before), VARIANTS["Whole"], quiet=True)
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

    print(f"[albania] [{year}] captured {len(captured)} total batchedDataV2 "
          f"responses; {len(complements)} month complements")

    return {
        "baseline":         baseline_merged,
        "complements":      complements,
        "present_periods":  present_periods,
    }


# ── Response parsing ─────────────────────────────────────────────────────────

def _decode_column(col: dict, size: int) -> list:
    """Decode one Looker ``batchedDataV2`` columnar column into a full
    ``size``-length, row-aligned list (None at null positions).

    Looker packs ONLY the non-null cell values into ``stringColumn.values`` /
    ``longColumn.values`` (in row order) and records the null ROW indices
    separately in ``nullIndex``.  So ``values[i]`` is the i-th *non-null* cell,
    NOT the value of row i: once any earlier row is null, every later row is
    shifted.  Indexing ``values[i]`` directly (as the original parser did)
    therefore mis-pairs vehicle/fuel/count for every row after the first null,
    which silently drops the rare trailing fuels — e.g. it folded the petrol
    plug-in hybrid (``Hybrid plug-in, Benzinë/Elektrik``) out of Autoveturë's
    PHEV tally.  Rebuilding the row-aligned array fixes that class of bug for
    every column at once."""
    null_idx = set(col.get("nullIndex", []))
    svals = col.get("stringColumn", {}).get("values", [])
    lvals = col.get("longColumn",   {}).get("values", [])
    packed = svals if svals else lvals
    out: list = []
    it = iter(packed)
    for i in range(size):
        out.append(None if i in null_idx else next(it, None))
    return out


_SUBSET_DUMPED = False

def _dump_all_subsets(data: dict, vehicle_types: set[str]) -> None:
    """DEBUG one-shot: enumerate EVERY qualifying (vehicle,fuel,count) subset in a
    merged batchedDataV2 response and print its per-fuel breakdown for the given
    vehicle_types.  Used to diagnose which subset separates the petrol plug-in
    hybrid (Hybrid plug-in, Benzinë/Elektrik) from Elektrik — _parse_fuel_counts
    only reads the FIRST qualifying subset, which may fold PHEVs into BEV."""
    global _SUBSET_DUMPED
    if _SUBSET_DUMPED:
        return
    _SUBSET_DUMPED = True
    print("[albania][dump] ===== enumerating ALL qualifying subsets =====")
    s_idx = 0
    for dr_i, dr in enumerate(data.get("dataResponse", [])):
        if dr.get("errorStatus"):
            continue
        for sub_i, subset in enumerate(dr.get("dataSubset", [])):
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
            qualifies = not (vehicle_idx is None or fuel_idx is None or count_idx is None)
            print(f"[albania][dump] subset #{s_idx} (dr={dr_i},sub={sub_i}) size={size} "
                  f"ncols={len(cols)} qualifies={qualifies} "
                  f"v_idx={vehicle_idx} f_idx={fuel_idx} c_idx={count_idx}")
            # Show distinct string values + value-array length + nullIndex count
            # per column, so misalignment between packed values and `size` is visible.
            for ci, col in enumerate(cols):
                sv = col.get("stringColumn", {}).get("values", [])
                lv = col.get("longColumn",   {}).get("values", [])
                nidx = col.get("nullIndex", [])
                if sv:
                    distinct = sorted(set(sv))
                    print(f"[albania][dump]   col{ci} STRING nvals={len(sv)} "
                          f"nulls={len(nidx)} distinct={len(distinct)}: {distinct[:40]!r}")
                elif lv:
                    print(f"[albania][dump]   col{ci} LONG nvals={len(lv)} "
                          f"nulls={len(nidx)} sample={lv[:6]!r}")
                else:
                    print(f"[albania][dump]   col{ci} EMPTY keys={list(col.keys())!r}")
            s_idx += 1
            if not qualifies:
                continue
            # Row-aligned decode (the actual fix) — compare against naive indexing.
            vehicle_vals = _decode_column(cols[vehicle_idx], size)
            fuel_vals    = _decode_column(cols[fuel_idx],    size)
            count_vals   = _decode_column(cols[count_idx],   size)
            vt_fuel: dict[str, int] = {}
            for i in range(size):
                if vehicle_vals[i] not in vehicle_types:
                    continue
                fv = fuel_vals[i] if fuel_vals[i] is not None else ""
                cnt = int(count_vals[i]) if count_vals[i] is not None else 0
                vt_fuel[fv] = vt_fuel.get(fv, 0) + cnt
            for fv, cnt in sorted(vt_fuel.items()):
                print(f"[albania][dump]     fuel {fv!r} → {_fuel_col(fv)} count={cnt}")
            print(f"[albania][dump]     subset #{s_idx-1} Autoveturë total={sum(vt_fuel.values())} (row-aligned decode)")
    print("[albania][dump] ===== end subset enumeration =====")


def _parse_fuel_counts(data: dict, vehicle_types: set[str],
                       quiet: bool = False) -> dict:
    """Aggregate registrations for the given vehicle_types by gallery fuel column
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

    if DEBUG and not quiet and ("Autoveturë" in vehicle_types):
        _dump_all_subsets(data, vehicle_types)

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

            # Row-aligned decode (honours nullIndex — see _decode_column).
            vehicle_vals = _decode_column(cols[vehicle_idx], size)
            fuel_vals    = _decode_column(cols[fuel_idx],    size)
            count_vals   = _decode_column(cols[count_idx],   size)

            if DEBUG and not quiet:
                print(f"[albania][debug] qualifying subset: size={size} "
                      f"cols={len(cols)} vehicle_idx={vehicle_idx} "
                      f"fuel_idx={fuel_idx} count_idx={count_idx}")
                # Dump ALL vehicle types present (incl. unknowns like N1/Vans)
                all_vt: dict[str, int] = {}
                for i in range(size):
                    veh = vehicle_vals[i] if vehicle_vals[i] is not None else ""
                    cnt = int(count_vals[i]) if count_vals[i] is not None else 0
                    all_vt[veh] = all_vt.get(veh, 0) + cnt
                known = set().union(*VARIANTS.values())
                for veh, cnt in sorted(all_vt.items(), key=lambda x: -x[1]):
                    tag = "" if veh in known else "  ← UNKNOWN"
                    print(f"[albania][debug]   vehicle {veh!r} total={cnt}{tag}")
                # Per-fuel breakdown for the requested vehicle_types
                vt_fuel: dict[str, int] = {}
                for i in range(size):
                    if vehicle_vals[i] not in vehicle_types:
                        continue
                    fv = fuel_vals[i] if fuel_vals[i] is not None else ""
                    cnt = int(count_vals[i]) if count_vals[i] is not None else 0
                    vt_fuel[fv] = vt_fuel.get(fv, 0) + cnt
                for fv, cnt in sorted(vt_fuel.items()):
                    print(f"[albania][debug]   fuel {fv!r} → "
                          f"{_fuel_col(fv)} count={cnt}")

            local = {c: 0 for c in VALUE_COLS}
            for i in range(size):
                if vehicle_vals[i] is None or fuel_vals[i] is None:
                    continue
                if vehicle_vals[i] not in vehicle_types:
                    continue
                count = int(count_vals[i]) if count_vals[i] is not None else 0
                local[_fuel_col(fuel_vals[i])] += count

            if DEBUG and not quiet:
                print(f"[albania][debug] fuel counts (subset size={size}): "
                      f"{local} total={sum(local.values())}")
            return local   # first qualifying vehicle×fuel×count subset wins

    return counts


def _difference_to_rows(fetched: dict) -> dict:
    """Recover true single-month gallery rows for every VARIANT from the
    all-months baseline and the per-month complement captures.

    With months sorted descending m_k > … > m_1 and A_i = the report total
    after toggling m_i (and all later months) OFF — i.e. the sum over months
    still selected (< m_i) — the single-month value is the telescoping diff
        m_i = A_{i-1} − A_i,   where A_0 = baseline (all months on)
    and A_1 = 0 (toggling January empties the selection → no data).
    This is done per fuel column, for each variant independently.
    """
    present = fetched["present_periods"]            # descending YYYY-MM
    zero    = {c: 0 for c in VALUE_COLS}

    # Guard (on Whole / Autoveturë): toggling the first month OFF must REDUCE the
    # total — proves the control defaulted to all-months-selected.
    _whole_vt  = VARIANTS["Whole"]
    _base_w    = _parse_fuel_counts(fetched["baseline"], _whole_vt)
    _comp_w0   = (_parse_fuel_counts(fetched["complements"][0][1], _whole_vt)
                  if fetched["complements"] else None)
    if _comp_w0 is not None and present:
        if sum(_comp_w0.values()) >= sum(_base_w.values()):
            raise RuntimeError(
                "[albania] Muaji filter is not all-months-selected by default "
                f"(baseline total={sum(_base_w.values())}, after toggling "
                f"{present[0]} off={sum(_comp_w0.values())}); the "
                "differencing assumption is invalid — aborting to avoid bad data")

    rows: dict = {}

    for variant, vt in VARIANTS.items():
        baseline = _parse_fuel_counts(fetched["baseline"], vt)
        comp     = {p: _parse_fuel_counts(m, vt)
                    for p, m in fetched["complements"]}

        if DEBUG:
            print(f"[albania][debug] [{variant}] baseline: {baseline} "
                  f"total={sum(baseline.values())}")
            for p in present:
                if p in comp:
                    print(f"[albania][debug] [{variant}] A[{p}]: "
                          f"{comp[p]} total={sum(comp[p].values())}")

        prev = baseline
        for i, p in enumerate(present):
            a = comp.get(p)
            if a is None:
                if i == len(present) - 1:
                    a = zero        # earliest month (Jan): empty selection → no capture
                else:
                    print(f"[albania] WARNING [{variant}]: missing complement "
                          f"for {p}; cannot difference this and the following "
                          f"month reliably")
                    prev = None
                    continue
            if prev is None:
                prev = a
                continue

            month = {c: max(0, prev[c] - a[c]) for c in VALUE_COLS}
            row = {
                "period":        p,
                "time_interval": "monthly",
                "variant":       variant,
                "source":        SOURCE,
                "BEV":    month["BEV"],    "PHEV":   month["PHEV"],
                "HEV":    month["HEV"],    "PETROL": month["PETROL"],
                "DIESEL": month["DIESEL"], "OTHERS": month["OTHERS"],
                "TOTAL":  sum(month.values()),
                "notes":  "",
            }
            # NOTE: zeros are written as 0, NOT blanked. A fuel column that is
            # *sometimes* reported (e.g. PHEV) must carry explicit 0s in its
            # quiet months — the TTM renderer uses strict rolling and DROPS any
            # month whose trailing-12 window touches a blank cell, which would
            # silently truncate the chart. Columns that are *never* non-zero for
            # a variant are blanked once, at write time, by _normalize_zero_cells
            # (so the renderer skips them, matching the per-variant CSV convention).
            rows[(p, variant)] = row
            prev = a

    return rows


# ── CSV upsert ───────────────────────────────────────────────────────────────

def variant_csv_path(variant: str) -> str:
    """Per-variant CSV layout (gallery convention): Whole lives in the bare
    data/Albania.csv; every other variant has its own data/Albania_<Variant>.csv
    (read directly by R/render_country.R via variant_filename())."""
    if variant == "Whole":
        return CSV_PATH
    base = os.path.splitext(CSV_PATH)[0]          # data/Albania
    return f"{base}_{variant}.csv"                # data/Albania_HDV.csv, …


def _num_or_none(v) -> float | None:
    s = str(v).strip()
    if s in ("", "na", "nan", "NA"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _normalize_zero_cells(rows: list[dict]) -> None:
    """In-place per-file cleanup of the fuel columns.

    A column that is non-zero in *any* row of the file is "active": its blank
    cells are filled with 0 so the column is a complete numeric series (the TTM
    renderer's strict rolling drops months whose trailing-12 window contains a
    blank, which truncates the chart). A column that is zero/blank in *every*
    row is left blank everywhere, so R/render_country.R skips it entirely
    (matches the per-variant CSV convention, e.g. PHEV/HEV for trucks)."""
    for col in VALUE_COLS:
        vals = [_num_or_none(r.get(col, "")) for r in rows]
        active = any(v is not None and v != 0 for v in vals)
        for r, v in zip(rows, vals):
            r[col] = ("" if not active else ("0" if v is None else r[col]))


def upsert_csv(csv_path: str, new_rows: dict, since: str | None) -> tuple[int, int]:
    """Upsert ``new_rows`` (keyed by (period, variant)) into ``csv_path``.
    All rows are expected to share one variant (the per-variant file)."""
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
            existing[key] = dict(new_row)
            added += 1
            print(f"  + {key[1]} {key[0]}")
        else:
            if not new_row.get("notes"):
                new_row["notes"] = existing[key].get("notes", "")
            existing[key] = {**existing[key], **new_row}
            updated += 1

    ordered = [existing[k] for k in sorted(existing.keys(), key=lambda k: (k[1], k[0]))]
    _normalize_zero_cells(ordered)

    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        w.writeheader()
        for row in ordered:
            w.writerow(row)
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
    ap.add_argument("--variants", default=None,
                    help="Comma-separated variants to UPSERT (default: all). "
                         "Parsing/printing still covers all; this only filters "
                         "what gets written. Use e.g. 'HDV,Buses,2-Wheelers' to "
                         "backfill non-Whole variants without touching existing "
                         "Whole rows.")
    ap.add_argument("--force", action="store_true",
                    help="Accepted for parity (commit-gated downstream).")
    args = ap.parse_args()

    write_variants: set[str] | None = None
    if args.variants:
        write_variants = {v.strip() for v in args.variants.split(",") if v.strip()}
        unknown_v = write_variants - set(VARIANTS)
        if unknown_v:
            print(f"[albania] ERROR: unknown variant(s) {sorted(unknown_v)}; "
                  f"known: {sorted(VARIANTS)}", file=sys.stderr)
            sys.exit(1)

    years = range(args.year_from, args.year_to + 1)
    unknown_years = [y for y in years if y not in YEAR_REPORTS]
    if unknown_years:
        print(f"[albania] ERROR: no report registered for year(s) {unknown_years}. "
              f"Add entries to YEAR_REPORTS in the script.", file=sys.stderr)
        sys.exit(1)

    all_rows: dict = {}
    for year in years:
        print(f"\n[albania] ── year {year} ──")
        fetched = _fetch_with_browser_session(year)
        rows = _difference_to_rows(fetched)
        if not rows:
            print(f"[albania] WARNING: no rows parsed for {year} — "
                  f"check report URL / Muaji filter / vehicle-type strings.")
        all_rows.update(rows)

    if not all_rows:
        print("[albania] no data rows parsed at all.", file=sys.stderr)
        sys.exit(1)

    print(f"\n[albania] parsed {len(all_rows)} month-variant rows total")
    for key in sorted(all_rows):
        r = all_rows[key]
        bev  = r["BEV"]  or 0
        phev = r["PHEV"] or 0
        hev  = r["HEV"]  or 0
        print(
            f"  {key[1]:12s} {key[0]}  BEV={bev:.0f}  PHEV={phev:.0f}"
            f"  HEV={hev:.0f}  PETROL={r['PETROL']:.0f}"
            f"  DIESEL={r['DIESEL']:.0f}  OTHERS={r['OTHERS'] or 0:.0f}"
            f"  TOTAL={r['TOTAL']:.0f}"
        )

    if args.dry_run:
        print("(dry-run: CSV not written)")
        return

    write_rows = all_rows
    if write_variants is not None:
        write_rows = {k: v for k, v in all_rows.items() if k[1] in write_variants}
        print(f"[albania] writing only variants {sorted(write_variants)}: "
              f"{len(write_rows)} of {len(all_rows)} rows")

    # One CSV per variant: Whole → data/Albania.csv, others → data/Albania_<V>.csv.
    by_variant: dict[str, dict] = {}
    for key, row in write_rows.items():
        by_variant.setdefault(key[1], {})[key] = row

    tot_added = tot_updated = 0
    for variant in sorted(by_variant):
        path = variant_csv_path(variant)
        added, updated = upsert_csv(path, by_variant[variant], args.since)
        tot_added += added
        tot_updated += updated
        print(f"{added} added, {updated} updated -> {path}")
    print(f"[albania] total {tot_added} added, {tot_updated} updated across "
          f"{len(by_variant)} variant file(s)")


if __name__ == "__main__":
    main()
