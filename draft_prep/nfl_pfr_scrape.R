library(tidyverse)
library(rvest)
library(data.table)

options(digits = 4)

setwd('C:/Users/Matt/Documents/DS Practice/NFLFFL')

year <- '2020'

scoring <- 'half-ppr'
# scoring <- 'standard'

# current week ----

scores.url <- 'https://www.nfl.com/schedules/'

scores.page <- read_html(scores.url) 

currweek <- html_nodes(scores.page, '.nfl-c-content-header__roofline') %>%
  html_text() %>%
  str_extract("WEEK \\d+")

currweek <- str_extract(currweek[!is.na(currweek)], "\\d+")

# PFR ------------------------------------------------------------------

url <- paste0('https://www.pro-football-reference.com/years/', year, '/')
lastweek = (as.numeric(currweek)-1)

passing = data.frame()
rushing = data.frame()
receiving = data.frame()

for (week in 1:lastweek) {
  print(week)
  week.url = paste0(url, 'week_', week, '.htm')
  week.page <- read_html(week.url) 
  week.links.spots <- html_nodes(week.page, 'a') %>%
    html_text()
  week.links <- html_nodes(week.page, 'a')[str_detect(week.links.spots, 'All Week \\d+ .+')] %>%
    as.character() %>%
    str_extract('a href.+\\\"') %>%
    str_replace('\\Qa href=\"\\E', '') %>%
    str_replace('"', '')
  #week.links = paste0('https://www.pro-football-reference.com', week.links)
  week.links = week.links[c(1:3)]
  for (link in week.links) {
    tab.page <- read_html(link)
    tab.table <- data.frame(html_table(html_nodes(tab.page, '#results')))
    stat <- tolower(names(tab.table[14]))
    print(stat)
    if (tab.table[1,1] == 'Rk') {
      tab.table <- setNames(tab.table, tab.table[1,])
      tab.table <- tab.table[-1,]
      tab.table <- tab.table[-which(tab.table$Rk== "Rk"),]
    }
    assign(stat, rbind(get(stat), tab.table))
  }
  xpa.link = paste0('https://www.pro-football-reference.com/play-index/pgl_finder.cgi?request=1&match=game&year_min=',year,'&year_max=',year,'&season_start=1&season_end=-1&pos%5B%5D=QB&pos%5B%5D=WR&pos%5B%5D=RB&pos%5B%5D=TE&pos%5B%5D=OL&pos%5B%5D=DL&pos%5B%5D=LB&pos%5B%5D=DB&is_starter=E&game_type=R&career_game_num_min=1&career_game_num_max=400&qb_start_num_min=1&qb_start_num_max=400&game_num_min=0&game_num_max=99&week_num_min=', week,'&week_num_max=', week, '&c1stat=xpa&c1comp=gt&c1val=1&c5val=1&order_by=scoring')
  fga.link = paste0('https://www.pro-football-reference.com/play-index/fg_finder.cgi?request=1&year_min=',year,'&year_max=',year,'&game_type=R&game_num_min=0&game_num_max=99&week_num_min=', week,'&week_num_max=', week, '&min_distance=7&max_distance=80&order_by=game_date')
  xpa.page <- read_html(xpa.link)
  xpa.table <- data.frame(html_table(html_nodes(xpa.page, 'table'))) 
  xpa.table <- xpa.table %>%
    setNames(xpa.table[1,]) %>%
    setnames('', 'at') %>%
    filter(Rk != 'Rk') %>%
    select(-Rk)
  fga.page <- read_html(fga.link)
  fga.table <- html_nodes(fga.page, '#all_attempts') %>%
    html_nodes('.placeholder') %>%
    html_text()
  fga.table <- fga.table %>%
    setNames(fga.table[1,]) %>%
    setnames('', 'at') %>%
    filter(Rk != 'Rk') %>%
    select(-Rk)
  kicking.table <- full_join(fga.table, xpa.table)
}
pass.names <- c(names(passing)[1:13], paste0('passing_',names(passing)[14:length(names(passing))]))
pass.names[22] <- 'Sk Yds'
rush.names <- c(names(rushing)[1:13], paste0('rushing_',names(rushing)[14:length(names(rushing))]))
rec.names <- c(names(receiving)[1:13], paste0('receiving_',names(receiving)[14:length(names(receiving))]))

passing <- setNames(passing, pass.names) %>%
  setnames("", "at") %>%
  select(-Rk)
rushing <- setNames(rushing, rush.names) %>%
  setnames("", "at") %>%
  select(-Rk)
receiving <- setNames(receiving, rec.names) %>% 
  setnames("", "at") %>%
  select(-Rk)
kicking <- full_join(kicking.table, fga.table)
  
joined <- full_join(passing, rushing) %>% full_join(receiving)

joined[is.na(joined)]=0

joined$standard <- as.numeric(joined$passing_Yds) * 0.04 + as.numeric(joined$rushing_Yds) * 0.1 + as.numeric(joined$receiving_Yds) * 0.1 + as.numeric(joined$passing_Int)*(-2) + as.numeric(joined$passing_TD)*(4) + as.numeric(joined$rushing_TD)*(6) + as.numeric(joined$receiving_TD)*(6)
joined$half_ppr <- as.numeric(joined$passing_Yds) * 0.04 + as.numeric(joined$rushing_Yds) * 0.1 + as.numeric(joined$receiving_Yds) * 0.1 + as.numeric(joined$passing_Int)*(-2) + as.numeric(joined$passing_TD)*(4) + as.numeric(joined$rushing_TD)*(6) + as.numeric(joined$receiving_TD)*(6) + as.numeric(joined$receiving_Rec)*(.5)

fwrite(joined, 'C:/Users/Matt/Documents/DS Practice/NFLFFL/Data/ffl.csv')
