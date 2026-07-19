# Domestic BEV share vs BEV export share — scatter/bubble for Ray Wills' article.
# Mirrors his thesis: countries that electrify at home (X) also lead BEV exports
# (Y). One dot per exporting country, sized two ways (vehicle production / GDP
# per capita) so the article can pick whichever framing fits.
#
#   X: fitted domestic BEV share of new registrations (from params.csv)
#   Y: BEV export share = value(HS 870380) / value(HS 8703), UN Comtrade 2024
#   Bubble: OICA 2024 total vehicle production  OR  World Bank GDP/capita 2024
#
# Comtrade note: force the single aggregate row (partner2Code/motCode/customsCode)
# or the API returns per-mode sub-rows that double-count on summation.
#
# Run from repo root:  Rscript scripts/export_scatter_chart.R

suppressPackageStartupMessages({ library(ggplot2); library(scales); library(jsonlite) })

repo <- normalizePath(".")
outdir <- file.path(repo, "exports", "ray_article")
dir.create(outdir, recursive = TRUE, showWarnings = FALSE)
YEAR <- 2024

# country -> Comtrade reporter code, World Bank ISO3, OICA 2024 total production
meta <- data.frame(
  country = c("China", "Germany", "Japan", "South Korea", "USA", "Thailand"),
  label   = c("China", "Germany", "Japan", "South Korea", "US", "Thailand"),
  reporter = c(156, 276, 392, 410, 842, 764),
  iso3    = c("CHN", "DEU", "JPN", "KOR", "USA", "THA"),
  production = c(31281592, 4069222, 8234681, 4127252, 10562188, 1468997),  # OICA 2024
  stringsAsFactors = FALSE
)
cols <- c(China = "#FF0000", Germany = "#FFD300", Japan = "#9E1B1B",
          `South Korea` = "#A427E8", USA = "#29ABE2", Thailand = "#FF8C00")

# --- UN Comtrade: export value (USD) to World for one reporter/commodity ------
comtrade_value <- function(reporter, cmd) {
  u <- sprintf(paste0("https://comtradeapi.un.org/public/v1/preview/C/A/HS",
                      "?reporterCode=%d&period=%d&cmdCode=%s&flowCode=X",
                      "&partnerCode=0&partner2Code=0&motCode=0&customsCode=C00"),
               reporter, YEAR, cmd)
  # The public preview endpoint rate-limits bursts (429); retry with backoff.
  for (attempt in 1:5) {
    d <- tryCatch(fromJSON(u)$data, error = function(e) NULL)
    if (!is.null(d) && length(d) > 0) { Sys.sleep(2); return(as.numeric(d$primaryValue[1])) }
    Sys.sleep(3 * attempt)
  }
  NA_real_
}

meta$bev_exp <- mapply(comtrade_value, meta$reporter, "870380")
meta$car_exp <- mapply(comtrade_value, meta$reporter, "8703")
meta$ev_export_share <- meta$bev_exp / meta$car_exp

# --- World Bank: GDP per capita (current US$), NY.GDP.PCAP.CD -----------------
wb_gdp_pc <- function(iso3) {
  u <- sprintf(paste0("https://api.worldbank.org/v2/country/%s/indicator/",
                      "NY.GDP.PCAP.CD?date=%d&format=json&per_page=5"), iso3, YEAR)
  j <- tryCatch(fromJSON(u, simplifyVector = FALSE), error = function(e) NULL)
  if (is.null(j) || length(j) < 2 || length(j[[2]]) == 0) return(NA_real_)
  as.numeric(j[[2]][[1]]$value)
}
meta$gdp_pc <- vapply(meta$iso3, wb_gdp_pc, numeric(1))

# --- X-axis: fitted domestic BEV share at each country's latest data month ----
params <- read.csv(file.path(repo, "params.csv"), stringsAsFactors = FALSE)
p <- subset(params, country %in% meta$country & variant == "Whole")
bev_curve <- function(v1, v2, t0, x) 1 - exp(v1 * (x - (t0 - 1))^v2)
# Evaluate the fitted domestic share at mid-2024 so it matches the full-year
# 2024 export data on the Y-axis (calendar year Y corresponds to internal x=Y-1).
x_2024 <- (2024 + 0.5) - 1
p$domestic_bev <- bev_curve(p$v1, p$v2, p$t0, x_2024)
df <- merge(meta, p[, c("country", "domestic_bev")], by = "country")

cat("\n--- assembled data (", YEAR, ") ---\n", sep = "")
print(df[, c("label", "domestic_bev", "ev_export_share", "production", "gdp_pc")],
      row.names = FALSE)

# --- Ray-style dark theme ----------------------------------------------------
BG <- "#3B3B3B"; FG <- "#EDEBE0"; GRID <- "#FFFFFF"
caption_txt <- paste0("X: fitted domestic BEV share (CPCA/JADA/KBA/ANL/thaiauto) · ",
                      "Y: BEV share of car exports (UN Comtrade HS 870380/8703, ", YEAR, ")",
                      "  ·  Chart @LeRaffl ",
                      format(Sys.Date(), "%d"), month.abb[as.integer(format(Sys.Date(), "%m"))],
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
    legend.position = "none"
  )

lim <- c(0, 0.45)   # equal axes so the y = x parity line is a true 45 degrees
scatter <- function(size_var, size_title, size_labels, bubble_max) {
  ggplot(df, aes(domestic_bev, ev_export_share, color = country)) +
    # Parity reference: points on it export the same BEV mix they register at
    # home; below = exports dirtier than home (Thailand), above = cleaner (Japan).
    geom_abline(slope = 1, intercept = 0, linetype = "dashed",
                color = FG, linewidth = 0.4, alpha = 0.6) +
    annotate("text", x = 0.155, y = 0.155, label = "parity: export mix = home mix",
             color = FG, alpha = 0.7, size = 3.6, fontface = "italic",
             angle = 45, hjust = 1, vjust = -0.4) +
    geom_point(aes(size = .data[[size_var]]), alpha = 0.85) +
    geom_text(aes(label = label), color = FG, fontface = "bold", size = 5,
              vjust = -0.9, hjust = 0.5) +
    scale_color_manual(values = cols) +
    scale_size_area(max_size = bubble_max, labels = size_labels,
                    name = size_title, guide = "none") +
    scale_x_continuous(labels = percent_format(accuracy = 1), limits = lim) +
    scale_y_continuous(labels = percent_format(accuracy = 1), limits = lim) +
    coord_fixed() +
    labs(title = "Electrify at home, export EVs: domestic vs export BEV share",
         subtitle = paste0(caption_txt, "\nbubble size = ", size_title),
         x = "Domestic BEV share of new registrations (2024)",
         y = "BEV share of car exports (2024)") +
    ray_theme
}

p_prod <- scatter("production", "vehicle production (OICA 2024)",
                  label_number(scale_cut = cut_short_scale()), 28)
ggsave(file.path(outdir, "export_scatter_production.png"), p_prod,
       width = 12, height = 7.5, dpi = 200, bg = BG)
cat("wrote exports/ray_article/export_scatter_production.png\n")

p_gdp <- scatter("gdp_pc", "GDP per capita (World Bank 2024)",
                 label_dollar(scale_cut = cut_short_scale()), 24)
ggsave(file.path(outdir, "export_scatter_gdp_per_capita.png"), p_gdp,
       width = 12, height = 7.5, dpi = 200, bg = BG)
cat("wrote exports/ray_article/export_scatter_gdp_per_capita.png\n")
