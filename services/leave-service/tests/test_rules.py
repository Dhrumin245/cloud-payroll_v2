from datetime import date
from decimal import Decimal

from app.leave_rules import count_leave_days, days_by_year, month_bounds


def test_count_skips_sundays():
    assert count_leave_days(
        date(2026, 10, 5), date(2026, 10, 11), date(2026, 1, 1), date(2026, 12, 31)
    ) == Decimal(6)
    assert count_leave_days(
        date(2026, 10, 11), date(2026, 10, 11), date(2026, 1, 1), date(2026, 12, 31)
    ) == Decimal(0)


def test_count_clips_to_window():
    assert count_leave_days(
        date(2026, 9, 28), date(2026, 10, 3), date(2026, 10, 1), date(2026, 10, 31)
    ) == Decimal(3)
    assert count_leave_days(
        date(2026, 9, 1), date(2026, 9, 5), date(2026, 10, 1), date(2026, 10, 31)
    ) == Decimal(0)


def test_days_by_year_splits_at_new_year():
    assert days_by_year(date(2026, 12, 28), date(2027, 1, 2)) == {
        2026: Decimal(4),
        2027: Decimal(2),
    }
    assert days_by_year(date(2026, 10, 11), date(2026, 10, 11)) == {}  # a lone Sunday


def test_month_bounds():
    assert month_bounds("2026-02") == (date(2026, 2, 1), date(2026, 2, 28))
    assert month_bounds("2028-02") == (date(2028, 2, 1), date(2028, 2, 29))
    assert month_bounds("2026-12") == (date(2026, 12, 1), date(2026, 12, 31))
