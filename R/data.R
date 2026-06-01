# Country CSV loader, share derivations, and TTM (trailing-12-month) shares.

period_to_year <- function(period) {
  parts <- strsplit(period, "-", fixed = TRUE)
  y <- as.integer(sapply(parts, `[`, 1))
  m <- as.integer(sapply(parts, `[`, 2))
  (y - 1) + (m - 1) / 12
}

period_to_date <- function(period) {
  as.Date(paste0(period, "-01"))
}

# Returns a data frame with raw fuel columns plus derived columns:
#   year, overall, bev_share, phev_share, ice_share, hybrid_share
# Plus per-fuel TTM share columns (NA where <12 months of monthly history exist).
load_country_csv <- function(path) {
  df <- read.csv(path, stringsAsFactors = FALSE, check.names = FALSE)
  df$year <- period_to_year(df$period)
  df$overall <- as.numeric(df$TOTAL)

  numcol <- function(name) if (name %in% names(df)) as.numeric(df[[name]]) else rep(NA_real_, nrow(df))

  bev   <- numcol("BEV");   bev[is.na(bev)] <- 0
  phev  <- numcol("PHEV");  phev[is.na(phev)] <- 0
  erev  <- numcol("EREV");  erev[is.na(erev)] <- 0

  # 3-curve rollup: EREV folds into PHEV; ICE = rest (incl. HEV/MHEV/Petrol/Diesel/Other/...)
  df$bev_share    <- bev / df$overall
  df$phev_share   <- (phev + erev) / df$overall            # used by ICE/BEV/PHEV plot blue curve
  df$ice_share    <- (df$overall - bev - phev - erev) / df$overall
  df$hybrid_share <- df$phev_share                          # legacy alias used by plots
  df
}

# Compute TTM (trailing-12-month) share per fuel column. Works on the most
# recent interval present: monthly (rolling 12 rows) or quarterly (rolling 4
# rows = the same 12 months). Yearly-only series return NULL (a yearly point is
# already 12 months). Returns a long data frame: month (YYYY-MM), type
# (factor), value (share 0..1). Stack order matches the historical plot.
compute_ttm_long <- function(df) {
  df <- df[order(df$year), ]
  if (nrow(df) == 0) return(NULL)
  last_ti <- df$time_interval[nrow(df)]
  window <- switch(last_ti, monthly = 12L, quarterly = 4L, NA_integer_)
  if (is.na(window)) return(NULL)        # yearly / unknown: no rolling-12 TTM
  m <- df[df$time_interval == last_ti, ]
  m <- m[order(m$year), ]
  if (nrow(m) < window) return(NULL)
  # Mirror the historical script: drop the first calendar year before rolling,
  # so the displayed TTM series doesn't include partial-window noise at the
  # left edge (monthly: 12 months; quarterly: 4 quarters).
  m <- m[m$year >= min(m$year) + 1, ]
  if (nrow(m) < window) return(NULL)

  fuel_cols <- c("BEV","PHEV","EREV","HEV","MHEV","PETROL","DIESEL","GAS","CNG","LPG","FLEXFUEL","ETHANOL","OTHERS","ICE")
  present <- fuel_cols[fuel_cols %in% names(m)]
  total <- as.numeric(m$TOTAL)

  # Rolling sum over the trailing `window` periods (= trailing 12 months for
  # both monthly window=12 and quarterly window=4). strict=TRUE returns NA
  # unless the whole window is non-NA, so stacked bars hit 100% from period 1.
  rolling <- function(x, strict = FALSE) {
    n <- length(x); out <- rep(NA_real_, n)
    if (n < window) return(out)
    for (i in window:n) {
      w <- x[(i - window + 1):i]
      if (strict) { if (!any(is.na(w))) out[i] <- sum(w) }
      else out[i] <- sum(w, na.rm = TRUE)
    }
    out
  }

  total_ttm <- rolling(total)
  ttm <- list()
  any_present <- rep(TRUE, nrow(m))
  for (col in present) {
    v <- as.numeric(m[[col]])
    if (all(is.na(v))) next
    rs <- rolling(v, strict = TRUE)
    ttm[[col]] <- rs / total_ttm
    any_present <- any_present & !is.na(rs)
  }

  # Recompute OTHERS as the TTM residual (TOTAL minus all other known fuels) so
  # that stacked bars always sum to 100%. This corrects under-filled OTHERS in
  # historical ACAP data where the breakdown was incomplete or quarterly-averaged.
  if ("OTHERS" %in% names(ttm) && length(ttm) > 1) {
    excl <- setdiff(names(ttm), "OTHERS")
    excl_counts <- lapply(excl, function(c) {
      v <- ttm[[c]] * total_ttm
      v[is.na(v)] <- 0
      v
    })
    excl_sum <- Reduce("+", excl_counts)
    ttm[["OTHERS"]] <- pmax(0, total_ttm - excl_sum) / total_ttm
  }

  # Keep only rows where every present column has a complete 12-month window.
  keep <- which(any_present)
  if (length(keep) == 0) return(NULL)
  months <- substr(m$period[keep], 1, 7)
  out <- data.frame(month = months, stringsAsFactors = FALSE)
  for (col in names(ttm)) out[[col]] <- ttm[[col]][keep]

  # Display labels: title-case for ICE-fuel families, keep acronyms as-is.
  display_label <- function(c) {
    if (c %in% c("BEV","PHEV","EREV","HEV","MHEV","CNG","LPG","ICE")) return(c)
    if (c == "OTHERS") return("Other")
    paste0(toupper(substr(c, 1, 1)), tolower(substr(c, 2, nchar(c))))
  }

  # Long format with stack order (top-of-stack last)
  # Stack from bottom to top. ICE sits next to the petrol/diesel cluster — it's
  # what countries report when they don't break ICE down further (China, USA,
  # South Korea, Thailand, Chile).
  stack_order <- c("OTHERS","FLEXFUEL","ETHANOL","LPG","CNG","GAS","PETROL","DIESEL","ICE","MHEV","HEV","EREV","PHEV","BEV")
  long_cols <- stack_order[stack_order %in% names(out)]
  long <- do.call(rbind, lapply(long_cols, function(c) {
    data.frame(month = out$month, type = display_label(c), value = out[[c]],
               stringsAsFactors = FALSE)
  }))
  long$type <- factor(long$type, levels = sapply(long_cols, display_label))
  long <- long[!is.na(long$value), ]
  long$numeric_month <- as.numeric(as.factor(long$month))
  long
}
