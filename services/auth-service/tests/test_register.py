import pytest

from tests.conftest import PASSWORD, headers_for


def payload(**overrides):
    base = {"username": "newuser", "password": "a-long-password", "role": "manager"}
    return {**base, **overrides}


def test_admin_creates_user_who_can_login(client, admin_headers):
    r = client.post("/auth/register", json=payload(), headers=admin_headers)
    assert r.status_code == 201
    body = r.json()
    assert body["username"] == "newuser" and body["role"] == "manager" and body["is_active"]
    assert "password" not in body and "password_hash" not in body
    login = client.post("/auth/login", json={"username": "newuser", "password": "a-long-password"})
    assert login.status_code == 200


def test_employee_role_requires_employee_id(client, admin_headers):
    r = client.post("/auth/register", json=payload(role="employee"), headers=admin_headers)
    assert r.status_code == 422


def test_employee_with_link(client, admin_headers):
    r = client.post(
        "/auth/register", json=payload(role="employee", employee_id=17), headers=admin_headers
    )
    assert r.status_code == 201 and r.json()["employee_id"] == 17


def test_manager_may_also_be_linked_to_an_employee(client, admin_headers):
    r = client.post("/auth/register", json=payload(employee_id=5), headers=admin_headers)
    assert r.status_code == 201 and r.json()["employee_id"] == 5


def test_duplicate_username_conflicts(client, admin_headers, make_user):
    make_user("taken", "manager")
    r = client.post("/auth/register", json=payload(username="taken"), headers=admin_headers)
    assert r.status_code == 409


def test_employee_can_only_be_linked_once(client, admin_headers, make_user):
    make_user("first", "employee", employee_id=9)
    r = client.post(
        "/auth/register",
        json=payload(role="employee", employee_id=9),
        headers=admin_headers,
    )
    assert r.status_code == 409 and "first" in r.json()["detail"]


@pytest.mark.parametrize(
    "bad",
    [
        {"password": "short"},  # < 8 chars
        {"password": "x" * 73},  # > 72 bytes (bcrypt limit)
        {"username": "ab"},  # too short
        {"username": "has space"},
        {"role": "superuser"},
        {"employee_id": 0},
    ],
)
def test_validation_errors(client, admin_headers, bad):
    r = client.post("/auth/register", json=payload(**bad), headers=admin_headers)
    assert r.status_code == 422


def test_no_token_is_401(client):
    assert client.post("/auth/register", json=payload()).status_code == 401


@pytest.mark.parametrize("role", ["manager", "employee"])
def test_non_admin_is_403(client, make_user, role):
    user = make_user(f"{role}-1", role)
    r = client.post("/auth/register", json=payload(), headers=headers_for(user))
    assert r.status_code == 403


def test_demoted_admin_loses_access_immediately(client, admin, admin_headers, db):
    admin.role = "manager"
    db.commit()
    assert client.post("/auth/register", json=payload(), headers=admin_headers).status_code == 403


def test_deactivated_admin_loses_access_immediately(client, admin, admin_headers, db):
    admin.is_active = False
    db.commit()
    assert client.get("/users", headers=admin_headers).status_code == 401


def test_password_is_hashed_in_db(client, admin_headers, db):
    from app.models import User

    client.post("/auth/register", json=payload(password=PASSWORD), headers=admin_headers)
    stored = db.query(User).filter_by(username="newuser").one().password_hash
    assert stored != PASSWORD and stored.startswith("$2b$")
