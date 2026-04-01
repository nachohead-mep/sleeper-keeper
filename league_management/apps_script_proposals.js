/**
 * Google Apps Script — Offseason Proposals read/write for GitHub Pages.
 *
 * Setup:
 *   1. Open the "Delta League Keepers {year}" Google Sheet
 *   2. Extensions → Apps Script → paste this file
 *   3. Deploy → New deployment → Web app
 *        Execute as: Me   |   Who has access: Anyone
 *   4. Copy the deployed URL into generate_offseason_pages.py APPS_SCRIPT_PROPOSALS_URL
 *
 * Reads/writes the "Offseason Proposals" tab.
 * Tab structure: Column A = #, B = Proposal Description, C = Pros, D = Cons
 */

const PROPOSALS_SHEET = "Offseason Proposals";

function doGet(e) {
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const ws = ss.getSheetByName(PROPOSALS_SHEET);
    const data = ws.getDataRange().getValues();

    const proposals = [];
    for (let r = 1; r < data.length; r++) {
      const num = String(data[r][0]).trim();
      const desc = String(data[r][1] || "").trim();
      if (!desc && !num) continue;
      proposals.push({
        number: num,
        description: desc,
        pros: String(data[r][2] || "").trim(),
        cons: String(data[r][3] || "").trim(),
      });
    }

    return ContentService.createTextOutput(
      JSON.stringify({ proposals: proposals })
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
    const { description, pros, cons } = body;
    if (!description) throw new Error("Proposal description is required");

    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const ws = ss.getSheetByName(PROPOSALS_SHEET);
    const data = ws.getDataRange().getValues();

    // Find the next proposal number
    let maxNum = 0;
    for (let r = 1; r < data.length; r++) {
      const n = parseInt(data[r][0]);
      if (!isNaN(n) && n > maxNum) maxNum = n;
    }

    // Find first empty row
    let emptyRow = data.length + 1;
    for (let r = 1; r < data.length; r++) {
      if (!String(data[r][0]).trim() && !String(data[r][1] || "").trim()) {
        emptyRow = r + 1;
        break;
      }
    }

    ws.getRange(emptyRow, 1).setValue(maxNum + 1);
    ws.getRange(emptyRow, 2).setValue(description);
    ws.getRange(emptyRow, 3).setValue(pros || "");
    ws.getRange(emptyRow, 4).setValue(cons || "");

    return ContentService.createTextOutput(
      JSON.stringify({ success: true, number: maxNum + 1 })
    ).setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService.createTextOutput(
      JSON.stringify({ success: false, error: err.message })
    ).setMimeType(ContentService.MimeType.JSON);
  }
}
