# Domestic BEV share vs BEV export share — scatter + trajectory for Ray Wills'
# article. Mirrors the thesis that countries electrifying at home (X) also lead
# BEV exports (Y). One dot per exporting country; the trajectory version joins
# each country's 2021-> latest path.
#
#   X: observed domestic BEV share of new registrations (raw country CSVs)
#   Y: BEV export share = value(HS 870380)/value(HS 8703), UN Comtrade
#      (cached in exports/ray_article/comtrade_bev_export_shares.csv — refresh
#       with scripts/fetch_export_shares.R)
#   Bubble: OICA 2024 vehicle production  OR  World Bank 2024 GDP/capita
#           (fixed per country across all years, so size = country scale, not a
#            time-varying value — the eye tracks position, not pulsing bubbles)
#
# Comtrade coverage: 2021-2024 complete for all six; 2025 filed by Germany,
# Japan, South Korea and the US but not yet China or Thailand (starred).
#
# Run from repo root:  Rscript scripts/export_scatter_chart.R

suppressPackageStartupMessages({ library(ggplot2); library(scales); library(ggrepel) })

repo <- normalizePath(".")
outdir <- file.path(repo, "exports", "ray_article")
cache <- read.csv(file.path(outdir, "comtrade_bev_export_shares.csv"),
                  stringsAsFactors = FALSE)

meta <- data.frame(
  country = c("China", "Germany", "Japan", "South Korea", "USA", "Thailand"),
  label   = c("China", "Germany", "Japan", "South Korea", "US", "Thailand"),
  production = c(31281592, 4069222, 8234681, 4127252, 10562188, 1468997),  # OICA 2024
  gdp_pc  = c(13293.116, 56103.732, 33797.101, 36238.640, 86169.664, 7386.636), # WB 2024
  stringsAsFactors = FALSE)
cols <- c(China = "#FF0000", Germany = "#FFD300", Japan = "#9E1B1B",
          `South Korea` = "#A427E8", USA = "#29ABE2", Thailand = "#FF8C00")

# --- X: observed domestic BEV share (BEV/TOTAL) for a country-year ------------
csvs <- setNames(lapply(meta$country, function(c)
  read.csv(file.path(repo, "data", paste0(c, ".csv")),
           stringsAsFactors = FALSE, check.names = FALSE)), meta$country)
domestic_share <- function(country, year) {
  d <- csvs[[country]]
  d <- d[d$variant == "Whole" & substr(d$period, 1, 4) == as.character(year), ]
  sum(as.numeric(d$BEV), na.rm = TRUE) / sum(as.numeric(d$TOTAL), na.rm = TRUE)
}

# --- assemble one long table: country-year with X, Y and fixed bubble sizes ---
df <- merge(cache[, c("year", "country", "ev_export_share")], meta, by = "country")
df$domestic_bev <- mapply(domestic_share, df$country, df$year)
df <- df[!is.na(df$ev_export_share), ]           # drop unfiled cells (China/TH 2025)
df <- df[order(df$country, df$year), ]

# --- shared Ray-style dark theme ---------------------------------------------
BG <- "#3B3B3B"; FG <- "#EDEBE0"; GRID <- "#FFFFFF"
lim <- c(0, 0.48)   # equal axes so the y = x parity line is a true 45 degrees
datestamp <- paste0(format(Sys.Date(), "%d"),
                    month.abb[as.integer(format(Sys.Date(), "%m"))],
                    format(Sys.Date(), "%Y"))
ray_theme <- theme_minimal(base_size = 16) +
  theme(
    plot.background = element_rect(fill = BG, color = BG),
    panel.background = element_rect(fill = BG, color = NA),
    panel.grid.minor = element_blank(),
    panel.grid.major = element_line(color = GRID, linewidth = 0.25),
    text = element_text(color = FG, face = "bold"),
    axis.text = element_text(color = FG, face = "bold", size = rel(1.05)),
    axis.title = element_text(color = FG, face = "bold", size = rel(0.9)),
    plot.title.position = "plot",
    plot.title = element_text(color = FG, face = "bold", size = rel(0.95), hjust = 0.5),
    plot.subtitle = element_text(color = FG, size = rel(0.6), hjust = 0.5, lineheight = 1.2),
    plot.margin = margin(15, 30, 10, 15),
    legend.position = "none")

parity_layer <- list(
  geom_abline(slope = 1, intercept = 0, linetype = "dashed",
              color = FG, linewidth = 0.4, alpha = 0.6),
  # Label parked in the empty lower-right triangle (below the line), horizontal,
  # so it never crosses the markers.
  annotate("text", x = 0.475, y = 0.045, hjust = 1,
           label = "dashed line = parity (export mix = home mix)",
           color = FG, alpha = 0.65, size = 3.4, fontface = "italic"))

# Repel labels clear of the (sometimes large) bubbles, with a thin leader line.
repel_labels <- function(data = NULL, mapping = aes(label = label)) {
  geom_text_repel(data = data, mapping = mapping, color = FG, fontface = "bold",
                  size = 5, seed = 1, box.padding = 1.0, point.padding = 0.9,
                  min.segment.length = 0, segment.color = FG, segment.alpha = 0.5,
                  max.overlaps = Inf)
}

bubble_variants <- list(
  list(var = "production", title = "vehicle production (OICA 2024)",
       labs = label_number(scale_cut = cut_short_scale()), max = 20, suffix = "production"),
  list(var = "gdp_pc", title = "GDP per capita (World Bank 2024)",
       labs = label_dollar(scale_cut = cut_short_scale()), max = 17, suffix = "gdp_per_capita"))

save_png <- function(p, name) {
  ggsave(file.path(outdir, name), p, width = 12, height = 7.5, dpi = 200, bg = BG)
  cat("wrote exports/ray_article/", name, "\n", sep = "")
}
axis_x <- "Domestic BEV share of new registrations"
axis_y <- "BEV share of passenger-car exports"
cap <- paste0("X: observed domestic BEV share (CPCA/JADA/KBA/ANL/thaiauto) · ",
              "Y: BEV share of passenger-car exports (UN Comtrade HS 870380/8703) · @LeRaffl ", datestamp)
# Honest-scope footnote: Y covers passenger cars only (pickups/LCVs are HS 8704
# and excluded); US and Thailand home-market shares include light trucks/pickups.
scope_note <- paste0("Y = passenger cars only, pickups/LCVs (HS 8704) excluded · ",
                     "US & Thailand domestic shares incl. pickups/light trucks")

# --- 1) one scatter per year (2021-2024, complete cross-sections) ------------
for (yr in 2021:2024) {
  dy <- df[df$year == yr, ]
  for (b in bubble_variants) {
    p <- ggplot(dy, aes(domestic_bev, ev_export_share, color = country)) +
      parity_layer +
      geom_point(aes(size = .data[[b$var]]), alpha = 0.85) +
      repel_labels() +
      scale_color_manual(values = cols) +
      scale_size_area(max_size = b$max, guide = "none") +
      scale_x_continuous(labels = percent_format(accuracy = 1), limits = lim) +
      scale_y_continuous(labels = percent_format(accuracy = 1), limits = lim) +
      coord_fixed() +
      labs(title = paste0("Electrify at home, export EVs — ", yr),
           subtitle = paste0(cap, "\nbubble size = ", b$title, "  ·  ", scope_note),
           x = paste0(axis_x, " (", yr, ")"), y = paste0(axis_y, " (", yr, ")")) +
      ray_theme
    save_png(p, sprintf("export_scatter_%d_%s.png", yr, b$suffix))
  }
}

# --- 2) trajectory: each country's 2021 -> latest path with an arrowhead ------
ends <- do.call(rbind, lapply(split(df, df$country),
                              function(d) d[which.max(d$year), ]))
# star countries whose export path stops before 2025 (not yet filed to Comtrade)
ends$lab <- ifelse(ends$year < 2025, paste0(ends$label, " *"), ends$label)
starred <- paste(sort(ends$label[ends$year < 2025]), collapse = ", ")

for (b in bubble_variants) {
  p <- ggplot(df, aes(domestic_bev, ev_export_share, color = country)) +
    parity_layer +
    geom_point(data = ends, aes(size = .data[[b$var]]), alpha = 0.85) +
    geom_point(size = 1.6, alpha = 0.7) +
    geom_path(aes(group = country), linewidth = 1.1, alpha = 0.9,
              arrow = arrow(type = "closed", length = unit(0.28, "cm"))) +
    repel_labels(data = ends, mapping = aes(label = lab)) +
    scale_color_manual(values = cols) +
    scale_size_area(max_size = b$max, guide = "none") +
    scale_x_continuous(labels = percent_format(accuracy = 1), limits = lim) +
    scale_y_continuous(labels = percent_format(accuracy = 1), limits = lim) +
    coord_fixed() +
    labs(title = "Electrify at home, export EVs — trajectories 2021→latest",
         subtitle = paste0(cap, "\nbubble size = ", b$title,
                           "  ·  * export path ends 2024 (", starred,
                           " not yet filed for 2025)\n", scope_note),
         x = axis_x, y = axis_y) +
    ray_theme
  save_png(p, sprintf("export_trajectory_%s.png", b$suffix))
}

cat("\n--- export share by country-year (%) ---\n")
tab <- reshape(df[, c("country", "year", "ev_export_share")],
               idvar = "country", timevar = "year", direction = "wide")
print(tab, row.names = FALSE)
