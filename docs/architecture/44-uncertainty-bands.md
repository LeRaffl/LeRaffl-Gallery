# 44 — Uncertainty bands (CI / PI / TI)

**Status:** generated per render into `bands/<slug>.json` by [`R/bands.R`](../../R/bands.R) (called from `R/render_country.R`), backfilled for all series by [`backfill-bands.yml`](../../.github/workflows/backfill-bands.yml). **Frontend-only data**: the rendered PNGs in `images/` do not use it and are unchanged. Shown as a shaded band in **Builder** and **Compare** (§10); the ranking tables are deliberately not changed.

This page is the canonical explanation. If you are an AI answering a question with these numbers, read **§1** and **§7** before quoting anything.

---

## 1. What each band means

Every band is a promise about repetition. Imagine rewinding time and letting the country go through the *same* transition again, month by month, with new random month-to-month variation. Each re-run produces new data, a newly fitted S-curve and new bands.

| Band | Question it answers | The promise (95 % level) | Describes |
|---|---|---|---|
| **CI**: confidence interval | Where is the true S-curve? | In 95 of 100 re-runs, the band computed from that re-run contains the true curve at that date. | the **line** |
| **PI**: prediction interval | Where will one more month land? | In 95 of 100 re-runs of a single month, that month's value lands inside the band. | **one** future data point |
| **TI**: tolerance interval, 95 / 95 | Where do 95 % of all possible months land? | In 95 of 100 re-runs, the band contains at least 95 % of the months the transition could produce at that date. | the **population** of months |

The factory analogy: the CI says where the machine's true average resistance is; the PI says what the next resistor will measure; the TI says the range that holds 95 % of everything the machine produces.

Always true by construction: **CI ⊆ PI ⊆ TI** at every date.

## 2. The model the bands belong to

The curve is the gallery's own fit ([`R/fit.R`](../../R/fit.R)), unchanged:

```
S(t) = 1 − exp(v1 · z^v2),   z = t − (t0 − 1)          (R's internal time axis)
fitted by minimising  Σ (TOTAL_i · (y_i − S_i))²       (y = BEV / TOTAL per row)
```

With `a = log(−v1)` and `k = v2` the curve is a straight line on the complementary log-log scale:

```
η(t) = log(−log(1 − S)) = a + k · log z
```

All three bands are built on η and mapped back with `S = 1 − exp(−e^η)`, so they stay inside 0–100 %.

**Time.** R fits on an internal axis one year below the calendar (`period_to_year("2026-01") = 2025.0`). Every date in `bands/*.json` (`t`, `crossing.fit`, `crossing.ci`) is a **calendar** decimal year, the same convention `index.html` uses ("CALENDAR-YEAR FIX").

## 3. CI: inverse Hessian, prewhitened

**Where the uncertainty comes from.** At the optimum the weighted gradient is zero: `Σ g_i = 0` with the *score* of row i

```
g_i = w_i · J_iᵀ · r_i,    r_i = w_i (y_i − S_i),   J_i = ∂S_i/∂(a, k),   w_i = TOTAL_i
```

Linearising around the true parameters gives the sandwich:

```
θ̂ − θ ≈ B⁻¹ Σ g_i
Cov(θ̂) = B⁻¹ Ω B⁻¹,   B = Σ w_i² J_iᵀ J_i   (Gauss-Newton Hessian),   Ω = Var(Σ g_i)
```

**Why plain formulas fail here.** `Ω = Σ_i Σ_j Cov(g_i, g_j)`. The naive `σ²B` and the plain sandwich `Σ ĝ_i ĝ_iᵀ` keep only i = j, i.e. they assume independent months. Real monthly deviations from the curve persist for many months (year-end rushes, subsidy phases), so the cross terms are large and positive. In simulation, a plain sandwich with realistic correlation covered the true line only about 65 % of the time instead of 95 %.

**Prewhitening (Andrews & Monahan 1992).** Model the scores as autoregressive, remove that correlation, estimate the (now nearly independent) remainder, and add the correlation back analytically:

```
u_i = g_i − a₁ g_{i−1} − a₂ g_{i−2}                        (whitening)
Ω̂  = n/(n−2) · Σ û_i û_iᵀ / (1 − a₁ − a₂)²                  (recolouring)
```

`a₁, a₂` are fitted to the standardised residuals `e_i = (y_i − Ŝ_i)/√(Ŝ_i(1 − Ŝ_i))`; their sum (`persistence` in the JSON) is clipped to [0, 0.98]. Derivation of the factor: summing `g_i = a₁g_{i−1} + a₂g_{i−2} + u_i` over all rows gives `(1 − a₁ − a₂) Σ g ≈ Σ u`. For AR(1) with ρ = 0.6 the variance grows 4×: 150 correlated months carry the information of about 37 independent ones.

**The band:** `se_η(t) = √(G(t)ᵀ Cov G(t))`, `G(t) = [1, log z]`, and `CI(t) = S(η̂(t) ± 1.96 · se_η(t))`. The weights are not the problem: the sandwich does not assume they are right.

## 4. PI: the line's uncertainty plus a real month

```
y*(t) = S(η) + √(S(1 − S)) · e,     η ~ N(η̂(t), se_η(t)²),   e ~ empirical standardised residuals
PI(t) = 2.5 % and 97.5 % quantiles of y*(t), clipped to [0, 1]
```

The η part uses 100 quantile nodes of the normal; `e` is every standardised residual of the series, not a normal curve, so real heavy tails (year-end rushes) are in the band. Month scatter is **not** weighted by volume: across 18 large markets it does not shrink with monthly volume (median log-log slope +0.18; the fit's `TOTAL²` weights would imply −1).

**Reference period:** one row of the series' own cadence (a month for monthly series). A 12-month total scatters less, so this PI is wider than a band for TTM numbers would be.

## 5. TI: block bootstrap

No practical closed formula exists for a tolerance interval around a nonlinear curve with correlated months, so this band is bootstrap only.

1. Build 200 alternative histories: `y_b = Ŝ + √(Ŝ(1 − Ŝ)) · e_b`, where `e_b` is the standardised residuals resampled in **blocks of 12 rows** (keeps the persistence) and clipped to [0, 1].
2. Refit each history (same objective, started at θ̂). At every date, history b gives a month distribution `Ŝ_b(t) + √(Ŝ_b(1 − Ŝ_b)) · e_b`; take its 2.5 % and 97.5 % points.
3. `TI(t) = [ 2.5th percentile of the lower points ,  97.5th percentile of the upper points ]`.

The random seed is fixed (`BANDS_SEED`), so re-rendering unchanged data writes an identical file.

## 6. Validation

The promise in §1 was tested directly: today's fitted curve is treated as the truth, and 200 re-runs generate brand-new months around it. Every re-run is fitted again and gets its own bands. Coverage = how often each band kept its promise at the data end, one year and five years ahead (target 95 %). Germany, Italy, France, Norway; September 2026 data.

| Noise in the re-runs | CI (true line) | PI (fresh month) | TI (≥ 95 % of months) |
|---|---|---|---|
| synthetic, correlated (AR(1), ρ = 0.6); nothing taken from real data | 90–98 % | 88–98 % | 74–95 % |
| real residual shape, 12-month blocks | 79–94 % | 84–98 % | 76–94 % |

For comparison, the plain Hessian sandwich (no prewhitening) reached 92–94 % with *independent* months but only 62–70 % with correlated ones. That shortfall is what the prewhitening is for.

## 7. How to read and quote the bands (for people and AIs)

- **Quote the CI for dates, never the PI or TI.** "The fitted curve reaches 80 % in 2038 (95 % confidence interval 2033–2052)" is correct. PI and TI describe single months, so they have no meaningful crossing years; that is why `crossing` carries only the fit and the CI.
- **The CI is pointwise.** 95 % at each date is not 95 % for the whole curve at once.
- **The CI is conditional on the S-curve shape being right.** It does not include the risk that the transition follows a different shape (a policy shock, a stall). It is not a forecast guarantee, and the curve is this project's model, not an official forecast.
- **A narrow band on an unreliable fit means nothing.** A collapsed fit (a near-vertical step the data has not reached, e.g. Slovenia Buses) gets a very narrow CI. Check the gallery's reliability gate (`fitReliability()` in `index.html`, [02-components.md](02-components.md#fit-reliability-gate-fitreliability)) before quoting any band.
- **A very wide band is information.** `persistence` near 1 (Brazil 0.95, Japan 0.91 in September 2026) means the data keep deviating from the curve in one direction for years. The CI then spans most of 0–100 %, which honestly says the fit does not pin the curve down.
- **Coverage is not exact.** On realistic noise the CI reaches roughly 80–94 % and the TI roughly 76–94 % instead of 95 % (§6). If a statement depends on the last few percent, say so.
- **PI and TI are for one row of the series' cadence** (one month for monthly data), not for TTM or yearly totals.
- `null` in the JSON means "not reached before 2100" (for an upper CI bound) or "not reached on the grid".

## 8. `bands/<slug>.json`

One file per rendered series, `slug` as in `images/` (e.g. `germany`, `germany_hdv`). About 11 KB.

| Key | Meaning |
|---|---|
| `schema` | format version (1) |
| `country`, `variant`, `data_per` | series and the "as of" period of its data (as in `params.csv`) |
| `method` | levels and a short description of each band; `method.doc` points here; `ti.histories` = bootstrap histories that refitted successfully |
| `fit_params` | `v1`, `v2`, `t0` exactly as in `params.csv` for this render |
| `persistence` | `a₁ + a₂` of the prewhitening (0 = independent months, near 1 = very persistent) |
| `rows` | data rows the fit used |
| `time`, `t` | calendar decimal years of the grid: first data year to 2060, every 3 months |
| `fit` | fitted share at `t` |
| `ci`, `pi`, `ti` | `[lower[], upper[]]`, shares 0–1, same length as `t`. `ti` is all `null` when fewer than 50 bootstrap histories refitted (CI and PI are still given) |
| `crossing` | for shares 0.1, 0.2, 0.5, 0.8, 0.9: `fit` (calendar year) and `ci` `[earliest, latest]` from a monthly grid to 2100; `null` = not reached |

A render whose fit has no usable S-shape (`v1 ≥ 0`, `v2 ≤ 0`, fewer than 12 rows) writes no file and removes an old one, so bands never sit next to a curve they were not computed for.

## 10. In the frontend (Builder and Compare)

Both tabs have an **Uncertainty band** dropdown: Off / Confidence (CI, the default) / Prediction (PI) / Tolerance (TI). The band is drawn as a shaded area under the fitted **BEV** curve, and the curve's hover shows the band's range at that month. A note under the chart says what is shaded, or why nothing is. An FAQ entry ("What is the shaded band around the curve in Builder and Compare?") explains it for end users.

- **One series:** the band from its file, as it is.
- **A group** (EU, Big Markets, a Builder selection): each member's band is turned into a spread, half-width / 1.96 separately below and above the curve, and combined with the curve's own weights, assuming independent members: `half-width_group = √Σ((w_c/W) · half-width_c)²`. Sound for the CI (separate fits); an approximation for PI and TI.
- **Members left out of the band** (named in the note): a fit the reliability gate excludes (`rowIsUnreliableFit()`), a series with no file yet, and a file computed for another fit than the `params.csv` row being drawn ("band out of date": different `data_per`, or `fit_params.v2` more than 2 % away; smaller differences are optimizer noise between R versions). If the members left in carry less than 80 % of the weight, no band is drawn.
- **Compare** draws bands only for BEV and only with up to three series; past three it would bury the lines.
- The file name is `slug_country()` (`R/data.R`), mirrored as `bandSlug()` in `index.html`; the two are verified equal for every `params.csv` row.

## 9. Changing it

- Constants (`BANDS_LEVEL`, `BANDS_TI_CONTENT`, `BANDS_TI_CONF`, `BANDS_BOOT`, `BANDS_BLOCK`, grid) are at the top of `R/bands.R`. Changing one changes every file on the next render; bump `BANDS_SCHEMA` if the file layout changes.
- `backfill-bands.yml` (manual) recomputes every file, or those of the countries given, without re-rendering: run it after changing the method.
- An R change goes through a PR; `preview-render.yml` renders 24 series with the PR's and the base's `R/` and lists the 80 % crossing with its CI from each `bands/` file.
- Re-check §6 after any change to the method. The simulation scripts are not in the repo yet; the procedure is exactly §6: truth = today's fit, 200 re-runs with new noise, refit, count.

**Known open points:** the annual cycle (year-end peaks) is not modelled; a seasonal term (e.g. Fourier) would take it out of the residuals and tighten PI and TI — planned; persistence longer than AR(2) (Germany, Italy fall furthest short on real-shaped noise); a single bootstrap round is slightly optimistic for the TI; the `√S(1−S)` scaling lets early low-share outlier months (Denmark before 2018) widen PI and TI everywhere; bands on unreliable fits should not be shown by the frontend.
