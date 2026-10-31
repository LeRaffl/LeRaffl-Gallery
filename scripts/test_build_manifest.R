#!/usr/bin/env Rscript
# Regression test for slug -> label in build_manifest.R (no network, no files).
# Run:  Rscript scripts/test_build_manifest.R
# Multi-word countries with a variant used to split at the first underscore
# ("hong_kong_used" -> "Hong (Kong Used)") because substr() was not vectorised.
source("build_manifest.R")
fails <- 0
eq <- function(slug, want) {
  got <- label_from_slug(slug)
  if (!identical(unname(got), want)) { fails <<- fails + 1; cat("FAIL:", slug, "->", got, "(want", want, ")\n") }
}
# multi-word countries, whole and with a variant (the broken case)
eq("hong_kong",            "Hong Kong")
eq("hong_kong_used",       "Hong Kong (Used)")
eq("hong_kong_vans",       "Hong Kong (Vans)")
eq("south_korea",          "South Korea")
eq("south_korea_hdv",      "South Korea (HDV)")
eq("new_zealand_used_imports", "New Zealand (Used Imports)")
eq("south_africa_vans",    "South Africa (Vans)")
eq("czech_republic_hdv",   "Czech Republic (HDV)")
eq("united_kingdom_vans",  "United Kingdom (Vans)")
eq("saudi_arabia",         "Saudi Arabia")
# legacy single-word spellings and plain slugs still work
eq("southkorea_hdv",       "South Korea (HDV)")
eq("norway",               "Norway")
eq("norway_hdv",           "Norway (HDV)")
eq("tuerkiye_vans",        "T\u00fcrkiye (Vans)")
eq("uk",                   "UK")
eq("india_4-wheelers",     "India (4-Wheelers)")
eq("india_2wheelers",      "India (2-Wheelers)")
# a country that merely starts like a multi-word one must not be swallowed
eq("south_sudan",          "South (Sudan)")
eq("hong_kongo",           "Hong (Kongo)")
# the real two-/three-wheeler series keep their class in the label
eq("india_2-wheelers",     "India (2-Wheelers)")
eq("india_3-wheelers",     "India (3-Wheelers)")
eq("india_3wheelers",      "India (3-Wheelers)")
# legacy slug "india-wheelers" is the India Whole render of 2026-03-15 (chart
# title "India", params row "India,Whole"), so it must read as plain "India",
# not as a wheeler class
eq("india-wheelers",       "India")
eq("india",                "India")

if (fails > 0) { cat(fails, "failure(s)\n"); quit(status = 1) }
cat("test_build_manifest: all checks passed\n")
