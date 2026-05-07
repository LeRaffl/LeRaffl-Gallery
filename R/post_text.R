# Build the social-media post text for a country.
# Format ported byte-for-byte from the historical Germany R script:
#
#   <flag> <Country> - <Month YY> - BEV Trajectory
#   <X%> BEV
#   <X%> PHEV (of which <Y%>p were EREV)        # parens only if EREV > 0
#   <X%> ICE (of which <Y%>p were HEV)          # parens only if HEV present
#                                                # blank line
#   Trailing 12 months are:
#   <X%> BEV
#   <X%> PHEV (of which <Y%>p were EREV)
#   <X%> ICE (of which <Y%>p were HEV)
#                                                # blank line
#   Graphs are available in the Gallery: https://leraffl.github.io/LeRaffl-Gallery/
#
# Edge cases:
#   - If a country has only one "Hybrid" total (no PHEV/HEV split), the
#     second line says "Hybrid" instead of "PHEV" and gets no parens.
#     In our schema this means: PHEV column absent/zero, HEV column present.
#   - If EREV column is absent or zero, no "(of which ...)" parens.
#   - If HEV column is absent or zero, no "(of which ...)" parens on ICE.

# Format helpers — match scales::percent(accuracy = 0.1) used in the original
# (which produces "12.3%" — yes, the inner-parens form ends up "12.3%p", that
# is the historical look).
.pt_pct <- function(x) {
  if (is.null(x) || is.na(x) || !is.finite(x)) return("0.0%")
  sprintf("%.1f%%", x * 100)
}

.pt_share <- function(num, denom) {
  if (is.null(num) || is.na(num) || is.null(denom) || is.na(denom) || denom == 0) return(NA_real_)
  num / denom
}

.pt_pp_if <- function(label, value, extra_label = NULL, extra_value = NA_real_) {
  if (!is.na(extra_value) && is.finite(extra_value) && extra_value > 0) {
    # "%p" reads as percentage points; intentional notation so readers can
    # tell at a glance these add up (HEV is a subset of ICE, EREV of PHEV).
    sprintf("%s %s (of which %sp were %s)", .pt_pct(value), label, .pt_pct(extra_value), extra_label)
  } else {
    sprintf("%s %s", .pt_pct(value), label)
  }
}

# Country → emoji flag. Falls back to a globe if unknown.
.pt_flag <- function(country) {
  m <- list(
    Albania = "\U0001F1E6\U0001F1F1", Australia = "\U0001F1E6\U0001F1FA", Austria = "\U0001F1E6\U0001F1F9",
    Belgium = "\U0001F1E7\U0001F1EA", Brazil = "\U0001F1E7\U0001F1F7", Bulgaria = "\U0001F1E7\U0001F1EC",
    Canada = "\U0001F1E8\U0001F1E6", Chile = "\U0001F1E8\U0001F1F1", China = "\U0001F1E8\U0001F1F3",
    Croatia = "\U0001F1ED\U0001F1F7", Cyprus = "\U0001F1E8\U0001F1FE", Czechia = "\U0001F1E8\U0001F1FF",
    Denmark = "\U0001F1E9\U0001F1F0", Estonia = "\U0001F1EA\U0001F1EA", Finland = "\U0001F1EB\U0001F1EE",
    France = "\U0001F1EB\U0001F1F7", Georgia = "\U0001F1EC\U0001F1EA", Germany = "\U0001F1E9\U0001F1EA",
    Greece = "\U0001F1EC\U0001F1F7", Hungary = "\U0001F1ED\U0001F1FA", Iceland = "\U0001F1EE\U0001F1F8",
    India = "\U0001F1EE\U0001F1F3", Indonesia = "\U0001F1EE\U0001F1E9", Ireland = "\U0001F1EE\U0001F1EA",
    Italy = "\U0001F1EE\U0001F1F9", Japan = "\U0001F1EF\U0001F1F5", Latvia = "\U0001F1F1\U0001F1FB",
    Lithuania = "\U0001F1F1\U0001F1F9", Luxembourg = "\U0001F1F1\U0001F1FA", Malaysia = "\U0001F1F2\U0001F1FE",
    Malta = "\U0001F1F2\U0001F1F9", Mexico = "\U0001F1F2\U0001F1FD", Netherlands = "\U0001F1F3\U0001F1F1",
    `New Zealand` = "\U0001F1F3\U0001F1FF", Norway = "\U0001F1F3\U0001F1F4", Poland = "\U0001F1F5\U0001F1F1",
    Portugal = "\U0001F1F5\U0001F1F9", Romania = "\U0001F1F7\U0001F1F4", Singapore = "\U0001F1F8\U0001F1EC",
    Slovakia = "\U0001F1F8\U0001F1F0", Slovenia = "\U0001F1F8\U0001F1EE", `South Korea` = "\U0001F1F0\U0001F1F7",
    Spain = "\U0001F1EA\U0001F1F8", Sweden = "\U0001F1F8\U0001F1EA", Switzerland = "\U0001F1E8\U0001F1ED",
    Thailand = "\U0001F1F9\U0001F1ED", Türkiye = "\U0001F1F9\U0001F1F7", UK = "\U0001F1EC\U0001F1E7",
    Uruguay = "\U0001F1FA\U0001F1FE", USA = "\U0001F1FA\U0001F1F8"
  )
  base <- sub("\\s*\\(.*\\)\\s*", "", country)
  flag <- m[[base]]
  if (is.null(flag)) "\U0001F310" else flag
}

.pt_month_label <- function(period) {
  # period like "2026-03" → "March 26"
  d <- as.Date(paste0(period, "-01"))
  if (is.na(d)) return(period)
  old <- Sys.getlocale("LC_TIME")
  on.exit(Sys.setlocale("LC_TIME", old), add = TRUE)
  Sys.setlocale("LC_TIME", "C")
  paste(format(d, "%B"), format(d, "%y"))
}

# Build the share triplet (BEV / second / ICE) for either monthly row or TTM
# rolling 12 sums. `vals` is a named numeric vector with keys BEV, PHEV, EREV,
# HEV, TOTAL. Missing keys → NA.
.pt_triplet_lines <- function(vals) {
  total <- vals[["TOTAL"]]
  bev   <- .pt_share(vals[["BEV"]],  total)
  phev  <- .pt_share(vals[["PHEV"]], total)
  erev  <- .pt_share(vals[["EREV"]], total)
  hev   <- .pt_share(vals[["HEV"]],  total)

  # Second-line: prefer PHEV if reported (column exists and value > 0).
  # If PHEV is missing/zero AND HEV is present, treat HEV as the country's
  # single "Hybrid" total and label accordingly (no parens).
  use_phev   <- !is.na(phev) && is.finite(phev) && phev > 0
  use_hybrid <- !use_phev && !is.na(hev) && is.finite(hev) && hev > 0

  bev_line <- sprintf("%s BEV", .pt_pct(if (is.na(bev)) 0 else bev))

  if (use_phev) {
    second_line <- .pt_pp_if("PHEV", phev, "EREV", erev)
    # ICE = remainder after BEV + PHEV; HEV (if present) goes in parens.
    ice <- max(0, 1 - (if (is.na(bev)) 0 else bev) - phev)
    ice_line <- .pt_pp_if("ICE", ice, "HEV", hev)
  } else if (use_hybrid) {
    second_line <- sprintf("%s Hybrid", .pt_pct(hev))
    ice <- max(0, 1 - (if (is.na(bev)) 0 else bev) - hev)
    ice_line <- sprintf("%s ICE", .pt_pct(ice))
  } else {
    second_line <- sprintf("%s PHEV", .pt_pct(0))
    ice <- max(0, 1 - (if (is.na(bev)) 0 else bev))
    ice_line <- .pt_pp_if("ICE", ice, "HEV", hev)
  }
  c(bev_line, second_line, ice_line)
}

# Public entry. Returns the post text as a single string with \n separators.
build_post_text <- function(df, country_label, last_period) {
  monthly <- df[df$time_interval == "monthly", , drop = FALSE]
  if (nrow(monthly) == 0) {
    # Some countries are quarterly/yearly only — fall back to last available row.
    monthly <- df[order(df$year), , drop = FALSE]
  } else {
    monthly <- monthly[order(monthly$year), , drop = FALSE]
  }
  if (nrow(monthly) == 0) return("")
  last <- monthly[nrow(monthly), , drop = FALSE]

  pick <- function(name) {
    if (name %in% names(last)) suppressWarnings(as.numeric(last[[name]][1])) else NA_real_
  }
  monthly_vals <- c(BEV = pick("BEV"), PHEV = pick("PHEV"), EREV = pick("EREV"),
                    HEV = pick("HEV"), TOTAL = pick("TOTAL"))
  monthly_lines <- .pt_triplet_lines(monthly_vals)

  # TTM: rolling 12-month sums on the most recent 12 monthly rows.
  ttm_lines <- NULL
  if (nrow(monthly) >= 12) {
    last12 <- monthly[(nrow(monthly) - 11):nrow(monthly), , drop = FALSE]
    sum_col <- function(name) {
      if (!(name %in% names(last12))) return(NA_real_)
      v <- suppressWarnings(as.numeric(last12[[name]]))
      v[is.na(v)] <- 0
      sum(v)
    }
    ttm_vals <- c(BEV = sum_col("BEV"), PHEV = sum_col("PHEV"), EREV = sum_col("EREV"),
                  HEV = sum_col("HEV"), TOTAL = sum_col("TOTAL"))
    if (is.finite(ttm_vals[["TOTAL"]]) && ttm_vals[["TOTAL"]] > 0) {
      ttm_lines <- .pt_triplet_lines(ttm_vals)
    }
  }

  flag <- .pt_flag(country_label)
  header <- sprintf("%s %s - %s - BEV Trajectory", flag, country_label, .pt_month_label(last_period))

  parts <- c(header, monthly_lines, "")
  if (!is.null(ttm_lines)) {
    parts <- c(parts, "Trailing 12 months are:", ttm_lines, "")
  }
  parts <- c(parts, "Graphs are available in the Gallery: https://leraffl.github.io/LeRaffl-Gallery/")
  paste(parts, collapse = "\n")
}
