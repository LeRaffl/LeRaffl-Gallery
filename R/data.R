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

# Compute TTM (12-month rolling) share per fuel column, on monthly rows only.
# Returns a long data frame: month (YYYY-MM), type (factor), value (share 0..1).
# Stack order matches historical plot: Other, Petrol, Diesel, HEV, EREV, PHEV, BEV
# (Other-most-bottom, BEV-most-top; same fill as the original viridis stack).
compute_ttm_long <- function(df) {
  m <- df[df$time_interval == "monthly", ]
  m <- m[order(m$year), ]
  if (nrow(m) < 12) return(NULL)
  # Mirror the historical script: drop the first calendar year of monthly data
  # before rolling, so the displayed TTM series doesn't include partial-window
  # noise at the left edge.
  m <- m[m$year >= min(m$year) + 1, ]
  if (nrow(m) < 12) return(NULL)

  fuel_cols <- c("BEV","PHEV","EREV","HEV","MHEV","PETROL","DIESEL","GAS","CNG","LPG","FLEXFUEL","ETHANOL","OTHERS","ICE")
  present <- fuel_cols[fuel_cols %in% names(m)]
  total <- as.numeric(m$TOTAL)

  rolling12 <- function(x) {
    n <- length(x); out <- rep(NA_real_, n)
    for (i in 12:n) out[i] <- sum(x[(i-11):i], na.rm = TRUE)
    out
  }

  total_ttm <- rolling12(total)
  # Per-column rolling sum: only valid when the entire 12-month window is non-NA.
  # This ensures stacked bars hit 100% from the very first plotted period.
  rolling12_strict <- function(x) {
    n <- length(x); out <- rep(NA_real_, n)
    for (i in 12:n) {
      w <- x[(i-11):i]
      if (!any(is.na(w))) out[i] <- sum(w)
    }
    out
  }
  ttm <- list()
  any_present <- rep(TRUE, nrow(m))
  for (col in present) {
    v <- as.numeric(m[[col]])
    if (all(is.na(v))) next
    rs <- rolling12_strict(v)
    ttm[[col]] <- rs / total_ttm
    any_present <- any_present & !is.na(rs)
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
