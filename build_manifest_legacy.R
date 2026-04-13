# build_manifest.R — robust für Slugs & Sonderfälle
suppressPackageStartupMessages({
  library(jsonlite); library(stringr); library(dplyr); library(lubridate); library(purrr); library(fs); library(tibble)
})

# ---- Typen aus Dateinamen erkennen ----
infer_type <- function(fname){
  n <- tolower(fname)
  case_when(
    str_detect(n, "_ice[_-]bev_") ~ "ICE_BEV",
    str_detect(n, "_ttm[_-]shares_") ~ "ttm_shares",
    str_detect(n, "_time_") ~ "time",
    TRUE ~ "share"
  )
}

# ---- Slug aus Basename extrahieren (vor Typ oder Datum) ----
# akzeptiert:
#  <slug>_ICE_BEV_YYYYMMDD.png
#  <slug>_time_YYYYMMDD.png
#  <slug>_ttm_shares_YYYYMMDD.png
#  <slug>_YYYYMMDD.png
extract_country_slug <- function(base){
  # base = filename ohne Extension
  slug <- base |>
    str_remove("_(?i)(time|ice[_-]bev|ttm[_-]shares)_.+$") |>
    str_remove("_(\\d{8})$")
  tolower(slug)
}

# ---- Hübsches Label aus Slug bauen: "Country (Special Case)" ----
to_title_keep_digits <- function(x) {
  x <- gsub("_", " ", x)
  x <- gsub("([0-9])([a-zA-Z])", "\\1-\\2", x)  # 4wheelers -> 4-wheelers
  stringr::str_to_title(x)
}

label_from_slug <- function(slug, country_overrides = NULL, variant_overrides = NULL){
  s <- tolower(slug)
  
  # Basisland = alles bis erstes "_"
  base <- sub("^([a-z0-9-]+).*$", "\\1", s)
  
  # Länder-Overrides (Diakritika etc.)
  country_map <- c("tuerkiye" = "Türkiye")
  if (!is.null(country_overrides)) {
    country_map[names(country_overrides)] <- country_overrides
  }
  
  base_label <- ifelse(!is.na(country_map[base]), country_map[base], stringr::str_to_title(base))
  
  # Variante = alles nach erstem "_"
  rest <- sub("^[a-z0-9-]+_?", "", s)
  
  # Normalisierung Rest (vektorisiert)
  rest2 <- gsub("-", " ", rest)
  rest2 <- gsub("\\bhev\\b",  "HEV",  rest2, ignore.case = TRUE)
  rest2 <- gsub("\\bphev\\b", "PHEV", rest2, ignore.case = TRUE)
  rest2 <- gsub("\\bev\\b",   "EV",   rest2, ignore.case = TRUE)
  rest_label <- to_title_keep_digits(rest2)
  rest_label <- gsub("\\bAnd\\b", "and", rest_label)
  rest_label <- gsub("\\bOf\\b",  "of",  rest_label)
  rest_label <- gsub("\\bIn\\b",  "In",  rest_label)
  
  # Variant-Overrides optional (vektorisiert)
  if (!is.null(variant_overrides) && length(variant_overrides)) {
    idx <- match(tolower(rest_label), tolower(names(variant_overrides)))
    repl <- ifelse(is.na(idx), rest_label, unname(variant_overrides[idx]))
    rest_label <- repl
  }
  
  # Wenn keine Variante existiert, nur Land; sonst "Land (Variante)"
  out <- ifelse(rest == "" | rest == s, base_label, sprintf("%s (%s)", base_label, rest_label))
  return(out)
}

# ---- Hauptfunktion ----
# root:    Verzeichnis mit Monatsordnern (z. B. "images/2025-09")
# base_url: URL-Prefix in deinem Web (typisch "images/")
# periods_tbl: optional Tabelle mit (country, type) -> period für Overrides
# country_overrides / variant_overrides: benutzerdefinierte Labels
build_manifest <- function(root = "images",
                           base_url = "images/",
                           periods_tbl = NULL,
                           country_overrides = NULL,
                           variant_overrides = NULL) {
  
  stopifnot(fs::dir_exists(root))
  
  files <- fs::dir_ls(root, recurse = TRUE, type = "file",
                      regexp = "[.](png|webp)$", fail = FALSE)
  
  if (length(files) == 0) stop("No images in ", root)
  
  df <- tibble(path = as.character(files)) |>
    mutate(
      rel_path = fs::path_rel(path, start = fs::path_abs(root)),
      period   = str_match(rel_path, "^([0-9]{4}-[0-9]{2})/")[,2],
      filename = fs::path_file(path),
      base     = str_remove(filename, "[.](png|webp)$"),
      # Country-Slug + Label
      country_slug = extract_country_slug(base),
      country      = label_from_slug(country_slug,
                                     country_overrides = country_overrides,
                                     variant_overrides = variant_overrides),
      type     = infer_type(filename),
      date8    = str_extract(filename, "(?<!\\d)(\\d{8})(?!\\d)"),
      date     = if_else(!is.na(date8), as.character(ymd(date8)), NA_character_),
      url      = paste0(base_url, rel_path),
      alt      = paste(country, recode(type,
                                       ICE_BEV    = "ICE-BEV-Hybrid trajectory",
                                       time       = "Transition time curve",
                                       ttm_shares = "TTM market split graph",
                                       share      = "BEV trajectory"))
    )
  
  # Validierung: fehlende period oder date melden
  bad_period <- which(is.na(df$period))
  if (length(bad_period)) {
    warning("Dateien ohne gültigen Monatsordner (YYYY-MM):\n  - ",
            paste(df$rel_path[bad_period], collapse = "\n  - "))
  }
  bad_date <- which(is.na(df$date))
  if (length(bad_date)) {
    warning("Dateien ohne YYYYMMDD am Ende des Dateinamens:\n  - ",
            paste(df$filename[bad_date], collapse = "\n  - "))
  }
  
  df <- df |>
    select(country, type, period, date, filename, url, alt, country_slug)
  
  # Optional Perioden-Overrides mergen
  if (!is.null(periods_tbl)) {
    df <- df |>
      left_join(periods_tbl, by = join_by(country, type), suffix = c("", ".tbl")) |>
      mutate(period = coalesce(period, period.tbl)) |>
      select(-tidyselect::ends_with(".tbl"))
  }
  
  # deterministische Sortierung: neueste zuerst
  df <- df |>
    arrange(desc(date), country, type, filename)
  
  manifest <- list(updated = as.character(Sys.Date()), images = df)
  jsonlite::write_json(manifest, file.path(dirname(root), "manifest.json"),
                       auto_unbox = TRUE, pretty = TRUE)
  message("manifest.json written (", nrow(df), " records)")
  invisible(manifest)
}

# # Beispiel:
# source("build_manifest.R"); build_manifest("images", "images/")
