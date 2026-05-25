"""Sleeper draft import via the public Sleeper API.

Replaces the old Selenium-based DOM scrape with direct API calls. Either pass
a draft_id explicitly via Config, or rely on league-name + member-user-id +
season to resolve one automatically.

Output columns mirror what the legacy scrape produced so combine.py can merge
on (position, team, player_first_init, player_last):
    auction: drafted_price, status, manager_name
    snake:   drafted_round, drafted_pick, drafted_ovr, status, manager_name
"""

from __future__ import annotations

import re

import pandas as pd
import requests

from ..config import Config

SLEEPER_BASE = "https://api.sleeper.app/v1"

TEAM_NORMALIZE = {"JAX": "JAC"}
POS_NORMALIZE = {"DEF": "DST"}


def _fetch_json(url: str):
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _resolve_draft_id(cfg: Config) -> tuple[str, str]:
    """Return (draft_id, draft_type)."""
    if cfg.sleeper_draft_id:
        meta = _fetch_json(f"{SLEEPER_BASE}/draft/{cfg.sleeper_draft_id}")
        return cfg.sleeper_draft_id, meta.get("type", "snake")

    leagues = _fetch_json(
        f"{SLEEPER_BASE}/user/{cfg.sleeper_member_user_id}/leagues/nfl/{cfg.season}"
    )
    matches = [lg for lg in leagues if lg["name"] == cfg.sleeper_league_name]
    if not matches:
        raise RuntimeError(
            f"No Sleeper league named '{cfg.sleeper_league_name}' for user "
            f"{cfg.sleeper_member_user_id} in {cfg.season}"
        )
    league_id = matches[0]["league_id"]
    drafts = _fetch_json(f"{SLEEPER_BASE}/league/{league_id}/drafts")
    if not drafts:
        raise RuntimeError(f"No drafts found for league {league_id}")
    draft = drafts[0]
    return draft["draft_id"], draft.get("type", "snake")


def _manager_map(draft_id: str) -> dict[str, str]:
    """Map roster_id (and user_id) → display name via the draft's league users."""
    meta = _fetch_json(f"{SLEEPER_BASE}/draft/{draft_id}")
    league_id = meta.get("league_id")
    if not league_id:
        return {}
    users = _fetch_json(f"{SLEEPER_BASE}/league/{league_id}/users")
    rosters = _fetch_json(f"{SLEEPER_BASE}/league/{league_id}/rosters")
    user_by_id = {u["user_id"]: (u.get("display_name") or u.get("username") or "") for u in users}
    out: dict[str, str] = {}
    for r in rosters:
        name = user_by_id.get(r.get("owner_id"), "")
        out[str(r["roster_id"])] = name
        if r.get("owner_id"):
            out[str(r["owner_id"])] = name
    return out


def _player_first_init_and_last(first: str | None, last: str | None) -> tuple[str, str]:
    first = (first or "").strip()
    last = (last or "").strip()
    last = re.sub(r" I+$| Jr\.$| V$| I+V$| VI+$| Sr\.$", "", last)
    return (first[:1] if first else ""), last


def fetch(cfg: Config) -> pd.DataFrame:
    """Return a DataFrame of drafted players for the configured draft.

    Columns depend on draft type — see module docstring.
    """
    draft_id, draft_type = _resolve_draft_id(cfg)
    picks = _fetch_json(f"{SLEEPER_BASE}/draft/{draft_id}/picks")
    managers = _manager_map(draft_id)

    rows = []
    for p in picks:
        meta = p.get("metadata", {}) or {}
        position = POS_NORMALIZE.get(meta.get("position", ""), meta.get("position", ""))
        team = TEAM_NORMALIZE.get(meta.get("team", ""), meta.get("team", ""))
        first_init, last = _player_first_init_and_last(meta.get("first_name"), meta.get("last_name"))
        is_keeper = meta.get("is_keeper") in (True, "true", 1, "1")
        picked_by = str(p.get("picked_by") or "")
        roster_id = str(p.get("roster_id") or "")
        manager = managers.get(roster_id) or managers.get(picked_by) or ""
        status = "k" if is_keeper else "p"

        row = {
            "position": position,
            "team": team,
            "player_first_init": first_init,
            "player_last": last,
            "status": status,
            "manager_name": manager,
        }
        if draft_type == "auction":
            amount = meta.get("amount")
            row["drafted_price"] = int(amount) if amount not in (None, "") else None
        else:
            rd = p.get("round")
            pick_no = p.get("draft_slot") or p.get("pick_no")
            ovr = p.get("pick_no")
            row["drafted_round"] = rd
            row["drafted_pick"] = pick_no
            row["drafted_ovr"] = ovr
        rows.append(row)

    return pd.DataFrame(rows)
