import pytest

from app.security import decode_token
from tests.conftest import headers_for, make_token


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_no_token_is_401(client):
    r = client.get("/users")
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == "Bearer"


def test_garbage_token_is_401(client):
    assert client.get("/users", headers=bearer("not.a.jwt")).status_code == 401


def test_expired_token_is_401(client):
    r = client.get("/users", headers=bearer(make_token("admin", expires_in=-10)))
    assert r.status_code == 401
    assert "expired" in r.json()["detail"].lower()


def test_token_signed_with_wrong_secret_is_401(client):
    bad = make_token("admin", secret="another-secret-key-that-is-32-chars-long!!")
    assert client.get("/users", headers=bearer(bad)).status_code == 401


def test_unknown_role_is_401(client):
    assert client.get("/users", headers=bearer(make_token("superuser"))).status_code == 401


def test_claims_are_parsed():
    user = decode_token(make_token("employee", user_id=7, employee_id=42))
    assert (user.user_id, user.role, user.employee_id) == (7, "employee", 42)


@pytest.mark.parametrize("role,expected", [("employee", 403), ("manager", 403), ("admin", 200)])
def test_users_endpoint_role_matrix(client, make_user, role, expected):
    user = make_user(f"{role}-x", role)
    assert client.get("/users", headers=headers_for(user)).status_code == expected
