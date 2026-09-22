#!/usr/bin/env python3
"""Sanity-check the scorecard against data/synth/history.parquet's VALIDATION
split (CLAUDE.md Phase 5, item 7): prints the tier mix and default rate by
score band, so tuning decisions in scorecard_v1.yaml can be checked against
real numbers rather than guessed. Never run against the TEST split (that is
scripts/validate_scorecard.py's job, Phase 8, after the scorecard is frozen).

Run from the repo root:
    uv run --project backend python scripts/tier_distribution.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

import pandas as pd  # noqa: E402

from app.services.scoring.decision import load_policy  # noqa: E402
from app.services.scoring.scorecard import compute_score, load_scorecard  # noqa: E402

HISTORY_PATH = REPO_ROOT / "data" / "synth" / "history.parquet"


def main() -> None:
    df = pd.read_parquet(HISTORY_PATH)
    val = df[df["split"] == "val"].copy()
    if val.empty:
        raise SystemExit(f"No 'val' split rows found in {HISTORY_PATH}")

    scorecard_cfg = load_scorecard()
    policy_cfg = load_policy()
    tiers = policy_cfg["score_tiers"]

    scores = []
    for _, row in val.iterrows():
        scoring_input = {
            name: (None if pd.isna(row.get(name)) else float(row[name]))
            for name in scorecard_cfg["factors"]
            if name in row.index
        }
        # authenticity_score has no history-dataset column (Phase 2's
        # fraud-free synthetic history) -- assume a clean/typical value so
        # the scorecard's other 6 real factors drive the tier distribution,
        # documented here rather than silently defaulting to None everywhere.
        scoring_input.setdefault("authenticity_score", 0.95)
        breakdown = compute_score(scoring_input, scorecard_cfg)
        scores.append(breakdown.total)
    val["score"] = scores

    def tier_of(score: int) -> str:
        if score >= tiers["approve_min"]:
            return "APPROVE"
        if score >= tiers["refer_min"]:
            return "REFER"
        return "DECLINE"

    val["tier"] = val["score"].apply(tier_of)

    print(f"VALIDATION split: n={len(val)}")
    print()
    print("Tier mix:")
    mix = val["tier"].value_counts(normalize=True).reindex(["APPROVE", "REFER", "DECLINE"])
    for tier, frac in mix.items():
        count = val["tier"].value_counts().get(tier, 0)
        print(f"  {tier:8s} {frac:6.1%}  (n={count})")
    print()

    print("Default rate by tier (should rise APPROVE -> REFER -> DECLINE):")
    by_tier = val.groupby("tier")["defaulted"].agg(["mean", "count"]).reindex(
        ["APPROVE", "REFER", "DECLINE"]
    )
    for tier, row in by_tier.iterrows():
        print(f"  {tier:8s} default_rate={row['mean']:.3f}  (n={int(row['count'])})")
    print()

    print("Default rate by score decile (should be monotonically non-increasing as score rises):")
    val["score_decile"] = pd.qcut(val["score"], 10, duplicates="drop")
    by_decile = val.groupby("score_decile", observed=True)["defaulted"].agg(["mean", "count"])
    for decile, row in by_decile.iterrows():
        print(f"  {decile}: default_rate={row['mean']:.3f}  (n={int(row['count'])})")

    rates = by_tier["mean"].tolist()
    monotonic = all(rates[i] <= rates[i + 1] for i in range(len(rates) - 1))
    print()
    print(f"Monotonic (APPROVE <= REFER <= DECLINE default rate): {monotonic}")


if __name__ == "__main__":
    main()
