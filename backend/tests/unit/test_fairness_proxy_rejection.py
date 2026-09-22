"""Phase 8 fairness-audit requirement (referenced from docs/fairness_report.md,
section 3): proves a synthetic, group-correlated PROXY feature -- one nobody
explicitly named "protected attribute" -- is still caught and dropped, because
app/services/guardrails/sanitizer.py is an ALLOWLIST (CLAUDE.md rule 7), not a
denylist that would need to recognise this specific proxy by name."""

import random

import pytest

from app.services.guardrails.sanitizer import sanitize
from app.services.scoring.features import CANONICAL_FEATURE_NAMES

pytestmark = pytest.mark.unit


def _context_with_proxy(group_label: str, proxy_value: float) -> dict:
    return {
        # A stand-in for a real-world proxy feature: e.g. a pincode-derived
        # regional price/cost-of-living index, deliberately correlated with
        # `group_label` below -- never itself a named protected attribute,
        # which is exactly what makes a denylist approach fragile.
        "regional_price_index": proxy_value,
        "group_label": group_label,  # also not a canonical feature; also dropped
        "utility_tenure_months": 12.0,
        "utility_on_time_ratio": 0.9,
        "weekly_inflow_cv": 0.3,
        "avg_daily_balance_inr": 5000.0,
        "gig_active_days_per_week": 5.0,
        "income_reconciliation_ratio": 1.0,
        "authenticity_score": 0.95,
        "verified_monthly_income_inr": 20000.0,
    }


class TestGroupCorrelatedProxyFeatureIsCaught:
    def test_group_correlated_proxy_feature_is_dropped_by_sanitizer(self):
        # Build a proxy that is STRONGLY correlated with group_label -- exactly
        # the shape of feature a real-world redlining-by-proxy risk looks like.
        rng = random.Random(42)
        rows = [
            _context_with_proxy(
                group_label=("A" if i % 2 == 0 else "B"),
                proxy_value=(100.0 if i % 2 == 0 else 40.0) + rng.uniform(-2, 2),
            )
            for i in range(40)
        ]

        for ctx in rows:
            scoring_input, report = sanitize(ctx)

            # The allowlist drops it -- no code anywhere had to know its name
            # in advance or recognise it as "the proxy for group_label".
            assert "regional_price_index" not in scoring_input
            assert "group_label" not in scoring_input
            assert set(scoring_input.keys()) == set(CANONICAL_FEATURE_NAMES)

            removed_names = {r.field for r in report.removed}
            assert "regional_price_index" in removed_names
            assert "group_label" in removed_names

    def test_proxy_feature_cannot_reach_the_scorecard_even_if_correlation_is_near_perfect(self):
        """Even a pathological, near-deterministic proxy (correlation ~1.0
        with group_label) is caught -- the allowlist's guarantee does not
        depend on how strong or subtle the correlation happens to be, unlike
        a statistical fairness filter that might only catch strong signals."""
        ctx = _context_with_proxy(group_label="A", proxy_value=999.0)
        scoring_input, report = sanitize(ctx)

        assert "regional_price_index" not in scoring_input
        removed = {r.field: r.reason for r in report.removed}
        assert "not on the scoring allowlist" in removed["regional_price_index"]
