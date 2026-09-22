"""Semantic / arithmetic consistency checks (CLAUDE.md Phase 4 check #3): does
the document's OWN internal math and chronology hold together? These catch
`edited_total_only` and `row_clone`-style tampers even when the pixel forensics
(tamper_radar.py) can't -- and, combined with the bank running-balance replay,
are the primary defense against the `consistent_edit` /
`inserted_fake_credit_with_rebalanced_chain` hard cases documented there.

Every check here is pure and works off already-validated Pydantic/dataclass
extraction objects -- no I/O, no LLM.
"""

from __future__ import annotations

import statistics
import uuid
from datetime import date

from app.schemas.extraction import GigPayoutExtraction, UtilityBillExtraction
from app.schemas.fraud import Finding
from app.services.ingestion.bank_parser import BankStatementData, verify_running_balance

_ARITH = "arithmetic_violation"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _finding(message: str, evidence: dict, policy: dict, document_id: uuid.UUID | None) -> Finding:
    return Finding(
        check_name="semantic_arithmetic",
        severity="MEDIUM",
        penalty_points=policy["penalties"][_ARITH],
        message=message,
        evidence=evidence,
        document_id=document_id,
    )


# ---------------------------------------------------------------------------
# Utility bill
# ---------------------------------------------------------------------------


def check_utility_bill(
    bill: UtilityBillExtraction, *, policy: dict, document_id: uuid.UUID | None = None
) -> list[Finding]:
    findings: list[Finding] = []
    tol = policy["arithmetic"]["utility_line_items_tolerance_inr"]

    line_item_values = [item.amount for item in bill.line_items]
    total = bill.total_amount_due.value
    if line_item_values and total is not None:
        computed = sum(line_item_values)
        if abs(computed - total) > tol:
            findings.append(
                _finding(
                    f"Utility bill line items sum to ₹{computed:.2f} but the printed "
                    f"total is ₹{total:.2f}.",
                    {"line_items_sum": round(computed, 2), "total_amount_due": total},
                    policy,
                    document_id,
                )
            )

    bill_date = _parse_date(bill.bill_date.value)
    due_date = _parse_date(bill.due_date.value)
    period_start = _parse_date(bill.billing_period_start.value)
    period_end = _parse_date(bill.billing_period_end.value)
    connection_date = _parse_date(bill.connection_date.value)

    if bill_date and period_end and bill_date < period_end:
        findings.append(
            _finding(
                "Bill date is before the billing period it covers ends.",
                {"bill_date": str(bill_date), "billing_period_end": str(period_end)},
                policy,
                document_id,
            )
        )
    if due_date and bill_date and due_date <= bill_date:
        findings.append(
            _finding(
                "Due date is not after the bill date.",
                {"bill_date": str(bill_date), "due_date": str(due_date)},
                policy,
                document_id,
            )
        )
    if period_start and period_end:
        days = (period_end - period_start).days
        min_days = policy["arithmetic"]["utility_period_days_min"]
        max_days = policy["arithmetic"]["utility_period_days_max"]
        if not (min_days <= days <= max_days):
            findings.append(
                _finding(
                    f"Billing period is {days} days, outside the plausible "
                    f"{min_days}-{max_days} day range.",
                    {"period_days": days, "min": min_days, "max": max_days},
                    policy,
                    document_id,
                )
            )
    if connection_date and bill_date and connection_date >= bill_date:
        findings.append(
            _finding(
                "Connection date is not before the bill date.",
                {"connection_date": str(connection_date), "bill_date": str(bill_date)},
                policy,
                document_id,
            )
        )

    findings.extend(_check_payment_history_contiguity(bill, policy, document_id))
    return findings


def _check_payment_history_contiguity(
    bill: UtilityBillExtraction, policy: dict, document_id: uuid.UUID | None
) -> list[Finding]:
    findings: list[Finding] = []
    rows = bill.payment_history
    months: list[tuple[int, int]] = []
    for row in rows:
        try:
            year_str, month_str = row.month.split("-")
            months.append((int(year_str), int(month_str)))
        except (ValueError, AttributeError):
            continue

    for i in range(1, len(months)):
        py, pm = months[i - 1]
        cy, cm = months[i]
        expected = (py, pm + 1) if pm < 12 else (py + 1, 1)
        if (cy, cm) != expected:
            findings.append(
                _finding(
                    f"Payment history month sequence is not contiguous at row {i} "
                    f"({rows[i - 1].month} -> {rows[i].month}).",
                    {"index": i, "previous_month": rows[i - 1].month, "month": rows[i].month},
                    policy,
                    document_id,
                )
            )

    # "paid_date not before the bill it pays": a payment cannot have been made
    # more than one full billing cycle (~35 days, with a small grace window)
    # before the due date it is recorded against -- a heuristic bound, not an
    # exact rule, documented here rather than asserted as precise.
    grace_days = 40
    for i, row in enumerate(rows):
        due = _parse_date(row.due_date)
        paid = _parse_date(row.paid_date) if row.paid_date else None
        if due and paid and (due - paid).days > grace_days:
            findings.append(
                _finding(
                    f"payment_history[{i}]: paid_date is implausibly far before its due_date.",
                    {"index": i, "due_date": row.due_date, "paid_date": row.paid_date},
                    policy,
                    document_id,
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Gig payout
# ---------------------------------------------------------------------------


def check_gig_payout(
    payout: GigPayoutExtraction, *, policy: dict, document_id: uuid.UUID | None = None
) -> list[Finding]:
    findings: list[Finding] = []
    tol = policy["arithmetic"]["gig_net_tolerance_inr"]

    for i, week in enumerate(payout.weeks):
        computed_net = week.gross_earnings + week.incentives - week.deductions
        if abs(computed_net - week.net_payout) > tol:
            findings.append(
                _finding(
                    f"week[{i}] ({week.week_start}..{week.week_end}): gross + incentives - "
                    f"deductions = ₹{computed_net:.2f} but printed net is ₹{week.net_payout:.2f}.",
                    {
                        "index": i,
                        "computed_net": round(computed_net, 2),
                        "printed_net": week.net_payout,
                    },
                    policy,
                    document_id,
                )
            )

    weekly_sum = sum(w.net_payout for w in payout.weeks)
    total = payout.total_net_payout_period.value
    if payout.weeks and total is not None and abs(weekly_sum - total) > tol:
        findings.append(
            _finding(
                f"Weekly net payouts sum to ₹{weekly_sum:.2f} but the printed period "
                f"total is ₹{total:.2f}.",
                {"weekly_sum": round(weekly_sum, 2), "period_total": total},
                policy,
                document_id,
            )
        )

    findings.extend(_check_week_period_contiguity(payout, policy, document_id))
    findings.extend(_check_earnings_outlier(payout, policy, document_id))
    return findings


def _check_week_period_contiguity(
    payout: GigPayoutExtraction, policy: dict, document_id: uuid.UUID | None
) -> list[Finding]:
    findings: list[Finding] = []
    parsed = [
        (i, _parse_date(w.week_start), _parse_date(w.week_end)) for i, w in enumerate(payout.weeks)
    ]
    for i, start, end in parsed:
        if start and end and end < start:
            findings.append(
                _finding(
                    f"week[{i}]: week_end is before week_start.",
                    {
                        "index": i,
                        "week_start": payout.weeks[i].week_start,
                        "week_end": payout.weeks[i].week_end,
                    },
                    policy,
                    document_id,
                )
            )
    for i in range(1, len(parsed)):
        _, _, prev_end = parsed[i - 1]
        _, cur_start, _ = parsed[i]
        if prev_end and cur_start and cur_start <= prev_end:
            findings.append(
                _finding(
                    f"week[{i}]: overlaps or is out of order with the previous week.",
                    {
                        "index": i,
                        "previous_week_end": payout.weeks[i - 1].week_end,
                        "week_start": payout.weeks[i].week_start,
                    },
                    policy,
                    document_id,
                )
            )
    return findings


def _check_earnings_outlier(
    payout: GigPayoutExtraction, policy: dict, document_id: uuid.UUID | None
) -> list[Finding]:
    """Robust (median/MAD) z-score outlier on net-payout-per-active-day across
    the reported weeks -- a single implausibly high week (consistent with an
    `amount_edit` that also patched the weekly total, so the sum-check above
    would miss it) still stands out against the applicant's OWN other weeks."""
    per_day = [
        w.net_payout / w.active_days for w in payout.weeks if w.active_days and w.active_days > 0
    ]
    if len(per_day) < 4:
        return []
    median = statistics.median(per_day)
    mad = statistics.median([abs(v - median) for v in per_day])
    if mad < 1e-6:
        return []
    threshold = policy["arithmetic"]["gig_earnings_outlier_z_threshold"]
    findings: list[Finding] = []
    for i, value in enumerate(per_day):
        robust_z = 0.6745 * (value - median) / mad
        if abs(robust_z) >= threshold:
            findings.append(
                _finding(
                    f"week[{i}]: net-payout-per-active-day (₹{value:.2f}) is a robust "
                    f"outlier against this applicant's own other weeks (median ₹{median:.2f}).",
                    {
                        "index": i,
                        "value": round(value, 2),
                        "median": round(median, 2),
                        "robust_z": round(robust_z, 2),
                    },
                    policy,
                    document_id,
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Bank statement
# ---------------------------------------------------------------------------


def check_bank_statement(
    stmt: BankStatementData, *, policy: dict, document_id: uuid.UUID | None = None
) -> list[Finding]:
    findings: list[Finding] = []
    tol = policy["arithmetic"]["bank_running_balance_tolerance_inr"]
    issues = verify_running_balance(stmt, tolerance=tol)
    for issue in issues:
        findings.append(
            _finding(
                f"Running balance breaks on {issue.txn_date}: "
                f"expected ₹{issue.expected_balance:.2f}, "
                f"statement shows ₹{issue.actual_balance:.2f}.",
                {
                    "index": issue.index,
                    "txn_date": str(issue.txn_date),
                    "expected_balance": issue.expected_balance,
                    "actual_balance": issue.actual_balance,
                    "delta": issue.delta,
                },
                policy,
                document_id,
            )
        )

    findings.extend(_check_monotonic_dates(stmt, policy, document_id))
    findings.extend(_check_duplicate_refs(stmt, policy, document_id))
    findings.extend(_check_credit_spike(stmt, policy, document_id))
    return findings


def _check_monotonic_dates(
    stmt: BankStatementData, policy: dict, document_id: uuid.UUID | None
) -> list[Finding]:
    """Transactions are parsed sorted by (date, ref) upstream, so a genuine
    out-of-order date can only mean two transactions on record for the exact
    same instant with duplicate/ambiguous refs, or a synthetic/malformed
    statement -- surfaced here as a low-severity data-quality flag."""
    findings: list[Finding] = []
    prev: date | None = None
    for i, txn in enumerate(stmt.transactions):
        if prev and txn.txn_date < prev:
            findings.append(
                _finding(
                    f"Transaction {i} is dated before the previous transaction.",
                    {"index": i, "txn_date": str(txn.txn_date), "previous_date": str(prev)},
                    policy,
                    document_id,
                )
            )
        prev = txn.txn_date
    return findings


def _check_duplicate_refs(
    stmt: BankStatementData, policy: dict, document_id: uuid.UUID | None
) -> list[Finding]:
    seen: dict[str, int] = {}
    findings: list[Finding] = []
    for i, txn in enumerate(stmt.transactions):
        if not txn.ref:
            continue
        if txn.ref in seen:
            findings.append(
                _finding(
                    f"Duplicate transaction reference {txn.ref!r} at rows {seen[txn.ref]} and {i}.",
                    {"ref": txn.ref, "first_index": seen[txn.ref], "second_index": i},
                    policy,
                    document_id,
                )
            )
        else:
            seen[txn.ref] = i
    return findings


def _check_credit_spike(
    stmt: BankStatementData, policy: dict, document_id: uuid.UUID | None
) -> list[Finding]:
    """A single credit far above the statement's own median WEEKLY inflow is
    surfaced as informational -- not proof of fraud (it could be a bonus, a
    loan, a gift), but exactly the kind of one-off `inserted_fake_credit`
    would produce, and worth a human's attention."""
    from collections import defaultdict
    from datetime import timedelta

    weekly: dict[date, float] = defaultdict(float)
    for txn in stmt.transactions:
        week_start = txn.txn_date - timedelta(days=txn.txn_date.weekday())
        weekly[week_start] += txn.credit or 0.0
    weekly_totals = [v for v in weekly.values() if v > 0]
    if len(weekly_totals) < 2:
        return []
    median_weekly = statistics.median(weekly_totals)
    if median_weekly <= 0:
        return []
    multiplier = policy["arithmetic"]["bank_spike_multiplier"]
    findings: list[Finding] = []
    for i, txn in enumerate(stmt.transactions):
        if txn.credit and txn.credit >= median_weekly * multiplier:
            findings.append(
                Finding(
                    check_name="semantic_arithmetic",
                    severity="LOW",
                    penalty_points=policy["penalties"][_ARITH],
                    message=(
                        f"A single credit of ₹{txn.credit:.2f} is "
                        f"{txn.credit / median_weekly:.1f}x the statement's own "
                        "median weekly inflow."
                    ),
                    evidence={
                        "index": i,
                        "credit": txn.credit,
                        "median_weekly_inflow": round(median_weekly, 2),
                    },
                    document_id=document_id,
                )
            )
    return findings
