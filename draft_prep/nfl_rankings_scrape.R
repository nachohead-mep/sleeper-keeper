library(tidyverse)
library(rvest)
library(data.table)
library(zoo)
library(writexl)

options(digits = 4)

setwd('C:/Users/Matt/Documents/DS Practice/NFLFFL')

# running backs ----

runningbacks.url <- 'https://www.fantasypros.com/nfl/rankings/half-point-ppr-rb-cheatsheets.php'

runningbacks.page <- read_html(runningbacks.url) 

runningbacks <- html_nodes(runningbacks.page, '#rank-data') %>%
  html_table(fill=TRUE) %>%
  data.frame()

runningbacks <- runningbacks[-1,]

runningbacks$Tier <- str_replace(ifelse(str_detect(runningbacks$Rank, "Tier"),runningbacks$Rank, NA), "Tier ", "")
runningbacks$Tier <- na.locf(runningbacks$Tier)

runningbacks <- runningbacks[runningbacks[3] != "",]
runningbacks$Name <- str_replace(str_extract(runningbacks[[3]], ".* .+\\."),".\\.$","")
runningbacks$Team <- str_extract(runningbacks[[3]], "\\s[^ ]+$")

runningbacks.trim <- runningbacks %>%
  select(c('Name', 'Team','Rank', 'ADP', 'Tier'))

# wide receivers ----

receivers.url <- 'https://www.fantasypros.com/nfl/rankings/half-point-ppr-wr-cheatsheets.php'

receivers.page <- read_html(receivers.url) 

receivers <- html_nodes(receivers.page, '#rank-data') %>%
  html_table(fill=TRUE) %>%
  data.frame()

receivers <- receivers[-1,]

receivers$Tier <- str_replace(ifelse(str_detect(receivers$Rank, "Tier"),receivers$Rank, NA), "Tier ", "")
receivers$Tier <- na.locf(receivers$Tier)

receivers <- receivers[receivers[3] != "",]
receivers$Name <- str_replace(str_extract(receivers[[3]], ".* .+\\."),".\\.$","")
receivers$Team <- str_extract(receivers[[3]], "\\s[^ ]+$")

receivers.trim <- receivers %>%
  select(c('Name', 'Team','Rank', 'ADP', 'Tier'))

# tight ends ----

tightends.url <- 'https://www.fantasypros.com/nfl/rankings/half-point-ppr-te-cheatsheets.php'

tightends.page <- read_html(tightends.url) 

tightends <- html_nodes(tightends.page, '#rank-data') %>%
  html_table(fill=TRUE) %>%
  data.frame()

tightends <- tightends[-1,]

tightends$Tier <- str_replace(ifelse(str_detect(tightends$Rank, "Tier"),tightends$Rank, NA), "Tier ", "")
tightends$Tier <- na.locf(tightends$Tier)

tightends <- tightends[tightends[3] != "",]
tightends$Name <- str_replace(str_extract(tightends[[3]], ".* .+\\."),".\\.$","")
tightends$Team <- str_extract(tightends[[3]], "\\s[^ ]+$")

tightends.trim <- tightends %>%
  select(c('Name', 'Team','Rank', 'ADP', 'Tier'))

# quarterbacks ----

quarterbacks.url <- 'https://www.fantasypros.com/nfl/rankings/qb-cheatsheets.php'

quarterbacks.page <- read_html(quarterbacks.url) 

quarterbacks <- html_nodes(quarterbacks.page, '#rank-data') %>%
  html_table(fill=TRUE) %>%
  data.frame()

quarterbacks <- quarterbacks[-1,]

quarterbacks$Tier <- str_replace(ifelse(str_detect(quarterbacks$Rank, "Tier"),quarterbacks$Rank, NA), "Tier ", "")
quarterbacks$Tier <- na.locf(quarterbacks$Tier)

quarterbacks <- quarterbacks[quarterbacks[3] != "",]
quarterbacks$Name <- str_replace(str_extract(quarterbacks[[3]], ".* .+\\."),".\\.$","")
quarterbacks$Team <- str_extract(quarterbacks[[3]], "\\s[^ ]+$")

quarterbacks.trim <- quarterbacks %>%
  select(c('Name', 'Team','Rank', 'ADP', 'Tier'))

# overall ----

overall.url <- 'https://www.fantasypros.com/nfl/rankings/half-point-ppr-cheatsheets.php'

overall.page <- read_html(overall.url) 

overall <- html_nodes(overall.page, '#rank-data') %>%
  html_table(fill=TRUE) %>%
  data.frame()

overall <- overall[-1,]

overall$Tier <- str_replace(ifelse(str_detect(overall$Rank, "Tier"),overall$Rank, NA), "Tier ", "")
overall$Tier <- na.locf(overall$Tier)

overall <- overall[overall[3] != "",]
overall$Name <- str_replace(str_extract(overall[[3]], ".* .+\\."),".\\.$","")
overall$Team <- str_extract(overall[[3]], "\\s[^ ]+$")

overall.trim <- overall %>%
  select(c('Name', 'Team','Rank', 'ADP', 'Tier', 'Pos')) %>%
  setnames('Pos', 'Pos.Rank')

overall.trim$Pos <- str_replace_all(overall.trim$Pos.Rank, '\\d',"")

# overall context ----

overall.merge <- overall.trim %>%
  select(c('Name', 'Team', 'ADP', 'Rank', 'Tier')) %>%
  setNames(c('Name', 'Team', 'Overall ADP', 'Overall Rank', 'Overall Tier'))

rb <- inner_join(overall.merge, runningbacks.trim)
wr <- inner_join(overall.merge, receivers.trim)
te <- inner_join(overall.merge, tightends.trim)
qb <- inner_join(overall.merge, quarterbacks.trim)

rb$`Overall ADP` <- as.numeric(rb$`Overall ADP`)
rb$`Overall Rank` <- as.numeric(rb$`Overall Rank`)
rb$`Overall Tier` <- as.numeric(rb$`Overall Tier`)
rb$Rank <- as.numeric(rb$Rank)
rb$ADP <- as.numeric(rb$ADP)
rb$Tier <- as.numeric(rb$Tier)
rb$pos_tier <- paste0('RB', rb$Tier)
rb$player_code <- str_replace_all(tolower(trimws(paste0(rb$Name, rb$Team, "RB"))), "\\s|[[:punct:]]","")

wr$`Overall ADP` <- as.numeric(wr$`Overall ADP`)
wr$`Overall Rank` <- as.numeric(wr$`Overall Rank`)
wr$`Overall Tier` <- as.numeric(wr$`Overall Tier`)
wr$Rank <- as.numeric(wr$Rank)
wr$ADP <- as.numeric(wr$ADP)
wr$Tier <- as.numeric(wr$Tier)
wr$pos_tier <- paste0('WR', wr$Tier)
wr$player_code <- str_replace_all(tolower(trimws(paste0(wr$Name, wr$Team, "WR"))), "\\s|[[:punct:]]","")

qb$`Overall ADP` <- as.numeric(qb$`Overall ADP`)
qb$`Overall Rank` <- as.numeric(qb$`Overall Rank`)
qb$`Overall Tier` <- as.numeric(qb$`Overall Tier`)
qb$Rank <- as.numeric(qb$Rank)
qb$ADP <- as.numeric(qb$ADP)
qb$Tier <- as.numeric(qb$Tier)
qb$pos_tier <- paste0('QB', qb$Tier)
qb$player_code <- str_replace_all(tolower(trimws(paste0(qb$Name, qb$Team, "QB"))), "\\s|[[:punct:]]","")

te$`Overall ADP` <- as.numeric(te$`Overall ADP`)
te$`Overall Rank` <- as.numeric(te$`Overall Rank`)
te$`Overall Tier` <- as.numeric(te$`Overall Tier`)
te$Rank <- as.numeric(te$Rank)
te$ADP <- as.numeric(te$ADP)
te$Tier <- as.numeric(te$Tier)
te$pos_tier <- paste0('TE', te$Tier)
te$player_code <- str_replace_all(tolower(trimws(paste0(te$Name, te$Team, "TE"))), "\\s|[[:punct:]]","")

overall.trim$Rank <- as.numeric(overall.trim$Rank)
overall.trim$ADP <- as.numeric(overall.trim$ADP)
overall.trim$Tier <- as.numeric(overall.trim$Tier)
overall.trim$player_code <- str_replace_all(tolower(trimws(paste0(overall.trim$Name, overall.trim$Team, overall.trim$Pos))), "\\s|[[:punct:]]","")

fantasypros.tiers <- rbind(qb, rb, te, wr) %>%
  select(pos_tier, player_code)

# cleanup ----

remove(runningbacks, quarterbacks, receivers, tightends, overall, runningbacks.page, quarterbacks.page, receivers.page, tightends.page, overall.page, runningbacks.trim, quarterbacks.trim, receivers.trim, tightends.trim, overall.merge)

setwd('C:/Users/Matt/Documents/DS Practice/NFLFFL/data')

sheets <- list("overall" = overall.trim, 'rb'=rb, 'wr'=wr, "qb" = qb, 'te'=te)
write_xlsx(sheets, "2020_ranks.xlsx")

# auction ----

#rb
#PPR

auction.ppr.rb.url <- 'https://www.cbssports.com/fantasy/football/rankings/ppr/RB/yearly/'

auction.ppr.rb.page <- read_html(auction.ppr.rb.url) 

auction.rb <- html_nodes(auction.ppr.rb.page, '.player-row')

auction.ppr.rb.names <- html_nodes(auction.rb, 'a') %>%
  html_attr('href') %>%
  str_extract('[[:alpha:]]+-[[:alpha:]]+') %>%
  str_replace_all('-',' ')

auction.ppr.rb.tp <- html_nodes(auction.rb, '.team') %>%
  html_text()

auction.ppr.rb.raw <- data.frame(names=auction.ppr.rb.names, tp = auction.ppr.rb.tp)
auction.ppr.rb.raw$team <- trimws(str_extract(auction.ppr.rb.raw$tp, '\\s+[[:upper:]]+'))
auction.ppr.rb.raw$value <- as.numeric(str_replace(trimws(str_extract(auction.ppr.rb.raw$tp, '\\s+\\$\\d+')),'\\$',""))
auction.ppr.rb.raw <- auction.ppr.rb.raw %>%
  select(-tp)

#standard

auction.std.rb.url <- 'https://www.cbssports.com/fantasy/football/rankings/standard/RB/yearly/'

auction.std.rb.page <- read_html(auction.std.rb.url) 

auction.rb <- html_nodes(auction.std.rb.page, '.player-row')

auction.std.rb.names <- html_nodes(auction.rb, 'a') %>%
  html_attr('href') %>%
  str_extract('[[:alpha:]]+-[[:alpha:]]+') %>%
  str_replace_all('-',' ')

auction.std.rb.tp <- html_nodes(auction.rb, '.team') %>%
  html_text()

auction.std.rb.raw <- data.frame(names=auction.std.rb.names, tp = auction.std.rb.tp)
auction.std.rb.raw$team <- trimws(str_extract(auction.std.rb.raw$tp, '\\s+[[:upper:]]+'))
auction.std.rb.raw$value <- as.numeric(str_replace(trimws(str_extract(auction.std.rb.raw$tp, '\\s+\\$\\d+')),'\\$',""))
auction.std.rb.raw <- auction.std.rb.raw %>%
  select(-tp)

auction.rb.raw <- rbind(auction.std.rb.raw, auction.ppr.rb.raw) %>%
  group_by(names) %>%
  summarise(team=first(team),
            value=round(2*mean(value))) %>%
  arrange(desc(value))

auction.rb.raw$pos <- 'RB'

#wr
#PPR

auction.ppr.wr.url <- 'https://www.cbssports.com/fantasy/football/rankings/ppr/WR/yearly/'

auction.ppr.wr.page <- read_html(auction.ppr.wr.url) 

auction.wr <- html_nodes(auction.ppr.wr.page, '.player-row')

auction.ppr.wr.names <- html_nodes(auction.wr, 'a') %>%
  html_attr('href') %>%
  str_extract('[[:alpha:]]+-[[:alpha:]]+') %>%
  str_replace_all('-',' ')

auction.ppr.wr.tp <- html_nodes(auction.wr, '.team') %>%
  html_text()

auction.ppr.wr.raw <- data.frame(names=auction.ppr.wr.names, tp = auction.ppr.wr.tp)
auction.ppr.wr.raw$team <- trimws(str_extract(auction.ppr.wr.raw$tp, '\\s+[[:upper:]]+'))
auction.ppr.wr.raw$value <- as.numeric(str_replace(trimws(str_extract(auction.ppr.wr.raw$tp, '\\s+\\$\\d+')),'\\$',""))
auction.ppr.wr.raw <- auction.ppr.wr.raw %>%
  select(-tp)

#standard

auction.std.wr.url <- 'https://www.cbssports.com/fantasy/football/rankings/standard/WR/yearly/'

auction.std.wr.page <- read_html(auction.std.wr.url) 

auction.wr <- html_nodes(auction.std.wr.page, '.player-row')

auction.std.wr.names <- html_nodes(auction.wr, 'a') %>%
  html_attr('href') %>%
  str_extract('[[:alpha:]]+-[[:alpha:]]+') %>%
  str_replace_all('-',' ')

auction.std.wr.tp <- html_nodes(auction.wr, '.team') %>%
  html_text()

auction.std.wr.raw <- data.frame(names=auction.std.wr.names, tp = auction.std.wr.tp)
auction.std.wr.raw$team <- trimws(str_extract(auction.std.wr.raw$tp, '\\s+[[:upper:]]+'))
auction.std.wr.raw$value <- as.numeric(str_replace(trimws(str_extract(auction.std.wr.raw$tp, '\\s+\\$\\d+')),'\\$',""))
auction.std.wr.raw <- auction.std.wr.raw %>%
  select(-tp)

auction.wr.raw <- rbind(auction.std.wr.raw, auction.ppr.wr.raw) %>%
  group_by(names) %>%
  summarise(team=first(team),
            value=round(2*mean(value))) %>%
  arrange(desc(value))

auction.wr.raw$pos <- 'WR'

#qb
#PPR

auction.ppr.qb.url <- 'https://www.cbssports.com/fantasy/football/rankings/ppr/QB/yearly/'

auction.ppr.qb.page <- read_html(auction.ppr.qb.url) 

auction.qb <- html_nodes(auction.ppr.qb.page, '.player-row')

auction.ppr.qb.names <- html_nodes(auction.qb, 'a') %>%
  html_attr('href') %>%
  str_extract('[[:alpha:]]+-[[:alpha:]]+') %>%
  str_replace_all('-',' ')

auction.ppr.qb.tp <- html_nodes(auction.qb, '.team') %>%
  html_text()

auction.ppr.qb.raw <- data.frame(names=auction.ppr.qb.names, tp = auction.ppr.qb.tp)
auction.ppr.qb.raw$team <- trimws(str_extract(auction.ppr.qb.raw$tp, '\\s+[[:upper:]]+'))
auction.ppr.qb.raw$value <- as.numeric(str_replace(trimws(str_extract(auction.ppr.qb.raw$tp, '\\s+\\$\\d+')),'\\$',""))
auction.ppr.qb.raw <- auction.ppr.qb.raw %>%
  select(-tp)

#standard

auction.std.qb.url <- 'https://www.cbssports.com/fantasy/football/rankings/standard/QB/yearly/'

auction.std.qb.page <- read_html(auction.std.qb.url)

auction.qb <- html_nodes(auction.std.qb.page, '.player-row')

auction.std.qb.names <- html_nodes(auction.qb, 'a') %>%
  html_attr('href') %>%
  str_extract('[[:alpha:]]+-[[:alpha:]]+') %>%
  str_replace_all('-',' ')

auction.std.qb.tp <- html_nodes(auction.qb, '.team') %>%
  html_text()

auction.std.qb.raw <- data.frame(names=auction.std.qb.names, tp = auction.std.qb.tp)
auction.std.qb.raw$team <- trimws(str_extract(auction.std.qb.raw$tp, '\\s+[[:upper:]]+'))
auction.std.qb.raw$value <- as.numeric(str_replace(trimws(str_extract(auction.std.qb.raw$tp, '\\s+\\$\\d+')),'\\$',""))
auction.std.qb.raw <- auction.std.qb.raw %>%
  select(-tp)

auction.qb.raw <- rbind(auction.std.qb.raw, auction.ppr.qb.raw) %>%
  group_by(names) %>%
  summarise(team=first(team),
            value=round(2*mean(value))) %>%
  arrange(desc(value))

auction.qb.raw$pos <- 'QB'

#te
#PPR

auction.ppr.te.url <- 'https://www.cbssports.com/fantasy/football/rankings/ppr/TE/yearly/'

auction.ppr.te.page <- read_html(auction.ppr.te.url) 

auction.te <- html_nodes(auction.ppr.te.page, '.player-row')

auction.ppr.te.names <- html_nodes(auction.te, 'a') %>%
  html_attr('href') %>%
  str_extract('[[:alpha:]]+-[[:alpha:]]+') %>%
  str_replace_all('-',' ')

auction.ppr.te.tp <- html_nodes(auction.te, '.team') %>%
  html_text()

auction.ppr.te.raw <- data.frame(names=auction.ppr.te.names, tp = auction.ppr.te.tp)
auction.ppr.te.raw$team <- trimws(str_extract(auction.ppr.te.raw$tp, '\\s+[[:upper:]]+'))
auction.ppr.te.raw$value <- as.numeric(str_replace(trimws(str_extract(auction.ppr.te.raw$tp, '\\s+\\$\\d+')),'\\$',""))
auction.ppr.te.raw <- auction.ppr.te.raw %>%
  select(-tp)

#standard

auction.std.te.url <- 'https://www.cbssports.com/fantasy/football/rankings/standard/TE/yearly/'

auction.std.te.page <- read_html(auction.std.te.url) 

auction.te <- html_nodes(auction.std.te.page, '.player-row')

auction.std.te.names <- html_nodes(auction.te, 'a') %>%
  html_attr('href') %>%
  str_extract('[[:alpha:]]+-[[:alpha:]]+') %>%
  str_replace_all('-',' ')

auction.std.te.tp <- html_nodes(auction.te, '.team') %>%
  html_text()

auction.std.te.raw <- data.frame(names=auction.std.te.names, tp = auction.std.te.tp)
auction.std.te.raw$team <- trimws(str_extract(auction.std.te.raw$tp, '\\s+[[:upper:]]+'))
auction.std.te.raw$value <- as.numeric(str_replace(trimws(str_extract(auction.std.te.raw$tp, '\\s+\\$\\d+')),'\\$',""))
auction.std.te.raw <- auction.std.te.raw %>%
  select(-tp)

auction.te.raw <- rbind(auction.std.te.raw, auction.ppr.te.raw) %>%
  group_by(names) %>%
  summarise(team=first(team),
            value=round(2*mean(value))) %>%
  arrange(desc(value))

auction.te.raw$pos <- 'TE'

auction.all.raw <- rbind(auction.te.raw, auction.qb.raw, auction.rb.raw, auction.wr.raw)

auction.all.raw$player_code <- str_replace_all(tolower(trimws(paste0(auction.all.raw$names, auction.all.raw$team, auction.all.raw$pos))), "\\s|[[:punct:]]","")

overall.auction <- left_join(overall.trim, auction.all.raw) %>%
  select('Name', "Team", "Tier", "value")
qb.auction <- left_join(qb, auction.all.raw) %>%
  select('Name', "Team", "Tier", "value")
wr.auction <- left_join(wr, auction.all.raw) %>%
  select('Name', "Team", "Tier", "value")
rb.auction <- left_join(rb, auction.all.raw) %>%
  select('Name', "Team", "Tier", "value")
te.auction <- left_join(te, auction.all.raw) %>%
  select('Name', "Team", "Tier", "value")

sheets <- list("overall" = overall.auction, 'rb'=rb.auction, 'wr'=wr.auction, "qb" = qb.auction, 'te'=te.auction)
write_xlsx(sheets, "2020_auction_prep.xlsx")

remove(auction.ppr.qb.names, auction.ppr.qb.page, auction.ppr.qb.raw, auction.ppr.qb.tp, auction.ppr.qb.url, auction.ppr.rb.names, auction.ppr.rb.page)
