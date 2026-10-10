---
country: Lithuania
slug: lithuania
method: file
summary: First registrations of passenger cars in Lithuania straight from Regitra, the state
  enterprise that keeps the national vehicle register — new cars (Whole) and, new to the
  gallery, the three-times-larger used-import market (Used), by the register's fuel field.
  Matches Regitra's own monthly totals exactly and ACEA's Lithuanian figure to within about
  0.5 % a month, about two weeks before ACEA publishes it.
source_name: Regitra — register statistics (table 5, first registrations of M1 by fuel) and open register data
source_url: https://www.regitra.lt/paslaugos/duomenu-teikimas/statistika/
source_links:
- label: Regitra statistics page (table 5 and the monthly totals)
  url: https://www.regitra.lt/paslaugos/duomenu-teikimas/statistika/
  note: one XLSX per year — "Pirmą kartą įregistruotų Lietuvoje M1 klasės transporto priemonių skaičius pagal degalų rūšį" (new / used × fuel, by month) and "Pirmą kartą Lietuvoje įregistruotų transporto priemonių skaičius" (the totals used as the cross-check)
- label: Regitra open data — register snapshot
  url: https://www.regitra.lt/imone/atviri-duomenys/
  note: Atviri_TP_parko_duomenys.zip, one row per registered vehicle (about 2.5 million, 167 MB), refreshed about quarterly; carries the EU hybrid category (OVC-HEV / NOVC-HEV), brand and model
- label: ACEA — monthly new-car registrations
  url: https://www.acea.auto/
  note: the Whole history before 2024 and the counted PHEV/HEV split from 2024
underlying: Lithuanian road-vehicle register (Kelių transporto priemonių registras), kept by VĮ Regitra
auth: none
cadence: twice daily (06:35 and 12:35 UTC); Regitra posts the year file for a month in the first ten days of the next one (August 2026 was up on 9 September) and restates the year on every update
variants:
- Whole
- Used
- Vans
- HDV
- Buses
variant_notes:
  Whole: New passenger cars — EU M1 incl. off-road M1G, Regitra status Nauja (new, first registration anywhere). Regitra from 2024-01, ACEA before.
  Used: Used passenger cars imported into Lithuania — EU M1 incl. M1G, Regitra status Naudota (first registered abroad), dated by the month of the first Lithuanian registration. From 2024-01. One combined hybrid number (in HEV, no PHEV column) — no counted PHEV/HEV split exists for used imports.
  Vans: ACEA commercial-vehicle figures (unchanged by this source).
  HDV: ACEA commercial-vehicle figures (unchanged by this source).
  Buses: ACEA commercial-vehicle figures (unchanged by this source).
hev_split: true
hev_note: Regitra's fuel table has one number for every fuel combination with "Elektra" (petrol, diesel or gas + electric). For Whole (new cars) it is split into PHEV and HEV with ACEA's counted split of the same month — the register snapshot's EU hybrid category (OVC-HEV = plug-in, NOVC-HEV = not externally chargeable) or a provisional share only bridge the weeks until ACEA publishes. HEV includes mild hybrids (type-approved as NOVC-HEV), as ACEA's does. Used has no counted split anywhere, so its hybrids stay one combined number in HEV (plug-in + full + mild, no PHEV column; the chart then draws no PHEV curve) — the Türkiye/Ukraine convention. Fuel-cell cars are OTHERS.
backfill: Whole is ACEA to 2023-12 and Regitra from 2024-01 (the first year with table 5); Used from 2024-01; Vans, HDV and Buses stay ACEA's commercial-vehicle series
scope_note: Every M1 vehicle first registered in Lithuania, split by Regitra's own new/used status. Lithuania is a re-export hub — many cars leave again within months — but a first registration counts once, whether the car stays or not.
caveats:
- 'Whole only — derived, not counted: the PHEV/HEV split. Regitra counts every car but has one hybrid number. For new cars the split is ACEA''s counted split of the same month scaled to Regitra''s hybrid count (exact to within one or two cars); for a month ACEA has not published yet it is the register snapshot''s plug-in share, and for the newest months, which neither covers, a provisional share from the three months before (the CSV row''s source then reads "Regitra (provisional)"). Every row''s notes column says which.'
- 'The register snapshot holds only cars still registered. Lithuania re-exports many cars, more hybrids than plug-ins, so for months more than about half a year before the snapshot its plug-in share runs high — by up to 80 cars a month in 2025 against ACEA''s counted split. That is why it ranks second for new cars, and why the brand and model tables below rank cars still registered, not all first registrations.'
- 'Used: hybrids are one combined number (HEV column, PHEV absent), counted exactly from table 5. A PHEV/HEV split would have to come from the register snapshot, which misses the 22–29 % of used imports re-exported since (more hybrids than plug-ins) and has no hybrid category for about 40 % of used hybrids — an estimate on a biased sample, so it is not made. Until 2026-10 the Used rows carried such a split; they were rewritten combined.'
- 'The Whole series changes source at 2024-01, not definition: from 2024 Regitra and ACEA count the same register (2024–2026: −0.2 % in total, −0.5 % in BEV). ACEA''s 2026-07 row was derived from year-to-date sums and was 134 cars too high; Regitra''s count replaces it.'
processing:
- title: Download
  text:
  - The fetcher reads Regitra's statistics page, finds the year files of table 5 (new / used × fuel by month) and of the monthly totals, and downloads the running year and the year before (about 40 KB). It then reads the open-data page; only when the register snapshot carries a new date does it download it (167 MB zip, 945 MB of CSV) and update the split store market/lithuania_fleet.json.
- title: Pick the vehicles
  text:
  - Table 5 holds every M1 vehicle (M1 and the off-road M1G) first registered in Lithuania, in two blocks with Regitra's own status. The status decides the variant; vans, lorries and buses are not in table 5 and stay ACEA's.
  decision:
    ask: Regitra status of the vehicle?
    branches:
    - when: Nauja — new, first registration anywhere
      then: Whole
    - when: Naudota — used, first registered abroad
      then: Used
      note: dated by the month of the first Lithuanian registration
- title: Powertrain
  text:
  - The register's fuel field (DEGALAI) lists the energy sources of the vehicle, separated by "/". It decides every column except the PHEV/HEV split of new cars, which it does not know.
  decision:
    ask: Fuel field (DEGALAI)?
    branches:
    - when: exactly Elektra
      then: BEV
    - when: contains Vandenilis (hydrogen)
      then: OTHERS
      note: fuel-cell cars, as at ACEA
    - when: any other combination with Elektra — petrol, diesel or gas + electric
      then: hybrid — one number
      note: Used keeps it combined in HEV; Whole is split in the next step
    - when: exactly Benzinas (petrol)
      then: PETROL
    - when: exactly Dyzelinas (diesel)
      then: DIESEL
    - when: anything else — petrol/LPG, petrol/CNG, ethanol, not stated
      then: OTHERS
- title: PHEV or HEV
  text:
  - 'Whole only, derived, not counted: the hybrid count of each month is split with a plug-in share from the best counted source available. The share is re-evaluated on every run, so a month gets the better split as soon as one exists. PHEV = hybrids × share, HEV = the rest. Used is not split: no counted source covers used imports.'
  decision:
    ask: Which variant, and which counted split covers the month?
    branches:
    - when: Used (used imports)
      then: not split — every hybrid in HEV, no PHEV column
      note: the snapshot misses re-exported cars and has no category for ~40 % of used hybrids
    - when: ACEA's PHEV and HEV for the month (new cars only)
      then: ACEA's share
      note: same register, so ACEA's split scaled to Regitra's hybrid count; exact to a car or two
    - when: no ACEA figure — the register snapshot has the month
      then: the snapshot's share OVC-HEV / (OVC-HEV + NOVC-HEV)
      note: counted, but only cars still registered; bridges the weeks until ACEA publishes
    - when: neither yet (the newest months)
      then: the pooled share of the three final months before — source "Regitra (provisional)"
      note: estimated; upgraded by a later run once ACEA or a newer snapshot covers it
- title: Checks before writing
  text:
  - Every block of table 5 must add up to its own sum line, every month's total must equal Regitra's separate monthly totals table exactly (64 of 64 month × status pairs did in October 2026), unknown fuel strings may not exceed 2 % of a month, and a month below a quarter of the usual volume is not written. Anything else stops the run before a CSV is touched.
market_breakdown: market/lithuania_top.json
market_designation_note: brand and model from the register snapshot's MARKE and KOMERCINIS_PAV (commercial name). The name is reduced to the model as buyers know it — trims, power and drive words are dropped (ID.4 PRO 4MOTION 210KW → ID.4, Q5 220KW TFSI E → Q5), and where Regitra lists two names ("TUCSON. ix35") the first is kept. Upper-cased.
market_powertrain_note: BEV is the fuel field Elektra; PHEV and HEV are the register's EU hybrid category (OVC-HEV / NOVC-HEV), counted per car — hybrids without a category are left out. Counted from the register snapshot, so only cars still registered on the snapshot date appear — about three quarters of 2025's first registrations, nearly all of 2026's.
market_breakdown_extra:
- path: market/lithuania_used_top.json
  id: market-used
  heading: Who sells the imported used electrified cars
  note: "Used imports (the Used variant): passenger cars first registered abroad, by the month of their first Lithuanian registration, from the register snapshot. About a quarter of each month's used imports is no longer in the register a few months later — mostly re-exported — so the table ranks the ones that stayed. Hybrids are one class, as in the Used CSV: plug-in, full and mild together, including the hybrids without a register category."
  class_names:
    HEV: Hybrid
  class_labels:
    HEV: Hybrid — every hybrid, plug-in + full + mild (one combined class, as in the Used CSV; counted as ICE in the curves)
fetcher: scripts/fetch_lithuania.py
workflow: .github/workflows/fetch-lithuania.yml
fragility_doc: docs/architecture/55-source-lithuania.md
data_file: data/Lithuania.csv
---

# 55 · Source: Lithuania (Regitra)

**Status: LIVE since 2026-10.** Fetcher `scripts/fetch_lithuania.py` (+ tests
`scripts/test_fetch_lithuania.py`), workflow `.github/workflows/fetch-lithuania.yml`.
Regitra writes Whole and Used from 2024-01; ACEA (`fetch_acea.py`) moved Lithuania from its
always-list to the conditional list and now only fills a Whole month Regitra has not written,
or replaces a provisional one.

## TL;DR

```
Source:    regitra.lt/paslaugos/duomenu-teikimas/statistika/
             5-Pirma-karta-iregistruotu-Lietuvoje-M1-...-pagal-degalu-rusi-<YYYY>...xlsx
                 table 5: Nauja / Naudota × fuel field × month (2024+)
             Pirma-karta-Lietuvoje-iregistruotu-transporto-priemoniu-skaicius-<YYYY>...xlsx
                 monthly totals (cross-check)
           regitra.lt/imone/atviri-duomenys/ → Atviri_TP_parko_duomenys.zip
                 register snapshot, ~2.5 M rows, about quarterly (PHEV/HEV, brands)
Auth:      None. A full browser User-Agent is needed for the zip (a short UA
           gets an HTML page back).
Timing:    a month's year file is up in the first ten days of the next month;
           ACEA publishes Lithuania around the 20th.
Variants:  Whole (Nauja) · Used (Naudota). Vans/HDV/Buses stay ACEA CV.
Split:     Whole: PHEV/HEV from ACEA's split → snapshot share → provisional (§5).
           Used: one combined hybrid number in HEV, no PHEV column (§5).
Check:     table 5 = Regitra's totals table, 64/64 exact. vs ACEA 2024-01..
           2026-06: −0.2 % total, every month within ±0.6 % (§4).
```

## 1. Why this source clears the bar

Lithuania was an ACEA "always" country: ACEA's monthly press release was the only source,
three weeks after month end, and one month (2026-07) had to be derived from year-to-date
sums. A Regitra entry in `country_source_stubs.yaml` recorded the register as unreachable (a
CAPTCHA, probed 2026-09-28). From GitHub's runners in October 2026 the statistics page, the
year files and the open-data zip all answer without one.

Regitra keeps the register ACEA's figure is built from (via the Lithuanian car dealers'
association), so it reproduces ACEA's totals and by-fuel numbers (§4) — the rule that a new
source extends the legacy series in the same categories holds. It adds what ACEA does not
have: the **used-import market**, about 3.6 times the new one in 2026 (118,622 against
32,655 cars, 55 % diesel), with the same fuel breakdown.

What it lacks is a PHEV/HEV split in the monthly table — §5 says how that is filled and how
exact each tier is.

## 2. Record → CSV row

Table 5 is one XLSX per year, restated with every new month. Rows are the fuel field
(`DEGALAI`) within a status block, columns are the months:

| Layout | Month header | Block | Block sum | Grand total |
|---|---|---|---|---|
| 2025, 2026 | `YYYY-MM` strings | `Nauja` / `Naudota` | "… suma" | `Bendroji suma` |
| 2024 | integers 1–12 (year from the title "2024 m.") | same | "… viso" | `IŠ VISO` |

`parse_fuel_table()` reads both; the month header is taken from the first row with at least
six months (an earlier version mistook a data row holding a single 1 for the header — the
block-sum check caught it). The totals file has one row per Lithuanian month name; new M1 is
column 5, used M1 column 3 (`parse_totals_table()`).

| Variant | File | Filter |
|---|---|---|
| `Whole` (`data/Lithuania.csv`) | table 5 | status `Nauja` |
| `Used` (`data/Lithuania_Used.csv`) | table 5 | status `Naudota` |

Table 5's "M1" is M1 + M1G (off-road M1) — the same scope ACEA's passenger-car figure has,
which is why the totals match (§4).

## 3. Fuel mapping

The fuel field lists components separated by "/". First match wins (`fuel_class()`):

| DEGALAI | Column |
|---|---|
| `Elektra` | BEV |
| contains `Vandenilis` (hydrogen) | OTHERS (fuel cell, as ACEA) |
| any other combination with `Elektra` (`Benzinas/Elektra`, `Dyzelinas/Elektra`, `Benzinas/Suskystintos naftos dujos/Elektra`, …) | hybrid → PHEV + HEV (§5) |
| `Benzinas` | PETROL |
| `Dyzelinas` | DIESEL |
| anything else (`Benzinas/Suskystintos naftos dujos` LPG, `…/Gamtinės dujos` CNG, `Etanolis`, `Nenurodyta` not stated, …) | OTHERS |

A component the fetcher does not know (`KNOWN_COMPONENTS`) is still mapped by these rules,
but is listed as a workflow warning; above 2 % of a month the run stops. The column set
(`BEV, PHEV, HEV, PETROL, DIESEL, OTHERS`) is exactly the legacy ACEA set — no coarser
category is introduced.

## 4. Validation

### 4.1 Against Regitra's own totals (every run)

Table 5's block sums equal the separate monthly totals publication for all 64 month × status
pairs 2024-01 … 2026-08. A mismatch stops the run (`--force` overrides).

### 4.2 Against ACEA (the legacy series)

Whole, Regitra minus the ACEA row it replaced:

| Year | Total | BEV | PHEV | HEV | Petrol | Diesel | Others |
|---|---|---|---|---|---|---|---|
| 2024 | −53 (−0.18 %) | −17 | −8 | −65 | +24 | +20 | −7 |
| 2025 | −62 (−0.15 %) | −9 | −15 | −66 | +23 | +5 | 0 |
| 2026 (Jan–Aug) | −247 (−0.75 %) | −12 | −52 | −182 | +25 | +7 | −33 |

Every month from 2024-01 to 2026-06 is within ±0.6 % (largest −22 cars, 2025-05). The two
2026 outliers are ACEA's: 2026-07 (−134) was derived from year-to-date sums, and 2026-08
(−89) is Regitra's first count of the month — the year file is restated, and a later run
picks up late registrations. PHEV and HEV follow ACEA's split (§5), so their small gaps are
the hybrid total's.

### 4.3 The register snapshot's bias

The snapshot of 2026-07-03 holds only cars registered on that day. Its count of a month's
first registrations falls short of table 5 by 0.5 % (2026-05) … 28 % (2025-06, new) and
22–29 % for used imports throughout — Lithuania re-exports many cars. Hybrids leave more
often than plug-ins, so the snapshot's plug-in share is too high for older months:

| Month | ACEA PHEV | snapshot share × Regitra hybrids |
|---|---|---|
| 2024 (monthly) | 95–209 | +3 … +24 |
| 2025-03 … 2025-10 | 220–514 | +51 … +83 |
| 2026-03 … 2026-05 | 454–569 | +1 … +13 |

Hence the order of the tiers in §5: ACEA's counted split where it exists, the snapshot only
for months near its date.

## 5. The PHEV/HEV split

**Used is not split.** No counted PHEV/HEV split exists for used imports (ACEA covers new
cars only), and the register snapshot is a poor stand-in: it misses the 22–29 % of used
imports re-exported since — hybrids more often than plug-ins (§4.3) — has no hybrid
category for about 40 % of used hybrids, and so far there is one snapshot for the whole
history. So `split_hybrids()` returns every used hybrid as `HEV` and
`data/Lithuania_Used.csv` has no `PHEV` column — the combined-hybrid convention of
Türkiye and Ukraine ([09](09-glossary.md) "Hybrid"; the trajectory draws no PHEV curve,
`has_phev_split`). The Used brand table ranks the same combined class, including the
hybrids without a category. (Until 2026-10 the Used rows carried a snapshot split; they
were rewritten combined in the PR that built this source.)

For **Whole**, `split_hybrids()` evaluates on every run, best first:

1. **ACEA** (Whole only). The share from ACEA's PHEV and HEV for the month, taken from the
   ACEA row in the CSV or, once Regitra has replaced it, from the note `ACEA PHEV a / HEV b`
   the fetcher leaves in that row. PHEV = round(H × a / (a + b)).
2. **Register snapshot.** OVC-HEV / (OVC-HEV + NOVC-HEV) among the month's first
   registrations in the snapshot (store `market/lithuania_fleet.json`, `months` →
   `"YYYY-MM|new"`; the `"|used"` counts are kept for diagnostics only), if at least 20
   categorised hybrids. Hybrids without a category (`UNK`) are left out. Months after the
   last full month of the snapshot are not used.
3. **Provisional.** The pooled share (ΣPHEV / Σhybrids) of the three final months before it
   (tier 1 or 2).
   The row's `source` is `Regitra (provisional)`; `fetch_acea.py` may replace it with ACEA's
   figure (`PROVISIONAL_NATIONAL_SOURCES`), and this fetcher re-derives it on its next run.

If none applies (no earlier month either), the month is not written (`NoSplit`). The `notes`
column of every row names its tier and the counts behind it.

## 6. Interplay with fetch-acea

| Row in `data/Lithuania.csv` | Written by |
|---|---|
| ≤ 2023-12 | ACEA (unchanged) |
| ≥ 2024-01, Regitra has the month | Regitra, ACEA's split in the note |
| Regitra provisional, ACEA publishes | ACEA overwrites it; the next Regitra run writes Regitra counts with ACEA's split |
| Regitra has not reached the month, ACEA has | ACEA (conditional), replaced by Regitra later |

Lithuania is in `CONDITIONAL_COUNTRIES` in `scripts/fetch_acea.py`. Vans, HDV and Buses are
untouched (`fetch_acea_cv.py`); Regitra's table 1 has monthly vans and lorries but no fuel,
the snapshot has fuel but only the cars still registered — not enough for a count series yet.

## 7. Outputs

| File | What |
|---|---|
| `data/Lithuania.csv` | Whole, Regitra rows from 2024-01 |
| `data/Lithuania_Used.csv` | Used, from 2024-01 — no `PHEV` column, hybrids combined in `HEV` |
| `market/lithuania_fleet.json` | snapshot date + per-month OVC/NOVC/UNK counts (tier 2 store, generated) |
| `market/lithuania_top.json` | Whole: top BEV/PHEV/HEV brands and models, last 12 full months of the snapshot (generated by `market_top.py`) |
| `market/lithuania_used_top.json` | Used: top BEV and Hybrid (combined) brands and models, same window — shown as its own section via `market_breakdown_extra` with `class_names: {HEV: Hybrid}` |

The brand tables are written only when a new snapshot is read, and their scope check
(`check_scope`, counted vs CSV) warns above 15 % — expected here because of re-exports
(§4.3) — and aborts only above 40 %.

## 8. Operations and debugging

* **Cron** `35 6,12 * * *` (UTC). A run makes no HTTP request when the target month (last
  month) is a final Regitra row in both CSVs and no provisional row is left (only Whole
  rows can be provisional).
* **Dispatch inputs:** `variant` (all / Whole / Used), `period` (YYYY-MM), `backfill`
  (every year file from 2024), `fleet` (download the snapshot even if its date is
  unchanged), `force` (skip throttle, completeness, cross-check and foreign-row guards).
* **Offline:** `python scripts/fetch_lithuania.py --from-dir DIR --fleet-file Atviri_TP_parko_duomenys.zip --dry-run`
  with `fuel_<YYYY>.xlsx` and `totals_<YYYY>.xlsx` in `DIR`.
* The run's step summary lists every written row with its tier and the change against the
  previous row.

### Debugging runbook

| Symptom | Likely cause | What to do |
|---|---|---|
| `No fuel-table year files found on the statistics page` | Regitra renamed the files or moved the page | open the page, compare the link text with `find_year_files()` (it looks for "pagal-degalu-rusi" + a year); update the pattern |
| `fuel table: no month header row` / `no Nauja/Naudota rows` | a new layout of the year file | open the XLSX; extend `_month_header()` / the status labels, add the layout to `test_fuel_table` |
| `Consistency check failed` (a block ≠ its sum line) | a row mis-read as header, a new subtotal label | the message names the month; check `parse_fuel_table()` against that sheet |
| `Cross-check … failed` | the totals file was restated later than table 5 (or the reverse) | rerun the next day; if it persists, compare both files by hand — never `force` without knowing which is right |
| `::warning New fuel label` | a new DEGALAI combination | add its components to `KNOWN_COMPONENTS` and a `test_fuel_class` case once the mapping is confirmed |
| `<variant> <month>: not written — no ACEA split, no register snapshot month …` | no ACEA row, no snapshot month and no earlier split | backfill order problem; run with `backfill` so earlier months exist |
| `register snapshot link not found` / `missing columns` / non-zip download | open-data page or snapshot changed, or a short User-Agent | the CSVs are still written (tier 1 / 3); check `find_fleet()` and the `UA` header |
| provisional Whole rows never upgrade | ACEA has not published the month (and no newer snapshot) | wait for ACEA; a provisional row older than two months means fetch-acea is failing |
| scope warnings above tolerance on the brand tables | re-exports (§4.3) | expected up to ~30 %; investigate only above 40 % (abort) |

## 9. Sequence

```mermaid
sequenceDiagram
  participant Cron as fetch-lithuania.yml (06:35, 12:35)
  participant R as regitra.lt
  participant Repo as data/Lithuania*.csv
  participant ACEA as fetch-acea.yml
  Cron->>Cron: target final in both CSVs, no provisional row? → exit
  Cron->>R: statistics page → table 5 + totals year files
  Cron->>Cron: parse, sum checks, cross-check (exact)
  Cron->>R: open-data page → snapshot date
  opt new snapshot date (or fleet input)
    Cron->>R: Atviri_TP_parko_duomenys.zip (167 MB)
    Cron->>Repo: market/lithuania_fleet.json + top tables
  end
  Cron->>Repo: Whole rows (split tier 1 / 2 / 3) + Used rows (hybrids combined)
  Cron->>Cron: dispatch render-country.yml (touched variants)
  ACEA->>Repo: only a Whole month Regitra lacks, or a provisional one
```
