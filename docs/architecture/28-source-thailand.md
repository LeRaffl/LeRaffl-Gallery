# 28 · Source: Thailand (TAI / AIU portal)

The Thailand Automotive Institute (TAI) publishes new-vehicle registrations by
fuel type. The old public table at
`data.thaiauto.or.th/.../stat-auto-registration-energy-menu.html` froze in early
2026 and now sits behind a member wall, so it is no longer a usable feed. The
live figures are published on TAI's **AIU member portal**
(`aiu.thaiauto.or.th`), a single-page app backed by a JSON API on
`taiapi.thaiauto.or.th` (port **3000**). We authenticate with a free member
login and read the "Car registration by fuel" report.

## TL;DR

```
Variants:
  Whole        data/Thailand.csv              "Passenger Car and Pickup Truck"
  HDV          data/Thailand_HDV.csv          "Truck"
  Buses        data/Thailand_Buses.csv        "Bus"
  3-Wheelers   data/Thailand_3-Wheelers.csv   "Three Wheelers"

Source:    aiu.thaiauto.or.th SPA -> taiapi.thaiauto.or.th:3000 JSON API
Auth:      member login (cookie session, no bearer token)
Secrets:   THAILAND_AIU_THAIAUTO_USER (default "leraffl")
           THAILAND_AIU_THAIAUTO_PW
Schema:    BEV,PHEV,HEV,OTHERS,ICE,TOTAL   (aggregate ICE — no petrol/diesel split)
Schedule:  Daily 1st-20th at 04:40 UTC (poll until the new month lands)
Scripts:   scripts/fetch_thailand.py
Workflow:  .github/workflows/fetch-thailand.yml
Archive:   data/Thailand_legacy.csv  (pre-rebase Whole series, inert)
```

## 1. CSV schema

Thailand reports only an **aggregate ICE** figure (not petrol/diesel/flexfuel),
so all variants use the six-metric ICE schema:

```
period,time_interval,variant,source,BEV,PHEV,HEV,OTHERS,ICE,TOTAL,notes
```

## 2. Data flow

The portal SPA calls three endpoints on `taiapi.thaiauto.or.th:3000`; the
fetcher reproduces them:

```
1. GET  /websites
   -> resolve the AIU website_id. Matched exactly as the portal does: any of
      site/name/title/url containing "AIU" -> that entry's id (currently 1).

2. POST /login_with_website   {username, password, website_id}
   -> establishes a COOKIE SESSION. There is NO bearer token — the response
      carries user_id/username and a Set-Cookie; requests.Session then rides
      that cookie into the report calls. (The SPA stores user_id under the
      localStorage key "userToken", which is a red herring: it is not a JWT.)

3. GET  /veh_reg_fuel/report?period_mode=year&year=<Y>&type_code=ALL
   -> one call per year returns EVERY vehicle-type category for all months of
      that year. The row array is under the "raw_rows" key. Nationwide by
      default (area_name = ทั่วประเทศ); no area parameter needed.
```

One report fetch per year serves all four variants — we filter its rows by
`type_label` rather than making four calls.

### Field mapping (per report row)

```
BEV    <- bev_units
PHEV   <- phev_units
HEV    <- hev_units
ICE    <- icev_units
OTHERS <- other_units + not_specific_units
TOTAL  <- total_units          (== BEV+PHEV+HEV+OTHERS+ICE)
period <- period_year + period_month_no   (period_year is Gregorian, e.g. 2026;
                                           the API also carries period_year_be
                                           = the Buddhist year, e.g. 2569 — we
                                           ignore it.)
```

## 3. Variant → category mapping (and the pickup question)

The report exposes four vehicle-type categories. We match on the **exact**
`type_label` — a substring match would fold "Passenger Car and Pickup **Truck**"
into the "**Truck**" (HDV) bucket.

| Category (`type_label`)          | Variant      |
| -------------------------------- | ------------ |
| `Passenger Car and Pickup Truck` | `Whole`      |
| `Truck`                          | `HDV`        |
| `Bus`                            | `Buses`      |
| `Three Wheelers`                 | `3-Wheelers` |

**Pickups are not separable.** AIU bundles passenger cars and pickup trucks into
one category, so `Whole` unavoidably includes pickups. This is fine for
Thailand — pickups are a huge share of the market — but note the base series is
"cars + pickups", not "cars only". `HDV` here is **trucks only** (lorries),
excluding buses, matching the repo convention where HDV and Buses are separate
variants.

## 4. The Whole rebase and the legacy archive

Going forward, `Whole` is the AIU "Passenger Car and Pickup Truck" series. In
July 2026 we rebased the full history (2018-01 onward) onto this definition and
archived the previous series as **`data/Thailand_legacy.csv`**.

What the rebase actually changed (the feared 2025→2026 level shift did **not**
exist — the old `data.thaiauto.or.th` series already included pickups):

* **2018-2020**: a PHEV↔HEV reclassification only (TOTAL unchanged). The old
  series used estimated fractional PHEV/HEV splits; AIU carries the real
  integer split.
* **2023-2024**: sub-10-unit `OTHERS`/`TOTAL` revisions.
* **2025 (Jan-Jul)**: material — the old energy-menu "car" figures ran
  ~3,800/month **high** versus AIU passenger+pickup; corrected down.
* **2026-01**: +3,663 ICE — the one genuinely anomalous month (a preliminary
  pre-AIU figure that had missed pickups); corrected up.

`Thailand_legacy.csv` is inert: the gallery manifest is built from rendered
images, and a data file with no `params.csv` row and no render is never
surfaced. It exists purely as provenance for the pre-rebase numbers.

## 5. 3-Wheelers: high BEV share, tiny volume

Electric tuk-tuks give the 3-Wheelers variant a **high BEV share (~33% TTM)**
even though total volume is tiny (~110 vehicles/year). Consequences:

* It is **not** flagged "shows no transition". The frontend's no-transition
  test (`index.html: rowHasNoTransition`) short-circuits to *in transition* at
  TTM BEV ≥ 5%, and 3-Wheelers sits far above that. Low unit volume is **not**
  a no-transition criterion — only BEV share and curve shape are. If a
  volume-based exclusion is ever wanted, `skip_plots.csv` is the lever.
* The monthly BEV share is **noisy** (single-digit unit counts), so the fitted
  Weibull is concave (v2 ≈ 0.44) and the 20→80% extrapolation is wide. Treat
  the 3-Wheelers trajectory as indicative, not precise.

## 6. Network note (port 3000)

The API listens on the non-standard port **3000**. GitHub-hosted runners reach
it directly (validated end-to-end). Some egress proxies allow only 443 — e.g.
Claude Code's sandbox resets non-443 CONNECTs, so the fetcher cannot be run
from there; it must run in CI (or from an unrestricted host). If a runner's
egress IP is ever blocked, set repository secret `THAILAND_HTTPS_PROXY` to a
permissive proxy.
