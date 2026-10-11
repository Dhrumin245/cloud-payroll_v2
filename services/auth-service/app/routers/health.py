"""Operational endpoints used by Docker, Kubernetes probes and monitoring.

/health  liveness  - "is the process up?"  (never touches dependencies)
/ready   readiness - "can it serve traffic?" (runs registered checks, e.g. DB ping)
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["ops"])


@router.get("/health")
def health(request: Request):
    return {"status": "ok", "service": request.app.state.service_name}


@router.get("/ready")
def ready(request: Request):
    failures: dict[str, str] = {}
    for name, check in request.app.state.readiness_checks.items():
        try:
            check()
        except Exception as exc:  # noqa: BLE001 - any failure means "not ready"
            failures[name] = str(exc)
    if failures:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "failures": failures},
        )
    return {"status": "ready", "service": request.app.state.service_name}
