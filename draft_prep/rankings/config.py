"""Runtime configuration for the rankings package.

Reads from environment (loaded from repo-root .env) with sensible defaults,
and provides typed accessors for use across source modules.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

PACKAGE_DIR = Path(__file__).resolve().parent
DRAFT_PREP_DIR = PACKAGE_DIR.parent
DEFAULT_OUTPUT_DIR = DRAFT_PREP_DIR / "output"

SCORING_MODES = {"half", "ppr", "std"}
QB_SCORING_MODES = {"4pt", "6pt"}

ALL_SOURCES = ("fpros", "cbs", "ffb", "nfc", "sleeper")
POSITIONS = ("QB", "RB", "WR", "TE", "K", "DST")


def _current_season() -> int:
    today = date.today()
    return today.year if today.month > 2 else today.year - 1


@dataclass(frozen=True)
class Config:
    season: int
    scoring: str           # half | ppr | std
    qb_scoring: str        # 4pt | 6pt
    draft_type: str        # auction | snake
    sources: tuple[str, ...]
    rookies_only: bool
    output_dir: Path
    sleeper_league_name: str
    sleeper_member_user_id: str
    sleeper_draft_id: str | None

    @property
    def output_path(self) -> Path:
        suffix = "rookies" if self.rookies_only else "rankings"
        return self.output_dir / f"{self.season}_{suffix}.xlsx"


def build_config(
    *,
    season: int | None = None,
    scoring: str = "half",
    qb_scoring: str = "4pt",
    draft_type: str = "auction",
    sources: tuple[str, ...] = ALL_SOURCES,
    rookies_only: bool = False,
    output_dir: Path | None = None,
    sleeper_draft_id: str | None = None,
) -> Config:
    if scoring not in SCORING_MODES:
        raise ValueError(f"scoring must be one of {SCORING_MODES}, got {scoring!r}")
    if qb_scoring not in QB_SCORING_MODES:
        raise ValueError(f"qb_scoring must be one of {QB_SCORING_MODES}, got {qb_scoring!r}")
    if draft_type not in {"auction", "snake"}:
        raise ValueError(f"draft_type must be auction|snake, got {draft_type!r}")
    unknown = [s for s in sources if s not in ALL_SOURCES]
    if unknown:
        raise ValueError(f"Unknown sources: {unknown}. Valid: {ALL_SOURCES}")

    return Config(
        season=season or _current_season(),
        scoring=scoring,
        qb_scoring=qb_scoring,
        draft_type=draft_type,
        sources=tuple(sources),
        rookies_only=rookies_only,
        output_dir=output_dir or DEFAULT_OUTPUT_DIR,
        sleeper_league_name=os.environ.get(
            "SLEEPER_LEAGUE_NAME", "Delta Fantasy Football League"
        ),
        sleeper_member_user_id=os.environ.get(
            "SLEEPER_MEMBER_USER_ID", "737386559564894208"
        ),
        sleeper_draft_id=sleeper_draft_id or os.environ.get("SLEEPER_DRAFT_ID"),
    )
