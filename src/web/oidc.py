"""Confidential-client OpenID Connect authorization code provider."""
import base64
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import re
import secrets
import tempfile
import time
from urllib.parse import parse_qsl, unquote_plus, urlencode, urlsplit, urlunsplit

import aiosqlite
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
import jwt

from src.config import settings
from src.web.dependencies import get_db
from src.web.sso import return_url

router = APIRouter()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode()


def load_key(filename):
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        fd, temporary = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
        finally:
            os.unlink(temporary)
    if path.stat().st_mode & 0o077:
        logging.getLogger(__name__).warning('OIDC signing key %s is readable or accessible by group/others; use mode 0600', path)
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
        raise ValueError('OIDC key must be RSA with at least 2048 bits')
    numbers = key.public_key().public_numbers()
    jwk = {'e': b64(numbers.e.to_bytes((numbers.e.bit_length()+7)//8, 'big')), 'kty': 'RSA', 'n': b64(numbers.n.to_bytes((numbers.n.bit_length()+7)//8, 'big'))}
    kid = b64(hashlib.sha256(json.dumps(jwk, sort_keys=True, separators=(',', ':')).encode()).digest())
    return key, dict(jwk, kid=kid, use='sig', alg='RS256')


@router.get('/.well-known/openid-configuration')
async def discovery():
    return dict(issuer=settings.PUBLIC_URL, **{name: settings.PUBLIC_URL + path for name, path in {
        'authorization_endpoint': '/authorize', 'token_endpoint': '/token', 'userinfo_endpoint': '/userinfo', 'jwks_uri': '/jwks.json'}.items()},
        response_types_supported=['code'], grant_types_supported=['authorization_code'], subject_types_supported=['public'],
        id_token_signing_alg_values_supported=['RS256'], scopes_supported=['openid', 'profile'],
        token_endpoint_auth_methods_supported=['client_secret_basic', 'client_secret_post'], code_challenge_methods_supported=['S256'],
        claims_supported=['sub', 'iss', 'aud', 'exp', 'iat', 'auth_time', 'nonce', 'preferred_username', 'name'],
        authorization_response_iss_parameter_supported=True)


@router.get('/jwks.json')
async def jwks(request: Request):
    return {'keys': [request.app.state.oidc_key[1]]}


def redirect(uri, values):
    parts = urlsplit(uri)
    return RedirectResponse(urlunsplit(parts._replace(query=urlencode(parse_qsl(parts.query, keep_blank_values=True) + list(values.items())))), 302)


@router.get('/authorize')
async def authorize(request: Request, db=Depends(get_db)):
    q = request.query_params
    if any(len(q.getlist(name)) > 1 for name in ('client_id', 'redirect_uri')):
        return HTMLResponse('Repeated client_id or redirect URI', 400)
    app = await db.get_app(q.get('client_id'))
    uri = q.get('redirect_uri')
    if not app or not app['secret_hash'] or not uri or uri not in json.loads(app['redirect_uris']):
        return HTMLResponse('Invalid client or redirect URI', 400)
    values = {'iss': settings.PUBLIC_URL}
    if 'state' in q:
        values['state'] = q['state']

    def error(code, description):
        return redirect(uri, dict(values, error=code, error_description=description))

    if any(len(q.getlist(name)) > 1 for name in q):
        return error('invalid_request', 'Repeated authorization parameter')
    if q.get('response_type') != 'code':
        return error('unsupported_response_type', 'Only code is supported')
    scopes = q.get('scope', '').split()
    if 'openid' not in scopes:
        return error('invalid_scope', 'openid scope required')
    challenge = q.get('code_challenge')
    if (q.get('code_challenge_method') not in (None, 'S256') or
            (challenge is not None and (q.get('code_challenge_method') != 'S256' or not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', challenge))) or
            ('code_challenge_method' in q and challenge is None)):
        return error('invalid_request', 'Invalid PKCE challenge')
    if 'request' in q or 'request_uri' in q:
        return error('request_not_supported', 'Request objects are unsupported')
    prompts = q.get('prompt', '').split()
    session = await db.browser_session(request.cookies.get(settings.SSO_COOKIE_NAME))
    if not session or 'login' in prompts:
        if 'none' in prompts:
            return error('login_required', 'Browser login required')
        continuation = settings.PUBLIC_URL + '/authorize?' + urlencode([(k, v) for k, v in q.multi_items() if not (k == 'prompt' and 'login' in prompts)])
        if return_url(continuation, app) is None:
            return error('invalid_request', 'authorization request too long or invalid')
        params = dict(app=app['id'], rd=continuation)
        if 'login' in prompts:
            params['force'] = '1'
        return RedirectResponse(settings.PUBLIC_URL + '/login?' + urlencode(params), 302)
    if not await db.allowed(app, session):
        return error('access_denied', 'User is not allowed')
    code = secrets.token_urlsafe(32)
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute('BEGIN IMMEDIATE')
        active = await (await conn.execute("SELECT 1 FROM sessions WHERE id=? AND kind='sso' AND revoked_at IS NULL AND expires_at>?", (session['id'], time.time()))).fetchone()
        if not active or not await allowed(conn, app['id'], session['user_id']):
            return error('access_denied', 'Browser session or app access revoked')
        await conn.execute('INSERT INTO oidc_codes VALUES (?,?,?,?,?,?,?,?,?,?,NULL)',
                           (digest(code), app['id'], session['user_id'], session['id'], uri, ' '.join(s for s in ('openid', 'profile') if s in scopes), q.get('nonce'), challenge, session['created_at'], time.time()+settings.OIDC_CODE_TTL_SECONDS))
        await conn.commit()
    return redirect(uri, dict(values, code=code))


def oauth_error(code, description, basic=False):
    headers = {'Cache-Control': 'no-store', 'Pragma': 'no-cache'}
    if basic:
        headers['WWW-Authenticate'] = 'Basic'
    return JSONResponse({'error': code, 'error_description': description}, 401 if code == 'invalid_client' else 400, headers=headers)


async def form(request):
    if request.headers.get('content-type', '').split(';')[0].lower() != 'application/x-www-form-urlencoded':
        return {}
    try:
        pairs = parse_qsl((await request.body()).decode(), keep_blank_values=True)
        if len(dict(pairs)) != len(pairs):
            return {}
        return dict(pairs)
    except UnicodeError:
        return {}


async def allowed(conn, app_id, user_id):
    return await (await conn.execute("SELECT u.* FROM users u JOIN apps a ON a.id=? WHERE u.id=? AND u.telegram_id IS NOT NULL AND (a.access_policy='all' OR EXISTS (SELECT 1 FROM app_users WHERE app_id=a.id AND user_id=u.id))", (app_id, user_id))).fetchone()


@router.post('/token')
async def token(request: Request, db=Depends(get_db)):
    body = await form(request)
    authorization = request.headers.get('authorization')
    basic = authorization is not None
    client_id, secret = body.get('client_id'), body.get('client_secret')
    if basic:
        try:
            scheme, encoded = authorization.split(' ', 1)
            if scheme.lower() != 'basic' or 'client_secret' in body:
                raise ValueError()
            client_id, secret = (unquote_plus(v) for v in base64.b64decode(encoded, validate=True).decode().split(':', 1))
            if 'client_id' in body and body['client_id'] != client_id:
                raise ValueError()
        except (ValueError, UnicodeError):
            return oauth_error('invalid_client', 'Invalid client authentication', True)
    app = await db.get_app(client_id)
    if not app or not app['secret_hash'] or not secret or not hmac.compare_digest(digest(secret), app['secret_hash']):
        return oauth_error('invalid_client', 'Invalid client authentication', basic)
    if body.get('grant_type') != 'authorization_code':
        return oauth_error('unsupported_grant_type', 'Only authorization_code is supported')
    code_hash = digest(body.get('code', ''))
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute('BEGIN IMMEDIATE')
        row = await (await conn.execute('SELECT * FROM oidc_codes WHERE code_hash=?', (code_hash,))).fetchone()
        now = time.time()
        if not row or row['used_at'] is not None:
            await conn.execute('UPDATE oidc_tokens SET revoked_at=? WHERE code_hash=?', (now, code_hash))
            await conn.commit()
            return oauth_error('invalid_grant', 'Unknown or used code')
        verifier = body.get('code_verifier')
        valid_pkce = (verifier is None if row['code_challenge'] is None else
                      bool(verifier and re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', verifier) and hmac.compare_digest(b64(hashlib.sha256(verifier.encode()).digest()), row['code_challenge'])))
        user = await allowed(conn, app['id'], row['user_id'])
        session = await (await conn.execute("SELECT 1 FROM sessions WHERE id=? AND user_id=? AND kind='sso' AND revoked_at IS NULL AND expires_at>?", (row['session_id'], row['user_id'], now))).fetchone()
        if row['app_id'] != app['id'] or row['redirect_uri'] != body.get('redirect_uri') or row['expires_at'] <= now or not valid_pkce or not user or not session:
            return oauth_error('invalid_grant', 'Invalid authorization grant')
        access = secrets.token_urlsafe(32)
        claims = dict(iss=settings.PUBLIC_URL, sub=user['public_id'], aud=app['id'], iat=int(now), exp=int(now)+settings.OIDC_TOKEN_TTL_SECONDS, auth_time=int(row['auth_time']))
        if row['nonce'] is not None:
            claims['nonce'] = row['nonce']
        if 'profile' in row['scope'].split():
            claims.update(preferred_username=user['username'], name=user['username'])
        key, jwk = request.app.state.oidc_key
        id_token = jwt.encode(claims, key, algorithm='RS256', headers={'kid': jwk['kid']})
        await conn.execute('UPDATE oidc_codes SET used_at=? WHERE code_hash=?', (now, code_hash))
        await conn.execute('INSERT INTO oidc_tokens VALUES (?,?,?,?,?,?,NULL)', (digest(access), app['id'], user['id'], code_hash, row['scope'], now+settings.OIDC_TOKEN_TTL_SECONDS))
        await conn.commit()
    return JSONResponse(dict(access_token=access, token_type='Bearer', expires_in=settings.OIDC_TOKEN_TTL_SECONDS, scope=row['scope'], id_token=id_token), headers={'Cache-Control': 'no-store', 'Pragma': 'no-cache'})


@router.get('/userinfo', operation_id='oidc_userinfo_get')
async def userinfo_get(request: Request, db=Depends(get_db)):
    return await userinfo(request, db)


@router.post('/userinfo', operation_id='oidc_userinfo_post')
async def userinfo_post(request: Request, db=Depends(get_db)):
    return await userinfo(request, db)


async def userinfo(request: Request, db):
    header = request.headers.get('authorization', '').split()
    if len(header) == 2 and header[0].lower() == 'bearer':
        async with aiosqlite.connect(db.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            row = await (await conn.execute('SELECT * FROM oidc_tokens WHERE token_hash=? AND revoked_at IS NULL AND expires_at>?', (digest(header[1]), time.time()))).fetchone()
            user = await allowed(conn, row['app_id'], row['user_id']) if row else None
            if user:
                result = {'sub': user['public_id']}
                if 'profile' in row['scope'].split():
                    result.update(preferred_username=user['username'], name=user['username'])
                return JSONResponse(result, headers={'Cache-Control': 'no-store'})
    return JSONResponse({'error': 'invalid_token'}, 401, headers={'WWW-Authenticate': 'Bearer error="invalid_token"', 'Cache-Control': 'no-store'})
