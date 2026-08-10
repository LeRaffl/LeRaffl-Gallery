# 35 · Proposal: the "Raw Data" tab

**Status:** Built (2026-08). `scripts/build_series.py`, `series/`,
`build-series.yml`, the generated checklist in
[35b](35b-raw-data-quality-todo.md), and the tab itself in `index.html`
(`#rawdata`). This document is the record of why it works the way it does.
**Audience:** the maintainer + whoever implements this later.
**Origin:** an X thread with @AndreasMemmer — a static PNG of the German BEV
share of new registrations over the last 24 months, and the reply *"sone
Graphik live und einstellbar bei mir auf der gallery einzubauen. Monatlich,
2,3,4… wieviele Monate auch immer."*

---

## 1 · What this is

**A viewer for the country CSVs.** Stacked bars, one bar per period, absolute or
relative, with the bar width set by a window control: 1 period, 2, 3, … 12.
Optionally aggregated across countries.

That is the whole feature. No model, no fit, no projection, no `params.csv`.
Every number on this tab is a number that is literally in
`data/<Country>.csv`, or a sum of such numbers.

Why it is worth building: the gallery has ~6 800 rows of hand-collected
registration data across 51 countries, and **there is currently no way to look
at it on the site.** Every existing tab shows model output derived from it. The
raw data is downloadable and diffable in Git, which serves contributors, and
invisible to everyone else.

### 1.1 The window control

The window `N` sums `N` consecutive periods into one bar:

| `N` | What one bar is |
|---|---|
| 1 | One reporting period as filed. **Default.** |
| 3 | A quarter's worth |
| 12 | A year's worth — the same trailing-twelve-month figure the TTM PNGs show |

For quarterly-native countries (§ 3.3) a period *is* a quarter, so the same
control gives 1 quarter, 2 quarters, 4 quarters (= a year). The unit follows the
data; the label follows the unit.

No seasonality lecture in the UI. A stacked bar chart of registration counts is
a thing people can read, and the window is self-evident once labelled. What the
tab *does* owe the reader is what the coloured bands mean — which is § 2, and is
the hard part.

### 1.2 Relationship to the static PNGs

The PNGs stay, permanently. They do a different job:

> **The PNG is the record. The tab is the instrument.**

A committed `images/2026-07/germany_ttm_shares_20260806.png` is a timestamped
file in Git history: it says what the data looked like on that date and cannot
be silently re-rendered into a different claim. The live tab always shows
*current* data, including later revisions — which is what makes it useful and
exactly what disqualifies it as a receipt.

---

## 2 · The category contract

> *"die fuel type definitions … müssen passen, das Problem hatten wir im Fleet
> Chart schon, dass wir aggregieren was teilweise nicht 100 % stimmig in fuel
> type Kategorien ist"*

This is the design problem. A line chart of BEV share can dodge it — one
numerator, one denominator. **A stacked bar cannot:** every band is a claim
about what the remaining bands are, and the bands have to add up to something
the reader believes. Below is what the data actually looks like, and the rules
that follow.

### 2.1 The 51 `Whole` CSVs are not one schema

Ten header shapes, but only two real families, and **the family is a property of
the row, not of the file**:

| Family | Bands available | Files |
|---|---|---|
| **Split-ICE** | BEV · PHEV · (EREV) · HEV · PETROL · DIESEL · (FLEXFUEL) · OTHERS | the majority |
| **Aggregate-ICE** | BEV · PHEV · (EREV) · HEV · ICE · OTHERS | China, South Korea, Thailand, USA, Chile, Colombia |

Chile and Colombia carry *both* an `ICE` column and `PETROL`/`DIESEL` columns.
The petrol/diesel columns are vestigial — Colombia: 0 of 89 rows populated;
Chile: 9 of 137, and `0.0` in all recent rows while `ICE` carries the real
number. A naive "sum every fuel column" double-counts them.

**Rule 1 — resolve the family per row.** If `ICE` is populated, the row is
aggregate-ICE and `PETROL`/`DIESEL`/`FLEXFUEL` are ignored. Otherwise the row is
split-ICE. Both populated and non-zero in the same row is a validation error, not
something to average over.

### 2.1b A reported zero is a measurement, not a blank

The CSVs are wide-but-sparse: an empty cell means "this source did not report
this". A cell holding `0` means something different — the source reported, and
the answer was none. Early PHEV years are full of honest zeros.

Treating the two the same is the single most expensive mistake in this pipeline.
It made a row look like it was **missing a category**, which blocks the residual
rule of § 4.2 Stage 3: Denmark says `PHEV=0` for May 2014 and means it, and the month
fell out of an otherwise continuous year. Distinguishing them recovered **48
periods across 6 countries** — Portugal +24, Iceland +12, Austria +6, Poland +3 —
and cut the total held back from 407 to 260.

**Rule 1b — an explicit `0` in an electrified column is a value; only an empty
cell is unreported.** The asymmetry is deliberate and it is not a hack: a zero in
`BEV`, `PHEV`, `HEV` or `MHEV` is an ordinary observation for most of the last
fifteen years, while a zero in `PETROL` or `DIESEL` never is — no market
registered thousands of cars and none of them petrol. So combustion zeros stay
"unreported" and let the residual rule fill them (Iceland 2018 writes
`PETROL=0, DIESEL=0` against a `TOTAL` of 1,623 and plainly means "not broken
out"), and electrified zeros are believed.

### 2.2 `HEV` does not mean the same thing everywhere

Some sources report a **single combined hybrid bucket** — HEV + PHEV (+ MHEV)
all in the `HEV` column, with `PHEV` left empty. Colombia is the clear case: 0 of
89 rows have a `PHEV` value. Malaysia, Nepal and Israel have their own variants
of this.

This is already documented, and — importantly — **already machine-readable**: the
source docs and `country_source_stubs.yaml` carry a `hev_note` front-matter field
for exactly this, consumed today by `build_source_pages.py`. It becomes a second
consumer here.

**Rule 2 — a country with a combined hybrid bucket gets one `Hybrid` band, not a
`HEV` band and an empty `PHEV` band.** Same colour as the combined bucket in the
TTM charts (`R/plots.R:TTM_FUEL_COLORS` already has a `Hybrid` entry for this
case — reuse it). The legend says "combined" and the definitions panel (§ 5.4)
carries the `hev_note` text verbatim.

### 2.3 Bands are not comparable across countries — so collapse before comparing

Germany reports Petrol and Diesel separately. Thailand reports one ICE number.
Colombia cannot separate PHEV from HEV. Put them side by side with their native
bands and the reader compares three different taxonomies.

**Rule 3 — the stack renders at the *coarsest granularity any selected country
can fill*.** Two modes:

- **As reported** (single country, default): the country's native bands.
- **Comparable** (auto-engaged as soon as a second country is selected, or
  aggregation is on): collapse to the common denominator — Petrol + Diesel +
  Flexfuel → ICE where any member is aggregate-ICE; PHEV + HEV → Hybrid where
  any member has a combined bucket.

Collapsing is always safe (summing bands you already have); un-collapsing is
impossible. So the common denominator is computable from the per-country
capability metadata alone, and the UI states which collapse was applied and why.

**For aggregation this is mandatory, not a preference.** Summing a `PETROL`
column across members where half of them do not report one silently under-counts
petrol and inflates the residual. This is the Fleet-chart failure mode, and the
collapse rule is what prevents it.

### 2.4 The residual: a period either adds up or is not served

Across the 51 `Whole` files, summing each row's resolved bands and comparing to
`TOTAL`: **5,779 of 6,849 rows close to within 0.5 %.** The rest are mostly
early history where `BEV` was collected years before `PETROL`/`DIESEL` —
`data/Germany.csv` 2012-07 sums to 0.4 % of `TOTAL`.

An earlier draft gave the gap its own hatched `Unreported` band. **Dropped** —
it put a validation artifact in front of a reader who came to look at
registrations, and it is the kind of thing that makes a simple chart look
complicated. A stacked bar has to add up; a period that cannot is not served.

**Rule 4 — a period whose bands miss `TOTAL` by more than 3 % is not drawn.**
The tolerance is a rendering question, not an audit one: the stack is drawn *from
the bands*, so what matters is whether the reported mix is complete enough to be
a mix. A 1–2 % disagreement is invisible in a bar; a row missing whole categories
still fails by a mile. At the original 0.5 % this rule alone cost Czechia its
entire 2016–2021 stretch — 62 periods — for discrepancies no reader could see. The chart carries one quiet line instead: *"Germany shown from 2017-01;
the CSV holds back to 2012-01 (60 periods not usable at this quality)."* The
data stays in `data/` and on the source pages, where coverage belongs.

### 2.5 A negative residual is a data error, and one country has them

`Σ bands > TOTAL` cannot be drawn and must not be clamped. It happens:

- **France, 11 rows** where `PETROL + DIESEL` alone exceed `TOTAL`. Worst case
  2020-04: `PETROL 61 796 + DIESEL 33 986` against `TOTAL 20 997` — the COVID
  lockdown month, where the total collapsed but petrol/diesel did not.
- The cause looks structural: **32 of France's 102 petrol/diesel rows repeat the
  previous row's values verbatim** (2020-04 and 2020-05 share `61796 / 33986`;
  2021-04 and 2021-05 share `66149 / 34932`). That is a coarser ACEA figure
  carried across months, the same shape as Germany's pre-2015 BEV values.
- Smaller overshoots elsewhere: Iceland (12 rows), Czechia (14), China (36, all
  under 0.6 % — rounding/OCR noise).

**Rule 5 — a negative residual fails the build** (§ 4.3). Not a render-time
clamp: a chart that quietly hides a 3× overshoot is worse than a build that
stops. France needs a data fix before it can appear on this tab; that is a
separate issue, and this proposal's job is to surface it rather than absorb it.

---

## 3 · Scope of the data shown

### 3.1 `Whole` variants only

Like Builder. `data/<Country>.csv`, no `_Rental` / `_Vans` / `_HDV` / `_Buses`
suffixes. **51 files.** Keeps the selector a country list, keeps the category
contract to one axis of variation, and matches how the rest of the DIY group
already scopes itself.

### 3.2 Native cadence only, contiguous runs as separate blocks

No interpolation, no bridging, no spreading a coarser figure across finer
periods. Cadence is derived from the **observed spacing** of the period labels,
not from `time_interval` — per
[31-proposal-country-source-pages.md](31-proposal-country-source-pages.md), 22
CSVs carry labels that contradict their own spacing.

The obvious implementation ("start at the first monthly period") is wrong, and
so is the careful-looking one ("use the trailing run"). Checked against the data,
4 files have several separate monthly runs of ≥ 12 periods:

| File | Monthly runs (periods) |
|---|---|
| `Italy_Rental.csv` | 63, 75 |
| `Italy_NonRental.csv` | 63, 75 |
| `Singapore.csv` | 37, 78 |
| `Ireland_Buses.csv` | 12, 40, 74 |

(Italy and Singapore are `Whole`-relevant via their siblings' shape; the point
stands for the `Whole` set too.) Taking only the trailing run would discard 63
months of real Italian history. Bridging would invent periods.

**Every contiguous run is its own block of bars.** A gap is a gap on the x-axis —
bars simply stop and resume. Windows never span a gap: a window needs `N`
consecutive periods within one run, otherwise it produces no bar.
`build_source_pages.py:contiguous_runs()` already computes these runs for the
source-page coverage bars; second consumer.

### 3.2b A single row can already *be* a whole cycle

§ 4.2 Stage 4 covers the annual figure spread across twelve rows. The same practice has
a second shape, and it needs the opposite treatment: the annual figure written
onto **one** row, with the rest of the year simply absent. Romania is one row per
June from 2010 to 2017 inside an otherwise monthly file; Greece has a single 2015
row; Uruguay two; Australia and Canada open the same way.

Read as a month, that row is a spike of the wrong order of magnitude — Romania
2017 landed at **106,873 a month against 10,910 either side, a factor of ten**,
which is exactly the "Balkenhöhen kommen mir nicht richtig vor" the maintainer
reported. Read as a hole, twelve years of Romania vanish.

**Rule 8 — a row labelled `yearly` (or `quarterly`) that is the only row in its
calendar year (quarter) stands for that whole cycle, and is drawn one cycle
wide at the cycle's end.**

The discriminator is the maintainer's own `time_interval` column, and it is the
only signal here that needs no threshold. The two alternatives both fail on real
data:

- **Magnitude alone** ("a row 12× its neighbours is annual") flags Ireland's
  every January/February/March/July and the UK's every March/September — real
  plate-change peaks, not annual figures. A detector tuned to 2.2–4.5× and
  7–18× returned 92 rows in 14 countries, and most of them were seasonality.
- **Spacing alone** ("rows 12 months apart are annual") needs a run to establish
  a cadence, so it misses Greece's single row and Uruguay's pair, and it cannot
  tell a yearly stamp from a hole — Singapore's 2019 is one surviving month
  inside a monthly file, not an annual figure.

Trusting the label only when it is the *whole story for that cycle* is what keeps
it safe. Singapore's 2018 is labelled `yearly` for twelve rows of genuinely
monthly totals; 2019-01, its one surviving row, is labelled `monthly`. Neither
is touched by this rule. It fires on **108 rows in 7 countries**, all verified
against the files, and Romania and Greece go from 8 dropped periods each to zero.

### 3.3 Quarterly-native countries are in, at quarterly resolution

**Canada** (StatCan's cube is quarterly) and **Georgia** never have monthly data.
They are not excluded — they render as quarterly bars, and the window control
offers multiples of a quarter (1, 2, 4, 8 …). The control means "N periods"
throughout; only the label changes with the country.

Mixing a monthly and a quarterly country in one comparison collapses the shared
axis to quarters, by the same logic as § 2.3: aggregate up, never split down.

---

## 4 · Backend

### 4.1 Why an artifact rather than reading the CSVs in the browser

The Compare tab already fetches `data/<Country>.csv` client-side
(`fetchCompareObs()`, `COMPARE_OBS_CACHE`), so this is a real option. The reason
not to: **§ 2 and § 3 are the feature**, and they are not chart code.

Per-row family resolution, the combined-hybrid lookup, per-column granularity,
cycle recovery, band folding and reconciliation are a body of rules with
documented exceptions per country. In the browser that is a `switch` on country
name inside a render path, re-run on every slider drag, with no test harness and
no way to fail loudly. At build time it runs once, has a `--check` mode, and
blocks a bad merge.

`data/` is an editor-friendly *source* format (principle 6). This adds a serving
format — a projection of the CSVs, not a replacement.

### 4.2 The generator, stage by stage

`scripts/build_series.py`, alongside `build_schedule.py` and
`build_source_pages.py`. Python because `observed_cadence()`, `contiguous_runs()`
and the `hev_note` front-matter reader already live there, and because no other
build-time generator needs an R toolchain.

The whole file is one function per country, run over `data/*.csv` filtered to
names without an underscore (the `Whole` set; `Italy_Rental.csv` and friends are
variants, § 3.1). **Order matters between every stage below** — several of them
were wrong the first time precisely because they ran too early or too late, and
each such case is recorded here so it is not re-broken.

---

#### Stage 1 · Parse and establish the native step

Keep rows whose `period` matches `YYYY` or `YYYY-MM`; sort by month index
(`year*12 + month-1`, with a bare year sitting at July so it lands mid-cycle).
Fewer than 3 usable rows → the country is skipped entirely.

```python
gaps = [b - a for a, b in zip(idx, idx[1:])]
step = max(set(gaps), key=gaps.count)      # modal spacing, NOT time_interval
if step not in (1, 3, 12): return None
```

**Why the modal spacing and not `time_interval`:** 22 of the files carry a label
that contradicts their own row spacing (§ 3.2). Singapore labels twelve rows of
real monthly totals `yearly` in 2018 and twelve more `quarterly` in 2020. The
spacing is a fact about the file; the label is an annotation, and it is trusted
in exactly one place (Stage 5b) under a condition that makes it self-checking.

#### Stage 2 · Resolve bands per row

```python
if ICE is populated:  v["ICE"] = ICE            # PETROL/DIESEL/FLEXFUEL ignored
else:                 PETROL, DIESEL → own bands
                      FLEXFUEL, ETHANOL → FLEXFUEL
                      GAS, CNG, LPG     → OTHERS
if hybrid_combined:   v["Hybrid"] = HEV         # § 2.2
else:                 PHEV, EREV, HEV, MHEV → own bands
BEV → own band;  OTHERS → added to whatever the gas fuels already put there
```

`hybrid_combined` is decided **per file**, not per row: *any* `HEV` populated and
*no* `PHEV` populated anywhere. Deciding it per row would flip the band set
mid-series the first month a country starts reporting PHEV separately.

**Exception, and it is load-bearing (§ 2.1b):** the population test is
`is not None` for the electrified columns and truthiness for the combustion ones.
A reported `0` in `BEV`/`PHEV`/`HEV`/`MHEV` is a measurement; a `0` in
`PETROL`/`DIESEL` never is. Getting this wrong cost 48 periods across six
countries and is invisible in every sum check, because a missing zero looks
exactly like a missing column.

#### Stage 3 · The unnamed remainder is combustion

```python
ev_cols  = electrified bands populated ANYWHERE in this file
ice_cols = ("ICE", "PETROL", "DIESEL", "FLEXFUEL")
for each row with TOTAL > 0:
    if any ice_col already in the row:      skip   # never overwrite a split
    if not every ev_col present in the row: skip   # the remainder is ambiguous
    rest = TOTAL - Σ bands
    if rest / TOTAL > 0.05: v["ICE"] = rest
```

Türkiye 2019 knows BEV, hybrids and the market total and nothing else; Germany
2012–2016 knows BEV/PHEV/HEV and the total. What is left in such a row cannot be
anything but petrol, diesel or LPG, because every electrified category is already
named. Calling it `ICE` is a statement about what is missing and the only honest
one available — the alternative is to serve nothing.

**Both guards are necessary and both have a counter-example.** Without the first,
a partially-reported split (petrol filled, diesel not) gets papered over.
Without the second, France 2015–2017 — which knows only BEV and PHEV, with `HEV`
appearing in 2021 — would have its hybrids silently folded into `ICE` for six
years while the same file draws a separate hybrid band from 2021. That is the
one place where refusing to draw is the correct answer, and it is why France
still holds back 72 periods (§ 8.1).

#### Stage 4 · Granularity is a property of the (column, period) pair

The maintainer's own account of how these files were built: where one series had
monthly numbers and another only annual, the annual one was divided by 12 (or
the quarterly one by 3) and the monthly one left alone, because that suited the
Weibull fit. So Hungary 2018 has a genuinely monthly `BEV` sitting next to a
quarterly `PETROL` in the same row. **Assuming one granularity per row is what
forced those rows to be thrown away wholesale.**

`gcol[column][row]` holds a granularity in months, starting at `step`.

```python
for each column:
    find maximal runs of EQUAL, non-zero values
    if run length >= 3 and (value is non-integer or value >= 1% of TOTAL):
        span = (12 if run >= 6 else 3) * step
        gcol[col][every row in the run] = max(current, span)
```

Three details, each of which was wrong at some point:

- **Always SUM the cycle**, never take the repeated value once. An earlier
  version assumed a repeated integer was a quarterly total stamped into three
  rows. The neighbour years disprove it: Slovakia 2018 (repeated) sums to
  101,271 against 101,417 in 2019 (natively monthly), while take-once gives
  33,757 — a 3× understatement. Belgium, Bulgaria, Estonia and Lithuania are the
  same shape.
- **The materiality gate earns its keep**: without it, small integers that repeat
  by coincidence (a country with 2 BEVs three months running) are read as a
  smear. Switching it off costs **133 periods across 28 countries**.
- **Snap to 3 or 12**, not to the raw run length, so granularity always lands on
  a real calendar cycle instead of an invented 7-month one. Worth ±1 period; kept
  for the invariant, not the count.

**Known blind spot.** This detector finds *copied* values, not *interpolated*
ones. France 2018–2020 carries petrol/diesel that drift smoothly (177,040 /
177,847 / 180,120) against real monthly totals, missing by up to 22 %. Nothing
here recovers that, and nothing should guess at it — it is listed in
`35b-raw-data-quality-todo.md` as data work.

#### Stage 5b · A row alone in its cycle already IS that cycle

The second shape of the same practice: the annual figure written onto **one**
row, the rest of the year absent (§ 3.2b).

```python
lab = row.time_interval.lower()
cyc = 12 if lab == "yearly" else 3 if lab == "quarterly" else 0
if cyc > step and this is the ONLY row in that calendar cycle:
    whole[row] = cyc
    gcol[every column][row] = max(current, cyc)
```

This is the only place `time_interval` is trusted, and the "only row in its
cycle" condition is what makes trusting it safe: Singapore's 2018 is labelled
`yearly` for twelve rows and is therefore untouched, and its 2019-01 — the one
surviving row of that year — is labelled `monthly` and stays a month.

Neither of the two obvious alternatives works, and both were tried:

| Approach | Fails on |
|---|---|
| Magnitude ("12× its neighbours ⇒ annual") | Ireland's every Jan/Feb/Mar/Jul and the UK's every Mar/Sep are real plate-change peaks. A detector tuned to 2.2–4.5× and 7–18× returned 92 rows in 14 countries, mostly seasonality. |
| Spacing ("rows 12 months apart ⇒ annual") | Needs a run to establish a cadence, so it misses Greece's single 2015 row and Uruguay's pair — and it cannot tell a yearly stamp from a hole. |

#### Stage 6 · Reconcile every ORIGINAL row, before aggregating anything

A row that does not add up must not be folded into a cycle, or the cycle inherits
the error silently. Four rejections, in this order:

| Test | Rationale |
|---|---|
| `TOTAL` missing or ≤ 0 | nothing to render a share against |
| EV-only row (combustion side **exactly** zero while neighbours carry thousands) | only the EV columns were filled and `TOTAL` computed from them. The test is the *exact* zero, not a collapsed total — April 2020 is a real lockdown trough in a dozen countries and must survive |
| `OTHERS` > 80 % of `TOTAL` | the source broke out almost nothing; a stack of 99 % grey is a faithful rendering of the file and a useless chart. Japan 2012–2019 sits at 99.5 % |
| \|Σ bands − TOTAL\| / TOTAL > **3 %** | the mix is not complete enough to *be* a mix |

**The 3 % tolerance is a rendering decision, not an audit one.** The stack is
drawn from the bands, so what matters is whether a reader could see the
disagreement. At the original 0.5 % this rule alone cost Czechia its entire
2016–2021 stretch — 62 periods — for discrepancies invisible in a bar. Tightening
it back costs **73 periods across 7 countries**.

**The `OTHERS` test must run HERE, before Stage 7.** Moving it after aggregation
(where it also "works") changes which rows Stage 7 sees, and Japan then folds its
hybrids away on the strength of eight pre-2020 years that never reach the chart.

#### Stage 7 · One band set for the whole series

A band that exists for only part of a series is a **definition change**, not a
market change. Czechia has no `HEV` column before 2022; the hybrids were inside
`PETROL`, and it shows — petrol runs 69.7 % of the market, drops to 55.0 % the
month `HEV` appears, and folding `HEV` back gives 69.8 %. Drawn as two bands
that is a cliff the reader has to be told to ignore. Colour cannot fix it: the
step is in the geometry.

```python
for (child, parents) in (HEV→PETROL|ICE, MHEV→PETROL|ICE,
                         FLEXFUEL→PETROL|ICE, EREV→PHEV):
    if child missing from > 40 % of the DRAWABLE rows and >= 24 drawable rows:
        fold child into the first available parent, for every row
```

**Decided on the drawable set, not the raw file** — that is the whole subtlety.
Deciding on the raw file folds Japan's hybrids away because of eight undrawn
pre-2020 years, and Norway's because of seventeen early months. Which means
Stage 6 has to run first, and then run **again** after a fold, because folding
changes the band set and therefore the sums. The prototype does exactly that:
`reconcile() → apply_folds() → reconcile()`.

#### Stage 8 · Aggregate to whole calendar cycles

`G[row] = max(gcol[c][row] for c in cols)` — the coarsest granularity in the row
governs the row, because a stack cannot mix resolutions.

```python
if G == step:            emit as-is, stamped at the CYCLE END
elif whole[row]:         emit as-is, stamped at the cycle end, width = whole[row]
else:                    collect the calendar cycle at granularity G;
                         emit only if the cycle is COMPLETE; sum every column
```

- **Stamped at the cycle end** in all three branches. A quarterly file stamps its
  rows on the middle month of the quarter (Canada, Georgia: Feb/May/Aug/Nov); if
  the native branch keeps that stamp while the aggregated branch uses the cycle
  end, a quarterly bar overlaps the yearly bar before it by one month.
- **Completeness is `idx[last] − idx[first] + step == G` and
  `idx[last] % G == G − step`** — a whole cycle, aligned to the calendar, not
  just G months of rows. A partial cycle is dropped rather than drawn short,
  because a half-year summed and drawn a year wide is a lie about the level.
- The `whole[row]` branch is the exception to completeness: one row *is* the
  cycle, so there is nothing to collect.

#### Stage 9 · Emit

```json
{ "country": "Romania", "slug": "romania", "source": "ACEA",
  "step": 1, "ice_split": true, "hybrid_combined": false,
  "held_from": "2010-06", "held_to": "2026-06",
  "dropped": 0, "coarse": 12, "residual_ice": 0, "folded": [],
  "m": [24131, 24143, "…"],          // month index of each cycle END
  "g": [12, 12, "…"],                // months the observation covers
  "t": [309952.0, 176555.0, "…"],    // TOTAL, ≡ Σ bands by construction
  "b": { "BEV": [...], "PETROL": [...], "DIESEL": [...], "OTHERS": [...] },
  "why": { "2018-02": "bands miss TOTAL by +10.5%" } }
```

Two properties the client relies on and must never lose:

1. **`t[i] ≡ Σ b[*][i]`** for every period. There is no `unreported` band — an
   earlier draft had one and it was dropped (§ 2.4): it put a validation artifact
   in front of a reader who came to look at registrations.
2. **`m` is strictly increasing and `g` divides its own cycle**, so the client's
   window walk (`m[j-1] === m[j] - g[j]`) is the only contiguity test it needs.

`why` is what `35b-raw-data-quality-todo.md` is generated from — one line per
held-back row, in the generator's own words, so the checklist can never drift
from the code that produced it.

### 4.3 The window function lives on the client, and why

Everything above is per-period. The trailing window is per-*view* — it changes
with a slider — so it runs in the browser over the emitted series. It is ~25
lines and it is the other place subtle things happen:

```js
for i from the newest period backwards:
  walk back accumulating g[] until >= N months
  contiguity: m[j-1] === m[j] - g[j]        // never bridge a gap
  emit a bar only if months === N and N % gmax === 0
  else if N < g[i]: draw the coarse period, scaled by N/g[i]
```

- **Accumulate `g[j]`, not row counts.** Counting rows skips every recovered
  quarterly stretch — Belgium showed nothing before 2022 until this was fixed.
- **`N % gmax === 0`** is the rule the user asked for in his own words: a
  quarterly stretch appears at T3M, T6M, T12M and not at T1M or T2M; a yearly
  stretch only at multiples of 12.
- **No alignment test against the series end.** An earlier version required
  `(anchor − m[i]) % gmax === 0`, which rejected every calendar-year row in any
  file that does not end in December (Japan). The cycle model already guarantees
  alignment; the extra test was redundant and wrong.
- **Rolling, not tiling.** One bar per period, each summing the N months behind
  *it* — 2026-07+06 then 2026-06+05, not 2026-07+06 then 2026-05+04.

### 4.4 Validation, `--check` mode

Mirrors `build_source_pages.py --check`: runs on PRs, writes nothing, exits
non-zero on a fatal.

| Check | Severity |
|---|---|
| Duplicate periods in one file | fatal |
| `ICE` and `PETROL`/`DIESEL` both populated non-zero in one row | fatal — § 2.1 |
| A negative value in any band column | fatal — see below |
| `hev_note` present but `PHEV` also populated | fatal — metadata and data disagree |
| Emitted `t[i] ≠ Σ b[*][i]` (within float epsilon) | fatal — the invariant the client assumes |
| A band at exactly zero between two populated, non-trivial neighbours | recorded |
| `time_interval` contradicts observed spacing | recorded |
| Every held-back row, with its reason | recorded → `35b` |

**Negatives are fatal and nothing else catches them.** `Poland 2021-01` carries
`OTHERS = −3,765.8`; Poland has seven such rows, Romania six, Norway one. They
pass reconciliation because a negative band still lets the row sum to `TOTAL`,
and they pass rendering because a zero-height rectangle is invisible. Only an
explicit sign check finds them — which is the argument for `--check` existing at
all.

**`--check` fails, the build does not.** Both paths compute the same list; only
`--check` exits non-zero. The gate belongs on the PR, where it stops a *new*
impossible value from being merged. Making the master build fail as well would
stop `series/` regenerating until an old defect is fixed, which serves a stale
tab to every reader in order to punish a row nobody is looking at. The row
itself is held back either way (§ 4.2 stage 6), so nothing wrong is ever drawn —
the 14 negatives currently in the data cost Poland, Romania and Norway their
affected cycles and cost the other 48 countries nothing.

**A zero band can vanish without breaking any sum.** `data/Colombia.csv` carries
`BEV = 0.0` for 2025-07, between 1,143 in June and 1,647 in August, and the row
still closes perfectly because `ICE` is a residual that absorbed the missing
cars. Recorded rather than fatal — Colombia 2020-04 is the April lockdown and may
be real.

### 4.5 CI wiring

New workflow `build-series.yml`:

- **Trigger:** `push` on `master`, path filter `data/**`, plus
  `workflow_dispatch`. One rule catches every writer — the 29 fetchers, manual
  commits, merged submission PRs — instead of chaining a dispatch into 29
  workflow files.
- **Writes** `series/**` and `docs/architecture/35b-raw-data-quality-todo.md`.
  Since the trigger filters on `data/**`, its own commit cannot re-trigger it.
- **On PRs:** `--check` only. A submission PR that breaks the category contract
  is rejected before merge.
- Not folded into `build-manifest.yml`, which is keyed on `images/**`.

### 4.6 If you change one thing, check the other

The rules interact, and the interactions are not obvious from the code. This is
the table to read before editing `build_series.py`.

| If you touch | Re-check | Because |
|---|---|---|
| Stage 2 population tests | Stage 3 residual, Denmark 2014-05 | a zero read as a blank makes a row look incomplete |
| Stage 3 guards | France 2015–2020, Uruguay 2021–22 | loosening them folds hybrids into ICE for years that have no hybrid column |
| Stage 4 thresholds | Slovakia 2018 vs 2019, Belgium 2018 | the sum-vs-take-once question, worth 3× |
| Stage 5b label trust | Singapore 2018/2019, Ireland Jan, UK Mar | the discriminator is "alone in its cycle", not magnitude |
| Stage 6 ordering | Japan hybrids, Norway 2008 | the `OTHERS` gate must precede the fold decision |
| Stage 6 tolerance | Czechia 2016–2021 | 62 periods sit between 0.5 % and 3 % |
| Stage 8 stamping | Canada/Georgia 2016→2017 seam | mid-quarter stamps overlap the yearly bar before them |
| The client window fn | Belgium pre-2022, Japan's non-December year end | accumulate `g`, and do not re-add an alignment test |
| The emitted schema | the `t ≡ Σ b` invariant, `35b` generation | the client stacks what it is given and never re-derives |

The empirical method behind those numbers is worth keeping: every rule was
switched off in turn and the output diffed against the full run (§ 7c). Two rules
survive on judgement rather than counts, and are labelled as such — the EV-only
detector (currently catches nothing, kept as insurance) and the snap-to-3/12.

### 4.7 What this does not add

No Worker, no API, no secret, no database, no frontend build step, no new CDN
dependency (Plotly is already loaded). Operating principle 4 — static-first on
the read path — holds.

### 4.8 Size

51 files, counts only, non-native periods dropped, gzipped by Pages. The full
prototype payload is **319 KB uncompressed** for all 51 series including the
`why` map; well under the 1.4 MB `data/` occupies today. Per-country files so the
tab fetches only what is selected and a single-country update invalidates one
cache entry; mirrors `COMPARE_OBS_CACHE`.

---

## 5 · Frontend

### 5.1 Name and placement

**"Raw Data"**, in the Builder group, with the group renamed **"DIY Curves" →
"DIY Charts"** (the tab has no curve in it):

```
DIY Charts:  Builder · Compare · Raw Data · Fleet
```

"Raw Data" over "Monthly" because it says what the tab is — the CSVs, drawn —
rather than one of its settings, and because it stays accurate for the quarterly
countries.

**Own tab, not a Builder sub-tab.** Thematically it is Builder's neighbour, and
that is what the group and cross-links are for. Structurally: Builder's bootstrap
loads `params.csv` + `weights.csv` + aggregate state this tab uses none of; and
deep links are the point (§ 5.3) — `#rawdata?c=Germany&n=1` is a link you paste
into a reply, `#builder?sub=rawdata&…` is a level deeper and couples two URL
grammars. Builder gets a "see the raw data" link that opens this tab pre-filled
with the current country, and back.

### 5.2 Controls

| Control | Default | Notes |
|---|---|---|
| Country | Germany | Multi-select; a second selection engages Comparable mode (§ 2.3) |
| Window `N` | 1 period | Slider 1–12 (quarterly countries: multiples of a quarter), presets `1 / 3 / 12` |
| Timeframe | **all bars** | all / 5y / 2y |
| Units | absolute | Toggle to relative (100 % stacked) |
| Aggregate | off | Sums selected countries into one stack; forces Comparable mode |
| Export | — | PNG and CSV of exactly what is plotted, plus a QR of the settings URL (**on by default**) |
| Presets | — | *All* / *None* / one per region, reusing `COUNTRY_REGION` from `index.html` rather than inventing a second mapping |
| Axes | Per chart | *Same everywhere* forces one shared time range and, in absolute units, one shared y scale across the small multiples |

### 5.3 Rendering and state

- **Hand-drawn SVG, not Plotly.** This is the one place the tab differs from
  Builder/Compare/Fleet, and the plan said Plotly. Four reasons it went the other
  way, in order of weight:
  1. It renders **up to 51 charts at once**, and 51 Plotly instances are not
     fast. The SVG path draws all 51 in well under a second.
  2. **The bar geometry is the feature.** Variable widths per granularity, a bar
     centred on the window it covers rather than on its end period, cycle labels
     thinned by pixel distance — every one of those was a bug at some point.
     Owning the geometry is worth more here than owning a hover tooltip.
  3. The `@LeRaffl` tag, the generation timestamp and the settings QR are **baked
     into the image**, so a screenshot carries its own provenance. Inside a
     Plotly layout that is annotation gymnastics.
  4. It keeps ~1 MB of Plotly off a tab that needs none of it.

  The cost is real and should be stated: no zoom, no pan, no modebar, and a
  tooltip we maintain ourselves. For a chart whose whole job is "show me the
  filed numbers", that trade is the right way round.
- **Lazy init** on `hashchange`/`DOMContentLoaded`, the same deferred pattern as
  `loadFleetWhenActive()`, so nothing is fetched until the tab is opened.
- **Band colours from the Fleet tab's palette** (`FE_C` in `index.html`), which
  is already built for the dark surface Builder and Compare use, re-stepped
  where two adjacent bands were not tellable apart. Every pair now clears
  ΔE2000 15 against its stack neighbours.
- **`ICE` comes from the R TTM palette, not from Fleet** — `R/plots.R:
  TTM_FUEL_COLORS` has an `ICE` entry, `FE_C` does not, and this tab draws the
  same band the TTM PNGs draw. R's value is `#692500`, chosen for a white ggplot
  panel where it measures 11.3:1; on `#0f1525` it measures **1.62:1** and the
  largest band in the stack vanishes. The tab uses `#a65832` — the same hue and
  chroma at L\*46, 3.52:1 on the dark surface and ΔE2000 17.6 from R's original,
  which is close enough that a reader who knows the PNGs reads it as the same
  brown.

  Borrowing Fleet's `Petrol #7b8db0` for `ICE` was the other candidate and it
  fails on the numbers: **ΔE2000 12.9 against `PHEV`**, which sits directly above
  `ICE` in every aggregate-ICE stack. `ICE` and `DIESEL` staying different
  colours is deliberate and costs nothing — a country reports one or the other,
  never both in the same stack, and they mean different things.
- **Run blocks** (§ 3.2) render as gaps in the category axis, not as bridged bars.
- **A bar sits over the months it is drawn as wide as** — not over its end month.
  Centring on the end period is correct for a monthly bar and wrong for every
  coarse one: the mockup drew Romania's 2010 bar from mid-2010 to mid-2011, half
  a cycle late, and the left-edge clamp then shoved it back on top of the 2011
  bar so the two overlapped in a visible pale seam. Every yearly bar in the tab
  was a half-year out of place, and every quarterly bar six weeks. The centre is
  `to − (width_in_months − 1) / 2`, which is a no-op at monthly resolution.
- **Prefix sums per run**, so a window is two lookups and dragging the slider is
  O(1) per bar. Debounce with the existing helper.
- **`SERIES_CACHE`** keyed by slug, same shape as `COMPARE_OBS_CACHE`.

**Deep links.** `…/#rawdata?c=Germany&n=1&t=24&u=abs` has to work — pasting a
configured chart into a reply is the use-case the thread started from. Today
`activateTabByHash()` does `hash.replace('#','')` → `getElementById('tab-'+id)`,
so a query string falls through to About. Contained change: split on `?` before
the lookup (existing tabs unaffected), pass the `URLSearchParams` to the tab's
init, write state back with `history.replaceState`. Also what makes the
Builder ↔ Raw Data cross-links work.

### 5.4 The definitions panel

The one piece of explanation the tab owes the reader, and the answer to *"sie
brauchen nur Kontext was sie da sehen"*. Below the chart, driven entirely by
`index.json`, changing with the selection:

- **What each visible band means** — one line each, from `definitions`.
- **What this country cannot separate** — the `hev_note` verbatim where present
  ("Colombia reports hybrids as one combined bucket"), and an aggregate-ICE note
  where `ice_split` is false.
- **What was collapsed and why** — in Comparable mode: *"Petrol and Diesel merged
  into ICE because Thailand does not report them separately."*
- **What `Unreported` is** — stated as the absence of a measurement, not a fuel,
  with the affected span (*"Germany: petrol/diesel from 2015-01; earlier bars
  show BEV against the market total only"*).
- **Source and freshness** — source name, last period, link to
  `sources/<slug>.html`.

No seasonality warning at `N = 1` or `N = 12`. Users can read a bar chart; what
they cannot do is guess that Colombia's yellow band means something different
from Germany's.

### 5.5 Cost to `index.html`

~428 KB / ~9.5k lines today; this adds ~400. Acceptable, no split proposed — but
this is where a `js/` extraction would start if the single-file approach stops
paying.

---

### 5.5b The default country is the visitor's own

Asked for as a wish ("ideal wär fast Default = Land der abrufenden IP, aber das
is viel zu viel verlangt"), and it is not too much: **no IP lookup is needed.**
The browser already names the visitor's place —
`Intl.DateTimeFormat().resolvedOptions().timeZone` returns `Europe/Vienna`, and
an IANA zone maps to a country in a ~55-entry table. No request, no third-party
service, no consent question, nothing to rate-limit, and it works offline.

Zones we have no series for fall back to Germany. `Africa/Cairo` → Germany;
`Europe/Vienna` → Austria, `Asia/Tokyo` → Japan, `America/Los_Angeles` → USA,
`Pacific/Auckland` → New Zealand.

Language (`navigator.language`) is the obvious alternative and is worse: a
German-speaking visitor could be in Germany, Austria or Switzerland, and half the
world browses in `en-US` regardless of where they are.

### 5.7 What the aggregate is allowed to be made of

A country whose file needed reconstruction to be drawable is fine on its own
chart — the footnote underneath says so. Summed into an aggregate it silently
lends that reconstruction to the total, and nobody reading a "world" line is
going to go looking for which member contributed a divided-out annual figure.

**The combined chart is therefore built only from series that came out of their
CSV complete** — no discarded periods — and says so: *"35 of 51 selected, summed
— complete data only"*, with *"15 left out as incomplete"* in the subtitle. A
toggle switches to all selected for anyone who wants it.

Two things make this better than the alternative of hand-picking a "perfect"
list:

- **It is derived, not curated.** The tier falls out of the same checks that
  decide whether a period is drawable at all, so it cannot drift away from what
  the charts show.
- **It does not silently drop the big markets.** A fixed "only pristine sources"
  list would have excluded Germany, the UK, Italy, Spain and the Netherlands —
  an aggregate missing most of Europe's volume. Judging on *completeness after
  recovery* keeps them in.

It also, unexpectedly, produces a **longer** series: dropping the ragged members
removes the constraints that were pinning the common span, so the complete-data
aggregate spans 13 periods from 2023-02 where the all-members one manages 12
from 2023-08.

### 5.6 Layout at scale

Selecting a region — or all 51 — is a supported action, so the layout has to
survive it rather than assume two or three countries.

- **A combined chart sits above the small multiples** whenever more than one
  country is selected. It is the answer to "what does the whole selection look
  like", and it means *All* is immediately useful instead of a wall to scroll.
- **Membership of that combined chart is constant**, never per-period. Summing
  "whoever reports this month" makes the total ramp with coverage rather than
  with the market. Per-period strict membership is the obvious alternative and
  it collapses: across all 51 series it yields **one bar**, because they start
  and end at different months and quarterly countries' windows land on four
  months a year. So the tab starts from the full selection and drops countries
  only while the common span is shorter than 12 bars, each time removing the one
  whose removal buys back the most periods — which is *not* the same as removing
  the latest starter, because the binding constraint is as often an early last
  month or a quarterly cadence. In practice: all 51 → 47 members; Europe → 33 of
  34 (only Georgia, quarterly, drops out); a four-country pick keeps all four.
  Whoever is left out is named in the footnote.
- **A window finer than the data still draws.** When `N` is smaller than an
  observation's granularity, the tab does not leave a hole: it draws that
  observation at its own size — one bar spanning the cycle, labelled for the year
  or quarter rather than a month. In share mode that is exactly the cycle's mix;
  in absolute mode the height is scaled to the window length so it stays
  comparable to the monthly bars beside it, and the tooltip says so. This is what
  makes T1M usable across the whole 51-country wall.
- **The y-axis is measured in the units the bars are drawn in.** A coarse bar
  carries its whole cycle — China 2016 is 28.4 M for the year — but is drawn
  scaled to the window, 2.37 M at T1M. Taking the axis maximum from the raw
  value put the top at 30 M and squashed every monthly bar to a hairline. It
  showed up in exactly the three countries that carry yearly rows (China,
  Germany, Poland) and nowhere else, which is what made it findable. The same
  scaling applies to the shared maximum under *Same axes everywhere*.
- **Bar width comes from the spacing to the neighbouring bar**, not from a fixed
  step, so a bar standing for a whole year looks a year wide next to monthly bars
  a month wide. The pixel cap that stops a lone monthly bar becoming a slab has
  to scale with the span too, or a yearly bar gets clipped back to a sliver and
  the run reads as a series of gaps — which is exactly what Romania's pre-2018
  years looked like. Without this a coarse stretch renders as hairlines with space
  between them and reads as *missing* data rather than *coarser* data — which is
  exactly the wrong conclusion.
- **Above six charts the small multiples go compact** — smaller cards, three or
  four per row, no per-chart subtitle or legend, one shared legend above the
  grid. 51 countries then read as a wall of shapes you can scan, which is the
  point, rather than 51 full-dress charts.
- **The QR is drawn inside the chart's header band**, beside the tag and
  timestamp, never over the plotting area — the data is the subject, the QR is
  provenance. Keeping it small is only possible because the payload is kept
  short: the selection encodes as `*` for all, `@Europe` for a region, or a
  base-36 bitmask over the country list beyond eight picks. Spelling out 51
  names exceeds what a version-10 code holds at all.

## 6 · Phasing

| Phase | Scope | Ships alone? |
|---|---|---|
| **0 · Spike** | One country, client-side straight from `data/Germany.csv`. Throwaway; proves the stack reads well and the slider feels right before any backend exists. | not shipped |
| **1 · Backend** | `build_series.py`, `series/`, `--check`, `build-series.yml`, the generated checklist. | **Done (2026-08).** 51 countries, 5,835 drawable periods, 300 held back, 448 KB |
| **1b · Data** | Work the checklist in [35b](35b-raw-data-quality-todo.md) down. Nothing blocks the tab; each item buys back bars. | Ongoing, country by country |
| **2 · The tab** | Single country, stacked bars, window, timeframe, absolute + relative, run blocks, definitions panel, deep links, group rename, cross-links, PNG + CSV export. | Yes — this is the feature |
| **3 · Multi-country** | 2–5 countries, Comparable mode + collapse notices. | Yes |
| **4 · Aggregation** | Sum across countries. **Strict membership**: a period is emitted only if every member reports it, otherwise the denominator jumps when one country publishes late. Show `n = 14/16 reporting`. | Yes |

---

## 7 · Decisions on record

Settled with the maintainer, 2026-08.

| # | Decision | Where |
|---|---|---|
| 1 | Stacked bars of the country CSVs — **no model, no `params.csv`, no fit** | § 1, § 4.3 |
| 2 | **`Whole` variants only**, like Builder — 51 files | § 3.1 |
| 3 | **Native cadence only.** Quarterly countries render as quarters with quarter-multiple windows; monthly runs are separate blocks, never bridged | § 3.2, § 3.3 |
| 4 | **Absolute and relative** both ship; aggregation optional | § 5.2 |
| 5 | **Tab named "Raw Data"**, own tab, group renamed "DIY Curves" → "DIY Charts", Builder association via cross-links | § 5.1 |
| 6 | **No seasonality warnings.** A definitions panel instead — fuel-type meanings, per-country quirks, collapse notices | § 5.4 |
| 7 | **A period that does not add up is not drawn**, and the chart says so in one line — no `Unreported` band, no validation UI in front of the reader | § 2.4 |
| 8 | **Negative residuals fail the build**, they are not clamped at render time | § 2.5 |
| 8b | **Smearing and zero-dropout detectors** added after the mockup — both catch conditions no sum check sees | § 4.2 Stage 4, § 4.4 |
| 8c | **Granularity per period drives the window control** — divided smears keep their data at multiples, copied smears are dropped | § 4.2 Stage 4 |
| 8d | **Fleet-tab palette**, re-stepped where adjacent bands were not tellable apart | § 5.3 |
| 8e | **Combined chart above the small multiples**, constant membership, drop-by-most-recovered | § 5.6 |
| 8f | **Compact small multiples above six charts**, shared legend | § 5.6 |
| 8g | **QR on by default**, in the header band, with a compact selection encoding | § 5.6 |
| 8h | **"Same axes everywhere"** — shared x range, shared y in absolute units; the combined chart keeps its own scale | § 5.2 |
| 8i | **A reported `0` in an electrified column is a value**, an empty cell is not; combustion zeros stay unreported | § 2.1b |
| 8j | **A row alone in its cycle and labelled `yearly`/`quarterly` IS that cycle**, drawn one cycle wide | § 3.2b |
| 8k | **Bars are centred on the window they cover**, not on their end period | § 5.3 |
| 9 | `series/` committed to Git | § 4.2 |
| 10 | Aggregation deferred to after the tab ships | § 6 |

---

## 7b · Why a chart has holes in it

Worth writing down, because the gaps are the first thing anyone asks about and
there are five unrelated causes behind them:

| Cause | Looks like | Examples |
|---|---|---|
| **`OTHERS` swallowing the market** — the source knows a few fuels and the total, and dumps the rest in the residual | a wall of one colour, or a hard gap once refused | Japan 2012–2019: `BEV`/`PHEV` as annual/12, petrol/diesel/HEV empty, **99.5 %** in `OTHERS` |
| **Coarse columns** — a quarterly or annual figure spread across finer rows, or written onto one row | a wide bar covering the cycle, labelled for it | Belgium, Bulgaria, Hungary, Poland (spread); Romania 2010–2017, Greece 2015, Australia, Canada, Uruguay (one row per cycle) — all now continuous |
| **Components don't reconcile with `TOTAL`** | a hard gap at every window | Czechia 2016–2021: 2011–2015 reconciles 12/12 every year, 2016–2021 never (±1–2 %), 2022 onward clean again — and the `HEV` column is empty for exactly the broken span |
| **Genuinely sparse or missing rows** | a hard gap | Türkiye pre-2020 (only `BEV` + `Hybrid`, no petrol/diesel), Malta (no rows at all for 2025-07 … 2026-03), Singapore 2019 (one row for the whole year), Australia 2020-01…06 (absent) |
| **A category the source only started reporting later** | a hard gap that ends the month a column appears | France (`HEV` from 2021, `PETROL`/`DIESEL` from 2018), Uruguay (`HEV` from 2023) — the residual rule refuses rather than fold hybrids into ICE |

`OTHERS` is a *reported* category ("none of the above" — LPG, CNG, fuel-cell),
so it is drawn like any other band. But when it carries almost the whole market
it is not a fuel mix, it is everything the source did not break out, and a stack
of 99 % "Other" is a faithful rendering of the file and a useless chart. **Rule:
a period whose `OTHERS` exceeds 80 % of `TOTAL` is not served.** The threshold is
deliberately far above the only other series that come near it — Singapore and
Malta touch ~52 % in a handful of months and are plausible fuel mixes. Japan
loses 41 periods to this and starts at 2020-01 instead of opening with eight
years of grey.

And one amplifier that makes any of them look far worse than it is: **at T12M a
bar needs twelve consecutive usable months, so a single unusable row blanks a
whole year of bars.** Latvia loses only 5 scattered rows and drops from 133
usable months to 82 bars — those 5 rows cost 51 bars. This is the mechanism
behind every "why is there a hole there" question, and it is worth saying in the
footnote rather than leaving the reader to infer it.

## 7c · Which rules earn their keep

The rule set grew one case at a time, so it was worth checking empirically rather
than by feel: each rule was switched off in turn and the output diffed against
the full run.

| Rule switched off | Effect |
|---|---|
| Materiality gate (repeat ≥ 1 % of `TOTAL`) | **−133 periods**, 28 countries |
| Reconciliation tolerance 3 % → 0.5 % | **−73 periods**, 7 countries |
| `OTHERS` > 80 % | +17 periods, all Japan — and all of them 99 % grey |
| copied-vs-divided distinction | 0 periods, but **values change in 16 countries** (Belgium et al. come out 3× high) |
| Band folding | 0 periods, but the definition cliff returns in 6 series |
| Combined-hybrid relabel | 0 periods, but 5 sources stop saying their `HEV` also contains `PHEV` |
| Snap to 3/12 instead of the raw run length | ±1 period — kept anyway, because it keeps granularity on real calendar cycles instead of inventing a 7-month one |
| **EV-only rows (exact-zero combustion side)** | **no effect at all** |

The last one is the interesting entry: the rule was written for Hungary 2021 Q1,
and the maintainer has since corrected that data at source, so it now guards
nothing. It is kept as insurance — the failure it catches (a bar reading ~100 %
EV) is both plausible from a fetcher bug and invisible once rendered — but it
should be understood as insurance, not as load-bearing.

Four things were removed outright as provably dead, with the output verified
byte-identical before and after:

- **`hev_note` plumbing** — parsed out of ~40 source docs plus the stub registry
  on every build, emitted into every series file, read by nothing. The
  combined-hybrid case is already carried by the band label.
- **The post-aggregation `TOTAL > 0` filter** — reconciliation guarantees
  `Σ bands ≥ 0.97 · TOTAL > 0`, and `TOTAL` after aggregation *is* `Σ bands`, so
  the branch could never fire.
- **Two rejection counters** kept apart and then only ever added together.
- **The `anchor` parameter** threaded through `bars()` and `combined()` — the
  window-alignment test that read it was replaced by the cycle model and the
  argument was never deleted.

Net: 26 lines out of the generator, no behaviour change.

## 8 · Open items

**A clickable mockup exists** — the real CSVs run through a ~150-line prototype
of § 2 and § 3, rendered as the tab would render them, with all eight demo
countries and the findings below written up inline.

### 8.1 What the current data still holds back

Rebuilt against master after the maintainer's cleanup: **51 countries, 5,843
periods drawable, 260 held back, 222 coarser observations recovered at their own
granularity.** 39 of 51 files now come out complete. What is left is data work,
not chart work, and it is worth naming precisely because each item has a
different answer.

| Country | Held back | What is actually in the file |
|---|---|---|
| **Japan** | 96 | 2012–2019 reports `BEV`, `PHEV` and the market total and nothing else — 99.5 % lands in `OTHERS`. There is no mix to stack; the chart correctly starts at 2020-01. Only a finer source fixes this. |
| **France** | 72 | Two distinct defects. 2015–2017 knows only `BEV`/`PHEV` (no combustion columns at all, and `HEV` appears in 2021, so the residual rule of § 4.2 Stage 3 cannot fire without folding France's hybrid band away for the years that have one). 2018–2020 is worse: `PETROL`/`DIESEL`/`OTHERS` are **smoothly interpolated** against real monthly `TOTAL`s — 2018-03 misses by −22 %, 2018-01 by +13 %. Interpolation, unlike copying, defeats the equal-run detector of § 4.2 Stage 4, so nothing recovers it. |
| **Portugal** | 44 | Confirmed as the maintainer described: quarterly figures re-simulated as monthly. 2010–2017 now renders (the § 2.1b fix); 2018–2020 does not. |
| **China** | 7 | 2020 `BEV`/`PHEV` are one figure spread over Jan and Mar–Sep, with February hand-corrected to the real COVID numbers. The correction breaks the equal run, so the year cannot be reassembled. Writing 2020 as twelve real monthly rows — or as one annual row — both work. |
| Türkiye, Slovenia, Singapore, Poland, Lithuania, Croatia | 6 each | Mostly single seams; **Slovenia 2015–2017 is a genuine contradiction** — `PETROL + DIESEL` is 64,018 against a `TOTAL` of 53,367 for 2016, and 60,069 against 72,710 for 2015. One of the two series is measuring a different population. |
| Iceland | 3 | 2019-03 and 2019-04 miss `TOTAL` by 3.3 % and 6.7 % — the synthesised HEV/petrol/diesel split does not tie out. |
| Uruguay | 2 | 2021 and 2022 are annual rows carrying only `BEV`; `HEV` starts in 2023, so the residual rule holds off rather than fold two years of hybrids into ICE. |

Two smaller items, both cosmetic in the file rather than in the chart:

- **`Norway.csv` 2008-11 has `OTHERS = -1`.** It survives every check because it
  is one unit; it should not exist.
- **`Singapore.csv`'s `time_interval` is unreliable in both directions** — 2018
  is labelled `yearly` for twelve rows of real monthly totals, 2020 `quarterly`
  for twelve more. Nothing depends on it there (§ 3.2 reads spacing, not
  labels), but § 3.2b now does trust the label in the one case where it is
  alone in its cycle, so it is worth correcting. Separately, **2019 has exactly
  one row** (2019-01); the other eleven months are absent.

The audit that produced this list checks three things over the built series and
now comes back clean on the first two: level continuity at every granularity
seam (**0 suspicious seams**, down from 4), bands outside 0–100 % (**1**, the
Norway unit above), and freshness (**48 of 51 current to 2026-06 or later**).

**Two data-quality checks were added by the mockup**, both catching things the
original rules missed: smeared values (§ 4.2 Stage 4) and zero-dropouts (§ 4.4).
Neither is a chart problem — they are pre-existing data conditions that a
stacked bar makes visible for the first time.

**The R TTM palette cannot be used verbatim on a dark surface, and the reason
is worth recording** — it is the whole combustion half, not one value. Against
the `#0f1525` that Builder and Compare use: `ICE #692500` 1.62:1,
`Petrol #502900` 1.44:1, `Diesel #914700` 2.69:1, `Other #3c2f2f` 1.42:1, all
below the 3:1 a filled area needs. The electrified half is the mirror image —
`BEV #00ff2c` measures 1.37:1 on white and works in the PNGs only because R
draws black outlines around every bar. **The two palettes are each correct for
their own background**, so this tab lifts R's hues rather than importing its
values (§ 5.3), and `TTM_FUEL_COLORS` is untouched.

One separation problem is real on *any* background and therefore exists in the
PNGs today: `Petrol #502900` vs `Other #3c2f2f` measures ΔE 6.4 — they are
effectively one colour wherever a TTM chart shows both. Moving `Other` to a
neutral (e.g. `#6b7280`, ΔE 34) fixes it in one value, but it changes every
rendered PNG, so it is a maintainer call and is not part of this proposal.

---

## 9 · See also

- [03-data-objects.md](03-data-objects.md) — where `series/` gets documented once built
- [05-flows.md](05-flows.md) — where the build-series flow diagram goes
- [31-proposal-country-source-pages.md](31-proposal-country-source-pages.md) — `observed_cadence()`, `contiguous_runs()`, and the `hev_note` front-matter this reuses
- `R/plots.R` — `TTM_FUEL_COLORS`, the palette this tab must match
- `index.html` — `fetchCompareObs()` / `COMPARE_OBS_CACHE`, the fetch pattern to reuse
