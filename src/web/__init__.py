"""Web module"""
from src.web.routes import router
from src.web.schemas import (
    RegisterRequest,
    RegisterResponse,
    LoginStartRequest,
    LoginStartResponse,
    LoginConfirmRequest,
    LoginConfirmResponse,
    LoginStatusResponse
)

__all__ = [
    "router",
    "RegisterRequest",
    "RegisterResponse",
    "LoginStartRequest",
    "LoginStartResponse",
    "LoginConfirmRequest",
    "LoginConfirmResponse",
    "LoginStatusResponse"
]
