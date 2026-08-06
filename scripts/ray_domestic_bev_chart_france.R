# Variant of ray_domestic_bev_chart.R for the EU-focused article: the same
# BEV-share chart with France added as a seventh line (Peter Newman's note —
# the text discusses France, so the big figure should show it). The canonical
# six-country set is left untouched because the published CleanTechnica piece
# embeds it; this renders *_with_france.png variants only.
#
# Run from repo root:  Rscript scripts/ray_domestic_bev_chart_france.R

suppressPackageStartupMessages({ library(ggplot2); library(scales) })

repo <- normalizePath(".")
params <- read.csv(file.path(repo, "params.csv"), stringsAsFactors = FALSE)
outdir <- file.path(repo, "exports", "ray_article")

countries <- c("China", "Japan", "Germany", "France", "South Korea", "USA", "Thailand")
labels    <- c(China = "China", Japan = "Japan", Germany = "Germany", France = "France",
               `South Korea` = "South Korea", USA = "US", Thailand = "Thailand")
cols <- c(China = "#FF0000", Japan = "#9E1B1B", Germany = "#FFD300", France = "#2E6FE8",
          `South Korea` = "#A427E8", USA = "#29ABE2", Thailand = "#FF8C00")

p7 <- subset(params, country %in% countries & variant == "Whole")
stopifnot(nrow(p7) == 7)

bev_curve <- function(v1, v2, t0, x) 1 - exp(v1 * (x - (t0 - 1))^v2)
per_to_x <- function(per) {
  y <- as.integer(substr(per, 1, 4)); m <- as.integer(substr(per, 6, 7))
  (y - 1) + (m - 1) / 12
}
curve_df <- function(row, x_end) {
  x <- seq(row$t0, x_end, by = 1 / 12)
  data.frame(country = row$country, cal = x + 1,
             bev = bev_curve(row$v1, row$v2, row$t0, x))
}

obs <- do.call(rbind, lapply(seq_len(nrow(p7)), function(i)
  curve_df(p7[i, ], per_to_x(p7$data_per[i]))))
ext_full <- do.call(rbind, lapply(seq_len(nrow(p7)), function(i) {
  d <- curve_df(p7[i, ], 2034)
  d[d$cal >= max(obs$cal[obs$country == p7$country[i]]), ]
}))
ext <- subset(ext_full, cal <= 2031)
x_end26 <- 2026 + 11 / 12
ext26 <- subset(ext_full, cal <= x_end26)

ends26 <- do.call(rbind, lapply(split(ext26, ext26$country),
                                function(d) d[which.max(d$cal), ]))
ext_ends <- do.call(rbind, lapply(split(ext, ext$country),
                                  function(d) d[which.max(d$cal), ]))

spread_labels <- function(y, gap) {
  o <- order(y); ys <- y[o]
  for (i in 2:length(ys)) if (ys[i] - ys[i - 1] < gap) ys[i] <- ys[i - 1] + gap
  y[o] <- ys
  y
}

caption_txt <- paste0("Data: CPCA, JADA/JAMA, KBA, ACEA, molit.go.kr, ANL, data.thaiauto.or.th",
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
    axis.text = element_text(color = FG, face = "bold", size = rel(1.05)),
    plot.title.position = "plot",
    plot.title = element_text(color = FG, face = "bold", size = rel(0.9), hjust = 0.5),
    plot.subtitle = element_text(color = FG, size = rel(0.7), hjust = 0.5, lineheight = 1.2),
    plot.margin = margin(15, 108, 10, 15),
    axis.title = element_blank(),
    legend.position = "none")

base_plot <- function(dat, x_min, x_max, title, ends,
                      xbreaks = seq(2015, 2027, 2), note = NULL) {
  ends$y_lab <- spread_labels(ends$bev, gap = 0.045 * max(c(dat$bev, ends$bev)))
  ggplot(dat, aes(cal, bev, color = country)) +
    geom_line(linewidth = 2) +
    geom_text(data = ends, aes(y = y_lab, label = labels[country]),
              hjust = 0, nudge_x = 0.15, size = 6, fontface = "bold", lineheight = 0.9) +
    scale_color_manual(values = cols) +
    scale_y_continuous(labels = percent_format(accuracy = 1),
                       breaks = seq(0, 1, 0.1), limits = c(0, NA),
                       expand = expansion(mult = c(0, 0.05))) +
    scale_x_continuous(breaks = xbreaks, limits = c(x_min, x_max), expand = c(0.01, 0)) +
    coord_cartesian(clip = "off") +
    labs(title = title,
         subtitle = if (is.null(note)) caption_txt else paste0(caption_txt, "\n", note)) +
    ray_theme
}

save_png <- function(p, name) {
  ggsave(file.path(outdir, name), p, width = 12, height = 6.75, dpi = 200, bg = BG)
  cat("wrote exports/ray_article/", name, "\n", sep = "")
}

title_main <- "BEV share of new registrations in home markets by vehicle-exporting country"

p1 <- base_plot(subset(obs, cal >= 2015), 2015, x_end26 + 0.3, title_main,
                ends = ends26, note = "dashed = estimate to end of 2026") +
  geom_line(data = ext26, linetype = "22", linewidth = 1.4)
save_png(p1, "domestic_bev_share_2015_now_with_france.png")

p2 <- base_plot(subset(obs, cal >= 2015), 2015, 2031.2, title_main,
                ends = ext_ends, xbreaks = seq(2015, 2035, 5)) +
  geom_line(data = ext, linetype = "22", linewidth = 1.4)
save_png(p2, "domestic_bev_share_extrapolated_2031_with_france.png")
