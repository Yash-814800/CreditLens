"""Shared date/period math so gig, utility and bank documents agree on "today".

Every document in the corpus is generated as of the same fixed reference date
(rather than `date.today()`), so that regenerating the corpus on a different
day never changes any output -- required for the determinism tests.
"""

from __future__ import annotations

from datetime import date, timedelta

REFERENCE_DATE = date(2026, 9, 14)  # a Monday


def most_recent_sunday(as_of: date = REFERENCE_DATE) -> date:
    return as_of - timedelta(days=(as_of.weekday() + 1) % 7)


def last_n_weeks(n: int, as_of: date = REFERENCE_DATE) -> list[tuple[date, date]]:
    """Returns n (week_start=Monday, week_end=Sunday) tuples, oldest first."""
    end = most_recent_sunday(as_of)
    weeks = []
    for i in range(n):
        week_end = end - timedelta(days=7 * i)
        week_start = week_end - timedelta(days=6)
        weeks.append((week_start, week_end))
    weeks.reverse()
    return weeks


def last_n_months(n: int, as_of: date = REFERENCE_DATE) -> list[tuple[int, int]]:
    """Returns n (year, month) tuples ending at the month before `as_of`, oldest first."""
    months = []
    y, m = as_of.year, as_of.month
    for _ in range(n):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
        months.append((y, m))
    months.reverse()
    return months
