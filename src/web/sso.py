"""Hosted browser login and forward authentication."""
import html
import json
import logging
import re
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from src.config import settings
from src.services.auth_service import AuthService
from src.web.dependencies import get_db, get_limiter
from src.web.schemas import LoginStartRequest, LoginStatusRequest

router = APIRouter()
logger = logging.getLogger(__name__)


def origin(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Invalid origin')
    port = parsed.port
    host = parsed.hostname.lower()
    if ':' in host:
        host = '[' + host + ']'
    return f'{parsed.scheme.lower()}://{host}' + (f':{port}' if port and port != (443 if parsed.scheme == 'https' else 80) else '')


def return_url(value, app=None):
    """Return an approved absolute target, or None. Reject ambiguous encodings."""
    if not isinstance(value, str) or not value or len(value) > 2048 or '\\' in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        return None
    # Reject encoded controls, backslashes and network-path references too, while
    # permitting ordinary encoded path/query values such as ?next=a%2Fb.
    decoded = value
    for _ in range(len(value)):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
        if "\\" in decoded or decoded.startswith('//') or any(ord(c) < 32 or ord(c) == 127 for c in decoded):
            return None
    if value.startswith('/') and not value.startswith('//'):
        return origin(settings.PUBLIC_URL) + value
    try:
        allowed = [origin(settings.PUBLIC_URL)] + (json.loads(app['origins']) if app else [])
        if origin(value) in allowed:
            return value
    except (ValueError, TypeError):
        pass
    return None


def csrf(request, form=False):
    content_type = request.headers.get('content-type', '').split(';')[0].lower()
    if content_type not in (('application/json', 'application/x-www-form-urlencoded') if form else ('application/json',)):
        raise HTTPException(403, 'Content-Type must be application/json' + (' or form' if form else ''))
    if 'origin' in request.headers and request.headers['origin'] != origin(settings.PUBLIC_URL):
        raise HTTPException(403, 'Invalid Origin')


def cookie(response, value='', clear=False):
    response.set_cookie(settings.SSO_COOKIE_NAME, value, max_age=0 if clear else settings.REFRESH_TOKEN_TTL_DAYS * 86400,
                        httponly=True, secure=settings.SSO_COOKIE_SECURE, samesite='lax', path='/', domain=settings.SSO_COOKIE_DOMAIN or None)


@router.get('/login')
async def login(request: Request, db=Depends(get_db)):
    app = await db.get_app(request.query_params.get('app'))
    rd = return_url(request.query_params.get('rd'), app)
    session = await db.browser_session(request.cookies.get(settings.SSO_COOKIE_NAME))
    if session and rd and request.query_params.get('force') != '1':
        return RedirectResponse(rd, 302)
    title = 'Sign in to ' + app['name'] if app else 'Secure authentication via Telegram'
    page = request.app.state.login_html.replace('Secure authentication via Telegram', html.escape(title))
    return HTMLResponse(page)


@router.get('/')
async def home(request: Request, db=Depends(get_db)):
    session = await db.browser_session(request.cookies.get(settings.SSO_COOKIE_NAME))
    base = html.escape(settings.PUBLIC_URL, quote=True)
    body = (f'Signed in as {html.escape(session["username"])} <form action="{base}/logout"><button>Log out</button></form>' if session else f'<a href="{base}/login">Sign in</a>')
    return HTMLResponse('<!doctype html><html lang="en"><title>TeleLogin</title><body>' + body + '</body></html>')


@router.post('/sso/start')
async def start(request: Request, background_tasks: BackgroundTasks, db=Depends(get_db), limiter=Depends(get_limiter)):
    csrf(request)
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError('Expected object')
    except ValueError:
        raise HTTPException(422, 'Invalid JSON object') from None
    try:
        username = LoginStartRequest(**body).username
    except (ValueError, TypeError):
        raise HTTPException(422, 'Invalid username') from None
    ip = request.client.host if request.client else 'unknown'
    limiter.check('login', username, ip)
    app = await db.get_app(body.get('app'))
    rd = return_url(body.get('rd'), app) or settings.PUBLIC_URL + '/'
    login_id, code, user = await db.start_request(username, ip, request.headers.get('user-agent', ''), 'sso', app['id'] if app else None, rd)
    if user:
        import datetime
        background_tasks.add_task(AuthService(db).send_login_notification, user['telegram_id'], login_id, username, code,
                                  datetime.datetime.now(datetime.timezone.utc).isoformat(), ip, request.headers.get('user-agent', '')[:200], app['name'] if app else None)
    return {'login_id': login_id, 'status': 'pending', 'verification_code': code}


@router.post('/sso/complete')
async def complete(request: Request, db=Depends(get_db)):
    csrf(request)
    try:
        body = LoginStatusRequest(**await request.json())
    except (ValueError, TypeError):
        raise HTTPException(422, 'Invalid login_id') from None
    result = await db.complete_browser_login(body.login_id)
    if result is None:
        raise HTTPException(404, 'Login request not found')
    secret = result.pop('secret', None)
    response = JSONResponse(result)
    if secret:
        cookie(response, secret)
    return response


@router.get('/logout')
async def logout_page(request: Request, db=Depends(get_db)):
    app_id = request.query_params.get('app', '')
    app = await db.get_app(app_id)
    rd = return_url(request.query_params.get('rd'), app) or settings.PUBLIC_URL + '/login'
    return HTMLResponse(f'<!doctype html><html lang="en"><title>Log out</title><body><form method="post" action="{html.escape(settings.PUBLIC_URL)}/sso/logout"><input type="hidden" name="app" value="{html.escape(app_id, quote=True)}"><input type="hidden" name="rd" value="{html.escape(rd, quote=True)}"><button>Confirm logout</button></form></body></html>')


@router.post('/sso/logout')
async def logout(request: Request, db=Depends(get_db)):
    csrf(request, form=True)
    try:
        if request.headers.get('content-type', '').split(';')[0].lower() == 'application/json':
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError('Expected object')
        else:
            # URL-encoded forms need no multipart parser dependency.
            fields = parse_qs((await request.body()).decode('utf-8'), keep_blank_values=True)
            body = {key: values[-1] for key, values in fields.items()}
    except (ValueError, UnicodeError):
        raise HTTPException(422, 'Invalid logout body') from None
    app = await db.get_app(body.get('app'))
    rd = return_url(body.get('rd'), app) or settings.PUBLIC_URL + '/login'
    await db.browser_session(request.cookies.get(settings.SSO_COOKIE_NAME), revoke=True)
    response = RedirectResponse(rd, 303)
    cookie(response, clear=True)
    return response


@router.get('/sso/verify')
async def verify(request: Request, db=Depends(get_db)):
    headers = {'Cache-Control': 'no-store'}
    header, query = request.headers.get('x-telelogin-app'), request.query_params.get('app')
    redirect = request.query_params.get('redirect') == '1'
    if header is not None and query is not None and header != query:
        return Response(status_code=403, headers=headers)
    app_id = header if header is not None else query
    app = await db.get_app(app_id)
    if not app and (app_id is None or re.fullmatch(r'[a-z0-9][a-z0-9-]{0,39}', app_id)):
        logger.warning('Missing or unknown forward-auth app: %s', repr(app_id)[:80])
    session = await db.browser_session(request.cookies.get(settings.SSO_COOKIE_NAME))
    if not session:
        original = request.headers.get('x-original-url')
        if original is None:
            original = request.headers.get('x-forwarded-proto', '') + '://' + request.headers.get('x-forwarded-host', '') + request.headers.get('x-forwarded-uri', '')
        params = {'app': app_id or ''}
        rd = return_url(original, app)
        if rd:
            params['rd'] = rd
        target = settings.PUBLIC_URL + '/login?' + urlencode(params)
        if redirect:
            return RedirectResponse(target, 302, headers=headers)
        headers['X-TeleLogin-Login'] = target
        return Response(status_code=401, headers=headers)
    if not await db.allowed(app, session):
        return HTMLResponse('Access denied' if redirect else '', 403, headers=headers)
    headers.update({'X-TeleLogin-User': quote(session['username'], safe=''), 'X-TeleLogin-User-Id': session['public_id']})
    return Response(status_code=200, headers=headers)
