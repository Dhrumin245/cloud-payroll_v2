from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app import leave_service
from app.clients import EmployeeClient, get_employee_client
from app.database import get_db
from app.schemas import (
    ApprovedLeaveOut,
    BalanceOut,
    DecisionNote,
    LeaveRequestIn,
    LeaveRequestOut,
    RejectIn,
    Status,
)
from app.security import (
    CurrentUser,
    require_admin,
    require_any_role,
    require_manager_or_above,
)

router = APIRouter(prefix="/leaves", tags=["leaves"])

MonthParam = Annotated[str, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM")]
Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]


def _own_employee_id(user: CurrentUser) -> int:
    if user.employee_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Your account is not linked to an employee record"
        )
    return user.employee_id


@router.post("", response_model=LeaveRequestOut, status_code=status.HTTP_201_CREATED)
def apply_for_leave(
    body: LeaveRequestIn,
    user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
    employees: EmployeeClient = Depends(get_employee_client),
):
    """The applicant is ALWAYS the employee in the token, never a field in the body."""
    employee_id = _own_employee_id(user)
    current = employees.check(employee_id, user.token)
    if not current.exists:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee record not found")
    if not current.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your employee record is inactive")
    return leave_service.create_request(db, employee_id, body)


@router.get("", response_model=list[LeaveRequestOut])
def list_all_leaves(
    status_filter: Annotated[Status | None, Query(alias="status")] = None,
    employee_id: int | None = None,
    leave_type_id: int | None = None,
    month: MonthParam | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
    _user: CurrentUser = Depends(require_manager_or_above),
    db: Session = Depends(get_db),
):
    return leave_service.list_requests(
        db,
        employee_id=employee_id,
        status_filter=status_filter,
        leave_type_id=leave_type_id,
        month=month,
        limit=limit,
        offset=offset,
    )


# NOTE: fixed paths (/my, /pending, /balance, /approved) must be declared BEFORE /{request_id}.
@router.get("/my", response_model=list[LeaveRequestOut])
def my_leaves(
    status_filter: Annotated[Status | None, Query(alias="status")] = None,
    limit: Limit = 50,
    offset: Offset = 0,
    user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    return leave_service.list_requests(
        db,
        employee_id=_own_employee_id(user),
        status_filter=status_filter,
        limit=limit,
        offset=offset,
    )


@router.get("/pending", response_model=list[LeaveRequestOut])
def pending_leaves(
    limit: Limit = 50,
    offset: Offset = 0,
    _user: CurrentUser = Depends(require_manager_or_above),
    db: Session = Depends(get_db),
):
    """Requests awaiting a decision, oldest first."""
    return leave_service.list_requests(
        db, status_filter="pending", oldest_first=True, limit=limit, offset=offset
    )


@router.get("/balance", response_model=BalanceOut)
def leave_balance(
    year: Annotated[int | None, Query(ge=2000, le=2100)] = None,
    employee_id: int | None = None,
    user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    """Own balance by default. Managers/admins may pass `employee_id` to see someone else's."""
    if employee_id is None:
        employee_id = _own_employee_id(user)
    elif employee_id != user.employee_id and not user.is_manager_or_above:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only view your own leave balance")
    year = year or date.today().year
    return BalanceOut(
        employee_id=employee_id, year=year, balances=leave_service.balances(db, employee_id, year)
    )


@router.get("/approved", response_model=ApprovedLeaveOut)
def approved_leave_for_month(
    month: MonthParam,
    _admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """For payroll-service: approved leave days per employee in the month, split paid / unpaid."""
    return ApprovedLeaveOut(month=month, employees=leave_service.approved_summary(db, month))


@router.get("/{request_id}", response_model=LeaveRequestOut)
def get_leave(
    request_id: int,
    user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    request = leave_service.get_request_or_404(db, request_id)
    if not user.is_manager_or_above and request.employee_id != user.employee_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only view your own leave requests")
    return request


@router.post("/{request_id}/cancel", response_model=LeaveRequestOut)
def cancel_leave(
    request_id: int,
    user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    return leave_service.cancel(db, request_id, user)


@router.post("/{request_id}/approve", response_model=LeaveRequestOut)
def approve_leave(
    request_id: int,
    body: DecisionNote | None = None,
    user: CurrentUser = Depends(require_manager_or_above),
    db: Session = Depends(get_db),
):
    return leave_service.approve(db, request_id, user, body.note if body else None)


@router.post("/{request_id}/reject", response_model=LeaveRequestOut)
def reject_leave(
    request_id: int,
    body: RejectIn,
    user: CurrentUser = Depends(require_manager_or_above),
    db: Session = Depends(get_db),
):
    return leave_service.reject(db, request_id, user, body.reason)
