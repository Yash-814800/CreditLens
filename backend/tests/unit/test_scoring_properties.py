"""Hypothesis-based property tests for Phase 5's decision core (CLAUDE.md
Phase 5, item 6): score bounds, scorecard monotonicity, and sanitizer
invariance under 200+ randomised profiles -- these are the properties a
handful of hand-picked example tests can't fully cover.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.services.guardrails.sanitizer import sanitize
from app.services.scoring.decision import decide, load_policy
from app.services.scoring.features import CANONICAL_FEATURE_NAMES
from app.services.scoring.scorecard import _bin_for_value, compute_score, load_scorecard

pytestmark = pytest.mark.unit

_SCORECARD = load_scorecard()
_POLICY = load_policy()
_FACTOR_NAMES = list(_SCORECARD["factors"].keys())

_FEATURE_RANGES: dict[str, tuple[float, float]] = {
    "utility_tenure_months": (0, 60),
    "weekly_inflow_cv": (0, 2),
    "utility_on_time_ratio": (0, 1),
    "avg_daily_balance_inr": (0, 200_000),
    "gig_active_days_per_week": (0, 7),
    "income_reconciliation_ratio": (0, 1.5),
    "authenticity_score": (0, 1),
}


def _feature_value_strategy(name: str):
    lo, hi = _FEATURE_RANGES[name]
    return st.one_of(st.none(), st.floats(min_value=lo, max_value=hi, allow_nan=False))


_scoring_input_strategy = st.fixed_dictionaries(
    {name: _feature_value_strategy(name) for name in _FACTOR_NAMES}
)


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(_scoring_input_strategy)
def test_score_always_within_bounds(scoring_input):
    breakdown = compute_score(scoring_input, _SCORECARD)
    assert 0 <= breakdown.total <= 100
    assert 0 <= breakdown.data_completeness <= 1


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(_scoring_input_strategy, st.sampled_from(_FACTOR_NAMES))
def test_monotonicity_improving_a_favourable_feature_never_lowers_score(scoring_input, factor_name):
    """Moving ONE feature to a strictly better bin (per its own `direction`)
    while holding every other feature fixed must never decrease the total
    score -- CLAUDE.md Phase 5's explicit monotonicity requirement."""
    factor_cfg = _SCORECARD["factors"][factor_name]
    bins = factor_cfg["bins"]

    baseline = compute_score(scoring_input, _SCORECARD)

    # Construct a value guaranteed to land in the single BEST bin for this
    # factor. For higher_is_better, the best bin is the last one (value
    # above every finite upper_bound); for lower_is_better, the best bin is
    # the FIRST one (value below its upper_bound, i.e. a small/zero value).
    finite_bounds = [b["upper_bound"] for b in bins if b["upper_bound"] is not None]
    if factor_cfg["direction"] == "higher_is_better":
        best_value = (max(finite_bounds) * 2) if finite_bounds else 1.0
    else:
        best_value = 0.0

    assert _bin_for_value(best_value, bins)["points"] == factor_cfg["max_up"]

    improved = dict(scoring_input)
    improved[factor_name] = best_value
    improved_breakdown = compute_score(improved, _SCORECARD)

    assert improved_breakdown.total >= baseline.total


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(
    name=st.text(min_size=1, max_size=20),
    phone=st.text(min_size=10, max_size=10, alphabet="0123456789"),
    address=st.text(min_size=1, max_size=40),
    vocation=st.text(min_size=1, max_size=40),
    gender=st.sampled_from(["male", "female", "other", "prefer_not_to_say"]),
    features=_scoring_input_strategy,
)
def test_sanitizer_invariance_pii_changes_never_affect_scoring_input(
    name, phone, address, vocation, gender, features
):
    """Changing PII/protected-attribute fields must never change the
    sanitized ScoringInput (and therefore never change the score) -- 200
    randomised profiles per CLAUDE.md Phase 5's sanitizer-invariance
    requirement."""
    base_ctx = {
        "full_name": name,
        "phone": phone,
        "declared_address": address,
        "stated_vocation": vocation,
        "gender": gender,
        **features,
    }
    varied_ctx = {
        "full_name": name + "_different",
        "phone": phone[::-1],
        "declared_address": address + " (varied)",
        "stated_vocation": vocation + " (varied)",
        "gender": "other" if gender != "other" else "male",
        **features,
    }

    base_input, _ = sanitize(base_ctx)
    varied_input, _ = sanitize(varied_ctx)

    assert base_input == varied_input
    base_breakdown = compute_score(base_input, _SCORECARD)
    varied_breakdown = compute_score(varied_input, _SCORECARD)
    assert base_breakdown.total == varied_breakdown.total

    base_decision = decide(
        score_breakdown=base_breakdown,
        fraud_severity="NONE",
        identity_check_status="PASS",
        suspected_instruction_text=False,
        requested_line_inr=25000.0,
        verified_monthly_income_inr=30000.0,
        policy=_POLICY,
    )
    varied_decision = decide(
        score_breakdown=varied_breakdown,
        fraud_severity="NONE",
        identity_check_status="PASS",
        suspected_instruction_text=False,
        requested_line_inr=25000.0,
        verified_monthly_income_inr=30000.0,
        policy=_POLICY,
    )
    assert base_decision.outcome == varied_decision.outcome
    assert base_decision.final_outcome == varied_decision.final_outcome
    assert base_decision.score == varied_decision.score
    assert base_decision.eligible_line_inr == varied_decision.eligible_line_inr
    assert base_decision.reason_codes == varied_decision.reason_codes


@given(st.dictionaries(st.text(min_size=1, max_size=15), st.integers(), max_size=5))
def test_sanitizer_never_lets_an_unknown_key_through(extra_fields):
    ctx = dict.fromkeys(CANONICAL_FEATURE_NAMES, 1.0) | extra_fields
    scoring_input, _ = sanitize(ctx)
    assert set(scoring_input.keys()) == set(CANONICAL_FEATURE_NAMES)
