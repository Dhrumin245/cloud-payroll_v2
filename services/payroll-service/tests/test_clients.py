"""The REAL employee/leave clients, tested against a mocked HTTP transport."""

from datetime import date
from decimal import Decimal

import httpx
import pytest
from fastapi import HTTPException

from app.clients import EmployeeClient, LeaveClient


def emp_client(handler) -> EmployeeClient:
    return EmployeeClient(
        "http://employee-service:8000", 1.0, transport=httpx.MockTransport(handler)
    )


def leave_client(handler) -> LeaveClient:
    return LeaveClient("http://leave-service:8000", 1.0, transport=httpx.MockTransport(handler))


PAYROLL_DATA = [
    {
        "id": 10,
        "employee_code": "EMP0010",
        "full_name": "Priya Shah",
        "salary": {
            "employee_id": 10,
            "basic_pay": "26000.00",
            "hra": "13000.00",
            "conveyance_allowance": "1600.00",
            "effective_from": "2026-01-01",
            "components": [{"component_type": "allowance", "name": "Meal", "amount": "2000.00"}],
        },
    },
    {"id": 20, "employee_code": "EMP0020", "full_name": "No Salary", "salary": None},
]


def test_payroll_data_is_parsed_and_request_is_correct():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(
            path=request.url.path,
            as_of=request.url.params["as_of"],
            auth=request.headers["authorization"],
        )
        return httpx.Response(200, json=PAYROLL_DATA)

    rows = emp_client(handler).payroll_data(date(2026, 8, 31), "tok")
    assert seen == {"path": "/employees/payroll-data", "as_of": "2026-08-31", "auth": "Bearer tok"}
    assert rows[0].salary.basic_pay == Decimal("26000.00")
    assert rows[0].salary.components == [("allowance", "Meal", Decimal("2000.00"))]
    assert rows[1].salary is None


def test_reveal_bank_returns_details_or_none_for_404():
    ok = emp_client(lambda r: httpx.Response(200, json={"account_number": "123"}))
    assert ok.reveal_bank(10, "t") == {"account_number": "123"}
    assert emp_client(lambda r: httpx.Response(404)).reveal_bank(10, "t") is None


def test_leave_approved_is_parsed():
    def handler(request):
        assert request.url.params["month"] == "2026-08"
        return httpx.Response(
            200,
            json={
                "month": "2026-08",
                "employees": [{"employee_id": 10, "paid_days": "3.0", "unpaid_days": "2.0"}],
            },
        )

    got = leave_client(handler).approved("2026-08", "t")
    assert got[10].paid_days == Decimal("3.0") and got[10].unpaid_days == Decimal("2.0")


@pytest.mark.parametrize("status_code", [401, 403, 500, 502])
def test_error_answers_become_503(status_code):
    calls = [
        lambda: emp_client(lambda r: httpx.Response(status_code)).payroll_data(
            date(2026, 8, 31), "t"
        ),
        lambda: emp_client(lambda r: httpx.Response(status_code)).reveal_bank(1, "t"),
        lambda: leave_client(lambda r: httpx.Response(status_code)).approved("2026-08", "t"),
    ]
    for call in calls:
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == 503


def test_network_errors_name_the_failing_service():
    def boom(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(HTTPException) as exc:
        emp_client(boom).payroll_data(date(2026, 8, 31), "t")
    assert exc.value.status_code == 503 and "employee-service" in exc.value.detail
    with pytest.raises(HTTPException) as exc:
        leave_client(boom).approved("2026-08", "t")
    assert "leave-service" in exc.value.detail


def _count(target, outcome):
    from app.metrics import DOWNSTREAM_CALLS

    return DOWNSTREAM_CALLS.labels(target=target, outcome=outcome)._value.get()


def test_downstream_calls_are_counted_per_target_and_outcome():
    emp_ok, emp_err = _count("employee-service", "ok"), _count("employee-service", "error")
    lv_ok, lv_err = _count("leave-service", "ok"), _count("leave-service", "error")

    emp_client(lambda r: httpx.Response(200, json=[])).payroll_data(date(2026, 8, 31), "t")
    assert (
        emp_client(lambda r: httpx.Response(404)).reveal_bank(1, "t") is None
    )  # 404 is a valid answer
    assert (
        _count("employee-service", "ok") == emp_ok + 2
        and _count("employee-service", "error") == emp_err
    )

    leave_client(
        lambda r: httpx.Response(200, json={"month": "2026-08", "employees": []})
    ).approved("2026-08", "t")
    assert _count("leave-service", "ok") == lv_ok + 1

    for handler in (lambda r: httpx.Response(503), lambda r: httpx.Response(401)):
        with pytest.raises(HTTPException):
            leave_client(handler).approved("2026-08", "t")

    def boom(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(HTTPException):
        emp_client(boom).payroll_data(date(2026, 8, 31), "t")
    assert _count("leave-service", "error") == lv_err + 2
    assert _count("employee-service", "error") == emp_err + 1
