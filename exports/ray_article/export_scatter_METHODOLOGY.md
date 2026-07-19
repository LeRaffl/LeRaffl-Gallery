# Domestic vs export BEV share — scatter/trajectory methodology

Data provenance and definitions for the export-scatter chart set, produced by
[`scripts/export_scatter_chart.R`](../../scripts/export_scatter_chart.R):

- `export_scatter_<year>_production.png` / `..._gdp_per_capita.png` — one scatter
  per year, **2021–2024** (the years with complete cross-country trade data).
- `export_trajectory_production.png` / `..._gdp_per_capita.png` — every country's
  **2021 → latest** path with an arrowhead at the most recent point.

Six vehicle-exporting countries (China, Germany, Japan, South Korea, US,
Thailand — the same six as the domestic BEV-share charts).

## Axes

### X — Domestic BEV share of new registrations (per year)
- **What it is:** share of that country's *new vehicle registrations at home* that
  are battery-electric (BEV only; excludes PHEV/HEV/ICE).
- **Source:** raw observed data from this repo's country CSVs (`data/<Country>.csv`)
  — **not** the fitted model. Underlying registration data: CPCA (China),
  JADA/JAMA (Japan), KBA (Germany), molit.go.kr (South Korea), ANL/StatCan (US),
  data.thaiauto.or.th (Thailand).
- **How:** `sum(BEV) / sum(TOTAL)` over that calendar year's rows. Every country
  reports these years as clean 12-month monthly data, so there is no interval
  overlap to double-count. Actual figures, not modelled.

### Y — BEV share of passenger-car exports (per year)
- **What it is:** share of that country's *passenger-car exports, by value*, that
  are battery-electric. The export-side mirror of X.
- **Definition:** `value(HS 870380) / value(HS 8703)`.
  - **HS 870380** = passenger cars propelled *solely* by electric motor (BEV).
  - **HS 8703** = passenger motor cars (BEV is a subheading, so the ratio is a
    clean 0–1 fraction).
- **⚠️ Pickups and LCVs are NOT included.** Goods vehicles — one-ton pickups,
  vans, light trucks — are **HS 8704** and sit outside both numerator and
  denominator. Y is strictly a *passenger-car* export mix. This matters most for
  Thailand (whose export backbone is ICE pickups) and the US (pickup exports):
  their *total* vehicle-export mix is even more ICE-heavy than Y shows.
- **Source:** UN Comtrade public preview API
  (`https://comtradeapi.un.org/public/v1/preview/C/A/HS`), export flow, reporter →
  World, annual. No API key. Pulled once into the cache below by
  [`scripts/fetch_export_shares.R`](../../scripts/fetch_export_shares.R); the chart
  script reads the cache, so re-renders need no network.
- **By value (USD), not units:** Comtrade quantity data is patchier than value.

**Cache:** [`comtrade_bev_export_shares.csv`](comtrade_bev_export_shares.csv) —
`year, country, bev_exp_usd, car_exp_usd, ev_export_share`, 2021–2025.

## Bubble size (two variants, fixed per country)
Bubble size is the same in every year/panel — it encodes **country scale**, not a
time-varying value, so the eye tracks *position* (the story), not pulsing bubbles.
Reference year 2024:
- `*_production.png` — total vehicle production 2024, **OICA** (oica.net).
- `*_gdp_per_capita.png` — GDP per capita (current US$) 2024, **World Bank**
  (`NY.GDP.PCAP.CD`).

## Data coverage
- **2021–2024:** complete for all six — used for the per-year scatters and the
  trajectory body.
- **2025:** domestic data complete (full 12 months, all six); export data filed by
  Germany, Japan, South Korea and the US, but **not yet China or Thailand**. So
  their trajectory paths end 2024 (marked with `*`) and there is no 2025 scatter.

## BEV export share by country-year (for citation)

| Country | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|
| China | 35.2% | 45.0% | 44.0% | 35.4% | not filed |
| Germany | 11.2% | 17.0% | 22.4% | 23.3% | 25.5% |
| South Korea | 12.7% | 15.8% | 21.0% | 14.8% | 12.7% |
| US | 8.5% | 10.0% | 11.5% | 9.3% | 7.0% |
| Japan | 1.2% | 2.5% | 6.9% | 6.3% | 4.7% |
| Thailand | 0.0% | 0.0% | 0.1% | 3.0% | not filed |

Domestic BEV share 2024 (X on the 2024 panel): China 27.7%, Germany 13.5%,
Thailand 10.9%, South Korea 8.7%, US 7.8%, Japan 1.3%.

## The 45° parity line
The dashed diagonal is **`y = x` (parity)**, not a fitted trend line — it marks
where a country's *export* BEV mix equals its *home* BEV mix.
- **Above:** exports more BEV-heavy than the home market (most car makers, most
  years — they build BEVs partly for export).
- **Below:** exports less electrified than home (Thailand).

It is a reading aid, **not proof of the thesis**. With n=6 a regression line would
be statistically thin and is not drawn.

## What the data actually shows (read before framing the thesis)
The **cross-sectional** thesis holds: in any single year, high-domestic countries
(China, Germany) sit top-right and laggards (Japan) bottom-left.

The **temporal** picture is more nuanced and the trajectory makes it honest:
- **Only Germany** rises cleanly on both axes (export share 11% → 26%).
- **China, South Korea, US, Japan** all **peaked ~2023 and then fell back** on
  export share, even as domestic BEV share kept climbing — because BEV export
  *value* rose but total car exports rose too (ICE export booms, e.g. China to
  Russia), and 2024–25 EV demand cooled. So "electrify at home ⇒ rising EV *export
  share*" does **not** hold as a simple time trend for four of six.
- **South Korea's fall (21% → 13%) is partly production offshoring, not EV
  retreat:** Hyundai/Kia's US Metaplant replaced Korean-built EV exports to the US
  with local production. An export-share drop can mean the EVs are now built
  closer to the customer.
- **Thailand** moves right (domestic up) while staying near zero on exports.

Framing implication: present the scatter as a **cross-sectional ordering**
(leaders vs laggards), not as proof that domestic uptake mechanically drives a
rising export share over time — the trajectory would contradict that stronger
claim.

## Caveats
- **Vehicle-scope mismatch between X and Y (the main caveat).** X covers each
  country's *home-market registrations as reported by its source*: passenger cars
  for China (CPCA) and Germany (KBA), but **light-duty vehicles including
  pickups/light trucks for the US (ANL)** and **including pickups for Thailand**
  (thaiauto — pickups are the majority of the Thai home market). Y covers
  *passenger cars only* (HS 8703). Consequences:
  - The **cross-sectional clustering is robust** (US and Japan are laggards on
    both axes regardless of scope; China and Germany lead on both).
  - The **parity reading is fragile for the US and Thailand**: a cars-only US
    home share would be higher than 7.8% (light trucks are ~80% of the US market
    and mostly ICE), which could move the US to or below parity. Do not build an
    argument on the US's exact position relative to the line.
  - All six countries are kept, with this caveat, rather than dropped — removing
    the US or Thailand would gut the leaders/laggards comparison the charts exist
    to show, and their *cluster* positions are scope-robust.
- **Thailand is the structural outlier — precisely stated:** ~97% of its
  *passenger-car* exports are still ICE, while its home market electrifies via
  imported Chinese BEVs and local assembly. Its main export line — ICE one-ton
  pickups — is HS 8704 and **not in Y at all**, so Thailand's total vehicle-export
  mix is even more combustion-heavy than the chart shows; adding pickups would
  push it further below parity, not less. Its BEV export capacity (EV3.0/3.5,
  Chinese-brand plants exporting from 2024) is only ramping now: the 2023→2024
  jump from 0.1% to 3.0% is that ramp starting. Treat it as a transition case.
- **HS 870380 is only clean from ~2017/2018** (before HS2017, BEVs sat in the
  residual code 870390) — so this method does not support a longer time series.
- **Comtrade aggregate row must be forced** (`partner2Code=0&motCode=0&customsCode=C00`),
  else the API returns per-transport-mode sub-rows that double-count on summation
  (raw Germany summed to a false ~$159B vs the true ~$40B aggregate).
- **Re-exports** (transhipment hubs) can inflate some reporters; the six here are
  primary producers, so the effect is minor. Comtrade also does not separate
  new from used vehicles (relevant to Japan's large used-car exports, though by
  *value* the effect is modest).
- **X and Y come from different pipelines** (registration CSVs vs customs records);
  both are observed data, with the usual registration-vs-customs definitional slack.
