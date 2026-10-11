from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app import outputs, payroll_service
from app.database import get_db
from app.periods import format_period, period_label
from app.schemas import PayslipSummaryOut
from app.security import CurrentUser, require_any_role

router = APIRouter(prefix="/payslips", tags=["payslips"])


@router.get("/my", response_model=list[PayslipSummaryOut])
def my_payslips(user: CurrentUser = Depends(require_any_role), db: Session = Depends(get_db)):
    if user.employee_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Your account is not linked to an employee record"
        )
    return [
        PayslipSummaryOut(
            id=li.id,
            period=format_period(li.payroll_run.period),
            gross_pay=li.gross_pay,
            total_deductions=li.total_deductions,
            net_pay=li.net_pay,
        )
        for li in payroll_service.payslips_for_employee(db, user.employee_id)
    ]


@router.get("/{payslip_id}/pdf")
def payslip_pdf(
    payslip_id: int,
    user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    """Your own payslip, or any payslip if you are an admin."""
    item = payroll_service.get_line_item_or_404(db, payslip_id)
    if not user.is_admin and item.employee_id != user.employee_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only download your own payslips")
    pdf = outputs.payslip_pdf(item, period_label(item.payroll_run.period))
    filename = f"payslip_{item.employee_code_snapshot}_{format_period(item.payroll_run.period)}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
