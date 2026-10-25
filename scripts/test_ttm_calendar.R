#!/usr/bin/env Rscript
# Regression test for compute_ttm_long(calendar = TRUE) in R/data.R (no network).
# Run:  Rscript scripts/test_ttm_calendar.R
# Pins the Vietnam layout: per-month spread of a yearly figure (row labelled
# `yearly`) inside a monthly series, a month with no row, and a hybrid split
# that starts late (HEV empty → inside ICE).
source("R/data.R")
fails <- 0
ok <- function(cond, msg) if (!isTRUE(cond)) { fails <<- fails + 1; cat("FAIL:", msg, "\n") }

p <- format(seq(as.Date("2021-01-01"), as.Date("2023-12-01"), by = "month"), "%Y-%m")
df <- data.frame(period = p, time_interval = "monthly", variant = "Whole",
                 BEV = 10, HEV = NA_real_, MHEV = NA_real_, ICE = 90, OTHERS = 0, TOTAL = 100,
                 stringsAsFactors = FALSE)
df$time_interval[p %in% c("2021-09", "2021-10")] <- "yearly"     # VinFast estimate months
df$HEV[p >= "2022-07"] <- 5; df$MHEV[p >= "2022-07"] <- 1; df$ICE[p >= "2022-07"] <- 84         # hybrid split starts 2022-07
df <- df[df$period != "2023-03", ]                                 # a month without a row
df$year <- period_to_year(df$period)

old <- compute_ttm_long(df)
new <- compute_ttm_long(df, calendar = TRUE)
w <- reshape(new[, c("month", "type", "value")], idvar = "month", timevar = "type", direction = "wide")
ok(!is.null(old) && min(old$month) == "2023-07", "calendar = FALSE keeps the old cut (HEV needs 12 own months)")
ok(min(w$month) == "2022-01", "coarse rows count: TTM from the second year")
ok(all(abs(w$value.BEV[w$month %in% c("2022-01", "2022-06")] - 0.10) < 1e-9), "BEV 10 % through the yearly months")
ok(!any(w$month >= "2023-03" & w$month <= "2024-02"), "windows across the missing month are dropped")
h <- w[w$month == "2022-12", ]
ok(h$value.HEV == 0 && h$value.MHEV == 0 && abs(h$value.ICE - 0.90) < 1e-9, "partial HEV window folded into ICE")
ok(all(abs(rowSums(w[, -1]) - 1) < 1e-9), "shares add up to 100 %")
if (fails > 0) { cat(fails, "failure(s)\n"); quit(status = 1) }
cat("compute_ttm_long calendar: all checks passed\n")
