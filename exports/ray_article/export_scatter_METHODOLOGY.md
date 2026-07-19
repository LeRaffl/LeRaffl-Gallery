# Domestic vs export BEV share — scatter/bubble methodology

Data provenance and definitions for `export_scatter_production.png` and
`export_scatter_gdp_per_capita.png`, produced by
[`scripts/export_scatter_chart.R`](../../scripts/export_scatter_chart.R).

One dot per vehicle-exporting country (China, Germany, Japan, South Korea, US,
Thailand — the same six as the domestic BEV-share charts). Snapshot year: **2024**
(latest full year with complete trade data).

## Axes

### X — Domestic BEV share of new registrations (2024)
- **What it is:** share of that country's *new vehicle registrations at home* that
  are battery-electric (BEV only, excludes PHEV/HEV/ICE).
- **Source:** this repository's own fitted BEV-share trajectories (`params.csv`),
  the same Weibull fits used across the gallery. Underlying registration data:
  CPCA (China), JADA/JAMA (Japan), KBA (Germany), molit.go.kr (South Korea),
  ANL/StatCan (US), data.thaiauto.or.th (Thailand).
- **How the number is taken:** the fitted curve evaluated at **mid-2024**
  (internal time `x = 2023.5`), so it represents the full calendar year 2024 and
  is time-aligned with the Y-axis. It is a smoothed fit, not a raw monthly point.

### Y — BEV share of car exports (2024)
- **What it is:** share of that country's *passenger-car exports, by value*, that
  are battery-electric. The export-side mirror of the X-axis.
- **Definition:** `value(HS 870380) / value(HS 8703)`.
  - **HS 870380** = passenger cars propelled *solely* by electric motor (BEV).
  - **HS 8703** = all passenger motor cars (BEV is a subheading of it, so the
    ratio is a clean 0–1 fraction).
- **Source:** UN Comtrade, public preview API
  (`https://comtradeapi.un.org/public/v1/preview/C/A/HS`), export flow (`X`),
  reporter → World (`partnerCode=0`), annual, 2024. No API key required.
- **By value (USD), not units:** Comtrade quantity/unit data is patchier than
  value; value share is the robust choice for a snapshot.

## Bubble size (two variants)
- `export_scatter_production.png` — **total vehicle production 2024**, OICA
  (oica.net, "By country/region 2024"). Hardcoded in the script from OICA's
  published table.
- `export_scatter_gdp_per_capita.png` — **GDP per capita (current US$) 2024**,
  World Bank indicator `NY.GDP.PCAP.CD` via the World Bank API.

## The 2024 snapshot (for citation / reproducibility)

| Country | Domestic BEV share | BEV export share | Production (OICA) | GDP/capita (WB) |
|---|---|---|---|---|
| China | 27.5% | 35.4% | 31,281,592 | $13,293 |
| Germany | 18.1% | 23.3% | 4,069,222 | $56,104 |
| South Korea | 11.7% | 14.8% | 4,127,252 | $36,239 |
| Thailand | 12.8% | 3.0% | 1,468,997 | $7,387 |
| US | 6.6% | 9.3% | 10,562,188 | $86,170 |
| Japan | 1.8% | 6.3% | 8,234,681 | $33,797 |

(Export shares recomputed live from Comtrade on each run; small revisions to
Comtrade back-data can shift them slightly.)

## The 45° parity line
The dashed diagonal is **`y = x` (parity)**, not a fitted trend line. It marks
where a country's *export* BEV mix equals its *home* BEV mix.
- **On the line:** exports as electrified as the home market.
- **Above (China, Germany, Korea, US, Japan):** exports *more* BEV-heavy than the
  2024 home market — these car makers build BEVs partly for export.
- **Below (Thailand):** exports *less* electrified than home — see caveat.

It is a reading aid, **not proof of the thesis**. Ray's thesis (domestic
electrification predicts export competitiveness) shows up as the cloud sloping
up-right; with n=6 a regression line would be statistically thin and is not drawn.

## Caveats
- **Thailand is the structural outlier.** Its domestic BEV uptake is driven by
  *imported* Chinese BEVs and local assembly for the home market, while its export
  base is still overwhelmingly ICE pickup trucks (the ASEAN/Australia hub). So it
  electrifies at home but exports combustion — hence far below parity. Its BEV
  export capacity (EV3.0/3.5 incentives) is being built now and will appear in
  later years. Treat Thailand as a transition/lag case, not a counterexample.
- **HS 870380 is only clean from ~2017/2018.** Before HS2017 revisions BEVs were
  buried in the residual code 870390, so this method does not support a long
  export time series — only recent snapshots.
- **Re-exports** (transhipment hubs) can inflate some reporters; the six here are
  primary producers, so the effect is minor, but worth a sanity check if the
  country set grows.
- **Comtrade aggregate row must be forced** (`partner2Code=0&motCode=0&customsCode=C00`),
  otherwise the API returns per-transport-mode sub-rows that double-count on
  summation (raw Germany summed to a false ~$159B vs the true ~$40B aggregate).
- **X and Y are both 2024** but from different pipelines (fitted domestic curve vs
  actual trade), so exact comparability has the usual fit-vs-observed slack.
