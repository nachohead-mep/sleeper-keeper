"""CBS Sportsline analyst rankings (Dave Richard, Heath Cummings, Jamey Eisenberg).

Loads the per-position rankings page for each scoring mode and extracts each
analyst's column.

NOTE: CBS has redesigned the rankings UI; the legacy selectors below
(`experts-column`, `player-row`, `rank`, `player-name`, `team`) may no longer
match. If `fetch()` returns empty for a working page, the selectors need to
be refreshed against the current DOM.
"""

from __future__ import annotations

import re
import time

import pandas as pd

from ..config import Config, POSITIONS
from ._selenium import chrome_driver

BASE = "https://www.cbssports.com/fantasy/football/rankings"
PLAYER_SUFFIX = re.compile(r" I+$| Jr\.$| V$| I+V$| VI+$| Sr\.$")


def _scrape_page(driver, url: str, position: str, mode: str) -> list[dict]:
    from bs4 import BeautifulSoup

    driver.get(url)
    time.sleep(1)
    soup = BeautifulSoup(driver.page_source, "html.parser")

    rows = []
    for analyst_col in soup.find_all(class_="experts-column"):
        author = analyst_col.find(class_="author-name")
        if author is None:
            continue
        analyst_name = re.sub(r"-.*", "", author.text).strip()
        for player_pane in analyst_col.find_all(class_="player-row"):
            rank_el = player_pane.find(class_="rank")
            name_el = player_pane.find(class_="player-name")
            team_el = player_pane.find(class_="team")
            if not (rank_el and name_el and team_el):
                continue

            orig_name = name_el.text.strip()
            player_name = PLAYER_SUFFIX.sub("", orig_name)
            team_text = team_el.text
            price_match = re.search(r"\$(\d+)", team_text)
            price = int(price_match.group(1)) if price_match else None

            if position == "DST":
                player_first = ""
                player_first_init = ""
                player_last = player_name
                team = re.sub(r"\$|\d", "", team_text).strip()
            else:
                player_first_match = re.search(r"\w\.", player_name)
                player_first_init = (
                    re.sub(r"\.", "", player_first_match.group()) if player_first_match else ""
                )
                player_last = re.sub(r"\w\.", "", player_name).strip()
                player_last = re.sub(r"^S ", "St. ", player_last)
                player_first = ""
                team = re.sub(r"\$|\d", "", team_text).strip()

            rows.append(
                {
                    "analyst": analyst_name,
                    "position": position,
                    "mode": mode,
                    "player_name": player_name,
                    "player_first": player_first,
                    "player_first_init": player_first_init,
                    "player_last": player_last,
                    "team": team,
                    "pos_rank": int(rank_el.text.strip()),
                    "price": price,
                }
            )
    return rows


def fetch(cfg: Config, modes: tuple[str, ...] = ("ppr", "standard")) -> pd.DataFrame:
    rows: list[dict] = []
    with chrome_driver() as driver:
        for mode in modes:
            for pos in POSITIONS:
                url = f"{BASE}/{mode}/{pos}/yearly/"
                rows.extend(_scrape_page(driver, url, pos, mode))
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # Average ppr+standard into a "half" mode so callers can pick consistently.
    half = (
        df.groupby(
            ["analyst", "position", "player_first", "player_name", "player_first_init", "player_last", "team"],
            as_index=False,
        )
        .agg({"price": "mean", "pos_rank": "mean"})
    )
    half["mode"] = "half"
    return pd.concat([df, half], ignore_index=True)
