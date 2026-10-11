"""Access rules that depend on WHICH employee is being accessed."""

from fastapi import Depends, HTTPException, status

from app.security import CurrentUser, require_any_role


def _forbidden() -> HTTPException:
    return HTTPException(
        status.HTTP_403_FORBIDDEN, "You do not have permission to access this employee"
    )


def staff_or_self(employee_id: int, user: CurrentUser = Depends(require_any_role)) -> CurrentUser:
    """Admin / manager, or the employee looking at their own record."""
    if user.is_manager_or_above or user.employee_id == employee_id:
        return user
    raise _forbidden()


def admin_or_self(employee_id: int, user: CurrentUser = Depends(require_any_role)) -> CurrentUser:
    """Admin, or the employee looking at their own (sensitive) data. Managers are excluded."""
    if user.is_admin or user.employee_id == employee_id:
        return user
    raise _forbidden()
