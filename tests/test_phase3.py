import asyncio
import sqlite3
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import jwt
import pytest

from src.app import app
from src.bot import TeleLoginBot
from src.config import settings
from src.database.sqlite import SQLiteDatabase
from src.utils.crypto import verify_token
from src.web.security import RateLimiter
from test_security import linked


@pytest.fixture
async def client(db, monkeypatch):
    monkeypatch.setattr(app.state, 'db', db, raising=False)
    monkeypatch.setattr(app.state, 'limiter', RateLimiter(), raising=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        yield client


async def issue(db, username='alice', telegram_id=42):
    login, code, _ = await db.start_request(username, 'ip', 'ua')
    assert await db.approve(login, telegram_id, code) == {'status': 'authenticated'}
    original = await db.get_login_request(login)
    results = await asyncio.gather(db.take_login_status(login), db.take_login_status(login))
    delivered = [r for r in results if 'session_token' in r]
    assert len(delivered) == 1
    assert delivered[0]['session_token'] == original['session_token']
    assert delivered[0]['refresh_token'] == original['refresh_token']
    assert 'verification_code' not in delivered[0]
    return delivered[0]


def headers(token):
    return {'Authorization': 'Bearer ' + token}


async def test_sessions_refresh_reuse_and_logout(db, client):
    await linked(db)
    tokens = await issue(db)
    access = headers(tokens['session_token'])
    assert (await client.get('/auth/me', headers=access)).status_code == 200
    rotated = await client.post('/auth/refresh', json={'refresh_token': tokens['refresh_token']})
    assert rotated.status_code == 200
    assert rotated.json()['refresh_token'] != tokens['refresh_token']
    assert (await client.post('/auth/refresh', json={'refresh_token': tokens['refresh_token']})).status_code == 401
    assert (await client.get('/auth/me', headers=access)).status_code == 401
    assert (await client.post('/auth/refresh', json={'refresh_token': rotated.json()['refresh_token']})).status_code == 401
    for endpoint in ('/auth/logout', '/auth/logout-all'):
        first, second = await issue(db), await issue(db)
        assert (await client.post(endpoint, headers=headers(first['session_token']))).json() == {'status': 'logged_out'}
        retry = await client.post(endpoint, headers=headers(first['session_token']))
        assert retry.status_code == (401 if endpoint.endswith('-all') else 200)
        if endpoint == '/auth/logout':
            assert retry.json() == {'status': 'logged_out'}
        assert (await client.get('/auth/me', headers=headers(first['session_token']))).status_code == 401
        assert (await client.get('/auth/me', headers=headers(second['session_token']))).status_code == (401 if endpoint.endswith('-all') else 200)


async def test_invalid_access_and_expired_refresh(db, client):
    await linked(db)
    tokens = await issue(db)
    payload = verify_token(tokens['session_token'])
    variants = [({}, 'other-key-' * 4), ({'exp': 1}, settings.SECRET_KEY), ({'type': 'refresh'}, settings.SECRET_KEY), ({'sid': None}, settings.SECRET_KEY)]
    for patch, key in variants:
        token = jwt.encode({**payload, **patch}, key, algorithm=settings.ALGORITHM)
        response = await client.get('/auth/me', headers=headers(token))
        assert response.status_code == 401 and response.headers['www-authenticate'] == 'Bearer'
    with sqlite3.connect(db.db_path) as conn:
        conn.execute('UPDATE sessions SET expires_at=0')
    assert (await client.get('/auth/me', headers=headers(tokens['session_token']))).status_code == 401
    assert (await client.post('/auth/refresh', json={'refresh_token': tokens['refresh_token']})).status_code == 401


async def test_refresh_concurrent(db):
    await linked(db)
    tokens = await issue(db)
    result = await asyncio.gather(db.refresh(tokens['refresh_token']), db.refresh(tokens['refresh_token']))
    assert sum(r is not None for r in result) == 1
    assert await db.session(verify_token(tokens['session_token'])) is None


async def test_number_matching_and_internal(db, client, monkeypatch):
    await linked(db)
    await db.create_user('unlinked')
    notification = AsyncMock()
    monkeypatch.setattr('src.services.auth_service.AuthService.send_login_notification', notification)
    internal = {'X-Internal-Key': settings.INTERNAL_API_KEY}
    for username in ('alice', 'missing', 'unlinked'):
        response = await client.post('/auth/start-login', json={'username': username}, headers={'user-agent': 'x' * 300})
        data = response.json()
        assert set(data) == {'login_id', 'status', 'verification_code'}
        assert 10 <= data['verification_code'] <= 99
        row = await db.get_login_request(data['login_id'])
        assert row['ip'] is None if username != 'alice' else len(row['user_agent']) == 200
    notification.assert_awaited_once()
    args = notification.call_args.args
    assert args[0] == 42 and 10 <= args[3] <= 99
    assert args[4].endswith('+00:00') and args[5] and len(args[6]) == 200
    data = (await client.post('/auth/start-login', json={'username': 'alice'})).json()
    body = {'login_id': data['login_id'], 'telegram_id': 42}
    assert (await client.post('/auth/confirm-login', json=body, headers=internal)).status_code == 422
    response = await client.post('/auth/confirm-login', json={**body, 'verification_code': 10 if data['verification_code'] != 10 else 11}, headers=internal)
    assert response.status_code == 400 and response.json()['detail'] == 'Wrong verification code'
    assert (await db.get_login_request(data['login_id']))['status'] == 'denied'
    assert (await client.post('/auth/confirm-login', json={**body, 'verification_code': data['verification_code']}, headers=internal)).status_code == 400
    login, _, _ = await db.start_request('alice', 'ip', 'ua')
    assert (await client.post('/auth/deny-login', json={**body, 'login_id': login}, headers=internal)).json() == {'status': 'denied'}
    for path in ('account', 'sessions', 'sessions/revoke', 'account/delete'):
        assert (await client.post('/internal/' + path, json={'telegram_id': 42})).status_code == 401


async def test_account_delete_and_ownership(db, client):
    await linked(db)
    await linked(db, 'bob', 43)
    tokens = await issue(db)
    other = await issue(db, 'bob', 43)
    sid = verify_token(other['session_token'])['sid']
    assert await db.account_action(42, 'revoke', sid) is None
    assert await db.session(verify_token(other['session_token']))
    for _ in range(6):
        await db.start_request('alice', 'ip', 'ua')
    account = await db.account_action(42, 'account')
    assert len(account['recent_logins']) == 5 and account['active_sessions'] == 1
    assert len((await db.account_action(42, 'sessions'))['sessions']) == 1
    await db.account_action(42, 'delete')
    assert await db.session(verify_token(tokens['session_token'])) is None
    with sqlite3.connect(db.db_path) as conn:
        for table in ('users', 'sessions', 'registration_tokens', 'login_requests'):
            assert conn.execute(f'SELECT COUNT(*) FROM {table} WHERE ' + ('id=1' if table == 'users' else 'user_id=1')).fetchone()[0] == 0
    assert (await client.post('/register', json={'username': 'alice'})).status_code == 200


async def test_deletion_race(db):
    await linked(db)
    await asyncio.gather(*(db.start_request('alice', 'ip', 'ua') for _ in range(10)), db.account_action(42, 'delete'))
    with sqlite3.connect(db.db_path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM login_requests WHERE user_id != 0 OR ip IS NOT NULL OR user_agent IS NOT NULL').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 0


async def test_retention(db):
    await linked(db)
    old, recent, closed = await issue(db), await issue(db), await issue(db)
    old_sid = verify_token(old['session_token'])['sid']
    closed_sid = verify_token(closed['session_token'])['sid']
    with sqlite3.connect(db.db_path) as conn:
        conn.execute('UPDATE sessions SET created_at=? WHERE id=?', (time.time()-200, old_sid))
        conn.execute('UPDATE sessions SET revoked_at=? WHERE id=?', (time.time()-200, closed_sid))
        conn.execute("UPDATE login_requests SET created_at='2000-01-01' WHERE rowid=(SELECT MIN(rowid) FROM login_requests)")
    await db.purge_old(100)
    assert await db.session(verify_token(old['session_token']))
    rows = (await db.account_action(42, 'sessions'))['sessions']
    assert next(r for r in rows if r['id'] == old_sid)['ip'] is None
    assert next(r for r in rows if r['id'] == verify_token(recent['session_token'])['sid'])['ip'] == 'ip'
    with sqlite3.connect(db.db_path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 2
        assert conn.execute('SELECT COUNT(*) FROM login_requests').fetchone()[0] == 2


async def test_periodic_retention(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'DB_URL', 'sqlite:///' + str(tmp_path / 'periodic.db'))
    monkeypatch.setattr(settings, 'PURGE_INTERVAL_SECONDS', .01)
    purge = AsyncMock(side_effect=[None, RuntimeError('transient'), None, None, None, None])
    monkeypatch.setattr(SQLiteDatabase, 'purge_old', purge)
    async with app.router.lifespan_context(app):
        await asyncio.sleep(.035)
        assert purge.call_count >= 3
    calls = purge.call_count
    await asyncio.sleep(.02)
    assert purge.call_count == calls


async def test_bot_codes_and_malformed_callbacks():
    bot = TeleLoginBot.__new__(TeleLoginBot)
    bot.app = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
    login = '00000000-0000-0000-0000-000000000001'
    await bot.send_login_notification(42, login, 'alice', 42, 'now', 'ip', 'x'*200)
    args = bot.app.bot.send_message.call_args.kwargs
    buttons = [b for row in args['reply_markup'].inline_keyboard for b in row]
    codes = [int(b.text) for b in buttons[:3]]
    assert len(set(codes)) == 3 and codes.count(42) == 1
    assert all(len(b.callback_data.encode()) <= 64 for b in buttons)
    assert 'parse_mode' not in args and 'x'*101 not in args['text']
    query = SimpleNamespace(answer=AsyncMock(), edit_message_text=AsyncMock())
    update = SimpleNamespace(callback_query=query)
    for data in (None, '', 'unknown', 'revoke_session:no', 'unlink_confirm:extra', f'login_confirm:{login}', f'login_confirm:{login}:9', f'login_confirm:{login}:100'):
        query.data = data
        await bot.button_callback(update, None)
        query.edit_message_text.assert_called_with('Invalid request')


async def test_refresh_rate_is_only_per_ip(client, db, monkeypatch):
    monkeypatch.setattr(settings, 'RATE_LIMIT_USERNAME', 1)
    monkeypatch.setattr(settings, 'RATE_LIMIT_IP', 2)
    for _ in range(2):
        assert (await client.post('/auth/refresh', json={'refresh_token': 'invalid'})).status_code == 401
    assert (await client.post('/auth/refresh', json={'refresh_token': 'invalid'})).status_code == 429
    assert (await client.get('/auth/me')).status_code == 401


async def test_expired_session_retention_and_deleted_refresh(db):
    await linked(db)
    old, current = await issue(db), await issue(db)
    sid = verify_token(old['session_token'])['sid']
    with sqlite3.connect(db.db_path) as conn:
        conn.execute('UPDATE sessions SET expires_at=? WHERE id=?', (time.time()-200, sid))
    await db.purge_old(100)
    with sqlite3.connect(db.db_path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM sessions WHERE id=?', (sid,)).fetchone()[0] == 0
    await db.account_action(42, 'delete')
    assert await db.refresh(current['refresh_token']) is None
