from decimal import Decimal

from app.clients import LeaveDays
from tests.conftest import (
    ADMIN,
    EMP10,
    MANAGER,
    PERIOD,
    component,
    employee,
    line,
    run_payroll,
)


def test_working_days_in_august_2026_is_26():
    from app.periods import parse_period, working_days

    assert working_days(parse_period(PERIOD)) == 26


def test_full_run_with_loss_of_pay(client, fake_employees, fake_leave):
    fake_employees.staff = [
        employee(10, "EMP0010", "Priya Shah", basic="26000"),
        employee(20, "EMP0020", "Ravi Mehta", basic="52000", hra="26000"),
    ]
    fake_leave.days = {
        10: LeaveDays(paid_days=Decimal(3), unpaid_days=Decimal(2)),  # paid leave is free, 2 unpaid
    }
    r = run_payroll(client)
    assert r.status_code == 201
    body = r.json()
    assert (
        body["period"] == PERIOD and body["status"] == "completed" and body["employee_count"] == 2
    )
    assert body["run_by_user_id"] == 100

    priya = line(body, 10)
    assert priya["paid_leave_days"] == "3.0" and priya["unpaid_leave_days"] == "2.0"
    assert priya["loss_of_pay_days"] == "2.0" and priya["payable_days"] == "24.0"
    assert priya["days_present"] == "21.0" and priya["total_working_days"] == "26.0"
    assert priya["gross_pay"] == "24000.00"  # 26000 x 24/26
    assert component(priya, "Basic Pay")["amount"] == "24000.00"

    ravi = line(body, 20)  # no leave at all
    assert ravi["gross_pay"] == "78000.00" and ravi["loss_of_pay_days"] == "0.0"
    assert body["total_gross"] == "102000.00" and body["total_net_pay"] == "102000.00"


def test_recorded_absence_adds_to_loss_of_pay(client, fake_employees, fake_leave):
    fake_employees.staff = [employee(10, basic="26000")]
    fake_leave.days = {10: LeaveDays(Decimal(0), Decimal(1))}
    client.put(f"/attendance/10/{PERIOD}", json={"days_absent": "1.5"}, headers=MANAGER)
    li = line(run_payroll(client).json())
    assert li["absent_days"] == "1.5" and li["loss_of_pay_days"] == "2.5"
    assert li["gross_pay"] == "23500.00"  # 26000 x 23.5/26


def test_variable_pay_is_added_unprorated(client, fake_employees, fake_leave):
    fake_employees.staff = [employee(10, basic="26000")]
    fake_leave.days = {10: LeaveDays(Decimal(0), Decimal(13))}  # half the month unpaid
    for body in (
        {
            "employee_id": 10,
            "period": PERIOD,
            "component_type": "earning",
            "name": "Bonus",
            "amount": "5000",
        },
        {
            "employee_id": 10,
            "period": PERIOD,
            "component_type": "deduction",
            "name": "Advance",
            "amount": "1000",
        },
    ):
        assert client.post("/variable-pay", json=body, headers=ADMIN).status_code == 201
    li = line(run_payroll(client).json())
    assert li["gross_pay"] == "18000.00" and li["total_deductions"] == "1000.00"
    assert li["net_pay"] == "17000.00"


def test_salary_components_from_employee_service(client, fake_employees):
    comps = [("allowance", "Meal", Decimal("2600")), ("deduction", "Loan", Decimal("500"))]
    fake_employees.staff = [employee(10, basic="26000", hra="13000", conv="1600", components=comps)]
    li = line(run_payroll(client).json())
    assert li["gross_pay"] == "43200.00" and li["total_deductions"] == "500.00"
    assert [c["name"] for c in li["components"]] == [
        "Basic Pay",
        "HRA",
        "Conveyance Allowance",
        "Meal",
        "Loan",
    ]


def test_statutory_deductions_use_prorated_gross(client, fake_employees, fake_leave):
    fake_employees.staff = [employee(10, basic="20000")]
    fake_leave.days = {10: LeaveDays(Decimal(0), Decimal(13))}  # gross becomes 10000
    client.put(
        "/settings/statutory",
        json={"pf_enabled": True, "esi_enabled": True, "pt_enabled": False, "pt_state": "MH"},
        headers=ADMIN,
    )
    li = line(run_payroll(client).json())
    assert li["gross_pay"] == "10000.00"
    # PF: 12% of FULL basic 20000 = 2400, capped at 1800. ESI: 0.75% of prorated gross 10000 = 75.
    assert component(li, "Provident Fund (PF)")["amount"] == "1800.00"
    assert component(li, "Employee State Insurance (ESI)")["amount"] == "75.00"
    assert li["total_deductions"] == "1875.00" and li["net_pay"] == "8125.00"


def test_calls_downstream_with_the_admin_token_and_month_end(client, fake_employees, fake_leave):
    fake_employees.staff = [employee(10)]
    run_payroll(client)
    emp_call, leave_call = fake_employees.calls[0], fake_leave.calls[0]
    token = ADMIN["Authorization"].removeprefix("Bearer ")
    assert emp_call == ("payroll_data", "2026-08-31", token)  # salary in effect on the last day
    assert leave_call == ("approved", PERIOD, token)


def test_second_run_for_same_month_is_refused(client, fake_employees):
    fake_employees.staff = [employee(10)]
    assert run_payroll(client).status_code == 201
    r = run_payroll(client)
    assert r.status_code == 409 and "already been processed" in r.json()["detail"]
    assert len(client.get("/payroll/runs", headers=ADMIN).json()) == 1


def test_future_month_is_refused_but_current_month_is_allowed(client, fake_employees):
    fake_employees.staff = [employee(10)]
    assert run_payroll(client, "2099-01").status_code == 409
    from datetime import date

    today = date.today()
    assert run_payroll(client, f"{today.year:04d}-{today.month:02d}").status_code == 201


def test_bad_period_format_is_422(client):
    for bad in ("2026-8", "202608", "2026-13", "August"):
        assert run_payroll(client, bad).status_code == 422


def test_no_active_employees_is_422(client):
    r = run_payroll(client)
    assert r.status_code == 422 and "No active employees" in r.json()["detail"]


def test_all_problems_are_reported_together_and_nothing_is_saved(
    client, fake_employees, fake_leave
):
    fake_employees.staff = [
        employee(10, "EMP0010", "Priya Shah"),
        employee(20, "EMP0020", "No Salary Nat", salary=False),
        employee(30, "EMP0030", "Too Much Leave", basic="26000"),
    ]
    fake_leave.days = {30: LeaveDays(Decimal(20), Decimal(10))}  # 30 > 26 working days
    r = run_payroll(client)
    assert r.status_code == 422
    problems = r.json()["detail"]["problems"]
    assert len(problems) == 2
    assert any("No Salary Nat" in p and "no salary" in p for p in problems)
    assert any("Too Much Leave" in p and "exceeds" in p for p in problems)
    assert client.get("/payroll/runs", headers=ADMIN).json() == []  # atomic: no partial run


def test_downstream_outage_means_no_run(client, fake_employees, fake_leave):
    fake_employees.staff = [employee(10)]
    fake_leave.down = True
    r = run_payroll(client)
    assert r.status_code == 503 and "leave-service" in r.json()["detail"]
    fake_leave.down, fake_employees.down = False, True
    r = run_payroll(client)
    assert r.status_code == 503 and "employee-service" in r.json()["detail"]
    assert client.get("/payroll/runs", headers=ADMIN).json() == []
    fake_employees.down = False
    assert run_payroll(client).status_code == 201  # and it works once they are back


def test_only_admin_can_run(client, fake_employees):
    fake_employees.staff = [employee(10)]
    assert run_payroll(client, headers=MANAGER).status_code == 403
    assert run_payroll(client, headers=EMP10).status_code == 403
    assert client.post("/payroll/runs", json={"period": PERIOD}).status_code == 401


def test_history_does_not_change_when_the_employee_does(client, fake_employees):
    fake_employees.staff = [employee(10, name="Priya Shah", basic="26000")]
    run_id = run_payroll(client).json()["id"]
    fake_employees.staff = [employee(10, name="Priya Renamed", basic="99999")]
    li = line(client.get(f"/payroll/runs/{run_id}", headers=ADMIN).json())
    assert li["employee_name"] == "Priya Shah" and li["gross_pay"] == "26000.00"


def test_run_list_and_detail_are_admin_only(client, fake_employees):
    fake_employees.staff = [employee(10)]
    run_id = run_payroll(client).json()["id"]
    assert [r["id"] for r in client.get("/payroll/runs", headers=ADMIN).json()] == [run_id]
    assert client.get(f"/payroll/runs/{run_id}", headers=ADMIN).status_code == 200
    assert client.get("/payroll/runs/999", headers=ADMIN).status_code == 404
    for h in (MANAGER, EMP10):
        assert client.get("/payroll/runs", headers=h).status_code == 403
        assert client.get(f"/payroll/runs/{run_id}", headers=h).status_code == 403


def test_run_metrics(client, fake_employees):
    fake_employees.staff = [employee(10)]
    run_payroll(client)
    run_payroll(client)  # refused
    text = client.get("/metrics").text
    assert 'payroll_runs_total{outcome="completed"}' in text
    assert 'payroll_runs_total{outcome="rejected"}' in text
    assert "payroll_last_run_employees 1.0" in text
