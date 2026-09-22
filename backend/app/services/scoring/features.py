"""Pure feature-builder functions: extracted documents + bank metrics -> the
canonical CLAUDE.md feature set. No I/O, no LLM, no DB access -- everything here
is a deterministic function of already-validated numbers, so Phase 5's scorecard
can treat these as ground truth inputs and Phase 5's hypothesis tests can call
them directly with synthetic profiles.

Every formula is also documented in docs/feature_definitions.md; keep both in
sync if you change one.

A feature is None (never a fabricated 0) whenever the document it depends on
is missing or the field inside it was unreadable -- Phase 5's scorecard treats
a missing factor as 0 points (neutral), not as a penalised bad value.
"""

from __future__ import annotations

import statistics
from datetime import date

from app.schemas.extraction import GigPayoutExtraction, UtilityBillExtraction
from app.services.ingestion.bank_parser import BankMetrics

WEEKS_PER_MONTH = 4.345  # 52 / 12, the standard weeks-in-a-month average
INCOME_RECONCILIATION_CAP = 1.5
UNVERIFIED_INCOME_HAIRCUT = 0.70  # single-source verified_monthly_income_inr discount
ON_TIME_STATUS = "On-time"
MAX_ON_TIME_HISTORY_ROWS = 12


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Utility-bill-derived features
# ---------------------------------------------------------------------------


def utility_tenure_months(bill: UtilityBillExtraction) -> float | None:
    """Months between the connection date and the bill date. >=12 months is the
    scorecard's top bin (see scorecard_v1.yaml, Phase 5)."""
    connected = _parse_date(bill.connection_date.value)
    billed = _parse_date(bill.bill_date.value)
    if connected is None or billed is None or billed < connected:
        return None
    return round((billed - connected).days / 30.44, 2)


def utility_on_time_ratio(bill: UtilityBillExtraction) -> float | None:
    """Fraction of the last <=12 payment-history rows marked "On-time". Older
    history beyond the last 12 months is ignored so a long-ago delinquency
    doesn't permanently cap an applicant who has since recovered."""
    if not bill.payment_history:
        return None
    recent = bill.payment_history[-MAX_ON_TIME_HISTORY_ROWS:]
    on_time = sum(1 for row in recent if row.status == ON_TIME_STATUS)
    return round(on_time / len(recent), 4)


# ---------------------------------------------------------------------------
# Gig-payout-derived features
# ---------------------------------------------------------------------------


def gig_active_days_per_week(payout: GigPayoutExtraction) -> float | None:
    if not payout.weeks:
        return None
    return round(statistics.fmean(w.active_days for w in payout.weeks), 2)


def gig_weekly_earnings_cv(payout: GigPayoutExtraction) -> float | None:
    """Coefficient of variation (population stdev / mean) of NET weekly payout
    across the reported weeks -- volatility of what the applicant actually
    takes home, not gross earnings (which ignores platform deductions)."""
    if len(payout.weeks) < 2:
        return None
    values = [w.net_payout for w in payout.weeks]
    mean = statistics.fmean(values)
    if mean == 0:
        return None
    return round(statistics.pstdev(values) / mean, 4)


def gig_tenure_weeks(payout: GigPayoutExtraction) -> float | None:
    """Weeks between the platform "partner since" date and the end of the
    reported period -- how long the applicant has actually been earning on the
    platform, not just how many weeks this one report happens to cover."""
    since = _parse_date(payout.partner_since.value)
    period_end = _parse_date(payout.report_period_end.value)
    if since is None or period_end is None or period_end < since:
        return None
    return round((period_end - since).days / 7, 2)


# ---------------------------------------------------------------------------
# Cross-document features
# ---------------------------------------------------------------------------


def income_reconciliation_ratio(
    *, bank_platform_credits_inr: float | None, gig_total_net_payout_inr: float | None
) -> float | None:
    """Bank credits tagged to the gig platform, divided by the platform's own
    declared net payout for the same period. 1.0 = perfectly reconciled; below
    1.0 means the bank shows less than the platform claims (a fraud/consistency
    signal); the ratio is capped at 1.5 so a bank statement covering a longer
    window than the payout report can't produce a runaway "too good" score.
    None when either document is missing (income_reconciliation_ratio is a
    cross-check, not a single-document feature -- it has no meaning with only
    one side of the comparison)."""
    if bank_platform_credits_inr is None or gig_total_net_payout_inr is None:
        return None
    if gig_total_net_payout_inr <= 0:
        return None
    ratio = bank_platform_credits_inr / gig_total_net_payout_inr
    return round(min(ratio, INCOME_RECONCILIATION_CAP), 4)


def verified_monthly_income_inr(
    *,
    bank_metrics: BankMetrics | None,
    bank_period_days: int | None,
    gig_payout: GigPayoutExtraction | None,
) -> float | None:
    """Conservative monthly income estimate.

    - Both documents present: the MIN of each document's own independent
      monthly-income estimate (bank's platform-tagged credits vs. the payout
      report's declared net payout, each annualised to a month) -- taking the
      lower of two independent estimates is deliberately conservative.
    - Only one document present: that document's monthly estimate, haircut by
      30% for being single-sourced and unreconciled.
    - Neither: None (Phase 5's scorecard then awards 0 points for this factor
      rather than penalising a merely-incomplete file)."""
    bank_monthly = None
    if bank_metrics is not None and bank_period_days and bank_metrics.platform_credit_count > 0:
        bank_monthly = bank_metrics.total_platform_credits_inr / bank_period_days * 30.44

    gig_monthly = None
    if gig_payout is not None and gig_payout.weeks:
        period_weeks = len(gig_payout.weeks)
        gig_monthly = (
            (gig_payout.total_net_payout_period.value or 0) / period_weeks * WEEKS_PER_MONTH
        )

    if bank_monthly is not None and gig_monthly is not None:
        return round(min(bank_monthly, gig_monthly), 2)
    if bank_monthly is not None:
        return round(bank_monthly * UNVERIFIED_INCOME_HAIRCUT, 2)
    if gig_monthly is not None:
        return round(gig_monthly * UNVERIFIED_INCOME_HAIRCUT, 2)
    return None


CANONICAL_FEATURE_NAMES = (
    "utility_tenure_months",
    "utility_on_time_ratio",
    "weekly_inflow_cv",
    "avg_daily_balance_inr",
    "low_balance_day_ratio",
    "gig_active_days_per_week",
    "gig_weekly_earnings_cv",
    "gig_tenure_weeks",
    "income_reconciliation_ratio",
    "authenticity_score",  # populated by the fraud layer (Phase 4), not here
    "verified_monthly_income_inr",
)


def build_features(
    *,
    gig_payout: GigPayoutExtraction | None,
    utility_bill: UtilityBillExtraction | None,
    bank_metrics: BankMetrics | None,
    bank_period_days: int | None,
) -> dict[str, float | None]:
    """Assemble the full canonical feature dict from whichever documents are
    present. Missing documents simply leave their dependent features as None."""
    features: dict[str, float | None] = dict.fromkeys(CANONICAL_FEATURE_NAMES)

    if utility_bill is not None:
        features["utility_tenure_months"] = utility_tenure_months(utility_bill)
        features["utility_on_time_ratio"] = utility_on_time_ratio(utility_bill)

    if bank_metrics is not None:
        features["weekly_inflow_cv"] = bank_metrics.weekly_inflow_cv
        features["avg_daily_balance_inr"] = bank_metrics.avg_daily_balance_inr
        features["low_balance_day_ratio"] = bank_metrics.low_balance_day_ratio

    if gig_payout is not None:
        features["gig_active_days_per_week"] = gig_active_days_per_week(gig_payout)
        features["gig_weekly_earnings_cv"] = gig_weekly_earnings_cv(gig_payout)
        features["gig_tenure_weeks"] = gig_tenure_weeks(gig_payout)

    bank_platform_credits = (
        bank_metrics.total_platform_credits_inr
        if bank_metrics is not None and bank_metrics.platform_credit_count > 0
        else None
    )
    gig_total_payout = gig_payout.total_net_payout_period.value if gig_payout is not None else None
    features["income_reconciliation_ratio"] = income_reconciliation_ratio(
        bank_platform_credits_inr=bank_platform_credits, gig_total_net_payout_inr=gig_total_payout
    )

    features["verified_monthly_income_inr"] = verified_monthly_income_inr(
        bank_metrics=bank_metrics, bank_period_days=bank_period_days, gig_payout=gig_payout
    )

    return features
