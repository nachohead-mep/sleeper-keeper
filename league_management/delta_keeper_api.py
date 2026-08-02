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


def fetch_draft_picks_by_player(league_id):
    """Fetch a league's most recent draft, keyed by player_id."""
    drafts = fetch_json(f"{SLEEPER_BASE}/league/{league_id}/drafts")
    if not drafts:
        return {}
    picks = fetch_json(f"{SLEEPER_BASE}/draft/{drafts[0]['draft_id']}/picks")
    return {str(p['player_id']): p for p in picks if p.get('player_id')}


def fetch_wire_added_player_ids(league_id, weeks=NFL_WEEKS):
    """
    Player IDs added via waiver or free agency at any point in a season.

    Used to detect when a player's keeper streak was actually broken (dropped
    and picked back up off the wire). Trades are excluded on purpose — moving
    a kept player between rosters doesn't reset his keeper clock.
    """
    added = set()
    for week in range(1, weeks + 1):
        txns = fetch_json(f"{SLEEPER_BASE}/league/{league_id}/transactions/{week}")
        for trans in txns:
            if trans['status'] == 'failed' or trans['type'] not in ('waiver', 'free_agent'):
                continue
            if trans['adds']:
                added.update(str(pid) for pid in trans['adds'])
    return added


def fetch_waiver_adds_detail(league_id, weeks=NFL_WEEKS):
    """
    Latest single-player waiver claim per player_id for a season, with the
    week and bid amount -- mirrors the current-season waiver_adds_by_player
    construction, needed so historical reconstruction can apply the same
    FAAB-based keeper round a waiver claim establishes (Article VI: a
    player can be kept the year after being claimed off waivers, with no
    draft pick involved at all, priced off the bid amount rather than a
    draft round).
    """
    detail = {}
    for week in range(1, weeks + 1):
        txns = fetch_json(f"{SLEEPER_BASE}/league/{league_id}/transactions/{week}")
        for trans in txns:
            if trans['status'] == 'failed' or trans['type'] != "waiver":
                continue
            if not trans['adds'] or len(trans['adds']) != 1:
                continue
            pid = str(next(iter(trans['adds'])))
            rec = {'trans_week': trans['leg'], 'waiver_bid': trans['settings']['waiver_bid']}
            if pid not in detail or trans['leg'] > detail[pid]['trans_week']:
                detail[pid] = rec
    return detail


def fetch_traded_pick_slots(league_id):
    """
    (round, roster_id) pairs for draft picks that changed hands before a
    league's draft that season -- i.e. NOT the team's own original slot.

    This league keeps players acquired via trade by manually drafting them
    with a pick that was itself traded for -- Sleeper's is_keeper checkbox
    only works on a team's own original slot, so it structurally can't flag
    that kind of keep. A traded pick used to draft a player already on that
    roster is strong, independently-provable evidence of a deliberate keep,
    even with no checkbox and no sheet record.
    """
    traded = fetch_json(f"{SLEEPER_BASE}/league/{league_id}/traded_picks")
    return {(t['round'], t['owner_id']) for t in traded}


def reconstruct_prior_keep_streak(player_id, player_name, history_seasons):
    """
    Reconstruct how many consecutive seasons a player has already been kept.

    A drafted season only counts as a confirmed keep if EITHER:
      1. Sleeper's is_keeper checkbox was set on that year's draft pick, OR
      2. The pick used was itself a traded pick (not the team's own original
         slot) -- proof the player couldn't have been freshly drafted with a
         normal pick, since he was already rostered.
    Continuous rostering plus a coincidentally-matching round is NOT enough
    on its own (a star who's simply never dropped gets re-drafted every year
    regardless, at whatever his natural market round is) -- that produced a
    flood of false positives (Josh Allen, CeeDee Lamb, etc.) when tried.

    Once a season is a candidate via (1) or (2), the round itself still has
    to make sense as a keeper cost: it must be exactly round_ - (1 +
    times_kept_so_far), or one round earlier (a team without its own pick at
    the exact cost round substituting an adjacent one it did have). Picked
    LATER (a higher round number) than the required cost is disqualifying --
    that's underpaying the discount, which isn't possible for a real keep,
    so it proves the pick must have been a normal draft selection instead.

    A season can ALSO establish (or override) next season's keeper-cost
    baseline with no draft pick involved at all: Article VI lets a player be
    kept the year after a waiver claim, priced off the FAAB bid via
    get_round_from_faab(), as long as the claim landed before the keeper
    deadline week and it isn't a high/early-round pick that season. This
    mirrors the live per-season computation exactly (a same-season waiver
    claim overrides the draft-based cost there too) -- confirmed for Trey
    McBride's case: an early, $0 waiver claim priced him at exactly round
    12, which is exactly the (traded) pick he was drafted with the next
    season, with no prior draft appearance to check round math against at
    all otherwise.

    The "Keeper Selections" Google Sheet, when it exists for that year, is
    independent corroboration (a requirement only when there's no round
    baseline yet to check math against -- a first sighting or the season
    right after a FAAB baseline resets to no-history -- since it has its own
    gaps, which is exactly why Drake London's case slipped through in the
    first place) and is recorded in the trail for transparency.

    history_seasons: seasons strictly before the one being computed, oldest
    to newest, each {'season': year, 'picks': {player_id: pick},
    'wire_added': {player_id,...}, 'waiver_detail': {player_id: {trans_week,
    waiver_bid}}, 'kept_names': {player_name,...}, 'traded_pick_slots':
    {(round, roster_id),...}}.

    Returns (times_kept, prev_round, trail). prev_round is the keeper-cost
    baseline entering the season being computed (from a draft pick or a
    FAAB claim, whichever applies), or None if the chain doesn't reach the
    season right before the one being computed. trail is a list of
    per-season dicts recording exactly which signal (or lack of one)
    applied each year, for transparency before anyone corrects a sheet off
    of this.
    """
    times_kept = 0
    prev_round = None
    trail = []
    for season in history_seasons:
        yr = season.get('season')
        pick = season['picks'].get(player_id)
        wire_detail = season.get('waiver_detail', {}).get(player_id)
        claimed_late = wire_detail is not None and wire_detail['trans_week'] >= KEEPER_DEADLINE_WEEK

        if pick is None:
            if wire_detail is None:
                trail.append({'season': yr, 'round': None, 'signal': 'not-drafted'})
                times_kept = 0
                prev_round = None
            elif claimed_late:
                trail.append({'season': yr, 'round': None, 'signal': 'waiver-after-deadline'})
                times_kept = 0
                prev_round = None
            else:
                faab_round = get_round_from_faab(wire_detail['waiver_bid'])
                trail.append({'season': yr, 'round': faab_round, 'signal': 'faab-baseline'})
                times_kept = 0  # establishes a fresh cost, not itself a keep
                # get_round_from_faab() already IS the computed keeper cost
                # for next season (not a raw "round" to subtract from again)
                # -- store it +1 so the general `prev_round - (1+times_kept)`
                # check below reproduces it exactly with times_kept=0, same
                # as how a fresh (non-keeper) draft pick's cost is round_-1.
                prev_round = faab_round + 1
            continue

        rnd = pick['round']
        rid = pick.get('roster_id')
        high_draft_pick = rnd <= HIGH_PICK_THRESHOLD
        is_keeper_flag = bool(pick.get('is_keeper'))
        pick_was_traded = (rnd, rid) in season.get('traded_pick_slots', set())
        sheet_recorded = player_name in season.get('kept_names', set())

        if rnd == 1 and FIRST_ROUND_INELIGIBLE:
            trail.append({'season': yr, 'round': rnd, 'signal': 'first-round-ineligible'})
            times_kept = 0
            prev_round = None
            continue

        if prev_round is not None:
            # A real prior baseline exists (from a draft pick or a FAAB
            # claim) to be continuing from -- a traded pick here is
            # meaningful evidence, checked against the formula.
            expected = prev_round - (1 + times_kept)
            round_makes_sense = expected - 1 <= rnd <= expected
        else:
            # No baseline to check round math against (a true rookie debut,
            # or the season right after a reset) -- round math can't apply.
            round_makes_sense = True

        # The Keeper Selections sheet, when it has a record for this player
        # this year, is authoritative on its own -- it's the direct human
        # record of what a team actually did, which is exactly what
        # Sleeper's is_keeper checkbox and the round-cost formula are both
        # trying to reconstruct indirectly. Trust it outright rather than
        # requiring it to also line up with the round math.
        confirmed = is_keeper_flag or sheet_recorded or (pick_was_traded and round_makes_sense)

        if confirmed:
            times_kept += 1
            signals = []
            if is_keeper_flag:
                signals.append('is_keeper-flag')
            if pick_was_traded:
                signals.append('traded-pick')
            if sheet_recorded:
                signals.append('sheet-record')
            if not round_makes_sense:
                signals.append('round-does-not-match-formula(trusting is_keeper anyway)')
            trail.append({'season': yr, 'round': rnd, 'signal': '+'.join(signals)})
        else:
            times_kept = 0
            reason = 'traded-pick-but-round-too-late' if (pick_was_traded and not round_makes_sense) \
                else 'baseline/normal-pick'
            trail.append({'season': yr, 'round': rnd, 'signal': reason})

        # A same-season waiver claim (in-season churn: dropped after the
        # draft, re-claimed later) overrides the draft-based cost for next
        # season, exactly like the live per-season computation -- his most
        # recent acquisition method wins. Same +1 units fix as the
        # standalone FAAB-baseline case above.
        if wire_detail is not None and not high_draft_pick and not claimed_late:
            prev_round = get_round_from_faab(wire_detail['waiver_bid']) + 1
            times_kept = 0
        else:
            prev_round = rnd
    return times_kept, prev_round, trail


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

    picks_by_player = fetch_draft_picks_by_player(league_id)
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

    current_traded_pick_slots = fetch_traded_pick_slots(league_id)

    print("Fetching transactions...")
    waiver_adds_by_player = {}
    current_wire_added = set()
    for week in range(1, NFL_WEEKS + 1):
        txns = fetch_json(f"{SLEEPER_BASE}/league/{league_id}/transactions/{week}")
        for trans in txns:
            if trans['status'] == 'failed':
                continue
            if trans['type'] in ('waiver', 'free_agent') and trans['adds']:
                current_wire_added.update(str(pid) for pid in trans['adds'])
            if trans['type'] != "waiver":
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

    print("Reconstructing multi-season keeper streaks from Sleeper history...")
    found_seasons = []
    probe_season = nfl_season - 1
    for _ in range(10):  # safety cap on lookback depth
        try:
            hist_league_id = find_league_id(_MEMBER_USER_ID, LEAGUE_NAME, probe_season)
        except RuntimeError:
            break
        found_seasons.append((probe_season, hist_league_id))
        probe_season -= 1
    found_seasons.reverse()  # oldest -> newest
    history_seasons = []
    for season, hist_league_id in found_seasons:
        hist_picks = fetch_draft_picks_by_player(hist_league_id)
        hist_waiver_detail = fetch_waiver_adds_detail(hist_league_id)
        hist_traded_slots = fetch_traded_pick_slots(hist_league_id)
        hist_kept_names = set()
        try:
            hist_sheet_id = find_keeper_sheet(drive_svc, season)
            hist_selections = read_sheet_tab(sheets_svc, hist_sheet_id, "Keeper Selections")
            for col in keeper_columns:
                if col in hist_selections.columns:
                    hist_kept_names.update(hist_selections[col].dropna())
        except FileNotFoundError:
            pass  # no sheet for this season (predates the tracking spreadsheet) -- fine, just no signal
        history_seasons.append({
            'season': season, 'picks': hist_picks, 'waiver_detail': hist_waiver_detail,
            'kept_names': hist_kept_names, 'traded_pick_slots': hist_traded_slots,
        })
        print(f"  {season}: {len(hist_picks)} draft picks, {len(hist_waiver_detail)} waiver claims, "
              f"{len(hist_kept_names)} sheet-recorded keepers, {len(hist_traded_slots)} traded pick slots")

    # --- One-off audit: where do the sheet and the mechanical evidence disagree? ---
    # Sheet-only (sheet says kept, no is_keeper/traded-pick/round evidence) is
    # expected and fine -- the sheet is authoritative, this is exactly the
    # traded-pick gap it exists to cover. Mechanical-only (evidence found,
    # sheet silent) is the interesting category -- same pattern as Drake
    # London, worth listing explicitly.
    print("Auditing sheet vs. mechanical evidence across all drafted players...")
    audit_targets = [(i, s) for i, s in enumerate(history_seasons) if s['kept_names']]
    audit_targets.append((len(history_seasons), {
        'season': nfl_season, 'picks': picks_by_player, 'waiver_detail': waiver_adds_by_player,
        'kept_names': kept_player_names, 'traded_pick_slots': current_traded_pick_slots,
    }))
    for idx, season_data in audit_targets:
        prior_seasons = history_seasons[:idx]
        sheet_only, mech_only = [], []
        for pid, pick in season_data['picks'].items():
            info = all_players.get(pid)
            if info is None:
                continue
            name = f"{info['first_name']} {info['last_name']}"
            rnd = pick['round']
            rid = pick.get('roster_id')
            is_keeper_flag = bool(pick.get('is_keeper'))
            pick_was_traded = (rnd, rid) in season_data.get('traded_pick_slots', set())
            sheet_recorded = name in season_data.get('kept_names', set())
            if rnd == 1 and FIRST_ROUND_INELIGIBLE:
                mech_confirmed = False  # round-1 picks can never be a keeper, regardless of flags/round math
            else:
                prev_tk, prev_round, _ = reconstruct_prior_keep_streak(pid, name, prior_seasons)
                round_makes_sense = (
                    prev_round is not None
                    and (prev_round - (2 + prev_tk)) <= rnd <= (prev_round - (1 + prev_tk))
                )
                mech_confirmed = is_keeper_flag or (pick_was_traded and round_makes_sense)
            if sheet_recorded and not mech_confirmed:
                sheet_only.append(name)
            elif mech_confirmed and not sheet_recorded:
                mech_only.append((name, 'is_keeper' if is_keeper_flag else 'traded-pick+round-match', rnd))
        yr = season_data['season']
        if sheet_only:
            print(f"  [{yr}] sheet-only (trusted, no independent mechanical evidence): {', '.join(sorted(sheet_only))}")
        if mech_only:
            details = ', '.join(f"{n} ({r}, round {rd})" for n, r, rd in sorted(mech_only))
            print(f"  [{yr}] MECHANICAL-ONLY (evidence found, sheet silent): {details}")
        if not sheet_only and not mech_only:
            print(f"  [{yr}] sheet and mechanical evidence fully agree")

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
            review_flag = ""

            pick = picks_by_player.get(player_id)
            if pick is not None:
                round_ = pick['round']
                pick_ = pick['pick_no']
                high_draft_pick = round_ <= HIGH_PICK_THRESHOLD
                if FIRST_ROUND_INELIGIBLE and round_ == 1:
                    keeper_eligible = False
                else:
                    keeper_round = min(round_ - 1, MAX_KEEPER_ROUND)
                flagged_keeper = pick['is_keeper'] or player_name in kept_player_names
                if flagged_keeper:
                    prev_tk = prev_keeper_by_id.get(str(player_info['player_id']))
                    if prev_tk is not None:
                        times_kept = int(prev_tk) + 1
                        keeper_round = round_ - (1 + times_kept)
                    else:
                        print(f"    WARNING: {player_name} flagged as keeper but not in previous year's sheet")

                # Cross-check against reconstructed history: Sleeper's is_keeper
                # checkbox structurally can't flag a keep for a player kept via
                # a traded pick -- its native keeper mechanic only recognizes a
                # team's own original draft slot, so those keeps get manually
                # entered as a plain draft pick instead. A season only counts
                # as a reconstructed continuation if EITHER is_keeper was set,
                # OR this pick was itself a traded pick AND the round makes
                # sense as a keeper cost (exactly round_ - (1+times_kept), or
                # one round earlier for a team without its own pick at that
                # exact round). Round continuity on an untraded, un-flagged
                # pick is NOT enough on its own -- that's indistinguishable
                # from a star simply never being dropped and re-drafted at his
                # natural market round, which produced a flood of false
                # positives (Josh Allen, CeeDee Lamb, etc.) when tried.
                #
                # This never overrides eligibility/keeper_round automatically
                # -- it only surfaces a review flag, covering two distinct
                # failure modes: (a) times_kept undercounted enough to flip
                # eligibility (like Drake London), and (b) times_kept off by
                # a smaller amount that still leaves the player eligible but
                # prices the discount at the wrong tier (e.g. costed as a
                # 1st-year keep when history says it's really the 2nd).
                wire_added_this_season = player_id in current_wire_added
                reconstructed_prev_tk, reconstructed_prev_round, reconstructed_trail = reconstruct_prior_keep_streak(
                    player_id, player_name, history_seasons
                )
                current_pick_was_traded = (round_, pick.get('roster_id')) in current_traded_pick_slots
                if reconstructed_prev_round is not None:
                    current_expected = reconstructed_prev_round - (1 + reconstructed_prev_tk)
                    current_round_makes_sense = current_expected - 1 <= round_ <= current_expected
                else:
                    current_round_makes_sense = False
                is_reconstructed_continuation = (
                    reconstructed_prev_round is not None
                    and not wire_added_this_season
                    and (flagged_keeper or (current_pick_was_traded and current_round_makes_sense))
                )
                if round_ != 1 and is_reconstructed_continuation:
                    reconstructed_times_kept = reconstructed_prev_tk + 1
                    if reconstructed_times_kept != times_kept:
                        corrected_round = round_ - (1 + reconstructed_times_kept)
                        would_flip = reconstructed_times_kept >= MAX_CONSECUTIVE_KEEPS or corrected_round < 1
                        direction = "undercounted" if reconstructed_times_kept > times_kept else "overcounted"
                        trail_str = " -> ".join(
                            f"{t['season']}:{t['round']}({t['signal']})" for t in reconstructed_trail
                        )
                        old_times_kept, old_keeper_round = times_kept, keeper_round
                        # Every step confirming this correction is either the
                        # is_keeper checkbox directly, or a verified traded
                        # pick with a round that makes sense as a keeper cost
                        # -- both independently provable from Sleeper's own
                        # data, not a coincidence-prone heuristic. Apply it.
                        times_kept = reconstructed_times_kept
                        keeper_round = corrected_round
                        review_flag = (
                            f"times_kept auto-corrected ({direction}): was {old_times_kept} "
                            f"(Keeper Round {old_keeper_round}), history confirms {reconstructed_times_kept} "
                            f"(Keeper Round {corrected_round}). "
                            f"{'Now NOT ELIGIBLE.' if would_flip else 'Still eligible.'} "
                            f"Confirmed via is_keeper flag or a verified traded draft pick each year "
                            f"(not roster continuity alone). Trail: {trail_str}"
                        )
                        print(f"    CORRECTED: {player_name} ({team_name}) - times_kept {direction}, "
                              f"{old_times_kept} -> {reconstructed_times_kept}"
                              + (" [NOW INELIGIBLE]" if would_flip else " [still eligible]")
                              + f" | {trail_str}")

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
                'review_flag': review_flag,
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
        'Keeper Eligible', 'Times Kept', 'Keeper Round', 'Review Flag',
    ]

    flagged_count = int((keeper_df['Review Flag'] != "").sum())
    if flagged_count:
        print(f"  {flagged_count} player(s) flagged for manual keeper-history review (see 'Review Flag' column)")

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

    worksheet.conditional_format('A2:L1000', {
        'type': 'formula', 'criteria': '=$I2<>TRUE', 'format': fmt_ineligible,
    })
    worksheet.set_column('B:B', None, None, {'hidden': True})
    worksheet.autofilter('A1:L1000')
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
