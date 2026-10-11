from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from app import input_services
from app.database import get_db
from app.periods import PERIOD_PATTERN, parse_period
from app.schemas import AbsenceIn, AbsenceOut
from app.security import CurrentUser, require_manager_or_above

router = APIRouter(prefix="/attendance", tags=["attendance"])
PeriodPath = Annotated[str, Path(pattern=PERIOD_PATTERN, description="YYYY-MM")]


@router.put("/{employee_id}/{period}", response_model=AbsenceOut)
def record_absence(
    employee_id: int,
    period: PeriodPath,
    body: AbsenceIn,
    user: CurrentUser = Depends(require_manager_or_above),
    db: Session = Depends(get_db),
):
    """Record UNEXPLAINED absence. Approved leave comes from leave-service automatically."""
    record = input_services.set_absence(
        db, employee_id, parse_period(period), body.days_absent, user.user_id
    )
    return AbsenceOut.from_record(record)


@router.get("/{period}", response_model=list[AbsenceOut])
def list_absences(
    period: PeriodPath,
    _user: CurrentUser = Depends(require_manager_or_above),
    db: Session = Depends(get_db),
):
    return [
        AbsenceOut.from_record(r) for r in input_services.list_absences(db, parse_period(period))
    ]
