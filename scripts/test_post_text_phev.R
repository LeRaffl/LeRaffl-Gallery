#!/usr/bin/env Rscript
# Regression test for the phantom PHEV / Hybrid rows in R/post_text.R (no network).
# Run:  Rscript scripts/test_post_text_phev.R
# Sources without a PHEV split (ACEA commercial vehicles fold PHEV into "EV")
# must not print "0.0% PHEV", "+0.0pp Hybrid" or "Hybrid peaked at 0.0%"; sources
# WITH a split keep their PHEV line even when this period's value is a real zero.
source("R/data.R"); source("R/post_text.R")
fails <- 0
ok <- function(cond, msg) if (!isTRUE(cond)) { fails <<- fails + 1; cat("FAIL:", msg, "\n") }
has <- function(txt, pat) grepl(pat, txt, fixed = TRUE)

# --- main post: triplet lines ----------------------------------------------
v <- c(BEV = 175, PHEV = NA, EREV = NA, HEV = 0, TOTAL = 1000)
l <- .pt_triplet_lines(v, bev_label = "EV", has_phev_split = FALSE)
ok(identical(l, c("17.5% EV", "82.5% ICE")), "no split, no hybrid: two lines only")
l <- .pt_triplet_lines(c(BEV = 175, PHEV = NA, EREV = NA, HEV = 0.4, TOTAL = 1000), "EV", FALSE)
ok(length(l) == 2 && !any(grepl("Hybrid|PHEV", l)), "no split, hybrid below 0.05%: still two lines")
l <- .pt_triplet_lines(c(BEV = 175, PHEV = NA, EREV = NA, HEV = 13, TOTAL = 1000), "EV", FALSE)
ok(identical(l, c("17.5% EV", "1.3% Hybrid", "81.2% ICE")), "no split, real hybrid: Hybrid line stays")
l <- .pt_triplet_lines(c(BEV = 175, PHEV = 0, EREV = NA, HEV = NA, TOTAL = 1000), "BEV", TRUE)
ok(identical(l, c("17.5% BEV", "0.0% PHEV", "82.5% ICE")), "split source: a measured zero PHEV keeps its line")
l <- .pt_triplet_lines(c(BEV = 100, PHEV = 50, EREV = 0, HEV = 20, TOTAL = 1000), "BEV", TRUE)
ok(identical(l, c("10.0% BEV", "5.0% PHEV", "85.0% ICE (of which 2.0%p were HEV)")), "split source with PHEV: unchanged")
ok(identical(.pt_triplet_lines(v, "BEV"), c("17.5% BEV", "0.0% PHEV", "82.5% ICE")), "default arg keeps old behaviour")

# --- full posts on a synthetic quarterly CV series -------------------------
mk <- function(n, bev, hev, phev = NA) {
  p <- sprintf("%04d-%02d", rep(2021:2026, each = 4)[seq_len(n)], rep(c(2, 5, 8, 11), 6)[seq_len(n)])
  d <- data.frame(period = p, time_interval = "quarterly", variant = "HDV", source = "ACEA",
                  BEV = bev, PHEV = phev, HEV = hev, TOTAL = 1000, stringsAsFactors = FALSE)
  d$year <- period_to_year(d$period)
  d
}
n <- 20
d <- mk(n, bev = seq(20, 200, length.out = n), hev = 0)
post <- build_post_text(d, "Sweden (HDV)", d$period[n], bev_label = "EV", has_phev_split = FALSE)
ok(!has(post, "PHEV") && !has(post, "Hybrid"), "post: no PHEV / Hybrid line without split")
ok(has(post, "EV Trajectory") && has(post, "ICE"), "post: EV and ICE remain")
ttm <- build_ttm_post_text(d, "Sweden (HDV)", d$period[n], bev_label = "EV", has_phev_split = FALSE)
ok(nzchar(ttm) && !has(ttm, "Hybrid") && !has(ttm, "PHEV") && !has(ttm, "HEV"), "ttm: no Hybrid band")
ok(has(ttm, " EV ") && has(ttm, " ICE "), "ttm: EV and ICE bands")

# Hybrid that vanished again after peaking at a printable level: peak is reported.
h <- c(rep(0, 8), 10, 12, 14, 12, 10, 8, 6, 4, 3, 2, 2, 2)
d2 <- mk(n, bev = seq(20, 200, length.out = n), hev = h)
ttm2 <- build_ttm_post_text(d2, "Germany (Vans)", d2$period[n], bev_label = "EV", has_phev_split = FALSE)
ok(has(ttm2, "Hybrid"), "ttm: real hybrid share keeps its band")
# A hybrid sliver (peak below 0.05%) never prints "peaked at 0.0%".
d3 <- mk(n, bev = seq(20, 200, length.out = n), hev = c(rep(0, 10), 0.3, rep(0, 9)))
ttm3 <- build_ttm_post_text(d3, "Germany (HDV)", d3$period[n], bev_label = "EV", has_phev_split = FALSE)
ok(!has(ttm3, "peaked at 0.0%") && !has(ttm3, "Hybrid"), "ttm: sliver hybrid hidden, no 'peaked at 0.0%'")
bands <- regmatches(ttm3, gregexpr("[0-9.]+% → [0-9.]+%", ttm3))[[1]]
ok(length(bands) == 2, "ttm: exactly EV + ICE rows")

# Split source: PHEV and HEV bands still there.
d4 <- mk(n, bev = seq(20, 200, length.out = n), hev = 30, phev = seq(10, 100, length.out = n))
ttm4 <- build_ttm_post_text(d4, "Belgium (HDV)", d4$period[n], bev_label = "BEV", has_phev_split = TRUE)
ok(has(ttm4, "PHEV") && has(ttm4, "HEV"), "ttm: split source keeps PHEV and HEV bands")

if (fails > 0) { cat(fails, "failure(s)\n"); quit(status = 1) }
cat("test_post_text_phev: all checks passed\n")
