# 28 · Source: Spain (DGT microdata — investigation & automation plan)

**Status: LIVE (bootstrap pending render check).** The maintainer decided
§4b **option 1** on 2026-07-08: DGT is canonical, the series is rebuilt from
the microdata under one definition, the previous curated series is parked as
`data/Spain_legacy.csv` (kept for quick rollback and for the pre-layout-era
splice), and the ACEA deviation is explained in `footnotes.csv`. Fetcher:
`scripts/fetch_spain.py` + `.github/workflows/fetch-spain.yml`. This
document records what the probe verified (runs #1–#7, 2026-07-08) and why
the definition is what it is. The verification vehicle was
`.github/workflows/probe-spain.yml` / `scripts/probe_spain_dgt.py`, which must
run from GitHub Actions because the Claude sandbox's egress proxy denies
CONNECT to every Spanish host involved (`www.dgt.es`, `sedeapl.dgt.gob.es`,
`datos.gob.es` — and `public.tableau.com`, see §6).

## TL;DR

```
Today:         data/Spain.csv history 2015-01…2026-03 = manual blend,
               source "ACEA / DGT / asierlizarraga"; new months appended by
               fetch_acea.py (conditional-list "no row exists" branch),
               source "ACEA" — arrives late (~22nd-25th of the next month)
Target:        DGT monthly matriculaciones microdata (raw registry, free,
               no login) → scripts/fetch_spain.py, ACEA demoted to fallback
Zip URL:       https://www.dgt.es/microdatos/salida/{Y}/{M}/vehiculos/
               matriculaciones/export_mensual_mat_{YYYYMM}.zip   [UNVERIFIED]
Format:        fixed-width .txt, NO header row (line 1 is an informational
               banner), layout from MATRICULACIONES_MATRABA.pdf design doc
Fuel fields:   CATEGORIA_VEHICULO_ELECTRICO ∈ {BEV, REEV, PHEV, HEV, FCEV,
               HICEV} + COD_PROPULSION_ITV (gasolina/diésel/GLP/GNC/H2/…)
Variants:      one file carries Whole (M1) · Vans (N1) · HDV (N2+N3) ·
               Buses (M2+M3) · 2-Wheelers (L) · Used Imports (IND_NUEVO_USADO)
               · Rental/NonRental (SERVICIO + RENTING) · Private/Company
Gate:          probe-spain.yml consistency report vs ACEA rows must reconcile
               (~±1-2% on TOTAL) before any fetcher lands
Attribution:   DGT as raw source; Asier Lizarraga Oroquieta credited for the
               curated history (like Ray Willis / Australia, R. Andrew /
               Singapore). His Tableau viz is NOT scraped (§6).
Scripts:       scripts/probe_spain_dgt.py           (probe, read-only)
Workflow:      .github/workflows/probe-spain.yml    (workflow_dispatch only)
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
| Layout | 714-char fixed-width records, 69 fields; the design table gives (name, CHAR length) with **no position column** — positions are cumulative lengths, and they tile to exactly 714. Transcribed as `MATRABA_LAYOUT` in `probe_spain_dgt.py`, spot-verified against real records (INE municipality code, tipo/clasificación/categoría at computed offsets). ~180–190k records/month. Banner line present in the monthly file (the design doc claims it's daily-only — outdated). Encoding latin-1. |
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

| Variant | Filter | Size (2026-05, whole file) | Precedent |
|---|---|---|---|
| `Whole` | Filter C (§4), `IND_NUEVO_USADO = N` | ~114 k | — |
| `Vans` | homologation `N1` (+`N1G`), new | ~13.9 k | Italy_Vans, Luxembourg, Poland |
| `HDV` | `N2` + `N3`, new | ~2.6 k (N3 2.5 k) | Denmark_HDV, Finland_HDV, Poland |
| `Buses` | `M2` + `M3`, new | sub-500 (check exact) | Finland_Buses, Ireland_Buses, Uruguay |
| `2-Wheelers` | category `L*` / tipo 50, new | ~27 k tipo-50 | Albania_2-Wheelers |
| `Used` (imports) | Filter C, `IND_NUEVO_USADO = U` | ~21.7 k U overall | **new axis for southern Europe** |
| `Rental` / `NonRental` | `SERVICIO = A01` (alquiler sin conductor) | **~35 k A01/month** — Spain's rental channel rivals Italy's noleggio | Italy_Rental / Italy_NonRental |
| `Renting` (leasing) | `RENTING = S` | ~34 k | — |
| `Private` / `Industry` | `PERSONA_FISICA_JURIDICA` (D/X) | not yet tabulated | Denmark, Finland |

Sizes are per-month from the probe's distribution tables (whole file — the
per-variant fuel splits need the variant filters applied, a fetcher-side
detail). Rental and Used are clearly big enough to be worth publishing;
Buses is borderline. Each extra CSV costs render time and gallery space.

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
  probe workflow, which runs where `fetch_acea.py` already proved WAF-laden
  sources are workable (browser headers + homepage warmup session).
- GitHub Actions egress is unrestricted; if dgt.es turns out to block GitHub
  runner IPs outright (Austria precedent), the fallback is the same one
  Austria uses: relay through the Cloudflare Worker `/fetch`
  ([20-source-austria.md](20-source-austria.md)).

## 8. Next steps

1. ~~Run the probe~~ **Done** (runs #1–#7, 2026-07-08; results in §3–§5.
   Note: on this branch the probe fires on pushes touching its own files —
   the `workflow_dispatch` path only appears once the file reaches master.
   Drop the temporary `push` trigger when merging).
2. **Maintainer decision on §4b** (DGT-C canonical + backfill vs. ACEA-keep
   + variants-only).
3. Build `scripts/fetch_spain.py` + `fetch-spain.yml` accordingly: Filter C,
   upsert semantics as in `fetch_italy.py`, source `DGT`, sanity check
   (components ≈ TOTAL), cron in the first week of the month, commit-gated
   render dispatch, ACEA cross-check warning. If §4b-option-1: a backfill
   script à la `backfill_italy_rental.py` over the historical monthly zips
   (verify per-year record lengths before trusting offsets).
4. Update [05-flows.md](05-flows.md) (Spain leaves the "practically never
   written" conditional-list note), this doc (from INVESTIGATION to live
   playbook), and the gallery's source/footnote surface (DGT + Asier
   credit).
