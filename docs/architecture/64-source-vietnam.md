---
country: Vietnam
slug: vietnam
method: pdf
summary: New passenger-car sales in Vietnam (as close to EU category M1 as the sources
  allow), built from three published sources — the industry association VAMA (its
  members' sales plus its estimate of non-member imports), VinFast's monthly delivery
  release and TC Group's monthly Hyundai sales. Trucks, pick-ups, buses and special
  vehicles are taken out. Sales, not police registrations.
source_name: VAMA monthly sales report + VinFast delivery release + TC Group (Hyundai)
source_url: http://vama.org.vn/en/sales-report.html
source_links:
- label: VAMA — monthly sales report, cover letter (ENG, PDF)
  url: http://vama.org.vn/Data/upload/files/2026/BCBH/Cover%20Letter%20Sales%20report%20-%20September%202026%20(ENG).pdf
  note: total industry (members + non-member imports) split into passenger cars, commercial and special-purpose vehicles; the members' passenger-car, BEV and Hybrid subtotals
- label: VAMA — monthly sales report, Detail sheet (PDF)
  url: http://vama.org.vn/Data/upload/files/2026/BCBH/VAMA%20sales%20report%20September%202026%20-%20%20Detail.pdf
  note: members only — one row per brand × model with VAMA's segment (Sedan, SUV, … Hybrid, BEV), month and year to date
- label: VinFast — monthly delivery release (vingroup.net, Vietnamese)
  url: https://www.vingroup.net/vi/tin-tuc-su-kien/bai-viet/9096/vinfast-ban-giao-23624-o-to-dien-tai-viet-nam-trong-thang-9
  note: domestic deliveries of the month and the year to date, top models; the same figures as VinFast's Form 6-K to the SEC
- label: VinFast — Form 6-K filings (SEC EDGAR, CIK 1913510)
  url: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=1913510&type=6-K
  note: the history 2024-10 … 2026-09 was read from these; sec.gov refuses GitHub's runners, so the monthly fetch reads vingroup.net
- label: TC Group — Hyundai monthly sales
  url: https://thanhcong.vn/tin-tuc/tc-group-thong-bao-doanh-so-ban-hang-xe-hyundai-thang-9-2026.html
  note: one row per model with a CKD/CBU flag, a commercial-vehicle row ("XE THƯƠNG MẠI"), the total; this and the previous month
- label: Traffic Police (CSGT) — new registrations, year 2025
  url: https://vov.vn/o-to-xe-may/o-to/gan-625000-o-to-dang-ky-moi-nam-2025-post1257567.vov
  note: 624,300 cars registered 15 Dec 2024 – 14 Dec 2025, incl. 122,235 trucks; cross-check only
- label: Traffic Police (CSGT) — first nine months of 2026
  url: https://tuoitre.vn/ca-nuoc-co-hon-33-trieu-xe-duoc-dang-ky-moi-trong-9-thang-dau-nam-2026-100260924115759761.htm
  note: 513,679 cars; the half-year report is in VnExpress (https://vnexpress.net/hon-2-1-trieu-oto-xe-may-dang-ky-moi-nua-dau-nam-5094742.html)
underlying: VAMA members' sales (dealer reports) and VAMA's estimate of non-member imports; VinFast delivery records; Hyundai Thành Công sales records
auth: none
cadence: twice daily on the 8th–28th (04:05 and 10:05 UTC) — VinFast and TC Group publish around the 10th, VAMA in the middle of the month; a month is written once all three are in
variants:
- Whole
variant_notes:
  Whole: "Passenger cars ≈ M1: VAMA's total-industry passenger cars (members + non-member imports) + every VinFast delivery + Hyundai minus TC's commercial row. Pick-ups, vans, trucks, buses and special vehicles are left out. The all-vehicle total the media quote is rebuilt from the same inputs and compared every month (\"Why other figures differ\")."
hev_split: true
hev_note: "HEV = full hybrids, per model from VAMA's Detail sheet: VAMA's Hybrid segment minus the mild hybrids Suzuki XL7 Hybrid and Ertiga Hybrid (→ MHEV, counted as ICE like everywhere in the gallery) plus full hybrids VAMA files under a body style (Toyota Land Cruiser Hybrid, SUV). Kia's \"New Sorento HEV/PHEV\" is one line and counts as HEV. No PHEV is reported. Hyundai has no fuel split (counted as ICE); non-member imports have none either and are their own column OTHERS (shown as Other)."
scope_note: "Passenger cars ≈ M1, sales and deliveries (VAMA's members' sales, VinFast deliveries, Hyundai sales), not registrations — the charts say \"new sales\". Not covered: brands that sell without reporting (VAMA estimates only the imported ones), personal and used imports. VinFast's EC Van stays in (named only in some months). Police registrations differ by timing, period and definition; see \"Why other figures differ\"."
backfill: 2024-09 onwards — the first month VinFast's figure, VAMA's cover letter and TC Group's table can all be read (earlier VinFast figures are quarterly)
caveats:
- "VinFast reports deliveries, which include handovers to dealers (Thanh Niên: \"bàn giao đến tay khách hàng cũng như các đại lý\"); this is one reason the BEV share here is well above registration-based figures (2025: 28.9 % here vs 17.8 % in police registrations)."
- "VinFast's monthly figures are preliminary and are sometimes revised through the year-to-date figure: the August 2026 release's year to date (154,073) is 3,785 below the July one plus August. The month before is then rewritten from the year to date (July 2026: 17,996, not 21,781); see \"How it works\"."
- "VinFast's figures before 2025-04 are rounded (\"more than 9,300\"); VinFast and Hyundai sometimes include a few dozen exported or commercial units."
- "Non-member imports (5,044 cars in 2026-09, 9.9 %) are an association estimate without brand or fuel split: they are the column OTHERS (shown as Other in the fuel breakdown), never ICE. In the three-curve BEV / PHEV / ICE view every non-plug-in column falls in the ICE band, as for every country. The BYD and other imported EVs and plug-ins inside that pool are therefore not in BEV/PHEV. Whether the estimate already contains some of Hyundai's imported (CBU) models cannot be verified (at most 0.5–2.7 % of the total)."
- "Lexus and BMW/MINI are VAMA members whose model figures VAMA publishes in separate sheets; they count in the totals and in ICE, but not in the brand/model tables."
- "VAMA has twice uploaded January's Detail sheet under another month (May 2025, February 2026). Those months' mild hybrids and model figures are rebuilt from the neighbouring sheets' year-to-date columns; the totals come from the cover letter and are unaffected."
- "Reference figures (media totals, police half-year and year) are entered by hand in checks/vietnam_reference.csv; a scheduled workflow keeps a GitHub issue open while one is due."
notes:
- "What goes where. BEV = every VinFast delivery (VinFast has built only electric vehicles since 2022 and reports \"electric vehicles\") plus VAMA's BEV segment (Ford Mustang Mach-E) and BEVs VAMA files under a body style. HEV = the full-hybrid models of VAMA's Detail sheet. MHEV = Suzuki XL7 Hybrid and Ertiga Hybrid. ICE = all other VAMA member passenger cars plus every Hyundai passenger model. Other = VAMA's estimate of non-member imported passenger cars. PHEV stays empty. September 2026: BEV 23,627 (46.3 %), HEV 2,171 (4.3 %), MHEV 113, ICE 20,058, Other 5,044 — Whole 51,013."
- "How the total is built. The police publish registrations only as occasional aggregates, with no monthly fuel or brand split. The national total the media quote each month is VAMA's total industry plus the two big non-members that publish their own numbers, VinFast and Hyundai Thành Công. We take the same documents and check every month that our inputs add up to the published total: from 2024-09 to 2026-09 they did in every one of the 20 months with a published figure, within the media's rounding — except July 2026, where the media used VinFast's first figure (21,781) before its revision."
reconciliation:
- title: "From the media headline to the charted total — September 2026"
  lead: "The figure Vietnamese media print every month (VnEconomy: 62,590 cars) is every vehicle type of VAMA, VinFast and Hyundai. The charts keep the passenger cars."
  rows:
  - cells: ["Published national total (VnEconomy)", "62,590"]
    url: https://vneconomy.vn/automotive/cu-hich-500000-xe-sau-9-thang-quy-mo-thi-truong-o-to-viet-nam-tien-sat-dinh-lich-su.htm
  - ["= VAMA total industry (members + non-member imports)", "35,094"]
  - ["+ VinFast deliveries", "23,624"]
  - ["+ Hyundai (TC Group)", "3,872"]
  - ["− VAMA commercial vehicles (pick-ups, vans, trucks, buses)", "−9,807"]
  - ["− VAMA special-purpose vehicles", "−632"]
  - ["− Hyundai commercial vehicles", "−1,138"]
  - ["= Whole (passenger cars ≈ M1)", "51,013"]
  - ["of which BEV · HEV · MHEV · ICE · Other", "23,627 · 2,171 · 113 · 20,058 · 5,044"]
  note: "BEV = VinFast 23,624 + VAMA BEV 3. ICE = VAMA members' passenger cars 17,440 − the Land Cruiser Hybrid (116, to HEV) + Hyundai passenger 2,734. Other = VAMA passenger cars 24,655 − members' passenger cars, Hybrid and BEV."
checks_file: market/vietnam_checks.json
market_breakdown: market/vietnam_top.json
market_total_word: new
market_powertrain_note: "BEV = VinFast and VAMA members' battery-electric models; HEV = full-hybrid models (Toyota, Honda, Kia Sorento HEV/PHEV, Land Cruiser Hybrid); MHEV = Suzuki XL7 and Ertiga Hybrid. Sales, not registrations: VAMA's members, VinFast's release and TC Group's release. Hyundai and non-member imports carry no fuel split and appear only in the every-powertrain table below."
market_designation_note: "Model names as the sources print them (CKD/CBU and model-year tags dropped). VinFast pools some models (VF 5 + Herio Green, VF 2 + Minio Green) and names only its top models — the rest is unranked. Non-member imports (BYD, Mercedes-Benz, …) are one pooled row: VAMA publishes no brand split for them."
market_breakdown_extra:
- path: market/vietnam_all_top.json
  id: market-all
  heading: Who sells the cars — every powertrain
  note: "Every passenger car of the series by brand and model: VAMA members (Detail sheet), VinFast and Hyundai (their releases), and VAMA's estimate of non-member imports as one row. Lexus and BMW/MINI (separate VAMA sheets) count in the total but are not ranked."
  class_labels:
    ALL: "Every powertrain (Hyundai and the non-member imports have no fuel split)"
processing:
- title: Download
  text:
  - "Three publishers per month. VAMA posts a cover letter (totals) and a Detail sheet (members' models) as PDFs on its sales-report page; VinFast posts a press release on vingroup.net (the same figures it files with the SEC as a Form 6-K); TC Group posts a press release with a Hyundai model table on thanhcong.vn. Each figure is kept with its URL in data/raw/vietnam/components.csv, and the month is written to the chart's CSV only when all three are in."
  decision:
    ask: Are VAMA, VinFast and TC Group all published for the month?
    branches:
    - when: "yes"
      then: read all three and write the month
    - when: one or two missing
      then: keep what arrived in the components file, write no chart row, retry next run
    - when: the cover letter is for another month, or a required figure cannot be read
      then: fail the run — never guess
- title: Build the total
  text:
  - "VAMA's total industry contains its members and its estimate of non-member imports, split into passenger cars (PC), commercial vehicles (CV) and special-purpose vehicles (SPV). VinFast and Hyundai are not VAMA members and are added on top. Whole keeps only passenger cars; each source line is mapped once, by the table below."
  rules_head: [Source line, Whole (M1) · column]
  rules:
  - ["VAMA members, passenger-car block (Sedan, SUV, Cross-over, MPV, Hatchback, Others, Peugeot; Lexus and BMW/MINI)", "yes · ICE"]
  - ["… a hybrid filed under a body style (Toyota Land Cruiser Hybrid)", "yes · HEV"]
  - ["VAMA members, Hybrid block (Toyota, Honda, Kia Sorento HEV/PHEV)", "yes · HEV"]
  - ["… Suzuki XL7 Hybrid, Ertiga Hybrid (12 V mild hybrids)", "yes · MHEV (counted as ICE)"]
  - ["VAMA members, BEV block (Ford Mustang Mach-E)", "yes · BEV"]
  - ["VAMA members, pick-ups, vans, trucks, buses", "no (N1–N3, M2/M3)"]
  - ["VAMA members, special-purpose vehicles", "no"]
  - ["Non-member imports, passenger cars (total-industry PC − members' PC, Hybrid, BEV)", "yes · Other"]
  - ["Non-member imports, CV + SPV", "no"]
  - ["VinFast domestic deliveries (all models)", "yes · BEV"]
  - ["Hyundai passenger models (Grand i10 … Stargazer) and \"Mẫu khác\"", "yes · ICE"]
  - ["Hyundai \"XE THƯƠNG MẠI\" (commercial)", "no"]
  decision:
    ask: Which source is the line from?
    branches:
    - when: VAMA Detail sheet (members)
      then:
        ask: VAMA segment?
        branches:
        - when: BEV
          then: BEV
        - when: Hybrid
          then:
            ask: Suzuki XL7 Hybrid or Ertiga Hybrid?
            branches:
            - when: "yes"
              then: MHEV
            - when: "no"
              then: HEV
        - when: Sedan / SUV / Cross-over / MPV / Hatchback / Others
          then:
            ask: Model name says hybrid, or is a known BEV?
            branches:
            - when: hybrid (Land Cruiser Hybrid)
              then: HEV
            - when: BEV
              then: BEV
            - when: "no"
              then: ICE
        - when: Pick-up / Van / truck / bus / SPV
          then: not in Whole
    - when: VAMA non-member imports
      then:
        ask: Passenger cars or CV/SPV?
        branches:
        - when: passenger cars
          then: Other
          note: BYD and other imported EVs and plug-ins sit here; VAMA gives no fuel split
        - when: CV / SPV
          then: not in Whole
    - when: VinFast release
      then: BEV
    - when: TC Group (Hyundai)
      then:
        ask: Row "XE THƯƠNG MẠI" (commercial)?
        branches:
        - when: "yes"
          then: not in Whole
        - when: no — passenger model or "Mẫu khác"
          then: ICE
          note: TC Group publishes no fuel per model
- title: VAMA's Detail sheet
  text:
  - "The cover letter gives the totals; the Detail sheet only decides which hybrids are mild and which hybrids or BEVs VAMA filed under a body style. VAMA has uploaded another month's sheet twice (May 2025 and February 2026 hold January's figures)."
  decision:
    ask: Does the sheet's header name the month?
    branches:
    - when: "yes"
      then: use it
      note: if its Hybrid lines disagree with the cover letter (April and June 2025), the cover letter wins and the run warns
    - when: no — another month's sheet
      then:
        ask: Is next month's sheet out?
        branches:
        - when: "yes"
          then: "rebuild the month: next month's year to date − next month − the year to date before"
        - when: not yet
          then: write the month with no mild hybrids split out; the next run rebuilds it
- title: VinFast revisions
  text:
  - "VinFast's release gives the month and the year to date. When this month's year to date minus this month is not last month's year to date, VinFast has revised last month."
  decision:
    ask: Does last month's year to date equal this year to date − this month?
    branches:
    - when: "yes"
      then: write the month
    - when: no (same year, both figures exact)
      then: rewrite last month as this year to date − this month − the year to date before it, and note it
      note: 2026-08 release — YTD 154,073 − 20,161 = 133,912; July becomes 133,912 − 115,916 = 17,996 (was 21,781)
- title: Check
  text:
  - "Our inputs are compared with independent figures entered by hand in checks/vietnam_reference.csv; the result is market/vietnam_checks.json, shown below under \"Why other figures differ\"."
  rules_head: [Check, Tolerance]
  rules:
  - ["VAMA total industry = PC + CV + SPV", "exact — the sum wins (2024-11 letter: 40,200 for 44,200)"]
  - ["Our all-vehicle sum vs the national total in the media", "±0.1 % · ±0.5 % if the article rounds (\"hơn / khoảng\")"]
  - ["Year sum vs the media's year total", "±1 %"]
  - ["Our sum vs police registrations (CSGT, 15 Dec → 14 Jun / 14 Dec)", "information only — another measure"]
  - ["Reference figure present (media total of the three newest months from the 20th; police H1 from 1 July, year from 5 January)", "missing → reminder issue; the data are written anyway"]
fetcher: scripts/fetch_vietnam.py
workflow: .github/workflows/fetch-vietnam.yml
fragility_doc: docs/architecture/64-source-vietnam.md
data_file: data/Vietnam.csv
---

# 64 · Source: Vietnam (VAMA + VinFast + TC Group)

**Status: LIVE since 2026-10.** Fetcher `scripts/fetch_vietnam.py` (+ tests
`scripts/test_fetch_vietnam.py`, VAMA PDFs in `scripts/fixtures/vietnam/`), workflow
`.github/workflows/fetch-vietnam.yml`; inputs `data/raw/vietnam/components.csv`
([README](../../data/raw/vietnam/README.md)); reference figures
`checks/vietnam_reference.csv` → `scripts/check_vietnam_reference.py` →
`market/vietnam_checks.json`, reminder `.github/workflows/vietnam-reference-reminder.yml`.
Was on the candidate list ([33](33-expansion-candidates.md)) as shelved — no source
publishes Vietnam's market by fuel.

## TL;DR

```
Sources:   VAMA   vama.org.vn/en/sales-report.html — cover letter + Detail sheet (PDF)
           VinFast vingroup.net news (Vietnamese release; = the SEC 6-K figures)
           TC     thanhcong.vn/tin-tuc — Hyundai release with a model table
Auth:      none. sec.gov and vinfastauto.com refuse GitHub's runners (403); csgt.vn
           times out — hence vingroup.net and the hand-kept police figures.
Timing:    VinFast and TC ~10th, VAMA mid-month; polled 8th–28th twice daily.
Variant:   Whole — passenger cars ≈ M1, sales (charts say "new sales").
Columns:   BEV (VinFast + VAMA BEV) · HEV · MHEV (XL7/Ertiga Hybrid) · ICE (VAMA
           members' PC + Hyundai) · OTHERS (VAMA's non-member import estimate) ·
           TOTAL = VAMA PC + VinFast + Hyundai passenger. PHEV empty.
History:   2024-09 … (25 months at launch). September 2026: 51,013, BEV 46.3 %.
Check:     our all-vehicle sum = the media's national total in all 20 months with a
           figure (within rounding), except 2026-07 (VinFast revision).
```

## 1. Why three sources

Vietnam has no open registration data: the traffic police (CSGT) publish new
registrations only as half-year and year aggregates in press conferences, without a
fuel or brand split, and csgt.vn is not reachable from GitHub. What the Vietnamese
press calls "the market" each month is the sum of three company publications, and this
series is built the same way:

| Publisher | What it covers | Fuel detail |
|---|---|---|
| VAMA (association, ~20 members: Toyota, Ford, Honda, Mitsubishi, Suzuki, THACO's Kia/Mazda/Peugeot, Isuzu, Hino, …) | its members' sales by model, and one estimate of non-member imported (CBU) vehicles | BEV and Hybrid blocks; mild hybrids by model name |
| VinFast (not a member) | its domestic deliveries, every model electric | all BEV |
| TC Group / Hyundai Thành Công (not a member) | Hyundai sales by model, commercial row | none |

Brands outside all three — non-member brands assembling locally and personal imports —
are not covered; their imported cars are in VAMA's estimate.

## 2. From documents to columns

The composition (the `notes` front-matter item and `data/raw/vietnam/README.md` give
the formulas) was checked by hand for every month 2024-09 … 2026-09 against the
published national total (§3). Parsing:

- **Cover letter** (`pdftotext -layout`; pdfplumber breaks the bold totals
  apart): the period sentence, the total-industry sentence (PC / CV / SPV) and the
  "Subtotal" line of the members' Passenger cars, BEV and Hybrid sections (4th number =
  the month's total). All 25 months reproduce the hand-read figures.
- **Detail sheet** (pdfplumber words → cells by gaps; the header month is checked):
  maker, model, segment, month, year to date. THACO's makers map to Kia / Mazda /
  Peugeot, TCIEV to Nissan; CKD/CBU and model-year tags are dropped.
- **VinFast release**: month and units ("hơn" / "more than" = rounded), year to date,
  and the per-model figures of the month (sentences about year-to-date figures are
  ignored; a model list adding up to more than the month is dropped).
- **TC Group release**: the HTML table (this month = second-last column, previous
  month = third-last); "TỔNG" total and "XE THƯƠNG MẠI" commercial.

### Workflow

```mermaid
flowchart TD
  CRON[fetch-vietnam.yml<br/>04:05 & 10:05 UTC, 8th–28th] --> T[unit tests]
  T --> L[VAMA sales-report page<br/>cover letter + Detail sheet]
  T --> V[vingroup.net news<br/>VinFast release]
  T --> H[thanhcong.vn<br/>Hyundai release]
  L --> C[(data/raw/vietnam/components.csv<br/>one row per month, with URLs)]
  V --> C
  H --> C
  C --> Q{all three in<br/>for the month?}
  Q -- no --> N[keep the components,<br/>no chart row]
  Q -- yes --> W[data/Vietnam.csv<br/>market/vietnam_*top/months.json]
  REF[checks/vietnam_reference.csv<br/>hand-kept] --> K[check_vietnam_reference.py]
  W --> K
  K --> J[market/vietnam_checks.json]
  W --> R[render-country.yml<br/>country=Vietnam]
  REF -.-> REM[vietnam-reference-reminder.yml<br/>one open issue while a figure is due]
```

## 3. Reconciliation

Results 2024-09 … 2026-09 (all in `market/vietnam_checks.json`):

- **Media monthly totals** — 20 months with a published figure: 14 exact, 5 within the
  article's rounding or a media slip (2025-07: −11, the article used VinFast 11,490
  instead of 11,479), and 2026-07 −6.4 % because the media used VinFast's first figure
  (21,781) and we use the revised 17,996.
- **Media year totals** — 2025: 603,551 vs VnExpress 604,134 (−0.1 %).
- **CSGT registrations**, our months Dec → May / Dec → Nov against the police's
  15 Dec → 14 Jun / 14 Dec: H1 2025 +0.6 %, year 2025 −6.8 %, H1 2026 −3.2 %, 9M 2026
  +0.1 %. A different event (registration follows sale) and the police count includes
  trucks (122,235 in 2025), so this is shown for scale only.

## 4. Brand and model tables

`market/vietnam_top.json` ranks BEV / HEV / MHEV; `market/vietnam_all_top.json` ranks
every powertrain (class ALL — Hyundai and the non-member imports have no fuel split, so
an ICE table would be incomplete). Month store: 15 months each (`*_months.json`).
VinFast's unnamed models and Lexus/BMW-MINI (separate VAMA sheets, not parsed) are the
unranked remainder; "Other imports (all brands)" — VAMA's non-member estimate — is one pooled row, skipped as
the leading brand. A VinFast month revised downwards after its release has its models scaled to the
revised total.

## 5. Reference figures and the reminder

`checks/vietnam_reference.csv` (by hand): `kind,period_from,period_to,figure,rounded,url,note`
with kind `media_total` (a month), `media_year` (a calendar year) or `csgt` (police,
dates as published). `fetch-vietnam.yml` re-runs the comparison on every run and on
every push of the file. `vietnam-reference-reminder.yml` (02:45 UTC on the 12th–28th,
and the 1st–11th of January and July) lists what is due — the media total of each of
the three newest months from the 20th of the following month, CSGT H1 from 1 July, the
CSGT year from 5 January, rows without a URL — in its run summary and in ONE open issue
labelled `vietnam-reference` (found by the marker `<!-- vietnam-reference -->`), which
it closes once nothing is due. It is the first workflow here with `issues: write`.

## 6. Fragility and runbook

| Symptom | Cause | Fix |
|---|---|---|
| "cover letter … is for 2026-xx, not …" | VAMA posted the wrong file | dispatch with `vama_cover` = the right URL |
| warning: Detail Hybrid lines ≠ cover letter | VAMA's sheet and letter disagree (2025-04, 2025-06) | none — the letter is used |
| month stays incomplete after the 20th | a release not found (new URL pattern or wording) | dispatch with `vinfast_url` / `tc_url`; if a parser fails, fix it with a test |
| VinFast release never appears | vingroup.net changed its news pages | enter `vinfast`, `vinfast_ytd`, `vinfast_kind=manual` in the components file and dispatch with `rebuild` |
| notice "VinFast revision" | next month's YTD implies another figure | expected; the row is rewritten and noted |
| vama.org.vn unreachable | the site is http-only and slow | the run retries; dispatch later |

Reachability from GitHub's runners (2026-10 probe): vama.org.vn, thanhcong.vn,
vingroup.net and bocongan.gov.vn answer; sec.gov and vinfastauto.com return 403;
csgt.vn times out.
