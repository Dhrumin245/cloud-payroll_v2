import logging
import time
import uuid

from fastapi import FastAPI, Request
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import Settings, get_settings
from app.database import check_database
from app.logging_config import configure_logging
from app.routers import auth, health, users

logger = logging.getLogger("app.request")
QUIET_PATHS = {"/health", "/ready", "/metrics"}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.service_name, settings.log_level)

    app = FastAPI(title=f"{settings.service_name}", version="0.1.0")
    app.state.service_name = settings.service_name
    # name -> callable that raises if the dependency is unhealthy
    app.state.readiness_checks = {"database": check_database}

    @app.middleware("http")
    async def request_logging(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "unhandled error",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                },
            )
            raise
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        log = logger.debug if request.url.path in QUIET_PATHS else logger.info
        log(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(users.router)

    # Prometheus metrics at GET /metrics (scraped by Prometheus, hidden from Swagger)
    Instrumentator(excluded_handlers=["/metrics", "/health", "/ready"]).instrument(app).expose(
        app, include_in_schema=False
    )
    return app


app = create_app()
