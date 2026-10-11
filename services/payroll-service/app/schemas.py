from datetime import datetime
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

from app.periods import PERIOD_PATTERN, format_period

# Responses: money is a 2-decimal string ("50000.00"), day counts a 1-decimal string ("2.5").
Money = Annotated[Decimal, PlainSerializer(lambda d: f"{d:.2f}", return_type=str, when_used="json")]
Days = Annotated[Decimal, PlainSerializer(lambda d: f"{d:.1f}", return_type=str, when_used="json")]
Period = Annotated[str, Field(pattern=PERIOD_PATTERN, description="YYYY-MM")]


def Text(max_length: int):  # noqa: N802 - used like a type: Text(60)
    return Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length)
    ]


# ---------------- attendance ----------------
class AbsenceIn(BaseModel):
    # half days allowed (0.5); at most one decimal place
    days_absent: Annotated[Decimal, Field(ge=0, max_digits=4, decimal_places=1)]


class AbsenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    employee_id: int
    period: str
    days_absent: Days
    recorded_by_user_id: int | None
    updated_at: datetime

    @classmethod
    def from_record(cls, r) -> "AbsenceOut":
        return cls(
            employee_id=r.employee_id,
            period=format_period(r.period),
            days_absent=r.days_absent,
            recorded_by_user_id=r.recorded_by_user_id,
            updated_at=r.updated_at,
        )


# ---------------- variable pay ----------------
class VariablePayIn(BaseModel):
    employee_id: int = Field(gt=0)
    period: Period
    component_type: Literal["earning", "deduction"]
    name: Text(60)
    amount: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]


class VariablePayOut(BaseModel):
    id: int
    employee_id: int
    period: str
    component_type: str
    name: str
    amount: Money
    created_by_user_id: int | None
    created_at: datetime

    @classmethod
    def from_item(cls, i) -> "VariablePayOut":
        return cls(
            id=i.id,
            employee_id=i.employee_id,
            period=format_period(i.period),
            component_type=i.component_type,
            name=i.name,
            amount=i.amount,
            created_by_user_id=i.created_by_user_id,
            created_at=i.created_at,
        )


# ---------------- payroll runs ----------------
class RunIn(BaseModel):
    period: Period


class ComponentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    component_type: Literal["earning", "deduction"]
    name: str
    amount: Money


class LineItemOut(BaseModel):
    id: int
    employee_id: int
    employee_code: str
    employee_name: str
    total_working_days: Days
    days_present: Days
    paid_leave_days: Days
    unpaid_leave_days: Days
    absent_days: Days
    loss_of_pay_days: Days
    payable_days: Days
    gross_pay: Money
    total_deductions: Money
    net_pay: Money
    components: list[ComponentOut]

    @classmethod
    def from_item(cls, li) -> "LineItemOut":
        return cls(
            id=li.id,
            employee_id=li.employee_id,
            employee_code=li.employee_code_snapshot,
            employee_name=li.employee_name_snapshot,
            total_working_days=li.total_working_days,
            days_present=li.days_present,
            paid_leave_days=li.paid_leave_days,
            unpaid_leave_days=li.unpaid_leave_days,
            absent_days=li.absent_days,
            loss_of_pay_days=li.loss_of_pay_days,
            payable_days=li.payable_days,
            gross_pay=li.gross_pay,
            total_deductions=li.total_deductions,
            net_pay=li.net_pay,
            components=[ComponentOut.model_validate(c) for c in li.components],
        )


class RunOut(BaseModel):
    id: int
    period: str
    run_date: datetime
    status: str
    total_gross: Money
    total_deductions: Money
    total_net_pay: Money
    employee_count: int
    run_by_user_id: int

    @classmethod
    def from_run(cls, r) -> "RunOut":
        return cls(
            id=r.id,
            period=format_period(r.period),
            run_date=r.run_date,
            status=r.status,
            total_gross=r.total_gross,
            total_deductions=r.total_deductions,
            total_net_pay=r.total_net_pay,
            employee_count=r.employee_count,
            run_by_user_id=r.run_by_user_id,
        )


class RunDetailOut(RunOut):
    line_items: list[LineItemOut]


class PayslipSummaryOut(BaseModel):
    id: int  # payroll line item id: use with /payslips/{id}/pdf
    period: str
    gross_pay: Money
    total_deductions: Money
    net_pay: Money


# ---------------- statutory settings ----------------
class StatutorySettingsIn(BaseModel):
    pf_enabled: bool
    esi_enabled: bool
    pt_enabled: bool
    pt_state: str


class StatutorySettingsOut(StatutorySettingsIn):
    pt_states: dict[str, str]


class PtSlabIn(BaseModel):
    state_code: str
    gross_from: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
    gross_to: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)] | None = None
    monthly_tax: Annotated[Decimal, Field(ge=0, max_digits=8, decimal_places=2)]

    @model_validator(mode="after")
    def _range(self):
        if self.gross_to is not None and self.gross_to < self.gross_from:
            raise ValueError("gross_to cannot be less than gross_from")
        return self


class PtSlabOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    state_code: str
    gross_from: Money
    gross_to: Money | None
    monthly_tax: Money
