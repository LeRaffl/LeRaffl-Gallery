# R/lib/plots.R
# All ggplots from the per-country pipeline, parameterized for country
# label and schema flags. Visual styling is preserved from the originals
# verbatim — colors, theme calls, sizes, breaks, labels.

suppressPackageStartupMessages({
  library(ggplot2)
  library(ggtext)
  library(scales)
  library(dplyr)
  library(tidyr)
  library(viridis)
  library(grid)
  library(png)
})

scaled_point_size <- function(overall, default_size = 2, min_size = 0.4) {
  values <- as.numeric(overall)
  spread <- sd(values, na.rm = TRUE)
  if (!is.finite(spread) || spread == 0) {
    return(rep(default_size, length(values)))
  }

  sizes <- default_size + (values - mean(values, na.rm = TRUE)) / spread
  sizes[!is.finite(sizes)] <- default_size
  pmax(min_size, sizes)
}

# Build the trailing-12-months stacked bar plot. The column composition
# adapts to the schema flags so countries with combined HYBRIDS (Türkiye),
# China-style EREV, single-ICE columns, etc. all render correctly.
#
# Time axis: prefers monthly data; falls back to quarterly when the sheet
# has no monthly rows (Canada, Denmark's default market, Georgia, Malta etc.).
build_ttm_plot <- function(data, flags, country_label, caption) {
  data_monthly <- subset(data, !is.na(data$time_interval) & data$time_interval == "monthly")
  step_by <- "month"
  if (nrow(data_monthly) == 0) {
    data_monthly <- subset(data, !is.na(data$time_interval) & data$time_interval == "quarterly")
    step_by <- "quarter"
  }
  if (nrow(data_monthly) == 0)
    stop("No monthly or quarterly rows in this sheet — cannot build TTM plot.")

  # Build layers using the same logic as below, but first we need to identify
  # which TTM columns participate so we can compute per-row completeness.
  # ICE takes priority over PETROL+DIESEL — never stack them together.
  use_ice     <- flags$has_ice_ttm
  use_petrol  <- flags$has_petrol_ttm && !use_ice
  use_diesel  <- flags$has_diesel_ttm && !use_ice
  use_hybrid  <- flags$has_hybrids_combined && flags$has_hybrid_ttm
  use_hev     <- flags$has_hev_ttm  && !use_hybrid
  use_phev    <- flags$has_phev_ttm && !use_hybrid
  use_erev    <- flags$has_erev_ttm && !use_hybrid

  active_ttm <- c("BEV TTM")
  if (flags$has_other_ttm) active_ttm <- c(active_ttm, "Other TTM")
  if (use_ice)    active_ttm <- c(active_ttm, "ICE TTM")
  if (use_petrol) active_ttm <- c(active_ttm, "Petrol TTM")
  if (use_diesel) active_ttm <- c(active_ttm, "Diesel TTM")
  if (use_hybrid) active_ttm <- c(active_ttm, "Hybrid TTM")
  if (use_hev)    active_ttm <- c(active_ttm, "HEV TTM")
  if (use_phev)   active_ttm <- c(active_ttm, "PHEV TTM")
  if (use_erev)   active_ttm <- c(active_ttm, "EREV TTM")
  present_ttm <- intersect(active_ttm, names(data_monthly))

  use_residual_ice <- FALSE

  # Keep only rows where all active TTM categories sum to ≥ 90% of TOTAL.
  # This replaces the old year-offset heuristic: it naturally skips the
  # 11-month warm-up period for rolling TTM AND skips early months where
  # a later-arriving category (e.g. PETROL for Portugal pre-2018) makes
  # the stack incomplete.
  if (length(present_ttm) > 0) {
    ttm_values <- data_monthly[, present_ttm, drop = FALSE]
    ttm_sums <- rowSums(ttm_values, na.rm = TRUE)
    has_ttm_data <- rowSums(!is.na(ttm_values)) > 0

    # Some non-ACEA markets (currently Brazil and Georgia) have a TOTAL
    # series plus partial fuel splits, but no explicit ICE column. If the
    # active stack never reaches 90%, treat the missing share as residual
    # combustion rather than dropping the entire TTM plot.
    use_residual_ice <- !use_ice &&
      any(has_ttm_data) &&
      !any(ttm_sums[has_ttm_data] > 0.90, na.rm = TRUE)

    if (use_residual_ice) {
      data_monthly$`Other ICE TTM` <- pmax(0, 1 - ttm_sums)
      data_monthly <- data_monthly[has_ttm_data, , drop = FALSE]
    } else {
      data_monthly <- data_monthly[ttm_sums > 0.90, , drop = FALSE]
    }
  }
  if (nrow(data_monthly) == 0)
    stop("No rows with complete TTM data (sum > 90%) for ", country_label)

  start_year <- floor(min(data_monthly$year) + 1)
  months <- format(seq.Date(from = as.Date(paste0(start_year, "-01-01")),
                            by = step_by,
                            length.out = nrow(data_monthly)),
                   "%Y-%m")

  # EREV: only show as a separate layer once its TTM represents a full 12-month
  # window (i.e. the "EREV TTM complete" column, which is NA during the
  # ramp-up). During the ramp-up fold it into PHEV so the stack stays at 100%.
  erev_complete <- if (use_erev && "EREV TTM" %in% names(data_monthly))
    data_monthly$`EREV TTM` else rep(NA_real_, nrow(data_monthly))
  erev_partial  <- if (use_erev && "EREV TTM partial" %in% names(data_monthly))
    data_monthly$`EREV TTM partial` else erev_complete

  layers <- list(month = months)

  if (flags$has_other_ttm)
    layers$Other <- data_monthly$`Other TTM`

  if (use_ice)    layers$ICE    <- data_monthly$`ICE TTM`
  if (use_petrol) layers$Petrol <- data_monthly$`Petrol TTM`
  if (use_diesel) layers$Diesel <- data_monthly$`Diesel TTM`
  if (use_residual_ice) layers$`Other ICE` <- data_monthly$`Other ICE TTM`

  if (use_hybrid) {
    layers$Hybrid <- data_monthly$`Hybrid TTM`
  } else {
    if (use_hev) layers$HEV <- data_monthly$`HEV TTM`
    if (use_phev) {
      # During EREV ramp-up (EREV TTM is NA in the "complete" column) fold
      # the partial EREV value into PHEV so the stack reaches 100%.
      phev_vals <- data_monthly$`PHEV TTM`
      if (use_erev) {
        fold_mask <- is.na(erev_complete)
        phev_vals <- ifelse(fold_mask,
                            phev_vals + ifelse(is.na(erev_partial), 0, erev_partial),
                            phev_vals)
      }
      layers$PHEV <- phev_vals
    }
    if (use_erev && any(!is.na(erev_complete)))
      layers$EREV <- erev_complete
  }

  layers$BEV <- data_monthly$`BEV TTM`

  ttm <- as.data.frame(layers, check.names = FALSE)
  fuel_levels <- setdiff(names(ttm), "month")

  ttm_long <- ttm %>%
    pivot_longer(cols = all_of(fuel_levels), names_to = "type", values_to = "value") %>%
    mutate(type = factor(type, levels = fuel_levels)) %>%
    filter(!is.na(value)) %>%
    mutate(numeric_month = as.numeric(as.factor(month)))

  ggplot(ttm_long, aes(x = month, y = value, fill = type)) +
    geom_bar(stat = "identity", position = "stack", width = 1) +
    geom_vline(
      data = ttm_long %>% filter(substr(month, 6, 7) == "01") %>% distinct(numeric_month),
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
    scale_fill_viridis_d(name = "Fuel Type", option = "H", direction = -1) +
    labs(title = paste0("12-Month Trailing Market Shares by Fuel Type in ", country_label),
         y = "Trailing 12 Months Market Share", x = "Jahre", caption = caption) +
    theme_minimal() +
    theme(axis.text.x = element_text(angle = 45, hjust = 1), axis.title.x = element_blank(),
          plot.title = element_text(size = 14, face = "bold"),
          legend.position = c(0.05, 0.95), legend.justification = c(0, 1),
          legend.background = element_rect(fill = "white", color = "gray90", linewidth = 0.5),
          legend.key = element_rect(fill = NA, color = NA), legend.key.height = unit(0.2, "cm"),
          plot.caption = element_markdown(hjust = 0))
}

# Timer plot: how the expected 20→80% / 80→20% durations evolve over time.
build_timer_plot <- function(fit_result, country_label, caption, flag_img) {
  timer <- data.frame(
    year     = fit_result$bev_obs$x[seq_along(fit_result$bev_time)],
    BEV_time = fit_result$bev_time,
    ICE_time = fit_result$ice_time
  )

  inf_or_na_idx <- c(which(!is.finite(timer$BEV_time)), which(!is.finite(timer$ICE_time)))
  last_inf_index <- if (length(inf_or_na_idx)) max(inf_or_na_idx) else 0
  if (nrow(timer) > (last_inf_index + 12)) {
    timer <- timer[(last_inf_index + 1 + 12):nrow(timer), ]
  }

  # Drop any remaining rows whose BEV_time/ICE_time aren't finite — very
  # flat fits (Croatia, where BEV stays around 9% in observation) can leave
  # `-Inf` values dangling at the tail because the model never reaches 80%
  # within the extrapolation window. Without this the y-limit becomes NaN
  # and the plot crashes during ggsave.
  timer <- timer[is.finite(timer$BEV_time) & is.finite(timer$ICE_time), , drop = FALSE]

  if (nrow(timer) == 0) {
    warning("Timer plot skipped — no finite BEV_time / ICE_time values for ", country_label)
    return(ggplot() +
             labs(title = paste0("Timer plot unavailable for ", country_label,
                                 " (insufficient transition signal in fit)")) +
             theme_void())
  }

  data_month <- (as.integer(((fit_result$bev_obs$x %% 1) * 12 + 1)[length(fit_result$bev_obs$x)]) + 1) %% 12
  y_limit <- max(c(timer$BEV_time, timer$ICE_time), na.rm = TRUE) * 1.05

  theme_set(theme_minimal(base_size = 14))

  p <- ggplot(timer, aes(x = year)) +
    geom_line(aes(y = BEV_time, col = "BEV share to rise from 20% to 80% market share"), lwd = 1) +
    geom_line(aes(y = ICE_time, col = "ICE share to fall from 80% to 20% market share"), lwd = 1) +
    scale_x_continuous(
      breaks = seq(fit_result$verschiebung, fit_result$extrapol, 1),
      labels = function(x) paste0("Jan ", x + 1)
    ) +
    scale_y_continuous(
      name = "Number of years expected",
      limits = c(0, y_limit)
    ) +
    labs(
      title = paste0("Time expectation for ", country_label, " transition time using historical data"),
      subtitle = "Each point in time marks what the expectation was at the time",
      caption = caption,
      x = " "
    ) +
    theme_minimal() +
    scale_color_manual(
      values = c("#33FF3B", "darkblue", "lightblue", "#FF5733"),
      name = "expected time for"
    ) +
    theme(
      plot.title    = element_text(face = "bold", size = rel(1.5)),
      plot.subtitle = element_text(size = rel(1.2), color = "black", lineheight = 0.3),
      axis.text     = element_text(size = rel(0.9)),
      axis.title    = element_text(size = rel(1.1)),
      legend.position  = "bottom",
      legend.direction = "horizontal",
      legend.title  = element_text(size = rel(1.1)),
      legend.text   = element_text(size = rel(1)),
      legend.key.width  = unit(0.6, "cm"),
      legend.key.height = unit(0.6, "cm"),
      plot.caption  = element_markdown(hjust = 0, size = rel(0.9))
    )

  current_year <- as.numeric(format(Sys.Date(), "%Y"))

  if (!is.null(flag_img)) {
    p <- p + annotation_custom(
      grob = rasterGrob(as.raster(flag_img), interpolate = TRUE),
      xmin = current_year + data_month / 12 - 1.5,
      ymax = 0.3 * timer$BEV_time[length(timer$BEV_time)] * 2,
      ymin = 0
    )
  }

  p
}

# BEV trajectory plot.
build_bev_trajectory_plot <- function(fit_result, country_label, caption,
                                      entire_caption, flag_img,
                                      default_size = 2) {
  fit       <- fit_result$fit
  new_A     <- fit_result$new_points
  BEV       <- fit_result$bev_obs
  extrapol  <- fit_result$extrapol
  t20_to_80 <- fit_result$time_20_to_80

  theme_set(theme_minimal(base_size = 14))

  x_limits <- c(2010, min(extrapol, 2045))

  p <- ggplot(fit, aes(x = x, y = BEV, color = Type)) +
    geom_ribbon(aes(ymin = BEV_lower, ymax = BEV_upper), fill = "grey", alpha = 0.5, color = NA) +
    geom_line(lwd = 1) +
    geom_point(data = new_A, aes(x = x, y = y, color = Quarter),
               size = scaled_point_size(new_A$overall, default_size)) +
    scale_x_continuous(breaks = seq(2010, extrapol, ifelse(extrapol > 2045, 4, 2)),
                       labels = function(x) paste0("Jan ", x + 1)) +
    scale_y_continuous(breaks = seq(0, 1, 0.1), labels = unit_format(unit = "%", scale = 1e2)) +
    coord_cartesian(xlim = x_limits, ylim = c(0, 1.1)) +
    labs(title    = paste0("BEV share in new registrations in ", country_label, " - an Extrapolation"),
         subtitle = paste0("expected time for BEV to rise from 20% to 80%: ",
                           floor(t20_to_80), " years ",
                           round(12 * (t20_to_80 - floor(t20_to_80)), 0), " months"),
         caption  = entire_caption, x = " ", y = "BEV share") +
    theme_minimal() +
    theme(legend.position = c(0.93, 0.60), legend.background = element_rect(fill = "gray99"),
          plot.title = element_text(face = "bold", size = rel(1.5)),
          plot.subtitle = element_text(size = rel(1.2)),
          legend.text = element_text(size = rel(1)),
          axis.text = element_text(size = rel(0.9)),
          plot.caption = element_markdown(hjust = 0)) +
    scale_color_manual(values = c("#FF5733", "#FFC300", "#33FF3B", "#33A1FF", "#B633FF", "#FF33E9"),
                       name = "Color")

  p <- p + annotate("text", x = 2010, y = 1, label = "New Registration estimates in",
                    size = rel(6), hjust = 0, vjust = 1, col = "red")

  # Year-by-year BEV % annotations. Stops once the projected BEV reaches
  # 100% or once the y-stack runs out of room. Defensive against the
  # subset returning zero rows (Malta-style sparse fits) — bail out instead
  # of dereferencing a length-zero numeric.
  counter <- 0
  repeat {
    sub <- subset(fit, fit$x == 2024 + counter & fit$Type == "New Registrations")
    if (nrow(sub) != 1) break
    bev_pct <- round(sub$BEV * 100, 1)
    if (!is.finite(bev_pct) || bev_pct >= 100) break
    if (1 - 0.05 * (counter + 1) <= 0.1) break
    p <- p + annotate("text", x = 2010 + 0.5, y = 1 - 0.05 * (counter + 1),
                      label = paste0("Jan ", 2025 + counter, ": ", bev_pct, "%"),
                      size = rel(5), hjust = 0, vjust = 1, col = "red")
    counter <- counter + 1
  }

  if (!is.null(flag_img)) {
    p <- p + annotation_custom(
      grob = rasterGrob(as.raster(flag_img), interpolate = TRUE,
                        width = unit(1 * 1920 / 1280, "in"), height = unit(1, "in")),
      xmin = x_limits[2] - 4, ymin = -0.9
    )
  }

  p
}

# BEV/ICE/PHEV trajectory plot (3 colored lines).
build_ice_bev_plot <- function(data, fit_result, country_label, caption, entire_caption,
                               flag_img, default_size = 2) {
  fit      <- fit_result$fit
  BEV      <- fit_result$bev_obs
  ICE_obs  <- fit_result$ice_obs
  Hybrid   <- fit_result$hybrid_obs
  extrapol <- fit_result$extrapol
  t80_20   <- fit_result$time_80_to_20

  ICE_obs$overall <- data$overall
  BEV$overall     <- data$overall
  Hybrid$overall  <- data$overall
  phev_points <- data[is.finite(data$hybrid_share) & is.finite(data$year), , drop = FALSE]

  theme_set(theme_minimal(base_size = 14))

  x_limits <- c(2010, min(extrapol, 2045))

  p <- ggplot(fit, aes(x = x, y = BEV, color = Type)) +
    geom_ribbon(aes(ymin = BEV_lower, ymax = BEV_upper), fill = "green", alpha = 0.5, color = NA) +
    geom_line(aes(y = BEV, color = "BEV"), lwd = 1) +
    geom_point(data = BEV, aes(x = x, y = y, color = "BEV", shape = "BEV"),
               size = scaled_point_size(BEV$overall, default_size)) +
    geom_ribbon(aes(ymin = ICE_lower, ymax = ICE_upper), fill = "red", alpha = 0.5, color = NA) +
    geom_line(aes(y = ICE, color = "ICE"), lwd = 1) +
    geom_point(data = ICE_obs, aes(x = x, y = y, color = "ICE", shape = "ICE"),
               size = scaled_point_size(ICE_obs$overall, default_size)) +
    geom_ribbon(aes(ymin = Hybrid_lower, ymax = Hybrid_upper), fill = "blue", alpha = 0.5, color = NA) +
    geom_line(aes(y = Hybrid, color = "PHEV"), lwd = 1) +
    scale_x_continuous(breaks = seq(2006, extrapol, ifelse(extrapol > 2045, 4, 2)),
                       labels = function(x) paste0("Jan ", x + 1)) +
    scale_y_continuous(breaks = seq(0, 1, 0.1), labels = unit_format(unit = "%", scale = 1e2)) +
    coord_cartesian(xlim = x_limits, ylim = c(0, 1.1)) +
    labs(title    = paste0("BEV / ICE / PHEV share of new registrations in ", country_label, " - an Extrapolation"),
         subtitle = paste0("expected time for ICE to drop from 80% to 20%: ",
                           floor(t80_20), " years ",
                           round(12 * (t80_20 - floor(t80_20)), 0), " months"),
         caption  = entire_caption, x = " ", y = "New Registration Share") +
    theme(
      axis.title    = element_text(size = rel(1.2)),
      axis.text     = element_text(size = rel(0.9)),
      plot.title    = element_text(face = "bold", size = rel(1.5)),
      plot.subtitle = element_text(size = rel(1.2)),
      legend.position   = c(0.93, 0.68),
      legend.background = element_rect(fill = "gray99"),
      legend.title  = element_text(size = rel(1)),
      legend.text   = element_text(size = rel(0.9)),
      plot.caption  = element_markdown(hjust = 0, size = rel(0.9))
    ) +
    scale_color_manual(name = "Legend", breaks = c("ICE", "BEV", "PHEV"),
                       values = c("ICE" = "red", "BEV" = "green", "PHEV" = "blue")) +
    scale_shape_manual(name = "Legend", breaks = c("ICE", "BEV", "PHEV"),
                       values = c("ICE" = 15, "BEV" = 16, "PHEV" = 23))

  if (nrow(phev_points) > 0) {
    p <- p + geom_point(data = phev_points,
                        aes(x = year, y = hybrid_share, color = "PHEV", shape = "PHEV"),
                        size = scaled_point_size(phev_points$overall, default_size))
  }

  p <- p + annotate("text", x = 2010, y = 0.9, label = "New ICE in",
                    size = rel(6), hjust = 0, vjust = 1, col = "red")

  counter <- 0
  repeat {
    sub_prev <- subset(fit, fit$x == 2024 + counter - 1 & fit$Type == "New Registrations")
    sub_curr <- subset(fit, fit$x == 2024 + counter     & fit$Type == "New Registrations")
    if (nrow(sub_prev) != 1 || nrow(sub_curr) != 1) break
    ice_prev <- round(sub_prev$ICE * 100, 1)
    ice_curr <- round(sub_curr$ICE * 100, 1)
    if (!is.finite(ice_prev) || !is.finite(ice_curr) || ice_prev <= 5) break
    if (1 - 0.05 * (counter + 1) <= 0.1) break
    p <- p + annotate("text", x = 2010 + 0.5, y = 0.85 - counter * 0.05,
                      label = paste0("Jan ", 2024 + counter + 1, ": ", ice_curr, "%"),
                      size = rel(5), hjust = 0, vjust = 1, col = "red")
    counter <- counter + 1
  }

  if (!is.null(flag_img)) {
    p <- p + annotation_custom(
      grob = rasterGrob(as.raster(flag_img), interpolate = TRUE,
                        width = unit(1.5, "in"), height = unit(1, "in")),
      xmin = x_limits[2] - 4, ymin = -0.9
    )
  }

  p
}
