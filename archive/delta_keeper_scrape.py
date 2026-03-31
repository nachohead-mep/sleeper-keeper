# -*- coding: utf-8 -*-
"""
Created on Mon Jan  3 09:01:41 2022

@author: Matt
"""

import pandas as pd
from bs4 import BeautifulSoup
import requests
from datetime import date, datetime
import re

from selenium import webdriver
from selenium.webdriver.common.keys import Keys

import time
import os
import numpy as np

path = r'C:\\Users\\Matt\\Downloads\\geckodriver-v0.34.0-win64\\geckodriver.exe'

output_path = 'C:/Users/Matt/Documents/DS Practice/NFLFFL/Data/'

league_url = 'https://sleeper.com/leagues/916474937517502464/league'

keeper_deadline = date(2022, 11, 28)

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


driver = webdriver.Firefox(executable_path=path)
time.sleep(2)
driver.get(league_url)

user_box = driver.find_element_by_tag_name("input")
user_box.send_keys("7036251615")

continue_button = driver.find_element_by_class_name("login-button")
continue_button.click()

time.sleep(1)

passwords_box = driver.find_element_by_xpath("/html/body/div[1]/div/div[2]/div/div[2]/div[2]/div[2]/div[1]/input")
passwords_box.send_keys(os.environ["SLEEPER_PASSWORD"])

continue_button = driver.find_element_by_class_name("login-button")
continue_button.click()

time.sleep(2)

driver.get(league_url)

time.sleep(1.5)

driver.set_window_size(1920, 1080)
    
#scrollbar = driver.find_element_by_xpath("/html/body/div[1]/div/div[1]/div[1]/div[2]/div[2]/div[1]/div/div[1]/div[2]/div[2]")
#driver.execute_script("arguments[0].scrollTo(0, document.body.scrollHeight)", scrollbar)

x = driver.find_elements_by_class_name("league-standing-item")

driver.execute_script("arguments[0].scrollIntoView();", x[0])

time.sleep(1.5)

name_list = driver.find_elements_by_class_name("league-standing-item")

keeper_df = pd.DataFrame()

for name in name_list:
    name_link = name.find_element_by_class_name('name')
    team_name = name_link.text
    name_link.click()
    print(team_name)
    player_list = driver.find_elements_by_class_name("player-name-row")
    player_list_final = []
    while len(player_list) != len(player_list_final):
        driver.execute_script("arguments[0].scrollIntoView();", player_list[len(player_list_final)])
        time.sleep(1)
        player_list = driver.find_elements_by_class_name("player-name-row")
        for player in player_list:
            player_name = player.find_element_by_class_name("player-name").text
            player_pos = player.find_element_by_class_name("pos").text
            round_ = False
            pick_ = False
            keeper_round = False
            waivered = False
            if player_name != "":
                player_list_final.append(player)
                print(player_name)
                player.click()
                time.sleep(10)
                transaction_title = driver.find_element_by_class_name("transaction-history-container")
                driver.execute_script("arguments[0].scrollIntoView();", transaction_title)
                time.sleep(.5)
                expand_button = driver.find_elements_by_class_name("view-all-text")
                if len(expand_button)>0:
                    expand_button[0].click()
                    time.sleep(1.5)
                html = driver.page_source
                soup = BeautifulSoup(html, 'html.parser')
                transaction_items = soup.find_all(class_='player-transaction-history-item')
                #transaction_items = driver.find_elements_by_class_name("player-transaction-history-item")
                transaction_list = []
                for transaction_item in transaction_items:
                    transaction_type = transaction_item.find(class_="action-column").text.upper()
                    transaction_text = transaction_item.find(class_="body-column").text
                    transaction_date = transaction_item.find(class_="date-time").text
                    transaction_date = datetime.strptime(transaction_date, '%b %d %Y').date()
                    transaction_list.append([transaction_type,transaction_text,transaction_date])
                transaction_df_historic = pd.DataFrame(transaction_list)
                transaction_df_historic.columns = ['transaction_type', 'transaction_text', 'transaction_date']
                transaction_df = transaction_df_historic[transaction_df_historic['transaction_date']>date(keeper_deadline.year, 3,1)]
                keeper_eligible = transaction_df.transaction_date[0] < keeper_deadline
                if len(transaction_df[transaction_df['transaction_type']=='ADDED'])>0:
                    print('player was added')
                    latest_add = transaction_df[transaction_df['transaction_type']=='ADDED']
                    text = latest_add['transaction_text'].values[0]
                    waivered = re.sub('\$|\(|\)','',re.findall('\(\$\d+\)', text)[0])
                    if keeper_eligible:
                        keeper_round = get_round_from_faab(waivered)
                times_kept = ""
                if len(transaction_df[transaction_df['transaction_type']=='KEEPER'])>0:
                    times_kept = 0
                    kpr_year = keeper_deadline.year
                    text = transaction_df[transaction_df['transaction_type']=='KEEPER']['transaction_text'].values[0]
                    drafted = re.findall('\d+\.\d+', text)[0]
                    round_, pick_ = drafted.split('.')
                    for row in range(len(transaction_df_historic[transaction_df_historic['transaction_type']=='KEEPER'])):
                        item = transaction_df_historic[transaction_df_historic['transaction_type']=='KEEPER'].reset_index(drop=True).loc[row,]
                        if item.transaction_date.year == kpr_year:
                            times_kept = times_kept+1
                            kpr_year = kpr_year + 1
                    print(f'player was kept {times_kept} time(s)')
                    if not keeper_round:
                        keeper_round = int(round_) - 1 - times_kept
                        
                if len(transaction_df[transaction_df['transaction_type']=='DRAFTED'])>0:
                    print('player was drafted')
                    text = transaction_df[transaction_df['transaction_type']=='DRAFTED']['transaction_text'].values[0]
                    drafted = re.findall('\d+\.\d+', text)[0]
                    round_, pick_ = drafted.split('.')
                    round_ = int(round_)
                    if round_ == 1:
                        keeper_eligible = False
                    elif round_ < 6 or (not keeper_round): 
                        if round_ > 12:
                            keeper_round = 12
                        else:
                            keeper_round = round_-1
                if keeper_round < 1:
                    keeper_eligible = False
                if str(times_kept).isnumeric() and times_kept > 2:
                    keeper_eligible = False
                if not keeper_eligible:
                    keeper_round = 0
                player_dict = {'team_name':[team_name], 'player_name': [player_name], 'player_pos': [player_pos], 'drafted_round':[round_], 'drafted_pick':[pick_], 'last_waiver':[waivered], 'keeper_eligible': [keeper_eligible], 'times_kept': [times_kept], 'keeper_round': [keeper_round]}
                player_df = pd.DataFrame(player_dict)
                keeper_df = keeper_df.append(player_df)
                webdriver.ActionChains(driver).send_keys(Keys.ESCAPE).perform()
    webdriver.ActionChains(driver).send_keys(Keys.ESCAPE).perform()
    
driver.close()

keeper_df.loc[keeper_df['drafted_round'] == 0,'drafted_round'] = 17

keeper_df = keeper_df.sort_values(['team_name','drafted_round'])

keeper_df.loc[keeper_df['last_waiver'] == False,'last_waiver'] = "NO CLAIMS"
keeper_df.loc[keeper_df['drafted_round'] == 17,'drafted_round'] = "UNDRAFTED"
keeper_df.loc[keeper_df['drafted_pick'] == False,'drafted_pick'] = "UNDRAFTED"

keeper_df.to_csv(output_path + f'delta_keepers_{date.today().year}.csv', line_terminator='\n', index=False)
