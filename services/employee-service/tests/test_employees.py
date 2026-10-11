import pytest

from tests.conftest import ADMIN, MANAGER, auth


def payload(**overrides):
    return {
        "full_name": "Asha Rao",
        "designation": "Engineer",
        "joining_date": "2024-01-15",
        **overrides,
    }


def test_codes_are_generated_sequentially(client):
    a = client.post("/employees", json=payload(), headers=ADMIN)
    b = client.post("/employees", json=payload(full_name="Ravi"), headers=ADMIN)
    assert a.status_code == 201
    assert (a.json()["employee_code"], b.json()["employee_code"]) == ("EMP0001", "EMP0002")
    assert a.json()["status"] == "active"


def test_next_code_uses_highest_numeric_suffix(client, make_employee):
    make_employee("EMP0007")
    make_employee("CUSTOM-1")
    r = client.get("/employees/next-code", headers=MANAGER)
    assert r.json() == {"employee_code": "EMP0008"}


def test_custom_code_and_duplicate_conflict(client):
    assert (
        client.post("/employees", json=payload(employee_code="X-1"), headers=ADMIN).status_code
        == 201
    )
    r = client.post("/employees", json=payload(employee_code="X-1"), headers=ADMIN)
    assert r.status_code == 409


def test_manager_can_create_but_employee_cannot(client):
    assert client.post("/employees", json=payload(), headers=MANAGER).status_code == 201
    assert (
        client.post(
            "/employees", json=payload(), headers=auth("employee", employee_id=1)
        ).status_code
        == 403
    )
    assert client.post("/employees", json=payload()).status_code == 401


@pytest.mark.parametrize(
    "bad",
    [
        {"full_name": ""},
        {"designation": "   "},
        {"joining_date": "2024-13-45"},
        {"email": "not-an-email"},
        {"phone": "abc"},
        {"employee_code": "has space"},
    ],
)
def test_create_validation(client, bad):
    assert client.post("/employees", json=payload(**bad), headers=ADMIN).status_code == 422


def test_blank_email_is_stored_as_null(client):
    r = client.post("/employees", json=payload(email="  ", phone=""), headers=ADMIN)
    assert r.json()["email"] is None and r.json()["phone"] is None


def test_list_filters_search_and_paging(client, make_employee):
    make_employee("EMP0001", "Asha Rao")
    make_employee("EMP0002", "Ravi Kumar")
    make_employee("EMP0003", "Old Timer", status="inactive")

    names = lambda r: [e["full_name"] for e in r.json()]  # noqa: E731
    assert names(client.get("/employees", headers=MANAGER)) == ["Asha Rao", "Ravi Kumar"]
    assert names(client.get("/employees?status=inactive", headers=MANAGER)) == ["Old Timer"]
    assert len(client.get("/employees?status=all", headers=MANAGER).json()) == 3
    assert names(client.get("/employees?search=ravi", headers=MANAGER)) == ["Ravi Kumar"]
    assert names(client.get("/employees?search=EMP0001", headers=MANAGER)) == ["Asha Rao"]
    assert names(client.get("/employees?limit=1&offset=1", headers=MANAGER)) == ["Ravi Kumar"]


def test_search_treats_percent_literally(client, make_employee):
    make_employee("EMP0001", "Asha Rao")
    assert client.get("/employees?search=%25", headers=MANAGER).json() == []


def test_me_returns_own_record(client, make_employee):
    emp = make_employee()
    r = client.get("/employees/me", headers=auth("employee", employee_id=emp.id))
    assert r.status_code == 200 and r.json()["id"] == emp.id


def test_me_without_link_is_404(client):
    assert client.get("/employees/me", headers=auth("admin")).status_code == 404


def test_get_by_id_access_rules(client, make_employee):
    mine, other = make_employee(), make_employee()
    h = auth("employee", employee_id=mine.id)
    assert client.get(f"/employees/{mine.id}", headers=h).status_code == 200
    assert client.get(f"/employees/{other.id}", headers=h).status_code == 403
    assert client.get(f"/employees/{other.id}", headers=MANAGER).status_code == 200
    assert client.get("/employees/9999", headers=ADMIN).status_code == 404


def test_exists_never_404s(client, make_employee):
    active = make_employee()
    inactive = make_employee(status="inactive")
    h = auth("employee", employee_id=active.id)  # any authenticated user may call it
    assert client.get(f"/employees/{active.id}/exists", headers=h).json() == {
        "exists": True,
        "is_active": True,
    }
    assert client.get(f"/employees/{inactive.id}/exists", headers=h).json() == {
        "exists": True,
        "is_active": False,
    }
    assert client.get("/employees/9999/exists", headers=h).json() == {
        "exists": False,
        "is_active": False,
    }
    assert client.get(f"/employees/{active.id}/exists").status_code == 401


def test_exists_returns_no_personal_data(client, make_employee):
    emp = make_employee()
    body = client.get(
        f"/employees/{emp.id}/exists", headers=auth("employee", employee_id=99)
    ).json()
    assert set(body) == {"exists", "is_active"}


def test_patch_partial_update(client, make_employee):
    emp = make_employee(designation="Engineer")
    r = client.patch(
        f"/employees/{emp.id}",
        json={"designation": "Senior Engineer", "email": "asha@example.com"},
        headers=MANAGER,
    )
    assert r.status_code == 200
    assert r.json()["designation"] == "Senior Engineer" and r.json()["email"] == "asha@example.com"
    assert r.json()["full_name"] == "Asha Rao"  # untouched
    cleared = client.patch(f"/employees/{emp.id}", json={"email": None}, headers=MANAGER)
    assert cleared.json()["email"] is None


def test_patch_validation_and_conflicts(client, make_employee):
    a, b = make_employee("EMP0001"), make_employee("EMP0002")
    assert client.patch(f"/employees/{a.id}", json={}, headers=ADMIN).status_code == 422
    assert (
        client.patch(f"/employees/{a.id}", json={"full_name": None}, headers=ADMIN).status_code
        == 422
    )
    assert (
        client.patch(
            f"/employees/{a.id}", json={"employee_code": "EMP0002"}, headers=ADMIN
        ).status_code
        == 409
    )
    # keeping your own code is fine
    assert (
        client.patch(
            f"/employees/{b.id}", json={"employee_code": "EMP0002"}, headers=ADMIN
        ).status_code
        == 200
    )
    assert (
        client.patch("/employees/9999", json={"full_name": "X"}, headers=ADMIN).status_code == 404
    )


def test_deactivate_and_reactivate(client, make_employee):
    emp = make_employee()
    r = client.post(f"/employees/{emp.id}/deactivate", headers=MANAGER)
    assert r.json()["status"] == "inactive" and r.json()["deactivated_at"] is not None
    assert client.get("/employees", headers=MANAGER).json() == []  # hidden from default list
    again = client.post(f"/employees/{emp.id}/deactivate", headers=MANAGER)  # idempotent
    assert again.status_code == 200 and again.json()["status"] == "inactive"
    back = client.post(f"/employees/{emp.id}/reactivate", headers=MANAGER)
    assert back.json()["status"] == "active" and back.json()["deactivated_at"] is None


def test_employee_cannot_deactivate_anyone(client, make_employee):
    emp = make_employee()
    h = auth("employee", employee_id=emp.id)
    assert client.post(f"/employees/{emp.id}/deactivate", headers=h).status_code == 403
    assert (
        client.patch(f"/employees/{emp.id}", json={"full_name": "Z"}, headers=h).status_code == 403
    )
