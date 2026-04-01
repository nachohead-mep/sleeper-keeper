/**
 * Google Apps Script — Keeper Selections read/write for GitHub Pages.
 *
 * Setup:
 *   1. Open the "Delta League Keepers {year}" Google Sheet
 *   2. Extensions → Apps Script → paste this file
 *   3. Deploy → New deployment → Web app
 *        Execute as: Me   |   Who has access: Anyone
 *   4. Copy the deployed URL into generate_offseason_pages.py APPS_SCRIPT_KEEPERS_URL
 *
 * Reads/writes the "Keeper Selections" tab.
 * Tab structure: Column A = Team name, B = Keeper 1, C = Keeper 2, D = Keeper 3
 */

const SELECTIONS_SHEET = "Keeper Selections";

function doGet(e) {
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const ws = ss.getSheetByName(SELECTIONS_SHEET);
    const data = ws.getDataRange().getValues();

    const selections = [];
    for (let r = 1; r < data.length; r++) {
      const team = String(data[r][0]).trim();
      if (!team) continue;
      selections.push({
        team: team,
        keeper_1: String(data[r][1] || "").trim(),
        keeper_2: String(data[r][2] || "").trim(),
        keeper_3: String(data[r][3] || "").trim(),
      });
    }

    return ContentService.createTextOutput(
      JSON.stringify({ selections: selections })
    ).setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService.createTextOutput(
      JSON.stringify({ error: err.message })
    ).setMimeType(ContentService.MimeType.JSON);
  }
}

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);
    const { manager, keeper1, keeper2, keeper3 } = body;

    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const ws = ss.getSheetByName(SELECTIONS_SHEET);
    const data = ws.getDataRange().getValues();

    let rowIdx = -1;
    for (let r = 1; r < data.length; r++) {
      if (String(data[r][0]).trim() === manager) { rowIdx = r; break; }
    }
    if (rowIdx < 0) throw new Error("Team not found: " + manager);

    // Write keepers to columns B, C, D (1-indexed: 2, 3, 4)
    ws.getRange(rowIdx + 1, 2).setValue(keeper1 || "");
    ws.getRange(rowIdx + 1, 3).setValue(keeper2 || "");
    ws.getRange(rowIdx + 1, 4).setValue(keeper3 || "");

    return ContentService.createTextOutput(
      JSON.stringify({ success: true })
    ).setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService.createTextOutput(
      JSON.stringify({ success: false, error: err.message })
    ).setMimeType(ContentService.MimeType.JSON);
  }
}
