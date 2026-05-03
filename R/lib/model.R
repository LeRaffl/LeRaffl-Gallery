# R/lib/model.R
# Weibull-style logistic fit, replicated bit-for-bit from the original
# per-country scripts. Math is intentionally unchanged.

suppressPackageStartupMessages({ library(stats) })

# Build the closure-based regression / RSS pair so that `verschiebung`
# stays bound exactly the way it does in the original scripts.
make_model_funs <- function(verschiebung) {
  reg <- function(v, x, type = "BEV") {
    if (type == "ICE")          return(1 - (1 - exp(v[1] * (x - (verschiebung - 1))^v[2])))
    if (type == "BEV")          return(1     - exp(v[1] * (x - (verschiebung - 1))^v[2]))
    if (type == "BEV extended") return(v[3]  - exp(v[1] * (x - (verschiebung - 1))^v[2])
                                        + ((1 - v[3]) - exp(v[4] * (x - (verschiebung - 1))^v[5]) + v[3])
                                        + (1 - v[3]))
    stop("Unknown type")
  }

  reg_ice <- function(v, x, type = "ICE") {
    if (type == "ICE") return(1 - (1 - 1 * exp(v[1] * (x - (verschiebung - 1))^v[2])))
    if (type == "BEV") return((0.98 - exp(v[1] * (x - (verschiebung - 1))^v[2])))
    stop("Unknown type")
  }

  list(reg = reg, reg_ice = reg_ice)
}

# Fit the BEV + ICE Weibulls iteratively (one fit per row of data) and
# return the final-fit parameters plus the per-iteration time-to-transition
# arrays needed by the timer plot.
fit_country <- function(data, verschiebung, extrapol = 2200, confidence_level = 0.999) {
  funs    <- make_model_funs(verschiebung)
  reg     <- funs$reg
  reg_ice <- funs$reg_ice
  alpha   <- 1 - confidence_level
  z       <- qnorm(1 - alpha / 2)
  control <- list(maxit = 100000, reltol = 10^-30)

  n <- length(data$`Electric/zero-emission`)
  bev_time <- ice_time <- numeric(n)

  RSS <- function(v, type = "BEV") {
    forecast  <- reg(v, BEV$x, type)
    residuals <- BEV$y - forecast
    sum((residuals * BEV$overall)^2)
  }
  RSS_ice <- function(v, type = "ICE") {
    forecast  <- reg_ice(v, ICE$x, type)
    residuals <- ICE$y - forecast
    sum((residuals * ICE$overall)^2)
  }

  res <- res_ice <- B <- austria <- new_A <- BEV <- ICE <- Hybrid <- NULL

  max_in_band <- function(df, col, lo, hi) {
    vals <- df$x[df[[col]] <= hi & df[[col]] >= lo]
    if (!length(vals)) return(NA_real_)
    max(vals)
  }

  span_in_band <- function(df, col, lo, hi) {
    vals <- df$x[df[[col]] <= hi & df[[col]] >= lo]
    if (!length(vals)) return(NA_real_)
    max(vals) - min(vals)
  }

  yearly_subset <- subset(data, !is.na(data$time_interval) & data$time_interval == "yearly")
  lastyearly <- if (nrow(yearly_subset) > 0) ceiling(max(yearly_subset$year)) else -Inf

  for (i in seq_len(n)) {
    looped <- data[1:i, ]

    xg <- looped$year
    yg <- as.double(looped$bev_share)
    BEV <- data.frame(x = xg, y = yg, overall = looped$overall)
    res <- optim(par = c(-0.1, 4), fn = RSS, control = control)

    xg <- seq(verschiebung, extrapol, by = 1/12)
    yg <- reg(v = res$par, xg)
    B  <- data.frame(x = xg, BEV = yg)

    se        <- sd(BEV$y) / sqrt(length(BEV$y))
    shape_lo  <- res$par[2] - z * se
    shape_up  <- res$par[2] + z * se
    scale_lo  <- res$par[1] - z * se * res$par[1]
    scale_up  <- res$par[1] + z * se * res$par[1]

    B$BEV_lower <- reg(v = c(scale_lo, shape_lo), xg)
    B$BEV_upper <- reg(v = c(scale_up, shape_up), xg)

    xg <- looped$year
    yg <- as.double(looped$ice_share)
    ICE <- data.frame(x = xg, y = yg, overall = looped$overall)
    res_ice <- optim(par = c(-0.1, 4), fn = RSS_ice, control = control)

    xg <- seq(verschiebung, extrapol, by = 1/12)
    B$ICE <- reg_ice(v = res_ice$par, xg, type = "ICE")
    se          <- sd(ICE$y) / sqrt(length(ICE$y))
    weibull_lo  <- res_ice$par[2] - z * se
    weibull_up  <- res_ice$par[2] + z * se
    B$ICE_upper <- reg_ice(v = c(res_ice$par[1], weibull_lo), xg)
    B$ICE_lower <- reg_ice(v = c(res_ice$par[1], weibull_up), xg)

    B$Hybrid       <- 1 - B$BEV       - B$ICE
    B$Hybrid_upper <- 1 - B$BEV_lower - B$ICE_lower
    B$Hybrid_lower <- 1 - B$BEV_upper - B$ICE_upper

    Hybrid <- BEV
    Hybrid$y <- 1 - BEV$y - ICE$y

    austria <- data.frame(B, "Type" = "New Registrations")
    new_A   <- data.frame(BEV, Type = "New Registrations", Quarter = BEV$x)
    new_A$Quarter <- ifelse(new_A$x %% 1 < 0.999, "Q4", new_A$Quarter)
    new_A$Quarter <- ifelse(new_A$x %% 1 < 0.668, "Q3", new_A$Quarter)
    new_A$Quarter <- ifelse(new_A$x %% 1 < 0.418, "Q2", new_A$Quarter)
    new_A$Quarter <- ifelse(new_A$x %% 1 < 0.168, "Q1", new_A$Quarter)
    new_A$Quarter <- ifelse(new_A$x <= lastyearly, "Yearly", new_A$Quarter)
    new_A$overall       <- looped$overall
    new_A$time_interval <- looped$time_interval

    austria$Hybrid       <- pmax(austria$Hybrid, 0)
    austria$Hybrid_upper <- pmax(austria$Hybrid_upper, 0)
    austria$Hybrid_lower <- pmax(austria$Hybrid_lower, 0)

    time_20_to_80 <- span_in_band(austria, "BEV", 0.2, 0.8)
    time_80_to_20 <- span_in_band(austria, "ICE", 0.2, 0.8)

    bev_time[i] <- time_20_to_80
    ice_time[i] <- time_80_to_20
  }

  # Final-iteration thresholds
  time_80 <- max_in_band(austria, "BEV", 0.2, 0.8)
  time_50 <- max_in_band(austria, "BEV", 0.2, 0.5)
  time_20 <- max_in_band(austria, "BEV", 0.1, 0.2)
  time_20_to_80 <- span_in_band(austria, "BEV", 0.2, 0.8)
  time_80_to_20 <- span_in_band(austria, "ICE", 0.2, 0.8)

  list(
    res            = res,
    res_ice        = res_ice,
    fit            = austria,
    new_points     = new_A,
    bev_obs        = BEV,
    ice_obs        = ICE,
    hybrid_obs     = Hybrid,
    bev_time       = bev_time,
    ice_time       = ice_time,
    time_20        = time_20,
    time_50        = time_50,
    time_80        = time_80,
    time_20_to_80  = time_20_to_80,
    time_80_to_20  = time_80_to_20,
    verschiebung   = verschiebung,
    extrapol       = extrapol,
    lastyearly     = lastyearly
  )
}
