# Shared market-variant helpers.

DEFAULT_VARIANT <- "New Cars"

variant_key <- function(variant) {
  key <- tolower(trimws(as.character(variant)))
  key[is.na(key)] <- ""
  key <- gsub("[_-]+", " ", key)
  key <- gsub("\\s+", " ", key)
  key
}

is_default_variant <- function(variant) {
  variant_key(variant) %in% c(
    "",
    "new cars",
    "new car",
    "passenger cars",
    "passenger car",
    "default",
    "all",
    "total",
    "overall",
    "whole",
    "total market",
    "market total",
    "entire",
    "entire market",
    "total vehicles",
    "fleet total"
  )
}

normalize_variant <- function(variant) {
  out <- trimws(as.character(variant))
  out[is.na(out)] <- ""
  out[is_default_variant(out)] <- DEFAULT_VARIANT
  out
}

variant_slug_suffix <- function(variant) {
  tolower(gsub("\\s+", "_", normalize_variant(variant)))
}

display_market_label <- function(country, variant) {
  if (is_default_variant(variant)) {
    country
  } else {
    paste0(country, " (", normalize_variant(variant), ")")
  }
}
