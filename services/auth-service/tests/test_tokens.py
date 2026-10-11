import jwt

from app.tokens import create_access_token
from tests.conftest import TEST_SECRET


def test_token_claims_match_contract(make_user):
    user = make_user("emp1", "employee", employee_id=42)
    token, expires_in = create_access_token(user)
    claims = jwt.decode(token, TEST_SECRET, algorithms=["HS256"])
    assert claims["sub"] == str(user.id)
    assert claims["role"] == "employee"
    assert claims["employee_id"] == 42
    assert claims["exp"] - claims["iat"] == expires_in == 3600


def test_admin_without_employee_link_has_null_employee_id(make_user):
    token, _ = create_access_token(make_user("boss", "admin"))
    assert jwt.decode(token, TEST_SECRET, algorithms=["HS256"])["employee_id"] is None


def test_expiry_is_configurable(make_user, monkeypatch):
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "5")
    from app.config import get_settings

    get_settings.cache_clear()
    _, expires_in = create_access_token(make_user("u", "admin"))
    assert expires_in == 300
