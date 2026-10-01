---
country: Italy
slug: italy
method: pdf
summary: Passenger-car registrations for Italy from UNRAE, with rental / non-rental splits and a separate
  light-commercial variant.
source_name: UNRAE — struttura del mercato PDF
source_url: https://unrae.it/dati-statistici
source_links:
- label: UNRAE — immatricolazioni (passenger-car PDFs)
  url: https://unrae.it/dati-statistici/immatricolazioni
- label: UNRAE — immatricolazioni veicoli commerciali (the LCV struttura PDFs, same index)
  url: https://unrae.it/dati-statistici/immatricolazioni/tag/autocarri
underlying: UNRAE / Ministero delle Infrastrutture e dei Trasporti
auth: none
cadence: passenger 4×/day on the 1st–3rd; vans 3×/day on the 8th–16th
variants:
- Whole
- Rental
- NonRental
- Vans
variant_notes:
  Whole: Passenger cars, whole market including rental.
  Rental: Rental fleet, derived exactly as Whole minus NonRental.
  NonRental: Passenger cars al netto del noleggio — private buyers, companies and self-registrations.
  Vans: Light commercial vehicles (autocarri up to 3.5 t), exact counts; pre-2025 months derived from year-to-date tables.
hev_split: true
fcev: counted in OTHERS (with LPG and CNG)
backfill: scripts/backfill_italy_vans.py (Vans, from 2017-05)
scope_note: Whole = passenger cars incl. rental; NonRental is the full non-rental sector, not private
  persons.
caveats:
- OTHERS (passenger) = LPG + CNG + hydrogen/FCEV — explicit, not a residual.
- NonRental mixes private buyers, self-registrations and companies; no per-fuel private-only split exists.
- Vans before 2025 are differences of UNRAE's year-to-date tables (flagged in notes); PHEV is not split out before 2020-07; June/July 2017–2021 and July/August 2023 are missing.
market_breakdown: market/italy_top.json
market_window_note: "The twelve-month view is computed directly from UNRAE's January-to-date model lists (this year's list, plus last December's, minus the same month last year), so it is exact. Single months are differences of two consecutive lists. January and February 2026 cannot be separated, because UNRAE published no January 2026 list. Hybrids (HEV) are not ranked: UNRAE lists only their top 10 models."
fetcher: scripts/fetch_italy.py
workflow: .github/workflows/fetch-italy.yml
fragility_doc: docs/architecture/18-source-italy.md
data_file: data/Italy.csv
---

# 18 · Source: Italy (UNRAE)

UNRAE (Unione Nazionale Rappresentanti Autoveicoli Esteri) publishes monthly
registration bulletins as PDFs. Two distinct publications are used:

- **PKW "Struttura del mercato"** — passenger cars, from
  `unrae.it/dati-statistici/immatricolazioni`, typically on the **1st (sometimes
  2nd) of the following month**.
- **LCV "Struttura del mercato"** (autocarri ≤ 3,5 t) — light commercial
  vehicles, on the same index (`immatricolazioni-veicoli-commerciali-<mese>-<anno>`),
  typically around the **10th of the following month**; July and August come
  together in September.

## TL;DR

```
Variants:
  Whole      data/Italy.csv           PKW whole market (inkl. Noleggio)
  Rental     data/Italy_Rental.csv    PKW rental fleet = Whole − (al netto del noleggio), exact
  NonRental  data/Italy_NonRental.csv PKW "al netto del noleggio" (second PDF block, exact)
  Vans       data/Italy_Vans.csv      LCV (autocarri ≤ 3,5 t), exact; pre-2025 YTD-derived

NOTE: Italy exposes only Whole and "al netto del noleggio" fuel breakdowns.
  Rental    = NLT + NBT + autoimm.uso.noleggio ≈ 30–35 % of new registrations.
  NonRental ≠ "private persons": it is the full non-rental sector
  (~78 % Privati + ~15 % Autoimm. uso privato + ~7 % Società, all mixed).
  No per-fuel breakdown for Privati alone is publicly available from MIT.
  See § 1 for full channel breakdown and cross-checks.

PKW source:  UNRAE struttura-del-mercato PDF (Whole + Rental + NonRental from one download)
Vans source: UNRAE LCV struttura PDF (same index, separate PDF and schedule)
Auth:        None
FLEXFUEL:    Not reported by Italy — column absent from all three CSVs
HEV:         Reported natively as 'Ibride elettriche (HEV)' (full + mild sum)
OTHERS (PKW): Gpl + Metano + Idrogeno (FCEV) — explicit, not a residual
OTHERS (Vans): Gpl + Metano — explicit, not a residual
Schedule:    PKW  4×/day on the 1st–3rd   (06:00/10:00/14:00/18:00 UTC)
             Vans 3×/day on the 8th–16th  (10:00/14:00/18:00 UTC)
Scripts:     scripts/fetch_italy.py
Workflow:    .github/workflows/fetch-italy.yml
```

## 1. Variant semantics and market-channel structure

### What the two variants represent

| Variant | CSV | Definition |
|---------|-----|------------|
| **Whole** | `data/Italy.csv` | All new PKW registrations, **including** rental fleet |
| **Rental** | `data/Italy_Rental.csv` | `Whole − NonRental` = registrations **for rental use only** |
| **NonRental** | `data/Italy_NonRental.csv` | Second PDF block "al netto del noleggio" read directly: Privati + Società + Autoimmatricolazioni (excl. uso noleggio) |

`Whole = Rental + NonRental` holds exactly because both NonRental and Whole are
read directly from the same PDF and Rental is their difference.

There is no "Private" variant. The "al netto del noleggio" PDF section
(= NonRental) is not the same as "private persons" (see below).

### The UNRAE market-channel breakdown (Per utilizzatore)

Every Struttura PDF includes a *Per utilizzatore* table that breaks total
registrations into five channels. Typical shares (based on 2026 monthly data):

| Channel | Italian term | Typical share | Notes |
|---------|--------------|---------------|-------|
| Private individuals | Privati | ~53 % | Natural persons buying outright |
| Long-term rental | Noleggio a Lungo Termine (NLT) | ~19–25 % | Contracts > 30 days, typically 24–48 months; full-service fleet |
| Short-term rental | Noleggio a Breve Termine (NBT) | ~8–12 % | Classic rent-a-car; seasonal, airport-driven |
| Dealer self-reg. | Autoimmatricolazioni | ~10 % | Includes a ~1 % "uso noleggio" sub-slice |
| Direct corporate | Società ed Enti | ~5 % | Firms/public bodies buying without a rental contract |

**Our "Rental" metric = NLT + NBT + autoimmatricolazioni "uso noleggio".**
The "al netto del noleggio" section of the PDF is the Totale **excluding all
three rental sub-channels**, so the subtraction captures exactly this combined
rental market (typically **30–35 %** of total new registrations).

Numerical cross-check (May 2026, verified against our CSV):

```
Whole TOTAL (our CSV):   151,659  ← matches UNRAE PDF "Totale mercato"
Rental TOTAL (our CSV):   48,695  ← NLT+NBT reported by UNRAE: 47,056
                                     difference ≈ 1,639 = autoimm. uso noleggio
                                     (~1.1 % of total) — included in our metric
```

### Common misconceptions

**"Rental = juristic persons, non-rental = private persons" — NOT correct.**

- Approximately **14–15 % of NLT contracts are with private individuals** who
  rent long-term instead of buying; they show up in *our Rental metric*, not in
  the private-buyer segment.
- Conversely, the non-rental sector (Whole − Rental = "al netto del noleggio")
  is not exclusively private persons. It contains:
  - Privati ~78 % of the non-rental total (≈ 53 % of the whole market)
  - Autoimmatricolazioni "uso privato" ~15 % of non-rental
  - Società ed Enti ~7 % of non-rental (direct corporate, no rental contract)

**"NonRental ≈ private persons" — APPROXIMATELY true but imprecise.**
Private individuals (Privati) represent ~53 % of the whole market and ~78 % of
the NonRental sector. The remaining ~22 % of NonRental are dealer
self-registrations and direct-corporate purchases.

### Why Italy has no "Private" variant

Denmark and Finland publish "Private" as a distinct channel with per-fuel
breakdowns. UNRAE's "Per alimentazione" fuel table exists only for:
1. The full market (→ Whole)
2. The market "al netto del noleggio" (→ used to derive Rental)

There is no "Per alimentazione" table for Privati only. A Private variant would
require raw microdata from MIT (Ministero delle Infrastrutture e dei Trasporti),
which is not publicly available.

---

## 2. CSV schema note

All three CSVs use the **12-column schema (no FLEXFUEL)**. Italy does not report
ethanol/flexfuel registrations. The schema is preserved as-is by the scraper.

### Historical backfill (2015–2016): quarterly-divided monthly rows

Rows from `2015-01` through `2016-12` carry `time_interval = "quarterly"` and
have fractional PHEV/HEV values with empty PETROL/DIESEL/OTHERS. These are
**quarterly totals divided by 3** to produce a per-month approximation — not
real monthly data from the UNRAE PDF. The same backfill pattern appears in
other countries in this repo (e.g. Netherlands, Denmark).

The renderer is unaffected: it always filters TTM/recent calculations on
`time_interval == last_ti`, which is `"monthly"` for Italy since 2017. These
rows are intentionally left as-is rather than corrected, to signal their lower
resolution. Do not re-label them `monthly`.

### Rental / NonRental history & provenance

| Period | Rental / NonRental source | notes column |
|---|---|---|
| 2019-06 → present | **Real.** UNRAE "al netto del noleggio" block; `Rental = Whole − netto`, `NonRental = Whole − Rental` (exact). | empty |
| 2015-01 → 2019-05 | **Estimated.** No rental block exists in pre-2019-06 UNRAE PDFs, so `Rental = round(Whole × per-fuel rental share)` using the 2019-H2 actual shares; `NonRental = Whole − Rental`. | `est: Whole x rental-share(2019-H2); …` |
| 2020-04 | **Omitted** from Rental & NonRental — COVID-lockdown data-revision anomaly (PDF rental BEV > recorded Whole BEV). | — |

The 2019-H2 reference shares (BEV 39.8 %, PHEV 42.4 %, HEV 18.5 %, PETROL
11.8 %, DIESEL 33.4 %, OTHERS 8.4 %, TOTAL 20.3 %) are the earliest *real*
rental data, pre-COVID and closest in time to the estimated span. Estimated
rows satisfy `Rental + NonRental == Whole` exactly. The 2015–2016 estimates
inherit the lower resolution of the underlying quarterly Whole rows (only
BEV/PHEV/HEV + TOTAL populated). Regenerate with
`scripts/estimate_italy_rental_history.py` (pure CSV arithmetic, no network).

## 2. PKW flow (Whole + Rental)

UNRAE has no public data API. The PKW bulletin is a two-page PDF:

```
Page 1 — whole market (including noleggio):
  Per utilizzatore table  →  (ignored)
  Per alimentazione table →  used for Whole
  Per segmento table      →  (ignored)
  Per area geografica     →  (ignored)

Then — fleet-excluded section:
  LA STRUTTURA DEL MERCATO ITALIANO DELL'AUTOMOBILE AL NETTO DEL NOLEGGIO
  Per alimentazione table →  used for NonRental directly
                              and subtracted from Whole → Rental
  Per segmento table      →  (ignored)
  Per area geografica     →  (ignored)
```

Discovery:

```
1. https://unrae.it/dati-statistici/immatricolazioni
   → find newest <a href="…/struttura-del-mercato-{mese}-{anno}">

2. GET that detail page
   → find <a href="…/files/NN Struttura del mercato {Mese} {Anno}_{hash}.pdf">
     (hash changes per upload; do not hardcode)

3. pdftotext -layout → locate both 'Per alimentazione' headers
   → parse first  block → Whole
   → Rental = Whole − second block  (exact, zero rounding error)
```

Both variants are written from a single PDF download.

## 3. PKW fuel mapping

| PDF row                                  | CSV column        |
|------------------------------------------|-------------------|
| Benzina                                  | PETROL            |
| Diesel                                   | DIESEL            |
| Gpl                                      | (part of OTHERS)  |
| Metano                                   | (part of OTHERS)  |
| Ibride elettriche (HEV)                  | HEV (full + mild) |
| Ibride elettriche plug-in (PHEV+REx)     | PHEV              |
| Elettriche (BEV)                         | BEV               |
| Idrogeno (FCEV)                          | (part of OTHERS)  |
| Totale mercato                           | TOTAL             |

`OTHERS = Gpl + Metano + Idrogeno`. Sanity check (strict): the script aborts if
`BEV+PHEV+HEV+PETROL+DIESEL+OTHERS` deviates from `Totale mercato` by more than
`max(50, 0.5%)`.

## 4. PKW number format

UNRAE uses Italian/European format: `.` as thousands separator, `,` as decimal.
Counts are always integers. The parser reads the first numeric token of each
table row and strips thousands separators. Subsequent columns (prior year,
YoY %, YTD, etc.) are ignored.

## 5. Vans flow (LCV)

UNRAE publishes a "Struttura del mercato" for **autocarri ≤ 3,5 t** next to the
passenger-car one, on the same index, slugged
`immatricolazioni-veicoli-commerciali-<mese>-<anno>`. Its 'Per alimentazione'
table gives exact counts per fuel, so Vans rows add up to `TOTAL` exactly.
(Until 2026-09 Vans were derived from percentages in the LCV *press release*;
that source broke on the combined July+August 2026 release, which only gave
year-to-date shares — see the 2026-10 note below.)

```
1. https://unrae.it/dati-statistici/immatricolazioni
   → newest (highest page id) <a href="…/immatricolazioni-veicoli-commerciali-…">

2. GET that page → its PDF (a few pages have none, see § 8)

3. pdftotext -layout → one 'Per alimentazione' table per month in the PDF
   (two in the July+August PDF).  Period from the table's own title
   "IMMATRICOLAZIONI - Agosto 2026" — not from the slug (see below).

4. Upsert that month, and — only if missing — the same month a year
   earlier from the table's comparison column (notes say so).
```

### Table layouts

| Tables from | Counts per fuel | Monthly value |
|---|---|---|
| 2025-02 → | month cur, month cmp, YTD cur, YTD cmp | read directly |
| 2018-05 → 2025-01 | YTD cur, YTD cmp only (plus every January, where YTD = month) | `backfill_italy_vans.py` only: Jan–M minus Jan–(M−1) |
| ≤ 2018-04, 2022-01, 2022-11 | none — monthly totals only | — (comparison columns of the next year fill some) |

Gotchas the parser handles, each seen in real PDFs:

- **Slug month ≠ data month.** Until 2023 the page for month M carried data
  up to M−1 (`aprile-2021` holds "Gennaio/Marzo 2021").
- **Comparison year ≠ year − 1.** The 2021 tables compare with 2019, not 2020.
  It is read from the header.
- **Blank cells mean 0** (Metano, often). Counts are mapped to columns by their
  right edge against the `totale` row, so a blank never shifts later values.
- **Every column must add up to its `totale`** or the parse fails.

### History: `scripts/backfill_italy_vans.py`

The fetcher only reads the newest PDF. The backfill walks all ~190 index pages
(≈ 110 LCV PDFs) and builds each month from, in order:

1. the month column of its own table (`notes` empty);
2. the comparison column of next year's table;
3. a YTD difference — all pairings of own-year and next-year (consolidated)
   YTD tables are tried and the one whose `TOTAL` is closest to UNRAE's
   published monthly total wins; > 2 % off, or any negative count, and the
   month stays empty;
4. a gap fill Jan–(M+1) − month M+1 − Jan–(M−1) when M has no table (2026-05).

Differencing two bulletins puts late registrations of earlier months into
month M; against UNRAE's monthly totals the median gap is < 0,01 % of
`TOTAL`, the worst kept ≈ 1 % (2020-04, 1 590 vans in lockdown). Step 3 matters: UNRAE's own Jan–Oct 2024 table moved
1 500 vans from Diesel to Gpl; the consolidated copy in the 2025 PDF is right,
and without the closest-total rule 2024-11 came out with negative Gpl.

Before 2020-07 the tables have no PHEV line (`Ibrido` / `Ibride` only):
`PHEV` is left empty and `notes` says so.

The backfill replaced the two press-release rows (2026-04, 2026-06). 2026-06
had PHEV 171 instead of 357: the regex read "**dall’**1,0% di un anno fa" (the
year-ago share) as the month's.

### Vans failures don't block PKW

`fetch_vans()` runs after the PKW block. When it raises, the script writes
`vans_failed=true` to `$GITHUB_OUTPUT` and exits non-zero; the workflow's
detect/commit steps run on `success() || vans_failed`, and the render job on
`!cancelled()`. So a broken LCV bulletin turns the run red but no longer
discards a PKW month fetched in the same run (as it would have on 2026-10-01).

### Vans fuel mapping

| Table row                                               | CSV column |
|---------------------------------------------------------|------------|
| Diesel                                                  | DIESEL     |
| Benzina                                                 | PETROL     |
| Ibridi elettrici (HEV) · before 2020-07: Ibrido / Ibride | HEV        |
| Ibridi elettrici plug-in (PHEV+REx)                     | PHEV (empty before 2020-07) |
| Elettrici (BEV) · before 2020-07: Elettrico / Elettriche | BEV        |
| Gpl + Metano (+ Idrogeno, not listed so far)            | OTHERS     |
| totale                                                  | TOTAL      |

`TOTAL` is the table's `totale`, which can differ slightly from the headline
monthly total on page 1 (August 2026: 8 376 vs 8 390 — the headline is a
projection).

## 6. Schedule

| Variant    | Published      | Polled                      |
|------------|----------------|-----------------------------|
| Whole      | ~1st of month  | 06/10/14/18 UTC, days 1–3   |
| Rental     | same PDF       | same schedule               |
| NonRental  | same PDF       | same schedule               |
| Vans       | ~10th of month | 10/14/18 UTC, days 8–16     |

All three scripts self-throttle: once the target period is in the CSV, runs are
no-ops until the next month.

## 7. Manual override

Dispatch `fetch-italy.yml` with manual inputs to bypass discovery:

- `pdf_url` + `year` + `month` → override PKW Struttura PDF
- `vans_pdf_url` → override the LCV struttura PDF (periods come from the PDF)
- `variant` → restrict to a specific variant (default: `all`)
- `force` → re-process even if period already in CSV

## 8. Known limitations

- **HDV not available.** Neither the HDV Comunicato Stampa nor the
  "immatricolazioni-veicoli-industriali" struttura PDF (checked 2026-10 on
  the July+August 2026 one) has a fuel-type breakdown — only volume by weight
  class. HDV cannot be added without a new structured data source.
- **Vans gaps.** No row for months before 2017-05, June/July 2017–2021, July/August
  2023 (UNRAE only gives the Jan–August sum for
  those), 2020-09/10/11/12 and 2021-10 (no table, or every derivation > 2 %
  off the monthly total), 2025-11/12 (pages without PDF; the fetcher fills
  them from the comparison columns of the 2026-11/12 tables).
- **Vans pre-2025 rows are differences** of year-to-date tables (flagged in
  `notes`); late registrations of earlier months land in the month.
- **PKW PDF layout dependency.** If UNRAE restructures the Struttura del
  mercato (column order, section headings, fuel naming), the strict sanity
  check guards against silent misparses.
- **Pre-2019-06 Rental/NonRental are estimates.** UNRAE PDFs before 2019-06
  carry no rental breakdown; those rows are modelled from Whole × 2019-H2
  rental shares and flagged in the `notes` column (see §2). They assume a
  flat rental share back through 2015 — adequate for fitting the long-run
  adoption curve, but not month-accurate, and 2015–2016 inherit the
  quarterly-approximation resolution of their Whole source.

## 9. Findings and decision log (Vans, 2026-10)

Everything learned while the Vans fetcher broke and was moved to the LCV
struttura tables (PRs #271, #272), so the next person does not have to
rediscover it. Findings are facts about the source, each with the evidence that
showed it; decisions are the choices made on top of them, with the reason and
the alternative that was turned down. To re-check any number here:
`python scripts/backfill_italy_vans.py --dry-run --cache-dir <dir>` re-downloads
and re-derives the whole history in a few minutes.

### 9.1 Findings

| # | Finding | Evidence |
|---|---|---|
| F1 | UNRAE's **LCV press release** for July + August 2026 (2026-09-10) gives each month's total and BEV share, but every other fuel share **only for January–August**. The old percentage parser put August's BEV share (7,0 %) and the YTD shares on July's total; the shares added up to 103,4 % and the sanity check refused the row. Every `fetch-italy.yml` run from 2026-09-15 to 2026-10-01 failed this way. | run 36832351407: `sum=16461 vs TOTAL=15921 (diff=540)` |
| F2 | The script fetched PKW first and Vans second, and the commit step ran only on success, so a Vans exception also **discarded a PKW month** written seconds earlier. It would have hit the September 2026 PKW data on 2026-10-01. | `fetch-italy.yml` before #271 |
| F3 | The press-release regex `all['’]` also matched inside "**dall’**1,0% di un anno fa" — the year-ago share. 2026-06 Vans was stored with PHEV 171 (1,0 %) instead of 357. The lenient tolerance (2 %) hid it. | June 2026 release, §5 |
| F4 | A **structured LCV table exists**: "Struttura del mercato" for autocarri ≤ 3,5 t on the passenger-car index (`immatricolazioni-veicoli-commerciali-<mese>-<anno>`), with exact counts per fuel. Pages exist from 2016-06. Fuel tables start in the 2018-05 page. Monthly fuel columns start in 2025-02; before that the table is January-to-date only. | 112 pages found walking all ~190 index pages |
| F5 | **Slug month ≠ data month** until 2023: the `aprile-2021` page holds "Gennaio/Marzo 2021". From 2023 the slug names the data month. | table titles vs. slugs |
| F6 | **The comparison year is not always year − 1**: the 2021 tables compare with **2019** (COVID). The first draft assumed year − 1 and filed 2019 values under 2020. | header row `2021 (°)  2019`, `aprile-2021` |
| F7 | **Blank cells mean 0** (often Metano, sometimes a 0 comparison value). Splitting on whitespace shifted every later value one column left; values have to be matched to columns by position. | July 2026 table, Metano 2025 column |
| F8 | **Pages without a PDF** (empty page body): 2016-11, 2020-11, 2020-12, 2025-01, 2025-11, 2025-12, 2026-05. **PDFs without a fuel table** (totals only): all up to the 2018-04 page, 2022-01, 2022-11. | `find_lcv_pdf_url` → None; no 'Per alimentazione' |
| F9 | July + August always share one page. Which tables it holds varies: Jan–July only (2018–2022), Jan–August only (2023), none for July (2024: only an `agosto-2024` page), both monthly (2025, 2026). So 2017–2021 June/July and 2023 July/August can only be split as a sum. | per-page table titles |
| F10 | **UNRAE's own Jan–Oct 2024 table is misprinted**: Gpl 5 943 and Diesel 138 967, where the consolidated copy in the Jan–Oct 2025 table's comparison column has 4 443 / 140 499. That means 1 500 vans booked under the wrong fuel; the total is unchanged. Taking the difference against it made 2024-11 Gpl negative (−1 070). | `novembre-2024` page vs `ottobre-2025` page |
| F11 | **Bulletins get revised.** A later table restates earlier YTD figures with late registrations. Own (provisional) vs. next-year (consolidated) YTD values differ by up to ≈ 1 %, mostly in Diesel. Where a direct monthly value and a YTD difference both exist (2025-02 … 2026-08), they agree to within 0,6 % of TOTAL, except 2025-09 (Diesel +319, ≈ 2 %). | comparison run during #272 |
| F12 | **Mixing a provisional with a consolidated endpoint amplifies the revision**: 2021-11 came out 936 too high when computed as consolidated Jan–Nov minus provisional Jan–Oct, because the revisions of ten months landed in one. | vs. UNRAE monthly total 15 472 |
| F13 | The table `totale` can differ from the headline monthly total on page 1. In August 2026 it was 8 376 vs. 8 390: the headline is a projection ("In corsivo proiezioni"), the table is registrations to date. | `luglioagosto-2026` PDF |
| F14 | **No PHEV line before 2020-07.** The hybrid line is `Ibride` (2018) / `Ibrido` (2019–2020-06); PHEV volumes then were single digits. | table rows |
| F15 | Real outlier, not a parse error: 2023-05 PHEV 466 (neighbours ~90–150). The consolidated YTD reads 212 (Apr), 678 (May), 828 (Jun). Likewise 2021-11 BEV 948. | YTD columns |
| F16 | **HDV still has no fuel split**: the `immatricolazioni-veicoli-industriali` struttura PDF (checked on July + August 2026) has weight classes only. | §8 |
| F17 | The LCV struttura PDF appears around the 10th, at about the same time as the press release or slightly before it. For July + August 2026, the table data are "al 04/09/2026" and the press release is dated 2026-09-10. The exact publication day is not recorded on the page. | PDF footer, press release |

### 9.2 Decisions

| # | Decision | Why | Turned down |
|---|---|---|---|
| D1 | A Vans failure writes `vans_failed=true` to `$GITHUB_OUTPUT` and exits non-zero. Detect + commit run on `success() \|\| vans_failed`, render on `!cancelled()`. (#271) | F2: PKW must never be lost to a Vans problem, but a broken Vans parse must stay visible (red run). | Warning + exit 0: green runs would hide a broken parser for weeks. |
| D2 | Vans source = the LCV **struttura table**, not the press release. (#272) | F1, F3, F4: exact counts, no prose regex, history back to 2017. | Repairing the regexes: a combined release still has no monthly split (F1), so it cannot be repaired. |
| D3 | The Vans history was **rewritten**, including the two existing press-release rows (2026-04, 2026-06). This is a deliberate exception to "don't rewrite the past", agreed with the owner on 2026-10-01. | Source switch; the old rows were percentage-derived and 2026-06 was wrong (F3). | Keep old rows and converge forward: it would have left a known-wrong PHEV and two methods in one series. |
| D4 | Precedence per month: **(1) own table's month column → (2) next year's comparison column → (3) YTD difference → (4) YTD gap fill**. | (1) is what the live fetcher writes, so backfilled and fetched months are the same kind of number. (2) is a real published monthly figure. (3)/(4) are derived and flagged. | Preferring the consolidated (2) over the provisional (1) everywhere would be slightly more accurate, but would make old months a different vintage than new ones. Revisit if consistency matters less than accuracy. |
| D5 | For (3), try all four pairings of own / next-year YTD for M and M−1 and keep the one whose TOTAL is **closest to UNRAE's monthly total**. Reject the month if all are > 2 % off or any count is negative. | F10 and F12: a fixed preference ("consolidated first, then own") failed both ways — mixed endpoints in 2021-11, and the misprint in 2024-10/11. UNRAE's monthly totals (page 1 of every PDF, later PDFs win) are an independent check. The 2 % threshold separates the revision noise (all kept months ≤ 1,1 %) from broken pairings (2020-09: 2,4 %, 2021-10: 2,5 %), which stay empty. | Hand-patching the misprinted 2024-10 value: not reproducible, and the next misprint would need another patch. |
| D6 | Before 2020-07 **`PHEV` stays empty**, not 0, and `notes` says HEV covers all hybrids. | F14, invariant 4 (empty ≠ 0). | 0: would assert "no plug-in vans", which the source does not say. |
| D7 | `OTHERS` = Gpl + Metano (+ Idrogeno if it ever appears). Before, it was Gpl only. | Explicit rows in the table; matches the PKW mapping. | — |
| D8 | `TOTAL` = the table's `totale`, not the headline total. | F13: consistent with the fuel columns, and every row adds up exactly. | Headline: it is a projection and does not match the fuel split. |
| D9 | The fetcher fills the **same month a year earlier only if it is missing**, and never overwrites. | Closes source gaps (2025-11/12 via the 2026-11/12 tables) without silently changing published history. | Overwriting with consolidated values on every run: endless churn in the CSV. |
| D10 | A newest page **without a PDF is a warning** (`::warning::`), not a failure. | F8: it is a gap in the source, and a red run every day until the next month would teach people to ignore red. | Failure. |
| D11 | Vans cron on the **8th–16th** (was 13th–16th). | F17. | — |
| D12 | **No estimates for the gaps** (June/July 2017–2021, July/August 2023, 2020-09…12, 2021-10, 2025-11/12). The rows are simply absent. | Splitting a two-month sum by the totals' ratio would be a modelled value. Vans is not rendered, and gaps are honest. | Proportional split, flagged in notes: possible later if Vans ever gets rendered and the gaps hurt the fit. |
| D13 | The interim fix of #271 (skip a combined press release by its slug) is **superseded** by D2 and removed in #272. | — | — |

## 10. Top brands / models (`market/italy_top.json`)

Whole market, **BEV and PHEV**, shown on the source page ("Who sells the
electrified cars") with a month picker; the default view is the trailing
twelve months. Built by `refresh_market_top()` in `fetch_italy.py` behind
`market_top.guarded` (it never blocks the data), whenever the top file is
behind the newest month. The month store is `market/italy_months.json`.
Committed, never rendered. Generic mechanics: `03-data-objects.md` §3.16.

### 10.1 Source

UNRAE publishes, alongside the struttura, one PDF per month and class:
`immatricolazioni-bev-per-modello-<mese>-<anno>` and
`…-phev-per-modello-…`. Each lists every model with its brand (only the top 100
since 2026-05), then `altre` and `Totale`. The list is **always January to
date** ("8 mesi 2026"; January is titled "gennaio 2026"). Available from
2023-11 on the index.

```
single month M     = list(M) − list(M−1)                (January: list(1))
trailing 12 at T   = list(T) + list(Dec of T−1) − list(T one year earlier)
```

The headline is computed from three lists directly, not by adding up single
months. It is therefore complete even where a month is missing, and unaffected
by one month's distortion.

### 10.2 Findings

| # | Finding | Evidence |
|---|---|---|
| M1 | **No rental split exists** for brands or models: no UNRAE table crosses brand with the rental channel. Only Whole can have a top list. | all brand/model publications on the index, 2026-10 |
| M2 | **HEV has no full list**: only `top-10-per-alimentazione` (top 10 models + `altre`, month and YTD). A brand ranking cannot be derived from it. HEV here also includes mild hybrids (§3). | that PDF |
| M3 | **No January 2026 lists** were published (neither BEV nor PHEV, nor the "per marca" tables). So 2026-01 and 2026-02 cannot be split; the month picker skips them. | index walk, 2026-10 |
| M4 | The **"per marca" tables** (BEV/PHEV by brand, XLSX) only exist from 2026-05. The brand ranking is therefore summed from the model lists. | index walk |
| M5 | From the 2026-05 list on, UNRAE **truncates to the top 100** models. `altre` then grows from ~0,2 % to 2,7 % (BEV). A model crossing rank 100 between two months shows up in the difference with all its earlier units at once. It only affects models with a few dozen units. | `altre` per list |
| M6 | **Model names change between lists**: `ATTO2` / `ATTO 2`, `N? 4` / `N4` (DS: pdftotext turns the `°` of "N° 4" into `?`). Matching is on letters and digits only; display is the newest spelling, `?` → `°`. | Jul/Aug 2026, Apr–Jun 2026 lists |
| M7 | UNRAE's lists contain a ranked **catch-all row** `ALTRE ESTERE  ALTRI TIPI`. It is counted as unranked rest. | e.g. rank 81, BEV 2026 |
| M8 | **Kia Sportage left the 2026 PHEV lists in May 2026**, retroactively for January to April too (−3 049 between the April and May lists). The struttura months January–April were not restated. So the list-based PHEV twelve months are 2,0 % below `data/Italy.csv`. BEV is within 0,03 %. Single-month PHEV for 2026-05 (difference) is +1,1 % against the CSV. | refresh log; April vs May 2026 lists |
| M9 | **Cross-check of single months** against UNRAE's own monthly `top-10-per-alimentazione` (real monthly figures, not differences): 2025-11, 2026-05, 2026-07, BEV and PHEV top 10. 54 of 60 models match exactly. The rest differ by 1–8 units, except one BEV model in 2026-05 at −43. The class totals of the differences are within a few units of `data/Italy.csv`, except PHEV 2026-05 (M8). | session 2026-10-01 |
| M10 | All 66 lists from 2023-11 to 2026-08 parse, with models + `altre` = `Totale` exactly. Brand and model columns are separated by two or more spaces. The column offsets shift from line to line, so a fixed-position split does not work. | backfill run |

### 10.3 Decisions

| # | Decision | Why | Turned down |
|---|---|---|---|
| MD1 | **BEV + PHEV, Whole only.** | M1, M2. | HEV with a brand ranking from the top 10 only: it would credit a brand with only its top-10 models. |
| MD2 | **Headline = exact trailing 12 months from three YTD lists**, not the sum of stored months. | Complete despite M3, and unaffected by M5/M8 distortions of single months. Owner's wish: the twelve-month sum as the default view. | Summing stored months: it would miss Jan/Feb 2026 and carry every month's artefacts. YTD headline (like Austria/Portugal): it restarts every January. |
| MD3 | Single months by **difference**. A model with a negative difference is not ranked, and the part of the class total not explained by ranked models goes to the unranked rest (never below 0). | M5, M6, M8: the class total stays the source's; a negative count would be nonsense on the page. | Single months from `top-10-per-alimentazione`: exact, but only 10 models and no brand ranking. |
| MD4 | Model identity = letters and digits of brand + model; display = newest spelling. | M6. | A hand-kept alias table: more upkeep for the same effect so far. |
| MD5 | The **brand ranking is summed from models**. | M4: the brand tables only exist from 2026-05. | — |
| MD6 | The window total (`total_registrations`) and month totals come from `data/Italy.csv`. The list-vs-CSV class gap is printed on every refresh, not enforced. | M8 is UNRAE's own inconsistency; aborting would hide the tables for a year. | `check_scope` with abort: it would have failed on M8. |

