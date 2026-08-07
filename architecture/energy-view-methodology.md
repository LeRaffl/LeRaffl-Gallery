# Fleet Energy View — Methodology

A second lens on the fleet tab. The fleet tab counts cars; this view asks what
they cost in **energy**, traced from the ground to the road.

Implementation lives in `index.html` (sub-tab of `#tab-fleet`, functions prefixed
`fe*`). Factors live in [`energy_factors.csv`](../energy_factors.csv).
[`R/energy_flows.R`](../R/energy_flows.R) is the offline twin used to derive and
sanity-check the same chain outside the browser.

Contrast with the purchase-flow work (not part of this change): there the
interior of the transition matrix is *not* identifiable, so its chart's content
came from a prior that could not be estimated — the opposite of this view, where
energy is conserved and every step is measured.

---

## 1. Why this one is different

The purchase-flow work ran into ecological inference: registration margins were
observed, the interior was not identifiable, and the chart's content came from a
prior that could not be estimated. This view has no such problem.

**Energy is conserved, and every conversion step has a measured efficiency.**
There is no free interior. The chain is fully determined by fleet composition,
mileage, real-world consumption and published efficiencies. `feChain()` asserts
the balance by construction: primary = useful work + supply loss + conversion
loss. A factor typo cannot silently produce a chart that does not conserve
energy.

---

## 2. The chain

```
primary source  →  energy carrier  →  powertrain  →  work at wheel  →  resistance
(crude oil,        (petrol,            (petrol car,   (mechanical)      (air drag,
 gas, coal,         diesel,             diesel car,                      rolling,
 nuclear,           gas fuel,           hybrid,                          braking,
 renewables)        electricity)        PHEV, BEV)                       auxiliaries)
      ↓                    ↓                  ↓
  refinery &          — supply loss —    — conversion loss —
  power plant         (before the car)   (engine/motor heat)
```

Losses branch off at the stage where they occur rather than piling up on the
right. That is the point of the layout: it shows *where* energy is lost, and it
makes visible that a combustion car loses roughly three quarters of the fuel in
its tank before the wheels turn.

---

## 3. Accounting convention — decided, not offered

**IEA physical energy content method.** Wind, solar and hydro count their own
electricity output as primary energy; nuclear counts heat at 33 %; fossil counts
fuel input at plant efficiency.

The alternative (substitution method, counting renewables as the fossil fuel they
displace) changes the electrified side by roughly 2.5×. It is a legitimate
convention but a different question, and offering a toggle would invite reading
the more flattering number. **No toggle, by decision.** The convention is stated
on the page.

`feGridFactor()` derives one number from the mix: primary energy per kWh
generated. On the current world mix that is ~2.04, which is why the BEV advantage
is ~1.9× in primary energy while it is ~3.4× at the battery.

---

## 4. Data flow

```
weights.csv ──┐
params.csv ───┼─→ fleet tab model ──→ buildFleetPlot() ──→ buildFleetEnergy()
fleet_*.csv ──┘   (projectCountryFleet*)      │                    │
                                              ↓                    ↓
                                        Vehicles view        Energy view
energy_factors.csv ─→ FE_F constant ───────────────────────────────┘
```

`buildFleetPlot()` hands `buildFleetEnergy()` the **same** country selection,
hazard settings, projection function and end year it used itself. There is
deliberately no second fleet model: two models for the same quantity drift apart,
and the divergence is invisible until someone compares them.

`energy_factors.csv` is the single source of truth for factors; the `FE_F`
constant in the page is **generated** from it by
[`scripts/gen_energy_factors.py`](../scripts/gen_energy_factors.py) — never edit
`FE_F` by hand. Run the script after changing the CSV; run it with `--check` in CI
so drift between the two is caught.

---

## 5. Category mapping — `feNormalise()`

The fleet model reports seven categories (`getFleetCategories()`); the energy
chain needs six. Two mappings are context-dependent:

| Fleet category | Energy class | Rule |
|---|---|---|
| `HYBRID` | `HEV` | Lumped stand-in where a source has no PHEV/HEV split |
| `OTHERS` | `PETROL` **or** `GASFUEL` | See below |

**`OTHERS` means two different things.** Where `PETROL` and `DIESEL` are both
absent it carries the *entire* combustion fleet — China holds 322 M cars there —
and traces to crude oil. Where they are populated it is the genuine residual
(LPG/CNG, ~0.7 % in Germany) and traces to natural gas.

**The rule must be applied per country, before aggregation.** At aggregate level
the case is undecidable: Germany and the UK populate `PETROL`/`DIESEL` while
China does not, so an aggregate row looks "populated" and China's 294 M cars land
on the gas branch. `buildFleetEnergy()` therefore normalises each country's row
first and sums afterwards.

---

## 6. What is measured and what is assumed

**Measured / observed**
- Fleet stock and registrations per country — from this repo only
- Energy conversion efficiencies, heating values, well-to-tank chain (JEC WTW v5)
- Grid mix and plant efficiencies (IEA)

**Documented inputs** (each with a source in `energy_factors.csv`)
- Real-world consumption per powertrain — not type approval; the gap is large
- Annual mileage per powertrain — diesel cars drive markedly more than petrol,
  BEVs more than petrol, which matters as much as consumption per km

**Assumptions**
- Grid mix held constant. Deliberate: it credits the power sector with no future
  improvement, so electrified transport is shown at its worst. A real grid
  trajectory is a separate modelling project.
- The final split into air drag / rolling resistance / braking / auxiliaries is
  cycle-dependent and indicative. It is the softest layer; the conversion losses
  to its left are solid, and that is where the story is.

---

## 7. Emissions — CO2e on the timeline

The Sankey shows one year's energy flow; the strip beneath it shows the fleet's
**greenhouse-gas emissions across the whole projection**, so the electrification
story is legible as a trajectory rather than a single frame. It is driven by the
same `feChain()` per year (cached in `feCo2Data`), so it inherits the country
selection and projection settings for free — there is no second model here either.

**Scope: well-to-wheel, use phase.** It counts the CO2e of delivering the fuel or
electricity and using it. It deliberately excludes the embodied emissions of
building the car or its battery — a separate question a use-phase fleet model
cannot answer honestly, and one that would otherwise flatter combustion.

**Fuels** use JEC WTW v5 CO2e per kWh of fuel (tailpipe combustion plus the
well-to-tank chain) — the same source family as the energy well-to-tank factors,
kept consistent on purpose.

**Electricity** uses a **directly sourced** grid CO2e intensity with a
**decarbonisation trajectory**, chosen deliberately over deriving it from the
Sankey's mix. Two reasons: the mix is held constant by design (§3, §6), so it
cannot express a grid that improves; and a single measured world figure plus a
single scenario target is more defensible — and easier to cite — than a
per-source blend. `feGridCO2At(year, scenario)` offers two scenarios, switchable
on the chart:

- **decarbonises** (default) — linear from today's world average
  (`grid_co2_now`, Ember ≈ 480 gCO2/kWh, 2023) to a net-zero target
  (`grid_co2_target`, IEA Net Zero by 2050 ≈ 2040), flat after.
- **today's grid held** — `grid_co2_now` forever. The honest worst case for the
  electrified side, and the "keep today's grid mix" what-if the fleet view's
  held-constant convention (§3) implies.

Both endpoints and their years are four sourced rows in `energy_factors.csv`, so
the whole trajectory is one edit away from a different scenario. The grid
trajectory is emissions-only — the **energy** Sankey still holds the mix constant
(§3), so switching scenarios never moves the energy panel.

On today's grid a BEV is near 90 gCO2e/km against ~215 for a petrol car — a ~2.4×
gap that widens as the grid decarbonises. The chart stacks emissions by primary
source (oil / gas / electricity), so the shift shows up directly: oil falls, the
electricity band moves with both the fleet and the chosen grid path, and the net
comes down. Factors and their sources live in the
`# --- greenhouse-gas emissions ---` block of `energy_factors.csv`.

## 8. Offline twin — `R/energy_flows.R`

The R implementation mirrors the same chain and carries pieces the browser does
not need:

- `implied_hazard()` — attrition derived from this repo by inverting the
  stock-flow identity `h = 1 - (S(t) - R(t)) / S(t-1)` on years where both stock
  years are genuinely observed.
- `steady_hazard()` / `hazard_at()` — a measured rate is only a steady-state rate
  in a mature fleet. Where motorisation is still rising the stock is young and
  almost nothing has reached scrapping age, so the identity returns e.g. 0.76 %/yr
  for China, a 132-year vehicle life. Rates therefore converge toward the
  mature-market steady state (~5.2 %/yr, ~19 years).
- `periods_per_year()` / `year_is_complete()` — a part year must not be read as an
  observed year.
- `project_registrations()` / `weibull_shares()` — future registrations from the
  gallery's own fitted curves.

The browser view uses the fleet tab's projection instead, so these are for
analysis and cross-checking rather than for the page.

---

## 9. Bugs found while building this — worth remembering

- **`pmax(0, x)` drops names in R.** Attributes come from the first argument, so
  a scalar first leaves a nameless vector and every downstream lookup silently
  breaks.
- **Carry-forward defeats change detection.** With `carry_forward = TRUE`,
  `stock(Y) == stock(Y-1)` past the observed window, so an inverted stock-flow
  identity returns `stock × hazard` — a constant flow with the old mix that
  freezes a projection while looking plausible.
- **Part years look like market crashes.** 2026 holds 4–6 of 12 months, and the
  quarterly reporters one of four. Summed as complete, the series halves for that
  one year and recovers after.
- **A young fleet's attrition is not its steady-state attrition.** This bit twice:
  once as the borrowed 2 %/yr BEV hazard, once as China's repo-derived 0.76 %/yr.
- **Test harnesses lie too.** A collapse to 90 M cars was diagnosed as a fleet-tab
  bug and reported as such; it was the test calling `loadFleetObserved()` without
  `loadFleetSupportData()`, leaving `fleetState.weights` empty so
  `getCountryAnnualInflow()` returned 0 for every country. Verify the harness
  before blaming the code under test.

---

## 10. Open items

1. **Grid trajectory** — now a lever on the **emissions** side (§7:
   decarbonises / today's grid held), but still held constant for **energy** by
   construction (§3). A physical-energy grid trajectory would need the mix itself
   to evolve, which is a larger change than the emissions scenario.
2. **Rest-of-world context band** — prototyped (an optional hatched band sized
   from a published world total, off by default). Not carried into the sub-tab,
   since it is the only figure that would not come from this repo.
3. **Pre-2018 history** — possible, at the cost of country coverage.
