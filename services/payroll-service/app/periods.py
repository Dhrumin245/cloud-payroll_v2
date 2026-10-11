"""'YYYY-MM' period helpers. A period is stored as the first day of its month."""

import calendar
from datetime import date, timedelta

PERIOD_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"


def parse_period(value: str) -> date:
    year, month = int(value[:4]), int(value[5:7])
    return date(year, month, 1)


def format_period(period: date) -> str:
    return f"{period.year:04d}-{period.month:02d}"


def period_label(period: date) -> str:
    return period.strftime("%B %Y")


def last_day(period: date) -> date:
    return period.replace(day=calendar.monthrange(period.year, period.month)[1])


def working_days(period: date) -> int:
    """Every day of the month except Sundays (same 6-day-week rule as leave-service)."""
    last = last_day(period)
    return sum(
        1
        for offset in range((last - period).days + 1)
        if (period + timedelta(days=offset)).weekday() != 6
    )


def is_future(period: date, today: date | None = None) -> bool:
    """True for any month after the current one."""
    today = today or date.today()
    return (period.year, period.month) > (today.year, today.month)
