#!/usr/bin/env Rscript
# Backfill bands/<slug>.json for every series in params.csv.
#
# bands/ is normally written by R/render_country.R, so a series would only get
# its file at its next render (weeks for some). This script computes the bands
# straight from data/ with the same code path as a render: same data selection,
# fit_history(), compute_bands(), write_bands_json(). It writes ONLY bands/ —
# no PNGs, no params.csv / weights.csv / posts changes.
#
#   Rscript scripts/backfill_bands.R [country ...]
#
# With no arguments every params.csv row is processed; otherwise only rows of
# the named countries. Run by .github/workflows/backfill-bands.yml (manual).
#
# The frontend only uses a band whose fit matches the params.csv row it draws
# (fit_params.v2), so a series whose params.csv row is older than its data
# (it was not re-rendered after a data change) gets a file here but no band on
# the page until it is rendered again. See docs/architecture/44-uncertainty-bands.md.

source("R/data.R"); source("R/fit.R"); source("R/upsert.R"); source("R/bands.R")

only <- commandArgs(trailingOnly = TRUE)
p <- read.csv("params.csv", stringsAsFactors = FALSE, check.names = FALSE)
if (length(only)) p <- p[p$country %in% only, ]

n_ok <- n_none <- n_err <- 0L
for (i in seq_len(nrow(p))) {
  country <- p$country[i]; variant <- p$variant[i]
  # Same data selection as render_country.R (per-variant file, legacy fallback).
  csv_path <- if (variant == "Whole") file.path("data", paste0(country, ".csv"))
              else file.path("data", paste0(country, "_", variant, ".csv"))
  legacy <- file.path("data", paste0(country, ".csv"))
  if (!file.exists(csv_path) && file.exists(legacy)) csv_path <- legacy
  slug <- slug_country(country, variant)
  path <- file.path("bands", paste0(slug, ".json"))
  res <- tryCatch({
    if (!file.exists(csv_path)) stop("missing data file ", csv_path)
    df_all <- load_country_csv(csv_path)
    df <- df_all[df_all$variant == variant, ]
    if (nrow(df) == 0) stop("no rows for variant")
    fit <- suppressWarnings(fit_history(df))
    b <- compute_bands(df, fit)
    if (is.null(b)) {
      if (file.exists(path)) file.remove(path)
      "none"
    } else {
      write_bands_json(path, b, country, variant, data_per_from_df(df))
      "ok"
    }
  }, error = function(e) paste("error:", conditionMessage(e)))
  if (identical(res, "ok")) n_ok <- n_ok + 1L
  else if (identical(res, "none")) n_none <- n_none + 1L
  else n_err <- n_err + 1L
  cat(sprintf("[bands] %-14s %-14s %-28s %s\n", country, variant, slug, res))
  flush(stdout())
}
cat(sprintf("[bands] done: %d written, %d without an S-shape (no file), %d failed\n", n_ok, n_none, n_err))
