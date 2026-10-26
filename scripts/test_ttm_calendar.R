#!/usr/bin/env Rscript
# Regression test for compute_ttm_long(calendar = TRUE) in R/data.R (no network).
# Run:  Rscript scripts/test_ttm_calendar.R
# Pins the Vietnam layout: per-month spread of a yearly figure inside a monthly
# series, a month with no row, and a hybrid split that starts late (HEV empty →
# inside ICE). The coarse-row case uses `yearly` labels (generic calendar mode);
# the `monthly_est` case at the end checks load_country_csv() turns those rows
# into plain months with estimated = TRUE.
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
# monthly_est: a month estimated from annual data counts as a month everywhere.
tmp <- tempfile(fileext = ".csv")
e <- data.frame(period = p[1:24], time_interval = "monthly", variant = "Whole",
                BEV = 10, ICE = 90, TOTAL = 100, notes = "", stringsAsFactors = FALSE)
e$time_interval[e$period %in% c("2021-09", "2021-10")] <- "monthly_est"
write.csv(e, tmp, row.names = FALSE)
l <- load_country_csv(tmp)
ok(all(l$time_interval == "monthly"), "monthly_est loads as monthly")
ok(identical(l$period[l$estimated], c("2021-09", "2021-10")), "monthly_est rows flagged estimated")
ok(!any(l$estimated[l$period != "2021-09" & l$period != "2021-10"]), "other rows not flagged")
m <- l; m$estimated <- NULL
plain <- e; plain$time_interval <- "monthly"; write.csv(plain, tmp, row.names = FALSE)
ref <- load_country_csv(tmp); ref$estimated <- NULL
ok(identical(compute_ttm_long(m), compute_ttm_long(ref)),
   "TTM (calendar = FALSE) of monthly_est rows = the same rows labelled monthly")
unlink(tmp)
if (fails > 0) { cat(fails, "failure(s)\n"); quit(status = 1) }
cat("compute_ttm_long calendar: all checks passed\n")
