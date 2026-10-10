# scripts/fixtures — source samples

Real upstream files kept for offline tests and as the record of what a parser
was validated against. They are **not data**: `data/` holds only the
`<Country>[_<Variant>].csv` series (plus `data/raw/` build inputs), and nothing
here is ever read by a fetcher's scheduled run.

| File | What it is | Used by |
|---|---|---|
| `202605081028169165.xlsx` | JADA «燃料別メーカー別登録台数（乗用車）» workbook, May 2026 release (months 2026-01 … 04) | `scripts/test_market_top.py` (`test_japan_maker_rows`); validation record in `docs/architecture/05-flows.md` § Flow J |
| `202605081027423166.pdf` | The same JADA publication as PDF | validation record, 05-flows § Flow J |
| `燃料別登録台数統計（2022年1月~12月）.xlsx` | JADA full-year 2022 rollup | validation record, 05-flows § Flow J |
| `Press_release_car_registrations_March_2026.pdf` | ACEA monthly car-registrations release, March 2026 | validation record, 05-flows § Flow K (`fetch_acea.py`) |
| `Press_release_car_registrations_April_2026.pdf` | ACEA release, April 2026 (Word-generated layout) | validation record, 05-flows § Flow K |
| `Total Sales for Website_April 2026.pdf` | ANL «Total Sales for Website», April 2026 | validation record, 05-flows § Flow N (`fetch_usa.py`) |
| `greece/2026-8-comp.xlsx`, `greece/2023-5-comp-1.xlsx` | SEAA passenger-car comparison workbooks (TOTAL by brand), August 2026 and May 2023 | `scripts/test_fetch_greece.py`; [53-source-greece.md](../../docs/architecture/53-source-greece.md) |
| `greece/2026-8-BEV.pdf`, `greece/2026-8-PHEV.pdf`, `greece/2026-3-BEV-1.pdf` | SEAA BEV / PHEV registrations by segment, brand and model (2026-03: the shifted "700,00%" volume line) | `scripts/test_fetch_greece.py` |
| `greece/2023-5-electric-1.pdf` | SEAA combined BEV + PHEV file of the 2021-12..2023-12 layout, May 2023 (printed month in Greek capitals, a few model lines missing) | `scripts/test_fetch_greece.py` |
| `greece/Δελτίο-τύπου-ΣΕΑΑ-…-Αυγούστου-2026.pdf`, `greece/…-Μαΐου-2023.pdf` | SEAA monthly press releases (fuel shares; 2026 also preliminary counts) | `scripts/test_fetch_greece.py` |

All were uploaded by the maintainer (`Add files via upload`) while the dev
sandbox could not reach the source, and moved here from `data/` in 2026-10 (the `greece/` files were mirrored
from seaa.gr by a GitHub Actions run in 2026-10, the sandbox being blocked).
Add a file here only together with the test or doc that uses it, and list it
in this table.
