from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app import outputs, payroll_service
from app.clients import EmployeeClient, LeaveClient, get_employee_client, get_leave_client
from app.database import get_db
from app.metrics import BANK_FILES
from app.periods import format_period, parse_period
from app.schemas import LineItemOut, RunDetailOut, RunIn, RunOut
from app.security import CurrentUser, require_admin

router = APIRouter(prefix="/payroll/runs", tags=["payroll"])


def _detail(run) -> RunDetailOut:
    return RunDetailOut(
        **RunOut.from_run(run).model_dump(),
        line_items=[LineItemOut.from_item(li) for li in run.line_items],
    )


def _attachment(content: bytes, media_type: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("", response_model=RunDetailOut, status_code=status.HTTP_201_CREATED)
def run_payroll(
    body: RunIn,
    admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
    employees: EmployeeClient = Depends(get_employee_client),
    leave: LeaveClient = Depends(get_leave_client),
):
    """Run payroll for a month. Pulls salaries from employee-service and approved leave from
    leave-service, then stores the whole run in one transaction (all or nothing)."""
    run = payroll_service.run_payroll(db, parse_period(body.period), admin, employees, leave)
    return _detail(run)


@router.get("", response_model=list[RunOut])
def list_runs(_admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    return [RunOut.from_run(r) for r in payroll_service.list_runs(db)]


@router.get("/{run_id}", response_model=RunDetailOut)
def get_run(
    run_id: int, _admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)
):
    return _detail(payroll_service.get_run_or_404(db, run_id))


@router.get("/{run_id}/export.csv")
def export_csv(
    run_id: int, _admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)
):
    run = payroll_service.get_run_or_404(db, run_id)
    return _attachment(
        outputs.payroll_csv(run.line_items), "text/csv", f"payroll_{format_period(run.period)}.csv"
    )


@router.get("/{run_id}/bank-file")
def bank_file(
    run_id: int,
    admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
    employees: EmployeeClient = Depends(get_employee_client),
):
    """NEFT payout CSV. Fetches each account number from employee-service, which audit-logs
    every reveal. If employee-service is down the file is NOT produced (503), never half-filled."""
    run = payroll_service.get_run_or_404(db, run_id)
    details = {
        li.employee_id: employees.reveal_bank(li.employee_id, admin.token) for li in run.line_items
    }
    BANK_FILES.inc()
    return _attachment(
        outputs.bank_payout_csv(run.line_items, details),
        "text/csv",
        f"bank_payout_{format_period(run.period)}.csv",
    )
