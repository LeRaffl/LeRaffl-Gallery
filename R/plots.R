# Plot constructors for the four country charts.
# `meta` is expected to be a list with: country, country_label, flag_img,
# qr_img (optional QR code), entire_caption, social_caption.
# `fit` is the result of fit_history().
# `df` is the full loaded data (with bev_share, ice_share, hybrid_share, year, overall).

suppressPackageStartupMessages({
  library(ggplot2); library(scales); library(grid); library(ggtext); library(viridis)
})

# Palette aligned with the in-browser Fleet plot (index.html ~line 4078) so
# the static PNGs and the live HTML chart read as one visual language.
# Keys for TTM_FUEL_COLORS are the DISPLAY labels emitted by compute_ttm_long
# (R/data.R `display_label`) — not the raw column names.
TTM_FUEL_COLORS <- c(
  BEV      = "#00ff2c",
  PHEV     = "#00bdfe",
  EREV     = "#1976d2",  # darker PHEV-cousin (subset of PHEV in some sources)
  HEV      = "#ffd300",
  MHEV     = "#c4a000",  # darker HEV-cousin
  ICE      = "#692500",  # used when a source gives ICE as one bucket (China etc.)
  Petrol   = "#502900",
  Diesel   = "#914700",
  Gas      = "#8a7253",
  CNG      = "#a89071",
  LPG      = "#bfa890",
  Flexfuel = "#6b4423",
  Ethanol  = "#7a5530",
  Other    = "#3c2f2f"
)
# 3-curve plot uses the gallery-wide builder palette (top-level COLORS in
# index.html ~line 1765): BEV green, PHEV blue, ICE brown.
TRAJ_COLORS <- c(BEV = "#00ff2c", PHEV = "#00bdfe", ICE = "#692500")

# ── Flag / QR overlay helpers ────────────────────────────────────────────────
#
# Flags are placed in the TOP-RIGHT corner of the ggplot panel at a consistent
# physical size regardless of the country's data range.  We use
# annotation_custom() with the default -Inf/Inf panel extent so the grob fills
# the whole panel viewport, then position within that viewport using npc units.
#
# Physical dimensions (inches, at 300 dpi ggsave canvas):
FLAG_W_IN  <- 1.50   # flag width  (3:2 aspect → most national flags)
FLAG_H_IN  <- 1.00   # flag height
FLAG_M_IN  <- 0.18   # margin from top-right corner of panel
QR_S_IN    <- 0.85   # QR code side length (square)
QR_GAP_IN  <- 0.12   # gap between QR code and flag

# Build a rasterGrob positioned at the top-right of its containing viewport.
flag_grob <- function(img) {
  rasterGrob(
    as.raster(img), interpolate = TRUE,
    x      = unit(1, "npc") - unit(FLAG_M_IN, "in"),
    y      = unit(1, "npc") - unit(FLAG_M_IN, "in"),
    width  = unit(FLAG_W_IN, "in"),
    height = unit(FLAG_H_IN, "in"),
    just   = c("right", "top")
  )
}

# QR code sits to the LEFT of the flag, aligned at the top.
qr_grob <- function(img) {
  rasterGrob(
    as.raster(img), interpolate = TRUE,
    x      = unit(1, "npc") - unit(FLAG_M_IN + FLAG_W_IN + QR_GAP_IN, "in"),
    y      = unit(1, "npc") - unit(FLAG_M_IN, "in"),
    width  = unit(QR_S_IN, "in"),
    height = unit(QR_S_IN, "in"),
    just   = c("right", "top")
  )
}

# Add flag (and optionally QR) overlays to a ggplot.
# show_qr = FALSE on charts where the title is too long to leave room.
add_overlays <- function(p, meta, show_qr = TRUE) {
  if (!is.null(meta$flag_img))
    p <- p + annotation_custom(flag_grob(meta$flag_img))
  if (show_qr && !is.null(meta$qr_img))
    p <- p + annotation_custom(qr_grob(meta$qr_img))
  p
}

# 1) TTM stacked bar plot (uses long ttm frame from compute_ttm_long)
plot_ttm_shares <- function(ttm_long, meta) {
  if (is.null(ttm_long) || nrow(ttm_long) == 0) return(NULL)
  p <- ggplot(ttm_long, aes(x = month, y = value, fill = type)) +
    geom_bar(stat = "identity", position = "stack", width = 1) +
    geom_vline(
      data = ttm_long[substr(ttm_long$month, 6, 7) == "01", ] |> unique(),
      aes(xintercept = numeric_month - 0.5), color = "gray40", linetype = "dashed"
    ) +
    geom_hline(yintercept = c(0.25, 0.5, 0.75), color = "gray40", linetype = "dashed") +
    scale_x_discrete(
      breaks = ttm_long$month[substr(ttm_long$month, 6, 7) == "01"],
      labels = function(x) format(as.Date(paste0(x, "-01")), "%b %Y")
    ) +
    scale_y_continuous(labels = scales::percent_format(scale = 100), expand = c(0, 0),
                       sec.axis = sec_axis(~ ., name = "Trailing 12 Months Market Share",
                                           labels = scales::percent_format(scale = 100))) +
    scale_fill_manual(name = "Fuel Type", values = TTM_FUEL_COLORS, drop = FALSE) +
    labs(title = paste0("12-Month Trailing Market Shares by Fuel Type in ", meta$country_label),
         y = "Trailing 12 Months Market Share", x = "Jahre",
         caption = meta$entire_caption) +
    theme_minimal() +
    theme(axis.text.x = element_text(angle = 45, hjust = 1), axis.title.x = element_blank(),
          plot.title = element_text(size = 14, face = "bold"),
          # Legend stays top-left; flag top-right — opposite corners, no overlap.
          legend.position = c(0.05, 0.95), legend.justification = c(0, 1),
          legend.background = element_rect(fill = "white", color = "gray90", size = 0.5),
          legend.key = element_rect(fill = NA, color = NA), legend.key.height = unit(0.2, "cm"),
          plot.caption = element_markdown(hjust = 0))
  # Flag top-right; no QR on TTM (tight header).
  add_overlays(p, meta, show_qr = FALSE)
}

# 2) Time-to-transition curve
plot_timer <- function(fit, meta) {
  ts <- fit$timer_short
  if (is.null(ts) || nrow(ts) == 0) return(NULL)
  current_year <- as.numeric(format(Sys.Date(), "%Y"))
  ymax_top <- ts$BEV_time[length(ts$BEV_time)] * 2

  p <- ggplot(ts, aes(x = year)) +
    geom_line(aes(y = BEV_time, col = "BEV share to rise from 20% to 80% market share"), lwd = 1) +
    geom_line(aes(y = ICE_time, col = "ICE share to fall from 80% to 20% market share"), lwd = 1) +
    scale_x_continuous(
      breaks = seq(fit$verschiebung, fit$extrapol, 1),
      labels = function(x) paste0("Jan ", x + 1)
    ) +
    scale_y_continuous(name = "Number of years expected", limits = c(0, ymax_top)) +
    labs(title = paste0("Time expectation for ", meta$country_label, " transition time using historical data"),
         subtitle = "Each point in time marks what the expectation was at the time",
         caption = meta$social_caption, x = " ") +
    theme_minimal() +
    scale_color_manual(values = c("#33FF3B", "darkblue", "lightblue", "#FF5733"),
                       name = "expected time for") +
    theme(plot.title = element_text(face = "bold", size = rel(1.5)),
          plot.subtitle = element_text(size = rel(1.2), color = "black", lineheight = 0.3),
          axis.text = element_text(size = rel(0.9)),
          axis.title = element_text(size = rel(1.1)),
          legend.position = "bottom", legend.direction = "horizontal",
          legend.title = element_text(size = rel(1.1)), legend.text = element_text(size = rel(1)),
          legend.key.width = unit(0.6, "cm"), legend.key.height = unit(0.6, "cm"),
          plot.caption = element_markdown(hjust = 0, size = rel(0.9)))

  # Flag + QR top-right; legend is at the bottom so no conflict.
  add_overlays(p, meta, show_qr = TRUE)
}

# 3) BEV trajectory (single curve)
plot_bev_trajectory <- function(fit, meta) {
  germany <- fit$extrap; new_A <- fit$new_A; default_size <- 2

  p <- ggplot(germany, aes(x = x, y = BEV, color = Type)) +
    geom_ribbon(aes(ymin = BEV_lower, ymax = BEV_upper), fill = "grey", alpha = 0.5, color = NA) +
    geom_line(lwd = 1) + ylim(0, 1.1) +
    geom_point(data = new_A, aes(x = x, y = y, color = Quarter),
               size = default_size + (new_A$overall - mean(new_A$overall)) / sd(new_A$overall)) +
    scale_x_continuous(breaks = seq(2010, fit$extrapol, ifelse(fit$extrapol > 2045, 4, 2)),
                       labels = function(x) paste0("Jan ", x + 1),
                       limits = c(2010, min(fit$extrapol, 2045))) +
    scale_y_continuous(breaks = seq(0, 1, 0.1), labels = unit_format(unit = "%", scale = 1e2)) +
    labs(title = paste0("BEV share in new registrations in ", meta$country_label, " - an Extrapolation"),
         subtitle = paste0("expected time for BEV to rise from 20% to 80%: ",
                           floor(fit$time_20_to_80), " years ",
                           round(12 * (fit$time_20_to_80 - floor(fit$time_20_to_80)), 0), " months"),
         caption = meta$entire_caption, x = " ", y = "BEV share") +
    theme_minimal() +
    theme(
      # Legend moved to bottom-right; flag + QR occupy the top-right corner.
      legend.position = c(0.97, 0.05), legend.justification = c("right", "bottom"),
      legend.background = element_rect(fill = "gray99"),
      plot.title = element_text(face = "bold", size = rel(1.5)),
      plot.subtitle = element_text(size = rel(1.2)),
      legend.text = element_text(size = rel(1)),
      axis.text = element_text(size = rel(0.9)),
      plot.caption = element_markdown(hjust = 0)
    ) +
    scale_color_manual(values = c("#FF5733","#FFC300","#33FF3B","#33A1FF","#B633FF","#FF33E9"), name = "Color")

  p <- p + annotate("text", x = 2010, y = 1, label = "New Registration estimates in",
                    size = rel(6), hjust = 0, vjust = 1, col = "red")
  counter <- 0
  repeat {
    row <- subset(germany, germany$x == 2024 + counter & germany$Type == "New Registrations")
    if (nrow(row) == 0) break
    if (!(round(row$BEV * 100, 1) < 100 & 1 - 0.05 * (counter + 1) > 0.1)) break
    p <- p + annotate("text", x = 2010 + 0.5, y = 1 - 0.05 * (counter + 1),
                      label = paste0("Jan ", 2025 + counter, ": ", round(row$BEV * 100, 1), "%"),
                      size = rel(5), hjust = 0, vjust = 1, col = "red")
    counter <- counter + 1
  }

  # Flag + QR top-right.
  add_overlays(p, meta, show_qr = TRUE)
}

# 4) ICE / BEV / PHEV combined trajectory
plot_ice_bev_phev <- function(fit, df, meta) {
  germany <- fit$extrap; default_size <- 2

  p <- ggplot(germany, aes(x = x, y = BEV, color = Type)) +
    geom_ribbon(aes(ymin = BEV_lower, ymax = BEV_upper), fill = TRAJ_COLORS[["BEV"]], alpha = 0.35, color = NA) +
    geom_line(aes(y = BEV, color = "BEV", shape = "BEV"), lwd = 1) +
    geom_point(data = fit$BEV, aes(x = x, y = y, color = "BEV", shape = "BEV"),
               size = default_size + (fit$BEV$overall - mean(fit$BEV$overall)) / sd(fit$BEV$overall)) +
    geom_ribbon(aes(ymin = ICE_lower, ymax = ICE_upper), fill = TRAJ_COLORS[["ICE"]], alpha = 0.35, color = NA) +
    geom_line(aes(y = ICE, color = "ICE", shape = "ICE"), lwd = 1) +
    geom_point(data = fit$ICE, aes(x = x, y = y, color = "ICE", shape = "ICE"),
               size = default_size + (fit$ICE$overall - mean(fit$ICE$overall)) / sd(fit$ICE$overall)) +
    geom_ribbon(aes(ymin = Hybrid_lower, ymax = Hybrid_upper), fill = TRAJ_COLORS[["PHEV"]], alpha = 0.35, color = NA) +
    geom_line(aes(y = Hybrid, color = "PHEV", shape = "PHEV"), lwd = 1) +
    geom_point(data = df, aes(x = year, y = hybrid_share, color = "PHEV", shape = "PHEV"),
               size = default_size + (fit$Hybrid$overall - mean(fit$Hybrid$overall)) / sd(fit$Hybrid$overall)) +
    ylim(0, 1.1) +
    scale_x_continuous(breaks = seq(2006, fit$extrapol, ifelse(fit$extrapol > 2045, 4, 2)),
                       labels = function(x) paste0("Jan ", x + 1),
                       limits = c(2010, min(fit$extrapol, 2045))) +
    scale_y_continuous(breaks = seq(0, 1, 0.1), labels = unit_format(unit = "%", scale = 1e2)) +
    labs(title = paste0("BEV / ICE / PHEV share of new registrations in ", meta$country_label, " - an Extrapolation"),
         subtitle = paste0("expected time for ICE to drop from 80% to 20%: ",
                           floor(fit$time_80_to_20), " years ",
                           round(12 * (fit$time_80_to_20 - floor(fit$time_80_to_20)), 0), " months"),
         caption = meta$entire_caption, x = " ", y = "New Registration Share") +
    theme_minimal() +
    theme(axis.title = element_text(size = rel(1.2)), axis.text = element_text(size = rel(0.9)),
          plot.title = element_text(face = "bold", size = rel(1.5)),
          plot.subtitle = element_text(size = rel(1.2)),
          # Legend moved to bottom-right; flag now occupies the top-right.
          # No QR on this chart — long title leaves too little room.
          legend.position = c(0.97, 0.05), legend.justification = c("right", "bottom"),
          legend.background = element_rect(fill = "gray99"),
          legend.title = element_text(size = rel(1)), legend.text = element_text(size = rel(0.9)),
          plot.caption = element_markdown(hjust = 0, size = rel(0.9))) +
    scale_color_manual(name = "Legend", breaks = c("ICE","BEV","PHEV"),
                       values = TRAJ_COLORS) +
    scale_shape_manual(name = "Legend", breaks = c("ICE","BEV","PHEV"),
                       values = c("ICE"=15,"BEV"=16,"PHEV"=23))

  p <- p + annotate("text", x = 2010, y = 0.9, label = "New ICE in",
                    size = rel(6), hjust = 0, vjust = 1, col = TRAJ_COLORS[["ICE"]])
  counter <- 0
  repeat {
    cond_row  <- subset(germany, germany$x == 2024 + counter - 1 & germany$Type == "New Registrations")
    label_row <- subset(germany, germany$x == 2024 + counter     & germany$Type == "New Registrations")
    if (nrow(cond_row) == 0 || nrow(label_row) == 0) break
    if (!(5 < round(cond_row$ICE * 100, 1) & 1 - 0.05 * (counter + 1) > 0.1)) break
    p <- p + annotate("text", x = 2010 + 0.5, y = 0.85 - counter * 0.05,
                      label = paste0("Jan ", 2024 + counter + 1, ": ", round(label_row$ICE * 100, 1), "%"),
                      size = rel(5), hjust = 0, vjust = 1, col = TRAJ_COLORS[["ICE"]])
    counter <- counter + 1
  }

  # Flag top-right; no QR (long title).
  add_overlays(p, meta, show_qr = FALSE)
}
