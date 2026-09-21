# build_backtest.R — "What the model said using data through <month>"
#
#   Rscript -e 'source("R/build_backtest.R"); build_backtest()'
#   Rscript -e 'source("R/build_backtest.R"); build_backtest(from="2024-01")'
#
# WHAT THIS IS, AND WHAT IT IS NOT
# -------------------------------
# `builder_history/` answers "what did we actually estimate on date X". It is
# recovered from git, so it cannot reach before the repository exists
# (2025-09) — and it carries whatever bugs and country coverage we had then.
#
# This answers a different question: "what would THIS model have said at date
# X, given the data available at date X". It re-fits from the CSVs, so it
# reaches back as far as the data does — 2005 for Norway, 2010 for China,
# 2012 for Germany.
#
# The two must never be mixed in one series. They are different quantities.
#
# THE LIMITATION THAT MATTERS
# ---------------------------
# This truncates TODAY's `data/<Country>.csv`, which contains REVISED figures.
# The numbers as originally published are not recoverable (they only exist in
# git from 2025-09 onward, same wall as above). So the model is handed a
# corrected past, which flatters it: a real forecaster would have been working
# with the first-release numbers. Read this as an upper bound on how well the
# model would have done, not as a clean out-of-sample test. Every consumer of
# this output has to say so.
#
# COST
# ----
# A fit takes ~1.8s and does not get cheaper with a smaller `extrapol` (the
# cost is the optimiser, not the projection). Monthly from 2015 is ~9,200 fits;
# across 4 cores that is roughly an hour, ONCE. Each new month afterwards is
# only ~95 fits, about three minutes — cheap enough for the monthly cron.
#
# Output is written per month and skipped if present, so an interrupted run
# resumes where it stopped.

suppressPackageStartupMessages({
  library(parallel)
})

source("R/data.R")
source("R/fit.R")

BACKTEST_DIR <- "backtest"

# A Weibull fit on a handful of points is noise wearing a curve's clothes.
# 24 months is the floor at which the shape parameter stops swinging wildly on
# one extra observation.
MIN_ROWS <- 24

# Months are stepped as YYYY-MM strings throughout; the data's own `period`
# column is the same shape, so truncation is a plain string comparison.
month_seq <- function(from, to) {
  fy <- as.integer(substr(from, 1, 4)); fm <- as.integer(substr(from, 6, 7))
  ty <- as.integer(substr(to,   1, 4)); tm <- as.integer(substr(to,   6, 7))
  out <- character(0)
  y <- fy; m <- fm
  while (y < ty || (y == ty && m <= tm)) {
    out <- c(out, sprintf("%04d-%02d", y, m))
    m <- m + 1L; if (m > 12L) { m <- 1L; y <- y + 1L }
  }
  out
}

# Every (file, variant) pair the repo holds, loaded once and reused for every
# month. Re-reading 167 CSVs per month would cost more than the fits.
load_all_series <- function() {
  files <- list.files("data", pattern = "\\.csv$", full.names = TRUE)
  out <- list()
  for (f in files) {
    df <- tryCatch(load_country_csv(f), error = function(e) NULL)
    if (is.null(df) || !("variant" %in% names(df))) next
    # `data/<Country>.csv` is the Whole series; `data/<Country>_<Variant>.csv`
    # carries its own. The country name is the part before the first underscore
    # only for the latter, so derive it from the file, not the variant.
    base <- sub("\\.csv$", "", basename(f))
    country <- sub("_[^_]+$", "", base)
    if (!grepl("_", base)) country <- base
    for (v in unique(df$variant)) {
      sub_df <- df[df$variant == v, , drop = FALSE]
      if (nrow(sub_df) < MIN_ROWS) next
      key <- paste0(country, "|", v)
      out[[key]] <- list(country = country, variant = v, df = sub_df)
    }
  }
  out
}

# Trailing-twelve-month total as of `upto`, mirroring what weights.csv holds.
# Quarterly series carry a quarter per row, so four rows are also 12 months;
# yearly series are one row. Returns NA when the window cannot be filled,
# because a partial window is a smaller quantity wearing the same name.
ttm_window <- function(df, upto) {
  d <- df[df$period <= upto, , drop = FALSE]
  if (nrow(d) == 0) return(NULL)
  d <- d[order(d$period), , drop = FALSE]
  iv <- tail(d$time_interval, 1)
  need <- if (identical(iv, "yearly")) 1L else if (identical(iv, "quarterly")) 4L else 12L
  if (nrow(d) < need) return(NULL)
  tail(d, need)
}

ttm_weight <- function(df, upto) {
  w <- ttm_window(df, upto)
  if (is.null(w)) return(NA_real_)
  sum(as.numeric(w$overall), na.rm = TRUE)
}

# Trailing-twelve-month BEV share as of `upto`.
#
# This delegates to `compute_ttm_long()` and takes its last BEV value, which
# is exactly what `render_country.R` writes into params.csv. Sharing the
# function is the point: the column is named `ttm_bev_share` in both files and
# a consumer must be able to read them the same way.
#
# An earlier version here wrote `tail(d$bev_share, 1)` -- the most recent
# single period's share -- under that name. Seasonality makes that a
# different number entirely, and all 87 comparable rows disagreed with
# params.csv.
#
# A hand-rolled "sum(BEV)/sum(TOTAL) over the last 12 rows" is also not
# equivalent, which is why this does not do that either: compute_ttm_long()
# restricts the window to rows sharing the series' LAST time_interval (so a
# mixed yearly/monthly history does not blend the two) and sums each fuel
# strictly (any NA in the window yields NA rather than being treated as
# zero). Reimplementing that invites exactly the silent drift this column
# already had once.
#
# OBSERVED trailing-twelve-month shares of the 3-curve rollup: what the
# sources actually reported, for the Time-lapse's data points.
#
# Deliberately NOT compute_ttm_long(). That function keeps a month only when
# EVERY fuel column it found has a complete window, which is right for a
# stacked bar (the bars must sum to 100%) and wrong here: Germany has 61
# monthly rows by 2017-01 and still yields nothing, because some column it
# does not need lacks a full window. Countries would then drop in and out of
# the aggregate frame by frame -- the composition artefact the cohort exists
# to remove, reintroduced in the observed series.
#
# So this uses the rollup `load_country_csv()` already derives and `fit.R`
# actually fits: bev_share, phev_share (EREV folded in) and ice_share (the
# residual, hybrids included). Multiplying each by `overall` recovers the
# counts, so the ratio of sums over the window is the honest TTM -- and the
# points are then compared against a curve fitted to the same quantity.
#
# The shares inherit load_country_csv()'s NA-as-zero treatment of an absent
# fuel column. That is a real choice, but it is the SAME choice the fitted
# curve is built on, so point and curve cannot disagree about it.
obs_shares <- function(df, upto) {
  none <- c(bev = NA_real_, phev = NA_real_, ice = NA_real_)
  w <- ttm_window(df, upto)
  if (is.null(w)) return(none)
  tot <- sum(as.numeric(w$overall), na.rm = TRUE)
  if (!is.finite(tot) || tot <= 0) return(none)
  wsum <- function(col) sum(as.numeric(w[[col]]) * as.numeric(w$overall),
                            na.rm = TRUE) / tot
  c(bev = wsum("bev_share"), phev = wsum("phev_share"), ice = wsum("ice_share"))
}

# `ttm_bev_share` keeps params.csv's definition -- compute_ttm_long()'s last
# BEV value, exactly what render_country.R writes -- so the column means the
# same thing in both files. It is NOT what the Time-lapse plots; that is
# `obs_bev_share` above.
ttm_bev_share <- function(df, upto) {
  d <- df[df$period <= upto, , drop = FALSE]
  if (nrow(d) == 0) return(NA_real_)
  tl <- try(compute_ttm_long(d), silent = TRUE)
  if (inherits(tl, "try-error") || is.null(tl)) return(NA_real_)
  rows <- tl[as.character(tl$type) == "BEV", , drop = FALSE]
  if (nrow(rows) == 0) return(NA_real_)
  rows$value[nrow(rows)]
}

# NA rather than Inf/NaN/NULL in the CSV. Shared by fit_one and the writer.
num <- function(x) if (is.null(x) || length(x) == 0 || !is.finite(x)) NA_real_ else x

fit_one <- function(entry, upto) {
  d <- entry$df[entry$df$period <= upto, , drop = FALSE]
  if (nrow(d) < MIN_ROWS) return(NULL)
  f <- try(suppressWarnings(fit_history(d)), silent = TRUE)
  if (inherits(f, "try-error")) return(NULL)
  list(
    country = entry$country, variant = entry$variant,
    v1 = num(f$v1), v2 = num(f$v2), t0 = num(f$t0),
    ice_v1 = num(f$ice_v1), ice_v2 = num(f$ice_v2), ice_t0 = num(f$ice_t0),
    data_per = max(d$period),
    ttm_bev_share = num(ttm_bev_share(entry$df, upto)),
    obs = obs_shares(entry$df, upto),
    weight = ttm_weight(entry$df, upto),
    n_rows = nrow(d)
  )
}

build_backtest <- function(from = "2015-01", to = NULL, cores = NULL,
                           out_dir = BACKTEST_DIR) {
  series <- load_all_series()
  cat(sprintf("[backtest] %d series with >= %d rows\n", length(series), MIN_ROWS))

  if (is.null(to)) {
    to <- max(unlist(lapply(series, function(s) max(s$df$period))))
  }
  months <- month_seq(from, to)
  if (is.null(cores)) cores <- max(1L, detectCores() - 1L)
  cat(sprintf("[backtest] %s .. %s (%d months), %d cores\n",
              from, to, length(months), cores))

  dir.create(file.path(out_dir, "params"), recursive = TRUE, showWarnings = FALSE)
  dir.create(file.path(out_dir, "weights"), recursive = TRUE, showWarnings = FALSE)

  for (mo in months) {
    pfile <- file.path(out_dir, "params",  sprintf("%s.csv", mo))
    wfile <- file.path(out_dir, "weights", sprintf("%s.csv", mo))
    if (file.exists(pfile) && file.exists(wfile)) next   # resume

    eligible <- Filter(function(s) sum(s$df$period <= mo) >= MIN_ROWS, series)
    if (length(eligible) == 0) next

    t0 <- Sys.time()
    res <- mclapply(eligible, fit_one, upto = mo, mc.cores = cores)
    res <- Filter(Negate(is.null), res)
    if (length(res) == 0) next

    pr <- do.call(rbind, lapply(res, function(r) data.frame(
      country = r$country, variant = r$variant,
      v1 = r$v1, v2 = r$v2, t0 = r$t0,
      data_per = r$data_per, model_date = mo, source = "backtest",
      baseline_date = "",
      ice_v1 = r$ice_v1, ice_v2 = r$ice_v2, ice_t0 = r$ice_t0,
      ttm_bev_share = r$ttm_bev_share,
      obs_bev_share = num(r$obs[["bev"]]),
      obs_phev_share = num(r$obs[["phev"]]),
      obs_ice_share = num(r$obs[["ice"]]),
      refit_swing = NA_real_,
      stringsAsFactors = FALSE)))
    write.csv(pr, pfile, row.names = FALSE, na = "")

    wr <- do.call(rbind, lapply(res, function(r) data.frame(
      country = r$country, variant = r$variant,
      weight = r$weight, data_per = r$data_per, model_date = mo,
      stringsAsFactors = FALSE)))
    wr <- wr[is.finite(wr$weight), , drop = FALSE]
    write.csv(wr, wfile, row.names = FALSE, na = "")

    cat(sprintf("[backtest] %s  %3d fits  %5.1fs\n", mo, length(res),
                as.numeric(difftime(Sys.time(), t0, units = "secs"))))
    flush.console()
  }
  cat("[backtest] done\n")
  invisible(TRUE)
}

if (sys.nframe() == 0 && !interactive()) build_backtest()
