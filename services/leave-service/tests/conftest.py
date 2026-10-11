import os
import time

# Must be set before the app is imported (settings and the DB engine are created at import).
TEST_SECRET = "test-secret-key-that-is-at-least-32-chars-long"
os.environ["JWT_SECRET"] = TEST_SECRET
os.environ["SERVICE_NAME"] = "test-service"
# in-memory SQLite by default; set TEST_DATABASE_URL to run the suite against PostgreSQL
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite://")

import jwt  # noqa: E402
import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.clients import EmployeeStatus, get_employee_client  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Base, LeaveType  # noqa: E402


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


# Fixed identities used across tests
EMP = auth("employee", user_id=1, employee_id=10)  # employee 10
EMP2 = auth("employee", user_id=2, employee_id=20)  # employee 20
MANAGER = auth("manager", user_id=101, employee_id=30)  # manager who is also employee 30
ADMIN = auth("admin", user_id=100)  # admin with no employee record


class FakeEmployeeClient:
    """Stands in for employee-service. Everyone exists and is active unless told otherwise."""

    def __init__(self) -> None:
        self.employees: dict[int, tuple[bool, bool]] = {}
        self.calls: list[tuple[int, str]] = []
        self.down = False

    def check(self, employee_id: int, token: str) -> EmployeeStatus:
        self.calls.append((employee_id, token))
        if self.down:
            raise HTTPException(503, "employee-service is unavailable, please try again shortly")
        exists, active = self.employees.get(employee_id, (True, True))
        return EmployeeStatus(exists=exists, is_active=active)


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
def fake_employees():
    return FakeEmployeeClient()


@pytest.fixture
def app(fake_employees):
    application = create_app()
    application.dependency_overrides[get_employee_client] = lambda: fake_employees
    return application


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def make_type(db):
    def _make(name="Casual Leave", max_days=None, is_paid=True) -> LeaveType:
        leave_type = LeaveType(name=name, max_days_per_year=max_days, is_paid=is_paid)
        db.add(leave_type)
        db.commit()
        return leave_type

    return _make


@pytest.fixture
def casual(make_type):
    return make_type("Casual Leave", max_days=12)


def apply(client, headers, leave_type_id, start="2026-10-05", end="2026-10-07", **extra):
    """Mon 5 Oct - Wed 7 Oct 2026 = 3 leave days by default."""
    body = {"leave_type_id": leave_type_id, "start_date": start, "end_date": end, **extra}
    return client.post("/leaves", json=body, headers=headers)
