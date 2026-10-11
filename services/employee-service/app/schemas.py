import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
    model_validator,
)

# Money in responses is always a 2-decimal STRING ("50000.00"), same from every endpoint.
Money = Annotated[
    Decimal,
    Field(max_digits=12, decimal_places=2),
    PlainSerializer(lambda d: f"{d:.2f}", return_type=str, when_used="json"),
]
PositiveMoney = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
NonNegMoney = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]


def Text(max_length: int):  # noqa: N802 - used like a type: Text(120)
    return Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length)
    ]


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?[0-9][0-9 \-]{5,18}$")
_IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
_ACCOUNT_RE = re.compile(r"^[A-Za-z0-9]{6,34}$")
_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,20}$")


def _email(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    if len(v) > 120 or not _EMAIL_RE.match(v):
        raise ValueError("Enter a valid email address")
    return v


def _phone(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    if not _PHONE_RE.match(v):
        raise ValueError("Enter a valid phone number")
    return v


def _code(v: str) -> str:
    v = v.strip()
    if not _CODE_RE.match(v):
        raise ValueError("Employee code: up to 20 letters, digits, '-' or '_'")
    return v


Email = Annotated[str | None, AfterValidator(_email)]
Phone = Annotated[str | None, AfterValidator(_phone)]
EmployeeCode = Annotated[str, AfterValidator(_code)]


# ---------------- employees ----------------
class EmployeeCreate(BaseModel):
    full_name: Text(120)
    designation: Text(80)
    joining_date: date
    employee_code: EmployeeCode | None = None  # generated (EMP0001...) when omitted
    email: Email = None
    phone: Phone = None


class EmployeeUpdate(BaseModel):
    full_name: Text(120) | None = None
    designation: Text(80) | None = None
    joining_date: date | None = None
    employee_code: EmployeeCode | None = None
    email: Email = None  # send null or "" to clear
    phone: Phone = None

    @model_validator(mode="after")
    def _check(self):
        sent = self.model_fields_set
        if not sent:
            raise ValueError("Provide at least one field to update")
        for name in ("full_name", "designation", "joining_date", "employee_code"):
            if name in sent and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class EmployeeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_code: str
    full_name: str
    designation: str
    joining_date: date
    email: str | None
    phone: str | None
    status: Literal["active", "inactive"]
    deactivated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ExistsOut(BaseModel):
    exists: bool
    is_active: bool


class NextCodeOut(BaseModel):
    employee_code: str


# ---------------- salary ----------------
class ComponentIn(BaseModel):
    component_type: Literal["allowance", "deduction"]
    name: Text(60)
    amount: NonNegMoney


class ComponentOut(BaseModel):
    component_type: Literal["allowance", "deduction"]
    name: str
    amount: Money

    model_config = ConfigDict(from_attributes=True)


class SalaryIn(BaseModel):
    basic_pay: PositiveMoney
    hra: NonNegMoney = Decimal("0")
    conveyance_allowance: NonNegMoney = Decimal("0")
    components: list[ComponentIn] = Field(default_factory=list, max_length=50)
    # When this version starts. Default: the employee's joining date for a first salary,
    # today for a change to an existing one. Ignored if the salary values don't change.
    effective_from: date | None = None


class SalaryOut(BaseModel):
    employee_id: int
    basic_pay: Money
    hra: Money
    conveyance_allowance: Money
    components: list[ComponentOut]
    effective_from: date


class SalaryHistoryOut(SalaryOut):
    id: int
    superseded_at: datetime
    created_by_user_id: int | None


class PayrollEmployeeOut(EmployeeOut):
    """One employee plus the salary in effect on the requested date (null if none)."""

    salary: SalaryOut | None


# ---------------- bank details ----------------
class BankDetailsIn(BaseModel):
    account_holder_name: Text(120)
    # Optional only when updating existing details (keeps the stored number unchanged).
    account_number: str | None = None
    ifsc_code: str | None = None
    bank_name: Text(80) | None = None

    @model_validator(mode="after")
    def _normalise(self):
        if self.account_number is not None:
            self.account_number = self.account_number.strip().replace(" ", "")
            if not _ACCOUNT_RE.match(self.account_number):
                raise ValueError("Account number must be 6-34 letters/digits")
        if self.ifsc_code is not None:
            code = self.ifsc_code.strip().upper()
            if code and not _IFSC_RE.match(code):
                raise ValueError("Invalid IFSC code (expected like HDFC0001234)")
            self.ifsc_code = code or None
        return self


class BankDetailsOut(BaseModel):
    employee_id: int
    account_holder_name: str
    account_number_masked: str
    account_number_last4: str
    ifsc_code: str | None
    bank_name: str | None
    updated_at: datetime


class BankDetailsRevealOut(BankDetailsOut):
    account_number: str
