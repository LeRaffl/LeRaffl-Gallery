# 66 · Proposal: primary-register HEV split for Netherlands and Finland

**Status:** proposal, not started. Written 2026-11-19.
**Audience:** the maintainer + whoever implements this later.
**Relationship to the flyer stack (#450–#453, `feat/acea-hev-split`,
`feat/capture-benchmark`):** independent track. Nothing here blocks or is
blocked by the flyer PRs. The ACEA counted-split merge
(`scripts/acea_split.py`, Greece pattern) ships first for Denmark/Finland
as the flyer stack's fallback; this proposal replaces ACEA as the *primary*
source for Netherlands and Finland once built, leaving ACEA as the
cross-check/fallback exactly as Latvia already treats it
([58](58-source-latvia.md): "ACEA … the cross-check of the Whole series …
and the fallback for a month CSDD has not published yet").

## 0. Why this exists

The flyer briefs need a counted HEV row. Six gallery countries have no
native HEV column (`data/*.csv`, HEV blank on every monthly-Whole row):
China, Denmark, Finland, Hong Kong, Latvia, Netherlands. ACEA's release
carries a counted HEV figure for four of them (DK, FI, LV, NL) because
ACEA relays **national automobile manufacturers' associations**, not the
vehicle register — a different institution with a different fuel
taxonomy (confirmed: ACEA's own tables say `SOURCE: NATIONAL AUTOMOBILE
MANUFACTURERS' ASSOCIATIONS`, footnote "Includes full and mild hybrids").

That is why Denmark's statbank TOTAL and ACEA's Denmark TOTAL differ by
fractions of a percent despite being "the same country": statbank BIL53
and the Danish Motor Register (DMR) have **no non-plug-in hybrid value at
all** — every drivmiddel enumeration (Danmarks Statistik's own
documentation, and the weekly `ESStatistikListeModtag` extract) lists only
petrol/diesel/LPG/N-gas/electricity/kerosene/hydrogen/ethanol/**plugin
hybrid**/other. A full or mild hybrid is filed under its combustion fuel,
untagged. There is no primary-source HEV split to fetch for Denmark; ACEA
(or the importers' association ACEA relays) is the only source that has
one. **Denmark is out of scope for this proposal** — it stays on the ACEA
counted-split fallback permanently, not as a stopgap.

Latvia looks like a counter-example but isn't: CSDD's record files are
per-vehicle and daily-fresh, yet [58](58-source-latvia.md) documents
explicitly that the register's fuel field only distinguishes plug-in
hybrids (`Elektrība un benzīns` / `Elektrība un dīzeļdegviela`) — full and
mild hybrids are filed under Benzīns/Dīzeļdegviela with no tag, same gap
as Denmark. **Latvia is also out of scope**: more granular data does not
fix a taxonomy that doesn't exist upstream.

Spain is the pattern to copy, not a country to fix: DGT's microdata
already has `hev_split: true` with its own column
([28](28-source-spain.md)) — proof that a per-vehicle register *can* carry
a real hybrid class, when the registering authority records one.

Netherlands and Finland are the two countries where the register **does**
record the distinction, but the pipeline we currently use doesn't read
it:

| Country | Register field | Values | Current pipeline reads it? |
|---|---|---|---|
| Netherlands | `klasse_hybride_elektrisch_voertuig` (RDW open data, dataset `8ys7-d773` / view `vsxf-rq7p`) | `OVC-HEV` (plug-in), `NOVC-HEV` (full/mild, no plug), `OVC-FCHV`, `NOVC-FCHV` (fuel-cell variants) | No — Swing pivots ([10](10-source-netherlands.md)) only expose `Benzine`/`Diesel`/`Elektriciteit`, the hybrid class is not a Swing dimension |
| Finland | `sähköhybridi` (Y/N) + `sähköhybridin luokka` (Traficom open vehicle data) | `01` off-vehicle charging (plug-in), `02` engine-only charging (full/mild), `03`/`04` fuel-cell (not in use) | No — StatFin table 121d ([12](12-source-finland.md)) has no non-plug-in hybrid driving-power code at all |

Both are real primary sources, on the same underlying register the
current pipeline already trusts for TOTAL/BEV/PHEV — this is not a new
institution, it is a finer field on the register we already use.

## 1. Scope

**In scope:** Netherlands, Finland. One new fetch path per country that
reads the register's own hybrid-class field, produces a counted HEV
column, and reconciles against the existing TOTAL/BEV/PHEV series before
it is allowed to write.

**Out of scope, explicitly:**
- Denmark, Latvia — no upstream hybrid taxonomy exists (see §0). ACEA
  fallback is the permanent answer for Denmark; Latvia's HEV column stays
  blank as documented.
- China, Hong Kong — no ACEA coverage either; out of scope for both the
  flyer stack and this proposal (honest "Combustion + hybrids" label).
- The flyer rendering itself — that is the flyer stack's job. This
  proposal only changes what is in `data/Netherlands.csv` /
  `data/Finland.csv` (and their variant CSVs); the briefs pick up a real
  HEV row automatically once the column is populated, exactly as they
  already do for Greece.
- Daily cadence. Both registers publish on a monthly-ish lag (see §2);
  this is not a Spain-style daily-provisional pipeline. Do not promise
  daily freshness the source does not have.

## 2. Source facts (verified 2026-11-19, re-verify before building)

### Netherlands — RDW open data (Socrata)

- Dataset: `Open-Data-RDW-Gekentekende_voertuigen_brandstof` (`8ys7-d773`),
  view `Elektrische auto's` (`vsxf-rq7p`) exposes the 3-column subset
  (`kenteken`, `brandstof_omschrijving`, `klasse_hybride_elektrisch_voertuig`).
- Parent dataset `Gekentekende_voertuigen` (`m9d7-ebf2`): ~16.9M rows,
  98 columns, one row per licensed vehicle (not per registration event).
  `datum_eerste_tenaamstelling_in_nederland` is the first-Dutch-registration
  date — the field that defines "new this month", already the basis of the
  Swing pipeline's Whole variant.
- Access: Socrata SODA API (`https://opendata.rdw.nl/resource/8ys7-d773.json`),
  SoQL `$where`/`$select`/`$limit`/`$offset`, no auth for read. A month's
  new registrations can be filtered server-side by registration date —
  no need to download the full 16.9M-row table per fetch.
- **Open question (spike must answer):** does `8ys7-d773` carry the
  registration date itself, or must it be joined to `m9d7-ebf2` on
  `kenteken`? If a join is needed, the fetch is two queries per month
  (date-filtered parent → kenteken list → fuel/hybrid-class lookup), not
  one. Confirm row counts and join cost on one real month before designing
  the loop.
- **Snapshot semantics:** RDW open data is the register *as it is today*,
  not a frozen monthly snapshot — same property Latvia's CSDD files have
  ([58](58-source-latvia.md) §caveats: "more than a year back the record
  counts drift up to ~1.5% below the headline table written at the time").
  A vehicle deregistered/exported since its registration month disappears
  from a later fetch of that same month. This is the backward-overwrite
  risk §4 exists to control.

### Finland — Traficom open vehicle data (bulk CSV)

- Dataset: "Ajoneuvotiedot / Open data for vehicles",
  `avoindata.suomi.fi/data/en_GB/dataset/ajoneuvojen-avoin-data`,
  resource `00041d67-966e-48cf-a720-255faf09d55c`.
- ~5.25M rows, ZIP-packed CSV ~202 MB (930 MB unpacked), ISO-8859-1.
  **Whole-register snapshot**, vehicles currently in traffic use — not a
  monthly increment, not a query API. Every fetch downloads the full
  file and filters locally (same shape as Latvia's ~70 MB passenger-car
  record file, an order of magnitude larger).
- Publication cadence observed: material date 30.9.2025 published
  4.11.2025; material date 31.3.2025 published 6.5.2025 — roughly
  **quarterly-to-monthly with a ~5-week lag**, not daily, not reliably
  monthly. The fetch must treat "no new snapshot yet" as normal, not as
  an error, and must not block the StatFin pipeline (which stays primary
  for TOTAL/BEV/PHEV regardless).
- Fields: `sähköhybridi` (true/false), `sähköhybridin luokka`
  (01 = off-vehicle charging / plug-in, 02 = engine-only charging /
  full+mild hybrid, 03/04 fuel-cell, not in use). Classification sheet:
  `Ajoneuvotiedot_avoin_data_luokitukset_24.03.2026.xlsx` on
  `tieto.traficom.fi`. **Open question (spike must answer):** the exact
  column name for first registration date in this CSV, and whether
  "in traffic use" excludes vehicles deregistered since registration
  (same snapshot-drift risk as RDW/Latvia — assume yes until proven
  otherwise).
- No geo-block observed (unlike CSDD); verify from the CI runner's region
  before assuming the Latvia-style relay is unnecessary.

## 3. Architecture (mirrors 28/58, do not invent a new shape)

Per country, one new fetcher (`scripts/fetch_netherlands_register.py`,
`scripts/fetch_finland_register.py` — names TBD in the spike) that:

1. Reads the register's hybrid-class field for the target month's new
   registrations.
2. Aggregates to the canonical CSV columns, **only filling HEV** (and,
   if the reconciliation in §5 passes, optionally PETROL/DIESEL as a
   counted split instead of the current ratio-scale). TOTAL/BEV/PHEV
   stay owned by the existing pipeline (Swing for NL, StatFin for FI) —
   this proposal does not replace those, it adds the missing column.
3. Writes through the same `acea_split.merge`-style gate: the register's
   own TOTAL/BEV/PHEV for the month must agree with the existing CSV row
   within tolerance before the HEV count is trusted (same-month check,
   exactly the Greece/Denmark pattern already in `scripts/acea_split.py`).
4. Is documented in `10-source-netherlands.md` / `12-source-finland.md`
   with the same front-matter fields (`hev_split`, `hev_note`,
   `processing` decision tree, `caveats`) as Spain/Latvia — **written
   before the fetcher merges, not after** (see §6).

ACEA's counted split (`feat/acea-hev-split`) remains wired as the
fallback for any month the register fetch cannot fill (no snapshot yet,
reconciliation refused, fetch failed) — same precedence Latvia already
uses: register first, ACEA fills the gap, never the reverse.

## 4. Backward-overwrite policy (the part that must not be improvised)

Both sources are live snapshots, not frozen history. Re-fetching an old
month can return **fewer** vehicles than the row already committed
(deregistration/export since). This is the exact failure mode Latvia's
doc already names. Rules, non-negotiable:

- **A re-fetch may raise a month's count, never silently lower it.** If
  the new count for an already-committed month is lower than the stored
  value, the fetcher writes nothing for that month and logs a
  `revision-down` event (month, old value, new value, delta, source
  snapshot date) to a per-country revision log committed alongside the
  CSV (e.g. `data/Netherlands_revisions.csv`). A human decides whether
  the drop is a real deregistration correction or a fetch/scope bug.
- **Every write carries its provenance**: source snapshot date, fetch
  date, and whether the row is register-primary or ACEA-fallback, in the
  row's `notes`/`source` fields exactly as the existing pipelines do.
- **No bulk historical overwrite in one run.** Backfill is month-by-month
  with the same gate as a live fetch; a backfill that would change more
  than N months (N set in the spike, suggested 3) in one run stops and
  reports instead of writing.
- **The diff must be reproducible from the log alone**: given the
  revision log and the source snapshot dates, a reader must be able to
  reconstruct why any month's value changed, without re-running the
  fetch. This is the acceptance criterion for "delta nachvollziehbar".

## 5. Reconciliation gate (before any HEV value is trusted)

For each month the register fetch produces:

1. Compute register TOTAL/BEV/PHEV for the month from the same records.
2. Compare to the existing CSV row (Swing/StatFin). Gate: TOTAL within
   1%, BEV/PHEV within 2% (the Greece tolerance — these are the *same
   register*, so the gate should pass almost always; a failure means a
   scope/date-filter bug, not a real divergence, and must stop the write).
3. Only then write HEV (and optionally the counted petrol/diesel split).
4. Cross-check the resulting HEV against ACEA's figure for the same month
   where available. Log the delta; do not gate on it (ACEA is a different
   institution, §0, so a small delta is expected and informative, not a
   refusal) — but a delta above ~10% is a flag for manual review before
   the country switches primary.

**Switch-over criterion:** the register fetch must reconcile cleanly for
a consecutive run (suggested: 6 months, including at least one backfill
month and one live month) before ACEA is demoted from primary to fallback
for that country. Until then, both run and the register's output is
shadow-logged, not written.

## 6. Documentation requirement (explicit, per the maintainer)

Docs have been neglected on this stack; that does not continue here.
Before any fetcher code merges:

- `10-source-netherlands.md` and `12-source-finland.md` get the new
  `processing` decision tree, `hev_note`, `caveats` (snapshot drift,
  publication lag, reconciliation gate), and `source_links` to the exact
  dataset/resource IDs above — same depth as 28/58.
- This proposal's §2 "open questions" must be answered in the doc (not
  left as questions) once the spike resolves them.
- The revision-log format (§4) is documented in the country doc, not
  only in code comments.
- `build_source_pages.py --check` must pass with the updated front-matter
  before the PR is opened.

## 7. Phasing

- **Phase 0 — spike (throwaway, no production code).** One month per
  country, manual: confirm the join/date-field questions in §2, measure
  row counts and fetch cost, confirm the hybrid-class values map cleanly
  to HEV vs PHEV, confirm no geo-block for Traficom from CI. Output: a
  short findings note appended to this doc, and a go/no-go per country.
- **Phase 1 — Netherlands.** Smaller lift: the existing pipeline already
  reads RDW (via Swing); this adds a direct Socrata query for the hybrid
  class on the same register. Build fetcher + reconciliation + revision
  log + doc update. Shadow-run against ACEA for the switch-over window.
- **Phase 2 — Finland.** Larger lift: new bulk-download path (~202 MB),
  new source relationship (StatFin stays primary for TOTAL/BEV/PHEV,
  Traficom register added for HEV only). Same gates, same doc depth.
- **Phase 3 — demote ACEA to fallback** for each country once its
  switch-over criterion (§5) is met. Update `acea_split.MERGED_SOURCE` /
  the flyer stack's source attribution accordingly.

Each phase is its own PR against master, independent of the flyer stack.
No phase merges without the maintainer's explicit OK on the reconciled
output (same rule as the flyer stack: no merge without review).

## 8. Decisions (maintainer, 2026-11-19)

1. **Traficom lag: accepted.** Finland's HEV row may lag the rest of the
   brief by up to ~5 weeks; StatFin keeps delivering TOTAL/BEV/PHEV on its
   own cadence.
2. **Counted petrol/diesel: yes.** Once reconciliation passes, the
   register's counted petrol/diesel split replaces the ratio-scale — not
   HEV-only. Two more columns change, and the doc must say so.
3. **Thresholds (revision-log N, switch-over window): deferred** until
   the first real diffs are visible. The spike reports actual deltas
   before any threshold is fixed.

Primary-source work happens in a separate session; the flyer stack is the
current focus. This branch stays plan-only until that session picks it up.