"""Fantasy Footballers (Andy / Mike / Jason) rankings.

The 2026 draft rankings page loads via async JS — `window.udk.fetchProjections()`
populates `window.udk.data.projections` with a single payload covering every
position. We load one page, wait for that AJAX call to complete, and pull the
JSON out directly.

Per-analyst ranks aren't published in the free `projections` payload; we expose
the consensus rank as `ffb_pos_rank` for parity with the legacy scraper.
"""

from __future__ import annotations

import json

import pandas as pd

from ..config import Config

# Any position page works — projections contains all positions.
PROBE_URL_TEMPLATE = "https://www.thefantasyfootballers.com/{year}-running-back-rankings-draft/"

TEAM_NORMALIZE = {"JAX": "JAC"}
POSITIONS_OF_INTEREST = {"QB", "RB", "WR", "TE", "K", "DST", "DEF"}

ADP_FIELD = {
    "half": "adp_half_ppr",
    "ppr": "adp_ppr",
    "std": "adp",
}


def fetch(cfg: Config) -> pd.DataFrame:
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.support.ui import WebDriverWait

    from ._selenium import chrome_driver

    url = PROBE_URL_TEMPLATE.format(year=cfg.season)
    with chrome_driver() as driver:
        driver.get(url)
        try:
            WebDriverWait(driver, 20).until(
                lambda d: d.execute_script(
                    "return !!(window.udk && window.udk.data && "
                    "window.udk.data.projections && window.udk.data.projections.length)"
                )
            )
        except TimeoutException:
            return pd.DataFrame()

        projections_json = driver.execute_script(
            "return JSON.stringify(window.udk.data.projections)"
        )

    projections = json.loads(projections_json)
    if not projections:
        return pd.DataFrame()

    # The projections array has one row per (player × analyst). ADP fields
    # are the same across analyst rows, so dedupe to one row per player.
    seen: set[str] = set()
    deduped = []
    for p in projections:
        pid = str(p.get("player_id", ""))
        if pid in seen:
            continue
        seen.add(pid)
        deduped.append(p)
    projections = deduped

    adp_key = ADP_FIELD.get(cfg.scoring, "adp_half_ppr")
    rows = []
    for p in projections:
        pos = p.get("fantasy_position") or ""
        if pos == "DEF":
            pos = "DST"
        if pos not in POSITIONS_OF_INTEREST - {"DEF"}:
            continue
        adp_val = p.get(adp_key)
        try:
            adp_float = float(adp_val) if adp_val not in (None, "", "0.00") else None
        except (TypeError, ValueError):
            adp_float = None
        first_last = (p.get("name") or "").split(" ", 1)
        player_first = first_last[0] if first_last else ""
        player_last = first_last[1] if len(first_last) > 1 else ""
        rows.append(
            {
                "player_name": p.get("name", ""),
                "player_first": player_first,
                "player_first_init": player_first[:1],
                "player_last": player_last,
                "position": pos,
                "team": TEAM_NORMALIZE.get(p.get("team", ""), p.get("team", "")),
                "bye": p.get("bye_week", ""),
                "ffb_adp": adp_float,
                "mode": cfg.scoring,
            }
        )

    df = pd.DataFrame(rows)
    # Per-position rank derived from ADP (lower ADP = better rank).
    df["ffb_pos_rank"] = (
        df.sort_values("ffb_adp")
        .groupby("position")
        .cumcount()
        + 1
    )
    return df
