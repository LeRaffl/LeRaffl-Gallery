# 08 · Deploy and Ops

Operational runbook. How to deploy, how to trigger, how to debug. Commands you can copy.

## Quick reference

| Task | Command | Section |
|---|---|---|
| Deploy worker code change | Push to `master` (Workers Builds auto-deploys); fallback `cd worker && npx wrangler@latest deploy` | [§ 8.1](#81-deploy-the-worker) |
| Re-render one country | Actions tab → "Render country charts" → Run workflow | [§ 8.2](#82-trigger-a-country-render) |
| Add a new country | Extract CSV, push, run render | [§ 8.3](#83-add-a-new-country) |
| Rotate the Worker's PAT | Edit PAT in GitHub, re-`wrangler secret put` (or re-set in Workers Builds env) | [§ 8.4](#84-rotate-secrets) |
| Merge a public submission | Review PR diff, click Merge, then [§ 8.2](#82-trigger-a-country-render) | [§ 8.5](#85-process-a-submission-pr) |
| Hide spam feedback | Add `hidden` label to the issue | [§ 8.6](#86-moderate-feedback) |
| Bulk-render all countries | Loop through countries calling [§ 8.2](#82-trigger-a-country-render) one at a time | [§ 8.7](#87-bulk-rerender) |
| Debug Worker errors | Cloudflare dashboard → Workers → Tail logs | [§ 8.8](#88-debugging) |
| Indonesia table shows ~5y 20→80 again | Frontend + backend recovery both already in place — see § "Indonesia v1=0 corruption" | [§ 8.8](#indonesia-v10-corruption) |
| Manually snapshot Builder curves | Actions tab → "Snapshot Builder curves" → Run workflow | [§ 8.9](#89-snapshot-builder-curves) |
| Look up when a country fetcher next runs | Cron schedule overview | [§ 8.11](#811-cron-schedule-overview) |

## 8.1 Deploy the Worker

### Default path — Workers Builds (auto-deploy from Git)

The Cloudflare Worker is linked to this repository via **Workers Builds** (Cloudflare → Workers → `leraffl-gallery-feedback` → Settings → Builds → "Connect to Git"). Any push to `master` that touches the `worker/` subdirectory triggers a Cloudflare build that runs `npx wrangler deploy` from the repo root (build config: `Root directory = worker`, `Deploy command = npx wrangler deploy`, `Branch = master`). No local CLI step needed for the day-to-day case.

Required when **any** of these change:
- `worker/index.js`
- `worker/wrangler.toml` (compat date, KV bindings, account_id, vars)

**What you should see** in Cloudflare dashboard → Workers & Pages → `leraffl-gallery-feedback` → Builds:
- A "Building" row appears within ~30 s of the push
- Logs show `npx wrangler deploy` running, KV/var bindings being read, upload + deploy completing in ~10–15 s
- Final state: `Success`, with the deployed version pinned to the commit SHA

If the build fails:
- **Auth-side**: re-link the GitHub integration (the dashboard surfaces a "Reconnect" button); see the [Cloudflare Workers Builds docs](https://developers.cloudflare.com/workers/ci-cd/builds/) for the OAuth flow.
- **Build-side**: same diagnostics as a local `wrangler deploy` failure (compat date, KV binding name mismatch, missing secret).
- **Fallback**: deploy manually from the maintainer's Mac with the command below — Workers Builds is convenience, not load-bearing.

### Fallback path — manual deploy from the maintainer's Mac

Still required if Workers Builds is unavailable (CI outage, GitHub integration revoked, hotfix-out-of-band):

```bash
cd /Users/leraffl/Projects/GitHub/LeRaffl-Gallery/worker
npx wrangler@latest deploy
```

**What you should see:**
```
Total Upload: ~20 KiB / gzip: ~6 KiB
Your Worker has access to the following bindings:
  env.RATE_KV       (...)        KV Namespace
  env.GITHUB_OWNER  ("leraffl")  Environment Variable
  env.GITHUB_REPO   ("leraffl-gallery")  Environment Variable
Uploaded leraffl-gallery-feedback (~10 sec)
Deployed leraffl-gallery-feedback triggers (~5 sec)
  https://leraffl-gallery-feedback.xgwvfz7nrb.workers.dev
```

If wrangler prompts about a config diff between local and remote, **say no** and reconcile the diff first (usually means someone tweaked the worker via the Cloudflare dashboard; pull those settings into `wrangler.toml`).

> **Secrets are not auto-deployed.** Workers Builds only ships the code + `wrangler.toml`. The `GITHUB_TOKEN` secret lives in the Worker's runtime environment (set out-of-band via `wrangler secret put` or the dashboard) and is **not** read from the repository. See § 8.4 to rotate.

## 8.2 Trigger a country render

Required after:
- Merging a public submission PR
- Pushing new data via local R / direct CSV edit
- Any change to `R/*.R` that affects rendered output

Steps:
1. Open <https://github.com/LeRaffl/LeRaffl-Gallery/actions/workflows/render-country.yml>
2. Click "Run workflow" (top-right)
3. Pick branch `master`
4. Fill `country` (e.g. `Germany`) and `variant` (default `Whole`)
5. Click "Run workflow"

The action takes 30–120 s and commits four PNGs + params/weights row update + posts files + `bands/<slug>.json` (uncertainty bands for the frontend, a few seconds of the run; [44](44-uncertainty-bands.md)). It then dispatches the Build-manifest action explicitly, because workflow commits made with `GITHUB_TOKEN` do not fan out into another push-triggered workflow. GitHub Pages auto-deploys from `master` after each generated commit (Pages-from-branch — there is no separate Pages workflow).

**You can also trigger via gh CLI:**
```bash
gh workflow run render-country.yml -f country=Germany -f variant=Whole
gh run watch  # follow the latest run
```

## 8.3 Add a new country

**The complete checklist is [42-adding-a-country.md](42-adding-a-country.md)** —
eleven phases from the first probe to the first render, each step naming the
file it touches. `scripts/check_country_integration.py` verifies the result
(CI: `check-country-integration.yml` on every PR). The steps people forget,
in short:

1. **Builder groups** — add the country to its region group in *both*
   `BUILDER_GROUPS` (`index.html`) and `GROUPS_STATIC`
   (`scripts/snapshot_builder.py`); ask the owner when no group fits.
2. **History** — dispatch `snapshot-builder.yml` on the PR branch with
   `backtest_only = true`, so the country is fitted into every past month and
   the Time-lapse series and GIFs include it before merge (§ 8.9).
3. **Flag file name** — `assets/flags/<slug>.png` with the slug exactly as
   `R/render_country.R` builds it (`hong_kong`, not `hongkong`).
4. **Schedule labels** — `FLAG`/`LABEL` in `R/render_schedule.R`, keyed by the
   workflow slug (`fetch-hong-kong.yml` → `hong-kong`).
5. After merge, § 8.2 to render.

## 8.11 Cron schedule overview

Every scheduled GitHub Action in the repo, in one place. All times are UTC (GitHub Actions crons don't honour timezones). All schedules are best-effort — GitHub may delay cron runs by 5–15 minutes under load — and every workflow also exposes a `workflow_dispatch` trigger for manual runs from the Actions UI.

### Country data-fetch actions

These are the workflows that pull the previous month's data from each national source and commit the resulting CSV change. Each one self-throttles by re-reading the latest period from the target CSV before any HTTP work, so most invocations on empty days are free (no commit, no render trigger, no downstream fan-out).

| Workflow | Human reading | Source | Country / variant scope | Self-throttle |
|---|---|---|---|---|
| [`fetch-acea.yml`](../../.github/workflows/fetch-acea.yml) | 08:40 UTC, 16th → EOM | ACEA monthly PDF press release | Always-list (16): Belgium, Bulgaria, Croatia, Cyprus, Czechia, Estonia, France, Greece, Hungary, Iceland, Latvia, Lithuania, Malta, Romania, Slovakia, Slovenia. Conditional-list: Norway, Switzerland — written only if the existing source is exactly `ACEA` | `max(period)` across always-list ≥ target |
| [`fetch-acea-cv.yml`](../../.github/workflows/fetch-acea-cv.yml) | 10:15 UTC — 18th-31st Jan (FY), 15th-30th Apr (Q1), 20th Jul-10th Aug (H1), 20th-31st Oct (Q1-Q3) | ACEA's quarterly-cumulative Commercial Vehicle PDF press releases ([38-source-acea-cv.md](38-source-acea-cv.md)) | `Vans` + `HDV` + `Buses` for a maintainer-curated 21-country roster (not fetch-acea.yml's list — see 38-source-acea-cv.md § 1a); conditional per (country, variant, period) row — skips any file whose existing source isn't `ACEA`. Reconstructs genuine Q1/Q2/Q3/Q4 rows from ACEA's cumulative checkpoints, yearly fallback only with no quarterly baseline yet | sentinel file (`already_have_checkpoint()`) already has this checkpoint's quarter (or a yearly row) recorded |
| [`fetch-albania.yml`](../../.github/workflows/fetch-albania.yml) | 07:00 UTC, 10th → 28th | DPSHTRR Open Data via its public Looker Studio report (headless Chromium) | `Whole` + `HDV` + `Buses` + `2-Wheelers` — first registrations, new **and** imported used | change-gated commit |
| [`fetch-argentina.yml`](../../.github/workflows/fetch-argentina.yml) | 09:15 & 21:15 UTC, 8th → 25th | DNRPA «Inscripciones iniciales» open microdata (`datos.jus.gob.ar` CKAN; yearly zips + newest-month CSV) — powertrain classified from the model designation ([39](39-source-argentina.md)) | `Whole` (≈M1) + `Private` + `Industry` (rendered) + `Pickups` (data only, never rendered) — one download, every variant | every CSV already has the target month from `DNRPA` → no HTTP |
| [`fetch-austria.yml`](../../.github/workflows/fetch-austria.yml) | 09:25 UTC, 8th → 22nd | Statistik Austria DE2/DE3 `.ods` (via the Cloudflare Worker relay — the source blocks datacenter IPs) | `Whole` + `HDV` + `Vans` | per-variant early-exit |
| [`fetch-brazil.yml`](../../.github/workflows/fetch-brazil.yml) | 08:50 UTC, 10th | ANFAVEA Central de Dados (admin-ajax query) | `Whole` (cars + light commercials) | change-gated commit |
| [`fetch-canada.yml`](../../.github/workflows/fetch-canada.yml) | 06:40 UTC, 8th → 20th of Mar/Jun/Sep/Dec | StatCan WDS cube 20-10-0025 | `Whole` (EU M1) + `Pickups` + `Vans` | change-gated commit (always re-fetches latest N quarters) |
| [`fetch-chile.yml`](../../.github/workflows/fetch-chile.yml) | 08:20 UTC, 14th → EOM | ANAC (Mercado Automotor + Cero y Bajas Emisiones PDFs) | `Whole` | `latest_period(Chile.csv) ≥ target` |
| [`fetch-china.yml`](../../.github/workflows/fetch-china.yml) | 11:00 UTC, 1st → EOM | CPCA monthly market analysis (article + OCR of the NEV slide) | `Whole` (retail) + `Wholesale` to a separate CSV | `latest_period` of both CSVs ≥ target |
| [`fetch-colombia.yml`](../../.github/workflows/fetch-colombia.yml) | 07:30 UTC, 5th → 25th | ANDI/FENALCO Boletín PDF (datos RUNT) — page listing, else the month's `/Uploads/` URL rebuilt (see [18](18-source-colombia.md)) | `Whole` — single combined Hybrid bucket | `latest_period(Colombia.csv) ≥ target` |
| [`fetch-denmark.yml`](../../.github/workflows/fetch-denmark.yml) | 05:15 UTC, 1st → 15th | Statbank BIL53 (`api.statbank.dk`) | `Whole` + `Private` + `Industry` + `HDV` + `Vans` | per-variant diff vs CSV |
| [`fetch-finland.yml`](../../.github/workflows/fetch-finland.yml) | 04:40 UTC, 1st → 15th | StatFin 121d (`pxdata.stat.fi` PxWeb) | `Whole` + `Private` + `Industry` + `HDV` + `Vans` + `Buses` | per-variant diff vs CSV |
| [`fetch-france.yml`](../../.github/workflows/fetch-france.yml) | 07:40 UTC, 18th → EOM | SDES motorisations série VP workbook (média link resolved from the landing page; [36](36-source-france.md)) | `Whole` | change-gated commit — no new row, no diff, no render |
| [`fetch-hong-kong.yml`](../../.github/workflows/fetch-hong-kong.yml) | 03:20 & 11:20 UTC, daily | Transport Department «Particulars of first registered vehicles» (`data.gov.hk` CKAN; one CSV per month, uploaded between the 13th and 28th of M+1) — fuel from the record, plug-ins from the model designation, cross-checked against TD table 4.1(e) ([41](41-source-hong-kong.md)) | `Whole` + `Used` + `Vans` — one set of files, every variant | newest portal month already in every CSV from TD → one JSON request, no download |
| [`fetch-indonesia.yml`](../../.github/workflows/fetch-indonesia.yml) | 09:35 UTC, 10th → EOM | GAIKINDO wholesales PDF (ProjectSend portal, client login) | `Whole` (auto-render) + `Pickups` + `HDV` + `Buses` (fetch-only) | newest portal file title already covered → no-op before download |
| [`fetch-ireland.yml`](../../.github/workflows/fetch-ireland.yml) | 04:00 & 13:00 UTC, 1st → 5th | SIMI motorstats (`stats.simi.ie`, Inertia SPA) | `Whole` + `Vans` + `HDV` + `Buses` | per-variant diff vs CSV |
| [`fetch-israel.yml`](../../.github/workflows/fetch-israel.yml) | 08:00 UTC, 10th → 20th | MoT vehicle registry on `data.gov.il` (CKAN datastore snapshot) + model-catalogue join for HEV/PHEV ([34](34-source-israel.md)) | `Whole` + `Vans` | early-exit once the previous month is present; real runs re-count the last 3 months |
| [`fetch-italy.yml`](../../.github/workflows/fetch-italy.yml) | 06:00/10:00/14:00/18:00 UTC, 1st → 3rd (passenger); 10:00/14:00/18:00 UTC, 13th → 16th (vans) | UNRAE «struttura del mercato» PDF; LCV from the separate Comunicato Stampa | `Whole` + `Rental` + `NonRental` + `Vans` | per-variant diff vs CSV |
| [`fetch-japan.yml`](../../.github/workflows/fetch-japan.yml) | 08:00 UTC, 1st → EOM | JADA monthly registrations file (XLSX preferred, PDF fallback) | `Whole` — 登録車 only, kei cars excluded | `latest_period(Japan.csv) ≥ target` |
| [`fetch-luxembourg.yml`](../../.github/workflows/fetch-luxembourg.yml) | 06:45 UTC, 1st → 15th | STATEC SDMX 2.1, dataflow DF_D6122 (`lustat.statec.lu`) | `Whole` + `Vans` + `HDV` | per-variant early-exit |
| [`fetch-malaysia.yml`](../../.github/workflows/fetch-malaysia.yml) | 07:00 UTC, 15th → EOM | data.gov.my cars dataset (Parquet) + `market/malaysia_top.json` | `Whole` | change-gated commit; render only if `data/Malaysia.csv` changed |
| [`fetch-nepal.yml`](../../.github/workflows/fetch-nepal.yml) | 07:50 UTC, daily | Department of Customs FTS XLSX (`customs.gov.np`) — HS 8703 **imports**, not registrations | `Whole` + `3-Wheelers` | cheap-skip when the CSV already covers every published workbook |
| [`fetch-netherlands.yml`](../../.github/workflows/fetch-netherlands.yml) | 06:30 UTC, 1st → 15th | RDW via Swing BI (`duurzamemobiliteit.databank.nl`, Deno Deploy relay) | `Whole` + `Used` + `HDV` | per-variant diff vs CSV |
| [`fetch-new-zealand.yml`](../../.github/workflows/fetch-new-zealand.yml) | **disabled** — cron commented out 2026-06 (Imperva); `workflow_dispatch` only, data entered by hand | transport.govt.nz `/inner` (CKAN fallback) | `Whole` | n/a |
| [`fetch-poland.yml`](../../.github/workflows/fetch-poland.yml) | 09:30 & 13:30 UTC, 6th → 10th | PZPM eRegistrations XLSX (from the CEP register) | `Whole` + `Vans` + `HDV` + `Buses` | per-variant early-exit |
| [`fetch-portugal.yml`](../../.github/workflows/fetch-portugal.yml) | 17:30 & 20:30 UTC, 1st → 5th | ACAP via motordata.pt (`chartdata_novo.php`) | `Whole` (auto-render) + `Vans` + `HDV` + `Buses` (fetch-only, thin history) | per-variant diff vs CSV |
| [`fetch-singapore.yml`](../../.github/workflows/fetch-singapore.yml) | 08:00 UTC, 15th → EOM | LTA Monthly Vehicle Statistics, file M03 (PDF) | `Whole` | change-gated commit (rolling ~6-month window) |
| [`fetch-south-korea.yml`](../../.github/workflows/fetch-south-korea.yml) | 03:35 & 09:35 UTC, 12th → 25th | MOTIR «자동차산업 동향» press-release PDF ([43](43-source-south-korea.md)) | `Whole` | newest release's month in the CSV and its previous month unchanged → no write |
| [`fetch-spain.yml`](../../.github/workflows/fetch-spain.yml) | 06:30 UTC, 1st → 16th | DGT matriculaciones microdata (fixed-width, monthly zip) + `market/spain_top.json` | `Whole` + `Rental` + `NonRental` + `Used` + `Vans` + `HDV` + `Buses` + `2-Wheelers` — one download, every variant | per-variant diff vs CSV |
| [`fetch-sweden.yml`](../../.github/workflows/fetch-sweden.yml) | 05:50 UTC, 1st → 15th | SCB PxWeb `PersBilarDrivMedel` (`api.scb.se`) | `Whole` | `latest_period(Sweden.csv) ≥ target` |
| [`fetch-thailand.yml`](../../.github/workflows/fetch-thailand.yml) | 04:40 UTC, 1st → 20th | TAI / AIU member portal JSON API (`taiapi.thaiauto.or.th:3000`, cookie login) | `Whole` (Passenger Car + Pickup Truck) + `HDV` + `Buses` + `3-Wheelers` | per-variant diff vs CSV |
| [`fetch-turkey.yml`](../../.github/workflows/fetch-turkey.yml) | 08:30 UTC, 15th → EOM | TÜİK «Motorlu Kara Taşıtları» bulletin (id auto-discovered; fuel table OCR'd) | `Whole` — otomobil only, combined Hybrid bucket | `latest_period(Türkiye.csv) ≥ target` |
| [`fetch-ukraine.yml`](../../.github/workflows/fetch-ukraine.yml) | 08:40 & 20:40 UTC, 1st → 15th | MIA open vehicle register (`data.gov.ua` CKAN; yearly zips, current year re-uploaded ~the 1st) — fuel from the record, new/used from operation codes ([40](40-source-ukraine.md)) | `Whole` + `Private` + `Industry` + `Used` + `Vans` — one download, every variant; combined Hybrid bucket | every CSV already has the target month from `MIA HSC (data.gov.ua)` → no HTTP |
| [`fetch-uruguay.yml`](../../.github/workflows/fetch-uruguay.yml) | 08:10 UTC, 1st → EOM | ACAU «Compilado YYYY» xlsx | `Whole` (AUTOS + SUV) + `Vans` + `HDV` + `Buses` | `latest_period` per variant ≥ target |
| [`fetch-usa.yml`](../../.github/workflows/fetch-usa.yml) | 10:30 UTC, 10th → EOM | ANL «Total Sales for Website» PDF | `Whole` — trailing 3-month window, re-written each run to absorb ANL revisions | change-detection on the window |

Notes on the schedule shape:
- **The 08:00 UTC pile-up was deliberately broken up.** It used to be the
  crowded slot (Brazil, Chile, Türkiye, Uruguay and ACEA all fired at `0 8`);
  those were staggered onto their own minutes — Uruguay `:10`, Chile `:20`,
  Türkiye `:30`, ACEA `:40`, Brazil `:50` — so a stall in one no longer lands
  on top of the others. Japan, Singapore and Israel are the only ones still
  on the hour. They never conflicted (each writes a different CSV, and ACEA's render
  fan-out is serialised by `max-parallel: 1`), but a CI outage at exactly
  08:00 used to take all of them out together.
- **The early band clears that window from below:** Hong Kong 03:20 & 11:20
  (HK office hours — TD's upload day is unpredictable, so it polls daily),
  Ireland 04:00 & 13:00
  (SIMI publishes very early on the 1st), Thailand 04:40, Finland 04:40,
  Denmark 05:15, Sweden 05:50, Italy from 06:00, Netherlands 06:30, Spain
  06:30, Canada 06:40, Luxembourg 06:45, Albania and Malaysia 07:00, Colombia
  07:30, France 07:40, Nepal 07:50; South Korea 03:35 & 09:35 (MOTIR releases
  at 11:00 KST).
- **And from above:** Ukraine 08:40 & 20:40 (1st–15th only — ACEA's 08:40
  slot starts on the 16th, so they never share a day), Argentina 09:15 & 21:15, Austria 09:25, Poland 09:30
  & 13:30, Indonesia 09:35, USA 10:30 (off the 10th's Brazil window), China
  11:00, Portugal 17:30 & 20:30 — the evening slots, because ACAP publishes
  from ~17:00 Lisbon on the 1st and DNRPA uploads in the Buenos Aires
  afternoon (~17:30 UTC).
- **Day-1 starters** (Japan, Uruguay, China, Netherlands, Denmark, Finland,
  Sweden, Spain, Thailand, Luxembourg, Ukraine; Ireland, Italy and Portugal from the
  1st too) rely entirely on the self-throttle to keep the empty days free —
  they fire many times a month but only do real HTTP on the days the source
  publishes.
- **Date-window starters** (Poland 6+, Argentina 8+, USA 10+, Indonesia 10+, Albania 10+,
  Israel 10–20, Chile 14+, South Korea 12–25, Singapore 15+, Malaysia 15+, Türkiye 15+, ACEA 16+, France 18+, and the
  matching upper cut-offs) reflect the earliest plausible publication day for
  the previous month from that source. Cutting off the empty days saves a
  handful of self-throttle checks; it doesn't change correctness.
- **Canada is the odd one out:** its cube is quarterly, so the workflow only
  runs in March, June, September and December (days 8–20).
- **Nepal and Hong Kong are the only unbounded daily crons** (`50 7 * * *`,
  `20 3,11 * * *`) — Nepali fiscal months don't line up with Gregorian ones,
  and TD uploads Hong Kong's month anywhere from the 13th to the 28th (and
  could slip past month end), so neither has a useful day window. Both
  self-throttle before downloading anything.
- **New Zealand has no cron at all** since 2026-06; both upstream endpoints
  are behind Imperva and months are entered by hand.

Country coverage of automated fetchers: **see also**
[02-components.md](02-components.md#27-fetch-actions-overview). Countries with
a CSV but no automated fetcher — maintained via the legacy local R pipeline or
public-submit PRs — are **Australia, Georgia, Germany and the UK**, plus **India** (no committed CSV at all) and **New Zealand** (fetcher
present, cron disabled).

### Infrastructure actions

| Workflow | Cron expression | Human reading | Purpose |
|---|---|---|---|
| [`build-manifest.yml`](../../.github/workflows/build-manifest.yml) | `17 3 * * *` | Daily 03:17 UTC | Self-healing fallback: rescans `images/` and rewrites `manifest.json` if anything drifted (also triggered on every push to `images/**` and on explicit dispatch from `render-country.yml`). |
| [`snapshot-builder.yml`](../../.github/workflows/snapshot-builder.yml) | `0 9 25 * *` | Monthly 25th 09:00 UTC | Dumps the aggregated Builder curves into `builder_history/<date>.csv`, **and** extends `backtest/` by the new month, then runs `scripts/build_backtest_series.py` and `scripts/build_builder_gif.py`, so the new frame reaches both the Time-lapse panel and its downloadable animation in the same commit. The 25th sits after the bulk of in-month country fetches has settled (Brazil 10th, USA 10+, ACEA 16+, ANAC/Türkiye 14–18, JADA varies) and before the next month's fetches start. |
| [`render-country.yml`](../../.github/workflows/render-country.yml) | (no cron) | On `workflow_dispatch` or `workflow_call` only | Manual or fan-out trigger from a fetch workflow — never auto-runs on its own clock. |
| [`build-series.yml`](../../.github/workflows/build-series.yml) | (no cron) | On push to `data/**` (one path filter catches all 29 fetchers, manual commits and merged submission PRs) | Regenerates `series/index.json` + `series/*.json` and the generated data-quality checklist. **Since the 2026-09 redesign this output is on the page's read path** — Raw Data *and the landing hero chart* fetch it at runtime (see [Flow F](05-flows.md#flow-f--gallery-read)), so a failure here degrades the live page rather than just aging a table. Does not trigger on `series/**`, so its own commit cannot retrigger it. |
| [`preview-render.yml`](../../.github/workflows/preview-render.yml) | (no cron) | On pull requests touching `R/**` (and manual dispatch) | Renders a fixed set of series with the PR's `R/` and the base branch's `R/` from the same data; uploads the side-by-side `render-preview` artifact and edits one PR comment. Read-only: commits nothing ([02 § 2.17](02-components.md#217-render-preview-githubworkflowspreview-renderyml-scriptsbuild_render_previewpy)). |
| [`check-country-integration.yml`](../../.github/workflows/check-country-integration.yml) | (no cron) | On pull requests touching data, `index.html`, R, flags, docs, `backtest/params` or a fetch workflow | Runs `scripts/check_country_integration.py`: fails a PR that leaves a country half-wired ([42](42-adding-a-country.md)). |
| [`build-source-pages.yml`](../../.github/workflows/build-source-pages.yml) | `37 4 * * *` | Daily 04:37 UTC (+ on push to a source doc, the stub registry, a generator, `index.html`, `params.csv`) | Regenerates `sources/*.html` and `assets/theme.css`, plus the schedule JSON. On a **pull request** it only validates: `build_source_pages.py --check` for the content model and `build_theme.py --check` for palette drift — a PR that changes `index.html`'s `:root` without regenerating the stylesheet fails here. |

### Reading a cron expression quickly

GitHub uses the standard 5-field cron format `minute hour day-of-month month day-of-week`. Two patterns dominate this repo:

- `0 8 D-31 * *` — "every day from the Dth to the end of the month at 08:00 UTC". Used as a "earliest plausible publication day onward" pattern.
- `0 H DD * *` — "the DDth of each month at HH:00 UTC". Used for sources with a known fixed publication day (Brazil).

If you need the *next* fire time for one of these, the easiest sanity check is the Actions tab — each workflow's run history shows the previous fire times, and from there the next one is +1 day (for daily windows) or +1 month (for monthly fixed-day crons).

---

## 8.10 Restoring from disaster

| Disaster | Recovery |
|---|---|
| Repo deleted / corrupted | Restore from any clone — every artefact is in Git |
| Cloudflare account lost | Re-create Worker via wrangler, re-set secret, re-bind KV, re-link Workers Builds to the repo (Cloudflare → Workers → Settings → Builds → "Connect to Git"). The KV's rate-limit data is lost but uncritical. |
| Workers Builds integration revoked | Manual deploy via `cd worker && npx wrangler@latest deploy` keeps the Worker fresh; re-link via the dashboard at convenience. The fallback is identical to the pre-integration deploy path, so no functional outage. |
| Maintainer's Mac lost | Clone the repo on a new machine, `wrangler login`, `gitcreds_set` for git OAuth, done. The local R scripts (`bev_share_*.R`) are off-repo and need to be restored from iCloud or a backup; if not, the in-repo `R/` pipeline alone is sufficient. Worker pushes still deploy via Workers Builds without any Mac-side setup. |
| GitHub down | Read-side serves from GitHub Pages CDN, may stay up briefly. Submit/feedback writes fail — Worker returns 502; page shows error. Workers Builds is also paused (no source to pull). Wait for GitHub. |

## See also

- [02-components.md](02-components.md) — what each component does
- [04-interfaces.md](04-interfaces.md) — request/response shapes for the Worker
- [07-secrets-trust.md](07-secrets-trust.md) — what each token can do
