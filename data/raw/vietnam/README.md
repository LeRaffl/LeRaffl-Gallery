# Vietnam — build inputs (`components.csv`)

`data/Vietnam.csv` is **derived**: every figure it is built from sits here, one
row per month, written by `scripts/fetch_vietnam.py` (workflow
`fetch-vietnam.yml`). `python scripts/fetch_vietnam.py --rebuild` rewrites the
CSV from this file without the network. Method and decisions:
[docs/architecture/64-source-vietnam.md](../../../docs/architecture/64-source-vietnam.md).

| Column | From | Meaning |
|---|---|---|
| `vama_ti`, `vama_ti_pc`, `vama_ti_cv`, `vama_ti_spv` | VAMA cover letter | Total industry and its passenger-car / commercial / special-purpose split (members **and** the non-member CBU importers VAMA estimates). If the headline disagrees with PC+CV+SPV (2024-11: 40,200 vs 44,200), the sum is used and `note` says so |
| `vama_members_pc`, `vama_members_bev`, `vama_members_hybrid` | VAMA cover letter | Members' "Subtotal" lines of the Passenger cars, BEV and Hybrid sections (month, TOTAL column). The BEV section exists from 2025-09 (0 before) |
| `vama_mhev` | VAMA Detail sheet | Mild hybrids inside the Hybrid section (Suzuki XL7 Hybrid, Ertiga Hybrid) — moved from HEV to MHEV |
| `vama_hev_in_pc`, `vama_bev_in_pc` | VAMA Detail sheet | Hybrids / BEVs that VAMA files in the passenger-car block (2026-09: Land Cruiser Hybrid, 116) — moved out of ICE |
| `vama_detail` | | `ok` (the sheet is the month's), `derived` (VAMA uploaded another month's sheet — 2025-05 and 2026-02 hold January — so the month was rebuilt from the neighbouring sheets' year-to-date columns), `pending` (not derivable yet; the three columns above are 0) |
| `vinfast`, `vinfast_ytd`, `vinfast_kind`, `vinfast_models` | VinFast release (vingroup.net; SEC 6-K text in the history; vinfastauto.com before 2024) | Domestic deliveries, year to date, `exact` / `rounded` ("more than N", 2024-09 … 2025-03) / `revised` (next month's YTD − its month, 2026-07: 21,781 → 17,996) / `manual` / `estimate` (no monthly figure: an even share of a year residual from VinFast's SEC filings, 2022-09/10 and 2023-08 … 2024-08; may have decimals, e.g. 3948.75; the CSV row is labelled `monthly_est`, drawn hollow in the charts); per-model figures as `NAME:n\|NAME:n` |
| `vinfast_ice` | VinFast release | The petrol part of `vinfast` (Fadil, Lux A/SA, President — sold until 2022); empty = 0 |
| `tc_total`, `tc_commercial`, `hyundai_models` | TC Group release (thanhcong.vn) | Hyundai total, commercial vehicles (out of scope), passenger models (`:n` = "Mẫu khác"); a month without a model table takes the next release's previous-month column |
| `src_vama`, `src_vinfast`, `src_tc` | | The URL each figure was read from (`manual input (file)` when a file was passed by hand) |
| `note` | | Shown in the CSV's `notes` column |

`data/Vietnam.csv` columns, per month:

- **BEV** = VinFast − `vinfast_ice` + `vama_members_bev` + `vama_bev_in_pc`
- **HEV** = `vama_members_hybrid` − `vama_mhev` + `vama_hev_in_pc` (empty before 2024-01: VAMA had no Hybrid block, hybrids are in ICE)
- **MHEV** = `vama_mhev` (empty before 2024-01, as HEV)
- **ICE** = `vama_members_pc` − `vama_hev_in_pc` − `vama_bev_in_pc` + Hyundai passenger (`tc_total` − `tc_commercial`; Hyundai is not split by powertrain and counted ICE) + `vinfast_ice`
- **OTHERS** = non-member imports: `vama_ti_pc` − members' PC − Hybrid − BEV (every powertrain, VAMA estimates them as one figure)
- **TOTAL** = `vama_ti_pc` + VinFast + Hyundai passenger. PHEV stays empty (no source splits it).

**Editing by hand** (a source that cannot be fetched): fill the columns, set
`vinfast_kind` to `manual` where VinFast was typed in (the fetcher then leaves
it alone), and run `--rebuild`. The rows 2024-09 … 2026-09 were seeded from
the publishers' pages and PDFs read in 2026-10; 2021-01 … 2024-08 were assembled
once from VAMA's archive, VinFast's releases and SEC filings and TC Group's
releases (or their media copies), each with its URL (doc 64 §2a). The fetcher
never revises an `estimate` row from a later year to date.
