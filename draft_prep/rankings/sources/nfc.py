"""NFFC industry ADP / AAV.

Submits a date-range form (last 14 days by default) and either auction or
snake-style ADP from nfc.shgn.com/adp/football.

NOTE: Auction (AAV) data is only published during draft season — querying
outside that window returns "No AAV Information Available" and `fetch()`
returns an empty frame.
"""

from __future__ import annotations

import re
import time
from datetime import date, timedelta
from io import StringIO

import pandas as pd

from ..config import Config

URL = "https://nfc.shgn.com/adp/football"
PLAYER_SUFFIX = re.compile(r" I+$| Jr\.$| V$| I+V$| VI+$| Sr\.$")
TEAM_NORMALIZE = {"JAX": "JAC", "ARZ": "ARI", "LA": "LAR"}
POSITION_NORMALIZE = {"TK": "K", "TDSP": "DST"}


def _submit_form(driver, draft_type: str) -> None:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select

    driver.get(URL)
    time.sleep(2)

    if draft_type == "auction":
        select = Select(driver.find_element(By.ID, "draft_type"))
        select.select_by_visible_text("Average Auction Values")
        driver.find_element(By.CSS_SELECTOR, "input[type='submit']").click()
        time.sleep(1)

    two_weeks = date.today() - timedelta(days=14)
    datefield = driver.find_element(By.ID, "from_date")
    datefield.click()
    datefield.clear()
    datefield.send_keys(two_weeks.isoformat())
    driver.find_element(By.CSS_SELECTOR, "input[type='submit']").click()
    time.sleep(1)


def fetch(cfg: Config) -> pd.DataFrame:
    from bs4 import BeautifulSoup
    from ._selenium import chrome_driver

    with chrome_driver() as driver:
        _submit_form(driver, cfg.draft_type)
        soup = BeautifulSoup(driver.page_source, "html.parser")
        table = soup.find("table", id="adp")

    if table is None:
        return pd.DataFrame()
    # Off-season auction queries (and any other empty result) come back as a
    # single tbody row with `colspan="100%"` and a message. Bail before pandas
    # trips on the non-numeric colspan.
    body_rows = table.find_all("tr") if table.tbody is None else table.tbody.find_all("tr")
    if len(body_rows) <= 1 and body_rows and body_rows[0].find("td", attrs={"colspan": True}):
        return pd.DataFrame()

    df = pd.read_html(StringIO(str(table)))[0]
    if "Player" not in df.columns:
        return pd.DataFrame()
    df["Player"] = df["Player"].apply(lambda v: re.sub(r"\d+ Betting Markets ", "", v).strip())
    df["Player"] = df["Player"].apply(lambda v: PLAYER_SUFFIX.sub("", v).strip())

    if cfg.draft_type == "auction":
        df = df[["Rk", "Player", "Team", "Position(s)", "ADP / AAV"]]
        df.columns = ["nfc_adp", "player_name", "team", "position", "nfc_price"]
        df["nfc_price"] = df["nfc_price"].apply(lambda v: int(re.sub(r"\$", "", v)))
    else:
        df = df[["Rk", "Player", "Team", "Position(s)"]]
        df.columns = ["nfc_adp", "player_name", "team", "position"]

    # Position players: split name → first / first_init / last
    pos_players = df[df["position"] != "TDSP"].copy()
    name_parts = pos_players["player_name"].str.split(" ", n=1, expand=True)
    pos_players["player_first"] = name_parts[0].replace("Hollywood", "Marquise")
    pos_players["player_first_init"] = pos_players["player_first"].str[0]
    pos_players["player_last"] = name_parts[1]

    # Team defenses
    dst = df[df["position"] == "TDSP"].copy()
    dst["position"] = "DST"
    dst = dst[dst["team"] != "FA"]
    dst["player_name"] = dst["player_name"].apply(lambda v: re.sub(r"\(.+\) ", "", v))
    split = dst["player_name"].str.split(" ")
    dst["player_last"] = split.apply(lambda parts: parts[-1])
    dst["player_first"] = split.apply(lambda parts: " ".join(parts[:-1]))
    dst["player_first_init"] = dst["player_first"].str[0]

    out = pd.concat([pos_players, dst], ignore_index=True)
    out["team"] = out["team"].replace(TEAM_NORMALIZE)
    out["position"] = out["position"].replace(POSITION_NORMALIZE)

    # Per-position adp rank
    out["nfc_pos_adp"] = (
        out.sort_values("nfc_adp").groupby("position").cumcount() + 1
    )
    return out
