"""
Pydantic schemas for API validation
"""
from pydantic import BaseModel, Field

# Registration schemas
class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)

class RegisterResponse(BaseModel):
    link: str

# Login schemas
class LoginStartRequest(BaseModel):
    username: str

class LoginStartResponse(BaseModel):
    login_id: str
    status: str

class LinkTelegramRequest(BaseModel):
    token: str
    telegram_id: int

class LinkTelegramResponse(BaseModel):
    success: bool
    message: str

class LoginConfirmRequest(BaseModel):
    login_id: str
    telegram_id: int

class LoginConfirmResponse(BaseModel):
    status: str
    session_token: str

class LoginStatusResponse(BaseModel):
    status: str
    session_token: str = None  # Optional, only present when status is 'approved'
