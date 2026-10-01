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
