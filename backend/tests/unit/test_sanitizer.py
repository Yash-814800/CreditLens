import pytest

from app.services.guardrails.sanitizer import sanitize
from app.services.scoring.features import CANONICAL_FEATURE_NAMES

pytestmark = pytest.mark.unit


def _full_context(**overrides):
    ctx = {
        "full_name": "Aarav Mehta",
        "phone": "9812345601",
        "pan": "AAAPM1234A",
        "aadhaar_hash": "deadbeef",
        "declared_address": "14, Whitefield, Bengaluru - 560066",
        "stated_vocation": "ride-hailing driver",
        "gender": "male",
        "requested_line_inr": 25000,
        "utility_tenure_months": 17.87,
        "utility_on_time_ratio": 1.0,
        "weekly_inflow_cv": 0.23,
        "avg_daily_balance_inr": 104083.48,
        "low_balance_day_ratio": 0.0,
        "gig_active_days_per_week": 6.42,
        "gig_weekly_earnings_cv": 0.15,
        "gig_tenure_weeks": 59.86,
        "income_reconciliation_ratio": 1.5,
        "authenticity_score": 0.97,
        "verified_monthly_income_inr": 23200.7,
    }
    ctx.update(overrides)
    return ctx


def test_only_canonical_features_pass_through():
    scoring_input, report = sanitize(_full_context())

    assert set(scoring_input.keys()) == set(CANONICAL_FEATURE_NAMES)
    assert scoring_input["utility_tenure_months"] == 17.87
    assert scoring_input["avg_daily_balance_inr"] == 104083.48


def test_pii_and_protected_attributes_are_removed_with_reasons():
    _, report = sanitize(_full_context())

    removed_fields = {r.field for r in report.removed}
    for pii_field in (
        "full_name",
        "phone",
        "pan",
        "aadhaar_hash",
        "declared_address",
        "stated_vocation",
        "gender",
        "requested_line_inr",
    ):
        assert pii_field in removed_fields
    for r in report.removed:
        assert r.reason  # every removal has a human-readable reason


def test_unknown_field_dropped_by_default_not_denylist():
    ctx = _full_context(some_future_field_nobody_anticipated="xyz")
    scoring_input, report = sanitize(ctx)

    assert "some_future_field_nobody_anticipated" not in scoring_input
    removed_names = {r.field: r.reason for r in report.removed}
    assert "not on the scoring allowlist" in removed_names["some_future_field_nobody_anticipated"]


def test_missing_canonical_feature_is_none_not_an_error():
    ctx = _full_context()
    del ctx["gig_tenure_weeks"]
    scoring_input, _ = sanitize(ctx)

    assert scoring_input["gig_tenure_weeks"] is None


def test_non_numeric_value_smuggled_under_allowlisted_name_is_dropped():
    ctx = _full_context(utility_tenure_months="not-a-number")
    scoring_input, report = sanitize(ctx)

    assert scoring_input["utility_tenure_months"] is None
    removed_names = {r.field: r.reason for r in report.removed}
    assert "not numeric" in removed_names["utility_tenure_months"]


def test_none_is_a_valid_value_for_a_canonical_feature():
    ctx = _full_context(gig_tenure_weeks=None)
    scoring_input, report = sanitize(ctx)

    assert scoring_input["gig_tenure_weeks"] is None
    assert "gig_tenure_weeks" not in {r.field for r in report.removed}
