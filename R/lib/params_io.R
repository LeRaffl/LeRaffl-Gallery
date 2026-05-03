# R/lib/params_io.R
# Read/upsert/write params.csv and weights.csv with full numeric precision.
#
# The legacy implementation used `options(scipen = 999)` plus
# `write.table(..., quote = TRUE)`, which silently rounded very small fitted
# parameters (e.g. Indonesia's v1 ~ 1e-25) to "0". Here we pre-format the
# numeric columns with formatC(format = "g", digits = 15) so that scientific
# notation kicks in when needed, preserving the actual fitted value.

suppressPackageStartupMessages({
  library(readr)
  library(stringi)
  library(utils)
})

if (!exists("normalize_variant", mode = "function")) {
  for (.variant_file in c(file.path("R", "lib", "variants.R"),
                          file.path("lib", "variants.R"),
                          "variants.R")) {
    if (file.exists(.variant_file)) {
      source(.variant_file)
      break
    }
  }
}

PARAMS_COLUMNS  <- c("country","variant","v1","v2","t0",
                     "data_per","model_date","source","baseline_date",
                     "ice_v1","ice_v2","ice_t0")

WEIGHTS_COLUMNS <- c("country","variant","weight","data_per","model_date")

country_key <- function(x) {
  tolower(gsub("[[:space:]_]+", "", as.character(x)))
}

# Format a number for params.csv. Keeps full mantissa precision and lets R
# pick scientific notation when it's the natural representation. Returns ""
# for NA so the resulting CSV cell is empty.
format_param_number <- function(x) {
  if (is.null(x) || length(x) == 0) return("")
  vapply(x, function(v) {
    if (is.na(v) || !is.finite(v)) return("")
    trimws(formatC(v, format = "g", digits = 15))
  }, character(1))
}

# Read params.csv, robust to BOM / Latin-1 / mojibake / odd separators.
read_params_csv <- function(path) {
  if (!file.exists(path)) {
    df <- as.data.frame(matrix(character(0), nrow = 0, ncol = length(PARAMS_COLUMNS)))
    names(df) <- PARAMS_COLUMNS
    return(df)
  }

  raw <- readBin(path, what = "raw", n = file.info(path)$size)
  txt <- rawToChar(raw)
  Encoding(txt) <- "UTF-8"
  txt <- sub("^﻿", "", txt, perl = TRUE)
  txt <- gsub("\r\n?", "\n", txt)

  # Mojibake fixups for common mis-decoded UTF-8 → cp1252 round trips
  fixes <- c("TÃ¼rkiye"="Türkiye","Ã¼"="ü","Ãœ"="Ü","Ã¶"="ö",
             "Ã–"="Ö","Ã§"="ç","Ã‡"="Ç","ÃŸ"="ß")
  txt <- stri_replace_all_fixed(txt, names(fixes), unname(fixes), vectorize_all = FALSE)

  # Auto-detect separator (some locales export with ';')
  first_line <- strsplit(txt, "\n", fixed = TRUE)[[1]][1]
  unquoted   <- gsub('"[^"]*"', "", first_line, perl = TRUE)
  semi       <- length(gregexpr(";", unquoted, fixed = TRUE)[[1]])
  comma      <- length(gregexpr(",", unquoted, fixed = TRUE)[[1]])
  delim      <- if (semi > comma) ";" else ","

  df <- read_delim(I(txt), delim = delim,
                   locale = locale(encoding = "UTF-8", decimal_mark = "."),
                   show_col_types = FALSE, progress = FALSE)
  df <- as.data.frame(df, check.names = FALSE)

  for (nm in setdiff(PARAMS_COLUMNS, names(df))) df[[nm]] <- NA
  df <- df[, PARAMS_COLUMNS, drop = FALSE]

  # Numeric coerce (handles "," decimals just in case)
  to_num <- function(x) suppressWarnings(as.numeric(gsub(",", ".", as.character(x), fixed = TRUE)))
  for (nm in c("v1","v2","t0","ice_v1","ice_v2","ice_t0")) df[[nm]] <- to_num(df[[nm]])

  # Trim text columns
  for (nm in c("country","variant","data_per","model_date","source","baseline_date")) {
    df[[nm]] <- trimws(as.character(df[[nm]]))
    df[[nm]][df[[nm]] == "NA"] <- ""
  }
  df$variant <- normalize_variant(df$variant)

  df
}

# Upsert one row into the params data frame, matching on (country, variant)
# case-insensitively for country.
upsert_params_row <- function(params, row) {
  params$variant <- normalize_variant(params$variant)
  row$variant <- normalize_variant(row$variant)
  idx <- which(country_key(params$country) == country_key(row$country) &
                 variant_key(params$variant) == variant_key(row$variant))
  if (length(idx) >= 1) {
    params[idx[1], ] <- row
    if (length(idx) > 1) params <- params[-idx[-1], , drop = FALSE]
  } else {
    params <- rbind(params, row)
  }
  params
}

# Write params.csv: numeric columns are pre-formatted as strings to avoid
# the scipen/digits round-off that silently zeroed Indonesia's parameters.
# readr::write_csv handles the quoting (only fields containing commas/
# newlines/quotes get wrapped) so the output matches the format the legacy
# pipeline produced for the existing rows.
write_params_csv <- function(params, path) {
  df <- params
  for (nm in setdiff(PARAMS_COLUMNS, names(df))) df[[nm]] <- NA
  df <- df[, PARAMS_COLUMNS, drop = FALSE]

  text_cols <- c("country","variant","data_per","model_date","source","baseline_date")
  for (nm in text_cols) {
    df[[nm]] <- ifelse(is.na(df[[nm]]), "", as.character(df[[nm]]))
    df[[nm]] <- stri_trans_nfc(df[[nm]])
    df[[nm]] <- gsub("[\\x00-\\x1F\\x7F\\x80-\\x9F]", "", df[[nm]], perl = TRUE)
    df[[nm]] <- trimws(df[[nm]])
  }
  df$variant <- normalize_variant(df$variant)

  num_cols <- c("v1","v2","t0","ice_v1","ice_v2","ice_t0")
  for (nm in num_cols) df[[nm]] <- format_param_number(df[[nm]])

  readr::write_csv(df, path, na = "")
  invisible(df)
}

# weights.csv

read_weights_csv <- function(path) {
  if (!file.exists(path)) {
    df <- as.data.frame(matrix(character(0), nrow = 0, ncol = length(WEIGHTS_COLUMNS)))
    names(df) <- WEIGHTS_COLUMNS
    return(df)
  }
  df <- as.data.frame(read_csv(path, show_col_types = FALSE, progress = FALSE),
                      check.names = FALSE)
  for (nm in setdiff(WEIGHTS_COLUMNS, names(df))) df[[nm]] <- NA
  df <- df[, WEIGHTS_COLUMNS, drop = FALSE]
  df$variant <- normalize_variant(df$variant)
  df
}

upsert_weights_row <- function(weights, country, variant, weight, data_per) {
  variant <- normalize_variant(variant)
  new <- data.frame(
    country    = country,
    variant    = variant,
    weight     = as.numeric(weight),
    data_per   = data_per,
    model_date = format(Sys.Date(), "%Y-%m-%d"),
    stringsAsFactors = FALSE
  )
  weights$variant <- normalize_variant(weights$variant)
  idx <- which(country_key(weights$country) == country_key(country) &
                 variant_key(weights$variant) == variant_key(variant))
  if (length(idx) >= 1) {
    weights[idx[1], ] <- new
    if (length(idx) > 1) weights <- weights[-idx[-1], , drop = FALSE]
  } else {
    weights <- rbind(weights, new)
  }
  weights
}

write_weights_csv <- function(weights, path) {
  weights$variant <- normalize_variant(weights$variant)
  write_csv(weights, path)
  invisible(weights)
}

# Helpers for the data_per / weight values written into the CSVs

compute_weight_from_data <- function(df) {
  ok <- !is.na(df$time_interval) & nzchar(as.character(df$time_interval))
  if (!any(ok)) return(NA_real_)
  d  <- df[ok, , drop = FALSE]
  last <- d[order(d$year), , drop = FALSE]
  last <- last[nrow(last), , drop = FALSE]
  ti   <- last$time_interval[[1]]

  if (ti == "monthly") {
    sub <- d[d$time_interval == "monthly", , drop = FALSE]
    sub <- sub[max(1, nrow(sub) - 11):nrow(sub), , drop = FALSE]
    return(sum(sub$overall, na.rm = TRUE))
  }
  if (ti == "quarterly") {
    sub <- d[d$time_interval == "quarterly", , drop = FALSE]
    sub <- sub[max(1, nrow(sub) - 3):nrow(sub), , drop = FALSE]
    return(sum(sub$overall, na.rm = TRUE))
  }
  if (ti == "yearly") {
    sub <- d[d$time_interval == "yearly", , drop = FALSE]
    return(sub$overall[nrow(sub)])
  }
  NA_real_
}

data_per_from_data <- function(df) {
  # Take the last row that actually has a time_interval set; some sheets
  # leave NA-only trailers (Malta) which would otherwise win the sort.
  ok <- !is.na(df$time_interval) & nzchar(as.character(df$time_interval))
  if (!any(ok)) return(NA_character_)
  d  <- df[ok, , drop = FALSE]
  d  <- d[order(d$year), , drop = FALSE]
  last <- d[nrow(d), , drop = FALSE]
  ti   <- last$time_interval[[1]]

  if (ti == "monthly")   return(sub("M", "-", last$YYYYMMM[[1]]))
  if (ti == "quarterly") {
    y  <- last$year[[1]]
    yr <- floor(y) + 1
    # Use floor() rather than round() to avoid q=5 when (y %% 1) ≈ 0.92
    # (which would land outside the c(3,6,9,12) lookup and produce NA).
    q  <- pmin(4L, pmax(1L, floor((y %% 1) * 4) + 1L))
    return(sprintf("%04d-%02d", yr, c(3, 6, 9, 12)[q]))
  }
  if (ti == "yearly")    return(sprintf("%04d-12", floor(last$year[[1]]) + 1))
  NA_character_
}
