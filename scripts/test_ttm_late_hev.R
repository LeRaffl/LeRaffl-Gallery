#!/usr/bin/env Rscript
# Regression test for the late-start HEV fold into PETROL in compute_ttm_long()
# (R/data.R). No network.  Run:  Rscript scripts/test_ttm_late_hev.R
# A source that books full hybrids inside petrol until its split starts
# (Czechia 2022-01, Netherlands and Finland register/ACEA fills) leaves HEV
# empty before that month. The TTM must keep its history: the partial-window
# HEV mass stays in PETROL and the HEV band is 0 until a full window of split
# months exists -- the same rule as EREV inside PHEV (China).
source("R/data.R")
fails <- 0
ok <- function(cond, msg) if (!isTRUE(cond)) { fails <<- fails + 1; cat("FAIL:", msg, "\n") }

p <- format(seq(as.Date("2019-01-01"), as.Date("2023-12-01"), by = "month"), "%Y-%m")
df <- data.frame(period = p, time_interval = "monthly", variant = "Whole",
                 BEV = 10, PHEV = 5, HEV = NA_real_, PETROL = 60, DIESEL = 20,
                 OTHERS = 5, TOTAL = 100, stringsAsFactors = FALSE)
split <- p >= "2022-01"
df$HEV[split] <- 25; df$PETROL[split] <- 35        # petrol 60 = 25 HEV + 35 pure
df$year <- period_to_year(df$period)

t <- compute_ttm_long(df)
w <- reshape(t[, c("month", "type", "value")], idvar = "month", timevar = "type", direction = "wide")
ok(min(w$month) == "2020-01", "history kept: TTM from the second year, not from the first full HEV window")
ok(all(abs(rowSums(w[, -1]) - 1) < 1e-9), "shares add up to 100 %")
mid <- w[w$month == "2022-06", ]
ok(abs(mid$value.HEV) < 1e-12 && abs(mid$value.Petrol - 0.60) < 1e-9,
   "partial window: HEV held at 0, its mass stays in PETROL")
ok(abs(w$value.Petrol[w$month == "2021-12"] - 0.60) < 1e-9, "before the split: petrol incl. hybrids")
last <- w[w$month == "2022-12", ]
ok(abs(last$value.HEV - 0.25) < 1e-9 && abs(last$value.Petrol - 0.35) < 1e-9,
   "first full window: HEV band appears, petrol is pure petrol")
ok(all(abs(w$value.BEV - 0.10) < 1e-9) && all(abs(w$value.Diesel - 0.20) < 1e-9),
   "other bands untouched by the fold")

# A series whose HEV is filled from the first month is unchanged.
full <- df; full$HEV <- 25; full$PETROL <- 35
tf <- compute_ttm_long(full)
ok(min(tf$month) == "2020-01" && all(abs(tf$value[tf$type == "HEV"] - 0.25) < 1e-9),
   "HEV from the start: no fold")

# No PETROL column (aggregate ICE without calendar mode): the old cut stays.
ice <- df; ice$ICE <- ice$PETROL + ice$DIESEL; ice$PETROL <- NULL; ice$DIESEL <- NULL
ti <- compute_ttm_long(ice)
ok(!is.null(ti) && min(ti$month) == "2022-12", "ICE host only folds in calendar mode (Vietnam rule)")

if (fails > 0) { cat(fails, "failure(s)\n"); quit(status = 1) }
cat("compute_ttm_long late HEV: all checks passed\n")
