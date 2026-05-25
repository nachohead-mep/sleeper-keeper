#!/usr/bin/env -S uv run
"""CLI orchestrator for the draft-rankings workbook.

Examples:
    # Just rookies, sorted by current overall ADP — runs in seconds, no Selenium
    uv run draft_prep/rankings_scrape.py --rookies-only

    # Full workbook, only FantasyPros + Sleeper (no Selenium-based sources)
    uv run draft_prep/rankings_scrape.py --sources fpros,sleeper

    # Everything (needs Chrome installed for the Selenium-based sources)
    uv run draft_prep/rankings_scrape.py

    # PPR scoring for a future season
    uv run draft_prep/rankings_scrape.py --scoring ppr --season 2027

The orchestrator runs each requested source independently. A failure in one
(e.g. CBS DOM has changed) is logged and the rest still produce output.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

import pandas as pd

from rankings import combine, excel
from rankings.config import ALL_SOURCES, build_config


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--season", type=int, default=None, help="NFL season year (defaults to current)")
    p.add_argument("--scoring", choices=("half", "ppr", "std"), default="half")
    p.add_argument("--qb-scoring", choices=("4pt", "6pt"), default="4pt")
    p.add_argument("--draft-type", choices=("auction", "snake"), default="auction")
    p.add_argument(
        "--sources",
        default=",".join(ALL_SOURCES),
        help=f"Comma-separated sources to run. Valid: {','.join(ALL_SOURCES)}",
    )
    p.add_argument("--rookies-only", action="store_true",
                   help="Skip the full workbook — just FP rookies + ADP, single sheet.")
    p.add_argument("--simple", action="store_true",
                   help="With --rookies-only: emit a 5-column sheet (name/pos/team/ADP/cost-round).")
    p.add_argument("--teams", type=int, default=12,
                   help="Teams in your league (used for rookie-cost-round calc). Default 12.")
    p.add_argument("--keeper-discount", type=int, default=6,
                   help="Picks of discount to apply to ADP for rookie-cost-round calc. Default 6.")
    p.add_argument("--draft-id", default=None,
                   help="Sleeper draft_id to pull drafted state from (overrides env)")
    p.add_argument("--output-dir", type=Path, default=None,
                   help="Output directory (defaults to draft_prep/output/)")
    return p.parse_args(argv)


def _safe_run(label: str, fn):
    print(f"  → {label}…", flush=True)
    try:
        df = fn()
        print(f"    ok ({len(df)} rows)")
        return df
    except Exception as exc:
        print(f"    skipped: {type(exc).__name__}: {exc}", file=sys.stderr)
        if "--debug" in sys.argv:
            traceback.print_exc()
        return pd.DataFrame()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    sources = tuple(s.strip() for s in args.sources.split(",") if s.strip())

    cfg = build_config(
        season=args.season,
        scoring=args.scoring,
        qb_scoring=args.qb_scoring,
        draft_type=args.draft_type,
        sources=sources,
        rookies_only=args.rookies_only,
        output_dir=args.output_dir,
        sleeper_draft_id=args.draft_id,
    )

    print(f"Season {cfg.season} · scoring={cfg.scoring} · sources={','.join(cfg.sources)} "
          f"· rookies_only={cfg.rookies_only}")

    # Always run FantasyPros (every downstream view needs it).
    from rankings.sources import fantasypros as fp
    fp_rookies = _safe_run("fpros rookies", lambda: fp.fetch_rookies(cfg))
    fp_overall = _safe_run("fpros overall", lambda: fp.fetch_overall_rankings(cfg))
    fp_adp = _safe_run("fpros ADP", lambda: fp.fetch_adp(cfg))

    drafted = pd.DataFrame()
    if "sleeper" in cfg.sources:
        from rankings.sources import sleeper as sl
        drafted = _safe_run("sleeper draft", lambda: sl.fetch(cfg))

    if cfg.rookies_only:
        if args.simple:
            view = combine.build_simple_rookies_view(
                fp_rookies, fp_adp,
                teams=args.teams, keeper_discount_picks=args.keeper_discount,
            )
            out_path = cfg.output_path.with_name(f"{cfg.season}_rookies_simple.xlsx")
            excel.write_simple_rookies(view, out_path)
            print(f"Wrote {out_path}")
        else:
            view = combine.build_rookies_view(fp_rookies, fp_overall, fp_adp, drafted=drafted)
            excel.write_rookies_only(view, cfg.output_path)
            print(f"Wrote {cfg.output_path}")
        return 0

    fp_position = _safe_run("fpros positions",
                            lambda: fp.fetch_position_rankings(cfg))

    cbs_df = ffb_df = nfc_df = pd.DataFrame()
    if "cbs" in cfg.sources:
        from rankings.sources import cbs
        cbs_df = _safe_run("CBS", lambda: cbs.fetch(cfg))
    if "ffb" in cfg.sources:
        from rankings.sources import ffb
        ffb_df = _safe_run("Fantasy Footballers", lambda: ffb.fetch(cfg))
    if "nfc" in cfg.sources:
        from rankings.sources import nfc
        nfc_df = _safe_run("NFFC", lambda: nfc.fetch(cfg))

    analyst_df, ovr_analyst_df = combine.build_full_views(
        fp_position=fp_position,
        fp_overall=fp_overall,
        fp_adp=fp_adp,
        cbs=cbs_df,
        ffb=ffb_df,
        nfc=nfc_df,
        drafted=drafted,
    )
    rookies_view = combine.build_rookies_view(
        fp_rookies, fp_overall, fp_adp, drafted=drafted,
    )
    excel.write_full_workbook(
        cfg.output_path,
        analyst_df=analyst_df,
        ovr_analyst_df=ovr_analyst_df,
        rookies_df=rookies_view,
    )
    print(f"Wrote {cfg.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
