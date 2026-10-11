import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.passwords import MAX_PASSWORD_BYTES, MIN_PASSWORD_LENGTH

Role = Literal["admin", "manager", "employee"]
_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,50}$")


def _check_username(value: str) -> str:
    value = value.strip()
    if not _USERNAME_RE.fullmatch(value):
        raise ValueError("Username must be 3-50 characters: letters, digits, '.', '_' or '-'")
    return value


def _check_new_password(value: str) -> str:
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(value.encode()) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes")
    return value


Username = Annotated[str, AfterValidator(_check_username)]
NewPassword = Annotated[str, AfterValidator(_check_new_password)]


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class UserCreate(BaseModel):
    username: Username
    password: NewPassword
    role: Role
    employee_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _employee_needs_link(self):
        if self.role == "employee" and self.employee_id is None:
            raise ValueError("employee_id is required for the 'employee' role")
        return self


class UserUpdate(BaseModel):
    role: Role | None = None
    is_active: bool | None = None
    employee_id: int | None = Field(default=None, gt=0)  # send null to unlink

    @model_validator(mode="after")
    def _at_least_one_field(self):
        sent = self.model_fields_set
        if not sent:
            raise ValueError("Provide at least one field to update")
        if "role" in sent and self.role is None:
            raise ValueError("role cannot be null")
        if "is_active" in sent and self.is_active is None:
            raise ValueError("is_active cannot be null")
        return self


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: NewPassword


class PasswordReset(BaseModel):
    new_password: NewPassword


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: Role
    employee_id: int | None
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime
