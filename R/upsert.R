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
