# Domestic BEV conversion chart for Ray Wills' article — mirror of his
# export-share chart. Reads fitted Weibull params from params.csv (no refit),
# draws the smoothed BEV-share trajectories for the six export countries in
# Ray's dark chart style. Produces the chart set in exports/ray_article/.
#
# Run from repo root:  Rscript scripts/ray_domestic_bev_chart.R

suppressPackageStartupMessages({ library(ggplot2); library(scales) })

repo <- normalizePath(".")
params <- read.csv(file.path(repo, "params.csv"), stringsAsFactors = FALSE)
outdir <- file.path(repo, "exports", "ray_article")
dir.create(outdir, recursive = TRUE, showWarnings = FALSE)

countries <- c("China", "Japan", "Germany", "South Korea", "USA", "Thailand")
labels    <- c(China = "China", Japan = "Japan", Germany = "Germany",
               `South Korea` = "South Korea", USA = "US", Thailand = "Thailand",
               AvgW = "6-market avg", Total = "6-market total")
# Palette matches Ray's export chart; Thailand (new line) gets orange.
# AvgW/Total are the combined grey-white lines (weighted share / summed units).
cols <- c(China = "#FF0000", Japan = "#9E1B1B", Germany = "#FFD300",
          `South Korea` = "#A427E8", USA = "#29ABE2", Thailand = "#FF8C00",
          AvgW = "#EDEBE0", Total = "#EDEBE0")

p6 <- subset(params, country %in% countries & variant == "Whole")
stopifnot(nrow(p6) == 6)

# Fitted BEV share; x is internal time (calendar year = x + 1, see R/data.R).
bev_curve <- function(v1, v2, t0, x) 1 - exp(v1 * (x - (t0 - 1))^v2)

# data_per "YYYY-MM" -> internal x of that month
per_to_x <- function(per) {
  y <- as.integer(substr(per, 1, 4)); m <- as.integer(substr(per, 6, 7))
  (y - 1) + (m - 1) / 12
}

curve_df <- function(row, x_end) {
  x <- seq(row$t0, x_end, by = 1 / 12)
  data.frame(country = row$country, cal = x + 1,
             bev = bev_curve(row$v1, row$v2, row$t0, x))
}

# Observed range curves (solid, end at each country's latest data month)
obs <- do.call(rbind, lapply(seq_len(nrow(p6)), function(i)
  curve_df(p6[i, ], per_to_x(p6$data_per[i]))))
# Extrapolated continuation (dashed), long horizon; trimmed per chart
ext_full <- do.call(rbind, lapply(seq_len(nrow(p6)), function(i) {
  d <- curve_df(p6[i, ], 2034)                      # cal 2035
  d[d$cal >= max(obs$cal[obs$country == p6$country[i]]), ]
}))
ext <- subset(ext_full, cal <= 2031)
# Short fitted continuation to Dec 2026: unifies the ragged per-country data
# ends (currently Jun/May/Apr 2026) into one clean "actual + 2026 estimate"
# endpoint for the non-projection charts.
x_end26 <- 2026 + 11 / 12
ext26 <- subset(ext_full, cal <= x_end26)

line_ends <- do.call(rbind, lapply(split(obs, obs$country),
                                   function(d) d[which.max(d$cal), ]))
ends26 <- do.call(rbind, lapply(split(ext26, ext26$country),
                                function(d) d[which.max(d$cal), ]))

# Push overlapping right-edge labels apart (order-preserving, min gap in y units)
spread_labels <- function(y, gap) {
  o <- order(y)
  ys <- y[o]
  for (i in 2:length(ys)) if (ys[i] - ys[i - 1] < gap) ys[i] <- ys[i - 1] + gap
  y[o] <- ys
  y
}

# Volume-weighted combined line (weights.csv, same weighting as the gallery)
w <- read.csv(file.path(repo, "weights.csv"), stringsAsFactors = FALSE)
w <- subset(w, country %in% countries & variant == "Whole")[, c("country", "weight")]

# Weighted average over the full fitted curves (incl. extrapolation horizon).
# Used both for the "with avg" variants of the extrapolated charts and, cut at
# Dec 2026, as the avg line of the actual-data chart.
fullc <- do.call(rbind, lapply(seq_len(nrow(p6)), function(i) curve_df(p6[i, ], 2034)))
avgc <- merge(fullc, w, by = "country")
avgc <- aggregate(cbind(bev_w = bev * weight, weight) ~ cal, avgc, FUN = sum)
avgc$bev <- avgc$bev_w / avgc$weight
avgc$country <- "AvgW"
avgc <- avgc[avgc$cal >= 2015, c("country", "cal", "bev")]

caption_txt <- paste0("Data: CPCA, JADA/JAMA, KBA, molit.go.kr, ANL, data.thaiauto.or.th",
                      "  ·  Fitted trajectories · Chart @LeRaffl ",
                      paste0(format(Sys.Date(), "%d"), month.abb[as.integer(format(Sys.Date(), "%m"))],
                             format(Sys.Date(), "%Y")))

BG <- "#3B3B3B"; FG <- "#EDEBE0"; GRID <- "#FFFFFF"

ray_theme <- theme_minimal(base_size = 16) +
  theme(
    plot.background = element_rect(fill = BG, color = BG),
    panel.background = element_rect(fill = BG, color = NA),
    panel.grid.minor = element_blank(),
    panel.grid.major.x = element_blank(),
    panel.grid.major.y = element_line(color = GRID, linewidth = 0.3),
    text = element_text(color = FG, face = "bold"),
    axis.text = element_text(color = FG, face = "bold", size = rel(1.2)),
    plot.title = element_text(color = FG, face = "bold", size = rel(1.15), hjust = 0.5),
    plot.subtitle = element_text(color = FG, size = rel(0.85), hjust = 0.5),
    plot.margin = margin(15, 150, 10, 15),
    axis.title = element_blank(),
    legend.position = "none"
  )

base_plot <- function(dat, x_min, x_max, title, ends = line_ends,
                      xbreaks = seq(2015, 2027, 2), note = NULL) {
  ends$y_lab <- spread_labels(ends$bev, gap = 0.045 * max(c(dat$bev, ends$bev)))
  ggplot(dat, aes(cal, bev, color = country)) +
    geom_line(linewidth = 2) +
    geom_text(data = ends, aes(y = y_lab, label = labels[country]),
              hjust = 0, nudge_x = 0.15, size = 6, fontface = "bold", lineheight = 0.9) +
    scale_color_manual(values = cols) +
    scale_y_continuous(labels = percent_format(accuracy = 1),
                       breaks = seq(0, 1, 0.2), limits = c(0, NA),
                       expand = expansion(mult = c(0, 0.05))) +
    scale_x_continuous(breaks = xbreaks,
                       limits = c(x_min, x_max), expand = c(0.01, 0)) +
    coord_cartesian(clip = "off") +
    labs(title = title,
         subtitle = if (is.null(note)) caption_txt else paste0(caption_txt, "  ·  ", note)) +
    ray_theme
}

save_png <- function(p, name) {
  ggsave(file.path(outdir, name), p, width = 12, height = 6.75, dpi = 200, bg = BG)
  cat("wrote", file.path("exports/ray_article", name), "\n")
}

title_main <- "BEV share of new registrations in home markets by vehicle-exporting country"

# 1) Main: observed fit range from 2015, dashed estimate to end-2026
note26 <- "dashed = estimate to end of 2026"
p1 <- base_plot(subset(obs, cal >= 2015), 2015, x_end26 + 1.6, title_main,
                ends = ends26, note = note26) +
  geom_line(data = ext26, linetype = "22", linewidth = 1.4)
save_png(p1, "domestic_bev_share_2015_now.png")

# 2) With dashed extrapolation to 2031 (labels move to the dashed line ends)
proj_breaks <- seq(2015, 2035, 5)   # puts 2030 / 2035 on the projection axes
ext_ends <- do.call(rbind, lapply(split(ext, ext$country),
                                  function(d) d[which.max(d$cal), ]))
p2 <- base_plot(subset(obs, cal >= 2015), 2015, 2031.2, title_main,
                ends = ext_ends, xbreaks = proj_breaks) +
  geom_line(data = ext, linetype = "22", linewidth = 1.4)
save_png(p2, "domestic_bev_share_extrapolated_2031.png")

# 2b) Zoomed out: extrapolation to 2035 on a full 0-100% scale
ext35_ends <- do.call(rbind, lapply(split(ext_full, ext_full$country),
                                    function(d) d[which.max(d$cal), ]))
p2b <- base_plot(subset(obs, cal >= 2015), 2015, 2035.2, title_main,
                 ends = ext35_ends, xbreaks = proj_breaks) +
  geom_line(data = ext_full, linetype = "22", linewidth = 1.4) +
  scale_y_continuous(labels = percent_format(accuracy = 1),
                     breaks = seq(0, 1, 0.2), limits = c(0, 1),
                     expand = expansion(mult = c(0, 0.03)))
save_png(p2b, "domestic_bev_share_extrapolated_2035_full_scale.png")

# 2a-avg / 2b-avg) Extrapolated variants incl. the weighted-average line
avg_end <- function(x_cut) {
  d <- avgc[avgc$cal <= x_cut, ]
  d[which.max(d$cal), ]
}
p2a <- base_plot(subset(obs, cal >= 2015), 2015, 2031.2, title_main,
                 ends = rbind(ext_ends, avg_end(2031)), xbreaks = proj_breaks) +
  geom_line(data = ext, linetype = "22", linewidth = 1.4) +
  geom_line(data = subset(avgc, cal <= 2031), linetype = "42", linewidth = 1.6)
save_png(p2a, "domestic_bev_share_extrapolated_2031_with_weighted_avg.png")

p2c <- base_plot(subset(obs, cal >= 2015), 2015, 2035.2, title_main,
                 ends = rbind(ext35_ends, avg_end(2035)), xbreaks = proj_breaks) +
  geom_line(data = ext_full, linetype = "22", linewidth = 1.4) +
  geom_line(data = avgc, linetype = "42", linewidth = 1.6) +
  scale_y_continuous(labels = percent_format(accuracy = 1),
                     breaks = seq(0, 1, 0.2), limits = c(0, 1),
                     expand = expansion(mult = c(0, 0.03)))
save_png(p2c, "domestic_bev_share_extrapolated_2035_full_scale_with_weighted_avg.png")

# 3) Main + volume-weighted combined line of the six markets (the avg line is
# the fitted weighted average, cut at the same end-2026 estimate endpoint)
p3 <- base_plot(subset(obs, cal >= 2015), 2015, x_end26 + 1.6, title_main,
                ends = rbind(ends26, avg_end(x_end26)), note = note26) +
  geom_line(data = ext26, linetype = "22", linewidth = 1.4) +
  geom_line(data = subset(avgc, cal <= x_end26), linetype = "42", linewidth = 1.6)
save_png(p3, "domestic_bev_share_with_weighted_avg.png")

# ── Absolute BEV registrations (history + current-year estimate) ─────────────
# Yearly/quarterly source rows are stored evenly spread over monthly rows, so
# calendar-year sums and rolling 12-month sums work uniformly across countries.
abs_raw <- do.call(rbind, lapply(countries, function(c) {
  d <- read.csv(file.path(repo, "data", paste0(c, ".csv")), stringsAsFactors = FALSE)
  d <- d[d$variant == "Whole", ]
  bev <- suppressWarnings(as.numeric(d$BEV)); bev[is.na(bev)] <- 0
  data.frame(country = c, period = substr(d$period, 1, 7), bev = bev)
}))
abs_raw$yr <- as.integer(substr(abs_raw$period, 1, 4))

title_abs <- "BEV registrations in home markets by vehicle-exporting country"
caption_abs <- paste0("Data: CPCA, JADA/JAMA, KBA, molit.go.kr, ANL, data.thaiauto.or.th",
                      "  ·  Chart @LeRaffl ",
                      paste0(format(Sys.Date(), "%d"), month.abb[as.integer(format(Sys.Date(), "%m"))],
                             format(Sys.Date(), "%Y")))
abs_theme_add <- list(
  theme(axis.title.y = element_text(color = FG, face = "bold", size = rel(0.8),
                                    angle = 90, margin = margin(r = 8)))
)

abs_plot <- function(dat, ends, x_min, x_max, title, xbreaks, y_max, note = NULL) {
  ends$y_lab <- spread_labels(ends$bev / 1e6, gap = y_max * 0.05)
  ggplot(dat, aes(x, bev / 1e6, color = country)) +
    geom_line(linewidth = 2) +
    geom_text(data = ends, aes(x, y_lab, label = labels[country]),
              hjust = 0, nudge_x = diff(c(x_min, x_max)) * 0.012,
              size = 6, fontface = "bold") +
    scale_color_manual(values = cols) +
    scale_y_continuous(limits = c(0, y_max), expand = expansion(mult = c(0, 0.05))) +
    scale_x_continuous(breaks = xbreaks, limits = c(x_min, x_max), expand = c(0.01, 0)) +
    coord_cartesian(clip = "off") +
    labs(title = title, y = "MILLIONS",
         subtitle = if (is.null(note)) caption_abs else paste0(caption_abs, "  ·  ", note)) +
    ray_theme + abs_theme_add
}

# 4) Annual BEV sales: full calendar years, plus a current-year full-year
# estimate = YTD x (full prior year / same months of prior year) per country,
# so the actual-data chart ends at 2026 as one clean endpoint. The final
# segment is dashed (dashed = estimate, same convention as the share charts).
cur_year <- as.integer(format(Sys.Date(), "%Y"))
yearly <- aggregate(bev ~ country + yr, subset(abs_raw, yr >= 2015 & yr < cur_year), sum)
yearly$x <- yearly$yr

est26 <- do.call(rbind, lapply(split(abs_raw, abs_raw$country), function(d) {
  ytd <- d[d$yr == cur_year, ]
  if (nrow(ytd) == 0) return(NULL)
  mo_max <- max(as.integer(substr(ytd$period, 6, 7)))
  prev <- d[d$yr == cur_year - 1, ]
  prev_same <- prev[as.integer(substr(prev$period, 6, 7)) <= mo_max, ]
  data.frame(country = d$country[1], x = cur_year,
             bev = sum(ytd$bev) * sum(prev$bev) / sum(prev_same$bev))
}))
cat(sprintf("%d full-year estimates (millions): %s\n", cur_year,
            paste(sprintf("%s %.2f", est26$country, est26$bev / 1e6), collapse = ", ")))

seg26 <- rbind(yearly[yearly$yr == cur_year - 1, c("country", "x", "bev")],
               est26[, c("country", "x", "bev")])
y_ends <- est26[, c("country", "x", "bev")]
y_tot <- aggregate(bev ~ x, yearly, sum); y_tot$country <- "Total"
tot26 <- data.frame(x = cur_year, bev = sum(est26$bev), country = "Total")
tot_seg26 <- rbind(y_tot[y_tot$x == cur_year - 1, ], tot26)
note_abs <- sprintf("dashed = %d estimate from year-to-date", cur_year)
y_max_annual <- max(y_tot$bev, tot26$bev) / 1e6   # shared y axis for the with/without pair
p4 <- abs_plot(yearly, y_ends, 2015, cur_year + 1.4,
               paste0("Annual ", title_abs), seq(2015, cur_year, 1), y_max_annual,
               note = note_abs) +
  geom_line(data = seg26, linetype = "22", linewidth = 2)
save_png(p4, "domestic_bev_absolute_annual.png")

# 4b) Annual + summed total of the six markets
p4b <- abs_plot(yearly, rbind(y_ends, tot26[, c("country", "x", "bev")]),
                2015, cur_year + 1.4,
                paste0("Annual ", title_abs), seq(2015, cur_year, 1), y_max_annual,
                note = note_abs) +
  geom_line(data = y_tot, linetype = "42", linewidth = 1.6) +
  geom_line(data = seg26, linetype = "22", linewidth = 2) +
  geom_line(data = tot_seg26, linetype = "22", linewidth = 1.6)
save_png(p4b, "domestic_bev_absolute_annual_with_total.png")

# 5) Trailing-12-month BEV sales, monthly resolution up to the latest data
ttm <- do.call(rbind, lapply(split(abs_raw, abs_raw$country), function(d) {
  d <- d[order(d$period), ]
  n <- nrow(d); if (n < 12) return(NULL)
  s <- stats::filter(d$bev, rep(1, 12), sides = 1)
  yr <- as.integer(substr(d$period, 1, 4)); mo <- as.integer(substr(d$period, 6, 7))
  out <- data.frame(country = d$country, x = yr + (mo - 1) / 12, bev = as.numeric(s))
  out[!is.na(out$bev), ]
}))
ttm <- subset(ttm, x >= 2015)
t_ends <- do.call(rbind, lapply(split(ttm, ttm$country), function(d) d[which.max(d$x), ]))
t_common <- min(tapply(ttm$x, ttm$country, max))
t_tot <- aggregate(bev ~ x, subset(ttm, x <= t_common), sum); t_tot$country <- "Total"
y_max_ttm <- max(t_tot$bev) / 1e6      # shared y axis for the with/without pair
p5 <- abs_plot(ttm, t_ends, 2015, max(ttm$x) + 1.6,
               paste0("Trailing 12-month ", title_abs), seq(2015, 2027, 2), y_max_ttm)
save_png(p5, "domestic_bev_absolute_ttm_monthly.png")

# 5b) TTM + summed total, capped at the last month all six countries cover
p5b <- abs_plot(ttm, rbind(t_ends[, c("country", "x", "bev")],
                           t_tot[which.max(t_tot$x), c("country", "x", "bev")]),
                2015, max(ttm$x) + 1.6,
                paste0("Trailing 12-month ", title_abs), seq(2015, 2027, 2), y_max_ttm) +
  geom_line(data = t_tot, linetype = "42", linewidth = 1.6)
save_png(p5b, "domestic_bev_absolute_ttm_monthly_with_total.png")
