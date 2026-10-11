"""JWT verification and role-based access control.

The auth-service is the only service that ISSUES tokens. Every other service
only VERIFIES them with the shared JWT_SECRET, so this file is identical in
all four services.

Token claims:  sub (user id, string) | role | employee_id (nullable) | exp | iat
"""

from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings

ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_EMPLOYEE = "employee"
VALID_ROLES = {ROLE_ADMIN, ROLE_MANAGER, ROLE_EMPLOYEE}

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    user_id: int
    role: str
    employee_id: int | None
    token: str  # raw JWT, forwarded when calling other services on the user's behalf

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def is_manager_or_above(self) -> bool:
        return self.role in (ROLE_ADMIN, ROLE_MANAGER)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def decode_token(token: str) -> CurrentUser:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub", "role"]},
        )
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Token has expired") from None
    except jwt.InvalidTokenError:
        raise _unauthorized("Invalid token") from None

    role = payload.get("role")
    if role not in VALID_ROLES:
        raise _unauthorized("Invalid token role")
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError):
        raise _unauthorized("Invalid token subject") from None

    employee_id = payload.get("employee_id")
    return CurrentUser(
        user_id=user_id,
        role=role,
        employee_id=int(employee_id) if employee_id is not None else None,
        token=token,
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    if credentials is None:
        raise _unauthorized("Not authenticated")
    return decode_token(credentials.credentials)


def require_roles(*allowed: str):
    """Dependency factory: 401 without a valid token, 403 for the wrong role."""

    def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return user

    return checker


require_admin = require_roles(ROLE_ADMIN)
require_manager_or_above = require_roles(ROLE_ADMIN, ROLE_MANAGER)
require_any_role = require_roles(ROLE_ADMIN, ROLE_MANAGER, ROLE_EMPLOYEE)
