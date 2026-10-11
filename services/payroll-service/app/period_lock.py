"""A month is locked once a payroll run exists for it: attendance and variable pay freeze."""

from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PayrollRun
from app.periods import format_period


def is_locked(db: Session, period: date) -> bool:
    return db.scalar(select(PayrollRun.id).where(PayrollRun.period == period)) is not None


def ensure_unlocked(db: Session, period: date) -> None:
    if is_locked(db, period):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Payroll for {format_period(period)} has already been processed; it is locked",
        )
