#!/usr/bin/env -S uv run
"""
Delta League Keeper Value Calculator

Pulls roster, draft, and transaction data from the Sleeper API
to compute keeper eligibility and round cost for each player.

Previous-year keeper data (times kept, rookie ADP rounds, keeper
selections) is read from the "Delta League Keepers {year}" Google
Sheet via the Sheets and Drive APIs using Application Default
Credentials (gcloud ADC).

Can be run standalone or imported as a module by delta_offseason_prep.py.

NOTE: This script does not verify that a player was continuously held
from the trade deadline through the end of the season (constitution
Article VI requires this for keeper eligibility). It only checks
whether the most recent waiver add was before the deadline week.
Players dropped after the deadline should be manually flagged.
"""

import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env'))

import requests
import pandas as pd
import datetime

from google.auth import default as google_auth_default
from googleapiclient.discovery import build as google_build

# ---------------------------------------------------------------------------
# League rules (Article VI) — update these if the constitution is amended
# ---------------------------------------------------------------------------
LEAGUE_NAME = os.environ.get("SLEEPER_LEAGUE_NAME", "Delta Fantasy Football League")
_MEMBER_USER_ID = os.environ.get("SLEEPER_MEMBER_USER_ID", "737386559564894208")
NFL_WEEKS = 18
DRAFT_ROUNDS = 16
NUM_TEAMS = 12
MAX_KEEPER_ROUND = 12
FIRST_ROUND_INELIGIBLE = True
HIGH_PICK_THRESHOLD = 5
KEEPER_DEADLINE_WEEK = 13
NUM_KEEPERS = 3
MAX_CONSECUTIVE_KEEPS = 3

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

# Article VII: Rookie draft lottery odds by consolation bracket finish
LOTTERY_ODDS = [
    ("Consolation Runner Up", 30),
    ("Consolation 3rd", 25),
    ("Consolation 4th", 20),
    ("Consolation 5th", 15),
    ("Consolation 6th/Sacko", 10),
]

SLEEPER_BASE = "https://api.sleeper.app/v1"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
script_dir = os.path.dirname(os.path.abspath(__file__))
output_path = os.path.normpath(
    os.path.join(script_dir, '..', 'Output', 'Keeper Spreadsheet')
) + os.sep


# ---------------------------------------------------------------------------
# Helpers — Sleeper
# ---------------------------------------------------------------------------
def fetch_json(url):
    """Fetch JSON from a URL, raising on HTTP errors."""
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.json()


def find_league_id(user_id, league_name, season):
    """Find a Sleeper league ID by searching a member's leagues for a given season."""
    leagues = fetch_json(f"{SLEEPER_BASE}/user/{user_id}/leagues/nfl/{season}")
    matches = [lg for lg in leagues if lg["name"] == league_name]
    if not matches:
        raise RuntimeError(f"No league named '{league_name}' found for user {user_id} in {season}")
    if len(matches) > 1:
        print(f"  WARNING: Multiple leagues named '{league_name}' in {season}, using first")
    return matches[0]["league_id"]


def get_round_from_faab(faab):
    """Map a FAAB bid amount to a first-year keeper round per Article VI."""
    faab = int(faab)
    for threshold, keeper_round in FAAB_ROUND_THRESHOLDS:
        if faab < threshold:
            return keeper_round
    return FAAB_DEFAULT_ROUND


# ---------------------------------------------------------------------------
# Helpers — Google Sheets
# ---------------------------------------------------------------------------
def init_google_services():
    """Initialize Google Sheets and Drive API clients using ADC."""
    creds, _ = google_auth_default(scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ])
    sheets_svc = google_build("sheets", "v4", credentials=creds)
    drive_svc = google_build("drive", "v3", credentials=creds)
    return sheets_svc, drive_svc


def find_keeper_sheet(drive_svc, year):
    """Search Google Drive for the 'Delta League Keepers {year}' spreadsheet."""
    query = (
        f"name = 'Delta League Keepers {year}' "
        "and mimeType = 'application/vnd.google-apps.spreadsheet' "
        "and trashed = false"
    )
    results = drive_svc.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])
    if not files:
        raise FileNotFoundError(f"No Google Sheet found named 'Delta League Keepers {year}'")
    if len(files) > 1:
        print(f"  WARNING: Multiple sheets for 'Delta League Keepers {year}', using first")
    return files[0]["id"]


def find_or_create_sheet(drive_svc, source_sheet_id, year):
    """Find 'Delta League Keepers {year}' or create it by copying the source sheet."""
    query = (
        f"name = 'Delta League Keepers {year}' "
        "and mimeType = 'application/vnd.google-apps.spreadsheet' "
        "and trashed = false"
    )
    results = drive_svc.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])
    if files:
        print(f"  Found existing 'Delta League Keepers {year}' ({files[0]['id']})")
        return files[0]["id"]
    copied = drive_svc.files().copy(
        fileId=source_sheet_id,
        body={"name": f"Delta League Keepers {year}"},
    ).execute()
    print(f"  Created 'Delta League Keepers {year}' ({copied['id']}) from previous year")
    return copied["id"]


def read_sheet_tab(sheets_svc, spreadsheet_id, tab_name):
    """Read a Google Sheets tab into a pandas DataFrame with snake_case columns."""
    result = sheets_svc.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=tab_name,
    ).execute()
    rows = result.get("values", [])
    if not rows:
        return pd.DataFrame()
    headers = rows[0]
    data = rows[1:]
    data = [row + [""] * (len(headers) - len(row)) for row in data]
    df = pd.DataFrame(data, columns=headers)
    df.columns = df.columns.str.strip().str.lower().str.replace(' ', '_')
    return df


def write_df_to_sheet(sheets_svc, spreadsheet_id, tab_name, df):
    """Write a DataFrame to a Google Sheets tab, replacing all existing content."""
    header = df.columns.tolist()
    values = [header] + df.values.tolist()
    sheets_svc.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id, range=tab_name,
    ).execute()
    sheets_svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=f"{tab_name}!A1",
        valueInputOption="RAW", body={"values": values},
    ).execute()


def write_values(sheets_svc, spreadsheet_id, range_, values):
    """Write raw values to a specific range in a Google Sheet."""
    sheets_svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=range_,
        valueInputOption="RAW", body={"values": values},
    ).execute()


def clear_range(sheets_svc, spreadsheet_id, range_):
    """Clear a range in a Google Sheet."""
    sheets_svc.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id, range=range_,
    ).execute()


def get_tab_id(sheets_svc, spreadsheet_id, tab_name):
    """Get the numeric sheet ID for a named tab."""
    meta = sheets_svc.spreadsheets().get(
        spreadsheetId=spreadsheet_id, fields="sheets.properties",
    ).execute()
    for sheet in meta["sheets"]:
        if sheet["properties"]["title"] == tab_name:
            return sheet["properties"]["sheetId"]
    return None


# ---------------------------------------------------------------------------
# Core keeper computation
# ---------------------------------------------------------------------------
def compute_keepers(sheets_svc, drive_svc, nfl_season):
    """
    Compute keeper values for the upcoming season based on the given NFL season.

    Returns:
        keeper_df: DataFrame with display columns (Title Case)
        league_id: Sleeper league ID for the season
        prev_sheet_id: Google Sheet ID for the previous year's keeper sheet
        rid_to_name: dict mapping roster_id -> display_name
        trade_notes: list of [year, note_text] from previous rookie draft tab
    """
    current_year = nfl_season + 1

    prev_sheet_id = find_keeper_sheet(drive_svc, nfl_season)
    print(f"  Found 'Delta League Keepers {nfl_season}' ({prev_sheet_id})")

    # Load previous-year data from Google Sheets
    previous_keeper_sheet = read_sheet_tab(sheets_svc, prev_sheet_id, "Keeper Values")
    previous_keeper_sheet['times_kept'] = pd.to_numeric(
        previous_keeper_sheet['times_kept'], errors='coerce'
    ).fillna(0)
    previous_keeper_sheet['player_id'] = previous_keeper_sheet['player_id'].astype(str)
    prev_keeper_by_id = {
        row['player_id']: row['times_kept']
        for _, row in previous_keeper_sheet.iterrows()
    }

    rookie_draft = read_sheet_tab(sheets_svc, prev_sheet_id, f"Rookie Draft {nfl_season}")
    rookie_draft['adp_round'] = pd.to_numeric(rookie_draft['adp_round'], errors='coerce')
    rookie_draft_filtered = rookie_draft.dropna(subset=['player_name', 'adp_round'])
    rookie_draft_picks = rookie_draft.dropna(subset=['pick', 'player'])
    rookie_draft_merged = pd.merge(
        rookie_draft_picks[['pick', 'team', 'player']],
        rookie_draft_filtered[['player_name', 'adp_round']],
        how='inner', left_on='player', right_on='player_name'
    ).drop(columns=['player_name'])
    rookie_by_name = {
        row['player']: row['adp_round']
        for _, row in rookie_draft_merged.iterrows()
    }

    keepers_xl = read_sheet_tab(sheets_svc, prev_sheet_id, "Keeper Selections")
    keeper_columns = [f"keeper_{i}" for i in range(1, NUM_KEEPERS + 1)]
    kept_player_names = set()
    for col in keeper_columns:
        if col in keepers_xl.columns:
            kept_player_names.update(keepers_xl[col].dropna())

    # Read trade notes from previous rookie draft tab
    trade_notes = []
    for _, row in rookie_draft.iterrows():
        year_val = str(row.get('pick', '')).strip()
        note_val = str(row.get('team', '')).strip()
        if year_val.isdigit() and len(year_val) == 4:
            trade_notes.append([year_val, note_val])
        elif not year_val and note_val and 'gets' in note_val.lower():
            trade_notes.append([str(nfl_season), note_val])

    # Fetch from Sleeper API
    print("Fetching league data from Sleeper API...")
    league_id = find_league_id(_MEMBER_USER_ID, LEAGUE_NAME, nfl_season)
    print(f"  Found '{LEAGUE_NAME}' {nfl_season} season (league ID: {league_id})")

    drafts = fetch_json(f"{SLEEPER_BASE}/league/{league_id}/drafts")
    draft_id = drafts[0]['draft_id']
    picks = fetch_json(f"{SLEEPER_BASE}/draft/{draft_id}/picks")
    picks_by_player = {str(p['player_id']): p for p in picks}
    rosters = fetch_json(f"{SLEEPER_BASE}/league/{league_id}/rosters")
    rosters_df = pd.DataFrame(rosters)
    roster_id_to_owner = {r['roster_id']: r['owner_id'] for r in rosters}
    users = fetch_json(f"{SLEEPER_BASE}/league/{league_id}/users")
    all_players = fetch_json(f"{SLEEPER_BASE}/players/nfl")

    uid_to_name = {u['user_id']: u['display_name'] for u in users}
    rid_to_name = {
        r['roster_id']: uid_to_name.get(r['owner_id'], str(r['owner_id']))
        for r in rosters
    }

    print("Fetching transactions...")
    waiver_adds_by_player = {}
    for week in range(1, NFL_WEEKS + 1):
        txns = fetch_json(f"{SLEEPER_BASE}/league/{league_id}/transactions/{week}")
        for trans in txns:
            if trans['status'] == 'failed' or trans['type'] != "waiver":
                continue
            if not trans['adds'] or len(trans['adds']) != 1:
                continue
            pid = str(next(iter(trans['adds'])))
            rid = trans['adds'][next(iter(trans['adds']))]
            rec = {
                'trans_week': trans['leg'],
                'waiver_bid': trans['settings']['waiver_bid'],
                'owner_id': roster_id_to_owner[rid],
            }
            if pid not in waiver_adds_by_player or trans['leg'] > waiver_adds_by_player[pid]['trans_week']:
                waiver_adds_by_player[pid] = rec

    print("Computing keeper values...")
    keeper_rows = []
    for team in users:
        team_name = team['display_name']
        roster = rosters_df[rosters_df['owner_id'] == team['user_id']]
        if len(roster) == 0:
            continue
        player_list = roster['players'].iloc[0]

        for player_id in player_list:
            player_id = str(player_id)
            player_info = all_players.get(player_id)
            if player_info is None:
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

            pick = picks_by_player.get(player_id)
            if pick is not None:
                round_ = pick['round']
                pick_ = pick['pick_no']
                high_draft_pick = round_ <= HIGH_PICK_THRESHOLD
                if FIRST_ROUND_INELIGIBLE and round_ == 1:
                    keeper_eligible = False
                else:
                    keeper_round = min(round_ - 1, MAX_KEEPER_ROUND)
                if pick['is_keeper'] or player_name in kept_player_names:
                    prev_tk = prev_keeper_by_id.get(str(player_info['player_id']))
                    if prev_tk is not None:
                        times_kept = int(prev_tk) + 1
                        keeper_round = round_ - (1 + times_kept)
                    else:
                        print(f"    WARNING: {player_name} flagged as keeper but not in previous year's sheet")

            rookie_adp = rookie_by_name.get(player_name)
            if rookie_adp is not None:
                round_ = rookie_adp
                high_draft_pick = round_ <= HIGH_PICK_THRESHOLD
                keeper_round = min(round_ - 1, MAX_KEEPER_ROUND)
                pick_ = 'R'

            waiver_add = waiver_adds_by_player.get(player_id)
            if waiver_add is not None:
                last_claim_date = waiver_add['trans_week']
                keeper_eligible = last_claim_date < KEEPER_DEADLINE_WEEK
                waivered = waiver_add['waiver_bid']
                if keeper_eligible and not high_draft_pick:
                    keeper_round = get_round_from_faab(waivered)

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
    keeper_df.loc[keeper_df['last_claim_amount'] == -1, 'last_claim_amount'] = "NO CLAIMS"
    keeper_df.loc[keeper_df['last_claim_week'] == -1, 'last_claim_week'] = "NO CLAIMS"
    keeper_df.loc[keeper_df['drafted_round'] == DRAFT_ROUNDS + 1, 'drafted_round'] = "UNDRAFTED"
    keeper_df.loc[keeper_df['keeper_round'] == 0, 'keeper_round'] = "NOT ELIGIBLE"

    keeper_df.columns = [
        'Team', 'Player ID', 'Player Name', 'Position', 'Drafted Round',
        'Drafted Pick', 'Last Claim Amount', 'Last Claim Week',
        'Keeper Eligible', 'Times Kept', 'Keeper Round',
    ]

    print(f"  Computed {len(keeper_df)} player rows across {keeper_df['Team'].nunique()} teams")

    return keeper_df, league_id, prev_sheet_id, rid_to_name, trade_notes


# ---------------------------------------------------------------------------
# Local export
# ---------------------------------------------------------------------------
def export_local(keeper_df, current_year):
    """Export keeper values to local CSV and formatted Excel."""
    os.makedirs(output_path, exist_ok=True)
    keeper_df.to_csv(f'{output_path}delta_keepers_{current_year}.csv', index=False)

    writer = pd.ExcelWriter(f'{output_path}delta_keepers_{current_year}.xlsx', engine='xlsxwriter')
    keeper_df.to_excel(writer, sheet_name="keepers", index=False)
    workbook = writer.book
    worksheet = writer.sheets["keepers"]

    fmt_ineligible = workbook.add_format({
        'bg_color': '#FFC7CE', 'font_color': '#9C0006',
        'italic': True, 'font_strikeout': True,
    })
    bottom_border = workbook.add_format({'bottom': 5, 'bottom_color': 'black'})
    border_blue = workbook.add_format({'bottom': 5, 'bottom_color': 'black', 'bg_color': '#cfe2f3'})
    light_blue = workbook.add_format({'bg_color': '#cfe2f3'})

    players_by_team = keeper_df.pivot_table(index='Team', aggfunc='count')['Player Name']
    highlight_row = 0
    for ti in range(len(players_by_team)):
        if ti % 2 == 0:
            for i in range(highlight_row, highlight_row + players_by_team.iloc[ti]):
                worksheet.set_row(i + 1, None, light_blue)
        highlight_row += players_by_team.iloc[ti]
        worksheet.set_row(highlight_row, None, border_blue if ti % 2 == 0 else bottom_border)

    worksheet.conditional_format('A2:K1000', {
        'type': 'formula', 'criteria': '=$I2<>TRUE', 'format': fmt_ineligible,
    })
    worksheet.set_column('B:B', None, None, {'hidden': True})
    worksheet.autofilter('A1:K1000')
    worksheet.set_column(7, 7, 19)
    worksheet.freeze_panes(1, 1)
    writer.close()
    print(f"  Saved to {output_path}")


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    current_year = datetime.datetime.now().year
    nfl_season = current_year - 1

    print("Connecting to Google Sheets...")
    sheets_svc, drive_svc = init_google_services()

    keeper_df, league_id, prev_sheet_id, rid_to_name, trade_notes = compute_keepers(
        sheets_svc, drive_svc, nfl_season
    )

    export_local(keeper_df, current_year)
    print("Done.")
