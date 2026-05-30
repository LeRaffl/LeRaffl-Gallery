# Upsert helpers for params.csv and weights.csv. Base R only.

# Last data period from a country/variant frame, formatted YYYY-MM (yearly: YYYY-12).
data_per_from_df <- function(df) {
  df <- df[order(df$year), ]
  last <- df[nrow(df), ]
  ti <- last$time_interval
  if (ti == "monthly")   return(last$period)
  if (ti == "quarterly") {
    y <- last$year; yr <- floor(y) + 1
    q <- round((y %% 1) * 4) + 1
    return(sprintf("%04d-%02d", yr, c(3, 6, 9, 12)[q]))
  }
  if (ti == "yearly") return(sprintf("%04d-12", floor(last$year) + 1))
  last$period
}

# Weight = trailing aggregate of overall (TOTAL).
compute_weight <- function(df) {
  df <- df[order(df$year), ]
  ti <- df$time_interval[nrow(df)]
  if (ti == "monthly") {
    sub <- df[df$time_interval == "monthly", ]
    return(sum(tail(sub$overall, 12), na.rm = TRUE))
  }
  if (ti == "quarterly") {
    sub <- df[df$time_interval == "quarterly", ]
    return(sum(tail(sub$overall, 4), na.rm = TRUE))
  }
  if (ti == "yearly") {
    sub <- df[df$time_interval == "yearly", ]
    return(tail(sub$overall, 1))
  }
  NA_real_
}

format_num <- function(x) {
  if (!is.finite(x)) return("")
  ax <- abs(x)
  s <- if (ax != 0 && ax < 1e-3) {
    format(x, scientific = TRUE, digits = 13, trim = TRUE)
  } else {
    format(x, scientific = FALSE, digits = 15, trim = TRUE)
  }
  # collapse "e+00"/"e-04" → "e-4" (historical style: signed, no leading zero, no '+')
  s <- sub("e([+-])0*([0-9])", "e\\1\\2", s)
  s <- sub("e\\+", "e", s)
  s
}

# Line-level upsert: only the matching country+variant row is touched.
upsert_params <- function(path, country, variant, fit, data_per, source_str) {
  header <- "country,variant,v1,v2,t0,data_per,model_date,source,baseline_date,ice_v1,ice_v2,ice_t0"
  new_line <- paste(
    country, variant,
    format_num(fit$v1), format_num(fit$v2), format_num(fit$t0),
    data_per, format(Sys.Date(), "%Y-%m-%d"), source_str, "",
    format_num(fit$ice_v1), format_num(fit$ice_v2), format_num(fit$ice_t0),
    sep = ","
  )

  if (!file.exists(path)) {
    writeLines(c(header, new_line), path, useBytes = TRUE)
    return(invisible())
  }
  lines <- readLines(path, encoding = "UTF-8", warn = FALSE)
  if (length(lines) == 0 || !startsWith(lines[1], "country,")) {
    lines <- c(header, lines)
  }

  prefix <- paste0(country, ",", variant, ",")
  match_idx <- which(tolower(substr(lines, 1, nchar(prefix))) == tolower(prefix))
  if (length(match_idx) >= 1) {
    lines[match_idx[1]] <- new_line
    if (length(match_idx) > 1) lines <- lines[-match_idx[-1]]
  } else {
    lines <- c(lines, new_line)
  }
  writeLines(lines, path, useBytes = TRUE)
}

# params.csv self-heal for "Indonesia v1=0" corruption.
# Background: the maintainer's legacy local "auto-publish model" scripts read
# params.csv with R defaults, which round tiny v1 values (≤ ~1e-7) to literal
# zero on write-back. For fast-adoption markets the fit produces v1 ≈ -6e-20
# with v2 > 10; once stored as 0 in the CSV, the page's Durations table
# anchors the Weibull ~20 years too far in the future and reports a ~5-year
# 20→80 transition instead of the true ~2 years.
# Strategy: on every render, scan params.csv for rows that match the
# corruption fingerprint (|v1| < 1e-25 AND v2 ≥ v2_threshold) and that have
# a backing data/<Country>.csv. Re-fit those rows in-place. Cheap when no
# corruption is present (one file read + numeric parse).
# Full background: docs/architecture/08-deploy-ops.md § "Indonesia v1=0 corruption".
heal_v1_zero_rows <- function(params_path = "params.csv",
                              weights_path = "weights.csv",
                              v2_threshold = 10) {
  if (!file.exists(params_path)) return(invisible())
  lines <- readLines(params_path, encoding = "UTF-8", warn = FALSE)
  if (length(lines) < 2) return(invisible())
  header <- strsplit(lines[1], ",", fixed = TRUE)[[1]]
  ci <- function(name) match(name, header)
  ci_country <- ci("country"); ci_variant <- ci("variant")
  ci_v1 <- ci("v1"); ci_v2 <- ci("v2")
  if (any(is.na(c(ci_country, ci_variant, ci_v1, ci_v2)))) return(invisible())

  # Collect the corruption-fingerprint rows ONCE, up front, deduped by
  # country/variant. Processing a fixed candidate list (instead of the old
  # "rewrite file, reset i to 1, rescan" loop) is what makes this terminate:
  # a genuinely degenerate fit — e.g. Canada/Whole's v1 ≈ -4e-153, which still
  # satisfies |v1| < 1e-25 after re-fitting — would otherwise re-match its own
  # fingerprint forever and spin the render job until it times out.
  need_max <- max(ci_country, ci_variant, ci_v1, ci_v2)
  candidates <- list(); seen <- character(0)
  for (i in 2:length(lines)) {
    parts <- strsplit(lines[i], ",", fixed = TRUE)[[1]]
    if (length(parts) < need_max) next
    v1 <- suppressWarnings(as.numeric(parts[ci_v1]))
    v2 <- suppressWarnings(as.numeric(parts[ci_v2]))
    if (is.na(v1) || is.na(v2)) next
    if (abs(v1) < 1e-25 && v2 >= v2_threshold) {
      key <- paste(parts[ci_country], parts[ci_variant], sep = "\r")
      if (!(key %in% seen)) {
        seen <- c(seen, key)
        candidates[[length(candidates) + 1L]] <-
          list(country = parts[ci_country], variant = parts[ci_variant], v2 = v2)
      }
    }
  }

  for (cand in candidates) {
    country <- cand$country; variant <- cand$variant
    csv_path <- file.path("data", paste0(country, ".csv"))
    if (!file.exists(csv_path)) {
      cat(sprintf("[heal] %s/%s: v1=0 detected but %s missing — skipping\n",
                  country, variant, csv_path))
      next
    }
    df_all <- load_country_csv(csv_path)
    df <- df_all[df_all$variant == variant, ]
    if (nrow(df) == 0) next
    fit <- fit_history(df)
    # Only rewrite when re-fitting actually RECOVERS a non-tiny v1 (the
    # Indonesia "CSV rounded v1 to literal 0" case). If the re-fit is itself
    # ≈0, the stored value is the genuine (degenerate) fit — the market has no
    # clean monotonic transition, like Japan/Croatia — not corruption. Leave it
    # and move on, so we neither loop nor churn params.csv on every render.
    if (abs(fit$v1) < 1e-25) {
      cat(sprintf("[heal] %s/%s: re-fit v1=%.4e v2=%.4f still ~0 — genuine degenerate fit, not corruption; leaving as-is\n",
                  country, variant, fit$v1, fit$v2))
      next
    }
    cat(sprintf("[heal] %s/%s: v1=0 corruption (v2=%.3f) — re-fitting from %s\n",
                country, variant, cand$v2, csv_path))
    data_per <- data_per_from_df(df)
    source_str <- df$source[!is.na(df$source) & nzchar(df$source)][1]
    if (is.na(source_str)) source_str <- ""
    upsert_params(params_path, country, variant, fit, data_per, source_str)
    weight <- compute_weight(df)
    upsert_weights(weights_path, country, variant, weight, data_per)
    cat(sprintf("[heal] %s/%s: restored v1=%.4e v2=%.4f\n",
                country, variant, fit$v1, fit$v2))
  }
  invisible()
}

upsert_weights <- function(path, country, variant, weight, data_per) {
  header <- "country,variant,weight,data_per,model_date"
  weight_str <- if (is.finite(weight)) format(round(weight), scientific = FALSE, trim = TRUE) else ""
  new_line <- paste(country, variant, weight_str, data_per,
                    format(Sys.Date(), "%Y-%m-%d"), sep = ",")

  if (!file.exists(path)) {
    writeLines(c(header, new_line), path, useBytes = TRUE); return(invisible())
  }
  lines <- readLines(path, encoding = "UTF-8", warn = FALSE)
  if (length(lines) == 0 || !startsWith(lines[1], "country,")) {
    lines <- c(header, lines)
  }
  prefix <- paste0(country, ",", variant, ",")
  match_idx <- which(substr(lines, 1, nchar(prefix)) == prefix)
  if (length(match_idx) >= 1) {
    lines[match_idx[1]] <- new_line
    if (length(match_idx) > 1) lines <- lines[-match_idx[-1]]
  } else {
    lines <- c(lines, new_line)
  }
  writeLines(lines, path, useBytes = TRUE)
}
