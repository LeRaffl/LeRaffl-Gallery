---
country: South Africa
slug: south_africa
method: file
summary: Quarterly new-vehicle sales in South Africa with naamsa's battery-electric,
  plug-in hybrid and hybrid counts, read automatically from naamsa's Quarterly Review of
  Business Conditions. The split exists only for the whole new-vehicle market — cars,
  bakkies, minibuses, trucks and buses together — not for passenger cars alone.
source_name: naamsa — Quarterly Review of Business Conditions (New energy vehicle sales)
source_url: https://naamsa.net/
source_links:
- label: naamsa media library — quarterly reviews (the list the fetcher reads)
  url: https://naamsa.net/wp-json/wp/v2/media?search=Review%20of%20Business%20Conditions&per_page=100
  note: public WordPress JSON; every review is a PDF named like 20260820-naamsa-2nd-Quarter-2026-Review-of-Business-Conditions.pdf
- label: 2nd quarter 2026 review (PDF)
  url: https://naamsa.net/wp-content/uploads/2026/08/20260820-naamsa-2nd-Quarter-2026-Review-of-Business-Conditions.pdf
  note: page 6 — the NEV drivetrain table (2020–2025 years, Q2 2025, Q2 2026); section 7 — the quarter's passenger and commercial vehicle sales
- label: naamsa press releases (monthly new-vehicle sales)
  url: https://naamsa.net/press-releases/
  note: monthly totals by segment; the NEV split there is year-to-date prose only, so the monthly releases are not used for the chart
underlying: naamsa (the Automotive Business Council) — new-vehicle sales reported by its member and reporting brands, compiled with Lightstone Auto
auth: none
cadence: daily on the 10th–31st of February, May, August and November, 12:25 UTC — naamsa publishes the review 7–8 weeks after the quarter ends (2024–2026 between the 15th and the 27th)
variants:
- Whole
variant_notes:
  Whole: The whole new-vehicle market as naamsa reports it — passenger cars, light commercial vehicles up to 3,500 kg (bakkies and minibuses), medium (3,501–8,500 kg), heavy (8,501–16,500 kg) and extra-heavy (over 16,500 kg) commercial vehicles and buses over 8,500 kg. Not new passenger cars (EU M1) — naamsa does not split its drivetrain table by segment. Motorcycles are not in naamsa's statistics.
hev_split: true
hev_note: naamsa reports "Traditional hybrid" (HEV, including mild hybrids as the brands report them) and "Plug-in hybrid" (PHEV) as separate lines; range-extender EVs are not separated and sit wherever the brand reports them.
backfill: quarterly from 2023-Q1 out of the reviews naamsa's media library holds (2024-Q1 review onward — each review repeats the year-ago quarter); 2021 and 2022 as yearly rows on the mid-year month. Earlier years exist as NEV counts (2019, 2020) but without a published total-market figure in the same scope, so they are left out.
scope_note: New vehicles sold in South Africa per quarter, every segment naamsa covers, as reported by the brands that report to naamsa / Lightstone Auto (30 brands for the NEV table in 2026). Exports are not included. The battery-electric share of new passenger cars alone is not published and is higher than the share shown here, because trucks, bakkies and buses are in the denominator.
caveats:
- 'NOT passenger cars: the BEV / PHEV / HEV counts and the total are the whole new-vehicle market (cars + LCV incl. bakkies and minibuses + MCV + HCV + XHCV + buses). naamsa relates its NEV table to "total new vehicle sales" (Q2-2026 review, p. 6: "NEV sales comprised 5,6% of total new vehicle sales"), and its September 2026 release says electrification "is also beginning to extend beyond the passenger vehicle market, with emerging adoption across the light and medium commercial vehicle segments". Compare South Africa with other countries'' car curves with care.'
- Quarterly, not monthly — each row sits on the quarter's middle month (Feb, May, Aug, Nov); 2021 and 2022 are one yearly row each on June.
- ICE is the total minus the NEVs; naamsa publishes no petrol / diesel split of the new-vehicle market.
- naamsa restates recent quarters by a few units in later reviews; the newest review wins.
- The Q4-2025 review printed the plug-in and traditional hybrid values of its two quarter columns in each other's rows; the fetcher detects this against the annual column and swaps them back (§5).
- There is no brand or model table — naamsa publishes brands' total sales, but not by drivetrain.
processing:
- title: Find the reviews
  text:
  - naamsa's website is WordPress; its media library answers a public JSON search. The fetcher asks it for "Review of Business Conditions" PDFs (one small request), keeps one file per upload date (naamsa sometimes uploads a signed and an unsigned copy) and reads the quarter from the file name. When that quarter is already in the chart it stops there.
- title: Read the review
  text:
  - The PDF is turned into text and two things are read from it. Section 7 states the quarter's aggregate new passenger car sales and aggregate commercial vehicle sales, with the same quarter a year earlier. The NEV section has a table with one line per drivetrain, by year and for the quarter and the year-ago quarter. Every column of that table must add up to its "Total NEVs" line, or the review is not used.
  decision:
    ask: naamsa NEV table line?
    branches:
    - when: Electric
      then: BEV
    - when: Plug-in hybrid
      then: PHEV
    - when: Traditional hybrid
      then: HEV
    - when: Total NEVs
      then: check only — must equal the three lines above
- title: Which vehicles are counted
  text:
  - naamsa's table covers every new vehicle the reporting brands sell — it has no segment split, so nothing is reclassified here and the chart is the whole market, not passenger cars.
  decision:
    ask: naamsa segment?
    branches:
    - when: Passenger cars (incl. SUVs)
      then: Whole
    - when: Light commercial vehicles ≤ 3,500 kg (bakkies, minibuses)
      then: Whole
      note: in the NEV table and in the total — not separable
    - when: Medium, heavy and extra-heavy commercial vehicles
      then: Whole
      note: in the NEV table and in the total — not separable
    - when: Buses over 8,500 kg
      then: Whole
    - when: Motorcycles, used vehicles, exports
      then: in no variant
      note: not in naamsa's domestic new-vehicle statistics
- title: Build the row
  text:
  - TOTAL is passenger plus commercial sales of the quarter; ICE is TOTAL minus BEV, PHEV and HEV. The row sits on the quarter's middle month. Every review repeats the year-ago quarter, often slightly revised — reviews are read oldest first, so the newest figure wins.
- title: Check it
  text:
  - For every year whose four quarters and annual column are known, the quarters must add up to the year (within a few units — naamsa's restatements). If they only add up with one quarter's plug-in and hybrid values exchanged, that quarter was printed in the wrong rows and is swapped back; otherwise the gap is reported and the published values stay. The newest quarter's total must be at least 75 % of the same quarter a year earlier (a warning below 90 %).
  decision:
    ask: Do the year's quarters add up to its annual column?
    branches:
    - when: "yes"
      then: written as published
    - when: no — but they do with one quarter's PHEV / HEV exchanged
      then: that quarter swapped back, reported in the run summary
      note: happened with the Q4-2025 review (2024-Q4 and 2025-Q4 columns)
    - when: no
      then: written as published, the gap reported
fetcher: scripts/fetch_south_africa.py
workflow: .github/workflows/fetch-south-africa.yml
fragility_doc: docs/architecture/56-source-south-africa.md
data_file: data/South Africa.csv
---

# 56 · Source: South Africa (naamsa Quarterly Review of Business Conditions)

**Status: LIVE from this PR.** Fetcher `scripts/fetch_south_africa.py`
(+ tests `scripts/test_fetch_south_africa.py`), workflow
`.github/workflows/fetch-south-africa.yml`. Replaces the 2026-07 probe
(`fetch_southafrica.py`, `fetch-southafrica.yml`). The gallery's first
African market.

> **Scope in one line:** the whole South African *new-vehicle* market
> (cars + bakkies/minibuses + trucks + buses), **not** new passenger cars (M1).

## TL;DR

```
naamsa.net (WordPress)
  └─ /wp-json/wp/v2/media?search=Review of Business Conditions   (JSON list)
       └─ YYYYMMDD-naamsa-<n>-Quarter-YYYY-Review-of-Business-Conditions.pdf
            ├─ §7  "aggregate industry new passenger car sales at N units …
            │       commercial vehicle sales … at M units"   (quarter + year ago)
            └─ NEV table: Traditional hybrid / Plug-in hybrid / Electric / Total NEVs
                          years 2019|2020 … last year, Q(year-1), Q(year)
                 │
                 ▼  fetch_south_africa.py   (pdftotext -layout)
  Electric→BEV · Plug-in hybrid→PHEV · Traditional hybrid→HEV
  TOTAL = passenger + commercial · ICE = TOTAL − NEVs · row on the middle month
                 │
                 └─ data/South Africa.csv   (line-level upsert, Whole, quarterly)
```

## 1. Why this source clears the bar (doc 14)

- **(a) the recognised body.** naamsa is the industry council that has
  published South Africa's official new-vehicle sales for decades; its data is
  compiled with Lightstone Auto and covers effectively the whole formal market
  including the Chinese entrants (BYD, Chery, GWM, Jetour, Omoda/Jaecoo report).
  There is no government registration statistic with a drivetrain split.
- **(b) complete enough.** The NEV table counts "30 industry brands" (2026).
  naamsa notes that new entrants started reporting in 2026, which lifted the
  NEV count — a real but small completeness drift, mentioned in the footnote.
- **(c) free and machine-readable.** Plain PDFs with a text layer, listed by a
  public JSON API; runners and the box reach naamsa.net without blocking
  (checked 2026-10-14). The Q4-2024 review is the one file whose first
  download looked image-only; a clean re-download parsed fine.

## 2. What exactly is counted — the segment definition

naamsa's domestic sales statistics have six segments (Flash Report December
2025, "New Vehicle Sales Totals"): **Passenger**, **Light CV < 3501 kg**
("light commercial vehicles, bakkies and minibuses"), **Medium CV
3501–8500 kg**, **Heavy CV 8501–16500 kg**, **Extra Heavy CV > 16500 kg**,
**Bus > 8500 kg**. Their sum is the "Industry Total" / "aggregate new vehicle
sales". Motorcycles are not part of naamsa's statistics.

The NEV table relates to that total, not to passenger cars:

- Q2-2026 review, p. 6: *"NEV sales comprised 5,6% of total new vehicle sales
  during the second quarter 2026"* — 8,611 / (109,236 + 43,883) = 5.62 %.
- Q2-2026 review, p. 6: *"For the full year 2025, NEV sales by 30 industry
  brands increased by 7,1% to 16,716 units … and comprised 2,8% of the total
  new vehicle market"* — 16,716 / 596,818 = 2.80 %.
- September 2026 media release, p. 2: *"Electrification is also beginning to
  extend beyond the passenger vehicle market, with emerging adoption across
  the light and medium commercial vehicle segments."*

**No segment-level drivetrain split exists in any naamsa publication checked**
(10 quarterly reviews 2024-Q1 … 2026-Q2, the monthly media releases and flash
reports). The flash reports list brands' total sales (top 15, local/export)
but no models and no drivetrain. Monthly passenger-car totals exist (e.g.
September 2026: 44,291), but without a drivetrain split, so an M1 series
would need an invented split — not done. No own classification is applied.

## 3. Row layout

`period` = middle month of the quarter (`Q1→-02 … Q4→-11`),
`time_interval = quarterly` (yearly rows: `YYYY-06`, `yearly`),
`variant = Whole`, `source = naamsa.net`, columns
`BEV, PHEV, HEV, ICE, TOTAL` (integers), `notes` names the scope.

## 4. History

| Rows | From |
|---|---|
| 2021-06, 2022-06 (yearly) | NEV years from the reviews' annual columns; TOTAL 2022 = 529,556 (Flash Report Summary Dec 2023, "Dec 2022 YTD"), TOTAL 2021 = 464,322 (sum of the four segment histories in Flash Report Standard Dec 2025). Written by `--backfill` only (`BOOTSTRAP_ROWS`). |
| 2023-02 … 2023-11 | year-ago columns of the 2024-Q1 … 2024-Q4 reviews |
| 2024-02 … 2026-05 | the reviews 2024-Q1 … 2026-Q2 (newest restatement wins) |

16 rows — below the 24 rows `R/build_backtest.R` needs, so South Africa is in
no Time-lapse month yet; it will enter by itself once the series is long enough.

## 5. Governance

| Check | What happens |
|---|---|
| Column sum | every NEV column must equal "Total NEVs" — else the review is skipped and listed |
| Year reconciliation | four quarters vs the annual column, ±max(5, 0.5 %); a PHEV↔HEV swap in one quarter that fixes it is applied and reported (Q4-2025 review: 2024-Q4 printed 4,156 / 261, 2025-Q4 3,452 / 1,026 in the wrong rows) |
| Completeness | newest total < 75 % of the year-ago quarter aborts (`--force` overrides), < 90 % warns |
| Foreign rows | a row with another `source` is never overwritten without `--force` |
| Restatements | rows from `naamsa.net` are overwritten by a newer review and listed as `updated` |
| Unknown layout | a review the parser cannot read is listed in the summary; the run fails only if none can be read |

Cross-check against naamsa's own sentences: 2026-Q2 NEV share 5.62 % (naamsa
"5,6 %"); 2025 NEVs 16,716 = 2.80 % of 596,818 (naamsa "2,8 %").

## 6. Operations and debugging runbook

| Symptom | Likely cause | Action |
|---|---|---|
| "naamsa media library lists no quarterly review" | WordPress search changed / blocked | open the media API URL above in a browser; adjust `list_reviews()` search terms |
| a review "not parsed (section-7 sales sentence not found)" | wording changed | add the new phrasing to `SALES_RE` and a test case |
| "NEV year header not found" | new header layout | extend the header search in `parse_review()`; add the layout to the tests (two layouts covered: `2020 …`, `FY2020 …`, `Year 2020 …`) |
| "quarters differ from the annual column … kept as published" | a restated year or a new print error | compare with the PDF; if it is a print error of a new kind, extend `reconcile()` |
| completeness guard fired | partial or wrong review | read the PDF; re-run with `force` only if the drop is real |
| rebuild offline | — | `python scripts/fetch_south_africa.py --backfill --dump-dir /tmp/za` once, then `--from-dir /tmp/za` |

```mermaid
sequenceDiagram
  participant GH as fetch-south-africa.yml
  participant WP as naamsa.net media API
  participant PDF as review PDF
  participant CSV as data/South Africa.csv
  GH->>WP: search "Review of Business Conditions"
  WP-->>GH: PDF list
  alt newest quarter already in CSV
    GH-->>GH: exit (self-throttle)
  else
    GH->>PDF: download 2 newest
    GH->>GH: parse, reconcile, guard
    GH->>CSV: line-level upsert
    GH->>GH: dispatch render-country.yml (South Africa, Whole)
  end
```

## 7. What would make it better

- A segment-level (passenger-car) drivetrain table from naamsa or Lightstone
  — then a true `Whole` (M1) and a `Vans` variant.
- A monthly NEV split (the monthly releases carry year-to-date prose only).
