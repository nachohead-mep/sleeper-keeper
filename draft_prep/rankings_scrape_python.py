# -*- coding: utf-8 -*-

"""

Spyder Editor



This is a temporary script file.

"""


import pandas as pd 
from bs4 import BeautifulSoup
import requests
from datetime import date, timedelta
import re
from selenium import webdriver
from selenium.webdriver.support.ui import Select
import time
import numpy as np
import math
import lxml
from string import ascii_uppercase

qb_scoring = '4pt'

ppr_scoring = 'half'

modes = ['ppr', 'standard']

import_draft_params = ['gamma', 'keepers']
import_draft = True

draft_type = 'auction'

positions = {'QB': ['quarterback'], 'RB': ['running-back'], 'WR': ['wide-receiver'], 'TE': ['tight-end'], 'K': ['kicker'], 'DST': ['defense']}

today = date.today()
year = today.year
if today.month > 2:
    current_season = year
else:
    current_season = year-1


path = r'C:\Users\Matt\Documents\DS Practice\WebDriver\\geckodriver.exe'

output_path = 'C:/Users/Matt/Documents/DS Practice/NFLFFL/Output/'

cbs_base_url = 'https://www.cbssports.com/fantasy/football/rankings/'
ffb_base_url = 'https://www.thefantasyfootballers.com/'
pfr_base_url = 'https://www.pro-football-reference.com/'
fpros_base_url = 'https://www.fantasypros.com/nfl/rankings/'
nffc_base_url = 'https://nfc.shgn.com/adp/football'

gamma_draft_keepers_url = 'https://sleeper.com/draft/nfl/1258477712587096064'
gamma_draft_results_url = 'https://sleeper.app/draft/nfl/736423088274718720'
delta_draft_keepers_url = 'https://sleeper.com/draft/nfl/1212820218368229376'
delta_draft_results_url = 'https://sleeper.com/draft/nfl/916474937517502465'
camp_draft_results_url = 'https://sleeper.com/draft/nfl/1257465651681832964'

rookie_adp_url = 'https://www.fantasypros.com/nfl/rankings/dynasty-rookies-overall.php'

player_suffix_regex = ' I+$| Jr\.$| V$| I+V$| VI+$| Sr\.$'


if import_draft:

    import_draft_url = globals()[f'{import_draft_params[0]}_draft_{import_draft_params[1]}_url']


# =============================================================================
# Fantasy Pros Rankings
# =============================================================================

fpros_rankings = pd.DataFrame()


driver = webdriver.Firefox(executable_path=path)

time.sleep(2)


for pos in list(positions.keys()) + ['OVERALL']:

    pos = pos.lower()

    if ppr_scoring == 'half':

        fpros_ppr_suffix = 'half-point-ppr-'

    elif ppr_scoring == 'ppr':

        fpros_ppr_suffix = 'ppr-'

    else:

        fpros_ppr_suffix = ''

    if pos in ['rb', 'wr', 'te']:

        fpros_scoring_url = fpros_ppr_suffix + pos + '-cheatsheets.php'

        type_string = 'pos'

    elif pos == 'overall':

        fpros_scoring_url = fpros_ppr_suffix + 'cheatsheets.php'

        type_string = 'ovr'

    else:

        fpros_scoring_url = pos + '-cheatsheets.php'

        type_string = 'pos'

    fpros_full_url = fpros_base_url + fpros_scoring_url

    print(fpros_full_url)

    driver.get(fpros_full_url)

    time.sleep(3)

    driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")

    time.sleep(1)

    driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")

    time.sleep(1)

    html = driver.page_source

    soup = BeautifulSoup(html, 'html.parser')

    fpros_table = soup.find(id='ranking-table')

    fpros_df = pd.read_html(str(fpros_table))[0]
    
        # Check how many levels the columns have
    if hasattr(fpros_df.columns, "nlevels"):
        print("Number of column index levels:", fpros_df.columns.nlevels)

        # If multi-level, drop the first one
        if fpros_df.columns.nlevels > 1:
            fpros_df.columns = fpros_df.columns.get_level_values(1)
    else:
        print("Columns are not a MultiIndex")

    fpros_df[f'{type_string}_tier'] = pd.to_numeric(fpros_df['RK'].replace(
        '(?<!Tier )\\d+', np.NaN, regex=True).replace('Tier ', '', regex=True).fillna(method='ffill'))

    fpros_df.columns = fpros_df.columns.str.lower()

    fpros_df = fpros_df.rename(columns={'rk': f'{type_string}_ecr', 'bye week': 'bye',
                               'ecr vs adp': f'{type_string}_ecr_v_{type_string}_adp'})

    if pos.upper() in list(positions.keys()):

        fpros_df['position'] = pos.upper()

    else:

        fpros_df['position'] = fpros_df['pos'].replace('\d+', '', regex=True)

        fpros_df = fpros_df.drop(columns=['pos'])

    fpros_df['strength_of_schedule'] = fpros_df['sos'].replace(
        'out of 5 stars|\D', "", regex=True).str[0]

    x = fpros_df['player name'].str.split(
        "(", n=2, expand=True).replace('\)', '', regex=True)

    fpros_df['player_name'] = x[0].str.strip()

    fpros_df['player_name'] = fpros_df['player_name'].replace(
        player_suffix_regex, '', regex=True)

    fpros_df['team'] = x[1].str.split(" ", n=1).str[0]

    fpros_df['mode'] = ppr_scoring

    fpros_df = fpros_df.drop(columns=['wsid', 'player name', 'sos'])

    fpros_df = fpros_df.dropna()

    fpros_df[f'{type_string}_ecr'] = pd.to_numeric(
        fpros_df[f'{type_string}_ecr'])

    fpros_df[f'{type_string}_ecr_v_{type_string}_adp'] = pd.to_numeric(
        fpros_df[f'{type_string}_ecr_v_{type_string}_adp'].replace('-$', 0, regex=True))

    fpros_df[f'{type_string}_adp'] = fpros_df[f'{type_string}_ecr'] + \
        fpros_df[f'{type_string}_ecr_v_{type_string}_adp']

    if pos == 'dst':

        fpros_df['player_first'] = ""

        fpros_df['player_first_init'] = ""

        fpros_df['player_last'] = ""

    else:

        x = fpros_df['player_name'].str.split(" ", n=1, expand=True)

        fpros_df['player_first'] = x[0]
        
        fpros_df['player_first'] = fpros_df['player_first'].apply(lambda x: re.sub('Hollywood', 'Marquise', x))

        fpros_df['player_first_init'] = fpros_df['player_first'].str[0]      
        

        player_last = x[1].apply(lambda y: re.sub('\w\.', '', y).strip())
        player_last = player_last.apply(lambda y: re.sub(
                    player_suffix_regex, '', y))
        player_last = player_last.apply(lambda y: re.sub('^S ', 'St. ', y))
        
        fpros_df['player_last'] = player_last
        
    if pos == 'overall':

        fpros_overall_rankings = fpros_df

    else:

        fpros_rankings = pd.concat([fpros_rankings,fpros_df])
    
fpros_rankings['player_first'].apply(lambda x: re.sub('Hollywood', 'Marquise', x))

driver.close()


del pos, fpros_ppr_suffix, fpros_scoring_url, fpros_full_url, html, soup, fpros_table, fpros_df, x


# =============================================================================
# CBS Rankings
# =============================================================================
    
cbs_rankings = pd.DataFrame()


driver = webdriver.Firefox(executable_path=path)

time.sleep(2)

dup_player_list = []

for mode in modes:

    mode_url = cbs_base_url + mode + '/'

    for position in positions.keys():

        full_url = mode_url + position + '/' + 'yearly/'

        driver.get(full_url)
        
        time.sleep(1)

        html = driver.page_source

        soup = BeautifulSoup(html, 'html.parser')

        analyst_tables = soup.find_all(class_='experts-column')

        for analyst in analyst_tables:

            player_info_panes = analyst.find_all(class_='player-row')

            analyst_name = re.sub(
                '-.*', '', analyst.find(class_='author-name').text).strip()

            for player_info_pane in player_info_panes:

                rank = player_info_pane.find(class_='rank').text.strip()

                orig_player_name = player_info_pane.find(
                    class_='player-name').text.strip()

                player_name = re.sub(
                    player_suffix_regex, '', orig_player_name)

                if position != 'DST':

                    player_last = re.sub('\w\.', '', player_name).strip()

                    player_last = re.sub('^S ', 'St. ', player_last)

                    player_first_init = re.sub(
                        "\.", "", re.search('\w\.', player_name).group())
                    
                    matching_rows = fpros_rankings[(fpros_rankings['player_last'] == player_last) & 
                   (fpros_rankings['player_first_init'] == player_first_init) & 
                   (fpros_rankings['position'] == position)]
                    
                    if len(matching_rows) == 1:
                        player_first = list(matching_rows['player_first'])[0]
                        team = list(matching_rows['team'])[0]
                    elif len(matching_rows) > 1:
                        print(f"Found multiple matches for {orig_player_name}")
                        dup_player_list.append(matching_rows)
                    elif len(matching_rows) < 1:
                        print(f"Found no matches for {orig_player_name}")
                        print(player_last in fpros_rankings['player_last'].values)
                        print(player_first_init in fpros_rankings['player_first_init'].values)
                        print(position in fpros_rankings['position'].values)
                    else: 
                        player_first = ''

                else:

                    player_last = player_name

                    player_first_init = ''
                    
                    player_first =  ''
                    
                    team = player_info_pane.find(class_='team').text
                    team = re.sub("\$|\d", '', team).strip()

                price = re.search(
                    '\$\d+', player_info_pane.find(class_='team').text).group()

                #team = player_info_pane.find(class_='team').text

                #team = re.sub("\$|\d", '', team).strip()

                player_row = pd.DataFrame({'analyst': analyst_name, 'position': position, 'mode': mode, 'pos_rank': [rank], 'player_name': [
                                          player_name], 'player_first': [player_first], 'player_first_init': [player_first_init], 'player_last': [player_last], 'price': [re.sub('\$', '', price)], 'team': [team]})
                
                #print(player_row)
                
                cbs_rankings = pd.concat([cbs_rankings,player_row])
                
cbs_rankings_copy = cbs_rankings.copy()
cbs_rankings = cbs_rankings_copy.copy()
cbs_rankings.reset_index(inplace=True)

for dup in dup_player_list:
    player_last = list(dup['player_last'])[0]
    player_first_init = list(dup['player_first_init'])[0]
    player_firsts = list(dup['player_first'])
    no_matches = len(dup)
    player_teams = list(dup['team'])
    position = list(dup['position'])[0]
    matching_rows = cbs_rankings[((cbs_rankings['player_last'] == player_last) & 
                   (cbs_rankings['player_first_init'] == player_first_init) & 
                   (cbs_rankings['position'] == position))]
    for i in range(len(matching_rows)):
        row = matching_rows.index[i]
        if len(matching_rows) / no_matches == 8:
            spot = i % no_matches
        else: 
            spot = 0
        print(player_firsts[spot])
        #matching_rows.iloc[row,pf_index] = player_firsts[spot]
        cbs_rankings['player_first'][row] = player_firsts[spot]
        #matching_rows.iloc[row,t_index] = player_teams[spot]
        cbs_rankings['team'][row] = player_teams[spot]
    matching_rows = cbs_rankings[((cbs_rankings['player_last'] == player_last) & 
                   (cbs_rankings['player_first_init'] == player_first_init) & 
                   (cbs_rankings['position'] == position))]
    #print(matching_rows.index)
    print(matching_rows[['player_name', 'player_first', 'team', 'pos_rank']])

cbs_rankings['pos_rank'] = pd.to_numeric(cbs_rankings['pos_rank'])

cbs_rankings['price'] = pd.to_numeric(cbs_rankings['price'])

cbs_rankings_halfppr = cbs_rankings.groupby(['analyst', 'position', 'player_first', 'player_name', 'player_first_init', 'player_last', 'team'], as_index=True).agg({
                                            'price': 'mean', 'pos_rank': 'mean'}).reset_index()

cbs_rankings_halfppr['mode'] = 'half'

cbs_rankings = pd.concat([cbs_rankings,cbs_rankings_halfppr])

driver.close()


del analyst_name, analyst_tables, cbs_base_url, full_url, mode, mode_url, player_info_panes, player_name, player_row, position, price, rank, team, player_last, player_first_init, cbs_rankings_halfppr

# =============================================================================
# Fantasy Footballers Rankings
# =============================================================================

driver = webdriver.Firefox(executable_path=path)

time.sleep(2)


ffb_rankings = pd.DataFrame()


for pos in positions:

    if pos in ['RB', 'WR', 'TE']:

        ffb_scoring_url = r'?scoring=' + ppr_scoring

    elif pos == 'QB':

        ffb_scoring_url = r'?scoring=' + qb_scoring
        ffb_scoring_url = ''

    else:

        ffb_scoring_url = ''

    ffb_full_url = ffb_base_url + \
        str(current_season) + '-' + \
            positions[pos][0] + '-rankings/' + ffb_scoring_url

    print(ffb_full_url)

    driver.get(ffb_full_url)

    time.sleep(2)

    html = driver.page_source

    soup = BeautifulSoup(html, 'html.parser')

    ffb_table = soup.find(class_='dataTable')

    ffb_df = pd.read_html(str(ffb_table))[0]

    if pos == 'DST':

        x = ffb_df['Player'].str.split("(", n = 1, expand = True).replace('\)','', regex=True)
        
        x[0] = x[0].str.strip()

        x[1] = x[1].str.strip()

        ffb_df['player_name'] = x[0].apply(lambda x: x.rsplit(' ', 1)[0])

        ffb_df['bye'] = x[1]

        ffb_df['player_first'] = ""

        ffb_df['player_first_init'] = ffb_df['player_name'].str[0]

        ffb_df['player_last'] = ""

        ffb_df = ffb_df.drop(columns=['Player'])

    else:

        x = ffb_df['Player'].str.split("(", n = 1, expand = True).replace('\)','', regex=True)

        x[0] = x[0].str.strip()

        x[1] = x[1].str.strip()
        
        #print(x[0])

        y = x[0].str.split(' ', n = 3)

        ffb_df['player_name'] = x[0].apply(lambda x: x.rsplit(' ', 1)[0])

        ffb_df['player_name'] = ffb_df['player_name'].replace(player_suffix_regex, '', regex=True)

        ffb_df['team'] = x[0].apply(lambda x: x.rsplit(' ', 1)[1])

        ffb_df['team'] = ffb_df['team'].replace('JAX', 'JAC', regex=True)

        ffb_df['bye'] = x[1]

        x = ffb_df['player_name'].str.split(" ", n = 1, expand = True)

        ffb_df['player_first'] = x[0]

        ffb_df['player_first_init'] = x[0].str[0]

        ffb_df['player_last'] = x[1]

        ffb_df = ffb_df.drop(columns=['Player'])

    ffb_df['position'] = pos 

    ffb_df['mode'] = ppr_scoring

    ffb_df = ffb_df.rename(columns={'Rank':'ffb_pos_rank'})

    if 'Clips' in ffb_df.columns:

        ffb_df = ffb_df.drop(columns=['Clips'])
   
    ffb_rankings = pd.concat([ffb_rankings,ffb_df])

# =============================================================================
# NFFC
# =============================================================================

driver.get(nffc_base_url)
time.sleep(2)

submit_button = driver.find_element("css selector", "input[type='submit']")

if draft_type == 'auction':
    select = Select(driver.find_element_by_id('draft_type'))
    time.sleep(1)
    select.select_by_visible_text('Average Auction Values')
    time.sleep(1)
    submit_button.click()
    time.sleep(1)

two_weeks = date.today() - timedelta(days=14)

datefield = driver.find_element_by_id('from_date')
time.sleep(1)
datefield.click()
time.sleep(1)
datefield.clear()
time.sleep(1)

datefield.send_keys(f"{str(two_weeks.year).zfill(4)}-{str(two_weeks.month).zfill(2)}-{str(two_weeks.day).zfill(2)}")
time.sleep(1)
submit_button.click()
time.sleep(1)

html = driver.page_source
soup = BeautifulSoup(html, 'html.parser')

nfc_adp = soup.find("table", { "id" : "adp" })

nfc_adp_df = pd.read_html(str(nfc_adp))[0]

nfc_adp_df['Player'] = nfc_adp_df['Player'].apply(lambda x: re.sub('\d+ Betting Markets ', '', x).strip())
nfc_adp_df['Player'] = nfc_adp_df['Player'].apply(lambda x: re.sub(player_suffix_regex, '', x).strip())

if draft_type == 'auction':
    nfc_adp_df = nfc_adp_df[['Rk', 'Player', 'Team', 'Position(s)', 'ADP / AAV']]
    nfc_adp_df.columns = ['nfc_adp', 'player_name', 'team', 'position', 'nfc_price']
    nfc_adp_df.loc[:,'nfc_price'] = nfc_adp_df.loc[:,'nfc_price'].apply(lambda x: int(re.sub('\$', '', x)))
elif draft_type == 'snake':
    nfc_adp_df = nfc_adp_df[['Rk', 'Player', 'Team', 'Position(s)']]
    nfc_adp_df.columns = ['nfc_adp', 'player_name', 'team', 'position']    

nfc_adp_df_posplayers = nfc_adp_df[nfc_adp_df['position'] != 'TDSP']
x = nfc_adp_df_posplayers['player_name'].str.split(' ', n=1, expand=True)
nfc_adp_df_posplayers['player_first'] = [x for x in x[0]]
nfc_adp_df_posplayers['player_first'] = nfc_adp_df_posplayers['player_first'].replace('Hollywood', 'Marquise')
nfc_adp_df_posplayers['player_first_init'] = [x[0] for x in nfc_adp_df_posplayers['player_first']]
nfc_adp_df_posplayers['player_last'] = [x for x in x[1]]

nfc_adp_df_dst = nfc_adp_df[nfc_adp_df['position'] == 'TDSP']
nfc_adp_df_dst.loc[:,'position'] = 'DST'
nfc_adp_df_dst = nfc_adp_df_dst[nfc_adp_df_dst['team'] != 'FA']
nfc_adp_df_dst.loc[:,'player_name'] = nfc_adp_df_dst['player_name'].apply(lambda x: re.sub('\(.+\) ','', x))
x = nfc_adp_df_dst.loc[:,'player_name'].str.split(' ')    
nfc_adp_df_dst.loc[:,'player_last'] = [y[len(y)-1] for y in x]
nfc_adp_df_dst.loc[:,'player_first'] = [' '.join(y[0:len(y)-1]) for y in x]
nfc_adp_df_dst.loc[:,'player_first_init'] = [x[0] for x in nfc_adp_df_dst.loc[:,'player_first']]
nfc_adp_df = pd.concat([nfc_adp_df_posplayers,nfc_adp_df_dst])
nfc_adp_df.loc[:,'team'].replace({'JAX':'JAC','ARZ':'ARI','LA':'LAR'}, inplace = True)

nfc_adp_df_out = pd.DataFrame()
for pos in nfc_adp_df['position'].unique():
    nfc_adp_df_pos = nfc_adp_df[nfc_adp_df['position'] == pos]
    nfc_adp_df_pos.sort_values('nfc_adp', ascending = True, inplace = True)
    nfc_adp_df_pos = nfc_adp_df_pos.reset_index(drop=True).reset_index()
    nfc_adp_df_pos.loc[:,'nfc_pos_adp'] = nfc_adp_df_pos['index'] + 1
    nfc_adp_df_pos.drop(columns = ['index'], inplace = True)
    nfc_adp_df_out = pd.concat([nfc_adp_df_out, nfc_adp_df_pos])
    
nfc_adp_df = nfc_adp_df_out.copy()

driver.close()

team_mapping = fpros_rankings[fpros_rankings['position']=='DST'][['team', 'player_name']].drop_duplicates().reset_index(drop=True)

team_mapping['player_first'] = ''

team_mapping['player_last'] = ''

team_mapping['player_first_init'] = ''

cbs_teams = cbs_rankings[cbs_rankings['position']=='DST'][['player_name']].drop_duplicates().reset_index(drop=True) 

for idx in range(len(cbs_teams['player_name'])):

    team_name = cbs_teams['player_name'][idx]

    x = team_mapping[team_mapping['player_name'].str.contains(team_name)]

    team_mapping.at[x.index[0], 'player_last'] = team_name

    city = re.sub(team_name, "", x.at[x.index[0],'player_name']).strip()

    team_mapping.at[x.index[0], 'player_first'] = city

    team_mapping.at[x.index[0], 'player_first_init'] = city[0]

fpros_rankings_def = fpros_rankings.drop(columns=['player_last','player_first_init', 'team', 'player_first']).merge(team_mapping, on='player_name', how='right')

fpros_rankings = pd.concat([fpros_rankings[fpros_rankings['position']!='DST'], fpros_rankings_def])

fpros_rankings[fpros_rankings.select_dtypes(['object']).columns] = fpros_rankings[fpros_rankings.select_dtypes(['object']).columns].apply(lambda x: x.str.strip())

cbs_rankings_def = cbs_rankings.drop(columns=['player_name','player_first_init', 'team']).merge(team_mapping, on='player_last', how='right')

cbs_rankings = pd.concat([cbs_rankings[cbs_rankings['position']!='DST'],cbs_rankings_def])

cbs_rankings = cbs_rankings[cbs_rankings['mode']==ppr_scoring]

ffb_rankings_def = pd.merge(ffb_rankings.drop(columns=['player_last','player_first_init', 'player_first', 'team']), team_mapping, on='player_name', how='right')

ffb_rankings = pd.concat([ffb_rankings[ffb_rankings['position']!='DST'],ffb_rankings_def])

cbs_rankings_pivot = cbs_rankings.pivot(index=['position', 'mode', 'player_name', 'player_first','player_first_init', 'player_last', 'team'], columns='analyst', values='pos_rank').reset_index()

cbs_price_pivot = cbs_rankings.pivot(index=['position', 'mode','player_name', 'player_first','player_first_init', 'player_last', 'team'], columns='analyst', values='price').reset_index()
cbs_price_pivot.loc[:,['Dave Richard', 'Heath Cummings', 'Jamey Eisenberg']] = cbs_price_pivot.loc[:,['Dave Richard', 'Heath Cummings', 'Jamey Eisenberg']].fillna(0)
cbs_price_pivot.loc[:,'cbs_price'] = 2 * cbs_price_pivot.loc[:,['Dave Richard', 'Heath Cummings', 'Jamey Eisenberg']].mean(axis=1)
cbs_price_pivot.loc[:,'cbs_price'] = cbs_price_pivot.loc[:,'cbs_price'].round()

if draft_type == 'auction':
    cbs_rankings_pivot = pd.merge(cbs_rankings_pivot, cbs_price_pivot[['position', 'mode', 'player_name', 'player_first_init', 'player_last',
       'team', 'cbs_price']], on = ['position', 'mode', 'player_name', 'player_first_init', 'player_last',
       'team'], how='inner')

if import_draft:

    driver = webdriver.Firefox(executable_path = path)
    time.sleep(2)
    driver.get(import_draft_url)
    time.sleep(5)
    html=driver.page_source
    soup=BeautifulSoup(html,'html.parser')
    team_cols = soup.find_all(class_='team-column')
    driver.close()

    drafted = pd.DataFrame()

    for team in team_cols:
        
        drafted_player_cards = team.find_all(class_='drafted')
        
        manager_name = team.find(class_='header-text').text
        
        for card in drafted_player_cards:
    
            position_team = card.find(class_='position').text.split(' - ')
    
            position = position_team[0]
            position = 'DST' if position == 'DEF' else position
    
            nfl_team = position_team[1]
    
            if nfl_team == 'JAX':
    
                nfl_team = 'JAC'
    
            if re.search("\$",card.find(class_='pick').text):
    
                draft_type = 'auction'
    
                price = pd.to_numeric(re.sub("\$","",card.find(class_='pick').text))
    
            else:
    
                draft_type = 'snake'
    
                pick_text = re.sub("\$","",card.find(class_='pick').text)
    
                rd = pd.to_numeric(re.sub('\.','',re.search('\d+\.', pick_text)[0]))
    
                pick = pd.to_numeric(re.sub('\.','',re.search('\.\d+', pick_text)[0]))
    
                ovr_pick = (rd-1)*12 + pick
                
                traded = card.find(class_='pick-traded')
                
                if traded:
                    manager_name = traded.text.strip()
                else:
                    manager_name = team.find(class_='header-text').text
    
            player_name = card.find(class_='player-name').text
    
            player_last = re.sub('\w\.','', player_name).strip()
    
            player_first_init = re.sub("\.", "", re.search('\w\.',player_name).group())
    
            keeper = card.find(class_='keeper-icon')
    
            if keeper:
    
                status = 'k'
    
            else:
    
                status = 'p'
    
            if draft_type == 'auction':
    
                drafted_player = pd.DataFrame({'position': [position],'team': [nfl_team], 'player_first_init':[player_first_init], 'player_last': [player_last], 'drafted_price': [price], 'status': [status], 'manager_name': [manager_name]})
    
            elif draft_type == 'snake':
    
                drafted_player = pd.DataFrame({'position': [position],'team': [nfl_team], 'player_first_init':[player_first_init], 'player_last': [player_last], 'drafted_round': [rd], 'drafted_pick':[pick], 'drafted_ovr':ovr_pick, 'status': [status], 'manager_name': [manager_name]})
    
            drafted = pd.concat([drafted,drafted_player])

analyst_df = cbs_rankings_pivot.merge(ffb_rankings, on=['player_first_init', 'player_first', 'player_last', 'team', 'position', 'mode'], how='outer')

analyst_df['player_name'] = analyst_df['player_name_y'].fillna(analyst_df['player_name_x'])
#analyst_df['team'] = analyst_df['team_y'].fillna(analyst_df['team_x'])

analyst_df = analyst_df.drop(columns=['Consensus','player_name_x', 'ffb_pos_rank', 'player_name_y'])

analyst_cols = ['Andy', 'Mike', 'Jason', 'Heath Cummings', 'Jamey Eisenberg', 'Dave Richard']

analyst_df = analyst_df.merge(fpros_rankings, on=['team', 'player_first_init', 'player_last', 'position', 'mode'], how='outer')
analyst_df['player_name'] = analyst_df['player_name_x'].fillna(analyst_df['player_name_y'])
analyst_df['player_first'] = analyst_df['player_first_x'].fillna(analyst_df['player_first_y'])
analyst_df.drop(columns = ['player_name_x', 'player_first_x', 'player_name_y', 'player_first_y'], inplace = True)

analyst_df = analyst_df.merge(nfc_adp_df, on = ['team', 'player_first_init', 'player_last', 'position'], how='outer')
analyst_df['player_name'] = analyst_df['player_name_x'].fillna(analyst_df['player_name_y'])
analyst_df['player_first'] = analyst_df['player_first_x'].fillna(analyst_df['player_first_y'])
analyst_df['bye'] = analyst_df['bye_x'].fillna(analyst_df['bye_y'])
analyst_df.drop(columns = ['player_name_x', 'player_first_x', 'player_name_y', 'player_first_y', 'bye_x', 'bye_y'], inplace = True)

bye_mapping = fpros_rankings[['bye', 'team']].drop_duplicates().dropna().reset_index(drop=True).rename(columns={'bye_x':'bye'})
analyst_df = analyst_df.merge(bye_mapping, on='team')
analyst_df['bye'] = analyst_df['bye_y'].fillna(analyst_df['bye_x'])
analyst_df.drop(columns = ['bye_x', 'bye_y'], inplace = True)

if import_draft:
    analyst_df = analyst_df.merge(drafted, on=['position', 'team', 'player_first_init', 'player_last'], how='outer')

else:

    if draft_type == 'auction':
        analyst_df['status'] = ''
        analyst_df['drafted_price'] = 0
        analyst_df['manager_name'] = ''
    else:
        analyst_df['status'] = ''
        analyst_df['drafted_round'] = 0
        analyst_df['drafted_pick'] = 0
        analyst_df['drafted_ovr'] = 0
        analyst_df['manager_name'] = ''

for analyst in analyst_cols:

    for pos in positions:
        max_rk = analyst_df[analyst_df['position']==pos][analyst].max()
        analyst_df.loc[analyst_df['position']==pos, analyst] = analyst_df[analyst_df['position']==pos][analyst].fillna(max_rk+1)

analyst_cols = analyst_cols + ['pos_ecr', 'nfc_pos_adp'] 

analyst_df['analyst_average'] = analyst_df[analyst_cols].mean(axis=1)

ovr_analyst_df = analyst_df.merge(fpros_overall_rankings, on=['position', 'team', 'player_first_init', 'player_last', 'bye', 'mode'], how='left', suffixes=('','_drop'))

if draft_type == 'auction':

    ovr_analyst_df_out = ovr_analyst_df[['ovr_tier','pos_tier', 'position', 'team', 'bye', 'pos_adp', 'ovr_adp', 'player_name'] + analyst_cols + ['nfc_adp', 'ovr_ecr','analyst_average', 'cbs_price', 'nfc_price','drafted_price', 'status', 'manager_name']]

    analyst_df_out = analyst_df[['pos_tier', 'position', 'team', 'bye', 'pos_adp', 'player_name'] + analyst_cols + ['analyst_average', 'cbs_price', 'nfc_price','drafted_price', 'status', 'manager_name']]

else:

    ovr_analyst_df_out = ovr_analyst_df[['ovr_tier','pos_tier', 'position', 'team', 'bye', 'pos_adp', 'ovr_adp', 'player_name'] + analyst_cols + ['nfc_adp','ovr_ecr','analyst_average', 'drafted_round', 'drafted_pick', 'drafted_ovr', 'status', 'manager_name']]

    analyst_df_out = analyst_df[['pos_tier', 'position', 'team', 'bye', 'pos_adp', 'player_name'] + analyst_cols + ['analyst_average', 'drafted_round', 'drafted_pick', 'drafted_ovr', 'status', 'manager_name']]
 

driver = webdriver.Firefox(executable_path = path)

time.sleep(2)

driver.get(rookie_adp_url)

time.sleep(5)

driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")

time.sleep(3)


html=driver.page_source

soup=BeautifulSoup(html,'html.parser')

rookies = soup.find_all(id='ranking-table')

rookies_df = pd.read_html(str(rookies))[0]

rookies_df = rookies_df

driver.close()

rookies_df['player_name'] = [re.sub('\([A-Z]+\)', '', x).strip() for x in rookies_df['Player Name']]

rookies_df['player_name'] = rookies_df['player_name'].replace(
    player_suffix_regex, '', regex=True)

rookies_df['player_first_init'] = [player_name[0:1] for player_name in rookies_df['player_name']]

rookies_df['player_last'] = [player_name.split()[1] for player_name in rookies_df['player_name']]

rookies_df['team'] = rookies_df['Player Name'].str.extract(r'\((.*?)\)')

rookies_df['position'] = [re.sub('\d+','',x) for x in rookies_df['POS']]

rookies_df['fpros_dynasty_rookie_rank'] = rookies_df['RK']

rookies_df.drop(columns=['RK', 'Player Name', 'POS', 'AVG.'], inplace = True)
ovr_analyst_df = ovr_analyst_df.loc[:, ~ovr_analyst_df.columns.str.endswith('_drop')]
rookies_df_merged = pd.merge(rookies_df, ovr_analyst_df, on=['team', 'position', 'player_first_init', 'player_last'], how='left', suffixes=('','_drop'))

letters = {letter: str(index) for letter, index in enumerate(ascii_uppercase, start=1)}

if draft_type == 'auction':
    rookies_df_merged =  rookies_df_merged[['fpros_dynasty_rookie_rank', 'position', 'team', 'bye', 'pos_adp', 'player_name'] + analyst_cols + ['analyst_average', 'drafted_price', 'status', 'manager_name']]
    rookies_df_merged.sort_values('fpros_dynasty_rookie_rank', ascending = True, inplace = True)
else:
    rookies_df_merged.dropna(subset=['ovr_adp'], inplace=True)
    rookies_df_merged['adp_round'] = (1 + ((rookies_df_merged['ovr_adp']-1) / 12)).round().astype(int)
    rookies_df_merged.sort_values('ovr_adp', ascending = True, inplace = True)
    rookies_df_merged['adp_round'] = [x if x < 17 else 16 for x in rookies_df_merged['adp_round']]
    rookies_df_merged =  rookies_df_merged[['fpros_dynasty_rookie_rank', 'position', 'team', 'bye', 'pos_adp','adp_round', 'player_name'] + analyst_cols + ['analyst_average', 'drafted_round', 'drafted_pick', 'drafted_ovr', 'status', 'manager_name']]
    rookies_df_merged = rookies_df_merged.head(50)

writer = pd.ExcelWriter(output_path + str(current_season) + '_' + (f'{import_draft_params[0]}_{import_draft_params[1]}_' if import_draft else '') + 'rankings_formatted.xlsx', engine = 'xlsxwriter')

workbook = writer.book

format1 = workbook.add_format({'bg_color':   '#FFC7CE',
                               'font_color': '#9C0006',
                                   'italic': True,
                                   'font_strikeout': True})

for pos in positions:

    pos_df_out = analyst_df_out[analyst_df_out['position'] == pos].sort_values(by='analyst_average').reset_index(drop=True)

    pos_df_out['analyst_average_diff'] = 0.0

    pos_df_out['calc_tier'] = 1

    for i in range(len(pos_df_out)):

        if i > 0:

            diff = pos_df_out['analyst_average'][i] - pos_df_out['analyst_average'][i-1]

            pos_df_out.loc[i,'analyst_average_diff'] = diff

            if diff > 1.25:
                pos_df_out.loc[i,'calc_tier'] = pos_df_out['calc_tier'][i-1] + 1
            else:
                pos_df_out.loc[i,'calc_tier'] = pos_df_out['calc_tier'][i-1]

    if draft_type == 'auction':

        pos_df_out =  pos_df_out[['calc_tier', 'pos_tier', 'position', 'team', 'bye', 'pos_adp', 'player_name'] + analyst_cols + ['analyst_average', 'cbs_price', 'nfc_price', 'drafted_price', 'status', 'manager_name']]
        drafted_price_col = letters[list(pos_df_out.columns).index('drafted_price')+2]
        pos_df_out.loc[pos_df_out['status'] != 'k', 'status'] = [f"""=IF({drafted_price_col}{x}>0,"p","")""" for x in pos_df_out.loc[pos_df_out['status'] != 'k', 'status'].index+2]
    else:

        pos_df_out =  pos_df_out[['calc_tier', 'pos_tier', 'position', 'team', 'bye', 'pos_adp', 'player_name'] + analyst_cols + ['analyst_average', 'drafted_round', 'drafted_pick', 'drafted_ovr', 'status', 'manager_name']]
        drafted_ovr_col = letters[list(pos_df_out.columns).index('drafted_ovr')+2]
        pos_df_out.loc[pos_df_out['status'] != 'k', 'status'] = [f"""=IF({drafted_ovr_col}{x}>0,"p","")""" for x in pos_df_out.loc[pos_df_out['status'] != 'k', 'status'].index+2]
        
    pos_df_out.to_excel(writer, sheet_name = pos, index = True)

    worksheet = writer.sheets[pos]

    #worksheet.conditional_format('H2:P1000', {'type': '2_color_scale', 'min_color': '#64A556', 'max_color': '#FFFFFF'})

    #worksheet.conditional_format('C2:C1000', {'type': '2_color_scale', 'min_color': '#9003fc', 'max_color': '#FFFFFF'})

    worksheet.conditional_format('B2:B1000', {'type': '2_color_scale', 'min_color': '#808080', 'max_color': '#FFFFFF'})

    #worksheet.conditional_format('G2:G1000', {'type': '2_color_scale', 'min_color': '#5D6CF0', 'max_color': '#FFFFFF'})

    #worksheet.conditional_format('Q2:Q1000', {'type': '2_color_scale', 'min_value': 1, 'max_value': 80, 'min_color': '#FFFFFF', 'max_color': '#5D6CF0'})

    worksheet.conditional_format('A2:A1000', {'type': 'formula', 'criteria': '=$U2<>""', 'format':format1})

    worksheet.conditional_format('D2:V1000', {'type': 'formula', 'criteria': '=$U2<>""', 'format':format1})

    worksheet.autofilter('A1:V1000')

    worksheet.set_column(7,7,19)

    worksheet.freeze_panes(1, 1)

 
if draft_type == 'auction':
    ovr_analyst_df_out.loc[:,'drafted_ovr'] = ovr_analyst_df_out['drafted_price'].rank(ascending=False)
    drafted_price_ovr_col = letters[list(ovr_analyst_df_out.columns).index('drafted_price')+2]
else:
    drafted_price_ovr_col = letters[list(ovr_analyst_df_out.columns).index('drafted_pick')+2]

ovr_analyst_df_out.loc[:,'diff'] = ovr_analyst_df_out['ovr_ecr']-ovr_analyst_df_out['drafted_ovr']

player_name_pos_col = letters[list(pos_df_out.columns).index('player_name')+2]
player_name_ovr_col = letters[list(ovr_analyst_df_out.columns).index('player_name')+2]
position_ovr_col = letters[list(ovr_analyst_df_out.columns).index('position')+2]
status_ovr_col = letters[list(ovr_analyst_df_out.columns).index('status')+2]

ovr_analyst_df_out = ovr_analyst_df_out.sort_values(by='ovr_ecr').reset_index(drop=True)

ovr_analyst_df_out['drafted_price'] = [f"""=IF(INDEX(INDIRECT("'"&${position_ovr_col}{x}&"'!"&"${player_name_pos_col}$2:$Z$100"),MATCH(${player_name_ovr_col}{x},INDIRECT("'"&${position_ovr_col}{x}&"'!"&"${player_name_pos_col}$2:${player_name_pos_col}$100"),0),MATCH({drafted_price_ovr_col}$1,INDIRECT("'"&${position_ovr_col}{x}&"'!"&"${player_name_pos_col}$1:$AA$1"), 0))<>"",INDEX(INDIRECT("'"&${position_ovr_col}{x}&"'!"&"${player_name_pos_col}$2:$Z$100"),MATCH(${player_name_ovr_col}{x},INDIRECT("'"&${position_ovr_col}{x}&"'!"&"${player_name_pos_col}$2:${player_name_pos_col}$100"),0),MATCH({drafted_price_ovr_col}$1,INDIRECT("'"&${position_ovr_col}{x}&"'!"&"${player_name_pos_col}$1:$AA$1"), 0)),"")""" for x in ovr_analyst_df_out.index+2]
ovr_analyst_df_out['status'] = [f"""=IF(INDEX(INDIRECT("'"&${position_ovr_col}{x}&"'!"&"${player_name_pos_col}$2:$Z$100"),MATCH(${player_name_ovr_col}{x},INDIRECT("'"&${position_ovr_col}{x}&"'!"&"${player_name_pos_col}$2:${player_name_pos_col}$100"),0),MATCH({status_ovr_col}$1,INDIRECT("'"&${position_ovr_col}{x}&"'!"&"${player_name_pos_col}$1:$AA$1"), 0))<>"",INDEX(INDIRECT("'"&${position_ovr_col}{x}&"'!"&"${player_name_pos_col}$2:$Z$100"),MATCH(${player_name_ovr_col}{x},INDIRECT("'"&${position_ovr_col}{x}&"'!"&"${player_name_pos_col}$2:${player_name_pos_col}$100"),0),MATCH({status_ovr_col}$1,INDIRECT("'"&${position_ovr_col}{x}&"'!"&"${player_name_pos_col}$1:$AA$1"), 0)),"")""" for x in ovr_analyst_df_out.index+2]

ovr_analyst_df_out.to_excel(writer, sheet_name = 'Overall', index = True)

rookies_df_merged.to_excel(writer, sheet_name = 'Rookies', index = True)

worksheet = writer.sheets['Overall']

worksheet.conditional_format('B2:B1000', {'type': '2_color_scale', 'min_color': '#808080', 'max_color': '#FFFFFF'})
worksheet.conditional_format('A2:A1000', {'type': 'formula', 'criteria': '=$X2<>""', 'format':format1})
worksheet.conditional_format('C2:Y1000', {'type': 'formula', 'criteria': '=$X2<>""', 'format':format1})

worksheet.autofilter('A1:Y1000')

worksheet.set_column(8,8,19)

worksheet.freeze_panes(1, 1)

writer.close()
