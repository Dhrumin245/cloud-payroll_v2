import pytest
from pydantic import ValidationError

from app.config import Settings


def test_missing_secret_fails_startup(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_short_secret_is_rejected(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "too-short")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_missing_database_url_fails_startup(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_missing_bank_key_fails_startup(monkeypatch):
    monkeypatch.delenv("BANK_ENCRYPTION_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_invalid_bank_key_is_rejected(monkeypatch):
    monkeypatch.setenv("BANK_ENCRYPTION_KEY", "not-a-fernet-key")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
