/**
 * Google Apps Script — Keeper Selections + Offseason Proposals
 * for Delta League GitHub Pages.
 *
 * Setup:
 *   1. Open "Delta League Keepers {year}" Google Sheet
 *   2. Extensions → Apps Script → paste this entire file
 *   3. Deploy → New deployment → Web app
 *        Execute as: Me   |   Who has access: Anyone
 *   4. Copy the deployed URL into generate_offseason_pages.py for both:
 *        APPS_SCRIPT_KEEPERS_URL and APPS_SCRIPT_PROPOSALS_URL
 *
 * Routing: GET/POST include an "action" parameter to select the handler.
 *   GET ?action=keepers     → read keeper selections
 *   GET ?action=proposals   → read offseason proposals
 *   POST {action:"keepers", ...}  → write keeper selections
 *   POST {action:"proposals", ...} → write offseason proposal
 */

const KEEPERS_SHEET = "Keeper Selections";
const PROPOSALS_SHEET = "Offseason Proposals";

// ── GET ─────────────────────────────────────────────────────

function doGet(e) {
  try {
    const action = (e && e.parameter && e.parameter.action) || "keepers";

    if (action === "proposals") return getProposals_();
    return getKeepers_();
  } catch (err) {
    return jsonResponse_({ error: err.message });
  }
}

function getKeepers_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const ws = ss.getSheetByName(KEEPERS_SHEET);
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

  return jsonResponse_({ selections: selections });
}

function getProposals_() {
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

  return jsonResponse_({ proposals: proposals });
}

// ── POST ────────────────────────────────────────────────────

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);
    const action = body.action || "keepers";

    if (action === "proposals") return postProposal_(body);
    return postKeepers_(body);
  } catch (err) {
    return jsonResponse_({ success: false, error: err.message });
  }
}

function postKeepers_(body) {
  const { manager, keeper1, keeper2, keeper3 } = body;

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const ws = ss.getSheetByName(KEEPERS_SHEET);
  const data = ws.getDataRange().getValues();

  let rowIdx = -1;
  for (let r = 1; r < data.length; r++) {
    if (String(data[r][0]).trim() === manager) { rowIdx = r; break; }
  }
  if (rowIdx < 0) throw new Error("Team not found: " + manager);

  ws.getRange(rowIdx + 1, 2).setValue(keeper1 || "");
  ws.getRange(rowIdx + 1, 3).setValue(keeper2 || "");
  ws.getRange(rowIdx + 1, 4).setValue(keeper3 || "");

  return jsonResponse_({ success: true });
}

function postProposal_(body) {
  const { description, pros, cons } = body;
  if (!description) throw new Error("Proposal description is required");

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const ws = ss.getSheetByName(PROPOSALS_SHEET);
  const data = ws.getDataRange().getValues();

  // Find next proposal number
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

  return jsonResponse_({ success: true, number: maxNum + 1 });
}

// ── Helpers ─────────────────────────────────────────────────

function jsonResponse_(obj) {
  return ContentService.createTextOutput(
    JSON.stringify(obj)
  ).setMimeType(ContentService.MimeType.JSON);
}
