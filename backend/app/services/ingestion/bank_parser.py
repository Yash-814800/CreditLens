"""Deterministic bank/UPI CSV parsing and cash-flow analytics. No LLM involved
anywhere in this module -- every number here is arithmetic on the applicant's
own numbers (FinBox BankConnect-style deterministic cash-flow analysis, not a
model's opinion of them). See docs/feature_definitions.md for exact formulas.
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.services.ingestion.validation import UploadValidationError, validate_csv_hardened

LOW_BALANCE_THRESHOLD_INR = 500.0


@dataclass(frozen=True)
class BankTransaction:
    txn_date: date
    narration: str
    ref: str
    debit: float | None
    credit: float | None
    balance: float


@dataclass(frozen=True)
class BankStatementData:
    account_holder: str
    account_number_masked: str
    bank: str
    period_from: date
    period_to: date
    transactions: list[BankTransaction]


@dataclass(frozen=True)
class RunningBalanceIssue:
    index: int
    txn_date: date
    expected_balance: float
    actual_balance: float
    delta: float


@dataclass(frozen=True)
class BankMetrics:
    avg_daily_balance_inr: float
    low_balance_day_ratio: float
    weekly_inflow_cv: float | None
    total_platform_credits_inr: float
    platform_credit_count: int
    account_last4: str
    running_balance_issues: list[RunningBalanceIssue]

    @property
    def running_balance_is_consistent(self) -> bool:
        return len(self.running_balance_issues) == 0


def _parse_amount(raw: str) -> float | None:
    raw = (raw or "").strip().lstrip("'")  # strip the CSV-injection-neutralising apostrophe
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError as exc:
        raise UploadValidationError(f"bank CSV has a non-numeric amount: {raw!r}") from exc


def parse_bank_csv(text: str) -> BankStatementData:
    meta, rows = validate_csv_hardened(text)

    required_meta = {"account_holder", "account_number_masked", "bank", "period_from", "period_to"}
    missing = required_meta - meta.keys()
    if missing:
        raise UploadValidationError(f"bank CSV metadata missing fields: {sorted(missing)}")

    required_columns = {"date", "narration", "ref", "debit", "credit", "balance"}
    if rows and not required_columns.issubset(rows[0].keys()):
        raise UploadValidationError(
            f"bank CSV header missing columns: {sorted(required_columns - rows[0].keys())}"
        )

    transactions: list[BankTransaction] = []
    for row in rows:
        try:
            txn_date = datetime.strptime(row["date"].strip().lstrip("'"), "%Y-%m-%d").date()
        except ValueError as exc:
            raise UploadValidationError(
                f"bank CSV has an unparsable date: {row['date']!r}"
            ) from exc
        balance = _parse_amount(row["balance"])
        if balance is None:
            raise UploadValidationError("bank CSV transaction row is missing a running balance")
        transactions.append(
            BankTransaction(
                txn_date=txn_date,
                narration=row["narration"].strip().lstrip("'"),
                ref=row["ref"].strip().lstrip("'"),
                debit=_parse_amount(row["debit"]),
                credit=_parse_amount(row["credit"]),
                balance=balance,
            )
        )

    transactions.sort(key=lambda t: (t.txn_date, t.ref))

    return BankStatementData(
        account_holder=meta["account_holder"],
        account_number_masked=meta["account_number_masked"],
        bank=meta["bank"],
        period_from=datetime.strptime(meta["period_from"], "%Y-%m-%d").date(),
        period_to=datetime.strptime(meta["period_to"], "%Y-%m-%d").date(),
        transactions=transactions,
    )


def account_last4(account_number_masked: str) -> str:
    digits = re.sub(r"\D", "", account_number_masked)
    return digits[-4:] if len(digits) >= 4 else digits


def verify_running_balance(
    stmt: BankStatementData, tolerance: float = 0.01
) -> list[RunningBalanceIssue]:
    """Replay debit/credit against the previous row's own stated balance. A clean
    statement's chain must reconcile to within a paisa-rounding tolerance;
    anything else is exactly what Phase 4's arithmetic-consistency fraud check
    (and the `inserted_fake_credit_with_rebalanced_chain` hard case) is testing."""
    issues: list[RunningBalanceIssue] = []
    running: float | None = None
    for i, txn in enumerate(stmt.transactions):
        if running is not None:
            expected = running + (txn.credit or 0.0) - (txn.debit or 0.0)
            if abs(expected - txn.balance) > tolerance:
                issues.append(
                    RunningBalanceIssue(
                        index=i,
                        txn_date=txn.txn_date,
                        expected_balance=round(expected, 2),
                        actual_balance=txn.balance,
                        delta=round(txn.balance - expected, 2),
                    )
                )
        running = txn.balance
    return issues


def compute_avg_daily_balance(stmt: BankStatementData) -> tuple[float, float]:
    """Forward-fill the end-of-day balance over every calendar day in the
    statement period (not just days with a transaction), then average.
    Returns (avg_daily_balance_inr, low_balance_day_ratio)."""
    if not stmt.transactions:
        raise UploadValidationError("cannot compute balance metrics with zero transactions")

    eod_by_date: dict[date, float] = {}
    for txn in stmt.transactions:
        eod_by_date[txn.txn_date] = txn.balance  # transactions are sorted; last one per day wins

    all_days = _date_range(stmt.period_from, stmt.period_to)
    daily_balances: list[float] = []
    last_known = stmt.transactions[0].balance
    for day in all_days:
        if day in eod_by_date:
            last_known = eod_by_date[day]
        daily_balances.append(last_known)

    avg = statistics.fmean(daily_balances)
    low_ratio = sum(1 for b in daily_balances if b < LOW_BALANCE_THRESHOLD_INR) / len(
        daily_balances
    )
    return round(avg, 2), round(low_ratio, 4)


def compute_weekly_inflow_cv(stmt: BankStatementData) -> float | None:
    """Coefficient of variation (std/mean) of total CREDIT amount per calendar
    week (Mon-Sun), counting COMPLETE weeks only -- a statement's first/last
    partial week would otherwise understate that week's real inflow and
    inflate volatility for a reason that has nothing to do with the applicant.
    "Income" here means every credit line in the statement (not just
    platform-tagged ones): weekly_inflow_cv is a general cash-inflow-stability
    signal, distinct from gig_weekly_earnings_cv (Phase 3 feature builder),
    which is computed from the gig-payout document's own declared weekly
    earnings instead. Returns None if fewer than 2 complete weeks exist."""
    weekly_credits: dict[date, float] = defaultdict(float)
    for txn in stmt.transactions:
        week_start = txn.txn_date - timedelta(days=txn.txn_date.weekday())
        weekly_credits[week_start] += txn.credit or 0.0

    complete_weeks = [
        total
        for week_start, total in sorted(weekly_credits.items())
        if week_start >= stmt.period_from and (week_start + timedelta(days=6)) <= stmt.period_to
    ]
    if len(complete_weeks) < 2:
        return None
    mean = statistics.fmean(complete_weeks)
    if mean == 0:
        return None
    stdev = statistics.pstdev(complete_weeks)
    return round(stdev / mean, 4)


def _normalize_platform_token(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", name.upper())


def find_platform_credits(stmt: BankStatementData, platform_name: str) -> tuple[float, int]:
    """Sum + count of credit transactions whose narration references the given
    gig-platform name. Narrations render platform names with spaces/punctuation
    stripped (see datagen's bank_statement.py), so matching normalises both
    sides to bare alphanumerics before comparing -- documented in
    docs/feature_definitions.md as the exact definition of "platform-tagged
    credit" that income_reconciliation_ratio is built from."""
    token = _normalize_platform_token(platform_name)
    if not token:
        return 0.0, 0
    total = 0.0
    count = 0
    for txn in stmt.transactions:
        if txn.credit and token in _normalize_platform_token(txn.narration):
            total += txn.credit
            count += 1
    return round(total, 2), count


def _date_range(start: date, end: date) -> list[date]:
    if end < start:
        raise UploadValidationError("bank CSV period_to is before period_from")
    days = (end - start).days + 1
    return [start + timedelta(days=i) for i in range(days)]


def analyze_bank_statement(
    stmt: BankStatementData, *, gig_platform_name: str | None = None
) -> BankMetrics:
    avg_daily_balance, low_balance_ratio = compute_avg_daily_balance(stmt)
    weekly_cv = compute_weekly_inflow_cv(stmt)
    running_issues = verify_running_balance(stmt)
    platform_total, platform_count = (
        find_platform_credits(stmt, gig_platform_name) if gig_platform_name else (0.0, 0)
    )
    return BankMetrics(
        avg_daily_balance_inr=avg_daily_balance,
        low_balance_day_ratio=low_balance_ratio,
        weekly_inflow_cv=weekly_cv,
        total_platform_credits_inr=platform_total,
        platform_credit_count=platform_count,
        account_last4=account_last4(stmt.account_number_masked),
        running_balance_issues=running_issues,
    )
