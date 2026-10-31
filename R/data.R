# Country CSV loader, share derivations, and TTM (trailing-12-month) shares.

period_to_year <- function(period) {
  parts <- strsplit(period, "-", fixed = TRUE)
  y <- as.integer(sapply(parts, `[`, 1))
  m <- as.integer(sapply(parts, `[`, 2))
  # Bare-year periods ("2024" without a month — Austria's annual Vans/HDV
  # rows) used to yield year = NA here. fit_history() then silently DROPPED
  # those rows (NA fails its year >= verschiebung subset) while the plots
  # still received them, so the fit-derived point-size vectors were shorter
  # than the plotted data — ggplot aborted every Austria Vans/HDV render
  # with "Aesthetics must be either length 1 or the same as the data".
  # Anchor an annual total mid-year (July) instead: the value summarises the
  # whole year, and July puts the marker at the year's centre of mass.
  m[is.na(m)] <- 7L
  (y - 1) + (m - 1) / 12
}

period_to_date <- function(period) {
  as.Date(paste0(period, "-01"))
}

# Returns a data frame with raw fuel columns plus derived columns:
#   year, overall, bev_share, phev_share, ice_share, hybrid_share
# Plus per-fuel TTM share columns (NA where <12 months of monthly history exist).
load_country_csv <- function(path) {
  df <- read.csv(path, stringsAsFactors = FALSE, check.names = FALSE)
  # Austria's Vans/HDV writer says "annual" where the rest of the repo says
  # "yearly"; normalise here so fit.R/upsert.R yearly handling applies.
  df$time_interval[df$time_interval %in% "annual"] <- "yearly"
  # "monthly_est" = a monthly row whose values are partly estimated from an
  # annual figure (docs/architecture/03-data-objects.md). Everything numeric
  # treats it as monthly (TTM, fit, post texts, upsert); only the charts
  # look at `estimated` and draw those points hollow.
  df$estimated <- df$time_interval %in% "monthly_est"
  df$time_interval[df$estimated] <- "monthly"
  df$year <- period_to_year(df$period)
  df$overall <- as.numeric(df$TOTAL)

  numcol <- function(name) if (name %in% names(df)) as.numeric(df[[name]]) else rep(NA_real_, nrow(df))

  bev   <- numcol("BEV");   bev[is.na(bev)] <- 0
  phev  <- numcol("PHEV");  phev[is.na(phev)] <- 0
  erev  <- numcol("EREV");  erev[is.na(erev)] <- 0

  # 3-curve rollup: EREV folds into PHEV; ICE = rest (incl. HEV/MHEV/Petrol/Diesel/Other/...)
  df$bev_share    <- bev / df$overall
  df$phev_share   <- (phev + erev) / df$overall            # used by ICE/BEV/PHEV plot blue curve
  df$ice_share    <- (df$overall - bev - phev - erev) / df$overall
  df$hybrid_share <- df$phev_share                          # legacy alias used by plots
  df
}

# Compute TTM (trailing-12-month) share per fuel column. Works on the most
# recent interval present: monthly (rolling 12 rows) or quarterly (rolling 4
# rows = the same 12 months). Yearly-only series return NULL (a yearly point is
# already 12 months). Returns a long data frame: month (YYYY-MM), type
# (factor), value (share 0..1). Stack order matches the historical plot.
# Countries whose TTM runs on the calendar month grid (`calendar = TRUE`
# below). Opt-in because switching it on everywhere re-shapes ~26 other
# series (Singapore, China, Greece, ... would gain their coarse history; a few
# with month gaps would lose a stretch) -- that is a separate decision.
TTM_CALENDAR_COUNTRIES <- c("Vietnam")

# Smallest share (0..1) of a hybrid-type band (HEV/MHEV/EREV/PHEV) that is still
# shown anywhere: 0.05%, the least one printed decimal can express ("0.1%").
# Below it the band is absent data / rounding dust, not a market share. Used by
# the TTM legend (compute_ttm_long) and by the post texts (R/post_text.R, which
# is always sourced after this file) -- one definition so they cannot drift.
HYBRID_MIN_SHARE <- 0.0005

compute_ttm_long <- function(df, bev_label = "BEV", calendar = FALSE) {
  df <- df[order(df$year), ]
  if (nrow(df) == 0) return(NULL)
  last_ti <- df$time_interval[nrow(df)]
  window <- switch(last_ti, monthly = 12L, quarterly = 4L, NA_integer_)
  if (is.na(window)) return(NULL)        # yearly / unknown: no rolling-12 TTM
  m <- df[df$time_interval == last_ti, ]
  m <- m[order(m$year), ]
  # Mixed intervals (monthly series with coarse stretches): a coarse row whose
  # period is still a calendar month (YYYY-MM) is a per-month spread of a
  # yearly / quarterly figure -- the Singapore / Vietnam layout, labelled by its
  # coarsest component. It belongs on the monthly axis, so the trailing window
  # takes it too. The axis is then laid on a full month grid: a month with no
  # row becomes an all-NA row, so a window across a gap is NA instead of
  # silently summing 12 rows that span more than 12 months.
  if (calendar && last_ti == "monthly") {
    is_month <- grepl("^[0-9]{4}-[0-9]{2}$", df$period)
    if (any(is_month & df$time_interval != "monthly")) {
      m <- df[is_month, ]
      m <- m[order(m$period), ]
      m <- m[!duplicated(m$period, fromLast = TRUE), ]
    }
    if (nrow(m) > 0 && all(grepl("^[0-9]{4}-[0-9]{2}$", m$period))) {
      grid <- format(seq(as.Date(paste0(m$period[1], "-01")),
                         as.Date(paste0(m$period[nrow(m)], "-01")), by = "month"), "%Y-%m")
      if (length(grid) > nrow(m)) {
        m <- m[match(grid, m$period), ]
        m$period <- grid
        m$year <- period_to_year(grid)
        m$time_interval[is.na(m$time_interval)] <- "gap"
      }
    }
  }
  if (nrow(m) < window) return(NULL)
  # Hide the first calendar year of the series so the displayed TTM doesn't open
  # with partial-window noise at the left edge (monthly: 12 months; quarterly:
  # 4 quarters). This is a DISPLAY cut only: those periods must stay in `m` so
  # the rolling window can still see them (a Jan point needs the prior 11
  # months; a Q1 point needs the prior 3 quarters). Dropping them from `m` here
  # instead would starve the next year's early windows, shifting the whole
  # series one window to the right and mis-placing every year-start tick.
  display_from <- min(m$year) + 1

  fuel_cols <- c("BEV","PHEV","EREV","HEV","MHEV","PETROL","DIESEL","GAS","CNG","LPG","FLEXFUEL","ETHANOL","OTHERS","ICE")
  present <- fuel_cols[fuel_cols %in% names(m)]
  total <- as.numeric(m$TOTAL)

  # Rolling sum over the trailing `window` periods (= trailing 12 months for
  # both monthly window=12 and quarterly window=4). strict=TRUE returns NA
  # unless the whole window is non-NA, so stacked bars hit 100% from period 1.
  rolling <- function(x, strict = FALSE) {
    n <- length(x); out <- rep(NA_real_, n)
    if (n < window) return(out)
    for (i in window:n) {
      w <- x[(i - window + 1):i]
      if (strict) { if (!any(is.na(w))) out[i] <- sum(w) }
      else out[i] <- sum(w, na.rm = TRUE)
    }
    out
  }

  gap_row <- m$time_interval %in% "gap"
  total[gap_row] <- NA
  total_ttm <- rolling(total)
  total_ttm[as.logical(rolling(as.numeric(gap_row)) > 0)] <- NA
  ttm <- list()
  any_present <- rep(TRUE, nrow(m))
  # Late-starting hybrid split: a source that books HEV / MHEV inside ICE
  # before it reports them (Vietnam pre-2024) leaves those columns NA while ICE
  # is filled. Count those months as 0 here and fold the partial-window mass
  # into ICE below (as EREV into PHEV), instead of cutting the whole TTM
  # until the hybrid columns have twelve months of their own.
  late_start <- list()
  if (calendar && "ICE" %in% present) {
    ice_ok <- !is.na(as.numeric(m[["ICE"]]))
    for (col in intersect(c("HEV", "MHEV"), present)) {
      v <- as.numeric(m[[col]])
      f <- which(!is.na(v))
      if (length(f) == 0 || f[1] == 1) next
      lead <- seq_len(nrow(m)) < f[1] & ice_ok
      if (!any(lead)) next
      late_start[[col]] <- list(first = f[1], lead = lead)
    }
  }
  for (col in present) {
    v <- as.numeric(m[[col]])
    if (all(is.na(v))) next
    if (!is.null(late_start[[col]])) v[late_start[[col]]$lead] <- 0
    rs <- rolling(v, strict = TRUE)
    ttm[[col]] <- rs / total_ttm
    any_present <- any_present & !is.na(rs)
  }

  # EREV: don't break it out of PHEV in the TTM until a FULL trailing window of
  # genuine split data exists. Before a source starts reporting the
  # BEV/PHEV/EREV split, EREV sales sit inside PHEV (the CSV carries 0.0
  # placeholders, e.g. China pre-2024-01); a partial trailing window would
  # otherwise render a misleading "growing" EREV band that is really just data
  # coverage ramping in. So fold the partial-window EREV mass back into PHEV and
  # hold the EREV band at 0 until the window post-dates the first reported EREV.
  # (The same coverage caveat applies to other fuel types; only EREV for now.)
  if ("EREV" %in% names(ttm) && "PHEV" %in% names(ttm)) {
    ev_raw <- as.numeric(m[["EREV"]]); ev_raw[is.na(ev_raw)] <- 0
    first_erev <- which(ev_raw > 0)
    if (length(first_erev) > 0) {
      full <- (seq_len(nrow(m)) - window + 1) >= first_erev[1]
      erev_ct <- ttm[["EREV"]] * total_ttm; erev_ct[is.na(erev_ct)] <- 0
      phev_ct <- ttm[["PHEV"]] * total_ttm
      phev_ct[!full] <- phev_ct[!full] + erev_ct[!full]
      ttm[["PHEV"]] <- phev_ct / total_ttm
      ttm[["EREV"]][!full] <- 0
    }
  }

  # Late-start HEV / MHEV (see above): until the window post-dates the first
  # reported month, their partial mass stays in ICE and the band is held at 0.
  for (col in names(late_start)) {
    if (!(col %in% names(ttm) && "ICE" %in% names(ttm))) next
    full <- (seq_len(nrow(m)) - window + 1) >= late_start[[col]]$first
    ct <- ttm[[col]] * total_ttm; ct[is.na(ct)] <- 0
    ice_ct <- ttm[["ICE"]] * total_ttm
    ice_ct[!full] <- ice_ct[!full] + ct[!full]
    ttm[["ICE"]] <- ice_ct / total_ttm
    ttm[[col]][!full] <- 0
  }

  # Recompute OTHERS as the TTM residual (TOTAL minus all other known fuels) so
  # that stacked bars always sum to 100%. This corrects under-filled OTHERS in
  # historical ACAP data where the breakdown was incomplete or quarterly-averaged.
  if ("OTHERS" %in% names(ttm) && length(ttm) > 1) {
    excl <- setdiff(names(ttm), "OTHERS")
    excl_counts <- lapply(excl, function(c) {
      v <- ttm[[c]] * total_ttm
      v[is.na(v)] <- 0
      v
    })
    excl_sum <- Reduce("+", excl_counts)
    ttm[["OTHERS"]] <- pmax(0, total_ttm - excl_sum) / total_ttm
  }

  # Keep only rows where every present column has a complete 12-month window,
  # and drop the hidden first display year (see `display_from` above).
  keep <- which(any_present & m$year >= display_from)
  if (length(keep) == 0) return(NULL)
  months <- substr(m$period[keep], 1, 7)
  out <- data.frame(month = months, stringsAsFactors = FALSE)
  for (col in names(ttm)) out[[col]] <- ttm[[col]][keep]

  # Some sources report a single combined hybrid figure (PHEV + HEV + MHEV
  # lumped together) which the pipeline parks in the HEV column with PHEV/EREV/
  # MHEV left empty (e.g. Colombia, Türkiye, Georgia). There "HEV" is a misnomer
  # — the bucket is all hybrids — so label it "Hybrid", matching the post text
  # (.pt_triplet_lines). When PHEV/EREV/MHEV carry their own data the HEV column
  # is genuine full-hybrid and keeps its label.
  hev_combined <- ("HEV" %in% names(out)) &&
    !any(c("PHEV", "EREV", "MHEV") %in% names(out))

  # Display labels: title-case for ICE-fuel families, keep acronyms as-is.
  display_label <- function(c) {
    if (c == "HEV" && hev_combined) return("Hybrid")
    if (c == "BEV") return(bev_label)
    if (c %in% c("PHEV","EREV","HEV","MHEV","CNG","LPG","ICE")) return(c)
    if (c == "OTHERS") return("Other")
    paste0(toupper(substr(c, 1, 1)), tolower(substr(c, 2, nchar(c))))
  }

  # Long format with stack order (top-of-stack last)
  # Stack from bottom to top. ICE sits next to the petrol/diesel cluster — it's
  # what countries report when they don't break ICE down further (China, USA,
  # South Korea, Thailand, Chile).
  stack_order <- c("OTHERS","FLEXFUEL","ETHANOL","LPG","CNG","GAS","PETROL","DIESEL","ICE","MHEV","HEV","EREV","PHEV","BEV")
  long_cols <- stack_order[stack_order %in% names(out)]
  # A hybrid-type band that never reaches one printable decimal anywhere in the
  # chart is absent data, not a market share (ACEA CV: PHEV is folded into EV
  # and HEV is a column of zeros). Leave it out instead of listing "Hybrid" in
  # the legend with nothing behind it. Its sliver, if any, is already part of
  # the other bands' 100%, so nothing else moves.
  absent <- vapply(long_cols, function(c) {
    c %in% c("HEV", "MHEV", "EREV", "PHEV") && !any(out[[c]] >= HYBRID_MIN_SHARE, na.rm = TRUE)
  }, logical(1))
  long_cols <- long_cols[!absent]
  long <- do.call(rbind, lapply(long_cols, function(c) {
    data.frame(month = out$month, type = display_label(c), value = out[[c]],
               stringsAsFactors = FALSE)
  }))
  long$type <- factor(long$type, levels = sapply(long_cols, display_label))
  long <- long[!is.na(long$value), ]
  long$numeric_month <- as.numeric(as.factor(long$month))
  long
}

# File-name slug of a series: "Germany"/"Whole" -> "germany", "Germany"/"HDV" ->
# "germany_hdv". Used for images/, posts/ and bands/; mirrored in index.html
# (bandSlug) — keep the two identical.
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

# The "Source:" line of a series — chart caption and params.csv: the source of
# the newest row, plus the label the series started with when that names a
# different source ("ASTRA · earlier: pxweb.bfs.admin.ch / ACEA"). The first
# row's label alone hid every change of source: Switzerland went BFS -> ACEA ->
# ASTRA and its charts kept saying BFS. Bare links are skipped (a link is not
# a name), and two labels that differ only from " (" or " —" on name the same
# source ("api.statbank.dk (BIL53) — pre-2018 via maintainer sheet").
# Mirrored by source_line() in scripts/build_series.py — keep the two identical.
source_line <- function(df) {
  s <- trimws(as.character(df$source))
  t <- suppressWarnings(period_to_year(as.character(df$period)))
  keep <- !is.na(s) & nzchar(s) & !grepl("^https?://", s) & !is.na(t)
  if (!any(keep)) return("")
  s <- s[keep][order(t[keep])]
  # useBytes: a label is matched byte-wise, so a non-UTF-8 session locale
  # cannot turn an em dash into an "invalid input string" error mid-render.
  name <- function(x) sub("[[:space:]]+(\\(|—).*$", "", x, useBytes = TRUE)
  current <- s[length(s)]
  if (name(current) == name(s[1])) current else paste0(current, " \u00b7 earlier: ", s[1])
}
