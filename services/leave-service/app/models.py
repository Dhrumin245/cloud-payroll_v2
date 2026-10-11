"""leave_db tables. employee_id / user ids are plain integers (they live in other services)."""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
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

from app.leave_rules import count_leave_days

STATUSES = ("pending", "approved", "rejected", "cancelled")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class LeaveType(Base):
    __tablename__ = "leave_types"
    __table_args__ = (
        UniqueConstraint("name", name="uq_leave_types_name"),
        CheckConstraint(
            "max_days_per_year IS NULL OR max_days_per_year > 0", name="ck_leave_types_max_days"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    # NULL = unlimited
    max_days_per_year: Mapped[Decimal | None] = mapped_column(Numeric(5, 1), nullable=True)
    # unpaid leave becomes loss-of-pay in payroll-service
    is_paid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class LeaveRequest(Base):
    __tablename__ = "leave_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'cancelled')",
            name="ck_leave_requests_status",
        ),
        CheckConstraint("start_date <= end_date", name="ck_leave_requests_dates"),
        Index("ix_leave_requests_employee_id", "employee_id"),
        Index("ix_leave_requests_status_start", "status", "start_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(Integer, nullable=False)  # employee-service id
    leave_type_id: Mapped[int] = mapped_column(
        ForeignKey("leave_types.id", ondelete="RESTRICT"), nullable=False
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="pending")
    decided_by_user_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # auth-service id
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    leave_type: Mapped[LeaveType] = relationship()

    @property
    def total_days(self) -> Decimal:
        return count_leave_days(self.start_date, self.end_date, self.start_date, self.end_date)


class LeaveBalance(Base):
    """Approved days used, per employee / leave type / year."""

    __tablename__ = "leave_balances"
    __table_args__ = (
        UniqueConstraint(
            "employee_id", "leave_type_id", "year", name="uq_leave_balance_emp_type_year"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(Integer, nullable=False)
    leave_type_id: Mapped[int] = mapped_column(
        ForeignKey("leave_types.id", ondelete="CASCADE"), nullable=False
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    days_used: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False, default=0)
