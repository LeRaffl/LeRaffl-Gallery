# Small-multiples panel for the EU-focused article (Electrive/T&E piece):
# one mini-chart per vehicle-exporting country plus France, showing the
# trailing-12-month BEV share of new registrations — and, in the second
# variant, the mirrored decline of everything that isn't a plug-in.
#
# "Non-plug-in" = (TOTAL − BEV − PHEV − EREV) / TOTAL, i.e. ICE plus full
# hybrids — the only fuel split derivable from every country CSV (fuel
# columns differ per source; BEV/PHEV/TOTAL are universal).
#
# Run from repo root:  Rscript scripts/eu_small_multiples.R

suppressPackageStartupMessages({ library(ggplot2); library(scales) })

repo <- normalizePath(".")
outdir <- file.path(repo, "exports", "ray_article")

countries <- c("China", "Thailand", "Germany", "France", "USA", "Japan")
labels    <- c(China = "China", Thailand = "Thailand", Germany = "Germany",
               France = "France", USA = "US", Japan = "Japan")
cols <- c(China = "#FF0000", Thailand = "#FF8C00", Germany = "#FFD300",
          France = "#2E6FE8", USA = "#29ABE2", Japan = "#9E1B1B")

num <- function(x) { v <- suppressWarnings(as.numeric(x)); v[is.na(v)] <- 0; v }

ttm <- do.call(rbind, lapply(countries, function(c) {
  d <- read.csv(file.path(repo, "data", paste0(c, ".csv")),
                stringsAsFactors = FALSE, check.names = FALSE)
  d <- d[d$variant == "Whole", ]
  d <- d[order(d$period), ]
  bev <- num(d$BEV); tot <- num(d$TOTAL)
  phev <- num(if ("PHEV" %in% names(d)) d$PHEV else rep(0, nrow(d)))
  erev <- num(if ("EREV" %in% names(d)) d$EREV else rep(0, nrow(d)))
  roll <- function(v) as.numeric(stats::filter(v, rep(1, 12), sides = 1))
  yr <- as.integer(substr(d$period, 1, 4)); mo <- as.integer(substr(d$period, 6, 7))
  out <- data.frame(country = c, x = yr + (mo - 1) / 12,
                    bev = roll(bev) / roll(tot),
                    nonplug = (roll(tot) - roll(bev) - roll(phev) - roll(erev)) / roll(tot))
  out[!is.na(out$bev) & out$x >= 2015, ]
}))
ttm$country <- factor(ttm$country, levels = countries)

BG <- "#3B3B3B"; FG <- "#EDEBE0"; GRID <- "#FFFFFF"
datestamp <- paste0(format(Sys.Date(), "%d"), month.abb[as.integer(format(Sys.Date(), "%m"))],
                    format(Sys.Date(), "%Y"))
cap_base <- paste0("Trailing-12-month share of new registrations · Data: CPCA, data.thaiauto.or.th, KBA, ",
                   "ACEA, ANL, JADA/JAMA · Chart @LeRaffl ", datestamp)

facet_theme <- theme_minimal(base_size = 15) +
  theme(
    plot.background = element_rect(fill = BG, color = BG),
    panel.background = element_rect(fill = BG, color = NA),
    panel.grid.minor = element_blank(),
    panel.grid.major.x = element_blank(),
    panel.grid.major.y = element_line(color = GRID, linewidth = 0.25),
    panel.spacing = unit(1.1, "lines"),
    text = element_text(color = FG, face = "bold"),
    axis.text = element_text(color = FG, face = "bold", size = rel(0.85)),
    strip.text = element_text(color = FG, face = "bold", size = rel(1.15)),
    plot.title.position = "plot",
    plot.title = element_text(color = FG, face = "bold", size = rel(0.95), hjust = 0.5),
    plot.subtitle = element_text(color = FG, size = rel(0.65), hjust = 0.5, lineheight = 1.2),
    plot.margin = margin(15, 25, 10, 15),
    axis.title = element_blank(),
    legend.position = "none")

xsc <- scale_x_continuous(breaks = seq(2015, 2025, 5),
                          labels = c("2015", "2020", "2025"),
                          expand = c(0.02, 0))
ysc <- scale_y_continuous(labels = percent_format(accuracy = 1),
                          breaks = seq(0, 1, 0.25), limits = c(0, 1),
                          expand = expansion(mult = c(0, 0.03)))

save_png <- function(p, name) {
  ggsave(file.path(outdir, name), p, width = 12, height = 6.75, dpi = 200, bg = BG)
  cat("wrote exports/ray_article/", name, "\n", sep = "")
}

# 1) BEV share only
p1 <- ggplot(ttm, aes(x, bev, color = country)) +
  geom_line(linewidth = 1.6) +
  scale_color_manual(values = cols) +
  facet_wrap(~country, nrow = 2, labeller = labeller(country = labels)) +
  xsc + ysc +
  labs(title = "BEV share of new registrations at home — country by country",
       subtitle = cap_base) +
  facet_theme
save_png(p1, "eu_small_multiples_bev.png")

# 2) BEV vs non-plug-in (ICE + full hybrid): the scissors chart
p2 <- ggplot(ttm, aes(x, color = country)) +
  geom_line(aes(y = nonplug), linewidth = 1.3, color = FG, alpha = 0.55) +
  geom_line(aes(y = bev), linewidth = 1.6) +
  scale_color_manual(values = cols) +
  facet_wrap(~country, nrow = 2, labeller = labeller(country = labels)) +
  xsc + ysc +
  labs(title = "The scissors: BEV rising, everything without a plug declining",
       subtitle = paste0("Colour = BEV share · white = non-plug-in share (ICE + full hybrid)\n", cap_base)) +
  facet_theme
save_png(p2, "eu_small_multiples_bev_vs_nonplugin.png")
