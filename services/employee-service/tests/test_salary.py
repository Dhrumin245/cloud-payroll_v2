from datetime import date

import pytest

from tests.conftest import ADMIN, MANAGER, auth

SALARY = {
    "basic_pay": "50000",
    "hra": "20000",
    "conveyance_allowance": "1600",
    "components": [
        {"component_type": "allowance", "name": "Meal", "amount": "2000"},
        {"component_type": "deduction", "name": "Loan", "amount": "500"},
    ],
}


def put(client, emp_id, headers=ADMIN, **overrides):
    return client.put(f"/employees/{emp_id}/salary", json={**SALARY, **overrides}, headers=headers)


def test_first_salary_is_created_with_two_decimal_strings(client, make_employee):
    emp = make_employee()
    r = put(client, emp.id)
    assert r.status_code == 200
    body = r.json()
    assert body["basic_pay"] == "50000.00" and body["hra"] == "20000.00"
    assert body["effective_from"] == "2024-01-15"  # first salary: from the joining date
    assert body["components"][0] == {
        "component_type": "allowance",
        "name": "Meal",
        "amount": "2000.00",
    }
    assert (
        client.get(f"/employees/{emp.id}/salary", headers=ADMIN).json() == body
    )  # same shape everywhere
    assert client.get(f"/employees/{emp.id}/salary/history", headers=ADMIN).json() == []


def test_only_admin_may_write_salary(client, make_employee):
    emp = make_employee()
    assert put(client, emp.id, MANAGER).status_code == 403
    assert put(client, emp.id, auth("employee", employee_id=emp.id)).status_code == 403
    assert client.put(f"/employees/{emp.id}/salary", json=SALARY).status_code == 401


def test_read_access_admin_or_self_only(client, make_employee):
    mine, other = make_employee(), make_employee()
    put(client, mine.id)
    me = auth("employee", employee_id=mine.id)
    assert client.get(f"/employees/{mine.id}/salary", headers=me).status_code == 200
    assert client.get(f"/employees/{mine.id}/salary/history", headers=me).status_code == 200
    assert (
        client.get(
            f"/employees/{mine.id}/salary", headers=auth("employee", employee_id=other.id)
        ).status_code
        == 403
    )
    assert (
        client.get(f"/employees/{mine.id}/salary", headers=MANAGER).status_code == 403
    )  # managers excluded


def test_no_salary_is_404_and_unknown_employee_is_404(client, make_employee):
    emp = make_employee()
    assert client.get(f"/employees/{emp.id}/salary", headers=ADMIN).status_code == 404
    assert client.get("/employees/9999/salary", headers=ADMIN).status_code == 404
    assert put(client, 9999).status_code == 404


@pytest.mark.parametrize(
    "bad",
    [
        {"basic_pay": "0"},
        {"basic_pay": "-5"},
        {"hra": "-1"},
        {"basic_pay": "100.123"},
        {"components": [{"component_type": "bonus", "name": "X", "amount": "1"}]},
        {"components": [{"component_type": "allowance", "name": "", "amount": "1"}]},
        {"components": [{"component_type": "allowance", "name": "X", "amount": "-1"}]},
    ],
)
def test_salary_validation(client, make_employee, bad):
    assert put(client, make_employee().id, **bad).status_code == 422


def test_change_archives_previous_version(client, make_employee):
    emp = make_employee()
    put(client, emp.id, effective_from="2026-01-01")
    r = put(client, emp.id, basic_pay="55000", components=[], effective_from="2026-07-01")
    assert r.json()["basic_pay"] == "55000.00" and r.json()["effective_from"] == "2026-07-01"

    history = client.get(f"/employees/{emp.id}/salary/history", headers=ADMIN).json()
    assert len(history) == 1
    old = history[0]
    assert old["basic_pay"] == "50000.00" and old["effective_from"] == "2026-01-01"
    assert [c["name"] for c in old["components"]] == ["Meal", "Loan"]
    assert old["created_by_user_id"] == 100  # the admin who made the change
    assert old["superseded_at"]


def test_identical_put_creates_no_history(client, make_employee):
    emp = make_employee()
    put(client, emp.id)
    put(client, emp.id)
    reordered = list(reversed(SALARY["components"]))
    put(client, emp.id, components=reordered)  # same components, different order
    assert client.get(f"/employees/{emp.id}/salary/history", headers=ADMIN).json() == []


def test_component_only_change_counts_as_a_change(client, make_employee):
    emp = make_employee()
    put(client, emp.id)
    put(
        client,
        emp.id,
        components=[{"component_type": "allowance", "name": "Meal", "amount": "2500"}],
    )
    assert len(client.get(f"/employees/{emp.id}/salary/history", headers=ADMIN).json()) == 1


def test_history_is_newest_first(client, make_employee):
    emp = make_employee()
    put(client, emp.id, basic_pay="40000", effective_from="2025-01-01")
    put(client, emp.id, basic_pay="50000", effective_from="2026-01-01")
    put(client, emp.id, basic_pay="60000", effective_from="2026-06-01")
    history = client.get(f"/employees/{emp.id}/salary/history", headers=ADMIN).json()
    assert [h["basic_pay"] for h in history] == ["50000.00", "40000.00"]


def test_salary_as_of(client, make_employee):
    emp = make_employee()
    put(client, emp.id, basic_pay="50000", effective_from="2026-01-01")
    put(client, emp.id, basic_pay="60000", effective_from="2026-07-01")
    put(client, emp.id, basic_pay="70000", effective_from="2026-10-01")

    def at(d):
        return client.get(f"/employees/{emp.id}/salary?as_of={d}", headers=ADMIN)

    assert at("2025-12-31").status_code == 404  # before any salary existed
    assert at("2026-03-01").json()["basic_pay"] == "50000.00"
    assert (
        at("2026-07-01").json()["basic_pay"] == "60000.00"
    )  # boundary day belongs to the new version
    assert at("2026-08-15").json()["basic_pay"] == "60000.00"
    assert at("2026-12-31").json()["basic_pay"] == "70000.00"


def test_payroll_data_is_admin_only(client):
    assert client.get("/employees/payroll-data", headers=MANAGER).status_code == 403
    assert (
        client.get("/employees/payroll-data", headers=auth("employee", employee_id=1)).status_code
        == 403
    )
    assert client.get("/employees/payroll-data").status_code == 401


def test_payroll_data_contents(client, make_employee):
    paid = make_employee("EMP0001", "Paid Pat")
    nosalary = make_employee("EMP0002", "No Salary")
    make_employee("EMP0003", "Gone Girl", status="inactive")
    make_employee("EMP0004", "Future Joiner", joining=date(2027, 1, 1))
    put(client, paid.id, basic_pay="50000", effective_from="2026-01-01")
    put(client, paid.id, basic_pay="60000", effective_from="2026-07-01")

    rows = client.get("/employees/payroll-data?as_of=2026-09-30", headers=ADMIN).json()
    assert [r["employee_code"] for r in rows] == [
        "EMP0001",
        "EMP0002",
    ]  # inactive + not-yet-joined excluded
    assert rows[0]["salary"]["basic_pay"] == "60000.00"
    assert rows[1]["salary"] is None

    earlier = client.get("/employees/payroll-data?as_of=2026-03-31", headers=ADMIN).json()
    assert earlier[0]["salary"]["basic_pay"] == "50000.00"  # the salary in effect THEN
    assert nosalary.id == earlier[1]["id"]


def test_default_effective_from_first_salary_vs_later_change(client, make_employee):
    emp = make_employee(joining=date(2025, 6, 2))
    first = put(client, emp.id)
    assert first.json()["effective_from"] == "2025-06-02"  # joining date, not today
    changed = put(client, emp.id, basic_pay="55000")
    assert changed.json()["effective_from"] == date.today().isoformat()  # a raise starts today
    old = client.get(f"/employees/{emp.id}/salary/history", headers=ADMIN).json()[0]
    assert old["effective_from"] == "2025-06-02" and old["basic_pay"] == "50000.00"
    # payroll for any month since joining finds a salary
    assert (
        client.get(f"/employees/{emp.id}/salary?as_of=2025-07-31", headers=ADMIN).json()[
            "basic_pay"
        ]
        == "50000.00"
    )
