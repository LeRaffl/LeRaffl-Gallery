#!/usr/bin/env Rscript
# Test for R/series_meta.R (no network).  Run:  Rscript scripts/test_series_meta.R
# What the BEV column means is decided per period from the data, not per source name:
# ACEA CV rows without a PHEV value are "EV" (BEV+PHEV); a real split or a pure-BEV
# source flips the label to "BEV" on its own.
source("R/data.R"); source("R/upsert.R"); source("R/series_meta.R")
fails <- 0
ok <- function(cond, msg) if (!isTRUE(cond)) { fails <<- fails + 1; cat("FAIL:", msg, "\n") }
mk <- function(period, interval, source, bev, phev = NA, hev = 0, variant = "HDV", total = 1000) {
  d <- data.frame(period = period, time_interval = interval, variant = variant, source = source,
                  BEV = bev, PHEV = phev, HEV = hev, TOTAL = total, stringsAsFactors = FALSE)
  d$year <- period_to_year(d$period); d
}

# Sweden-style: ACEA quarters only -> EV, no PHEV split.
s <- mk(c("2025-02", "2025-05", "2025-08"), "quarterly", "ACEA", c(10, 20, 30))
m <- derive_series_meta(s, "HDV")
ok(m$bev_label == "EV" && m$ev_combined && m$ev_combined_any, "ACEA CV quarters read as EV")
ok(!m$has_phev_split && !m$has_phev_split_latest && m$ev_basis_change == "", "no split, no basis change")

# Poland-style: ACEA quarters, then PZPM months (pure BEV) -> per-period label.
p <- rbind(mk(c("2025-11", "2026-02"), "quarterly", "ACEA", c(71, 49)),
           mk(c("2026-04", "2026-05"), "monthly", "PZPM", c(16, 7)))
ok(identical(row_ev_combined(p, "HDV"), c(TRUE, TRUE, FALSE, FALSE)), "Poland: ACEA rows EV, PZPM rows BEV")
m <- derive_series_meta(p, "HDV")
ok(m$bev_label == "BEV" && !m$ev_combined, "Poland: latest period is pure BEV")
ok(m$ev_combined_any && m$ev_basis_change == "2026-04", "Poland: history still flagged, break at 2026-04")

# Germany-with-KBA-style: ACEA quarters, then a real BEV/PHEV split source.
g <- rbind(mk(c("2025-11", "2026-02"), "quarterly", "ACEA", c(71, 49)),
           mk(c("2026-04", "2026-05"), "monthly", "KBA", c(16, 7), phev = c(5, 4)))
m <- derive_series_meta(g, "HDV")
ok(m$bev_label == "BEV" && m$has_phev_split && m$has_phev_split_latest, "real split: BEV label and PHEV rows")

# Passenger-car ACEA ("Whole") is NOT combined.
w <- mk(c("2026-01", "2026-02"), "monthly", "ACEA", c(100, 120), phev = c(50, 60), variant = "Whole")
ok(derive_series_meta(w, "Whole")$bev_label == "BEV", "ACEA Whole stays BEV")
w2 <- mk(c("2026-01", "2026-02"), "monthly", "ACEA", c(100, 120), variant = "Whole")
ok(!any(row_ev_combined(w2, "Whole")), "variant gate: ACEA Whole without PHEV is still BEV")

# TOTAL-only rows are neutral; an all-empty series degrades to BEV.
t <- mk("2021-07", "yearly", "ACEA", NA)
ok(derive_series_meta(t, "HDV")$bev_label == "BEV", "TOTAL-only series: BEV, nothing flagged")

# upsert round trip.
tmp <- tempfile(fileext = ".csv")
upsert_series_meta(tmp, "Poland", "HDV", "2026-09", derive_series_meta(p, "HDV"))
upsert_series_meta(tmp, "Sweden", "HDV", "2026-09", derive_series_meta(s, "HDV"))
upsert_series_meta(tmp, "Poland", "HDV", "2026-10", derive_series_meta(p, "HDV"))
r <- read.csv(tmp, stringsAsFactors = FALSE)
ok(nrow(r) == 2 && identical(r$data_per[r$country == "Poland"], "2026-10"), "upsert replaces by country+variant")
ok(identical(names(r), strsplit(SERIES_META_HEADER, ",")[[1]]), "header stable")
ok(all(r$ev_combined_any == "true" | r$ev_combined_any == TRUE), "booleans written as true")

# TTM legend: a hybrid band with no data is not drawn / not in the legend.
q <- mk(sprintf("%04d-%02d", rep(2021:2025, each = 4), rep(c(2, 5, 8, 11), 5)), "quarterly", "ACEA",
        bev = seq(10, 200, length.out = 20), hev = 0)
q$OTHERS <- 0; q$DIESEL <- q$TOTAL - q$BEV
tl <- compute_ttm_long(q, bev_label = "EV")
ok(!is.null(tl) && !any(as.character(tl$type) %in% c("Hybrid", "HEV")), "TTM: no Hybrid band for all-zero HEV")
ok("EV" %in% as.character(tl$type), "TTM: EV band stays")
q$HEV <- c(rep(0, 10), rep(40, 10))
tl2 <- compute_ttm_long(q, bev_label = "EV")
ok(any(as.character(tl2$type) == "Hybrid"), "TTM: real hybrid share keeps its band")

if (fails > 0) { cat(fails, "failure(s)\n"); quit(status = 1) }
cat("test_series_meta: all checks passed\n")
