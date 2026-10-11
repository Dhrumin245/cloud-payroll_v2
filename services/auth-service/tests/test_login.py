import jwt

from app.config import get_settings
from tests.conftest import PASSWORD, TEST_SECRET, headers_for


def login(client, username, password=PASSWORD, **kwargs):
    return client.post("/auth/login", json={"username": username, "password": password}, **kwargs)


def test_login_success_returns_usable_token(client, make_user):
    make_user("alice", "manager")
    r = login(client, "alice")
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer" and body["expires_in"] == 3600
    claims = jwt.decode(body["access_token"], TEST_SECRET, algorithms=["HS256"])
    assert claims["role"] == "manager"
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["username"] == "alice"


def test_login_updates_last_login(client, make_user, db):
    user = make_user("alice", "admin")
    assert user.last_login_at is None
    login(client, "alice")
    db.refresh(user)
    assert user.last_login_at is not None


def test_username_is_trimmed(client, make_user):
    make_user("alice", "admin")
    assert login(client, "  alice  ").status_code == 200


def test_wrong_password_and_unknown_user_look_identical(client, make_user):
    make_user("alice", "admin")
    wrong_pw = login(client, "alice", "nope-nope-nope")
    unknown = login(client, "nobody", "nope-nope-nope")
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json() == unknown.json()


def test_inactive_user_cannot_login(client, make_user):
    make_user("gone", "employee", active=False)
    r = login(client, "gone")
    assert r.status_code == 401 and r.json()["detail"] == "Invalid username or password"


def test_login_validation_error(client):
    assert client.post("/auth/login", json={"username": "x"}).status_code == 422


def test_rate_limit_blocks_after_limit(client, make_user, monkeypatch):
    monkeypatch.setenv("LOGIN_RATE_LIMIT_PER_MINUTE", "3")
    get_settings.cache_clear()
    make_user("alice", "admin")
    for _ in range(3):
        assert login(client, "alice", "wrong-password").status_code == 401
    blocked = login(client, "alice")  # even the right password is refused now
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1


def test_forwarded_for_gives_each_client_its_own_bucket(client, make_user, monkeypatch):
    monkeypatch.setenv("LOGIN_RATE_LIMIT_PER_MINUTE", "1")
    monkeypatch.setenv("TRUST_FORWARDED_FOR", "true")
    get_settings.cache_clear()
    make_user("alice", "admin")
    assert login(client, "alice", headers={"X-Forwarded-For": "10.0.0.1"}).status_code == 200
    assert login(client, "alice", headers={"X-Forwarded-For": "10.0.0.2"}).status_code == 200
    assert login(client, "alice", headers={"X-Forwarded-For": "10.0.0.1"}).status_code == 429


def test_forwarded_for_ignored_unless_trusted(client, make_user, monkeypatch):
    monkeypatch.setenv("LOGIN_RATE_LIMIT_PER_MINUTE", "1")
    get_settings.cache_clear()
    make_user("alice", "admin")
    assert login(client, "alice", headers={"X-Forwarded-For": "10.0.0.1"}).status_code == 200
    assert login(client, "alice", headers={"X-Forwarded-For": "10.0.0.2"}).status_code == 429


def test_login_metrics_exported(client, make_user):
    make_user("alice", "admin")
    login(client, "alice")
    login(client, "alice", "wrong-password")
    text = client.get("/metrics").text
    assert 'auth_logins_total{result="success"}' in text
    assert 'auth_logins_total{result="failure"}' in text


def test_deactivated_account_token_stops_working(client, make_user, db):
    user = make_user("alice", "manager")
    headers = headers_for(user)
    assert client.get("/auth/me", headers=headers).status_code == 200
    user.is_active = False
    db.commit()
    assert client.get("/auth/me", headers=headers).status_code == 401


def test_deleted_account_token_stops_working(client, make_user, db):
    user = make_user("alice", "manager")
    headers = headers_for(user)
    db.delete(user)
    db.commit()
    assert client.get("/auth/me", headers=headers).status_code == 401
