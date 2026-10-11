"""Environment-based configuration.

There are deliberately NO defaults for secrets: if JWT_SECRET is missing or
too short the service refuses to start instead of running insecurely.
"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "template"
    environment: str = "development"
    log_level: str = "INFO"

    # --- security (required, no default) ---
    jwt_secret: str
    jwt_algorithm: str = "HS256"

    # --- persistence (set per service from Phase 2 onward) ---
    database_url: str | None = None

    # --- other services (Kubernetes/compose DNS names) ---
    auth_service_url: str = "http://auth-service:8000"
    employee_service_url: str = "http://employee-service:8000"
    leave_service_url: str = "http://leave-service:8000"
    payroll_service_url: str = "http://payroll-service:8000"

    @field_validator("jwt_secret")
    @classmethod
    def _secret_long_enough(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters long")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
