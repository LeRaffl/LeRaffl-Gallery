---
country: Netherlands
slug: netherlands
method: scrape
summary: New-vehicle registrations for the Netherlands, sourced from RDW (the Dutch vehicle authority)
  via the duurzamemobiliteit BI portal.
source_name: duurzamemobiliteit.databank.nl (Swing 7.1, ABF Research)
source_url: https://duurzamemobiliteit.databank.nl/
underlying: RDW — Rijksdienst voor het Wegverkeer
auth: none
cadence: daily cron, 1st–15th of the month
variants:
- Whole
- Used
- HDV
variant_notes:
  Whole: New passenger cars (Instroom Personenauto Nieuw).
  Used: Imported used passenger cars at first Dutch registration (Personenauto Occasion import).
  HDV: New heavy commercial vehicles (Zware bedrijfsvoertuigen) — broader than EU N2/N3.
hev_split: false
fcev: folded into OTHERS (~1 unit/month Whole, ~30/month Used)
backfill: pre-2018 Whole rows from the maintainer's Google Sheet (one-off)
scope_note: HDV ≈ Zware bedrijfsvoertuigen, not a strict EU N-class.
column_map:
  BEV: BEV
  PHEV: PHEV
  Benzine: PETROL
  Diesel: DIESEL
  Overig + FCEV: OTHERS
caveats:
- RDW doesn't split full hybrids; HEV lands in Petrol/Diesel.
- Publication date varies within the first half of the month.
- The portal blocks GitHub Actions and Cloudflare IPs; data is fetched via a Deno Deploy relay.
fetcher: scripts/fetch_netherlands.py
workflow: .github/workflows/fetch-netherlands.yml
fragility_doc: docs/architecture/10-source-netherlands.md
data_file: data/Netherlands.csv
market_breakdown: market/netherlands_top.json
market_designation_note: a "designation" is RDW's trade name with the brand prefix and the engine, power and trim codes removed, so the versions of one model rank together (ID.4 PRO 210KW and ID.4 GTX → ID.4).
market_powertrain_note: Powertrain from RDW's fuel table — BEV is electricity as the only fuel, PHEV an externally chargeable hybrid; full hybrids are not split, as in the charts. Counted from the register record by record, so a month can differ from the chart's total by about 1–3 %.
---

# 10 · Source: Netherlands (duurzamemobiliteit.databank.nl / RDW)

The Netherlands pipeline is more involved than most other countries because
the upstream data is served from a proprietary BI tool, not a static Excel
or open CSV. This document records what we built, why, and how to maintain
or extend it. Audience: future contributors and LLMs picking the work up
cold.

> The same playbook is the template for Denmark, Sweden, Finland, Norway
> (planned), which all expose their registration data via BI portals rather
> than flat files. Re-use the patterns; don't expect identical endpoints.

## TL;DR

```
Source:    duurzamemobiliteit.databank.nl (Swing 7.1, vendor: ABF Research)
           Underlying data: RDW (Rijksdienst voor het Wegverkeer)
Auth:      None required (anonymous session; the server sets swing_* cookies)
API:       Three saved Swing workspace templates, opened like the viewer's SPA:
           GET /viewer?workspace_guid=T → POST api/workspace/<ws>/presentationfromurl
           → GET api/workspace/<ws>/presentation/<id> (table JSON). Since 2026-09;
           the old GetTableStart flow answers 404.
Variants:  Whole, Used, HDV   (three separate CSV files)
HEV:       Not split by RDW (folded into Benzine/Diesel upstream); no HEV column
FCEV:      Folded into OTHERS (~1 unit/month for Whole; ~30/month for Used)
Backfill:  Pre-2018 Whole rows from the maintainer's Google Sheet (one-off)
Schedule:  Daily cron 1st–15th, 06:30 UTC; early-exit per variant once last month is in
Scripts:   scripts/fetch_netherlands.py   (monthly scraper)
           scripts/backfill_netherlands_pre2018.py  (one-off)
Workflow:  .github/workflows/fetch-netherlands.yml
IP block:  duurzamemobiliteit.databank.nl blocks GitHub Actions Azure IPs
           (TCP-drop, errno 101) AND Cloudflare egress IPs (HTTP 403).
           Fix: route via a Deno Deploy relay (Google Cloud egress). See §13.
           The relay must be the 2026-09 version (POST support) — the SPA's
           API is POST/JSON.
Secrets:   NL_FETCH_RELAY  — https://<project>.deno.dev/fetch?url=
           NL_RELAY_TOKEN  — shared secret set in Deno env + GitHub secret
           NL_PROXY        — optional socks5/http proxy (overrides relay)
```

## 1. Why this is hard

`duurzamemobiliteit.databank.nl` is a [Swing 7.1](https://www.abfresearch.nl/)
dashboard ("Swing" is ABF Research's product, formerly named "Jive" — both
strings appear in the URLs and JS bundles). It has no documented public API,
no OData/JSON-Stat endpoint, and no per-country CSV downloads at stable URLs.

The UI does expose a CSV export button per pivot, but the export is gated
behind a session-bound workspace handle that doesn't survive a fresh `curl`
unless you replay a specific sequence of dimension-selection calls. We tried
both paths:

| Approach | Verdict |
|---|---|
| Reverse-engineer the JSON endpoint and replay dimension-toggle calls | Works but ~12 HTTP calls per variant in a brittle ordering; breaks if Swing changes any one item code |
| Have the maintainer save a permalink per variant in the Swing UI and open each one | Picked. 3 HTTP calls per variant (§2). The saved permalinks (`?workspace_guid=...`) are stable as long as nobody deletes them in the maintainer's Swing account — they survived the September 2026 viewer migration |
| Use CBS Statline OData as an alternative source | Rejected — different granularity, ~6 week publication lag, and doesn't split Used / HDV the way we need |

## 2. The Swing endpoint flow

Each variant maps to one saved-permalink URL of the form:

```
https://duurzamemobiliteit.databank.nl/viewer?workspace_guid=<TEMPLATE_GUID>
```

Since **September 2026** the viewer is a client-side SPA with a REST/JSON API
(`/viewer/api/…`). Opening a permalink is no longer done by the server: the
page only creates an anonymous **session workspace**, and the SPA's own
JavaScript then asks the API to copy the saved workspace into it. The fetcher
does exactly what the SPA does (`open_presentation`):

```python
# 1. Hit the permalink with an empty cookie jar (relay: 302 → /viewer/account/login
#    → 302 back). Cookies: .AspNetCore.swing_auth_viewer, swing_token, swing_profile, …
GET /viewer?workspace_guid=<TEMPLATE_GUID>
    → HTML with   Globals.workspaceId = "<SESSION_WS>"   and  <html data-page-type="Index">

# 2. Ask the API to open the saved workspace in the session workspace. The SPA sends
#    every query parameter of its URL as "entries"; there is only workspace_guid.
POST /viewer/api/workspace/<SESSION_WS>/presentationfromurl
     headers: Content-Type: application/json, X-Page-Type: Index, Referer, Origin,
              (__RequestVerificationToken if the page has that input — it does not today)
     body:    {"entries": {"workspace_guid": "<TEMPLATE_GUID>"}}
    → {"presentationID": "<id>", "isValid": true, …}

# 3. Read the presentation. It carries the whole table — no paging.
GET /viewer/api/workspace/<SESSION_WS>/presentation/<id>
    → {"title": "Instroom Personenauto Nieuw - Nederland",
       "info": {"period": "30 september 2023 - 31 augustus 2026", "source": "Brondata: RDW - Bewerkt door: RVO"},
       "table": {"colCount": 6, "headColCount": 1, "headRowCount": 1,
                 "columnHeaderRows": [{"cells": [{"text": "Maand"}, {"text": "BEV"}, …]}],
                 "rows": [{"cells": [{"text": "30 september 2023"}, {"text": "10.075"}, …]}]}}
```

`colCount` counts the **value** columns (Whole 6, Used 12); every header level
and row carries `headColCount + colCount` cells. `swing_table_to_legacy` checks
that and raises if a level or row does not add up, instead of letting labels
slide. Where a header cell spans columns (Used: each fuel over `> 90 dgn` /
`<= 90 dgn`, `colSpan: 2`) the payload already contains the empty type-4
continuation cell behind it — adding them again once shifted every fuel two
columns while the totals still matched (found by the first dry run).

The endpoints, headers and request bodies were read from the viewer's own
bundle (`/viewer/js/common.js`: `addPresentationFromUrl`, the `fetch` wrapper
that adds `X-Page-Type` and `__RequestVerificationToken`) with the workflow's
probe mode (§11). `GET …/presentationfromurl` answers 405 — it is POST only, so
the relay has to forward POSTs (§13).

**Important nuance**: the `?workspace_guid=...` in the URL does *not* survive
into the session as-is. The GUID in the page (`Globals.workspaceId`) is a fresh
session workspace, different on every request; the template GUID only travels
in the POST body. So if you log the HTTP traffic you will see two different
GUIDs, exactly as before the migration.

### History: the old flow (until 2026-09)

Swing 7.1 rendered the workspace on the server: `GET /viewer?workspace_guid=T`
returned HTML with `WsGuid: "<session>"` and the pivot came from
`GET /viewer/Presentation/GetTableStart?workspaceGuid=<session>` (first ~70 rows)
plus `GetTableRows` for the rest, as `{headRows, headCols, rowData}`. The viewer
was migrated to the SPA in early September 2026; from 2026-09-05 every run failed
(`WsGuid not found`), and a first debugging attempt that only swapped in
`Globals.workspaceId` ended in a 404 on `GetTableStart`, which is gone. The
parsers still expect the old `{headRows, headCols, rowData}` shape — the adapter
`swing_table_to_legacy` produces it from the new JSON, so Whole, Used and HDV kept
their parse path.

## 3. The three variants and why we split them

| Variant | File | Display label | Swing pivot | Saved permalink |
|---|---|---|---|---|
| `Whole` | `data/Netherlands.csv` | Netherlands | Instroom Personenauto Nieuw | `29fcfefb-b82b-47cb-a601-b7c31ebd2901` |
| `Used` | `data/Netherlands_Used.csv` | Netherlands (Used) | Personenauto Occasion import (sum of `> 90 dgn` and `<= 90 dgn`) | `7f40022a-d4cf-4030-abaf-adf5edf412b3` |
| `HDV` | `data/Netherlands_HDV.csv` | Netherlands (HDV) | Zware bedrijfsvoertuigen Nieuw | `3ca8fa6f-52a6-4b29-8f43-7bae5200c74c` |

> **Period dimension — use the rolling window, not a fixed month list.**
> The original permalinks (`a7d36cf5…`, `ffaf2d83…`, `992eb09a…`) had a
> *static* month selection that silently capped at 2026-04: the fetch kept
> succeeding but never saw newer months, because opening the saved workspace
> reproduces exactly the months that were ticked when it was saved. Re-saved
> 2026-07 using Swing's **"last N months" option (N=36)**, which is dynamic —
> new months appear automatically. If you ever re-save these, keep the rolling
> window; don't tick individual months. The 36-month window always overlaps
> the CSV's existing tail and `upsert` never deletes rows, so the pre-2018-→
> history is untouched.

### Why three CSV files instead of one with a `variant` column

The architecture (see [03-data-objects.md](03-data-objects.md)) anticipated
per-variant files but had not activated them. Netherlands is the first
country to use the new layout because the maintainer wanted Used and HDV
to feel like distinct entries in the gallery (separate ranking rows,
separate trajectory pages, separate post text), and because the previous
single-CSV approach had two practical pain points:

1. PR diffs touched all three slices even when only one variant updated.
2. The `render-country.yml` dropdown could pick a variant that didn't exist
   in the CSV, producing a confusing "no rows for variant 'Foo'" stop
   instead of the much clearer "missing data file: data/Foo_Bar.csv" stop.

[R/render_country.R](../../R/render_country.R) resolves
`data/<Country>_<Variant>.csv` first and falls back to
`data/<Country>.csv` so countries that haven't migrated yet still work.

### Why "Used" and not "Used Imports"

Earlier the variant was called "Used Imports" in `params.csv` (matching
the literal Dutch UI label "Occasion import"). The maintainer wanted the
shorter "Used" in the UI dropdown and in the gallery card title. The
variant key, the CSV filename, the `params.csv` row, the `weights.csv`
row, and the flag asset (`assets/flags/netherlands_used.png`) all carry
the short name. There is no override map keeping the long name alive
elsewhere — search-and-replace was the cleanest path.

### Why "HDV" maps to *Zware bedrijfsvoertuigen* and not *Vrachtauto*

"Heavy Duty Vehicle" has no perfect single-category equivalent in the RDW
taxonomy. The closest single bucket is *Zware bedrijfsvoertuigen* (heavy
goods vehicles, conceptually N-class trucks at ≥3500 kg). This is an
approximation: it under-counts a few edge categories (buses) and isn't
strictly aligned with the EU N-class definitions other country sources use.
For the gallery's cross-country HDV ranking the approximation is
acceptable. Revisit if a stricter definition becomes important.

## 4. Column mapping

Source columns (Swing pivot, Dutch labels) → canonical CSV columns:

| Swing label | Canonical column | Notes |
|---|---|---|
| `BEV` | `BEV` | |
| `PHEV` | `PHEV` | |
| `Benzine` | `PETROL` | Includes petrol-HEV (RDW doesn't split full hybrids out) |
| `Diesel` | `DIESEL` | Includes diesel-HEV |
| `Overig` + `FCEV` | `OTHERS` | FCEV folded — single-digit units/month for Whole, ~30/month for Used. Negligible effect on the ICE/BEV trajectory and the headline TTM stack. |
| (none) | `HEV` | **Always blank** — see "HEV gap" below |

### The HEV gap

The Swing pivots do not separately show full-hybrid registrations. They land in
the `Benzine` or `Diesel` bucket. (The record-level open-data fuel table
*does* flag them — `NOVC-HEV` — see §11b; the CSV keeps the pivots' convention.)
The downstream effect is that:

- The TTM stacked-shares plot for Netherlands has no HEV slice (correct —
  it really isn't reported).
- The social-media post text drops the "(of which X%p were HEV)" annotation.
  This is automatic via [`R/post_text.R::.pt_pp_if`](../../R/post_text.R)
  which only emits the parens when `extra_value > 0`.
- The headline ICE/BEV/PHEV trajectory is unaffected, because ICE share is
  computed as `(TOTAL - BEV - PHEV - EREV) / TOTAL` — the breakdown
  *within* ICE doesn't change the curve.

If RDW ever adds an HEV split, the scraper's `FUEL_MAP` and the
`to_csv_rows` function need one new entry and the post text starts emitting
the HEV line automatically.

### Number formatting

Dutch locale: `.` is the thousands separator (so `"10.075"` is ten-thousand-
seventy-five, not 10.075). Empty cells are the empty string (the old viewer
rendered them as the HTML entity `"&nbsp;"`, still accepted). Both are handled
by `parse_nl_number`.

## 5. Table orientations

The saved views come back in one of these orientations. The SPA's JSON is first
mapped onto the shape below (`swing_table_to_legacy`: `headRows` = the first
`headColCount` cells of each row, `headCols` = one list per `columnHeaderRows`
level without the corner cell, `rowData` = the value cells), so one parser reads
all of them:

| Orientation | Returned for | `headRows` contains | `headCols` contains |
|---|---|---|---|
| Periods-in-rows, one col/fuel | Whole, HDV | Period labels (`"31 januari 2018"` …) | Fuel labels (one level) |
| Periods-in-rows, fuel × sub-col | **Used (current)** | Period labels | Fuels on the **outer** level, each spanning two sub-columns (`Occasion import > 90 dgn` / `<= 90 dgn`) — summed |
| Fuels-in-rows | Used (legacy template) | Fuel labels (`BEV`, `FCEV`, `PHEV` …) | Period labels + `> 90`/`<= 90` sub-categories (two levels) |

`parse_table` first checks whether the first `headRows` entry is a fuel
(`NL_FUELS`) → fuels-in-rows (`_parse_fuels_in_rows`); otherwise
periods-in-rows (`_parse_periods_in_rows`). The periods-in-rows parser finds
whichever `headCols` level actually carries fuel names, propagates each fuel
label across the sub-columns it spans (blank cell = span continuation), and
sums columns per fuel — so it handles both Whole/HDV (one column per fuel)
and Used (two `> 90`/`<= 90` sub-columns per fuel).

> **Watch the Used orientation when re-saving.** Re-saving the Used workspace
> with the rolling-36-month window (2026-07) flipped it from *fuels-in-rows*
> to *periods-in-rows with fuel sub-columns*. The parser now handles that, but
> it silently produced **0 rows** until fixed — see the "variant parses 0 rows"
> diagnostic in `main()`, which dumps the pivot shape when this recurs.

## 6. Backfill: pre-2018 history

The Swing dataset only goes back to 2018-01 (a Swing-side configuration —
not all years are available in the public templates). The maintainer's
[Google Sheet](https://docs.google.com/spreadsheets/d/1tT_Ja3de_S528_JeSBkj74q-lfEIekE5-GRm9_pWgUo/)
has Whole monthly data back to 2011-01. Without backfilling, fitting the
regression on Swing-only data would shift the baseline year `t0` from
2010 to 2018 and visibly alter the published trajectory (the `t0` for
the BEV regression curve is `floor(min(year))`, see [R/fit.R:10](../../R/fit.R)).

[`scripts/backfill_netherlands_pre2018.py`](../../scripts/backfill_netherlands_pre2018.py)
is the one-off, idempotent merge:

- Reads the "Netherlands" tab as CSV via the
  `https://docs.google.com/spreadsheets/d/<ID>/gviz/tq?tqx=out:csv&sheet=<name>`
  endpoint (works because the sheet is shared as "anyone with the link can
  view").
- Filters to `period < 2018-01` (the cutoff matching the Swing dataset's
  start so backfill and live data never overlap).
- Existing `(period, "Whole")` rows in `data/Netherlands.csv` are left
  untouched; only the 84 missing pre-2018 rows are added.
- Pre-2018 rows have **only** `BEV`/`PHEV`/`TOTAL`; `PETROL`/`DIESEL`/`OTHERS`
  are blank (those splits weren't tracked at the time). The downstream BEV/
  PHEV/ICE math still works because ICE share is derived from TOTAL minus
  the EV columns. The TTM stacked-shares plot starts later (2019-01) because
  `compute_ttm_long` requires every present fuel column to have a complete
  12-month rolling window.

`Used` and `HDV` sheet tabs both start 2018-01 (same as Swing) so this
script does not touch those variants.

Run on-demand:
```sh
python scripts/backfill_netherlands_pre2018.py
```

Re-running is safe — adds 0 new rows on a no-op pass.

## 7. Schedule and idempotency

`fetch-netherlands.yml` runs:

- **Daily 1st–15th at 06:30 UTC** (`cron: '30 6 1-15 * *'`). RDW's monthly
  publication date isn't fixed — sometime in the first half of the month.
  Daily polling within that window catches the new data on the day it
  appears.
- **06:30 UTC** is chosen to clear `fetch-brazil.yml`'s 08:00 UTC slot.
- The saved views are a rolling 36 months (`30 september 2023 - 31 augustus 2026`
  on 2026-09-28), so a run after an outage backfills every missed month on its own
  — the September 2026 outage (Jul + Aug) needed no manual catch-up.
- After day 15, the cron sleeps for the rest of the month.

The scraper's `previous_month_period()` + `csv_has_period` short-circuit:
once a variant's CSV already contains last month's row, that variant is
skipped without any HTTP call. On most days the run is a sub-second no-op.
Use `--force` to override (e.g. when RDW restates an older month and you
want it picked up the same day).

Change detection uses `git add -N` to make `git diff` include untracked
new files (so the first run when a CSV doesn't exist on master yet still
triggers renders). Only variants whose CSV actually changed get a
`render-country.yml` dispatch.

## 8. Workflow data flow

```mermaid
flowchart TD
    Cron["Cron 1-15 * 06:30 UTC<br/>or workflow_dispatch"]
    Cron --> Fetch["scripts/fetch_netherlands.py"]
    Fetch -->|"per variant"| Swing["duurzamemobiliteit.databank.nl<br/>Swing template GUID"]
    Swing -->|"JSON pivot"| Fetch
    Fetch -->|"upsert"| W["data/Netherlands.csv"]
    Fetch -->|"upsert"| U["data/Netherlands_Used.csv"]
    Fetch -->|"upsert"| H["data/Netherlands_HDV.csv"]
    W -.->|"if changed"| GA["EndBug/add-and-commit"]
    U -.->|"if changed"| GA
    H -.->|"if changed"| GA
    GA --> Dispatch["gh workflow run render-country.yml<br/>(once with the touched variants)"]
    Dispatch --> Render["R/render_country.R<br/>(four PNGs + params.csv + weights.csv + post)"]
```

## 9. Plot palette alignment

The TTM stacked-shares plot and the ICE/BEV/PHEV three-curve plot use the
same color values as the Fleet tab on the gallery page so the static PNGs
and the live HTML plot read as one visual language. See `TTM_FUEL_COLORS`
and `TRAJ_COLORS` at the top of [R/plots.R](../../R/plots.R). The
ground-truth values are the `colorMap` and top-level `COLORS` constants
near lines 1765 and 4078 of [index.html](../../index.html). If those
change, mirror the change in plots.R.

## 10. Known fragility

| Failure mode | What happens | Diagnostic |
|---|---|---|
| **Persistent** Azure IP block (`errno 101` / TCP connection drop) | All three fetch attempts fail; job fails after retry sequence | Confirmed as persistent from 2026-06-01. Fix: relay via Deno Deploy (§13). Not a transient network blip — the host silently drops TCP from GitHub's Azure ranges. |
| Relay also blocked (403 from Cloudflare egress IPs) | `_get()` returns a 403 from the relay; job fails | The Austria CF Worker relay returns 403 in ~400 ms — the host blocks Cloudflare IP ranges too. Use the Deno Deploy relay (Google Cloud egress) or `NL_PROXY` instead. |
| Deno Deploy relay unavailable or misconfigured | `_get()` raises a connection error against the Deno URL | Check `NL_FETCH_RELAY`/`NL_RELAY_TOKEN` secrets. Re-deploy `worker/deno-relay.ts` at dash.deno.com. See §13. |
| Relay reaches databank.nl but returns 500/512 | Fetch fails right after `[Whole] init:`; the Python side prints the relay response body | A crash *inside* the relay (not a block). A plain `Internal Server Error` body = Deno-runtime throw; a `relay handler error: …` body = caught with stack. Usually a `worker/deno-relay.ts` change that wasn't redeployed to the playground. See §13 "Two relay bugs". |
| Maintainer deletes a saved permalink in Swing | `presentationfromurl gave no valid presentation (…)` for that variant | Look at the failing variant in the Action log; recreate the permalink in the Swing UI; update `TEMPLATES` in `fetch_netherlands.py` |
| Swing changes the viewer page again | `Globals.workspaceId not found in /viewer` | Run the workflow with `probe` (structure + bundle strings) and `probe_grep` / `probe_get` (§11); the flow in §2 was read that way |
| Swing changes an API path or body | HTTP 4xx from `presentationfromurl` / the presentation GET | Same probe; `addPresentationFromUrl` in `/viewer/js/common.js` is the reference |
| Relay predates POST support | `presentationfromurl` answers 404 (`Not found`) | Redeploy `worker/deno-relay.ts` (§13) — it must be the 2026-09 version |
| Swing changes the table JSON shape | `Swing header level has N columns, the table declares M` / `Swing row i has …` | Run `probe_open` (prints title, dimensions, header levels and sample rows) and adapt `swing_table_to_legacy`. Deliberately a hard error: a shifted label once mis-assigned every fuel while the totals still matched. |
| Swing changes the pivot layout of a variant | Parser returns 0 rows or fails noisily; render aborts before commit | `probe_open` with the `variant` input; adapt `parse_table` / `_parse_periods_in_rows` / `_parse_fuels_in_rows` |
| RDW retroactively restates a month with values that differ >50% from what's in the CSV | Upsert prints `WARNING` to the action log but still commits the new values | Decide whether the restatement is real and revert with a manual edit if not |
| Google Sheet revoked from "anyone with the link" | Backfill script fails with a Google login HTML response | Re-share the sheet, or hardcode the pre-2018 history into a static CSV |
| The maintainer reconfigures a saved Swing template (e.g. drops a year, changes Aandrijfcategorie selection) | Scraper succeeds but produces wrong-shaped data | The "Captured caption" line in the action log doesn't match `Instroom Personenauto Nieuw - Nederland`. Re-save the workspace with the correct configuration. |
| **Silent period cap** — a saved workspace with a *static* month list stops at the last month that was ticked when saved | Scraper keeps succeeding (`committed: false`, render skipped) but the CSV never advances — looks exactly like "source hasn't published yet" | The `[Whole] parsed … (2018-01 .. YYYY-MM)` line in the log shows a max period that stops advancing while the portal (opened in a browser) has newer months. Fix: re-save the 3 workspaces with the **rolling "last N months"** option, not individual month ticks (see §3). This bit us 2026-07 — the fetch had silently capped at 2026-04 for months. |

## 11. Maintenance recipes

### Rotate one of the three Swing template GUIDs

1. Open the existing permalink in a logged-in Swing UI session, click the
   pencil/edit icon to adjust the pivot (e.g. add a newly-available year).
2. Click the share icon (chain links). Swing saves the modified workspace
   and shows a new permalink URL with a new `?workspace_guid=...`.
3. Replace the corresponding entry in `TEMPLATES` in
   [`scripts/fetch_netherlands.py`](../../scripts/fetch_netherlands.py).
4. Commit. Next run uses the new GUID.

### Add a fourth variant (e.g. Buses, Motorcycles)

1. In Swing, set up the pivot with the desired `Voertuigsoort` /
   `Aanvoertype` / `Aandrijfcategorie` combination and full-year range.
2. Share-icon → permalink.
3. Add a new entry to both `TEMPLATES` and `CSV_PATHS` in the scraper.
4. Add the variant name to the `render-country.yml` choice list.
5. Add a flag asset at `assets/flags/netherlands_<lowercase variant>.png`.
6. Update this doc's variant table.

### Re-deploy the Deno relay after expiry or rotation

1. Generate a new random token: `python3 -c "import secrets; print(secrets.token_hex(32))"`.
2. Update `RELAY_TOKEN` in Deno Deploy project settings.
3. Update the `NL_RELAY_TOKEN` GitHub secret to match.
4. No code change needed; the relay reads the token from the env at request time.

If the project URL changed (e.g. new deployment), also update `NL_FETCH_RELAY`.

### Force-refetch an older month (RDW restated something)

```sh
python scripts/fetch_netherlands.py --variant whole --force
```

The `--force` flag skips the early-exit check; the scraper re-fetches all
available months and the upsert overwrites existing rows (logging a
WARNING for any cell that moved by >50%).

### Diagnose the portal (workflow inputs)

The portal drops datacentre IPs (§13), so diagnostics run where the relay
secrets are: `fetch-netherlands.yml` → *Run workflow*, on the branch to test.
Probe runs skip change detection and the commit, so nothing is written.

| Input | What it does |
|---|---|
| `dry_run` | Fetch and parse all variants, print per variant which months are `NEW`, which `CHANGED` (cell by cell, old→new) and how many are identical to the CSV. Writes nothing, no render, no top-brands refresh. The way to check a repair against the historic CSV. |
| `probe_open` (+ `variant`) | Open that variant's workspace like the SPA and print title, period, table dimensions, the header levels and sample rows. Needs the POST-capable relay. |
| `probe` | Structure of the page: `Globals.*`, script tags, and the URL-like strings / ajax call sites of the same-origin bundles. |
| `probe_grep` | With `probe`: regexes (separated by `\|\|`) — prints the bundle code around each match. |
| `probe_get` | With `probe`: API paths to GET through the relay; `{ws}` = the session workspace id, `{pres}` = its first presentation, `{tpl}` = the Whole template GUID. |

Example that found the whole SPA flow: `probe` + `probe_grep`
`presentationfromurl||apiUrl||method:"POST"` + `probe_get`
`/viewer/api/configuration /viewer/api/workspace/{ws}`.

### Validate the flow by hand

Only from a network the portal does not block (a home connection, not a cloud VM):

```sh
T=29fcfefb-b82b-47cb-a601-b7c31ebd2901          # Whole template
curl -sL -c /tmp/c "https://duurzamemobiliteit.databank.nl/viewer?workspace_guid=$T" -o /tmp/p.html
WS=$(grep -oE 'Globals.workspaceId = "[0-9a-f-]+"' /tmp/p.html | grep -oE '[0-9a-f-]{36}')
curl -s -b /tmp/c -H 'Content-Type: application/json' -H 'X-Page-Type: Index' \
  -d "{\"entries\":{\"workspace_guid\":\"$T\"}}" \
  "https://duurzamemobiliteit.databank.nl/viewer/api/workspace/$WS/presentationfromurl"
# → {"presentationID":"…","isValid":true,…}
curl -s -b /tmp/c "https://duurzamemobiliteit.databank.nl/viewer/api/workspace/$WS/presentation/<presentationID>" \
  | python3 -m json.tool | head -60
# → title, info.period, table.columnHeaderRows, table.rows
```

If step 2 says `"isValid":false`, the template GUID is gone. If step 1 leaves
`$WS` empty, Swing changed the page.

## 11b. Top brands / models (`market/netherlands_top.json`)

The Swing pivots carry no make. The same register is published record by record
as RDW open data (`opendata.rdw.nl`, Socrata, no key, no relay — RDW's open-data
host is not blocked from GitHub the way the BI portal is), so
`refresh_top()` in `scripts/fetch_netherlands.py` builds the source page's "Who
sells the electrified cars" section from it. Whole only; classes BEV and PHEV.

| Piece | Dataset | Used for |
|---|---|---|
| Gekentekende voertuigen (`m9d7-ebf2`) | one row per plate | scope filter, `merk` (brand), `handelsbenaming` (trade name) |
| …brandstof (`8ys7-d773`) | one row per plate × fuel | class: `brandstof_omschrijving`, `klasse_hybride_elektrisch_voertuig` |

**Scope — rebuilding the Swing "Personenauto Nieuw" instroom.**
`voertuigsoort = Personenauto`, first registration in NL inside the month
(`datum_eerste_tenaamstelling_in_nederland_dt`) **and** first admission in the
same month (`datum_eerste_toelating_dt`; an earlier admission means a used
import), `export_indicator = Nee`. Tested against the CSV on 2026-09-28: every
month of 2025-07 → 2026-06 within −0.8 % … +1.9 % of `data/Netherlands.csv`
(RDW is a live register, Swing a fetch-time snapshot), the window as a whole
+0.3 % (BEV +0.1 %, PHEV +2.2 %). Looser scopes miss by 3–60 % (first
admission alone: +6 %; first registration alone: +70 %, it contains every used
import). `market_top.check_scope` logs every month and stops the refresh if the
window drifts more than 10 % — a changed scope must not publish tables that no
longer describe the charts.

**Class — the CSV's split.** BEV = electricity as the only fuel row; PHEV = a
fuel row with `klasse_hybride_elektrisch_voertuig = OVC-HEV`. Full hybrids
(`NOVC-HEV`, about a quarter of the market) are *not* ranked, exactly as the CSV
folds them into petrol/diesel (see "The HEV gap": the Swing pivots do not split
them; the open-data fuel table would allow it, and adding an HEV class here
would be one line in `powertrain_class` — but then the charts and the tables
would disagree). Fuel-cell cars are OTHERS in the CSV and not ranked. A plate
without a fuel row counts in the total only.

**Cost and store.** The fuel table cannot be joined server-side (Socrata
answers "joins are not supported"), so a month's ~30 000 plates go in as `IN`
lists of `FUEL_BATCH` = 800 (the URL limit is ~1 000): ~40 queries, about a
minute. `market/netherlands_months.json` (the month store of
`market_top.py`) keeps every month already read, so a normal run reads only the
month the CSV just gained; the first run reads twelve (about 12 minutes). RDW
answers an occasional HTTP 500 — `rdw_get` retries five times with backoff.

**Display names.** Only the table sees them. `merk` has a few duplicate
spellings (`DS AUTOMOBILES` → `DS`, `LYNK&CO` → `LYNK & CO`);
`handelsbenaming` is the type-approval trade name with engine, power and trim
(`ID.4 PRO 210KW`, `IX3 50 XDRIVE`, `CLA 250+`, `Q3 200KW TFSI E`), so
`display_model` removes the brand prefix, power figures and equipment words and
applies a few per-brand rules (BMW/Porsche: first word; Mercedes: letters up to
the first number; Audi: family + `E-TRON`; Škoda: number suffixes). Versions of
one model then rank together (ID.4 PRO / PURE / GTX → `ID.4`). It is a
heuristic: a new naming scheme shows up as a stray row, never as a wrong
number; extend `display_model` and re-run with an empty store
(`rm market/netherlands_*.json`) to re-key history.

**Also in the register:** motorhomes (`ADRIA`, `HYMER`, …) are `Personenauto`
with a camper body and are in the total like in Swing; they are diesel, so
they never reach the BEV/PHEV lists.

Runs with the daily fetch, behind `market_top.guarded`, and alone when the
data is current but the top file is not; `--no-top` skips it.

## 12. What is **not** in this pipeline

- Authentication. JIVE_AUTH is a server-side anti-CSRF token, not a user
  credential. The whole flow works for any anonymous client. Do not commit
  the maintainer's logged-in cookies anywhere.
- A non-Swing fallback. If Swing is persistently unreachable, there is no
  automatic switch to CBS Statline or anywhere else. Connection errors are
  retried; a failure that survives all retries fails the action. If the
  relay is also blocked, the maintainer must fix the routing (see §13).
- Real-time updates. The cron is daily, not hourly. There is no webhook
  from RDW or Swing.
- Backfill for Used/HDV before 2018. The maintainer's sheet doesn't have
  those slices that far back. They start 2018-01 in both the sheet and
  Swing.

## 13. IP routing and relay architecture

### The blocking problem (observed 2026-06-01)

`duurzamemobiliteit.databank.nl` (hosted in the Netherlands) began silently
dropping TCP connections from GitHub Actions (Azure) IP ranges on or around
2026-06-01, producing `[Errno 101] Network is unreachable` after a ~25 s
IPv4 connect timeout. Nine consecutive daily runs failed before diagnosis.

Investigation showed:
- **GitHub Actions Azure IPs**: TCP-dropped (errno 101).
- **Cloudflare egress IPs** (CF Worker relay used for Austria): HTTP 403
  returned in ~400 ms. The host blocks Cloudflare CDN ranges too.
- **Anthropic API infrastructure**: HTTP 403 (same block list).
- **Google Cloud egress** (Deno Deploy): not (yet) blocked — confirmed by
  successful test fetches.

### Solution: Deno Deploy relay (`worker/deno-relay.ts`)

`worker/deno-relay.ts` is a Deno Deploy serverless function that speaks the
same `/fetch?url=<encoded>` contract as the Austria CF Worker
(`worker/index.js`). Because Deno Deploy's free tier egresses from **Google
Cloud** IP ranges rather than Cloudflare or Azure, it is not caught by the
current block.

The relay is session-aware (required for Swing's JIVE_AUTH cookie flow):

| Header from client → relay | Forwarded upstream as |
|---|---|
| `X-Relay-Token` | auth check against `RELAY_TOKEN` env var |
| `X-Fwd-User-Agent` | `User-Agent` |
| `X-Fwd-Cookie` | `Cookie` |
| `X-Fwd-Referer` | `Referer` |
| `X-Fwd-Accept-Language` | `Accept-Language` |
| `X-Fwd-Content-Type` | `Content-Type` (POST bodies) |
| `X-Fwd-Accept` | `Accept` (default `text/html,…`) |
| `X-Fwd-Page-Type` | `X-Page-Type` (Swing SPA) |
| `X-Fwd-Antiforgery` | `__RequestVerificationToken` (Swing SPA) |
| `X-Fwd-Origin` | `Origin` |
| ← `X-Upstream-Set-Cookie-B64` | upstream `Set-Cookie` headers, `\n`-joined **then base64-encoded** |

**GET and POST.** Until 2026-09 the relay only forwarded GET (a `POST` answered
404). The SPA's API needs POST, so `POST /fetch?url=…` now forwards the request
body and the headers above; anything else still answers 404, and only these
headers travel (the relay stays a narrow, host-allowlisted pipe). The change is
backward compatible — a GET without the extra headers behaves as before — and
was tested locally with Deno against a fake upstream (GET unchanged, POST
forwarded, PUT rejected) before it was deployed. **The relay is not deployed by
CI: after editing `worker/deno-relay.ts` paste it into the Deno Deploy playground
and *Save & Deploy* (§ "Setting up the Deno Deploy relay").**

`scripts/fetch_netherlands.py::_get()` (GET) and `_post_json()` (POST) transparently
use the relay when `session.relay_base` is set, accumulating upstream cookies in
`session.relay_cookies` across the bootstrap → presentationfromurl → presentation
call sequence. It base64-decodes `X-Upstream-Set-Cookie-B64` (falling back to
a plain `X-Upstream-Set-Cookie` header for the single-cookie CF-worker path).

### Two relay bugs found on first live run (2026-07, fixed)

The relay reached databank.nl on the first try but its *response handling*
crashed, so the fetch still failed. Both bugs are fixed in `worker/deno-relay.ts`;
recorded here because they're easy to reintroduce when porting the relay:

1. **Opaque `500 Internal Server Error`.** `Headers.getSetCookie()` isn't
   available in the Deno Deploy runtime; calling it threw a `TypeError` that
   surfaced as a generic Deno 500. Fixed with a `readSetCookies()` helper
   (uses `getSetCookie()` when present, else the combined header) and a
   top-level `try/catch` that returns a readable `512` + stack instead of an
   opaque 500. The Python side prints the relay response body on any non-200
   init — that diagnostic is what made both bugs visible.
2. **`TypeError: Invalid header value`.** databank.nl returns **6** session
   cookies; the relay joined them with `\n` into one header, but HTTP header
   values can't contain newlines. Austria only issues one cookie so it never
   hit this. Fixed by base64-encoding the `\n`-joined blob (see the header
   table above). This is why the response header is `X-Upstream-Set-Cookie-B64`,
   not the older plain `X-Upstream-Set-Cookie`.

The live relay is deployed at `perky-terrapin-5228.leraffl.deno.net`
(Deno Deploy playground on the `leraffl` org). Note the domain is
`.leraffl.deno.net`, not the older `<project>.deno.dev` form some examples
below still show.

### Priority order for routing

```
1. NL_PROXY (socks5:// or http://)        — highest priority; set if you have
                                             a self-hosted proxy with NL egress
2. NL_FETCH_RELAY + NL_RELAY_TOKEN        — Deno Deploy relay (preferred)
3. AUSTRIA_FETCH_RELAY + AUSTRIA_RELAY_TOKEN  — CF Worker fallback (will 403
                                               for this host, kept as last-resort)
4. Direct connection                       — fails for GitHub Actions runners
```

The workflow maps these in priority order via `${{ secrets.NL_PROXY || secrets.AUSTRIA_PROXY }}` etc.

### Setting up the Deno Deploy relay

1. Go to [dash.deno.com](https://dash.deno.com) → sign in with GitHub → **New Playground**.
2. Paste `worker/deno-relay.ts`, click **Save & Deploy**.
3. In the project's **Settings → Environment Variables**, add:
   `RELAY_TOKEN` = `<a long random string>`.
4. Note the deployed URL, e.g. `https://purple-whale-12.deno.dev`.
5. In GitHub repo Settings → Secrets → Actions, add:
   - `NL_FETCH_RELAY` = `https://purple-whale-12.deno.dev/fetch?url=`
   - `NL_RELAY_TOKEN` = same random string from step 3.

The relay is free and needs no credit card. Deno Deploy's free tier allows
1 000 000 requests/month; the Netherlands workflow runs at most ~45 × 3 requests/month.

### If Deno Deploy is also blocked in the future

Options in order of effort:
1. Deploy a second Deno project (new outbound IP pool — may differ).
2. Deploy to Fly.io / Render / Railway / another free PaaS with different IP
   ranges. The relay contract is simple enough to port in <50 lines.
3. Set `NL_PROXY` to a residential or datacenter proxy URL (`socks5://user:pass@host:port`).
4. Run a one-off local fetch and commit the result manually:
   `python scripts/fetch_netherlands.py --force && git add data/ && git commit -m "chore: manual Netherlands update"`
