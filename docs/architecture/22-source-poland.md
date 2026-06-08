# 22 · Source: Poland (PZPM eRegistrations)

PZPM (*Polski Związek Przemysłu Motoryzacyjnego*, the Polish Automotive Industry
Association) publishes a monthly **eRegistrations** workbook on its public page
`pzpm.org.pl/en/Electromobility/eRegistrations`, based on the **Central Register
of Vehicles (CEP)**. This is the upstream source behind ACEA's Poland numbers —
verified to the unit (PZPM `OSOBOWE` Apr-2026 = ACEA Poland Apr-2026) — and it
additionally breaks out the commercial categories (vans, trucks >3.5t, buses)
that ACEA does not expose. PZPM publishes the previous month around the **7th**.

## TL;DR

```
Source:    PZPM eRegistrations workbook (XLSX), from CEP
Auth:      None
API:       None. Scrape the page for the "PZPM_eRejestracje - tabele MM.YYYY.xlsx"
           link (its /content/download/<id>/<id>/ IDs rotate every month), then
           download + parse the "Ogółem" (Overall) sheet only.
Period:    Parsed from the xlsx filename ("tabele 04.2026" → 2026-04)
Variants:  Whole (OSOBOWE), Vans (SAMOCHODY DOSTAWCZE),
           HDV (SAMOCHODY CIĘŻAROWE POW. 3,5T), Buses (AUTOBUSY)
HEV:       Reported natively for Whole/Buses ("Hybrydowe"). Vans report a single
           combined "Hybrydowe / hybrydowe plug-in" that can't be split → it
           falls into OTHERS; PHEV/HEV stay empty for Vans/HDV.
OTHERS:    Residual = TOTAL − (BEV+PHEV+HEV+PETROL+DIESEL).
           Captures LPG, Wodorowe/FCEV, CNG/LNG (and combined hybrids for Vans).
Backfill:  Workbook holds the current month only (no history). Whole history
           back to 2010 retained in data/Poland.csv from the prior ACEA pipeline.
           --xlsx PATH --period YYYY-MM parses an archived workbook on demand.
Schedule:  Twice-daily cron on the 6th–10th, 09:30 & 13:30 UTC
Scripts:   scripts/fetch_poland.py
Workflow:  .github/workflows/fetch-poland.yml
```

## 1. Ownership handoff from ACEA

`data/Poland.csv` (Whole) was previously maintained by `scripts/fetch_acea.py`
(Poland was on its *conditional* list). Since PZPM is the CEP-based upstream
behind those exact numbers — and is published earlier and with commercial
variants — **PZPM now owns the Whole row** (`source := "PZPM"`) and Poland was
removed from `fetch_acea.py`'s country list. The full Whole history (2010-01+)
already committed in `Poland.csv` is retained as-is; only the current month is
re-sourced each run.

## 2. The workbook

The page links exactly one data file per month:

```
https://www.pzpm.org.pl/en/content/download/<id1>/<id2>/file/PZPM_eRejestracje%20-%20tabele%20MM.YYYY.xlsx
```

`<id1>/<id2>` change every month (TYPO3 content IDs), so there is **no stable
URL** — the fetcher GETs the page and regexes the `tabele ...xlsx` href, then
derives the period from the filename (`tabele 04.2026` → `2026-04`). Download
requires a browser `User-Agent` and a `Referer` of the page.

### Only the "Ogółem" sheet is trustworthy

The workbook has nine sheets, but **only `Ogółem` (Overall) is refreshed each
month**. The brand/model ranking tabs (`Osobowe - rankingi`, `Samochody
dostawcze`, …) and `Paliwa_Samochody osobowe` are **stale 2023 template tabs**
(they still show Feb-2023 brand tables) and must NOT be parsed. The fetcher
reads `Ogółem` exclusively.

### "Ogółem" layout

Column B holds labels, column C the **current month** count, column F the
year-to-date count (ignored — we take the current month only). Rows are grouped
by an uppercase category header followed by `w tym:` ("of which:") and per-drive
sub-rows:

```
OSOBOWE                       51824   ← Whole (passenger cars)
  Benzyna        → PETROL     13819
  Diesel         → DIESEL      2961
  Elektryczne    → BEV         2651
  Wodorowe       → (FCEV→OTHERS)   0
  Hybrydowe plug-in → PHEV     5052
  Hybrydowe      → HEV        26119
  LPG            → (OTHERS)    1222
SAMOCHODY DOSTAWCZE            6048   ← Vans (LCV ≤3.5t)
SAMOCHODY CIĘŻAROWE POW. 3,5T  3469   ← HDV (trucks >3.5t)
SAMOCHODY CIĘŻAROWE OD 12T     3188   ← skipped (subset of HDV)
AUTOBUSY                        388   ← Buses
MOTOCYKLE / MOTOROWERY                ← skipped (out of scope)
```

Headers are matched after ASCII-folding Polish diacritics (`Ę`→`E`, `Ż`→`Z`, …),
so encoding never matters. `SAMOCHODY CIĘŻAROWE OD 12T` (≥12t) is deliberately
skipped — it is a subset of the >3.5t HDV bucket and would double-count.

## 3. Drive-type → canonical column

| Ogółem row | Canonical | Notes |
|---|---|---|
| Benzyna | PETROL | |
| Diesel | DIESEL | |
| Elektryczne | BEV | the headline metric |
| Hybrydowe plug-in | PHEV | Whole only |
| Hybrydowe (exact) | HEV | Whole + Buses (full/mild) |
| Wodorowe, LPG, CNG/LNG | → OTHERS | via residual |

`OTHERS = TOTAL − (BEV+PHEV+HEV+PETROL+DIESEL)`. A column a category does not
report separately is written **empty (`""` = not reported), not 0** — e.g. Vans
and HDV have no PHEV/HEV split, and HDV reports no petrol. For Vans, PZPM gives a
single combined `Hybrydowe / hybrydowe plug-in` figure that cannot be split, so
it is absorbed into OTHERS rather than guessed into PHEV/HEV.

Cross-check (Apr-2026), all matching the workbook to the unit:

| Variant | BEV | PHEV | HEV | PETROL | DIESEL | OTHERS | TOTAL |
|---|---|---|---|---|---|---|---|
| Whole | 2651 | 5052 | 26119 | 13819 | 2961 | 1222 | 51824 |
| Vans  | 263 | — | — | 237 | 5403 | 145 | 6048 |
| HDV   | 16 | — | — | — | 3429 | 24 | 3469 |
| Buses | 145 | — | 31 | — | 201 | 11 | 388 |

## 4. Rendering

Only **Whole** is auto-rendered on schedule (it has full history and is in
`params.csv`). Vans/HDV/Buses are fetched and committed so their history
accumulates, but **not** auto-rendered yet — the workbook carries no history, so
they start at one month and grow over time (mirroring Portugal's commercials).
Render them on demand via `render-country.yml` once enough months exist.

## 5. Gotchas

- **No history in the file.** Each run only ever sees the latest month; backfill
  of pre-2026 commercial variants would require archived workbooks
  (`--xlsx PATH --period YYYY-MM`).
- **Rotating download IDs.** Never hard-code the XLSX URL; always scrape the page.
- **Stale template tabs.** Parsing anything other than `Ogółem` will silently
  yield Feb-2023 brand data. Don't.
- **Combined van hybrids** inflate Vans `OTHERS`; this is intentional and
  documented above (no split is available upstream).
