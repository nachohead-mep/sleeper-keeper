# -*- coding: utf-8 -*-
"""
Created on Sat Mar 30 14:43:03 2024

@author: Matt
"""

import requests
import json
import pandas as pd
import xlsxwriter
import numbers
import datetime

current_year = datetime.datetime.now().year
league_id = "1123784296227069952"

output_path = 'C:/Users/Matt/Documents/DS Practice/NFLFFL/Output/Keeper Spreadsheet/'

previous_keeper_sheet = pd.read_csv(f'{output_path}delta_keepers_{current_year-1}.csv')
previous_keeper_sheet['times_kept'].fillna(0, inplace = True)

rookie_draft = pd.read_excel(f'{output_path}Delta League Keepers {current_year-1}.xlsx', sheet_name = f'Rookie Draft {current_year-1}')
rookie_draft_picks = rookie_draft[['Pick', 'Team', 'Player']]
rookie_draft_cost = rookie_draft[['player_name', 'adp_round']]

rookie_draft_merged = pd.merge(rookie_draft_picks, rookie_draft_cost, how='inner', left_on='Player', right_on='player_name').drop(columns=['player_name'])

keepers = pd.read_excel(f'{output_path}Delta League Keepers {current_year-1}.xlsx', sheet_name = 'Keeper Selections')
keepers = pd.concat([keepers[['Team', "Keeper 1"]].set_axis(['team', 'player_name'], axis=1), keepers[['Team', "Keeper 2"]].set_axis(['team', 'player_name'], axis=1), keepers[['Team', "Keeper 3"]].set_axis(['team', 'player_name'], axis=1)])

# Construct the complete URL
drafts_url = f"https://api.sleeper.app/v1/league/{league_id}/drafts"

headers = {
    "Content-Type": "application/json"
}
# Make a GET request to retrieve league information
response = requests.get(drafts_url, headers = headers)

# Parse the JSON string into a Python dictionary
drafts = json.loads(response.text)
drafts_df = pd.DataFrame(drafts)
draft_id = drafts[0]['draft_id']

picks_url = f"https://api.sleeper.app/v1/draft/{draft_id}/picks"
# Make a GET request to retrieve league information
response = requests.get(picks_url, headers = headers)
picks = json.loads(response.text)
picks_df = pd.DataFrame(picks)

roster_url = f"https://api.sleeper.app/v1/league/{league_id}/rosters"  
# Make a GET request to retrieve league information
response = requests.get(roster_url, headers = headers)
rosters = json.loads(response.text)
rosters_df = pd.DataFrame(rosters)

users_url = f"https://api.sleeper.app/v1/league/{league_id}/users"
# Make a GET request to retrieve league information
response = requests.get(users_url, headers = headers)
users = json.loads(response.text)
  
players_url = "https://api.sleeper.app/v1/players/nfl"
# Make a GET request to retrieve league information
response = requests.get(players_url, headers = headers)
players = json.loads(response.text)

transactions = pd.DataFrame()
transactions_url = f"https://api.sleeper.app/v1/league/{league_id}/transactions/"
waiver_adds = []
trade_adds = []
for rd in range(1,19):
    response = requests.get(transactions_url + str(rd), headers = headers)
    transaction_json = json.loads(response.text)
    for trans in transaction_json:
        trans_type = trans['type']
        trans_status = trans['status']
        trans_week = trans['leg']
        if trans_status == 'failed':
            continue
        if trans_type == "waiver":
            assert len(trans['adds']) == 1, 'multiple adds, this looks weird'
            added_player_id = next(iter(trans['adds']))
            added_player_roster_id = trans['adds'][added_player_id]                
            waiver_bid = trans['settings']['waiver_bid']
            waiver_claim = {'trans_type': trans_type,
                            'trans_status': trans_status,
                            'trans_week': trans_week,                            
                            'added_player_id':added_player_id,
                            'added_player_roster_id':added_player_roster_id,
                            'waiver_bid': waiver_bid,
                            'owner_id': rosters[added_player_roster_id-1]['owner_id']
                            }
            waiver_adds.append(waiver_claim)
        elif (trans_type == "trade") & (trans['adds'] is not None):
            for trade_add_obj in trans['adds']:
                added_player_id = trade_add_obj
                added_player_roster_id = trans['adds'][added_player_id] 
                trade_add = {'trans_type': trans_type,
                             'trans_status': trans_status,
                             'trans_week': trans_week,                            
                             'added_player_id':added_player_id,
                             'added_player_roster_id':added_player_roster_id,
                             'owner_id': rosters[added_player_roster_id-1]['owner_id']
                                }
                trade_adds.append(trade_add)
waiver_adds = pd.DataFrame(waiver_adds)
trade_adds = pd.DataFrame(trade_adds)
adds = pd.concat([waiver_adds, trade_adds])
adds.sort_values(by='trans_week', ascending = False, inplace = True)
    
keeper_df = pd.DataFrame()

def get_round_from_faab(faab):
    faab = int(faab)
    if faab < 6:
        round_ = 12
    elif faab < 11:
        round_ = 11
    elif faab < 16:
        round_ = 10
    elif faab < 21:
        round_ = 9
    elif faab < 26:
        round_ = 8
    elif faab < 31:
        round_ = 7
    else:
        round_ = 6
    return round_

def ask_user_about_keeper(player_name):
    user_resp = input(f"We found that {player_name} may have been kept. Was {player_name} kept? (y/n): ")
    
    # Print the input (or do something else with it)
    if user_resp.lower() == 'y' or user_resp.lower() == 'n':
        return user_resp
    else:
        ask_user_about_keeper(player_name)

for team in users:
    team_name = team['display_name']
    print(team_name)
    roster = rosters_df[rosters_df['owner_id'] == team['user_id']]
    if len(roster) == 0:
        continue
    player_list = roster['players'].iloc[0]
    for player_id in player_list:
        player_info = players[player_id]
        player_name = player_info['first_name'] + " " + player_info['last_name']
        print(player_name)
        player_pos = player_info['position']
        round_ = False
        pick_ = False
        keeper_round = False
        waivered = -1
        keeper_eligible = True
        last_claim_date = -1
        times_kept = 0
        
                    
        pick = picks_df[picks_df['player_id'] == player_id]
        if len(pick)>0:
            print('player was picked')
            round_ = pick.iloc[0]['round']
            pick_ = pick.iloc[0]['pick_no']
            if round_ == 1:
                keeper_eligible = False
            elif round_ < 6 or (not keeper_round): 
                keeper_round = round_ - 1
            elif round_ > 12:
                keeper_round = 12
            else:
                keeper_round = round_-1
            previous_keeper_sheet_slice = previous_keeper_sheet[previous_keeper_sheet['player_id'] == player_info['player_id']]
            if pick.iloc[0]['is_keeper'] == True or player_name in list(keepers['player_name']):
                print('player was kept')
                player_name_formatted = player_info['first_name'][0] + " " + player_info['last_name'] if player_info['position'] != 'DEF' else player_id
                times_kept = previous_keeper_sheet_slice.iloc[0]['times_kept'] + 1
                keeper_round = round_ - (1+1*times_kept)
        
        adds_slice = waiver_adds[waiver_adds['added_player_id'] == player_id]
        if len(adds_slice)>0:
            print('player was added')
            last_claim_date = next(iter(adds_slice.trans_week))
            keeper_eligible = last_claim_date < 13
            latest_add = adds_slice.iloc[0]
            waivered = adds_slice.iloc[0]['waiver_bid']
            if keeper_eligible:
                keeper_round = get_round_from_faab(waivered)
        
        rookie_slice = rookie_draft_merged[rookie_draft_merged['Player'] == player_name]
        if len(rookie_slice)>0:
            print('rookie draftee')
            round_ = rookie_slice.iloc[0]['adp_round']
            keeper_round = round_ - 1
            if keeper_round > 12:
                keeper_round = 12
            pick_ = 'R'
        
        if keeper_round < 1:
            keeper_eligible = False
        if isinstance(times_kept, numbers.Number) and times_kept > 2:
            keeper_eligible = False
        if ((round_ < 6 or (not keeper_round)) and len(pick)>0) and times_kept<1: 
            keeper_round = round_ - 1
        if not keeper_eligible:
            keeper_round = 0
        player_dict = {'team_name':[team_name], 'player_id': [player_id], 'player_name': [player_name], 'player_pos': [player_pos], 'drafted_round':[round_], 'drafted_pick':[pick_], 'last_claim_amount':[waivered], 'last_claim_week':[last_claim_date], 'keeper_eligible': [keeper_eligible], 'times_kept': [times_kept], 'keeper_round': [keeper_round]}
        player_df = pd.DataFrame(player_dict)
        keeper_df = pd.concat([keeper_df, player_df])

keeper_df.loc[keeper_df['drafted_round'] == 0,'drafted_round'] = 17

keeper_df = keeper_df.sort_values(['team_name','drafted_round'])

keeper_df.loc[keeper_df['last_claim_amount'] == -1,'last_claim_amount'] = "NO CLAIMS"
keeper_df.loc[keeper_df['last_claim_week'] == -1,'last_claim_week'] = "NO CLAIMS"
keeper_df.loc[keeper_df['drafted_round'] == 17,'drafted_round'] = "UNDRAFTED"
keeper_df.loc[keeper_df['drafted_pick'] == False,'drafted_pick'] = "UNDRAFTED"
keeper_df.loc[keeper_df['keeper_round'] == 0,'keeper_round'] = "NOT ELIGIBLE"

keeper_df.to_csv(output_path + f'delta_keepers_{current_year}.csv', index=False)

writer = pd.ExcelWriter(output_path + f'delta_keepers_{current_year}.xlsx', engine = 'xlsxwriter')

columns = ['Team', 'Player ID', 'Player Name', 'Position', 'Drafted Round', 'Drafted Pick', 'Last Claim Amount', 'Last Claim Week', 'Keeper Eligible','Times Kept','Keeper Round']
keeper_df.columns = columns
keeper_df.to_excel(writer, sheet_name = "keepers", index = False)

workbook = writer.book

worksheet = writer.sheets["keepers"]

format1 = workbook.add_format({'bg_color':   '#FFC7CE',
                               'font_color': '#9C0006',
                                   'italic': True,
                                   'font_strikeout': True})

bottom_border_format = workbook.add_format({
    'bottom': 5,
    'bottom_color': 'black'
})

left_border_format = workbook.add_format({
    'left': 5,
    'left_color': 'black'
})

border_format_blue = workbook.add_format({
    'bottom': 5,
    'bottom_color': 'black',
    'bg_color': '#cfe2f3'
})

# Add a format with light blue background color
format_light_blue = workbook.add_format({'bg_color': '#cfe2f3'})

players_by_team = keeper_df.pivot_table(index='Team', aggfunc='count')['Player Name']
    
highlight_row = 0
team_index = 0
while team_index < len(players_by_team):
    if team_index % 2 == 0:
        for i in range(highlight_row, highlight_row + players_by_team[team_index]):
            #print(i+1)
            worksheet.set_row(i+1, None, format_light_blue)
    highlight_row = highlight_row + players_by_team[team_index] 
    if team_index % 2 == 0:
        worksheet.set_row(highlight_row, None, border_format_blue)
    else:
        worksheet.set_row(highlight_row, None, bottom_border_format)
        
    team_index = team_index + 1
        

#worksheet.conditional_format('H2:P1000', {'type': '2_color_scale', 'min_color': '#64A556', 'max_color': '#FFFFFF'})

#worksheet.conditional_format('C2:C1000', {'type': '2_color_scale', 'min_color': '#9003fc', 'max_color': '#FFFFFF'})

#worksheet.conditional_format('B2:B1000', {'type': '2_color_scale', 'min_color': '#808080', 'max_color': '#FFFFFF'})

#worksheet.conditional_format('G2:G1000', {'type': '2_color_scale', 'min_color': '#5D6CF0', 'max_color': '#FFFFFF'})

#worksheet.conditional_format('Q2:Q1000', {'type': '2_color_scale', 'min_value': 1, 'max_value': 80, 'min_color': '#FFFFFF', 'max_color': '#5D6CF0'})

#worksheet.conditional_format('A2:A1000', {'type': 'formula', 'criteria': '=$U2<>""', 'format':format1})

worksheet.conditional_format('A2:K1000', {'type': 'formula', 'criteria': '=$I2<>TRUE', 'format':format1})
worksheet.set_column('B:B', None, None, {'hidden': True})
worksheet.set_column('L:L', None, left_border_format)

worksheet.autofilter('A1:K1000')

worksheet.set_column(7,7,19)

worksheet.freeze_panes(1, 1)

writer.close()
