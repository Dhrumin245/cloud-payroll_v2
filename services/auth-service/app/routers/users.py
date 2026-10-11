from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app import user_service
from app.database import get_db
from app.deps import active_admin
from app.models import User
from app.schemas import PasswordReset, Role, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(
    role: Role | None = None,
    is_active: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    _admin: User = Depends(active_admin),
    db: Session = Depends(get_db),
):
    return user_service.list_users(db, role, is_active, limit, offset)


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, _admin: User = Depends(active_admin), db: Session = Depends(get_db)):
    return user_service.get_user_or_404(db, user_id)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserUpdate,
    admin: User = Depends(active_admin),
    db: Session = Depends(get_db),
):
    target = user_service.get_user_or_404(db, user_id)
    return user_service.update_user(db, target, body, actor_id=admin.id)


@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    user_id: int,
    body: PasswordReset,
    _admin: User = Depends(active_admin),
    db: Session = Depends(get_db),
):
    target = user_service.get_user_or_404(db, user_id)
    user_service.set_password(db, target, body.new_password)
