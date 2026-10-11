"""HTTP clients for employee-service and leave-service. The caller's JWT is forwarded."""

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import httpx
from fastapi import HTTPException, status

from app.config import get_settings
from app.metrics import DOWNSTREAM_CALLS

logger = logging.getLogger("app.clients")


@dataclass(frozen=True)
class SalaryData:
    basic_pay: Decimal
    hra: Decimal
    conveyance_allowance: Decimal
    components: list[tuple[str, str, Decimal]] = field(default_factory=list)  # (type, name, amount)


@dataclass(frozen=True)
class EmployeeData:
    id: int
    employee_code: str
    full_name: str
    salary: SalaryData | None


@dataclass(frozen=True)
class LeaveDays:
    paid_days: Decimal
    unpaid_days: Decimal


class _ServiceClient:
    service = "downstream service"

    def __init__(
        self, base_url: str, timeout: float, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport

    def _unavailable(self) -> HTTPException:
        return HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"{self.service} is unavailable, please try again shortly",
        )

    def _get(self, path: str, token: str, params: dict | None = None) -> httpx.Response:
        try:
            with httpx.Client(
                base_url=self.base_url, timeout=self.timeout, transport=self.transport
            ) as client:
                response = client.get(
                    path, params=params, headers={"Authorization": f"Bearer {token}"}
                )
        except httpx.HTTPError as exc:
            DOWNSTREAM_CALLS.labels(target=self.service, outcome="error").inc()
            logger.error(f"{self.service} unreachable: {exc!r}", extra={"event": "dep_down"})
            raise self._unavailable() from None
        # 404 is a valid answer (e.g. "no bank details"); 5xx / 401 / 403 mean the call failed
        ok = response.status_code < 400 or response.status_code == 404
        DOWNSTREAM_CALLS.labels(target=self.service, outcome="ok" if ok else "error").inc()
        return response


class EmployeeClient(_ServiceClient):
    service = "employee-service"

    def payroll_data(self, as_of: date, token: str) -> list[EmployeeData]:
        """Active employees + the salary in effect on `as_of`, in one call."""
        response = self._get("/employees/payroll-data", token, {"as_of": as_of.isoformat()})
        if response.status_code != 200:
            logger.error(
                f"employee-service answered {response.status_code}", extra={"event": "dep_error"}
            )
            raise self._unavailable()
        result = []
        for row in response.json():
            salary = row.get("salary")
            result.append(
                EmployeeData(
                    id=row["id"],
                    employee_code=row["employee_code"],
                    full_name=row["full_name"],
                    salary=None
                    if salary is None
                    else SalaryData(
                        basic_pay=Decimal(salary["basic_pay"]),
                        hra=Decimal(salary["hra"]),
                        conveyance_allowance=Decimal(salary["conveyance_allowance"]),
                        components=[
                            (c["component_type"], c["name"], Decimal(c["amount"]))
                            for c in salary["components"]
                        ],
                    ),
                )
            )
        return result

    def reveal_bank(self, employee_id: int, token: str) -> dict | None:
        """Full bank details for a payout file (employee-service audit-logs it). None if absent."""
        response = self._get(f"/employees/{employee_id}/bank-details/reveal", token)
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            logger.error(
                f"employee-service answered {response.status_code}", extra={"event": "dep_error"}
            )
            raise self._unavailable()
        return response.json()


class LeaveClient(_ServiceClient):
    service = "leave-service"

    def approved(self, month: str, token: str) -> dict[int, LeaveDays]:
        """Approved leave days inside `month`, per employee, split paid / unpaid."""
        response = self._get("/leaves/approved", token, {"month": month})
        if response.status_code != 200:
            logger.error(
                f"leave-service answered {response.status_code}", extra={"event": "dep_error"}
            )
            raise self._unavailable()
        return {
            row["employee_id"]: LeaveDays(Decimal(row["paid_days"]), Decimal(row["unpaid_days"]))
            for row in response.json()["employees"]
        }


def get_employee_client() -> EmployeeClient:
    s = get_settings()
    return EmployeeClient(s.employee_service_url, s.downstream_timeout_seconds)


def get_leave_client() -> LeaveClient:
    s = get_settings()
    return LeaveClient(s.leave_service_url, s.downstream_timeout_seconds)
