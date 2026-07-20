---
country: Nepal
slug: nepal
status: live
method: file
summary: >-
  Vehicle-import figures for Nepal from the Department of Customs' monthly
  cumulative Foreign Trade Statistics workbooks (HS 8703).
source_name: "Department of Customs — customs.gov.np (FTS workbooks)"
source_url: "https://www.customs.gov.np/"
underlying: "Department of Customs, ASYCUDA World customs records"
auth: "none (public downloads)"
cadence: "daily 07:50 UTC; cheap-skips until DoC publishes a new month"
variants: [Whole, 3-Wheelers]
hev_split: false
backfill: "monthly from 2020-08; pre-2020 not splittable (see §7)"
scope_note: >-
  Whole = HS 8703 cars/jeeps/vans (≈ EU M1) excl. three-wheelers; figures
  are imports, not registrations — Nepal imports its entire vehicle market.
caveats:
  - "Figures are customs imports, not registrations (no domestic car production; import ≈ market)."
  - "Nepali-calendar months (mid-month to mid-month) are labelled by their Gregorian end month."
  - "Hybrids are one combined bucket (PHEV/HEV boundary in the tariff codes is unreliable); tiny volumes either way."
  - "Passenger three-wheelers (auto-/e-rickshaws) are split into their own 3-Wheelers series — they would otherwise dwarf the BEV car count."
fetcher: "scripts/fetch_nepal.py"
workflow: ".github/workflows/fetch-nepal.yml"
fragility_doc: "docs/architecture/32-source-nepal.md"
data_file: "data/Nepal.csv"
---

# 32 · Source: Nepal (Department of Customs FTS workbooks)

Nepal has **no domestic car manufacturing** — every four-wheeler is
imported, so the Department of Customs' (DoC) import statistics *are* the
national new-vehicle market, and they are what every Nepali press report on
EV adoption quotes. DoC publishes one cumulative fiscal-year-to-date
**Foreign Trade Statistics (FTS) Excel workbook per Nepali month**; sheet
`5_Imports_By_Commodity` carries 8-digit HS codes with unit + quantity,
which yields a full fuel split for passenger vehicles (heading 87.03).

Nepal is one of the world's most electrified car markets: FY 2081/82
(2024-07 … 2025-07) saw **13,578 BEV cars/jeeps/vans vs ~5,000 fossil**
ones — plus 16,505 electric three-wheelers (e-rickshaws), which is why the
three-wheelers are split into their own series instead of polluting the
headline BEV count.

## TL;DR

```
Variants:
  Whole       data/Nepal.csv              HS 8703 minus three-wheelers
                                          (cars, jeeps, vans ≈ EU M1)
  3-Wheelers  data/Nepal_3-Wheelers.csv   passenger three-wheelers:
                                          auto-rickshaws (petrol) +
                                          e-rickshaws (BEV)

Source:    customs.gov.np → nav "तथ्याङ्क → वैदेशिक व्यापारको तथ्याङ्क"
           → FY category → content page → <div class="details__desc">
           → one giwmscdnone.gov.np/media/files/*.xlsx per month
Auth:      none
Schema:    BEV,HEV,PETROL,DIESEL,OTHERS,TOTAL (PHEV empty — single
           Hybrid bucket, see §4)
Cadence:   cumulative FYTD file per Nepali month, published a few weeks
           after the month ends; fetcher polls daily, cheap-skips
Scripts:   scripts/fetch_nepal.py
Workflow:  .github/workflows/fetch-nepal.yml
```

## 1. Semantics: imports, not registrations

The FTS counts customs clearances (ASYCUDA records). Import ≈ sale is a
good approximation for Nepal (landlocked, no production, re-export
negligible), but monthly timing reflects when vehicles *cleared customs*,
not when they were registered — importers front-load ahead of fiscal-year
budget/tariff changes and pause after them (visible as a low Shrawan month
every year). Same caveat class as Indonesia (wholesales) and China
(Wholesale variant). The TTM view smooths the seasonality out.

## 2. Calendar: Bikram Sambat fiscal months

The Nepali fiscal year runs Shrawan 1 → Ashadh end (≈ 17 July → ≈ 16
July). FY "2082/83" starts in AD 2082 − 57 = 2025. The gallery's `period`
for fiscal month k (Shrawan = 1 … Ashadh = 12) is the Gregorian month in
which the Nepali month **ends**:

```
period(fy, k) = (July of AD fy−57) + k months
FY 2082/83:  Shrawan → 2025-08, Poush → 2026-01, Ashadh → 2026-07
```

A fixed rule (rather than midpoint-of-actual-dates) guarantees a gapless,
duplicate-free monthly series across fiscal years. Each labelled month
actually covers ~mid-previous-month to ~mid-labelled-month; this constant
half-month shift is irrelevant at S-curve timescales and is footnoted on
the charts (`footnotes.csv`).

## 3. Monthly values from cumulative files

Workbooks are cumulative FYTD, so `month k = FYTD(k) − FYTD(k−1)`
(Shrawan = its own file). Every run re-downloads all published files of
the processed FY and rebuilds all of its months, so upstream revisions are
absorbed Indonesia-style. The coverage (FY + month count) is parsed from
the sheet's own English header line — e.g. `Based on First Eleven Months
(Shrawan-Jestha) of FY 2081/82` — **never** from the Devanagari link
labels or filenames, which are wildly inconsistent («जेठसम्म» vs
«जेष्ठसम्म», «आ.ब.» vs «आ.व.», a file literally named
`फागुनसम्म_nwsjsgt.xlsx`, `FTS_ogzzoqd.xlsx`).

## 4. Fuel mapping (HS 8703 sub-codes)

By 6-digit prefix; descriptions only decide the three-wheeler split and an
"electric" override for legacy codes:

| Prefix | Bucket | Note |
|---|---|---|
| 870310 | OTHERS | golf cars etc. |
| 870321–870324 | PETROL | 87032111/19 (petrol auto-rickshaws) → 3-Wheelers series |
| 870331–870333 | DIESEL | |
| 870340, 870350 | HEV | non-plug-in hybrids per int'l HS |
| 870360, 870370 | HEV | **single Hybrid bucket** — see below |
| 870380 | BEV | 87038011/19 (e-rickshaws) → 3-Wheelers series |
| 870390 | OTHERS | description containing "electric" → BEV (legacy files) |

**Why one Hybrid bucket:** DoC's 8-digit descriptions split hybrids by
engine displacement, not by plug: `87034090 "… plugin UPTO 2000CC"` vs
`87036090 "… plug out ABOVE 2000 CC"` — mutually contradictory and
inconsistent with the international 6-digit meaning (8703.40 = non-plug-in,
8703.60 = plug-in). The PHEV/HEV boundary in this source is therefore not
trustworthy → all hybrids go to the `HEV` column, `PHEV` stays empty, the
charts label the bucket "Hybrid" (Türkiye/Georgia/Colombia convention).
Volumes are tiny (85 hybrid units in all of FY 2081/82 vs 13.6k BEVs), so
nothing meaningful is lost.

**Three-wheelers:** any 8703 row whose description matches
`rik?shaw|three wheel|3 wheel` goes to the `3-Wheelers` series (petrol
auto-rickshaws + electric e-rickshaws). E-rickshaws are one of Nepal's
biggest EV segments (16.5k in FY 2081/82) but a different vehicle class —
mixing them into `Whole` would roughly double the BEV count.

**Out of scope** (documented candidates for future variants): buses and
10+-seat vans under 8702 — including the large electric mini/microbus wave
(3,100+ units FY 2081/82); goods vehicles/pickups under 8704 (incl.
electric cargo three-wheelers and vans); motorcycles/scooters under 8711
(a 2-Wheelers variant would be viable: ~14k electric 2W in FY 2081/82).

## 5. Validation (hard fail, no partial writes)

* header line must parse to (FY, month count) — FY must match expectation;
* the month set of a FY must be contiguous 1..K (deltas need every step);
* any negative per-bucket monthly delta aborts (a cumulative figure was
  revised downward — needs a human look);
* non-PCS units and unknown 8703 sub-codes warn loudly (unknowns land in
  OTHERS);
* an all-zero parsed month refuses to write.

Cross-checks performed at build time (2026-07): FY 2080/81 Whole BEV
11,701 vs Kathmandu Post's "11,466 electric cars/vans/jeeps in the first
11 months of FY 2080/81" + a small Ashadh month ✓; FY 2081/82 Whole BEV
13,578 matches the NADA/press "record EV imports" narrative ✓.

## 6. Discovery fragility

| What can break | Symptom | Fix |
|---|---|---|
| Homepage nav layout changes | `no 'आ.व. YYYY/YY' category links found` | Re-derive the FY-category discovery from the new nav (`discover_fy_categories`) |
| FY category slugs are irregular (`fts-2081-082`, `a-v-2042-063`, `a-v-2082-043` is the *revenue* one) | wrong/missing category | Discovery already fetches every candidate and requires a «तथ्याङ्क»-titled, non-«राजस्व» content item |
| New FY category exists before its first FTS file | steady state finds no statistics item | fetcher falls back to the previous FY automatically |
| DoC renames the sheet or header wording | `no Imports_By_Commodity sheet` / `cannot parse coverage` | extend the sheet-name/regex patterns (`parse_workbook`, `parse_coverage`) |
| New 8703 sub-codes appear (tariff revisions happen at FY boundaries) | `unknown sub-code` warning, values land in OTHERS | add the code to `PREFIX_BUCKET` (or fix the 3W regex) |
| Cumulative value revised downward | negative-delta abort | inspect both files, decide manually, re-run with the fix |

## 7. History & backfill floor (2020-08)

The series is a gapless **monthly** run from **2020-08** (FY 2077/78
Shrawan) onward, spanning Nepal's whole BEV take-off (calendar-year Whole
BEV share: 0.6 % in 2020 → 6 % in 2021 → 24 % in 2022 → 60 % in 2023 →
~75 % from 2024). The floor is deliberate, not a parser limitation.

### Why the pre-2020 tail is *not* backfilled (investigated & rejected)

The pre-2020 annual workbooks parse fine — the imports-by-commodity sheet
exists in every FY back to ~2073/74 and an adaptive extractor reads all
the layout variants. The blocker is **semantic, in the source's electric
tariff codes**, and it breaks the `Whole` vs `3-Wheelers` split that the
gallery is built on:

- From FY 2077/78 the tariff carries **eight** 8703.80 sub-codes that
  cleanly separate the two series: `8703.80.11/.19` = *Electric three
  wheelers* → `3-Wheelers`; `8703.80.21/.29/.59/.69/.79/.89` = *Electric
  car/jeep/van* by motor kW → `Whole`.
- Pre-2020 the tariff used a coarse **two-code** structure —
  `8703.80.10` and `8703.80.90` — whose descriptions are the identical,
  useless string *"Other vehicles, with only electric motor for
  propulsion"* for **both** codes. There is no way to tell cars from
  three-wheelers.
- Worse, FY 2076/77's `8703.80.10` (14,935 units — the bulk of that
  year's electric imports) carries a **corrupted description**, *"Parts
  for electric filament or discharge lamps"* (a data-entry error in the
  DoC spreadsheet). Those 14,935 units are almost certainly mostly
  e-rickshaws (Nepal imported ~13–14 k e-rickshaws in 2019/20 vs a few
  thousand electric cars), which the monthly era would file under
  `3-Wheelers` — but the source gives no reliable way to split them.

A naive parse dumps all of `8703.80.10` into `Whole` BEV, producing an
inflated FY 2076/77 `Whole` BEV of ~15,500 that dwarfs and contradicts the
monthly era right next to it. Publishing that would make the headline
`Whole` curve wrong, so the pre-2020 annual points are **deliberately
omitted**. (The analytical loss is negligible: the model already assumes a
0 % start, and the monthly series already captures the take-off from
< 1 % share.) The rejected approach — an adaptive annual parser plus a
consistency-validation harness against the monthly overlap — lived on this
branch during the investigation and was removed once the tariff-code
ambiguity was confirmed.

`archive.customs.gov.np` (which historically hosted the older files) is
gone — the hostname now serves an unrelated Provincial Assembly site
(hence its TLS hostname-mismatch) — so the current CMS is the only online
source anyway.
