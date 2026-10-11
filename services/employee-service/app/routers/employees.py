from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import employee_service, salary_service
from app.database import get_db
from app.deps import staff_or_self
from app.models import Employee
from app.schemas import (
    EmployeeCreate,
    EmployeeOut,
    EmployeeUpdate,
    ExistsOut,
    NextCodeOut,
    PayrollEmployeeOut,
)
from app.security import (
    CurrentUser,
    require_admin,
    require_any_role,
    require_manager_or_above,
)

router = APIRouter(prefix="/employees", tags=["employees"])


@router.post("", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED)
def create_employee(
    body: EmployeeCreate,
    _user: CurrentUser = Depends(require_manager_or_above),
    db: Session = Depends(get_db),
):
    return employee_service.create_employee(db, body)


@router.get("", response_model=list[EmployeeOut])
def list_employees(
    search: str = "",
    status_filter: Annotated[
        Literal["active", "inactive", "all"], Query(alias="status")
    ] = "active",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    _user: CurrentUser = Depends(require_manager_or_above),
    db: Session = Depends(get_db),
):
    return employee_service.list_employees(db, search, status_filter, limit, offset)


# NOTE: fixed paths (/next-code, /me, /payroll-data) must be declared BEFORE /{employee_id}.
@router.get("/next-code", response_model=NextCodeOut)
def next_code(
    _user: CurrentUser = Depends(require_manager_or_above), db: Session = Depends(get_db)
):
    return NextCodeOut(employee_code=employee_service.next_employee_code(db))


@router.get("/me", response_model=EmployeeOut)
def my_record(user: CurrentUser = Depends(require_any_role), db: Session = Depends(get_db)):
    if user.employee_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No employee record linked to this account")
    return employee_service.get_employee_or_404(db, user.employee_id)


@router.get("/payroll-data", response_model=list[PayrollEmployeeOut])
def payroll_data(
    as_of: date | None = None,
    _admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """For payroll-service: active employees + salary in effect on `as_of` (default today)."""
    rows = salary_service.payroll_data(db, as_of or date.today())
    return [
        PayrollEmployeeOut.model_validate(
            {**EmployeeOut.model_validate(e).model_dump(), "salary": salary}
        )
        for e, salary in rows
    ]


@router.get("/{employee_id}", response_model=EmployeeOut)
def get_employee(
    employee_id: int, _user: CurrentUser = Depends(staff_or_self), db: Session = Depends(get_db)
):
    return employee_service.get_employee_or_404(db, employee_id)


@router.get("/{employee_id}/exists", response_model=ExistsOut)
def employee_exists(
    employee_id: int, _user: CurrentUser = Depends(require_any_role), db: Session = Depends(get_db)
):
    """Lightweight check for other services (never 404). Returns no personal data."""
    row = db.scalar(select(Employee.status).where(Employee.id == employee_id))
    return ExistsOut(exists=row is not None, is_active=row == "active")


@router.patch("/{employee_id}", response_model=EmployeeOut)
def update_employee(
    employee_id: int,
    body: EmployeeUpdate,
    _user: CurrentUser = Depends(require_manager_or_above),
    db: Session = Depends(get_db),
):
    employee = employee_service.get_employee_or_404(db, employee_id)
    return employee_service.update_employee(db, employee, body)


@router.post("/{employee_id}/deactivate", response_model=EmployeeOut)
def deactivate(
    employee_id: int,
    _user: CurrentUser = Depends(require_manager_or_above),
    db: Session = Depends(get_db),
):
    employee = employee_service.get_employee_or_404(db, employee_id)
    return employee_service.set_status(db, employee, active=False)


@router.post("/{employee_id}/reactivate", response_model=EmployeeOut)
def reactivate(
    employee_id: int,
    _user: CurrentUser = Depends(require_manager_or_above),
    db: Session = Depends(get_db),
):
    employee = employee_service.get_employee_or_404(db, employee_id)
    return employee_service.set_status(db, employee, active=True)
