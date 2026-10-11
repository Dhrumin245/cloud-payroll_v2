from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app import input_services
from app.database import get_db
from app.periods import PERIOD_PATTERN, parse_period
from app.schemas import VariablePayIn, VariablePayOut
from app.security import CurrentUser, require_admin

router = APIRouter(prefix="/variable-pay", tags=["variable-pay"])


@router.post("", response_model=VariablePayOut, status_code=status.HTTP_201_CREATED)
def add_variable_pay(
    body: VariablePayIn,
    admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """One-off bonus ('earning') or deduction for a single month. Not prorated."""
    item = input_services.add_variable_pay(db, parse_period(body.period), body, admin.user_id)
    return VariablePayOut.from_item(item)


@router.get("", response_model=list[VariablePayOut])
def list_variable_pay(
    period: str | None = Query(None, pattern=PERIOD_PATTERN),
    employee_id: int | None = None,
    _admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    items = input_services.list_variable_pay(
        db, parse_period(period) if period else None, employee_id
    )
    return [VariablePayOut.from_item(i) for i in items]


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_variable_pay(
    item_id: int, _admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)
):
    input_services.delete_variable_pay(db, item_id)
