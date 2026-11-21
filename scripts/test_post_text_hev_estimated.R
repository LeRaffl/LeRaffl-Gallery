#!/usr/bin/env Rscript
# Which notes mark the latest month's HEV as an estimate (R/post_text.R,
# .pt_hev_estimated): the posts then leave HEV out. No network.
# Run: Rscript scripts/test_post_text_hev_estimated.R
source("R/data.R")
source("R/post_text.R")
fails <- 0
ok <- function(cond, msg) if (!isTRUE(cond)) { fails <<- fails + 1; cat("FAIL:", msg, "\n") }
last <- function(note) data.frame(period = c("2026-09", "2026-10"), notes = c("", note),
                                  stringsAsFactors = FALSE)
ok(.pt_hev_estimated(last("register count (BEV/PHEV/OTHERS/TOTAL); HEV/PETROL/DIESEL estimated from the 2026-08 ACEA split")),
   "Czechia's register row")
ok(.pt_hev_estimated(last("TOTAL/BEV/PHEV/DIESEL/OTHERS StatFin 121d; HEV/PETROL estimated: StatFin petrol split by 2026-09's HEV share, until ACEA ...")),
   "Finland's previous-month estimate")
ok(.pt_hev_estimated(last("TOTAL/BEV/PHEV/DIESEL/OTHERS StatFin 121d; HEV/PETROL estimated: StatFin petrol split by ACEA's HEV share ...")),
   "Finland's ACEA-share estimate")
ok(.pt_hev_estimated(last("HEV estimated (with PETROL): Swing petrol split by the RDW register ...")),
   "a back-estimate")
ok(!.pt_hev_estimated(last("TOTAL/BEV/PHEV/DIESEL/OTHERS StatFin 121d; HEV/PETROL = StatFin petrol split by the Traficom register's counted HEV share ...")),
   "the register's counted share is quoted")
ok(!.pt_hev_estimated(last("")), "no note")
ok(!.pt_hev_estimated(data.frame(period = "2026-10", notes = "HEV estimated ...")[0, , drop = FALSE]), "no rows")
if (fails > 0) { cat(fails, "failure(s)\n"); quit(status = 1) }
cat("post text HEV estimate detection: all checks passed\n")
