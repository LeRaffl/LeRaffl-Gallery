# India (VAHAN) — raw exports & reproduction protocol

India has no reachable API (`scripts/fetch_india.py` is probe-only: VAHAN
resets foreign connections). The series is therefore built from **hand-pulled
Excel exports of the VAHAN4 dashboard**, stored in this folder, and turned into
`data/India.csv` by **`scripts/build_india.py`**.

This file is the single source of truth for *how* to pull, so the next pull is
**identical**. If you change the recipe here, also update the fuel map / source
string in `scripts/build_india.py` and the country's entry in
`docs/architecture/09-glossary.md` + `country_source_stubs.yaml`.

> ⚠️ **VAHAN4 is being retired** ("discontinued after 15 August 2026" banner).
> When it goes, switch to the *New Public Dashboard*; the vehicle-class /
> fuel taxonomy should carry over, but re-verify the labels against the fuel
> map below before trusting a pull.

---

## 1. Dashboard settings (all variants, every pull)

Site: <https://vahan.parivahan.gov.in/vahan4dashboard/> → the **dashboardview**
page.

| Control | Value |
|---|---|
| Type | `Actual Value` |
| State | `All Vahan4 Running States` (36/36) |
| RTO / Office | `All Vahan4 Running Office` |
| Y-Axis | **`Fuel`** |
| X-Axis | **`Month Wise`** |
| Year Type | **`Calendar Year`** |
| Year | one export **per year** across the whole timeline |

Then open the **left filter panel** (the small arrow/refresh box on the left of
the table), tick the variant's classes/categories (§2), **Refresh**, and export
the table to Excel. Repeat for every year.

**File naming:** `<Variant>_reportTable<YYYY>.xlsx` (the year is read from the
sheet title, not the filename, so minor name drift like
`Whole_reportTable.2022xlsx.xlsx` is tolerated — but keep the `<Variant>_`
prefix, it's how the builder assigns the variant).

**Timeline:** currently **2020–present**. VAHAN's pre-2020 state coverage is thin
(and BEV ≈ 0 anyway), so we start at 2020. Old years are stable — you never need
to re-pull them. **Only re-pull the current year** on an update (see §4).

---

## 2. Variant → VAHAN filter (the categorisation)

The gallery anchors variants to **EU vehicle classes** so countries stay
comparable (see `docs/architecture/09-glossary.md`). India's headline `Whole`
is **EU M1 passenger cars** — *not* "all vehicle categories" (that was the old,
retired definition).

### `Whole` = EU M1 (DONE — this is what's in `data/India.csv`)

Filter on **Vehicle Class** (not Category), tick exactly:

- ☑ `MOTOR CAR`  — private passenger cars incl. SUVs (the bulk)
- ☑ `MOTOR CAB`  — passenger-car taxis (≤ 6 pax) = M1
- ☑ `LUXURY CAB` — premium sedan taxis = M1

Together = all M1 passenger cars across ownership types, matching how every
other country counts `Whole`.

> **Do NOT tick — common traps:**
> - `MAXI CAB` → 7–12 pax = EU **M2** (bus), *not* M1. The name is the trap.
> - `QUADRICYCLE (PRIVATE/COMMERCIAL)` → EU **L7e**.
> - `OMNI BUS`, `PRIVATE SERVICE VEHICLE`, `BUS`, `SCHOOL BUS` → M2/M3.
> - `MOTOR CARAVAN`, `CAMPER VAN`, `AMBULANCE`, `HEARSES`, `ADAPTED VEHICLE`
>   → M1 *special-purpose*; excluded for cross-country comparability (other
>   countries exclude these too).

### Commercial variants (NOT yet pulled — recipe for next time)

Pull on **Vehicle Category** (cleaner than class-level for these). Members below
are the *intended* mapping — **sanity-check the counts on the first pull** and
correct here if VAHAN buckets differently:

| Variant | EU class | Vehicle Category to tick |
|---|---|---|
| `Vans` | N1 | `LIGHT GOODS VEHICLE` |
| `HDV` | N2 + N3 | `MEDIUM GOODS VEHICLE` + `HEAVY GOODS VEHICLE` |
| `Buses` | M2 + M3 | `LIGHT PASSENGER VEHICLE` + `MEDIUM PASSENGER VEHICLE` + `HEAVY PASSENGER VEHICLE` |

These do **not** overlap `Whole`: cars sit under the *MOTOR* classes (LMV), the
GOODS / PASSENGER-VEHICLE categories are trucks / buses respectively.

### India-specific variants (optional, NOT EU-mappable)

India's two- and three-wheeler segments are huge but map to EU **L-category**,
not M1/N/M2. Keep them only as India-specific extras (like Canada `Pickups`),
never folded into `Whole`:

| Variant | Vehicle Category to tick |
|---|---|
| `2-Wheelers` | `TWO WHEELER(NT)` + `TWO WHEELER(T)` + `TWO WHEELER (Invalid Carriage)` |
| `3-Wheelers` | `THREE WHEELER(NT)` + `THREE WHEELER(T)` + `THREE WHEELER (Invalid Carriage)` |

---

## 3. Fuel mapping (VAHAN label → gallery column)

The builder collapses VAHAN's ~20 fuel labels with an **ordered** rule set
(`FUEL_RULES` in `scripts/build_india.py`). **Order matters** — the electrified
signal wins over alt-fuel, which wins over the base fuel:

| Priority | Match (uppercased label contains…) | → column | Examples |
|---|---|---|---|
| 1 | `PLUG-IN HYBRID` | `PHEV` | PLUG-IN HYBRID EV |
| 2 | `PURE EV` or `ELECTRIC(BOV)` | `BEV` | both battery-only labels are summed |
| 3 | `HYBRID` | `HEV` | STRONG HYBRID EV, PETROL/HYBRID, DIESEL/HYBRID, PETROL(E20)/HYBRID/CNG |
| 4 | `LPG` | `LPG` | LPG ONLY, PETROL/LPG, PETROL(E20)/LPG |
| 5 | `CNG` | `CNG` | CNG ONLY, PETROL/CNG, PETROL(E20)/CNG |
| 6 | `FLEX-FUEL` or `ETHANOL` | `FLEXFUEL` | FLEX-FUEL(ETHANOL) |
| 7 | `DIESEL` | `DIESEL` | DIESEL |
| 8 | `PETROL` | `PETROL` | PETROL, PETROL(E20) |
| 9 | *(else)* | `OTHERS` | LNG, NOT APPLICABLE, SOLAR, FUEL CELL HYDROGEN, PETROL/METHANOL |

Rationale for the two judgement calls:
- **`PETROL/CNG` (bi-fuel) → `CNG`.** The CNG capability is the meaningful
  classifier (and keeps it consistent with `CNG ONLY`); for BEV-share it's
  ICE either way. India's CNG-car boom is real and worth its own column.
- **Anything containing `HYBRID` → `HEV`, even with a CNG/LPG token**
  (`PETROL(E20)/HYBRID/CNG`): the electrified nature dominates. VAHAN has **no
  consistent MHEV label**, so all hybrids fold into `HEV` — flagged as
  unverified in the glossary/footnote.

`BEV = ELECTRIC(BOV) + PURE EV` (both labels coexist across vintages/RTOs — the
old and new spelling of battery-electric). India-included columns:
`BEV, PHEV, HEV, PETROL, DIESEL, CNG, LPG, FLEXFUEL, OTHERS` (+ computed `TOTAL`).

---

## 4. Current month & provisional data

VAHAN updates **daily**, so:

1. **The running month is dropped.** The builder keeps only months strictly
   before the current calendar month (the "one month back" rule France/Chile/
   China also use). You can export the whole year with the incomplete month in
   it — the builder trims it. `--asof YYYY-MM-DD` overrides "today" for testing.
2. **The last ~2 completed months are flagged `provisional`** in the `notes`
   column. VAHAN keeps backfilling them for weeks as RTOs enter data late.
3. **They converge on re-pull.** The upsert is keyed on `(period, variant)`, so
   re-pulling the current year overwrites the provisional months with the
   settled figures. → On any update, **re-pull the whole current year**.

---

## 5. Rebuild

```bash
python3 scripts/build_india.py          # reads data/raw/india/*.xlsx -> data/India.csv
```

Requires `openpyxl`. After building, render with the normal pipeline
(`R/render_country.R` for India) and update `params.csv` / `weights.csv`.
