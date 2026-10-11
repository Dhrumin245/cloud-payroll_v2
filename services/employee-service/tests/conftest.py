import os
import time
from datetime import date

from cryptography.fernet import Fernet

# Must be set before the app is imported (settings and the DB engine are created at import).
TEST_SECRET = "test-secret-key-that-is-at-least-32-chars-long"
os.environ["JWT_SECRET"] = TEST_SECRET
os.environ["SERVICE_NAME"] = "test-service"
# in-memory SQLite by default; set TEST_DATABASE_URL to run the suite against PostgreSQL
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite://")
os.environ["BANK_ENCRYPTION_KEY"] = Fernet.generate_key().decode()

import jwt  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Base, Employee  # noqa: E402


def make_token(
    role: str = "employee",
    user_id: int = 1,
    employee_id: int | None = None,
    expires_in: int = 3600,
    secret: str = TEST_SECRET,
) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "role": role,
        "employee_id": employee_id,
        "iat": now,
        "exp": now + expires_in,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def auth(role: str, user_id: int = 1, employee_id: int | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(role, user_id, employee_id)}"}


ADMIN = auth("admin", user_id=100)
MANAGER = auth("manager", user_id=101)


@pytest.fixture(autouse=True)
def _fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _database():
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def make_employee(db):
    counter = {"n": 0}

    def _make(
        code: str | None = None,
        name: str = "Asha Rao",
        status: str = "active",
        joining: date = date(2024, 1, 15),
        designation: str = "Engineer",
    ) -> Employee:
        counter["n"] += 1
        employee = Employee(
            employee_code=code or f"EMP{counter['n']:04d}",
            full_name=name,
            designation=designation,
            joining_date=joining,
            status=status,
        )
        db.add(employee)
        db.commit()
        return employee

    return _make


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    return TestClient(app)
