import os
import time

# Must be set before the app is imported (settings and the DB engine are created at import).
TEST_SECRET = "test-secret-key-that-is-at-least-32-chars-long"
os.environ["JWT_SECRET"] = TEST_SECRET
os.environ["SERVICE_NAME"] = "test-service"
# in-memory SQLite by default; set TEST_DATABASE_URL to run the suite against PostgreSQL
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite://")
os.environ["BCRYPT_ROUNDS"] = "4"  # fast hashing in tests

import jwt  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Base, User  # noqa: E402
from app.passwords import hash_password  # noqa: E402
from app.ratelimit import login_limiter  # noqa: E402
from app.tokens import create_access_token  # noqa: E402

PASSWORD = "correct-horse-battery"


def make_token(
    role: str = "employee",
    user_id: int = 1,
    employee_id: int | None = None,
    expires_in: int = 3600,
    secret: str = TEST_SECRET,
    **extra,
) -> str:
    """Forge an arbitrary token (for testing rejection of bad ones)."""
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


@pytest.fixture(autouse=True)
def _fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _database():
    Base.metadata.create_all(engine)
    login_limiter.reset()
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def make_user(db):
    def _make(username="user1", role="employee", password=PASSWORD, employee_id=None, active=True):
        if role == "employee" and employee_id is None:
            employee_id = abs(hash(username)) % 100000 + 1
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
            employee_id=employee_id,
            is_active=active,
        )
        db.add(user)
        db.commit()
        return user

    return _make


def headers_for(user: User) -> dict[str, str]:
    token, _ = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin(make_user):
    return make_user("admin1", "admin")


@pytest.fixture
def admin_headers(admin):
    return headers_for(admin)


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    return TestClient(app)
