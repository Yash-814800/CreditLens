#!/usr/bin/env python3
"""Phase 8 (CLAUDE.md's "no fake results" rule): validates the FROZEN
scorecard (scorecard_v1.yaml, last touched in Phase 5) against
data/synth/history.parquet's held-out TEST split -- never touched during
calibration (see scripts/tier_distribution.py, which only ever reads the
VALIDATION split) -- and writes every number straight into
docs/validation_report.md. No number in that report is hand-typed.

Reports: tier mix, default rate by tier/decile, a monotonicity check, AUC/
Gini/KS (implemented here with plain rank statistics -- no scikit-learn
dependency for one script), agreement between the scorecard's tier and an
offline replay of the two-signal precedent rule (real k=25 cosine-similarity
peer lookup over the embedder, computed against the TRAIN split only, so a
TEST row is never compared to itself or to other TEST/VAL rows -- avoiding
the leakage a live run against the fully-seeded historical_borrowers table
would have, since that table currently contains every split), and an
explicit weight-sensitivity check (Phase 8's stretch item): every factor's
points perturbed +/-20%, reporting what fraction of TEST-split applicants
would flip tier as a result.

Run from the repo root:
    uv run --project backend python scripts/validate_scorecard.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from app.services.scoring.decision import load_policy  # noqa: E402
from app.services.scoring.scorecard import compute_score, load_scorecard  # noqa: E402
from app.services.vectors.embedder import EngineeredFeatureEmbedder  # noqa: E402
from app.services.vectors.precedents import wilson_score_interval  # noqa: E402

HISTORY_PATH = REPO_ROOT / "data" / "synth" / "history.parquet"
OUT_PATH = REPO_ROOT / "docs" / "validation_report.md"
K = 25
AUTHENTICITY_DEFAULT = 0.95  # see tier_distribution.py -- history has no fraud simulation


def _score_split(df: pd.DataFrame, scorecard_cfg: dict) -> pd.Series:
    scores = []
    for _, row in df.iterrows():
        scoring_input = {
            name: (None if pd.isna(row.get(name)) else float(row[name]))
            for name in scorecard_cfg["factors"]
            if name in row.index
        }
        scoring_input.setdefault("authenticity_score", AUTHENTICITY_DEFAULT)
        scores.append(compute_score(scoring_input, scorecard_cfg).total)
    return pd.Series(scores, index=df.index)


def _tier_of(score: float, tiers: dict) -> str:
    if score >= tiers["approve_min"]:
        return "APPROVE"
    if score >= tiers["refer_min"]:
        return "REFER"
    return "DECLINE"


def _auc_gini_ks(score: pd.Series, defaulted: pd.Series) -> tuple[float, float, float]:
    """AUC = P(score_nondefault > score_default), via the rank-sum
    (Mann-Whitney U) identity -- equivalent to sklearn.metrics.roc_auc_score
    for a binary label, without adding scikit-learn as a dependency for one
    validation script. Gini = 2*AUC - 1 (the credit-risk convention). KS =
    max separation between the two groups' empirical CDFs of score."""
    ranks = score.rank(method="average")
    non_default_mask = ~defaulted.astype(bool)
    n1 = int(non_default_mask.sum())
    n0 = int((~non_default_mask).sum())
    r1 = ranks[non_default_mask].sum()
    auc = (r1 - n1 * (n1 + 1) / 2) / (n1 * n0)
    gini = 2 * auc - 1

    thresholds = np.sort(score.unique())
    cdf_default = np.array([(score[defaulted.astype(bool)] <= t).mean() for t in thresholds])
    cdf_nondefault = np.array([(score[non_default_mask] <= t).mean() for t in thresholds])
    ks = float(np.max(np.abs(cdf_default - cdf_nondefault)))
    return float(auc), float(gini), ks


def _two_signal_agreement(
    test_df: pd.DataFrame, train_df: pd.DataFrame, policy_cfg: dict
) -> dict:
    """Offline replay of app/services/scoring/decision.py's `_apply_two_signal`
    rule, using a real k=NN cosine-similarity peer lookup computed here
    (TRAIN-split embeddings only -- never the row's own split), not the live
    pgvector service (which currently holds every split at once and would let
    a TEST row match itself). REFER trivially "agrees" (the real rule never
    touches a REFER outcome), matching decision.py's own logic exactly."""
    embedder = EngineeredFeatureEmbedder()
    ts = policy_cfg["two_signal"]
    tiers = policy_cfg["score_tiers"]
    k = int(ts.get("k", 35))

    def features_of(row: pd.Series) -> dict:
        feats = {
            name: (None if pd.isna(row.get(name)) else float(row[name]))
            for name in [
                "utility_tenure_months",
                "utility_on_time_ratio",
                "weekly_inflow_cv",
                "avg_daily_balance_inr",
                "low_balance_day_ratio",
                "gig_active_days_per_week",
                "gig_weekly_earnings_cv",
                "gig_tenure_weeks",
                "income_reconciliation_ratio",
                "verified_monthly_income_inr",
            ]
        }
        return feats

    train_vecs = np.array([embedder.embed(features_of(row)) for _, row in train_df.iterrows()])
    train_defaulted = train_df["defaulted"].to_numpy().astype(bool)

    agree = 0
    disagree = 0
    skipped = 0
    for _, row in test_df.iterrows():
        vec = np.array(embedder.embed(features_of(row)))
        sims = train_vecs @ vec  # both sides are L2-normalised -> dot product = cosine similarity
        top_k_idx = np.argsort(-sims)[:k]
        peer_defaults = train_defaulted[top_k_idx]
        n = len(peer_defaults)
        defaults = int(peer_defaults.sum())
        ci_lower, ci_upper = wilson_score_interval(defaults, n)

        tier = _tier_of(row["score"], tiers)
        if n < ts["min_sample_size"] or tier == "REFER":
            skipped += 1
            continue
        if tier == "APPROVE" and ci_lower > ts["max_acceptable_default_rate_for_approve"]:
            disagree += 1
        elif tier == "DECLINE" and ci_upper < ts["min_acceptable_default_rate_for_decline"]:
            disagree += 1
        else:
            agree += 1

    checked = agree + disagree
    return {
        "checked": checked,
        "agree": agree,
        "disagree": disagree,
        "skipped_refer_or_thin_peer_group": skipped,
        "agreement_rate": (agree / checked) if checked else float("nan"),
    }


def _weight_sensitivity(test_df: pd.DataFrame, scorecard_cfg: dict, tiers: dict) -> dict:
    """Perturbs every factor's every bin's points by +/-20% (Phase 8's stretch
    item) and reports what fraction of TEST-split applicants would land in a
    DIFFERENT tier than the frozen scorecard assigns -- a direct, measured
    answer to "how sensitive is this policy to the exact point values",
    rather than an assertion that the weights are robust."""
    base_scores = test_df["score"]
    base_tiers = base_scores.apply(lambda s: _tier_of(s, tiers))

    results = {}
    for direction, factor in (("up", 1.20), ("down", 0.80)):
        perturbed_cfg = copy.deepcopy(scorecard_cfg)
        for factor_cfg in perturbed_cfg["factors"].values():
            for bin_cfg in factor_cfg["bins"]:
                # ScoreFactor.points is a strict `int` field (schemas/scoring.py) --
                # round rather than leave a fractional float, which pydantic would reject.
                bin_cfg["points"] = round(bin_cfg["points"] * factor)
        perturbed_scores = _score_split(test_df, perturbed_cfg)
        perturbed_tiers = perturbed_scores.apply(lambda s: _tier_of(s, tiers))
        flipped = (perturbed_tiers.values != base_tiers.values).mean()
        results[direction] = float(flipped)
    return results


def main() -> None:
    df = pd.read_parquet(HISTORY_PATH)
    test = df[df["split"] == "test"].copy()
    train = df[df["split"] == "train"].copy()
    if test.empty or train.empty:
        raise SystemExit(f"Expected non-empty 'train' and 'test' splits in {HISTORY_PATH}")

    scorecard_cfg = load_scorecard()
    policy_cfg = load_policy()
    tiers = policy_cfg["score_tiers"]

    test["score"] = _score_split(test, scorecard_cfg)
    test["tier"] = test["score"].apply(lambda s: _tier_of(s, tiers))

    mix = test["tier"].value_counts(normalize=True).reindex(["APPROVE", "REFER", "DECLINE"])
    counts = test["tier"].value_counts().reindex(["APPROVE", "REFER", "DECLINE"]).fillna(0)
    by_tier = (
        test.groupby("tier")["defaulted"].agg(["mean", "count"]).reindex(["APPROVE", "REFER", "DECLINE"])
    )
    rates = by_tier["mean"].tolist()
    monotonic = all(rates[i] <= rates[i + 1] for i in range(len(rates) - 1))

    test["score_decile"] = pd.qcut(test["score"], 10, duplicates="drop")
    by_decile = test.groupby("score_decile", observed=True)["defaulted"].agg(["mean", "count"])

    auc, gini, ks = _auc_gini_ks(test["score"], test["defaulted"])

    agreement = _two_signal_agreement(test, train, policy_cfg)
    sensitivity = _weight_sensitivity(test, scorecard_cfg, tiers)

    lines = []
    lines.append("# Scorecard validation report")
    lines.append("")
    lines.append(
        "**SYNTHETIC DATA.** Every number below is computed by "
        "`scripts/validate_scorecard.py` against `data/synth/history.parquet`'s "
        "held-out TEST split (never touched during Phase 5's calibration, which used "
        "the VALIDATION split only -- see `scripts/tier_distribution.py`). This is a "
        "pipeline-correctness demonstration on synthetic, latent-variable-generated "
        "data, **not a claim of real-world predictive accuracy** on real applicants, "
        "per CLAUDE.md rule 4."
    )
    lines.append("")
    lines.append(f"TEST split size: n={len(test)}")
    lines.append("")
    lines.append("## Tier mix and default rate by tier")
    lines.append("")
    lines.append("| Tier | Share | n | Default rate |")
    lines.append("|---|---|---|---|")
    for tier in ["APPROVE", "REFER", "DECLINE"]:
        lines.append(
            f"| {tier} | {mix[tier]:.1%} | {int(counts[tier])} | {by_tier.loc[tier, 'mean']:.3f} |"
        )
    lines.append("")
    lines.append(f"**Monotonic (APPROVE <= REFER <= DECLINE default rate): {monotonic}**")
    lines.append("")
    lines.append("## Default rate by score decile")
    lines.append("")
    lines.append("| Score decile | Default rate | n |")
    lines.append("|---|---|---|")
    for decile, row in by_decile.iterrows():
        lines.append(f"| {decile} | {row['mean']:.3f} | {int(row['count'])} |")
    lines.append("")
    lines.append("## Discrimination metrics")
    lines.append("")
    lines.append(
        "AUC is computed here as `P(score_nondefaulter > score_defaulter)` via the "
        "Mann-Whitney rank-sum identity (equivalent to `sklearn.metrics.roc_auc_score`, "
        "reimplemented with `pandas`/`numpy` rank statistics to avoid adding "
        "scikit-learn as a dependency for one script)."
    )
    lines.append("")
    lines.append(f"- **AUC**: {auc:.3f}")
    lines.append(f"- **Gini** (2*AUC - 1): {gini:.3f}")
    lines.append(f"- **KS statistic**: {ks:.3f}")
    lines.append("")
    lines.append("## Agreement with the pgvector two-signal precedent rule")
    lines.append("")
    lines.append(
        "Offline replay of `app/services/scoring/decision.py`'s `_apply_two_signal` rule: "
        f"for every TEST-split applicant, a real k={K} cosine-similarity peer lookup is run "
        "against the TRAIN split's embeddings only (never TEST/VAL rows, and never the "
        "applicant's own row -- unlike a live query against the fully-seeded "
        "`historical_borrowers` table, which currently holds every split at once). "
        "REFER-tier applicants are excluded (the real rule never touches a REFER outcome), "
        "matching `decision.py`'s own logic exactly."
    )
    lines.append("")
    lines.append(f"- Checked (APPROVE/DECLINE with a large-enough peer group): {agreement['checked']}")
    lines.append(f"- Agree: {agreement['agree']}")
    lines.append(f"- Disagree (would be downgraded/upgraded to REFER): {agreement['disagree']}")
    lines.append(
        f"- Skipped (REFER tier, or peer group below `min_sample_size`): "
        f"{agreement['skipped_refer_or_thin_peer_group']}"
    )
    if agreement["checked"]:
        lines.append(f"- **Agreement rate: {agreement['agreement_rate']:.1%}**")
    lines.append("")
    lines.append("## Weight-sensitivity (stretch item): +/-20% perturbation of every factor's points")
    lines.append("")
    lines.append(
        "Every bin's points in a copy of the frozen `scorecard_v1.yaml` are scaled by the "
        "given factor (base points unaffected), the TEST split is re-scored, and the fraction "
        "of applicants whose tier changes as a result is reported."
    )
    lines.append("")
    lines.append(f"- All points x1.20: {sensitivity['up']:.1%} of TEST-split applicants flip tier")
    lines.append(f"- All points x0.80: {sensitivity['down']:.1%} of TEST-split applicants flip tier")
    lines.append("")
    lines.append("## Limitations")
    lines.append("")
    lines.append(
        "- This history dataset is synthetic: `defaulted` is generated from a latent "
        "creditworthiness variable plus an independent unobserved shock (see "
        "`docs/data_card.md`), deliberately NOT derived from the scorecard's own features, "
        "specifically to avoid circular validation -- but it is still a simulation, not "
        "observed real-world repayment behaviour."
    )
    lines.append(
        "- `authenticity_score` has no history-dataset column (the synthetic history has no "
        f"fraud simulation) and is fixed at {AUTHENTICITY_DEFAULT} for every row here, same as "
        "`scripts/tier_distribution.py` -- this validation exercises the other 6 factors only."
    )
    lines.append(
        "- The two-signal agreement check is an offline reimplementation for validation "
        "purposes (TRAIN-only peer pool), not a call to the live `/api/v1` precedent-matching "
        "endpoint, which is exercised separately by `backend/tests/integration/test_pipeline_full.py`."
    )
    lines.append("")

    OUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_PATH}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
