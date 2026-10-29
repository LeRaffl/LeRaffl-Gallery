# Per-series (and per-period) metadata: what does the BEV column MEAN?
#
# One place decides it, and charts, post text, the TTM legend and the frontend
# (series_meta.csv) all read the result. Before this, the same question was
# answered four times (render_country.R label, has_phev_split flag, post text
# fallback, index.html footnote string match) and they disagreed.
#
# The rule is per ROW, not per source name alone:
#   * A row's BEV column is the combined BEV+PHEV bucket ("EV") when its
#     (source, variant) is registered in EV_COMBINED_SOURCES AND the row carries
#     no PHEV / EREV value of its own. ACEA's commercial-vehicle release is the
#     only registered case (docs/architecture/38-source-acea-cv.md).
#   * Anything else is pure BEV. So the moment a real split source for a series
#     appears (e.g. KBA rows for Germany HDV with a PHEV column), those periods
#     read "BEV" automatically; and Poland, which mixes ACEA quarters (EV) with
#     PZPM months (pure BEV), is labelled per period.
#
# The registry is only needed because "PHEV empty" alone cannot tell
# "BEV+PHEV folded into BEV" (ACEA CV) from "pure BEV, PHEV simply not
# published" (PZPM): both look identical in the CSV.
#
# ICE is deliberately NOT unified (owner decision): hev_in_ice only documents
# what the pipeline already does today -- ICE contains HEV where a PHEV split
# exists (HEV shown as "of which"), and is 1 - BEV - HEV where it does not.

EV_COMBINED_SOURCES <- list(ACEA = c("Vans", "HDV", "Buses"))

.sm_has <- function(x) {
  if (is.character(x)) x <- suppressWarnings(as.numeric(trimws(x)))
  !is.na(x)
}

# Logical per row: TRUE where the BEV column holds BEV+PHEV.
row_ev_combined <- function(df, variant = NULL) {
  n <- nrow(df)
  if (n == 0) return(logical(0))
  src <- if ("source" %in% names(df)) toupper(trimws(as.character(df$source))) else rep("", n)
  src[is.na(src)] <- ""
  var <- if (!is.null(variant)) rep(variant, n) else if ("variant" %in% names(df)) as.character(df$variant) else rep("", n)
  reg <- names(EV_COMBINED_SOURCES)
  registered <- vapply(seq_len(n), function(i) {
    k <- match(src[i], toupper(reg))
    !is.na(k) && var[i] %in% EV_COMBINED_SOURCES[[k]]
  }, logical(1))
  own_split <- (if ("PHEV" %in% names(df)) .sm_has(df$PHEV) else rep(FALSE, n)) |
               (if ("EREV" %in% names(df)) .sm_has(df$EREV) else rep(FALSE, n))
  registered & !own_split & .sm_has(df$BEV)
}

# Series-level summary. `df` is one country/variant frame (ordered or not).
derive_series_meta <- function(df, variant = NULL) {
  df <- df[order(df$year), , drop = FALSE]
  n <- nrow(df)
  comb <- row_ev_combined(df, variant)
  has_bev <- .sm_has(df$BEV)
  # Rows that carry a BEV figure decide the basis; TOTAL-only rows stay neutral.
  kind <- ifelse(comb, "EV", "BEV")
  kind_known <- kind[has_bev]
  latest <- if (length(kind_known)) kind_known[length(kind_known)] else "BEV"
  # Start of the latest run of the same basis; "" when the basis never changed.
  basis_change <- ""
  if (length(kind_known) && length(unique(kind_known)) > 1) {
    per <- as.character(df$period[has_bev])
    r <- rle(kind_known)
    basis_change <- per[sum(r$lengths[-length(r$lengths)]) + 1L]
  }
  has_col <- function(col) col %in% names(df) && any(.sm_has(df[[col]]))
  split_any <- has_col("PHEV") || has_col("EREV")
  # Latest window (the rows posts and the TTM chart actually use).
  last_ti <- if (n) df$time_interval[n] else NA_character_
  win <- df[df$time_interval %in% last_ti, , drop = FALSE]
  win <- tail(win, if (identical(last_ti, "quarterly")) 4L else 12L)
  split_latest <- nrow(win) > 0 &&
    any((if ("PHEV" %in% names(win)) .sm_has(win$PHEV) else FALSE) |
        (if ("EREV" %in% names(win)) .sm_has(win$EREV) else FALSE))
  list(
    bev_label        = latest,                     # label for the latest period
    ev_combined      = identical(latest, "EV"),     # latest BEV column = BEV+PHEV
    ev_combined_any  = any(comb),                   # any period combined (history caveat)
    ev_basis_change  = basis_change,                # first period of latest basis, if it changed
    has_phev_split   = split_any,                   # any PHEV/EREV ever (charts)
    has_phev_split_latest = split_latest,           # PHEV/EREV in the latest window (posts)
    hev_in_ice       = split_any                    # documents current behaviour, see header
  )
}

SERIES_META_HEADER <- "country,variant,data_per,bev_label,ev_combined,ev_combined_any,ev_basis_change,has_phev_split,hev_in_ice"

series_meta_line <- function(country, variant, data_per, sm) {
  b <- function(x) if (isTRUE(x)) "true" else "false"
  paste(country, variant, data_per, sm$bev_label, b(sm$ev_combined), b(sm$ev_combined_any),
        sm$ev_basis_change, b(sm$has_phev_split), b(sm$hev_in_ice), sep = ",")
}

# Line-level upsert of series_meta.csv, same convention as upsert_params().
upsert_series_meta <- function(path, country, variant, data_per, sm) {
  new_line <- series_meta_line(country, variant, data_per, sm)
  lines <- if (file.exists(path)) readLines(path, encoding = "UTF-8", warn = FALSE) else character(0)
  if (length(lines) == 0 || !startsWith(lines[1], "country,")) lines <- c(SERIES_META_HEADER, lines)
  else lines[1] <- SERIES_META_HEADER
  prefix <- paste0(country, ",", variant, ",")
  idx <- which(tolower(substr(lines, 1, nchar(prefix))) == tolower(prefix))
  if (length(idx) >= 1) {
    lines[idx[1]] <- new_line
    if (length(idx) > 1) lines <- lines[-idx[-1]]
  } else lines <- c(lines, new_line)
  writeLines(lines, path, useBytes = TRUE)
}
