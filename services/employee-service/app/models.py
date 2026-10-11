"""employee_db tables. Foreign keys exist only BETWEEN tables of this service."""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app import crypto


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Employee(Base):
    __tablename__ = "employees"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_employees_status"),
        UniqueConstraint("employee_code", name="uq_employees_employee_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_code: Mapped[str] = mapped_column(String(20), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    designation: Mapped[str] = mapped_column(String(80), nullable=False)
    joining_date: Mapped[date] = mapped_column(Date, nullable=False)
    email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    bank_details: Mapped["EmployeeBankDetails | None"] = relationship(
        back_populates="employee", uselist=False, cascade="all, delete-orphan"
    )
    salary_structure: Mapped["SalaryStructure | None"] = relationship(
        back_populates="employee", uselist=False, cascade="all, delete-orphan"
    )
    salary_history: Mapped[list["SalaryStructureHistory"]] = relationship(
        back_populates="employee", cascade="all, delete-orphan"
    )


class EmployeeBankDetails(Base):
    """The raw account number is never stored: only ciphertext plus the last 4 digits."""

    __tablename__ = "employee_bank_details"
    __table_args__ = (UniqueConstraint("employee_id", name="uq_bank_details_employee_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    account_holder_name: Mapped[str] = mapped_column(String(120), nullable=False)
    account_number_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    account_number_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    ifsc_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    employee: Mapped[Employee] = relationship(back_populates="bank_details")

    def set_account_number(self, plaintext: str) -> None:
        self.account_number_encrypted = crypto.encrypt(plaintext)
        self.account_number_last4 = crypto.last4(plaintext)

    def reveal_account_number(self) -> str:
        """Decrypts. Only call from a deliberate, audit-logged code path."""
        return crypto.decrypt(self.account_number_encrypted)


class SalaryStructure(Base):
    """CURRENT salary, one row per employee. Earlier versions live in SalaryStructureHistory."""

    __tablename__ = "salary_structures"
    __table_args__ = (
        CheckConstraint("basic_pay > 0", name="ck_salary_structures_basic_pay_positive"),
        CheckConstraint("hra >= 0", name="ck_salary_structures_hra_nonnegative"),
        CheckConstraint("conveyance_allowance >= 0", name="ck_salary_structures_conv_nonnegative"),
        UniqueConstraint("employee_id", name="uq_salary_structures_employee_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    basic_pay: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    hra: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    conveyance_allowance: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    employee: Mapped[Employee] = relationship(back_populates="salary_structure")
    components: Mapped[list["SalaryComponent"]] = relationship(
        back_populates="salary_structure",
        cascade="all, delete-orphan",
        order_by="SalaryComponent.id",
    )


class SalaryComponent(Base):
    """Extra allowance / deduction line attached to the current salary structure."""

    __tablename__ = "salary_components"
    __table_args__ = (
        CheckConstraint(
            "component_type IN ('allowance', 'deduction')", name="ck_salary_components_type"
        ),
        CheckConstraint("amount >= 0", name="ck_salary_components_amount_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    salary_structure_id: Mapped[int] = mapped_column(
        ForeignKey("salary_structures.id", ondelete="CASCADE"), nullable=False
    )
    component_type: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    salary_structure: Mapped[SalaryStructure] = relationship(back_populates="components")


class SalaryStructureHistory(Base):
    """Immutable copy of a PREVIOUS salary structure, written when a salary changes.

    `effective_from` is when that version started; it ended when the next version took over.
    """

    __tablename__ = "salary_structure_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    basic_pay: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    hra: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    conveyance_allowance: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # [{"component_type": ..., "name": ..., "amount": "123.00"}]
    components: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    superseded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    # user id in auth-service of whoever made the change (plain integer, no foreign key)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    employee: Mapped[Employee] = relationship(back_populates="salary_history")
