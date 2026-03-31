#!/usr/bin/env python3
"""
Delta League Keeper Value Calculator

Pulls roster, draft, and transaction data from the Sleeper API
to compute keeper eligibility and round cost for each player.

NOTE: This script does not verify that a player was continuously held
from the trade deadline through the end of the season (constitution
Article VI requires this for keeper eligibility). It only checks
whether the most recent waiver add was before the deadline week.
Players dropped after the deadline should be manually flagged.
"""

import os
import requests
import pandas as pd
import datetime

# ---------------------------------------------------------------------------
# League rules (Article VI) — update these if the constitution is amended
# ---------------------------------------------------------------------------
LEAGUE_ID = "1123784296227069952"
NFL_WEEKS = 18
DRAFT_ROUNDS = 16
MAX_KEEPER_ROUND = 12               # Rounds 13-16 picks cap to round 12
FIRST_ROUND_INELIGIBLE = True        # Round 1 cost → round 0 → ineligible
HIGH_PICK_THRESHOLD = 5              # Rounds 1-5 keeper value locked; waiver FAAB won't override
KEEPER_DEADLINE_WEEK = 13            # Waiver adds in week 13+ are not keeper-eligible
NUM_KEEPERS = 3                      # Keeper slots per team
MAX_CONSECUTIVE_KEEPS = 3            # A player can be kept at most 3 consecutive years

# FAAB bid → first-year keeper round (Article VI: Free Agent Keepers)
# Constitution brackets: $0, $1-5, $6-10, $11-15, $16-20, $21-25, $26-30, $31+
FAAB_ROUND_THRESHOLDS = [
    (1, 12),    # $0 → forfeit 12th round pick
    (6, 11),    # $1-5 → forfeit 11th round pick
    (11, 10),   # $6-10 → forfeit 10th round pick
    (16, 9),    # $11-15 → forfeit 9th round pick
    (21, 8),    # $16-20 → forfeit 8th round pick
    (26, 7),    # $21-25 → forfeit 7th round pick
    (31, 6),    # $26-30 → forfeit 6th round pick
]
FAAB_DEFAULT_ROUND = 5              # $31+ → forfeit 5th round pick

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
current_year = datetime.datetime.now().year
script_dir = os.path.dirname(os.path.abspath(__file__))
output_path = os.path.normpath(
    os.path.join(script_dir, '..', 'Output', 'Keeper Spreadsheet')
) + os.sep

SLEEPER_BASE = "https://api.sleeper.app/v1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def fetch_json(url):
    """Fetch JSON from a URL, raising on HTTP errors."""
    response = requests.get(url)
    response.raise_for_status()
    return response.json()


def get_round_from_faab(faab):
    """Map a FAAB bid amount to a first-year keeper round per Article VI."""
    faab = int(faab)
    for threshold, keeper_round in FAAB_ROUND_THRESHOLDS:
        if faab < threshold:
            return keeper_round
    return FAAB_DEFAULT_ROUND


# ---------------------------------------------------------------------------
# Load previous year's keeper data
# ---------------------------------------------------------------------------
previous_keeper_sheet = pd.read_csv(f'{output_path}delta_keepers_{current_year - 1}.csv')
previous_keeper_sheet['times_kept'] = previous_keeper_sheet['times_kept'].fillna(0)
previous_keeper_sheet['player_id'] = previous_keeper_sheet['player_id'].astype(str)
prev_keeper_by_id = {
    row['player_id']: row['times_kept']
    for _, row in previous_keeper_sheet.iterrows()
}

rookie_draft = pd.read_excel(
    f'{output_path}Delta League Keepers {current_year - 1}.xlsx',
    sheet_name=f'Rookie Draft {current_year - 1}'
)
rookie_draft_merged = pd.merge(
    rookie_draft[['Pick', 'Team', 'Player']],
    rookie_draft[['player_name', 'adp_round']],
    how='inner', left_on='Player', right_on='player_name'
).drop(columns=['player_name'])
# Index by player_id where available for robust matching, fall back to name
rookie_by_name = {
    row['Player']: row['adp_round']
    for _, row in rookie_draft_merged.iterrows()
}

keepers_xl = pd.read_excel(
    f'{output_path}Delta League Keepers {current_year - 1}.xlsx',
    sheet_name='Keeper Selections'
)
keeper_columns = [f"Keeper {i}" for i in range(1, NUM_KEEPERS + 1)]
kept_player_names = set()
for col in keeper_columns:
    if col in keepers_xl.columns:
        kept_player_names.update(keepers_xl[col].dropna())

# ---------------------------------------------------------------------------
# Fetch data from Sleeper API
# ---------------------------------------------------------------------------
print("Fetching league data from Sleeper API...")
drafts = fetch_json(f"{SLEEPER_BASE}/league/{LEAGUE_ID}/drafts")
draft_id = drafts[0]['draft_id']

picks = fetch_json(f"{SLEEPER_BASE}/draft/{draft_id}/picks")
picks_by_player = {str(p['player_id']): p for p in picks}

rosters = fetch_json(f"{SLEEPER_BASE}/league/{LEAGUE_ID}/rosters")
rosters_df = pd.DataFrame(rosters)
roster_id_to_owner = {r['roster_id']: r['owner_id'] for r in rosters}

users = fetch_json(f"{SLEEPER_BASE}/league/{LEAGUE_ID}/users")

players = fetch_json(f"{SLEEPER_BASE}/players/nfl")

# ---------------------------------------------------------------------------
# Gather all waiver and trade adds across the season
# ---------------------------------------------------------------------------
print("Fetching transactions...")
waiver_adds_by_player = {}  # player_id → most recent waiver add
trade_adds = []

for week in range(1, NFL_WEEKS + 1):
    transaction_json = fetch_json(
        f"{SLEEPER_BASE}/league/{LEAGUE_ID}/transactions/{week}"
    )
    for trans in transaction_json:
        if trans['status'] == 'failed':
            continue
        trans_type = trans['type']
        trans_week = trans['leg']

        if trans_type == "waiver":
            if not trans['adds'] or len(trans['adds']) != 1:
                print(f"  WARNING: Waiver in week {trans_week} has unexpected adds count, skipping")
                continue
            added_player_id = str(next(iter(trans['adds'])))
            added_player_roster_id = trans['adds'][next(iter(trans['adds']))]
            add_record = {
                'trans_week': trans_week,
                'waiver_bid': trans['settings']['waiver_bid'],
                'owner_id': roster_id_to_owner[added_player_roster_id],
            }
            # Keep the most recent (highest week) waiver add per player
            if added_player_id not in waiver_adds_by_player or trans_week > waiver_adds_by_player[added_player_id]['trans_week']:
                waiver_adds_by_player[added_player_id] = add_record

        elif trans_type == "trade" and trans['adds'] is not None:
            for pid, rid in trans['adds'].items():
                trade_adds.append({
                    'trans_type': trans_type,
                    'trans_week': trans_week,
                    'added_player_id': str(pid),
                    'added_player_roster_id': rid,
                    'owner_id': roster_id_to_owner[rid],
                })

# ---------------------------------------------------------------------------
# Process each team's roster
# ---------------------------------------------------------------------------
print("Computing keeper values...")
keeper_rows = []

for team in users:
    team_name = team['display_name']
    print(f"  {team_name}")
    roster = rosters_df[rosters_df['owner_id'] == team['user_id']]
    if len(roster) == 0:
        continue
    player_list = roster['players'].iloc[0]

    for player_id in player_list:
        player_id = str(player_id)
        player_info = players.get(player_id)
        if player_info is None:
            print(f"    WARNING: player_id {player_id} not found in Sleeper player database, skipping")
            continue
        player_name = f"{player_info['first_name']} {player_info['last_name']}"
        player_pos = player_info['position']

        round_ = None
        pick_ = None
        keeper_round = None
        waivered = -1
        keeper_eligible = True
        last_claim_date = -1
        times_kept = 0
        high_draft_pick = False

        # 1. Check if player was drafted in the main draft
        #    For keepers, Sleeper records them as "drafted" at their keeper round,
        #    so round_ already reflects last year's keeper cost.
        pick = picks_by_player.get(player_id)
        if pick is not None:
            round_ = pick['round']
            pick_ = pick['pick_no']
            high_draft_pick = round_ <= HIGH_PICK_THRESHOLD

            if FIRST_ROUND_INELIGIBLE and round_ == 1:
                keeper_eligible = False
            else:
                keeper_round = min(round_ - 1, MAX_KEEPER_ROUND)

            # Check if player was kept from previous year.
            # Escalation formula: round_ - (1 + times_kept) gives the correct
            # next-year cost because round_ from Sleeper already reflects the
            # previous year's keeper cost (see Article VI cost schedule).
            if pick['is_keeper'] or player_name in kept_player_names:
                prev_times_kept = prev_keeper_by_id.get(str(player_info['player_id']))
                if prev_times_kept is not None:
                    times_kept = int(prev_times_kept) + 1
                    keeper_round = round_ - (1 + times_kept)
                else:
                    print(f"    WARNING: {player_name} flagged as keeper but not found in previous year's sheet")

        # 2. Check if player was a rookie draftee
        #    ADP round acts as their "draft round" for keeper purposes (Article VII).
        #    TODO: match by player_id instead of name to avoid "Gabe/Gabriel" mismatches
        rookie_adp = rookie_by_name.get(player_name)
        if rookie_adp is not None:
            round_ = rookie_adp
            high_draft_pick = round_ <= HIGH_PICK_THRESHOLD
            keeper_round = min(round_ - 1, MAX_KEEPER_ROUND)
            pick_ = 'R'

        # 3. Check waiver adds — FAAB cost overrides keeper value unless the
        #    player was drafted in rounds 1-5, in which case value is locked
        #    on draft day (Article VI: Additional Stipulations).
        waiver_add = waiver_adds_by_player.get(player_id)
        if waiver_add is not None:
            last_claim_date = waiver_add['trans_week']
            keeper_eligible = last_claim_date < KEEPER_DEADLINE_WEEK
            waivered = waiver_add['waiver_bid']
            if keeper_eligible and not high_draft_pick:
                keeper_round = get_round_from_faab(waivered)

        # Final eligibility checks
        if keeper_round is None or keeper_round < 1:
            keeper_eligible = False
        if times_kept >= MAX_CONSECUTIVE_KEEPS:
            keeper_eligible = False
        if not keeper_eligible:
            keeper_round = 0

        keeper_rows.append({
            'team_name': team_name,
            'player_id': player_id,
            'player_name': player_name,
            'player_pos': player_pos,
            'drafted_round': round_ if round_ is not None else DRAFT_ROUNDS + 1,
            'drafted_pick': pick_ if pick_ is not None else 'UNDRAFTED',
            'last_claim_amount': waivered,
            'last_claim_week': last_claim_date,
            'keeper_eligible': keeper_eligible,
            'times_kept': times_kept,
            'keeper_round': keeper_round,
        })

keeper_df = pd.DataFrame(keeper_rows)
keeper_df = keeper_df.sort_values(['team_name', 'drafted_round'])

# Convert sentinel values to display strings after sorting
keeper_df.loc[keeper_df['last_claim_amount'] == -1, 'last_claim_amount'] = "NO CLAIMS"
keeper_df.loc[keeper_df['last_claim_week'] == -1, 'last_claim_week'] = "NO CLAIMS"
keeper_df.loc[keeper_df['drafted_round'] == DRAFT_ROUNDS + 1, 'drafted_round'] = "UNDRAFTED"
keeper_df.loc[keeper_df['keeper_round'] == 0, 'keeper_round'] = "NOT ELIGIBLE"

# ---------------------------------------------------------------------------
# Export to CSV
# ---------------------------------------------------------------------------
keeper_df.to_csv(f'{output_path}delta_keepers_{current_year}.csv', index=False)

# ---------------------------------------------------------------------------
# Export formatted Excel
# ---------------------------------------------------------------------------
columns = [
    'Team', 'Player ID', 'Player Name', 'Position', 'Drafted Round',
    'Drafted Pick', 'Last Claim Amount', 'Last Claim Week',
    'Keeper Eligible', 'Times Kept', 'Keeper Round',
]
keeper_df.columns = columns

writer = pd.ExcelWriter(f'{output_path}delta_keepers_{current_year}.xlsx', engine='xlsxwriter')
keeper_df.to_excel(writer, sheet_name="keepers", index=False)

workbook = writer.book
worksheet = writer.sheets["keepers"]

format_ineligible = workbook.add_format({
    'bg_color': '#FFC7CE',
    'font_color': '#9C0006',
    'italic': True,
    'font_strikeout': True,
})
bottom_border_format = workbook.add_format({'bottom': 5, 'bottom_color': 'black'})
left_border_format = workbook.add_format({'left': 5, 'left_color': 'black'})
border_format_blue = workbook.add_format({
    'bottom': 5, 'bottom_color': 'black', 'bg_color': '#cfe2f3',
})
format_light_blue = workbook.add_format({'bg_color': '#cfe2f3'})

# Alternate team row shading
players_by_team = keeper_df.pivot_table(index='Team', aggfunc='count')['Player Name']
highlight_row = 0
for team_index in range(len(players_by_team)):
    if team_index % 2 == 0:
        for i in range(highlight_row, highlight_row + players_by_team[team_index]):
            worksheet.set_row(i + 1, None, format_light_blue)
    highlight_row += players_by_team[team_index]
    if team_index % 2 == 0:
        worksheet.set_row(highlight_row, None, border_format_blue)
    else:
        worksheet.set_row(highlight_row, None, bottom_border_format)

worksheet.conditional_format('A2:K1000', {
    'type': 'formula', 'criteria': '=$I2<>TRUE', 'format': format_ineligible,
})
worksheet.set_column('B:B', None, None, {'hidden': True})
worksheet.set_column('L:L', None, left_border_format)
worksheet.autofilter('A1:K1000')
worksheet.set_column(7, 7, 19)
worksheet.freeze_panes(1, 1)

writer.close()
print(f"Done. Output saved to {output_path}")
