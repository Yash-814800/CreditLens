import pytest

from app.schemas.extraction import (
    ExtractedDate,
    ExtractedFloat,
    ExtractedInt,
    ExtractedStr,
    GigPayoutExtraction,
    GigPayoutWeek,
    UtilityBillExtraction,
    UtilityPaymentHistoryRow,
)
from app.services.ingestion.bank_parser import BankMetrics
from app.services.scoring.features import (
    build_features,
    gig_active_days_per_week,
    gig_tenure_weeks,
    gig_weekly_earnings_cv,
    income_reconciliation_ratio,
    utility_on_time_ratio,
    utility_tenure_months,
    verified_monthly_income_inr,
)

pytestmark = pytest.mark.unit


def _str_field(v):
    return ExtractedStr(value=v, confidence=1.0, legible=True)


def _date_field(v):
    return ExtractedDate(value=v, confidence=1.0, legible=True)


def _float_field(v):
    return ExtractedFloat(value=v, confidence=1.0, legible=True)


def _int_field(v):
    return ExtractedInt(value=v, confidence=1.0, legible=True)


def _make_gig(weeks, since="2025-01-01", period_end="2026-01-01", total=None):
    return GigPayoutExtraction(
        platform_name=_str_field("ZipRide Partner"),
        partner_name=_str_field("Test Partner"),
        partner_id=_str_field("ZIP-1"),
        partner_since=_date_field(since),
        report_period_start=_date_field("2025-12-01"),
        report_period_end=_date_field(period_end),
        weeks=weeks,
        total_net_payout_period=_float_field(
            total if total is not None else sum(w.net_payout for w in weeks)
        ),
        payout_account_last4=_str_field("1234"),
        suspected_instruction_text=False,
    )


def _week(net_payout, active_days=6):
    return GigPayoutWeek(
        week_start="2025-12-01",
        week_end="2025-12-07",
        active_days=active_days,
        trips_or_orders=20,
        gross_earnings=net_payout * 1.1,
        incentives=10,
        deductions=5,
        net_payout=net_payout,
    )


def _make_bill(connection="2024-01-01", bill_date="2026-01-01", history=None):
    return UtilityBillExtraction(
        utility_name=_str_field("Bharat Power Distribution (Demo)"),
        consumer_name=_str_field("Test User"),
        consumer_number=_str_field("CN01"),
        service_address=_str_field("Addr"),
        connection_date=_date_field(connection),
        meter_number=_str_field("MT01"),
        bill_date=_date_field(bill_date),
        due_date=_date_field("2026-01-20"),
        billing_period_start=_date_field("2025-12-01"),
        billing_period_end=_date_field("2025-12-30"),
        units_consumed=_int_field(100),
        line_items=[],
        total_amount_due=_float_field(1000.0),
        payment_history=history or [],
        suspected_instruction_text=False,
    )


def _history_row(month, status="On-time"):
    return UtilityPaymentHistoryRow(
        month=month, amount=1000.0, due_date=f"{month}-20", paid_date=f"{month}-18", status=status
    )


class TestUtilityFeatures:
    def test_tenure_months_hand_computed(self):
        bill = _make_bill(connection="2025-01-01", bill_date="2026-01-01")
        # 365 days / 30.44 ~= 11.99
        assert utility_tenure_months(bill) == pytest.approx(365 / 30.44, abs=0.01)

    def test_tenure_none_when_dates_missing(self):
        bill = _make_bill(connection="2025-01-01", bill_date="2026-01-01")
        bill.connection_date.value = None
        assert utility_tenure_months(bill) is None

    def test_on_time_ratio_uses_last_12_only(self):
        # 13 rows: first is "Late" (should be dropped), remaining 12 "On-time".
        history = [
            _history_row(f"2025-{m:02d}", "Late" if m == 1 else "On-time") for m in range(1, 13)
        ]
        history.append(_history_row("2026-01", "On-time"))
        bill = _make_bill(history=history)
        assert utility_on_time_ratio(bill) == 1.0

    def test_on_time_ratio_none_with_no_history(self):
        bill = _make_bill(history=[])
        assert utility_on_time_ratio(bill) is None


class TestGigFeatures:
    def test_active_days_mean(self):
        gig = _make_gig([_week(1000, active_days=5), _week(1000, active_days=7)])
        assert gig_active_days_per_week(gig) == 6.0

    def test_earnings_cv_zero_when_constant(self):
        gig = _make_gig([_week(1000), _week(1000), _week(1000)])
        assert gig_weekly_earnings_cv(gig) == 0.0

    def test_earnings_cv_none_with_single_week(self):
        gig = _make_gig([_week(1000)])
        assert gig_weekly_earnings_cv(gig) is None

    def test_tenure_weeks_hand_computed(self):
        gig = _make_gig([_week(1000)], since="2025-01-01", period_end="2025-01-15")
        assert gig_tenure_weeks(gig) == 2.0


class TestCrossDocumentFeatures:
    def test_income_reconciliation_ratio_capped(self):
        assert (
            income_reconciliation_ratio(
                bank_platform_credits_inr=3000, gig_total_net_payout_inr=1000
            )
            == 1.5
        )

    def test_income_reconciliation_ratio_exact(self):
        assert (
            income_reconciliation_ratio(
                bank_platform_credits_inr=800, gig_total_net_payout_inr=1000
            )
            == 0.8
        )

    def test_income_reconciliation_none_when_missing_a_side(self):
        assert (
            income_reconciliation_ratio(
                bank_platform_credits_inr=None, gig_total_net_payout_inr=1000
            )
            is None
        )
        assert (
            income_reconciliation_ratio(
                bank_platform_credits_inr=800, gig_total_net_payout_inr=None
            )
            is None
        )

    def test_verified_income_min_of_both_when_present(self):
        bank_metrics = BankMetrics(
            avg_daily_balance_inr=1000,
            low_balance_day_ratio=0.0,
            weekly_inflow_cv=None,
            total_platform_credits_inr=30000,  # -> monthly ~= 30000/30*30.44 ~= 30440
            platform_credit_count=4,
            account_last4="1234",
            running_balance_issues=[],
        )
        gig = _make_gig([_week(5000)] * 4, total=20000)  # -> monthly = 20000/4*4.345 = 21725
        result = verified_monthly_income_inr(
            bank_metrics=bank_metrics, bank_period_days=30, gig_payout=gig
        )
        bank_est = 30000 / 30 * 30.44
        gig_est = 20000 / 4 * 4.345
        assert result == round(min(bank_est, gig_est), 2)

    def test_verified_income_haircut_single_source(self):
        gig = _make_gig([_week(5000)] * 4, total=20000)
        result = verified_monthly_income_inr(
            bank_metrics=None, bank_period_days=None, gig_payout=gig
        )
        gig_est = 20000 / 4 * 4.345
        assert result == round(gig_est * 0.70, 2)

    def test_verified_income_none_with_no_documents(self):
        assert (
            verified_monthly_income_inr(bank_metrics=None, bank_period_days=None, gig_payout=None)
            is None
        )


class TestBuildFeaturesMissingDocs:
    def test_only_bank_present_leaves_gig_and_utility_features_none(self):
        bank_metrics = BankMetrics(
            avg_daily_balance_inr=2000,
            low_balance_day_ratio=0.1,
            weekly_inflow_cv=0.2,
            total_platform_credits_inr=0,
            platform_credit_count=0,
            account_last4="9999",
            running_balance_issues=[],
        )
        features = build_features(
            gig_payout=None, utility_bill=None, bank_metrics=bank_metrics, bank_period_days=180
        )
        assert features["avg_daily_balance_inr"] == 2000
        assert features["utility_tenure_months"] is None
        assert features["gig_active_days_per_week"] is None
        assert features["income_reconciliation_ratio"] is None
        assert features["authenticity_score"] is None  # populated only by the fraud layer (Phase 4)

    def test_all_documents_present_populates_every_dependent_feature(self):
        gig = _make_gig([_week(5000, 6)] * 4, total=20000)
        bill = _make_bill(history=[_history_row("2025-12")])
        bank_metrics = BankMetrics(
            avg_daily_balance_inr=3000,
            low_balance_day_ratio=0.0,
            weekly_inflow_cv=0.1,
            total_platform_credits_inr=18000,
            platform_credit_count=4,
            account_last4="1234",
            running_balance_issues=[],
        )
        features = build_features(
            gig_payout=gig, utility_bill=bill, bank_metrics=bank_metrics, bank_period_days=30
        )
        for name, value in features.items():
            if name == "authenticity_score":
                continue
            assert value is not None, f"{name} unexpectedly None with all documents present"
