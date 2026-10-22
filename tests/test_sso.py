import asyncio
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import time
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
import pytest
from pydantic import ValidationError

from src.app import app
from src.config import Settings, settings
from src.database.sqlite import SQLiteDatabase
from src.web.security import RateLimiter
from src.web.sso import return_url
from test_phase3 import issue, headers
from test_security import linked

INTERNAL = {'X-Internal-Key': settings.INTERNAL_API_KEY}


@pytest.fixture
async def client(db, monkeypatch):
    monkeypatch.setattr(settings, 'PUBLIC_URL', 'http://test/telelogin')
    monkeypatch.setattr(settings, 'SSO_COOKIE_SECURE', False)
    monkeypatch.setattr(settings, 'SSO_COOKIE_DOMAIN', '')
    monkeypatch.setattr(app.state, 'db', db, raising=False)
    monkeypatch.setattr(app.state, 'limiter', RateLimiter(), raising=False)
    monkeypatch.setattr(app.state, 'login_html', Path('src/web/templates/index.html').read_text(), raising=False)
    monkeypatch.setattr('src.services.auth_service.AuthService.send_login_notification', AsyncMock())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        yield client


def add_app(db, name='demo', policy='allowlist', origins=None):
    with sqlite3.connect(db.db_path) as conn:
        conn.execute('INSERT INTO apps(id,name,access_policy,origins,created_at) VALUES (?,?,?,?,?)', (name, 'Demo <app>', policy, json.dumps(origins or []), time.time()))


def allow(db, user, app_id='demo'):
    with sqlite3.connect(db.db_path) as conn:
        conn.execute('INSERT INTO app_users VALUES (?,?)', (app_id, user.id))


async def start(client, username='alice', **extra):
    response = await client.post('/sso/start', json={'username': username, 'app': 'demo', **extra})
    assert response.status_code == 200, response.text
    return response.json()


async def approve(client, data, telegram_id=42):
    response = await client.post('/auth/confirm-login', json={'login_id': data['login_id'], 'telegram_id': telegram_id, 'verification_code': data['verification_code']}, headers=INTERNAL)
    assert response.status_code == 200, response.text


async def complete(client, data):
    return await client.post('/sso/complete', json={'login_id': data['login_id']})


async def test_approval_delivery_purpose_and_cookie(db, client, monkeypatch):
    await linked(db)
    add_app(db, policy='all')
    monkeypatch.setattr(settings, 'SSO_COOKIE_SECURE', True)
    monkeypatch.setattr(settings, 'SSO_COOKIE_DOMAIN', 'test.example.com')
    data = await start(client, rd='/demo')
    assert (await complete(client, data)).json() == {'status': 'pending'}
    await approve(client, data)
    row = await db.get_login_request(data['login_id'])
    secret = row['session_token']
    assert row['refresh_token'] is None
    with sqlite3.connect(db.db_path) as conn:
        assert conn.execute('SELECT kind, refresh_hash FROM sessions').fetchone() == ('sso', hashlib.sha256(secret.encode()).hexdigest())
    assert (await client.post('/auth/status', json={'login_id': data['login_id']})).json() == {'status': 'approved'}
    response = await complete(client, data)
    assert response.json() == {'status': 'approved', 'redirect': 'http://test/demo'}
    cookie = response.headers['set-cookie']
    assert cookie.startswith('tl_sso=')
    for attr in ('Domain=test.example.com', 'HttpOnly', 'Max-Age=2592000', 'Path=/', 'SameSite=lax', 'Secure'):
        assert attr in cookie
    assert 'set-cookie' not in (await complete(client, data)).headers
    assert (await db.get_login_request(data['login_id']))['session_token'] is None
    assert (await client.post('/auth/refresh', json={'refresh_token': secret})).status_code == 401
    api, code, _ = await db.start_request('alice', 'ip', 'ua')
    assert (await complete(client, {'login_id': api})).status_code == 404
    await db.approve(api, 42, code)
    assert 'session_token' in (await db.take_login_status(api))


@pytest.mark.parametrize('revoke', ['bot', 'api', 'delete'])
async def test_revoke_before_collection(db, client, revoke):
    await linked(db)
    token = await issue(db)
    data = await start(client)
    await approve(client, data)
    if revoke == 'api':
        assert (await client.post('/auth/logout-all', headers=headers(token['session_token']))).status_code == 200
    else:
        path = '/internal/sessions/revoke' if revoke == 'bot' else '/internal/account/delete'
        assert (await client.post(path, json={'telegram_id': 42}, headers=INTERNAL)).status_code == 200
    response = await complete(client, data)
    assert response.status_code == (404 if revoke == 'delete' else 200)
    if revoke != 'delete':
        assert response.json() == {'status': 'denied'}
        # A retry and the login history must keep reporting denied, not approved
        retry = await complete(client, data)
        assert retry.json() == {'status': 'denied'} and 'set-cookie' not in retry.headers
        assert (await db.get_login_request(data['login_id']))['status'] == 'denied'
    assert 'set-cookie' not in response.headers


@pytest.mark.parametrize('username', ['用户甲', 'has spaces', '100%', 'control\r\n\x01'])
async def test_unicode_header_and_verify_matrix(db, client, username):
    user = await linked(db, username)
    add_app(db)
    allow(db, user)
    data = await start(client, username)
    await approve(client, data)
    await complete(client, data)
    response = await client.get('/sso/verify', headers={'X-TeleLogin-App': 'demo'})
    assert response.status_code == 200
    assert unquote(response.headers['X-TeleLogin-User']) == username
    assert response.headers['X-TeleLogin-User-Id'] == user.public_id
    assert response.text == '' and response.headers['cache-control'] == 'no-store'
    assert (await client.get('/sso/verify?app=demo')).status_code == 200
    for path, hdr in [('/sso/verify', {}), ('/sso/verify?app=missing', {}), ('/sso/verify?app=other', {'X-TeleLogin-App': 'demo'})]:
        assert (await client.get(path, headers=hdr)).status_code == 403
    with sqlite3.connect(db.db_path) as conn:
        before = conn.execute('SELECT last_used_at FROM sessions').fetchone()[0]
    await client.get('/sso/verify?app=demo')
    with sqlite3.connect(db.db_path) as conn:
        assert conn.execute('SELECT last_used_at FROM sessions').fetchone()[0] == before
        conn.execute('DELETE FROM app_users')
    assert (await client.get('/sso/verify?app=demo')).status_code == 403
    with sqlite3.connect(db.db_path) as conn:
        conn.execute("UPDATE apps SET access_policy='all'")
    assert (await client.get('/sso/verify?app=demo')).status_code == 200
    with sqlite3.connect(db.db_path) as conn:
        conn.execute('UPDATE users SET telegram_id=NULL')
    assert (await client.get('/sso/verify?app=demo')).status_code == 403
    with sqlite3.connect(db.db_path) as conn:
        conn.execute('UPDATE sessions SET expires_at=0')
    assert (await client.get('/sso/verify?app=demo')).status_code == 401


async def test_verify_redirects_and_revocation(db, client):
    await linked(db)
    add_app(db, origins=['https://app.example.com'], policy='all')
    original = 'https://app.example.com/x?a=1&b=%E7%94%A8%E6%88%B7'
    response = await client.get('/sso/verify?app=demo', headers={'X-Original-URL': original})
    assert response.status_code == 401
    target = response.headers['x-telelogin-login']
    assert parse_qs(urlsplit(target).query)['app'] == ['demo']
    assert parse_qs(urlsplit(target).query)['rd'] == [original]
    response = await client.get('/sso/verify?app=demo&redirect=1', headers={'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': 'app.example.com', 'X-Forwarded-Uri': '/x?a=1&b=2'})
    assert response.status_code == 302
    assert parse_qs(urlsplit(response.headers['location']).query)['rd'] == ['https://app.example.com/x?a=1&b=2']
    response = await client.get('/sso/verify?app=demo', headers={'X-Original-URL': 'https://evil.test'})
    assert 'rd' not in parse_qs(urlsplit(response.headers['x-telelogin-login']).query)
    data = await start(client)
    await approve(client, data)
    await complete(client, data)
    sessions = (await db.account_action(42, 'sessions'))['sessions']
    assert sessions[0]['kind'] == 'sso'
    assert (await client.post('/internal/sessions/revoke', json={'telegram_id': 42, 'session_id': sessions[0]['id']}, headers=INTERNAL)).status_code == 200
    assert (await client.get('/sso/verify?app=demo')).status_code == 401


@pytest.mark.parametrize('target', ['//evil', '/\\evil', 'https://evil', 'https://test.evil', 'javascript:x', 'http://test@evil', '/%5cevil', '/%2fevil', '/%252fevil', 'http://test/\r\nx', 'https://sibling.example.com'])
def test_redirect_rejections(target, monkeypatch):
    monkeypatch.setattr(settings, 'PUBLIC_URL', 'http://test/telelogin')
    assert return_url(target) is None


def test_redirect_context(monkeypatch):
    monkeypatch.setattr(settings, 'PUBLIC_URL', 'http://test/telelogin')
    app_x = {'origins': '["https://app.example.com"]'}
    assert return_url('/local', app_x) == 'http://test/local'
    assert return_url('https://app.example.com/x?q=用户&a=2', app_x)
    assert return_url('https://app.example.com', {'origins': '[]'}) is None
    assert return_url('http://test:80/path')
    assert return_url('http://test:81/path') is None
    assert return_url('/' + 'x' * 2048) is None


async def test_csrf_logout_pages_and_dummy(db, client):
    await linked(db)
    add_app(db, policy='all')
    for endpoint in ('start', 'complete', 'logout'):
        assert (await client.post('/sso/' + endpoint, json={}, headers={'Origin': 'https://evil.test'})).status_code == 403
        assert (await client.post('/sso/' + endpoint, content='{}')).status_code == 403
    for username in ('missing', 'unlinked'):
        if username == 'unlinked':
            await db.create_user(username)
        data = await start(client, username)
        assert set(data) == {'status', 'verification_code', 'login_id'}
        assert (await db.get_login_request(data['login_id']))['user_id'] == 0
    data = await start(client, rd='/app')
    await approve(client, data)
    await complete(client, data)
    response = await client.get('/login?app=demo&rd=/app')
    assert response.status_code == 302 and response.headers['location'] == 'http://test/app'
    assert (await client.get('/login?app=demo&rd=/app&force=1')).status_code == 200
    assert 'Sign in to Demo &lt;app&gt;' in (await client.get('/login?app=demo')).text
    assert 'Signed in as alice' in (await client.get('/')).text
    assert 'Confirm logout' in (await client.get('/logout?app=demo&rd=/app')).text
    assert (await client.get('/sso/verify?app=demo')).status_code == 200
    response = await client.post('/sso/logout', data={'app': 'demo', 'rd': '/app'}, headers={'Origin': 'http://test'})
    assert response.status_code == 303 and response.headers['location'] == 'http://test/app'
    assert 'Max-Age=0' in response.headers['set-cookie']
    assert (await client.get('/sso/verify?app=demo')).status_code == 401
    assert 'Sign in' in (await client.get('/')).text
    assert (await client.post('/sso/logout', json={})).headers['location'] == 'http://test/telelogin/login'


async def test_wrong_code_expiry_and_delete_cascade(db, client):
    user = await linked(db)
    add_app(db)
    allow(db, user)
    data = await start(client)
    assert (await client.post('/auth/confirm-login', json={'login_id': data['login_id'], 'telegram_id': 42, 'verification_code': 10 if data['verification_code'] != 10 else 11}, headers=INTERNAL)).status_code == 400
    assert (await complete(client, data)).json()['status'] == 'denied'
    data = await start(client)
    with sqlite3.connect(db.db_path) as conn:
        conn.execute('UPDATE login_requests SET expires_at=0')
    assert (await complete(client, data)).json()['status'] == 'expired'
    await db.account_action(42, 'delete')
    with sqlite3.connect(db.db_path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM app_users').fetchone()[0] == 0


@pytest.mark.parametrize('domain', ['127.0.0.1', 'localhost', '.example.com', 'other.com', 'co.uk', 'github.io'])
def test_invalid_cookie_domain(domain):
    host = 'auth.' + domain if domain in ('co.uk', 'github.io') else 'auth.example.com'
    with pytest.raises(ValidationError):
        Settings(PUBLIC_URL='https://' + host, SSO_COOKIE_DOMAIN=domain, _env_file=None)


def test_offline_psl_and_public_url(monkeypatch):
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('Network used'))
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: pytest.fail('Network used'))
    value = Settings(PUBLIC_URL='https://auth.example.co.uk/prefix/', SSO_COOKIE_DOMAIN='example.co.uk', _env_file=None)
    assert value.PUBLIC_URL == 'https://auth.example.co.uk/prefix'
    for url in ('ftp://host', 'https://host/?q=1', 'https://host/#x', 'https://user@host'):
        with pytest.raises(ValidationError):
            Settings(PUBLIC_URL=url, _env_file=None)


async def test_closed_registration(db, client, monkeypatch):
    monkeypatch.setattr(settings, 'REGISTRATION_MODE', 'closed')
    assert (await client.post('/register', json={'username': 'alice'})).status_code == 403


async def test_baseline_migration(tmp_path, client, monkeypatch):
    path = tmp_path / 'old.db'
    with sqlite3.connect(path) as conn:
        conn.executescript('''
        CREATE TABLE users(id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, telegram_id INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, linked_at DATETIME);
        CREATE TABLE login_requests(id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, status TEXT DEFAULT 'pending', session_token TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, expires_at REAL,token_delivered_at REAL,ip TEXT,user_agent TEXT,verification_code INTEGER,refresh_token TEXT);
        CREATE TABLE sessions(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,refresh_hash TEXT UNIQUE NOT NULL,previous_refresh_hash TEXT,created_at REAL NOT NULL,expires_at REAL NOT NULL,last_used_at REAL,revoked_at REAL,ip TEXT,user_agent TEXT);
        INSERT INTO users(username,telegram_id) VALUES ('alice',42),('bob',43);
        INSERT INTO sessions(id,user_id,refresh_hash,created_at,expires_at) VALUES ('old',1,'hash',1,9999999999);
        ''')
    db = SQLiteDatabase(str(path))
    await db.init_db()
    await db.init_db()
    monkeypatch.setattr(app.state, 'db', db)
    assert (await client.post('/register', json={'username': 'alice'})).status_code == 400
    a = await db.get_user_by_username('alice')
    assert a.public_id and a == await db.get_user_by_telegram_id(42)
    assert a.public_id != (await db.get_user_by_username('bob')).public_id
    with pytest.raises(sqlite3.IntegrityError):
        await db.create_user('alice')
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT kind FROM sessions').fetchone()[0] == 'api'


async def test_concurrent_cookie_delivery(db, client):
    await linked(db)
    data = await start(client)
    await approve(client, data)
    responses = await asyncio.gather(complete(client, data), complete(client, data))
    assert sum('set-cookie' in response.headers for response in responses) == 1
    assert all(response.json()['status'] == 'approved' for response in responses)


async def test_shared_login_rate_limit(db, client, monkeypatch):
    monkeypatch.setattr(settings, 'RATE_LIMIT_USERNAME', 1)
    assert (await client.post('/auth/start-login', json={'username': 'missing'})).status_code == 200
    assert (await client.post('/sso/start', json={'username': 'missing'})).status_code == 429


async def test_throttle_invalid_cookie_and_notification(db, client, monkeypatch):
    await linked(db)
    add_app(db, policy='all')
    notify = AsyncMock()
    monkeypatch.setattr('src.services.auth_service.AuthService.send_login_notification', notify)
    data = await start(client)
    assert notify.call_args.args[-1] == 'Demo <app>'
    await approve(client, data)
    await complete(client, data)
    await client.get('/sso/verify?app=demo')
    with sqlite3.connect(db.db_path) as conn:
        conn.execute('UPDATE sessions SET last_used_at=?', (time.time() - 301,))
    await client.get('/sso/verify?app=demo')
    with sqlite3.connect(db.db_path) as conn:
        assert conn.execute('SELECT last_used_at FROM sessions').fetchone()[0] > time.time() - 2
    client.cookies.clear()
    client.cookies.set(settings.SSO_COOKIE_NAME, 'invalid')
    assert (await client.get('/sso/verify?app=demo')).status_code == 401
    response = await client.options('/sso/start', headers={'Origin': 'http://test', 'Access-Control-Request-Method': 'POST'})
    assert 'access-control-allow-origin' not in response.headers


@pytest.mark.parametrize('app_id,logged', [(None, True), ('', False), ('unknown-app', True), ('bad\r\nvalue', False), ('x' * 10000, False), ('BAD', False)])
async def test_verify_warning_log_is_bounded(app_id, logged, caplog):
    from types import SimpleNamespace
    from starlette.requests import Request
    from src.web.sso import verify
    request = Request({'type': 'http', 'method': 'GET', 'path': '/sso/verify', 'query_string': b'',
                       'headers': [] if app_id is None else [(b'x-telelogin-app', app_id.encode())]})
    db = SimpleNamespace(get_app=AsyncMock(return_value=None), browser_session=AsyncMock(return_value=None))
    with caplog.at_level('WARNING', logger='src.web.sso'):
        response = await verify(request, db)
    assert response.status_code == 401
    records = [r for r in caplog.records if r.name == 'src.web.sso']
    assert len(records) == int(logged)
    if logged:
        assert records[0].getMessage() == 'Missing or unknown forward-auth app: ' + repr(app_id)[:80]
