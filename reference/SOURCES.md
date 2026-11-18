# Reference figures (not country data)

Small files with figures quoted from a third party as they publish them.
They are **not** country series: nothing in `data/` is derived from them,
and writing them never touches a country CSV.

## acea_eu_shares.csv

ACEA's own EU-level powertrain shares, shown on the EU region brief and
card as a separate, labelled line ("ACEA, EU · Jan–Sep 2026 — Hybrids
(HEV): 36.3 % of new cars"). The brief's own mix and who-gained come from
the members' national data. ACEA's HEV share is printed next to them and
never mixed in. The brief's footnote says the same.

- One row per ACEA release. The brief takes the row with the latest
  `period_to`.
- The shares are ACEA's units for the EU (EU27) row of the release's
  year-to-date table, divided by its TOTAL and rounded to one decimal.
  They match the shares in ACEA's text: BEV 22.7 %, PHEV 10.1 % and
  HEV 36.3 % for January–September 2026.
- ACEA's "hybrid electric" includes full and mild hybrids.
- ACEA publishes no trailing-12-month figure, so the period is the
  release's year-to-date window, and it is printed exactly. It can differ
  from the brief's own 12-month window.
- Source: the public monthly press release PDF on acea.auto
  (`https://www.acea.auto/files/Press_release_car_registrations_<Month>_<Year>.pdf`).
  `published` is the release's embargo date, `retrieved` the date the row
  was first written, and `pdf_sha256` identifies the file that was read.

### How it stays current

`scripts/fetch_acea.py` writes this file. It is the same daily run
(`.github/workflows/fetch-acea.yml`, from the 16th of each month) that
updates the country CSVs from ACEA.

- **Parsing:** each run reads the EUROPEAN UNION row of the PDF's
  YEAR-TO-DATE table from the text layer, checks that the parts add up
  to TOTAL, and adds the row for `period_to` = the release month.
- **Re-runs and revisions:** the same units are a byte-for-byte no-op.
  A revised figure for the same month replaces only that row, and older
  rows keep their bytes.
- **Commit:** the workflow commits the file together with `data/` and
  outputs `reference_changed`.
- **Short-circuit:** the latest-period short-circuit does not skip a run
  while this file has no row for the target month.
- **Old PDFs:** releases from before April 2026 (the old PDF generator)
  carry no text line for the row. The run then prints a warning and
  leaves the file alone.

### Staleness guard

`region_card.ACEA_MAX_LAG` (2 months) is the most this file may lag the
EU brief's data end, which is the common 12-month window's last month.
ACEA publishes month M around the 22nd–27th of M+1, so a lag of one month
is normal.

- **In the brief:** when the lag is over the limit, the build warns on
  stderr and the line itself says "Latest ACEA figure, N months before
  the data above". The ACEA period is always printed in the chip.
- **On pull requests:** CI runs `scripts/test_region_card.py`, and its
  `test_repo_acea_figure_is_current` fails when the file is too old.
- **On master:** build-source-pages runs `region_card.py --check-acea`
  daily, after the pages are committed, so the run turns red.

### Not done here

Using ACEA as a fallback for missing country HEV (DK, FI, NL, LV) is a
later, separate change. Country CSVs stay national-source only.
