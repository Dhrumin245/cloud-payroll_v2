import pytest

from tests.conftest import ADMIN, EMP10, MANAGER, PERIOD, employee, run_payroll


# ---------------------------------------------------------------- attendance
def test_record_and_update_absence(client):
    r = client.put(f"/attendance/10/{PERIOD}", json={"days_absent": "1"}, headers=MANAGER)
    assert r.status_code == 200
    assert r.json() == {
        **r.json(),
        "employee_id": 10,
        "period": PERIOD,
        "days_absent": "1.0",
        "recorded_by_user_id": 101,
    }
    client.put(f"/attendance/10/{PERIOD}", json={"days_absent": "2.5"}, headers=ADMIN)  # upsert
    listing = client.get(f"/attendance/{PERIOD}", headers=MANAGER).json()
    assert len(listing) == 1 and listing[0]["days_absent"] == "2.5"


@pytest.mark.parametrize("bad", ["-1", "27", "1.25", "abc"])
def test_absence_validation(client, bad):
    r = client.put(f"/attendance/10/{PERIOD}", json={"days_absent": bad}, headers=ADMIN)
    assert r.status_code == 422


def test_attendance_access(client):
    assert (
        client.put(f"/attendance/10/{PERIOD}", json={"days_absent": "1"}, headers=EMP10).status_code
        == 403
    )
    assert client.get(f"/attendance/{PERIOD}", headers=EMP10).status_code == 403
    assert client.get(f"/attendance/{PERIOD}").status_code == 401
    assert (
        client.put("/attendance/10/2026-13", json={"days_absent": "1"}, headers=ADMIN).status_code
        == 422
    )


# ---------------------------------------------------------------- variable pay
def vp(**over):
    return {
        "employee_id": 10,
        "period": PERIOD,
        "component_type": "earning",
        "name": "Bonus",
        "amount": "1000",
        **over,
    }


def test_variable_pay_crud(client):
    created = client.post("/variable-pay", json=vp(), headers=ADMIN)
    assert created.status_code == 201
    item = created.json()
    assert (
        item["amount"] == "1000.00"
        and item["period"] == PERIOD
        and item["created_by_user_id"] == 100
    )
    client.post(
        "/variable-pay",
        json=vp(name="Advance", component_type="deduction", employee_id=20),
        headers=ADMIN,
    )

    assert len(client.get("/variable-pay", headers=ADMIN).json()) == 2
    assert (
        len(client.get(f"/variable-pay?period={PERIOD}&employee_id=10", headers=ADMIN).json()) == 1
    )
    assert client.get("/variable-pay?period=2026-09", headers=ADMIN).json() == []
    assert client.delete(f"/variable-pay/{item['id']}", headers=ADMIN).status_code == 204
    assert client.delete(f"/variable-pay/{item['id']}", headers=ADMIN).status_code == 404


def test_duplicate_item_name_for_same_month_conflicts(client):
    client.post("/variable-pay", json=vp(), headers=ADMIN)
    assert client.post("/variable-pay", json=vp(), headers=ADMIN).status_code == 409
    assert client.post("/variable-pay", json=vp(period="2026-09"), headers=ADMIN).status_code == 201


@pytest.mark.parametrize(
    "bad",
    [
        {"amount": "-5"},
        {"amount": "1.234"},
        {"name": ""},
        {"component_type": "bonus"},
        {"period": "2026-13"},
        {"employee_id": 0},
    ],
)
def test_variable_pay_validation(client, bad):
    assert client.post("/variable-pay", json=vp(**bad), headers=ADMIN).status_code == 422


def test_variable_pay_is_admin_only(client):
    for h in (MANAGER, EMP10):
        assert client.post("/variable-pay", json=vp(), headers=h).status_code == 403
        assert client.get("/variable-pay", headers=h).status_code == 403


# ---------------------------------------------------------------- period lock
def test_month_is_locked_after_payroll_runs(client, fake_employees):
    fake_employees.staff = [employee(10)]
    existing = client.post("/variable-pay", json=vp(), headers=ADMIN).json()["id"]
    assert run_payroll(client).status_code == 201

    r = client.put(f"/attendance/10/{PERIOD}", json={"days_absent": "1"}, headers=ADMIN)
    assert r.status_code == 409 and "locked" in r.json()["detail"]
    assert client.post("/variable-pay", json=vp(name="Late"), headers=ADMIN).status_code == 409
    assert client.delete(f"/variable-pay/{existing}", headers=ADMIN).status_code == 409
    # other months stay editable
    assert (
        client.put("/attendance/10/2026-09", json={"days_absent": "1"}, headers=ADMIN).status_code
        == 200
    )
