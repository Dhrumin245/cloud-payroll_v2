import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import bank_service, employee_service
from app.database import get_db
from app.deps import admin_or_self
from app.metrics import BANK_REVEALS
from app.schemas import BankDetailsIn, BankDetailsOut, BankDetailsRevealOut
from app.security import CurrentUser, require_admin

router = APIRouter(prefix="/employees/{employee_id}/bank-details", tags=["bank-details"])
audit = logging.getLogger("app.audit")


@router.get("", response_model=BankDetailsOut)
def get_bank_details(
    employee_id: int,
    _user: CurrentUser = Depends(admin_or_self),
    db: Session = Depends(get_db),
):
    """Masked view (last 4 digits only)."""
    employee_service.get_employee_or_404(db, employee_id)
    return bank_service.to_out(bank_service.get_bank_details_or_404(db, employee_id))


@router.put("", response_model=BankDetailsOut)
def put_bank_details(
    employee_id: int,
    body: BankDetailsIn,
    _admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    employee = employee_service.get_employee_or_404(db, employee_id)
    return bank_service.to_out(bank_service.upsert(db, employee, body))


@router.get("/reveal", response_model=BankDetailsRevealOut)
def reveal_bank_details(
    employee_id: int,
    admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Full account number, e.g. for a bank payout file. Admin only and always audit-logged."""
    employee_service.get_employee_or_404(db, employee_id)
    row = bank_service.get_bank_details_or_404(db, employee_id)
    BANK_REVEALS.inc()
    audit.warning(
        f"bank account revealed employee_id={employee_id} by user_id={admin.user_id}",
        extra={"event": "bank_revealed"},
    )
    return bank_service.to_reveal_out(row)
