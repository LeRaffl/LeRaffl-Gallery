#### set up packages ####
#install.packages("readxl")
#install.packages("dplyr")
#install.packages("tidyr")
#install.packages("reshape2") # for melt function
#install.packages("ggrepel")                     # coole kleine boxen in legende
#install.packages("googlesheets4)
#install.packages("scales") # for unit_format
#install.packages("png") # for readPNG
#install.packages("grid") # for rasterGrob
#install.packages("ecb")
#install.packages("tidyquant")
#install.packages("patchwork")


library("ggrepel")
library(readxl)
library(tidyr) #to fill in the empty values of names Modellreihe with the value above it
library(dplyr) #his is for leaving out last 5 rows later on
library(ggplot2)
library(reshape2)
library(xts)  #for as.yearmon
library(googlesheets4)
library(scales)
library(grid)
library(png)
library(ecb)
library(tidyquant) # for FED interest rates
library(patchwork)
#devtools::install_github("gaba-tope/socialcap")
#library(socialcap) # wird nicht benutzt
library(ggtext) # um unicode in der caption zu setzen
library(ggplot2)
library(grid)
library(png)
library(dplyr)
library(lubridate)
library(htmltools)

#install.packages("sysfonts")
#install.packages("fontawesome")
#install.packages("emojifont")
library(fontawesome)
library(emojifont)

#### set up icons for caption with social media ####
sysfonts::font_add(family = "Font Awesome 6 Brands", 
                   regular = "/Users/raphaelwellmann/Library/Mobile Documents/com~apple~CloudDocs/R/fonts/fontawesome/otfs/Font-Awesome-6-Brands-Regular-400.otf"
)
sysfonts::font_add(family = "CustomIcons", 
                   regular = "/Users/raphaelwellmann/Library/Mobile Documents/com~apple~CloudDocs/R/fonts/fontawesome/otfs/icomoon.ttf"
)
showtext::showtext_auto()
x_icon <- "&#xe61b"
x_username <- "leraffl"
bluesky_icon <- "&#xe671"
bluesky_username <- "leraffl.bsky.social "
buy_me_a_coffee_icon <- "&#xe900"
buy_me_a_coffee_username <- "leraffl"

social_caption <- glue::glue(
  "<span style='font-family:\"CustomIcons\";'>{buy_me_a_coffee_icon};</span>",
  "<span style='font-family:\"Font Awesome 6 Brands\";'>{x_icon};</span>
  <span style='color: #000000'>{x_username}</span>",
  strrep(" ", 4),  # 4 Leerzeichen
  "<span style='font-family:\"Font Awesome 6 Brands\";'>{bluesky_icon};</span>
  <span style='color: #000000'>{bluesky_username}</span>"#,
  # strrep(" ", 4),  # 4 Leerzeichen
  #"<span style='font-family:\"CustomIcons\";'>{buy_me_a_coffee_icon};</span>
  #<span style='color: #000000'>{buy_me_a_coffee_username}</span>"
)

source <- paste0("ACEA, febiac.be")
current_date <- format(Sys.Date(), "%Y")
entire_caption <- paste0(social_caption, " | \t ", Sys.Date(), "  | \t    Source: ",source)

flag_path <- "/Users/raphaelwellmann/Library/Mobile Documents/com~apple~CloudDocs/R/bev_share_belgium/belgium.png"
flag_img <- readPNG(flag_path)
flag_base64 <- base64enc::dataURI(file = flag_path)



#### read all the data and give a data.frame ####
# Get a list of all Excel files in the directory
# googlesheets4::gs4_deauth() # revoke existing API access token
# googlesheets4::gs4_auth() # (re)start existing API access token
data_belgium <- read_sheet("https://docs.google.com/spreadsheets/d/17h0MJXfIJH4yn2Kk-vmS9Qx_bNJfXfCRqZjFS5__y0k/edit?gid=2120584822#gid=2120584822", sheet = "registrations_belgium")

#data_belgium$`Electric/zero-emission` <- data_belgium$BEV
#data_belgium$overall <- data_belgium$TOTAL
#data_belgium$Fossil <- data_belgium$TOTAL - data_belgium$PHEV - data_belgium$BEV
#data_belgium$Hybrid <- data_belgium$PHEV
#data_belgium$`Other fuel` <- data_belgium$OTHERS

data_belgium$bev_share <- data_belgium$`Electric/zero-emission`/data_belgium$overall
data_belgium$ice_share <- data_belgium$Fossil/data_belgium$overall
data_belgium$hybrid_share <- data_belgium$Hybrid/data_belgium$overall
data_belgium$other_share <- data_belgium$`Other fuel`/data_belgium$overall
#data_belgium$pure_ICE <- (data_belgium$Fossil - data_belgium$HEV)/data_belgium$overall
data_belgium$pure_ICE <- (data_belgium$Fossil)/data_belgium$overall

lastyearly <- ceiling(max(subset(data_belgium, data_belgium$time_interval=="yearly")$year))

#### trailing 12 months data and plot ####
data_belgium_monthly <- subset(data_belgium, data_belgium$time_interval=="monthly")
data_belgium_monthly <- subset(data_belgium_monthly, data_belgium_monthly$year>=min(data_belgium_monthly$year+1))
TTM_shares_belgium <- data.frame(
  "month" = format(seq.Date(from = as.Date(paste0(floor(min(data_belgium_monthly$year)+1),"-01-01")), by = "month", length.out = nrow(data_belgium_monthly)), "%Y-%m"),
  "Other" = data_belgium_monthly$`Other TTM`,
  #"ICE (excl. HEV)" = data_belgium_monthly$`ICE TTM`-data_belgium_monthly$`HEV TTM`-data_belgium_monthly$`Other TTM`,
  #"ICE (incl. HEV)" = data_belgium_monthly$`ICE TTM`,
  "Petrol" = data_belgium_monthly$`Petrol TTM`,
  #"Petrol (incl. HEV Petrol)" = data_belgium_monthly$`Petrol TTM`,
  "Diesel" = data_belgium_monthly$`Diesel TTM`,
  #"Diesel (incl. HEV Diesel)" = data_belgium_monthly$`Diesel TTM`,
  #"Ethanol" = data_belgium_monthly$`Ethanol TTM`,
  #"Gas" = data_belgium_monthly$`Gas TTM`,
  "HEV" = data_belgium_monthly$`HEV TTM`, 
  #"ICE" = data_belgium_monthly$`ICE TTM`, 
  "PHEV" = data_belgium_monthly$`PHEV TTM`, 
  "BEV" = data_belgium_monthly$`BEV TTM`
)

# Du musst zuerst die Spalte type erstellen, bevor du sie als Faktor definierst. Wenn du type mit den Werten "ICE", "HEV", "PHEV", "BEV" hinzufügen möchtest, kannst du das direkt in mutate() machen.
# Erklärung:
# pivot_longer: Wandelt die Spalten "ICE", "HEV", "PHEV", "BEV" in eine Spalte namens type um und speichert die entsprechenden Werte in value. So hast du eine Spalte type, die benötigt wird.
# mutate(type = factor(...)): Transformiert die Spalte type in einen Faktor mit der definierten Reihenfolge der Levels.
# Wenn der Name von R verändert wurde
colnames(TTM_shares_belgium)[colnames(TTM_shares_belgium) == "Other.Unknown"] <- "Other/Unknown"
colnames(TTM_shares_belgium)[colnames(TTM_shares_belgium) == "HEV.Petrol"] <- "HEV Petrol"
colnames(TTM_shares_belgium)[colnames(TTM_shares_belgium) == "HEV.Diesel"] <- "HEV Diesel"
colnames(TTM_shares_belgium)[colnames(TTM_shares_belgium) == "PHEV.Petrol"] <- "PHEV Petrol"
colnames(TTM_shares_belgium)[colnames(TTM_shares_belgium) == "PHEV.Diesel"] <- "PHEV Diesel"
colnames(TTM_shares_belgium)[colnames(TTM_shares_belgium) == "Petrol..incl..HEV.Petrol."] <- "Petrol (incl. HEV Petrol)"
colnames(TTM_shares_belgium)[colnames(TTM_shares_belgium) == "Diesel..incl..HEV.Diesel."] <- "Diesel (incl. HEV Diesel)"
colnames(TTM_shares_belgium)[colnames(TTM_shares_belgium) == "ICE..excl..HEV."] <- "ICE (excl. HEV)"
colnames(TTM_shares_belgium)[colnames(TTM_shares_belgium) == "ICE..incl..HEV."] <- "ICE (incl. HEV)"
# das Spiel mit den Pünktchen muss sein weil die Spalte so benannt wird von R
TTM_shares_belgium_long <- TTM_shares_belgium %>%
  pivot_longer(cols = c("Other", "Petrol", "Diesel", "HEV", "PHEV", "BEV"), 
               names_to = "type", 
               values_to = "value") %>%
  mutate(type = factor(type, levels = c("Other", "Petrol", "Diesel", "HEV", "PHEV", "BEV")))

TTM_shares_belgium_long <- TTM_shares_belgium_long %>%
  filter(!is.na(value))


# Create the stacked bar chart
library(viridis)

# Erstellen einer numerischen Spalte für die Positionen
TTM_shares_belgium_long <- TTM_shares_belgium_long %>%
  mutate(numeric_month = as.numeric(as.factor(month)))

# Plot mit Korrektur für die vertikalen Linien
TTM_barplot_belgium <- ggplot(TTM_shares_belgium_long, aes(x = month, y = value, fill = type)) +
  # Balkendiagramm
  geom_bar(stat = "identity", position = "stack", width = 1) +
  
  # Vertikale Linien für Januar
  geom_vline(
    data = TTM_shares_belgium_long %>% filter(substr(month, 6, 7) == "01") %>% distinct(numeric_month),
    aes(xintercept = numeric_month-0.5), # Verschiebung um 0.5 weil die Linie sonst in der Balkenmitte sind und ich sie aber links haben will
    color = "gray40", linetype = "dashed"
  ) +
  
  # Horizontale Linien bei 0.25, 0.5, 0.75
  geom_hline(yintercept = c(0.25, 0.5, 0.75), color = "gray40", linetype = "dashed") +
  
  # Nur Januar-Labels anzeigen
  scale_x_discrete(
    breaks = TTM_shares_belgium_long$month[substr(TTM_shares_belgium_long$month, 6, 7) == "01"],
    labels = function(x) format(as.Date(paste0(x, "-01")), "%b %Y") 
  ) +
  
  # Y-Achse und Farbschema anpassen
  scale_y_continuous(
    labels = scales::percent_format(scale = 100), 
    expand = c(0, 0),
    sec.axis = sec_axis(~ ., name = "Trailing 12 Months Market Share", labels = scales::percent_format(scale = 100))
  ) +
  scale_fill_viridis_d(name = "Fuel Type", option = "D") +  # Verwenden von viridis Farben
  
  # Labels und Titel
  labs(
    title = "12-Month Trailing Market Shares by Fuel Type in Belgium",
    y = "Trailing 12 Months Market Share",
    x = "Jahre",
    caption = entire_caption,
  ) +
  
  # Layout
  theme_minimal() +
  theme(
    axis.text.x = element_text(angle = 45, hjust = 1),
    axis.title.x = element_blank(),
    plot.title = element_text(size = 14, face = "bold"),
    #legend.position = "right",
    legend.position = c(0.05, 0.95),  # Position links oben
    legend.justification = c(0, 1),   # Ankerpunkt der Legende (oben links)
    legend.background = element_rect(fill = "white", color = "gray90", size = 0.5), # Heller Hintergrund
    legend.key = element_rect(fill = NA, color = NA),  # Heller Hintergrund innerhalb der Legende
    legend.key.height = unit(0.2, "cm"),
    plot.caption = element_markdown(hjust=0)  # Caption als Markdown/HTML interpretieren # hjust=1 heißt rechtsbündig
  )

print(TTM_barplot_belgium)


#### define functions for regression and parameter to start at 2010 ####
verschiebung <- floor(min(data_belgium$year))
extrapol <- 2065
data_belgium <- subset(data_belgium, data_belgium$year>=verschiebung)
confidence_level <- 0.999
alpha <- 1-confidence_level
z <- qnorm(1-alpha/2)
default_size <- 2

#### regression functions ####
reg <- function(v, x, type="BEV"){
  if (type == "ICE"){
    return(1-(1-exp(v[1]*(x-(verschiebung-1))^v[2])))
  } else if (type == "BEV"){
    return(1-exp(v[1]*(x-(verschiebung-1))^v[2]))
  } else if (type == "BEV extended"){
    return(v[3]-exp(v[1]*(x-(verschiebung-1))^v[2]) + ((1-v[3])-exp(v[4]*(x-(verschiebung-1))^v[5])+v[3]) + (1-v[3]))
  } else {
    stop("Unknown type. Please use 'ICE' or 'BEV'.")
  }
}

RSS <- function(v, type="BEV"){
  forecast <- reg(v, BEV$x, type)
  residuals <- BEV$y-forecast
  r <- sum((residuals*data_belgium$overall)^2)           #ANGEPASST FÜR GEWICHTUNG NACH MENGE DER GESAMTEN ZULASSUNGEN
  return(r)
}

reg_ice <- function(v, x, type="ICE"){
  if (type == "ICE"){
    return(1-(1-1*exp(v[1]*(x-(verschiebung-1))^v[2])))
    #return(0.98-(0.98-0.98*exp(v[1]*(x-(verschiebung-1))^v[2])))
  } else if (type == "BEV"){
    return((0.98-exp(v[1]*(x-(verschiebung-1))^v[2])))
  } else {
    stop("Unknown type. Please use 'ICE' or 'BEV'.")
  }
}

RSS_ice <- function(v, type="ICE"){
  forecast <- reg_ice(v, ICE$x, type)
  residuals <- ICE$y-forecast
  r <- sum((residuals*data_belgium$overall)^2)           #ANGEPASST FÜR GEWICHTUNG NACH MENGE DER GESAMTEN ZULASSUNGEN
  return(r)
}

bev_time <- seq(0,0,length=length(data_belgium$`Electric/zero-emission`))
ice_time <- seq(0,0,length=length(data_belgium$`Electric/zero-emission`))
for(i in 1:length(data_belgium$`Electric/zero-emission`)){
  data_belgium_looped <- data_belgium[1:i,]
#### optimize BEV ####
xg<-data_belgium_looped$year
yg<-as.double(data_belgium_looped$bev_share)
BEV <- data.frame(x=xg,y=yg)
control <- list(maxit = 100000, reltol=10^-30)  # Hier kannst du die maximale Anzahl der Iterationen anpassen
res <- optim(par=c(-0.1, 4), fn=RSS, control=control)
res
xg <- seq(verschiebung, extrapol, by=1/12)#bis 75 zum extrapolieren
yg <- reg(v=res$par,xg)
B <- data.frame(x=xg,BEV=yg)

# CI for shape parameter
se <- sd(BEV$y)/sqrt(length(BEV$y))
shape_lo <- res$par[2]-z*se
shape_up <- res$par[2]+z*se
# CI for scale parameter # https://math.stackexchange.com/questions/3569295/deriving-confidence-interval-for-scale-parameter-of-weibull-distribution
scale_lo <- res$par[1]-z*se*res$par[1]
scale_up <- res$par[1]+z*se*res$par[1]
# future curve for lower CI
xg <- seq(verschiebung, extrapol, by=1/12)#bis 75 zum extrapolieren
yg <- reg(v=c(scale_lo,shape_lo),xg)
B <- data.frame(B, "BEV_lower"=yg)
# future curve for lower CI
xg <- seq(verschiebung, extrapol, by=1/12)#bis 75 zum extrapolieren
yg <- reg(v=c(scale_up,shape_up),xg)
B <- data.frame(B,"BEV_upper"=yg)


#### optimize ICE ####
xg<-data_belgium_looped$year
yg<-as.double(data_belgium_looped$ice_share)
ICE <- data.frame(x=xg,y=yg)
control <- list(maxit = 100000, reltol=10^-30)  # Hier kannst du die maximale Anzahl der Iterationen anpassen
res_ice <- optim(par=c(-0.1, 4), fn=RSS_ice, control=control)
xg <- seq(verschiebung, extrapol, by=1/12)#bis 75 zum extrapolieren
yg <- reg_ice(v=res_ice$par,xg, type="ICE")
B <- data.frame(B, ICE=yg)
# CI for shape parameter 
se <- sd(ICE$y)/sqrt(length(ICE$y))
weibull_lo <- res_ice$par[2]-z*se
weibull_up <- res_ice$par[2]+z*se
# future curve for lower CI
xg <- seq(verschiebung, extrapol, by=1/12)#bis 75 zum extrapolieren
yg <- reg_ice(v=c(res_ice$par[1], weibull_lo), xg)
B <- data.frame(B, "ICE_upper"=yg)
# future curve for lower CI
xg <- seq(verschiebung, extrapol, by=1/12)#bis 75 zum extrapolieren
yg <- reg_ice(v=c(res_ice$par[1], weibull_up), xg)
B <- data.frame(B,"ICE_lower"=yg)

B$Hybrid <- 1-B$BEV-B$ICE
B$Hybrid_upper <- 1- B$BEV_lower - B$ICE_lower
B$Hybrid_lower <- 1- B$BEV_upper - B$ICE_upper

#### set up Hybrid estimate data.frame ####
Hybrid <- BEV
Hybrid$y <- 1 - BEV$y - ICE$y

#### add quarter ####
belgium <- data.frame(B, "Type"="New Registrations")
new_A <- data.frame(BEV, Type="New Registrations")
new_A <- subset(new_A, new_A$x>=verschiebung)
new_A <- data.frame(BEV, Type="New Registrations", Quarter=BEV$x)
new_A$Quarter <- ifelse(new_A$x%%1 <0.999, "Q4", new_A$Quarter)
new_A$Quarter <- ifelse(new_A$x%%1 <0.668, "Q3", new_A$Quarter)
new_A$Quarter <- ifelse(new_A$x%%1 <0.418, "Q2", new_A$Quarter)
new_A$Quarter <- ifelse(new_A$x%%1 <0.168, "Q1", new_A$Quarter)
new_A$Quarter <- ifelse(new_A$x <= lastyearly, "Yearly", new_A$Quarter) # speziell Australien gemischt jährlich quartalsweise

new_A$overall <- data_belgium_looped$overall
new_A$time_interval <- data_belgium_looped$time_interval

#### keine negativen Werte ####
belgium$Hybrid <- ifelse(belgium$Hybrid < 0, 0, belgium$Hybrid)
belgium$Hybrid_upper <- ifelse(belgium$Hybrid_upper < 0, 0, belgium$Hybrid_upper)
belgium$Hybrid_lower <- ifelse(belgium$Hybrid_lower < 0, 0, belgium$Hybrid_lower)

time_80_belgium <- max(subset(belgium, belgium$BEV<=0.8 & belgium$BEV >= 0.2)$x)
time_50_belgium <- max(subset(belgium, belgium$BEV<=0.5 & belgium$BEV >= 0.2)$x)
time_20_belgium <- max(subset(belgium, belgium$BEV<=0.2 & belgium$BEV >= 0.1)$x)
time_20_to_80_belgium <- max(subset(belgium, belgium$BEV<=0.8 & belgium$BEV >= 0.2)$x)-min(subset(belgium, belgium$BEV<=0.8 & belgium$BEV >= 0.2)$x)
print(time_20_to_80_belgium)
time_80_to_20_belgium <- max(subset(belgium, belgium$ICE<=0.8 & belgium$ICE >= 0.2)$x)-min(subset(belgium, belgium$ICE<=0.8 & belgium$ICE >= 0.2)$x)
bev_time[i] <- time_20_to_80_belgium
ice_time[i] <- time_80_to_20_belgium
}

timer_belgium <- data.frame("year"=data_belgium[1:length(bev_time),]$year, "BEV_time"=bev_time, "ICE_time"=ice_time)
# Letzten Index mit -Inf finden
last_inf_index <- max(which(timer_belgium$BEV_time == -Inf))
last_inf_index_ICE <- max(which(timer_belgium$ICE_time == -Inf))
last_inf_index <- max(last_inf_index, last_inf_index_ICE)
last_inf_index <- max(last_inf_index, 0)
# DataFrame ab dem letzten -Inf-Wert kürzen, und 2 Monate später weil sonst fast 0
timer_belgium_short <- timer_belgium[(last_inf_index + 1+2):nrow(timer_belgium), ]


#### plot timer ####
# einmalig:
#install.packages("devtools")
#devtools::install_github("expersso/ecb")

# dann:
library(ecb)
# add ECB interest rates
# Deine Daten vorbereiten
ecb_data <- get_data("FM.B.U2.EUR.4F.KR.MRR_FR.LEV")
ecb_data$obstime <- as.Date(ecb_data$obstime)
ecb_data <- ecb_data %>% mutate(year = year(obstime) + (yday(obstime) - 1) / 365)
#ecb_data <- ecb_data %>% 
#    select(year, obsvalue) %>% # obsvalue ist korrekt
#    rename(ECB_rate = obsvalue) # umbenennen in ECB_rate
ecb_data$year <- ecb_data$year - 1
ecb_data$ECB_rate <- ecb_data$obsvalue/100

# Lade die Leitzins-Daten der FED
# Lade tidyquant
library(tidyquant)

# Lade FED Leitzinsen (Federal Funds Rate)
fed_rates <- tq_get("FEDFUNDS", get = "economic.data", from = "1990-01-01")
fed_rates <- fed_rates %>% mutate(year = year(date) + (yday(date) - 1) / 365)
fed_rates$year <- fed_rates$year - 1
fed_rates$FED_rate <- fed_rates$price/100

# korrelation rechnen
# Schritt 1: Für jedes Jahr in timer_belgium_short den passenden ECB-Zins finden
timer_belgium_short$ECB_rate <- sapply(timer_belgium_short$year, function(yr) {
  # Finde den letzten Eintrag in ecb_data, der vor oder gleich dem aktuellen Jahr liegt
  last_rate <- ecb_data$ECB_rate[max(which(ecb_data$year <= yr))]
  return(last_rate)
})
timer_belgium_short$FED_rate <- sapply(timer_belgium_short$year, function(yr) {
  # Finde den letzten Eintrag in fed_rates, der vor oder gleich dem aktuellen Jahr liegt
  last_rate <- fed_rates$FED_rate[max(which(fed_rates$year <= yr))]
  return(last_rate)
})
cor_BEVIce_ECB <- cor(timer_belgium_short$BEV_time, timer_belgium_short$FED_rate, use = "complete.obs")
cor_ICE_ECB <- cor(timer_belgium_short$ICE_time, timer_belgium_short$FED_rate, use = "complete.obs")

print(cor_BEVIce_ECB)
print(cor_ICE_ECB)

# Relevante Variablen auswählen und in einer nbelgiumen DataFrame speichern
cor_data <- timer_belgium_short[, c("BEV_time", "ICE_time", "ECB_rate")]
cor_matrix <- cor(cor_data, use = "complete.obs")
print(cor_matrix)
library(ggcorrplot)
library(gridExtra)
library(grid)
# Create the correlation plot
cor_plot <- ggcorrplot(cor_matrix, lab = TRUE, type = "lower",
                       lab_size = 3,
                       colors = c("#6D9EC1", "white", "#E46726"),
                       title = "Correlation Matrix for transition time an ECB rate - belgium",
                       ggtheme = theme_minimal())

# Convert the correlation matrix into a table grob
cor_table <- tableGrob(round(cor_matrix, 2), theme = ttheme_minimal())
# Combine the plot and the table
correlation_table_plot <- grid.arrange(cor_table, ncol = 1, heights = c(1, 1))
correlation_plot <- grid.arrange(cor_plot, cor_table, ncol = 1, heights = c(2, 1))

# Plot erstellen
# DIE 100 SIND EINFACH NUR SKALIERUNG DAMIT DIE ACHSE RECHTS SCHÖN AUSSIEHT
data_month <- (as.integer(((BEV$x %% 1) * 12 + 1)[length(BEV$x)]) + 1) %% 12

plot_timer <- ggplot(timer_belgium_short, aes(x = year)) +
  geom_line(aes(y = BEV_time, col = "BEV share to rise from 20% to 80% market share"), lwd = 1) +
  geom_line(aes(y = ICE_time, col = "ICE share to fall from 80% to 20% market share"), lwd = 1) +
  geom_step(data = subset(timer_belgium_short, timer_belgium_short$year >= min(timer_belgium_short$year)), aes(y = ECB_rate * 250, col = "ECB interest rate"), lwd = 1) +  # Skalieren der Zinssätze für die zweite Achse
  geom_step(data = subset(timer_belgium_short, timer_belgium_short$year >= min(timer_belgium_short$year)), aes(y = FED_rate * 250, col = "FED interest rate"), lwd = 1) +  # Skalieren der Zinssätze für die zweite Achse
  scale_x_continuous(breaks = seq(verschiebung, extrapol, 1), labels = function(x) paste0("Jan ", x + 1)) +
  scale_y_continuous(
    name = "Number of years expected",
    limits = c(0,max(timer_belgium_short$BEV_time, timer_belgium_short$ICE_time)+5),
    #sec.axis = sec_axis(~ . / 250, name = "interest rate (%)", labels = scales::percent_format(accuracy = 1))
  ) +
  labs(
    title = "Time expectation for belgium transition time using historical data",
    subtitle = "Each point in time marks what the expectation was at the time",
    caption = social_caption,
    x = " "
  ) +
  theme_minimal() +
  scale_color_manual(values = c("#33FF3B", "darkblue", "lightblue", "#FF5733"), name = "expected time for") +
  theme(
    axis.title = element_text(size = 32),
    axis.text = element_text(size = 28),   # Achsenticks
    plot.title = element_text(size = 40, face = "bold"),
    plot.subtitle = element_text(size = 24, color="black", lineheight = 0.3),
    legend.position = "bottom",  # Legende unter die x-Achse verschieben
    legend.direction = "horizontal",  # Legende horizontal ausrichten
    legend.title = element_text(size = 32),
    legend.text = element_text(size = 32),
    legend.key.width = unit(0.5, "cm"),  # Breite der Legenden-Schlüssel anpassen
    legend.key.height = unit(0.5, "cm"),  # Höhe der Legenden-Schlüssel anpassen
    #plot.caption = element_text(size = 24), # Quellenangabe etc.    
    plot.caption = element_markdown(hjust=0, size=24)  # Caption als Markdown/HTML interpretieren # hjust=1 heißt rechtsbündig
  ) #+
#theme(legend.position = c(0.5, 0.8), legend.background = element_rect(fill = "gray99"))

# Grafik hinzufügen
current_date <- format(Sys.Date(), "%Y")
plot_timer <- plot_timer + annotation_custom(grob = rasterGrob(as.raster(flag_img), interpolate = TRUE), 
                                             xmin = as.double((current_date)) + data_month / 12 - 1.5, 
                                             ymin = 0, ymax = 3)
#plot_timer <- plot_timer + annotate("text", x = as.double((current_date)) + data_month / 12 - 1, y = 1.75, label = "@LeRaffl", size = 5, hjust = 1, vjust = 1)
#plot_timer <- plot_timer + annotate("text", x = as.double((current_date)) + data_month / 12 - 1, y = 0.75, label = paste0("Estimation per ", Sys.Date()), size = 4, hjust = 1, vjust = 1)
#plot_timer <- plot_timer + annotate("text", x = as.double((current_date)) + data_month / 12 - 1, y = 0, label = paste0("Source: ", source, ", ECB, FED"), size = 3, hjust = 1, vjust = 1)

plot_timer


#### ggplot ####
plot_belgium <- ggplot(belgium, aes(x = x, y = BEV, color = Type)) +
  geom_ribbon(aes(ymin = BEV_lower, ymax = BEV_upper), fill = "grey", alpha = 0.5, color = NA) +  # Bereich zwischen lower und upper einfärben
  geom_line(lwd = 1) +
  ylim(0, 1.1) +
  geom_point(data = new_A, aes(x = x, y = y, color = Quarter
                               #,shape = time_interval
                               ), size=default_size+(new_A$overall-mean(new_A$overall))/(sd(new_A$overall)) ) +
  scale_x_continuous(breaks = seq(verschiebung, extrapol, ifelse(extrapol>2045,4,2)), labels = function(x) paste0("Jan ", x + 1), limits=c(verschiebung, min(extrapol, 2045))) + 
  scale_y_continuous(breaks = seq(0, 1, 0.1), labels = unit_format(unit = "%", scale = 1e2)) +  # Y-Achse in 0.1er Schritten skalieren
  labs(title = paste0("BEV share in new registrations in Belgium - an Extrapolation"),
       #subtitle = paste0("Model for new registrations: y=1-exp(", round(res$par[1], 5), "x^", round(res$par[2], 2), ")"),
       subtitle = paste0("expected time for BEV to rise from 20% to 80%: ", floor(time_20_to_80_belgium),
                         " years ", round(12*(time_20_to_80_belgium-floor(time_20_to_80_belgium)),0), " months"),
       caption = entire_caption,
       x = " ",
       y = "BEV share") +
  theme_minimal() +
  theme(
    legend.position = c(0.93, 0.68), 
    legend.background = element_rect(fill = "gray99"),
    axis.title = element_text(size = 32),  # Achsentitel
    axis.text = element_text(size = 28),   # Achsenticks
    legend.title = element_text(size = 32),# Legendentitel
    legend.text = element_text(size = 32), # Legendentext
    plot.title = element_text(size = 40, face = "bold"), # Titel
    plot.subtitle = element_text(size=36), 
    #plot.caption = element_text(size = 20), # Quellenangabe etc.    
    plot.caption = element_markdown(hjust=0, size=34)  # Caption als Markdown/HTML interpretieren # hjust=1 heißt rechtsbündig
  ) +  
  #scale_shape_manual(values = c(16, 17, 18, 19), name = "Shape") +
  scale_color_manual(values = c("#FF5733", "#FFC300", "#33FF3B", "#33A1FF", "#B633FF", "#FF33E9"), name = "Color") #+

#### add yearly estimates as text and flag ####
plot_belgium <- plot_belgium + annotate("text", x=min(BEV$x), y=1, label="New Registration estimates in", size=10,hjust=0, vjust=1, col="red")
counter <- 0
while(round(subset(belgium, belgium$x==2024+counter & belgium$Type=="New Registrations")$BEV*100, 1) < 100 & 1-0.05*(counter+1)>0.1){
  plot_belgium <- plot_belgium + annotate("text", x=min(BEV$x)+0.5, y=1-0.05*(counter+1), label=paste0("Jan ",2025+counter,": ",round(subset(belgium, belgium$x==2024+counter & belgium$Type=="New Registrations")$BEV*100, 1),"%"), size=10,hjust=0, vjust=1, col="red")
  counter <- counter+1
}
plot_belgium <- plot_belgium + annotation_custom(grob = rasterGrob(as.raster(flag_img), interpolate = TRUE, width = unit(1*1920/1280
                                                                                                                                 , "in"), height = unit(1, "in")), 
                                             xmin = min(extrapol-4, 2045-4), ymin=-0.9)
plot_belgium


#### plot BEV + ICE + PHEV ####
ICE <- data.frame(ICE, "overall"=data_belgium$overall)
BEV <- data.frame(BEV, "overall"=data_belgium$overall)
Hybrid <- data.frame(Hybrid, "overall"=data_belgium$overall)


plot_ICE_BEV_belgium <- ggplot(belgium, aes(x = x, y = BEV, color = Type)) +
  geom_ribbon(aes(ymin = BEV_lower, ymax = BEV_upper), fill = "green", alpha = 0.5, color = NA) +  # Bereich zwischen lower und upper einfärben
  geom_line(aes(y = BEV, color="BEV", shape='BEV')) +
  geom_point(data = BEV, aes(x=x, y=y,color = "BEV", shape = "BEV"), size=default_size+(BEV$overall-mean(BEV$overall))/(sd(BEV$overall)) )+
  geom_ribbon(aes(ymin = ICE_lower, ymax = ICE_upper), fill = "red", alpha = 0.5, color = NA) +  # Bereich zwischen lower und upper einfärben
  geom_line(aes(y = ICE, color="ICE", shape='ICE')) +
  geom_point(data = ICE, aes(x=x, y=y, color = "ICE", shape = "ICE"), size=default_size+(ICE$overall-mean(ICE$overall))/(sd(ICE$overall)) )+
  geom_ribbon(aes(ymin = Hybrid_lower, ymax = Hybrid_upper), fill = "blue", alpha = 0.5, color = NA) +  # Bereich zwischen lower und upper einfärben
  geom_line(aes(y = Hybrid, color="PHEV", shape="PHEV")) +
  geom_point(data = data_belgium, aes(x=year, y=hybrid_share, color = "PHEV", shape = "PHEV"), size=default_size+(Hybrid$overall-mean(Hybrid$overall))/(sd(Hybrid$overall)) )+
  ylim(0, 1.1) +
  scale_x_continuous(breaks = seq(2006, extrapol, ifelse(extrapol>2045,4,2)), labels = function(x) paste0("Jan ", x + 1), limits=c(verschiebung, min(extrapol, 2045))) + 
  scale_y_continuous(breaks = seq(0, 1, 0.1), labels = unit_format(unit = "%", scale = 1e2)) +  # Y-Achse in 0.1er Schritten skalieren
  labs(title = paste0("BEV / ICE / PHEV share of new registrations in Belgium - an Extrapolation"),
       #subtitle = paste0("Model for new registrations: y=1-exp(", round(res$par[1], 5), "x^", round(res$par[2], 2), ")"),
       subtitle = paste0("expected time for ICE to drop from 80% to 20%: ", floor(time_80_to_20_belgium),
                         " years ", round(12*(time_80_to_20_belgium-floor(time_80_to_20_belgium)),0), " months"),
       caption = entire_caption,
       x = " ",
       y = "New Registration Share") +
  theme_minimal() +
  theme(
    legend.position = c(0.95, 0.68), 
    legend.background = element_rect(fill = "gray99"),
    axis.title = element_text(size = 32),  # Achsentitel
    axis.text = element_text(size = 28),   # Achsenticks
    legend.title = element_text(size = 32),# Legendentitel
    legend.text = element_text(size = 32), # Legendentext
    plot.title = element_text(size = 40, face = "bold"), # Titel
    plot.subtitle = element_text(size=36), 
    #plot.caption = element_text(size = 20), # Quellenangabe etc.    
    plot.caption = element_markdown(hjust=0, size=34)  # Caption als Markdown/HTML interpretieren # hjust=1 heißt rechtsbündig
  ) +  
  scale_color_manual(name='Legend',
                     breaks=c('ICE', 'BEV', 'PHEV'),
                     values=c('ICE'='red', 'BEV'='green', 'PHEV'='blue')
  ) +
  scale_shape_manual(name = 'Legend',
                     breaks = c('ICE', 'BEV', 'PHEV'),
                     values = c('ICE' = 15, 'BEV' = 16, 'PHEV' = 23))

# Grafik hinzufügen

#### add yearly estimates as text and a flag ####
plot_ICE_BEV_belgium <- plot_ICE_BEV_belgium + annotate("text", x=min(belgium$x), y=0.9, label="New ICE in", size=10,hjust=0, vjust=1, col="red")
counter <- 0
while(5 < round(subset(belgium, belgium$x==2024+counter-1 & belgium$Type=="New Registrations")$ICE*100, 1) & 1-0.05*(counter+1)>0.1) {
  plot_ICE_BEV_belgium <- plot_ICE_BEV_belgium + annotate("text", x=min(belgium$x)+0.5, y=0.85-counter*0.05, label=paste0("Jan ", 2024+counter+1,": ",round(subset(belgium, belgium$x==2024+counter & belgium$Type=="New Registrations")$ICE*100, 1),"%"), size=10,hjust=0, vjust=1, col="red")
  counter <- counter+1
}
plot_ICE_BEV_belgium <- plot_ICE_BEV_belgium + annotation_custom(grob = rasterGrob(as.raster(flag_img), interpolate = TRUE, width = unit(2*1920/1280
                                                                                                                                                 , "cm"), height = unit(2, "cm")), 
                                                             xmin = min(extrapol-4, 2045-4), ymin=-0.9)
print(plot_ICE_BEV_belgium)

#### output graphic ####
plot_belgium
# Erzbelgiumge den Dateinamen mit dem aktuellen Datum
ggsave(paste0("belgium_", format(Sys.Date(), "%Y%m%d"), ".png"), path = "/Users/raphaelwellmann/Library/Mobile Documents/com~apple~CloudDocs/R/bev_share_belgium", 
       plot = plot_belgium, width = 12.80, height = 7.20, units = "in", dpi = 300, bg = "white")

ggsave(paste0("belgium_ICE_BEV_", format(Sys.Date(), "%Y%m%d"), ".png"), path = "/Users/raphaelwellmann/Library/Mobile Documents/com~apple~CloudDocs/R/bev_share_belgium", 
       plot = plot_ICE_BEV_belgium, width = 12.80, height = 7.20, units = "in", dpi = 300, bg = "white")

ggsave(paste0("belgium_time_", format(Sys.Date(), "%Y%m%d"), ".png"), path = "/Users/raphaelwellmann/Library/Mobile Documents/com~apple~CloudDocs/R/bev_share_belgium", 
       plot = plot_timer, width = 12.80, height = 7.20, units = "in", dpi = 300, bg = "white")

#ggsave(paste0("belgium_time_correlation_", format(Sys.Date(), "%Y%m%d"), ".png"), path = "/Users/raphaelwellmann/Library/Mobile Documents/com~apple~CloudDocs/R/bev_share_belgium", 
#       plot = correlation_plot, width = 12.80, height = 7.20, units = "in", dpi = 300, bg = "white")

ggsave(paste0("belgium_ttm_shares_", format(Sys.Date(), "%Y%m%d"), ".png"), path = "/Users/raphaelwellmann/Library/Mobile Documents/com~apple~CloudDocs/R/bev_share_belgium", 
       plot = TTM_barplot_belgium, width = 1280, height = 720, units = "px", dpi = 300, bg = "white")

#### save in Google Sheets ####
# Authentifiziere dich, falls nötig
# gs4_auth()  # nur nötig beim ersten Mal

# Sheet-ID (aus der URL) – hier als Beispiel:
sheet_id <- "1u7HyIqxSAeSEiU4E3wht-9Z7qBlboRiOsMp_467za4Y"  # ersetzen!

# prepare data
country <- "Belgium"
library(googlesheets4)
library(dplyr)

safe_numeric_chr <- function(x, placeholder = "Inf") {
  ifelse(is.finite(x), as.double(x), placeholder)
}

upsert_country_result <- function(sheet_id, sheet_name = "per_country", country, bev_ttm, bev_20, bev_50, bev_80, bev_20_80, ice_80_20, scale, shape, movement, updated_to) {
  timestamp <- Sys.time()
  
  # Load all data from Sheet
  existing <- read_sheet(sheet_id, sheet = sheet_name)
  
  # Prepare new line
  new_row <- data.frame(
    Country = country,
    Timestamp = timestamp,
    BEV_TTM = bev_ttm,
    BEV_20 = bev_20,
    BEV_50 = bev_50,
    BEV_80 = bev_80,
    BEV_20_to_80 = safe_numeric_chr(bev_20_80),   # -> "Inf" oder "123.4"
    ICE_80_to_20 = safe_numeric_chr(ice_80_20),
    Scale = scale,
    Shape = shape,
    Movement =  movement,
    Updated_to = updated_to
  )
  
  # Check if country already in there
  if (country %in% existing$Country) {
    row_index <- which(existing$Country == country)
    range <- paste0(sheet_name, "!A", row_index + 1)  # +1 weil Header in Zeile 1
    range_write(sheet_id, data = new_row, range = range, col_names = FALSE)
  } else {
    sheet_append(sheet_id, new_row, sheet = sheet_name)
  }
}
as_date_from_numeric <- function(x, placeholder = NA_character_) {
  ## placeholder kann z. B. NA_character_, "Inf" oder "NA" sein
  if (!is.finite(x)) return(placeholder)
  
  year  <- floor(x) + 1
  month <- floor(12 * (x %% 1)) + 1
  as.Date(sprintf("%04d-%02d-01", year, month))
}
upsert_country_result(
  sheet_id = sheet_id,
  country = country,
  bev_ttm = tail(data_belgium$`BEV TTM`, 1),  # Letzter BEV TTM Wert
  bev_20 = as_date_from_numeric(time_20_belgium, "Inf"),
  bev_50 = as_date_from_numeric(time_50_belgium, "Inf"),
  bev_80 = as_date_from_numeric(time_80_belgium, "Inf"),
  bev_20_80 = time_20_to_80_belgium,
  ice_80_20 = time_80_to_20_belgium,
  scale = res$par[1],
  shape = res$par[2],
  movement = verschiebung,
  updated_to = tail(sub("M", "-", data_belgium$YYYYMMM), n=1)
)
