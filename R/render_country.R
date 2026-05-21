#!/usr/bin/env Rscript
# Entry point: Rscript R/render_country.R <Country> [<Variant>]
# Reads data/<Country>.csv (variant column filters which slice to render),
# fits the regression, builds the four canonical plots, writes them to
# images/<period>/. params.csv / weights.csv updates are handled by a
# separate step (TBD).

suppressPackageStartupMessages({
  library(ggplot2); library(scales); library(grid); library(png); library(ggtext)
})

source("R/data.R"); source("R/fit.R"); source("R/plots.R"); source("R/upsert.R"); source("R/post_text.R")

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1) stop("usage: Rscript R/render_country.R <Country> [<Variant>]")
country <- args[[1]]
variant <- if (length(args) >= 2) args[[2]] else "Whole"

csv_path <- file.path("data", paste0(country, ".csv"))
if (!file.exists(csv_path)) stop("missing data file: ", csv_path)

df_all <- load_country_csv(csv_path)
df <- df_all[df_all$variant == variant, ]
if (nrow(df) == 0) stop("no rows for variant '", variant, "' in ", csv_path)

source_str <- df$source[!is.na(df$source) & nzchar(df$source)][1]
if (is.na(source_str)) source_str <- ""

# Period folder and filename suffix mirror the historical R script.
last_period <- df$period[order(df$year)][nrow(df)]
period_folder <- last_period
date_suffix <- format(Sys.Date(), "%Y%m%d")

# Country slug used in image filenames + flag lookup.
#
# Why translit before gsub-to-underscore: a naive `gsub("[^A-Za-z0-9]+", "_")`
# applied to "Türkiye" produces "t_rkiye" because "ü" is non-ASCII and gets
# replaced with the separator — which then makes build_manifest.R's manifest
# pipeline split the slug into country="t" + variant="rkiye" (rendered as
# "T (Rkiye)" in the gallery dropdown). The historical convention, baked into
# build_manifest.R's `country_map = c("tuerkiye" = "Türkiye", …)`, is the
# German-style expansion ü→ue / ö→oe / ä→ae plus a few Turkish letters that
# have unambiguous ASCII equivalents. Apply that translit step first so the
# slug-then-relabel round-trips cleanly.
slug_country <- function(country, variant) {
  translit <- function(s) {
    pairs <- list(
      c("ü","ue"), c("ö","oe"), c("ä","ae"), c("ß","ss"),
      c("Ü","Ue"), c("Ö","Oe"), c("Ä","Ae"),
      c("ı","i"),  c("İ","I"),
      c("ş","s"),  c("Ş","S"),
      c("ğ","g"),  c("Ğ","G"),
      c("ç","c"),  c("Ç","C")
    )
    for (p in pairs) s <- gsub(p[1], p[2], s, fixed = TRUE)
    s
  }
  base <- tolower(gsub("[^A-Za-z0-9]+", "_", translit(country)))
  if (variant == "Whole") return(base)
  paste0(base, "_", tolower(gsub("[^A-Za-z0-9]+", "_", translit(variant))))
}
slug <- slug_country(country, variant)

# Flag (optional — falls back to no flag if missing).
flag_path <- file.path("assets", "flags", paste0(slug, ".png"))
flag_img <- if (file.exists(flag_path)) readPNG(flag_path) else NULL

# Caption: FA-icon caption requires showtext; if fonts missing we still produce
# a readable plain caption so headless CI works.
font_brands <- "assets/fonts/fontawesome/otfs/Font-Awesome-6-Brands-Regular-400.otf"
font_custom <- "assets/fonts/fontawesome/otfs/icomoon.ttf"
have_fonts <- file.exists(font_brands) && file.exists(font_custom)
social_caption <- if (have_fonts) {
  suppressPackageStartupMessages({ library(showtext); library(sysfonts) })
  try(font_add(family = "Font Awesome 6 Brands", regular = font_brands), silent = TRUE)
  try(font_add(family = "CustomIcons", regular = font_custom), silent = TRUE)
  showtext_auto()
  # Match showtext's text-rendering DPI to ggsave's canvas DPI. Without this,
  # showtext renders at 96 dpi on a 300 dpi canvas → text comes out ~32% size.
  showtext_opts(dpi = 300)
  glue::glue(
    "<span style='font-family:\"CustomIcons\";'>&#xe900;</span>",
    "<span style='font-family:\"Font Awesome 6 Brands\";'>&#xe61b;</span> <span style='color:#000000'>leraffl</span>",
    strrep(" ", 4),
    "<span style='font-family:\"Font Awesome 6 Brands\";'>&#xe671;</span> <span style='color:#000000'>leraffl.bsky.social </span>"
  )
} else {
  "leraffl  •  leraffl.bsky.social"
}
entire_caption <- paste0(social_caption, " | \t ", Sys.Date(), "  | \t    Source: ", source_str)

meta <- list(
  country = country, country_label = country,
  flag_img = flag_img,
  social_caption = social_caption,
  entire_caption = entire_caption
)

cat(sprintf("[render] %s / %s — %d rows, last period %s\n", country, variant, nrow(df), last_period))

cat("[render] fitting ...\n")
fit <- fit_history(df)
cat(sprintf("[render] params: v1=%.13e v2=%.13f t0=%d  ice_v1=%.13e ice_v2=%.13f\n",
            fit$v1, fit$v2, fit$t0, fit$ice_v1, fit$ice_v2))

# Compare to params.csv if present (warn on drift, never fail).
params_path <- "params.csv"
if (file.exists(params_path)) {
  pp <- tryCatch(read.csv(params_path, stringsAsFactors = FALSE), error = function(e) NULL)
  if (!is.null(pp)) {
    row <- pp[pp$country == country & pp$variant == variant, , drop = FALSE]
    if (nrow(row) == 1) {
      check <- function(name, got, exp) {
        if (is.na(exp) || !is.finite(exp)) return(invisible())
        delta <- abs(got - exp)
        rel <- delta / max(1e-30, abs(exp))
        cat(sprintf("[check] %-7s got=%.13g  prev=%.13g  rel-Δ=%.2e\n", name, got, exp, rel))
        if (rel > 1e-3) cat(sprintf("[check] WARNING: %s drift > 0.1%%\n", name))
      }
      check("v1", fit$v1, suppressWarnings(as.numeric(row$v1)))
      check("v2", fit$v2, suppressWarnings(as.numeric(row$v2)))
      check("ice_v1", fit$ice_v1, suppressWarnings(as.numeric(row$ice_v1)))
      check("ice_v2", fit$ice_v2, suppressWarnings(as.numeric(row$ice_v2)))
    }
  }
}

ttm_long <- compute_ttm_long(df)

cat("[render] building plots ...\n")
p_traj   <- plot_bev_trajectory(fit, meta)
p_combo  <- plot_ice_bev_phev(fit, df, meta)
p_timer  <- plot_timer(fit, meta)
p_ttm    <- plot_ttm_shares(ttm_long, meta)

out_dir <- file.path("images", period_folder)
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

save_one <- function(plot, fname, w, h, units, dpi = 300) {
  if (is.null(plot)) { cat("[render] skip ", fname, " (nothing to plot)\n"); return(invisible()) }
  path <- file.path(out_dir, fname)
  ggsave(filename = path, plot = plot, width = w, height = h, units = units, dpi = dpi, bg = "white")
  cat("[render] wrote ", path, "\n")
}

save_one(p_traj,  paste0(slug, "_", date_suffix, ".png"),            3840, 2160, "px")
save_one(p_combo, paste0(slug, "_ICE_BEV_", date_suffix, ".png"),    12.80, 7.20, "in")
save_one(p_timer, paste0(slug, "_time_", date_suffix, ".png"),       12.80, 7.20, "in")
save_one(p_ttm,   paste0(slug, "_ttm_shares_", date_suffix, ".png"), 12.80, 7.20, "in")

# params.csv / weights.csv upsert
data_per <- data_per_from_df(df)
cat(sprintf("[upsert] params.csv  %s/%s  data_per=%s\n", country, variant, data_per))
upsert_params("params.csv", country, variant, fit, data_per, source_str)
weight <- compute_weight(df)
cat(sprintf("[upsert] weights.csv %s/%s  weight=%s\n", country, variant, format(weight, big.mark = ",")))
upsert_weights("weights.csv", country, variant, weight, data_per)

# Self-heal any rows whose v1 was rounded to 0 by an external tool — see
# heal_v1_zero_rows() in R/upsert.R for full context. Runs on every render so
# Indonesia-style corruption from the legacy "auto-publish model" script is
# repaired the next time CI touches params.csv, even if a different country
# is being rendered.
heal_v1_zero_rows("params.csv", "weights.csv")

# Build the social-media post text and write to posts/<slug>.txt (latest, what
# the Gallery's Copy-post button + the Apple Shortcut fetch) plus a periodised
# copy posts/<slug>_<period>.txt that stays around as a history record.
post_text <- build_post_text(df, country, last_period)
if (nzchar(post_text)) {
  dir.create("posts", showWarnings = FALSE)
  writeLines(post_text, file.path("posts", paste0(slug, ".txt")), useBytes = TRUE)
  writeLines(post_text, file.path("posts", paste0(slug, "_", last_period, ".txt")), useBytes = TRUE)
  cat(sprintf("[post]   wrote posts/%s.txt + posts/%s_%s.txt\n", slug, slug, last_period))
}

cat("[render] done.\n")
