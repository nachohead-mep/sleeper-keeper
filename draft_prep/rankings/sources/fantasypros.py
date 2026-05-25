"""FantasyPros source — rankings, ADP, and rookies via embedded ecrData JSON.

Every FP rankings page (position, overall, rookies) ships a `var ecrData = {...}`
blob containing the full consensus ranking data, so no Selenium is needed.

The ADP page is a standard HTML table with stable `fp-id-XXXXX` link classes
that join cleanly to ecrData's `player_id`.
"""

from __future__ import annotations

import json
import re
from typing import Iterable

import pandas as pd
import requests
from bs4 import BeautifulSoup

from ..config import POSITIONS, Config

UA = {"User-Agent": "Mozilla/5.0"}
ECR_DATA_RE = re.compile(r"var ecrData\s*=\s*(\{.*?\});", re.DOTALL)
BASE = "https://www.fantasypros.com/nfl/rankings"
ADP_BASE = "https://www.fantasypros.com/nfl/adp"

SCORING_SLUG = {"half": "half-point-ppr", "ppr": "ppr", "std": ""}
POSITION_SLUG = {"QB": "qb", "RB": "rb", "WR": "wr", "TE": "te", "K": "k", "DST": "dst"}


def _fetch(url: str) -> str:
    resp = requests.get(url, headers=UA, timeout=30)
    resp.raise_for_status()
    return resp.text


def _parse_ecr_data(html: str, url: str) -> dict:
    match = ECR_DATA_RE.search(html)
    if not match:
        raise RuntimeError(f"Could not locate ecrData on {url}")
    return json.loads(match.group(1))


def _ranking_url(scoring: str, position: str | None) -> str:
    slug = SCORING_SLUG[scoring]
    pos = POSITION_SLUG[position] if position else None
    if position is None:
        # overall
        if slug:
            return f"{BASE}/{slug}-cheatsheets.php"
        return f"{BASE}/cheatsheets.php"
    if position in ("RB", "WR", "TE") and slug:
        return f"{BASE}/{slug}-{pos}-cheatsheets.php"
    return f"{BASE}/{pos}-cheatsheets.php"


def _adp_url(scoring: str) -> str:
    slug = SCORING_SLUG[scoring] or "standard"
    return f"{ADP_BASE}/{slug}-overall.php"


def _ecr_to_df(data: dict, prefix: str) -> pd.DataFrame:
    df = pd.DataFrame(data["players"])
    if df.empty:
        return df
    rename = {
        "rank_ecr": f"{prefix}_ecr",
        "tier": f"{prefix}_tier",
        "pos_rank": f"{prefix}_pos_rank",
        "player_position_id": "position",
        "player_team_id": "team",
        "player_bye_week": "bye",
    }
    keep = [
        "player_id",
        "player_name",
        "player_position_id",
        "player_team_id",
        "player_bye_week",
        "rank_ecr",
        "tier",
        "pos_rank",
        "rank_min",
        "rank_max",
        "rank_ave",
        "rank_std",
    ]
    if "player_age" in df.columns:
        keep.append("player_age")
        rename["player_age"] = "age"
    return df[keep].rename(columns=rename)


def fetch_position_rankings(cfg: Config, positions: Iterable[str] = POSITIONS) -> pd.DataFrame:
    """Per-position ECR rankings (one row per player, all positions concatenated)."""
    frames = []
    for pos in positions:
        url = _ranking_url(cfg.scoring, pos)
        data = _parse_ecr_data(_fetch(url), url)
        df = _ecr_to_df(data, prefix="pos")
        if not df.empty:
            df["position"] = pos
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def fetch_overall_rankings(cfg: Config) -> pd.DataFrame:
    """Overall ECR rankings across all positions."""
    url = _ranking_url(cfg.scoring, position=None)
    data = _parse_ecr_data(_fetch(url), url)
    return _ecr_to_df(data, prefix="ovr")


def fetch_adp(cfg: Config) -> pd.DataFrame:
    """Standard ADP table from the FantasyPros ADP page (not the ECR-derived value)."""
    url = _adp_url(cfg.scoring)
    soup = BeautifulSoup(_fetch(url), "html.parser")
    table = soup.find("table", id="data")
    if table is None:
        raise RuntimeError(f"Could not locate ADP table on {url}")

    rows = []
    for tr in table.tbody.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 4:
            continue
        link = cells[1].find("a", class_="fp-player-link")
        if link is None:
            continue
        classes = link.get("class") or []
        fp_id = next(
            (int(c.split("fp-id-")[1]) for c in classes if c.startswith("fp-id-")),
            None,
        )
        if fp_id is None:
            continue
        rows.append(
            {
                "player_id": fp_id,
                "adp_rank": int(cells[0].get_text(strip=True)),
                "adp_pos_rank": cells[2].get_text(strip=True),
                "adp_avg": float(cells[3].get_text(strip=True)),
            }
        )
    return pd.DataFrame(rows)


def fetch_rookies(cfg: Config) -> pd.DataFrame:  # noqa: ARG001 (cfg reserved for future use)
    """Dynasty rookie consensus rankings."""
    url = f"{BASE}/dynasty-rookies-overall.php"
    data = _parse_ecr_data(_fetch(url), url)
    df = _ecr_to_df(data, prefix="rookie")
    return df
