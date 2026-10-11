"""Attendance (unexplained absence) and one-off variable pay entries."""

import logging
from datetime import date
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AttendanceRecord, VariablePayItem
from app.period_lock import ensure_unlocked
from app.periods import working_days
from app.schemas import VariablePayIn

logger = logging.getLogger("app.inputs")


# ---------------------------------------------------------------- attendance
def set_absence(
    db: Session, employee_id: int, period: date, days_absent: Decimal, user_id: int
) -> AttendanceRecord:
    ensure_unlocked(db, period)
    total = working_days(period)
    if days_absent > total:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"days_absent cannot exceed the {total} working days in this month",
        )
    record = db.scalar(
        select(AttendanceRecord).where(
            AttendanceRecord.employee_id == employee_id, AttendanceRecord.period == period
        )
    )
    if record is None:
        record = AttendanceRecord(employee_id=employee_id, period=period)
        db.add(record)
    record.days_absent = days_absent
    record.recorded_by_user_id = user_id
    db.commit()
    logger.info(
        f"absence recorded employee_id={employee_id} days={days_absent}",
        extra={"event": "absence_recorded"},
    )
    return record


def list_absences(db: Session, period: date) -> list[AttendanceRecord]:
    return list(
        db.scalars(
            select(AttendanceRecord)
            .where(AttendanceRecord.period == period)
            .order_by(AttendanceRecord.employee_id)
        )
    )


# ---------------------------------------------------------------- variable pay
def add_variable_pay(
    db: Session, period: date, data: VariablePayIn, user_id: int
) -> VariablePayItem:
    ensure_unlocked(db, period)
    exists = db.scalar(
        select(VariablePayItem.id).where(
            VariablePayItem.employee_id == data.employee_id,
            VariablePayItem.period == period,
            VariablePayItem.name == data.name,
        )
    )
    if exists is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"'{data.name}' is already recorded for this employee and month",
        )
    item = VariablePayItem(
        employee_id=data.employee_id,
        period=period,
        component_type=data.component_type,
        name=data.name,
        amount=data.amount,
        created_by_user_id=user_id,
    )
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Duplicate variable pay item") from None
    return item


def list_variable_pay(
    db: Session, period: date | None, employee_id: int | None
) -> list[VariablePayItem]:
    stmt = select(VariablePayItem).order_by(
        VariablePayItem.period, VariablePayItem.employee_id, VariablePayItem.name
    )
    if period is not None:
        stmt = stmt.where(VariablePayItem.period == period)
    if employee_id is not None:
        stmt = stmt.where(VariablePayItem.employee_id == employee_id)
    return list(db.scalars(stmt))


def delete_variable_pay(db: Session, item_id: int) -> None:
    item = db.get(VariablePayItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Variable pay item not found")
    ensure_unlocked(db, item.period)
    db.delete(item)
    db.commit()
