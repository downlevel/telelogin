"""
API routes definition
FastAPI router with all endpoints
"""
from fastapi import APIRouter, HTTPException, Depends
from src.web.schemas import (
    RegisterRequest,
    RegisterResponse,
    LoginStartRequest,
    LoginStartResponse,
    LinkTelegramRequest,
    LinkTelegramResponse,
    LoginConfirmRequest,
    LoginConfirmResponse,
    LoginStatusResponse
)
from src.services.auth_service import AuthService
from src.services.user_service import UserService
from src.services.token_service import TokenService
from src.database.sqlite import SQLiteDatabase

router = APIRouter()

# Initialize services (in production, use dependency injection)
db = SQLiteDatabase()
auth_service = AuthService(db)
user_service = UserService(db)
token_service = TokenService()

@router.post("/register", response_model=RegisterResponse)
async def register(request: RegisterRequest):
    """
    Register a new user and get Telegram link
    """
    # Create user
    user = await user_service.create_user(request.username)
    
    if not user:
        raise HTTPException(status_code=400, detail="Username already exists")
    
    # Generate registration token
    token = token_service.generate_registration_token(user.id)
    
    # Create Telegram link
    link = token_service.create_telegram_link(token)
    
    return RegisterResponse(link=link)

@router.post("/auth/link-telegram", response_model=LinkTelegramResponse)
async def link_telegram(request: LinkTelegramRequest):
    """
    Link Telegram account to user (called by bot after /start with token)
    """
    # Verify registration token
    user_id = token_service.verify_registration_token(request.token)
    
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    
    # Link telegram_id to user
    success = await user_service.link_telegram(user_id, request.telegram_id)
    
    if not success:
        raise HTTPException(status_code=400, detail="Failed to link Telegram account")
    
    return LinkTelegramResponse(
        success=True,
        message="Telegram account linked successfully"
    )

@router.post("/auth/start-login", response_model=LoginStartResponse)
async def start_login(request: LoginStartRequest):
    """
    Start the login process
    """
    result = await auth_service.start_login(request.username)
    
    if not result:
        raise HTTPException(status_code=404, detail="User not found or Telegram not linked")
    
    return LoginStartResponse(**result)

@router.post("/auth/confirm-login", response_model=LoginConfirmResponse)
async def confirm_login(request: LoginConfirmRequest):
    """
    Confirm login request (called by bot)
    """
    result = await auth_service.confirm_login(request.login_id, request.telegram_id)
    
    if not result:
        raise HTTPException(status_code=400, detail="Invalid login request")
    
    return LoginConfirmResponse(**result)

@router.get("/status/{login_id}", response_model=LoginStatusResponse)
async def get_login_status(login_id: str):
    """
    Get login request status
    """
    result = await auth_service.get_login_status(login_id)
    
    if not result:
        raise HTTPException(status_code=404, detail="Login request not found")
    
    return LoginStatusResponse(**result)
