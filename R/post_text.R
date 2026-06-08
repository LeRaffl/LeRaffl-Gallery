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
  # period like "2026-03" → "March 26". Defensive: garbage in → garbage out.
  if (is.null(period) || !is.character(period) || !nzchar(period) ||
      !grepl("^\\d{4}-\\d{2}$", period)) return(as.character(period %||% ""))
  d <- as.Date(paste0(period, "-01"))
  if (is.na(d)) return(period)
  old <- Sys.getlocale("LC_TIME")
  on.exit(Sys.setlocale("LC_TIME", old), add = TRUE)
  Sys.setlocale("LC_TIME", "C")
  paste(format(d, "%B"), format(d, "%y"))
}
`%||%` <- function(a, b) if (is.null(a)) b else a

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
  bev0  <- if (is.na(bev) || !is.finite(bev)) 0 else bev
  phev0 <- if (is.na(phev) || !is.finite(phev)) 0 else phev
  erev0 <- if (is.na(erev) || !is.finite(erev)) 0 else erev

  # EREV is a special case of PHEV (a range-extender is a plug-in hybrid), so
  # the reported PHEV is the BROAD figure = narrow PHEV column + EREV column,
  # annotated "(of which X%p were EREV)". This mirrors the (phev + erev) rollup
  # in R/data.R that drives the BEV/PHEV/ICE plot, and keeps EREV OUT of the ICE
  # remainder. Almost everywhere EREV is 0 (only China breaks it out), so
  # phev_broad == phev and nothing changes; for China it moves the EREV share
  # from the ICE band into PHEV where it belongs.
  phev_broad <- phev0 + erev0

  use_phev   <- phev_broad > 0
  use_hybrid <- !use_phev && !is.na(hev) && is.finite(hev) && hev > 0

  bev_line <- sprintf("%s BEV", .pt_pct(bev0))

  if (use_phev) {
    second_line <- .pt_pp_if("PHEV", phev_broad, "EREV", erev)
    # ICE = remainder after BEV + broad PHEV; HEV (if present) goes in parens.
    ice <- max(0, 1 - bev0 - phev_broad)
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
# `last_period` is optional — if NULL/empty, it is derived from the data.
build_post_text <- function(df, country_label, last_period = NULL) {
  monthly <- df[df$time_interval == "monthly", , drop = FALSE]
  if (nrow(monthly) == 0) {
    # Some countries are quarterly/yearly only — fall back to last available row.
    monthly <- df[order(df$year), , drop = FALSE]
  } else {
    monthly <- monthly[order(monthly$year), , drop = FALSE]
  }
  if (nrow(monthly) == 0) return("")
  last <- monthly[nrow(monthly), , drop = FALSE]
  if (is.null(last_period) || !nzchar(last_period)) {
    last_period <- last$period[1]
  }

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

# Companion post for the TTM market-split chart. Different shape from the
# main BEV-trajectory post:
#   <flag> <Country> - TTM Market Split
#                                                # blank line
#   <prior 12m window>  vs  <current 12m window>
#   <±X.Xpp>  <BAND>  (<prior%> → <current%>)    # one per band, padded
#   ...
#                                                # blank line (only if extras)
#   <PHEV/HEV peaked at X% in YYYY-MM (declining for N months).>
#   <If the changes from the last 6 months continued linearly, BEV would overtake X in YYYY-MM.>
#   <If the changes from the last 6 months continued linearly, BEV would become the largest powertrain in YYYY-MM.>
#                                                # blank line
#   Graphs are available in the Gallery: ...
#
# Bands sum to 100%: BEV + PHEV + HEV + ICE (pure ICE, i.e. ICE minus HEV).
# Hybrid-only countries (no PHEV/HEV split) collapse to BEV / Hybrid / ICE.

.pt_short_month <- function(period) {
  if (is.null(period) || !is.character(period) || !nzchar(period) ||
      !grepl("^\\d{4}-\\d{2}$", period)) return(as.character(period %||% ""))
  d <- as.Date(paste0(period, "-01"))
  if (is.na(d)) return(period)
  old <- Sys.getlocale("LC_TIME")
  on.exit(Sys.setlocale("LC_TIME", old), add = TRUE)
  Sys.setlocale("LC_TIME", "C")
  paste0(format(d, "%b"), format(d, "%y"))
}

.pt_add_months <- function(period, n) {
  d <- as.Date(paste0(period, "-01"))
  y <- as.integer(format(d, "%Y"))
  m <- as.integer(format(d, "%m"))
  total <- (y * 12L) + (m - 1L) + as.integer(n)
  ny <- total %/% 12L
  nm <- (total %% 12L) + 1L
  sprintf("%04d-%02d", ny, nm)
}

build_ttm_post_text <- function(df, country_label, as_of_period = NULL) {
  monthly <- df[df$time_interval == "monthly", , drop = FALSE]
  if (nrow(monthly) < 24) return("")
  monthly <- monthly[order(monthly$year), , drop = FALSE]

  num <- function(name) {
    if (!(name %in% names(monthly))) return(rep(0, nrow(monthly)))
    v <- suppressWarnings(as.numeric(monthly[[name]]))
    v[is.na(v)] <- 0
    v
  }
  bev_m  <- num("BEV"); phev_m <- num("PHEV"); hev_m <- num("HEV"); tot_m <- num("TOTAL")
  periods <- monthly$period
  N <- nrow(monthly)

  # Rolling 12-month sums, indexed by the LAST month included. Defined for i>=12.
  roll <- function(v) {
    out <- rep(NA_real_, N)
    cs <- cumsum(v)
    for (i in 12:N) out[i] <- cs[i] - (if (i == 12) 0 else cs[i - 12])
    out
  }
  bev_r <- roll(bev_m); phev_r <- roll(phev_m); hev_r <- roll(hev_m); tot_r <- roll(tot_m)
  safe_div <- function(a, b) ifelse(is.finite(b) & b > 0, a / b, NA_real_)
  bev_s  <- safe_div(bev_r,  tot_r)
  phev_s <- safe_div(phev_r, tot_r)
  hev_s  <- safe_div(hev_r,  tot_r)
  ice_s  <- pmax(0, 1 - bev_s - phev_s - hev_s)

  cur <- N; pri <- N - 12L
  if (!isTRUE(is.finite(bev_s[cur])) || !isTRUE(is.finite(bev_s[pri]))) return("")

  use_phev <- any(phev_m > 0)

  fmt_pct <- function(s) sprintf("%.1f%%", s * 100)
  fmt_pp  <- function(d) {
    s <- if (is.na(d) || d >= 0) "+" else "−"  # Unicode minus
    sprintf("%s%.1fpp", s, abs(d * 100))
  }

  # --- Bands ---
  if (use_phev) {
    bands <- list(
      list(label = "BEV",  cur = bev_s[cur],  pri = bev_s[pri]),
      list(label = "PHEV", cur = phev_s[cur], pri = phev_s[pri]),
      list(label = "HEV",  cur = hev_s[cur],  pri = hev_s[pri]),
      list(label = "ICE",  cur = ice_s[cur],  pri = ice_s[pri])
    )
  } else {
    # Hybrid-only: redefine ICE = 1 - BEV - HEV (no PHEV band).
    hyb_cur_ice <- pmax(0, 1 - bev_s - hev_s)
    bands <- list(
      list(label = "BEV",    cur = bev_s[cur],     pri = bev_s[pri]),
      list(label = "Hybrid", cur = hev_s[cur],     pri = hev_s[pri]),
      list(label = "ICE",    cur = hyb_cur_ice[cur], pri = hyb_cur_ice[pri])
    )
  }

  label_w <- max(nchar(vapply(bands, function(b) b$label, character(1))))
  delta_lines <- vapply(bands, function(b) {
    padded <- sprintf(paste0("%-", label_w + 1L, "s"), b$label)
    sprintf("%s  %s (%s → %s)", fmt_pp(b$cur - b$pri), padded,
            fmt_pct(b$pri), fmt_pct(b$cur))
  }, character(1))

  # --- Peak detection (PHEV/HEV only; ≥6 months since peak, peak within 24M) ---
  peak_lines <- character(0)
  peak_for <- function(series, label) {
    win_start <- max(13L, cur - 23L)
    idx <- win_start:cur
    vals <- series[idx]
    if (!any(is.finite(vals))) return(NULL)
    pk_local <- which.max(vals)
    pk_i <- idx[pk_local]
    months_since <- cur - pk_i
    if (months_since < 6L) return(NULL)
    if (!isTRUE(series[cur] < series[pk_i])) return(NULL)
    sprintf("%s peaked at %s in %s (declining for %d months).",
            label, fmt_pct(series[pk_i]), periods[pk_i], months_since)
  }
  peak_targets <- if (use_phev) {
    list(list(s = phev_s, l = "PHEV"), list(s = hev_s, l = "HEV"))
  } else {
    list(list(s = hev_s, l = "Hybrid"))
  }
  for (p in peak_targets) {
    line <- peak_for(p$s, p$l)
    if (!is.null(line)) peak_lines <- c(peak_lines, line)
  }

  # --- Crossover predictions (6-month linear TTM trend) ---
  cross_lines <- character(0)
  trend <- function(series) {
    if (cur < 6L) return(NULL)
    idx <- (cur - 5L):cur
    x <- 0:5
    y <- series[idx]
    if (any(!is.finite(y))) return(NULL)
    m <- sum((x - mean(x)) * (y - mean(y))) / sum((x - mean(x))^2)
    list(slope = m, level = y[length(y)])
  }
  bev_t <- trend(bev_s)
  if (!is.null(bev_t) && isTRUE(bev_t$slope > 0)) {
    if (use_phev) {
      others <- list(list(l = "PHEV", s = phev_s), list(l = "HEV", s = hev_s),
                     list(l = "ICE",  s = ice_s))
    } else {
      hyb_ice <- pmax(0, 1 - bev_s - hev_s)
      others <- list(list(l = "Hybrid", s = hev_s), list(l = "ICE", s = hyb_ice))
    }
    crossings <- list()
    unreachable <- FALSE  # any band BEV won't catch within 120 months
    for (o in others) {
      ot <- trend(o$s)
      if (is.null(ot)) { unreachable <- TRUE; next }
      if (bev_t$level >= ot$level) next  # already at/above this band
      ds <- bev_t$slope - ot$slope
      if (!isTRUE(ds > 0)) { unreachable <- TRUE; next }
      m_ahead <- ceiling((ot$level - bev_t$level) / ds)
      if (m_ahead > 120L) { unreachable <- TRUE; next }
      crossings[[length(crossings) + 1L]] <- list(label = o$l, months = max(1L, m_ahead))
    }
    if (length(crossings) > 0L) {
      crossings <- crossings[order(vapply(crossings, function(x) x$months, numeric(1)))]
      if (!unreachable) {
        # BEV catches every band → label the last crossover as "becomes largest"
        # and skip near-tie overtakes (same event, different framing).
        n_cross <- length(crossings)
        largest_m <- crossings[[n_cross]]$months
        for (j in seq_along(crossings)) {
          c1 <- crossings[[j]]
          ymd <- .pt_add_months(periods[cur], c1$months)
          if (j == n_cross) {
            cross_lines <- c(cross_lines,
                             sprintf("If the changes from the last 6 months continued linearly, BEV would become the largest powertrain in %s.", ymd))
          } else if (largest_m - c1$months > 2L) {
            cross_lines <- c(cross_lines,
                             sprintf("If the changes from the last 6 months continued linearly, BEV would overtake %s in %s.", c1$label, ymd))
          }
        }
      } else {
        # Some band will outpace BEV → no "becomes largest", only individual overtakes.
        for (c1 in crossings) {
          ymd <- .pt_add_months(periods[cur], c1$months)
          cross_lines <- c(cross_lines,
                           sprintf("If the changes from the last 6 months continued linearly, BEV would overtake %s in %s.", c1$label, ymd))
        }
      }
    }
  }

  # --- Compose ---
  flag <- .pt_flag(country_label)
  header <- sprintf("%s %s - TTM Market Split", flag, country_label)
  window_line <- sprintf("%s–%s  vs  %s–%s",
                         .pt_short_month(periods[pri - 11L]), .pt_short_month(periods[pri]),
                         .pt_short_month(periods[cur - 11L]), .pt_short_month(periods[cur]))

  parts <- c(header, "", window_line, delta_lines)
  extras <- c(peak_lines, cross_lines)
  if (length(extras) > 0L) parts <- c(parts, "", extras)
  parts <- c(parts, "", "Graphs are available in the Gallery: https://leraffl.github.io/LeRaffl-Gallery/")
  paste(parts, collapse = "\n")
}
