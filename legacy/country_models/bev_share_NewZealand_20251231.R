#### New Zealand: BEV share, trajectories, TTM etc. + auto‑publish to GitHub ####
country <- "New Zealand"

#### packages ####
#install.packages(c("emojifont","fs","gert","glue","readxl","dplyr","tidyr","reshape2","ggrepel","googlesheets4","scales","png","grid","ecb","tidyquant","patchwork","ggtext","lubridate","viridis","ggcorrplot","gridExtra"))

suppressPackageStartupMessages({
  library(fs); library(gert); library(glue)
  library(ggrepel); library(readxl); library(tidyr); library(dplyr)
  library(ggplot2); library(reshape2); library(xts); library(googlesheets4)
  library(scales); library(grid); library(png); library(ecb); library(tidyquant)
  library(patchwork); library(ggtext); library(lubridate); library(viridis)
  library(ggcorrplot); library(gridExtra); library(htmltools)
  library(fontawesome); library(emojifont)
  library(googlesheets4)
})

#### ---- helper: ggsave + copy to local repo + commit/push ---- ####
# einmalig für Git credentials weil er sonst 10 mal fragt
#install.packages("gitcreds")   # falls noch nicht da
library(gitcreds)
#gitcreds_set()                 # Token einfügen -> landet im macOS Schlüsselbund #

# vorher einmalig im terminal am mac laufen lassen zum speichern in keychain
#git config --global credential.helper osxkeychain
#git config --global user.name  "LeRaffl"
#git config --global user.email "raphael.wellmann@me.com"

# nicht einmalig
#### ==== GLOBAL GIT/PATH CONFIG (einmal anpassen) ==== ####
repo_dir_local <- "/Users/leraffl/Projects/GitHub/LeRaffl-Gallery"         # <- lokales Clone-Verzeichnis
repo_branch    <- "master"                          # oder "main"
#url_https      <- "https://github.com/LeRaffl/LeRaffl-Gallery.git"
url_https      <- "git@github.com:LeRaffl/LeRaffl-Gallery.git"
params_path <- file.path(repo_dir_local, "params.csv")

ensure_remote <- function(repo_dir = repo_dir_local,
                          remote   = "origin",
                          url      = url_https,
                          branch   = repo_branch){
  if (!fs::dir_exists(repo_dir)) stop("repo_dir_local existiert nicht: ", repo_dir)
  rems <- tryCatch(gert::git_remote_list(repo = repo_dir)$name, error = function(e) character(0))
  if ("origin" %in% rems) {
    try(gert::git_remote_set_url(remote, url, repo = repo_dir), silent = TRUE)
  } else {
    gert::git_remote_add(remote, url, repo = repo_dir)
  }
  try(gert::git_branch_checkout(branch, repo = repo_dir), silent = TRUE)
  invisible(TRUE)
}
ensure_remote(repo_dir_local)


# Kontrolle
git_remote_list(repo = repo_dir_local)



# Einmal pro Session laden. Speichert weiter in iCloud UND zusätzlich ins lokal geklonte Repo.
# Überschreibt vorhandene Dateien gleichen Namens, committet nur echte Änderungen und pusht.

# nimmt den letzten verfügbaren Monats-Zeitraum aus deinem Sheet
detect_period_from_data <- function(df) {
  # bevorzugt YYYYMMM (z.B. "2025M08")
  if ("YYYYMMM" %in% names(df)) {
    v <- df$YYYYMMM[!is.na(df$YYYYMMM)]
    if (length(v)) return(sub("M", "-", tail(v, 1)))
  }
  # Fallback: numerische year-Spalte (Jahresbruchteil)
  if ("year" %in% names(df)) {
    y <- tail(df$year, 1); yr <- floor(y); mo <- floor(12 * (y - yr)) + 1
    return(sprintf("%04d-%02d", yr, mo))
  }
  # absolute Notlösung: heute (sollte eigentlich nie nötig sein)
  format(Sys.Date(), "%Y-%m")
}

library(gert)

ggsave_git <- function(
    filename,
    plot,
    path_icloud,
    repo_dir = repo_dir_local,
    period,
    width,
    height,
    units = "in",
    dpi = 300,
    bg = "white",
    wait_seconds = 5
) {
  path_icloud <- path.expand(path_icloud)
  dir.create(path_icloud, recursive = TRUE, showWarnings = FALSE)
  
  icloud_file <- file.path(path_icloud, filename)
  
  ggplot2::ggsave(
    filename = icloud_file,
    plot = plot,
    width = width,
    height = height,
    units = units,
    dpi = dpi,
    bg = bg
  )
  
  ## ---- WARTEN BIS DATEI STABIL IST ----
  for (i in seq_len(wait_seconds * 10)) {
    if (file.exists(icloud_file) && file.size(icloud_file) > 10000) break
    Sys.sleep(0.1)
  }
  
  if (!file.exists(icloud_file) || file.size(icloud_file) <= 10000) {
    stop("iCloud file not ready or empty: ", icloud_file)
  }
  
  ## ---- INS REPO KOPIEREN ----
  dest_dir <- file.path(normalizePath(repo_dir), "images", period)
  dir.create(dest_dir, recursive = TRUE, showWarnings = FALSE)
  
  repo_file <- file.path(dest_dir, filename)
  file.copy(icloud_file, repo_file, overwrite = TRUE)
}






retry_push <- function(repo, branch, tries = 3) {
  for (i in seq_len(tries)) {
    ok <- TRUE
    tryCatch({
      try(gert::git_fetch(repo = repo), silent = TRUE)
      ub <- paste0("origin/", branch)
      ab <- try(gert::git_ahead_behind(repo = repo, ref = branch, upstream = ub), silent = TRUE)
      if (!inherits(ab, "try-error") && ab$behind > 0) {
        tryCatch(
          gert::git_pull(repo = repo, rebase = TRUE),
          error = function(e) { try(gert::git_rebase_abort(repo = repo), silent = TRUE); gert::git_pull(repo = repo, rebase = FALSE) }
        )
      }
      gert::git_push(repo = repo, set_upstream = TRUE)
    }, error = function(e) { ok <<- FALSE })
    if (ok) return(invisible(TRUE))
    Sys.sleep(2 * i)  # 2s, 4s, 6s
  }
  stop("Push nach mehreren Versuchen fehlgeschlagen.")
}



# function to commit and push
commit_and_push <- function(msg = "Auto-publish charts",
                            repo = repo_dir_local,
                            branch = repo_branch,
                            remote = "origin") {
  try({
    if (!(branch %in% gert::git_branch_list(repo = repo)$name))
      gert::git_branch_create(branch, repo = repo)
    gert::git_branch_checkout(branch, repo = repo)
  }, silent = TRUE)
  
  st <- gert::git_status(repo = repo)
  if (nrow(st)) {
    # nur images/ und params.csv mitnehmen
    take <- st$file[ grepl("^images/", st$file) | st$file %in% c("params.csv","weights.csv") ]
    if (length(take)) {
      gert::git_add(take, repo = repo)
      # nur committen, wenn jetzt wirklich staged
      if (nrow(gert::git_status(repo = repo)) > 0) {
        gert::git_commit(msg, repo = repo)
      }
    }
  } else {
    message("Nichts zu committen.")
  }
  
  retry_push(repo, branch)
  invisible(TRUE)
}



safe_commit_and_push <- function(msg = "Auto-publish charts",
                                 repo = repo_dir_local,
                                 branch = repo_branch,
                                 remote = "origin") {
  commit_and_push(msg, repo, branch, remote)
}


#### set up icons for caption with social media ####
font_brands <- "/Users/leraffl/Projects/bev_assets/fonts/fontawesome/otfs/Font-Awesome-6-Brands-Regular-400.otf"
font_custom <- "/Users/leraffl/Projects/bev_assets/fonts/fontawesome/otfs/icomoon.ttf"

add_safe_font <- function(family, path) {
  if (file.exists(path)) {
    try(sysfonts::font_add(family = family, regular = path), silent = TRUE)
  } else {
    warning("Font file not found: ", path)
  }
}

add_safe_font("Font Awesome 6 Brands", font_brands)
add_safe_font("CustomIcons",          font_custom)

if (any(file.exists(c(font_brands, font_custom)))) {
  showtext::showtext_auto()
}

x_icon <- "&#xe61b"; x_username <- "leraffl"
bluesky_icon <- "&#xe671"; bluesky_username <- "leraffl.bsky.social "
buy_me_a_coffee_icon <- "&#xe900"; buy_me_a_coffee_username <- "leraffl"

social_caption <- glue::glue(
  "<span style='font-family:\"CustomIcons\";'>{buy_me_a_coffee_icon};</span>",
  "<span style='font-family:\"Font Awesome 6 Brands\";'>{x_icon};</span> <span style='color: #000000'>{x_username}</span>",
  strrep(" ", 4),
  "<span style='font-family:\"Font Awesome 6 Brands\";'>{bluesky_icon};</span> <span style='color: #000000'>{bluesky_username}</span>"
)


flag_path <- "/Users/leraffl/Projects/bev_assets/flags/newzealand.png"
flag_img  <- readPNG(flag_path)
flag_base64 <- base64enc::dataURI(file = flag_path)

#### read data ####
# googlesheets4::gs4_deauth(); googlesheets4::gs4_auth()
data_newzealand <- read_sheet("https://docs.google.com/spreadsheets/d/1tT_Ja3de_S528_JeSBkj74q-lfEIekE5-GRm9_pWgUo/", sheet = "New Zealand")
source <- data_newzealand$Source[1]
entire_caption <- paste0(social_caption, " | \t ", Sys.Date(), "  | \t    Source: ", source)

# if we work with the ACEA Google Sheets we need to rename cuz headers are different
# comment this out if not ACEA file
#data_newzealand$BEV <- data_newzealand$`Electric/zero-emission`
#data_newzealand$PHEV <- data_newzealand$Hybrid
#data_newzealand$TOTAL <- data_newzealand$overall
#data_newzealand$OTHERS <- data_newzealand$`Other fuel`
#data_newzealand$TOTAL - data_newzealand$BEV - data_newzealand$PHEV <- data_newzealand$Fossil

data_newzealand$`Electric/zero-emission` <- data_newzealand$BEV
data_newzealand$Hybrid <- data_newzealand$PHEV
data_newzealand$overall <- data_newzealand$TOTAL
data_newzealand$`Other fuel` <- data_newzealand$OTHERS
data_newzealand$Fossil <- data_newzealand$TOTAL - data_newzealand$BEV - data_newzealand$PHEV


data_newzealand$bev_share   <- data_newzealand$`Electric/zero-emission`/data_newzealand$overall
data_newzealand$ice_share   <- data_newzealand$Fossil/data_newzealand$overall
data_newzealand$hybrid_share<- data_newzealand$Hybrid/data_newzealand$overall
data_newzealand$other_share <- data_newzealand$`Other fuel`/data_newzealand$overall
# pure ICE ohne HEV-Abzug (deine Wahl)
data_newzealand$pure_ICE    <- (data_newzealand$Fossil)/data_newzealand$overall

lastyearly <- ceiling(max(subset(data_newzealand, data_newzealand$time_interval=="yearly")$year))

#### trailing 12 months data and plot ####
data_newzealand_monthly <- subset(data_newzealand, data_newzealand$time_interval=="monthly")
data_newzealand_monthly <- subset(data_newzealand_monthly, data_newzealand_monthly$year>=min(data_newzealand_monthly$year+1))
TTM_shares_newzealand <- data.frame(
  month = format(seq.Date(from = as.Date(paste0(floor(min(data_newzealand_monthly$year)+1),"-01-01")), by = "month", length.out = nrow(data_newzealand_monthly)), "%Y-%m"),
  Other = data_newzealand_monthly$`Other TTM`,
  #`ICE` = data_newzealand_monthly$`ICE TTM`,#-data_newzealand_monthly$`HEV TTM`,
  Petrol = data_newzealand_monthly$`Petrol TTM`,
  Diesel = data_newzealand_monthly$`Diesel TTM`,
  #Ethanol = data_newzealand_monthly$`Ethanol TTM`,
  #FlexFuel = data_newzealand_monthly$`FlexFuel TTM`,
  HEV = data_newzealand_monthly$`HEV TTM`,
  PHEV = data_newzealand_monthly$`PHEV TTM`,
  BEV = data_newzealand_monthly$`BEV TTM`
)

colnames(TTM_shares_newzealand)[colnames(TTM_shares_newzealand) == "HEV.Petrol"]   <- "HEV Petrol"
colnames(TTM_shares_newzealand)[colnames(TTM_shares_newzealand) == "HEV.Diesel"]   <- "HEV Diesel"
colnames(TTM_shares_newzealand)[colnames(TTM_shares_newzealand) == "PHEV.Petrol"]  <- "PHEV Petrol"
colnames(TTM_shares_newzealand)[colnames(TTM_shares_newzealand) == "PHEV.Diesel"]  <- "PHEV Diesel"
colnames(TTM_shares_newzealand)[colnames(TTM_shares_newzealand) == "ICE..excl..HEV."] <- "ICE (excl. HEV)"

TTM_shares_newzealand_long <- TTM_shares_newzealand %>%
  pivot_longer(cols = c("Other", 
                        #"ICE", 
                        #"FlexFuel",
                        "Petrol", "Diesel", 
                        "HEV", 
                        "PHEV", "BEV"),
               names_to = "type", values_to = "value") %>%
  mutate(type = factor(type, levels = c("Other", 
                                        #"ICE", 
                                        #"FlexFuel",
                                        "Petrol", "Diesel", 
                                        "HEV", 
                                        "PHEV", "BEV"))) %>%
  filter(!is.na(value)) %>%
  mutate(numeric_month = as.numeric(as.factor(month)))

TTM_barplot_newzealand <- ggplot(TTM_shares_newzealand_long, aes(x = month, y = value, fill = type)) +
  geom_bar(stat = "identity", position = "stack", width = 1) +
  geom_vline(
    data = TTM_shares_newzealand_long %>% filter(substr(month, 6, 7) == "01") %>% distinct(numeric_month),
    aes(xintercept = numeric_month-0.5), color = "gray40", linetype = "dashed"
  ) +
  geom_hline(yintercept = c(0.25, 0.5, 0.75), color = "gray40", linetype = "dashed") +
  scale_x_discrete(
    breaks = TTM_shares_newzealand_long$month[substr(TTM_shares_newzealand_long$month, 6, 7) == "01"],
    labels = function(x) format(as.Date(paste0(x, "-01")), "%b %Y")
  ) +
  scale_y_continuous(labels = scales::percent_format(scale = 100), expand = c(0, 0),
                     sec.axis = sec_axis(~ ., name = "Trailing 12 Months Market Share",
                                         labels = scales::percent_format(scale = 100))) +
  scale_fill_viridis_d(name = "Fuel Type", option = "H", direction=-1) +
  labs(title = "12-Month Trailing Market Shares by Fuel Type in New Zealand",
       y = "Trailing 12 Months Market Share", x = "Jahre", caption = entire_caption) +
  theme_minimal() +
  theme(axis.text.x = element_text(angle = 45, hjust = 1), axis.title.x = element_blank(),
        plot.title = element_text(size = 14, face = "bold"),
        legend.position = c(0.05, 0.95), legend.justification = c(0, 1),
        legend.background = element_rect(fill = "white", color = "gray90", size = 0.5),
        legend.key = element_rect(fill = NA, color = NA), legend.key.height = unit(0.2, "cm"),
        plot.caption = element_markdown(hjust=0))

print(TTM_barplot_newzealand)

#### regression setup ####
verschiebung <- floor(min(na.omit(data_newzealand$year)))
extrapol <- 2200
data_newzealand <- subset(data_newzealand, data_newzealand$year>=verschiebung)
confidence_level <- 0.999
alpha <- 1-confidence_level
z <- qnorm(1-alpha/2)
default_size <- 2

reg <- function(v, x, type="BEV"){
  if (type == "ICE") return(1-(1-exp(v[1]*(x-(verschiebung-1))^v[2])))
  if (type == "BEV") return(1-exp(v[1]*(x-(verschiebung-1))^v[2]))
  if (type == "BEV extended") return(v[3]-exp(v[1]*(x-(verschiebung-1))^v[2]) + ((1-v[3])-exp(v[4]*(x-(verschiebung-1))^v[5])+v[3]) + (1-v[3]))
  stop("Unknown type")
}
RSS <- function(v, type="BEV"){ forecast <- reg(v, BEV$x, type); residuals <- BEV$y-forecast; sum((residuals*data_newzealand$overall)^2) }
reg_ice <- function(v, x, type="ICE"){ if (type=="ICE") return(1-(1-1*exp(v[1]*(x-(verschiebung-1))^v[2]))) else if (type=="BEV") return((0.98-exp(v[1]*(x-(verschiebung-1))^v[2]))) else stop("Unknown type") }
RSS_ice <- function(v, type="ICE"){ forecast <- reg_ice(v, ICE$x, type); residuals <- ICE$y-forecast; sum((residuals*data_newzealand$overall)^2) }

bev_time <- ice_time <- seq(0,0,length=length(data_newzealand$`Electric/zero-emission`))
for(i in 1:length(data_newzealand$`Electric/zero-emission`)){
  data_newzealand_looped <- data_newzealand[1:i,]
  xg<-data_newzealand_looped$year; yg<-as.double(data_newzealand_looped$bev_share)
  BEV <- data.frame(x=xg,y=yg)
  control <- list(maxit = 100000, reltol=10^-30)
  res <- optim(par=c(-0.1, 4), fn=RSS, control=control)
  xg <- seq(verschiebung, extrapol, by=1/12); yg <- reg(v=res$par,xg); B <- data.frame(x=xg,BEV=yg)
  se <- sd(BEV$y)/sqrt(length(BEV$y)); shape_lo <- res$par[2]-z*se; shape_up <- res$par[2]+z*se; scale_lo <- res$par[1]-z*se*res$par[1]; scale_up <- res$par[1]+z*se*res$par[1]
  xg <- seq(verschiebung, extrapol, by=1/12); B$BEV_lower <- reg(v=c(scale_lo,shape_lo),xg); B$BEV_upper <- reg(v=c(scale_up,shape_up),xg)
  
  xg<-data_newzealand_looped$year; yg<-as.double(data_newzealand_looped$ice_share); ICE <- data.frame(x=xg,y=yg)
  res_ice <- optim(par=c(-0.1, 4), fn=RSS_ice, control=control)
  xg <- seq(verschiebung, extrapol, by=1/12); B$ICE <- reg_ice(v=res_ice$par,xg, type="ICE")
  se <- sd(ICE$y)/sqrt(length(ICE$y)); weibull_lo <- res_ice$par[2]-z*se; weibull_up <- res_ice$par[2]+z*se
  xg <- seq(verschiebung, extrapol, by=1/12); B$ICE_upper <- reg_ice(v=c(res_ice$par[1], weibull_lo), xg)
  xg <- seq(verschiebung, extrapol, by=1/12); B$ICE_lower <- reg_ice(v=c(res_ice$par[1], weibull_up), xg)
  
  B$Hybrid <- 1-B$BEV-B$ICE
  B$Hybrid_upper <- 1- B$BEV_lower - B$ICE_lower
  B$Hybrid_lower <- 1- B$BEV_upper - B$ICE_upper
  
  Hybrid <- BEV; Hybrid$y <- 1 - BEV$y - ICE$y
  
  newzealand <- data.frame(B, "Type"="New Registrations")
  new_A <- data.frame(BEV, Type="New Registrations", Quarter=BEV$x)
  new_A$Quarter <- ifelse(new_A$x%%1 <0.999, "Q4", new_A$Quarter)
  new_A$Quarter <- ifelse(new_A$x%%1 <0.668, "Q3", new_A$Quarter)
  new_A$Quarter <- ifelse(new_A$x%%1 <0.418, "Q2", new_A$Quarter)
  new_A$Quarter <- ifelse(new_A$x%%1 <0.168, "Q1", new_A$Quarter)
  new_A$Quarter <- ifelse(new_A$x <= lastyearly, "Yearly", new_A$Quarter)
  new_A$overall <- data_newzealand_looped$overall; new_A$time_interval <- data_newzealand_looped$time_interval
  
  newzealand$Hybrid       <- pmax(newzealand$Hybrid, 0)
  newzealand$Hybrid_upper <- pmax(newzealand$Hybrid_upper, 0)
  newzealand$Hybrid_lower <- pmax(newzealand$Hybrid_lower, 0)
  
  time_80_newzealand <- max(subset(newzealand, newzealand$BEV<=0.8 & newzealand$BEV >= 0.2)$x)
  time_50_newzealand <- max(subset(newzealand, newzealand$BEV<=0.5 & newzealand$BEV >= 0.2)$x)
  time_20_newzealand <- max(subset(newzealand, newzealand$BEV<=0.2 & newzealand$BEV >= 0.1)$x)
  time_20_to_80_newzealand <- max(subset(newzealand, newzealand$BEV<=0.8 & newzealand$BEV >= 0.2)$x)-min(subset(newzealand, newzealand$BEV<=0.8 & newzealand$BEV >= 0.2)$x)
  time_80_to_20_newzealand <- max(subset(newzealand, newzealand$ICE<=0.8 & newzealand$ICE >= 0.2)$x)-min(subset(newzealand, newzealand$ICE<=0.8 & newzealand$ICE >= 0.2)$x)
  bev_time[i] <- time_20_to_80_newzealand; ice_time[i] <- time_80_to_20_newzealand
}

timer_newzealand <- data.frame("year"=data_newzealand[1:length(bev_time),]$year, "BEV_time"=bev_time, "ICE_time"=ice_time)
last_inf_index <- max(c(which(timer_newzealand$BEV_time == -Inf), which(timer_newzealand$ICE_time == -Inf)), na.rm = TRUE)
if (!is.finite(last_inf_index)) last_inf_index <- 0
# DataFrame ab dem letzten -Inf-Wert kürzen, und 12 Monate später
if (nrow(timer_newzealand) > (last_inf_index + 12)) {
  timer_newzealand_short <- timer_newzealand[(last_inf_index + 1 + 12):nrow(timer_newzealand), ]
} else {
  timer_newzealand_short <- timer_newzealand
}

#### Charts: timer ####
data_month <- (as.integer(((BEV$x %% 1) * 12 + 1)[length(BEV$x)]) + 1) %% 12
theme_set(theme_minimal(base_size = 14))

plot_timer <- ggplot(timer_newzealand_short, aes(x = year)) +
  geom_line(aes(y = BEV_time, col = "BEV share to rise from 20% to 80% market share"), lwd = 1) +
  geom_line(aes(y = ICE_time, col = "ICE share to fall from 80% to 20% market share"), lwd = 1) +
  #geom_step(aes(y = ECB_rate * 250, col = "ECB interest rate"), lwd = 1) +
  #geom_step(aes(y = FED_rate * 250, col = "FED interest rate"), lwd = 1) +
  
  scale_x_continuous(
    breaks = seq(verschiebung, extrapol, 1),
    labels = function(x) paste0("Jan ", x + 1)
  ) +
  
  scale_y_continuous(
    name = "Number of years expected",
    limits = c(0, timer_newzealand_short$BEV_time[length(timer_newzealand_short$BEV_time)]*2)
  ) +
  
  labs(
    title = "Time expectation for New Zealand transition time using historical data",
    subtitle = "Each point in time marks what the expectation was at the time",
    caption = social_caption,
    x = " "
  ) +
  
  theme_minimal() +
  
  scale_color_manual(
    values = c("#33FF3B", "darkblue", "lightblue", "#FF5733"),
    name = "expected time for"
  ) +
  
  theme(
    # Titel & Untertitel
    plot.title = element_text(face = "bold", size = rel(1.5)),
    plot.subtitle = element_text(size = rel(1.2), color = "black", lineheight = 0.3),
    
    # Achsen
    axis.text = element_text(size = rel(0.9)),
    axis.title = element_text(size = rel(1.1)),
    
    # Legende
    legend.position = "bottom",
    legend.direction = "horizontal",
    legend.title = element_text(size = rel(1.1)),
    legend.text = element_text(size = rel(1)),
    legend.key.width = unit(0.6, "cm"),
    legend.key.height = unit(0.6, "cm"),
    
    # Caption
    plot.caption = element_markdown(hjust = 0, size = rel(0.9))
  )

current_year <- as.numeric(format(Sys.Date(), "%Y"))

plot_timer <- plot_timer +
  annotation_custom(
    grob = rasterGrob(as.raster(flag_img), interpolate = TRUE),
    xmin = current_year + data_month / 12 - 1.5,
    ymax = 0.3*timer_newzealand_short$BEV_time[length(timer_newzealand_short$BEV_time)]*2,
    ymin = 0
  )

plot_timer

#### Chart: BEV trajectory ####
theme_set(theme_minimal(base_size = 14))
plot_newzealand <- ggplot(newzealand, aes(x = x, y = BEV, color = Type)) +
  geom_ribbon(aes(ymin = BEV_lower, ymax = BEV_upper), fill = "grey", alpha = 0.5, color = NA) +
  geom_line(lwd = 1) + ylim(0, 1.1) +
  geom_point(data = new_A, aes(x = x, y = y, color = Quarter), size=default_size+(new_A$overall-mean(new_A$overall))/(sd(new_A$overall)) ) +
  scale_x_continuous(breaks = seq(2010, extrapol, ifelse(extrapol>2045,4,2)), labels = function(x) paste0("Jan ", x + 1), limits=c(2010, min(extrapol, 2045))) +
  scale_y_continuous(breaks = seq(0, 1, 0.1), labels = unit_format(unit = "%", scale = 1e2)) +
  labs(title = "BEV share in new registrations in New Zealand - an Extrapolation",
       subtitle = paste0("expected time for BEV to rise from 20% to 80%: ",
                         floor(time_20_to_80_newzealand), " years ", round(12*(time_20_to_80_newzealand-floor(time_20_to_80_newzealand)),0), " months"),
       caption = entire_caption, x = " ", y = "BEV share") +
  theme_minimal() +
  theme(legend.position = c(0.93, 0.60), legend.background = element_rect(fill = "gray99"),
        plot.title = element_text(face = "bold", size = rel(1.5)),
        plot.subtitle = element_text(size = rel(1.2)),
        legend.text = element_text(size = rel(1)),
        axis.text = element_text(size = rel(0.9)),
        plot.caption = element_markdown(hjust=0)  # Caption als Markdown/HTML interpretieren # hjust=1 heißt rechtsbündig
  ) +
  scale_color_manual(values = c("#FF5733", "#FFC300", "#33FF3B", "#33A1FF", "#B633FF", "#FF33E9"), name = "Color")

plot_newzealand <- plot_newzealand + annotate("text", x=2010, y=1, label="New Registration estimates in", size=rel(6),hjust=0, vjust=1, col="red")
counter <- 0
while(round(subset(newzealand, newzealand$x==2024+counter & newzealand$Type=="New Registrations")$BEV*100, 1) < 100 & 1-0.05*(counter+1)>0.1){
  plot_newzealand <- plot_newzealand + annotate("text", x=2010+0.5, y=1-0.05*(counter+1),
                                        label=paste0("Jan ",2025+counter,": ",round(subset(newzealand, newzealand$x==2024+counter & newzealand$Type=="New Registrations")$BEV*100, 1),"%"),
                                        size=rel(5),hjust=0, vjust=1, col="red")
  counter <- counter+1
}
plot_newzealand <- plot_newzealand + annotation_custom(grob = rasterGrob(as.raster(flag_img), interpolate = TRUE,
                                                                 width = unit(1*1920/1280
                                                                              ,"in"), height = unit(1, "in")), xmin = min(extrapol-4, 2045-4), ymin=-0.9)
plot_newzealand

#### Chart: ICE/BEV/PHEV ####
ICE <- data.frame(ICE, "overall"=data_newzealand$overall)
BEV <- data.frame(BEV, "overall"=data_newzealand$overall)
Hybrid <- data.frame(Hybrid, "overall"=data_newzealand$overall)

theme_set(theme_minimal(base_size = 14))

plot_ICE_BEV_newzealand <- ggplot(newzealand, aes(x = x, y = BEV, color = Type)) +
  
  # BEV
  geom_ribbon(aes(ymin = BEV_lower, ymax = BEV_upper), fill = "green", alpha = 0.5, color = NA) +
  geom_line(aes(y = BEV, color = "BEV", shape = "BEV"), lwd = 1) +
  geom_point(
    data = BEV,
    aes(x = x, y = y, color = "BEV", shape = "BEV"),
    size = default_size + (BEV$overall - mean(BEV$overall)) / sd(BEV$overall)
  ) +
  
  # ICE
  geom_ribbon(aes(ymin = ICE_lower, ymax = ICE_upper), fill = "red", alpha = 0.5, color = NA) +
  geom_line(aes(y = ICE, color = "ICE", shape = "ICE"), lwd = 1) +
  geom_point(
    data = ICE,
    aes(x = x, y = y, color = "ICE", shape = "ICE"),
    size = default_size + (ICE$overall - mean(ICE$overall)) / sd(ICE$overall)
  ) +
  
  # Hybrid / PHEV
  geom_ribbon(aes(ymin = Hybrid_lower, ymax = Hybrid_upper), fill = "blue", alpha = 0.5, color = NA) +
  geom_line(aes(y = Hybrid, color = "PHEV", shape = "PHEV"), lwd = 1) +
  geom_point(
    data = data_newzealand,
    aes(x = year, y = hybrid_share, color = "PHEV", shape = "PHEV"),
    size = default_size + (Hybrid$overall - mean(Hybrid$overall)) / sd(Hybrid$overall)
  ) +
  
  ylim(0, 1.1) +
  scale_x_continuous(
    breaks = seq(2006, extrapol, ifelse(extrapol > 2045, 4, 2)),
    labels = function(x) paste0("Jan ", x + 1),
    limits = c(2010, min(extrapol, 2045))
  ) +
  scale_y_continuous(
    breaks = seq(0, 1, 0.1),
    labels = unit_format(unit = "%", scale = 1e2)
  ) +
  
  labs(
    title = "BEV / ICE / PHEV share of new registrations in New Zealand - an Extrapolation",
    subtitle = paste0(
      "expected time for ICE to drop from 80% to 20%: ",
      floor(time_80_to_20_newzealand), " years ",
      round(12 * (time_80_to_20_newzealand - floor(time_80_to_20_newzealand)), 0),
      " months"
    ),
    caption = entire_caption,
    x = " ",
    y = "New Registration Share"
  ) +
  
  theme(
    # Achsen
    axis.title = element_text(size = rel(1.2)),
    axis.text  = element_text(size = rel(0.9)),
    
    # Titel
    plot.title = element_text(face = "bold", size = rel(1.5)),
    plot.subtitle = element_text(size = rel(1.2)),
    
    # Legende
    legend.position = c(0.93, 0.68),
    legend.background = element_rect(fill = "gray99"),
    legend.title = element_text(size = rel(1)),
    legend.text = element_text(size = rel(0.9)),
    
    # Caption
    plot.caption = element_markdown(hjust = 0, size = rel(0.9))
  ) +
  
  scale_color_manual(
    name = "Legend",
    breaks = c("ICE", "BEV", "PHEV"),
    values = c("ICE" = "red", "BEV" = "green", "PHEV" = "blue")
  ) +
  
  scale_shape_manual(
    name = "Legend",
    breaks = c("ICE", "BEV", "PHEV"),
    values = c("ICE" = 15, "BEV" = 16, "PHEV" = 23)
  )




# --- Jahres-Textblock (standardisiert) ---

plot_ICE_BEV_newzealand <- plot_ICE_BEV_newzealand +
  annotate(
    "text",
    x = 2010,
    y = 0.9,
    label = "New ICE in",
    size = rel(6),
    hjust = 0,
    vjust = 1,
    col = "red"
  )

counter <- 0
while (
  5 < round(subset(newzealand, newzealand$x == 2024 + counter - 1 & newzealand$Type == "New Registrations")$ICE * 100, 1) &
  1 - 0.05 * (counter + 1) > 0.1
) {
  plot_ICE_BEV_newzealand <- plot_ICE_BEV_newzealand +
    annotate(
      "text",
      x = 2010 + 0.5,
      y = 0.85 - counter * 0.05,
      label = paste0(
        "Jan ", 2024 + counter + 1, ": ",
        round(subset(newzealand, newzealand$x == 2024 + counter & newzealand$Type == "New Registrations")$ICE * 100, 1), "%"
      ),
      size = rel(5),
      hjust = 0,
      vjust = 1,
      col = "red"
    )
  
  counter <- counter + 1
}

# Flag (auf inches umgestellt, nicht cm)
plot_ICE_BEV_newzealand <- plot_ICE_BEV_newzealand +
  annotation_custom(
    grob = rasterGrob(as.raster(flag_img), interpolate = TRUE,
                      width = unit(1.5, "in"),
                      height = unit(1, "in")),
    xmin = min(extrapol - 4, 2045 - 4),
    ymin = -0.9
  )

# ---------- Helfer für updates in weights.csv ------------
compute_weight_from_data <- function(df) {
  last <- df |> dplyr::arrange(year) |> dplyr::slice_tail(n = 1)
  ti   <- last$time_interval[[1]]
  
  if (ti == "monthly") {
    return(
      df |>
        dplyr::filter(time_interval == "monthly") |>
        dplyr::slice_tail(n = 12) |>
        dplyr::summarise(w = sum(overall, na.rm = TRUE)) |>
        dplyr::pull(w)
    )
  }
  
  if (ti == "quarterly") {
    return(
      df |>
        dplyr::filter(time_interval == "quarterly") |>
        dplyr::slice_tail(n = 4) |>
        dplyr::summarise(w = sum(overall, na.rm = TRUE)) |>
        dplyr::pull(w)
    )
  }
  
  if (ti == "yearly") {
    return(
      df |>
        dplyr::filter(time_interval == "yearly") |>
        dplyr::slice_tail(n = 1) |>
        dplyr::pull(overall)
    )
  }
  
  NA_real_
}

upsert_weight <- function(path, country, variant, weight, data_per) {
  
  # 1) Einlesen
  if (file.exists(path)) {
    w <- readr::read_csv(path, show_col_types = FALSE)
  } else {
    w <- tibble::tibble()
  }
  
  # 2) Schema erzwingen (Spalten anlegen)
  needed <- c("country","variant","weight","data_per","model_date")
  for (nm in setdiff(needed, names(w))) w[[nm]] <- NA
  w <- w[, needed]
  
  # 3) >>> HIER <<< Typen erzwingen (WICHTIG)
  w$country    <- as.character(w$country)
  w$variant    <- as.character(w$variant)
  w$data_per   <- as.character(w$data_per)
  w$model_date <- as.character(w$model_date)
  w$weight     <- suppressWarnings(as.numeric(w$weight))
  
  # 4) Upsert-Logik
  idx <- which(w$country == country & w$variant == variant)
  
  new <- tibble::tibble(
    country    = country,
    variant    = variant,
    weight     = as.numeric(weight),
    data_per   = data_per,
    model_date = format(Sys.Date(), "%Y-%m-%d")
  )
  
  if (length(idx) == 1) {
    w[idx, ] <- new
  } else {
    w <- dplyr::bind_rows(w, new)
  }
  
  # 5) Schreiben
  readr::write_csv(w, path)
}


# ---------- Helfer für data_per in params.csv ------------
data_per_from_data <- function(df) {
  last <- df |> dplyr::arrange(year) |> dplyr::slice_tail(n = 1)
  ti <- last$time_interval[[1]]
  
  if (ti == "monthly") {
    return(sub("M", "-", last$YYYYMMM[[1]]))
  }
  
  if (ti == "quarterly") {
    y  <- last$year[[1]]
    yr <- floor(y) + 1              # <<< DAS war der Bug
    q  <- round((y %% 1) * 4) +1      # 1..4
    return(sprintf("%04d-%02d", yr, c(3, 6, 9, 12)[q]))
  }
  
  if (ti == "yearly") {
    return(sprintf("%04d-12", floor(last$year[[1]]) + 1))
  }
}

#### ---- SAVE: iCloud + GitHub Repo (auto) ---- ####
period_folder <- data_per_from_data(data_newzealand)
updated_to    <- period_folder

# 1) BEV trajectory
ggsave_git(
  filename = paste0("newzealand_", format(Sys.Date(), "%Y%m%d"), ".png"),
  plot = plot_newzealand,
  path_icloud = "~/Library/Mobile Documents/com~apple~CloudDocs/R/bev_share_newzealand",
  repo_dir = repo_dir_local,
  period = period_folder,         # <= HIER!
  width = 3840, height = 2160, units = "px", bg = "white",
  #branch = repo_branch,
  #push_now = FALSE
)

# 2) ICE vs BEV vs PHEV
ggsave_git(
  filename = paste0("newzealand_ICE_BEV_", format(Sys.Date(), "%Y%m%d"), ".png"),
  plot = plot_ICE_BEV_newzealand,
  path_icloud = "~/Library/Mobile Documents/com~apple~CloudDocs/R/bev_share_newzealand",
  repo_dir = repo_dir_local,
  period = period_folder,         # <=
  width = 12.80, height = 7.20, units = "in", dpi = 300, bg = "white"
  #branch = repo_branch,
  #push_now = FALSE
)

# 3) Transition time curve
ggsave_git(
  filename = paste0("newzealand_time_", format(Sys.Date(), "%Y%m%d"), ".png"),
  plot = plot_timer,
  path_icloud = "~/Library/Mobile Documents/com~apple~CloudDocs/R/bev_share_newzealand",
  repo_dir = repo_dir_local,
  period = period_folder,         # <=
  width = 12.80, height = 7.20, units = "in", dpi = 300, bg = "white"
  #branch = repo_branch,
  #push_now = FALSE
)

# 4) TTM market split
ggsave_git(
  filename = paste0("newzealand_ttm_shares_", format(Sys.Date(), "%Y%m%d"), ".png"),
  plot = TTM_barplot_newzealand,
  path_icloud = "~/Library/Mobile Documents/com~apple~CloudDocs/R/bev_share_newzealand",
  repo_dir = repo_dir_local,
  period = period_folder,         # <=
  width = 12.80, height = 7.20, units = "in", dpi = 300, bg = "white"
  #branch = repo_branch,
  #push_now = FALSE
)


#### ---- Google Sheets upsert (unverändert) ---- ####
sheet_id <- "1u7HyIqxSAeSEiU4E3wht-9Z7qBlboRiOsMp_467za4Y"
safe_numeric_chr <- function(x, placeholder = "Inf") ifelse(is.finite(x), as.double(x), placeholder)

upsert_country_result <- function(sheet_id, sheet_name = "per_country", country, bev_ttm, bev_20, bev_50, bev_80, bev_20_80, ice_80_20, scale, shape, movement, updated_to) {
  timestamp <- Sys.time()
  existing <- read_sheet(sheet_id, sheet = sheet_name)
  new_row <- data.frame(Country = country, Timestamp = timestamp, BEV_TTM = bev_ttm, BEV_20 = bev_20, BEV_50 = bev_50,
                        BEV_80 = bev_80, BEV_20_to_80 = safe_numeric_chr(bev_20_80), ICE_80_to_20 = safe_numeric_chr(ice_80_20),
                        Scale = scale, Shape = shape, Movement =  movement, Updated_to = updated_to)
  if (country %in% existing$Country) {
    row_index <- which(existing$Country == country)
    range <- paste0(sheet_name, "!A", row_index + 1)
    range_write(sheet_id, data = new_row, range = range, col_names = FALSE)
  } else {
    sheet_append(sheet_id, new_row, sheet = sheet_name)
  }
}

as_date_from_numeric <- function(x, placeholder = NA_character_) {
  if (!is.finite(x)) return(placeholder)
  year  <- floor(x) + 1; month <- floor(12 * (x %% 1)) + 1
  as.Date(sprintf("%04d-%02d-01", year, month))
}

upsert_country_result(
  sheet_id = sheet_id,
  country = country,
  bev_ttm = tail(data_newzealand$`BEV TTM`, 1),
  bev_20 = as_date_from_numeric(time_20_newzealand, "Inf"),
  bev_50 = as_date_from_numeric(time_50_newzealand, "Inf"),
  bev_80 = as_date_from_numeric(time_80_newzealand, "Inf"),
  bev_20_80 = time_20_to_80_newzealand,
  ice_80_20 = time_80_to_20_newzealand,
  scale = res$par[1],
  shape = res$par[2],
  movement = verschiebung,
  updated_to = tail(sub("M", "-", data_newzealand$YYYYMMM), n=1)
)


#### ---- Console summary print (last month + TTM) ---- ####
# Falls noch nicht installiert:
# install.packages("countrycode")

suppressPackageStartupMessages({ library(countrycode) })

# Buchstabe -> Regional-Indicator
iso2_to_flag <- function(iso2) {
  if (is.na(iso2) || nchar(iso2) != 2) return("")
  chars <- strsplit(toupper(iso2), "")[[1]]
  to_ri <- function(ch) intToUtf8(0x1F1E6 + utf8ToInt(ch) - utf8ToInt("A"))
  paste0(vapply(chars, to_ri, FUN.VALUE = character(1)), collapse = "")
}

#### ---- Console summary print (last month + TTM) ---- ####
# Falls noch nicht installiert:
# install.packages("countrycode")

suppressPackageStartupMessages({ library(countrycode) })

# Buchstabe -> Regional-Indicator
iso2_to_flag <- function(iso2) {
  if (is.na(iso2) || nchar(iso2) != 2) return("")
  chars <- strsplit(toupper(iso2), "")[[1]]
  to_ri <- function(ch) intToUtf8(0x1F1E6 + utf8ToInt(ch) - utf8ToInt("A"))
  paste0(vapply(chars, to_ri, FUN.VALUE = character(1)), collapse = "")
}

# Ländernamen -> ISO2 -> Flag
country_to_flag <- function(name) {
  # ein paar häufige Aliase korrigieren
  alias <- c("Türkiye" = "Turkey", "Czechia" = "Czech Republic")
  canon <- if (!is.na(alias[name])) alias[name] else name
  iso2  <- countrycode(canon, origin = "country.name", destination = "iso2c", custom_match = c("Hong Kong"="HK", "Macau"="MO"))
  # wenn already iso2 übergeben wurde
  if (is.na(iso2) && nchar(name) == 2) iso2 <- toupper(name)
  iso2_to_flag(iso2)
}

flag <- country_to_flag(country)

pct <- function(x) scales::percent(x, accuracy = 0.1)
nz  <- function(x, z = 0) ifelse(is.finite(x), x, z)

# letzter Monats-Datensatz
last_m <- data_newzealand |>
  dplyr::arrange(year) |>
  dplyr::slice_tail(n = 1)

if (nrow(last_m) == 0) stop("no data at all")

# Monats-Label "August 25"
last_date_from_data <- function(df) {
  stopifnot(nrow(df) > 0)
  
  # monthly vorhanden → nimm letzten Monat
  if ("YYYYMMM" %in% names(df) && any(!is.na(df$YYYYMMM))) {
    ym <- tail(df$YYYYMMM[!is.na(df$YYYYMMM)], 1)
    return(as.Date(paste0(sub("M", "-", ym), "-01")))
  }
  
  # sonst quarterly über year-Fraction (Q1→Feb, Q2→Mai, Q3→Aug, Q4→Nov)
  y  <- max(df$year, na.rm = TRUE)
  yr <- floor(y)
  q  <- round((y %% 1) * 4)           # 1..4
  mo <- c(2, 5, 8, 11)[q]
  
  as.Date(sprintf("%04d-%02d-01", yr, mo))
}

old_loc <- Sys.getlocale("LC_TIME"); try(Sys.setlocale("LC_TIME","C"), silent=TRUE)

last_label_from_data <- function(df, last_date) {
  last <- df |> dplyr::arrange(year) |> dplyr::slice_tail(n = 1)
  ti <- last$time_interval[[1]]
  
  if (ti == "monthly") {
    old <- Sys.getlocale("LC_TIME")
    on.exit(Sys.setlocale("LC_TIME", old), add = TRUE)
    Sys.setlocale("LC_TIME", "C")
    return(paste(format(last_date, "%B"), format(last_date, "%y")))
  }
  
  if (ti == "quarterly") {
    y <- as.integer(format(last_date, "%Y"))
    q <- (as.integer(format(last_date, "%m")) - 1) %/% 3 + 1
    return(sprintf("Q%d %d", q, y))
  }
  
  if (ti == "yearly") {
    return(as.character(floor(last$year[[1]])))
  }
  
  ""
}
last_date <- last_date_from_data(data_newzealand)
month_label <- last_label_from_data(data_newzealand, last_date)

try(Sys.setlocale("LC_TIME", old_loc), silent=TRUE)

#### ---- Monats-/TTM-Shares robust + Console-Ausgabe mit Sonderfällen ----

pct <- function(x) scales::percent(x, accuracy = 0.1)
nz  <- function(x, z = 0) ifelse(is.finite(x), x, z)
has <- function(nm, obj) nm %in% names(obj)

# ---------- Monatswerte (letzte Monatszeile) ----------
# BEV
bev_m <- nz(last_m$bev_share[[1]])

# Hybrid gesamt (falls statt PHEV/HEV nur "Hybrid" geliefert wird)
hybrid_m <- {
  if (has("Hybrid share", last_m)) {
    nz(last_m$`Hybrid share`[[1]])
  } else if (has("Hybrid", last_m)) {
    nz(last_m$Hybrid[[1]] / last_m$overall[[1]])
  } else {
    NA_real_
  }
}

# PHEV
phev_m <- {
  if (has("PHEV share", last_m)) {
    nz(last_m$`PHEV share`[[1]])
  } else if (has("PHEV", last_m)) {
    nz(last_m$PHEV[[1]] / last_m$overall[[1]])
  } else if (is.finite(hybrid_m)) {
    # Länder mit nur "Hybrid": verwende hybrid_m und kennzeichne als Hybrid
    NA_real_
  } else {
    0
  }
}

# EREV (Teilmenge von PHEV)
erev_m <- {
  if (has("EREV share", last_m)) {
    nz(last_m$`EREV share`[[1]])
  } else if (has("EREV", last_m)) {
    nz(last_m$EREV[[1]] / last_m$overall[[1]])
  } else {
    NA_real_
  }
}

# HEV (Teilmenge von ICE; wenn nur "Hybrid" existiert, können wir HEV nicht separat angeben)
hev_m <- {
  if (has("HEV share", last_m)) {
    nz(last_m$`HEV share`[[1]])
  } else if (has("HEV", last_m)) {
    nz(last_m$HEV[[1]] / last_m$overall[[1]])
  } else if (is.finite(hybrid_m) && is.finite(phev_m)) {
    # selten: sowohl Hybrid als Summe als auch PHEV separat -> HEV = Hybrid - PHEV
    pmax(hybrid_m - phev_m, 0)
  } else {
    NA_real_
  }
}

# Welcher „zweite“ Antriebstyp steht in der zweiten Zeile? PHEV oder Hybrid
second_label_m <- if (is.finite(phev_m)) "PHEV" else if (is.finite(hybrid_m)) "Hybrid" else "PHEV"
second_value_m <- if (is.finite(phev_m)) phev_m else if (is.finite(hybrid_m)) hybrid_m else 0

# ICE inkl. HEV, abziehen was wir tatsächlich ausgewiesen haben (PHEV oder Hybrid)
ice_m <- pmax(1 - bev_m - nz(second_value_m, 0), 0)

# ---------- TTM (letzte Zeile) ----------
bev_ttm <- nz(tail(data_newzealand$`BEV TTM`, 1))

hybrid_ttm <- {
  if (has("Hybrid TTM", data_newzealand)) nz(tail(data_newzealand$`Hybrid TTM`, 1)) else NA_real_
}

phev_ttm <- {
  if (has("PHEV TTM", data_newzealand)) {
    nz(tail(data_newzealand$`PHEV TTM`, 1))
  } else if (is.finite(hybrid_ttm)) {
    NA_real_
  } else 0
}

erev_ttm <- if (has("EREV TTM", data_newzealand)) nz(tail(data_newzealand$`EREV TTM`, 1)) else NA_real_

hev_ttm <- {
  if (has("HEV TTM", data_newzealand)) {
    nz(tail(data_newzealand$`HEV TTM`, 1))
  } else if (is.finite(hybrid_ttm) && is.finite(phev_ttm)) {
    pmax(hybrid_ttm - phev_ttm, 0)
  } else {
    NA_real_
  }
}

second_label_ttm <- if (is.finite(phev_ttm)) "PHEV" else if (is.finite(hybrid_ttm)) "Hybrid" else "PHEV"
second_value_ttm <- if (is.finite(phev_ttm)) phev_ttm else if (is.finite(hybrid_ttm)) hybrid_ttm else 0

ice_ttm <- pmax(1 - bev_ttm - nz(second_value_ttm, 0), 0)


# ---------- Helfer für optionale Klammern ----------
pp_if <- function(lbl, val, extra_lbl = NULL, extra_val = NA_real_) {
  if (is.finite(extra_val) && extra_val > 0) {
    sprintf("%s %s (of which %sp were %s)\n", pct(val), lbl, pct(extra_val), extra_lbl)
  } else {
    sprintf("%s %s\n", pct(val), lbl)
  }
}

# PHEV-/Hybrid-Zeile: bei PHEV ggf. EREV anhängen; bei Hybrid keine Klammer
second_line_month <- {
  if (second_label_m == "PHEV") {
    pp_if("PHEV", second_value_m, "EREV", erev_m)
  } else {
    sprintf("%s Hybrid\n", pct(second_value_m))
  }
}
second_line_ttm <- {
  if (second_label_ttm == "PHEV") {
    pp_if("PHEV", second_value_ttm, "EREV", erev_ttm)
  } else {
    sprintf("%s Hybrid\n", pct(second_value_ttm))
  }
}

# ICE-Zeile: HEV-Klammer nur, wenn HEV-Daten tatsächlich vorhanden
ice_line_month <- pp_if("ICE", ice_m, "HEV", if (is.finite(hev_m)) hev_m else NA_real_)
ice_line_ttm   <- pp_if("ICE", ice_ttm, "HEV", if (is.finite(hev_ttm)) hev_ttm else NA_real_)


# ---------- Helfer für optionale CSV Zeichenkodierung ----------
suppressPackageStartupMessages({ library(stringi) })

# -- Feste Ersetzungen für gängige Mojibake --
fix_known_mojibake <- function(x) {
  if (!is.character(x)) return(x)
  map <- c(
    "TÃ¼rkiye"="Türkiye", "TÃœrkiye"="TÜrkiye",
    "Ã¼"="ü","Ãœ"="Ü","Ã¶"="ö","Ã–"="Ö",
    "Ã§"="ç","Ã‡"="Ç","Ã±"="ñ","ÃŸ"="ß",
    "Ã¡"="á","Ã " ="à","Ã¢"="â","Ã£"="ã","Ã¤"="ä",
    "Ã©"="é","Ã¨"="è","Ãª"="ê","Ã«"="ë",
    "Ã³"="ó","Ã²"="ò","Ã´"="ô","Ãµ"="õ","Ã¶"="ö",
    "Ãº"="ú","Ã¹"="ù","Ã»"="û",
    "â€“"="–","â€”"="—","â€ž"="„","â€œ"="“","â€\u009d"="”","â€˜"="‘","â€™"="’"
  )
  stringi::stri_replace_all_fixed(x, names(map), unname(map), vectorize_all = FALSE)
}

# Vollständige Text-Normalisierung
normalize_utf8_nfc <- function(x) {
  if (is.null(x)) return(x)
  if (is.character(x)) {
    x <- fix_known_mojibake(x)
    x <- iconv(x, from = "", to = "UTF-8", sub = "")        # UTF-8 erzwingen
    x <- stringi::stri_trans_nfc(x)                          # Unicode NFC
    x <- gsub("[\\x00-\\x1F\\x7F\\x80-\\x9F]", "", x, perl=TRUE)  # Steuerzeichen killen
  }
  x
}

normalize_df_text <- function(df) {
  if (!is.data.frame(df)) return(df)
  char_cols <- vapply(df, is.character, logical(1))
  df[char_cols] <- lapply(df[char_cols], normalize_utf8_nfc)
  df
}


## ==== params.csv robust upsert mit Delimiter-Erkennung ====
target_cols <- c("country","variant",
                 "v1","v2","t0",
                 "data_per","model_date","source","baseline_date",
                 "ice_v1","ice_v2","ice_t0"
)

params_path <- file.path(repo_dir_local, "params.csv")

# ---- 1) Robuste Delimiter-Erkennung über N Zeilen, ignoriert Kommas in Quotes ----
detect_delim <- function(path, n = 50) {
  if (!file.exists(path)) return(",")
  lines <- suppressWarnings(readLines(path, n = n, warn = FALSE, encoding = "unknown"))
  lines <- lines[ nzchar(lines) ]
  if (!length(lines)) return(",")
  
  strip_quoted <- function(s) {
    # entfernt Inhalte in "..." damit Trennzeichen darin nicht gezählt werden
    gsub('"[^"]*"', "", s, perl = TRUE)
  }
  unquoted <- vapply(lines, strip_quoted, character(1))
  
  count <- function(ch) vapply(unquoted, function(x) lengths(regmatches(x, gregexpr(ch, x, perl=TRUE))), integer(1))
  sc <- sum(count(";"))
  cc <- sum(count(","))
  
  if (sc > cc) ";" else ","
}

# ---- 2) Lesen: Encoding robust, Zahlen normieren, Spalten vervollständigen ----
read_params <- function(path) {
  if (!file.exists(path)) {
    df <- data.frame()
  } else {
    delim <- detect_delim(path)
    
    # ISO-8859-1 rein, danach auf UTF-8 normalisieren (Base R)
    df <- tryCatch(
      utils::read.table(path,
                        header = TRUE, sep = delim, dec = ".",
                        quote = "\"", comment.char = "",
                        check.names = FALSE, stringsAsFactors = FALSE,
                        fileEncoding = "Latin1", encoding = "UTF-8"),
      error = function(e) {
        # Fallback: UTF-8 probieren
        utils::read.table(path,
                          header = TRUE, sep = delim, dec = ".",
                          quote = "\"", comment.char = "",
                          check.names = FALSE, stringsAsFactors = FALSE,
                          fileEncoding = "UTF-8")
      }
    )
  }
  
  # Fehlende Spalten ergänzen
  for (nm in setdiff(target_cols, names(df))) df[[nm]] <- NA
  df <- df[, target_cols, drop = FALSE]
  
  # Trim Strings
  is_char <- vapply(df, is.character, logical(1))
  df[is_char] <- lapply(df[is_char], function(x) trimws(iconv(x, to = "UTF-8")))
  
  # Zahlen robust: Komma -> Punkt, Spaces raus, dann numeric
  to_num <- function(x) {
    if (is.numeric(x)) return(x)
    x <- gsub("\\s+", "", x)
    x <- gsub(",", ".", x, fixed = TRUE)
    suppressWarnings(as.numeric(x))
  }
  df$v1 <- to_num(df$v1)
  df$v2 <- to_num(df$v2)
  df$t0 <- to_num(df$t0)
  
  df
}

# ---- 3) Schreiben: UTF-8 Komma + "."-Dezimal + leere Felder für NA + säubern zum entfernen unsichtbarer Zeichen damit index.html nicht stürzt ----
suppressPackageStartupMessages({ 
  library(readr); library(stringi)
})

sanitize_params_csv <- function(path_in, path_out = path_in, 
                                expected_cols = c("country","variant","v1","v2","t0","data_per","model_date","source","baseline_date", "ice_v1", "ice_v2", "ice_t0")) {
  
  if (!file.exists(path_in)) stop("params.csv fehlt: ", path_in)
  
  # 1) Rohinhalt lesen (Bytes -> Text)
  raw_txt <- read_file_raw(path_in)
  txt <- rawToChar(raw_txt)
  Encoding(txt) <- "UTF-8"
  # BOM entfernen + Zeilenenden normalisieren
  txt <- sub("^\uFEFF", "", txt, perl = TRUE)
  txt <- gsub("\r\n?", "\n", txt)
  
  # 2) Unsichtbares und Mojibake fixen (ohne Inhalt zu verändern)
  txt <- gsub("[\u200B-\u200D\u2060\u00A0]", " ", txt)   # Zero-Width & NBSP -> Leerzeichen
  # bekannte Mojibake-Mappings (sparsam)
  fixes <- c("TÃ¼rkiye"="Türkiye","Ã¼"="ü","Ãœ"="Ü","Ã¶"="ö","Ã–"="Ö","Ã§"="ç","Ã‡"="Ç","ÃŸ"="ß")
  txt <- stri_replace_all_fixed(txt, names(fixes), unname(fixes), vectorize_all = FALSE)
  
  # 3) Schnell-Validierung: ungerade Anzahl Anführungszeichen pro Zeile -> Problem melden
  lines <- strsplit(txt, "\n", fixed = TRUE)[[1]]
  q_odd <- which((nchar(gsub('[^"]', "", lines)) %% 2L) == 1L)
  if (length(q_odd)) {
    warning(sprintf("Achtung: %d Zeile(n) mit ungerader Quote-Anzahl, z.B. Zeile %s",
                    length(q_odd), paste(head(q_odd, 5), collapse = ", ")))
  }
  
  # 4) Sauber mit readr parsen (Delimiter automatisch oder erzwingen = ",")
  #    Wir erzwingen Komma, weil dein Frontend das erwartet.
  df <- read_csv(I(txt),
                 locale = locale(encoding = "UTF-8", decimal_mark = "."),
                 show_col_types = FALSE,
                 progress = FALSE,
                 col_names = TRUE,
                 quote = "\"")
  
  # 5) Header & Text normalisieren
  names(df) <- trimws(tolower(names(df)))
  want <- tolower(expected_cols)
  # fehlende Spalten ergänzen (als leere)
  for (nm in setdiff(want, names(df))) df[[nm]] <- NA_character_
  # nur erwartete Spalten, in fixer Reihenfolge
  df <- df[, want, drop = FALSE]
  
  # alle Char-Felder: NFC, trim, Steuerzeichen raus
  is_chr <- vapply(df, is.character, logical(1))
  df[is_chr] <- lapply(df[is_chr], function(x) {
    x <- stri_trans_nfc(x)
    x <- trimws(x)
    x <- gsub("[\\x00-\\x1F\\x7F\\x80-\\x9F]", "", x, perl = TRUE)
    x
  })
  
  # 6) Zahlenfelder sicher nach numeric
  to_num <- function(x) suppressWarnings(as.numeric(gsub(",", ".", x, fixed = TRUE)))
  for (nm in c("v1","v2","t0")) if (nm %in% names(df)) df[[nm]] <- to_num(df[[nm]])
  
  # 7) Zurückschreiben: UTF-8 **ohne BOM**, Komma-CSV, NA = "", nur nötige Quotes
  write_csv(df, file = path_out, na = "", append = FALSE)
  
  invisible(df)
}

write_params <- function(df, path) {
  target_cols <- c("country","variant",
                   "v1","v2","t0",
                   "data_per","model_date","source","baseline_date",
                   "ice_v1","ice_v2","ice_t0"
  )
  
  # Spaltenreihenfolge fix & fehlende Spalten ergänzen
  for (nm in setdiff(target_cols, names(df))) df[[nm]] <- NA
  df <- df[, target_cols, drop = FALSE]
  
  # Zeichenfelder sauber machen + NA -> ""
  df <- normalize_df_text(df)
  is_char <- vapply(df, is.character, logical(1))
  df[is_char] <- lapply(df[is_char], function(x) { x[is.na(x)] <- ""; x })
  
  # Zahlen vernünftig ausgeben
  old <- options(scipen = 999, OutDec = ".")
  on.exit(options(old), add = TRUE)
  
  # Immer UTF-8 schreiben (ohne BOM; für Excel siehe Kommentar unten)
  con <- file(path, open = "w", encoding = "UTF-8")
  on.exit(close(con), add = TRUE)
  
  utils::write.table(
    df, file = con,
    sep = ",", dec = ".",
    row.names = FALSE, col.names = TRUE,
    quote = TRUE, qmethod = "double",
    na = ""
  )
}


# 1) Einlesen und normalisieren
params <- read_params(params_path)
params <- normalize_df_text(params)

# 2) Neue/aktualisierte Zeile bauen
variant <- if (grepl("\\(", country)) sub(".*\\(([^)]+)\\).*", "\\1", country) else "Whole"
country_clean <- sub("\\s*\\(.*\\)\\s*", "", country)

row <- data.frame(
  country = normalize_utf8_nfc(country_clean),
  variant = normalize_utf8_nfc(variant),
  
  v1 = as.numeric(res$par[1]),
  v2 = as.numeric(res$par[2]),
  t0 = as.numeric(verschiebung),
  
  data_per = data_per_from_data(data_newzealand),
  model_date = format(Sys.Date(), "%Y-%m-%d"),
  source = normalize_utf8_nfc(sub("^Source:\\s*", "", source)),
  baseline_date = "",
  
  ice_v1 = as.numeric(res_ice$par[1]),
  ice_v2 = as.numeric(res_ice$par[2]),
  ice_t0 = as.numeric(verschiebung),
  
  stringsAsFactors = FALSE
)



# 3) Upsert by country+variant (case-insensitive für country)
idx <- which(tolower(params$country) == tolower(country_clean) &
               params$variant == variant)
if (length(idx) == 1) {
  params[idx, ] <- row
} else {
  params <- rbind(params, row)
}

# 4) NEU: erst schreiben, dann sanitizen 
write_params(params, params_path)          # dein vorhandener Writer (Komma, UTF-8)
sanitize_params_csv(params_path)           # BOM/Zero-Width/Quotes/Mojibake fixen
# -------------------------------------------

# ------------------ weights.csv updaten ------
weight_total <- compute_weight_from_data(data_newzealand)
upsert_weight(
  path    = file.path(repo_dir_local, "weights.csv"),
  country = country_clean,
  variant = variant,
  weight  = weight_total,
  data_per = data_per_from_data(data_newzealand)
)



# 5) Sofort commit & push, aber nur wenn sich wirklich was geändert hat
try(gert::git_branch_checkout(repo_branch, repo = repo_dir_local), silent = TRUE)
gert::git_add("params.csv", repo = repo_dir_local)

safe_commit_and_push(paste0(country, ": auto-publish model"))


# ---------- Ausgabe in Konsole für Postings ----------
cat(
  sprintf("%s %s - %s - BEV Trajectory\n", flag, country, month_label),
  sprintf("%s BEV\n", pct(bev_m)),
  second_line_month,
  ice_line_month, "\n",
  "Trailing 12 months are:\n",
  sprintf("%s BEV\n", pct(bev_ttm)),
  second_line_ttm,
  ice_line_ttm, "\n",
  "Graphs are available in the Gallery: https://leraffl.github.io/LeRaffl-Gallery/",
  sep = ""
)

