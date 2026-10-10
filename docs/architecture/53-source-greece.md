---
country: Greece
slug: greece
method: pdf
summary: New passenger-car registrations for Greece from SEAA, the importers' association
  that processes ELSTAT's registration data every month and is the source of ACEA's Greek
  figure. Exact BEV, PHEV and total counts from SEAA's statistics files; the hybrid,
  petrol and diesel split is first derived from the fuel shares in SEAA's press release
  and replaced by ACEA's counted split when ACEA publishes the month.
source_name: SEAA — monthly passenger-car registration statistics (seaa.gr)
source_url: https://seaa.gr/registrations/
source_links:
- label: SEAA — registration statistics
  url: https://seaa.gr/registrations/
  note: per month <Y>-<M>-BEV.pdf and <Y>-<M>-PHEV.pdf (battery-electric and plug-in hybrid cars by segment, brand and model; one combined electric.pdf until 2023)
- label: SEAA — passenger-car comparisons
  url: https://seaa.gr/passenger-car-registrations-comparisons/
  note: per month <Y>-<M>-comp.xlsx, passenger cars by brand against the year before — the month's exact total
- label: SEAA — press releases
  url: https://seaa.gr/seaa-press-releases/
  note: the month's fuel split as shares with one decimal; since 2025-11 also preliminary BEV / PHEV / total counts
- label: ACEA — monthly new-car registrations
  url: https://www.acea.auto/
  note: relays SEAA's figures including the counted hybrid / petrol / diesel split, which replaces the derived one about a week after SEAA
underlying: ELSTAT (Hellenic Statistical Authority) registration records of new vehicles, processed and published by SEAA (Σύνδεσμος Εισαγωγέων Αντιπροσώπων Αυτοκινήτων)
auth: none
cadence: twice daily from the 8th to the end of the month — the press release comes out around the 10th–24th, the statistics files around the 15th–21st
variants:
- Whole
variant_notes:
  Whole: New passenger cars incl. taxis (SEAA's "PC and taxi cars", EU M1) — the scope of ACEA's Greek figure.
hev_split: true
hev_note: HEV, PETROL and DIESEL are ACEA's counts (SEAA's own, which SEAA does not publish) once ACEA has published the month — source "SEAA / ACEA". Until then they are derived from the press release's one-decimal fuel shares — source "SEAA" — typically about 5 cars off the count, at most 15 in 9 months out of 10 and at most 50 (0.4 % of the month). HEV includes mild hybrids. BEV, PHEV and TOTAL are always SEAA's exact counts.
backfill: SEAA from 2022-01 (the first full month with exact BEV/PHEV counts); ACEA before that (quarterly figures spread over the quarter's months, as before). HEV/PETROL/DIESEL of 2022-01..2026-08 are the old ACEA rows' counts wherever ACEA's month matches SEAA's (54 of 56). The old all-ACEA series is kept as data/Greece_legacy.csv.
scope_note: New passenger cars and taxis registered in Greece (SEAA's PC + taxi tables). Used imports are not counted — ELSTAT publishes them without a fuel split.
caveats:
- 'Until ACEA publishes a month (about a week after SEAA), its HEV, PETROL, DIESEL and OTHERS are derived from one-decimal fuel shares (source "SEAA"): typically about 5 cars off the count, at most 15 in 9 months out of 10, at most 50 (0.4 % of the month). When ACEA publishes, its counted HEV/PETROL/DIESEL replace them and OTHERS becomes TOTAL minus the rest (source "SEAA / ACEA"). BEV, PHEV and TOTAL, and so the BEV share, never change.'
- 2022-12 and 2023-07 keep the derived split — ACEA's rows for those months are wrong (below), so their split does not fit SEAA's counts.
- 'A month the press release has announced but whose statistics files are not out yet is written provisionally from the press release (BEV, PHEV and TOTAL only) and marked "provisional" in its notes; the run that finds the statistics files replaces it.'
- Two ACEA months were wrong and are corrected by SEAA — 2022-12 (ACEA 8,001 cars, SEAA 6,486) and 2023-07 (ACEA 8,342, SEAA 12,380). SEAA's own year-to-date columns confirm its figures.
- Vans, HDV and Buses still come from ACEA's quarterly commercial-vehicle report — SEAA publishes them without a fuel split.
processing:
- title: Find the files
  text:
  - SEAA posts every file to its WordPress site. The fetcher lists the uploads through the site's media API and recognises each file by its name — <Y>-<M>-comp.xlsx, <Y>-<M>-BEV.pdf, <Y>-<M>-PHEV.pdf, <Y>-<M>-electric.pdf, and the press release, whose name carries the month in Greek. When a file was re-uploaded, the newest copy wins.
- title: Exact counts
  text:
  - TOTAL is the TOTAL row of the comparison workbook. BEV and PHEV are the summary lines of the BEV and PHEV files (until 2023 one electric file with both). Each file's printed month must be the month its name claims.
  decision:
    ask: Statistics files for the month out?
    branches:
    - when: comp.xlsx and BEV.pdf + PHEV.pdf
      then: TOTAL, BEV, PHEV exact
    - when: comp.xlsx and electric.pdf (2021-12..2023-12)
      then: TOTAL, BEV, PHEV exact
    - when: not yet
      then:
        ask: Press release with preliminary counts (since 2025-11)?
        branches:
        - when: "yes"
          then: provisional row — replaced when the statistics files appear
        - when: "no"
          then: month not written — ACEA may fill it meanwhile
- title: Fuel split
  text:
  - SEAA counts hybrids, petrol and diesel but publishes them only as shares with one decimal; ACEA publishes SEAA's counts about a week later. So the split is first derived from the shares and replaced by ACEA's counts when they appear — whichever of the two fetchers runs second does it. TOTAL, BEV and PHEV always stay SEAA's.
  decision:
    ask: ACEA's release for the month out, and its TOTAL / BEV / PHEV the same as SEAA's (within 1 % / 2 %)?
    branches:
    - when: "yes"
      then: HEV, PETROL, DIESEL = ACEA's counts; OTHERS = TOTAL − BEV − PHEV − HEV − PETROL − DIESEL; source "SEAA / ACEA"
    - when: not yet
      note: derived, not counted — typically ±5 cars per column, at most ±15 in 9 of 10 months, at most ±50; replaced when ACEA publishes
      then:
        ask: Do the press release's shares add up (within 1.5 points of the non-plug-in share)?
        branches:
        - when: "yes"
          then:
            ask: Fuel in the press release?
            branches:
            - when: HEV (full and mild hybrids)
              then: HEV
            - when: petrol
              then: PETROL
            - when: diesel
              then: DIESEL
            - when: LPG, CNG, rest
              then: OTHERS
            - when: BEV, PHEV
              then: not used — counted exactly instead
        - when: no, or no press release
          then: BEV, PHEV, TOTAL only — the other columns stay empty
    - when: "no — ACEA's month does not match (its 2022-12 and 2023-07 rows are wrong)"
      then: the derived split stays
- title: Cross-checks
  text:
  - The press release's preliminary counts and its BEV share must agree with the statistics files within 3 %, or the run stops. A month far below the usual volume is not written. The model lines of each BEV/PHEV file are summed and compared with the file's own total; only months where they agree feed the brand and model lists.
market_breakdown: market/greece_top.json
market_designation_note: the brand is SEAA's make, the model SEAA's "Range" (the model family — MODEL Y, ATTO 2, PROACE CITY), as printed in the BEV and PHEV files.
market_powertrain_note: BEV and PHEV exactly as in the CSV (SEAA's BEV and PHEV files). Hybrids are not ranked — SEAA publishes them only as a share.
fetcher: scripts/fetch_greece.py
workflow: .github/workflows/fetch-greece.yml
fragility_doc: docs/architecture/53-source-greece.md
data_file: data/Greece.csv
---

# 53 · Source: Greece (SEAA registration statistics)

**Status: LIVE since 2026-10.** Fetcher `scripts/fetch_greece.py` (+ tests
`scripts/test_fetch_greece.py`, fixtures `scripts/fixtures/greece/`), workflow
`.github/workflows/fetch-greece.yml`. Writes `data/Greece.csv` (Whole) from 2022-01;
ACEA (`fetch_acea.py`) adds its counted HEV/PETROL/DIESEL to a SEAA row, and fills a month
on its own only while SEAA has not published it.

## TL;DR

```
Source:    seaa.gr — files found through the WordPress media API
           https://seaa.gr/wp-json/wp/v2/media?per_page=100&page=N
           (newest uploads first; ~20 pages, the page past the end is HTTP 400)
Auth:      None.
Files:     <Y>-<M>-comp.xlsx       TOTAL                        since 2020-07
           <Y>-<M>-BEV.pdf/-PHEV.pdf  BEV, PHEV (+ brand/model) since 2024-01
           <Y>-<M>-electric.pdf    both in one             2021-12..2023-12
           Δελτίο-τύπου-ΣΕΑΑ-για-τις-ταξινομήσεις-<μήνα>-<Y>.pdf
                                   fuel shares (1 decimal); since 2025-11 also
                                   preliminary BEV/PHEV/TOTAL counts
Timing:    press release ~10th–24th, statistics files ~15th–21st of the next
           month (July 2026's statistics only on 21 Sept). ACEA: ~20th–25th.
Whole:     TOTAL/BEV/PHEV exact (SEAA); HEV/PETROL/DIESEL derived from shares
           until ACEA publishes its counts (~a week later), then ACEA's
           ("SEAA / ACEA"); OTHERS = TOTAL minus the rest.
Check:     2022-01..2026-08 vs the old ACEA rows: 49 of 56 months identical in
           every column; two of the rest are ACEA errors (§4).
Run:       seconds (a few HTTP requests; files are ~100–400 KB).
```

## 1. Why this source

Before 2026-10 every Greek series came from ACEA: `Whole` from the monthly car press
release (an "always" country in `fetch_acea.py`), `Vans`/`HDV`/`Buses` from the quarterly
commercial-vehicle release. ACEA's Greek figure is SEAA's, and SEAA's is ELSTAT's
registration data, processed every month.

SEAA publishes the same month earlier than ACEA, free and without a login, with exact
BEV and PHEV counts, the brand and model of every plug-in, and its own year-to-date
columns — which exposed two months where ACEA's figure (and so our CSV) was wrong
(§4).

What SEAA does **not** publish is a counted hybrid/petrol/diesel split: the press release
gives the fuel mix only as shares with one decimal. ACEA does publish SEAA's counts, about
a week later. So those columns are first derived (§3) and then replaced by ACEA's counts;
the row's `source` and `notes` say which.

ELSTAT itself (statistics.gr, the monthly "Motor vehicle registrations" release) has
passenger cars new vs used but **no fuel split**, and neither does SEAA's van, truck or
bus data. That is why Vans, HDV and Buses stay on ACEA's commercial-vehicle report
(`docs/architecture/38-source-acea-cv.md`), and why there is no `Used` variant.

## 2. File → CSV row

| Column | From | How |
|---|---|---|
| `TOTAL` | `<Y>-<M>-comp.xlsx` | the TOTAL row, the month's column (the header row whose column B reads "Brand"); exact |
| `BEV` | `<Y>-<M>-BEV.pdf` (`electric.pdf` before 2024) | the file's summary line, month column; exact |
| `PHEV` | `<Y>-<M>-PHEV.pdf` (`electric.pdf` before 2024) | ditto; exact |
| `HEV`, `PETROL`, `DIESEL` | ACEA release, once out | ACEA's counts (source `SEAA / ACEA`) |
| | press release, until then | share × (TOTAL − BEV − PHEV) / (100 − plug-in share), largest-remainder rounded (source `SEAA`) |
| `OTHERS` | — | with ACEA: TOTAL − BEV − PHEV − HEV − PETROL − DIESEL; before: LPG + CNG + whatever the shares leave out |
| `notes` | — | which files, and whether the split is derived or ACEA's; "provisional — …" for a press-release-only row |

The press release's subject line names the month ("…κατά τον Αύγουστο 2026"); the
statistics files print it ("AUGUST '26", "Aug. '26" — once with Greek capitals, "ΜΑΥ
'23"). Both must match the month in the file name.

**Provisional rows.** Since 2025-11 the press release, out a few days before the
statistics files, carries preliminary BEV, PHEV and total counts. The fetcher writes such a
month from the press release alone (`notes` start with "provisional"), and the next run
that finds the statistics files rewrites it. Preliminary and final counts differ by a few
cars (2026-08: 5,159 vs 5,153 total, 546 vs 544 BEV).

## 3. The split: derived first, ACEA's counts later

The press release's table lists petrol, diesel, HEV, PHEV, BEV, LPG (and until 2022
CNG) as shares with one decimal, e.g. 2026-08: petrol 18.8, diesel 1.3, HEV 59.8, PHEV
5.4, BEV 10.6, LPG 4.1. The plug-in shares are not used — BEV and PHEV are counted.

1. plug-in share = 100 × (BEV + PHEV) / TOTAL, from the counts.
2. The non-plug-in shares (HEV + PETROL + DIESEL + LPG + CNG) must add up to
   100 − plug-in share within 1.5 points, or the month gets no split (empty columns,
   never zeros — invariant 4).
3. TOTAL − BEV − PHEV is split in those shares; OTHERS takes LPG, CNG and the
   remainder. Largest-remainder rounding keeps the row summing to TOTAL.

With one decimal the rounding alone would be within ±0.05 % of TOTAL per column; in
practice the press release's shares and the final statistics differ slightly too. Against
ACEA's counted figures (2022-01..2026-08 without its two wrong months) a derived column is
off by a median of 3–5 cars, by at most 8–13 in 9 months out of 10 (≤ 0.13 % of the month)
and by at most 50 (HEV 2024-07, 0.4 %).

**ACEA's counts replace it.** `scripts/acea_split.py` does the merge, called from both
fetchers so the order they run in does not matter:

- `fetch_acea.py` finds a `SEAA` (or `SEAA / ACEA`) row for the month → it changes only
  HEV, PETROL, DIESEL and OTHERS (also for the prior-year column of its release).
- `fetch_greece.py` writes a month that has an `ACEA` (or `SEAA / ACEA`) row → it keeps
  that row's HEV/PETROL/DIESEL and puts its own TOTAL/BEV/PHEV around them.

HEV/PETROL/DIESEL are ACEA's; OTHERS is TOTAL − BEV − PHEV − HEV − PETROL − DIESEL, so the
row always sums to SEAA's TOTAL. The merge is refused, and the derived split stays, when
ACEA's TOTAL is more than 1 % or its BEV/PHEV more than 2 % (at least 5 cars) off SEAA's —
not the same month (2022-12, 2023-07) — or OTHERS would be negative. The run log says
which. ACEA publishes no July release, so a July keeps the derived split (2026-07 has ACEA's
split only because that row was derived by hand from ACEA's year-to-date sums).

## 4. Check against ACEA

Every SEAA month 2022-01..2026-08 against the ACEA row it replaced
(`data/Greece_legacy.csv`):

| Column | Months | Identical | Largest differences |
|---|---|---|---|
| TOTAL | 56 | 50 | 2023-07 +4,038 · 2022-12 −1,515 · 2026-07 +32 · 2026-04 −32 |
| BEV | 56 | 52 | 2023-07 +218 · 2022-12 −68 · 2026-07 +2 · 2026-04 −2 |
| PHEV | 56 | 51 | 2023-07 +149 · 2022-12 +117 · 2023-09 +10 |
| HEV / PETROL / DIESEL | 56 | 54 | ACEA's own counts; only 2022-12 and 2023-07 keep the derived split |
| OTHERS | 56 | 49 | residual: moves with the TOTAL/BEV/PHEV differences above |

- **2022-12** — ACEA 8,001 cars; SEAA 6,486, and SEAA's year-to-date columns of
  November and December differ by exactly that.
- **2023-07** — ACEA 8,342; SEAA 12,380, again consistent with its year-to-date.
- **2026-07** — ACEA publishes no July; our row was derived by hand from year-to-date
  sums (13,220). SEAA counts 13,252.

So in 49 of 56 months the row is identical in every column to the old ACEA row. Before
the merge, the derived columns differed from ACEA's by the rounding of the shares (§3).

## 5. Month and revisions

A month is the calendar month of registration. SEAA does not revise a published month;
a re-uploaded file (WordPress adds `-1`, `-2` to the name) replaces the older copy, and
the fetcher always reads the newest. Own rows (`SEAA`, `SEAA / ACEA`) are rewritten only
when provisional or under `--force`, and keep ACEA's split when they have it. An `ACEA`
row for a month SEAA covers is replaced, keeping its HEV/PETROL/DIESEL (§3); any other
source is never touched. This is a revision of a published row, as with the UK's revised
figures: the derived split is an estimate until ACEA's counts arrive. Before 2022-01 nothing changes (invariant 3): those rows are ACEA quarterly
figures spread over the quarter's months (see 35b), and a monthly 2021-12 row would split
that quarter.

## 6. Governance

Every run, before anything is written:

- The regression tests (`scripts/test_fetch_greece.py`, offline fixtures) gate the fetch
  in the workflow: file-name patterns, Greek month names, PDF column positions, the share
  split and the upsert rules.
- Printed month = file-name month, for every file.
- Shares within 1.5 points (§3), else no split.
- Press-release preliminary counts and BEV share × TOTAL vs the statistics files: a
  difference above 3 % stops the run.
- A new month below 25 % of the trailing-12 median TOTAL is not written; below 50 % a
  warning (Greek Augusts are legitimately ~45 %).
- Model lines vs the file's own summary line: off by more than max(3, 3 %) and the month
  is left out of the brand/model lists (SEAA's 2022–2023 electric files miss a few
  lines). Counts never come from the model table.
- Fuels sum to TOTAL in every row written.
- ACEA's split is taken only when its TOTAL/BEV/PHEV match SEAA's (§3).

The step summary of each run lists the months written with their files and checks.

## 7. Operations

| | |
|---|---|
| Schedule | `55 11,17 8-31 * *` (14:55 / 20:55 Athens) |
| Dispatch inputs | `period` (one month), `backfill` (every month from 2022-01 still missing, ACEA or provisional; with `force`: all), `force` |
| Commits | `data/Greece.csv`, `market/greece_top.json`, `market/greece_months.json` — `chore: update Greece data from SEAA` |
| Render | `render-country.yml` with `country=Greece`, `variants=Whole` |
| Dependencies | `requests`, `pdfplumber`, `openpyxl` |

### Debugging runbook

- **"nothing published yet" / "incomplete … — not written"** — SEAA has not posted the
  month's files yet; the run writes what it can (or the provisional row) and a later run
  picks the rest up. `https://seaa.gr/wp-json/wp/v2/media?search=<Y>-<M>` shows what is
  there.
- **"… file for <month> prints <other month>" / "press release filed as … is about …"** —
  a file uploaded under the wrong name; the run stops. Check it by hand; a local mirror
  (`--from-dir`) with `--period` replays one month.
- **"no summary line found" / model-gap warnings for a new month** — the PDF layout
  changed. Save the file into `scripts/fixtures/greece/`, add a test, and adjust
  `parse_plugin_pdf`.
- **Shares do not add up** — the press release's table changed; the month is written
  without a split until `parse_press_release` is fixed and the month re-run with
  `--period … --force`.
- **"… not the same month or the split does not fit; national row kept"** (in either
  fetcher's log) — ACEA's TOTAL/BEV/PHEV differ from SEAA's by more than 1 % / 2 %. Compare
  the two releases by hand; if ACEA is wrong (as in 2022-12) nothing is to be done, the
  derived split stays.
- **seaa.gr unreachable** — nothing is written; ACEA fills the month around the 20th–25th
  and SEAA replaces it on a later run.

## 8. Sequence

```
cron 8th–31st ──► fetch_greece.py
                    ├─ CSV: newest SEAA month, rows that are ACEA or provisional
                    ├─ media API (3 newest pages) ──► comp.xlsx, BEV/PHEV.pdf, press release
                    ├─ parse + checks ──► upsert data/Greece.csv (Whole)
                    └─ market/greece_top.json (guarded)
                  ──► commit ──► render-country.yml (Greece, Whole) ──► build-manifest
fetch-acea.yml ──► Greece: on a SEAA row only HEV/PETROL/DIESEL (+ OTHERS residual)
                   → source "SEAA / ACEA"; a missing month → a plain ACEA row
```
