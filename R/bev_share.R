# R/bev_share.R
# Entry point for the consolidated BEV trajectory pipeline.
#
# Usage:
#   Rscript R/bev_share.R <sheet-name>
#   Rscript R/bev_share.R "Denmark (HDV)"
#
# What this does for a single sheet/country:
#   1. Read its sheet from data/raw/bev_share_acea.xlsx
#   2. Detect the schema (HEV / EREV / HYBRIDS / single-ICE / etc.)
#   3. Fit the Weibull-style logistic model (math identical to the legacy
#      per-country scripts)
#   4. Render the four standard PNG charts under images/<YYYY-MM>/
#   5. Upsert the fitted parameters into params.csv and weights.csv
#
# Math, plot styling, and CSV column layouts are preserved verbatim so that
# the output can replace the legacy per-country runs without disturbing the
# downstream gallery / thresholds / durations UI.

suppressPackageStartupMessages({
  library(dplyr)
  library(tidyr)
  library(ggplot2)
})

# Repo root: this script lives in <repo>/R/bev_share.R
script_dir <- function() {
  args <- commandArgs(trailingOnly = FALSE)
  file_arg <- grep("^--file=", args, value = TRUE)
  if (length(file_arg) == 1) {
    return(normalizePath(dirname(sub("^--file=", "", file_arg))))
  }
  if (!is.null(sys.frame(1)$ofile)) return(normalizePath(dirname(sys.frame(1)$ofile)))
  normalizePath(".")
}

R_DIR    <- script_dir()
REPO_DIR <- normalizePath(file.path(R_DIR, ".."))

source(file.path(R_DIR, "lib", "variants.R"))
source(file.path(R_DIR, "lib", "load_data.R"))
source(file.path(R_DIR, "lib", "model.R"))
source(file.path(R_DIR, "lib", "plots.R"))
source(file.path(R_DIR, "lib", "params_io.R"))
source(file.path(R_DIR, "lib", "captions.R"))
source(file.path(R_DIR, "lib", "posts.R"))

# Parse arguments. We currently only need the sheet name; everything else
# (variant, country label) is derived from it.
parse_args <- function() {
  args <- commandArgs(trailingOnly = TRUE)
  if (length(args) < 1) {
    stop("Usage: Rscript R/bev_share.R <sheet-name>\n",
         "Example: Rscript R/bev_share.R Austria\n",
         "         Rscript R/bev_share.R \"Denmark (HDV)\"")
  }
  list(sheet = args[1])
}

# Split a sheet name like "Denmark (HDV)" into country + variant.
split_country_variant <- function(sheet_name) {
  if (grepl("\\(", sheet_name)) {
    country <- trimws(sub("\\s*\\(.*\\)\\s*", "", sheet_name))
    variant <- sub(".*\\(([^)]+)\\).*", "\\1", sheet_name)
  } else {
    country <- sheet_name
    variant <- DEFAULT_VARIANT
  }
  list(country = country, variant = normalize_variant(variant))
}

# Choose a filename slug for PNGs: lowercase, no spaces, variant suffix
# joined with '_'. Falls back through the same alias table the flag loader
# uses so e.g. "Türkiye" → "tuerkiye" (matches the legacy filenames).
country_filename_slug <- function(country, variant) {
  base <- country_to_flag_slug(country)
  if (is_default_variant(variant)) base else paste0(base, "_", variant_slug_suffix(variant))
}

# Run the full pipeline for one sheet. Exposed so run_all.R can drive it
# without re-parsing argv per country.
process_sheet <- function(sheet_name, repo_dir = REPO_DIR) {
  cv      <- split_country_variant(sheet_name)
  country <- cv$country
  variant <- cv$variant

  display_label <- display_market_label(country, variant)

  message("Country: ", country, " | variant: ", variant, " | sheet: ", sheet_name)

  markets_dir <- file.path(repo_dir, "data", "markets")
  loaded      <- load_country_data(markets_dir, sheet_name)
  data       <- loaded$data
  flags      <- loaded$flags
  source_str <- loaded$source

  # Trim to baseline year (`verschiebung`) — matches the original recipe.
  verschiebung <- floor(min(na.omit(data$year)))
  data <- subset(data, data$year >= verschiebung)

  # Drop rows whose computed shares are NA / non-finite. Denmark's default market has
  # 3 such rows from missing TOTAL values; NewZealand (HDV) has ~22. With
  # them in place optim refuses to evaluate the starting parameters and
  # blows up early. The legacy per-country scripts never hit this because
  # they were hand-cleaned per country.
  ok_share <- !is.na(data$bev_share) & !is.na(data$ice_share) &
              is.finite(data$bev_share) & is.finite(data$ice_share)
  if (!all(ok_share)) {
    message("Dropping ", sum(!ok_share), " row(s) with NA / non-finite shares")
    data <- data[ok_share, , drop = FALSE]
  }
  if (nrow(data) < 2) stop("Not enough usable rows after NA-share filter")

  fit <- fit_country(data, verschiebung, extrapol = 2200, confidence_level = 0.999)

  flag_load <- load_flag_image(country_to_flag_slug(country))
  flag_img  <- if (!is.null(flag_load)) flag_load$img else NULL

  font_brands <- "/Users/leraffl/Projects/bev_assets/fonts/fontawesome/otfs/Font-Awesome-6-Brands-Regular-400.otf"
  font_custom <- "/Users/leraffl/Projects/bev_assets/fonts/fontawesome/otfs/icomoon.ttf"
  social_caption <- build_social_caption(font_brands, font_custom)
  entire_caption <- build_entire_caption(social_caption, source_str)

  ttm_plot     <- build_ttm_plot(data, flags, display_label, entire_caption)
  bev_plot     <- build_bev_trajectory_plot(fit, display_label, social_caption, entire_caption, flag_img)
  ice_bev_plot <- build_ice_bev_plot(data, fit, display_label, social_caption, entire_caption, flag_img)
  timer_plot   <- build_timer_plot(fit, display_label, social_caption, flag_img)

  period_folder <- data_per_from_data(data)
  out_dir <- file.path(repo_dir, "images", period_folder)
  dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

  slug     <- country_filename_slug(country, variant)
  date_tag <- format(Sys.Date(), "%Y%m%d")

  ggsave(file.path(out_dir, paste0(slug, "_", date_tag, ".png")),
         plot = bev_plot, width = 3840, height = 2160, units = "px", bg = "white")
  ggsave(file.path(out_dir, paste0(slug, "_ICE_BEV_", date_tag, ".png")),
         plot = ice_bev_plot, width = 12.80, height = 7.20, units = "in", dpi = 300, bg = "white")
  ggsave(file.path(out_dir, paste0(slug, "_time_", date_tag, ".png")),
         plot = timer_plot, width = 12.80, height = 7.20, units = "in", dpi = 300, bg = "white")
  ggsave(file.path(out_dir, paste0(slug, "_ttm_shares_", date_tag, ".png")),
         plot = ttm_plot, width = 12.80, height = 7.20, units = "in", dpi = 300, bg = "white")

  params_path  <- file.path(repo_dir, "params.csv")
  weights_path <- file.path(repo_dir, "weights.csv")

  params <- read_params_csv(params_path)
  row <- data.frame(
    country       = country,
    variant       = variant,
    v1            = as.numeric(fit$res$par[1]),
    v2            = as.numeric(fit$res$par[2]),
    t0            = as.numeric(verschiebung),
    data_per      = period_folder,
    model_date    = format(Sys.Date(), "%Y-%m-%d"),
    source        = sub("^Source:\\s*", "", source_str),
    baseline_date = "",
    ice_v1        = as.numeric(fit$res_ice$par[1]),
    ice_v2        = as.numeric(fit$res_ice$par[2]),
    ice_t0        = as.numeric(verschiebung),
    stringsAsFactors = FALSE
  )
  params <- upsert_params_row(params, row)
  write_params_csv(params, params_path)

  weights <- read_weights_csv(weights_path)
  weights <- upsert_weights_row(weights, country, variant,
                                compute_weight_from_data(data),
                                period_folder)
  write_weights_csv(weights, weights_path)

  # Social-post snippet — same text the iPhone Shortcut used to grab from
  # the console. Written to a stable path so a Shortcut can fetch it via
  # raw.githubusercontent.com.
  posts_dir <- file.path(repo_dir, "posts")
  dir.create(posts_dir, recursive = TRUE, showWarnings = FALSE)
  post_text <- build_post_text(country, variant, data, flags,
                               gallery_url = default_gallery_url(repo_dir))
  post_path <- file.path(posts_dir, paste0(slug, "_", date_tag, ".txt"))
  writeLines(post_text, post_path)
  cat("\n", post_text, "\n", sep = "")

  message("\nDone. Outputs:\n  ", out_dir, "/", slug, "_*_", date_tag, ".png")
  message("  params.csv updated for ", country, " / ", variant)
  message("  weights.csv updated for ", country, " / ", variant)
  message("  post written: ", post_path)

  invisible(list(country = country, variant = variant, fit = fit, flags = flags,
                 out_dir = out_dir, slug = slug, date_tag = date_tag,
                 post_path = post_path))
}

main <- function() {
  args <- parse_args()
  process_sheet(args$sheet)
}

# Run main() only when invoked from the command line (Rscript). When this
# file is `source()`d from run_all.R the helpers are exposed without firing
# main automatically.
if (!interactive() && sys.nframe() == 0) main()
