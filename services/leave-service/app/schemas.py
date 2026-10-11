from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
    model_validator,
)

# Day counts in responses are always 1-decimal strings ("3.0").
Days = Annotated[Decimal, PlainSerializer(lambda d: f"{d:.1f}", return_type=str, when_used="json")]
MaxDays = Annotated[Decimal, Field(gt=0, max_digits=5, decimal_places=1)]
Status = Literal["pending", "approved", "rejected", "cancelled"]


def Text(max_length: int):  # noqa: N802 - used like a type: Text(60)
    return Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length)
    ]


# ---------------- leave types ----------------
class LeaveTypeIn(BaseModel):
    name: Text(60)
    max_days_per_year: MaxDays | None = None  # null = unlimited
    is_paid: bool = True


class LeaveTypeUpdate(BaseModel):
    name: Text(60) | None = None
    max_days_per_year: MaxDays | None = None  # send null for unlimited
    is_paid: bool | None = None

    @model_validator(mode="after")
    def _check(self):
        sent = self.model_fields_set
        if not sent:
            raise ValueError("Provide at least one field to update")
        for field in ("name", "is_paid"):
            if field in sent and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class LeaveTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    max_days_per_year: Days | None
    is_paid: bool


# ---------------- leave requests ----------------
class LeaveRequestIn(BaseModel):
    leave_type_id: int
    start_date: date
    end_date: date
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None = None

    @model_validator(mode="after")
    def _dates(self):
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self


class DecisionNote(BaseModel):
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None = None


class RejectIn(BaseModel):
    reason: Text(255)


class LeaveRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: int
    leave_type: LeaveTypeOut
    start_date: date
    end_date: date
    total_days: Days
    reason: str | None
    status: Status
    decided_by_user_id: int | None
    decided_at: datetime | None
    decision_note: str | None
    created_at: datetime
    updated_at: datetime


# ---------------- balances / payroll hand-off ----------------
class BalanceItem(BaseModel):
    leave_type_id: int
    leave_type_name: str
    is_paid: bool
    max_days_per_year: Days | None
    days_used: Days
    days_pending: Days
    remaining: Days | None


class BalanceOut(BaseModel):
    employee_id: int
    year: int
    balances: list[BalanceItem]


class ApprovedLeaveItem(BaseModel):
    employee_id: int
    paid_days: Days
    unpaid_days: Days


class ApprovedLeaveOut(BaseModel):
    month: str
    employees: list[ApprovedLeaveItem]
