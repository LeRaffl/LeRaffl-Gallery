# R/run_all.R
# Run the consolidated pipeline across every market in data/markets/.
# Useful for monthly batch updates and for the GitHub Actions workflow.
#
# Usage:
#   Rscript R/run_all.R                   # every market in _index.csv
#   Rscript R/run_all.R --skip-fail       # keep going even if one fails
#   Rscript R/run_all.R Austria China     # only the named sheets

suppressPackageStartupMessages({
  library(readr)
})

script_dir_runall <- function() {
  args <- commandArgs(trailingOnly = FALSE)
  fa <- grep("^--file=", args, value = TRUE)
  if (length(fa) == 1) return(normalizePath(dirname(sub("^--file=", "", fa))))
  normalizePath(".")
}

R_DIR     <- script_dir_runall()
REPO_DIR  <- normalizePath(file.path(R_DIR, ".."))
INDEX_CSV <- file.path(REPO_DIR, "data", "markets", "_index.csv")

source(file.path(R_DIR, "bev_share.R"))

main_run_all <- function() {
  args      <- commandArgs(trailingOnly = TRUE)
  skip_fail <- "--skip-fail" %in% args
  args      <- setdiff(args, "--skip-fail")

  if (!file.exists(INDEX_CSV))
    stop("Index file missing: ", INDEX_CSV,
         ". Run scripts/migrate_xlsx_to_csv.R first.")

  index <- suppressMessages(read_csv(INDEX_CSV, show_col_types = FALSE))
  sheets <- if (length(args)) args else index$sheet_name

  cat(sprintf("Running pipeline on %d sheet(s)\n", length(sheets)))
  cat(sprintf("INDEX: %s\nREPO:  %s\n", INDEX_CSV, REPO_DIR))
  cat("--------------------------------------------\n")

  failed  <- character(0)
  errors  <- character(0)
  results <- list()

  for (sheet in sheets) {
    cat(sprintf("\n[%s]\n", sheet))
    res <- tryCatch({
      process_sheet(sheet)
      "ok"
    }, error = function(e) {
      msg <- conditionMessage(e)
      cat(sprintf("  ERROR: %s\n", msg))
      msg
    })
    if (!identical(res, "ok")) {
      failed <- c(failed, sheet)
      errors <- c(errors, res)
      if (!skip_fail) {
        stop(sprintf("Sheet '%s' failed; pass --skip-fail to keep going.", sheet))
      }
    }
    results[[sheet]] <- res
  }

  cat("\n============================================\n")
  cat(sprintf("Done. %d sheet(s) processed, %d failed.\n",
              length(sheets), length(failed)))
  if (length(failed)) {
    cat("Failed sheets:\n")
    for (i in seq_along(failed))
      cat(sprintf("  - %s : %s\n", failed[i], errors[i]))
    quit(status = if (skip_fail) 0 else 1)
  }
}

if (!interactive() && sys.nframe() == 0) main_run_all()
