"""payroll_db tables. employee_id / user ids are plain integers (they live in other services).

Payroll history is SNAPSHOT data: names, codes, day counts and amounts are copied into the
line items at run time, so old payslips never change when an employee's record does.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class AttendanceRecord(Base):
    """Unexplained absence for one employee in one month (approved leave: leave-service)."""

    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint("employee_id", "period", name="uq_attendance_employee_period"),
        CheckConstraint("days_absent >= 0", name="ck_attendance_days_absent_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(Integer, nullable=False)
    period: Mapped[date] = mapped_column(Date, nullable=False)  # first day of the month
    days_absent: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False, default=0)
    recorded_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class VariablePayItem(Base):
    """One-off bonus / deduction for a single month, on top of the standing salary."""

    __tablename__ = "variable_pay_items"
    __table_args__ = (
        CheckConstraint("component_type IN ('earning', 'deduction')", name="ck_variable_pay_type"),
        CheckConstraint("amount >= 0", name="ck_variable_pay_amount_nonnegative"),
        UniqueConstraint(
            "employee_id", "period", "name", name="uq_variable_pay_employee_period_name"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(Integer, nullable=False)
    period: Mapped[date] = mapped_column(Date, nullable=False)
    component_type: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class PayrollRun(Base):
    __tablename__ = "payroll_runs"
    __table_args__ = (
        CheckConstraint("status IN ('completed')", name="ck_payroll_runs_status"),
        UniqueConstraint("period", name="uq_payroll_runs_period"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period: Mapped[date] = mapped_column(Date, nullable=False)
    run_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="completed")
    total_gross: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total_deductions: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total_net_pay: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    employee_count: Mapped[int] = mapped_column(Integer, nullable=False)
    run_by_user_id: Mapped[int] = mapped_column(Integer, nullable=False)  # auth-service id

    line_items: Mapped[list["PayrollLineItem"]] = relationship(
        back_populates="payroll_run",
        cascade="all, delete-orphan",
        order_by="PayrollLineItem.employee_code_snapshot",
    )


class PayrollLineItem(Base):
    """One employee's result within a run: a snapshot, not a live reference."""

    __tablename__ = "payroll_line_items"
    __table_args__ = (
        UniqueConstraint(
            "payroll_run_id", "employee_id", name="uq_payroll_line_items_run_employee"
        ),
        Index("ix_payroll_line_items_employee_id", "employee_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payroll_run_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[int] = mapped_column(Integer, nullable=False)  # employee-service id
    employee_code_snapshot: Mapped[str] = mapped_column(String(20), nullable=False)
    employee_name_snapshot: Mapped[str] = mapped_column(String(120), nullable=False)
    total_working_days: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False)
    days_present: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False)
    paid_leave_days: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False)
    unpaid_leave_days: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False)
    absent_days: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False)
    loss_of_pay_days: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False)
    payable_days: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False)
    gross_pay: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_deductions: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    net_pay: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    payroll_run: Mapped[PayrollRun] = relationship(back_populates="line_items")
    components: Mapped[list["PayrollLineItemComponent"]] = relationship(
        back_populates="line_item",
        cascade="all, delete-orphan",
        order_by="PayrollLineItemComponent.id",
    )


class PayrollLineItemComponent(Base):
    __tablename__ = "payroll_line_item_components"
    __table_args__ = (
        CheckConstraint(
            "component_type IN ('earning', 'deduction')", name="ck_payroll_components_type"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payroll_line_item_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_line_items.id", ondelete="CASCADE"), nullable=False
    )
    component_type: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    line_item: Mapped[PayrollLineItem] = relationship(back_populates="components")


class StatutoryConfig(Base):
    """Company-wide key/value switches: pf_enabled, esi_enabled, pt_enabled, pt_state."""

    __tablename__ = "statutory_configs"
    __table_args__ = (UniqueConstraint("key", name="uq_statutory_configs_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(60), nullable=False)
    value: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    updated_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class PtSlab(Base):
    """Professional Tax slab for one Indian state."""

    __tablename__ = "pt_slabs"
    __table_args__ = (
        CheckConstraint("gross_from >= 0 AND monthly_tax >= 0", name="ck_pt_slabs_nonnegative"),
        Index("ix_pt_slabs_state_code", "state_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    state_code: Mapped[str] = mapped_column(String(10), nullable=False)
    gross_from: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    gross_to: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )  # NULL = no upper bound
    monthly_tax: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
