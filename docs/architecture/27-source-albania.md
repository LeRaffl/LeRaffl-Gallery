# 27 · Source: Albania (dpshtrr.al, Looker Studio via headless Chromium)

Albania's General Directorate of Road Transport Services (DPSHTRR — *Drejtoria
e Përgjithshme e Shërbimeve të Transportit Rrugor*) publishes monthly vehicle
registration counts broken down by fuel type through its Open Data portal.  The
data lives in a public Looker Studio (Google Data Studio) report.  We fetch it
by driving a headless Chromium (Playwright) session, intercepting the
`batchedDataV2` JSON responses the report itself fires.

## TL;DR

```
Source:        dpshtrr.al  (DPSHTRR Open Data, Looker Studio)
Report:        Albanian (Shqip) report — 233df2cc-6bd4-45fc-bf9b-e8ee4f83293e
Page (URL):    VPWqB   ("Mjete sipas Lëndës Djegëse")
Page (numeric):24871631
datasourceId:  013d0728-f5d3-4599-8899-cfb3f02fa77e
revisionNumber:16  (captured 2026-06-13; bump if responses go empty)
Auth:          Real browser session required; plain-HTTP is PREFETCH_VALIDATION-blocked
Approach:      Headless Playwright → intercept batchedDataV2 → Muaji filter differencing
Filter:        Autoveturë (passenger cars only)
Variant:       Whole (all first registrations, new + imported used)
Coverage:      Current-year months via Playwright; pre-2026 from bootstrapped CSV
Cadence:       Monthly; time_interval=monthly
Schedule:      Daily days 10-28, 07:00 UTC; commit-gated
Scripts:       scripts/fetch_albania.py
Workflow:      .github/workflows/fetch-albania.yml
```

## 1. Why headless Chromium (not a plain HTTP request)

There are two independent reasons we cannot use a plain-HTTP POST to
`batchedDataV2`:

**PREFETCH_VALIDATION.** Google Looker Studio validates every
`batchedDataV2` request body against a pre-computed fingerprint set during page
load.  Any request whose payload was not pre-registered by the page returns
`ACCESS / PREFETCH_VALIDATION`.  Custom payloads are categorically rejected.
A real browser session that loads the actual report page is required.

**SNAPSHOT_WITH_NON_REAGGREGATABLE.** The *English* version of the DPSHTRR
report (`407ce08b-d3ce-478e-9bc7-a50125f875f3`) sets `createSnapshot:true` in
its component body.  All `batchedDataV2` responses for that report fail with
`SNAPSHOT_WITH_NON_REAGGREGATABLE`.  The *Albanian (Shqip)* version
(`233df2cc-6bd4-45fc-bf9b-e8ee4f83293e`) does **not** set that flag and returns
data correctly.  We must use the Albanian report, not the English one.

## 2. Automation flow

```
1. Launch headless Chromium (Playwright), install route intercept on **/*
2. Navigate to the Albanian report page (lookerstudio.google.com/reporting/233df2cc…)
3. Wait 35 s for the initial batchedDataV2 responses (baseline = all months selected)
4. Locate and open the "Muaji" (Month) multi-select filter popup
5. Toggle each month OFF in DESCENDING order (latest first), capturing the
   batchedDataV2 complement response after each toggle
6. Recover single-month counts by differencing consecutive complements
7. Parse vehicle×fuel×count table, keep Autoveturë rows, map to gallery schema
8. Upsert data/Albania.csv
```

## 3. Report internals (reverse-engineered 2026-06-13)

IDs obtained by loading the Albanian report in a browser and inspecting
intercepted `batchedDataV2` network requests.

| Item | Value |
|---|---|
| Report ID (Albanian / Shqip) | `233df2cc-6bd4-45fc-bf9b-e8ee4f83293e` |
| Report ID (English — **do not use**, see §1) | `407ce08b-d3ce-478e-9bc7-a50125f875f3` |
| Page ID (URL slug) | `VPWqB` |
| Page ID (numeric, in API body) | `24871631` |
| Component ID | `cd-p9hqinijec` |
| datasourceId | `013d0728-f5d3-4599-8899-cfb3f02fa77e` |
| revisionNumber | `16` |

Internal field IDs referenced in the intercepted request bodies:

| Field | sourceFieldName |
|---|---|
| Vehicle type (Lloji Mjetit) | `_73515086_` |
| Fuel type (Lënda Djegëse) | `_818800577_` |
| Record Count | `datastudio_record_count_system_field_id_98323387` |
| Date / Month | `_3076010_` |

**Column order in the pivot is not fixed.**  `_parse_fuel_counts` detects each
column by sampling values against known vehicle-type and fuel-type string sets
(`_VEHICLE_TYPE_HINTS`, `_FUEL_TYPE_HINTS`).  Column index is not assumed.

## 4. Muaji (Month) filter — differencing approach

The "Muaji" filter is an AngularJS Material multi-select checkbox list.  Every
month is selected by default, so the initial page load gives the year-to-date
**baseline** (all months summed).

The per-row "only" single-select link is `display:none` behind a CSS `:hover`
pseudo-class that cannot be triggered programmatically, so single-selecting a
month directly is not possible.  Instead, we toggle each month *off* one at a
time in **descending order** (latest month first), and after each toggle we
capture the `batchedDataV2` response — the **complement** (sum of months still
selected).

Notation: let months be `m_k > m_{k-1} > … > m_1` (e.g. May > Apr > … > Jan).
Define `A_i` as the report total after toggling `m_i` off (months `m_{i-1}, …,
m_1` still on).  Then:

```
A_0 = baseline (all months on)
A_k = sum(months < m_k)  after toggling m_k off
A_{k-1} = sum(months < m_{k-1})  after toggling m_{k-1} off
…
A_1 = 0  (toggling January empties the selection → no data captured)

Single-month value:  m_i = A_{i-1} − A_i
```

This is computed per fuel column in `_difference_to_rows`.

**Why descending, not ascending?**  This was a hard-won finding (see §8).
The DPSHTRR Looker pivot returns *different fuel-type label strings* depending
on the time window size.  In a 5-month (Jan–May) window, `"Hybrid
Benzinë/Elektrik"` (→ HEV) is present; in a 4-month (Feb–May) window it
disappears, replaced by `"Hybrid plug-in, Benzinë/Elektrik"` (→ PHEV).  With
ascending toggle order, January = `baseline(Jan–May) − complement(Feb–May)`,
so PHEV diff = `max(0, 4 − 551) = 0` (wrong), inflating Jan TOTAL from 5673 to
6220.  Descending order gives January as `complement-after-Feb-off` = a 1-month
window where labels are consistent.

**Toggle mechanism.**  Playwright `page.get_by_text("Mon YYYY", exact=True).first.click(force=True)` bypasses the `.popup-backdrop intercepts pointer events` actionability error.

**Timing.**  After each toggle, we poll until `_parse_fuel_counts(slice).total > 0`.  The vehicle×fuel "main" subset (`cd-p9hqinijec`) arrives several seconds after the barchart and row-0 sub-responses.  Recording too early captures an incomplete merge and gives zeros.  After the main subset appears, we wait an additional 2.5 s for trailing subsets to settle.

## 5. Fuel-type mapping (Lënda Djegëse → gallery schema)

Derived from DPSHTRR Looker pivot output, Autoveturë rows only.

| DPSHTRR Lënda Djegëse | Gallery column | Notes |
|---|---|---|
| Elektrik | BEV | |
| Hybrid plug-in, Benzinë/Elektrik | PHEV | petrol PHEV |
| Hybrid plug-in, Naftë/Elektrik | PHEV | diesel PHEV |
| Hybrid Benzinë/Elektrik | HEV | |
| Hybrid Naftë/Elektrik | HEV | mild-hybrid diesel |
| Hybrid Benzinë/Gaz/Elektrik | HEV | gas-electric hybrid |
| Benzinë | PETROL | |
| Naftë | DIESEL | |
| everything else (Benzinë/Gaz, Gaz, Metan, Naftë/Gaz, LPG, `-`, …) | OTHERS | LPG / CNG / gas |

This mapping is ACEA-congruent: BEV, PHEV, HEV, PETROL, DIESEL, OTHERS.
LPG folds into OTHERS (consistent with ACEA practice).  If `OTHERS` looks high,
it is because Albania has substantial LPG registrations.

Albania **does** have separate PHEV and HEV tracking (both small in 2026: ≈ 84
PHEV, ≈ 944 HEV across Jan–May).

**Label-inconsistency caveat (§8):** the pivot table shows `"Hybrid
Benzinë/Elektrik"` in large time windows but `"Hybrid plug-in, Benzinë/Elektrik"`
in small windows.  Both strings are handled by the mapping sets; the
descending toggle order prevents them from appearing in the same diff pair.

## 6. What the figures actually count

**All first registrations in Albania** — both brand-new vehicles *and* imported
used vehicles being registered for the first time in the Albanian vehicle
database.  Albania has an exceptionally active used-car import market (primarily
from Western Europe and, increasingly, China), so headline monthly totals
(~5,000–8,000 in 2025–2026) are considerably larger than a new-car-only count
would show.

Variant is `Whole`.  No body-type or passenger/commercial sub-split is available
from DPSHTRR.

**Sanity reference:** `robbieandrew.github.io/carsales/albania_carsales_monthly.csv`
(Robbie Andrew's mirror of the same DPSHTRR source, with a different column
schema).  Small deviations (tens of cars per month, < 1 %) are acceptable —
Andrew's series includes LPG as a separate column while we fold it into OTHERS,
and minor retroactive corrections appear in the source.  Large deviations
(hundreds of cars) indicate a parsing or filter regression.

## 7. Historical data (pre-2026)

The DPSHTRR Looker report is scoped to a single calendar year ("year 2026").
Historical years (2019–2025) were bootstrapped into `data/Albania.csv` from
Robbie Andrew's pre-parsed mirror of the same DPSHTRR figures.  Attribution for
all rows is `dpshtrr.al`.

**When a new calendar year begins:** DPSHTRR publishes a fresh Looker report.

1. Open the new Albanian (Shqip) report page in a browser.
2. Go to the "Mjete sipas Lëndës Djegëse" page (same URL slug `VPWqB` may or may not persist).
3. Inspect a `batchedDataV2` network request and extract `REPORT_ID`,
   `PAGE_ID_NUM`, `COMPONENT_ID`, `DATASOURCE_ID`, `REVISION_NUMBER`.
4. Update those constants in `scripts/fetch_albania.py`.
5. Dispatch the workflow with `--year-from <new_year>` to bootstrap the new year.

## 8. Upsert & idempotence

Keyed on `(period, variant)`.  The commit step is change-gated; steady-state
daily runs after a month is already in the CSV are a no-op.  The `--since`
flag (and `--year-from` / `--year-to` arguments) can scope re-runs to specific
ranges.

## 9. Source attribution & footnote

* **`source` column** (`data/Albania.csv`): `dpshtrr.al` for every row.
* **`footnotes.csv`** (`Albania, Whole`):
  > Figures include first registrations of both new and imported used vehicles.
  > Historical series (pre-2026) compiled by R. Andrew from DPSHTRR open data.

## 10. Known quirks and hard-won discoveries

| Quirk | Detail |
|---|---|
| English report broken | `407ce08b-…` fails with `SNAPSHOT_WITH_NON_REAGGREGATABLE`; always use Albanian `233df2cc-…` |
| PREFETCH_VALIDATION | Plain-HTTP `batchedDataV2` POST is rejected; must use real browser session |
| Muaji "only" link | Per-row single-select is `display:none` / `:hover`-gated; force-clicking the label text works |
| Fuel-label inconsistency | DPSHTRR pivot emits different label strings for different window sizes (see §4); descending toggle order is required |
| Timing race | The vehicle×fuel subset arrives seconds after other sub-responses; poll `_parse_fuel_counts(...).total > 0` before recording |
| Ascending toggle = wrong TOTALS | Jan/Feb TOTAL wrong by ~500 cars due to label inconsistency in large-window diffs; descending fixes this |
| LPG is large | Albania has high LPG adoption; `OTHERS` column will be non-trivial |
| Year-scoped report | DPSHTRR publishes a new Looker report each calendar year; `REPORT_ID` et al. must be updated annually |
| revisionNumber | Hard-coded to `16` (2026-06-13); if workflow returns empty data or 4xx, bump it after checking DevTools |
| Data starts 2019-01 | No DPSHTRR open data before 2019 |
