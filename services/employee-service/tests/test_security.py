import pytest

from app.security import decode_token
from tests.conftest import auth, make_token


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_no_token_is_401(client):
    r = client.get("/employees")
    assert r.status_code == 401 and r.headers["WWW-Authenticate"] == "Bearer"


def test_garbage_expired_wrong_secret_and_unknown_role_are_401(client):
    assert client.get("/employees", headers=bearer("not.a.jwt")).status_code == 401
    assert (
        client.get("/employees", headers=bearer(make_token("admin", expires_in=-5))).status_code
        == 401
    )
    forged = make_token("admin", secret="another-secret-key-that-is-32-chars-long!!")
    assert client.get("/employees", headers=bearer(forged)).status_code == 401
    assert client.get("/employees", headers=bearer(make_token("root"))).status_code == 401


def test_claims_are_parsed():
    user = decode_token(make_token("employee", user_id=7, employee_id=42))
    assert (user.user_id, user.role, user.employee_id) == (7, "employee", 42)


@pytest.mark.parametrize("role,expected", [("employee", 403), ("manager", 200), ("admin", 200)])
def test_employee_list_role_matrix(client, role, expected):
    assert client.get("/employees", headers=auth(role)).status_code == expected
