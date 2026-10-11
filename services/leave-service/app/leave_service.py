"""Leave workflow: apply, approve, reject, cancel, balances, and the payroll hand-off."""

import logging
from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.leave_rules import MAX_SPAN_DAYS, count_leave_days, days_by_year, month_bounds
from app.metrics import LEAVE_EVENTS
from app.models import LeaveBalance, LeaveRequest, LeaveType
from app.schemas import BalanceItem, LeaveRequestIn
from app.security import CurrentUser

logger = logging.getLogger("app.leave")
ZERO = Decimal("0")


def _err(code: int, detail: str) -> HTTPException:
    return HTTPException(code, detail)


# ---------------------------------------------------------------- lookups
def get_request_or_404(db: Session, request_id: int, lock: bool = False) -> LeaveRequest:
    stmt = (
        select(LeaveRequest)
        .options(selectinload(LeaveRequest.leave_type))
        .where(LeaveRequest.id == request_id)
    )
    if lock:
        stmt = stmt.with_for_update()  # serialises concurrent approvals on PostgreSQL
    row = db.scalar(stmt)
    if row is None:
        raise _err(status.HTTP_404_NOT_FOUND, "Leave request not found")
    return row


def _used_days(db: Session, employee_id: int, leave_type_id: int, year: int, lock: bool = False):
    stmt = select(LeaveBalance).where(
        LeaveBalance.employee_id == employee_id,
        LeaveBalance.leave_type_id == leave_type_id,
        LeaveBalance.year == year,
    )
    if lock:
        stmt = stmt.with_for_update()
    return db.scalar(stmt)


def _ensure_within_limit(
    db: Session, employee_id: int, leave_type: LeaveType, per_year: dict[int, Decimal], lock: bool
) -> dict[int, LeaveBalance | None]:
    """409 if approving these days would exceed the yearly entitlement. Returns balance rows."""
    rows: dict[int, LeaveBalance | None] = {}
    for year, days in per_year.items():
        row = _used_days(db, employee_id, leave_type.id, year, lock=lock)
        rows[year] = row
        used = row.days_used if row else ZERO
        limit = leave_type.max_days_per_year
        if limit is not None and used + days > limit:
            raise _err(
                status.HTTP_409_CONFLICT,
                f"Leave limit exceeded for {leave_type.name} in {year}: "
                f"used {used}, requested {days}, allowed {limit}",
            )
    return rows


# ---------------------------------------------------------------- apply
def create_request(db: Session, employee_id: int, data: LeaveRequestIn) -> LeaveRequest:
    leave_type = db.get(LeaveType, data.leave_type_id)
    if leave_type is None:
        raise _err(status.HTTP_404_NOT_FOUND, "Leave type not found")
    if (data.end_date - data.start_date).days >= MAX_SPAN_DAYS:
        raise _err(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"A leave request can span at most {MAX_SPAN_DAYS} days",
        )
    per_year = days_by_year(data.start_date, data.end_date)
    if not per_year:
        raise _err(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "The selected dates contain no working days (Sundays are not counted)",
        )

    overlap = db.scalar(
        select(LeaveRequest.id).where(
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.status.in_(("pending", "approved")),
            LeaveRequest.start_date <= data.end_date,
            LeaveRequest.end_date >= data.start_date,
        )
    )
    if overlap is not None:
        raise _err(
            status.HTTP_409_CONFLICT,
            "You already have a pending or approved leave request overlapping these dates",
        )

    # Friendly early check against already-APPROVED usage; approval re-checks under a lock.
    _ensure_within_limit(db, employee_id, leave_type, per_year, lock=False)

    request = LeaveRequest(
        employee_id=employee_id,
        leave_type_id=leave_type.id,
        start_date=data.start_date,
        end_date=data.end_date,
        reason=data.reason or None,
        status="pending",
    )
    db.add(request)
    db.commit()
    LEAVE_EVENTS.labels(event="created").inc()
    logger.info(
        f"leave requested id={request.id} employee_id={employee_id}",
        extra={"event": "leave_created"},
    )
    return request


# ---------------------------------------------------------------- decide
def _require_pending(request: LeaveRequest, action: str) -> None:
    if request.status != "pending":
        raise _err(
            status.HTTP_409_CONFLICT,
            f"Only pending requests can be {action}; this one is {request.status}",
        )


def _forbid_own_request(request: LeaveRequest, actor: CurrentUser, action: str) -> None:
    if actor.employee_id is not None and actor.employee_id == request.employee_id:
        raise _err(status.HTTP_403_FORBIDDEN, f"You cannot {action} your own leave request")


def approve(db: Session, request_id: int, actor: CurrentUser, note: str | None) -> LeaveRequest:
    request = get_request_or_404(db, request_id, lock=True)
    _require_pending(request, "approved")
    _forbid_own_request(request, actor, "approve")

    per_year = days_by_year(request.start_date, request.end_date)
    rows = _ensure_within_limit(db, request.employee_id, request.leave_type, per_year, lock=True)
    for year, days in per_year.items():
        row = rows[year]
        if row is None:
            row = LeaveBalance(
                employee_id=request.employee_id,
                leave_type_id=request.leave_type_id,
                year=year,
                days_used=ZERO,
            )
            db.add(row)
        row.days_used = row.days_used + days

    request.status = "approved"
    request.decided_by_user_id = actor.user_id
    request.decided_at = datetime.now(UTC)
    request.decision_note = note or None
    db.commit()
    LEAVE_EVENTS.labels(event="approved").inc()
    logger.info(
        f"leave approved id={request.id} by user_id={actor.user_id}",
        extra={"event": "leave_approved"},
    )
    return request


def reject(db: Session, request_id: int, actor: CurrentUser, reason: str) -> LeaveRequest:
    request = get_request_or_404(db, request_id, lock=True)
    _require_pending(request, "rejected")
    _forbid_own_request(request, actor, "reject")
    request.status = "rejected"
    request.decided_by_user_id = actor.user_id
    request.decided_at = datetime.now(UTC)
    request.decision_note = reason
    db.commit()
    LEAVE_EVENTS.labels(event="rejected").inc()
    logger.info(
        f"leave rejected id={request.id} by user_id={actor.user_id}",
        extra={"event": "leave_rejected"},
    )
    return request


def cancel(db: Session, request_id: int, actor: CurrentUser) -> LeaveRequest:
    request = get_request_or_404(db, request_id, lock=True)
    if actor.employee_id != request.employee_id:
        raise _err(status.HTTP_403_FORBIDDEN, "You can only cancel your own leave requests")
    _require_pending(request, "cancelled")
    request.status = "cancelled"
    db.commit()
    LEAVE_EVENTS.labels(event="cancelled").inc()
    logger.info(f"leave cancelled id={request.id}", extra={"event": "leave_cancelled"})
    return request


# ---------------------------------------------------------------- queries
def list_requests(
    db: Session,
    *,
    employee_id: int | None = None,
    status_filter: str | None = None,
    leave_type_id: int | None = None,
    month: str | None = None,
    oldest_first: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[LeaveRequest]:
    stmt = select(LeaveRequest).options(selectinload(LeaveRequest.leave_type))
    if employee_id is not None:
        stmt = stmt.where(LeaveRequest.employee_id == employee_id)
    if status_filter is not None:
        stmt = stmt.where(LeaveRequest.status == status_filter)
    if leave_type_id is not None:
        stmt = stmt.where(LeaveRequest.leave_type_id == leave_type_id)
    if month is not None:
        first, last = month_bounds(month)
        stmt = stmt.where(LeaveRequest.start_date <= last, LeaveRequest.end_date >= first)
    order = (LeaveRequest.created_at, LeaveRequest.id)
    stmt = stmt.order_by(*(c.asc() if oldest_first else c.desc() for c in order))
    return list(db.scalars(stmt.limit(limit).offset(offset)))


def balances(db: Session, employee_id: int, year: int) -> list[BalanceItem]:
    leave_types = list(db.scalars(select(LeaveType).order_by(LeaveType.name)))
    used = {
        b.leave_type_id: b.days_used
        for b in db.scalars(
            select(LeaveBalance).where(
                LeaveBalance.employee_id == employee_id, LeaveBalance.year == year
            )
        )
    }
    year_start, year_end = date(year, 1, 1), date(year, 12, 31)
    pending: dict[int, Decimal] = {}
    for r in db.scalars(
        select(LeaveRequest).where(
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.status == "pending",
            LeaveRequest.start_date <= year_end,
            LeaveRequest.end_date >= year_start,
        )
    ):
        pending[r.leave_type_id] = pending.get(r.leave_type_id, ZERO) + count_leave_days(
            r.start_date, r.end_date, year_start, year_end
        )

    items = []
    for lt in leave_types:
        days_used = used.get(lt.id, ZERO)
        limit = lt.max_days_per_year
        items.append(
            BalanceItem(
                leave_type_id=lt.id,
                leave_type_name=lt.name,
                is_paid=lt.is_paid,
                max_days_per_year=limit,
                days_used=days_used,
                days_pending=pending.get(lt.id, ZERO),
                remaining=(limit - days_used) if limit is not None else None,
            )
        )
    return items


def approved_summary(db: Session, month: str) -> list[dict]:
    """Per employee: approved leave days inside `month`, split into paid / unpaid.

    This is what payroll-service calls; unpaid days become loss-of-pay.
    """
    first, last = month_bounds(month)
    totals: dict[int, dict[str, Decimal]] = {}
    rows = db.scalars(
        select(LeaveRequest)
        .options(selectinload(LeaveRequest.leave_type))
        .where(
            LeaveRequest.status == "approved",
            LeaveRequest.start_date <= last,
            LeaveRequest.end_date >= first,
        )
    )
    for r in rows:
        days = count_leave_days(r.start_date, r.end_date, first, last)
        bucket = totals.setdefault(r.employee_id, {"paid_days": ZERO, "unpaid_days": ZERO})
        bucket["paid_days" if r.leave_type.is_paid else "unpaid_days"] += days
    return [{"employee_id": eid, **vals} for eid, vals in sorted(totals.items())]
