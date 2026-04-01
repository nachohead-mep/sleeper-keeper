#!/usr/bin/env -S uv run
"""
Generate static HTML pages for the Delta League offseason site (GitHub Pages).

Reads keeper data from Google Sheets at build time and generates:
  - index.html (landing page)
  - keeper-values.html (interactive sortable/filterable table)
  - keeper-selections.html (form → Apps Script → Google Sheet)
  - offseason-proposals.html (form → Apps Script → Google Sheet)
  - rookie-draft.html (read-only pick order)
  - style.css (dark theme)
"""

import argparse
import os
import shutil
import datetime
from pathlib import Path

from delta_keeper_api import (
    init_google_services,
    find_keeper_sheet,
    read_sheet_tab,
    compute_keepers,
)
from delta_offseason_prep import build_rookie_draft_rows

# ---------------------------------------------------------------------------
# Config — update Apps Script URLs after deploying
# ---------------------------------------------------------------------------
# Single Apps Script URL — deploy apps_script_combined.js, paste URL here.
# Keepers and proposals are routed via ?action= param and body.action field.
APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbx2qVlCiJXTVzBkksauGabXjXaxuPM0AE1-6-CFn36XcL6vG6JkOSf_uU_dXNlgjoDaeQ/exec"
APPS_SCRIPT_KEEPERS_URL = APPS_SCRIPT_URL
APPS_SCRIPT_PROPOSALS_URL = APPS_SCRIPT_URL + "?action=proposals" if APPS_SCRIPT_URL else ""

PAGES_BASE_URL = "https://nachohead-mep.github.io/nfl-fantasy"

script_dir = os.path.dirname(os.path.abspath(__file__))

# Read SVG logo and prepare inline versions
_logo_svg_path = os.path.join(script_dir, '..', 'assets', 'delta-logo.svg')
with open(_logo_svg_path) as f:
    _logo_svg_full = f.read()

def _logo_inline(size):
    """Return the logo SVG inline at a given pixel size."""
    svg = _logo_svg_full.replace('width="200"', f'width="{size}"').replace('height="200"', f'height="{size}"')
    return svg

def _logo_nav():
    """Small logo for the nav bar."""
    return _logo_inline(24)

def _logo_hero():
    """Large logo for the landing page hero."""
    return _logo_inline(120)

def _logo_page_header():
    """Medium logo for sub-page headers."""
    return _logo_inline(64)


def generate_og_image(output_dir, year):
    """Generate a 1200x630 OG social preview image."""
    from PIL import Image, ImageDraw, ImageFont

    WIDTH, HEIGHT = 1200, 630
    BG = "#1a1d24"
    ACCENT = "#3b82f6"
    GREEN = "#10b981"
    WHITE = "#ffffff"
    MUTED = "#94a3b8"

    def load_font(size, bold=False):
        candidates = [
            # macOS
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Supplemental/Verdana Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Verdana.ttf",
            # Linux (CI)
            "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        for path in candidates:
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
        return ImageFont.load_default()

    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    # Accent bars
    draw.rectangle([0, 0, WIDTH, 8], fill=ACCENT)
    draw.rectangle([0, HEIGHT - 6, WIDTH, HEIGHT], fill=GREEN)

    # Decorative side accents
    draw.rectangle([0, 0, 4, HEIGHT], fill=ACCENT)
    draw.rectangle([WIDTH - 4, 0, WIDTH, HEIGHT], fill=ACCENT)

    # Draw logo natively with Pillow (delta triangle + football)
    logo_size = 180
    lx = (WIDTH - logo_size) // 2
    ly = 30

    # Delta triangle (outer)
    outer = [(lx + 90, ly + 10), (lx + 20, ly + 155), (lx + 160, ly + 155)]
    draw.polygon(outer, fill=ACCENT)
    # Inner cutout
    inner = [(lx + 90, ly + 55), (lx + 48, ly + 138), (lx + 132, ly + 138)]
    draw.polygon(inner, fill=BG)

    # Football (rotated ellipse approximation in the center)
    from PIL import Image as PILImage
    ball_w, ball_h = 90, 50
    ball_img = PILImage.new("RGBA", (ball_w * 2, ball_h * 2), (0, 0, 0, 0))
    ball_draw = ImageDraw.Draw(ball_img)
    ball_draw.ellipse([ball_w // 2, ball_h // 2, ball_w * 3 // 2, ball_h * 3 // 2],
                      fill="#A0522D", outline="#5C2D06", width=2)
    # Laces
    cx, cy = ball_w, ball_h
    ball_draw.line([(cx - 15, cy), (cx + 15, cy)], fill="white", width=3)
    for dx in [-8, -2, 4, 10]:
        ball_draw.line([(cx + dx, cy - 5), (cx + dx, cy + 5)], fill="white", width=2)
    ball_img = ball_img.rotate(35, expand=True, resample=PILImage.BICUBIC)
    # Paste football centered in delta hole
    fx = lx + 90 - ball_img.width // 2
    fy = ly + 95 - ball_img.height // 2
    img.paste(ball_img, (fx, fy), ball_img)

    # Title
    font_title = load_font(72, bold=True)
    draw.text((WIDTH // 2, 350), "DELTA LEAGUE", font=font_title, fill=WHITE, anchor="mm")

    # Year
    font_year = load_font(36, bold=True)
    draw.text((WIDTH // 2, 420), f"{year} OFFSEASON", font=font_year, fill=GREEN, anchor="mm")

    # Bottom tagline
    font_small = load_font(22)
    draw.text(
        (WIDTH // 2, 540),
        "Keeper Values  |  Rookie Draft  |  Proposals",
        font=font_small, fill=MUTED, anchor="mm"
    )

    # Horizontal rule
    draw.rectangle([200, 470, WIDTH - 200, 471], fill="#3d4450")

    images_dir = Path(output_dir) / "images"
    images_dir.mkdir(exist_ok=True)
    og_path = images_dir / "og-default.png"
    img.save(str(og_path))
    print(f"  Generated OG image: {og_path}")


def _escape(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _nav():
    return f"""<nav class="site-nav">
    <a class="site-nav-home" href="index.html">{_logo_nav()} Delta League</a>
</nav>"""


def _head(title, description="Delta Fantasy Football League"):
    og_image = f"{PAGES_BASE_URL}/images/og-default.png"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta property="og:title" content="{_escape(title)}">
    <meta property="og:description" content="{_escape(description)}">
    <meta property="og:image" content="{og_image}">
    <meta property="og:type" content="website">
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="{_escape(title)}">
    <meta name="twitter:description" content="{_escape(description)}">
    <meta name="twitter:image" content="{og_image}">
    <title>{_escape(title)}</title>
    <link rel="stylesheet" href="style.css">
</head>"""


# ============================================================================
# Landing page
# ============================================================================
def generate_landing(year, sheet_id):
    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
    sleeper_url = "https://sleeper.com/leagues"
    return f"""{_head(f"Delta League {year}")}
<body>
{_nav()}
<div class="container-narrow">
    <div class="hero">
        <div class="hero-logo">{_logo_hero()}</div>
        <div class="hero-title">DELTA LEAGUE</div>
        <div class="hero-subtitle">{year} Offseason Command Center</div>
        <div class="hero-links">
            <a class="hero-link" href="{sheet_url}" target="_blank">&#128196; Google Sheet</a>
            <a class="hero-link" href="{sleeper_url}" target="_blank">&#128247; Sleeper</a>
        </div>
    </div>
    <div class="landing-grid">
        <a class="landing-card" href="keeper-values.html">
            <div class="card-icon">&#128202;</div>
            <h2>Keeper Values</h2>
            <p>Full roster with keeper costs. Filter by team, sort by round, toggle eligible only.</p>
        </a>
        <a class="landing-card" href="keeper-selections.html">
            <div class="card-icon">&#9989;</div>
            <h2>Keeper Selections</h2>
            <p>Submit your keeper picks for {year}. Up to 3 per team.</p>
        </a>
        <a class="landing-card" href="offseason-proposals.html">
            <div class="card-icon">&#128220;</div>
            <h2>Offseason Proposals</h2>
            <p>Submit and view rule change proposals for the upcoming season.</p>
        </a>
        <a class="landing-card" href="rookie-draft.html">
            <div class="card-icon">&#127942;</div>
            <h2>Rookie Draft</h2>
            <p>Pick order, lottery odds, and traded picks for {year}.</p>
        </a>
    </div>
</div>
</body></html>"""


# ============================================================================
# Keeper Values — interactive table
# ============================================================================
def generate_keeper_values(keeper_df, year, sheet_id):
    teams = sorted(keeper_df["Team"].unique())
    team_options = "".join(f'<option value="{_escape(t)}">{_escape(t)}</option>' for t in teams)

    # Build table rows — shading/borders applied dynamically by JS
    rows_html = ""
    for _, row in keeper_df.iterrows():
        eligible = str(row["Keeper Eligible"]).upper() == "TRUE"
        cls = ' class="ineligible"' if not eligible else ""

        rows_html += f"""<tr{cls} data-team="{_escape(row['Team'])}" data-eligible="{str(eligible).lower()}">
    <td>{_escape(row['Team'])}</td>
    <td>{_escape(row['Player Name'])}</td>
    <td>{_escape(row['Position'])}</td>
    <td>{_escape(row['Drafted Round'])}</td>
    <td class="col-hide-mobile">{_escape(row['Drafted Pick'])}</td>
    <td class="col-hide-mobile">{_escape(row['Last Claim Amount'])}</td>
    <td>{_escape(row['Keeper Eligible'])}</td>
    <td>{_escape(row['Times Kept'])}</td>
    <td><strong>{_escape(row['Keeper Round'])}</strong></td>
</tr>"""

    eligible_count = len(keeper_df[keeper_df["Keeper Eligible"] == True])  # noqa
    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"

    return f"""{_head(f"Keeper Values {year}", "Full roster keeper values with filtering")}
<body>
{_nav()}
<div class="container">
    <div class="page-header">
        <div class="page-header-icon">{_logo_page_header()}</div>
        <h1>Keeper Values {year}</h1>
        <p class="subtitle">{len(keeper_df)} players &middot; {len(teams)} teams &middot; {eligible_count} eligible</p>
        <a class="sheet-link" href="{sheet_url}" target="_blank">&#128196; Open in Google Sheets</a>
    </div>

    <div class="filter-bar">
        <label for="team-filter">Team:</label>
        <select id="team-filter">
            <option value="">All Teams</option>
            {team_options}
        </select>
        <label class="toggle-label">
            <input type="checkbox" id="eligible-toggle"> Eligible only
        </label>
        <label for="pos-filter">Position:</label>
        <select id="pos-filter">
            <option value="">All</option>
            <option value="QB">QB</option>
            <option value="RB">RB</option>
            <option value="WR">WR</option>
            <option value="TE">TE</option>
            <option value="K">K</option>
            <option value="DEF">DEF</option>
        </select>
    </div>

    <table class="data-table" id="keeper-table">
        <thead><tr>
            <th data-col="0">Team <span class="sort-arrow"></span></th>
            <th data-col="1">Player <span class="sort-arrow"></span></th>
            <th data-col="2">Pos <span class="sort-arrow"></span></th>
            <th data-col="3">Drafted Rd <span class="sort-arrow"></span></th>
            <th data-col="4" class="col-hide-mobile">Pick <span class="sort-arrow"></span></th>
            <th data-col="5" class="col-hide-mobile">FAAB <span class="sort-arrow"></span></th>
            <th data-col="6">Eligible <span class="sort-arrow"></span></th>
            <th data-col="7">Kept <span class="sort-arrow"></span></th>
            <th data-col="8">Keeper Rd <span class="sort-arrow"></span></th>
        </tr></thead>
        <tbody>
{rows_html}
        </tbody>
    </table>
</div>

<script>
(function() {{
    const table = document.getElementById("keeper-table");
    const tbody = table.querySelector("tbody");
    const teamFilter = document.getElementById("team-filter");
    const eligibleToggle = document.getElementById("eligible-toggle");
    const posFilter = document.getElementById("pos-filter");

    function applyTeamStyles() {{
        const visible = Array.from(tbody.querySelectorAll("tr")).filter(r => r.style.display !== "none");
        let prevTeam = null, teamIdx = 0;
        visible.forEach(function(row, i) {{
            row.classList.remove("team-shade", "team-border");
            const t = row.dataset.team;
            if (t !== prevTeam) {{ prevTeam = t; teamIdx++; }}
            if (teamIdx % 2 === 1) row.classList.add("team-shade");
            // Add border on last row of each team group
            const nextRow = visible[i + 1];
            if (!nextRow || nextRow.dataset.team !== t) row.classList.add("team-border");
        }});
    }}

    function applyFilters() {{
        const team = teamFilter.value;
        const eligOnly = eligibleToggle.checked;
        const pos = posFilter.value;
        tbody.querySelectorAll("tr").forEach(function(row) {{
            let show = true;
            if (team && row.dataset.team !== team) show = false;
            if (eligOnly && row.dataset.eligible !== "true") show = false;
            if (pos && row.children[2].textContent !== pos) show = false;
            row.style.display = show ? "" : "none";
        }});
        applyTeamStyles();
    }}
    teamFilter.addEventListener("change", applyFilters);
    eligibleToggle.addEventListener("change", applyFilters);
    posFilter.addEventListener("change", applyFilters);

    // Sortable columns
    let sortCol = -1, sortAsc = true;
    table.querySelectorAll("thead th").forEach(function(th) {{
        th.addEventListener("click", function() {{
            const col = parseInt(th.dataset.col);
            if (sortCol === col) {{ sortAsc = !sortAsc; }}
            else {{ sortCol = col; sortAsc = true; }}

            const rows = Array.from(tbody.querySelectorAll("tr"));
            rows.sort(function(a, b) {{
                let va = a.children[col].textContent.trim();
                let vb = b.children[col].textContent.trim();
                // Numeric sort
                const na = parseFloat(va), nb = parseFloat(vb);
                if (!isNaN(na) && !isNaN(nb)) {{
                    return sortAsc ? na - nb : nb - na;
                }}
                // Push non-numeric (UNDRAFTED, NOT ELIGIBLE, NO CLAIMS) to bottom
                if (isNaN(na) && !isNaN(nb)) return 1;
                if (!isNaN(na) && isNaN(nb)) return -1;
                return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
            }});
            rows.forEach(function(r) {{ tbody.appendChild(r); }});

            // Update arrows
            table.querySelectorAll(".sort-arrow").forEach(function(s) {{ s.textContent = ""; }});
            th.querySelector(".sort-arrow").textContent = sortAsc ? " \\u25B2" : " \\u25BC";
            applyTeamStyles();
        }});
    }});

    // Initial styling
    applyTeamStyles();
}})();
</script>
</body></html>"""


# ============================================================================
# Keeper Selections — form page
# ============================================================================
def generate_keeper_selections(keeper_df, year, sheet_id):
    # Build eligible players by team as JSON for client-side dropdowns
    eligible = keeper_df[keeper_df["Keeper Eligible"] == True]  # noqa
    by_team = {}
    for _, row in eligible.iterrows():
        t = row["Team"]
        if t not in by_team:
            by_team[t] = []
        by_team[t].append({
            "name": row["Player Name"],
            "pos": row["Position"],
            "round": str(row["Keeper Round"]),
        })

    import json
    eligible_json = json.dumps(by_team)
    teams_json = json.dumps(sorted(by_team.keys()))
    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"

    return f"""{_head(f"Keeper Selections {year}", "Submit your keeper picks")}
<body>
{_nav()}
<div class="container-narrow">
    <div class="page-header">
        <div class="page-header-icon">{_logo_page_header()}</div>
        <h1>Keeper Selections {year}</h1>
        <p class="subtitle">Select up to 3 keepers for your team</p>
        <a class="sheet-link" href="{sheet_url}" target="_blank">&#128196; Open in Google Sheets</a>
    </div>

    <div class="section-card">
        <div class="form-group">
            <label for="team-select">Your Team</label>
            <select id="team-select"><option value="">Select your team...</option></select>
        </div>
        <div id="keeper-form" style="display:none">
            <div class="form-group">
                <label for="k1">Keeper 1</label>
                <select id="k1"><option value="">-- none --</option></select>
            </div>
            <div class="form-group">
                <label for="k2">Keeper 2</label>
                <select id="k2"><option value="">-- none --</option></select>
            </div>
            <div class="form-group">
                <label for="k3">Keeper 3</label>
                <select id="k3"><option value="">-- none --</option></select>
            </div>
            <button class="btn" id="save-btn">Save Keepers</button>
            <span id="save-status" style="margin-left:12px; font-size:0.85rem;"></span>
        </div>
    </div>

    <div id="all-selections" class="section-card" style="display:none">
        <h2>Current Selections</h2>
        <div id="selections-list"></div>
    </div>
</div>

<script>
(function() {{
    const API = "{APPS_SCRIPT_KEEPERS_URL}";
    const eligibleByTeam = {eligible_json};
    const teams = {teams_json};
    const teamSelect = document.getElementById("team-select");
    const keeperForm = document.getElementById("keeper-form");
    const saveBtn = document.getElementById("save-btn");
    const saveStatus = document.getElementById("save-status");

    teams.forEach(function(t) {{
        const opt = document.createElement("option");
        opt.value = t; opt.textContent = t;
        teamSelect.appendChild(opt);
    }});

    function populateDropdowns(team) {{
        const players = eligibleByTeam[team] || [];
        ["k1","k2","k3"].forEach(function(id) {{
            const sel = document.getElementById(id);
            const cur = sel.value;
            sel.innerHTML = '<option value="">-- none --</option>';
            players.forEach(function(p) {{
                const opt = document.createElement("option");
                opt.value = p.name;
                opt.textContent = p.name + " (" + p.pos + ", Rd " + p.round + ")";
                sel.appendChild(opt);
            }});
            sel.value = cur;
        }});
    }}

    teamSelect.addEventListener("change", function() {{
        const team = teamSelect.value;
        if (!team) {{ keeperForm.style.display = "none"; return; }}
        keeperForm.style.display = "";
        populateDropdowns(team);
        // Load current selections from Apps Script
        if (API) {{
            fetch(API).then(r => r.json()).then(function(data) {{
                const sel = (data.selections || []).find(s => s.team === team);
                if (sel) {{
                    document.getElementById("k1").value = sel.keeper_1 || "";
                    document.getElementById("k2").value = sel.keeper_2 || "";
                    document.getElementById("k3").value = sel.keeper_3 || "";
                }}
            }}).catch(function() {{}});
        }}
    }});

    saveBtn.addEventListener("click", function() {{
        const team = teamSelect.value;
        if (!team || !API) return;
        saveBtn.disabled = true;
        saveStatus.textContent = "Saving...";
        const payload = {{
            manager: team,
            keeper1: document.getElementById("k1").value,
            keeper2: document.getElementById("k2").value,
            keeper3: document.getElementById("k3").value
        }};
        fetch(API, {{
            method: "POST",
            headers: {{"Content-Type": "text/plain"}},
            body: JSON.stringify(payload),
            mode: "no-cors"
        }}).then(function() {{
            saveStatus.textContent = "\\u2705 Saved!";
            saveBtn.disabled = false;
        }}).catch(function() {{
            saveStatus.textContent = "\\u274C Error saving";
            saveBtn.disabled = false;
        }});
    }});

    // Load all current selections
    if (API) {{
        fetch(API).then(r => r.json()).then(function(data) {{
            const container = document.getElementById("selections-list");
            const sec = document.getElementById("all-selections");
            if (!data.selections || data.selections.length === 0) return;
            sec.style.display = "";
            let html = "";
            data.selections.forEach(function(s) {{
                const keepers = [s.keeper_1, s.keeper_2, s.keeper_3].filter(Boolean);
                html += '<div class="current-selections" style="margin-bottom:8px">';
                html += '<h3>' + s.team + '</h3>';
                if (keepers.length === 0) {{
                    html += '<div class="sel-empty">No selections yet</div>';
                }} else {{
                    keepers.forEach(function(k) {{
                        html += '<div class="sel-item">\\u2022 ' + k + '</div>';
                    }});
                }}
                html += '</div>';
            }});
            container.innerHTML = html;
        }}).catch(function() {{}});
    }}
}})();
</script>
</body></html>"""


# ============================================================================
# Offseason Proposals — form page
# ============================================================================
def generate_proposals(year, sheet_id):
    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"

    return f"""{_head(f"Offseason Proposals {year}", "Submit and view rule change proposals")}
<body>
{_nav()}
<div class="container-narrow">
    <div class="page-header">
        <div class="page-header-icon">{_logo_page_header()}</div>
        <h1>Offseason Proposals {year}</h1>
        <p class="subtitle">Submit and discuss rule changes</p>
        <a class="sheet-link" href="{sheet_url}" target="_blank">&#128196; Open in Google Sheets</a>
    </div>

    <div class="section-card">
        <h2>Submit a Proposal</h2>
        <div class="form-group">
            <label for="prop-desc">Proposal Description</label>
            <textarea id="prop-desc" placeholder="Describe your rule change proposal..."></textarea>
        </div>
        <div class="form-group">
            <label for="prop-pros">Pros (optional)</label>
            <input id="prop-pros" placeholder="Arguments in favor">
        </div>
        <div class="form-group">
            <label for="prop-cons">Cons (optional)</label>
            <input id="prop-cons" placeholder="Arguments against">
        </div>
        <button class="btn" id="submit-btn">Submit Proposal</button>
        <span id="submit-status" style="margin-left:12px; font-size:0.85rem;"></span>
    </div>

    <div class="section-card">
        <h2>Current Proposals</h2>
        <div id="proposals-list">
            <div class="loading">Loading proposals&hellip;</div>
        </div>
    </div>
</div>

<script>
(function() {{
    const API = "{APPS_SCRIPT_PROPOSALS_URL}";
    const list = document.getElementById("proposals-list");
    const submitBtn = document.getElementById("submit-btn");
    const submitStatus = document.getElementById("submit-status");

    function loadProposals() {{
        if (!API) {{ list.innerHTML = '<div class="error">Apps Script URL not configured</div>'; return; }}
        fetch(API).then(r => r.json()).then(function(data) {{
            if (!data.proposals || data.proposals.length === 0) {{
                list.innerHTML = '<p style="color:var(--text-muted)">No proposals yet. Be the first!</p>';
                return;
            }}
            let html = "";
            data.proposals.forEach(function(p, i) {{
                html += '<div class="proposal-card">';
                html += '<div class="proposal-num">Proposal #' + (i + 1) + '</div>';
                html += '<div class="proposal-text">' + (p.description || "") + '</div>';
                if (p.pros) html += '<div class="proposal-meta" style="color:var(--accent-green)">Pros: ' + p.pros + '</div>';
                if (p.cons) html += '<div class="proposal-meta" style="color:var(--accent-red)">Cons: ' + p.cons + '</div>';
                html += '</div>';
            }});
            list.innerHTML = html;
        }}).catch(function() {{
            list.innerHTML = '<div class="error">Failed to load proposals</div>';
        }});
    }}

    submitBtn.addEventListener("click", function() {{
        const desc = document.getElementById("prop-desc").value.trim();
        if (!desc || !API) return;
        submitBtn.disabled = true;
        submitStatus.textContent = "Submitting...";
        fetch(API, {{
            method: "POST",
            headers: {{"Content-Type": "text/plain"}},
            body: JSON.stringify({{
                action: "proposals",
                description: desc,
                pros: document.getElementById("prop-pros").value.trim(),
                cons: document.getElementById("prop-cons").value.trim()
            }}),
            mode: "no-cors"
        }}).then(function() {{
            submitStatus.textContent = "\\u2705 Submitted!";
            submitBtn.disabled = false;
            document.getElementById("prop-desc").value = "";
            document.getElementById("prop-pros").value = "";
            document.getElementById("prop-cons").value = "";
            setTimeout(loadProposals, 1500);
        }}).catch(function() {{
            submitStatus.textContent = "\\u274C Error";
            submitBtn.disabled = false;
        }});
    }});

    loadProposals();
}})();
</script>
</body></html>"""


# ============================================================================
# Rookie Draft — read-only
# ============================================================================
def generate_rookie_draft(pick_rows, year, sheet_id):
    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"

    picks_html = ""
    lottery_html = ""
    trades_html = ""
    section = "picks"

    for row in pick_rows[1:]:  # skip header
        pick, team, player = (row + ["", "", ""])[:3]

        if team == "Lottery Odds":
            section = "lottery"
            continue
        if team == "Trade Notes" or pick == "Year":
            section = "trades"
            continue
        if not pick and not team and not player:
            continue

        if section == "picks":
            is_lottery = "LOTTERY" in str(team)
            is_traded = "(from" in str(team)
            cls = ""
            if is_lottery:
                cls = ' class="lottery"'
            elif is_traded:
                cls = ' class="pick-traded"'
            picks_html += f"<tr{cls}><td>{_escape(pick)}</td><td>{_escape(team)}</td><td>{_escape(player) or '—'}</td></tr>\n"
        elif section == "lottery":
            picks_html  # lottery info is in the main table already
            lottery_html += f"<tr><td>{_escape(team)}</td><td>{_escape(player)}</td></tr>\n"
        elif section == "trades":
            if pick or team:
                trades_html += f"<tr><td>{_escape(pick)}</td><td>{_escape(team)}</td></tr>\n"

    return f"""{_head(f"Rookie Draft {year}", "Pick order, lottery odds, and traded picks")}
<body>
{_nav()}
<div class="container-narrow">
    <div class="page-header">
        <div class="page-header-icon">{_logo_page_header()}</div>
        <h1>Rookie Draft {year}</h1>
        <p class="subtitle">Pick order &middot; Lottery odds &middot; Trade notes</p>
        <a class="sheet-link" href="{sheet_url}" target="_blank">&#128196; Open in Google Sheets</a>
    </div>

    <div class="section-card">
        <h2>Pick Order</h2>
        <table class="draft-table">
            <thead><tr><th>Pick</th><th>Team</th><th>Player</th></tr></thead>
            <tbody>{picks_html}</tbody>
        </table>
    </div>

    <div class="section-card">
        <h2>Lottery Odds</h2>
        <table class="draft-table">
            <thead><tr><th>Position</th><th>Range</th></tr></thead>
            <tbody>{lottery_html}</tbody>
        </table>
    </div>

    <div class="section-card">
        <h2>Trade Notes</h2>
        <table class="draft-table">
            <thead><tr><th>Year</th><th>Note</th></tr></thead>
            <tbody>{trades_html}</tbody>
        </table>
    </div>
</div>
</body></html>"""


# ============================================================================
# Main
# ============================================================================
def generate_all_pages(keeper_df, pick_rows, year, sheet_id, output_dir):
    """Generate all pages and CSS to the output directory."""
    os.makedirs(output_dir, exist_ok=True)

    # CSS
    css_src = os.path.join(script_dir, "offseason_style.css")
    shutil.copy2(css_src, os.path.join(output_dir, "style.css"))

    # OG image
    generate_og_image(output_dir, year)

    pages = {
        "index.html": generate_landing(year, sheet_id),
        "keeper-values.html": generate_keeper_values(keeper_df, year, sheet_id),
        "keeper-selections.html": generate_keeper_selections(keeper_df, year, sheet_id),
        "offseason-proposals.html": generate_proposals(year, sheet_id),
        "rookie-draft.html": generate_rookie_draft(pick_rows, year, sheet_id),
    }

    for filename, html in pages.items():
        path = os.path.join(output_dir, filename)
        with open(path, "w") as f:
            f.write(html)
        print(f"  Generated {filename}")


def main():
    parser = argparse.ArgumentParser(description="Generate Delta League offseason pages")
    parser.add_argument("--output", default="pages", help="Output directory")
    parser.add_argument("--year", type=int, default=datetime.datetime.now().year)
    args = parser.parse_args()

    nfl_season = args.year - 1
    print(f"Generating offseason pages for {args.year}...")

    sheets_svc, drive_svc = init_google_services()
    keeper_df, league_id, prev_sheet_id, rid_to_name, trade_notes = compute_keepers(
        sheets_svc, drive_svc, nfl_season
    )

    # Find current year's sheet ID for links
    from delta_keeper_api import find_or_create_sheet
    sheet_id = find_or_create_sheet(drive_svc, prev_sheet_id, args.year)

    # Read rookie draft data from the current year's sheet (includes manual trade edits)
    from delta_keeper_api import read_sheet_tab
    rookie_tab = read_sheet_tab(sheets_svc, sheet_id, f"Rookie Draft {args.year}")
    pick_rows = [["Pick", "Team", "Player"]]
    for _, row in rookie_tab.iterrows():
        pick_rows.append([str(row.get('pick', '')), str(row.get('team', '')), str(row.get('player', ''))])

    generate_all_pages(keeper_df, pick_rows, args.year, sheet_id, args.output)
    print(f"Done! Pages written to {args.output}/")


if __name__ == "__main__":
    main()
