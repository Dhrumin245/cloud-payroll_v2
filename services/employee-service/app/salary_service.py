import logging
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.metrics import SALARY_CHANGES
from app.models import (
    Employee,
    SalaryComponent,
    SalaryStructure,
    SalaryStructureHistory,
)
from app.schemas import SalaryIn, SalaryOut

logger = logging.getLogger("app.salary")


def _components_key(items) -> list[tuple]:
    return sorted((c.component_type, c.name.strip(), c.amount) for c in items)


def _is_unchanged(current: SalaryStructure, data: SalaryIn) -> bool:
    return (
        current.basic_pay == data.basic_pay
        and current.hra == data.hra
        and current.conveyance_allowance == data.conveyance_allowance
        and _components_key(current.components) == _components_key(data.components)
    )


def _to_out(
    employee_id: int, basic_pay, hra, conveyance, components, effective_from: date
) -> SalaryOut:
    return SalaryOut(
        employee_id=employee_id,
        basic_pay=basic_pay,
        hra=hra,
        conveyance_allowance=conveyance,
        components=components,
        effective_from=effective_from,
    )


def structure_to_out(s: SalaryStructure) -> SalaryOut:
    comps = [
        {"component_type": c.component_type, "name": c.name, "amount": c.amount}
        for c in s.components
    ]
    return _to_out(
        s.employee_id, s.basic_pay, s.hra, s.conveyance_allowance, comps, s.effective_from
    )


def history_to_out(h: SalaryStructureHistory) -> SalaryOut:
    return _to_out(
        h.employee_id, h.basic_pay, h.hra, h.conveyance_allowance, h.components, h.effective_from
    )


def get_current(db: Session, employee_id: int) -> SalaryStructure | None:
    return db.scalar(select(SalaryStructure).where(SalaryStructure.employee_id == employee_id))


def salary_as_of(db: Session, employee_id: int, as_of: date) -> SalaryOut | None:
    """The salary version that was in effect on `as_of` (None if nothing was yet)."""
    current = get_current(db, employee_id)
    if current is not None and current.effective_from <= as_of:
        return structure_to_out(current)
    row = db.scalar(
        select(SalaryStructureHistory)
        .where(
            SalaryStructureHistory.employee_id == employee_id,
            SalaryStructureHistory.effective_from <= as_of,
        )
        .order_by(SalaryStructureHistory.effective_from.desc(), SalaryStructureHistory.id.desc())
        .limit(1)
    )
    return history_to_out(row) if row is not None else None


def list_history(db: Session, employee_id: int) -> list[SalaryStructureHistory]:
    return list(
        db.scalars(
            select(SalaryStructureHistory)
            .where(SalaryStructureHistory.employee_id == employee_id)
            .order_by(
                SalaryStructureHistory.effective_from.desc(), SalaryStructureHistory.id.desc()
            )
        )
    )


def set_salary(
    db: Session, employee: Employee, data: SalaryIn, actor_user_id: int
) -> SalaryStructure:
    """Create the salary, or replace it. A real change archives the old version first."""
    current = get_current(db, employee.id)
    new_components = [
        SalaryComponent(component_type=c.component_type, name=c.name, amount=c.amount)
        for c in data.components
    ]

    if current is None:
        current = SalaryStructure(
            employee_id=employee.id,
            basic_pay=data.basic_pay,
            hra=data.hra,
            conveyance_allowance=data.conveyance_allowance,
            # a FIRST salary takes effect from the joining date, so payroll for earlier months works
            effective_from=data.effective_from or employee.joining_date,
            components=new_components,
        )
        db.add(current)
        db.commit()
        logger.info(f"salary set employee_id={employee.id}", extra={"event": "salary_set"})
        return current

    if _is_unchanged(current, data):
        return current  # nothing to archive, nothing to change

    db.add(
        SalaryStructureHistory(
            employee_id=employee.id,
            basic_pay=current.basic_pay,
            hra=current.hra,
            conveyance_allowance=current.conveyance_allowance,
            components=[
                {"component_type": c.component_type, "name": c.name, "amount": str(c.amount)}
                for c in current.components
            ],
            effective_from=current.effective_from,
            superseded_at=datetime.now(UTC),
            created_by_user_id=actor_user_id,
        )
    )
    current.basic_pay = data.basic_pay
    current.hra = data.hra
    current.conveyance_allowance = data.conveyance_allowance
    current.effective_from = data.effective_from or date.today()
    current.components = new_components
    db.commit()
    SALARY_CHANGES.inc()
    logger.info(
        f"salary changed employee_id={employee.id} by user_id={actor_user_id}",
        extra={"event": "salary_changed"},
    )
    return current


def payroll_data(db: Session, as_of: date) -> list[tuple[Employee, SalaryOut | None]]:
    """Active employees who had joined by `as_of`, each with the salary in effect then."""
    employees = db.scalars(
        select(Employee)
        .where(Employee.status == "active", Employee.joining_date <= as_of)
        .order_by(Employee.employee_code)
    )
    return [(e, salary_as_of(db, e.id, as_of)) for e in employees]
