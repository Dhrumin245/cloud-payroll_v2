"""Payroll run: gather inputs from the other services, calculate, persist atomically."""

import logging
from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app import engine
from app.clients import EmployeeClient, LeaveClient
from app.metrics import LAST_RUN_EMPLOYEES, LAST_RUN_NET_PAY, PAYROLL_RUNS
from app.models import (
    AttendanceRecord,
    PayrollLineItem,
    PayrollLineItemComponent,
    PayrollRun,
    VariablePayItem,
)
from app.period_lock import is_locked
from app.periods import format_period, is_future, last_day, working_days
from app.security import CurrentUser
from app.statutory import StatutoryContext

logger = logging.getLogger("app.payroll")
ZERO = Decimal(0)


def _reject(code: int, detail) -> HTTPException:
    PAYROLL_RUNS.labels(outcome="rejected").inc()
    return HTTPException(code, detail)


def get_run_or_404(db: Session, run_id: int) -> PayrollRun:
    run = db.scalar(
        select(PayrollRun)
        .options(selectinload(PayrollRun.line_items).selectinload(PayrollLineItem.components))
        .where(PayrollRun.id == run_id)
    )
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payroll run not found")
    return run


def list_runs(db: Session) -> list[PayrollRun]:
    return list(db.scalars(select(PayrollRun).order_by(PayrollRun.period.desc())))


def run_payroll(
    db: Session,
    period: date,
    actor: CurrentUser,
    employees: EmployeeClient,
    leave: LeaveClient,
) -> PayrollRun:
    label = format_period(period)
    if is_locked(db, period):
        raise _reject(status.HTTP_409_CONFLICT, f"Payroll for {label} has already been processed")
    if is_future(period):
        raise _reject(status.HTTP_409_CONFLICT, f"Cannot run payroll for a future month ({label})")

    # 1. Who is on the payroll, and what did each earn on the last day of the month?
    staff = employees.payroll_data(last_day(period), actor.token)
    if not staff:
        raise _reject(status.HTTP_422_UNPROCESSABLE_ENTITY, "No active employees to process")
    # 2. Approved leave in that month, split paid / unpaid.
    leave_days = leave.approved(label, actor.token)

    absences = {
        a.employee_id: a.days_absent
        for a in db.scalars(select(AttendanceRecord).where(AttendanceRecord.period == period))
    }
    variable: dict[int, list[VariablePayItem]] = {}
    for item in db.scalars(select(VariablePayItem).where(VariablePayItem.period == period)):
        variable.setdefault(item.employee_id, []).append(item)

    total_days = Decimal(working_days(period))
    statutory = StatutoryContext(db)
    inputs: list[engine.PayrollInput] = []
    problems: list[str] = []

    for emp in staff:
        if emp.salary is None:
            problems.append(f"{emp.full_name} ({emp.employee_code}): no salary structure in effect")
            continue
        leave_for_emp = leave_days.get(emp.id)
        components = [engine.ComponentInput(t, n, a) for t, n, a in emp.salary.components]
        components += [
            engine.ComponentInput(v.component_type, v.name, v.amount)
            for v in variable.get(emp.id, [])
        ]
        data = engine.PayrollInput(
            employee_id=emp.id,
            employee_code=emp.employee_code,
            employee_name=emp.full_name,
            basic_pay=emp.salary.basic_pay,
            hra=emp.salary.hra,
            conveyance_allowance=emp.salary.conveyance_allowance,
            components=components,
            total_working_days=total_days,
            paid_leave_days=leave_for_emp.paid_days if leave_for_emp else ZERO,
            unpaid_leave_days=leave_for_emp.unpaid_days if leave_for_emp else ZERO,
            absent_days=absences.get(emp.id, ZERO),
        )
        problem = engine.validate_days(data)
        if problem:
            problems.append(f"{emp.full_name} ({emp.employee_code}): {problem}")
            continue
        # Statutory deductions depend on gross, which depends on attendance, so add them last.
        names = {c.name for c in components}
        data.components += statutory.deductions(data.basic_pay, engine.prorated_gross(data), names)
        inputs.append(data)

    if problems:  # all-or-nothing, but report EVERY problem at once
        raise _reject(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"message": "Payroll cannot run until these are fixed", "problems": problems},
        )

    result = engine.calculate_run(inputs)

    run = PayrollRun(
        period=period,
        run_date=datetime.now(UTC),
        status="completed",
        total_gross=result.total_gross,
        total_deductions=result.total_deductions,
        total_net_pay=result.total_net_pay,
        employee_count=result.employee_count,
        run_by_user_id=actor.user_id,
    )
    for r in result.line_items:
        run.line_items.append(
            PayrollLineItem(
                employee_id=r.employee_id,
                employee_code_snapshot=r.employee_code,
                employee_name_snapshot=r.employee_name,
                total_working_days=r.total_working_days,
                days_present=r.days_present,
                paid_leave_days=r.paid_leave_days,
                unpaid_leave_days=r.unpaid_leave_days,
                absent_days=r.absent_days,
                loss_of_pay_days=r.loss_of_pay_days,
                payable_days=r.payable_days,
                gross_pay=r.gross_pay,
                total_deductions=r.total_deductions,
                net_pay=r.net_pay,
                components=[
                    PayrollLineItemComponent(
                        component_type=c.component_type, name=c.name, amount=c.amount
                    )
                    for c in r.components
                ],
            )
        )
    db.add(run)
    try:
        db.commit()  # one commit: no partial run is ever stored
    except IntegrityError:  # a concurrent run for the same month won the race
        db.rollback()
        raise _reject(
            status.HTTP_409_CONFLICT, f"Payroll for {label} has already been processed"
        ) from None

    PAYROLL_RUNS.labels(outcome="completed").inc()
    LAST_RUN_EMPLOYEES.set(run.employee_count)
    LAST_RUN_NET_PAY.set(float(run.total_net_pay))
    logger.info(
        f"payroll completed period={label} employees={run.employee_count} "
        f"by user_id={actor.user_id}",
        extra={"event": "payroll_completed"},
    )
    return get_run_or_404(db, run.id)


def get_line_item_or_404(db: Session, line_item_id: int) -> PayrollLineItem:
    item = db.scalar(
        select(PayrollLineItem)
        .options(
            selectinload(PayrollLineItem.components), selectinload(PayrollLineItem.payroll_run)
        )
        .where(PayrollLineItem.id == line_item_id)
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payslip not found")
    return item


def payslips_for_employee(db: Session, employee_id: int) -> list[PayrollLineItem]:
    return list(
        db.scalars(
            select(PayrollLineItem)
            .options(selectinload(PayrollLineItem.payroll_run))
            .join(PayrollRun)
            .where(PayrollLineItem.employee_id == employee_id)
            .order_by(PayrollRun.period.desc())
        )
    )
