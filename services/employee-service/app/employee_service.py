import logging
import re
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Employee
from app.schemas import EmployeeCreate, EmployeeUpdate

logger = logging.getLogger("app.employees")
_CODE_PATTERN = re.compile(r"^EMP(\d+)$")


def get_employee_or_404(db: Session, employee_id: int) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    return employee


def next_employee_code(db: Session) -> str:
    """EMP0001, EMP0002, ... one above the highest existing numeric suffix."""
    highest = 0
    for (code,) in db.execute(select(Employee.employee_code)):
        match = _CODE_PATTERN.match(code or "")
        if match:
            highest = max(highest, int(match.group(1)))
    return f"EMP{highest + 1:04d}"


def _code_taken(db: Session, code: str, ignore_id: int | None = None) -> bool:
    other = db.scalar(select(Employee).where(Employee.employee_code == code))
    return other is not None and other.id != ignore_id


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_employees(
    db: Session, search: str, status_filter: str, limit: int, offset: int
) -> list[Employee]:
    stmt = select(Employee).order_by(Employee.employee_code).limit(limit).offset(offset)
    if status_filter in ("active", "inactive"):
        stmt = stmt.where(Employee.status == status_filter)
    term = search.strip()
    if term:
        like = f"%{_escape_like(term)}%"
        stmt = stmt.where(
            or_(
                Employee.full_name.ilike(like, escape="\\"),
                Employee.employee_code.ilike(like, escape="\\"),
            )
        )
    return list(db.scalars(stmt))


def create_employee(db: Session, data: EmployeeCreate) -> Employee:
    code = data.employee_code or next_employee_code(db)
    if _code_taken(db, code):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Employee code '{code}' already exists")
    employee = Employee(
        employee_code=code,
        full_name=data.full_name,
        designation=data.designation,
        joining_date=data.joining_date,
        email=data.email,
        phone=data.phone,
        status="active",
    )
    db.add(employee)
    try:
        db.commit()
    except IntegrityError:  # concurrent create got the same code
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Employee code already exists") from None
    logger.info(f"employee created id={employee.id}", extra={"event": "employee_created"})
    return employee


def update_employee(db: Session, employee: Employee, data: EmployeeUpdate) -> Employee:
    sent = data.model_fields_set
    if "employee_code" in sent and _code_taken(db, data.employee_code, ignore_id=employee.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Employee code '{data.employee_code}' already exists"
        )
    for name in ("full_name", "designation", "joining_date", "employee_code", "email", "phone"):
        if name in sent:
            setattr(employee, name, getattr(data, name))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Employee code already exists") from None
    return employee


def set_status(db: Session, employee: Employee, active: bool) -> Employee:
    if active and employee.status != "active":
        employee.status = "active"
        employee.deactivated_at = None
    elif not active and employee.status != "inactive":
        employee.status = "inactive"
        employee.deactivated_at = datetime.now(UTC)
    else:
        return employee  # already in the requested state
    db.commit()
    logger.info(
        f"employee {'reactivated' if active else 'deactivated'} id={employee.id}",
        extra={"event": "employee_status_changed"},
    )
    return employee
