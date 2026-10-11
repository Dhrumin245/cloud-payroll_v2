from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app import leave_type_service
from app.database import get_db
from app.schemas import LeaveTypeIn, LeaveTypeOut, LeaveTypeUpdate
from app.security import CurrentUser, require_admin, require_any_role

router = APIRouter(prefix="/leave-types", tags=["leave-types"])


@router.get("", response_model=list[LeaveTypeOut])
def list_leave_types(_user: CurrentUser = Depends(require_any_role), db: Session = Depends(get_db)):
    return leave_type_service.list_leave_types(db)


@router.post("", response_model=LeaveTypeOut, status_code=status.HTTP_201_CREATED)
def create_leave_type(
    body: LeaveTypeIn, _admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)
):
    return leave_type_service.create_leave_type(db, body)


@router.patch("/{leave_type_id}", response_model=LeaveTypeOut)
def update_leave_type(
    leave_type_id: int,
    body: LeaveTypeUpdate,
    _admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Note: changing `is_paid` also changes how already-approved leave is treated by payroll."""
    leave_type = leave_type_service.get_leave_type_or_404(db, leave_type_id)
    return leave_type_service.update_leave_type(db, leave_type, body)
