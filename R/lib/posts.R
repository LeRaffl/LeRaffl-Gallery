# R/lib/posts.R
# Generate the social-post text snippet that the user copies into X / Bluesky
# from their iPhone Shortcut. Format matches the user's existing posts (verified
# against Albania / Türkiye / China / South Korea / UK / Germany / NewZealand /
# Portugal / Ireland / Romania screenshots from April 2026).
#
# The text is schema-aware:
#   - Standard:        "X.X% PHEV"  + "X.X% ICE (of which X.X%p were HEV)"
#   - China style:     "X.X% PHEV (of which X.X%p were EREV)"  +  "X.X% ICE"
#   - Türkiye style:   "X.X% Hybrid"  +  "X.X% ICE"

suppressPackageStartupMessages({
  library(scales)
  library(countrycode)
  library(dplyr)
})

if (!exists("display_market_label", mode = "function")) {
  for (.variant_file in c(file.path("R", "lib", "variants.R"),
                          file.path("lib", "variants.R"),
                          "variants.R")) {
    if (file.exists(.variant_file)) {
      source(.variant_file)
      break
    }
  }
}

# Two letters → regional-indicator emoji (e.g. "AT" → 🇦🇹)
iso2_to_flag <- function(iso2) {
  if (is.na(iso2) || nchar(iso2) != 2) return("")
  chars <- strsplit(toupper(iso2), "")[[1]]
  to_ri <- function(ch) intToUtf8(0x1F1E6 + utf8ToInt(ch) - utf8ToInt("A"))
  paste0(vapply(chars, to_ri, FUN.VALUE = character(1)), collapse = "")
}

# Country name → flag emoji. Mirrors the alias table from the legacy scripts.
country_to_flag_emoji <- function(country) {
  alias <- c("Türkiye" = "Turkey", "Czechia" = "Czech Republic", "USA" = "United States")
  canon <- if (country %in% names(alias)) unname(alias[country]) else country
  iso2 <- suppressWarnings(countrycode::countrycode(
    canon, origin = "country.name", destination = "iso2c",
    custom_match = c("Hong Kong" = "HK", "Macau" = "MO")
  ))
  if (is.na(iso2) && nchar(country) == 2) iso2 <- toupper(country)
  iso2_to_flag(iso2)
}

# Last data point → "March 26" style label (English month, 2-digit year).
post_period_label <- function(data) {
  ok <- !is.na(data$time_interval) & nzchar(as.character(data$time_interval))
  if (!any(ok)) return(NA_character_)
  d <- data[ok, , drop = FALSE]
  d <- d[order(d$year), , drop = FALSE]
  last <- d[nrow(d), , drop = FALSE]
  ti <- last$time_interval[[1]]

  last_date <- if (ti == "monthly" && "YYYYMMM" %in% names(last) && !is.na(last$YYYYMMM)) {
    as.Date(paste0(sub("M", "-", last$YYYYMMM), "-01"))
  } else if (ti == "quarterly") {
    y <- last$year[[1]]; yr <- floor(y)
    q <- pmin(4L, pmax(1L, floor((y %% 1) * 4) + 1L))
    mo <- c(2, 5, 8, 11)[q]
    as.Date(sprintf("%04d-%02d-01", yr, mo))
  } else if (ti == "yearly") {
    as.Date(sprintf("%04d-12-01", floor(last$year[[1]])))
  } else {
    return(NA_character_)
  }

  # Force English month name regardless of system locale.
  old <- Sys.getlocale("LC_TIME")
  on.exit(suppressWarnings(Sys.setlocale("LC_TIME", old)), add = TRUE)
  suppressWarnings(Sys.setlocale("LC_TIME", "C"))
  paste(format(last_date, "%B"), format(last_date, "%y"))
}

# Pull the last monthly row's per-category share, falling back to NA when
# the column isn't reported. Mirrors the helpers in legacy Austria.R 936-1004.
last_monthly_shares <- function(data) {
  m <- data[!is.na(data$time_interval) & data$time_interval == "monthly", , drop = FALSE]
  if (nrow(m) == 0) return(NULL)
  last <- m[order(m$year), , drop = FALSE]
  last <- last[nrow(last), , drop = FALSE]
  total <- last$total[[1]]
  share <- function(col) {
    if (col %in% names(last) && !is.na(last[[col]][[1]]) && !is.na(total) && total > 0)
      return(last[[col]][[1]] / total)
    NA_real_
  }
  list(
    bev     = share("bev"),
    phev    = share("phev"),
    erev    = share("erev"),
    hev     = share("hev"),
    hybrids = share("hybrids")
  )
}

# Pull the last monthly row's *_TTM values (already trailing-12-month aggregated
# in the source sheet). Falls back gracefully when columns are missing.
last_ttm_shares <- function(data) {
  m <- data[!is.na(data$time_interval) & data$time_interval == "monthly", , drop = FALSE]
  if (nrow(m) == 0) return(NULL)
  last <- m[order(m$year), , drop = FALSE]
  last <- last[nrow(last), , drop = FALSE]
  pick <- function(col) {
    if (col %in% names(last) && !is.na(last[[col]][[1]])) return(last[[col]][[1]])
    NA_real_
  }
  list(
    bev    = pick("BEV TTM"),
    phev   = pick("PHEV TTM"),
    erev   = pick("EREV TTM"),
    hev    = pick("HEV TTM"),
    hybrid = pick("Hybrid TTM")
  )
}

nz <- function(x) if (is.na(x)) 0 else x

# Render one of the three "stack" lines:
#   - "X.X% BEV"
#   - "X.X% PHEV [(of which X.X%p were EREV)]" / "X.X% Hybrid"
#   - "X.X% ICE [(of which X.X%p were HEV)]"
#
# China style: the PHEV figure is PHEV+EREV combined (matches user's posts),
# with EREV called out as a sub-share. Türkiye style: single Hybrid line and
# no HEV sub on ICE because HEV is already folded into HYBRIDS.
post_block <- function(s, flags) {
  pct <- function(x) scales::percent(x, accuracy = 0.1)
  bev <- s$bev

  if (flags$has_hybrids_combined) {
    second_value <- nz(s$hybrids)
  } else if (flags$has_erev) {
    second_value <- nz(s$phev) + nz(s$erev)
  } else {
    second_value <- nz(s$phev)
  }

  ice_value <- pmax(1 - nz(bev) - second_value, 0)

  lines <- character()
  lines[1] <- sprintf("%s BEV", pct(bev))

  if (flags$has_hybrids_combined) {
    lines[2] <- sprintf("%s Hybrid", pct(second_value))
    lines[3] <- sprintf("%s ICE", pct(ice_value))
  } else if (flags$has_erev && !is.na(s$erev) && s$erev > 0) {
    lines[2] <- sprintf("%s PHEV (of which %sp were EREV)", pct(second_value), pct(s$erev))
    lines[3] <- sprintf("%s ICE", pct(ice_value))
  } else {
    lines[2] <- sprintf("%s PHEV", pct(second_value))
    if (flags$has_hev && !is.na(s$hev)) {
      lines[3] <- sprintf("%s ICE (of which %sp were HEV)", pct(ice_value), pct(s$hev))
    } else {
      lines[3] <- sprintf("%s ICE", pct(ice_value))
    }
  }
  lines
}

# TTM block: same schema rules, reading from the *_TTM columns.
post_block_ttm <- function(t, flags) {
  pct <- function(x) scales::percent(x, accuracy = 0.1)
  bev <- t$bev

  if (flags$has_hybrids_combined) {
    second_value <- nz(t$hybrid)
  } else if (flags$has_erev) {
    second_value <- nz(t$phev) + nz(t$erev)
  } else {
    second_value <- nz(t$phev)
  }

  ice_value <- pmax(1 - nz(bev) - second_value, 0)

  lines <- character()
  lines[1] <- sprintf("%s BEV", pct(bev))

  if (flags$has_hybrids_combined) {
    lines[2] <- sprintf("%s Hybrid", pct(second_value))
    lines[3] <- sprintf("%s ICE", pct(ice_value))
  } else if (flags$has_erev && !is.na(t$erev) && t$erev > 0) {
    lines[2] <- sprintf("%s PHEV (of which %sp were EREV)", pct(second_value), pct(t$erev))
    lines[3] <- sprintf("%s ICE", pct(ice_value))
  } else {
    lines[2] <- sprintf("%s PHEV", pct(second_value))
    if (flags$has_hev && !is.na(t$hev)) {
      lines[3] <- sprintf("%s ICE (of which %sp were HEV)", pct(ice_value), pct(t$hev))
    } else {
      lines[3] <- sprintf("%s ICE", pct(ice_value))
    }
  }
  lines
}

# Assemble the full post text for one country/variant.
default_gallery_url <- function(repo_dir = NULL) {
  env_url <- Sys.getenv("GALLERY_URL", unset = "")
  if (nzchar(env_url)) return(env_url)

  repo_name <- if (!is.null(repo_dir)) {
    basename(normalizePath(repo_dir, mustWork = FALSE))
  } else {
    ""
  }
  if (identical(repo_name, "Gallery-TEST")) {
    return("leraffl.github.io/Gallery-TEST/")
  }
  "leraffl.github.io/LeRaffl-Gallery/"
}

build_post_text <- function(country, variant, data, flags,
                            gallery_url = "leraffl.github.io/LeRaffl-Gallery/") {
  flag <- country_to_flag_emoji(country)
  period_label <- post_period_label(data)

  display_country <- display_market_label(country, variant)
  header <- sprintf("%s %s - %s - BEV Trajectory", flag, display_country, period_label)

  m <- last_monthly_shares(data)
  t <- last_ttm_shares(data)
  if (is.null(m) || is.null(t)) {
    return(paste(header, "(no monthly data — post not generated)", sep = "\n"))
  }

  block_now <- post_block(m, flags)
  block_ttm <- post_block_ttm(t, flags)

  paste(
    header,
    block_now[1], block_now[2], block_now[3],
    "",
    "Trailing 12 months are:",
    block_ttm[1], block_ttm[2], block_ttm[3],
    "",
    paste0("Graphs are available in the Gallery: ", gallery_url),
    sep = "\n"
  )
}
