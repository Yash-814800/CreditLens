import pytest

from app.schemas.extraction import (
    ExtractedDate,
    ExtractedFloat,
    ExtractedInt,
    ExtractedStr,
    GigPayoutExtraction,
    GigPayoutWeek,
    UtilityBillExtraction,
    UtilityLineItem,
    UtilityPaymentHistoryRow,
)
from app.services.fraud.policy import load_fraud_policy
from app.services.fraud.semantic_checks import (
    check_bank_statement,
    check_gig_payout,
    check_utility_bill,
)
from app.services.ingestion.bank_parser import BankStatementData, BankTransaction

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def policy():
    return load_fraud_policy()


def _str(v):
    return ExtractedStr(value=v, confidence=1.0, legible=True)


def _date(v):
    return ExtractedDate(value=v, confidence=1.0, legible=True)


def _float(v):
    return ExtractedFloat(value=v, confidence=1.0, legible=True)


def _int(v):
    return ExtractedInt(value=v, confidence=1.0, legible=True)


def _clean_gig_payout() -> GigPayoutExtraction:
    return GigPayoutExtraction(
        platform_name=_str("ZipRide Partner"),
        partner_name=_str("Aarav Mehta"),
        partner_id=_str("ZIP-001"),
        partner_since=_date("2024-01-01"),
        report_period_start=_date("2025-09-01"),
        report_period_end=_date("2025-09-28"),
        weeks=[
            GigPayoutWeek(
                week_start="2025-09-01",
                week_end="2025-09-07",
                active_days=6,
                trips_or_orders=80,
                gross_earnings=8000.0,
                incentives=500.0,
                deductions=200.0,
                net_payout=8300.0,
            ),
            GigPayoutWeek(
                week_start="2025-09-08",
                week_end="2025-09-14",
                active_days=6,
                trips_or_orders=82,
                gross_earnings=8100.0,
                incentives=400.0,
                deductions=250.0,
                net_payout=8250.0,
            ),
        ],
        total_net_payout_period=_float(16550.0),
        payout_account_last4=_str("1234"),
        suspected_instruction_text=False,
    )


class TestGigPayoutChecks:
    def test_clean_gig_payout_has_no_findings(self, policy):
        assert check_gig_payout(_clean_gig_payout(), policy=policy) == []

    def test_net_payout_arithmetic_violation_is_flagged(self, policy):
        payout = _clean_gig_payout()
        payout.weeks[0].net_payout = 999999.0  # no longer gross+incentives-deductions
        findings = check_gig_payout(payout, policy=policy)
        assert any(f.check_name == "semantic_arithmetic" for f in findings)

    def test_weekly_sum_vs_period_total_mismatch_is_flagged(self, policy):
        payout = _clean_gig_payout()
        payout.total_net_payout_period = _float(1.0)
        findings = check_gig_payout(payout, policy=policy)
        assert any("period total" in f.message for f in findings)

    def test_overlapping_weeks_are_flagged(self, policy):
        payout = _clean_gig_payout()
        payout.weeks[1].week_start = "2025-09-05"  # overlaps week[0]'s 09-01..09-07
        findings = check_gig_payout(payout, policy=policy)
        assert any("overlaps" in f.message for f in findings)

    def test_earnings_outlier_is_flagged(self, policy):
        payout = _clean_gig_payout()
        # Pad with several weeks with SLIGHT natural variation (identical values
        # collapse the median-absolute-deviation to zero, which is degenerate,
        # not realistic) so one extreme week is a clear robust-z outlier.
        months = ["10", "11", "12", "01"]
        for i, net in enumerate([8100.0, 8400.0, 8250.0, 8350.0]):
            payout.weeks.append(
                GigPayoutWeek(
                    week_start=f"2025-{months[i]}-01",
                    week_end=f"2025-{months[i]}-07",
                    active_days=6,
                    trips_or_orders=80,
                    gross_earnings=net - 300.0,
                    incentives=500.0,
                    deductions=200.0,
                    net_payout=net,
                )
            )
        payout.weeks.append(
            GigPayoutWeek(
                week_start="2025-11-01",
                week_end="2025-11-07",
                active_days=1,
                trips_or_orders=2,
                gross_earnings=100000.0,
                incentives=0.0,
                deductions=0.0,
                net_payout=100000.0,
            )
        )
        payout.total_net_payout_period = _float(sum(w.net_payout for w in payout.weeks))
        findings = check_gig_payout(payout, policy=policy)
        assert any("outlier" in f.message for f in findings)


def _clean_utility_bill() -> UtilityBillExtraction:
    return UtilityBillExtraction(
        utility_name=_str("Bharat Power Distribution (Demo)"),
        consumer_name=_str("Aarav Mehta"),
        consumer_number=_str("CN00001"),
        service_address=_str("14, Whitefield, Bengaluru - 560066"),
        connection_date=_date("2023-01-01"),
        meter_number=_str("MT00001"),
        bill_date=_date("2025-09-25"),
        due_date=_date("2025-10-15"),
        billing_period_start=_date("2025-08-20"),
        billing_period_end=_date("2025-09-19"),
        units_consumed=_int(180),
        line_items=[
            UtilityLineItem(label="Energy charge", amount=1200.0),
            UtilityLineItem(label="Fixed charge", amount=100.0),
        ],
        total_amount_due=_float(1300.0),
        payment_history=[
            UtilityPaymentHistoryRow(
                month="2025-07",
                amount=1200.0,
                due_date="2025-07-20",
                paid_date="2025-07-19",
                status="On-time",
            ),
            UtilityPaymentHistoryRow(
                month="2025-08",
                amount=1250.0,
                due_date="2025-08-20",
                paid_date="2025-08-18",
                status="On-time",
            ),
        ],
        suspected_instruction_text=False,
    )


class TestUtilityBillChecks:
    def test_clean_bill_has_no_findings(self, policy):
        assert check_utility_bill(_clean_utility_bill(), policy=policy) == []

    def test_line_items_not_summing_to_total_is_flagged(self, policy):
        bill = _clean_utility_bill()
        bill.total_amount_due = _float(50000.0)
        findings = check_utility_bill(bill, policy=policy)
        assert any("line items sum" in f.message for f in findings)

    def test_due_date_before_bill_date_is_flagged(self, policy):
        bill = _clean_utility_bill()
        bill.due_date = _date("2025-01-01")
        findings = check_utility_bill(bill, policy=policy)
        assert any("Due date" in f.message for f in findings)

    def test_implausible_billing_period_length_is_flagged(self, policy):
        bill = _clean_utility_bill()
        bill.billing_period_start = _date("2025-01-01")
        bill.billing_period_end = _date("2025-09-19")  # way more than 35 days
        findings = check_utility_bill(bill, policy=policy)
        assert any("Billing period" in f.message for f in findings)

    def test_non_contiguous_payment_history_is_flagged(self, policy):
        bill = _clean_utility_bill()
        bill.payment_history.append(
            UtilityPaymentHistoryRow(
                month="2025-11",
                amount=1300.0,
                due_date="2025-11-20",
                paid_date="2025-11-19",
                status="On-time",
            )
        )  # skips 2025-09, 2025-10
        findings = check_utility_bill(bill, policy=policy)
        assert any("not contiguous" in f.message for f in findings)


def _clean_bank_statement() -> BankStatementData:
    from datetime import date

    transactions = [
        BankTransaction(
            txn_date=date(2025, 9, 1),
            narration="UPI/ZIPRIDE PAYOUT/xyz",
            ref="R1",
            debit=None,
            credit=8300.0,
            balance=8300.0,
        ),
        BankTransaction(
            txn_date=date(2025, 9, 3),
            narration="ATM WDL",
            ref="R2",
            debit=2000.0,
            credit=None,
            balance=6300.0,
        ),
        BankTransaction(
            txn_date=date(2025, 9, 8),
            narration="UPI/ZIPRIDE PAYOUT/xyz",
            ref="R3",
            debit=None,
            credit=8250.0,
            balance=14550.0,
        ),
    ]
    return BankStatementData(
        account_holder="Aarav Mehta",
        account_number_masked="XXXXXXXX1234",
        bank="Demo Sahakari Bank",
        period_from=date(2025, 9, 1),
        period_to=date(2025, 9, 8),
        transactions=transactions,
    )


class TestBankStatementChecks:
    def test_clean_statement_has_no_findings(self, policy):
        assert check_bank_statement(_clean_bank_statement(), policy=policy) == []

    def test_broken_running_balance_is_flagged(self, policy):
        stmt = _clean_bank_statement()
        stmt.transactions[-1] = BankTransaction(
            txn_date=stmt.transactions[-1].txn_date,
            narration=stmt.transactions[-1].narration,
            ref=stmt.transactions[-1].ref,
            debit=None,
            credit=8250.0,
            balance=999999.0,  # breaks the chain
        )
        findings = check_bank_statement(stmt, policy=policy)
        assert any("Running balance" in f.message for f in findings)

    def test_duplicate_ref_is_flagged(self, policy):
        stmt = _clean_bank_statement()
        stmt.transactions[1] = BankTransaction(
            txn_date=stmt.transactions[1].txn_date,
            narration=stmt.transactions[1].narration,
            ref="R1",  # duplicate of transactions[0]'s ref
            debit=stmt.transactions[1].debit,
            credit=stmt.transactions[1].credit,
            balance=stmt.transactions[1].balance,
        )
        findings = check_bank_statement(stmt, policy=policy)
        assert any("Duplicate transaction reference" in f.message for f in findings)

    def test_large_credit_spike_is_flagged(self, policy):
        from datetime import date

        transactions = [
            BankTransaction(
                txn_date=date(2025, 9, 1),
                narration="UPI credit",
                ref="R1",
                debit=None,
                credit=1000.0,
                balance=1000.0,
            ),
            BankTransaction(
                txn_date=date(2025, 9, 8),
                narration="UPI credit",
                ref="R2",
                debit=None,
                credit=1000.0,
                balance=2000.0,
            ),
            BankTransaction(
                txn_date=date(2025, 9, 15),
                narration="UPI credit",
                ref="R3",
                debit=None,
                credit=1000.0,
                balance=3000.0,
            ),
            BankTransaction(
                txn_date=date(2025, 9, 22),
                narration="Suspicious credit",
                ref="R4",
                debit=None,
                credit=50000.0,
                balance=53000.0,
            ),
        ]
        stmt = BankStatementData(
            account_holder="Test",
            account_number_masked="XXXXXXXX0000",
            bank="Demo Sahakari Bank",
            period_from=date(2025, 9, 1),
            period_to=date(2025, 9, 22),
            transactions=transactions,
        )
        findings = check_bank_statement(stmt, policy=policy)
        assert any("median weekly inflow" in f.message for f in findings)
