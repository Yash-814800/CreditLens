"""Counterfactual recourse engine (CLAUDE.md rule 6: pure function, no I/O, no
LLM). Given an applicant's current sanitized features and their scorecard
breakdown, `recommend_recourse()` finds the cheapest realistic set of
ACTIONABLE changes that would reach the next-better outcome tier, and -- per
the phase spec -- VERIFIES every recommendation by literally re-running
`scorecard.compute_score()` on the counterfactual profile before returning it.
If no combination of actionable changes verifiably reaches the next tier, this
returns an empty list rather than overclaiming (CLAUDE.md rule 4: no fake
results, including in the direction of false hope).

Scope decision (documented, not an oversight): recourse is offered ONLY for
the 5 actionable features that are already PRESENT (not None) and not already
at their best bin. Missing documents are deliberately excluded from the
verified recourse list -- submitting a document neither of us has seen might
score *worse* than the neutral 0 points a missing factor currently earns, so
"submit the missing utility bill" cannot be honestly verified to help, and
CLAUDE.md's no-fake-results rule applies to recourse advice as much as to any
other number in this app. (Phase 6/7's UI can separately note which documents
are missing; that is a completeness message, not a scored recourse action.)

Excluded from the actionable set entirely, on purpose:
  - weekly_inflow_cv: cash-inflow volatility isn't something an applicant can
    just decide to reduce; there's no honest coaching action for it.
  - authenticity_score: a fraud/integrity signal, not a coachable behaviour --
    the only "action" that would move it is either not committing fraud
    (nothing to recommend) or literally gaming a fraud check, which this
    engine must never suggest.

See docs/recourse_gaming_risk.md for the gaming-risk discussion the phase
spec asks for (e.g. a temporary deposit right before reapplying to inflate
avg_daily_balance_inr) and how monitoring would counter it.
"""

from __future__ import annotations

import math
from typing import Any

from app.schemas.scoring import RecourseAction, ScoreBreakdown
from app.services.guardrails.sanitizer import ScoringInput
from app.services.scoring.decision import load_policy
from app.services.scoring.scorecard import compute_score, load_scorecard

ACTIONABLE_FEATURES: tuple[str, ...] = (
    "utility_tenure_months",
    "utility_on_time_ratio",
    "avg_daily_balance_inr",
    "gig_active_days_per_week",
    "income_reconciliation_ratio",
)

_FIXED_HORIZON_DAYS: dict[str, int] = {
    "utility_on_time_ratio": 90,
    "avg_daily_balance_inr": 30,
    "gig_active_days_per_week": 14,
    "income_reconciliation_ratio": 30,
}

_ACTION_TEMPLATES: dict[str, str] = {
    "utility_tenure_months": (
        "Keep this utility connection active for about {extra_months} more month(s) "
        "(currently {current:.1f} months) to reach {target:.0f}+ months of tenure: "
        "+{points} points."
    ),
    "utility_on_time_ratio": (
        "Pay your utility bill on time for the next few billing cycles to raise your "
        "on-time ratio from {current:.0%} toward {target:.0%}: +{points} points."
    ),
    "avg_daily_balance_inr": (
        "Maintain an average daily bank balance of at least Rs {target:,.0f} "
        "(currently Rs {current:,.0f}) for about 30 days: +{points} points."
    ),
    "gig_active_days_per_week": (
        "Increase your active work days to at least {target:.1f} per week "
        "(currently {current:.1f}) over your next reporting period: +{points} points."
    ),
    "income_reconciliation_ratio": (
        "Route your gig-platform payouts into the same bank account shown in your "
        "statement so your bank credits reconcile with your declared payouts "
        "(currently {current:.0%} reconciled): +{points} points."
    ),
}


def _bin_index(value: float, bins: list[dict[str, Any]]) -> int:
    for i, b in enumerate(bins):
        if b["upper_bound"] is None or value < b["upper_bound"]:
            return i
    return len(bins) - 1


def _best_reachable_bin(
    name: str, current_value: float, scorecard_cfg: dict[str, Any]
) -> tuple[float, int, str] | None:
    """(target_value, points_gain, best_bin_label) for the single BEST bin
    reachable above `current_value` (not just the next incremental one) --
    or None if already at the best bin.

    Jumping straight to the top bin, rather than nudging one bin at a time,
    is deliberate: with only one candidate per feature, `recommend_recourse`'s
    greedy selection (largest gain first) can close a large point gap with
    the FEWEST distinct behaviour changes asked of the applicant, which is a
    more honest "cheapest realistic path" than silently requiring several
    partial steps on the same feature. Every recommendation is still
    verified by re-scoring before being returned (see `recommend_recourse`).

    Only supports higher_is_better factors -- every ACTIONABLE_FEATURES
    entry is one, by construction (see module docstring for what's excluded
    and why)."""
    factor_cfg = scorecard_cfg["factors"][name]
    bins = factor_cfg["bins"]
    idx = _bin_index(current_value, bins)
    if idx >= len(bins) - 1:
        return None
    current_points = bins[idx]["points"]
    best_bin = bins[-1]
    # The smallest value that reaches the best bin is the second-to-last
    # bin's own upper_bound (its exact threshold); with only one bin above
    # `current_value` (idx == len(bins) - 2), that's simply the next bin.
    target_value = bins[-2]["upper_bound"]
    gain = best_bin["points"] - current_points
    if gain <= 0:
        return None
    return target_value, gain, best_bin["label"]


def _horizon_days(name: str, current: float, target: float) -> int | None:
    if name == "utility_tenure_months":
        extra_months = max(1, math.ceil(target - current))
        return round(extra_months * 30.44)
    return _FIXED_HORIZON_DAYS.get(name)


def _action_text(name: str, current: float, target: float, points: int) -> str:
    template = _ACTION_TEMPLATES[name]
    if name == "utility_tenure_months":
        extra_months = max(1, math.ceil(target - current))
        return template.format(
            extra_months=extra_months, current=current, target=target, points=points
        )
    return template.format(current=current, target=target, points=points)


def recommend_recourse(
    scoring_input: ScoringInput,
    score_breakdown: ScoreBreakdown,
    *,
    policy_cfg: dict[str, Any] | None = None,
    scorecard_cfg: dict[str, Any] | None = None,
) -> list[RecourseAction]:
    policy_cfg = policy_cfg or load_policy()
    scorecard_cfg = scorecard_cfg or load_scorecard()
    tiers = policy_cfg["score_tiers"]

    total = score_breakdown.total
    if total >= tiers["approve_min"]:
        return []  # already at the best tier
    target_threshold = tiers["approve_min"] if total >= tiers["refer_min"] else tiers["refer_min"]
    needed_points = target_threshold - total

    candidates: list[tuple[str, float, float, int, str]] = []
    for name in ACTIONABLE_FEATURES:
        value = scoring_input.get(name)
        if value is None:
            continue
        step = _best_reachable_bin(name, value, scorecard_cfg)
        if step is None:
            continue
        target_value, points_gain, label = step
        candidates.append((name, value, target_value, points_gain, label))

    # Cheapest-first: fewest/biggest-impact changes first, to minimise how
    # many separate behaviours we ask the applicant to change at once.
    candidates.sort(key=lambda c: c[3], reverse=True)

    counterfactual: ScoringInput = dict(scoring_input)
    chosen: list[tuple[str, float, float, int]] = []
    cumulative = 0
    for name, current, target_value, points_gain, _label in candidates:
        if cumulative >= needed_points:
            break
        counterfactual[name] = target_value
        cumulative += points_gain
        chosen.append((name, current, target_value, points_gain))

    if cumulative < needed_points:
        return []  # no verifiable combination reaches the next tier; don't overclaim

    verified = compute_score(counterfactual, scorecard_cfg)
    if verified.total < target_threshold:
        # Bin interactions didn't add up exactly as the greedy sum predicted
        # (can happen if two factors share knock-on effects in a future
        # scorecard version) -- refuse to report an unverified recourse path.
        return []

    actions: list[RecourseAction] = []
    running_total = total
    for name, current, target_value, points_gain in chosen:
        running_total += points_gain
        actions.append(
            RecourseAction(
                feature=name,
                current=current,
                target=target_value,
                points_gain=points_gain,
                resulting_score=min(100, running_total),
                horizon_days=_horizon_days(name, current, target_value),
                text=_action_text(name, current, target_value, points_gain),
                actionable=True,
            )
        )
    return actions
