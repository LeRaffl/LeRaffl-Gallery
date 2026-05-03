# R/lib/captions.R
# Caption + flag-image helpers. The original per-country scripts pulled
# fonts and flag PNGs from a hard-coded /Users/leraffl/... asset directory;
# here we look in repo-relative paths first and fall back to the asset
# directory when running locally on Raphael's machine.

suppressPackageStartupMessages({
  library(glue)
  library(png)
})

# Where to look for flag PNGs, in priority order.
flag_search_paths <- function() {
  c(
    file.path("data", "flags"),
    file.path("assets", "flags"),
    "/Users/leraffl/Projects/bev_assets/flags"
  )
}

# Resolve a flag PNG for a country slug. Returns NULL if no flag is found
# (plots will then render without a flag overlay).
load_flag_image <- function(country_slug) {
  fname <- paste0(tolower(country_slug), ".png")
  for (dir in flag_search_paths()) {
    candidate <- file.path(dir, fname)
    if (file.exists(candidate)) {
      return(list(img = readPNG(candidate), path = candidate))
    }
  }
  NULL
}

# Build the social-media markup caption. If the FontAwesome / custom-icon
# fonts are not on disk we silently skip the icon glyphs — the chart still
# renders, just without the little icons. This keeps CI runs that don't
# have the font assets working.
build_social_caption <- function(font_brands_path = NULL, font_custom_path = NULL) {
  if (!is.null(font_brands_path) && file.exists(font_brands_path) &&
      requireNamespace("sysfonts", quietly = TRUE)) {
    try(sysfonts::font_add(family = "Font Awesome 6 Brands", regular = font_brands_path), silent = TRUE)
  }
  if (!is.null(font_custom_path) && file.exists(font_custom_path) &&
      requireNamespace("sysfonts", quietly = TRUE)) {
    try(sysfonts::font_add(family = "CustomIcons", regular = font_custom_path), silent = TRUE)
  }
  if (requireNamespace("showtext", quietly = TRUE) &&
      ((!is.null(font_brands_path) && file.exists(font_brands_path)) ||
       (!is.null(font_custom_path) && file.exists(font_custom_path)))) {
    try(showtext::showtext_auto(), silent = TRUE)
  }

  x_icon <- "&#xe61b"; x_username <- "leraffl"
  bluesky_icon <- "&#xe671"; bluesky_username <- "leraffl.bsky.social "
  buy_me_a_coffee_icon <- "&#xe900"

  glue::glue(
    "<span style='font-family:\"CustomIcons\";'>{buy_me_a_coffee_icon};</span>",
    "<span style='font-family:\"Font Awesome 6 Brands\";'>{x_icon};</span> <span style='color: #000000'>{x_username}</span>",
    strrep(" ", 4),
    "<span style='font-family:\"Font Awesome 6 Brands\";'>{bluesky_icon};</span> <span style='color: #000000'>{bluesky_username}</span>"
  )
}

# Combine the social caption with the date and source string for the chart caption.
build_entire_caption <- function(social_caption, source) {
  paste0(social_caption, " | \t ", Sys.Date(), "  | \t    Source: ", source)
}

# Some country names don't map cleanly to a lowercase slug for the flag
# filename. Handle the few known exceptions explicitly.
country_to_flag_slug <- function(country) {
  aliases <- c(
    "Türkiye"       = "tuerkiye",
    "South Korea"   = "southkorea",
    "New Zealand"   = "newzealand",
    "United States" = "usa",
    "USA"           = "usa",
    "United Kingdom"= "uk",
    "UK"            = "uk",
    "Czechia"       = "czechia",
    "Czech Republic"= "czechia"
  )
  if (country %in% names(aliases)) return(unname(aliases[country]))
  tolower(gsub("\\s+", "", country))
}
