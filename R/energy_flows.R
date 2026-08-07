# Primary-energy Sankey for road passenger cars.
#
# Unlike the purchase-flow model, this one is PHYSICS: energy is conserved, and
# every conversion step has a measured efficiency. There is no unidentifiable
# interior — the chain is determined by fleet composition, mileage, real-world
# consumption and published efficiencies. Factors live in energy_factors.csv.
#
# Accounting: IEA physical energy content method (see energy_factors.csv header).
#
# Chain, with losses branching off at each stage:
#   primary source -> energy carrier -> powertrain -> work at the wheel -> resistances
#
# Country universe follows the fleet tab: whatever is in fleet/fleet_initial.csv,
# so "world" here means the same bottom-up aggregate the fleet tab already shows.

# CSV mileage keys do not all match the powertrain codes (HEV is "hybrid").
KM_KEY <- c(PETROL = "km_petrol", DIESEL = "km_diesel", HEV = "km_hybrid",
            PHEV = "km_phev", BEV = "km_bev", GASFUEL = "km_petrol")

read_factors <- function(path = "energy_factors.csv") {
  f <- read.csv(path, stringsAsFactors = FALSE, comment.char = "#")
  setNames(as.numeric(f$value), trimws(f$key))
}

# Primary energy per kWh of electricity GENERATED, under the IEA physical method:
# renewables count as their own output, nuclear as heat at 33%, fossil at plant
# efficiency. This is the single number that makes electrified transport look
# good or bad, so it is derived here rather than hard-coded.
# Grid decarbonisation scenario. The real trajectory is a separate modelling
# project; until then two deliberately simple options:
#   "constant" (default) — today's mix held forever. A worst case, and honest:
#       it attributes none of the future improvement to the power sector.
#   "linear"  — renewables grow linearly to `target` share by `target_year`,
#       displacing coal first, then gas. PLACEHOLDER, flagged as such.
grid_mix_at <- function(f, year, scenario = "constant", base_year = 2025,
                        target = 0.75, target_year = 2050) {
  m <- c(coal = f[["mix_coal"]], gas = f[["mix_gas"]], nuclear = f[["mix_nuclear"]],
         other = f[["mix_other"]], renew = f[["mix_hydro"]] + f[["mix_wind"]] + f[["mix_solar"]])
  if (scenario == "constant" || year <= base_year) return(m)
  prog <- min(1, (year - base_year) / (target_year - base_year))
  want <- m[["renew"]] + prog * max(0, target - m[["renew"]])
  need <- want - m[["renew"]]
  take_coal <- min(m[["coal"]], need); m["coal"] <- m[["coal"]] - take_coal
  need <- need - take_coal
  take_gas <- min(m[["gas"]], need); m["gas"] <- m[["gas"]] - take_gas
  m["renew"] <- want
  m / sum(m)
}

grid_primary_factor_at <- function(f, year, scenario = "constant") {
  m <- grid_mix_at(f, year, scenario)
  m[["coal"]] / f[["eff_coal_plant"]] + m[["gas"]] / f[["eff_gas_plant"]] +
  m[["nuclear"]] / f[["eff_nuclear_iea"]] + m[["other"]] / f[["eff_other_plant"]] +
  m[["renew"]]
}

grid_primary_factor <- function(f) {
  f[["mix_coal"]]    / f[["eff_coal_plant"]] +
  f[["mix_gas"]]     / f[["eff_gas_plant"]] +
  f[["mix_nuclear"]] / f[["eff_nuclear_iea"]] +
  f[["mix_other"]]   / f[["eff_other_plant"]] +
  f[["mix_hydro"]] + f[["mix_wind"]] + f[["mix_solar"]]
}

# Grid CO2e intensity (kgCO2e per kWh GENERATED) at `year`, under a sourced
# scenario. Mirrors feGridCO2At() in index.html.
#   "linear"   - from grid_co2_now (at grid_co2_base_year) to grid_co2_target
#                (at grid_co2_target_year), flat outside that window.
#   "constant" - today's grid held forever.
grid_co2_at <- function(f, year = f[["grid_co2_base_year"]], scenario = "constant") {
  now <- f[["grid_co2_now"]]; tgt <- f[["grid_co2_target"]]
  if (scenario != "linear") return(now)
  by <- f[["grid_co2_base_year"]]; ty <- f[["grid_co2_target_year"]]
  if (year <= by) return(now)
  if (year >= ty) return(tgt)
  now + (tgt - now) * (year - by) / (ty - by)
}

# Per-vehicle annual energy, in kWh, for one powertrain.
# Returns carrier energy (at tank/wall), primary energy, and useful work.
vehicle_energy <- function(pt, f) {
  gp <- grid_primary_factor(f)
  elec_primary <- function(kwh_at_wall) {
    gen <- kwh_at_wall / (1 - f[["grid_td_loss"]])
    list(carrier = kwh_at_wall, primary = gen * gp)
  }
  fuel_primary <- function(litres, lhv, wtt) {
    kwh <- litres * lhv
    list(carrier = kwh, primary = kwh * wtt)
  }
  switch(pt,
    PETROL = { e <- fuel_primary(f[["cons_petrol"]] / 100 * f[["km_petrol"]],
                                 f[["lhv_petrol"]], f[["wtt_petrol"]])
               c(e, list(work = e$carrier * f[["ttw_ice"]], src = "oil")) },
    DIESEL = { e <- fuel_primary(f[["cons_diesel"]] / 100 * f[["km_diesel"]],
                                 f[["lhv_diesel"]], f[["wtt_diesel"]])
               c(e, list(work = e$carrier * f[["ttw_ice"]], src = "oil")) },
    HEV    = { e <- fuel_primary(f[["cons_hybrid"]] / 100 * f[["km_hybrid"]],
                                 f[["lhv_petrol"]], f[["wtt_petrol"]])
               c(e, list(work = e$carrier * f[["ttw_hybrid"]], src = "oil")) },
    PHEV   = { a <- fuel_primary(f[["cons_phev_fuel"]] / 100 * f[["km_phev"]],
                                 f[["lhv_petrol"]], f[["wtt_petrol"]])
               b <- elec_primary(f[["cons_phev_elec"]] / 100 * f[["km_phev"]])
               list(carrier = a$carrier + b$carrier,
                    primary = a$primary + b$primary,
                    work = a$carrier * f[["ttw_hybrid"]] + b$carrier * f[["ttw_bev"]],
                    src = "mixed", carrier_fuel = a$carrier, carrier_elec = b$carrier,
                    primary_fuel = a$primary, primary_elec = b$primary) },
    BEV    = { e <- elec_primary(f[["cons_bev"]] / 100 * f[["km_bev"]])
               c(e, list(work = e$carrier * f[["ttw_bev"]], src = "elec")) },
    # LPG/CNG: petrol-like engine efficiency, but the primary source is gas.
    GASFUEL = { e <- fuel_primary(f[["cons_petrol"]] / 100 * f[["km_petrol"]],
                                  f[["lhv_petrol"]], f[["wtt_gasfuel"]])
                c(e, list(work = e$carrier * f[["ttw_ice"]], src = "gas")) },
    stop("unknown powertrain: ", pt))
}

# Fleet stock by powertrain, aggregated over a country set, for one year.
# Mirrors the fleet tab's loader: HYBRID and PHEV/HEV are alternative encodings,
# so take whichever the row actually populates.
# `carry_forward`: national stock series end in different years (CA/IN/UK stop
# before 2025). Taking only exact-year rows silently changes the country set
# from year to year, which makes an animated aggregate jump for reasons that
# look like reality but are coverage artefacts. Instead take each country's
# most recent year <= `year`, and report which ones were carried forward.
fleet_stock <- function(year, countries = NULL, path = "fleet/fleet_initial.csv",
                        carry_forward = TRUE) {
  d <- read.csv(path, stringsAsFactors = FALSE, strip.white = TRUE)
  names(d) <- trimws(names(d)); d$country <- trimws(d$country)
  if (!is.null(countries)) d <- d[d$country %in% countries, , drop = FALSE]
  if (carry_forward) {
    d <- d[d$year <= year, , drop = FALSE]
    if (!nrow(d)) return(NULL)
    d <- do.call(rbind, lapply(split(d, d$country), function(x)
      x[which.max(x$year), , drop = FALSE]))
    attr_carried <- d$country[d$year < year]
  } else {
    d <- d[d$year == year, , drop = FALSE]
    attr_carried <- character(0)
  }
  if (!nrow(d)) return(NULL)
  num <- function(k) if (k %in% names(d)) { v <- suppressWarnings(as.numeric(d[[k]])); v[is.na(v)] <- 0; v } else rep(0, nrow(d))
  hybrid <- num("HYBRID"); hev <- num("HEV"); phev <- num("PHEV")
  # A single lumped HYBRID column stands in for HEV when the split is absent.
  hev_eff <- ifelse(hybrid > 100 & hev == 0, hybrid, hev)
  petrol <- num("PETROL"); diesel <- num("DIESEL"); others <- num("OTHERS")
  # OTHERS means two different things across sources. Where PETROL and DIESEL
  # are both absent it carries the ENTIRE combustion fleet (China: 322M cars in
  # OTHERS) — ignoring it understated the aggregate threefold. Where they are
  # populated it is a genuine residual (LPG/CNG, ~0.7% in Germany). Assign the
  # first case to petrol: markets reporting this way are overwhelmingly petrol
  # for passenger cars, and diesel shares there are low single digits.
  lumped <- petrol == 0 & diesel == 0 & others > 0
  petrol <- petrol + ifelse(lumped, others, 0)
  # The residual case is a different animal: where petrol/diesel ARE reported,
  # OTHERS is LPG/CNG — gas-derived, not oil-derived. Small (0.7% in Germany)
  # but it belongs on the gas branch of the primary column, not on petrol.
  gasfuel <- ifelse(lumped, 0, others)
  out <- c(BEV = sum(num("BEV")), PHEV = sum(phev), HEV = sum(hev_eff),
           DIESEL = sum(diesel), PETROL = sum(petrol), GASFUEL = sum(gasfuel))
  attr(out, "countries") <- sort(d$country)
  attr(out, "carried")   <- sort(attr_carried)
  out
}

# Which countries the fleet tab offers — the universe for "world".
fleet_countries <- function(path = "fleet/fleet_initial.csv") {
  d <- read.csv(path, stringsAsFactors = FALSE, strip.white = TRUE)
  sort(unique(trimws(d$country)))
}

# Full energy chain for a vehicle population (stock or annual registrations).
# Returns node totals and links, in TWh/year.
energy_chain <- function(counts, f = read_factors(),
                         year = f[["grid_co2_base_year"]], grid_scenario = "constant") {
  TWH <- 1e9  # kWh -> TWh
  pts <- names(counts)[counts > 0]
  agg <- list(prim_oil = 0, prim_elec = 0,
              carrier_petrol = 0, carrier_diesel = 0, carrier_elec = 0,
              work = 0, loss_wtt = 0, loss_conv = 0)
  per_pt <- list()
  for (pt in pts) {
    e <- vehicle_energy(pt, f); n <- counts[[pt]]
    carrier <- e$carrier * n; primary <- e$primary * n; work <- e$work * n
    if (pt == "PHEV") {
      agg$prim_oil  <- agg$prim_oil  + e$primary_fuel * n
      agg$prim_elec <- agg$prim_elec + e$primary_elec * n
      agg$carrier_petrol <- agg$carrier_petrol + e$carrier_fuel * n
      agg$carrier_elec   <- agg$carrier_elec   + e$carrier_elec * n
    } else if (e$src == "elec") {
      agg$prim_elec <- agg$prim_elec + primary
      agg$carrier_elec <- agg$carrier_elec + carrier
    } else {
      agg$prim_oil <- agg$prim_oil + primary
      if (pt == "DIESEL") agg$carrier_diesel <- agg$carrier_diesel + carrier
      else                agg$carrier_petrol <- agg$carrier_petrol + carrier
    }
    agg$work <- agg$work + work
    agg$loss_wtt  <- agg$loss_wtt  + (primary - carrier)
    agg$loss_conv <- agg$loss_conv + (carrier - work)
    per_pt[[pt]] <- list(n = n, carrier = carrier / TWH, primary = primary / TWH,
                         work = work / TWH,
                         primary_per_km = e$primary / f[[KM_KEY[[pt]]]])
  }
  total_primary <- agg$prim_oil + agg$prim_elec
  res <- c(air = f[["res_air"]], roll = f[["res_roll"]],
           brake = f[["res_brake"]], aux = f[["res_aux"]])
  # Well-to-wheel CO2e (Mt/yr), use phase. Fuels: JEC WTW per kWh; electricity:
  # sourced grid intensity under `grid_scenario` (see grid_co2_at). Gas fuel is
  # folded into the petrol carrier in this twin (as it is for energy), so its CO2
  # rides ghg_petrol — a sliver. Mirrors feChain()'s co2 block in index.html.
  MT <- 1e9  # kg -> Mt
  gen_elec <- agg$carrier_elec / (1 - f[["grid_td_loss"]])
  co2_oil  <- (agg$carrier_petrol * f[["ghg_petrol"]] + agg$carrier_diesel * f[["ghg_diesel"]]) / MT
  co2_elec <- (gen_elec * grid_co2_at(f, year, grid_scenario)) / MT
  list(
    unit = "TWh/yr",
    primary = list(oil = agg$prim_oil / TWH, electricity = agg$prim_elec / TWH,
                   total = total_primary / TWH),
    carrier = list(petrol = agg$carrier_petrol / TWH, diesel = agg$carrier_diesel / TWH,
                   electricity = agg$carrier_elec / TWH),
    work = agg$work / TWH,
    losses = list(supply = agg$loss_wtt / TWH, conversion = agg$loss_conv / TWH),
    resistances = as.list(res * agg$work / TWH),
    per_powertrain = per_pt,
    # CO2e in Mt/yr (well-to-wheel, use phase), split by primary source.
    co2 = list(oil = co2_oil, electricity = co2_elec, total = co2_oil + co2_elec),
    # Energy must balance: primary = work + all losses. Guards against a factor
    # typo silently producing a chart that does not conserve energy.
    balance_error = abs(total_primary - (agg$work + agg$loss_wtt + agg$loss_conv)) / total_primary
  )
}

if (sys.nframe() == 0) {
  f <- read_factors()
  cat(sprintf("Grid primary factor (IEA physical): %.2f kWh primary / kWh generated\n",
              grid_primary_factor(f)))
  cat(sprintf("Grid CO2e now: %.0f gCO2e/kWh (Ember); target %.0f by %d (IEA NZE)\n",
              1000 * f[["grid_co2_now"]], 1000 * f[["grid_co2_target"]],
              as.integer(f[["grid_co2_target_year"]])))
  cat("\nPrimary energy per km, by powertrain:\n")
  for (pt in c("PETROL", "DIESEL", "HEV", "PHEV", "BEV")) {
    e <- vehicle_energy(pt, f)
    km <- f[[KM_KEY[[pt]]]]
    cat(sprintf("  %-7s %.3f kWh/km primary   (carrier %.3f, useful %.3f)\n",
                pt, e$primary / km, e$carrier / km, e$work / km))
  }
  cs <- fleet_countries()
  cat("\nFleet-tab universe:", paste(cs, collapse = " "), "\n")
  st <- fleet_stock(2025, cs)
  if (!is.null(st)) {
    r <- energy_chain(st, f)
    cat(sprintf("\nStock 2025: %.0f M cars\n", sum(st) / 1e6))
    cat(sprintf("Primary energy: %.0f TWh/yr (oil %.0f, electricity %.0f)\n",
                r$primary$total, r$primary$oil, r$primary$electricity))
    cat(sprintf("Useful work at the wheel: %.0f TWh (%.0f%% of primary)\n",
                r$work, 100 * r$work / r$primary$total))
    cat(sprintf("Well-to-wheel CO2e: %.0f Mt/yr (oil %.0f, electricity %.1f)\n",
                r$co2$total, r$co2$oil, r$co2$electricity))
    cat(sprintf("Balance error: %.2e (must be ~0)\n", r$balance_error))
  }
}

# Periods a country reports per full year (12 monthly, 4 quarterly, 1 annual),
# taken as the maximum seen across its history. A year carrying fewer periods
# than this is a PART year: 2026 holds 4-6 months for the monthly reporters and
# one quarter for the quarterly ones. Summing it as if complete collapses that
# single year and makes the series jump back afterwards, which reads as a real
# market event. Callers must treat an incomplete year as unobserved.
periods_per_year <- function(path) {
  d <- read.csv(path, stringsAsFactors = FALSE)
  d <- d[d$variant %in% "Whole", , drop = FALSE]
  if (!nrow(d)) return(0L)
  as.integer(max(table(substr(d$period, 1, 4))))
}

year_is_complete <- function(path, year) {
  d <- read.csv(path, stringsAsFactors = FALSE)
  d <- d[d$variant %in% "Whole", , drop = FALSE]
  sum(substr(d$period, 1, 4) == as.character(year)) >= periods_per_year(path)
}

# --------------------------------------------------------------- projection
#
# The historical panels stop where national statistics stop. To carry the
# slider into the future we reuse the gallery's own machinery rather than
# inventing a second model:
#   registrations — the fitted Weibull trajectories in params.csv
#   fleet         — stock-flow roll-forward with the hazards in fleet/
#
# Two documented simplifications:
#   * params.csv resolves BEV / PHEV / ICE, where ICE deliberately includes
#     hybrids. Energy intensity differs a lot inside that bucket, so its
#     internal split (petrol : diesel : hybrid) is frozen at each country's
#     last observed year and only the bucket total follows the model.
#   * total market size is held at the last observed level. Modelling market
#     growth is a separate question and would confound the powertrain story.

# BEV / ICE share from the fitted Weibull, identical algebra to R/fit.R.
weibull_shares <- function(row, year) {
  bev <- 1 - exp(row$v1 * (year - (row$t0 - 1))^row$v2)
  ice <- exp(row$ice_v1 * (year - (row$ice_t0 - 1))^row$ice_v2)
  bev <- min(max(bev, 0), 1); ice <- min(max(ice, 0), 1)
  if (bev + ice > 1) ice <- 1 - bev
  c(BEV = bev, PHEV = max(0, 1 - bev - ice), ICE = ice)
}

hazards <- function(path = "fleet/hazard_defaults.csv", tier = "WORLD") {
  h <- read.csv(path, stringsAsFactors = FALSE, strip.white = TRUE)
  names(h) <- trimws(names(h)); h$country <- trimws(h$country); h$fuel <- trimws(h$fuel)
  h <- h[h$country == tier, ]
  setNames(as.numeric(h$hazard), h$fuel)
}

# Registrations for one country in `year`: observed where available, else the
# Weibull shares applied to the frozen market size and ICE composition.
project_registrations <- function(counts_last, params_row, year, last_year) {
  if (year <= last_year) return(counts_last)
  sh <- weibull_shares(params_row, year)
  total <- sum(counts_last)
  ice_last <- counts_last[c("PETROL", "DIESEL", "HEV", "GASFUEL")]
  ice_last[is.na(ice_last)] <- 0
  mix <- if (sum(ice_last) > 0) ice_last / sum(ice_last) else c(PETROL = 1, DIESEL = 0, HEV = 0, GASFUEL = 0)
  out <- c(BEV = total * sh[["BEV"]], PHEV = total * sh[["PHEV"]], mix * total * sh[["ICE"]])
  out[names(counts_last)]
}

# Roll a fleet forward one year: survivors plus this year's registrations.
roll_fleet <- function(stock, regs, haz = hazards()) {
  hz <- c(BEV = haz[["BEV"]], PHEV = haz[["PHEV"]], HEV = haz[["HEV"]],
          DIESEL = haz[["REST"]], PETROL = haz[["REST"]], GASFUEL = haz[["REST"]])
  keys <- names(stock)
  # pmax(0, x) would drop the names (attributes come from the first argument),
  # and a nameless vector silently breaks every downstream lookup.
  out <- stock * (1 - hz[keys]) + regs[keys]
  out[out < 0] <- 0
  setNames(as.numeric(out), keys)
}

# Attrition derived from the repo's OWN data, not from an external assumption:
# the stock-flow identity S(t) = S(t-1)*(1-h) + R(t) inverts to
#   h = 1 - (S(t) - R(t)) / S(t-1)
# evaluated only on years where both stock years are genuinely observed (no
# carry-forward) and registrations exist. Median over those years per country.
# Falls back to the pooled median where a country has too few usable years.
#
# This replaces the borrowed NL/EU/WORLD hazards for projection. Those put BEV
# attrition at 2%/yr — a figure from a young stock where almost nothing has
# reached scrapping age — which over 25 years implies a 50-year vehicle life.
implied_hazard <- function(reg_fn, path = "fleet/fleet_initial.csv", min_years = 4) {
  d <- read.csv(path, stringsAsFactors = FALSE, strip.white = TRUE)
  d$country <- trimws(d$country)
  per <- list()
  for (cd in sort(unique(d$country))) {
    ys <- sort(d$year[d$country == cd]); hs <- numeric(0)
    for (y in ys) {
      if (!(y - 1) %in% ys) next
      a <- fleet_stock(y, cd, path, carry_forward = FALSE)
      b <- fleet_stock(y - 1, cd, path, carry_forward = FALSE)
      r <- reg_fn(cd, y)
      if (is.null(a) || is.null(b) || is.null(r)) next
      h <- 1 - (sum(a) - sum(r)) / sum(b)
      if (is.finite(h) && h > -0.05 && h < 0.4) hs <- c(hs, h)
    }
    if (length(hs) >= min_years) per[[cd]] <- stats::median(hs)
  }
  pooled <- if (length(per)) stats::median(unlist(per)) else 0.05
  list(per_country = per, pooled = pooled)
}

# Roll forward using a single country-level rate. Per-fuel rates are not
# identifiable from the repo at this resolution, and inventing them is exactly
# what the borrowed hazards did wrong.
roll_fleet_h <- function(stock, regs, h) {
  keys <- names(stock)
  out <- stock * (1 - h) + regs[keys]
  out[out < 0] <- 0
  setNames(as.numeric(out), keys)
}

# A measured attrition rate is only a steady-state rate in a MATURE fleet. Where
# motorisation is still rising the stock is young, almost nothing has reached
# scrapping age, and the identity above returns a very low rate — China 0.76%/yr,
# i.e. a 132-year vehicle life. Projecting that unchanged doubles China's fleet
# by 2050 and drives most of the aggregate growth. It is the same young-stock
# artefact that made the borrowed 2% BEV hazard useless, one level up.
#
# Fix: let each country's rate converge from what it shows today toward the
# steady-state rate of the mature markets, over `tau` years. Both ends come from
# the repo — only the convergence itself is a structural assumption.
#
# "Mature" = implied lifetime under 25 years, i.e. the countries whose fleets are
# actually turning over.
steady_hazard <- function(h, max_life = 25) {
  mature <- unlist(h$per_country)
  mature <- mature[mature >= 1 / max_life]
  if (!length(mature)) h$pooled else stats::median(mature)
}

hazard_at <- function(h_obs, h_steady, year, base_year = 2025, tau = 12) {
  if (year <= base_year) return(h_obs)
  h_obs + (h_steady - h_obs) * (1 - exp(-(year - base_year) / tau))
}
