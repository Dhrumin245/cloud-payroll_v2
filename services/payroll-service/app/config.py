"""Environment-based configuration. No defaults for secrets: bad config stops startup."""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "payroll-service"
    environment: str = "development"
    log_level: str = "INFO"

    # --- security (required, no default) ---
    jwt_secret: str
    jwt_algorithm: str = "HS256"

    # --- persistence (required) ---
    database_url: str

    # --- other services (Kubernetes/compose DNS names) ---
    auth_service_url: str = "http://auth-service:8000"
    employee_service_url: str = "http://employee-service:8000"
    leave_service_url: str = "http://leave-service:8000"
    payroll_service_url: str = "http://payroll-service:8000"
    # payroll reads many rows from other services, so allow a bit longer than leave-service does
    downstream_timeout_seconds: float = Field(10.0, gt=0, le=60)

    # --- printed on payslips ---
    company_name: str = "Your Company Name"
    company_address: str = ""

    @field_validator("jwt_secret")
    @classmethod
    def _secret_long_enough(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters long")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
