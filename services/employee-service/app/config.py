"""Environment-based configuration. No defaults for secrets: bad config stops startup."""

from functools import lru_cache

from cryptography.fernet import Fernet
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "employee-service"
    environment: str = "development"
    log_level: str = "INFO"

    # --- security (required, no default) ---
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    # Fernet key used to encrypt bank account numbers. Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Keep it separate from JWT_SECRET. Losing it makes stored account numbers unreadable.
    bank_encryption_key: str

    # --- persistence (required) ---
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

    @field_validator("bank_encryption_key")
    @classmethod
    def _valid_fernet_key(cls, value: str) -> str:
        try:
            Fernet(value.encode())
        except Exception as exc:
            raise ValueError("BANK_ENCRYPTION_KEY must be a valid Fernet key") from exc
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
