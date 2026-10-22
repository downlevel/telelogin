"""
API routes definition
FastAPI router with all endpoints
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from src.web.dependencies import (
    get_db, get_limiter, get_auth_service, get_user_service, get_token_service,
)
from src.web.schemas import (
    LinkTelegramRequest,
    LinkTelegramResponse,
    LoginConfirmRequest,
    LoginConfirmResponse,
    LoginStartRequest,
    LoginStartResponse,
    LoginStatusResponse,
    LoginStatusRequest,
    RegisterRequest,
    RegisterResponse,
)
from src.web.security import require_internal_key

router = APIRouter()
@router.post("/register", response_model=RegisterResponse)
async def register(request: RegisterRequest, http_request: Request, limiter=Depends(get_limiter), user_service=Depends(get_user_service), token_service=Depends(get_token_service)):
    """
    Register a new user and get Telegram link
    """
    limiter.check("register", request.username, http_request.client.host if http_request.client else "unknown")
    # Create user
    user = await user_service.create_user(request.username)

    if not user:
        raise HTTPException(status_code=400, detail="Username already exists")

    # Generate registration token
    token = await token_service.generate_registration_token(user.id)

    # Create Telegram link
    link = token_service.create_telegram_link(token)

    return RegisterResponse(link=link)

@router.post("/auth/link-telegram", response_model=LinkTelegramResponse, dependencies=[Depends(require_internal_key)])
async def link_telegram(request: LinkTelegramRequest, db=Depends(get_db)):
    """
    Link Telegram account to user (called by bot after /start with token)
    """
    try:
        await db.consume_and_link(request.token, request.telegram_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None

    return LinkTelegramResponse(
        success=True,
        message="Telegram account linked successfully"
    )

@router.post("/auth/start-login", response_model=LoginStartResponse)
async def start_login(request: LoginStartRequest, http_request: Request, background_tasks: BackgroundTasks, limiter=Depends(get_limiter), auth_service=Depends(get_auth_service)):
    """
    Start the login process
    """
    limiter.check("login", request.username, http_request.client.host if http_request.client else "unknown")
    result = await auth_service.start_login(request.username, background_tasks)

    return LoginStartResponse(**result)

@router.post("/auth/confirm-login", response_model=LoginConfirmResponse, dependencies=[Depends(require_internal_key)])
async def confirm_login(request: LoginConfirmRequest, auth_service=Depends(get_auth_service)):
    """
    Confirm login request (called by bot)
    """
    result = await auth_service.confirm_login(request.login_id, request.telegram_id)

    if not result:
        raise HTTPException(status_code=400, detail="Invalid login request")

    return LoginConfirmResponse(**result)

@router.get("/status/{login_id}", response_model=LoginStatusResponse, response_model_exclude_none=True, deprecated=True)
async def get_login_status(login_id: str, auth_service=Depends(get_auth_service)):
    """
    Get login request status
    """
    result = await auth_service.get_login_status(login_id)

    if not result:
        raise HTTPException(status_code=404, detail="Login request not found")

    return LoginStatusResponse(**result)


@router.post("/auth/deny-login", dependencies=[Depends(require_internal_key)])
async def deny_login(request: LoginConfirmRequest, db=Depends(get_db)):
    if not await db.update_login_status(request.login_id, "denied", telegram_id=request.telegram_id):
        raise HTTPException(400, "Request already handled, expired or invalid")
    return {"status": "denied"}


@router.post("/auth/status", response_model=LoginStatusResponse, response_model_exclude_none=True)
async def post_login_status(request: LoginStatusRequest, auth_service=Depends(get_auth_service)):
    return await get_login_status(request.login_id, auth_service)
