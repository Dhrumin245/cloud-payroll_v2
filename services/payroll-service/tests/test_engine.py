from decimal import Decimal

import pytest

from app.engine import (
    ComponentInput,
    PayrollInput,
    calculate,
    calculate_run,
    prorated_gross,
    validate_days,
)

D = Decimal


def pay_input(**kw) -> PayrollInput:
    base = dict(
        employee_id=1,
        employee_code="EMP0001",
        employee_name="Asha",
        basic_pay=D("26000"),
        hra=D(0),
        conveyance_allowance=D(0),
        components=[],
        total_working_days=D(26),
    )
    return PayrollInput(
        **{
            **base,
            **{
                k: D(v) if isinstance(v, (int, str)) and k.endswith("days") else v
                for k, v in kw.items()
            },
        }
    )


def amounts(result):
    return {c.name: c.amount for c in result.components}


def test_full_month_pays_in_full():
    r = calculate(pay_input())
    assert r.gross_pay == D("26000.00") and r.net_pay == D("26000.00") and r.loss_of_pay_days == 0


def test_paid_leave_does_not_reduce_pay():
    # The legacy engine paid this person LESS unless HR counted the leave days as 'present'.
    r = calculate(pay_input(paid_leave_days=3))
    assert r.gross_pay == D("26000.00")
    assert (r.days_present, r.payable_days, r.loss_of_pay_days) == (D(23), D(26), D(0))


def test_unpaid_leave_is_loss_of_pay():
    r = calculate(pay_input(unpaid_leave_days=2))
    assert r.gross_pay == D("24000.00")  # 26000 x 24/26
    assert (r.loss_of_pay_days, r.payable_days) == (D(2), D(24))


def test_unexplained_absence_is_loss_of_pay_and_half_days_work():
    r = calculate(pay_input(absent_days="1.5"))
    assert r.gross_pay == D("24500.00") and r.payable_days == D("24.5")


def test_all_three_together():
    r = calculate(pay_input(paid_leave_days=3, unpaid_leave_days=2, absent_days=1))
    assert r.days_present == D(20)  # 26 - 3 - 2 - 1
    assert r.loss_of_pay_days == D(3) and r.payable_days == D(23)
    assert r.gross_pay == D("23000.00")


def test_every_fixed_part_and_allowance_is_prorated():
    r = calculate(
        pay_input(
            unpaid_leave_days=13,
            basic_pay=D("20000"),
            hra=D("8000"),
            conveyance_allowance=D("1600"),
            components=[ComponentInput("allowance", "Meal", D("2000"))],
        )
    )
    assert amounts(r) == {
        "Basic Pay": D("10000.00"),
        "HRA": D("4000.00"),
        "Conveyance Allowance": D("800.00"),
        "Meal": D("1000.00"),
    }
    assert r.gross_pay == D("15800.00")


def test_bonus_and_deductions_are_never_prorated():
    r = calculate(
        pay_input(
            unpaid_leave_days=13,
            components=[
                ComponentInput("earning", "Diwali Bonus", D("5000")),
                ComponentInput("deduction", "Loan EMI", D("1500")),
            ],
        )
    )
    assert amounts(r)["Diwali Bonus"] == D("5000.00") and amounts(r)["Loan EMI"] == D("1500.00")
    assert r.gross_pay == D("18000.00")  # 13000 prorated basic + 5000 bonus
    assert r.total_deductions == D("1500.00") and r.net_pay == D("16500.00")


def test_rounding_is_half_up_to_two_places():
    r = calculate(pay_input(basic_pay=D("1000"), unpaid_leave_days=1))  # 1000 x 25/26 = 961.538...
    assert r.gross_pay == D("961.54")


def test_negative_net_pay_is_shown_not_hidden():
    r = calculate(pay_input(components=[ComponentInput("deduction", "Advance", D("40000"))]))
    assert r.net_pay == D("-14000.00")


def test_day_counts_that_do_not_add_up_are_reported():
    bad = pay_input(paid_leave_days=20, unpaid_leave_days=5, absent_days=3)  # 28 > 26
    assert "exceeds the 26" in validate_days(bad)
    with pytest.raises(ValueError, match="Asha"):
        calculate(bad)
    assert validate_days(pay_input()) is None
    assert validate_days(pay_input(total_working_days=D(0))) == "the month has no working days"


def test_exactly_all_days_off_gives_zero_not_error():
    r = calculate(pay_input(unpaid_leave_days=26))
    assert r.gross_pay == D("0.00") and r.days_present == 0


def test_prorated_gross_matches_calculate_before_deductions():
    data = pay_input(
        unpaid_leave_days=2,
        hra=D("5000"),
        components=[ComponentInput("earning", "Bonus", D("100"))],
    )
    assert prorated_gross(data) == calculate(data).gross_pay


def test_run_totals():
    a = pay_input()
    b = pay_input(employee_id=2, employee_code="EMP0002", employee_name="Ravi", unpaid_leave_days=2)
    run = calculate_run([a, b])
    assert run.employee_count == 2
    assert run.total_gross == D("50000.00") and run.total_net_pay == D("50000.00")
