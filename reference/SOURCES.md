# Reference figures (not country data)

Small files with figures quoted from a third party as they publish them.
They are **not** country series: nothing in `data/` is derived from them,
and writing them never touches a country CSV.

## ACEA, EU: `acea_eu_shares.csv` and `acea_eu_monthly.csv`

ACEA's own EU-level counts feed the **HEV row in "Who gained, who lost"**
on the EU region brief: the change in points and the share over the last
12 months. Under the bars a note names the window, for example:
"HEV from ACEA (EU, Oct 2025–Sep 2026 vs 12 months before), full + mild
hybrids. Other rows from members' national data." The mini card has no
who-gained block, so it carries the same figure as one chip line:
"ACEA, EU · Oct 2025–Sep 2026 — Hybrids (HEV): 35.7 %, +1.4 pts, full +
mild." The brief's other rows, the mix and the headline all come from the
members' national data. ACEA's HEV is never mixed into them.

- **`acea_eu_shares.csv`:** one row per ACEA monthly release. It holds the
  EUROPEAN UNION (EU27) row of the release's YEAR-TO-DATE table: the
  current-year units of every powertrain, the BEV/PHEV/HEV shares of
  TOTAL, the period (Jan–month), the release, its embargo date
  (`published`), the source URL, `retrieved`, `pdf_sha256` and
  `parsed_with`.
- **`acea_eu_monthly.csv`:** one row per calendar month, derived from the
  year-to-date rows:
  - **January:** YTD(January) (`ytd_january`).
  - **Other months:** YTD(m) − YTD(m−1) (`ytd_diff`). The December
    release's year-to-date table is the full year.
  - **No release for m−1:** ACEA's summer break means there is no July
    2026 release. Month m is then its own MONTHLY table
    (`monthly_table`), and m−1 = YTD(m) − YTD(m−2) − m
    (`ytd_diff_less_next_month`). Their sum is exact.
  - **Cross-check:** `table_HEV_units` and `table_TOTAL_units` keep the
    release's own MONTHLY row beside the derived figure.
- **Revisions:** ACEA revises earlier months of the year in later
  releases. Differencing year-to-date tables puts that revision into the
  month being derived, so a derived month can differ from the MONTHLY
  table of its own release. For example, Sep 2026 derived HEV is
  330,812 against 330,693 in the table. In return, the months of a year
  always add up to ACEA's latest year-to-date figure, and a 12-month sum
  is consistent with the latest releases.
- **Full-window rule:** the brief uses the latest month that has all 24
  months behind it, the 12-month window plus the 12 months before. If
  any month is missing, the HEV row is not shown. Nothing is filled in
  or estimated.
- **Definition:** ACEA's "hybrid electric" includes full and mild
  hybrids.
- **Source:** the public monthly press release PDFs on acea.auto,
  `https://www.acea.auto/files/Press_release_car_registrations_<Month>_<Year>.pdf`.

### Backfill (2026-11-18)

The 24 releases from September 2024 to September 2026 were read with
`scripts/fetch_acea.py --eu-only --pdf-url <local copy> --source-url <URL>`.
There is no July 2026 release, because of ACEA's summer break. This gives
months October 2024 to September 2026, enough for Oct 2025–Sep 2026
against Oct 2024–Sep 2025.

| Release | YTD row read with | MONTHLY row read with | Month derived as |
|---|---|---|---|
| 2024-09 | pdfplumber text | pdftotext -layout | (start: no Aug 2024 row needed) |
| 2024-10 | pdftotext -layout | pdftotext -layout | ytd_diff |
| 2024-11 | pdfplumber text | pdfplumber text | ytd_diff |
| 2024-12 | pdfplumber text | pdfplumber text | ytd_diff |
| 2025-01 | pdfplumber text | pdfplumber text | ytd_january |
| 2025-02 | pdfplumber text | pdfplumber text | ytd_diff |
| 2025-03 | pdfplumber text | pdfplumber text | ytd_diff |
| 2025-04 | pdfplumber text | pdfplumber text | ytd_diff |
| 2025-05 | pdftotext -layout | pdfplumber text | ytd_diff |
| 2025-06 | pdftotext -layout | pdfplumber text | ytd_diff |
| 2025-07 | pdftotext -layout | pdfplumber text | ytd_diff |
| 2025-08 | pdftotext -layout | pdfplumber text | ytd_diff |
| 2025-09 | pdfplumber text | pdfplumber text | ytd_diff |
| 2025-10 | pdftotext -layout | pdfplumber text | ytd_diff |
| 2025-11 | pdftotext -layout | pdfplumber text | ytd_diff |
| 2025-12 | pdftotext -layout | pdfplumber text | ytd_diff (full-year table) |
| 2026-01 | pdftotext -layout | pdfplumber text | ytd_january |
| 2026-02 | pdftotext -layout | pdfplumber text | ytd_diff |
| 2026-03 | pdftotext -layout | pdfplumber text | ytd_diff |
| 2026-04 | pdfplumber text | pdfplumber text | ytd_diff |
| 2026-05 | pdfplumber text | pdfplumber text | ytd_diff |
| 2026-06 | pdfplumber text | pdfplumber text | ytd_diff |
| (2026-07) | no release (summer break) | — | ytd_diff_less_next_month |
| 2026-08 | pdfplumber text | pdfplumber text | monthly_table (Aug) |
| 2026-09 | pdfplumber text | pdfplumber text | ytd_diff |

Every year-to-date row's parts add up to its TOTAL; the parser refuses a
row otherwise. "pdftotext -layout" is the fallback for releases whose
table pdfplumber reads as rotated single glyphs.

### How it stays current

`scripts/fetch_acea.py` writes both files. It is the same daily run
(`.github/workflows/fetch-acea.yml`, from the 16th of each month) that
updates the country CSVs from ACEA.

- **Each run:** it adds the new release's year-to-date row and derives the
  new month.
- **Re-runs:** the same units are a byte-for-byte no-op.
- **Fallback parser:** the workflow installs poppler-utils for the
  `pdftotext -layout` fallback.
- **Commit:** it commits both files with `data/` and outputs
  `reference_changed`.
- **Short-circuit:** the latest-period short-circuit does not skip a run
  while `acea_eu_shares.csv` has no row for the target month.

### Staleness guard

`region_card.ACEA_MAX_LAG` (2 months) is the most ACEA's 12-month window
may end before the EU brief's data end. ACEA publishes month M around the
22nd–27th of M+1, so a lag of one month is normal.

- **In the brief:** when the lag is over the limit, the build warns on
  stderr and the note under the bars says "Latest ACEA month is N months
  before the data above".
- **On pull requests:** CI runs `scripts/test_region_card.py`, and its
  `test_repo_acea_figure_is_current` fails when the window is too old.
- **On master:** build-source-pages runs `region_card.py --check-acea`
  daily, after the pages are committed.

### Not done here

Using ACEA as a fallback for missing country HEV (DK, FI, NL, LV) is a
later, separate change. Country CSVs stay national-source only.
