#!/usr/bin/env Rscript
# (Re)build series_meta.csv for every series in params.csv, offline.
# Run:  Rscript scripts/build_series_meta.R
# render_country.R keeps the file current one series at a time afterwards; this
# only seeds / repairs it. Metadata rules live in R/series_meta.R.
source("R/data.R"); source("R/upsert.R"); source("R/series_meta.R")
pp <- read.csv("params.csv", stringsAsFactors = FALSE)
out <- "series_meta.csv"
if (file.exists(out)) file.remove(out)
n <- 0L
for (i in seq_len(nrow(pp))) {
  country <- pp$country[i]; variant <- pp$variant[i]
  f <- if (variant == "Whole") file.path("data", paste0(country, ".csv")) else file.path("data", paste0(country, "_", variant, ".csv"))
  if (!file.exists(f)) f <- file.path("data", paste0(country, ".csv"))
  if (!file.exists(f)) { cat("skip (no data file):", country, variant, "\n"); next }
  df_all <- load_country_csv(f)
  df <- df_all[df_all$variant == variant, , drop = FALSE]
  if (nrow(df) == 0) { cat("skip (no rows):", country, variant, "\n"); next }
  upsert_series_meta(out, country, variant, pp$data_per[i], derive_series_meta(df, variant))
  n <- n + 1L
}
cat("wrote", n, "series to", out, "\n")
