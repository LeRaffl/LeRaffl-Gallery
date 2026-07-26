# 33 · Expansion candidates — Israel, India, Africa, MENA (July 2026 investigation)

This document records a **desk investigation (2026-07)** into expanding the
gallery's country portfolio into regions it currently doesn't cover at all:
Africa, the Arab world, Israel, and India. It is the forward-looking sibling of
[14-data-source-gaps.md](14-data-source-gaps.md) (which records countries we
investigated and *rejected*). Same bar applies: **(a) direct from the original
registry/agency or the de-facto complete industry body, (b) reasonably complete
for the market, (c) machine-accessible without paywalls or identity checks.**

> **Verification status:** everything below is from web research only. The
> session that produced this doc ran under a network policy that blocked direct
> requests to the candidate endpoints, so **none of the APIs/PDFs have been
> exercised yet**. Each candidate lists its open verification points — check
> those first when building the fetcher.

---

## Tier 1 — viable candidates, ordered by expected effort (lowest first)

### 🇮🇱 Israel — two complementary routes, both free

> **Status: BUILT (2026-07).** Route A implemented as `scripts/fetch_israel.py`
> — see [34-source-israel.md](34-source-israel.md). The PHEV/HEV question
> resolved unexpectedly: the registry hides regular HEVs inside the petrol
> value; the model-catalogue join recovers them (and the PHEV split) with
> 100% coverage back to 2017.

**Route A (registry, preferred): data.gov.il vehicle registry.**
The Ministry of Transport's licensing database is published as an open dataset
— "מספרי רישוי של כלי רכב פרטיים ומסחריים" (private & commercial vehicles),
[data.gov.il/dataset/private-and-commercial-vehicles](https://data.gov.il/dataset/private-and-commercial-vehicles)
— behind a standard **CKAN datastore API** (same tech as data.gov.my /
Malaysia, so `fetch_malaysia`-style code applies). Fields include fuel type
(`sug_delek_nm`) and road-entry date (`moed_aliya_lakvish`), so monthly new
registrations by fuel can be derived by grouping on the entry month.

- Caveat 1: this is a **stock snapshot**, not an events feed — deregistered
  vehicles drop out over time. Negligible for recent months (the gallery's
  use case), but don't backfill deep history from it without noting this.
- Caveat 2 (**verify first**): whether `sug_delek_nm` separates **PHEV from
  HEV** (the raw values are along the lines of בנזין/דיזל/חשמל/חשמל־בנזין —
  the hybrid value may not carry a plug-in flag). If not separable at the
  registry level, join against the model (degem) dataset on the same portal,
  or fall back to Route B for the PHEV/HEV split.

**Route B (industry body): I-VIA monthly reviews.**
The Israel Vehicle Importers Association ([car-importers.org.il](https://www.car-importers.org.il/Monthly_reviews),
OICA member) publishes **free English monthly review PDFs** and quarterly
trend analyses with a full powertrain split (petrol / diesel / HEV / PHEV /
BEV). Israel has no domestic car manufacturing — the market *is* imports via
licensed importers — so coverage is effectively complete, and I-VIA's figures
are licensing-data-based. A Chile/Colombia-style monthly PDF parser would work.

**Recommendation:** try Route A first (structured API beats PDF); keep Route B
as the PHEV/HEV disambiguator and as a cross-check.

### 🇮🇳 India — Vahan (MoRTH national registry)

The **Vahan** platform (Ministry of Road Transport & Highways) is the national
vehicle register, and its public analytics dashboard
([vahan.parivahan.gov.in/analytics](https://vahan.parivahan.gov.in/analytics/))
exposes monthly registrations by fuel — with categories that map cleanly onto
the gallery split: PURE EV → BEV, PLUG-IN HYBRID EV → PHEV, STRONG HYBRID
EV → HEV, PETROL, DIESEL, CNG/LPG/others → OTHERS. Registry-based, so no
BYD-style completeness hole.

> **Status updates (2026-07-10, CI probes v1–v3 — `scripts/fetch_india.py --probe`):**
> - `vahan.parivahan.gov.in` **resets connections from GitHub runners** (geo/WAF
>   block — matches the maintainer's own need for a VPN). Dashboard scraping
>   from CI is dead; a Cloudflare relay wouldn't help (also foreign egress).
> - `api.data.gov.in` is reachable, but the docs' public sample key is
>   **globally dead** (403 even on their own demo resource) and keyless calls
>   get 400 — a personal key is mandatory, and **foreign registration is
>   broken** (SMS verification never arrives on non-Indian numbers).
> - **IndiaDataPortal CKAN** (`ckan.indiadataportal.com`) is open and keyless
>   with Vahan mirrors at RTO-office granularity — but the fuel-type resource
>   has **no vehicle-category dimension** (all vehicle types lumped, 2W
>   dominate) and the mirror is **stale: 2019-01…2024-05**. Unusable as
>   primary; useful as a historical plausibility reference at most.
> - The maintainer's historical Vahan Excel extract (2010-01…2026-04, LMV +
>   2W/3W wheeler groups) has header/data vintage misalignment in its raw
>   sheets and is a **cross-check reference only**, not a bootstrap.
>
> **Net:** no route is simultaneously automated, key-less, current, and
> fuel×category-crossed. Pragmatic plan: **semi-automated ingestion** — the
> maintainer pulls the Vahan reportview XLSX exports via VPN (the workflow
> they already have), a converter script validates alignment and builds the
> gallery CSVs (Türkiye/Georgia-style manual cadence). Full automation
> unlocks if a data.gov.in key is ever obtained.

Access routes, in order of preference:

1. **data.gov.in OGD API** — dataset "All India Level Year, Month, Vehicle
   Category and Fuel Type-wise Total Number of Vehicles Registered"
   ([API detail page](https://www.data.gov.in/apis/76192d23-59ba-4be8-9ccb-a469e83dc552)),
   free API key, refreshed monthly. If the refresh cadence holds in practice,
   this is the fetcher base.
2. **Scrape the Vahan analytics dashboard** — it's a JSF/PrimeFaces app
   (POST-back, viewstate), scrapeable but brittle; several public mirrors
   (India Data Portal CKAN, dataful.in) do exactly this and can serve as
   parsing references. **Ruled out 2026-07: geo-blocked from CI (see above).**

Caveats:

- **Registrations ≠ dispatches.** SIAM publishes wholesales; Vahan is retail
  registrations. Registrations are what the gallery prefers anyway.
- **Telangana structural break:** Telangana ran its own registration IT and
  only joined Vahan on **2026-03-15**. All-India Vahan series before that date
  exclude Telangana (~3–4 % of the market); after it, the state flows in. Needs
  a footnote (footnotes.csv) and possibly a level-shift sanity check around
  Mar 2026. Lakshadweep is also absent (negligible).
- **Category filter:** Vahan counts every vehicle class. `Whole` should filter
  to the four-wheeler passenger category (LMV / "Motor Car" class), otherwise
  two-wheelers dominate the total.

**Variant upside:** Vahan's category dimension makes `India_2-Wheelers` and
`India_3-Wheelers` nearly free — and India's 3W segment is one of the most
electrified vehicle markets on earth, which would be a genuinely novel curve
for the gallery (precedent: `Albania_2-Wheelers`).

### 🇲🇦 Morocco — AIVAM (importers' association)

AIVAM ([aivam.ma](https://www.aivam.ma/fr/documentation-et-etudes)) publishes
monthly market statistics with an unusually fine energy split — press relays
(Medias24, EcoActu, Le Matin) consistently quote **BEV / PHEV / HEV / MHEV /
REEV** unit counts plus petrol/diesel for passenger cars. Morocco's formal new
market flows through AIVAM member importers, and the stats already count the
21 Chinese brands (11.3 % share H1 2026), so the LatAm-style BYD hole does not
appear to exist here.

- Mapping per existing conventions: REEV → PHEV (EREV convention, see
  [09-glossary.md](09-glossary.md)), MHEV → OTHERS or PETROL (Uruguay maps
  MHEV → OTHERS; stay consistent).

> **Status: SHELVED (2026-07-12, CI probes v1–v4 — `scripts/fetch_morocco.py --probe`).**
> The open verification question resolved negatively:
> - AIVAM's **monthly press PDF** is a one-pager (VP/VUL totals + brand
>   table) and the **monthly "Statistiques des ventes … FP.xls"** is
>   machine-readable but brand×VP/VUL only — **neither carries the energy
>   split** the press quotes.
> - The energy data lives in AIVAM's stats portal `statistique.aivam.ma`
>   (Angular SPA): the API has an explicit `statistics/energy` resource, but
>   only under **`/api/v1/private/` → 401 Unauthenticated** (role
>   `read_statistics_energy`); `/api/v1/public/` has no statistics at all.
>   Login-walled member portal = the Colombia/RUNT access failure mode.
> - The annual "Bilan" deck has a *Focus NEV* section — yearly only.
>
> **What would change the decision:** AIVAM portal credentials (if
> membership/registration is attainable, the fetcher authenticates with a
> repo-secret token and Morocco becomes a clean JSON-API source), or AIVAM
> starting to publish the energy table in the monthly XLS/PDF.

### 🇿🇦 South Africa — naamsa (quarterly granularity)

> **Status: VERIFIED VIABLE (2026-07-12, CI probes — `scripts/fetch_southafrica.py --probe`).**
> naamsa.net is open from CI, the press-release archive reaches back to 2017,
> and the **Quarterly Business Review** (found via the WP sitemap; the
> newest lives under `naamsa.net/wp-content/uploads/...Quarterly-Review...`)
> parses cleanly with pdfplumber. Its NEV page carries the full drivetrain
> table — Q1-2026 edition: Plug-in hybrid / Traditional hybrid / Electric /
> Total NEVs with **yearly columns 2020–2025 plus quarterly columns**
> (Q1:2025, Q1:2026) — i.e. one current PDF bootstraps the yearly history
> for free, and the review archive backfills the quarters. Monthly flash
> reports carry totals only (no NEV split).
> Open design decision for the fetcher: the NEV table is all-vehicles
> (no passenger/LCV split), so `Whole` should be the **total market** with a
> footnote (mixing naamsa's passenger-only total with the all-vehicle NEV
> count would repeat the Mexico two-universes mistake).

naamsa, the Automotive Business Council
([naamsa.net/press-releases](https://naamsa.net/press-releases/)), publishes
free monthly **flash reports** (total sales by segment, PDF) and a
**Quarterly Review of Business Conditions** with the NEV breakdown
(BEV / PHEV / HEV unit counts; 2025: BEV 1,088, PHEV 2,810, HEV 12,818).
Manufacturer-reported, but naamsa's reporting roster covers effectively the
whole formal market including BYD, Chery, GWM — so completeness looks OK
(**verify: the quarterly NEV table says "21 industry brands"; confirm no
significant EV importer is outside it**).

- Cadence: NEV split is **quarterly** → Canada-style quarterly ingestion
  (store under the middle month).
- No public petrol/diesel split of the ICE remainder → USA convention
  (ICE = TOTAL − BEV − PHEV − HEV in one bucket, OTHERS = 0).
- Realistically this is a *slow* curve (BEV share ≈ 0.2 %), but it would be
  the gallery's first African market and an honest early-stage data point.

---

## Shelved — investigated 2026-07, no viable source

Same spirit as [14-data-source-gaps.md](14-data-source-gaps.md); listed here
so the next session doesn't redo the search.

- **🇦🇪🇸🇦 Gulf states (UAE, Saudi Arabia, Qatar, …):** no official monthly
  registration statistics by fuel type anywhere in the public domain. What
  exists is annual/ad-hoc ministry claims (Saudi Ministry of Investment EV
  counts), Dubai RTA EV-fleet totals, and paid market research. Fails
  access + format. Re-check if Saudi GASTAT or UAE MoI start publishing.
- **🇯🇴 Jordan:** the EV story is dramatic (EVs ≈ 55 % of vehicle imports) but
  the only recurring numbers are **Zarqa Free Zone customs-clearance figures**
  relayed through press releases — clearances include re-exports, cadence is
  irregular, and there is no structured publication. Clearance ≠ registration;
  shelved.
- **🇪🇬 Egypt:** AMIC (Automotive Marketing Information Council) has exactly
  the right data — and sells it. Paywalled; shelved.
- **🇰🇪 Kenya / 🇪🇹 Ethiopia / 🇳🇬 Nigeria:** registries capture a fuel field
  (Kenya NTSA does), but **no agency publishes a monthly fuel-split series**.
  Kenya's NTSA/KNBS output is totals by vehicle type; Ethiopia — despite the
  most aggressive ICE-import restrictions in Africa — publishes nothing
  machine-readable; Nigeria's NBS is quarterly totals only. Ethiopia is the
  one to re-check periodically, since the policy story will eventually force
  official numbers into the open.

---

## Alternative axis — variant leads for countries already on the gallery

Unverified leads (training-knowledge level, no fetch performed — confirm the
publication + fuel split before building):

| Variant | Source lead | Note |
|---|---|---|
| `Germany_Vans` / `Germany_HDV` / `Germany_Buses` | KBA monthly FZ-series (e.g. FZ 28 / monthly Fahrzeugzulassungen tables) | KBA publishes N1/N2-N3/bus new registrations by Kraftstoffart monthly; Germany currently has no variants at all |
| `UK_Vans` | SMMT monthly LCV registrations | Monthly, free, BEV split published; HGV/bus only quarterly |
| `France_Vans` / `France_HDV` | SDES / data.gouv.fr (RSVERO-based immatriculations by energy) | Registry-direct, structured downloads |
| `Sweden_Vans` / `Sweden_HDV` / `Sweden_Buses` | Mobility Sweden monthly press stats | Complements the existing SCB PxWeb source |
| `Norway_Vans` | OFV monthly varebil registrations | Norway is the most-watched market on the gallery; vans curve lags cars interestingly |
| `India_2-Wheelers` / `India_3-Wheelers` | Vahan (see above) | Comes almost free with the India fetcher |

## Suggested order of attack

1. **Israel** (CKAN API, known tech, complete registry) — highest
   value-per-effort.
2. **India** (data.gov.in API + Telangana footnote) — biggest market gap on
   the gallery, plus 2W/3W variants.
3. **Morocco** (after verifying AIVAM's own PDFs carry the energy table).
4. **South Africa** (quarterly, Canada-pattern).
