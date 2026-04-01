#!/usr/bin/env -S uv run
"""
Delta League Offseason Sheet Preparation

Single script that prepares the "Delta League Keepers {year}" Google Sheet
for the upcoming season:

1. Computes keeper values (via delta_keeper_api)
2. Creates/finds the Google Sheet for the new year
3. Writes keeper values with formatting
4. Sets up the Rookie Draft tab with pick order from standings/brackets
5. Preserves traded rookie pick notes with year indicators
6. Clears the Keeper Selections tab for fresh input
"""

import datetime

from delta_keeper_api import (
    LEAGUE_NAME,
    LOTTERY_ODDS,
    NUM_KEEPERS,
    SLEEPER_BASE,
    compute_keepers,
    export_local,
    fetch_json,
    find_or_create_sheet,
    get_tab_id,
    init_google_services,
    read_sheet_tab,
    clear_range,
    write_df_to_sheet,
    write_values,
)

current_year = datetime.datetime.now().year
nfl_season = current_year - 1


# ============================================================================
# Rookie draft order helpers (Article VII)
# ============================================================================

def resolve_bracket_order(bracket):
    """
    Parse a Sleeper bracket (winners or losers) and return finish order.
    Returns dict: {finish_place: roster_id}
    """
    max_round = max(m['r'] for m in bracket)
    results = {}

    # Matches with explicit placement ('p' field)
    for m in bracket:
        if 'p' in m and m['p'] and m.get('w') is not None:
            results[m['p']] = m['w']
            results[m['p'] + 1] = m['l']

    # If placements aren't tagged, infer from final round
    if not results:
        final_matches = sorted(
            [m for m in bracket if m['r'] == max_round],
            key=lambda m: m['m']
        )
        # First final match = championship/consolation final
        if len(final_matches) >= 1:
            results[1] = final_matches[0]['w']
            results[2] = final_matches[0]['l']
        if len(final_matches) >= 2:
            results[3] = final_matches[1]['w']
            results[4] = final_matches[1]['l']

        # Previous round for 5th/6th
        prev_round_matches = [m for m in bracket if m['r'] == max_round - 1]
        final_teams = set()
        for m in final_matches:
            final_teams.add(m.get('t1'))
            final_teams.add(m.get('t2'))
        fifth_match = [m for m in prev_round_matches if m.get('w') not in final_teams]
        if fifth_match:
            results[5] = fifth_match[0]['w']
            results[6] = fifth_match[0]['l']

    return results


def get_pick_label(rid, rid_to_name):
    """Get display name for a pick."""
    return rid_to_name.get(rid, f"roster_{rid}")


def build_rookie_draft_rows(league_id, rid_to_name, trade_notes):
    """
    Build the Rookie Draft tab content from Sleeper bracket data.
    Returns list of rows for columns A-C.
    """
    winners = fetch_json(f"{SLEEPER_BASE}/league/{league_id}/winners_bracket")
    losers = fetch_json(f"{SLEEPER_BASE}/league/{league_id}/losers_bracket")

    losers_order = resolve_bracket_order(losers)
    winners_order = resolve_bracket_order(winners)

    rows = [["Pick", "Team", "Player"]]

    # Pick 1: consolation bracket winner
    consolation_winner = losers_order.get(1)
    rows.append(["1", get_pick_label(consolation_winner, rid_to_name), ""])

    # Picks 2-6: lottery (consolation places 2-6)
    lottery_rids = [losers_order.get(i + 2) for i in range(len(LOTTERY_ODDS))]
    for i, (label, odds) in enumerate(LOTTERY_ODDS):
        rid = lottery_rids[i]
        name = rid_to_name.get(rid, "TBD") if rid else "TBD"
        rows.append([str(i + 2), f"LOTTERY ({odds}% {name})", ""])

    # Picks 7-12: winners bracket, 6th overall → pick 7, champion → pick 12
    standings_order = [
        winners_order.get(6),  # pick 7
        winners_order.get(5),  # pick 8
        winners_order.get(4),  # pick 9
        winners_order.get(3),  # pick 10
        winners_order.get(2),  # pick 11
        winners_order.get(1),  # pick 12 (champion)
    ]
    for i, rid in enumerate(standings_order):
        rows.append([str(i + 7), get_pick_label(rid, rid_to_name), ""])

    # Blank separator
    rows.append(["", "", ""])

    # Lottery odds reference
    rows.append(["", "Lottery Odds", ""])
    cumulative = 0
    for i, (label, odds) in enumerate(LOTTERY_ODDS):
        rid = lottery_rids[i]
        name = rid_to_name.get(rid, "TBD") if rid else "TBD"
        low = cumulative + 1
        high = cumulative + odds
        rows.append(["", f"{label} ({name})", f"{low}-{high}"])
        cumulative = high

    # Blank separator
    rows.append(["", "", ""])

    # Trade notes with year
    rows.append(["Year", "Trade Notes", ""])
    for note in trade_notes:
        rows.append([note[0], note[1], ""])

    return rows


# ============================================================================
# Google Sheets formatting
# ============================================================================

def format_keeper_values_tab(sheets_svc, spreadsheet_id, keeper_df):
    """Apply formatting to the Keeper Values tab in Google Sheets."""
    keeper_tab_id = get_tab_id(sheets_svc, spreadsheet_id, "Keeper Values")
    if keeper_tab_id is None:
        print("  WARNING: 'Keeper Values' tab not found, skipping formatting")
        return

    num_rows = len(keeper_df) + 1
    num_cols = len(keeper_df.columns)

    # Delete stale conditional format rules
    existing = sheets_svc.spreadsheets().get(
        spreadsheetId=spreadsheet_id, fields="sheets(properties,conditionalFormats)",
    ).execute()
    del_reqs = []
    for s in existing["sheets"]:
        if s["properties"]["sheetId"] == keeper_tab_id:
            for i in range(len(s.get("conditionalFormats", [])) - 1, -1, -1):
                del_reqs.append({"deleteConditionalFormatRule": {
                    "sheetId": keeper_tab_id, "index": i,
                }})
            break
    if del_reqs:
        sheets_svc.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": del_reqs},
        ).execute()

    fmt_reqs = []

    # Clear cell formatting
    fmt_reqs.append({"repeatCell": {
        "range": {"sheetId": keeper_tab_id, "startRowIndex": 1, "endRowIndex": 1000,
                  "startColumnIndex": 0, "endColumnIndex": num_cols},
        "cell": {"userEnteredFormat": {}}, "fields": "userEnteredFormat",
    }})

    # Conditional format: ineligible = strikethrough red
    fmt_reqs.append({"addConditionalFormatRule": {
        "rule": {
            "ranges": [{"sheetId": keeper_tab_id, "startRowIndex": 1, "endRowIndex": num_rows,
                        "startColumnIndex": 0, "endColumnIndex": num_cols}],
            "booleanRule": {
                "condition": {"type": "CUSTOM_FORMULA",
                              "values": [{"userEnteredValue": "=$I2<>TRUE"}]},
                "format": {
                    "textFormat": {"strikethrough": True, "italic": True,
                                   "foregroundColorStyle": {"rgbColor": {"red": 0.61, "green": 0.0, "blue": 0.024}}},
                    "backgroundColor": {"red": 1.0, "green": 0.78, "blue": 0.81},
                },
            },
        }, "index": 0,
    }})

    # Alternating team shading + team separator borders
    current_team = None
    team_idx = 0
    team_last_row = {}  # team_idx -> last row index (0-based, in sheet)
    for i, (_, row) in enumerate(keeper_df.iterrows()):
        if row["Team"] != current_team:
            current_team = row["Team"]
            team_idx += 1
        team_last_row[team_idx] = i + 1  # +1 for header
        if team_idx % 2 == 1:
            fmt_reqs.append({"repeatCell": {
                "range": {"sheetId": keeper_tab_id, "startRowIndex": i + 1, "endRowIndex": i + 2,
                          "startColumnIndex": 0, "endColumnIndex": num_cols},
                "cell": {"userEnteredFormat": {"backgroundColor": {"red": 0.81, "green": 0.89, "blue": 0.95}}},
                "fields": "userEnteredFormat.backgroundColor",
            }})

    # Add thick bottom border on last row of each team
    for tidx, last_row in team_last_row.items():
        fmt_reqs.append({"updateBorders": {
            "range": {"sheetId": keeper_tab_id, "startRowIndex": last_row, "endRowIndex": last_row + 1,
                      "startColumnIndex": 0, "endColumnIndex": num_cols},
            "bottom": {"style": "SOLID_THICK", "color": {"red": 0, "green": 0, "blue": 0}},
        }})

    # Freeze + hide + bold
    fmt_reqs.append({"updateSheetProperties": {
        "properties": {"sheetId": keeper_tab_id,
                       "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 1}},
        "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
    }})
    fmt_reqs.append({"updateDimensionProperties": {
        "range": {"sheetId": keeper_tab_id, "dimension": "COLUMNS", "startIndex": 1, "endIndex": 2},
        "properties": {"hiddenByUser": True}, "fields": "hiddenByUser",
    }})
    fmt_reqs.append({"repeatCell": {
        "range": {"sheetId": keeper_tab_id, "startRowIndex": 0, "endRowIndex": 1,
                  "startColumnIndex": 0, "endColumnIndex": num_cols},
        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
        "fields": "userEnteredFormat.textFormat.bold",
    }})

    sheets_svc.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body={"requests": fmt_reqs},
    ).execute()
    print("  Applied formatting to 'Keeper Values' tab")


# ============================================================================
# Main
# ============================================================================

def main():
    print("=" * 60)
    print(f"Delta League Offseason Prep — {current_year} Season")
    print("=" * 60)

    # --- Step 1: Compute keepers ---
    print()
    print("STEP 1: Compute keeper values")
    print("-" * 40)
    sheets_svc, drive_svc = init_google_services()
    keeper_df, league_id, prev_sheet_id, rid_to_name, trade_notes = compute_keepers(
        sheets_svc, drive_svc, nfl_season
    )

    # --- Step 2: Export local files ---
    print()
    print("STEP 2: Export local files")
    print("-" * 40)
    export_local(keeper_df, current_year)

    # --- Step 3: Create/find Google Sheet ---
    print()
    print("STEP 3: Prepare Google Sheet")
    print("-" * 40)
    current_sheet_id = find_or_create_sheet(drive_svc, prev_sheet_id, current_year)

    # Rename Rookie Draft tab
    prev_rookie_tab = f"Rookie Draft {nfl_season}"
    rookie_tab = f"Rookie Draft {current_year}"
    tab_id = get_tab_id(sheets_svc, current_sheet_id, prev_rookie_tab)
    if tab_id is not None:
        sheets_svc.spreadsheets().batchUpdate(
            spreadsheetId=current_sheet_id,
            body={"requests": [{"updateSheetProperties": {
                "properties": {"sheetId": tab_id, "title": rookie_tab},
                "fields": "title",
            }}]},
        ).execute()
        print(f"  Renamed '{prev_rookie_tab}' → '{rookie_tab}'")

    # --- Step 4: Write Keeper Values ---
    print()
    print("STEP 4: Write Keeper Values")
    print("-" * 40)
    write_df_to_sheet(sheets_svc, current_sheet_id, "Keeper Values", keeper_df)
    print("  Updated 'Keeper Values' tab")
    format_keeper_values_tab(sheets_svc, current_sheet_id, keeper_df)

    # --- Step 5: Write Rookie Draft ---
    print()
    print("STEP 5: Set up Rookie Draft")
    print("-" * 40)
    pick_rows = build_rookie_draft_rows(league_id, rid_to_name, trade_notes)
    clear_range(sheets_svc, current_sheet_id, rookie_tab)
    write_values(sheets_svc, current_sheet_id, f"'{rookie_tab}'!A1", pick_rows)
    write_values(sheets_svc, current_sheet_id, f"'{rookie_tab}'!F1", [["adp_round", "player_name"]])
    for row in pick_rows[1:13]:
        print(f"  Pick {row[0]}: {row[1]}")
    print(f"  {len(trade_notes)} trade note(s) carried forward")

    # --- Step 6: Clear Keeper Selections ---
    print()
    print("STEP 6: Clear Keeper Selections")
    print("-" * 40)
    keepers_sel = read_sheet_tab(sheets_svc, current_sheet_id, "Keeper Selections")
    num_rows = len(keepers_sel) + 1
    clear_vals = [["Keeper 1", "Keeper 2", "Keeper 3"]]
    clear_vals += [["", "", ""]] * (num_rows - 1)
    write_values(sheets_svc, current_sheet_id, f"'Keeper Selections'!B1:D{num_rows}", clear_vals)
    print("  Cleared keeper selections (kept team names)")

    # --- Done ---
    sheet_url = f"https://docs.google.com/spreadsheets/d/{current_sheet_id}/edit"
    print()
    print("=" * 60)
    print(f"Done! Google Sheet: {sheet_url}")
    print("=" * 60)


if __name__ == "__main__":
    main()
