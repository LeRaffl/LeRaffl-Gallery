# 18 · Source: Italy (UNRAE)

UNRAE (Unione Nazionale Rappresentanti Autoveicoli Esteri) publishes monthly
registration bulletins as PDFs. Two distinct publications are used:

- **PKW "Struttura del mercato"** — passenger cars, from
  `unrae.it/dati-statistici/immatricolazioni`, typically on the **1st (sometimes
  2nd) of the following month**.
- **LCV "Comunicato Stampa"** — light commercial vehicles, from
  `unrae.it/sala-stampa/veicoli-commerciali`, typically on the **14th of the
  following month**.

## TL;DR

```
Variants:
  Whole   data/Italy.csv        PKW whole market (inkl. Noleggio)
  Rental  data/Italy_Rental.csv PKW rental fleet = Whole − (al netto del noleggio), exact
  Vans    data/Italy_Vans.csv   LCV (veicoli commerciali leggeri) ⚠ pct-derived

NOTE: Italy does NOT expose Private/Industry splits comparable to Denmark/Finland.
  The PDF only provides Whole and "al netto del noleggio" fuel breakdowns.
  'Rental' = noleggio a lungo + noleggio a breve + autoimm. uso noleggio.
  A Private/Industry split by juridical person is not available per-fuel.

PKW source:  UNRAE struttura-del-mercato PDF (Whole + Rental from one download)
Vans source: UNRAE LCV Comunicato Stampa PDF (separate page, separate schedule)
Auth:        None
FLEXFUEL:    Not reported by Italy — column absent from all three CSVs
HEV:         Reported natively as 'Ibride elettriche (HEV)' (full + mild sum)
OTHERS (PKW): Gpl + Metano + Idrogeno (FCEV) — explicit, not a residual
OTHERS (Vans): derived GPL count; unlisted fuels not separately extractable
Schedule:    PKW  4×/day on the 1st–3rd  (06/10/14/18 UTC)
             Vans 3×/day on the 13th–16th (10/14/18 UTC)
Scripts:     scripts/fetch_italy.py
Workflow:    .github/workflows/fetch-italy.yml
```

## 1. CSV schema note

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
  Per alimentazione table →  subtracted from Whole → Rental
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

UNRAE publishes LCV data only as a narrative "Comunicato Stampa" press release
(not as a structured data table). Absolute counts are therefore **derived**:

```
1. https://unrae.it/sala-stampa/veicoli-commerciali
   → find newest <a href="…/veicoli-commerciali-leggeri-{...}">
     (month name embedded in slug; year inferred from today)

2. GET that detail page → find the first PDF link

3. pdftotext -layout → extract from prose:
     total  from "posizionano a NN.NNN unità"
     diesel from "diesel ... al XX,X%"
     benzina, gpl, plug-in, BEV, ibridi similarly

4. Compute: abs_count = round(pct / 100 × total)
```

⚠ **Data quality caveat**: percentages are rounded to one decimal in the press
release. The derived counts typically deviate from the true values by ±1–5
units per fuel type. The sanity check uses a lenient tolerance of
`max(200, 2%)` for Vans rows. This deviation is documented in `notes` if needed.

### Vans regex patterns

The LCV percentage patterns (`_LCV_PCT` in the script) match sentence-scoped
text (stopping at `.`) to avoid picking up cumulative YTD percentages. They
rely on UNRAE's PR agency keeping consistent phrasing. If the Comunicato
Stampa phrasing changes, update `_LCV_PCT` and re-run with `--force`.

Verified against April 2026 LCV bulletin (May 14 2026 release).

### Vans fuel mapping

| Press-release phrase                              | CSV column        |
|---------------------------------------------------|-------------------|
| diesel … al XX,X%                                 | DIESEL            |
| benzina … al XX,X%                                | PETROL            |
| veicoli ibridi … XX,X% del totale                 | HEV               |
| veicoli plug-in … al XX,X%                        | PHEV              |
| veicoli BEV … al XX,X%                            | BEV               |
| Gpl … all' XX,X%                                  | OTHERS (GPL only) |
| Metano, Idrogeno etc.                             | (not mentioned)   |

`OTHERS` for Vans = derived GPL count only. Metano and Idrogeno registrations
for LCV are not reported in the Comunicato Stampa text; they would be negligible
(<<1% combined).

## 6. Schedule

| Variant | Published    | Polled                        |
|---------|--------------|-------------------------------|
| Whole  | ~1st of month  | 06/10/14/18 UTC, days 1–3  |
| Rental | same PDF       | same schedule               |
| Vans   | ~14th of month | 10/14/18 UTC, days 13–16   |

All three scripts self-throttle: once the target period is in the CSV, runs are
no-ops until the next month.

## 7. Manual override

Dispatch `fetch-italy.yml` with manual inputs to bypass discovery:

- `pdf_url` + `year` + `month` → override PKW Struttura PDF
- `vans_pdf_url` + `year` + `month` → override LCV Comunicato Stampa PDF
- `variant` → restrict to a specific variant (default: `all`)
- `force` → re-process even if period already in CSV

## 8. Known limitations

- **HDV not available.** The HDV Comunicato Stampa (`/sala-stampa/
  veicoli-commerciali` entries for "veicoli industriali") contains no
  fuel-type breakdown — only volume by weight class. HDV cannot be added
  without a new structured data source.
- **Vans derived counts.** Absolute counts for Vans are computed from rounded
  percentages; true values may differ by ±1–5 units per fuel type.
- **LCV regex fragility.** `_LCV_PCT` patterns depend on UNRAE's PR phrasing.
  If a month's Comunicato Stampa uses different wording, a WARNING is printed
  and the affected column defaults to 0. Run with `--force` after fixing.
- **PKW PDF layout dependency.** If UNRAE restructures the Struttura del
  mercato (column order, section headings, fuel naming), the strict sanity
  check guards against silent misparses.
