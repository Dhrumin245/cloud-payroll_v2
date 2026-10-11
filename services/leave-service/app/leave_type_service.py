from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import LeaveType
from app.schemas import LeaveTypeIn, LeaveTypeUpdate


def get_leave_type_or_404(db: Session, leave_type_id: int) -> LeaveType:
    leave_type = db.get(LeaveType, leave_type_id)
    if leave_type is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Leave type not found")
    return leave_type


def list_leave_types(db: Session) -> list[LeaveType]:
    return list(db.scalars(select(LeaveType).order_by(LeaveType.name)))


def _name_taken(db: Session, name: str, ignore_id: int | None = None) -> bool:
    other = db.scalar(select(LeaveType).where(func.lower(LeaveType.name) == name.lower()))
    return other is not None and other.id != ignore_id


def create_leave_type(db: Session, data: LeaveTypeIn) -> LeaveType:
    if _name_taken(db, data.name):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Leave type '{data.name}' already exists")
    leave_type = LeaveType(
        name=data.name, max_days_per_year=data.max_days_per_year, is_paid=data.is_paid
    )
    db.add(leave_type)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Leave type already exists") from None
    return leave_type


def update_leave_type(db: Session, leave_type: LeaveType, data: LeaveTypeUpdate) -> LeaveType:
    sent = data.model_fields_set
    if "name" in sent and _name_taken(db, data.name, ignore_id=leave_type.id):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Leave type '{data.name}' already exists")
    if "name" in sent:
        leave_type.name = data.name
    if "max_days_per_year" in sent:
        leave_type.max_days_per_year = data.max_days_per_year
    if "is_paid" in sent:
        leave_type.is_paid = data.is_paid
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Leave type already exists") from None
    return leave_type
