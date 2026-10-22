"""
API routes definition
FastAPI router with all endpoints
"""
from src.utils.crypto import verify_token
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from src.web.dependencies import (
    get_db, get_limiter, get_auth_service, get_user_service, get_token_service,
)
from src.web.schemas import (
    LinkTelegramRequest,
    LinkTelegramResponse,
    LoginConfirmRequest, LoginDenyRequest, RefreshRequest, AccountRequest, RevokeRequest,
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
    result = await auth_service.start_login(request.username, background_tasks, http_request.client.host if http_request.client else "unknown", http_request.headers.get("user-agent", ""))

    return LoginStartResponse(**result)

@router.post("/auth/confirm-login", response_model=LoginConfirmResponse, dependencies=[Depends(require_internal_key)])
async def confirm_login(request: LoginConfirmRequest, auth_service=Depends(get_auth_service)):
    """
    Confirm login request (called by bot)
    """
    result = await auth_service.confirm_login(request.login_id, request.telegram_id, request.verification_code)

    if result == "wrong":
        raise HTTPException(400, "Wrong verification code")
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
async def deny_login(request: LoginDenyRequest, db=Depends(get_db)):
    if not await db.update_login_status(request.login_id, "denied", telegram_id=request.telegram_id):
        raise HTTPException(400, "Request already handled, expired or invalid")
    return {"status": "denied"}


@router.post("/auth/status", response_model=LoginStatusResponse, response_model_exclude_none=True)
async def post_login_status(request: LoginStatusRequest, auth_service=Depends(get_auth_service)):
    return await get_login_status(request.login_id, auth_service)




def bearer(request):
    scheme, _, token = request.headers.get('authorization', '').partition(' ')
    payload = verify_token(token) if scheme.lower() == 'bearer' else None
    if not payload or payload.get('type') != 'access' or not payload.get('sid') or not all(k in payload for k in ('exp','iat','jti','user_id','sub')):
        raise unauthorized()
    if not isinstance(payload['sid'], str) or type(payload['user_id']) is not int:
        raise unauthorized()
    return payload


def unauthorized():
    return HTTPException(401, 'Invalid token', headers={'WWW-Authenticate':'Bearer'})


@router.get('/auth/me')
async def me(request: Request, db=Depends(get_db)):
    result = await db.session(bearer(request))
    if result is None:
        raise unauthorized()
    return result


@router.post('/auth/refresh')
async def refresh(body: RefreshRequest, request: Request, db=Depends(get_db), limiter=Depends(get_limiter)):
    limiter.check('refresh', None, request.client.host if request.client else 'unknown')
    result = await db.refresh(body.refresh_token)
    if result is None:
        raise unauthorized()
    return result


@router.post('/auth/logout')
@router.post('/auth/logout-all')
async def logout(request: Request, db=Depends(get_db)):
    result = await db.session(bearer(request), allow_revoked=not request.url.path.endswith('logout-all'), revoke='all' if request.url.path.endswith('logout-all') else 'one')
    if result is None:
        raise unauthorized()
    return {'status':'logged_out'}


@router.post('/internal/account', dependencies=[Depends(require_internal_key)])
async def account(body: AccountRequest, db=Depends(get_db)):
    return await internal_action(db, body.telegram_id, 'account')


@router.post('/internal/sessions', dependencies=[Depends(require_internal_key)])
async def sessions(body: AccountRequest, db=Depends(get_db)):
    return await internal_action(db, body.telegram_id, 'sessions')


@router.post('/internal/sessions/revoke', dependencies=[Depends(require_internal_key)])
async def revoke(body: RevokeRequest, db=Depends(get_db)):
    return await internal_action(db, body.telegram_id, 'revoke', body.session_id)


@router.post('/internal/account/delete', dependencies=[Depends(require_internal_key)])
async def delete(body: AccountRequest, db=Depends(get_db)):
    return await internal_action(db, body.telegram_id, 'delete')


async def internal_action(db, telegram_id, action, session_id=None):
    result = await db.account_action(telegram_id, action, session_id)
    if result is None:
        raise HTTPException(404, 'Account or session not found')
    return result
