"""Access-token issuing. auth-service is the ONLY service that creates JWTs."""

import time

import jwt

from app.config import get_settings
from app.models import User


def create_access_token(user: User) -> tuple[str, int]:
    """Returns (token, expires_in_seconds). Claims match docs/api-contract.md."""
    settings = get_settings()
    now = int(time.time())
    expires_in = settings.access_token_expire_minutes * 60
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "employee_id": user.employee_id,
        "iat": now,
        "exp": now + expires_in,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_in
