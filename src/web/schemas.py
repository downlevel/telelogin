"""
Pydantic schemas for API validation
"""
from uuid import UUID
from pydantic import BaseModel, Field, field_validator

# Registration schemas
class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)

class RegisterResponse(BaseModel):
    link: str

# Login schemas
class LoginStartRequest(BaseModel):
    username: str

class LoginStartResponse(BaseModel):
    verification_code: int
    login_id: str
    status: str

class LinkTelegramRequest(BaseModel):
    token: str
    telegram_id: int

class LinkTelegramResponse(BaseModel):
    success: bool
    message: str

class LoginDenyRequest(BaseModel):
    login_id: str
    telegram_id: int

class LoginConfirmRequest(LoginDenyRequest):
    verification_code: int = Field(strict=True)

class LoginConfirmResponse(BaseModel):
    status: str

class LoginStatusResponse(BaseModel):
    refresh_token: str | None = None
    status: str
    session_token: str | None = None  # Optional, only present when status is 'approved'


class LoginStatusRequest(BaseModel):
    login_id: str


class RefreshRequest(BaseModel):
    refresh_token: str

class AccountRequest(BaseModel):
    telegram_id: int

class RevokeRequest(AccountRequest):
    session_id: str | None = None

    @field_validator('session_id')
    @classmethod
    def valid_session_id(cls, value):
        if value is not None:
            UUID(value)
        return value
