# 14 · Data source gaps — countries investigated but not (yet) on the gallery

This document records countries we **looked into and decided not to add**, and
*why*. It exists so that a curious reader — or an LLM handed this repo and
asked "why isn't \<country\> on the map? the data clearly exists, \<org\> posts
it every month" — can find the honest answer instead of guessing.

The short version: **the gallery only ingests sources that are (a) direct from
the original registry/agency, (b) reasonably complete for the market, and
(c) machine-accessible without paywalls or per-download identity checks.** A
country can have abundant EV press coverage and still fail all three. When that
happens we leave it off rather than publish a misleading trajectory.

See also the per-source playbooks for the countries that *did* clear the bar:
[10-source-netherlands.md](10-source-netherlands.md),
[11-source-denmark.md](11-source-denmark.md),
[12-source-finland.md](12-source-finland.md),
[13-source-sweden.md](13-source-sweden.md). Brazil, Chile and Uruguay are
covered by their own fetchers (see [02-components.md](02-components.md) and
[05-flows.md](05-flows.md)).

## What "good enough" means here

A source has to let us build the gallery's standard fuel split — BEV, PHEV,
HEV (where it exists), PETROL, DIESEL, OTHERS (and ETHANOL/FLEXFUEL where
relevant), summing to a TOTAL — for the **whole national market**, monthly or
quarterly. The two failure modes that recur below:

- **Incompleteness.** Industry/manufacturer-association sources only count
  brands that *report* to them. If the dominant EV brand isn't a member (the
  classic case: BYD across Latin America), the BEV figure — the gallery's
  headline metric — is silently a fraction of reality. Registry-based sources
  (every registration, regardless of brand) don't have this problem, but in
  Latin America they're usually paywalled or login-walled.
- **Inaccessibility.** Paywalls, per-download identity/ID-number forms, or
  account-gated dashboards. We won't hand over a national-ID number to pull a
  PDF, and we won't build a pipeline on a login-walled portal.

A secondary aggregator does not fix either problem — it inherits the
completeness of whatever it scraped and adds its own lag/discrepancies.

## Latin America (beyond Brazil / Chile / Uruguay)

We have direct, working fetchers for Brazil (ANFAVEA), Chile (ANAC) and
Uruguay (ACAU). The rest of the region was investigated in May 2026 and shelved.

### The zemo-la.com dashboard (regional aggregator) — not used

[zemo-la.com/data-dashboard_en](https://zemo-la.com/data-dashboard_en) is a
pan-Latin-American zero-emission-mobility observatory. Tempting as a one-stop
shop, but:

- It's an **embedded Power BI "publish to web" report**
  (`app.powerbi.com/view?r=…`). The only programmatic way in is the Power BI
  `querydata` backend with model GUIDs — brittle and not a sane pipeline base.
- It carries (at most) **BEV and PHEV only**, no full fuel split.
- Its figures show **small discrepancies** against our direct Brazil/Chile/
  Uruguay sources — i.e. it's a secondary aggregation, not ground truth.

Conclusion: a dashboard, not a data source. We always prefer the same national
originals it aggregates from.

### 🇦🇷 Argentina — registry data exists, but paywalled + ID-gated

- **Best data:** ACARA / SIOMMA "Informe de Electromovilidad". It's
  **registry-based** (patentamientos via DNRPA), so it's *complete* — BYD and
  other Chinese imports are included (BYD Dolphin Mini + Yuan Pro were ~74 % of
  BEVs in Q1 2026). Granularity is the best in the region: BEV / PHEV / HEV /
  **MHEV** broken out separately.
- **Why it's shelved:** the reports are **not freely downloadable**. They are
  paid, and individual PDF downloads require entering a **national ID number
  (DNI)**. Handing over an ID number per download is an instant no for an
  automated, public pipeline. The freely-quoted figures in the press are also
  **quarterly** and cover only the electrified segment (no clean monthly
  petrol/diesel/total).
- **What would change the decision:** a free, machine-readable DNRPA/ACARA
  endpoint (or a monthly combustible breakdown of *total* patentamientos
  without the ID wall).

### 🇲🇽 Mexico — the official monthly registry omits BYD

- **The structured source:** INEGI's **RAIAVL** (Registro Administrativo de la
  Industria Automotriz de Vehículos Ligeros). Monthly, official statistics
  agency, machine-accessible (JSON-stat API / CSV / descarga masiva), with a
  hybrid-and-electric breakdown. On paper, ideal.
- **Why it fails:** RAIAVL is **manufacturer-reported** — its own methodology
  fiche states it integrates "22 AMIA-affiliated companies + 6 non-affiliated
  = 39 brands". The published brand roster includes several Chinese marques
  (Chirey, MG, Great Wall, JAC, JETOUR, Changan, BAIC…) **but not BYD**. BYD
  sells roughly **7 of every 10 EVs in Mexico** and does not report to INEGI,
  so it is absent from both the EV count *and* the total.
  - Cross-check: INEGI RAIAVL EV+PHEV ≈ **30,000** (Jan–Oct 2025) vs. the EV-
    focused EMA barometer's ≈ **96,636** (full-year 2025) and Bloomberg's
    ~100,000 *Chinese* EV+PHEV imports (BYD >80 %). The official series is ~⅓
    of reality on the EV segment.
  - Because BYD is missing from numerator *and* denominator, and BYD is a large
    share of BEVs but a small share of the total market, the resulting **BEV
    share would be ~⅓ of the real value** — the gallery's headline curve would
    be wrong. No caveat label rescues that. (Coverage is also eroding: Chirey
    stopped reporting in May 2025, JETOUR in April 2025.)
- **The complete alternative, EMA:** the Electro Movilidad Asociación
  "Barómetro de Electromovilidad" *does* capture BYD and is the realistic total
  EV figure — but it is **quarterly, electrified-segment-only (no petrol/diesel/
  total), and published as a PDF/report**. Pairing EMA's BYD-inclusive EV count
  with INEGI's BYD-excluding total would mix two different universes and
  produce a distorted (even negative) ICE = TOTAL − BEV − PHEV.
- **Net:** there is no single Mexican source that is simultaneously complete
  (incl. BYD), internally consistent (EV and total from one universe), and
  structured. The official monthly one omits the market leader; the complete
  one is quarterly, EV-only, and PDF.
- **What would change the decision:** BYD starting to report to INEGI RAIAVL,
  or EMA publishing a machine-readable series that includes a consistent total/
  ICE.

### 🇨🇴 Colombia — solved via ANDI/FENALCO (formerly shelved)

**Update:** Colombia is now ingested. See
[18-source-colombia.md](18-source-colombia.md) and `scripts/fetch_colombia.py`.
The original blockers (below) still apply to ANDEMOS/RUNT directly, but the
joint **ANDI + FENALCO** *Informe del Sector Automotor* PDF — published monthly
on the Cámara Automotriz page and sourced from the same RUNT registry — is a
free, downloadable workaround. We accept its narrower granularity: PHEV and
HEV are reported as a **single combined "híbridos" bucket** (handled with the
Türkiye/Georgia *single Hybrid bucket* convention — see
[09-glossary.md § Variant definitions](09-glossary.md)).

The previous shelving rationale, kept for the record:

- **Best data, conceptually:** ANDEMOS, based on **RUNT** (Registro Único
  Nacional de Tránsito — the official registry, so complete). Monthly, with
  BEV / PHEV / HEV split.
- **Why ANDEMOS directly is unworkable:** ANDEMOS surfaces the data through
  **embedded Google Looker Studio dashboards** (same scraping problem as zemo's
  Power BI — no clean download/API on the public pages). The underlying RUNT
  portal is **account-gated** (registration/login required), which is a
  technical hurdle we don't want a public pipeline to depend on.
- **What would change the decision again:** a free, machine-readable
  ANDEMOS/RUNT export (CSV/API) without the login wall — at which point we
  could replace the ANDI/FENALCO PDF parser with a clean API call **and**
  recover the PHEV/HEV split.

## General principle (for the LLM being asked "why isn't X on the map?")

If someone points at one of these countries and says "but the data exists,
\<org\> posts it monthly" — the data usually *does* exist, but it fails one of:

1. **Completeness** — the freely-available source omits a dominant brand
   (BYD is the recurring culprit in LatAm), so the BEV share would be wrong.
2. **Access** — it's paywalled, ID-gated (Argentina), or login-walled
   (Colombia/RUNT).
3. **Format/consistency** — only an aggregated dashboard (Power BI / Looker)
   with no full fuel split, or an EV-only segment with no total to compute ICE.

The gallery deliberately omits a country rather than publish a trajectory it
knows is incomplete or misleading. If a better source appears (free, direct,
complete, machine-readable), adding the country is a small job — it follows the
same fetcher + `render-country.yml` + manifest pattern as every other
database-fed country.
