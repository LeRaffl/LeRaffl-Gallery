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
Report:        Albanian (Shqip) report, one per calendar year — see YEAR_REPORTS
               (current year 2026 = 233df2cc-6bd4-45fc-bf9b-e8ee4f83293e)
Page (URL):    VPWqB   ("Mjete sipas Lëndës Djegëse")  — same slug every year
datasourceId:  NOT hardcoded; intercept captures all batchedDataV2 and selects
               the qualifying pivot subset structurally (per-year IDs differ)
Auth:          Real browser session required; plain-HTTP is PREFETCH_VALIDATION-blocked
Approach:      Headless Playwright → intercept batchedDataV2 → Muaji filter differencing
Variants:      Whole (M1, Autoveturë) · HDV (N2+N3, Kamion) ·
               Buses (M2+M3, Autobus) · 2-Wheelers (L, Motor + Ciklomotorr …)
Counts:        All first registrations (new + imported used)
Coverage:      Whole 2019→ (bootstrapped pre-2026 + live current year);
               HDV/Buses/2-Wheelers backfilled 2020–2024 + live current year.
               2025 non-Whole NOT fetched — source snapshots are corrupt (§11).
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
2. Navigate to that year's Albanian report page (report ID from YEAR_REPORTS)
3. Wait 35 s for the initial batchedDataV2 responses (baseline = all months selected)
4. Locate and open the "Muaji" (Month) multi-select filter popup
5. Toggle each month OFF in DESCENDING order (latest first), capturing the
   batchedDataV2 complement response after each toggle
6. Recover single-month counts by differencing consecutive complements
7. Parse vehicle×fuel×count table; sum rows per VARIANT (all four in one pass)
8. Upsert data/Albania.csv (optionally filtered by --variants)
```

## 3. Report internals (reverse-engineered 2026-06-13)

IDs obtained by loading the Albanian report in a browser and inspecting
intercepted `batchedDataV2` network requests.

**Per-year report registry.** DPSHTRR publishes a *separate* Looker report for
each calendar year, each with its own report ID, datasource ID, component ID
and revision number. The script holds these in the `YEAR_REPORTS` dict
(`{year: (report_id, page_slug)}`). Every year uses the **same page slug
`VPWqB`** ("Mjete sipas Lëndës Djegëse", the vehicle×fuel pivot with the Muaji
month multiselect). 2019 is deliberately **omitted** — its report has a
different layout with no Muaji multiselect, so the differencing approach does
not apply.

| Year | Report ID (Albanian / Shqip) | Page |
|---|---|---|
| 2020 | `70f605d5-f454-4776-af73-fdbbcd757bbb` | VPWqB |
| 2021 | `3c73a68e-3df5-4ad4-b210-274b9d274d36` | VPWqB |
| 2022 | `bb9de550-a4cd-45ce-84d5-ec9fa5af028f` | VPWqB |
| 2023 | `78d2f17c-8f62-4b3a-872e-141c0ffecd53` | VPWqB |
| 2024 | `5d405a90-3508-4e91-abec-85ea46cd9426` | VPWqB |
| 2025 | `8d58f55d-117f-4c4e-939a-2b42188966f4` | VPWqB (snapshots corrupt, §11) |
| 2026 | `233df2cc-6bd4-45fc-bf9b-e8ee4f83293e` | VPWqB |
| English (**do not use**, see §1) | `407ce08b-d3ce-478e-9bc7-a50125f875f3` | — |

**`datasourceId` is NOT hardcoded.** Because it differs per year, the intercept
captures *every* `batchedDataV2` response and `_parse_fuel_counts` selects the
qualifying vehicle×fuel pivot subset by structure (a 3-column subset whose
columns sample as vehicle-type / fuel-type / count), not by datasource ID.
`revisionNumber` is likewise read from the page's own requests rather than
pinned.

For reference, the **2026** report's internals were:
`datasourceId 013d0728-f5d3-4599-8899-cfb3f02fa77e`, component `cd-p9hqinijec`,
page numeric `24871631`, revision `16`.

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

**Popup close before toggle loop.**  The code opens the Muaji popup once (to read month labels via JS) and then calls `_open_muaji()` again at the start of every loop iteration.  If the popup is still open from the label-read step when the first `_open_muaji()` fires, clicking the header *closes* it instead of opening it — so the subsequent "May 2026" click lands on a chart label in the report body (not the filter checkbox), fires no `batchedDataV2`, and the first month's complement is never captured.  Fix: press `Escape` after reading labels so the popup is cleanly closed before the loop starts.

**Timing.**  After each toggle, we poll until `_parse_fuel_counts(slice).total > 0`.  The vehicle×fuel "main" subset (`cd-p9hqinijec`) arrives several seconds after the barchart and row-0 sub-responses.  Recording too early captures an incomplete merge and gives zeros.  After the main subset appears, we wait an additional 2.5 s for trailing subsets to settle.

## 5. Fuel-type mapping (Lënda Djegëse → gallery schema)

Derived from DPSHTRR Looker pivot output (applies to every variant's rows).

**Two label dialects.** Reports **≥2023** use mixed-case labels with slash/word
separators (`Naftë`, `Hybrid Benzinë/Elektrik`). Reports **≤2022** use ALL CAPS
with `+` separators (`NAFTË`, `BENZINË+ELEKTRIK`). Both forms are carried in the
mapping sets so one code path covers all years.

| DPSHTRR Lënda Djegëse (≥2023) | ≤2022 ALL-CAPS form | Gallery column | Notes |
|---|---|---|---|
| Elektrik | ELEKTRIK | BEV | |
| Hybrid plug-in, Benzinë/Elektrik | BENZINË+ELEKTRIK+HYBRID | PHEV | petrol PHEV |
| Hybrid plug-in, Naftë/Elektrik | NAFTË+ELEKTRIK+HYBRID | PHEV | diesel PHEV |
| Hybrid Benzinë/Elektrik | BENZINË+ELEKTRIK | HEV | |
| Hybrid Naftë/Elektrik | NAFTË+ELEKTRIK | HEV | mild-hybrid diesel |
| Hybrid Benzinë/Gaz/Elektrik | BENZINË+GAZ+ELEKTRIK | HEV | gas-electric hybrid |
| Benzinë | BENZINË | PETROL | |
| Naftë | NAFTË | DIESEL | |
| everything else (Benzinë/Gaz, Gaz, Metan, LPG, `-`, …) | BENZINË+GAZ, GAZ, NUK KA | OTHERS | LPG / CNG / gas |

Note the ≤2022 `+ELEKTRIK` vs `+ELEKTRIK+HYBRID` distinction: the bare
`+ELEKTRIK` form is the *non-plug-in* hybrid (→ HEV), the `+HYBRID`-suffixed
form is the plug-in (→ PHEV). Getting this backwards swaps HEV/PHEV in the
older years.

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

### Variants & EU category mapping

The same vehicle×fuel pivot carries *all* vehicle types, so every variant is
extracted in **one** browser session (no extra round-trips) — `VARIANTS` maps a
gallery variant to the set of Albanian vehicle-type strings whose rows it sums.

| Gallery variant | EU class | DPSHTRR vehicle-type string(s) |
|---|---|---|
| Whole | M1 | `Autoveturë` / `AUTOVETURË` |
| HDV | N2+N3 | `Kamion` / `KAMION` |
| Buses | M2+M3 | `Autobus` / `AUTOBUS` |
| 2-Wheelers | L | `Motor`/`MOTORË`, `Motor me kosh`, `Motor me tre rrota, simetrike`, `Motor me katër rrota, i lehtë`, `Motor me katër rrota, jo i lehtë`, `Ciklomotorr me dy rrota`, `Ciklomotorr me tre rrota` |

Discovery notes (these cost real time to pin down):

* The motorcycle bulk row is **`Motor`** (`MOTORË` in old reports), *not* the
  textbook Albanian `Motoçikletë` — that string never appears in the pivot.
  Likewise mopeds are **`Ciklomotorr`** (double-r), not `Çikëlomotor`.
* Buses are a single `Autobus` row; there is no separate `Miniautobuz`.
* **No N1 (Vans).** DPSHTRR has no dedicated van/light-commercial category in
  this pivot, so the gallery's Vans variant is **not** produced. The closest
  row is `Automjet për transport të përzier` (~300/month) but its EU mapping is
  ambiguous, so it is left in OTHERS-of-nothing (i.e. unmapped, not emitted).
* The `--variants` flag filters only what gets **written**; parsing/printing
  always covers all four. This let the non-Whole backfill run without touching
  the existing Whole rows.

**Sanity reference:** `robbieandrew.github.io/carsales/albania_carsales_monthly.csv`
(Robbie Andrew's mirror of the same DPSHTRR source, with a different column
schema).  Small deviations (tens of cars per month, < 1 %) are acceptable —
Andrew's series includes LPG as a separate column while we fold it into OTHERS,
and minor retroactive corrections appear in the source.  Large deviations
(hundreds of cars) indicate a parsing or filter regression.

## 7. Historical data (pre-2026)

Each DPSHTRR Looker report is scoped to a single calendar year, but a separate
report exists per year (see the `YEAR_REPORTS` registry, §3). The same
Playwright + Muaji-differencing pipeline therefore works on any listed year.

* **Whole (M1):** bootstrapped 2019→2025 into `data/Albania.csv` from Robbie
  Andrew's pre-parsed mirror of the same DPSHTRR figures, then kept current by
  the live fetch. These rows were left untouched by the multi-variant work.
* **HDV / Buses / 2-Wheelers:** these variants do not exist in Andrew's mirror,
  so they were **backfilled directly** from the per-year DPSHTRR reports for
  **2020–2024** (one-off dispatch:
  `year_from=2020 year_to=2024 variants=HDV,Buses,2-Wheelers`), and are kept
  current by the live fetch. **2019** is excluded (different report layout, no
  Muaji control); **2025** non-Whole is excluded because that year's report
  serves corrupt snapshots (see §11).

**When a new calendar year begins:** DPSHTRR publishes a fresh Looker report.

1. Open the new Albanian (Shqip) report page in a browser.
2. Go to the "Mjete sipas Lëndës Djegëse" page (page slug `VPWqB` has persisted
   across every year so far, but verify it).
3. Inspect a `batchedDataV2` network request and extract the new `REPORT_ID`.
   The datasource ID, component ID and revision number are auto-detected (§3),
   so only the report ID and page slug are needed.
4. Add the `{year: (report_id, page_slug)}` entry to `YEAR_REPORTS` in
   `scripts/fetch_albania.py`.
5. Dispatch the workflow with `year_from=<new_year>` to bootstrap the new year.

## 8. Upsert & idempotence

Keyed on `(period, variant)`.  The commit step is change-gated; steady-state
daily runs after a month is already in the CSV are a no-op.  The `--since`
flag (and `--year-from` / `--year-to` arguments) can scope re-runs to specific
ranges.

## 9. Source attribution & footnote

* **`source` column** (`data/Albania.csv`): `dpshtrr.al` for every row.
* **`footnotes.csv`** — one entry per variant:
  * `Albania, Whole`: pre-2026 historical compiled by R. Andrew from DPSHTRR.
  * `Albania, HDV` / `Buses` / `2-Wheelers`: pre-2026 fetched directly from
    DPSHTRR open data (2020–2024); 2019 and 2025 unavailable.
  * All four note: *figures include first registrations of both new and
    imported used vehicles.*

## 10. Known quirks and hard-won discoveries

| Quirk | Detail |
|---|---|
| English report broken | `407ce08b-…` fails with `SNAPSHOT_WITH_NON_REAGGREGATABLE`; always use Albanian `233df2cc-…` |
| PREFETCH_VALIDATION | Plain-HTTP `batchedDataV2` POST is rejected; must use real browser session |
| Muaji "only" link | Per-row single-select is `display:none` / `:hover`-gated; force-clicking the label text works |
| Fuel-label inconsistency | DPSHTRR pivot emits different label strings for different window sizes (see §4); descending toggle order is required |
| Timing race | The vehicle×fuel subset arrives seconds after other sub-responses; poll `_parse_fuel_counts(...).total > 0` before recording |
| Ascending toggle = wrong TOTALS | Jan/Feb TOTAL wrong by ~500 cars due to label inconsistency in large-window diffs; descending fixes this |
| Muaji popup double-open | `_open_muaji()` called twice in sequence (label-read + first toggle) closes instead of opens the popup; first month click lands on chart body → press Escape after label-read |
| LPG is large | Albania has high LPG adoption; `OTHERS` column will be non-trivial |
| Year-scoped reports | A separate Looker report per calendar year; new years are added to `YEAR_REPORTS` (only report ID + page slug needed) |
| Per-year datasource IDs | datasource/component/revision differ per year and are auto-detected structurally, NOT hardcoded |
| ALL-CAPS labels ≤2022 | Reports ≤2022 emit `AUTOVETURË`/`NAFTË`/`BENZINË+ELEKTRIK` etc.; ≥2023 use mixed case. Both forms are in the mapping sets |
| `Motor` not `Motoçikletë` | The pivot's motorcycle row is `Motor`/`MOTORË`; mopeds are `Ciklomotorr` (double-r). Textbook spellings never appear |
| No N1 / Vans | DPSHTRR has no van category in the pivot; the gallery Vans variant cannot be produced |
| 2025 snapshots corrupt | The 2025 report serves frozen Looker snapshots (every call logs `SNAPSHOT_WITH_NON_REAGGREGATABLE`) that were cached under inconsistent column schemas → fuel columns flip mid-year; 2025 non-Whole is not fetched (§11) |
| Data starts 2019-01 | No DPSHTRR open data before 2019; 2019 report is also un-differenceable (no Muaji) |

## 11. The corrupt 2025 report (why 2025 non-Whole is skipped)

The 2025 report (`8d58f55d-…`) returns internally inconsistent data and is
**deliberately excluded** from the non-Whole backfill. Symptoms, from a debug
dry-run (`ALBANIA_DEBUG=1`):

* **Every** `batchedDataV2` response for 2025 carries an API error
  `SNAPSHOT_WITH_NON_REAGGREGATABLE` — i.e. Looker is serving *pre-computed
  frozen snapshots* rather than re-aggregating live. (This is the same flag
  that makes the English report unusable, §1, but here it appears on the
  Albanian 2025 report's own page requests.)
* Those snapshots were cached at different times under **different column
  schemas**, so the fuel mapping flips mid-year. Cumulative Whole snapshots:
  `A[2025-02]` = `{DIESEL: 4442, BEV: 0}` (plausible Albanian diesel fleet),
  but `A[2025-03]…A[2025-10]` show `BEV` in the tens of thousands and `DIESEL`
  near zero (implausible), then `A[2025-11]/A[2025-12]` snap back to
  diesel-dominant. The same flip corrupts HDV/Buses/2-Wheelers (e.g. HDV shows
  `BEV` dominating from March — impossible for trucks).
* The telescoping difference across the flip boundary produces garbage, e.g.
  `Whole 2025-10 DIESEL=54315` (≈ the whole year's total in one month).

The column-detection and fuel-mapping code is **correct** — the debug log shows
`vehicle_idx=0 fuel_idx=1 count_idx=2` and clean `Naftë→DIESEL`,
`Elektrik→BEV` mappings on every call. The defect is purely server-side in
DPSHTRR's cached snapshots; there is nothing to fix in the script.

**Decision:** leave the existing bootstrapped 2025 **Whole** rows (from Andrew's
mirror) in place and do **not** fetch 2025 HDV/Buses/2-Wheelers. Re-attempt only
if DPSHTRR refreshes the 2025 snapshots (re-run the debug dry-run and confirm
the `SNAPSHOT_WITH_NON_REAGGREGATABLE` errors are gone and the cumulative
columns are monotonic before writing).
