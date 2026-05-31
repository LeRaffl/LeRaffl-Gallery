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

# Per-variant CSV layout: non-Whole variants live in data/<Country>_<Variant>.csv;
# Whole (the default) stays in data/<Country>.csv. The legacy fall-through
# (any variant in the single data/<Country>.csv keyed by the variant column)
# is preserved so countries that haven't been migrated yet still work.
variant_filename <- function(country, variant) {
  if (variant == "Whole") return(file.path("data", paste0(country, ".csv")))
  file.path("data", paste0(country, "_", variant, ".csv"))
}
csv_path <- variant_filename(country, variant)
legacy_path <- file.path("data", paste0(country, ".csv"))
if (!file.exists(csv_path) && file.exists(legacy_path)) {
  cat(sprintf("[render] %s not found; falling back to %s with variant filter\n",
              csv_path, legacy_path))
  csv_path <- legacy_path
}
if (!file.exists(csv_path)) stop("missing data file: ", csv_path)

df_all <- load_country_csv(csv_path)
df <- df_all[df_all$variant == variant, ]
if (nrow(df) == 0) stop("no rows for variant '", variant, "' in ", csv_path)

source_str <- df$source[!is.na(df$source) & nzchar(df$source)][1]
if (is.na(source_str)) source_str <- ""

# Period folder + post date use the "as of" period (data_per): for quarterly
# data the CSV stores each quarter's MIDDLE month (so the regression dots sit in
# the middle of the quarter and the fit behaves), but the outward-facing period
# is the quarter's END month (Q4 → December), which is what params.csv/data_per
# and the Thresholds/Durations tables already show. Keeping the image folder on
# the middle month was the lone inconsistency. last_period (the raw CSV period)
# is kept only for logging.
last_period <- df$period[order(df$year)][nrow(df)]
as_of_period <- data_per_from_df(df)
period_folder <- as_of_period
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
# All flags are PNG. To add a flag: place assets/flags/<slug>.png.
flag_path <- file.path("assets", "flags", paste0(slug, ".png"))
flag_img <- if (file.exists(flag_path)) readPNG(flag_path) else NULL

# QR code pointing to the gallery — downloaded once per render run.
# Set SHOW_QR=FALSE to disable globally, or remove the env var to enable.
# Silently skipped if the download fails (no internet, rate limit, etc.).
SHOW_QR <- !identical(Sys.getenv("SHOW_QR"), "FALSE")
qr_img <- if (SHOW_QR) {
  tryCatch({
    qr_url <- paste0(
      "https://api.qrserver.com/v1/create-qr-code/?size=200x200&margin=4&data=",
      utils::URLencode("https://leraffl.github.io/LeRaffl-Gallery/#gallery", reserved = TRUE)
    )
    tmp <- tempfile(fileext = ".png")
    utils::download.file(qr_url, tmp, quiet = TRUE, mode = "wb")
    readPNG(tmp)
  }, error = function(e) { cat("[render] QR code download skipped:", conditionMessage(e), "\n"); NULL })
} else NULL

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

# Optional curated footnote per country/variant, appended as a second caption
# line (ggtext renders the <br>). Driven by footnotes.csv (columns:
# country,variant,footnote) — kept separate from the per-row `notes` CSV column,
# which is internal/not display-safe. Used e.g. to flag Canada's pre-2017
# passenger-cars-only scope on the Whole charts.
footnote <- ""
if (file.exists("footnotes.csv")) {
  fn <- tryCatch(read.csv("footnotes.csv", stringsAsFactors = FALSE), error = function(e) NULL)
  if (!is.null(fn) && all(c("country", "variant", "footnote") %in% names(fn))) {
    hit <- fn[fn$country == country & fn$variant == variant, , drop = FALSE]
    if (nrow(hit) >= 1 && !is.na(hit$footnote[1]) && nzchar(hit$footnote[1])) {
      footnote <- hit$footnote[1]
      entire_caption <- paste0(entire_caption, "<br>", footnote)
      cat(sprintf("[render] footnote: %s\n", footnote))
    }
  }
}

# Non-Whole variants get the variant appended in parens so the chart title
# matches the gallery entry (e.g. "Denmark (Private)", "Netherlands (HDV)").
country_label <- if (variant == "Whole") country else paste0(country, " (", variant, ")")

meta <- list(
  country = country, country_label = country_label,
  flag_img = flag_img,
  qr_img  = qr_img,
  social_caption = social_caption,
  entire_caption = entire_caption
)

cat(sprintf("[render] %s / %s — %d rows, last period %s (as of %s)\n",
            country, variant, nrow(df), last_period, as_of_period))

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

# Optional per-country/variant plot suppression, driven by skip_plots.csv
# (columns: country,variant,skip — semi-colon-separated plot keys).
# Valid keys: trajectory, icebev, time, ttm. Kept separate from footnotes.csv.
skip_plots <- character(0)
if (file.exists("skip_plots.csv")) {
  sp <- tryCatch(read.csv("skip_plots.csv", stringsAsFactors = FALSE), error = function(e) NULL)
  if (!is.null(sp) && all(c("country", "variant", "skip") %in% names(sp))) {
    sp_hit <- sp[sp$country == country & sp$variant == variant, , drop = FALSE]
    if (nrow(sp_hit) >= 1 && !is.na(sp_hit$skip[1]) && nzchar(sp_hit$skip[1])) {
      skip_plots <- strsplit(sp_hit$skip[1], ";")[[1]]
      cat(sprintf("[render] skip_plots: %s\n", paste(skip_plots, collapse = ", ")))
    }
  }
}

cat("[render] building plots ...\n")
p_traj   <- if (!"trajectory" %in% skip_plots) plot_bev_trajectory(fit, meta) else NULL
p_combo  <- if (!"icebev"     %in% skip_plots) plot_ice_bev_phev(fit, df, meta) else NULL
p_timer  <- if (!"time"       %in% skip_plots) plot_timer(fit, meta) else NULL
p_ttm    <- plot_ttm_shares(ttm_long, meta)

out_dir <- file.path("images", period_folder)
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

# Add flag + QR code into the chart HEADER (title/subtitle rows of the gtable)
# so they appear above the panel, at the same height as the title text, right-aligned.
# show_qr: FALSE on ICE-BEV-PHEV (long title) and TTM (tight single-line header).
add_header_overlays <- function(g, meta, show_qr = TRUE) {
  if (is.null(meta$flag_img)) return(g)

  # Locate the rows that contain the title and (optional) subtitle.
  lay <- g$layout
  title_row <- lay$t[lay$name == "title"]
  sub_row   <- lay$t[lay$name == "subtitle"]
  t_top <- min(c(title_row, sub_row))
  t_bot <- max(c(title_row, sub_row))
  # Span the full horizontal extent of those rows.
  l_col <- min(lay$l[lay$name %in% c("title","subtitle")])
  r_col <- max(lay$r[lay$name %in% c("title","subtitle")])

  # Flag: right-aligned, centred vertically in the header rows.
  fg <- rasterGrob(
    as.raster(meta$flag_img), interpolate = TRUE,
    x     = unit(1, "npc") - unit(FLAG_M_IN, "in"),
    y     = unit(0.5, "npc"),
    width = unit(FLAG_W_IN, "in"), height = unit(FLAG_H_IN, "in"),
    just  = c("right", "center")
  )
  g <- gtable::gtable_add_grob(g, fg,
    t = t_top, b = t_bot, l = l_col, r = r_col,
    name = "flag-header", clip = "off"
  )

  # QR code: to the LEFT of the flag, same top alignment.
  if (show_qr && SHOW_QR && !is.null(meta$qr_img)) {
    qg <- rasterGrob(
      as.raster(meta$qr_img), interpolate = TRUE,
      x     = unit(1, "npc") - unit(FLAG_M_IN + FLAG_W_IN + QR_GAP_IN, "in"),
      y     = unit(0.5, "npc"),
      width = unit(QR_S_IN, "in"), height = unit(QR_S_IN, "in"),
      just  = c("right", "center")
    )
    g <- gtable::gtable_add_grob(g, qg,
      t = t_top, b = t_bot, l = l_col, r = r_col,
      name = "qr-header", clip = "off"
    )
  }
  g
}

save_one <- function(plot, fname, w, h, units, dpi = 300, show_qr = TRUE) {
  if (is.null(plot)) { cat("[render] skip ", fname, " (nothing to plot)\n"); return(invisible()) }
  path <- file.path(out_dir, fname)

  if (!is.null(meta$flag_img)) {
    # Convert to gtable, composite header overlays, save via png/grid.draw.
    g <- add_header_overlays(ggplotGrob(plot), meta, show_qr = show_qr)
    w_in <- if (units == "px") w / dpi else w
    h_in <- if (units == "px") h / dpi else h
    png(path, width = w_in, height = h_in, units = "in", res = dpi, bg = "white")
    grid.newpage()
    grid.draw(g)
    dev.off()
  } else {
    ggsave(filename = path, plot = plot, width = w, height = h, units = units, dpi = dpi, bg = "white")
  }
  cat("[render] wrote ", path, "\n")
}

save_one(p_traj,  paste0(slug, "_", date_suffix, ".png"),            3840, 2160, "px",  show_qr = TRUE)
save_one(p_combo, paste0(slug, "_ICE_BEV_", date_suffix, ".png"),    12.80, 7.20, "in", show_qr = FALSE)
save_one(p_timer, paste0(slug, "_time_", date_suffix, ".png"),       12.80, 7.20, "in", show_qr = TRUE)
save_one(p_ttm,   paste0(slug, "_ttm_shares_", date_suffix, ".png"), 12.80, 7.20, "in", show_qr = FALSE)

# params.csv / weights.csv upsert
data_per <- as_of_period
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
post_text <- build_post_text(df, country_label, as_of_period)
if (nzchar(post_text)) {
  dir.create("posts", showWarnings = FALSE)
  writeLines(post_text, file.path("posts", paste0(slug, ".txt")), useBytes = TRUE)
  writeLines(post_text, file.path("posts", paste0(slug, "_", as_of_period, ".txt")), useBytes = TRUE)
  cat(sprintf("[post]   wrote posts/%s.txt + posts/%s_%s.txt\n", slug, slug, as_of_period))
}

cat("[render] done.\n")
