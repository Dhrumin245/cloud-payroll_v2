"""Pure payroll calculation: no FastAPI, no database, no HTTP. Easy to unit test.

Ported from the legacy engine, with loss-of-pay added:

    total_working_days  every day of the month except Sundays
    paid_leave_days     approved leave of a PAID type        (from leave-service)
    unpaid_leave_days   approved leave of an UNPAID type     (from leave-service)
    absent_days         unexplained absence recorded by HR   (attendance record)
    ------------------------------------------------------------------------
    loss_of_pay_days    = unpaid_leave_days + absent_days
    payable_days        = total_working_days - loss_of_pay_days
    days_present        = total_working_days - paid_leave - unpaid_leave - absent

Fixed salary parts and 'allowance' components are prorated by payable_days / total_working_days.
'earning' components (one-off bonuses) and all deductions apply at their full amount.
Net pay is NOT floored at zero: a negative number is shown rather than hidden.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

TWO_PLACES = Decimal("0.01")
ZERO = Decimal("0.00")


@dataclass
class ComponentInput:
    component_type: str  # "allowance" (prorated) | "earning" (full) | "deduction" (full)
    name: str
    amount: Decimal


@dataclass
class PayrollInput:
    employee_id: int
    employee_code: str
    employee_name: str
    basic_pay: Decimal
    hra: Decimal
    conveyance_allowance: Decimal
    components: list[ComponentInput]
    total_working_days: Decimal
    paid_leave_days: Decimal = Decimal(0)
    unpaid_leave_days: Decimal = Decimal(0)
    absent_days: Decimal = Decimal(0)

    @property
    def days_on_leave(self) -> Decimal:
        return self.paid_leave_days + self.unpaid_leave_days

    @property
    def days_present(self) -> Decimal:
        return self.total_working_days - self.days_on_leave - self.absent_days

    @property
    def loss_of_pay_days(self) -> Decimal:
        return self.unpaid_leave_days + self.absent_days

    @property
    def payable_days(self) -> Decimal:
        return self.total_working_days - self.loss_of_pay_days


@dataclass
class LineComponent:
    component_type: str  # "earning" | "deduction"
    name: str
    amount: Decimal


@dataclass
class PayrollResult:
    employee_id: int
    employee_code: str
    employee_name: str
    total_working_days: Decimal
    days_present: Decimal
    paid_leave_days: Decimal
    unpaid_leave_days: Decimal
    absent_days: Decimal
    loss_of_pay_days: Decimal
    payable_days: Decimal
    gross_pay: Decimal
    total_deductions: Decimal
    net_pay: Decimal
    components: list[LineComponent] = field(default_factory=list)


@dataclass
class RunResult:
    line_items: list[PayrollResult]
    total_gross: Decimal
    total_deductions: Decimal
    total_net_pay: Decimal
    employee_count: int


def _round(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def validate_days(data: PayrollInput) -> str | None:
    """A human-readable problem with the day counts, or None if they add up."""
    if data.total_working_days <= 0:
        return "the month has no working days"
    if data.days_present < 0:
        return (
            f"paid leave {data.paid_leave_days} + unpaid leave {data.unpaid_leave_days} + "
            f"absent {data.absent_days} exceeds the {data.total_working_days} working days"
        )
    return None


def prorate(amount: Decimal, data: PayrollInput) -> Decimal:
    return _round(amount * data.payable_days / data.total_working_days)


def prorated_gross(data: PayrollInput) -> Decimal:
    """Gross pay BEFORE statutory deductions exist (they depend on it)."""
    gross = (
        prorate(data.basic_pay, data)
        + prorate(data.hra, data)
        + prorate(data.conveyance_allowance, data)
    )
    for c in data.components:
        if c.component_type == "allowance":
            gross += prorate(c.amount, data)
        elif c.component_type == "earning":
            gross += _round(c.amount)
    return gross


def calculate(data: PayrollInput) -> PayrollResult:
    problem = validate_days(data)
    if problem:
        raise ValueError(f"{data.employee_name}: {problem}")

    lines = [LineComponent("earning", "Basic Pay", prorate(data.basic_pay, data))]
    if data.hra:
        lines.append(LineComponent("earning", "HRA", prorate(data.hra, data)))
    if data.conveyance_allowance:
        lines.append(
            LineComponent(
                "earning", "Conveyance Allowance", prorate(data.conveyance_allowance, data)
            )
        )
    total_deductions = ZERO
    for c in data.components:
        if c.component_type == "allowance":
            lines.append(LineComponent("earning", c.name, prorate(c.amount, data)))
        elif c.component_type == "earning":
            lines.append(LineComponent("earning", c.name, _round(c.amount)))
        elif c.component_type == "deduction":
            amount = _round(c.amount)
            lines.append(LineComponent("deduction", c.name, amount))
            total_deductions += amount
        # any other type is ignored defensively

    gross = sum((ln.amount for ln in lines if ln.component_type == "earning"), ZERO)
    return PayrollResult(
        employee_id=data.employee_id,
        employee_code=data.employee_code,
        employee_name=data.employee_name,
        total_working_days=data.total_working_days,
        days_present=data.days_present,
        paid_leave_days=data.paid_leave_days,
        unpaid_leave_days=data.unpaid_leave_days,
        absent_days=data.absent_days,
        loss_of_pay_days=data.loss_of_pay_days,
        payable_days=data.payable_days,
        gross_pay=gross,
        total_deductions=total_deductions,
        net_pay=gross - total_deductions,
        components=lines,
    )


def calculate_run(inputs: list[PayrollInput]) -> RunResult:
    items = [calculate(i) for i in inputs]
    return RunResult(
        line_items=items,
        total_gross=sum((i.gross_pay for i in items), ZERO),
        total_deductions=sum((i.total_deductions for i in items), ZERO),
        total_net_pay=sum((i.net_pay for i in items), ZERO),
        employee_count=len(items),
    )
