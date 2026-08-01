# Pull BEV export shares from UN Comtrade into a cached CSV so the scatter/
# trajectory charts are reproducible without re-hitting the API. For each
# reporter/year it records value(HS 870380) and value(HS 8703); the BEV export
# share is 870380/8703. Missing cells (e.g. reporters that have not filed a
# given year yet) are left blank.
#
# Force the single aggregate row (partner2Code/motCode/customsCode) or the API
# returns per-transport-mode sub-rows that double-count on summation.
#
# Run from repo root:  Rscript scripts/fetch_export_shares.R

suppressPackageStartupMessages(library(jsonlite))
repo <- normalizePath(".")
out <- file.path(repo, "exports", "ray_article", "comtrade_bev_export_shares.csv")

reporters <- c(China = 156, Germany = 276, Japan = 392,
               `South Korea` = 410, USA = 842, Thailand = 764)
years <- 2021:2025

comtrade_value <- function(reporter, cmd, year) {
  u <- sprintf(paste0("https://comtradeapi.un.org/public/v1/preview/C/A/HS",
                      "?reporterCode=%d&period=%d&cmdCode=%s&flowCode=X",
                      "&partnerCode=0&partner2Code=0&motCode=0&customsCode=C00"),
               reporter, year, cmd)
  for (attempt in 1:6) {
    d <- tryCatch(fromJSON(u)$data, error = function(e) NULL)
    if (!is.null(d) && length(d) > 0) { Sys.sleep(2); return(as.numeric(d$primaryValue[1])) }
    Sys.sleep(3 * attempt)
  }
  NA_real_
}

rows <- list()
for (nm in names(reporters)) for (yr in years) {
  bev <- comtrade_value(reporters[[nm]], "870380", yr)
  car <- comtrade_value(reporters[[nm]], "8703", yr)
  rows[[length(rows) + 1]] <- data.frame(
    year = yr, country = nm, bev_exp_usd = bev, car_exp_usd = car,
    ev_export_share = bev / car)
  cat(sprintf("%-12s %d  BEV=%s  cars=%s  share=%s\n", nm, yr,
              ifelse(is.na(bev), "NA", format(round(bev/1e9,1))),
              ifelse(is.na(car), "NA", format(round(car/1e9,1))),
              ifelse(is.na(bev/car), "NA", sprintf("%.1f%%", 100*bev/car))))
}
df <- do.call(rbind, rows)
write.csv(df, out, row.names = FALSE)
cat("\nwrote", sub(paste0(repo, "/"), "", out), "\n")
