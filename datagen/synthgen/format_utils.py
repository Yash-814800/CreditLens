"""Shared display formatting so negative rupee amounts read "-₹15.19", not
the arithmetically-correct-but-wrong-looking "₹-15.19"."""

from __future__ import annotations


def fmt_inr(amount: float) -> str:
    sign = "-" if amount < 0 else ""
    return f"{sign}₹{abs(amount):,.2f}"
