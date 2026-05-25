"""Merge per-source DataFrames into the views the Excel writer expects.

Two views:
  - `build_rookies_view` — FP rookies + FP overall + FP ADP joined on player_id,
    optionally annotated with drafted state from Sleeper.
  - `build_full_views` — analyst_df (positional analyst rankings + ADP) and
    ovr_analyst_df (with overall ECR layered on). Used by the full workbook.

Sources that are missing/empty are silently skipped — combine.py degrades to
whatever it has rather than requiring every scraper to succeed.
"""

from __future__ import annotations

import re

import pandas as pd

PLAYER_SUFFIX = re.compile(r" I+$| Jr\.$| V$| I+V$| VI+$| Sr\.$")
NAME_KEYS = ["position", "team", "player_first_init", "player_last"]


def _strip_suffix(name: str) -> str:
    return PLAYER_SUFFIX.sub("", name or "").strip()


def _names(df: pd.DataFrame) -> pd.DataFrame:
    """Add player_first_init / player_last on a frame keyed by player_name."""
    if df.empty:
        return df
    parts = df["player_name"].fillna("").apply(_strip_suffix).str.split(" ", n=1, expand=True)
    df = df.copy()
    df["player_first_init"] = parts[0].str[:1]
    df["player_last"] = parts[1].fillna("")
    return df


# ---------------------------------------------------------------------------
# Rookies view
# ---------------------------------------------------------------------------
def build_rookies_view(
    fp_rookies: pd.DataFrame,
    fp_overall: pd.DataFrame,
    fp_adp: pd.DataFrame,
    drafted: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Rookies, sorted by current overall ADP (rookies with no ADP at the bottom)."""
    if fp_rookies.empty:
        return fp_rookies

    df = fp_rookies.copy()
    if not fp_overall.empty:
        ovr = fp_overall[["player_id", "ovr_ecr", "ovr_tier"]]
        df = df.merge(ovr, on="player_id", how="left")
    if not fp_adp.empty:
        df = df.merge(fp_adp, on="player_id", how="left")

    if drafted is not None and not drafted.empty:
        df = _names(df)
        d = drafted.copy()
        if "player_last" not in d.columns:
            d = _names(d.assign(player_name=d.get("player_name", "")))
        d = d.drop_duplicates(subset=NAME_KEYS)
        df = df.merge(d, on=NAME_KEYS, how="left")

    sort_col = "adp_avg" if "adp_avg" in df.columns else "rookie_ecr"
    df["_sort"] = df[sort_col].fillna(float("inf")) if sort_col == "adp_avg" else df[sort_col]
    df = df.sort_values(["_sort", "rookie_ecr"], ascending=[True, True]).drop(columns="_sort")
    df.insert(0, "overall_order", range(1, len(df) + 1))
    return df.reset_index(drop=True)


def build_simple_rookies_view(
    fp_rookies: pd.DataFrame,
    fp_adp: pd.DataFrame,
    *,
    teams: int = 12,
    keeper_discount_picks: int = 6,
) -> pd.DataFrame:
    """Trimmed view: name / pos / team / ADP / rookie draft cost (round).

    Rookie draft cost = round that ADP falls in after pushing back by
    `keeper_discount_picks` picks. E.g. ADP 12 with a 6-pick discount lands
    at pick 18 — round 2 in a 12-team league.
    """
    if fp_rookies.empty:
        return fp_rookies

    df = fp_rookies[["player_id", "player_name", "position", "team"]].copy()
    if not fp_adp.empty:
        df = df.merge(fp_adp[["player_id", "adp_avg"]], on="player_id", how="left")
    else:
        df["adp_avg"] = pd.NA

    discounted = df["adp_avg"] + keeper_discount_picks
    cost = ((discounted - 1) // teams + 1).astype("Int64")
    df["discounted_pick"] = discounted.round(1)
    df["rookie_cost_round"] = cost

    df = df.drop(columns="player_id")
    df = df.sort_values("adp_avg", na_position="last").reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# Full workbook view
# ---------------------------------------------------------------------------
def build_full_views(
    fp_position: pd.DataFrame,
    fp_overall: pd.DataFrame,
    fp_adp: pd.DataFrame,
    cbs: pd.DataFrame | None = None,
    ffb: pd.DataFrame | None = None,
    nfc: pd.DataFrame | None = None,
    drafted: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (analyst_df, ovr_analyst_df).

    `analyst_df` is per-position; columns include FP pos_ecr/pos_adp/pos_tier
    plus optional CBS/FFB/NFC analyst columns. `ovr_analyst_df` adds overall
    ecr/adp/tier.
    """
    if fp_position.empty:
        return pd.DataFrame(), pd.DataFrame()

    df = fp_position.copy()
    df = _names(df)

    analyst_cols: list[str] = ["pos_ecr"]

    # CBS — pivot per-analyst pos_rank into wide columns
    if cbs is not None and not cbs.empty:
        cbs_pivot = (
            cbs.pivot_table(
                index=NAME_KEYS,
                columns="analyst",
                values="pos_rank",
                aggfunc="mean",
            )
            .reset_index()
        )
        df = df.merge(cbs_pivot, on=NAME_KEYS, how="left")
        analyst_cols.extend([c for c in cbs_pivot.columns if c not in NAME_KEYS])

    # FFB — single pos_rank column
    if ffb is not None and not ffb.empty:
        ffb_keep = ffb[NAME_KEYS + ["ffb_pos_rank"]].drop_duplicates(subset=NAME_KEYS)
        df = df.merge(ffb_keep, on=NAME_KEYS, how="left")
        analyst_cols.append("ffb_pos_rank")

    # NFC ADP — overall adp + per-position adp
    if nfc is not None and not nfc.empty:
        nfc_keep = nfc[NAME_KEYS + ["nfc_adp", "nfc_pos_adp"] + (["nfc_price"] if "nfc_price" in nfc.columns else [])]
        nfc_keep = nfc_keep.drop_duplicates(subset=NAME_KEYS)
        df = df.merge(nfc_keep, on=NAME_KEYS, how="left")
        analyst_cols.append("nfc_pos_adp")

    # Fill missing analyst ranks with worst+1 per position so averaging is fair.
    for col in analyst_cols:
        if col not in df.columns:
            continue
        worst = df.groupby("position")[col].transform("max") + 1
        df[col] = df[col].fillna(worst)

    df["analyst_average"] = df[analyst_cols].mean(axis=1)

    # Drafted state
    if drafted is not None and not drafted.empty:
        d = drafted.drop_duplicates(subset=NAME_KEYS)
        df = df.merge(d, on=NAME_KEYS, how="left")

    analyst_df = df

    # Overall view: layer FP overall onto analyst rows by player_id
    if fp_overall.empty:
        return analyst_df, pd.DataFrame()
    ovr_cols = ["player_id", "ovr_ecr", "ovr_tier"]
    ovr_analyst_df = analyst_df.merge(fp_overall[ovr_cols], on="player_id", how="left")
    if not fp_adp.empty:
        ovr_analyst_df = ovr_analyst_df.merge(fp_adp, on="player_id", how="left")
    return analyst_df, ovr_analyst_df
