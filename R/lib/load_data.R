# R/lib/load_data.R
# Load a country's data from data/markets/<slug>.csv (long format) and
# normalize it to the wide-format frame the rest of the pipeline expects.
#
# Long-format CSV layout (canonical input):
#   period,interval,year,category,registrations,source
#
# Wide-format columns produced (when available in source):
#   YYYYMMM           — period label e.g. "2025M08"
#   year              — fractional year
#   time_interval     — "monthly" / "quarterly" / "yearly"
#   overall           — total registrations
#   bev / phev / erev / hev / hybrids / petrol / diesel / ice / other / total
#   Hybrid            — the "PHEV-like" line used by the trajectory plot
#                       (= HYBRIDS, or PHEV+EREV, or PHEV depending on schema)
#   Fossil            — total − BEV − Hybrid
#   <…>_share         — shares used by the regression
#   *_TTM columns     — trailing 12-month aggregated shares, computed dynamically
#                       from the monthly counts (the legacy XLSX shipped these
#                       precomputed; here they're derived so they stay in sync)
#   Source            — source string from the CSV
#   schema_flags      — list($has_erev, $has_hev, $has_hybrids_combined, …)

suppressPackageStartupMessages({
  library(readr)
  library(dplyr)
  library(tidyr)
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

# Resolve a sheet name (e.g. "Denmark (HDV)") to a CSV path under data/markets/.
# Slug rules mirror captions.R::country_to_flag_slug + the variant suffix.
sheet_name_to_slug <- function(sheet_name) {
  if (grepl("\\(", sheet_name)) {
    country <- trimws(sub("\\s*\\(.*\\)\\s*", "", sheet_name))
    variant <- sub(".*\\(([^)]+)\\).*", "\\1", sheet_name)
  } else {
    country <- sheet_name; variant <- DEFAULT_VARIANT
  }
  variant <- normalize_variant(variant)
  base <- if (exists("country_to_flag_slug")) country_to_flag_slug(country) else
    tolower(gsub("\\s+", "", country))
  if (is_default_variant(variant)) base else paste0(base, "_", variant_slug_suffix(variant))
}

# Public entry. The signature (`xlsx_path`, `sheet_name`) is kept for
# call-site compatibility, but the first argument is now treated as the
# repo's data directory root: it accepts either a path to the legacy XLSX
# (we look in its parent's `markets/` subfolder) or a `data/markets/` dir
# directly.
load_country_data <- function(data_root, sheet_name) {
  markets_dir <- if (file.info(data_root)$isdir %in% TRUE) {
    if (basename(data_root) == "markets") data_root
    else file.path(data_root, "markets")
  } else {
    file.path(dirname(data_root), "markets")
  }

  slug     <- sheet_name_to_slug(sheet_name)
  csv_path <- file.path(markets_dir, paste0(slug, ".csv"))
  if (!file.exists(csv_path))
    stop("CSV not found: ", csv_path,
         " (sheet '", sheet_name, "' → slug '", slug, "')")

  long <- suppressMessages(read_csv(csv_path, show_col_types = FALSE,
                                    progress = FALSE))
  if (nrow(long) == 0) stop("CSV is empty: ", csv_path)
  long <- validate_market_rows(long, csv_path)

  raw <- pivot_to_wide(long)
  flags <- detect_schema_flags(raw)
  raw   <- add_ttm_columns(raw, flags)
  df    <- normalize_columns(raw, flags)

  list(data = df, flags = flags, sheet_name = sheet_name,
       slug = slug, source = pull_source(df), csv_path = csv_path)
}

validate_market_rows <- function(long, csv_path) {
  required <- c("period", "interval", "year", "category", "registrations", "source")
  missing <- setdiff(required, names(long))
  if (length(missing)) {
    stop("CSV missing required column(s) in ", csv_path, ": ",
         paste(missing, collapse = ", "))
  }

  long <- as.data.frame(long, check.names = FALSE)
  long$interval <- tolower(trimws(as.character(long$interval)))
  long$interval[is.na(long$interval)] <- ""

  valid_intervals <- c("monthly", "quarterly", "yearly")
  bad <- !nzchar(long$interval) | !(long$interval %in% valid_intervals)
  if (any(bad)) {
    bad_period <- long$period[which(bad)[1]]
    bad_value <- long$interval[which(bad)[1]]
    if (!nzchar(bad_value)) bad_value <- "(blank)"
    stop("CSV has ", sum(bad), " row(s) with missing/invalid interval in ",
         csv_path, ". First bad period: ", bad_period,
         " with interval ", bad_value,
         ". Expected one of: ", paste(valid_intervals, collapse = ", "))
  }

  long
}

# Long → wide pivot, recreating the column set the legacy XLSX shipped.
# OTHER (canonical CSV name) becomes OTHERS in the wide frame for backward
# compat with the rest of the pipeline.
pivot_to_wide <- function(long) {
  long <- as.data.frame(long, check.names = FALSE)
  long$category <- toupper(as.character(long$category))

  source_str <- {
    s <- long$source[!is.na(long$source) & nzchar(long$source)]
    if (length(s)) as.character(s[1]) else ""
  }

  wide <- long %>%
    pivot_wider(id_cols = c(period, interval, year),
                names_from = category, values_from = registrations,
                values_fn = ~ .x[1]) %>%
    arrange(year)

  wide <- as.data.frame(wide, check.names = FALSE)

  # Canonical wide column names match the legacy XLSX
  if ("OTHER" %in% names(wide)) names(wide)[names(wide) == "OTHER"] <- "OTHERS"

  wide$YYYYMMM       <- as.character(wide$period)
  wide$time_interval <- as.character(wide$interval)
  wide$Source        <- source_str
  wide$period        <- NULL
  wide$interval      <- NULL

  wide
}

# Inspect the wide frame and figure out which fuel split this sheet uses.
detect_schema_flags <- function(raw) {
  nms <- names(raw)
  list(
    has_erev               = "EREV" %in% nms,
    has_hev                = "HEV"  %in% nms,
    has_hybrids_combined   = "HYBRIDS" %in% nms,
    has_ice_column         = "ICE"  %in% nms,
    has_petrol_diesel_split= all(c("PETROL", "DIESEL") %in% nms),
    has_phev               = "PHEV" %in% nms,
    has_other_ttm          = "OTHER"  %in% nms || "OTHERS" %in% nms,
    has_petrol_ttm         = "PETROL" %in% nms,
    has_diesel_ttm         = "DIESEL" %in% nms,
    has_hev_ttm            = "HEV"    %in% nms,
    has_phev_ttm           = "PHEV"   %in% nms,
    has_erev_ttm           = "EREV"   %in% nms,
    has_ice_ttm            = "ICE"    %in% nms,
    has_hybrid_ttm         = "HYBRIDS"%in% nms,
    column_count           = length(nms)
  )
}

# Compute the trailing-12-month share of `category_col` against `total_col`.
# Primary mode: monthly rows, rolling window of 12.
# Fallback: when no monthly rows exist, uses quarterly rows with a window of 4
# (≈ trailing annual share). Non-matching rows always get NA.
#
# require_complete: when TRUE the window must have no NA in the category column
# for the share to be non-NA. Used for EREV so the "partial ramp-up" months
# are NA rather than an under-counted positive value.
rolling_ttm_share <- function(df, category_col, total_col = "TOTAL",
                              require_complete = FALSE) {
  out <- rep(NA_real_, nrow(df))
  if (!category_col %in% names(df) || !total_col %in% names(df)) return(out)

  monthly <- which(!is.na(df$time_interval) & df$time_interval == "monthly")
  if (length(monthly) >= 12) {
    win  <- 12L
    idx  <- monthly
    itype <- "monthly"
  } else {
    quarterly <- which(!is.na(df$time_interval) & df$time_interval == "quarterly")
    if (length(quarterly) < 4) return(out)
    win  <- 4L
    idx  <- quarterly
    itype <- "quarterly"
  }

  ord <- idx[order(df$year[idx])]
  cv  <- as.numeric(df[[category_col]][ord])
  tv  <- as.numeric(df[[total_col]][ord])
  for (i in win:length(ord)) {
    cat_win <- cv[(i - win + 1L):i]
    tot_win <- tv[(i - win + 1L):i]
    if (require_complete && any(is.na(cat_win))) next
    sc <- sum(cat_win, na.rm = TRUE)
    st <- sum(tot_win, na.rm = TRUE)
    out[ord[i]] <- if (is.finite(st) && st > 0) sc / st else NA_real_
  }
  out
}

# Materialize the *_TTM columns the plot/post code reads. Names mirror the
# legacy XLSX (capitalized "TTM" suffix; "Other TTM" with title case "O").
add_ttm_columns <- function(raw, flags) {
  raw$`BEV TTM`    <- rolling_ttm_share(raw, "BEV")
  if (flags$has_phev)               raw$`PHEV TTM`   <- rolling_ttm_share(raw, "PHEV")
  if (flags$has_erev) {
    raw$`EREV TTM`         <- rolling_ttm_share(raw, "EREV", require_complete = TRUE)
    raw$`EREV TTM partial` <- rolling_ttm_share(raw, "EREV", require_complete = FALSE)
  }
  if (flags$has_hev)                raw$`HEV TTM`    <- rolling_ttm_share(raw, "HEV")
  if (flags$has_hybrids_combined)   raw$`Hybrid TTM` <- rolling_ttm_share(raw, "HYBRIDS")
  if (flags$has_ice_column)         raw$`ICE TTM`    <- rolling_ttm_share(raw, "ICE")
  if (flags$has_petrol_diesel_split) {
    raw$`Petrol TTM` <- rolling_ttm_share(raw, "PETROL")
    raw$`Diesel TTM` <- rolling_ttm_share(raw, "DIESEL")
  }
  if ("OTHERS" %in% names(raw))     raw$`Other TTM` <- rolling_ttm_share(raw, "OTHERS")
  raw
}

# Build the canonical lower-snake view + share columns that downstream code
# (model.R, plots.R, posts.R, params_io.R) reads from.
normalize_columns <- function(raw, flags) {
  df <- raw

  df$bev    <- if ("BEV"    %in% names(df)) as.numeric(df$BEV)    else NA_real_
  df$phev   <- if ("PHEV"   %in% names(df)) as.numeric(df$PHEV)   else NA_real_
  df$erev   <- if ("EREV"   %in% names(df)) as.numeric(df$EREV)   else NA_real_
  df$hev    <- if ("HEV"    %in% names(df)) as.numeric(df$HEV)    else NA_real_
  df$hybrids<- if ("HYBRIDS"%in% names(df)) as.numeric(df$HYBRIDS)else NA_real_
  df$petrol <- if ("PETROL" %in% names(df)) as.numeric(df$PETROL) else NA_real_
  df$diesel <- if ("DIESEL" %in% names(df)) as.numeric(df$DIESEL) else NA_real_
  df$ice    <- if ("ICE"    %in% names(df)) as.numeric(df$ICE)    else NA_real_
  df$other  <- if ("OTHERS" %in% names(df)) as.numeric(df$OTHERS) else NA_real_
  df$total  <- if ("TOTAL"  %in% names(df)) as.numeric(df$TOTAL)  else NA_real_

  df$`Electric/zero-emission` <- df$bev
  df$overall                  <- df$total
  df$`Other fuel`             <- df$other

  hybrid <- if (flags$has_hybrids_combined) {
    df$hybrids
  } else if (flags$has_erev && flags$has_phev) {
    coalesce_sum(df$phev, df$erev)
  } else if (flags$has_phev) {
    df$phev
  } else {
    rep(NA_real_, nrow(df))
  }
  df$Hybrid <- hybrid

  df$Fossil <- df$total - coalesce_zero(df$bev) - coalesce_zero(hybrid)

  df$bev_share    <- df$bev / df$total
  df$ice_share    <- df$Fossil / df$total
  df$hybrid_share <- hybrid / df$total
  df$other_share  <- df$other / df$total
  df$pure_ICE     <- df$Fossil / df$total

  df
}

pull_source <- function(df) {
  if ("Source" %in% names(df)) {
    s <- df$Source[!is.na(df$Source) & nzchar(df$Source)]
    if (length(s)) return(as.character(s[1]))
  }
  ""
}

coalesce_sum <- function(a, b) {
  ifelse(is.na(a) & is.na(b), NA_real_,
         ifelse(is.na(a), b,
                ifelse(is.na(b), a, a + b)))
}

coalesce_zero <- function(x) ifelse(is.na(x), 0, x)
