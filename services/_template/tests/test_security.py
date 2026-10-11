import pytest

from tests.conftest import auth_header, make_token


def test_no_token_is_401(client):
    r = client.get("/example/me")
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == "Bearer"


def test_garbage_token_is_401(client):
    r = client.get("/example/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401


def test_expired_token_is_401(client):
    r = client.get("/example/me", headers=auth_header("admin", expires_in=-10))
    assert r.status_code == 401
    assert "expired" in r.json()["detail"].lower()


def test_token_signed_with_wrong_secret_is_401(client):
    bad = make_token("admin", secret="another-secret-key-that-is-32-chars-long!!")
    r = client.get("/example/me", headers={"Authorization": f"Bearer {bad}"})
    assert r.status_code == 401


def test_unknown_role_is_401(client):
    r = client.get("/example/me", headers=auth_header("superuser"))
    assert r.status_code == 401


def test_claims_are_parsed(client):
    r = client.get("/example/me", headers=auth_header("employee", user_id=7, employee_id=42))
    assert r.json() == {"user_id": 7, "role": "employee", "employee_id": 42}


# Role matrix: (role, endpoint) -> expected status
@pytest.mark.parametrize(
    "role,path,expected",
    [
        ("employee", "/example/me", 200),
        ("manager", "/example/me", 200),
        ("admin", "/example/me", 200),
        ("employee", "/example/staff", 403),
        ("manager", "/example/staff", 200),
        ("admin", "/example/staff", 200),
        ("employee", "/example/admin", 403),
        ("manager", "/example/admin", 403),
        ("admin", "/example/admin", 200),
    ],
)
def test_role_matrix(client, role, path, expected):
    assert client.get(path, headers=auth_header(role)).status_code == expected
