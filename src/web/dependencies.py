"""Application-scoped dependencies."""
from fastapi import Depends, Request
from src.services.auth_service import AuthService
from src.services.user_service import UserService
from src.services.token_service import TokenService


def get_db(request: Request):
    return request.app.state.db


def get_limiter(request: Request):
    return request.app.state.limiter


def get_auth_service(db=Depends(get_db)):
    return AuthService(db)


def get_user_service(db=Depends(get_db)):
    return UserService(db)


def get_token_service(db=Depends(get_db)):
    return TokenService(db)
