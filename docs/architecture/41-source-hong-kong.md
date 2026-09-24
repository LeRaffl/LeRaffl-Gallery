---
country: Hong Kong
slug: hong_kong
method: file
summary: New-car, used-import and van registration data for Hong Kong from the Transport
  Department's record-level list of every vehicle first registered each month — with make,
  model, fuel, TD's own first-registration status and gross weight.
source_name: DATA.GOV.HK — Transport Department «Particulars of first registered vehicles»
source_url: https://data.gov.hk/en-data/dataset/hk-td-wcms_11-first-reg-vehicle
source_links:
- label: CKAN API (resource discovery)
  url: https://data.gov.hk/en-data/api/3/action/package_show?id=hk-td-wcms_11-first-reg-vehicle
  note: one CSV per month (English, Traditional and Simplified Chinese), from November 2019
- label: Data specification (field and status definitions)
  url: https://www.td.gov.hk/datagovhk_td/first-reg-vehicle/resources/en/dataspec/particulars_of_first_registered_vehicle_dataspec_eng.pdf
  note: defines the first-registration statuses A, B, C1, C2, D, E, F
- label: TD Monthly Traffic and Transport Digest, table 4.1(e) (cross-check)
  url: https://www.td.gov.hk/datagovhk_tis/mttd-csv/en/table41e_eng.csv
  note: TD's own aggregate — first registration of private cars by make, status and fuel; checked against the records on every run
underlying: Transport Department, HKSAR Government — vehicle registration and licensing records
auth: none
cadence: twice daily, 03:20 and 11:20 UTC — TD uploads month M between the 13th and the 28th of M+1
variants:
- Whole
- Used
- Vans
variant_notes:
  Whole: New private cars — TD class "Private Car" with first-registration status A, B or C1 (never, or under 15 days, registered abroad) ≈ EU M1.
  Used: Used-import private cars — status C2 (registered outside Hong Kong before import).
  Vans: New light goods vehicles with a permitted gross weight ≤ 3.5 t (EU N1; status A/B/C1/E).
hev_split: false
hev_note: TD's fuel field (Electric / Petrol / Diesel / LPG) has no hybrid value. Full and mild hybrids are counted in PETROL (inside ICE); plug-in hybrids are classified from the model designation into PHEV/EREV.
backfill: record-level files from 2019-11; TD's aggregate table reaches back to 2016-05 but with a different new/used definition before 2019, so it is not spliced on
scope_note: First registrations in Hong Kong only (new, or used imports), by TD's own first-registration status; taxis (their own vehicle class), own-use imports (status D) and government auctions (F) are in no variant.
caveats:
- The fuel field has no hybrid value. Plug-in hybrids are recovered from the model designation (few — about 1 % of new cars in 2025–26); full and mild hybrids cannot be told apart and are counted as petrol.
- The EV first-registration-tax concession was cut for applications from 1 April 2024 and ended for applications from 1 April 2026. Registrations spike in the months before each date and the BEV share steps down after it — a policy effect, not noise.
- Private cars only; taxis (about 100 a month, mostly LPG hybrids and now BEVs) are a separate vehicle class and not in Whole.
- The record files match TD's own table 4.1(e) exactly for every month compared, except one used-import car in June 2020.
- Used is a different population (used imports, dominated by Japanese-market Toyota and Honda MPVs) — read it next to Whole, not as part of it.
market_breakdown: market/hong_kong_top.json
market_designation_note: a "designation" is TD's model string with the brand prefix, chassis codes and trim words removed, so the trims of one model rank together (MODEL Y RWD and MODEL Y LONG RANGE → MODEL Y).
market_powertrain_note: BEV is TD's own fuel value; PHEV and EREV are classified from the model designation (see the developer doc).
fetcher: scripts/fetch_hong_kong.py
workflow: .github/workflows/fetch-hong-kong.yml
fragility_doc: docs/architecture/41-source-hong-kong.md
data_file: data/Hong Kong.csv
---

# 41 · Source: Hong Kong (Transport Department first registrations)

**Status: LIVE since 2026-09.** Fetcher `scripts/fetch_hong_kong.py` (+ tests
`scripts/test_fetch_hong_kong.py`) and `.github/workflows/fetch-hong-kong.yml`.
Hong Kong is the gallery's third record-level registry after Argentina and
Ukraine: one row per vehicle, with a fuel field, make, model and TD's own
classification of the vehicle's history before it reached Hong Kong.

The facts below were established by temporary probe workflows (runs of
2026-09-24 on the development branch; since removed): the dev sandbox cannot
reach `data.gov.hk` or `td.gov.hk`, the GitHub runners can. The same probes
ran the finished fetcher online end to end; its output matched the offline
build byte for byte.

## TL;DR

```
Source:    Transport Department (TD), DATA.GOV.HK dataset
           hk-td-wcms_11-first-reg-vehicle. One CSV per month, one row per
           vehicle first registered: class, make, model, fuel, cc, rated
           power, body, first-registration status, gross weight, seats,
           taxable-value band, year of manufacture.
Auth:      None. No login, no key.
API:       CKAN package_show → one English CSV per month (never hard-code
           the URL; resources are listed, the month is parsed from the name).
Timing:    Month M lands between the 13th and 28th of M+1 (2026: Mar file
           Apr 14, Apr May 13, May Jun 22, Jun Jul 28, Jul Aug 21).
History:   2019-11 → today (81 months at 2026-07).
Fuel:      In the record: Electric / Petrol / Diesel / LPG / Hydrogen — no
           hybrid value. Plug-ins classified from the model (PHEV_RULES).
Variants:  Whole (new private cars, M1) · Used (used imports) · Vans (N1).
Checked:   TD table 4.1(e) — private cars by status and electric, 80 months
           2019-11 → 2026-06: exact, except one C2 car in 2020-06.
```

## 1. Why this source clears the bar

The gallery's rule ([14](14-data-source-gaps.md)): direct from the registry,
complete for the market, obtainable without paying or handing over an ID.
This is the licensing authority's own list of every first registration,
published on the government open-data portal. It is complete by
construction — every brand, every importer, parallel imports included.

**Why Hong Kong and not a bigger market.** The same session looked for the
largest markets still missing from the gallery and found no workable source
for them (details in [33](33-expansion-candidates.md#investigated-2026-09--large-markets-still-missing)):
Taiwan's highway-bureau statistics site blocks datacenter IPs and its open
dataset has no fuel split; Mexico's official series omits BYD (see
[14](14-data-source-gaps.md)); Russia, Vietnam, the Philippines, Saudi Arabia
and Egypt publish no free fuel split. Hong Kong is small (~45,000 new cars a
year) but has one of the cleanest registration datasets anywhere and one of
the highest BEV shares (86 % of new private cars in 2025).

## 2. Record → CSV row

| Field | Use |
|---|---|
| file name / resource name (`…_jul_2026_eng.csv`, "July 2026") | period |
| `Vehicle Class` | `Private Car` → Whole / Used; `LGV` → Vans |
| `First Registration Vehicle Status` | new vs used (below) |
| `Permitted Gross Vehicle Weight` (tonnes) | Vans only: ≤ 3.5 t (EU N1) |
| `Fuel Type` | fuel column (§3) |
| `Vehicle Make`, `Vehicle Model`, `Year Of Manufacture` | plug-in rules (§3); `market/hong_kong_top.json` |

**First-registration status** — TD's classification (data specification):

| Status | Meaning | Used for |
|---|---|---|
| A | never registered outside HK (or registered but not permitted on roads) | Whole / Vans |
| B | never registered outside HK, as declared by the importer | Whole / Vans |
| C1 | registered outside HK for < 15 days (documented) | Whole / Vans |
| C2 | registered outside HK before import — a **used import** | Used |
| D | imported by the owner for own use (new or used) | — (≈ 10 a month) |
| E | assembled in HK with specified additions to an imported chassis | Vans only (bodywork on a new chassis) |
| F | bought at a HK SAR Government auction | — |

**Header drift seen so far** (all handled by `resolve_columns()`): the status
column is sometimes `First Registration Vehicle Status (Note)`;
`Rated Power (kW)` exists only in some months; early files carry a trailing
empty column; 2026 files have trailing spaces in two headers. Required
columns: class, make, model, fuel, status, gross weight, year of manufacture.

CSV columns: `BEV, PHEV, EREV, PETROL, DIESEL, OTHERS, TOTAL`; `source` =
`Transport Department (data.gov.hk)`. Line-level upserts (invariant 2); a row
whose `source` is not ours is never overwritten without `--force`.

**Why the series starts 2019-11.** That is the first record-level file. TD's
aggregate table 4.1(e) reaches back to 2016-05, but before 2019 it only splits
"Brand new" from "Others", and "Brand new" then counted ~3,000 cars a month
against ~2,500 A+B+C1 in 2019 — many parallel imports that are C2 today were
"brand new" then. Splicing it on would put a definition break into the curve
(invariant 3 spirit: no invented history). 2019-01…10 exist in the table with
the new statuses but without models, so no plug-in split — also left out.

## 3. Fuel mapping and plug-in classification

| `Fuel Type` | Column |
|---|---|
| `Electric` | BEV — TD's own value, never reclassified |
| `Petrol`, `Diesel` | PHEV / EREV if a plug-in rule matches, else PETROL / DIESEL |
| `LPG`, `Hydrogen`, anything else | OTHERS (unknown strings listed in the report; > 2 % of Whole aborts) |

The fuel field follows Cap. 311L (Air Pollution Control (Motor Vehicle Fuel)
Regulation) and has **no hybrid value**: a plug-in hybrid is "Petrol". Full
and mild hybrids cannot be recovered reliably — new franchise-dealer cars
rarely carry "HYBRID" in the designation (TD writes `ALPHARD`, `NOAH`, `JAZZ`
for trims that are often hybrids), so any HEV column would be a guessed lower
bound. They are counted in **PETROL**, i.e. inside ICE in the three-curve
chart, and there is no HEV column.

Plug-ins are recoverable because manufacturers name them. `PHEV_RULES` in the
fetcher is an ordered list (first match wins), each rule with its reason:

| Rule (model designation, make) | Class | Examples in the files |
|---|---|---|
| `REEV`, `EREV`, `RANGE EXTEND…` | EREV | FORTHING FRIDAY REEV |
| `PHEV`, `PHV`, `PLUG-IN`, `E:PHEV` | PHEV | GAC E9 PHEV GL, OUTLANDER PHEV, PRIUS PHV, ALPHARD PLUG-IN, JAECOO7 PHEV |
| `DM-i` / `DM-p` / `DM-o` | PHEV | BYD SEAL U DM-I |
| `E-HYBRID` | PHEV | PORSCHE CAYENNE E-HYBRID |
| `T8`, `RECHARGE` | PHEV | VOLVO XC90 T8 |
| `E PERFORMANCE` | PHEV | MERCEDES-AMG C63 S E PERFORMANCE |
| `GTE`, `TFSI e`, `4xe`, `Hybrid4`, `450h+` | PHEV | (none yet — standard designations, kept ready) |
| JLR `PxxxE` (year ≥ 2015) | PHEV | RRS P440E, DEFENDER P300E |
| BMW `xxxe`, `xDriveNNe`, `i8`, `XM` (year ≥ 2014) | PHEV | 530E, 745LE, XM, I8 |
| Mercedes `xxx e` / `xxx de`, AMG `53 HYBRID` (year ≥ 2015) | PHEV | S500 E L, AMG E 53 HYBRID — the year guard keeps the 1980s 190E/300E (E = fuel injection) out |
| MINI `COOPER S E COUNTRYMAN` / `SE ALL4` | PHEV | |
| Bentley `HYBRID` | PHEV | BENTAYGA HYBRID |
| Ferrari `SF90`, `296` · Lamborghini `REVUELTO`, `URUS SE`, `TEMERARIO` · McLaren `ARTURA` | PHEV | |
| GAC `E9` | PHEV | E9 GX, E9 GL — the E9 is sold only as a plug-in |
| any Petrol BYD or Denza | PHEV | BYD SEALION 6, DENZA B5 — neither brand sells a pure-combustion car in HK |

Deliberately **not** plug-ins (pinned in the tests): Maserati `… HYBRID`
(48 V mild), Suzuki `MILD HYBRID`, `MG3 HYBRID+`, Nissan `E-POWER` and Honda
`E:HEV` (full hybrids without a plug), Range Rover `P400` (mild), Volvo `T6`
before Recharge, Lamborghini `URUS S`.

**Scale.** New private cars 2019-11 → 2026-07: 930 PHEV + 8 EREV — 0.06 %
in 2022, 0.7 % in 2025, 1.2 % in Jan–Jul 2026 (mostly GAC E9, BYD Sealion 6,
Denza B5). The first-registration tax treats plug-ins as petrol cars, so
they never took off in Hong Kong; a mistake in one rule moves a handful of
cars, not the curve.

**The net for new plug-in models.** Every run lists (step summary) all
records classified as plug-ins this month, and every Petrol/Diesel record of a
brand whose Hong Kong line-up is mainly electric (`NEV_BRANDS`: Zeekr, Xpeng,
Aion, Leapmotor, Deepal, …) that matches no rule. A new plug-in from one of
those brands shows up there the month it arrives.

## 4. Variants

| Variant | Rule | EU anchor | 2025 |
|---|---|---|---|
| `Whole` | `Private Car` ∧ status A/B/C1 | M1 | 43,335 (BEV 86.3 %) |
| `Used` | `Private Car` ∧ status C2 | M1, **used imports** (like Netherlands/Spain/Ukraine `Used`) | 7,608 (BEV 0.5 %) |
| `Vans` | `LGV` ∧ gross weight ≤ 3.5 t ∧ status A/B/C1/E | N1 | 1,236 (BEV 35.2 %) |

**Not produced:** taxis (class `Taxi`, M1 but not "private car"; ~1,000 a
year), buses and goods vehicles > 3.5 t (TD's LGV class runs to 5.5 t; MGV,
HGV), motorcycles (EU L). All are one filter away in `variant_for()`.
`Used` here is TD's C2, the used-import population the gallery calls `Used`
([09](09-glossary.md)); changes of owner within Hong Kong are not in this
dataset at all.

## 5. Governance — what every run checks

| Check | On failure |
|---|---|
| Required columns resolve (all three header layouts, §2) | abort, nothing written |
| > 0.1 % of a file's rows short or without a vehicle class | abort |
| A month file with zero records | abort (broken upload) |
| Target Whole ≥ 25 % of the trailing-12 median (loose on purpose: after the April 2026 deadline June ran at 49 %) | not written (`--force` overrides); 25–50 % → written with a `::warning::` |
| Unknown fuel strings ≤ 2 % of Whole | abort above; below → OTHERS, listed |
| Unknown vehicle classes / statuses | listed in the step summary |
| **Cross-check vs TD table 4.1(e)** — private cars by status A/B/C1/C2 and electric, every month the table has | ≤ 2 units or 0.5 % → reported; more → abort (`--force` overrides) |
| Fuels sum to TOTAL, every row | abort |
| Months missing on the portal between the first and the newest | `::warning::` annotation |
| Fetcher + `market_top` regression tests (`test_fetch_hong_kong.py`) | the workflow stops before fetching |

The cross-check table lags the record files by about a month (at 2026-09-24
the records reach 2026-07, the table 2026-06), so the newest month is usually
checked on the following run — the step summary says which months were
compared.

## 6. Validation

**Against TD's own aggregate (table 4.1(e)), 80 months 2019-11 → 2026-06:**
private cars by status A, B, C1, C2 and electric private cars by status match
the record files exactly in every month but one — 2020-06, status C2: 777
records vs 778 in the table (the two are cut from the register at different
times). That is the tolerance the cross-check allows.

**Plausibility.** New private cars 2025: 43,335 (TD's gross new
registrations of private cars, table 4.1(c), count used imports too:
≈ 51,000). BEV share of new private cars: 16 % (2020) → 60 % (2022) → 86 %
(2025). Counting used imports too (Whole + Used, close to the scope of TD's own
headline figure) the 2024 BEV share is 71 %.

## 6a. Reading the fit

Two policy steps dominate the recent months:

- **April 2024** — the EV first-registration-tax concession was cut (to
  HK$58,500; HK$172,500 under "One-for-One Replacement"; none above HK$500,000
  pre-tax value). March–April 2024: ~5,700 new cars a month, BEV 90 %;
  May–July: ~2,300 a month, BEV ~70 %.
- **April 2026** — the concession ended for applications from 1 April 2026
  (orders placed by 25 February 2026 keep it if registered by 24 February
  2027). March–April 2026: ~9,000 a month, BEV 95 %; June 2026: 1,910, BEV 73 %.

Expect the fit to be pulled up by the pre-deadline months and the post-2026
points to sit below it until the market settles; as with Ukraine's VAT
deadline ([40](40-source-ukraine.md)) this is policy, not noise. `Used`
(Japanese-market Toyota/Honda MPVs) has almost no BEVs and no trend; `Vans`
is small but shows a real transition (BEV 1 % in 2022 → 46 % in 2026).

## 7. Outputs

- `data/Hong Kong.csv`, `data/Hong Kong_Used.csv`, `data/Hong Kong_Vans.csv`
  (monthly, 2019-11 →).
- `market/hong_kong_top.json` — trailing-12-month top brands and models per
  class (BEV, PHEV, EREV) for Whole, via `scripts/market_top.py`. Display
  names only: brand aliases merged (`B.M.W.`/`BMW I` → BMW, `M.G.` → MG,
  `MERCEDES BENZ` → MERCEDES-BENZ, `LANDROVER` → LAND ROVER), the brand
  prefix, chassis codes `(G20)` and trim words (`MODEL_TRIM`) removed, so
  `MODEL Y RWD` and `MODEL Y LONG RANGE DUAL MOTOR ALL WHEEL DRIVE` rank as
  one model. The data CSVs never use these names.

## 8. Operations and debugging

```mermaid
sequenceDiagram
    participant Cron as fetch-hong-kong.yml (cron / dispatch)
    participant Test as test_fetch_hong_kong.py
    participant Py as fetch_hong_kong.py
    participant HK as data.gov.hk (CKAN) / td.gov.hk
    participant CSV as data/Hong Kong*.csv
    participant Top as market/hong_kong_top.json
    participant Render as render-country.yml
    Cron->>Test: scope + plug-in rules + headers + cross-check + upsert tests (gate)
    Cron->>Py: run (target = newest month on the portal)
    Py->>HK: package_show → monthly CSV list
    Py->>CSV: target month already from TD in every CSV?
    alt yes
        Py-->>Cron: no-op, no download
    else no
        Py->>HK: newest 12 monthly CSVs (all since 2019-11 on backfill)
        Py->>Py: class × status × weight → variant; fuel + PHEV_RULES → column
        Py->>HK: table 4.1(e) → cross-check private cars by status + electric
        Py->>CSV: line-level upserts (changed lines only)
        Py->>Top: trailing-12-month top brands / models (if changed)
        Py-->>Cron: run report → step summary
        Cron->>Render: once, variants = touched of "Used|Vans|Whole"
    end
```

- **Schedule:** `20 3,11 * * *` (daily, HK 11:20 and 19:20). The first HTTP
  call is the portal's resource list; when every CSV already has the newest
  published month the run ends there ("already fetched … nothing to do").
- **Normal run:** downloads the newest 12 monthly files (~5 MB), re-derives
  those months (no-op if unchanged) and rebuilds the top list.
- **Backfill / rebuild:** dispatch with `backfill = true` (81 files, ~30 MB,
  ~1 min).
- **Render:** the fetch job dispatches `render-country.yml` once with the
  changed variants (`Used|Vans|Whole`).
- **After each monthly run:** read the step summary — plug-in list, NEV-brand
  watch list, unknown classes/statuses/fuels, the cross-check line.

**If a run fails — where to look:**

| Symptom in the log | Cause | Fix |
|---|---|---|
| `No monthly files found — portal layout changed?` | `package_show` returned no English CSV whose name/URL parses to a month | open the `package_show` URL; adjust `period_of()` / the `inLanguage` filter in `list_month_urls()`; add the new name to `test_period_parsing` |
| `schema drift: columns [...] not in header [...]` | TD renamed a column | map the new name in `FIELDS` / `norm_header()`; add the header to the tests |
| `N of M rows are short or have no vehicle class` | a malformed or truncated upload | re-run later; if TD fixed nothing, report the file to TD (tdenq@td.gov.hk) |
| `Cross-check against TD table 4.1(e) failed` | records and TD's table disagree beyond 2 units | compare the named months by hand (both URLs are in the front-matter). A re-uploaded record file → re-run with `backfill`; a table revision the records don't have yet → wait a run; a genuine definition change → document it here, then `force` |
| `unknown fuel strings … schema drift` | a new fuel value (> 2 % of Whole) | map it in `FUEL_MAP` with a test |
| `is not published on the portal yet` | normal between the 1st and the upload day | nothing |
| `below 25% of the trailing median` (not written) or the `unusually low` warning (written) | a partial upload — or a real collapse (a tax deadline just passed) | compare with TD's table 4.1(e) / press; if genuine and not written, re-run with `force` |
| `months missing on the portal` warning | TD skipped or removed a month | the CSV keeps the old row; nothing is written for the gap |
| commit step `non-fast-forward` | a concurrent commit | already rebased by the action; re-run |
| render not dispatched | no CSV change, or the commit failed | see the `changed_variants` output of the fetch step |

**If a new plug-in model appears** (NEV-brand watch list, or a PHEV you can
see in the market): add a rule to `PHEV_RULES` with its reason, add the real
model string to `FUEL_CASES` in the tests (a rule without a test fails
`test_every_rule_is_exercised`), and dispatch with `backfill = true` so the
history is re-classified.
