"""Pure date rules, no database. Same rule as the legacy app: Sundays don't count as leave."""

from datetime import date, timedelta
from decimal import Decimal

MAX_SPAN_DAYS = 365


def count_leave_days(start: date, end: date, window_start: date, window_end: date) -> Decimal:
    """Non-Sunday days of [start, end] that fall inside [window_start, window_end]."""
    first, last = max(start, window_start), min(end, window_end)
    days = 0
    current = first
    while current <= last:
        if current.weekday() != 6:  # 6 = Sunday
            days += 1
        current += timedelta(days=1)
    return Decimal(days)


def days_by_year(start: date, end: date) -> dict[int, Decimal]:
    """Leave days per calendar year (a request over New Year is split between the two years)."""
    result: dict[int, Decimal] = {}
    for year in range(start.year, end.year + 1):
        days = count_leave_days(start, end, date(year, 1, 1), date(year, 12, 31))
        if days > 0:
            result[year] = days
    return result


def month_bounds(month: str) -> tuple[date, date]:
    """'2026-09' -> (2026-09-01, 2026-09-30)."""
    year, mon = int(month[:4]), int(month[5:7])
    first = date(year, mon, 1)
    nxt = date(year + (mon == 12), mon % 12 + 1, 1)
    return first, nxt - timedelta(days=1)
