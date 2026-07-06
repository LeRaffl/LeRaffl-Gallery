# Domestic BEV conversion chart for Ray Wills' article — mirror of his
# export-share chart. Reads fitted Weibull params from params.csv (no refit),
# draws the smoothed BEV-share trajectories for the six export countries in
# Ray's dark chart style. Produces three variants into exports/ray_article/.
#
# Run from repo root:  Rscript scripts/ray_domestic_bev_chart.R

suppressPackageStartupMessages({ library(ggplot2); library(scales) })

repo <- normalizePath(".")
params <- read.csv(file.path(repo, "params.csv"), stringsAsFactors = FALSE)
outdir <- file.path(repo, "exports", "ray_article")
dir.create(outdir, recursive = TRUE, showWarnings = FALSE)

countries <- c("China", "Japan", "Germany", "South Korea", "USA", "Thailand")
labels    <- c(China = "China", Japan = "Japan", Germany = "Germany",
               `South Korea` = "South Korea", USA = "US", Thailand = "Thailand")
# Palette matches Ray's export chart; Thailand (new line) gets orange.
cols <- c(China = "#FF0000", Japan = "#9E1B1B", Germany = "#FFD300",
          `South Korea` = "#A427E8", USA = "#29ABE2", Thailand = "#FF8C00")

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

line_ends <- do.call(rbind, lapply(split(obs, obs$country),
                                   function(d) d[which.max(d$cal), ]))

# Volume-weighted combined line (weights.csv, same weighting as the gallery)
w <- read.csv(file.path(repo, "weights.csv"), stringsAsFactors = FALSE)
w <- subset(w, country %in% countries & variant == "Whole")[, c("country", "weight")]
# cap at the last month covered by all six countries, so the weight set is constant
common_end <- min(tapply(obs$cal, obs$country, max))
comb <- merge(subset(obs, cal <= common_end), w, by = "country")
comb <- aggregate(cbind(bev_w = bev * weight, weight) ~ cal, comb, FUN = sum)
comb$bev <- comb$bev_w / comb$weight
comb <- comb[comb$cal >= 2014, ]

caption_txt <- paste0("Data: CPCA, JADA/JAMA, KBA, molit.go.kr, ANL, data.thaiauto.or.th",
                      "  ·  Fitted trajectories · Chart @LeRafll ",
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
    plot.margin = margin(15, 130, 10, 15),
    axis.title = element_blank(),
    legend.position = "none"
  )

base_plot <- function(dat, x_min, x_max, title, ends = line_ends) {
  ggplot(dat, aes(cal, bev, color = country)) +
    geom_line(linewidth = 2) +
    geom_text(data = ends, aes(label = labels[country]),
              hjust = 0, nudge_x = 0.15, size = 6, fontface = "bold") +
    scale_color_manual(values = cols) +
    scale_y_continuous(labels = percent_format(accuracy = 1),
                       breaks = seq(0, 1, 0.2), limits = c(0, NA),
                       expand = expansion(mult = c(0, 0.05))) +
    scale_x_continuous(breaks = seq(2010, 2036, 2),
                       limits = c(x_min, x_max), expand = c(0.01, 0)) +
    coord_cartesian(clip = "off") +
    labs(title = title, subtitle = caption_txt) +
    ray_theme
}

save_png <- function(p, name) {
  ggsave(file.path(outdir, name), p, width = 12, height = 6.75, dpi = 200, bg = BG)
  cat("wrote", file.path("exports/ray_article", name), "\n")
}

title_main <- "BEV share of new vehicle sales in home markets by vehicle-exporting country"

# 1) Main: observed fit range, 2014 -> latest data
p1 <- base_plot(subset(obs, cal >= 2014), 2014, max(obs$cal) + 1.6, title_main)
save_png(p1, "domestic_bev_share_2014_now.png")

# 2) With dashed extrapolation to 2031 (labels move to the dashed line ends)
ext_ends <- do.call(rbind, lapply(split(ext, ext$country),
                                  function(d) d[which.max(d$cal), ]))
p2 <- base_plot(subset(obs, cal >= 2014), 2014, 2031.2, title_main, ends = ext_ends) +
  geom_line(data = ext, linetype = "22", linewidth = 1.4)
save_png(p2, "domestic_bev_share_extrapolated_2031.png")

# 2b) Zoomed out: extrapolation to 2035 on a full 0-100% scale
ext35_ends <- do.call(rbind, lapply(split(ext_full, ext_full$country),
                                    function(d) d[which.max(d$cal), ]))
p2b <- base_plot(subset(obs, cal >= 2014), 2014, 2035.2, title_main, ends = ext35_ends) +
  geom_line(data = ext_full, linetype = "22", linewidth = 1.4) +
  scale_y_continuous(labels = percent_format(accuracy = 1),
                     breaks = seq(0, 1, 0.2), limits = c(0, 1),
                     expand = expansion(mult = c(0, 0.03)))
save_png(p2b, "domestic_bev_share_extrapolated_2035_full_scale.png")

# 3) Main + volume-weighted combined line of the six markets
p3 <- base_plot(subset(obs, cal >= 2014), 2014, max(obs$cal) + 3.1, title_main) +
  geom_line(data = comb, aes(cal, bev), color = FG, linewidth = 1.6, linetype = "42",
            inherit.aes = FALSE) +
  annotate("text", x = max(comb$cal) + 0.15, y = comb$bev[which.max(comb$cal)] - 0.045,
           label = "6-market avg\n(vol. weighted)", hjust = 0, size = 4.5,
           fontface = "bold", color = FG, lineheight = 0.9)
save_png(p3, "domestic_bev_share_with_weighted_avg.png")

# ── Absolute BEV registrations (history only, no extrapolation) ──────────────
# Yearly/quarterly source rows are stored evenly spread over monthly rows, so
# calendar-year sums and rolling 12-month sums work uniformly across countries.
abs_raw <- do.call(rbind, lapply(countries, function(c) {
  d <- read.csv(file.path(repo, "data", paste0(c, ".csv")), stringsAsFactors = FALSE)
  d <- d[d$variant == "Whole", ]
  bev <- suppressWarnings(as.numeric(d$BEV)); bev[is.na(bev)] <- 0
  data.frame(country = c, period = substr(d$period, 1, 7), bev = bev)
}))
abs_raw$yr <- as.integer(substr(abs_raw$period, 1, 4))

title_abs <- "BEV sales in home markets by vehicle-exporting country"
caption_abs <- paste0("Data: CPCA, JADA/JAMA, KBA, molit.go.kr, ANL, data.thaiauto.or.th",
                      "  ·  Chart @LeRafll ",
                      paste0(format(Sys.Date(), "%d"), month.abb[as.integer(format(Sys.Date(), "%m"))],
                             format(Sys.Date(), "%Y")))

# Push overlapping right-edge labels apart (order-preserving, min gap in y units)
spread_labels <- function(y, gap) {
  o <- order(y)
  ys <- y[o]
  for (i in 2:length(ys)) if (ys[i] - ys[i - 1] < gap) ys[i] <- ys[i - 1] + gap
  y[o] <- ys
  y
}
abs_theme_add <- list(
  theme(axis.title.y = element_text(color = FG, face = "bold", size = rel(0.8),
                                    angle = 90, margin = margin(r = 8)))
)

abs_plot <- function(dat, ends, x_min, x_max, title, xbreaks) {
  ends$y_lab <- spread_labels(ends$bev / 1e6, gap = max(dat$bev) / 1e6 * 0.05)
  ggplot(dat, aes(x, bev / 1e6, color = country)) +
    geom_line(linewidth = 2) +
    geom_text(data = ends, aes(x, y_lab, label = labels[country]),
              hjust = 0, nudge_x = diff(c(x_min, x_max)) * 0.012,
              size = 6, fontface = "bold") +
    scale_color_manual(values = cols) +
    scale_y_continuous(limits = c(0, NA), expand = expansion(mult = c(0, 0.05))) +
    scale_x_continuous(breaks = xbreaks, limits = c(x_min, x_max), expand = c(0.01, 0)) +
    coord_cartesian(clip = "off") +
    labs(title = title, subtitle = caption_abs, y = "MILLIONS") +
    ray_theme + abs_theme_add
}

# 4) Annual BEV sales, full calendar years only
cur_year <- as.integer(format(Sys.Date(), "%Y"))
yearly <- aggregate(bev ~ country + yr, subset(abs_raw, yr >= 2014 & yr < cur_year), sum)
yearly$x <- yearly$yr
y_ends <- do.call(rbind, lapply(split(yearly, yearly$country), function(d) d[which.max(d$x), ]))
p4 <- abs_plot(yearly, y_ends, 2014, max(yearly$x) + 1.4,
               paste0("Annual ", title_abs), seq(2014, max(yearly$x), 1))
save_png(p4, "domestic_bev_absolute_annual.png")

# 5) Trailing-12-month BEV sales, monthly resolution up to the latest data
ttm <- do.call(rbind, lapply(split(abs_raw, abs_raw$country), function(d) {
  d <- d[order(d$period), ]
  n <- nrow(d); if (n < 12) return(NULL)
  s <- stats::filter(d$bev, rep(1, 12), sides = 1)
  yr <- as.integer(substr(d$period, 1, 4)); mo <- as.integer(substr(d$period, 6, 7))
  out <- data.frame(country = d$country, x = yr + (mo - 1) / 12, bev = as.numeric(s))
  out[!is.na(out$bev), ]
}))
ttm <- subset(ttm, x >= 2014)
t_ends <- do.call(rbind, lapply(split(ttm, ttm$country), function(d) d[which.max(d$x), ]))
p5 <- abs_plot(ttm, t_ends, 2014, max(ttm$x) + 1.6,
               paste0("Trailing 12-month ", title_abs), seq(2014, 2028, 2))
save_png(p5, "domestic_bev_absolute_ttm_monthly.png")
