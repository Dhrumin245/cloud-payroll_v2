from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import employee_service, salary_service
from app.database import get_db
from app.deps import admin_or_self
from app.schemas import SalaryHistoryOut, SalaryIn, SalaryOut
from app.security import CurrentUser, require_admin

router = APIRouter(prefix="/employees/{employee_id}/salary", tags=["salary"])


@router.get("", response_model=SalaryOut)
def get_salary(
    employee_id: int,
    as_of: date | None = None,
    _user: CurrentUser = Depends(admin_or_self),
    db: Session = Depends(get_db),
):
    """Current salary, or the version that was in effect on `as_of`."""
    employee_service.get_employee_or_404(db, employee_id)
    if as_of is not None:
        result = salary_service.salary_as_of(db, employee_id, as_of)
    else:
        current = salary_service.get_current(db, employee_id)
        result = salary_service.structure_to_out(current) if current else None
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No salary structure on file")
    return result


@router.put("", response_model=SalaryOut)
def put_salary(
    employee_id: int,
    body: SalaryIn,
    admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Set or replace the salary. A real change archives the previous version to history."""
    employee = employee_service.get_employee_or_404(db, employee_id)
    structure = salary_service.set_salary(db, employee, body, actor_user_id=admin.user_id)
    return salary_service.structure_to_out(structure)


@router.get("/history", response_model=list[SalaryHistoryOut])
def salary_history(
    employee_id: int,
    _user: CurrentUser = Depends(admin_or_self),
    db: Session = Depends(get_db),
):
    """Previous salary versions, newest first (the current one is GET .../salary)."""
    employee_service.get_employee_or_404(db, employee_id)
    return [
        SalaryHistoryOut(
            **salary_service.history_to_out(h).model_dump(),
            id=h.id,
            superseded_at=h.superseded_at,
            created_by_user_id=h.created_by_user_id,
        )
        for h in salary_service.list_history(db, employee_id)
    ]
