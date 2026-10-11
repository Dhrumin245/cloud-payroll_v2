"""Demo routes that prove the role guards work. DELETE this file in each real service."""

from fastapi import APIRouter, Depends

from app.security import (
    CurrentUser,
    require_admin,
    require_any_role,
    require_manager_or_above,
)

router = APIRouter(prefix="/example", tags=["example"])


@router.get("/me")
def me(user: CurrentUser = Depends(require_any_role)):
    return {"user_id": user.user_id, "role": user.role, "employee_id": user.employee_id}


@router.get("/staff")
def staff_only(user: CurrentUser = Depends(require_manager_or_above)):
    return {"ok": True, "role": user.role}


@router.get("/admin")
def admin_only(user: CurrentUser = Depends(require_admin)):
    return {"ok": True, "role": user.role}
