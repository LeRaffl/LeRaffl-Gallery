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

The mix decides how much primary energy a kWh of electricity costs: about 2.0
kWh on the world mix, close to 1.0 on Norway's hydro grid. That is why the BEV
advantage in primary energy depends on where the car is charged, and why the
view charges each country's cars from that country's own grid (§6a).

---

## 4. Data flow

```
weights.csv ──────────────┐
params.csv ───────────────┼─→ fleet tab model ──→ buildFleetPlot() ──→ buildFleetEnergy()
fleet/fleet_initial.csv ──┤   (projectCountryFleet*)      │                    │
fleet/fleet_calibration ──┘                               ↓                    ↓
                                                    Vehicles view        Energy view
energy_factors.csv ─→ FE_F constant ───────────────────────────────────────────┤
fleet/grid_mix.csv ─→ fleetState.grid (per country, per year) ─────────────────┘
```

`buildFleetPlot()` hands `buildFleetEnergy()` the **same** country selection,
hazard settings, projection function and end year it used itself. There is
deliberately no second fleet model: two models for the same quantity drift apart,
and the divergence is invisible until someone compares them. `buildFleetEnergy()`
keeps the **per-country** rows of every year next to their sum (`parts`), because
electricity has to be charged from each country's own grid (§6a).

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

**Projected combustion cars must not land in `OTHERS`.** Until 2026-11 the fleet
model booked the whole combustion side of future registrations into `OTHERS`. For
every country with a petrol/diesel split this view then read those cars as
LPG/CNG: by 2035 almost a quarter (23 %) of Germany's projected fleet was a "gas
car", charged at
the gas factor (0.252 instead of 0.320 kgCO2e/kWh) and drawn on the natural-gas
branch. The fleet model now splits that inflow into `HEV` / `PETROL` / `DIESEL` by
the country's own registration mix (`docs/architecture/37-fleet-data-harmonization.md`
§7), so `OTHERS` only ever holds what the stock put there.

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
- Grid mix and CO2e intensity **per country and year** (Ember, §6a); plant
  efficiencies (IEA)

- **Mileage by fuel** — per country where Eurostat or the national office
  publishes it (§6b: 16 countries), their median elsewhere

**Documented inputs** (each with a source in `energy_factors.csv`)
- Real-world consumption per powertrain — not type approval; the gap is large

**Assumptions**
- Consumption and tank-to-wheel efficiency are **one fleet-average value per
  powertrain for every country and every year**. A country whose cars are
  larger, or older and thirstier, is not distinguished. With mileage now
  sourced (§6b) this is the largest uncalibrated layer of the view.
- Mileage for the 18 fleet countries without figures of their own is the
  median of the others (§6b); China, India and Canada are among them.
- Grid **mix** held at the last year on record for all future years. Deliberate: it
  credits the power sector with no future improvement, so in the energy Sankey
  electrified transport is shown at its worst. (The emissions strip has scenarios,
  §7.)
- The final split into air drag / rolling resistance / braking / auxiliaries is
  cycle-dependent and indicative. It is the softest layer; the conversion losses
  to its left are solid, and that is where the story is.

---

## 6a. The grid — per country, per year

`fleet/grid_mix.csv` holds, for every fleet country and for `World`, one row per
year from 2010: the CO2e intensity of generation (`gco2_kwh`, gCO2e per kWh
generated) and the shares of generation by source. It is written by
[`scripts/fetch_grid_mix.py`](../scripts/fetch_grid_mix.py) from the Our World in
Data energy dataset (CC BY 4.0), which republishes **Ember's** Yearly Electricity
Data. Refreshed by hand once a year; generated, never hand-edited.

Until 2026-11 the view used one world grid (≈ 480 g, 35 % coal) for every
country. The spread it hid is the largest single factor in the electric side:

| Grid (2025) | gCO2e/kWh |
|---|---|
| Norway | 28 |
| France | 41 |
| Germany | 330 |
| World | 458 |
| China | 525 |
| India | 670 |

`feGridAt(country, year, scenario)` returns `{g, mix}`:

- **up to the last year on record** — that year's own row (the first row for
  earlier years). An observed fleet year therefore meets the grid it ran on,
  under every scenario.
- **after it** — the mix is held (see §6); the intensity follows the scenario (§7).
- **no rows for a country** — the file's `World` series. **File not loadable** —
  the world mix and `grid_co2_now` in `energy_factors.csv`, as before.

`feChain()` computes generation per country (`parts`), multiplies each by its own
grid, and sums: several countries selected together are never charged from an
average of their grids.

**Caveat — generation, not consumption.** The figures describe what a country
generates. A country that imports much of its electricity (Luxembourg, also
Lithuania or Hungary in some years) consumes a different mix. Ember publishes no
consumption-based series for all fleet countries; this is noted on the page.

---

## 6b. Mileage — by fuel, by country, and held per car

Energy is cars × km × consumption, and the km were five global numbers (petrol
11,000, diesel 17,500, hybrid 13,000, PHEV 15,000, battery 14,000).
`fleet/mileage.csv` now holds the vehicle-kilometres statistics offices
publish, by fuel, mostly from odometer readings at inspection:

- **Eurostat `road_tf_vehage`** — passenger cars registered in the reporting
  country, wherever they drive, by fuel (petrol, diesel, electricity, and full
  and plug-in hybrids together). The preferred table.
- **Eurostat `road_tf_veh`** — all passenger cars only, for countries the first
  table lacks. The concept counting foreign cars on national roads
  (`TERNAT_REG`) is never used: that is traffic, not what the fleet drives.
- **SSB 12577** for Norway — a year newer, and with plug-in and full hybrids
  apart. Where both exist the national row is kept; for 2024 they agree to the
  kilometre.

| km per car of the year-end stock | year | all | petrol | diesel | battery | hybrids |
|---|---|---|---|---|---|---|
| Norway (SSB) | 2025 | 12,294 | 8,065 | 12,958 | 13,994 | 14,241 PHEV / 11,974 HEV |
| Sweden | 2024 | 13,291 | 10,358 | 16,415 | 15,521 | 16,080 |
| Germany | 2024 | 12,042 | 9,466 | 16,645 | — | — |
| France | 2024 | 11,532 | 8,820 | 13,317 | 11,872 | 14,246 |
| Finland | 2024 | 10,282 | 7,957 | 14,623 | 16,299 | 16,813 |
| Estonia | 2023 | 7,388 | 4,962 | 10,471 | 9,834 | 6,553 |
| **median of 12 countries** | | **12,168** | **9,088** | **14,358** | **12,532** | **16,080** |

Sixteen fleet countries have a figure of their own, twelve of them by fuel
(`fleet_calibration.json`: `mileage`). Every other country is given the median
over those twelve, class by class (`mileage_default`); a class one country does
not report takes the median scaled to that country's overall level.

**Basis.** The figure the page needs is `total km of a fuel ÷ cars of that fuel
in fleet/fleet_initial.csv`, because that is what it is multiplied back by.
`scripts/build_fleet_calibration.py` does the division. An office's own
per-vehicle average is not the same thing: SSB's (11,350 for all cars) divides
by every vehicle on the road at some point in the year, about 8 % more vehicles
than the year-end stock.

**Gates.** Three ways the division can go wrong, each with a rule:

- *Petrol hiding the hybrids.* Some countries report only petrol and diesel,
  adding up to the total, so their "petrol" includes hybrids while the stock's
  does not (the Netherlands' petrol cars would come out at 14,068 km, its
  diesels at 27,180). The fetcher writes a country's per-fuel rows only when
  the table shows the other drivetrains are counted elsewhere: electricity
  reported on its own, or the reported fuels visibly short of the total
  (Germany: 86 %). Otherwise the country gets its all-car figure only.
- *Classes that do not match.* A per-fuel figure outside 0.4–1.8× the country's
  own all-car figure is left out (Croatia's hybrids at 30,857 km, Latvia's at
  791: the km and the stock count different cars).
- *Stale years.* Nothing before 2021 is used: not the pandemic year, not a
  series that ended (the UK's stops in 2020), not figures from before the
  battery fleet (Belgium 2017, Lithuania 2018).

**What changed.** The old petrol and diesel values overstated driving by about
a fifth against the median. Germany's 2025 well-to-wheel figure fell from 132
Mt to 121 Mt, Norway's from 7.2 Mt to 4.7 Mt, Estonia's from 2.4 Mt to 1.3 Mt.

**Why the fuels differ: age, not drivetrain.** SSB table 12578 splits the same
figures by vehicle age (2025, km per vehicle):

| age | all | petrol | diesel | battery |
|---|---|---|---|---|
| 0–4 years | 13,927 | 11,594 | 14,825 | 13,812 |
| 5–9 | 13,035 | 10,629 | 13,997 | 13,573 |
| 10–14 | 10,875 | 8,983 | 12,045 | 8,864 |
| 15–19 | 9,167 | 7,260 | 9,885 | 3,308 |
| 25 and over | 3,768 | 3,410 | 5,155 | 1,833 |

Age for age a battery car does the fleet average. The petrol fleet is old, and
an old car is driven little; that is most of the gap between 8,065 and 13,994.

**Consequence for projections.** Applied unchanged to a fleet that turns
electric, per-fuel mileages would add driving that nobody does (+14 % per car in
Norway, +17 % in Sweden for a fully electric fleet). `buildFleetEnergy()`
therefore holds each country's fleet-average km per car at its last observed
value: every projected year gets one factor per country (`kmScale`) that
restores the average, and the fuels keep their proportions. Observed years use
the figures as they are. What this does *not* model: travel demand changing
(cheaper electric km, population), and mileage by age inside the projection —
the vintage model knows each car's age, so that is the natural next refinement.
Eurostat's table carries the age split for a dozen countries, so the Norwegian
pattern is not a Norwegian oddity (km per car, all fuels, 2024): Germany 12,800
at 2–4 years and 7,300 at 20 and over; France 15,700 and 6,600; Sweden 18,400
and 8,700; Finland 16,900 and 3,800.

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

**Electricity** uses each country's own grid CO2e intensity (§6a): observed for
the years on record, and one of three scenarios after the last of them,
switchable on the chart (`feGridAt`):

- **recent trend continues** (default) — the country's own least-squares trend
  over the last ten data years carries on, never upwards and never below
  `grid_co2_target`. No acceleration and no stall is assumed. On the world series
  that is about −7 g a year, on Germany's about −17 g.
- **net-zero path** — linear from the last observed value to `grid_co2_target`
  (≈ 20 g) at `grid_co2_target_year` (2040), flat after: IEA Net Zero by 2050.
  This was the default until 2026-11. It is a normative scenario — what would
  have to happen — not a forecast, and as a silent default it made every
  electrified fleet look about as clean as it can ever be. It stays one click
  away.
- **today's grid held** — the last observed value forever. The worst case for the
  electrified side, and the what-if the Sankey's held mix (§6) implies.

The scenario moves emissions only — the **energy** Sankey holds the mix (§6), so
switching scenarios never moves the energy panel. The headline under the chart
shows the generation-weighted grid intensity of the selected year, so the number
behind the electricity band is always on the page.

On the 2025 world grid a BEV is near 95 gCO2e/km against ~215 for a petrol car;
on Norway's it is near 6. The chart stacks emissions by primary source (oil / gas
/ electricity), so the shift shows up directly: oil falls, the electricity band
moves with both the fleet and the chosen grid path, and the net comes down.
Factors and their sources live in the `# --- greenhouse-gas emissions ---` block
of `energy_factors.csv`.

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
analysis and cross-checking rather than for the page. Two things the page now
does that the R twin does not: it charges each country from its own grid (§6a;
the R script still uses the world mix rows of `energy_factors.csv`), and it
handles the young-fleet problem by starting each fleet from the age structure its
registration history implies (`37-fleet-data-harmonization.md` §7) rather than by
converging the rate.

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

1. **Grid trajectory** — per country and with three scenarios on the
   **emissions** side (§6a, §7), but the mix is still held for **energy** (§6). A
   physical-energy grid trajectory would need the mix itself to evolve.
1a. **Mileage outside Europe, and by fuel for the Netherlands, the UK,
   Denmark, Ireland and Switzerland** (§6b) — their national offices publish
   it; each is one block in `scripts/fetch_fleet_mileage.py`. **Per-country
   consumption** has no such source and stays one value per powertrain.
1c. **Mileage by age inside the projection** (§6b) instead of a held average.
1b. **Consumption-based grid** for net importers (§6a).
2. **Rest-of-world context band** — prototyped (an optional hatched band sized
   from a published world total, off by default). Not carried into the sub-tab,
   since it is the only figure that would not come from this repo.
3. **Pre-2018 history** — possible, at the cost of country coverage.
