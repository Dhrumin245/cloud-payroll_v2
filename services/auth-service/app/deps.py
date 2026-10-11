"""Auth-service guards.

Other services trust the JWT alone. Here, where accounts are managed, we additionally
re-check the database so a deactivated or demoted account stops working immediately
instead of at token expiry.
"""

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import ROLE_ADMIN, CurrentUser, get_current_user, require_admin


def _load_active(db: Session, user_id: int) -> User:
    row = db.get(User, user_id)
    if row is None or not row.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is inactive or no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return row


def active_user(
    token_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> User:
    return _load_active(db, token_user.user_id)


def active_admin(
    token_user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)
) -> User:
    row = _load_active(db, token_user.user_id)
    if row.role != ROLE_ADMIN:  # demoted since the token was issued
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission")
    return row
