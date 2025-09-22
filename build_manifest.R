# build_manifest.R
suppressPackageStartupMessages({
  library(jsonlite); library(stringr); library(dplyr); library(lubridate); library(purrr); library(fs)
})

infer_type <- function(fname){
  n <- tolower(fname)
  dplyr::case_when(
    str_detect(n, "_ice_bev_")    ~ "ICE_BEV",
    str_detect(n, "_ttm_shares_") ~ "ttm_shares",
    str_detect(n, "_time_")       ~ "time",
    TRUE                          ~ "share"
  )
}

norm_country <- function(x){
  x <- str_to_title(x)
  dplyr::recode(x, "Tuerkiye" = "Türkiye")
}

# root: e.g. "images" with subfolders "YYYY-MM"
# base_url: how your site will reference files (typically "images/")
build_manifest <- function(root = "images", base_url = "images/", periods_tbl = NULL) {
  stopifnot(fs::dir_exists(root))
  files <- fs::dir_ls(root, recurse = TRUE, type = "file", regexp = "\.(png|webp)$", fail = FALSE)
  if (length(files) == 0) stop("No images in ", root)

  df <- tibble::tibble(path = as.character(files)) |>
    mutate(
      rel_path = fs::path_rel(path, start = fs::path_abs(root)),
      period   = stringr::str_match(rel_path, "^([0-9]{4}-[0-9]{2})/")[,2],
      filename = fs::path_file(path),
      base     = stringr::str_remove(filename, "\.(png|webp)$"),
      parts    = stringr::str_split(base, "_", simplify = TRUE),
      country0 = parts[,1],
      country  = norm_country(country0),
      type     = infer_type(filename),
      date8    = stringr::str_extract(filename, "(?<!\d)(\d{8})(?!\d)"),
      date     = dplyr::if_else(!is.na(date8), as.character(lubridate::ymd(date8)), NA_character_),
      url      = paste0(base_url, rel_path),
      alt      = paste(country, dplyr::recode(type,
                    ICE_BEV    = "ICE-BEV-Hybrid trajectory",
                    time       = "Transition time curve",
                    ttm_shares = "TTM market split graph",
                    share      = "BEV trajectory"))
    ) |>
    dplyr::select(country, type, period, date, filename, url, alt)

  if (!is.null(periods_tbl)) {
    df <- df |>
      dplyr::left_join(periods_tbl, by = dplyr::join_by(country, type), suffix = c("", ".tbl")) |>
      dplyr::mutate(period = dplyr::coalesce(period, period.tbl)) |>
      dplyr::select(-tidyselect::ends_with(".tbl"))
  }

  manifest <- list(updated = as.character(Sys.Date()), images = df)
  jsonlite::write_json(manifest, file.path(dirname(root), "manifest.json"), auto_unbox = TRUE, pretty = TRUE)
  message("manifest.json written")
  invisible(manifest)
}

# Example call:
source('build_manifest.R')
build_manifest('images', 'images/')
