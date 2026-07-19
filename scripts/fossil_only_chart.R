# "No domestic car industry" fossil-exit chart for Ray Wills' SE Asia/Oceania
# article. Plots the pure petrol/diesel share of new registrations over time for
# markets without a large domestic car industry, in Ray's dark chart style.
#
# Fossil-only share per year = sum(PETROL + DIESEL) / sum(TOTAL). Hybrids (HEV),
# PHEV and BEV are deliberately excluded — this is the "pure ICE" line. Where a
# row lacks the petrol/diesel split (early Australian yearly rows), fossil is the
# residual TOTAL - BEV - PHEV - HEV - OTHERS, which equals petrol+diesel.
#
# Each source year uses a single time_interval (verified — no monthly/yearly
# overlap), so summing all rows within a calendar year never double-counts.
#
# Run from repo root:  Rscript scripts/fossil_only_chart.R

suppressPackageStartupMessages({ library(ggplot2); library(scales) })

repo <- normalizePath(".")
outdir <- file.path(repo, "exports", "ray_article")
dir.create(outdir, recursive = TRUE, showWarnings = FALSE)

# Vietnam has no data in the gallery; Malaysia stands in for the SE Asia slot.
countries <- c(Singapore = "Singapore", Indonesia = "Indonesia",
               Australia = "Australia", Malaysia = "Malaysia")
cols <- c(Singapore = "#29ABE2", Indonesia = "#FF0000",
          Australia = "#FFD300", Malaysia = "#A427E8")

num <- function(x) { x <- suppressWarnings(as.numeric(x)); ifelse(is.na(x), 0, x) }

# Annual fossil-only share for one country CSV.
fossil_by_year <- function(name, file) {
  d <- read.csv(file.path(repo, "data", file), stringsAsFactors = FALSE,
                check.names = FALSE)
  d <- d[d$variant == "Whole", ]
  d$yr <- as.integer(substr(d$period, 1, 4))
  petrol <- num(d$PETROL); diesel <- num(d$DIESEL); total <- num(d$TOTAL)
  # Residual fallback where petrol/diesel are both blank.
  blank <- is.na(suppressWarnings(as.numeric(d$PETROL))) &
           is.na(suppressWarnings(as.numeric(d$DIESEL)))
  resid <- total - num(d$BEV) - num(d$PHEV) - num(d$HEV) - num(d$OTHERS)
  fossil <- ifelse(blank, pmax(resid, 0), petrol + diesel)
  agg <- aggregate(cbind(fossil, total) ~ yr, data.frame(yr = d$yr, fossil, total), sum)
  data.frame(country = name, cal = agg$yr, share = agg$fossil / agg$total)
}

df <- do.call(rbind, Map(fossil_by_year, names(countries), paste0(countries, ".csv")))
df <- df[df$cal >= 2015, ]

# Current calendar year is only year-to-date (partial); flag it in the note.
cur_year <- as.integer(format(Sys.Date(), "%Y"))

# ---- Ray-style dark theme (mirrors scripts/ray_domestic_bev_chart.R) ----
caption_txt <- paste0("Data: lta.gov.sg, gaikindo.io, VFACTS, data.gov.my",
                      "  ·  Pure petrol + diesel share · Chart @LeRaffl ",
                      paste0(format(Sys.Date(), "%d"),
                             month.abb[as.integer(format(Sys.Date(), "%m"))],
                             format(Sys.Date(), "%Y")))
note <- paste0(cur_year, " = year-to-date")

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
    plot.margin = margin(15, 150, 10, 15),
    axis.title = element_blank(),
    legend.position = "none"
  )

# Right-edge labels, pushed apart if they collide (order-preserving).
spread_labels <- function(y, gap) {
  o <- order(y); ys <- y[o]
  for (i in 2:length(ys)) if (ys[i] - ys[i - 1] < gap) ys[i] <- ys[i - 1] + gap
  y[o] <- ys; y
}
ends <- do.call(rbind, lapply(split(df, df$country),
                              function(d) d[which.max(d$cal), ]))
ends$y_lab <- spread_labels(ends$share, gap = 0.045 * max(df$share))

x_max <- max(df$cal) + 1.2

p <- ggplot(df, aes(cal, share, color = country)) +
  geom_line(linewidth = 2) +
  geom_point(size = 2.2) +
  geom_text(data = ends, aes(y = y_lab, label = country),
            hjust = 0, nudge_x = 0.15, size = 6, fontface = "bold") +
  scale_color_manual(values = cols) +
  scale_y_continuous(labels = percent_format(accuracy = 1),
                     breaks = seq(0, 1, 0.2), limits = c(0, NA),
                     expand = expansion(mult = c(0, 0.05))) +
  scale_x_continuous(breaks = seq(2015, cur_year, 2),
                     limits = c(2015, x_max), expand = c(0.01, 0)) +
  coord_cartesian(clip = "off") +
  labs(title = "Fossil-only (petrol + diesel) share of new registrations",
       subtitle = paste0(caption_txt, "\n", note)) +
  ray_theme

ggsave(file.path(outdir, "fossil_only_share.png"), p,
       width = 12, height = 6.75, dpi = 200, bg = BG)
cat("wrote", file.path("exports/ray_article", "fossil_only_share.png"), "\n")

# Print the latest fossil-only share per country for a quick sanity check.
for (nm in names(countries)) {
  e <- ends[ends$country == nm, ]
  cat(sprintf("%-10s %d: %.1f%% fossil-only\n", nm, e$cal, 100 * e$share))
}
