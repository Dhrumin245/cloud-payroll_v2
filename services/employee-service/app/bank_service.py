import logging

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Employee, EmployeeBankDetails
from app.schemas import BankDetailsIn, BankDetailsOut, BankDetailsRevealOut

logger = logging.getLogger("app.bank")


def get_bank_details_or_404(db: Session, employee_id: int) -> EmployeeBankDetails:
    row = db.scalar(
        select(EmployeeBankDetails).where(EmployeeBankDetails.employee_id == employee_id)
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No bank details on file for this employee")
    return row


def to_out(row: EmployeeBankDetails) -> BankDetailsOut:
    return BankDetailsOut(
        employee_id=row.employee_id,
        account_holder_name=row.account_holder_name,
        account_number_masked=f"****{row.account_number_last4}",
        account_number_last4=row.account_number_last4,
        ifsc_code=row.ifsc_code,
        bank_name=row.bank_name,
        updated_at=row.updated_at,
    )


def to_reveal_out(row: EmployeeBankDetails) -> BankDetailsRevealOut:
    return BankDetailsRevealOut(
        **to_out(row).model_dump(), account_number=row.reveal_account_number()
    )


def upsert(db: Session, employee: Employee, data: BankDetailsIn) -> EmployeeBankDetails:
    row = db.scalar(
        select(EmployeeBankDetails).where(EmployeeBankDetails.employee_id == employee.id)
    )
    if row is None:
        if not data.account_number:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "account_number is required when adding bank details",
            )
        row = EmployeeBankDetails(employee_id=employee.id)
        db.add(row)
    row.account_holder_name = data.account_holder_name
    row.ifsc_code = data.ifsc_code
    row.bank_name = data.bank_name
    if data.account_number:  # omitted on update = keep the stored number
        row.set_account_number(data.account_number)
    db.commit()
    logger.info(f"bank details saved employee_id={employee.id}", extra={"event": "bank_saved"})
    return row
