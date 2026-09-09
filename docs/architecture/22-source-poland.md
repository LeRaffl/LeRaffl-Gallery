---
country: Poland
slug: poland
method: file
summary: New-registration data for Poland from PZPM's monthly eRegistrations workbook, sourced from the
  CEP central vehicle register.
source_name: PZPM eRegistrations — the monthly workbook
source_url: https://www1.pzpm.org.pl/pl/Elektromobilnosc/eRejestracje
underlying: PZPM — Polish Automotive Industry Association (CEP register)
auth: none
cadence: twice-daily cron, 6th–10th, 09:30 & 13:30 UTC
variants:
- Whole
- Vans
- HDV
- Buses
variant_notes:
  Whole: New passenger cars (OSOBOWE, M1).
  Vans: Light commercial vehicles up to 3.5 t (SAMOCHODY DOSTAWCZE, N1).
  HDV: Trucks over 3.5 t (SAMOCHODY CIEZAROWE POW. 3,5T, N2/N3).
  Buses: Buses (AUTOBUSY, M2/M3).
hev_split: true
backfill: workbook holds the current month only; Whole history to 2010 retained from the prior ACEA pipeline
scope_note: Whole = passenger (OSOBOWE); Vans, HDV (>3.5t) and Buses are separate variants.
caveats:
- Full hybrids (HEV) are reported natively for Whole and Buses.
- Vans report a single combined hybrid bucket that lands in OTHERS; PHEV/HEV stay empty for Vans/HDV.
- OTHERS is a residual capturing LPG, FCEV and CNG/LNG.
fetcher: scripts/fetch_poland.py
workflow: .github/workflows/fetch-poland.yml
fragility_doc: docs/architecture/22-source-poland.md
data_file: data/Poland.csv
---

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
Source:    PZPM eRegistrations workbook (XLSX), from CEP — on www1.pzpm.org.pl
Auth:      None
API:       None. Two-level scrape of the Electromobility/eRegistrations section:
           the landing page + the newest month sub-pages (…/eRegistrations/
           JULY-2026), collecting every eRejestracje "tabele ...xlsx" table (its
           /content/download/<id>/<id>/ IDs rotate every month). Download +
           parse the "Ogółem" (Overall) sheet only.
Period:    Read from the workbook's own "Ogółem" header ("Czerwiec 2026" →
           2026-06) — NEVER from the URL/filename, which PZPM routinely
           mislabels (newest month under the previous month's name; duplicate
           pages). The filename MM.YYYY is only a download/early-exit hint.
Fallback:  When a month is PDF-only (no .xlsx table yet), the run is a clean
           no-op and ACEA (scripts/fetch_acea.py, Poland on its conditional
           list) fills that month instead, never overwriting a PZPM row.
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

## 1. Ownership: PZPM-primary, ACEA fallback

`data/Poland.csv` (Whole) was originally maintained by `scripts/fetch_acea.py`
(Poland on its *conditional* list). PZPM is the CEP-based upstream behind those
exact numbers — published earlier, with the commercial variants — so **PZPM is
the primary source** (`source := "PZPM"`) and additionally carries Vans/HDV/Buses.

But PZPM curates its eRegistrations section **by hand** and is inconsistent:
some months ship only as a PDF infographic (no machine-readable `.xlsx` table),
the newest month is sometimes published under the previous month's page name,
and duplicate pages appear (JULY twice, APRIL three times). So Poland is **back
on ACEA's conditional list as a fallback**: when PZPM has no `.xlsx` for a month,
the PZPM run is a no-op and ACEA fills that month (`source := "ACEA"`). The
conditional rule means **ACEA never overwrites a PZPM row** (`should_write()` in
`fetch_acea.py`), and since ACEA Poland == PZPM `OSOBOWE` to the unit, the two
sources form one comparable Whole series. The full Whole history (2010-01+) is
retained as-is; only current/recent months are (re-)sourced.

## 2. The workbook & two-level discovery

The machine-readable tables live on **`www1.pzpm.org.pl`**, one per month:

```
https://www1.pzpm.org.pl/en/content/download/<id1>/<id2>/file/PZPM_eRejestracje%20-%20tabele%20MM.YYYY.xlsx
```

`<id1>/<id2>` rotate every month (TYPO3 content IDs) → **no stable URL**. The
`www.pzpm.org.pl` landing page now serves only PDF infographics; the `.xlsx`
tables sit on **per-month sub-pages** (`…/eRejestracje/SIERPIEN-2026`) linked
from the left nav. So discovery is **two-level**: `collect_xlsx_candidates()`
reads the landing page plus the newest handful of month sub-pages and returns
every `tabele ...xlsx` link.

**Scrape the Polish section, not the English one.** The fetcher targets
`www1.pzpm.org.pl/pl/Elektromobilnosc/eRejestracje`, because PZPM curates the
Polish original correctly — each month's sub-page carries its OWN month name —
whereas the English mirror (`/en/Electromobility/eRegistrations`) frequently
labels the newest month with the *previous* month's name and duplicates pages.
`_SUBPAGE_RE` matches both languages' month slugs as a safety net.

Regardless of language, each candidate is downloaded and its **true month read
from the `Ogółem` sheet header** (`"Czerwiec 2026"` → `2026-06`) — the URL,
sub-page title and even the filename are NOT trusted for the period. Download
requires a browser `User-Agent` and a `Referer` of the page.

> **History note.** Until mid-2026 PZPM published a single `tabele ...xlsx` link
> directly on one `www.pzpm.org.pl` page, discovered by a simple filename regex.
> When PZPM moved to `www1`, split tables onto per-month sub-pages, and started
> shipping PDF-only months with mislabelled titles, the fetcher was reworked to
> the two-level, sheet-authoritative scheme above (plus the ACEA fallback).

### Only the "Ogółem" sheet is trustworthy

The workbook has nine sheets, but **only `Ogółem` (Overall) is refreshed each
month**. The brand/model ranking tabs (`Osobowe - rankingi`, `Samochody
Dostawcze`, …) and `Paliwa_Samochody osobowe` are **stale 2023 template tabs**
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
- **Slow server / read timeouts.** `www.pzpm.org.pl` is a low-traffic association
  site. A 30 s timeout produced `requests.exceptions.ReadTimeout` in CI (observed
  2026-06-09). The fetcher now uses a 60 s read timeout and `urllib3.Retry(total=4,
  read=4, connect=4, backoff_factor=2)` — up to four retries with waits of 2, 4,
  8, 16 s before the job fails. If the site is down, the retry sequence takes ~30 s
  before the final failure; the next scheduled run will pick it up.
