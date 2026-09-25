
# BEV Trajectories · @LeRaffl

This repository powers the public **BEV Trajectory Gallery**, an interactive dashboard that visualizes electric-vehicle transition dynamics for countries around the world.

▶ **Open the live gallery:**  
https://leraffl.github.io/LeRaffl-Gallery/#gallery

The gallery is updated continuously and provides, for each country:

- 📈 **BEV transition trajectories** (fitted logistic / Weibull-style curves)
- 🔄 **ICE↔BEV market-share transition charts**
- 🟫 **TTM (trailing-twelve-month) market-split graphs**
- ⏱️ **Transition-time curves** (speed of change between thresholds)

In addition, the dashboard includes two analytical views:

- **Thresholds** — When does a market reach 20%, 50%, 80% BEV share?  
- **Durations** — How long does it take to move from one share level to another (e.g., 20→80%)?

All computations run purely **client-side** in the browser.

---

## 🚀 Project Purpose

Many countries follow an S-curve when transitioning from internal-combustion engines to battery-electric vehicles.  
This project aims to make these transitions **comparable, transparent, and publicly accessible**, using a consistent modelling approach across all markets.

Inputs include:

- Monthly new-registration data (sources include ACEA, KBA, CPCA, Statistik Austria, and others)
- A generalized logistic (Weibull-like) model
- Harmonized modelling assumptions for cross-country comparability

Outputs:

- PNG charts for each country and month
- A parameter table (`params.csv`) containing all fitted model parameters
- Uncertainty bands per series (`bands/<slug>.json`: confidence, prediction and tolerance intervals)
- A machine-generated gallery manifest (`manifest.json`)

---

## 📂 Repository Structure

Key files in the repository root:

| File | Purpose |
|------|---------|
| **index.html** | The full interactive UI, single file, no build step. Four primary nav entries — **Charts / Map / Rankings / Tools** — with a sub-nav, over 14 sections (Gallery, World Map, Thresholds, Durations, Time Interval, Builder, Compare, Raw Data, Fleet, Data freshness, Submit Data, About, FAQ, Feedback). Runs 100% in the browser. |
| **manifest.json** | Auto-generated list of all available charts, used by the Gallery to display images. |
| **build_manifest.R** | Scans `images/` and generates `manifest.json`. |
| **params.csv** | Contains the model parameters (v1, v2, t0, baseline year, last data month) for each market. Used for Thresholds & Durations. |
| **bands/** | Generated per render by `R/bands.R`: one `<slug>.json` per series with the 95 % confidence, prediction and tolerance bands around the fitted curve, plus the 10/20/50/80/90 % crossing years with their confidence ranges. Frontend data only (the PNGs do not use it): drawn as the optional uncertainty band in Builder and Compare. What the bands mean and how to quote them: `docs/architecture/44-uncertainty-bands.md`. |
| **footnotes.csv** | Optional curated per-country/variant chart footnotes (`country,variant,footnote`). `render_country.R` appends the matching note as a second caption line on the PNGs (e.g. Canada `Whole`'s pre-2017 passenger-cars-only scope). Separate from the CSVs' internal `notes` column. |
| **log_params.R** | Produces and updates the parameter table (`params.csv`). |
| **images/** | Contains all exported PNG files structured as `images/YYYY-MM/...`. GitHub Pages serves them directly. |
| **.github/workflows/build-manifest.yml** | CI workflow ensuring that `manifest.json` always stays up to date. |
| **docs/architecture/** | Architecture handbook — components, data objects, interfaces, flows, secrets, ops. Kept up to date with every PR that changes structure. Start at [docs/architecture/README.md](docs/architecture/README.md). |
| **scripts/fetch_brazil.py** | Automated data ingestion for Brazil. Queries ANFAVEA's "Central de Dados" (WordPress `admin-ajax.php`, registrations by fuel for cars + light commercials) for the running year and upserts the monthly rows into `data/Brazil.csv`. Until the 2026-09 site relaunch it parsed the yearly xlsx instead. Full parsing logic & column mapping documented in the module docstring; offline regression test in `scripts/test_fetch_brazil.py`. |
| **.github/workflows/fetch-brazil.yml** | Runs `fetch_brazil.py` on the 10th of each month (08:50 UTC) and on manual dispatch. If `data/Brazil.csv` changes, the workflow commits it and triggers `render-country.yml` with `country=Brazil`. |
| **scripts/fetch_chile.py** | Automated data ingestion for Chile. Discovers the latest ANAC PDFs (Mercado Automotor + Cero y Bajas Emisiones) for the previous calendar month, parses TOTAL from the bar chart and BEV/PHEV/HEV from the summary table, and writes the new row to `data/Chile.csv` only when both PDFs are available. Self-throttles via the CSV's latest period. |
| **.github/workflows/fetch-chile.yml** | Runs `fetch_chile.py` daily from the 14th of each month (08:20 UTC) and on manual dispatch — most runs are no-ops until ANAC publishes both PDFs. If `data/Chile.csv` changes, the workflow commits it and triggers `render-country.yml` with `country=Chile`. |
| **scripts/fetch_japan.py** | Automated data ingestion for Japan. Discovers the latest JADA monthly "燃料別メーカー別登録台数（乗用車）" file on jada.or.jp/pages/342/ (XLSX preferred, PDF fallback), extracts the 乗用車計 (all-makes total) row for the target month — PETROL/HEV/PHEV/DIESEL/BEV/(FCV+その他)/TOTAL — and upserts into `data/Japan.csv`. Scope is 登録車 only (no 軽自動車). Self-throttles via the CSV's latest period; manual override via `--xlsx-url`/`--pdf-url` when the JADA host blocks the runner IP. |
| **scripts/fetch_thailand.py** | Automated data ingestion for Thailand. Logs into the TAI **AIU member portal** (`aiu.thaiauto.or.th`, cookie session — no bearer token) and reads its JSON API on `taiapi.thaiauto.or.th:3000`: resolves the AIU `website_id` via `/websites`, then one `GET /veh_reg_fuel/report?period_mode=year&year=<Y>&type_code=ALL` per year returns every vehicle-type category (row array under `raw_rows`). Exact-`type_label` match splits four variants from that one call: `Whole` = **Passenger Car and Pickup Truck** (pickups are bundled, not separable) → `data/Thailand.csv`; plus `HDV` (Truck), `Buses` (Bus), `3-Wheelers` (Three Wheelers). Maps BEV/PHEV/HEV←units, ICE←icev_units, OTHERS←other+not_specific; aggregate-ICE schema (no petrol/diesel split). Credentials via `THAILAND_AIU_THAIAUTO_USER`/`_PW`. The API is port 3000 — GHA runners reach it directly. `Whole` was rebased onto the AIU passenger+pickup definition (old series archived in `data/Thailand_legacy.csv`). See [docs/architecture/29-source-thailand.md](docs/architecture/29-source-thailand.md). |
| **.github/workflows/fetch-japan.yml** | Runs `fetch_japan.py` daily from the 1st of each month (08:00 UTC) and on manual dispatch — most runs are no-ops until JADA publishes the file for the previous month (typically the first business week). If `data/Japan.csv` changes, the workflow commits it and triggers `render-country.yml` with `country=Japan`. |
| **scripts/fetch_indonesia.py** | Automated data ingestion for Indonesia. Logs into GAIKINDO's ProjectSend portal (`files.gaikindo.or.id`, csrf + password login, credentials via `INDONESIA_GAIKINDO_USER`/`_PW`), discovers the newest cumulative "Wholesales Jan-XXX YYYY" PDF (English *and* Indonesian month abbreviations) and parses its seven model-level Excel-paste sheets positionally with pdfplumber (1.56 pt font — tight tolerances, split-number reassembly, wrapped-row re-attachment). `Whole` = GAIKINDO Passenger Car (Sedan+4x2+4x4+LCGC, continues the R. Andrew series) → `data/Indonesia.csv`; plus `Pickups` (pick ups < 5 t + double cabins), `HDV` (trucks ≥ 5 t), `Buses`. Fuel split G/D/BEV/HEV/PHEV per model; rarities (CNG) → OTHERS. Every month is checksummed against the PDF's printed section totals and PC/CV/DOMESTIC summary rows — any mismatch aborts before writing. Each cumulative file rewrites all covered months (absorbs revisions). See [docs/architecture/30-source-indonesia.md](docs/architecture/30-source-indonesia.md). |
| **.github/workflows/fetch-indonesia.yml** | Runs `fetch_indonesia.py` daily from the 10th of each month (09:35 UTC) and on manual dispatch (`download_url` override, `force`) — the script self-throttles via the newest portal file title, so runs are no-ops until GAIKINDO publishes a new month. If a CSV changes, the workflow commits the four Indonesia CSVs and triggers `render-country.yml` with `country=Indonesia` (variant `Whole`). |
| **scripts/build_theme.py** | Extracts the design tokens (palette + type stack) from `index.html`'s `:root` block into `assets/theme.css`, which the generated standalone pages — `sources/*.html` and `schedule*.html` — link. `index.html` stays the single source of truth for the design, so those surfaces cannot drift away from the gallery the way they did before [#221](https://github.com/LeRaffl/LeRaffl-Gallery/issues/221). `--check` verifies the committed stylesheet still matches and fails CI if not. **`assets/theme.css` is generated — never hand-edit it.** |
| **scripts/snapshot_builder.py** | Snapshots the Builder-tab aggregated BEV/ICE/PHEV curves (world + 13 regional/weight-based groups) to `builder_history/<date>.csv` plus a metadata entry in `builder_history/index.json`. Mirrors the in-page Builder math (including the v1=0 anchor recovery), so a snapshot reproduces what the page plots that day. Every snapshot is on one x-basis: the formerly one-year-late band was **rebuilt** from git rather than annotated; see [#219](https://github.com/LeRaffl/LeRaffl-Gallery/issues/219). Regression tests in `scripts/test_snapshot_builder.py`. |
| **scripts/rebuild_builder_history.py** | Regenerates any past snapshot from the `params.csv` / `weights.csv` git holds for that date. `--cohort` additionally writes `builder_history/cohort/`, every frame restricted to the 44 countries present on all dates — which separates "the model changed its mind" from "the gallery gained countries". |
| **R/build_backtest.R** | The backtest: re-fits every country series from `data/` truncated to each month, writing `backtest/params/<YYYY-MM>.csv` + `backtest/weights/<YYYY-MM>.csv`. Answers "what would this model have said at date X" — a different question from `builder_history/`, and one that reaches **2015** where git-based archaeology cannot start before 2025-09. Truncates *today's revised* CSVs, so it is an upper bound, not a clean out-of-sample test. Resumable and parallel; the 2015 backfill is ~9,200 fits (~1 h on 4 cores), each new month ~95. A newly added country is backfilled into every existing month once, automatically. |
| **scripts/build_backtest_series.py** | Pivots `backtest/` into `backtest/series/<group>.json` — one group, all months, both country sets, at half-year resolution, with the 20/50/80 % crossing years precomputed per frame. **This is the only form the browser reads.** Imports its aggregation from `snapshot_builder.py` so a backtest curve and a snapshot curve cannot differ by code. |
| **scripts/build_builder_series.py** | The same pivot for `builder_history/`. Nothing renders its output today, but it owns the grid/sampling/labelling helpers the backtest builder imports, so the two aggregations cannot drift. |
| **scripts/build_builder_gif.py** | Renders each group's series into `backtest/series/<group>.gif` (Pillow, no matplotlib). Only the curated `GIF_GROUPS` (four blocs + six spotlight countries), **overwritten in place** — each run is the same animation one frame longer, so vintages are not kept. Quarterly subsample (`--step 3`), so 116 monthly frames become a 40-frame, ~12 s loop rather than a minute of footage. Every frame carries the revised-data caveat, because a still travels without the page around it. |
| **.github/workflows/snapshot-builder.yml** | On the 25th of each month (09:00 UTC) and on manual dispatch: runs `snapshot_builder.py` to freeze what the page shows today into `builder_history/`, **and** extends the backtest by the new month, rebuilds `backtest/series/` and re-renders the animations. Both land in one commit, so the Time-lapse panel in the Builder tab is never behind the data. |
| **scripts/check_country_integration.py** | Verifies every country in `data/` is wired into every place the gallery needs it — Submit-Data list, flag file and emoji, continent colour, a Builder region group (and that the two group mirrors agree), time zone, source page, glossary, its fetch workflow's docs and schedule labels, and a backtest history for the Time-lapse. Pre-existing gaps are listed with reasons in `KNOWN_GAPS`; a fixed gap left there also fails. The checklist it enforces: [docs/architecture/42-adding-a-country.md](docs/architecture/42-adding-a-country.md). |
| **.github/workflows/backfill-bands.yml** | Manual only: recomputes `bands/<slug>.json` for every series (or the given countries) via `scripts/backfill_bands.R` and commits only `bands/`. For the first fill and after changing `R/bands.R`. |
| **.github/workflows/preview-render.yml** | On every pull request touching `R/` (and on manual dispatch): renders a fixed set of series twice from the same data — with the PR's `R/` and the base branch's — and uploads the side-by-side charts plus `params.csv` before/after as the `render-preview` artifact, linked from one PR comment. Commits nothing. |
| **scripts/build_render_preview.py** | Turns the preview's per-series renders into `compare/*.png` (base \| PR, side by side), `index.html` and a summary table. |
| **.github/workflows/check-country-integration.yml** | Runs `check_country_integration.py` on every pull request touching data, `index.html`, R, flags, docs, `backtest/params` or a fetch workflow (and on manual dispatch). |
| **scripts/fetch_uruguay.py** | Automated data ingestion for Uruguay. Scrapes the ACAU homepage for the current year's "Compilado YYYY" xlsx (filename is timestamp-based and changes between publications), parses the AUTOS + SUV sheets, maps the per-model `Combustible` codes (E→BEV, PHEV→PHEV, H→HEV, N→PETROL, D→DIESEL, MHEV→OTHERS), and upserts new months into `data/Uruguay.csv`. Cross-checks against each sheet's bottom TOTAL row. Self-throttles via the CSV's latest period. |
| **.github/workflows/fetch-uruguay.yml** | Runs `fetch_uruguay.py` daily from the 1st of each month (08:10 UTC) and on manual dispatch — most runs are no-ops until ACAU edits the previous month into the Compilado workbook (typically the first week of the following month). If `data/Uruguay.csv` changes, the workflow commits it and triggers `render-country.yml` with `country=Uruguay`. |
| **scripts/fetch_germany.py** | Automated data ingestion for Germany (registrations). Discovers the newest KBA monthly press-release `…_merkmale.xlsx` (listing page → `…_komplett.html` → SharedDocs xlsx, both hops overridable), reads the "Kraftstoffarten" block (Benzin→PETROL, Diesel→DIESEL, Elektro→BEV, Hybrid − darunter Plug-in → HEV, Plug-in→PHEV), and upserts one monthly row into `data/Germany.csv` (Whole). `OTHERS` is the residual `TOTAL − BEV − PHEV − HEV − PETROL − DIESEL` (LPG/CNG/H₂/fuel-cell/Sonstige) — matches the pre-automation hand-entry convention exactly (verified against 08/2026). Line-level upsert keyed on `(period, Whole)`; historical quarterly/modelled decimal rows are preserved byte-for-byte. Honours `KBA_FETCH_RELAY`/`KBA_PROXY` for datacenter-IP blocks; `--file`/`--url`/`--dry-run`/`--force`. See the module docstring and `docs/architecture/country_source_stubs.yaml` (Germany). |
| **.github/workflows/fetch-germany.yml** | Runs `fetch_germany.py` daily on the 4th–9th of each month (06:00 UTC) and on manual dispatch (`url`, `force`, `dry_run`). The fetcher early-exits once the previous month is in the CSV, so most runs are no-ops until KBA publishes the press release (typically the first week). If `data/Germany.csv` changes, the workflow commits it and triggers `render-country.yml` with `country=Germany` (variant `Whole`) — unlike the Germany **fleet** fetcher, which does not render. |
| **scripts/fetch_turkey.py** | Automated data ingestion for Türkiye. Finds the TÜİK "Motorlu Kara Taşıtları" bulletin for the target month itself — the Veri Portalı is a React SPA with no listing endpoint, so `scripts/tuik_discover.py` walks bulletin ids outward from the newest one in the CSV and matches on title + period — then pulls the authoritative monthly + YTD totals from the narrative, OCRs the fuel-breakdown table image (poppler + imagemagick + tesseract-tur), and upserts the row into `data/Türkiye.csv` (Elektrik→BEV, Hibrit→HEV, Benzin→PETROL, Dizel→DIESEL, LPG→OTHERS). Three validation layers: narrative-vs-OCR Toplam, per-fuel sum check with single-error auto-repair via Pay % cross-check, and previous-year-same-month column cross-check against the existing CSV row. Self-throttles via the CSV's latest period. |
| **.github/workflows/fetch-turkey.yml** | Runs `fetch_turkey.py` daily from the 15th of each month (08:30 UTC) and on manual dispatch. No input is required — the bulletin id is auto-discovered; `press_id` / `pdf_url` remain as overrides for when the portal changes shape. Runs self-throttle to a no-op until TÜİK publishes the next bulletin (date footnoted in the previous one as "Bu konu ile ilgili bir sonraki haber bülteninin yayımlanma tarihi …"). If `data/Türkiye.csv` changes, the workflow commits it and triggers `render-country.yml` with `country=Türkiye`. |
| **scripts/fetch_canada.py** | Automated data ingestion for Canada. Reads Statistics Canada's Web Data Service (WDS cube **20-10-0025** "New motor vehicle registrations"): one `getCubeMetadata` call resolves the dimension members by name (Geography=Canada, Vehicle type, the Fuel type leaves), then a batched `getDataFromCubePidCoordAndLatestNPeriods` call pulls the latest quarters per fuel. Maps the fuel leaves (battery electric→BEV, plug-in hybrid→PHEV, hybrid→HEV, gasoline→PETROL, diesel→DIESEL, other/fuel-cell→OTHERS), stores each quarter under its middle month (Q1→02 … Q4→11). Produces three variants from this light-vehicle cube: `Whole` = **EU M1** (Passenger cars + Multi-purpose vehicles/SUVs, harmonised with how every other country counts passenger cars) → `data/Canada.csv`; plus Canada-specific `Pickups` (Pickup trucks) → `data/Canada_Pickups.csv` and `Vans` (minivans + cargo vans) → `data/Canada_Vans.csv`. **Definition change:** `Whole` was historically passenger-cars-only; it is now M1 (starts ~2017 where the SUV fuel split begins). See [docs/architecture/17-source-canada.md](docs/architecture/17-source-canada.md). Full logic in the module docstring and [docs/architecture/17-source-canada.md](docs/architecture/17-source-canada.md). |
| **.github/workflows/fetch-canada.yml** | Runs `fetch_canada.py` daily on the 8th–20th of March/June/September/December (06:40 UTC) — the cube is quarterly and StatCan releases it ~2.5 months after quarter-end — and on manual dispatch. The script always re-fetches the latest N quarters (StatCan revises recent ones); the commit step is change-gated, so steady-state runs are a no-op. Detects which per-variant CSVs changed and triggers `render-country.yml` once with the touched variants (`country=Canada`), which it renders serially in a single "Render: Canada" run. |
| **scripts/fetch_nepal.py** | Automated data ingestion for Nepal. Downloads the Department of Customs' cumulative monthly **Foreign Trade Statistics** workbooks (customs.gov.np — three-hop discovery: homepage nav → fiscal-year category → content page → one xlsx per Nepali month), parses sheet "5_Imports_By_Commodity" (8-digit HS codes) and rebuilds every month of the processed fiscal year from consecutive-file deltas. `Whole` = HS 8703 cars/jeeps/vans (≈ M1, **imports not registrations** — Nepal imports its entire market) → `data/Nepal.csv`; passenger three-wheelers (petrol auto-rickshaws + electric e-rickshaws, 16.5k units FY 2081/82!) are split into `data/Nepal_3-Wheelers.csv`. Hybrids use the single-Hybrid-bucket convention (DoC's PHEV/HEV tariff descriptions are displacement-garbled). Nepali fiscal months are labelled by their Gregorian end month (Shrawan → August). Coverage is parsed from each workbook's own English header line — the Devanagari link labels are too inconsistent to trust. See [docs/architecture/32-source-nepal.md](docs/architecture/32-source-nepal.md). |
| **.github/workflows/fetch-nepal.yml** | Runs `fetch_nepal.py` daily (07:50 UTC) and on manual dispatch (`fy`, `backfill` inputs). The fetcher cheap-skips when the CSV already carries every workbook published for the current fiscal year, so steady-state runs are no-ops; when a CSV changes, the workflow commits it and triggers `render-country.yml` once with both variants (`Whole`, `3-Wheelers`), which it renders serially in a single "Render: Nepal" run. |
| **scripts/fetch_usa.py** | Automated data ingestion for the USA. Auto-discovers the latest ANL "Total Sales for Website" PDF on the ESIA reference page (or takes a direct `--pdf-url`), parses the full monthly Light-Duty table (BEV/PHEV/HEV/Total LDV; ICE = Total − BEV − PHEV − HEV, OTHERS = 0), and upserts a trailing window of `--months` (default 3) months into `data/USA.csv`. ANL revises the last ~2 months between releases, so the window appends new months *and* corrects recently-revised ones in place; rows older than the window are never touched (deep-history rows may still differ from a newer PDF). The CSV is only rewritten when a value in the window actually changed, so steady-state runs are a no-op. |
| **scripts/fetch_argentina.py** | Automated data ingestion for Argentina. Reads DNRPA's free record-level *Inscripciones iniciales de autos* open data (datos.jus.gob.ar CKAN — one record per first registration, 2018 →), keeps 0 km registrations, and writes `Whole` (passenger-car body types ≈ M1), `Private`/`Industry` (natural vs legal-person first owner) and `Pickups` from one download — Pickups is **data only** (CSV kept current, never rendered). The records carry **no fuel field**: the powertrain is classified from the model designation by the hand-edited, tested rule table `classification/argentina_rules.csv` (e.g. Arkana "E-Tech Hybrid" and Suzuki "Hybrid" are mild hybrids; Volvo T8 / BMW 330E / BYD DM-i are plug-ins), validated against ACARA's electrified totals. Every run also regenerates the full designation → class → rule mapping and the top BEV/PHEV brands and models (`classification/argentina_models.csv`, `argentina_top.json`), both shown on the Argentina source page. See `docs/architecture/39-source-argentina.md`. |
| **scripts/market_top.py** | Shared builder for the per-country **top brands / models** summary (`market/<slug>_top.json`; Argentina's `classification/argentina_top.json`): trailing-12-month units per electrified class, top 10 brands and top 15 models, country-neutral schema, byte-stable. Used by the Argentina, Spain (DGT), Malaysia (data.gov.my) and Ukraine (MIA register) fetchers; rendered on each source page as "Who sells the electrified cars" via the `market_breakdown:` front-matter key. Refresh failures are warnings and never block a data commit. Tests: `scripts/test_market_top.py`. See `docs/architecture/03-data-objects.md` §3.16. |
| **.github/workflows/fetch-argentina.yml** | Runs the classifier tests, then `fetch_argentina.py`, twice daily on the 8th–25th (09:15 & 21:15 UTC; DNRPA uploads ~the 11th) and on manual dispatch (`variant`, `period`, `backfill`, `force`). Self-throttles once every CSV has the month; real runs re-derive the current and previous year (DNRPA re-uploads past years) and dispatch `render-country.yml` once with the touched rendered variants (Whole/Private/Industry; Pickups is data only). |
| **scripts/fetch_ukraine.py** | Automated data ingestion for Ukraine. Reads the Ministry of Internal Affairs' free record-level vehicle register on data.gov.ua (CKAN — one record per registration operation, yearly zips, the current year re-uploaded around the 1st), keeps first registrations by the register's own operation codes and writes `Whole` (new passenger cars, M1), `Private`/`Industry` (owner type P/J), `Used` (used imports at first Ukrainian registration) and `Vans` (new goods vehicles ≤ 3.5 t, N1) from one download, 2018-09 onward. The fuel comes from the record itself (`ЕЛЕКТРО` → BEV; the register's single "electric or petrol/diesel" value → one combined Hybrid bucket, no PHEV split). Governance checks abort on schema drift, broken uploads, unknown fuel strings or a Private+Industry≠Whole mismatch, and list any unmapped first-registration code in the step summary. Also writes `market/ukraine_top.json`. Tests: `scripts/test_fetch_ukraine.py`. See `docs/architecture/40-source-ukraine.md`. |
| **.github/workflows/fetch-ukraine.yml** | Runs the fetcher tests, then `fetch_ukraine.py`, twice daily on the 1st–15th (08:40 & 20:40 UTC) and on manual dispatch (`variant`, `period`, `backfill`, `force`). Self-throttles once every CSV has the month; a real run reads the current and previous yearly file and dispatches `render-country.yml` once with the touched variants. |
| **scripts/fetch_hong_kong.py** | Automated data ingestion for Hong Kong. Reads the Transport Department's free record-level *Particulars of first registered vehicles* on DATA.GOV.HK (CKAN — one CSV per month from 2019-11, one row per vehicle: class, make, model, fuel, TD first-registration status, gross weight), keeps private cars never registered abroad (status A/B/C1 → `Whole`), used imports (C2 → `Used`) and light goods vehicles ≤ 3.5 t (`Vans`). BEV from TD's fuel field; plug-in hybrids from the model designation (`PHEV_RULES` — the fuel field has no hybrid value, full/mild hybrids stay in PETROL). Cross-checks every run against TD's aggregate table 4.1(e) and aborts on a real mismatch; writes `market/hong_kong_top.json`. Line-level upserts into `data/Hong Kong.csv`, `_Used`, `_Vans`. See [docs/architecture/41-source-hong-kong.md](docs/architecture/41-source-hong-kong.md). |
| **.github/workflows/fetch-hong-kong.yml** | Runs the fetcher tests, then `fetch_hong_kong.py`, twice daily (03:20 & 11:20 UTC — TD uploads month M between the 13th and 28th of M+1) and on manual dispatch (`variant`, `period`, `backfill`, `force`). Self-throttles on the portal's newest month (one JSON request, no download); a real run reads the newest 12 monthly files. Commits changed CSVs + the top list and dispatches `render-country.yml` once with the touched variants. |
| **scripts/fetch_colombia.py** | Automated data ingestion for Colombia. Scrapes ANDI's Cámara Automotriz page for the newest joint ANDI/FENALCO "Informe del Sector Automotor" PDF (RUNT-sourced; the filename shape has changed every year — discovery reads month + year out of any bulletin-named PDF link rather than pinning a template). Since September 2026 that page lists only year-end reports, so when the newest listed bulletin is older than the month due, discovery falls back to rebuilding that month's `andi.com.co/Uploads/` URL, where ANDI still serves it — accepted only if the body really is a PDF *and* parses to the month requested. If neither route reaches the due month, the run exits quietly before the 20th and **fails** after it, so a source that moves can never look green. Then runs `pdftotext -layout` and reads the three monthly bar charts (passenger-car total, eléctricos → BEV, híbridos → HEV as a single combined hybrid bucket; ICE = TOTAL − BEV − HEV) for the ~31 months each PDF covers. Bar values that pdftotext puts below their month label are picked up by a column-aware look-ahead; a value that still cannot be read is *unknown* — it never overwrites an existing CSV cell and never becomes a 0. Regression tests in `scripts/test_fetch_colombia.py`. See [docs/architecture/18-source-colombia.md](docs/architecture/18-source-colombia.md). |
| **.github/workflows/fetch-colombia.yml** | Runs `fetch_colombia.py` daily on the 5th–25th of each month (07:30 UTC) and on manual dispatch (`pdf_url` override, `force`, `dry_run`, `dump_listing`). `dry_run=true` parses the newest bulletin, prints what would change plus the full pdftotext output into the log, and uploads PDF + text as a run artifact without writing or committing — the way to check discovery or a parser change from a branch. `dump_listing=true` additionally reports what the Cámara page actually contains (every PDF href, every `AUTOMOTOR` mention, and the links it rejected) and saves the page HTML into the artifact — the way to tell “the bulletin moved” apart from “we failed to recognise it”. If `data/Colombia.csv` changes, the workflow commits it and triggers `render-country.yml` with `country=Colombia`. |
| **.github/workflows/fetch-usa.yml** | Runs `fetch_usa.py` daily from the 10th of each month (10:30 UTC — offset from the 08:00 slot used by other fetchers) and on manual dispatch. If `data/USA.csv` changes, the workflow commits it and triggers `render-country.yml` with `country=USA`. |
| **scripts/fetch_israel.py** | Automated data ingestion for Israel. Counts monthly new registrations from the Ministry of Transport's open vehicle registry on data.gov.il (CKAN datastore, ~4.15M currently-registered vehicles), scope `sug_degem=P` (private passenger cars), grouped by the **unpadded** road-entry month (`moed_aliya_lakvish`, e.g. "2016-3"). The registry codes regular HEVs as plain petrol — the fetcher joins every row against the official model catalogue (`degem-rechev-wltp`, `technologiat_hanaa_nm`: PLUG IN / regular hybrid / electric / conventional) on (make, model code, model year, trim) to recover the HEV and PHEV split; validated against I-VIA monthly reviews. Also has a `--probe` mode that dumps datastore schema/cross-tabs. See [docs/architecture/34-source-israel.md](docs/architecture/34-source-israel.md). |
| **.github/workflows/fetch-israel.yml** | Runs `fetch_israel.py` daily on the 10th–20th (08:00 UTC) and on manual dispatch (probe/fetch mode, optional YYYY-MM backfill window, commit gate). Self-throttles once the previous month is present; real runs re-count the last 3 months (late registrations trickle into the snapshot). If `data/Israel.csv` changes, the workflow commits it and triggers `render-country.yml` with `country=Israel`. |
| **scripts/fetch_france.py** | Automated data ingestion for France. Resolves the current SDES *Immatriculations mensuelles de voitures neuves par motorisation* workbook from the StatInfo landing page (the média id rotates each publication), reads the série VP neuves par énergie — the SIV registry statistics behind ACEA/PFA, with a real HEV column and the full énergie split back to 2011 — and upserts `data/France.csv` (Whole, EU M1). See [docs/architecture/36-source-france.md](docs/architecture/36-source-france.md). |
| **.github/workflows/fetch-france.yml** | Runs `fetch_france.py` daily on the 18th–end of month (07:40 UTC) and on manual dispatch (`url` override, `diagnose`). Change-gated commit; a changed `data/France.csv` dispatches `render-country.yml` for Whole. |
| **scripts/fetch_south_korea.py** | Automated data ingestion for South Korea. Finds the newest «자동차산업 동향» press releases on the MOTIR board, downloads each PDF and parses total domestic sales (표 3) and the eco-friendly-car table (참고 2: hybrid, BEV, plug-in, hydrogen) — three columns per release (year earlier / previous / current, from the header). Writes the current and the revised previous month into `data/South Korea.csv` (Whole, ICE = total − eco); cross-checks the year-earlier column. See [docs/architecture/43-source-south-korea.md](docs/architecture/43-source-south-korea.md). |
| **.github/workflows/fetch-south-korea.yml** | Runs the parser tests, then `fetch_south_korea.py`, twice daily on the 12th–25th (03:35 & 09:35 UTC) and on manual dispatch (`releases`, `force`, `dry_run`). Change-gated commit; dispatches `render-country.yml` for Whole. |

### The other data fetchers

The rows above are the ones that grew a long-form entry; they are **not** the
full set. Data is fetched automatically for 30 countries in total — the ones
without a row here are Albania, Austria, China, Colombia, Denmark, Finland,
Ireland, Italy, Luxembourg, Malaysia, Netherlands, Poland, Portugal, Singapore,
Spain and Sweden, plus the ~16-country ACEA cluster
(`scripts/fetch_acea.py`) and New Zealand, whose fetcher exists but whose cron
is currently disabled.

A related but separately-curated set of countries gets `Vans` / `HDV` /
`Buses` variants from a second, separate fetcher — `scripts/fetch_acea_cv.py`,
ACEA's Commercial Vehicle press release — since ACEA publishes cars and
commercial vehicles as two different reports, and which countries need which
report differs (Germany/France/Sweden have their own passenger-car source
but no national commercial-vehicle one, so they're in this roster and not
the `fetch_acea.py` one; see `docs/architecture/38-source-acea-cv.md` § 1a).
ACEA only publishes cumulative year-to-date
checkpoints (Q1/H1/Q1-Q3/full-year) for commercial vehicles, so this fetcher
reconstructs genuine `Q1`/`Q2`/`Q3`/`Q4` rows from them, falling back to a
single yearly row only when no quarterly baseline exists yet for that
country/variant/year; see
[docs/architecture/38-source-acea-cv.md](docs/architecture/38-source-acea-cv.md)
for how.

For the complete, always-current picture — every fetcher, its source, the
variants it writes and its schedule — see
[docs/architecture/02-components.md § 2.7](docs/architecture/02-components.md#27-fetch-actions-overview)
and the cron table in
[docs/architecture/08-deploy-ops.md § 8.11](docs/architecture/08-deploy-ops.md#811-cron-schedule-overview).
Each country also has a public source page under
[`sources/`](https://leraffl.github.io/LeRaffl-Gallery/sources/) explaining
where its numbers come from.

---

## 🖼️ How the Gallery Works

When opening `index.html`, the browser loads:

1. **manifest.json** — the full list of charts  
2. **params.csv** — all relevant model parameters  
3. **series/index.json**, then **series/&lt;country&gt;.json** on demand — the observed monthly series behind Raw Data and the landing hero chart  
4. Renders everything dynamically

The landing section opens with a hand-rolled inline-SVG chart for your **home market**, picked from your browser's timezone — no IP lookup, no location prompt — and a search box that writes straight through to the gallery filter (press Enter to jump to the gallery).

### Gallery
- Filter by country, date, chart type, filename  
- Lightbox preview and direct download  
- “Latest only” mode automatically selects the newest chart per type/country (there may be several even for a single month, e.g. when I'm cleaning up or trying something)  

### Thresholds
- Computes 20%, 50%, 80% share dates + any custom threshold  
- Based on the fitted model parameters  
- Exportable as CSV  

### Durations
- Estimates transition durations (20→80%, 10→90%, custom X→Y%)  
- Includes the numerical speed at the inflection point  
- Exportable as CSV  

---

## 🔧 Data Generation (Overview)

Charts are generated locally using R scripts.  
The workflow:

1. Monthly registration data is ingested and modelled  
2. PNG charts are exported to the images folders by my locally run R scripts
3. `build_manifest.R` scans the directory → produces `manifest.json`
4. `params.csv` is carrying relevant output parameters from each model
5. GitHub Galerie shows updated gallery using the manifest as a guide of what to show with what filter
6. Github Thresholds and Durations are calculated on your device using the parameters from the R output cached in params.csv

The tables calculate thresholds and durations live.

**Why isn't country X on the gallery?** Some countries were investigated and deliberately left off because their freely-available data is incomplete (e.g. the dominant EV brand doesn't report), paywalled, login-walled, or because the market doesn't fit the new-registration / organic-transition model (e.g. Ethiopia's 100 %-EV import *mandate* over an ~85 %-used-import market). The rationale per country (Mexico, Ethiopia, … — plus Argentina and Colombia, which were shelved there first and have since been added from better sources) is documented in [docs/architecture/14-data-source-gaps.md](docs/architecture/14-data-source-gaps.md).

---

## 🧠 The model
1. What is being modelled

For each country, I model the BEV share of new car registrations over time.
Empirically, this share does not behave like random noise.
It behaves like a structured transition process: slow start, acceleration, eventual stabilization.
The model is therefore not trying to “predict the future”, but to describe the structure of the transition as observed so far.


2. Why an S-curve at all?

Most large-scale technology transitions follow a similar qualitative pattern:
- early friction (costs, infrastructure, trust)
- positive feedback loops once adoption takes off
- diminishing returns as edge cases remain

This produces curves that are monotonic, bounded, and nonlinear.
An S-shape is not assumed because it is pretty, it is assumed because it is the simplest structure that repeatedly matches real transitions. We've seen transitions between technologies in the past and this shape just fits.


3. Why not a normal distribution?

A normal distribution can, in fact, be fitted to cumulative adoption data like this.
The problem is not that it can't be used. The problem is structure.

A normal distribution is:
- symmetric by construction
- unable to express asymmetric acceleration/deceleration
- unable to “break” as visibly when the data stops behaving like a transition

In other words:
A normal distribution is just less suited.


4. Why a Weibull / generalized logistic formulation?
The Weibull-style formulation is chosen for three reasons:

(1) Asymmetry
Real-world adoption curves are almost never symmetric. The Weibull allows early-heavy, late-heavy, or roughly symmetric transitions — all with the same functional form.

(2) Failure visibility
A Weibull does not HAVE to produce an S-curve. It could yield other shapes as well. It doesn't produce other shapes in most cases though, simply because the data fits S-shapes best.
If the data does not support a meaningful transition, the model can:
- fail to converge
- produce nonsensical parameters (NaN, ±∞)
- collapse into degenerate shapes
This is a feature, not a bug.

Example:
Markets like Japan, which show no clear BEV transition, cause the model to break — exactly where it should. These examples are rare though. At time of writing I know of exactly 2 cases: Japan and Croatia

(3) Parametes
The model uses two parameters.
fewer → insufficient flexibility
more → unstable estimation and overfitting
Two parameters are a sweet spot, flexible enough to reflect reality, constrained enough to remain interpretable.

(4) Weights and calculation
The basis for the fit was a basic Weibull distribution function of the form 1-exp(v[1]*x^v[2]). This function is being fitted to the data via a numerical OLS approach that introduces the market sizes as weights. These weights have turned out to be necessary in cases where countries have highly fluctuating market sizes. That is because BEV have proven to be much more stable in their absolute number of registrations than other fuel types, meaning that if in a certain month, there are much fewer newly registered cars, then this affects BEV much less than Petrol, Diesel or even Hybrids. As an aftereffect this means that with a relatively constant absolute number compared to this now shrunken total number, BEV share would produce an outlier that pulls the BEV share upwards more than it should. Weights correct this and make cases like Ireland much more stable. Convergence criteria are set to maxit = 100000 and reltol=10^-30.



5. What the parameters mean (conceptually)
v1 — transition intensity
Controls how aggressively the market moves once adoption starts.
Intuitively: How sharp is the flip from “niche” to “mainstream”?

v2 — transition shape
Controls where acceleration happens.
Intuitively: Does the market ramp up early, or only after a long hesitation phase?

t0 — time shift
It's a horizontal shift so the curve aligns nicely with calendar time. Ignore this one.


6. Most important model assumption
Two hard assumptions are imposed:
- The transition starts at 0% (or 100% for ICE)
- The transition asymptotically ends at 100% (or 0% for ICE)

Technically these are assumptions. However, would we not assume this we'd introduce either less stable models or subjective models (which goes against what I want this to be).
However, both the 0% and the 100% seem to fit reality quite well. Would they not fit reality, models would eventually output nonsense. If real data contradicts these bounds, the model stops fitting and this breakdown is visible.
So far, mature markets (e.g. Norway or Denmark) genuinely converge towards 100%, not 70% or 80%.


7. ICE and PHEV curves
Since the BEV curves fits so well, I have decided to redo an analogue curve for newly registered ICE cars as well. I struggled with the definition of what to call an ICE in this definition, but ended up at the split BEV & PHEV & ICE, meaning ICE in this categorisation includes HEV, H2, GAS, PETROL, DIESEL, ETHANOL and all other fuel types that are not BEV or PHEV (this also means that EREV are treated as PHEV). I could have chosen to define a Hybrid category for PHEV+HEV and sometimes I do even use it due to lack of more granular data (Türkiye), but this BEV-PHEV-ICE split seems like the one that yields the best insight on these trajectory curves. As a result of producing ICE and BEV curves, the leftover PHEV part should now not only make up the remaining percentage points to get to 100% if summed up, but if models behave, should also fit against real world data, so can be used as a sort of verification.
Thus the graph showing 3 curves is produced.


8. This is a statement about TODAY
This deserves to be absolutely unambiguous:

This is not a forecast.
This is not a prediction.
This is not a statement about the future.

The curve represents a best-fit description of the transition as of today. If future data changes the trajectory also changes, which is why I update it regularly.
The parameters change, the curve changes, the derived thresholds change.

Think of it as:
“Given everything we know right now,
what would the transition look like if things simply continued?”

Not:
“What will happen?”


9. Early-stage instability
Uncertainty is not only a function of data quantity. It is also a function of where a market sits on the curve. Early-stage markets (low BEV share) are inherently volatile. Small absolute changes produce large parameter swings. This stabilizes naturally as the transition progresses. This stabilization is visible in the transition-time curves. Stability is also greater in bigger markets.

---

## 🌍 License & Usage

Charts and model outputs may be shared freely with attribution to **@LeRaffl**.
Original data sources are subject to their respective licenses.
Feel free to use these outputs for your own purposes, but please link me to whatever you do.

---

