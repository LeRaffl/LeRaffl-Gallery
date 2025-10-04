# log_params.R — schreibe/überschreibe Fit-Parameter in params.csv
suppressWarnings(suppressMessages({ library(readr); library(dplyr) }))

log_params <- function(out_csv, country, shape, scale, t0_date,
                       last_obs_date, variant = NA_character_,
                       model_date = Sys.Date(), source = NA_character_) {

  row <- tibble::tibble(
    country = country,
    variant = ifelse(is.na(variant), "", variant),
    shape = round(shape, 6),
    scale = round(scale, 6),
    t0_date = as.character(as.Date(t0_date)),
    last_obs_date = as.character(as.Date(last_obs_date)),
    model_date = as.character(as.Date(model_date)),
    source = source
  )

  if (!file.exists(out_csv)) {
    write_csv(row, out_csv)
  } else {
    cur <- read_csv(out_csv, show_col_types = FALSE)
    keep <- cur %>% filter(!(country == !!country & (variant == ifelse(is.na(variant), "", variant))))
    write_csv(bind_rows(keep, row), out_csv)
  }
}

# Beispiel:
# log_params("site/params.csv", "Germany", fit_shape, fit_scale, as.Date("2010-01-01"), as.Date("2025-08-31"), variant = "All", source = "KBA; eigene Aufbereitung")
