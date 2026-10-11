"""File outputs: payslip PDF, payroll CSV, bank payout CSV. All use SNAPSHOT data only."""

import csv
import io
from decimal import Decimal

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from app.config import get_settings
from app.models import PayrollLineItem

_NEXT_LINE = {"new_x": XPos.LMARGIN, "new_y": YPos.NEXT}


def _money(amount: Decimal) -> str:
    # "Rs." not the rupee sign: fpdf2's built-in fonts are Latin-1 only.
    return f"Rs. {amount:,.2f}"


def payslip_pdf(item: PayrollLineItem, period_label: str) -> bytes:
    settings = get_settings()
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, settings.company_name, **_NEXT_LINE)
    if settings.company_address:
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, settings.company_address, **_NEXT_LINE)
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "Payslip", **_NEXT_LINE)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Pay Period: {period_label}", **_NEXT_LINE)
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, f"{item.employee_name_snapshot} ({item.employee_code_snapshot})", **_NEXT_LINE)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(
        0,
        6,
        f"Working days: {item.total_working_days:.1f}   Present: {item.days_present:.1f}   "
        f"Paid leave: {item.paid_leave_days:.1f}",
        **_NEXT_LINE,
    )
    pdf.cell(
        0,
        6,
        f"Unpaid leave: {item.unpaid_leave_days:.1f}   Absent: {item.absent_days:.1f}   "
        f"Loss-of-pay days: {item.loss_of_pay_days:.1f}   Payable days: {item.payable_days:.1f}",
        **_NEXT_LINE,
    )
    pdf.ln(4)

    def section(title: str, rows: list, total: Decimal) -> None:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, title, **_NEXT_LINE)
        pdf.set_font("Helvetica", "", 10)
        for row in rows:
            pdf.cell(130, 6, row.name)
            pdf.cell(0, 6, _money(row.amount), align="R", **_NEXT_LINE)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(130, 7, f"Total {title}")
        pdf.cell(0, 7, _money(total), align="R", **_NEXT_LINE)
        pdf.ln(3)

    section(
        "Earnings", [c for c in item.components if c.component_type == "earning"], item.gross_pay
    )
    section(
        "Deductions",
        [c for c in item.components if c.component_type == "deduction"],
        item.total_deductions,
    )

    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(130, 10, "Net Pay")
    pdf.cell(0, 10, _money(item.net_pay), align="R", **_NEXT_LINE)
    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 8)
    pdf.cell(0, 5, "This is a system-generated payslip.", **_NEXT_LINE)
    return bytes(pdf.output())


def _safe(cell: str) -> str:
    """Stop spreadsheet formula injection: a name like '=cmd|...' must not run in Excel."""
    return "'" + cell if cell[:1] in ("=", "+", "-", "@") else cell


def payroll_csv(items: list[PayrollLineItem]) -> bytes:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(
        [
            "Employee Code",
            "Employee Name",
            "Working Days",
            "Present",
            "Paid Leave",
            "Unpaid Leave",
            "Absent",
            "Loss Of Pay Days",
            "Payable Days",
            "Gross Pay",
            "Total Deductions",
            "Net Pay",
        ]
    )
    for i in items:
        w.writerow(
            [
                _safe(i.employee_code_snapshot),
                _safe(i.employee_name_snapshot),
                f"{i.total_working_days:.1f}",
                f"{i.days_present:.1f}",
                f"{i.paid_leave_days:.1f}",
                f"{i.unpaid_leave_days:.1f}",
                f"{i.absent_days:.1f}",
                f"{i.loss_of_pay_days:.1f}",
                f"{i.payable_days:.1f}",
                f"{i.gross_pay:.2f}",
                f"{i.total_deductions:.2f}",
                f"{i.net_pay:.2f}",
            ]
        )
    return out.getvalue().encode("utf-8")


def bank_payout_csv(items: list[PayrollLineItem], bank_details: dict[int, dict | None]) -> bytes:
    """NEFT batch file. `bank_details[employee_id]` comes from employee-service's reveal endpoint;
    None means that employee has no bank details on file (row is written blank so it is visible)."""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(
        [
            "Employee Code",
            "Employee Name",
            "Account Holder Name",
            "Account Number",
            "IFSC Code",
            "Bank Name",
            "Net Pay",
        ]
    )
    for i in items:
        bank = bank_details.get(i.employee_id) or {}
        w.writerow(
            [
                _safe(i.employee_code_snapshot),
                _safe(i.employee_name_snapshot),
                _safe(bank.get("account_holder_name") or ""),
                bank.get("account_number") or "",
                bank.get("ifsc_code") or "",
                _safe(bank.get("bank_name") or ""),
                f"{i.net_pay:.2f}",
            ]
        )
    return out.getvalue().encode("utf-8")
