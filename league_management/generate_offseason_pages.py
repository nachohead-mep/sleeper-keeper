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
import sys
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
# Apps Script URL — set via environment variable (kept secret for public repos).
# Deploy apps_script_combined.js and set APPS_SCRIPT_URL in env or GitHub Secrets.
APPS_SCRIPT_URL = os.environ.get("APPS_SCRIPT_URL", "")
APPS_SCRIPT_KEEPERS_URL = APPS_SCRIPT_URL
APPS_SCRIPT_PROPOSALS_URL = APPS_SCRIPT_URL + "?action=proposals" if APPS_SCRIPT_URL else ""

PAGES_BASE_URL = os.environ.get("PAGES_BASE_URL", "https://nachohead-mep.github.io/sleeper-keeper")

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

    # Render SVG logo
    logo_path = os.path.join(script_dir, '..', 'assets', 'delta-logo.svg')
    try:
        import cairosvg
        from io import BytesIO
        logo_png = cairosvg.svg2png(url=logo_path, output_width=180, output_height=180,
                                     background_color=BG)
        logo_img = Image.open(BytesIO(logo_png)).convert("RGBA")
    except (ImportError, OSError):
        # Fallback: draw simple delta + football with Pillow
        logo_img = Image.new("RGBA", (180, 180), (0, 0, 0, 0))
        ldraw = ImageDraw.Draw(logo_img)
        ldraw.polygon([(90, 10), (20, 155), (160, 155)], fill=ACCENT)
        ldraw.polygon([(90, 55), (48, 138), (132, 138)], fill=BG)
        ball_layer = Image.new("RGBA", (90, 50), (0, 0, 0, 0))
        bdraw = ImageDraw.Draw(ball_layer)
        bdraw.ellipse([0, 0, 89, 49], fill="#A0522D", outline="#5C2D06", width=2)
        bdraw.line([(30, 25), (60, 25)], fill="white", width=3)
        for dx in [37, 43, 49, 55]:
            bdraw.line([(dx, 20), (dx, 30)], fill="white", width=2)
        ball_layer = ball_layer.rotate(35, expand=True, resample=Image.BICUBIC)
        bx = 90 - ball_layer.width // 2
        by = 95 - ball_layer.height // 2
        logo_img.paste(ball_layer, (bx, by), ball_layer)

    lx = (WIDTH - 180) // 2
    ly = 30
    img.paste(logo_img, (lx, ly), logo_img)

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
        <a class="landing-card" href="rookie-lottery.html">
            <div class="card-icon">&#9917;</div>
            <h2>The Draw</h2>
            <p>World Cup&ndash;style weighted lottery for picks 2&ndash;6. Run it live and verify the odds.</p>
        </a>
        <a class="landing-card" href="rookie-values.html">
            <div class="card-icon">&#128202;</div>
            <h2>Rookie Values</h2>
            <p>Incoming rookie class &mdash; consensus ADP and the draft round each rookie is worth.</p>
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
        <a class="sheet-link" href="rookie-lottery.html">&#127942; Run the Draft Lottery</a>
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
# Rookie Lottery — provably-fair animated draw
# ============================================================================
LOTTERY_COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#a855f7",
                  "#06b6d4", "#ec4899", "#84cc16"]

# World Cup theme: map each lottery entrant (Sleeper name) to a 2-letter country
# code so their flag shows in the draw — matching the deltaworldcup draft site.
# Fill these in to match each manager's nation. Unmapped names just show no flag.
LOTTERY_FLAGS = {
    # "DannyN": "fr",
    # "zachmassey": "br",
    # "jpersily": "de",
    # "jaw7475": "ar",
    # "JoshWasserman": "pt",
}


def _parse_lottery_participants(pick_rows):
    """Extract lottery entrants (name + weight) from the rookie-draft rows.

    The lottery section rows look like:
        ["", "Consolation Runner Up (DannyN)", "1-30"]
    where the parenthetical is the team name and the range width is the weight.
    """
    import re

    participants = []
    section = None
    for row in pick_rows[1:]:
        pick, team, player = (list(row) + ["", "", ""])[:3]
        if team == "Lottery Odds":
            section = "lottery"
            continue
        if team == "Trade Notes" or pick == "Year":
            section = "trades"
            continue
        if section != "lottery" or not team:
            continue

        m = re.search(r"\(([^)]*)\)\s*$", team)
        name = m.group(1).strip() if m else team.strip()
        label = re.sub(r"\s*\([^)]*\)\s*$", "", team).strip()
        parts = str(player).strip().split("-")
        try:
            lo, hi = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            continue
        participants.append({
            "name": name, "label": label,
            "lo": lo, "hi": hi, "weight": hi - lo + 1,
        })
    return participants


def _parse_all_picks(pick_rows):
    """Return the full draft order (picks 1..N) from the rookie-draft rows.

    Lottery picks (team contains 'LOTTERY') are flagged so the page can show them
    as pending slots pre-draw and fill them in as the lottery resolves.
    """
    picks = []
    for row in pick_rows[1:]:
        pick, team, player = (list(row) + ["", "", ""])[:3]
        if team in ("Lottery Odds", "Trade Notes") or pick == "Year":
            break  # reached the reference sections below the pick list
        if not str(pick).strip() and not str(team).strip():
            continue
        picks.append({"pick": str(pick).strip(), "team": str(team).strip(),
                      "lottery": "LOTTERY" in str(team)})
    return picks


def _owner_handle(team_str):
    """Strip an acquired-pick note to the owning manager's handle.

    'JoshWasserman (from spencerrubin7)' -> 'JoshWasserman'; 'Gohrdo' -> 'Gohrdo'.
    """
    import re
    return re.sub(r"\s*\(from[^)]*\)\s*$", "", str(team_str)).strip()


def _available_photos():
    """Set of manager handles that have a headshot in assets/photos/."""
    photos_dir = os.path.join(script_dir, "..", "assets", "photos")
    if not os.path.isdir(photos_dir):
        return set()
    return {os.path.splitext(f)[0] for f in os.listdir(photos_dir)
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))}


def _photo_url(handle, available):
    return f"photos/{handle}.png" if handle in available else ""


# Plain (non-f) string: all { } and ${ } are literal JS. Only __TEAMS__ is replaced.
LOTTERY_JS = r"""
const TEAMS = __TEAMS__;
const ALL_PICKS = __PICKS__;  // full 1-N order; lottery slots get filled by the draw

// ── Deterministic PRNG (seed string -> reproducible stream) ──────────
function cyrb53(str, seed) {
  let h1 = 0xdeadbeef ^ (seed || 0), h2 = 0x41c6ce57 ^ (seed || 0);
  for (let i = 0; i < str.length; i++) {
    const ch = str.charCodeAt(i);
    h1 = Math.imul(h1 ^ ch, 2654435761);
    h2 = Math.imul(h2 ^ ch, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507); h1 ^= Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507); h2 ^= Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return (h1 >>> 0);
}
function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function rngFromSeed(s) { return mulberry32(cyrb53(s)); }

function teamForRoll(roll) {
  for (let i = 0; i < TEAMS.length; i++)
    if (roll >= TEAMS[i].lo && roll <= TEAMS[i].hi) return i;
  return -1;
}

// Sequential weighted draw without replacement, via repeated 1-100 rolls
// (re-roll on an already-drafted team). Returns the full ordered result plus
// a log of every roll so the animation can replay it faithfully.
function runLottery(rng) {
  const taken = new Set();
  const order = [];     // order[k] -> overall pick (k + 2)
  const log = [];
  while (order.length < TEAMS.length - 1) {
    const roll = 1 + Math.floor(rng() * 100);
    const ti = teamForRoll(roll);
    const skipped = taken.has(ti);
    if (!skipped) { taken.add(ti); order.push(ti); }
    log.push({ roll: roll, teamIndex: ti, skipped: skipped, pick: skipped ? null : order.length + 1 });
  }
  const last = TEAMS.findIndex((_, i) => !taken.has(i));
  order.push(last);
  log.push({ roll: null, teamIndex: last, skipped: false, pick: order.length + 1, auto: true });
  return { order: order, log: log };
}

// ── DOM helpers ─────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let animating = false;

function flagHtml(t) {
  return t.cc ? '<img class="flag" src="https://flagcdn.com/h20/' + t.cc + '.png" alt=""> ' : '';
}
function avatarHtml(photo, cls) {
  return photo ? '<img class="avatar ' + (cls || "") + '" src="' + photo + '" alt="" loading="lazy"> ' : '';
}

function buildBar() {
  const bar = $("oddsBar");
  bar.innerHTML = "";
  TEAMS.forEach((t, i) => {
    const seg = document.createElement("div");
    seg.className = "odds-seg"; seg.id = "seg-" + i;
    seg.style.flexGrow = t.weight; seg.style.background = t.color;
    seg.innerHTML = '<span class="seg-name">' + flagHtml(t) + t.name + '</span>' +
                    '<span class="seg-pct">' + t.weight + ' balls &middot; ' + t.lo + '-' + t.hi + '</span>';
    bar.appendChild(seg);
  });
  const ptr = document.createElement("div");
  ptr.className = "odds-pointer"; ptr.id = "oddsPointer"; ptr.style.left = "0%";
  bar.appendChild(ptr);
}
function movePointer(roll) { $("oddsPointer").style.left = (roll - 0.5) + "%"; }
function dimSegments(on) {
  TEAMS.forEach((_, i) => $("seg-" + i).classList.toggle("dim", on));
}
function hotSegment(i) {
  TEAMS.forEach((_, j) => $("seg-" + j).classList.toggle("hot", j === i));
}

function buildBoard() {
  const b = $("board");
  b.innerHTML = "";
  for (let p = 2; p <= TEAMS.length + 1; p++) {
    const slot = document.createElement("div");
    slot.className = "board-slot"; slot.id = "slot-" + p;
    slot.innerHTML = '<div class="slot-pick">Pick ' + p + '</div>' +
                     '<div class="slot-team">&mdash;</div>' +
                     '<div class="slot-roll">&nbsp;</div>';
    b.appendChild(slot);
  }
}
function fillSlot(pick, teamIndex, roll) {
  const slot = $("slot-" + pick);
  const t = TEAMS[teamIndex];
  slot.classList.add("filled", "reveal");
  slot.querySelector(".slot-team").innerHTML =
    avatarHtml(t.photo, "av-md") + flagHtml(t) + t.name;
  slot.querySelector(".slot-roll").textContent = roll === null ? "last ball remaining" : "ball " + roll;
  slot.addEventListener("animationend", () => slot.classList.remove("reveal"), { once: true });
}

// Full draft order (picks 1..N). Lottery slots start "pending" and fill as drawn.
function buildFullOrder() {
  const el = $("fullOrder");
  el.innerHTML = "";
  ALL_PICKS.forEach((p) => {
    const row = document.createElement("div");
    row.className = "order-row" + (p.lottery ? " is-lottery" : "") + (p.from_handle ? " is-traded-row" : "");
    if (p.lottery) row.id = "full-" + p.pick;
    let team;
    if (p.lottery) {
      team = '<span class="order-pending">&#127922; lottery slot <span class="lottery-tag">to be drawn</span></span>';
    } else if (p.from_handle) {
      // Traded pick: original owner &rarr; current owner, colour-coded.
      team = avatarHtml(p.from_photo, "av-sm av-from") +
             '<span class="trade-arrow">&rarr;</span>' +
             avatarHtml(p.photo, "av-sm av-owner") +
             '<span class="trade-text">' + escapeHtml(p.owner) +
             ' <span class="trade-from">traded from ' + escapeHtml(p.from_handle) + '</span></span>';
    } else {
      team = avatarHtml(p.photo, "av-sm") + escapeHtml(p.team);
    }
    row.innerHTML = '<span class="order-pick">' + p.pick + '</span>' +
                    '<span class="order-team' + (p.from_handle ? ' is-traded' : '') + '">' + team + '</span>';
    el.appendChild(row);
  });
}
function setFullOrder(pick, teamIndex) {
  const row = $("full-" + pick);
  if (!row) return;
  const t = TEAMS[teamIndex];
  row.classList.add("filled", "reveal");
  row.querySelector(".order-team").innerHTML =
    avatarHtml(t.photo, "av-sm") + flagHtml(t) + t.name;
  row.addEventListener("animationend", () => row.classList.remove("reveal"), { once: true });
}
function escapeHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function animateRoll(target, dur) {
  return new Promise((resolve) => {
    const el = $("rollNum"), ball = $("drawBall");
    ball.classList.add("rolling");
    const start = performance.now();
    let last = 0;
    function frame(now) {
      const p = Math.min(1, (now - start) / dur);
      if (p < 0.88) {
        // slow the visible flicker so the numbers are readable, not a blur
        if (now - last > 70) { const r = 1 + Math.floor(Math.random() * 100); el.textContent = r; movePointer(r); last = now; }
        requestAnimationFrame(frame);
      } else {
        el.textContent = target; movePointer(target); ball.classList.remove("rolling"); resolve();
      }
    }
    requestAnimationFrame(frame);
  });
}

function buildPermalink(seedStr) {
  // Locked link, but no auto-start — the recipient presses play when ready.
  return location.origin + location.pathname + "?seed=" + encodeURIComponent(seedStr) + "&lock=1";
}

let seedLocked = false;
function lockSeed(s) {
  seedLocked = true;
  $("seed").value = s;
  $("seed").readOnly = true;
  $("seed").classList.add("locked");
  $("runBtn").textContent = "Watch the Official Draw";
  $("rollStatus").innerHTML = 'Press <strong>Watch the Official Draw</strong> when ready.';
  $("officialBanner").classList.add("show");
  $("officialSeed").textContent = s;
}
function showPractice() {
  $("practiceBanner").classList.add("show");
}

// How far the drawn number sits from a team's ball-range (0 if inside).
function rangeDistance(roll, t) {
  if (roll < t.lo) return t.lo - roll;
  if (roll > t.hi) return roll - t.hi;
  return 0;
}

// Penalty shootout for one pick. The nation the ball landed on scores; the
// others are ranked by how close their range was to the number — closest is
// saved, next clangs off the crossbar, the rest sky it. Purely cosmetic: the
// winner is already decided by the provably-fair draw above.
// Commentary pools per outcome — chosen deterministically from the draw so a
// shared/locked link shows the same call-outs for everyone.
const SHOT = {
  score: ["top corner &mdash; buried it!", "roofs it, no chance!", "slots it bottom corner &mdash; GOAL!",
          "sends the keeper the wrong way &mdash; scores!", "cool as you like &mdash; buried!",
          "rifles it home!", "tucked away, top bins!"],
  saved: ["tipped off the keeper's fingertips &mdash; what a save!", "huge save &mdash; denied!",
          "the keeper guesses right and stops it!", "stoned by the keeper!", "parried away &mdash; denied!",
          "full stretch &mdash; what a stop!"],
  crossbar: ["off the crossbar!", "rattles the woodwork and out!", "off the post &mdash; so close!",
             "clangs the bar &mdash; no goal!", "inches away &mdash; off the frame!"],
  miss: ["way off &mdash; into the stands!", "skies it over the bar", "drags it wide of the post",
         "blazes it over the top", "scuffs it well wide", "slips and slices it miles wide",
         "wide &mdash; never close"],
};
const REVEAL_ORDER = { miss: 0, crossbar: 1, saved: 2, score: 3 };

function shootout(remaining, winnerIdx, roll, instant) {
  const pitch = $("pitch");
  pitch.style.display = "block";
  pitch.innerHTML = '<div class="goal-banner">&#129349; Penalty shootout for the pick</div>';

  // Assign each kicker an outcome.
  const outcome = {};
  outcome[winnerIdx] = "score";
  remaining.filter((ti) => ti !== winnerIdx)
    .sort((a, b) => rangeDistance(roll, TEAMS[a]) - rangeDistance(roll, TEAMS[b]))
    .forEach((ti, idx) => { outcome[ti] = idx === 0 ? "saved" : idx === 1 ? "crossbar" : "miss"; });

  const rows = remaining.map((ti) => {
    const t = TEAMS[ti];
    const row = document.createElement("div");
    row.className = "kicker";
    row.innerHTML =
      '<span class="kicker-name">' + avatarHtml(t.photo, "av-md") + flagHtml(t) + t.name + '</span>' +
      '<span class="lane"><span class="ball">&#9917;</span></span>' +
      '<span class="keeper">&#129508;</span>' +
      '<span class="net">&#129349;</span>' +
      '<span class="kicker-result"></span>';
    pitch.appendChild(row);
    return { ti: ti, row: row };
  });
  const settle = ({ ti, row }) => {
    const oc = outcome[ti];
    row.classList.add(oc);
    const pool = SHOT[oc];
    const idx = (((roll == null ? 7 : roll) + ti * 31) % pool.length + pool.length) % pool.length;
    row.querySelector(".kicker-result").innerHTML = pool[idx];
  };
  if (instant) { rows.forEach(settle); return Promise.resolve(); }

  // Reveal misses first, building up to the goal.
  const order = rows.slice().sort((a, b) => REVEAL_ORDER[outcome[a.ti]] - REVEAL_ORDER[outcome[b.ti]]);
  void pitch.offsetWidth; // force reflow so CSS transitions/animations fire
  return new Promise((resolve) => {
    order.forEach((r, i) => setTimeout(() => settle(r), 400 + i * 700));
    setTimeout(resolve, 400 + order.length * 700 + 1300);
  });
}

async function play(seedStr, instant) {
  if (animating) return;
  animating = true;
  $("runBtn").disabled = true;
  try { $("rollStage").scrollIntoView({ behavior: "smooth", block: "start" }); } catch (e) {}
  $("seedShown").textContent = seedStr;
  $("permaUrl").value = buildPermalink(seedStr);
  $("permaBox").style.display = "flex";
  buildBoard(); buildFullOrder(); dimSegments(false); hotSegment(-1);
  $("pitch").style.display = "none"; $("pitch").innerHTML = "";

  const placed = new Set();
  const { log } = runLottery(rngFromSeed(seedStr));
  for (const ev of log) {
    if (ev.roll !== null) {
      // The ball + number always show; movePointer just updates the (maybe-hidden) odds bar.
      if (instant) { $("rollNum").textContent = ev.roll; movePointer(ev.roll); }
      else await animateRoll(ev.roll, 1700);
    }
    if (ev.skipped) {
      // Landed on a team already out of the pot — don't re-highlight them.
      $("rollStatus").innerHTML = '<span style="color:var(--accent-yellow)">Ball ' + ev.roll +
        ' &rarr; ' + TEAMS[ev.teamIndex].name + ' already drawn &mdash; back in the pot</span>';
      if (!instant) await sleep(950);
    } else {
      const remaining = TEAMS.map((_, i) => i).filter((i) => !placed.has(i));
      // Don't name the winner yet — let the shootout's goal be the reveal.
      $("rollStatus").innerHTML = ev.auto
        ? 'The final kicker steps up for Pick ' + ev.pick + '&hellip;'
        : 'Ball ' + ev.roll + ' &mdash; the kickers line up for Pick ' + ev.pick + '&hellip;';
      await shootout(remaining, ev.teamIndex, ev.roll, instant);
      placed.add(ev.teamIndex);
      hotSegment(ev.teamIndex); // reveal on the picker only after the goal
      fillSlot(ev.pick, ev.teamIndex, ev.roll);
      setFullOrder(ev.pick, ev.teamIndex);
      $("rollStatus").innerHTML = '&#9917; Pick ' + ev.pick + ' &rarr; <strong>' + TEAMS[ev.teamIndex].name + '</strong> scores!';
      if (!instant) await sleep(900);
      $("seg-" + ev.teamIndex).classList.add("dim");
      hotSegment(-1); // clear the highlight now that they're out of the pool
    }
  }
  hotSegment(-1);
  $("pitch").style.display = "none";
  $("rollStatus").innerHTML = '&#127942; <span style="color:var(--accent-green)">The draw is complete &mdash; reproducible from the seed above.</span>';
  $("runBtn").disabled = false;
  $("runBtn").textContent = seedLocked ? "Watch Again" : "Draw Again";
  animating = false;
}

// ── Monte Carlo fairness check ──────────────────────────────────────
function runSimulation() {
  const N = 200000;
  const counts = TEAMS.map(() => new Array(TEAMS.length).fill(0));
  for (let n = 0; n < N; n++) {
    const { order } = runLottery(Math.random);
    order.forEach((ti, slot) => { counts[ti][slot]++; });
  }
  let head = '<tr><th class="team-cell">Team</th><th>Target<br>(Pick 2)</th>';
  for (let p = 2; p <= TEAMS.length + 1; p++) head += '<th>Pick ' + p + '</th>';
  head += '</tr>';
  let body = "";
  TEAMS.forEach((t, i) => {
    const sim2 = 100 * counts[i][0] / N;
    const good = Math.abs(sim2 - t.weight) < 0.6;
    body += '<tr><td class="team-cell"><span class="slot-dot" style="background:' + t.color +
            '"></span>' + flagHtml(t) + t.name + '</td>';
    body += '<td class="target">' + t.weight + '%</td>';
    counts[i].forEach((c, slot) => {
      const pct = (100 * c / N).toFixed(1);
      const cls = slot === 0 ? (good ? "match-good" : "") : "";
      body += '<td class="' + cls + '">' + pct + '%</td>';
    });
    body += '</tr>';
  });
  $("simTable").innerHTML = head + body;
  $("simNote").textContent = "Each team's Pick-2 rate (green) matches its target odds within rounding — the " +
    "draw respects the weights. Run again for a fresh " + N.toLocaleString() + "-draw sample.";
}

// ── Wiring ──────────────────────────────────────────────────────────
function randomSeed() {
  return "delta-" + Math.random().toString(36).slice(2, 8) + Math.random().toString(36).slice(2, 6);
}
buildBar(); buildBoard(); buildFullOrder();
$("runBtn").addEventListener("click", () => {
  let s = $("seed").value.trim();
  if (!s) {
    if (seedLocked) return;
    s = randomSeed(); $("seed").value = s;
  }
  play(s, $("instant").checked);
});
$("permalink").addEventListener("click", () => {
  $("permaUrl").select();
  navigator.clipboard.writeText($("permaUrl").value).then(() => {
    $("permalink").textContent = "✓ Copied";
    setTimeout(() => { $("permalink").textContent = "Copy"; }, 1600);
  });
});
$("simBtn").addEventListener("click", () => {
  $("simBtn").disabled = true; $("simNote").textContent = "Running 200,000 draws…";
  setTimeout(() => { runSimulation(); $("simBtn").disabled = false; }, 30);
});
$("potToggle").addEventListener("click", () => {
  const hidden = $("drawMechanics").classList.toggle("hidden");
  $("potToggle").classList.toggle("open", !hidden);
  $("potToggle").setAttribute("aria-expanded", String(!hidden));
  $("potToggleLabel").textContent = (hidden ? "Show" : "Hide") + " the odds picker";
});

// Click any headshot to enlarge it
document.addEventListener("click", (e) => {
  const lb = $("lightbox");
  const img = e.target.closest ? e.target.closest("img.avatar") : null;
  if (img) { $("lightbox-img").src = img.src; lb.classList.add("open"); }
  else if (e.target === lb) { lb.classList.remove("open"); }
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") $("lightbox").classList.remove("open");
});

const params = new URLSearchParams(location.search);
if (params.get("practice")) showPractice();
if (params.get("seed")) {
  const s = params.get("seed");
  if (params.get("lock")) lockSeed(s); else $("seed").value = s;
  // Locked (shared) links never auto-start, even older links that still carry run=1.
  if (params.get("run") && !params.get("lock")) play(s, false);
}
"""


def generate_lottery(pick_rows, year, sheet_id):
    import json

    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
    participants = _parse_lottery_participants(pick_rows)
    available = _available_photos()

    # Attach a stable color + (optional) flag + headshot to each entrant
    teams = []
    for i, p in enumerate(participants):
        teams.append({
            **p,
            "color": LOTTERY_COLORS[i % len(LOTTERY_COLORS)],
            "cc": LOTTERY_FLAGS.get(p["name"], ""),
            "photo": _photo_url(p["name"], available),
        })

    if len(teams) < 2:
        body = """<div class="section-card"><p style="color:var(--text-muted)">
        Lottery participants aren't set yet. Once the consolation bracket resolves and the
        Rookie Draft tab is populated, the weighted lottery will appear here.</p></div>"""
        return f"""{_head(f"Rookie Lottery {year}", "Provably-fair weighted draft lottery")}
<body>
{_nav()}
<div class="container-narrow">
    <div class="page-header">
        <div class="page-header-icon">{_logo_page_header()}</div>
        <h1>Rookie Lottery {year}</h1>
        <p class="subtitle">Weighted draw for picks 2&ndash;6</p>
    </div>
    {body}
</div>
</body></html>"""

    import re
    all_picks = _parse_all_picks(pick_rows)
    for p in all_picks:
        # Lottery slots stay generic placeholders (filled by the draw).
        if p["lottery"]:
            p["photo"] = ""
            p["owner"] = ""
            p["from_handle"] = ""
            p["from_photo"] = ""
            continue
        owner = _owner_handle(p["team"])
        m = re.search(r"\(from\s+([^)]+)\)", p["team"])
        p["owner"] = owner
        p["photo"] = _photo_url(owner, available)             # current owner
        p["from_handle"] = m.group(1).strip() if m else ""    # original owner (traded)
        p["from_photo"] = _photo_url(p["from_handle"], available) if m else ""
    js = (LOTTERY_JS
          .replace("__TEAMS__", json.dumps(teams))
          .replace("__PICKS__", json.dumps(all_picks)))
    first_pick = len(teams) + 1  # picks 2 .. (n+1)

    return f"""{_head(f"Rookie Draft Lottery {year}", "World Cup-style weighted lottery for the rookie draft")}
<body class="wc-theme">
{_nav()}
<div class="container-narrow">
    <div class="page-header wc-header">
        <div class="page-header-icon">&#127942;</div>
        <h1>The Draw {year}</h1>
        <p class="subtitle">Weighted lottery for rookie draft picks 2&ndash;{first_pick}</p>
        <a class="sheet-link" href="{sheet_url}" target="_blank">&#128196; Open in Google Sheets</a>
    </div>

    <div class="section-card lottery-intro">
        <h2>&#9917; How it works</h2>
        <ol>
            <li>The consolation-bracket teams are in the lottery for picks 2&ndash;{first_pick}. The better the
                consolation finish, the better the odds at the top pick &mdash; see the pot below.</li>
            <li>It's a <strong>1&ndash;100 draw</strong>: each team owns a slice of numbers sized to its odds.
                We draw a number, whoever's slice it lands in takes the next pick, then draw again (skipping anyone
                already in) until the order is set.</li>
            <li>The whole draw runs off one agreed-upon starting number, so it plays out the same for everyone and
                can be replayed. Want to sanity-check the odds? Hit <strong>Verify the odds</strong> at the bottom.</li>
        </ol>
    </div>

    <div class="section-card">
        <h2>&#127942; The Draw</h2>
        <div class="official-banner" id="officialBanner">
            <div>&#128274; This is the <strong>official draw</strong> (seed <code id="officialSeed"></code>).
            Press <strong>Watch the Official Draw</strong> when you're ready &mdash; everyone with this link sees the same result.</div>
            <a class="practice-link" href="?practice=1" target="_blank" rel="noopener">&#129514; Open a practice run to try other seeds &rarr;</a>
        </div>
        <div class="practice-banner" id="practiceBanner">
            &#129514; <strong>Practice run.</strong> Enter any seed and draw to see how it could play out &mdash; this isn't the official result.
        </div>
        <div class="seed-controls">
            <input id="seed" placeholder="Agreed-upon starting number (e.g. MNF-total-47)">
            <label class="toggle-label"><input type="checkbox" id="instant"> instant</label>
            <button class="btn" id="runBtn">Begin the Draw</button>
        </div>
        <div class="seed-note">
            Leave blank for a random one (fine for a test run). For the real draw, agree on a number first.
            Seed used: <span class="seed-shown" id="seedShown">&mdash;</span>
        </div>
        <div class="permalink-box" id="permaBox" style="display:none">
            <span class="permalink-label">&#128279; Shareable link</span>
            <input id="permaUrl" class="permalink-url" readonly>
            <button class="btn btn-small" id="permalink">Copy</button>
        </div>

        <button type="button" class="collapse-btn" id="potToggle" aria-expanded="false" aria-controls="drawMechanics">
            <span class="chev">&#9656;</span>
            <span id="potToggleLabel">Show the odds picker</span>
        </button>

        <div id="drawMechanics" class="hidden">
            <div class="pot-label">The pot &mdash; 100 balls by odds</div>
            <div class="odds-bar" id="oddsBar"></div>
        </div>

        <div class="roll-stage" id="rollStage">
            <div class="draw-ball">
                <span class="draw-ball-icon" id="drawBall">&#9917;</span>
                <span class="roll-num" id="rollNum">&ndash;</span>
            </div>
        </div>

        <div class="roll-status" id="rollStatus">Press <strong>Begin the Draw</strong> to start the ceremony.</div>

        <div class="pitch" id="pitch" style="display:none"></div>

        <div class="board" id="board"></div>
    </div>

    <div class="section-card">
        <h2>&#127942; Full draft order</h2>
        <p style="color:var(--text-secondary); font-size:0.88rem; margin-bottom:12px;">
            All {len(all_picks)} picks. The
            <span style="color:var(--wc-gold)">lottery slots (picks 2&ndash;{first_pick})</span>
            start pending and fill in as the draw runs.
        </p>
        <div class="order-list" id="fullOrder"></div>
        <p style="margin-top:14px;">
            <a class="sheet-link" href="rookie-values.html">&#128202; Rookie values &rarr;</a>
            <span style="color:var(--text-muted); font-size:0.78rem; margin-left:6px;">updated through the offseason &mdash; subject to change</span>
        </p>
    </div>

    <div class="section-card">
        <h2>&#128202; Verify the odds</h2>
        <p style="color:var(--text-secondary); font-size:0.88rem;">
            Don't take it on faith &mdash; simulate. This runs the <em>exact same</em> draw routine
            hundreds of thousands of times in your browser and shows how often each nation lands at each pick.
        </p>
        <button class="btn" id="simBtn" style="margin-top:10px;">Run 200,000 simulations</button>
        <table class="sim-table" id="simTable"></table>
        <p class="seed-note" id="simNote"></p>
    </div>
</div>

<div class="lightbox" id="lightbox"><img id="lightbox-img" alt="headshot"></div>

<script>
{js}
</script>
</body></html>"""


# ============================================================================
# Rookie Values — FantasyPros rookie ADP + draft cost (from the rankings script)
# ============================================================================
def _rookie_values_df(year, teams=12, keeper_discount=6):
    """Run the existing rankings scraper (FantasyPros, no Selenium) for rookie
    values. Returns a DataFrame, or an empty one if the scrape fails — a flaky
    scrape must never break the whole deploy.
    """
    import pandas as pd
    draft_prep = os.path.normpath(os.path.join(script_dir, "..", "draft_prep"))
    if draft_prep not in sys.path:
        sys.path.insert(0, draft_prep)
    try:
        from rankings.config import build_config
        from rankings.sources import fantasypros as fp
        from rankings import combine

        cfg = build_config(season=year, sources=("fpros",), rookies_only=True)
        rookies = fp.fetch_rookies(cfg)
        if rookies is None or rookies.empty:
            return pd.DataFrame()
        # ADP is often unpublished in the offseason — that's fine, the dynasty
        # rookie ranking still stands. Fetch it independently.
        try:
            adp = fp.fetch_adp(cfg)
        except Exception as exc:
            print(f"  Rookie ADP unavailable ({type(exc).__name__}); showing ranking only.", file=sys.stderr)
            adp = pd.DataFrame()
        return combine.build_simple_rookies_view(
            rookies, adp, teams=teams, keeper_discount_picks=keeper_discount,
        )
    except Exception as exc:  # network/DOM/season-not-published — degrade gracefully
        print(f"  Rookie values scrape skipped: {type(exc).__name__}: {exc}", file=sys.stderr)
        return pd.DataFrame()


def generate_rookie_values(df, year, teams=12, keeper_discount=6):
    import math

    if df is None or df.empty:
        body = """<div class="section-card"><p style="color:var(--text-muted)">
        Rookie values aren't available yet &mdash; the rankings source hasn't published this
        season's rookie class, or the scrape was unavailable at build time. Check back closer to the draft.</p></div>"""
        return f"""{_head(f"Rookie Values {year}", "Incoming rookie ADP and draft cost")}
<body>
{_nav()}
<div class="container-narrow">
    <div class="page-header">
        <div class="page-header-icon">{_logo_page_header()}</div>
        <h1>Rookie Values {year}</h1>
        <p class="subtitle">Incoming rookie class</p>
    </div>
    {body}
</div>
</body></html>"""

    positions = [p for p in ["QB", "RB", "WR", "TE"] if p in set(df["position"])]
    pos_options = "".join(f'<option value="{_escape(p)}">{_escape(p)}</option>' for p in positions)

    has_adp = bool(df["adp_avg"].notna().any()) if "adp_avg" in df.columns else False

    def _adp_cells(row):
        if not has_adp:
            return ""
        adp = getattr(row, "adp_avg", None)
        disc = getattr(row, "discounted_pick", None)
        cost = getattr(row, "rookie_cost_round", None)
        adp_txt = "&mdash;" if adp is None or (isinstance(adp, float) and math.isnan(adp)) else f"{adp:.1f}"
        disc_txt = "&mdash;" if disc is None or (isinstance(disc, float) and math.isnan(disc)) else f"{disc:.0f}"
        try:
            cost_txt = "&mdash;" if cost is None or (isinstance(cost, float) and math.isnan(cost)) else f"Rd {int(cost)}"
        except (ValueError, TypeError):
            cost_txt = "&mdash;"
        return (f'<td>{adp_txt}</td><td class="col-hide-mobile">{disc_txt}</td>'
                f'<td><strong>{cost_txt}</strong></td>')

    rows_html = ""
    for i, row in enumerate(df.itertuples(index=False), start=1):
        pos = _escape(getattr(row, "position", ""))
        rows_html += (f'<tr data-pos="{pos}"><td>{i}</td>'
                      f'<td>{_escape(getattr(row, "player_name", ""))}</td>'
                      f'<td>{pos}</td><td>{_escape(getattr(row, "team", ""))}</td>'
                      f'{_adp_cells(row)}</tr>\n')

    adp_head = (
        '<th data-col="4" data-num="1">ADP <span class="sort-arrow"></span></th>'
        '<th data-col="5" data-num="1" class="col-hide-mobile">Disc. Pick <span class="sort-arrow"></span></th>'
        '<th data-col="6" data-num="1">Rookie Rd <span class="sort-arrow"></span></th>'
    ) if has_adp else ''
    subtitle = (f"{len(df)} rookies &middot; consensus ADP from FantasyPros" if has_adp
                else f"{len(df)} rookies &middot; dynasty rookie rankings (FantasyPros)")
    intro = (
        f'<strong>Rookie Rd</strong> is the round a rookie is worth in our draft &mdash; their ADP pushed back '
        f'{keeper_discount} picks (keeper discount), then placed in a {teams}-team draft. Lower ADP = earlier pick.'
        if has_adp else
        'Ranked by dynasty rookie consensus &mdash; the order to target in the rookie draft. ADP and draft-cost '
        'columns will fill in once redraft ADP is published closer to the season.'
    )

    return f"""{_head(f"Rookie Values {year}", "Incoming rookie ADP and draft cost")}
<body>
{_nav()}
<div class="container">
    <div class="page-header">
        <div class="page-header-icon">{_logo_page_header()}</div>
        <h1>Rookie Values {year}</h1>
        <p class="subtitle">{subtitle}</p>
    </div>

    <div class="section-card" style="padding:14px 16px;">
        <p style="color:var(--text-secondary); font-size:0.85rem; margin:0;">{intro}</p>
    </div>

    <div class="filter-bar">
        <label for="pos-filter">Position:</label>
        <select id="pos-filter"><option value="">All</option>{pos_options}</select>
        <input id="name-filter" placeholder="Search player&hellip;"
               style="background:var(--bg-primary); color:var(--text-primary); border:1px solid var(--border); border-radius:4px; padding:4px 8px; font-size:0.85rem;">
    </div>

    <table class="data-table" id="rookie-table">
        <thead><tr>
            <th data-col="0" data-num="1">#  <span class="sort-arrow"></span></th>
            <th data-col="1">Player <span class="sort-arrow"></span></th>
            <th data-col="2">Pos <span class="sort-arrow"></span></th>
            <th data-col="3">Team <span class="sort-arrow"></span></th>
            {adp_head}
        </tr></thead>
        <tbody>
{rows_html}
        </tbody>
    </table>
</div>

<script>
(function() {{
    const table = document.getElementById("rookie-table");
    const tbody = table.querySelector("tbody");
    const posFilter = document.getElementById("pos-filter");
    const nameFilter = document.getElementById("name-filter");

    function applyFilters() {{
        const pos = posFilter.value;
        const q = nameFilter.value.trim().toLowerCase();
        tbody.querySelectorAll("tr").forEach(function(row) {{
            let show = true;
            if (pos && row.dataset.pos !== pos) show = false;
            if (q && !row.children[1].textContent.toLowerCase().includes(q)) show = false;
            row.style.display = show ? "" : "none";
        }});
    }}
    posFilter.addEventListener("change", applyFilters);
    nameFilter.addEventListener("input", applyFilters);

    let sortCol = -1, sortAsc = true;
    table.querySelectorAll("thead th").forEach(function(th) {{
        th.addEventListener("click", function() {{
            const col = parseInt(th.dataset.col);
            const num = th.dataset.num === "1";
            if (sortCol === col) {{ sortAsc = !sortAsc; }} else {{ sortCol = col; sortAsc = true; }}
            const rows = Array.from(tbody.querySelectorAll("tr"));
            rows.sort(function(a, b) {{
                let va = a.children[col].textContent.trim();
                let vb = b.children[col].textContent.trim();
                if (num) {{
                    const na = parseFloat(va.replace(/[^0-9.]/g, ""));
                    const nb = parseFloat(vb.replace(/[^0-9.]/g, ""));
                    const aa = isNaN(na), bb = isNaN(nb);
                    if (aa && bb) return 0;
                    if (aa) return 1;        // blanks/dashes to bottom
                    if (bb) return -1;
                    return sortAsc ? na - nb : nb - na;
                }}
                return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
            }});
            rows.forEach(function(r) {{ tbody.appendChild(r); }});
            table.querySelectorAll(".sort-arrow").forEach(function(s) {{ s.textContent = ""; }});
            th.querySelector(".sort-arrow").textContent = sortAsc ? " \\u25B2" : " \\u25BC";
        }});
    }});
}})();
</script>
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

    # Manager headshots (for the lottery / draft order avatars)
    photos_src = os.path.join(script_dir, "..", "assets", "photos")
    if os.path.isdir(photos_src):
        photos_dst = os.path.join(output_dir, "photos")
        os.makedirs(photos_dst, exist_ok=True)
        for f in os.listdir(photos_src):
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                shutil.copy2(os.path.join(photos_src, f), os.path.join(photos_dst, f))

    # OG image
    generate_og_image(output_dir, year)

    pages = {
        "index.html": generate_landing(year, sheet_id),
        "keeper-values.html": generate_keeper_values(keeper_df, year, sheet_id),
        "keeper-selections.html": generate_keeper_selections(keeper_df, year, sheet_id),
        "offseason-proposals.html": generate_proposals(year, sheet_id),
        "rookie-draft.html": generate_rookie_draft(pick_rows, year, sheet_id),
        "rookie-lottery.html": generate_lottery(pick_rows, year, sheet_id),
        "rookie-values.html": generate_rookie_values(_rookie_values_df(year), year),
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
