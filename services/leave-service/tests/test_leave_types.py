import pytest

from tests.conftest import ADMIN, EMP, MANAGER


def test_admin_creates_and_everyone_lists(client):
    r = client.post(
        "/leave-types", json={"name": " Sick Leave ", "max_days_per_year": "10"}, headers=ADMIN
    )
    assert r.status_code == 201
    assert r.json()["name"] == "Sick Leave"
    assert r.json()["max_days_per_year"] == "10.0" and r.json()["is_paid"] is True
    for headers in (EMP, MANAGER, ADMIN):
        assert [t["name"] for t in client.get("/leave-types", headers=headers).json()] == [
            "Sick Leave"
        ]
    assert client.get("/leave-types").status_code == 401


def test_unlimited_and_unpaid_types(client):
    r = client.post("/leave-types", json={"name": "Unpaid", "is_paid": False}, headers=ADMIN)
    assert r.json()["max_days_per_year"] is None and r.json()["is_paid"] is False


def test_only_admin_may_write(client):
    body = {"name": "X"}
    assert client.post("/leave-types", json=body, headers=MANAGER).status_code == 403
    assert client.post("/leave-types", json=body, headers=EMP).status_code == 403
    assert client.patch("/leave-types/1", json=body, headers=MANAGER).status_code == 403


def test_duplicate_names_conflict_case_insensitively(client):
    client.post("/leave-types", json={"name": "Sick Leave"}, headers=ADMIN)
    r = client.post("/leave-types", json={"name": "sick LEAVE"}, headers=ADMIN)
    assert r.status_code == 409


@pytest.mark.parametrize(
    "bad",
    [
        {"name": ""},
        {"name": "X", "max_days_per_year": "0"},
        {"name": "X", "max_days_per_year": "-3"},
    ],
)
def test_validation(client, bad):
    assert client.post("/leave-types", json=bad, headers=ADMIN).status_code == 422


def test_patch(client, make_type):
    lt = make_type("Casual Leave", max_days=12)
    other = make_type("Sick Leave", max_days=10)
    r = client.patch(
        f"/leave-types/{lt.id}", json={"name": "Casual", "is_paid": False}, headers=ADMIN
    )
    assert r.json()["name"] == "Casual" and r.json()["is_paid"] is False
    assert r.json()["max_days_per_year"] == "12.0"  # untouched
    unlimited = client.patch(
        f"/leave-types/{lt.id}", json={"max_days_per_year": None}, headers=ADMIN
    )
    assert unlimited.json()["max_days_per_year"] is None
    assert (
        client.patch(f"/leave-types/{other.id}", json={"name": "casual"}, headers=ADMIN).status_code
        == 409
    )
    assert client.patch(f"/leave-types/{other.id}", json={}, headers=ADMIN).status_code == 422
    assert (
        client.patch(f"/leave-types/{other.id}", json={"name": None}, headers=ADMIN).status_code
        == 422
    )
    assert client.patch("/leave-types/999", json={"name": "Z"}, headers=ADMIN).status_code == 404
