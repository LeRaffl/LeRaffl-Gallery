#!/usr/bin/env Rscript
# Offline contract: optional raw detail cannot alter legacy fit/chart/post inputs.
source('R/data.R'); source('R/post_text.R')
read_fixture <- function(d) {
  path <- tempfile(fileext='.csv'); on.exit(unlink(path))
  write.csv(d,path,row.names=FALSE,na=''); load_country_csv(path)
}
for (country in c('Japan','South Korea')) for (interval in c('monthly','quarterly','yearly')) {
  n <- 36L; i <- seq_len(n)
  dates <- seq(as.Date('2020-01-01'), by=switch(interval,monthly='month',quarterly='3 months',yearly='year'),length.out=n)
  fc <- ifelse(i == 26,0,1+i%%2)
  old <- data.frame(period=format(dates,'%Y-%m'), time_interval=interval,
    variant='Whole',source='fixture',BEV=10+i,PHEV=2+i%%3,HEV=30+i%%5,
    OTHERS=3+i%%3+fc,notes='',stringsAsFactors=FALSE)
  if(country == 'Japan') {old$PETROL <- 100+2*i;old$DIESEL <- 20+i%%7} else old$ICE <- 200+i
  old$TOTAL <- rowSums(old[sapply(old,is.numeric)])
  split <- old;split$FCEV <- ifelse(i < 19,NA,fc)
  split$OTHERS[i >= 19] <- split$OTHERS[i >= 19]-fc[i >= 19]
  a <- read_fixture(old);b <- read_fixture(split)
  # Exact unchanged fit inputs: no FCEV in battery or plug-in numerator.
  fit_cols <- c('year','overall','bev_share','phev_share','ice_share','hybrid_share')
  stopifnot(identical(a[fit_cols],b[fit_cols]),is.na(b$FCEV[1]),b$FCEV[26]==0)
  for(calendar in c(FALSE,TRUE)) stopifnot(identical(compute_ttm_long(a,calendar=calendar),compute_ttm_long(b,calendar=calendar)))
  stopifnot(identical(build_post_text(a,country,tail(a$period,1)),build_post_text(b,country,tail(b$period,1))))
  stopifnot(identical(build_ttm_post_text(a,country,tail(a$period,1)),build_ttm_post_text(b,country,tail(b$period,1))))
  blank <- a;blank$FCEV <- NA_real_
  stopifnot(identical(legacy_fuel_rollup(blank)$OTHERS,a$OTHERS),identical(compute_ttm_long(a),compute_ttm_long(blank)))
  if(interval=='monthly') {
    stopifnot(nrow(compute_ttm_long(b))>0, min(compute_ttm_long(b)$month) < b$period[19])
    # No raw Other column: derived view supplies only the legacy rollup.
    absent <- b;absent$OTHERS <- NULL
    rolled <- legacy_fuel_rollup(absent)
    stopifnot(all(rolled$OTHERS[1:18]==0),all(rolled$OTHERS[19:36]==fc[19:36]))
    stopifnot(!is.null(compute_ttm_long(absent)))
  }
}
for(value in c(-1,Inf,NaN,'bad')) {
  bad <- data.frame(FCEV=as.character(value),OTHERS=0)
  stopifnot(inherits(try(legacy_fuel_rollup(bad),silent=TRUE),'try-error'))
}
cat('FCEV legacy fit inputs, TTM history, post text and unknown/zero regressions passed\n')

# Activation transition using actual existing source fixture counts:
# JADA January 2026 (FCV79 + Other1), MOTIR August 2026 (hydrogen312).
for(country in c('Japan','South Korea')) {
  n <- 36L
  d <- data.frame(period=format(seq(as.Date('2024-01-01'),by='month',length.out=n),'%Y-%m'),
    time_interval='monthly',variant='Whole',source='fixture',notes='')
  if(country=='Japan') {
    d$BEV <- 5419;d$PHEV <- 3582;d$HEV <- 121955;d$PETROL <- 59876;d$DIESEL <- 9135
    d$OTHERS <- 80;d$TOTAL <- 200047;fc <- 79
  } else {
    d$BEV <- 31060;d$PHEV <- 1334;d$HEV <- 36102;d$ICE <- 41112
    d$OTHERS <- 312;d$TOTAL <- 109920;fc <- 312
  }
  split <- d;split$FCEV <- NA_real_;split$FCEV[n] <- fc;split$OTHERS[n] <- split$OTHERS[n]-fc
  old <- read_fixture(d);new <- read_fixture(split)
  stopifnot(identical(old[fit_cols],new[fit_cols]))
  stopifnot(identical(compute_ttm_long(old),compute_ttm_long(new)))
  stopifnot(identical(build_post_text(old,country),build_post_text(new,country)))
  stopifnot(identical(build_ttm_post_text(old,country),build_ttm_post_text(new,country)))
}
cat('Actual JP/KR source-count activation transition preserves legacy outputs\n')
