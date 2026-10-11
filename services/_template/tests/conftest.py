import os
import time

# Must be set before the app is imported (settings are read at import time).
TEST_SECRET = "test-secret-key-that-is-at-least-32-chars-long"
os.environ["JWT_SECRET"] = TEST_SECRET
os.environ["SERVICE_NAME"] = "test-service"

import jwt
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def make_token(
    role: str = "employee",
    user_id: int = 1,
    employee_id: int | None = None,
    expires_in: int = 3600,
    secret: str = TEST_SECRET,
    **extra,
) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "role": role,
        "employee_id": employee_id,
        "iat": now,
        "exp": now + expires_in,
        **extra,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def auth_header(role: str = "employee", **kwargs) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(role, **kwargs)}"}


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    return TestClient(app)
