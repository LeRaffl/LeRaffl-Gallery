# scripts/audit_xlsx_csv_categories.R
# Compare raw category columns in the legacy XLSX with canonical market CSVs.
#
# Usage:
#   Rscript scripts/audit_xlsx_csv_categories.R data/raw/bev_share_acea.xlsx
#   Rscript scripts/audit_xlsx_csv_categories.R /path/to/bev_share_acea.xlsx data/markets

suppressPackageStartupMessages({
  library(readxl)
  library(readr)
  library(dplyr)
})

script_dir <- function() {
  args0 <- commandArgs(trailingOnly = FALSE)
  file_arg <- grep("^--file=", args0, value = TRUE)
  if (length(file_arg) == 1) {
    return(normalizePath(dirname(sub("^--file=", "", file_arg))))
  }
  normalizePath(".")
}

repo_dir <- normalizePath(file.path(script_dir(), ".."))

args <- commandArgs(trailingOnly = TRUE)
xlsx <- if (length(args) >= 1) args[[1]] else file.path(repo_dir, "data", "raw", "bev_share_acea.xlsx")
market_dir <- if (length(args) >= 2) args[[2]] else file.path(repo_dir, "data", "markets")

if (!file.exists(xlsx)) {
  stop("XLSX not found: ", xlsx, call. = FALSE)
}
if (!dir.exists(market_dir)) {
  stop("Market CSV directory not found: ", market_dir, call. = FALSE)
}

source(file.path(repo_dir, "R", "lib", "variants.R"))

SKIP_SHEETS <- c(
  "Europeanunion", "Netherlands_HDV(old)", "NewZealand (Legacy)",
  "Georgia (Fleet)", "Netherlands (Fleet)"
)

slug_aliases <- c(
  "Türkiye"        = "tuerkiye",
  "South Korea"    = "southkorea",
  "New Zealand"    = "newzealand",
  "United States"  = "usa",
  "USA"            = "usa",
  "United Kingdom" = "uk",
  "UK"             = "uk",
  "Czechia"        = "czechia",
  "Czech Republic" = "czechia"
)

country_to_slug <- function(country) {
  if (country %in% names(slug_aliases)) return(unname(slug_aliases[country]))
  tolower(gsub("\\s+", "", country))
}

parse_sheet_name <- function(sheet) {
  if (grepl("\\(", sheet)) {
    country <- trimws(sub("\\s*\\(.*\\)\\s*", "", sheet))
    variant <- normalize_variant(sub(".*\\(([^)]+)\\).*", "\\1", sheet))
    slug <- if (is_default_variant(variant)) {
      country_to_slug(country)
    } else {
      paste0(country_to_slug(country), "_", variant_slug_suffix(variant))
    }
  } else {
    country <- sheet
    variant <- DEFAULT_VARIANT
    slug <- country_to_slug(country)
  }
  list(country = country, variant = variant, slug = slug)
}

canon_category <- function(name) {
  if (name %in% c("OTHER", "OTHERS")) return("OTHER")
  toupper(name)
}

source_category_columns <- function(raw) {
  nms <- names(raw)
  ti <- match("time_interval", nms)
  block <- if (!is.na(ti) && ti > 1) nms[seq_len(ti - 1)] else nms
  block <- setdiff(block, c("YYYYMMM", "year", "Source", "time_interval"))
  block <- block[!grepl("share|TTM|hazard|Uistrom|^Fossil$|^Hybrid$|^Spalte",
                        block, ignore.case = TRUE)]
  block <- block[grepl("^[A-Za-z0-9][A-Za-z0-9 +_-]*$", block)]
  block[vapply(block, function(col) {
    any(!is.na(suppressWarnings(as.numeric(raw[[col]]))))
  }, logical(1))]
}

issues <- list()
for (sheet in setdiff(excel_sheets(xlsx), SKIP_SHEETS)) {
  parsed <- parse_sheet_name(sheet)
  csv_path <- file.path(market_dir, paste0(parsed$slug, ".csv"))
  if (!file.exists(csv_path)) {
    issues[[length(issues) + 1]] <- data.frame(
      sheet = sheet, slug = parsed$slug, issue = "missing_csv",
      missing_categories = "", stringsAsFactors = FALSE
    )
    next
  }

  raw <- suppressWarnings(read_excel(xlsx, sheet = sheet)) %>%
    as.data.frame(check.names = FALSE)
  xlsx_categories <- sort(unique(vapply(source_category_columns(raw),
                                        canon_category, character(1))))
  csv_categories <- sort(unique(suppressMessages(
    read_csv(csv_path, show_col_types = FALSE, progress = FALSE)
  )$category))
  missing <- setdiff(xlsx_categories, csv_categories)
  if (length(missing)) {
    issues[[length(issues) + 1]] <- data.frame(
      sheet = sheet, slug = parsed$slug, issue = "missing_category",
      missing_categories = paste(missing, collapse = "|"),
      stringsAsFactors = FALSE
    )
  }
}

out <- bind_rows(issues)
if (nrow(out)) {
  write_csv(out, stdout())
  quit(status = 1)
}

cat("No non-empty XLSX source categories are missing from CSVs.\n")
