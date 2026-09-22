"""BANK_STATEMENT document: a CSV, not an image.

First lines are `key,value` metadata (account holder, masked account number,
bank, period), then a blank line, then a `date,narration,ref,debit,credit,balance`
header and one row per transaction across ~180 days. The running balance is
always arithmetically consistent (each row's balance = previous balance -
debit + credit) -- this is asserted by tests and re-verified by the bank CSV
parser in Phase 3.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from synthgen.brands import BANK_NAME
from synthgen.calendar_utils import REFERENCE_DATE
from synthgen.schemas import PersonaMeta

_NARRATIONS_DEBIT = [
    "RENT PAYMENT NEFT",
    "MOBILE RECHARGE UPI",
    "GROCERY STORE UPI",
    "ATM CASH WDL",
    "ELECTRICITY BILL UPI",
    "DTH RECHARGE UPI",
]


@dataclass
class Txn:
    txn_date: date
    narration: str
    ref: str
    debit: float | None
    credit: float | None
    balance: float


def build_bank_data(
    rng: np.random.Generator,
    persona: PersonaMeta,
    account_last4: str,
    platform_name: str,
    days: int = 180,
    opening_balance: float = 6000.0,
    daily_spend_mean: float = 220.0,
    platform_credit_weekly_mean: float = 5000.0,
    platform_credit_cv: float = 0.2,
    customer_credit_mean: float = 900.0,
    as_of: date = REFERENCE_DATE,
    injected_platform_credits: list[tuple[date, float]] | None = None,
    prevent_overdraft: bool = False,
    cashflow_profile: str = "standard",
) -> tuple[dict, list[Txn]]:
    start = as_of - timedelta(days=days)
    balance = opening_balance
    rows: list[Txn] = []
    ref_counter = 100000 + int(rng.integers(0, 900000))

    injected = {d: amt for d, amt in (injected_platform_credits or [])}

    # `balance` is rounded to paise after EVERY transaction (not just when displayed) so the
    # stored running balance is always exactly prev_balance -/+ the stored debit/credit --
    # otherwise sub-paise rounding noise accumulates over ~180 days and the chain silently
    # stops reconciling, which is the opposite of what a "clean" fixture is for.
    balance = round(balance, 2)
    day = start
    week_anchor_offset = int(rng.integers(0, 7))

    if cashflow_profile == "blind_spot":
        while day <= as_of:
            day_i = (day - start).days
            if day_i % 7 == week_anchor_offset:
                amt = injected.get(day)
                if amt is None:
                    amt = 8000.0 if (day_i // 7) % 2 == 0 else 5000.0
                    amt = round(float(rng.normal(amt, amt * 0.04)), 2)
                amt = round(amt, 2)
                ref_counter += 1
                balance = round(balance + amt, 2)
                rows.append(
                    Txn(
                        day,
                        f"UPI/{platform_name.upper().replace(' ', '')} PAYOUT/{ref_counter}",
                        str(ref_counter),
                        None,
                        amt,
                        balance,
                    )
                )
                emi = round(amt * 0.45, 2)
                balance = round(balance - emi, 2)
                ref_counter += 1
                rows.append(Txn(day, "VEHICLE LEASE AUTO-DEBIT", str(ref_counter), emi, None, balance))
            elif day_i % 7 == (week_anchor_offset + 2) % 7:
                spend = round(balance * 0.60, 2)
                balance = round(balance - spend, 2)
                ref_counter += 1
                rows.append(Txn(day, "FUEL BULK PAYMENT", str(ref_counter), spend, None, balance))
            elif day_i % 7 == (week_anchor_offset + 3) % 7:
                if balance > 300:
                    spend = round(balance - 200.0, 2)
                    balance = round(balance - spend, 2)
                    ref_counter += 1
                    rows.append(Txn(day, "GROCERY / LIVING", str(ref_counter), spend, None, balance))
            day += timedelta(days=1)
    elif cashflow_profile == "resilient":
        while day <= as_of:
            day_i = (day - start).days
            if day_i % 7 == week_anchor_offset:
                amt = injected.get(day)
                if amt is None:
                    amt = round(float(rng.normal(platform_credit_weekly_mean, platform_credit_weekly_mean * 0.08)), 2)
                amt = round(amt, 2)
                ref_counter += 1
                balance = round(balance + amt, 2)
                rows.append(
                    Txn(
                        day,
                        f"UPI/{platform_name.upper().replace(' ', '')} PAYOUT/{ref_counter}",
                        str(ref_counter),
                        None,
                        amt,
                        balance,
                    )
                )
            if rng.random() < 0.70:
                spend = round(float(rng.normal(daily_spend_mean, daily_spend_mean * 0.15)), 2)
                if balance - spend >= 550.0:
                    balance = round(balance - spend, 2)
                    ref_counter += 1
                    rows.append(Txn(day, "UPI/MERCHANT/GROCERY", str(ref_counter), spend, None, balance))
                elif balance > 600:
                    spend = round(balance - 550.0, 2)
                    balance = 550.0
                    ref_counter += 1
                    rows.append(Txn(day, "UPI/MERCHANT/GROCERY", str(ref_counter), spend, None, balance))
            day += timedelta(days=1)
    else:
        while day <= as_of:
            # weekly platform payout (UPI credit) landing on a consistent weekday
            if (day - start).days % 7 == week_anchor_offset:
                amt = injected.get(day)
                if amt is None:
                    amt = max(
                        500.0,
                        float(
                            rng.normal(
                                platform_credit_weekly_mean,
                                platform_credit_weekly_mean * platform_credit_cv,
                            )
                        ),
                    )
                amt = round(amt, 2)
                ref_counter += 1
                balance = round(balance + amt, 2)
                rows.append(
                    Txn(
                        day,
                        f"UPI/{platform_name.upper().replace(' ', '')} PAYOUT/{ref_counter}",
                        str(ref_counter),
                        None,
                        amt,
                        balance,
                    )
                )
            # occasional customer UPI credit (e.g. personal transfer)
            if rng.random() < 0.12:
                amt = round(max(100.0, float(rng.normal(customer_credit_mean, customer_credit_mean * 0.4))), 2)
                ref_counter += 1
                balance = round(balance + amt, 2)
                rows.append(Txn(day, "UPI/CUSTOMER TRANSFER/IN", str(ref_counter), None, amt, balance))
            # daily-ish small debits
            if rng.random() < 0.55:
                label = rng.choice(_NARRATIONS_DEBIT)
                amt = round(max(30.0, float(rng.normal(daily_spend_mean, daily_spend_mean * 0.5))), 2)
                if prevent_overdraft and balance > 50:
                    amt = round(min(balance - 50.0, amt), 2)
                if not prevent_overdraft or (prevent_overdraft and balance > 50):
                    ref_counter += 1
                    balance = round(balance - amt, 2)
                    rows.append(Txn(day, str(label), str(ref_counter), amt, None, balance))
            day += timedelta(days=1)

    metadata = {
        "account_holder": persona.full_name,
        "account_number_masked": f"XXXXXXXX{account_last4}",
        "bank": BANK_NAME,
        "period_from": start.isoformat(),
        "period_to": as_of.isoformat(),
    }
    return metadata, rows


def to_csv_bytes(metadata: dict, rows: list[Txn]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    for k, v in metadata.items():
        w.writerow([k, v])
    w.writerow([])
    w.writerow(["date", "narration", "ref", "debit", "credit", "balance"])
    for r in rows:
        w.writerow(
            [
                r.txn_date.isoformat(),
                r.narration,
                r.ref,
                f"{r.debit:.2f}" if r.debit is not None else "",
                f"{r.credit:.2f}" if r.credit is not None else "",
                f"{r.balance:.2f}",
            ]
        )
    return buf.getvalue().encode("utf-8")


def to_visible_fields(metadata: dict, rows: list[Txn]) -> dict:
    return {
        **metadata,
        "transactions": [
            {
                "date": r.txn_date.isoformat(),
                "narration": r.narration,
                "ref": r.ref,
                "debit": r.debit,
                "credit": r.credit,
                "balance": r.balance,
            }
            for r in rows
        ],
    }
