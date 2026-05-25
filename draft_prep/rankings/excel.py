"""xlsxwriter output for the rankings workbook."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def _autosize(worksheet, df: pd.DataFrame) -> None:
    for i, col in enumerate(df.columns):
        col_str = df[col].astype(str)
        width = max(len(str(col)), col_str.str.len().max() if not col_str.empty else 0)
        worksheet.set_column(i, i, min(width + 2, 32))


def _write_sheet(writer, sheet_name: str, df: pd.DataFrame, *, color_cols: list[str] | None = None) -> None:
    df.to_excel(writer, sheet_name=sheet_name, index=False)
    workbook = writer.book
    worksheet = writer.sheets[sheet_name]

    header_fmt = workbook.add_format({"bold": True, "bg_color": "#1F2937", "font_color": "#FFFFFF"})
    for col_idx, name in enumerate(df.columns):
        worksheet.write(0, col_idx, name, header_fmt)

    _autosize(worksheet, df)
    n_rows = len(df) + 1
    worksheet.freeze_panes(1, 1)
    if n_rows > 1:
        worksheet.autofilter(0, 0, n_rows - 1, len(df.columns) - 1)

    for col in color_cols or []:
        if col not in df.columns:
            continue
        idx = df.columns.get_loc(col)
        worksheet.conditional_format(
            1, idx, n_rows - 1, idx,
            {
                "type": "3_color_scale",
                "min_color": "#63BE7B",
                "mid_color": "#FFEB84",
                "max_color": "#F8696B",
            },
        )


def write_rookies_only(rookies_df: pd.DataFrame, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out_path, engine="xlsxwriter") as writer:
        _write_sheet(writer, "Rookies", rookies_df, color_cols=["adp_avg", "rookie_ecr"])


def write_simple_rookies(rookies_df: pd.DataFrame, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out_path, engine="xlsxwriter") as writer:
        _write_sheet(writer, "Rookies", rookies_df,
                     color_cols=["adp_avg", "rookie_cost_round"])


def write_full_workbook(
    out_path: Path,
    *,
    analyst_df: pd.DataFrame,
    ovr_analyst_df: pd.DataFrame,
    rookies_df: pd.DataFrame,
    position_order: tuple[str, ...] = ("QB", "RB", "WR", "TE", "K", "DST"),
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out_path, engine="xlsxwriter") as writer:
        for pos in position_order:
            sub = analyst_df[analyst_df["position"] == pos].sort_values("analyst_average")
            if sub.empty:
                continue
            _write_sheet(writer, pos, sub.reset_index(drop=True), color_cols=["analyst_average"])
        if not ovr_analyst_df.empty:
            ovr = ovr_analyst_df.sort_values("ovr_ecr")
            _write_sheet(writer, "Overall", ovr.reset_index(drop=True), color_cols=["ovr_ecr", "adp_avg"])
        if not rookies_df.empty:
            _write_sheet(writer, "Rookies", rookies_df, color_cols=["adp_avg", "rookie_ecr"])
