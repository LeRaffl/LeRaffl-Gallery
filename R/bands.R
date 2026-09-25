# Uncertainty bands for the fitted BEV S-curve: confidence (CI), prediction (PI)
# and tolerance (TI) intervals, written to bands/<slug>.json for the frontend.
#
# The fit itself is NOT touched: fit_history() (R/fit.R) produces v1, v2, t0 as
# always, and this file only measures how uncertain that fit is. Nothing here
# feeds the rendered PNGs in images/. The full explanation — definitions,
# maths, validation, caveats — is docs/architecture/44-uncertainty-bands.md;
# read it before changing anything below.
#
#   CI  (95 %)      where the true curve is. Inverse-Hessian sandwich with the
#                   scores prewhitened by an AR(2) and recoloured, so correlated
#                   months do not make the band too narrow.
#   PI  (95 %)      where one more month lands. The CI's uncertainty for the
#                   line combined with the EMPIRICAL distribution of monthly
#                   deviations (real tails, no normal assumption).
#   TI  (95 / 95)   where 95 % of all possible months land, with 95 %
#                   confidence. Block bootstrap (12-month blocks).
#
# Time: R fits on an internal axis one year below the calendar
# (period_to_year() maps "2026-01" to 2025.0). Every date written to the JSON
# is converted to CALENDAR decimal years (internal + 1), the same convention
# the frontend uses (index.html, "CALENDAR-YEAR FIX").

BANDS_LEVEL      <- 0.95   # CI and PI level
BANDS_TI_CONTENT <- 0.95   # TI: share of months covered
BANDS_TI_CONF    <- 0.95   # TI: confidence in that coverage
BANDS_BOOT       <- 200L   # TI bootstrap histories
BANDS_BLOCK      <- 12L    # TI bootstrap block length (rows)
BANDS_NODES      <- 100L   # PI: quantile nodes for the line's uncertainty
BANDS_SEED       <- 20260925L  # fixed: a re-render of unchanged data gives an identical file
BANDS_GRID_TO    <- 2060   # last calendar year of the band grid
BANDS_STEP       <- 3L     # grid step in months
BANDS_SCHEMA     <- 1L

# S on the internal axis for theta = (a, k), a = log(-v1), k = v2.
.bands_S <- function(theta, z) 1 - exp(-exp(theta[1]) * z^theta[2])

# Rows exactly as fit_history() fits them, in time order.
.bands_rows <- function(df, t0) {
  d <- df[!is.na(df$year) & df$year >= t0 & is.finite(df$bev_share) & is.finite(df$overall), ]
  d[order(d$year), ]
}

# Standardised deviation: (y - S) / sqrt(S (1 - S)).
.bands_std <- function(y, S) (y - S) / sqrt(pmax(S * (1 - S), 1e-9))

# Covariance of theta_hat: B^-1 Omega B^-1 with AR(2)-prewhitened scores.
#   g_i = w_i J_i' r_i  (score of row i),  r_i = w_i (y_i - S_i),  w = TOTAL
#   u_i = g_i - a1 g_{i-1} - a2 g_{i-2}
#   Omega = sum(u u') * n/(n-2) / (1 - a1 - a2)^2
# a1, a2 are fitted to the standardised residuals; a1 + a2 clipped to [0, 0.98].
.bands_cov <- function(theta, z, y, w) {
  S <- .bands_S(theta, z)
  u <- exp(theta[1]) * z^theta[2]
  J <- cbind((1 - S) * u, (1 - S) * u * log(z))          # dS / d(a, k)
  ws <- w / mean(w)                                        # scale-free; avoids overflow
  Jw <- J * ws
  r <- (y - S) * ws
  Binv <- solve(crossprod(Jw))
  e <- .bands_std(y, S)
  n <- length(e)
  X <- cbind(e[2:(n - 1)], e[1:(n - 2)])
  a <- as.numeric(qr.solve(X, e[3:n]))
  s <- min(max(sum(a), 0), 0.98)
  g <- Jw * r
  U <- g[3:n, , drop = FALSE] - a[1] * g[2:(n - 1), , drop = FALSE] - a[2] * g[1:(n - 2), , drop = FALSE]
  omega <- crossprod(U) * n / (n - 2) / (1 - s)^2
  list(cov = Binv %*% omega %*% Binv, persistence = s, e = e)
}

# eta = a + k log z and its standard error at positions z.
.bands_eta <- function(theta, cov, z) {
  G <- cbind(1, log(z))
  list(eta = theta[1] + theta[2] * log(z),
       se  = sqrt(pmax(rowSums((G %*% cov) * G), 0)))
}

# Refit from a known start (bootstrap histories). Same objective as fit.R.
.bands_refit <- function(theta, z, y, w) {
  ws <- w / mean(w)
  rss <- function(p) sum(((y - .bands_S(c(p[1], exp(p[2])), z)) * ws)^2)
  o <- optim(c(theta[1], log(theta[2])), rss, method = "BFGS",
             control = list(maxit = 500, reltol = 1e-12))
  c(o$par[1], exp(o$par[2]))
}

# Moving-block bootstrap index of length n.
.bands_blocks <- function(n, L) {
  starts <- sample.int(n, ceiling(n / L) + 1L, replace = TRUE)
  idx <- as.vector(vapply(starts, function(s) ((s - 1L + 0:(L - 1L)) %% n) + 1L, integer(L)))
  idx[seq_len(n)]
}

# First calendar year at which `curve` (on grid `t`) reaches share p; NA if never.
.bands_cross <- function(t, curve, p) {
  i <- which(curve >= p)
  if (length(i)) t[i[1]] else NA_real_
}

# Main entry. df = the data frame render_country.R fits; fit = fit_history(df).
# Returns NULL when the fit has no usable S-shape (v1 >= 0, v2 <= 0, too few rows).
compute_bands <- function(df, fit) {
  v1 <- fit$v1; v2 <- fit$v2; t0 <- fit$t0
  if (!is.finite(v1) || !is.finite(v2) || v1 >= 0 || v2 <= 0) return(NULL)
  d <- .bands_rows(df, t0)
  if (nrow(d) < 12) return(NULL)
  origin <- t0 - 1                                         # z = x - (t0 - 1), as in fit.R
  z <- d$year - origin; y <- d$bev_share; w <- d$overall
  theta <- c(log(-v1), v2)
  S <- .bands_S(theta, z)
  cv <- .bands_cov(theta, z, y, w)
  q <- qnorm(1 - (1 - BANDS_LEVEL) / 2)

  # Grid: calendar years from the first data point to BANDS_GRID_TO.
  cal0 <- floor((min(d$year) + 1) * 12) / 12
  cal  <- seq(cal0, BANDS_GRID_TO, by = BANDS_STEP / 12)
  zg   <- cal - 1 - origin
  keep <- zg > 0; cal <- cal[keep]; zg <- zg[keep]
  fitg <- .bands_S(theta, zg)
  es   <- .bands_eta(theta, cv$cov, zg)
  f    <- function(v) 1 - exp(-exp(v))
  ci_lo <- f(es$eta - q * es$se); ci_hi <- f(es$eta + q * es$se)

  # PI: quantiles of S(eta_j) + sqrt(S_j(1-S_j)) * e over nodes j and deviations e.
  nodes <- qnorm((seq_len(BANDS_NODES) - 0.5) / BANDS_NODES)
  e <- cv$e
  pl <- (1 - BANDS_LEVEL) / 2
  pi_lo <- pi_hi <- numeric(length(zg))
  for (i in seq_along(zg)) {
    Sj <- f(es$eta[i] + es$se[i] * nodes)
    ys <- pmin(pmax(outer(Sj, rep(1, length(e))) + outer(sqrt(pmax(Sj * (1 - Sj), 0)), e), 0), 1)
    qq <- quantile(ys, c(pl, 1 - pl), names = FALSE, type = 7)
    pi_lo[i] <- qq[1]; pi_hi[i] <- qq[2]
  }

  # TI: block bootstrap. Each history b gives its own month distribution at t;
  # its (1-P)/2 and (1+P)/2 points are collected, and the band takes the
  # (1-gamma)/2 percentile of the lower points and (1+gamma)/2 of the upper.
  old_seed <- if (exists(".Random.seed", envir = globalenv())) get(".Random.seed", envir = globalenv()) else NULL
  set.seed(BANDS_SEED)
  on.exit(if (!is.null(old_seed)) assign(".Random.seed", old_seed, envir = globalenv()), add = TRUE)
  sd_i <- sqrt(pmax(S * (1 - S), 1e-9))
  pc <- (1 - BANDS_TI_CONTENT) / 2
  qlo <- qhi <- matrix(NA_real_, BANDS_BOOT, length(zg))
  for (b in seq_len(BANDS_BOOT)) {
    yb <- pmin(pmax(S + sd_i * e[.bands_blocks(length(e), BANDS_BLOCK)], 0), 1)
    thb <- tryCatch(.bands_refit(theta, z, yb, w), error = function(err) NULL)
    if (is.null(thb) || any(!is.finite(thb))) next
    eb <- .bands_std(yb, .bands_S(thb, z))
    ql <- quantile(eb, c(pc, 1 - pc), names = FALSE)
    Sb <- .bands_S(thb, zg); sb <- sqrt(pmax(Sb * (1 - Sb), 0))
    qlo[b, ] <- pmin(pmax(Sb + sb * ql[1], 0), 1)
    qhi[b, ] <- pmin(pmax(Sb + sb * ql[2], 0), 1)
  }
  ok <- rowSums(is.finite(qlo)) > 0
  gc <- (1 - BANDS_TI_CONF) / 2
  if (sum(ok) >= 50) {
    ti_lo <- apply(qlo[ok, , drop = FALSE], 2, quantile, probs = gc, names = FALSE)
    ti_hi <- apply(qhi[ok, , drop = FALSE], 2, quantile, probs = 1 - gc, names = FALSE)
  } else {
    # Too few histories refitted to trust a 95th percentile: no TI (JSON null),
    # CI and PI are still written.
    ti_lo <- ti_hi <- rep(NA_real_, length(zg))
  }

  # Nesting by definition: TI contains PI contains CI.
  pi_lo <- pmin(pi_lo, ci_lo); pi_hi <- pmax(pi_hi, ci_hi)
  ti_lo <- pmin(ti_lo, pi_lo); ti_hi <- pmax(ti_hi, pi_hi)

  # Crossing years (fit and CI) on a fine monthly grid to 2100.
  calf <- seq(cal0, 2100, by = 1 / 12); zf <- calf - 1 - origin
  kf <- zf > 0; calf <- calf[kf]; zf <- zf[kf]
  ef <- .bands_eta(theta, cv$cov, zf)
  Sf <- .bands_S(theta, zf); lf <- f(ef$eta - q * ef$se); hf <- f(ef$eta + q * ef$se)
  crossing <- lapply(c(0.1, 0.2, 0.5, 0.8, 0.9), function(p) list(
    share = p, fit = .bands_cross(calf, Sf, p),
    ci = c(.bands_cross(calf, hf, p), .bands_cross(calf, lf, p))))

  list(t = cal, fit = fitg, ci = list(ci_lo, ci_hi), pi = list(pi_lo, pi_hi),
       ti = list(ti_lo, ti_hi), crossing = crossing, persistence = cv$persistence,
       n = nrow(d), boot_ok = sum(ok), v1 = v1, v2 = v2, t0 = t0)
}

# Minimal JSON writer (base R only; the render workflow installs no jsonlite).
.json_num <- function(x, digits = 5) {
  ifelse(is.finite(x), formatC(round(x, digits), format = "fg", digits = 15, flag = ""), "null")
}
.json_arr <- function(x, digits = 5) paste0("[", paste(trimws(.json_num(x, digits)), collapse = ","), "]")
.json_str <- function(s) paste0('"', gsub('"', '\\\\"', gsub("\\\\", "\\\\\\\\", s)), '"')

write_bands_json <- function(path, b, country, variant, data_per) {
  if (is.null(b)) return(invisible(FALSE))
  cr <- vapply(b$crossing, function(c) sprintf('{"share":%s,"fit":%s,"ci":[%s,%s]}',
               .json_num(c$share, 2), trimws(.json_num(c$fit, 4)),
               trimws(.json_num(c$ci[1], 4)), trimws(.json_num(c$ci[2], 4))), character(1))
  body <- paste0(
    '{"schema":', BANDS_SCHEMA,
    ',"country":', .json_str(country), ',"variant":', .json_str(variant),
    ',"data_per":', .json_str(data_per),
    ',"method":{"doc":"docs/architecture/44-uncertainty-bands.md",',
    '"ci":{"level":', BANDS_LEVEL, ',"kind":"inverse-Hessian sandwich, AR(2)-prewhitened scores","pointwise":true},',
    '"pi":{"level":', BANDS_LEVEL, ',"kind":"CI line uncertainty + empirical monthly deviations","reference":"one row of the series cadence"},',
    '"ti":{"content":', BANDS_TI_CONTENT, ',"confidence":', BANDS_TI_CONF,
    ',"kind":"block bootstrap","histories":', b$boot_ok, ',"block":', BANDS_BLOCK, '}},',
    '"fit_params":{"v1":', trimws(formatC(b$v1, format = "e", digits = 12)),
    ',"v2":', trimws(.json_num(b$v2, 10)), ',"t0":', b$t0, '},',
    '"persistence":', trimws(.json_num(b$persistence, 3)), ',"rows":', b$n,
    ',"time":"calendar decimal year","t":', .json_arr(b$t, 4),
    ',"fit":', .json_arr(b$fit),
    ',"ci":[', .json_arr(b$ci[[1]]), ',', .json_arr(b$ci[[2]]), ']',
    ',"pi":[', .json_arr(b$pi[[1]]), ',', .json_arr(b$pi[[2]]), ']',
    ',"ti":[', .json_arr(b$ti[[1]]), ',', .json_arr(b$ti[[2]]), ']',
    ',"crossing":[', paste(cr, collapse = ","), ']}\n')
  dir.create(dirname(path), showWarnings = FALSE, recursive = TRUE)
  writeLines(body, path, sep = "", useBytes = TRUE)
  invisible(TRUE)
}
