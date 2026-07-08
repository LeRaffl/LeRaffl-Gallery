# 28 · Source: Spain (DGT microdata — investigation & automation plan)

**Status: INVESTIGATION.** Spain is live on the gallery, but its pipeline is
only half-automated (see §1). This document records the plan to put Spain on
its own DGT-based fetcher, what has been verified so far, and — critically —
what has *not*. The verification vehicle is
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

**Assumed until the probe confirms** (all encoded as candidates/diagnostics
in `probe_spain_dgt.py`, not as hard-wired truths):

| Assumption | Risk if wrong | Probe behaviour |
|---|---|---|
| Zip URL pattern `…/microdatos/salida/{Y}/{M}/vehiculos/matriculaciones/export_mensual_mat_{YYYYMM}.zip` | 404s | tries 3 pattern variants, logs each status; `--zip-url` override |
| dgt.es WAF tolerates Actions runners with browser headers (ACEA-style warmup) | 403s | logs status + explains 403-vs-404 diagnosis |
| Design PDF auto-parses into (name, position, length) rows via `pdftotext -layout` | layout unknown | dumps raw pdftotext text as artifact for manual transcription |
| Encoding latin-1 | mojibake in labels | decodes with `errors="replace"`, keeps a raw sample artifact |
| Field semantics (codes for clase matrícula, tipo vehículo, servicio) | filter definitions off | prints full value distributions instead of hiding them behind filters |
| Exact publication day-of-month | cron window wrong | run the probe on the 1st–5th for the just-ended month and observe |

## 4. Consistency check (the go/no-go gate)

"Was auch immer wir ziehen, es müsste mit ACEA konsistent sein." The probe
aggregates the gallery fuel split under **three candidate market filters** and
prints per-fuel deltas against the ACEA rows already in `Spain.csv`:

- **Filter A** — EU homologation category `M1`, new vehicles.
- **Filter B** — A + clase matrícula *ordinaria* (excludes diplomatic,
  temporary, historic plates).
- **Filter C** — DGT vehicle *type* turismo/todoterreno, new vehicles
  (ANFAC's own market wording is "turismos y todoterrenos").

Acceptance: the filter whose TOTAL and per-fuel deltas sit consistently
within **~±1–2 %** of ACEA across several probed months becomes the
`fetch_spain.py` market definition. Expected wrinkles, to be documented
rather than tuned away:

- **HEV**: ACEA's "hybrid electric" bucket includes mild hybrids. If DGT's
  `HEV` category is materially narrower/wider, the delta will be systematic —
  that's a bucket-definition difference, not noise. If it's large, the
  honest options are (a) accept and footnote it, or (b) keep HEV from ACEA.
- **REEV**: folded into BEV for comparison (ACEA counts extended-range EVs
  as battery-electric); the probe reports the REEV count separately so the
  fold is auditable.
- **FCEV/HICEV** → OTHERS (matches ACEA, where hydrogen sits outside the
  battery-electric column). Counts are near-zero either way.
- **Autocaravanas/motorhomes** are homologated M1 but are not "turismos y
  todoterrenos" — comparing Filter A vs C exposes whether this matters at
  ACEA-reconciliation scale.
- **Month cut-off**: microdata records carry both fecha de matriculación and
  fecha de trámite; late-processed registrations can shift a few hundred
  units between months depending on which date ANFAC cuts on.

If **no** filter reconciles, Spain stays on the ACEA appender and this doc
gains a postmortem section — same policy as
[14-data-source-gaps.md](14-data-source-gaps.md): no consistency, no switch.

## 5. Variant opportunities (why DGT is worth the effort)

All from the *same* monthly file, i.e. one fetcher run populates every CSV:

| Variant | Filter | Precedent |
|---|---|---|
| `Whole` | winning filter from §4, `IND_NUEVO_USADO = N` | — |
| `Vans` | homologation `N1`, new | Italy_Vans, Luxembourg, Poland |
| `HDV` | `N2` + `N3`, new | Denmark_HDV, Finland_HDV, Poland |
| `Buses` | `M2` + `M3`, new | Finland_Buses, Ireland_Buses, Uruguay |
| `2-Wheelers` | category `L`, new | Albania_2-Wheelers |
| `Used` (imports) | winning filter, `IND_NUEVO_USADO = U` — first Spanish registration of a used (imported) vehicle | Netherlands/Denmark Used discussions; **new axis for southern Europe** |
| `Rental` / `NonRental` | `SERVICIO` = alquiler sin conductor (short-term rental); `RENTING` flag = leasing/renting | Italy_Rental / Italy_NonRental |
| `Private` / `Industry` | `PERSONA_FISICA_JURIDICA` (natural vs. legal person) | Denmark, Finland |

The probe prints the full distributions of every one of these fields, so the
first successful run doubles as the sizing study (are Spanish rental-channel
registrations big enough to matter, like Italy's noleggio? how many used
imports per month?). Decide which variants to actually publish *after*
seeing the numbers — each extra CSV costs render time and gallery space.

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

1. **Run the probe** (Actions → "Probe Spain data (DGT microdata)" →
   defaults probe 2026-04 + 2026-05, both of which have pure-ACEA rows to
   compare against). Cost: one manual click, ~2 minutes.
2. Read the job summary: download OK? design parsed? which filter
   reconciles? variant sizes?
3. If the layout auto-parse failed, transcribe positions from the
   `design_pdftotext.txt` artifact into the future fetcher (one-time,
   ~15 min).
4. Build `scripts/fetch_spain.py` + `fetch-spain.yml` on the verified
   ground: winning filter, upsert semantics as in `fetch_italy.py`,
   source `DGT`, sanity check (components ≈ TOTAL), cron in the first week
   of the month, commit-gated render dispatch. Decide the variant lineup
   from the probe's distribution tables.
5. Update [05-flows.md](05-flows.md) (Spain leaves the "practically never
   written" conditional-list note), this doc (from INVESTIGATION to live
   playbook), and the gallery's source/footnote surface (DGT + Asier
   credit).
