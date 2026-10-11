"""User management rules (ported from the legacy users router, minus the HTML)."""

import logging
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import User
from app.passwords import burn_time, hash_password, verify_password
from app.schemas import UserCreate, UserUpdate

logger = logging.getLogger("app.users")


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def get_user_or_404(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def list_users(
    db: Session,
    role: str | None = None,
    is_active: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[User]:
    stmt = select(User).order_by(User.id).limit(limit).offset(offset)
    if role is not None:
        stmt = stmt.where(User.role == role)
    if is_active is not None:
        stmt = stmt.where(User.is_active.is_(is_active))
    return list(db.scalars(stmt))


def _ensure_employee_free(db: Session, employee_id: int, ignore_user_id: int | None = None) -> None:
    other = db.scalar(select(User).where(User.employee_id == employee_id))
    if other is not None and other.id != ignore_user_id:
        raise _conflict(f"This employee is already linked to user '{other.username}'")


def create_user(db: Session, data: UserCreate) -> User:
    if db.scalar(select(User).where(User.username == data.username)):
        raise _conflict(f"Username '{data.username}' is already taken")
    if data.employee_id is not None:
        _ensure_employee_free(db, data.employee_id)

    user = User(
        username=data.username,
        password_hash=hash_password(data.password),
        role=data.role,
        employee_id=data.employee_id,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # lost a race against a concurrent create
        db.rollback()
        raise _conflict("Username or employee link already in use") from None
    logger.info("user created", extra={"event": "user_created"})
    return user


def update_user(db: Session, target: User, data: UserUpdate, actor_id: int) -> User:
    sent = data.model_fields_set
    is_self = target.id == actor_id

    if is_self and data.is_active is False:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot deactivate your own account")
    if is_self and "role" in sent and data.role != target.role:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot change your own role")

    new_role = data.role if "role" in sent else target.role
    new_employee_id = data.employee_id if "employee_id" in sent else target.employee_id
    if new_role == "employee" and new_employee_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "employee_id is required for the 'employee' role",
        )
    if "employee_id" in sent and new_employee_id is not None:
        _ensure_employee_free(db, new_employee_id, ignore_user_id=target.id)

    target.role = new_role
    target.employee_id = new_employee_id
    if "is_active" in sent:
        target.is_active = data.is_active
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _conflict("Employee link already in use") from None
    logger.info("user updated", extra={"event": "user_updated"})
    return target


def set_password(db: Session, user: User, new_password: str) -> None:
    user.password_hash = hash_password(new_password)
    db.commit()
    logger.info("password changed", extra={"event": "password_changed"})


def authenticate(db: Session, username: str, password: str) -> User | None:
    """Same result for unknown user, inactive account and wrong password (no user enumeration)."""
    user = db.scalar(select(User).where(User.username == username.strip()))
    if user is None:
        burn_time(password)
        return None
    if not verify_password(password, user.password_hash) or not user.is_active:
        return None
    user.last_login_at = datetime.now(UTC)
    db.commit()
    return user
