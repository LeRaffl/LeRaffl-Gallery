# Single-glance figure for the short (Electrive) piece — Peter Newman asked for
# a version of the message that reads immediately rather than a multi-line
# trajectory chart. One ranked bar per country: observed BEV share of new
# registrations. France included (Peter's second note).
#
# Period = the latest month all series cover, matching the monthly figures the
# article quotes. A year-to-date average would put France marginally ahead of
# Thailand (28.2% vs 27.9%) and contradict the text, because it averages in
# Thailand's slower start; the single month reflects where each market is now.
#
# Run from repo root:  Rscript scripts/eu_bev_share_bars.R

suppressPackageStartupMessages({ library(ggplot2); library(scales) })

repo <- normalizePath(".")
outdir <- file.path(repo, "exports", "ray_article")

countries <- c("China", "France", "Thailand", "Germany", "South Korea", "USA", "Japan")
labels <- c(China = "China", France = "France", Thailand = "Thailand", Germany = "Germany",
            `South Korea` = "South Korea", USA = "US", Japan = "Japan")
cols <- c(China = "#FF0000", France = "#2E6FE8", Thailand = "#FF8C00", Germany = "#FFD300",
          `South Korea` = "#A427E8", USA = "#29ABE2", Japan = "#9E1B1B")

cur_year <- as.integer(format(Sys.Date(), "%Y"))

# Latest month common to all seven series, so the bars compare like with like.
raw <- lapply(countries, function(c) {
  d <- read.csv(file.path(repo, "data", paste0(c, ".csv")), stringsAsFactors = FALSE)
  d <- d[d$variant == "Whole" & substr(d$period, 1, 4) == as.character(cur_year), ]
  num <- function(x) { v <- suppressWarnings(as.numeric(x)); v[is.na(v)] <- 0; v }
  data.frame(country = c, period = substr(d$period, 1, 7), bev = num(d$BEV), tot = num(d$TOTAL))
})
names(raw) <- countries
cutoff <- min(sapply(raw, function(d) max(d$period)))
cat("common latest month:", cutoff, "\n")

df <- do.call(rbind, lapply(raw, function(d) {
  d <- d[d$period == cutoff, ]
  data.frame(country = d$country[1], share = sum(d$bev) / sum(d$tot))
}))
df$country <- factor(df$country, levels = df$country[order(df$share)])
print(df[order(-df$share), ], row.names = FALSE)

BG <- "#3B3B3B"; FG <- "#EDEBE0"; GRID <- "#FFFFFF"
mon <- month.name[as.integer(substr(cutoff, 6, 7))]
datestamp <- paste0(format(Sys.Date(), "%d"), month.abb[as.integer(format(Sys.Date(), "%m"))],
                    format(Sys.Date(), "%Y"))

p <- ggplot(df, aes(country, share, fill = country)) +
  geom_col(width = 0.72) +
  geom_text(aes(label = percent(share, accuracy = 0.1)), hjust = -0.15,
            color = FG, fontface = "bold", size = 6) +
  scale_fill_manual(values = cols) +
  scale_x_discrete(labels = labels) +
  scale_y_continuous(labels = percent_format(accuracy = 1), limits = c(0, 0.5),
                     breaks = seq(0, 0.5, 0.1), expand = expansion(mult = c(0, 0.02))) +
  coord_flip(clip = "off") +
  labs(title = "Who electrifies at home: BEV share of new registrations",
       subtitle = paste0(mon, " ", cur_year, "  ·  ",
                         "Data: CPCA, ACEA, data.thaiauto.or.th, KBA, molit.go.kr, ANL, JADA/JAMA",
                         "  ·  Chart @LeRaffl ", datestamp)) +
  theme_minimal(base_size = 17) +
  theme(
    plot.background = element_rect(fill = BG, color = BG),
    panel.background = element_rect(fill = BG, color = NA),
    panel.grid.minor = element_blank(),
    panel.grid.major.y = element_blank(),
    panel.grid.major.x = element_line(color = GRID, linewidth = 0.25),
    text = element_text(color = FG, face = "bold"),
    axis.text = element_text(color = FG, face = "bold"),
    axis.text.y = element_text(size = rel(1.15)),
    plot.title.position = "plot",
    plot.title = element_text(color = FG, face = "bold", size = rel(0.95), hjust = 0.5),
    plot.subtitle = element_text(color = FG, size = rel(0.62), hjust = 0.5, lineheight = 1.2),
    plot.margin = margin(15, 40, 10, 15),
    axis.title = element_blank(),
    legend.position = "none")

ggsave(file.path(outdir, "bev_share_bars_latest_month.png"), p,
       width = 12, height = 6.75, dpi = 200, bg = BG)
cat("wrote exports/ray_article/bev_share_bars_latest_month.png\n")
