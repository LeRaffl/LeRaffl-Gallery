---
country: Spain
slug: spain
method: file
summary: New-registration data for Spain from DGT's raw matriculaciones microdata — the canonical registry
  source (ACEA no longer covers Spain).
source_name: datos.gob.es — DGT matriculaciones microdata
source_url: https://datos.gob.es/es/catalogo/e00130502-microdatos-de-matriculaciones-de-vehiculos-mensual
source_links:
- label: Direct monthly download (pattern)
  url: https://www.dgt.es/microdatos/salida/2026/6/vehiculos/matriculaciones/export_mensual_mat_202606.zip
  note: one zip per month; swap year / month / YYYYMM. The month folder is not zero-padded
- label: DGT
  url: https://www.dgt.es/
underlying: DGT — Dirección General de Tráfico
auth: none
cadence: daily in the first half of the month (publishes weeks before ACEA)
variants:
- Whole
- Rental
- NonRental
- Used
- Vans
- HDV
- Buses
- 2-Wheelers
variant_notes:
  Whole: New turismos + todoterrenos (registry-side passenger cars, incl. M1 people movers).
  Rental: Whole where the vehicle is rent-a-car or renting/leasing.
  NonRental: Whole minus Rental — the exact complement.
  Used: Used cars at their first Spanish registration — overwhelmingly used imports.
  Vans: New EU N1 (incl. N1G) light commercials.
  HDV: New EU N2/N3 trucks.
  Buses: New EU M2/M3 buses and coaches.
  2-Wheelers: New EU L-category motorcycles and mopeds.
hev_split: true
backfill: pre-Oct-2015 curated history credited to Asier Lizarraga Oroquieta
scope_note: Whole = turismos + todoterrenos (registry-side); one microdata download yields all variants.
caveats:
- Raw DGT registry microdata (fixed-width, no header row); ACEA no longer writes Spain.
- EREV has its own column and folds into PHEV in the three-curve view.
- Whole is ~2% above ACEA's market definition (registry vs association scope).
fetcher: scripts/fetch_spain.py
workflow: .github/workflows/fetch-spain.yml
fragility_doc: docs/architecture/28-source-spain.md
data_file: data/Spain.csv
---

# 28 · Source: Spain (DGT matriculaciones microdata)

**Status: LIVE.** DGT is the canonical source. The series is rebuilt from the
microdata under one definition (§4b, decided 2026-07-08); the previous
curated series is parked as `data/Spain_legacy.csv` (quick rollback + the
pre-layout-era splice); the deviation vs ANFAC/ACEA is explained in
`footnotes.csv`; and Spain has been **removed from `fetch_acea.py` entirely**
so an ACEA-sourced (ANFAC-defined) row can never mix into the DGT series.
Fetcher: `scripts/fetch_spain.py` + `.github/workflows/fetch-spain.yml`.

The facts below were established by a temporary probe workflow
(`probe-spain.yml` / `probe_spain_dgt.py`, runs #1–#7 on 2026-07-08),
**since removed** — it had to run from GitHub Actions because the Claude
sandbox's egress proxy denies CONNECT to every Spanish host involved
(`www.dgt.es`, `sedeapl.dgt.gob.es`, `datos.gob.es` — and
`public.tableau.com`, see §6). To re-verify layout/consistency later,
resurrect it from git history (last present on branch
`claude/spain-data-automation-9jml5p`).

## TL;DR

```
Source:        DGT monthly matriculaciones microdata (raw registry, free,
               no login) → scripts/fetch_spain.py. Canonical; ACEA no longer
               writes Spain at all.
Publishes:     first half of the following month — weeks before ACEA.
Schedule:      daily cron 1st–16th, 06:30 UTC; per-variant early-exit.
Zip URL:       https://www.dgt.es/microdatos/salida/{Y}/{M}/vehiculos/
               matriculaciones/export_mensual_mat_{YYYYMM}.zip
               ({M} NOT zero-padded — the padded variant 404s)
Format:        714-char fixed-width .txt, NO header row (line 1 is an
               informational banner), 69-field layout from
               MATRICULACIONES_MATRABA.pdf (hardcoded in fetch_spain.py)
Market (Whole):COD_TIPO ∈ {40 turismo, 25 todo terreno}, new; registry-side
               "turismos y todoterrenos" — ~2% above ACEA (§4)
Fuel fields:   CATEGORIA_VEHICULO_ELECTRICO ∈ {BEV, REEV→EREV, PHEV, HEV,
               FCEV} + COD_PROPULSION_ITV (gasolina/diésel/GLP/GNC/H2/…);
               EREV folds into PHEV in the 3-curve plot, own TTM band (China)
Variants:      one download → Whole · Rental · NonRental · Used · Vans ·
               HDV · Buses · 2-Wheelers  (definitions in §5/§5b)
Attribution:   DGT as raw source; Asier Lizarraga Oroquieta credited for the
               pre-Oct-2015 curated history (like Ray Willis / Australia,
               R. Andrew / Singapore). His Tableau viz is NOT scraped (§6).
```

## 1. Where Spain stands today

`data/Spain.csv` (variant `Whole` only) has monthly rows since 2015-01 with a
full BEV/PHEV/HEV/PETROL/DIESEL/OTHERS split:

- **2015-01 … 2026-03** — source `ACEA / DGT / asierlizarraga`: a manual
  blend the maintainer curated from Asier Lizarraga's DGT-based analyses and
  ACEA press releases.
- **2026-04 onward** — source `ACEA`: `fetch_acea.py` has Spain on its
  *conditional* list ([05-flows.md](05-flows.md), Flow "ACEA ingest"). The
  conditional rule ("write iff no row exists or source is exactly `ACEA`")
  means the blended history is never touched, but **brand-new months are
  appended automatically** — so Spain is already hands-off, just *slow*:
  ACEA publishes the previous month around the 22nd–25th.

The pain point is therefore latency and granularity, not coverage. DGT
publishes monthly microdata within days of month-end (daily files exist even
intra-month), and one microdata file carries every variant axis the gallery
knows from other countries (§5). ACEA exposes none of them.

## 2. The source landscape

| Source | What it is | Verdict |
|---|---|---|
| **DGT microdata** (`dgt.es` → DGT en cifras → Microdatos de Matriculaciones, mensual) | The raw registry: one fixed-width record per registered vehicle, with technical attributes. Free download, no login, listed on [datos.gob.es](https://datos.gob.es/es/catalogo/e00130502-microdatos-de-matriculaciones-de-vehiculos-mensual). | **Target.** Raw source ("Rohquellen müssen rauf"), earliest availability, richest splits. |
| **ANFAC** (`anfac.com`) | Industry association. Monthly matriculaciones press notes for turismos / LCV / industriales+buses, incl. electrified splits. Data is *not* self-reported by members — it is elaborated by IEA/Ideauto (MSI) **from DGT registry data**, so it is complete. | Viable PDF-parsing fallback (Colombia-style), but strictly downstream of DGT. No reason to parse their PDFs if the registry itself is machine-readable. |
| **ACEA** | European aggregate of ANFAC's numbers. | Current fallback; stays as the conditional-list safety net. |
| **Asier Lizarraga's Tableau Public vizzes** | Curated analyses built on DGT microdata (transferencias + matriculaciones de turismos y todoterrenos). Faster than ACEA, trusted by the maintainer. | Not scraped — see §6. Credited for the curated history. |

The provenance chain for the consistency question (§4) is:

```
DGT registry ──→ microdata files            (what we would ingest)
      └────────→ Ideauto/MSI ──→ ANFAC ──→ ACEA   (what Spain.csv holds today)
```

Both branches start from the same registry, so agreement should be tight —
but Ideauto/ANFAC apply their own market definition (turismos y todoterrenos,
their own treatment of matrícula classes, month cut-off by fecha de
matriculación vs. fecha de trámite) and small discrepancies between DGT
microdata aggregates and ANFAC press numbers are a known phenomenon (DGT,
asked about it, points at ANFAC's methodology). The probe quantifies the gap
instead of assuming it away.

## 3. The microdata product (what's established, what's assumed)

**Established** (from DGT's own pages, the datos.gob.es catalogue and the
IEST help):

- Monthly file per calendar month, plus daily files that get consolidated
  into the monthly one after month-end. Also available: bajas
  (deregistrations) and transferencias (used-vehicle transfers — the basis of
  Asier's transfer analyses, and a possible future "Used (transfers)"
  variant beyond used *imports*).
- Format: fixed-width `.txt`, **not** delimited, **no column-name header**.
  The first line is an informational banner ("Vehículos matriculados. Letras
  de la serie de la última matrícula asignada: …") that must be skipped.
- The field layout is specified in the record-design PDF
  (`MATRICULACIONES_MATRABA.pdf`); field positions/lengths come from there,
  not from the file itself.
- The electrification field `CATEGORIA_VEHICULO_ELECTRICO` distinguishes
  BEV / REEV / PHEV / HEV / FCEV / HICEV; combustion fuel comes from the
  propulsion code (gasolina / diésel / GLP / GNC/GNL / hidrógeno / …).
- Since 2025-02-01 the files no longer carry full chassis numbers
  (bastidor) — irrelevant for aggregation, but explains layout revisions.
- No certificate/login for these downloads. (The SOAP web service
  `descargaArchivoMicrodatosService` *does* require an FNMT-class client
  certificate — that service is for bulk consumers and is **not** the path
  we use; the plain HTTPS file download is.)

**Verified by probe runs #1–#7 (2026-07-08, months 2026-01…05):**

| Fact | Detail |
|---|---|
| Zip URL | `https://www.dgt.es/microdatos/salida/{Y}/{M}/vehiculos/matriculaciones/export_mensual_mat_{YYYYMM}.zip` — month directory **not zero-padded** (`2026/4/`, the padded variant 404s). ~16–17 MB, one `.txt` inside. |
| Access | Anonymous HTTP 200 from a GitHub Actions runner with browser headers + dgt.es warmup GET. No WAF trouble observed. Design PDF also downloads (910 KB, `/export/sites/web-DGT/.galleries/downloads/dgt-en-cifras/matraba/MATRICULACIONES_MATRABA.pdf`). |
| Layout | 714-char fixed-width records, 69 fields; the design table gives (name, CHAR length) with **no position column** — positions are cumulative lengths, and they tile to exactly 714. Transcribed as `MATRABA_LAYOUT` in `fetch_spain.py`, spot-verified against real records (INE municipality code, tipo/clasificación/categoría at computed offsets). ~180–190k records/month. Banner line present in the monthly file (the design doc claims it's daily-only — outdated). Encoding latin-1. |
| Trámite mix | The monthly file is 96–97 % clave trámite `1` (matriculación); `9` (re-matriculación, ≈ clase 7 histórica) and `B` are excluded by the new+turismo filters anyway. FEC_MATRICULA is ≈100 % in-month — no cut-off drift vs ANFAC. |
| Key code tables (Anexo I) | COD_PROPULSION: 0 gasolina, 1 diésel, 2 eléctrico, 6 GLP, 7 GNC, 8 GNL, 9 H2, B etanol, C biodiésel. COD_SERVICIO/SERVICIO: `B00` particular (~75 %), `A01` alquiler sin conductor (~34–35k/month!), `A00` público, … CATEGORIA_VEHICULO_ELECTRICO: BEV/REEV/PHEV/HEV (+FCEV, single digits). COD_TIPO: 40 turismo, 25 todo terreno, 20 furgoneta, 30 autobús… |

Still unverified: the exact publication day-of-month (observe live; both
probed months were long since available) and layout stability across older
years (matters only for a history backfill — check record lengths per year).

## 4. Consistency check — results (runs #3–#7, months 2026-01/02/03/05)

"Was auch immer wir ziehen, es müsste mit ACEA konsistent sein." The probe
compared five candidate market filters against the `Spain.csv` rows. The
winner on fuel-split fidelity is **Filter C = COD_TIPO ∈ {40 turismo,
25 todo terreno}, IND_NUEVO_USADO = N** — exactly ANFAC's "turismos y
todoterrenos" wording. Its deltas vs the CSV, stable across all four months:

| Fuel | Δ DGT-C vs CSV | Verdict |
|---|---|---|
| HEV | **−0.04 % … +0.17 %** (2026-05: ±0 *to the unit*) | identical bucket |
| PETROL | +0.8 … +1.7 % | ≈ identical |
| OTHERS | +1.5 … +3.5 % (small base) | ≈ identical |
| PHEV | +1.6 … +3.2 % | small systematic surplus |
| BEV | +3.1 … +3.6 % | small systematic surplus |
| DIESEL | **+29 … +39 %** (+1.0 … +1.5 k units) | definitional, see below |
| TOTAL | +1.9 … +2.5 % | — |

In BEV-share terms (the gallery's headline metric) DGT-C sits **+0.05 to
+0.28 pp** above the CSV series — e.g. 2026-05: 10.86 % vs 10.77 %.

**What the residual is (and is not).** The probe falsified, in order: trámite
contamination (99.9 % of Filter C is plain clave `1`), month-cut-off effects
(≈100 % in-month), tipo-25 scope (only ~1.7 k units, almost all PHEV/HEV —
removing them *hurts* the HEV match), clase-matrícula scope (Filter B ≈ A),
and autocaravanas (the diesel excess is 94 % inside clasificación `1000`,
plain turismo). What remains is a segment of ~2.4 k units/month with a
signature of ~55 % diesel, ~10 % BEV, ~10 % PHEV, ~10 % petrol and **zero
HEV** — the profile of M1-homologated people movers / van-derived passenger
vehicles (Multivan, V-Class, Vito Tourer, ID.Buzz, …), which DGT types as
`40` but Ideauto/ANFAC segments into *light commercials* on a per-model
basis. A model-list segmentation cannot be replicated from DGT attributes,
so this residual is the irreducible definitional difference between
"registry M1 passenger cars" and "ANFAC's turismo market".

**Important discovery about the existing history:** the blend rows
(2026-01…03, source `ACEA / DGT / asierlizarraga`) show *the same* deltas as
the pure-ACEA rows — the curated history follows the ANFAC market
definition, not raw DGT-C. Switching the series to DGT-C therefore
introduces a one-time definitional step (+~2 % TOTAL, +~30 % diesel,
+~0.1–0.3 pp BEV share) unless the history is backfilled from DGT microdata
under the same Filter-C definition (see §4b).

Bucket conventions confirmed: REEV → BEV (~60–210/month, reported
separately by the probe), FCEV → OTHERS (single digits), HEV covers
full+mild in both sources (that's why it matches to ~zero).

## 4b. The decision (taken 2026-07-08): DGT-C canonical, full backfill

The maintainer picked option 1 with three explicit calls:

1. **M1 people movers stay in Whole.** ID.Buzz/Multivan/V-Class are
   passenger cars in the registry sense; ANFAC's model-based reclassification
   into light commercials is *their* convention, not ours. The deviation is
   surfaced where people will look for it (`footnotes.csv`, this doc) because
   most readers compare against ACEA.
2. **REEV → `EREV` column** (not BEV): the renderer folds EREV into the PHEV
   curve in the BEV/PHEV/ICE trajectory and shows it as its own band in the
   TTM fuel mix — exactly the China convention (see `R/data.R`'s EREV
   partial-window guard and `R/post_text.R`'s "(of which X %p were EREV)").
3. **The old series is parked, not deleted:** `data/Spain.csv` →
   `data/Spain_legacy.csv` (inert — the gallery is driven by params/manifest,
   not by a data/ glob). Quick rollback = rename it back. Months older than
   the current MATRABA layout era are spliced from it into the new CSV with
   their original source string, so the fit window stays populated and the
   seam is visible in the `source` column.

The rejected alternatives, for the record: ACEA-stays-canonical (keeps the
3-week lag that started this) and the hybrid "DGT early, ACEA overwrites
later" (mixes two definitions inside single rows over time — the gallery
never publishes a number it later silently redefines).

## 5. Variant opportunities (why DGT is worth the effort)

All from the *same* monthly file, i.e. one fetcher run populates every CSV:

All variants are attribute filters over the same monthly file — one
download feeds every CSV (`scripts/fetch_spain.py`, one pass). Implemented
lineup and DGT-term definitions:

| Variant | CSV | Definition (DGT fields) | ~Size/month |
|---|---|---|---|
| `Whole` | `Spain.csv` | `COD_TIPO ∈ {40 turismo, 25 todo terreno}`, `IND_NUEVO_USADO = N` | ~110–130 k |
| `Rental` | `Spain_Rental.csv` | Whole ∧ (`SERVICIO = A01` alquiler sin conductor ∨ `RENTING = S`) | ~35–40 k |
| `NonRental` | `Spain_NonRental.csv` | Whole ∧ ¬Rental (exact complement: Rental + NonRental = Whole) | ~75–90 k |
| `Used` | `Spain_Used.csv` | `COD_TIPO ∈ {40,25}`, `IND_NUEVO_USADO = U`, `CLAVE_TRAMITE = 1` | ~18–20 k |
| `Vans` | `Spain_Vans.csv` | EU homologation `N1*` (incl. `N1G`), new | ~13–14 k |
| `HDV` | `Spain_HDV.csv` | EU homologation `N2*`/`N3*`, new | ~2.5–3 k |
| `Buses` | `Spain_Buses.csv` | EU homologation `M2*`/`M3*`, new | ~0.4–0.6 k |
| `2-Wheelers` | `Spain_2-Wheelers.csv` | `COD_TIPO ∈ {50 motocicleta, 90 ciclomotor}`, new | ~25–29 k |

Precedents: Italy_Rental/NonRental, Denmark/Finland HDV, Ireland Buses,
Albania 2-Wheelers. `Private`/`Industry` (via `PERSONA_FISICA_JURIDICA`)
would be possible but is not implemented.

## 5b. "What is in which variant?" — the idiot-proof reference

The question users will actually ask. Keep this table in sync with
`record_variants()` in `scripts/fetch_spain.py`.

| Vehicle | Lands in | Why |
|---|---|---|
| Normal car, SUV, crossover | **Whole** (+Rental or NonRental) | tipo 40; modern SUVs are tipo 40, not 25 |
| Old-school off-roader (Jimny, Land Cruiser as M1) | **Whole** | tipo 25 "todo terreno" |
| M1 people mover — ID.Buzz, Multivan, V-Class, Vito Tourer | **Whole** | tipo 40/25; **this is the deliberate difference vs ANFAC/ACEA**, who count these as light commercials (§4) |
| Taxi, driving-school car, ambulance-service *car* | **Whole** | servicio codes don't exclude from Whole; only A01/renting routes to Rental |
| Rent-a-car registration | **Whole + Rental** | `SERVICIO = A01` (alquiler sin conductor) |
| Renting/leasing registration | **Whole + Rental** | `RENTING = S`; note "Rental" = rent-a-car **plus** leasing, the closest analogue to Italy's noleggio |
| Company car bought outright | **Whole + NonRental** | juridical owner but neither A01 nor renting flag |
| Used car imported from abroad (first Spanish plate) | **Used** | `IND_NUEVO_USADO = U`, clave 1; Used is *not* part of Whole |
| Used car sold within Spain | **nowhere** | domestic ownership transfers are DGT's *transferencias* dataset, not matriculaciones |
| Historic-plate re-registration | **nowhere** | clave 9 rematriculación, excluded from Used on purpose |
| Panel van, car-derived van (Caddy cargo, Kangoo…) | **Vans** | homologation N1 |
| **Pickup** (Hilux, Ranger, …) | **Vans** | pickups are homologated N1 (heavy ones N1G) — not Whole, not HDV |
| Truck >3.5 t, rigid or articulated | **HDV** | N2 (3.5–12 t) / N3 (>12 t) |
| Road tractor unit (Sattelzugmaschine) | **HDV** | N3 |
| **Agricultural tractor**, harvester | **nowhere** | EU category T/agrícola — deliberately no variant |
| Construction machinery, forklifts | **nowhere** | special tipos/homologations, fail every filter |
| City bus, coach, minibus >8 seats | **Buses** | M2/M3 |
| Motorcycle | **2-Wheelers** | tipo 50 |
| Moped/scooter ≤50 cc | **2-Wheelers** | tipo 90 (ciclomotor) |
| Trike, quad/ATV | **nowhere** | own tipos, deliberately excluded from 2-Wheelers |
| **Motorhome/autocaravana** | **nowhere** | own tipo/clasificación; neither tipo 40/25 nor N1 |
| Trailer, semi-trailer | **nowhere** | category O |
| Used van/truck/motorcycle import | **nowhere** | Used covers turismos/todoterrenos only; all other variants are new-only |

Rules of thumb: everything except `Used` is **new registrations only**;
`Used` is **first Spanish registrations of used turismos/todoterrenos**
(overwhelmingly imports) and is disjoint from Whole; `Rental + NonRental =
Whole` exactly; and the 2-Wheelers filter is tipo-based because the EU
L-homologation field is sparsely populated for two-wheelers (national `*0x`
codes instead).

Note on the ACEA interplay once `fetch_spain.py` exists: the moment DGT rows
are written with a non-`ACEA` source string (e.g. `DGT`), `fetch_acea.py`'s
conditional rule automatically stops touching Spain — no ACEA-side change
needed. Since DGT publishes weeks before ACEA, the DGT row will exist first
in the steady state. Give `fetch_spain.py` the mirrored courtesy rule:
overwrite an existing row only if its source is exactly `ACEA` (the fallback
that beat us to it) or already `DGT`; never touch the blended history rows.

## 6. Attribution, and why we don't scrape Asier's Tableau

The maintainer's requirement: raw sources must be listed, and if Asier's
work is used, he is credited the way Prof. Ray Willis is for Australia
(`VFACTS & Prof. Ray Willis`) and Robbie Andrew for Singapore.

- His public viz ([Análisis de transferencias de turismos y todoterrenos](https://public.tableau.com/app/profile/asier.lizarraga.oroquieta/viz/Analisisdetrasferenciasdeturismosytodoterrenos/1-PORTADA))
  and related matriculaciones dashboards are built **on the same DGT
  microdata** this plan targets. Going DGT-direct gets the same numbers
  earlier in the chain, independently, with clean licensing — strictly
  better than scraping a Tableau Public workbook (brittle dashboard
  scraping; same class of objection as the Power BI / Looker Studio cases
  in [14-data-source-gaps.md](14-data-source-gaps.md) — Albania proves it
  *can* be done when there is no alternative, but here there is one).
- The existing history rows keep their `ACEA / DGT / asierlizarraga` source
  string forever — that *is* the credit, and the gallery's footnote/source
  surface should keep naming him for the historical series.
- Future DGT-fetched rows get source `DGT` with the file URL in `notes`
  (same convention as every other fetcher).

## 7. Sandbox/network constraints hit during this investigation

Recorded so the next session doesn't rediscover them:

- The Claude Code remote sandbox egress proxy returns CONNECT 403 (policy
  denial) for `www.dgt.es`, `sedeapl.dgt.gob.es`, `datos.gob.es` and
  `public.tableau.com`. Server-side WebFetch reaches them but gets
  HTTP 403 from the DGT/Akamai WAF (non-browser client). Consequence:
  **nothing DGT-side is verifiable from a sandbox session** — hence the
  investigation ran through a GitHub Actions probe, where `fetch_acea.py`
  had already proved WAF-laden sources are workable (browser headers +
  homepage warmup session). `fetch_spain.py` reuses that approach.
- GitHub Actions egress is unrestricted; if dgt.es ever blocks GitHub
  runner IPs outright (Austria precedent), the fallback is the same one
  Austria uses: relay through the Cloudflare Worker `/fetch`
  ([20-source-austria.md](20-source-austria.md)).

## 8. Status & possible follow-ups

Live since 2026-07 (§4b option 1). Done: bootstrap backfill (2015-01→,
DGT from 2015-10 with the pre-layout months spliced from the legacy file),
all eight variants, ACEA removed from Spain, footnotes, renders. The
temporary probe scaffolding was removed after use (recover from git history
on branch `claude/spain-data-automation-9jml5p` if a re-verification is
ever needed).

Possible later work, none blocking:

- `Private`/`Industry` split via `PERSONA_FISICA_JURIDICA` (D/X) — the one
  obvious variant axis not yet built.
- A per-year MATRABA layout table if the backfill is ever pushed before
  2015-10 (older files have a different record length; `fetch_spain.py`
  stops at the first length mismatch rather than misread offsets).
- Attribute-level refinement toward the ANFAC market definition is
  **not** pursued on purpose — the ~2% people-mover difference is a
  model-list segmentation ANFAC does that DGT attributes can't reproduce;
  it is documented, not tuned away (§4).
