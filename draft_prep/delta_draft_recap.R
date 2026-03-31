library(tidyverse)
library(rvest)
library(data.table)
library(zoo)
library(writexl)

options(digits = 4)

setwd('C:/Users/Matt/Documents/DS Practice/NFLFFL/Data')

positions <- c("QB", "RB", "WR", "TE", "DST", "K")

raw <- fread('2020_delta_draft_recap.csv')

raw <- raw[!str_detect(raw$V1, 'ROUND'),]
raw <- raw[!(raw$V3=="" & raw$V1=="" & raw$V2==""),]

raw.left <- raw[!(raw$V1=='')]
raw.right <- raw[raw$V1=='']

raw.right$V1 <- str_replace(str_extract(raw.right$V3, '^\\D+,'),",","")
raw.right$V2 <- str_replace(str_extract(raw.right$V3, ',.+$'),", ","")

delta_recap <- raw.left %>%
  setNames(c("No.", "Manager", "Player"))

delta_recap$Pos <- raw.right$V1 %>%
  str_replace("\\/","")
delta_recap$Team <- raw.right$V2

remove(raw, raw.left, raw.right)

delta_recap.wranks <- data.frame()

for (pos in positions) {
  slice <- delta_recap[delta_recap$Pos==pos]
  slice$Pos.Rank <- seq(1, nrow(slice))
  slice$Pos.Rank <- paste0(pos, slice$Pos.Rank)
  delta_recap.wranks <- rbind(delta_recap.wranks, slice)
}

delta_recap <- delta_recap.wranks
delta_recap$No. <- as.numeric(delta_recap$No.)
delta_recap <- arrange(delta_recap, No.)
remove(delta_recap.wranks, slice, pos, positions)

my_team <- delta_recap[delta_recap$Manager == "Team Eskippy",]

delta_recap.fantasypros <- inner_join(delta_recap, overall.trim, by=c('Player'='Name', 'Pos'='Pos')) %>%
  select(-Team.x) %>%
  setnames('Pos.Rank.x', 'Pos.Rank.Draft') %>%
  setnames('Pos.Rank.y', 'Pos.Rank.FantasyPros')

delta_recap.fantasypros$pick_differential <- delta_recap.fantasypros$No. - delta_recap.fantasypros$Rank
delta_recap.fantasypros$pick_differential_ratio <- 100*(delta_recap.fantasypros$pick_differential / delta_recap.fantasypros$No.)
