# Regression + history-loop. Math is byte-identical to the historical Germany R
# script (do not alter). The history loop produces, for every prefix df[1:i, ],
# the time-to-transition expectations bev_time[i] / ice_time[i].
#
# Returns: list with the fitted extrapolation data.frame (`extrap`), the timer
# data.frame, the latest BEV/ICE/Hybrid observation frames, the optim params,
# and the final transition-time scalars.

fit_history <- function(df, extrapol = 2200, confidence_level = 0.999) {
  verschiebung <- floor(min(na.omit(df$year)))
  df <- subset(df, df$year >= verschiebung)
  alpha <- 1 - confidence_level
  z <- qnorm(1 - alpha / 2)

  reg <- function(v, x, type = "BEV") {
    if (type == "ICE") return(1 - (1 - exp(v[1] * (x - (verschiebung - 1))^v[2])))
    if (type == "BEV") return(1 - exp(v[1] * (x - (verschiebung - 1))^v[2]))
    stop("Unknown type")
  }
  reg_ice <- function(v, x, type = "ICE") {
    if (type == "ICE") return(1 - (1 - 1 * exp(v[1] * (x - (verschiebung - 1))^v[2])))
    if (type == "BEV") return((0.98 - exp(v[1] * (x - (verschiebung - 1))^v[2])))
    stop("Unknown type")
  }

  bev_time <- ice_time <- seq(0, 0, length = nrow(df))
  control <- list(maxit = 100000, reltol = 10^-30)

  res <- res_ice <- NULL
  germany_extrap <- new_A <- BEV <- ICE <- Hybrid <- NULL
  time_20_to_80 <- time_80_to_20 <- NA_real_

  for (i in seq_len(nrow(df))) {
    df_loop <- df[1:i, ]
    BEV <- data.frame(x = df_loop$year, y = as.double(df_loop$bev_share))
    RSS <- function(v, type = "BEV") {
      forecast <- reg(v, BEV$x, type); residuals <- BEV$y - forecast
      sum((residuals * df_loop$overall)^2)
    }
    res <- optim(par = c(-0.1, 4), fn = RSS, control = control)
    xg <- seq(verschiebung, extrapol, by = 1/12)
    yg <- reg(v = res$par, xg)
    B <- data.frame(x = xg, BEV = yg)
    se <- sd(BEV$y) / sqrt(length(BEV$y))
    shape_lo <- res$par[2] - z*se; shape_up <- res$par[2] + z*se
    scale_lo <- res$par[1] - z*se*res$par[1]; scale_up <- res$par[1] + z*se*res$par[1]
    B$BEV_lower <- reg(v = c(scale_lo, shape_lo), xg)
    B$BEV_upper <- reg(v = c(scale_up, shape_up), xg)

    ICE <- data.frame(x = df_loop$year, y = as.double(df_loop$ice_share))
    RSS_ice <- function(v, type = "ICE") {
      forecast <- reg_ice(v, ICE$x, type); residuals <- ICE$y - forecast
      sum((residuals * df_loop$overall)^2)
    }
    res_ice <- optim(par = c(-0.1, 4), fn = RSS_ice, control = control)
    B$ICE <- reg_ice(v = res_ice$par, xg, type = "ICE")
    se <- sd(ICE$y) / sqrt(length(ICE$y))
    weibull_lo <- res_ice$par[2] - z*se; weibull_up <- res_ice$par[2] + z*se
    B$ICE_upper <- reg_ice(v = c(res_ice$par[1], weibull_lo), xg)
    B$ICE_lower <- reg_ice(v = c(res_ice$par[1], weibull_up), xg)

    B$Hybrid       <- 1 - B$BEV - B$ICE
    B$Hybrid_upper <- 1 - B$BEV_lower - B$ICE_lower
    B$Hybrid_lower <- 1 - B$BEV_upper - B$ICE_upper

    Hybrid <- BEV; Hybrid$y <- 1 - BEV$y - ICE$y

    germany_extrap <- data.frame(B, "Type" = "New Registrations")
    new_A <- data.frame(BEV, Type = "New Registrations", Quarter = BEV$x)
    new_A$Quarter <- ifelse(new_A$x %% 1 < 0.999, "Q4", new_A$Quarter)
    new_A$Quarter <- ifelse(new_A$x %% 1 < 0.668, "Q3", new_A$Quarter)
    new_A$Quarter <- ifelse(new_A$x %% 1 < 0.418, "Q2", new_A$Quarter)
    new_A$Quarter <- ifelse(new_A$x %% 1 < 0.168, "Q1", new_A$Quarter)
    lastyearly <- ceiling(max(subset(df_loop, df_loop$time_interval == "yearly")$year, default = -Inf))
    if (is.finite(lastyearly)) {
      new_A$Quarter <- ifelse(new_A$x <= lastyearly, "Yearly", new_A$Quarter)
    }
    new_A$overall <- df_loop$overall
    new_A$time_interval <- df_loop$time_interval

    germany_extrap$Hybrid       <- pmax(germany_extrap$Hybrid, 0)
    germany_extrap$Hybrid_upper <- pmax(germany_extrap$Hybrid_upper, 0)
    germany_extrap$Hybrid_lower <- pmax(germany_extrap$Hybrid_lower, 0)

    time_80 <- max(subset(germany_extrap, germany_extrap$BEV <= 0.8 & germany_extrap$BEV >= 0.2)$x)
    time_20_80 <- max(subset(germany_extrap, germany_extrap$BEV <= 0.8 & germany_extrap$BEV >= 0.2)$x) -
                  min(subset(germany_extrap, germany_extrap$BEV <= 0.8 & germany_extrap$BEV >= 0.2)$x)
    time_80_20 <- max(subset(germany_extrap, germany_extrap$ICE <= 0.8 & germany_extrap$ICE >= 0.2)$x) -
                  min(subset(germany_extrap, germany_extrap$ICE <= 0.8 & germany_extrap$ICE >= 0.2)$x)
    bev_time[i] <- time_20_80; ice_time[i] <- time_80_20
    time_20_to_80 <- time_20_80; time_80_to_20 <- time_80_20
  }

  timer_df <- data.frame(year = df$year[seq_along(bev_time)],
                         BEV_time = bev_time, ICE_time = ice_time)
  last_inf_index <- max(c(which(timer_df$BEV_time == -Inf),
                          which(timer_df$ICE_time == -Inf)), na.rm = TRUE)
  if (!is.finite(last_inf_index)) last_inf_index <- 0
  if (nrow(timer_df) > (last_inf_index + 12)) {
    timer_short <- timer_df[(last_inf_index + 1 + 12):nrow(timer_df), ]
  } else {
    timer_short <- timer_df
  }

  ICE <- data.frame(ICE, overall = df$overall)
  BEV <- data.frame(BEV, overall = df$overall)
  Hybrid <- data.frame(Hybrid, overall = df$overall)

  list(extrap = germany_extrap, new_A = new_A, BEV = BEV, ICE = ICE, Hybrid = Hybrid,
       timer = timer_df, timer_short = timer_short,
       v1 = res$par[1], v2 = res$par[2], t0 = verschiebung,
       ice_v1 = res_ice$par[1], ice_v2 = res_ice$par[2], ice_t0 = verschiebung,
       extrapol = extrapol, verschiebung = verschiebung,
       time_20_to_80 = time_20_to_80, time_80_to_20 = time_80_to_20)
}
