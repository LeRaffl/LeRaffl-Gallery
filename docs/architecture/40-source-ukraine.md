---
country: Ukraine
slug: ukraine
method: file
summary: New- and used-car registration data for Ukraine from the Ministry of Internal Affairs'
  open vehicle register — one record per registration operation, with the register's own fuel,
  brand, model, vehicle kind, gross weight and owner type.
source_name: data.gov.ua — MIA «Відомості про транспортні засоби та їх власників»
source_url: https://data.gov.ua/dataset/0ffd8b75-0628-48cc-952a-9302f9799ec0
source_links:
- label: CKAN API (resource discovery)
  url: https://data.gov.ua/api/3/action/package_show?id=0ffd8b75-0628-48cc-952a-9302f9799ec0
  note: one zip per year (one CSV inside); the current year is re-uploaded monthly, cut at the previous month end
- label: Ukrautoprom monthly market releases (cross-check)
  url: https://ukrautoprom.com.ua/category/news/avtorynok
  note: the carmakers' association publishes new-car, EV and brand totals derived from the same register
underlying: Головний сервісний центр МВС (MIA Main Service Centre) — national vehicle register
auth: none
cadence: twice daily on the 1st–15th, 08:40 and 20:40 UTC — the MIA re-uploads the current year around the 1st of M+1
variants:
- Whole
- Private
- Industry
- Used
- Vans
variant_notes:
  Whole: New passenger cars (register kind ЛЕГКОВИЙ = EU M1), by the register's new-vehicle first-registration codes.
  Private: Whole where the owner is a natural person (PERSON = P).
  Industry: Whole where the owner is a legal person (PERSON = J); Private + Industry = Whole.
  Used: Used passenger cars at their first Ukrainian registration — i.e. used imports.
  Vans: New goods vehicles with gross vehicle weight ≤ 3,500 kg (EU N1).
hev_split: false
hev_note: One combined hybrid value in the register (plug-in, full and mild hybrids together) — stored in the HEV column, shown as "Hybrid", counted inside ICE; there is no PHEV curve.
backfill: record-level register from 2018-09 (the first full month of the current operation codes); older years exist but do not separate new from used cars
scope_note: First registrations only (new or used-import), by the MIA's own operation codes; changes of owner, re-registrations and deregistrations are excluded.
caveats:
- The register has one combined hybrid fuel value — plug-in, full and mild hybrids cannot be told apart, so there is no PHEV curve and plug-ins sit inside ICE.
- New vs used comes from the register's operation codes. Code 105 ("new vehicle from a dealer, imported") only exists from August 2018; before that new and used dealer sales shared one code, so the series starts 2018-09.
- Registrations, not sales. The carmakers' association Ukrautoprom (dealer sales) reports ~3–5 % more new cars; BEV counts agree within ~1 % (see the developer doc).
- EV imports were VAT-exempt until 31 Dec 2025. December 2025 shows a pull-forward spike and 2026 a sharp drop in both new and used BEV registrations — a policy step, not noise.
- Used is a different population from new registrations (used imports, dominated by customs policy); read it next to Whole, not as part of it.
market_breakdown: market/ukraine_top.json
market_class_names:
  HEV: Hybrid
market_class_labels:
  HEV: Hybrid — the register's single hybrid value (plug-in + full + mild; counted as ICE in the curves)
fetcher: scripts/fetch_ukraine.py
workflow: .github/workflows/fetch-ukraine.yml
fragility_doc: docs/architecture/40-source-ukraine.md
data_file: data/Ukraine.csv
---

# 40 · Source: Ukraine (MIA open vehicle register)

**Status: LIVE since 2026-09.** Fetcher `scripts/fetch_ukraine.py` (+ tests
`scripts/test_fetch_ukraine.py`) and `.github/workflows/fetch-ukraine.yml`.
Ukraine is the gallery's second record-level registry after Argentina — and
unlike Argentina's, the Ukrainian register carries a **fuel field**, so
nothing is classified from model names.

The facts below were established by temporary probe workflows (runs of
2026-09-24 on the development branch; since removed): the dev sandbox cannot
reach `data.gov.ua`, the GitHub runners can.

## TL;DR

```
Source:    MIA Main Service Centre (ГСЦ МВС) register on data.gov.ua (CKAN),
           dataset 0ffd8b75-0628-48cc-952a-9302f9799ec0. One record per
           registration operation: op code (+ name), date, brand, model,
           kind, body, fuel, gross weight, owner type (P/J), …
Auth:      None. No login, no key. CSV in yearly zips.
API:       CKAN package_show → resource URLs (ids change on re-upload, never
           hard-code). One zip per year (2013 →), one CSV inside.
Timing:    Current-year zip re-uploaded ~1st of M+1, cut at the month end
           (member "reestrtz31.08.2026.csv", uploaded 2026-09-01 11:02 UTC).
History:   2018-09 → today (new/used operation codes); records back to 2013.
Fuel:      In the record. ЕЛЕКТРО → BEV; ЕЛЕКТРО АБО БЕНЗИН/ДИЗЕЛЬНЕ ПАЛИВО
           → one combined Hybrid bucket (HEV column, no PHEV column).
Variants:  Whole (M1) · Private · Industry · Used (used imports) · Vans (N1).
Checked:   Ukrautoprom Jul-2026: new BEV 421 vs 423, used BEV 3,361 vs 3,333,
           new cars 5,488 vs 5,754 (registrations vs dealer sales).
```

## 1. Why this source clears the bar

The gallery's rule ([14](14-data-source-gaps.md)): direct from the registry or
its recognised body, complete for the market, obtainable without paying or
handing over an ID. This *is* the national register, published by the
ministry that keeps it, on the government open-data portal, under an open
licence. It is complete by construction — every brand, every importer, every
private import. Ukraine was not on any candidate list
([33](33-expansion-candidates.md)) only because nobody had looked: the same
dataset is what Ukrautoprom's monthly market releases are built from.

## 2. Record → CSV row

| Field | Use |
|---|---|
| `D_REG` | period (`dd.mm.yy` → `YYYY-MM`) |
| `OPER_CODE` (2026: merged into `CD.OPER_CODE\|\|'-'\|\|CD.OPERAS`) | scope — first registrations only (below) |
| `KIND` | `ЛЕГКОВИЙ` (passenger car) → M1 variants; `ВАНТАЖНИЙ` (goods) → Vans |
| `TOTAL_WEIGHT` | Vans only: ≤ 3,500 kg (EU N1) |
| `PERSON` | Private (`P`) / Industry (`J`) |
| `FUEL` | fuel column (§3) |
| `BRAND`, `MODEL` | `market/ukraine_top.json` only |

**Operation codes** (the register's own classification — no heuristics):

| Set | Codes | Meaning |
|---|---|---|
| new | 105 | new vehicle bought from a dealer, imported (the bulk of Whole) |
| | 99 | new vehicle bought from a dealer, made in Ukraine |
| | 72 | new vehicle imported by the owner (customs declaration) |
| | 180, 184, 185 | new vehicle first registered by a business (from 2025-11) |
| | 74, 75, 102 | new vehicle — humanitarian import / experimental (a handful) |
| used | 100 | used vehicle bought from a dealer, imported |
| | 70, 71 | used vehicle imported by the owner (customs declaration / certificate) |
| | 76, 77 | used vehicle — humanitarian import |
| | 172 | first registration of imported passenger cars (the 2018 wave) |

Everything else — changes of owner (3xx), re-registrations (4xx),
deregistrations (5xx), temporary military registration (213/215) — is not a
first registration and is ignored. Code **69** ("new vehicles by acceptance
act", ~10 a month) is deliberately left out: before 2018-09 it was mostly old
vehicles, and it is listed every month in the run report instead.

**Why the series starts 2018-09.** Code 105 appeared in August 2018 (660
records, then ~6,000 a month). Before that, code 100 covered *all* dealer
first registrations: in 2013–2018-08, 82 % of its passenger cars were at most
one model year old and 12 % were four or more years old — new and used
mixed. Splitting them by model year would be our heuristic, not the source's
definition, so we don't (invariant 3 spirit: no invented history).

CSV columns: `BEV, HEV, PETROL, DIESEL, OTHERS, TOTAL`; `source` =
`MIA HSC (data.gov.ua)`. Line-level upserts (invariant 2); a row whose
`source` is not ours is never overwritten without `--force`.

## 3. Fuel mapping

| `FUEL` | Column | Note |
|---|---|---|
| `ЕЛЕКТРО` | BEV | |
| `ЕЛЕКТРО АБО БЕНЗИН`, `ЕЛЕКТРО АБО ДИЗЕЛЬНЕ ПАЛИВО`, `БЕНЗИН, ГАЗ АБО ЕЛЕКТРО`, `ГАЗ ТА ЕЛЕКТРО` | HEV — **combined Hybrid** | the register has no plug-in flag; a RAV4 Hybrid, a Volvo XC90 T8 and a 48 V Audi Q8 TDI all carry "electric or …" |
| `БЕНЗИН` | PETROL | |
| `ДИЗЕЛЬНЕ ПАЛИВО` | DIESEL | |
| `БЕНЗИН АБО ГАЗ`, `ГАЗ`, `ДИЗЕЛЬНЕ ПАЛИВО АБО ГАЗ`, `ВОДЕНЬ`, blank, `НЕ ВИЗНАЧЕНО` | OTHERS | LPG/CNG bi-fuel, hydrogen, unknown (Whole 2018-09 → 2026-08: 11,660 of 601,704 = 1.9 %) |

This is the **Türkiye / Georgia / Colombia combined-hybrid convention**
([09](09-glossary.md) "Hybrid"): the HEV column holds every hybrid, there is no
PHEV column, the fuel-split chart labels it "Hybrid", and the BEV/ICE
trajectory counts it inside ICE with no PHEV curve (`has_phev_split = FALSE`,
#210). Could PHEVs be recovered from `MODEL`? No — the register's model
strings are bare (`XC90`, `RAV4`, `Q8`), so the Argentina approach does not
transfer.

## 4. Variants

| Variant | Rule | EU anchor | Volume 2025 |
|---|---|---|---|
| `Whole` | `KIND = ЛЕГКОВИЙ` ∧ new codes | M1 | ~80,000 |
| `Private` | Whole ∧ `PERSON = P` | M1 sub-slice | ~57,500 |
| `Industry` | Whole ∧ `PERSON = J` | M1 sub-slice; P + J = Whole (checked every run) | ~22,300 |
| `Used` | `KIND = ЛЕГКОВИЙ` ∧ used codes | M1, **used imports** (like Netherlands/Spain `Used`) | ~280,000 |
| `Vans` | `KIND = ВАНТАЖНИЙ` ∧ `TOTAL_WEIGHT ≤ 3500` ∧ new codes | N1 | ~5,800 |

**Not produced:** `HDV` (goods > 3.5 t: ~4,000 new a year, BEV ≤ 12) and
`Buses` (~600 a year, BEV ≈ 0) — no signal to fit yet. Both are one filter
away in `variants_for()` if that changes. Motorcycles/mopeds (`МОТОЦИКЛ`,
`МОПЕД`) are EU L-category.

**Resales are not `Used`.** `Used` = used vehicles at their *first*
Ukrainian registration (imports). Changes of owner within Ukraine (op codes
3xx) are the reserved `Resale` variant ([09](09-glossary.md)) — not built.
For scale: IAR's August-2026 EV market of 9,074 BEVs = 504 new (our Whole) +
3,613 used imports (our Used, exact match) + 4,957 domestic resales.

## 5. Governance — what every run checks

| Check | On failure |
|---|---|
| Required columns resolve (both header layouts: 2013–2025 `OPER_CODE`+`OPER_NAME`; 2026 merged op column, `POWER_KWT` added, `N_REG_NEW` dropped) | abort, nothing written |
| Every yearly file in range yields records; > 0.1 % unparsable date/op | abort |
| Target month covered: the extract's cut day (from the member name, e.g. `reestrtz31.08.2026` — **exclusive**, the file ends on 30 Aug) must be within 3 days of the month end | "not published yet", retry next slot |
| A month whose newest record is before its last day | row written with a factual note in `notes` ("MIA extract has no records after …"); listed in the step summary |
| Target Whole ≥ 40 % of the trailing-12 median | not written (`--force` overrides) |
| Unknown `FUEL` strings ≤ 2 % of Whole (else schema drift) | abort; below that → OTHERS + listed in the report |
| Private + Industry + blank-PERSON = Whole; fuels sum to TOTAL, every month | abort |
| First-registration-like op codes outside the two sets | listed in the step summary every run |
| Fetcher + `market_top` regression tests (`test_fetch_ukraine.py`) | the workflow stops before fetching |

The run's step summary also lists the month's top-10 new-car brands, so the
Ukrautoprom cross-check (§6) takes a minute.

**Holes in the published extract.** The closed yearly files miss a few
month-end days: 2019-04-28…30, 2019-09-30, 2019-12-30/31, 2022-02-28 (the
fifth day of the full-scale invasion, when service centres closed) and
2025-12-31 (the 2025 file is cut "31.12.2025", exclusive — so the last day
of the EV-import VAT exemption is not in it). Those rows carry the note; no
value is imputed. For the current year the next monthly upload normally
fills the last day (2026-08-31 arrives with the September extract) and the
re-derived row loses its note.

## 6. Validation against Ukrautoprom

Ukrautoprom (the carmakers' association) publishes monthly totals derived
from the same register. July 2026 (their release of 2026-08-05 / -08-11):

| | Ukrautoprom | this pipeline | Δ |
|---|---:|---:|---:|
| New passenger cars | 5,754 | 5,488 | −4.6 % |
| New BEV passenger cars | 423 | 421 | −0.5 % |
| Used-import BEV passenger cars | 3,333 | 3,361 | +0.8 % |
| Jan–Jul 2026 new cars | ~38,800 | 37,677 | −2.9 % |
| Toyota / BMW / Hyundai / Mazda / Suzuki / Audi | 986 / 308 / 298 / 259 / 194 / 156 | 958 / 309 / 293 / 259 / 193 / 160 | ≤ 3 % |
| Skoda | 693 | 584 | −16 % |

BEV — the headline — agrees within 1 %. The total gap sits almost entirely in
Skoda (assembled in Ukraine by Eurocar, sold partly to state and fleet buyers
whose cars reach the register through other procedures or later); no other
first-registration code carries the missing units. We keep the register's
definition — first registrations — and note the gap rather than patch it.

## 6a. Reading the fit (first render, 2026-09-24)

The new-car BEV share is not a smooth adoption curve yet: it climbs from
0.5 % (2019) to ~15 % (2024), then **spikes** in H2 2025 — 52 % in
December 2025 — as buyers pulled purchases ahead of the end of the EV-import
VAT exemption, and **collapses** to 3–10 % in 2026. The generalized Weibull
fit (20→80 % in ~7 years at first render) is pulled up by that spike and
sits well above the 2026 points; expect it to flatten as post-exemption
months accumulate. Same caveat, same reason, as Argentina's quota-driven
early fit ([39](39-source-argentina.md)). The `Used` series (used imports)
shows the same policy step and is the larger, steadier EV market.

## 7. Outputs

- `data/Ukraine.csv`, `_Private`, `_Industry`, `_Used`, `_Vans` (monthly, 2018-09 →).
- `market/ukraine_top.json` — trailing-12-month top brands and models per class
  (BEV, Hybrid) for Whole, via `scripts/market_top.py`; shown on the source
  page with the class relabelled "Hybrid" (`market_class_names` /
  `market_class_labels` front-matter, generic in `build_source_pages.py`).

## 8. Operations

- **Schedule:** `40 8,20 1-15 * *`. Self-throttles on `data/Ukraine*.csv`
  (target = previous month); a normal run reads the current and previous
  yearly zip (~160 MB, ~2 min) so corrections to either year land. The MIA
  re-uploads past years too (the 2025 zip was refreshed 2026-05-08).
- **Backfill / rebuild:** dispatch with `backfill = true` (all years from
  2018, ~800 MB, ~6 min).
- **Render:** the fetch job dispatches `render-country.yml` once with the
  changed variants (`Whole|Private|Industry|Used|Vans`).
- **After each monthly run:** read the step summary — new FUEL strings,
  unlisted first-registration codes, blank PERSON — and compare the top-10
  brands with Ukrautoprom's release.
- **If the MIA changes the header again:** `resolve_columns()` aborts with the
  new header in the log; add the new name there and a case to the tests.
- **If a new operation code appears** (as 180/184/185 did in 2025-11): it
  shows up under "First-registration-like operations NOT counted"; decide
  new/used from its name and add it to `NEW_OPS`/`USED_OPS` with a test.
