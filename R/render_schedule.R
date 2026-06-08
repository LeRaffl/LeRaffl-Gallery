# render_schedule.R — baut schedule.html + schedule.ics aus den fetch-*.yml crons
# und gleicht mit manifest.json ab (was wurde wann wirklich gefetcht).
suppressPackageStartupMessages({
  library(yaml); library(jsonlite); library(stringr); library(lubridate); library(purrr)
})

FLAG <- c(
  austria="\U0001F1E6\U0001F1F9", brazil="\U0001F1E7\U0001F1F7", canada="\U0001F1E8\U0001F1E6",
  chile="\U0001F1E8\U0001F1F1", china="\U0001F1E8\U0001F1F3", colombia="\U0001F1E8\U0001F1F4",
  denmark="\U0001F1E9\U0001F1F0", finland="\U0001F1EB\U0001F1EE", ireland="\U0001F1EE\U0001F1EA",
  italy="\U0001F1EE\U0001F1F9", italy_rental="\U0001F1EE\U0001F1F9", japan="\U0001F1EF\U0001F1F5",
  luxembourg="\U0001F1F1\U0001F1FA", netherlands="\U0001F1F3\U0001F1F1", `new-zealand`="\U0001F1F3\U0001F1FF",
  portugal="\U0001F1F5\U0001F1F9", sweden="\U0001F1F8\U0001F1EA", turkey="\U0001F1F9\U0001F1F7",
  uruguay="\U0001F1FA\U0001F1FE", usa="\U0001F1FA\U0001F1F8", acea="\U0001F1EA\U0001F1FA"
)

LABEL <- c(
  austria="Austria", brazil="Brazil", canada="Canada", chile="Chile", china="China",
  colombia="Colombia", denmark="Denmark", finland="Finland", ireland="Ireland",
  italy="Italy", italy_rental="Italy (Rental)", japan="Japan", luxembourg="Luxembourg",
  netherlands="Netherlands",
  `new-zealand`="New Zealand", portugal="Portugal", sweden="Sweden", turkey="Turkey",
  uruguay="Uruguay", usa="USA", acea="ACEA (EU)"
)

# italy_rental erbt italy's cron-schedule, hat aber eigene Manifest-Einträge
SHARED_SCHEDULE <- list(italy_rental = "italy")

# ---- Cron-Parser -----------------------------------------------------------
parse_field <- function(field, lo, hi) {
  if (field == "*") return(lo:hi)
  parts <- strsplit(field, ",", fixed = TRUE)[[1]]
  out <- integer()
  for (p in parts) {
    if (grepl("-", p, fixed = TRUE)) {
      r <- as.integer(strsplit(p, "-", fixed = TRUE)[[1]])
      out <- c(out, r[1]:r[2])
    } else {
      out <- c(out, as.integer(p))
    }
  }
  sort(unique(out))
}

parse_cron <- function(expr) {
  f <- strsplit(trimws(expr), "\\s+")[[1]]
  if (length(f) != 5) return(NULL)
  list(
    minute = parse_field(f[1], 0, 59),
    hour   = parse_field(f[2], 0, 23),
    dom    = parse_field(f[3], 1, 31),
    month  = parse_field(f[4], 1, 12)
  )
}

# ---- Schedules aus Workflow-Dateien lesen ---------------------------------
read_schedules <- function(workflow_dir = ".github/workflows") {
  files <- list.files(workflow_dir, pattern = "^fetch-.+\\.yml$", full.names = TRUE)
  out <- list()
  for (f in files) {
    slug <- sub("^fetch-(.+)\\.yml$", "\\1", basename(f))
    y <- tryCatch(yaml::read_yaml(f), error = function(e) NULL)
    if (is.null(y)) next
    # `on:` wird von yaml manchmal als TRUE geparst (YAML-Bool)
    # yaml::read_yaml parst die `on:`-Key in GH-Workflows als Logical TRUE
    on_block <- y[["on"]]; if (is.null(on_block)) on_block <- y[["TRUE"]]
    sched <- on_block$schedule
    if (is.null(sched)) next
    crons <- map(sched, ~ parse_cron(.x$cron)) |> compact()
    if (length(crons) == 0) next
    out[[slug]] <- crons
  }
  # Sibling-Schedules anhängen (italy_rental erbt von italy)
  for (child in names(SHARED_SCHEDULE)) {
    parent <- SHARED_SCHEDULE[[child]]
    if (!is.null(out[[parent]])) out[[child]] <- out[[parent]]
  }
  out
}

# ---- Manifest: wann wurde tatsächlich gefetcht? ---------------------------
read_actual_fetches <- function(manifest_path = "manifest.json") {
  if (!file.exists(manifest_path)) return(list())
  m <- jsonlite::read_json(manifest_path, simplifyVector = TRUE)
  if (is.null(m$images) || nrow(m$images) == 0) return(list())
  df <- unique(m$images[, c("country_slug", "date")])
  df$date <- as.Date(df$date)
  split(df$date, df$country_slug)
}

# ---- Pro (slug, calendar_month): welche Tage hat cron + reale Fetches? ----
expand_for_month <- function(schedules, year, month) {
  days_in_month <- as.integer(format(
    as.Date(sprintf("%04d-%02d-01", year, month)) %m+% months(1) - days(1), "%d"
  ))
  out <- list()
  for (slug in names(schedules)) {
    rows <- list()
    for (cr in schedules[[slug]]) {
      if (!(month %in% cr$month)) next
      doms <- cr$dom[cr$dom <= days_in_month]
      for (d in doms) for (h in cr$hour) {
        rows[[length(rows) + 1]] <- list(day = d, hour = h, minute = min(cr$minute))
      }
    }
    if (length(rows) > 0) {
      df <- do.call(rbind, lapply(rows, as.data.frame))
      df <- df[!duplicated(df[, c("day", "hour", "minute")]), , drop = FALSE]
      df <- df[order(df$day, df$hour, df$minute), , drop = FALSE]
      out[[slug]] <- df
    }
  }
  out
}

# ---- Status pro Chip -------------------------------------------------------
# Status-Codes: "done", "today", "missed", "skip", "pending"
chip_status <- function(slug, day_date, hour, actual_fetches, today) {
  fetched_days <- actual_fetches[[slug]]
  fetched_this_month <- !is.null(fetched_days) &&
    any(format(fetched_days, "%Y-%m") == format(day_date, "%Y-%m"))
  on_this_day <- !is.null(fetched_days) && day_date %in% fetched_days

  if (on_this_day)              return("done")
  if (day_date == today)        return(if (fetched_this_month) "skip" else "today")
  if (day_date <  today) {
    return(if (fetched_this_month) "skip" else "missed")
  }
  # future
  if (fetched_this_month) "skip" else "pending"
}

# ---- HTML-Rendering --------------------------------------------------------
render_html <- function(year, month, schedules, actual_fetches, today = Sys.Date()) {
  month_start <- as.Date(sprintf("%04d-%02d-01", year, month))
  days_n <- as.integer(format(month_start %m+% months(1) - days(1), "%d"))
  # Monday-first; ISO wday: Mon=1..Sun=7
  first_wday <- as.integer(format(month_start, "%u"))
  lead_blanks <- first_wday - 1L

  per_slug <- expand_for_month(schedules, year, month)

  # Für jeden Tag: chips sammeln
  chips_for_day <- function(d) {
    day_date <- month_start + (d - 1)
    rows <- list()
    for (slug in names(per_slug)) {
      sub <- per_slug[[slug]][per_slug[[slug]]$day == d, , drop = FALSE]
      if (nrow(sub) == 0) next
      # innerhalb eines Slugs: nur erster Slot pro Tag als Chip
      r <- sub[1, ]
      st <- chip_status(slug, day_date, r$hour, actual_fetches, today)
      rows[[length(rows) + 1]] <- list(
        slug = slug, hour = r$hour, minute = r$minute, status = st
      )
    }
    # Sortieren nach Uhrzeit (top=früh, bottom=spät)
    if (length(rows) > 0) {
      rows <- rows[order(sapply(rows, function(x) x$hour * 60 + x$minute))]
    }
    rows
  }

  # Tile-HTML
  tile_html <- function(d) {
    day_date <- month_start + (d - 1)
    chips <- chips_for_day(d)
    is_today <- day_date == today
    cls <- c("day", if (day_date < today) "past", if (is_today) "today",
             if (day_date > today) "future")
    show_time <- length(chips) <= 4
    chip_html <- if (length(chips) == 0) "" else paste(map_chr(chips, function(c) {
      label <- LABEL[[c$slug]]; flag <- FLAG[[c$slug]] %||% "?"
      time_label <- sprintf("%02d:%02d", c$hour, c$minute)
      badge <- if (c$slug == "italy_rental") '<span class="rb">R</span>' else ""
      time_span <- if (show_time) sprintf('<span class="t">%s</span>', time_label) else ""
      sprintf(
        '<span class="chip s-%s" title="%s &middot; %s UTC">%s%s%s</span>',
        c$status, label, time_label, flag, badge, time_span
      )
    }), collapse = "")
    sprintf(
      '<div class="%s"><div class="dn">%d</div><div class="chips">%s</div></div>',
      paste(cls, collapse = " "), d, chip_html
    )
  }

  blanks <- paste(rep('<div class="day blank"></div>', lead_blanks), collapse = "")
  cells  <- paste(map_chr(1:days_n, tile_html), collapse = "")

  month_name <- format(month_start, "%B %Y")

  prev_m <- month_start %m-% months(1)
  next_m <- month_start %m+% months(1)
  nav_prev <- sprintf("schedule-%04d-%02d.html",
                      as.integer(format(prev_m, "%Y")), as.integer(format(prev_m, "%m")))
  nav_next <- sprintf("schedule-%04d-%02d.html",
                      as.integer(format(next_m, "%Y")), as.integer(format(next_m, "%m")))

  sprintf('<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Schedule &middot; %s</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; font-family:-apple-system,Segoe UI,Roboto,sans-serif;
         background:#0c0c0e; color:#eaeaea; padding:16px; }
  header { display:flex; align-items:center; justify-content:space-between;
           margin-bottom:12px; gap:12px; flex-wrap:wrap; }
  h1 { font-size:22px; margin:0; font-weight:600; }
  .nav a { color:#aaa; text-decoration:none; padding:4px 10px;
           border:1px solid #333; border-radius:6px; margin-left:4px; font-size:13px; }
  .nav a:hover { color:#fff; border-color:#666; }
  .grid { display:grid; grid-template-columns:repeat(7,1fr); gap:4px; }
  .dow { font-size:11px; text-transform:uppercase; color:#888;
         text-align:left; padding:4px 6px; letter-spacing:0.5px; }
  .day { background:#16161a; border:1px solid #222; border-radius:8px;
         min-height:96px; padding:6px; display:flex; flex-direction:column; gap:4px; }
  .day.blank { background:transparent; border:none; }
  .day.past { opacity:0.85; }
  .day.today { border-color:#d4a017; box-shadow:0 0 0 1px #d4a017; }
  .dn { font-size:12px; color:#777; font-weight:500; }
  .day.today .dn { color:#d4a017; }
  .chips { display:flex; flex-wrap:wrap; gap:3px; align-content:flex-start; }
  .chip { display:inline-flex; align-items:center; gap:3px;
          padding:1px 5px; border-radius:5px; font-size:13px; line-height:1.4;
          border:1px solid transparent; }
  .chip .t { font-size:10px; color:#999; font-variant-numeric:tabular-nums; }
  .chip .rb { font-size:8px; background:#444; color:#ddd; padding:0 3px;
              border-radius:3px; margin-left:-2px; }
  .s-done    { background:#1e3a24; border-color:#2d6b3a; }
  .s-today   { background:transparent; border-color:#d4a017; border-style:dashed; }
  .s-missed  { background:#3a1e1e; border-color:#6b2d2d; }
  .s-skip    { background:transparent; opacity:0.35; }
  .s-pending { background:transparent; border-color:#444; border-style:dashed; }
  .legend { font-size:11px; color:#777; margin-top:14px; display:flex; gap:14px;
            flex-wrap:wrap; }
  .legend .chip { font-size:11px; }
  @media (max-width:640px) {
    body { padding:8px; }
    .day { min-height:64px; padding:4px; }
    .chip { font-size:11px; padding:1px 3px; }
    .chip .t { display:none; }
    .dn { font-size:10px; }
  }
</style>
</head><body>
<header>
  <h1>%s</h1>
  <div class="nav">
    <a href="%s">&larr; prev</a>
    <a href="schedule.html">today</a>
    <a href="%s">next &rarr;</a>
    <a href="schedule.ics">.ics</a>
  </div>
</header>
<div class="grid">
  <div class="dow">Mo</div><div class="dow">Tu</div><div class="dow">We</div>
  <div class="dow">Th</div><div class="dow">Fr</div><div class="dow">Sa</div><div class="dow">Su</div>
  %s%s
</div>
<div class="legend">
  <span><span class="chip s-done">done</span> fetched</span>
  <span><span class="chip s-today">today</span> scheduled today</span>
  <span><span class="chip s-pending">pending</span> upcoming</span>
  <span><span class="chip s-skip">skip</span> already fetched, slot would re-run</span>
  <span><span class="chip s-missed">missed</span> slot passed, no fetch</span>
  <span style="margin-left:auto">generated %s UTC</span>
</div>
</body></html>',
    month_name, month_name, nav_prev, nav_next, blanks, cells,
    format(Sys.time(), tz = "UTC", "%Y-%m-%d %H:%M")
  )
}

`%||%` <- function(a, b) if (is.null(a) || length(a) == 0) b else a

# ---- iCal ------------------------------------------------------------------
render_ics <- function(year, month, schedules, n_months = 3) {
  lines <- c(
    "BEGIN:VCALENDAR", "VERSION:2.0",
    "PRODID:-//LeRaffl-Gallery//Schedule//EN",
    "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
    "X-WR-CALNAME:LeRaffl Fetch Schedule"
  )
  start <- as.Date(sprintf("%04d-%02d-01", year, month))
  end   <- start %m+% months(n_months)
  d <- start
  while (d < end) {
    y <- as.integer(format(d, "%Y")); m <- as.integer(format(d, "%m"))
    dd <- as.integer(format(d, "%d"))
    for (slug in names(schedules)) {
      for (cr in schedules[[slug]]) {
        if (!(m %in% cr$month)) next
        if (!(dd %in% cr$dom)) next
        for (h in cr$hour) {
          mn <- min(cr$minute)
          dt <- sprintf("%04d%02d%02dT%02d%02d00Z", y, m, dd, h, mn)
          uid <- sprintf("%s-%s@leraffl-gallery", slug, dt)
          lines <- c(lines,
            "BEGIN:VEVENT",
            paste0("UID:", uid),
            paste0("DTSTAMP:", format(Sys.time(), tz="UTC", "%Y%m%dT%H%M%SZ")),
            paste0("DTSTART:", dt),
            paste0("DURATION:PT15M"),
            paste0("SUMMARY:", LABEL[[slug]] %||% slug, " fetch"),
            "END:VEVENT"
          )
        }
      }
    }
    d <- d + 1
  }
  lines <- c(lines, "END:VCALENDAR")
  paste(lines, collapse = "\r\n")
}

# ---- Main ------------------------------------------------------------------
build_schedule <- function(out_html = "schedule.html", out_ics = "schedule.ics",
                           year = NULL, month = NULL) {
  today <- Sys.Date()
  if (is.null(year))  year  <- as.integer(format(today, "%Y"))
  if (is.null(month)) month <- as.integer(format(today, "%m"))

  schedules <- read_schedules()
  actual    <- read_actual_fetches()

  # Aktuellen Monat als schedule.html, plus prev/curr/next als datierte Aliase
  write(render_html(year, month, schedules, actual, today), out_html)

  for (off in -1:1) {
    d <- as.Date(sprintf("%04d-%02d-01", year, month)) %m+% months(off)
    y2 <- as.integer(format(d, "%Y")); m2 <- as.integer(format(d, "%m"))
    fn <- sprintf("schedule-%04d-%02d.html", y2, m2)
    write(render_html(y2, m2, schedules, actual, today), fn)
  }

  write(render_ics(year, month, schedules, n_months = 3), out_ics)
  invisible(TRUE)
}

if (sys.nframe() == 0 && !interactive()) {
  build_schedule()
}
