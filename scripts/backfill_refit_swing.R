#!/usr/bin/env Rscript
# One-off migration: add the `refit_swing` column to an existing params.csv.
#
# The column is normally written by upsert_params() when a country is rendered,
# so every row would otherwise carry it only after its next render. This script
# recomputes the fit for each row straight from data/ and fills the column in
# place, so the gallery's tag gate has a value for every market from day one.
#
#   Rscript scripts/backfill_refit_swing.R [params.csv]
#
# Rows whose data file is missing from the repo get "Inf" (not classifiable):
# without the series there is no way to tell whether their fit is settled.
# Re-render those countries once their CSV is in place to get a real value.

source("R/data.R"); source("R/fit.R"); source("R/upsert.R")

path <- commandArgs(trailingOnly = TRUE)[1]
if (is.na(path)) path <- "params.csv"

lines  <- readLines(path, encoding = "UTF-8", warn = FALSE)
had_col <- grepl("refit_swing", lines[1], fixed = TRUE)
header <- if (had_col) lines[1] else paste0(lines[1], ",refit_swing")
cols <- strsplit(header, ",", fixed = TRUE)[[1]]
n_new <- length(cols)
n_old <- if (had_col) n_new else n_new - 1L
SOURCE_COL <- 8L   # the one free-text column

# Split a CSV line honouring double quotes (params.csv now quotes free text).
split_csv <- function(line) {
  out <- character(0); cur <- ""; inq <- FALSE
  ch <- strsplit(line, "", fixed = TRUE)[[1]]
  i <- 1
  while (i <= length(ch)) {
    c1 <- ch[i]
    if (c1 == '"') {
      if (inq && i < length(ch) && ch[i + 1] == '"') { cur <- paste0(cur, '"'); i <- i + 1 }
      else inq <- !inq
    } else if (c1 == "," && !inq) { out <- c(out, cur); cur <- "" }
    else cur <- paste0(cur, c1)
    i <- i + 1
  }
  c(out, cur)
}

variant_path <- function(country, variant) {
  p <- if (variant == "Whole") file.path("data", paste0(country, ".csv"))
       else file.path("data", paste0(country, "_", variant, ".csv"))
  if (!file.exists(p)) {
    legacy <- file.path("data", paste0(country, ".csv"))
    if (file.exists(legacy)) return(legacy)
  }
  p
}

out <- character(length(lines)); out[1] <- header
n_ok <- n_skip <- 0L
for (li in seq_along(lines)[-1]) {
  line <- lines[li]
  if (!nzchar(trimws(line))) { out[li] <- line; next }
  f <- split_csv(line)
  country <- f[1]; variant <- f[2]
  # Repair rows written before source was quoted: an unquoted comma inside the
  # source string split it across several fields and shifted everything after
  # it (Nepal's ttm_bev_share ended up reading "2019"). Any overflow past the
  # expected column count belongs to source, so glue it back together first --
  # otherwise the migration would inherit the shift and overwrite a real value.
  if (length(f) > n_old) {
    extra <- length(f) - n_old
    f <- c(f[seq_len(SOURCE_COL - 1)],
           paste(f[SOURCE_COL:(SOURCE_COL + extra)], collapse = ","),
           f[(SOURCE_COL + extra + 1):length(f)])
    cat(sprintf("  [repair] %s/%s: re-joined %d stray source field(s)\n", country, variant, extra))
  }
  if (length(f) < n_old) f <- c(f, rep("", n_old - length(f)))
  f <- f[seq_len(n_old)]
  if (!had_col) f <- c(f, "")

  swing <- Inf
  p <- variant_path(country, variant)
  if (file.exists(p)) {
    df_all <- try(load_country_csv(p), silent = TRUE)
    if (!inherits(df_all, "try-error")) {
      df <- df_all[df_all$variant == variant, ]
      if (nrow(df) > 0) {
        df <- df[order(df$year), ]
        fit <- try(fit_history(df), silent = TRUE)
        if (!inherits(fit, "try-error")) swing <- fit$refit_swing
      }
    }
  }
  f[n_new] <- if (is.finite(swing)) sprintf("%.2f", swing) else "Inf"
  if (is.finite(swing)) n_ok <- n_ok + 1L else n_skip <- n_skip + 1L

  # Re-quote free text (source); the rest are numbers/dates.
  f[SOURCE_COL] <- csv_field(f[SOURCE_COL])
  out[li] <- paste(f, collapse = ",")
  cat(sprintf("%-22s %-14s swing=%s\n", country, variant,
              if (is.finite(swing)) sprintf("%.1f yrs", swing) else "Inf"))
  flush.console()
}
writeLines(out, path, useBytes = TRUE)
cat(sprintf("\n%s: %d rows with a computed swing, %d not classifiable\n", path, n_ok, n_skip))
