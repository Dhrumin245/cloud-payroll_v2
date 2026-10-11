"""Environment-based configuration.

There are deliberately NO defaults for secrets: if JWT_SECRET is missing or
too short the service refuses to start instead of running insecurely.
"""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "auth-service"
    environment: str = "development"
    log_level: str = "INFO"

    # --- security (required, no default) ---
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(60, ge=1, le=1440)
    bcrypt_rounds: int = Field(12, ge=4, le=15)  # 12 in production; tests use 4 for speed

    # --- login rate limit (per client IP, in-memory, per replica) ---
    login_rate_limit_per_minute: int = Field(5, ge=1)
    # Behind nginx / a k8s Ingress every request comes from the proxy's IP.
    # Set TRUST_FORWARDED_FOR=true there so the real client IP (X-Forwarded-For) is used.
    trust_forwarded_for: bool = False

    # --- persistence (required for auth-service) ---
    database_url: str

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
