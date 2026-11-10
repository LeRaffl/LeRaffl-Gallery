---
explainer: true
slug: fleet
title: How the Fleet tab is calculated
summary: The Fleet tab shows how many cars of each drivetrain are on the road, projects that stock forward year by year, and converts it into the energy the cars need and the CO2 they cause. Every input is observed per country where a statistics office publishes it. This page walks through the calculation, shows the data behind each step, and says what is assumed.
figures: fleet
flow_heading: The calculation, step by step
flow_position: top
processing:
- title: 1 · Start from the cars that are registered today
  text:
  - The starting point is each country's stock of passenger cars by drivetrain at the end of the last year on record (battery, plug-in hybrid, full hybrid, petrol, diesel, other). It comes from the national register or from Eurostat. Nothing about it is modelled.
- title: 2 · Work out how old those cars are
  text:
  - A fleet of old cars loses many cars next year, a fleet of young cars almost none. So the first thing the model needs is the age of the stock.
  decision:
    ask: Does Eurostat publish this country's stock by age band?
    branches:
    - when: yes (27 countries)
      then: use the observed shares under 5, 5–10, 10–20 and over 20 years; battery cars and hybrids are placed by their own registration years first
    - when: 'no'
      then:
        ask: Is there an unbroken registration history of at least five years?
        branches:
        - when: 'yes'
          then: each year's registrations, thinned by the survival curve, fill the young ages; the rest of the stock is older than the record
        - when: 'no'
          then: assume a mature fleet (the age mix that a steady stream of registrations settles into)
- title: 3 · Set how many cars leave each year
  text:
  - The share of the stock that leaves per year is not assumed. It is read off each country's own record — last year's stock plus this year's new registrations minus this year's stock — as a median over the last five years.
  decision:
    ask: Is "Match each country's observed turnover" switched on (the default)?
    branches:
    - when: 'no'
      then: the seven rates typed into the Hazard section apply as they are, the same for every country
    - when: 'yes'
      then:
        ask: Does the country have an observed rate?
        branches:
        - when: 'no'
          then: the typed rates apply
        - when: yes, 1% a year or more
          then: all seven rates are scaled by one factor so the first projected year loses exactly that share
        - when: yes, below 1% (more used cars arrive than are scrapped)
          then: 1% of the fleet leaves, and the difference is booked as used cars arriving
- title: 4 · Decide which cars leave
  decision:
    ask: Which hazard model is selected?
    branches:
    - when: Per-vintage Weibull (the default)
      then: every model year is tracked on its own; a young car almost never leaves, an old one leaves fast
    - when: Constant rate
      then: every category loses the same share each year whatever its age
- title: 5 · Add the new cars
  text:
  - The number of new cars per year is the country's registrations of the last 12 months. How they split is taken from the gallery's own fitted curves and from the country's recent registrations.
  rules_head: [Part of the new cars, Goes to]
  rules:
  - [battery cars — the fitted BEV curve for that year, BEV]
  - [plug-in hybrids — what lies between the BEV curve and the combustion curve, PHEV (or the combined hybrid band where the stock does not separate plug-ins)]
  - [the combustion side — split by the last 12 months of registrations, full hybrid / petrol / diesel / gas and other]
- title: 6 · Repeat for every year up to the end year
  text:
  - Steps 4 and 5 are repeated year by year. Each year's result is the next year's starting fleet, one year older.
- title: 7 · Convert cars into energy
  text:
  - Energy is cars × kilometres per car × consumption per kilometre, traced back to what comes out of the ground.
  decision:
    ask: Are the kilometres driven published for this country?
    branches:
    - when: yes, by fuel (12 countries)
      then: each fuel's own kilometres per car
    - when: yes, for all cars only (4 countries)
      then: the cross-country pattern between the fuels, scaled to that country's level
    - when: 'no'
      then: the median of the countries that report by fuel
  note: In projected years each country's kilometres per car are held at the last observed value, so a fleet that turns electric does not appear to drive more.
- title: 8 · Convert energy into CO2
  text:
  - Fuel is counted well-to-wheel (getting it to the car and burning it). Electricity is counted at the intensity of the grid in the country where the car is charged.
  decision:
    ask: Is the year within the grid data on record?
    branches:
    - when: 'yes'
      then: that year's own grid, so an observed fleet year meets the grid it ran on
    - when: no — a future year
      then:
        ask: Which grid scenario is selected?
        branches:
        - when: recent trend continues (the default)
          then: the grid keeps improving at its own pace of the last ten years, no faster
        - when: net-zero path
          then: linear to about 20 g per kWh by 2040 (IEA Net Zero by 2050 — a target, not a forecast)
        - when: today's grid held
          then: the last observed grid, unchanged
sections:
- heading: What this is, and what it is not
  text:
  - It is a stock-and-flow model. Cars on the road are a stock; registrations flow in and scrapped or exported cars flow out. Given the stock today, how many cars leave and how many arrive, next year's stock follows by arithmetic. The only genuinely uncertain inputs are how many cars will be registered and what they will be, and those come from the gallery's fitted adoption curves.
  - It is not an official forecast. The adoption curves are this project's own model, and the projection holds several things constant that will change (listed at the end). Read it as "what follows if recent behaviour continues", country by country.
- heading: Why it was rebuilt in November 2026
  text:
  - A review compared the tab's defaults with the data. The defaults were global guesses, and several were visibly wrong in the default chart.
  list:
  - One attrition level for every country made growing fleets shrink. With the old defaults Finland's fleet halved by 2035 and China's fell by a fifth. Neither fleet is shrinking.
  - Battery fleets, whose cars are mostly under five years old, were treated as if they were as old as the rest of the fleet and started losing cars at once.
  - Battery cars were given a 40% longer life than petrol cars, without a source. No battery fleet is old enough to show a difference either way.
  - Every new petrol and diesel car was booked under "Other", which the Energy view counts as a gas car. By 2035 almost a quarter of Germany's projected fleet was a gas car.
  - Every petrol car in every country was assumed to drive 11,000 km a year and every diesel 17,500. The measured median is about 9,100 and 14,400.
  - Every electric car was charged from one world-average grid. Norway's grid emits about 30 g of CO2 per kWh, the world average about 460.
  - The default grid scenario was a net-zero target rather than a continuation of what grids have been doing.
- heading: How many cars leave — observed per country
  id: turnover
  text:
  - Stock is a balance. If a country had 49.3 million cars at the end of one year, registered 2.9 million new ones and had 49.5 million at the end of the next, then 2.7 million cars left — 5.5% of the stock. That is all the calculation is, repeated for the last five years, and the median is used.
  - It is a net figure, and it describes the register rather than the car. It counts scrappage and exports and subtracts used cars coming in. Countries that export their young used cars sit at the top of the chart; countries that import used cars sit at the bottom, some below zero because more used cars arrive than are scrapped.
  figure: turnover
  after:
  - This is why one global number could not be right. The projection matches each country's first projected year to its own bar. After that the rate drifts as the fleet's age structure changes — a model effect, not a forecast of policy.
- heading: How old the fleet is — observed per country
  id: age
  text:
  - The same turnover means different things for a young fleet and an old one. Eurostat publishes the stock by age band for 27 of the fleet countries, and the projection starts from exactly those shares.
  figure: ages
  after:
  - Battery cars and hybrids are placed first, by the years they were actually registered in, because they are far younger than the rest. What is left of each band is shared among petrol, diesel and other cars.
- heading: Which cars leave — the survival curve
  id: survival
  text:
  - Inside the model every model year loses cars according to a Weibull survival curve. It has two numbers. The scale sets how long cars last and is calibrated per country (previous two sections). The shape sets how sharply the chance of leaving rises with age.
  - The shape used to be 3.0 by convention. It is now fitted. Eurostat has each country's new registrations back to 1970, so a survival curve applied to them must reproduce the observed age bands. For the registers that are neither fed by used imports nor drained by exports, the best shape lies between about 2 and 3, and the median is the default.
  figure: survival
  after:
  - The three curves share the same average life and differ only in shape. A lower shape spreads departures over more ages; a higher one bunches them around the average life.
  - Where the curve is wrong whatever its shape is the tail. Fitted curves leave 5 to 7% of a fleet over 20 years old where 9 to 12% is observed, because some cars are kept far longer than any smooth curve allows. That is one reason the projection starts from the observed age bands and not from the fitted curve. The table under the chart shows both shares per country.
- heading: What the new cars are
  id: inflow
  text:
  - The gallery's fitted curves give the battery share and the combustion share of future registrations; plug-in hybrids are what lies between the two. "Combustion" there means everything without a plug, so it contains full hybrids, petrol, diesel and gas cars. That side is split the way each country's last 12 months of registrations were split.
  figure: inflow
  after:
  - Countries whose source does not report petrol and diesel separately are not in the chart; for them the split follows the existing stock. The split is held constant in the projection, which overstates future diesel where diesel is still losing share.
- heading: How far cars are driven
  id: mileage
  text:
  - Kilometres per car come from odometer readings at inspection, published by Eurostat by country and by fuel. They are divided by the stock, so that cars times kilometres gives the kilometres actually driven.
  figure: mileage
  after:
  - Battery cars are driven more than petrol cars, but not because they are electric. Norway publishes the same figures by the age of the car. Cars up to four years old do about 13,800 km a year as battery cars and 13,900 on average across all fuels; cars of 25 years and over do under 4,000. Petrol cars are mostly old, and old cars are driven little.
  - For that reason the projection does not let electrification add driving. Each country's kilometres per car stay at their last observed value, and the fuels keep their proportions to each other.
  - A country's per-fuel figures are only used where Eurostat's table shows that petrol and diesel are not hiding the hybrids. Otherwise only its all-car figure is used.
- heading: How clean the electricity is
  id: grid
  text:
  - An electric car is as clean as the grid it is charged from. The Energy view uses each country's own generation mix and CO2 intensity, year by year as far as the record goes (Ember's yearly electricity data).
  figure: grid
  after:
  - The figure is the electricity a country generates. A country that imports much of its electricity consumes a different mix; Luxembourg is the clearest case.
- heading: What the projection assumes — read before quoting a number
  list:
  - Turnover stays at its recent level. There is no saturation — a fleet that has been growing keeps growing. Over ten years that is the recent trend; over twenty-five it is an extrapolation.
  - The number of new cars per year stays at the last 12 months.
  - The split of the combustion side between hybrid, petrol and diesel stays as it is today.
  - One turnover level per country, not per fuel. Countries that export young battery cars keep them in the projection.
  - Used cars that arrive are assumed to look like the fleet they arrive in.
  - One survival-curve shape for every country and every drivetrain.
  - Consumption per kilometre is one fleet-average value per drivetrain for every country. This is the least well-founded input left.
  - Countries without mileage statistics of their own use a median of European countries. That includes China, India and Canada.
  - Emissions cover fuel and electricity in use, well-to-wheel. Building the car and its battery is not included.
  - Passenger cars only. Vans, trucks and buses are not in the Fleet tab yet.
- heading: Where the numbers come from
  text:
  - Every file is fetched or derived by a script and refreshed monthly. Nothing is typed in by hand.
  list:
  - Stock by drivetrain — national registers (Germany's KBA and others) and Eurostat, "Passenger cars by type of motor energy".
  - Stock by age and new registrations since 1970 — Eurostat, "Passenger cars by age" and "New passenger cars".
  - New registrations and the fitted adoption curves — the gallery's own country data.
  - Kilometres driven by fuel — Eurostat, "Road traffic performance by age of vehicle, type of vehicle and motor energy"; Statistics Norway for Norway.
  - Electricity mix and CO2 intensity — Ember's yearly electricity data, via Our World in Data.
  - Fuel energy content and well-to-wheel CO2 — the JEC well-to-wheels study (JRC, EUCAR, Concawe).
  - Real-world consumption per drivetrain — single values from the literature, listed with their sources in energy_factors.csv.
---

# 65 · Fleet model — the public explainer

This file is the source of **`sources/fleet.html`**, "How the Fleet tab is
calculated": the page the Fleet tab links to and the one to point people at
when they ask how a fleet or emissions number comes about. Its front-matter is
the page (`scripts/build_source_pages.py`, the same explainer mechanism as
`61-tag-system.md`):

- `processing:` — the step-by-step flow with decision gateways, shown first
  (`flow_position: top`).
- `sections:` — the prose. A section's `figure:` names a chart from
  `assets/fleet_figures.js`, which draws it **from the live `fleet/` files at
  page load**; `list:` renders bullets; `after:` is prose under the chart;
  `id:` is the anchor the Fleet tab deep-links to.
- `figures: fleet` — loads that script.

## Keeping it true

- **Charts cannot go stale**: they read `fleet/fleet_calibration.json`,
  `fleet/survival_fit.csv` and `fleet/grid_mix.csv`, the files the tab reads.
- **Prose can.** Numbers written into the text above are examples and are
  phrased as such ("about", a named year). When a default or a rule changes,
  change the sentence here too: this page is listed under *The Fleet
  projection* in `AGENTS.md`'s "when you change X".
- `scripts/test_fleet_explainer.py` checks that every `figure:` exists in the
  script, that the page is generated and linked from the Fleet tab, and that
  the defaults the prose names (shape, the 1% floor) still match the code.

## Where the detail lives

| Question | Document |
|---|---|
| Calibration file, rules, bounds, what is still assumed | `37-fleet-data-harmonization.md` §7 |
| Energy chain, mileage, grid, emissions | `architecture/energy-view-methodology.md` |
| File inventory and who writes what | `03-data-objects.md` §3.9 |
| Workflows | `08-deploy-ops.md` (`refresh-fleet-data.yml`, `build-fleet-calibration.yml`) |

## Figures

| `figure:` | Drawn from | Shows |
|---|---|---|
| `turnover` | `attrition.rate` | observed net attrition per country, with the 1% floor |
| `ages` | `age_bands` | stock by age band per country |
| `survival` | `survival_fit.csv` | survival curve at the lowest, median and highest usable shape; fits in the table |
| `inflow` | `inflow_mix` | split of the non-plug-in registrations |
| `mileage` | `mileage`, `mileage_default` | km per car by fuel per country, and the median |
| `grid` | `grid_mix.csv` | grid CO2e intensity per country, latest year |

Colours: charts stay light in dark mode like every chart on the site
(`02-components.md` §2.12). The four series colours (petrol `#3a78b5`, diesel
`#c2622d`, battery `#1f9a8a`, hybrid `#8a5fb5`) pass the palette validator's
checks for lightness, chroma, colour-vision separation and contrast; the
site's muted fuel colours do not, which is why the explainer does not reuse
them.
