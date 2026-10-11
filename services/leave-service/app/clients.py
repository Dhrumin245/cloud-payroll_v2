"""HTTP client for employee-service. The caller's JWT is forwarded (no service accounts)."""

import logging
from dataclasses import dataclass

import httpx
from fastapi import HTTPException, status

from app.config import get_settings
from app.metrics import DOWNSTREAM_CALLS

logger = logging.getLogger("app.clients")


@dataclass(frozen=True)
class EmployeeStatus:
    exists: bool
    is_active: bool


class EmployeeClient:
    def __init__(
        self, base_url: str, timeout: float, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport

    def check(self, employee_id: int, token: str) -> EmployeeStatus:
        """Ask employee-service whether an employee exists / is active. 503 if it can't answer."""
        try:
            with httpx.Client(
                base_url=self.base_url, timeout=self.timeout, transport=self.transport
            ) as client:
                response = client.get(
                    f"/employees/{employee_id}/exists",
                    headers={"Authorization": f"Bearer {token}"},
                )
        except httpx.HTTPError as exc:
            DOWNSTREAM_CALLS.labels(target="employee-service", outcome="error").inc()
            logger.error(f"employee-service unreachable: {exc!r}", extra={"event": "dep_down"})
            raise self._unavailable() from None
        if response.status_code != 200:
            DOWNSTREAM_CALLS.labels(target="employee-service", outcome="error").inc()
            logger.error(
                f"employee-service answered {response.status_code}", extra={"event": "dep_error"}
            )
            raise self._unavailable()
        DOWNSTREAM_CALLS.labels(target="employee-service", outcome="ok").inc()
        body = response.json()
        return EmployeeStatus(exists=bool(body["exists"]), is_active=bool(body["is_active"]))

    @staticmethod
    def _unavailable() -> HTTPException:
        return HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "employee-service is unavailable, please try again shortly",
        )


def get_employee_client() -> EmployeeClient:
    settings = get_settings()
    return EmployeeClient(settings.employee_service_url, settings.employee_service_timeout_seconds)
