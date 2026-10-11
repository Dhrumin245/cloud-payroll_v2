import os
import time
from decimal import Decimal

# Must be set before the app is imported (settings and the DB engine are created at import).
TEST_SECRET = "test-secret-key-that-is-at-least-32-chars-long"
os.environ["JWT_SECRET"] = TEST_SECRET
os.environ["SERVICE_NAME"] = "test-service"
# in-memory SQLite by default; set TEST_DATABASE_URL to run the suite against PostgreSQL
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite://")
os.environ["COMPANY_NAME"] = "Test Co"

import jwt  # noqa: E402
import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.clients import (  # noqa: E402
    EmployeeData,
    LeaveDays,
    SalaryData,
    get_employee_client,
    get_leave_client,
)
from app.config import get_settings  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Base  # noqa: E402


def make_token(
    role="employee", user_id=1, employee_id=None, expires_in=3600, secret=TEST_SECRET
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
MANAGER = auth("manager", user_id=101, employee_id=30)
EMP10 = auth("employee", user_id=1, employee_id=10)
EMP20 = auth("employee", user_id=2, employee_id=20)

PERIOD = "2026-08"  # August 2026: 31 days, 5 Sundays -> 26 working days (26000 pay = 1000/day)


def employee(
    emp_id=10,
    code="EMP0010",
    name="Priya Shah",
    basic="26000",
    hra="0",
    conv="0",
    components=(),
    salary=True,
) -> EmployeeData:
    return EmployeeData(
        id=emp_id,
        employee_code=code,
        full_name=name,
        salary=SalaryData(Decimal(basic), Decimal(hra), Decimal(conv), list(components))
        if salary
        else None,
    )


class FakeEmployeeClient:
    def __init__(self) -> None:
        self.staff: list[EmployeeData] = []
        self.banks: dict[int, dict | None] = {}
        self.calls: list[tuple] = []
        self.down = False

    def _check(self):
        if self.down:
            raise HTTPException(503, "employee-service is unavailable, please try again shortly")

    def payroll_data(self, as_of, token):
        self.calls.append(("payroll_data", as_of.isoformat(), token))
        self._check()
        return list(self.staff)

    def reveal_bank(self, employee_id, token):
        self.calls.append(("reveal_bank", employee_id, token))
        self._check()
        return self.banks.get(employee_id)


class FakeLeaveClient:
    def __init__(self) -> None:
        self.days: dict[int, LeaveDays] = {}
        self.calls: list[tuple] = []
        self.down = False

    def approved(self, month, token):
        self.calls.append(("approved", month, token))
        if self.down:
            raise HTTPException(503, "leave-service is unavailable, please try again shortly")
        return dict(self.days)


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
def fake_leave():
    return FakeLeaveClient()


@pytest.fixture
def app(fake_employees, fake_leave):
    application = create_app()
    application.dependency_overrides[get_employee_client] = lambda: fake_employees
    application.dependency_overrides[get_leave_client] = lambda: fake_leave
    return application


@pytest.fixture
def client(app):
    return TestClient(app)


def run_payroll(client, period=PERIOD, headers=ADMIN):
    return client.post("/payroll/runs", json={"period": period}, headers=headers)


def line(run_json, employee_id=10):
    return next(li for li in run_json["line_items"] if li["employee_id"] == employee_id)


def component(li, name):
    return next((c for c in li["components"] if c["name"] == name), None)
