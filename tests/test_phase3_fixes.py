import asyncio
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiosqlite
import httpx
import pytest

from src.app import app
from src.bot import TeleLoginBot
from src.config import settings
from src.database.sqlite import SQLiteDatabase
from test_phase3 import client as _client, headers, issue
from test_security import linked


client = _client


def test_javascript_client():
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is not on PATH')
    result = subprocess.run(
        [node, 'tests/client_refresh.cjs'], cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


async def test_revoked_session_cannot_logout_all(db, client):
    await linked(db)
    first, other = await issue(db), await issue(db)
    access = headers(first['session_token'])
    assert (await client.post('/auth/logout', headers=access)).status_code == 200
    response = await client.post('/auth/logout-all', headers=access)
    assert response.status_code == 401
    assert response.headers['www-authenticate'] == 'Bearer'
    assert (await client.get('/auth/me', headers=headers(other['session_token']))).status_code == 200
    assert (await client.post('/auth/logout', headers=access)).json() == {'status': 'logged_out'}


@pytest.mark.parametrize('session_id', ['', 'not-a-uuid', 42])
async def test_invalid_session_id_cannot_revoke_all(db, client, session_id):
    await linked(db)
    tokens = await issue(db)
    response = await client.post('/internal/sessions/revoke', json={'telegram_id': 42, 'session_id': session_id}, headers={'X-Internal-Key': settings.INTERNAL_API_KEY})
    assert response.status_code == 422
    assert (await client.get('/auth/me', headers=headers(tokens['session_token']))).status_code == 200
    assert await db.account_action(42, 'revoke', '') is None
    assert (await client.get('/auth/me', headers=headers(tokens['session_token']))).status_code == 200


async def test_confirm_http_response_exact(db, client):
    await linked(db)
    login_id, code, _ = await db.start_request('alice', 'ip', 'ua')
    response = await client.post('/auth/confirm-login', json={'telegram_id': 42, 'login_id': login_id, 'verification_code': code}, headers={'X-Internal-Key': settings.INTERNAL_API_KEY})
    assert response.status_code == 200
    assert response.json() == {'status': 'authenticated'}
    delivered = (await client.post('/auth/status', json={'login_id': login_id})).json()
    assert set(delivered) == {'status', 'session_token', 'refresh_token'}


async def test_start_waits_for_deletion_transaction(db, monkeypatch):
    user = await linked(db)
    await issue(db)
    waiting = asyncio.Event()
    execute = aiosqlite.Connection.execute
    async with aiosqlite.connect(db.db_path) as owner:
        await owner.execute('BEGIN IMMEDIATE')

        async def observed_execute(connection, sql, *args, **kwargs):
            if connection is not owner and sql == 'BEGIN IMMEDIATE':
                waiting.set()
            return await execute(connection, sql, *args, **kwargs)

        monkeypatch.setattr(aiosqlite.Connection, 'execute', observed_execute)
        task = asyncio.create_task(db.start_request('alice', 'private-ip', 'private-ua'))
        try:
            await asyncio.wait_for(waiting.wait(), 2)
            await asyncio.sleep(.03)
            assert not task.done()
            for table in ('sessions', 'registration_tokens', 'login_requests'):
                await owner.execute(f'DELETE FROM {table} WHERE user_id=?', (user.id,))
            await owner.execute('DELETE FROM users WHERE id=?', (user.id,))
            await owner.commit()
            login_id, _, found = await asyncio.wait_for(task, 2)
            assert found is None
            row = await db.get_login_request(login_id)
            assert row['user_id'] == 0 and row['ip'] is None and row['user_agent'] is None
            with sqlite3.connect(db.db_path) as connection:
                assert connection.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 0
                assert connection.execute('SELECT COUNT(*) FROM login_requests WHERE user_id!=0 OR ip IS NOT NULL OR user_agent IS NOT NULL').fetchone()[0] == 0
        finally:
            await owner.rollback()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_startup_purge_failure_does_not_stop_periodic_task(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(settings, 'DB_URL', 'sqlite:///' + str(tmp_path / 'purge.db'))
    monkeypatch.setattr(settings, 'PURGE_INTERVAL_SECONDS', .01)
    periodic = asyncio.Event()
    calls = 0

    async def purge_once(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError('Startup purge failed')
        periodic.set()

    monkeypatch.setattr(SQLiteDatabase, 'purge_old', purge_once)
    state = app.state._state.copy()
    try:
        async with app.router.lifespan_context(app):
            await asyncio.wait_for(periodic.wait(), 2)
        assert calls >= 2
        assert 'Retention purge failed' in caplog.text
        after = calls
        await asyncio.sleep(.03)
        assert calls == after
    finally:
        app.state._state.clear()
        app.state._state.update(state)


async def test_purge_rolls_back_all_statements(db, monkeypatch):
    await linked(db)
    await issue(db)
    with sqlite3.connect(db.db_path) as connection:
        connection.execute("UPDATE login_requests SET created_at='2000-01-01'")
        connection.execute('UPDATE sessions SET expires_at=0')
    execute = aiosqlite.Connection.execute

    async def fail_metadata_update(connection, sql, *args, **kwargs):
        if sql.startswith('UPDATE sessions SET ip=NULL'):
            raise RuntimeError('Simulated purge failure')
        return await execute(connection, sql, *args, **kwargs)

    monkeypatch.setattr(aiosqlite.Connection, 'execute', fail_metadata_update)
    with pytest.raises(RuntimeError, match='Simulated purge failure'):
        await db.purge_old(100)
    with sqlite3.connect(db.db_path) as connection:
        assert connection.execute('SELECT COUNT(*) FROM login_requests').fetchone()[0] == 1
        assert connection.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 1


async def test_recent_logins_reports_expired_pending(db, client):
    await linked(db)
    login_id, _, _ = await db.start_request('alice', 'ip', 'ua')
    with sqlite3.connect(db.db_path) as connection:
        connection.execute('UPDATE login_requests SET expires_at=0 WHERE id=?', (login_id,))
    response = await client.post('/internal/account', json={'telegram_id': 42}, headers={'X-Internal-Key': settings.INTERNAL_API_KEY})
    assert response.json()['recent_logins'][0]['status'] == 'expired'


@pytest.mark.parametrize('field,value', [('verification_code', None), ('verification_code', True), ('verification_code', '42'), ('verification_code', 9), ('verification_code', 100), ('requested_at', None), ('requested_at', ''), ('ip', None), ('user_agent', None)])
async def test_notification_validation(field, value):
    bot = TeleLoginBot.__new__(TeleLoginBot)
    bot.send_login_notification = AsyncMock()
    payload = {'telegram_id': 42, 'login_id': 'id', 'username': 'alice', 'verification_code': 42, 'requested_at': '2026-10-22T00:00:00+00:00', 'ip': '', 'user_agent': ''}
    for missing in (True, False):
        data = dict(payload)
        if missing:
            del data[field]
        else:
            data[field] = value
        request = SimpleNamespace(headers={'X-Internal-Key': settings.INTERNAL_API_KEY}, json=AsyncMock(return_value=data))
        response = await bot.handle_login_notification(request)
        assert response.status == 400
        assert json.loads(response.body) == {'error': 'Missing required fields'}
        bot.send_login_notification.assert_not_awaited()
    request.json.return_value = payload
    assert (await bot.handle_login_notification(request)).status == 200


@pytest.mark.parametrize('command', ['status_command', 'sessions_command'])
@pytest.mark.parametrize('status,text', [(404, 'No linked account'), (401, 'Unable to process request'), (500, 'Unable to process request')])
async def test_bot_account_errors(command, status, text):
    bot = TeleLoginBot.__new__(TeleLoginBot)
    bot.internal_request = AsyncMock(return_value=httpx.Response(status))
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42), message=SimpleNamespace(reply_text=AsyncMock()))
    await getattr(bot, command)(update, None)
    update.message.reply_text.assert_awaited_once_with(text)


async def test_bot_sessions_caps_and_sorts():
    bot = TeleLoginBot.__new__(TeleLoginBot)
    sessions = [dict(id=str(i), created_at=i, last_used_at=None, ip='ip', user_agent='ua') for i in range(12)]
    sessions[0]['last_used_at'] = 100
    bot.internal_request = AsyncMock(return_value=httpx.Response(200, json={'sessions': sessions}))
    reply = AsyncMock()
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42), message=SimpleNamespace(reply_text=reply))
    await bot.sessions_command(update, None)
    assert reply.await_count == 11
    shown = [call.kwargs['reply_markup'].inline_keyboard[0][0].callback_data for call in reply.call_args_list[:10]]
    assert shown == ['revoke_session:0'] + [f'revoke_session:{i}' for i in range(11, 2, -1)]
    assert reply.call_args.args == ('2 more not shown',)
    assert reply.call_args.kwargs['reply_markup'].inline_keyboard[0][0].callback_data == 'revoke_all'


async def test_migration_from_cbc70b8_schema(tmp_path):
    import hashlib
    import sqlite3
    from src.database.sqlite import SQLiteDatabase
    path = str(tmp_path / "cbc70b8.db")
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, telegram_id INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, linked_at DATETIME);
            CREATE TABLE login_requests (id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, status TEXT DEFAULT 'pending', session_token TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, expires_at REAL, token_delivered_at REAL, FOREIGN KEY (user_id) REFERENCES users (id));
            CREATE INDEX idx_users_username ON users(username);
            CREATE UNIQUE INDEX idx_users_telegram_id ON users(telegram_id) WHERE telegram_id IS NOT NULL;
            CREATE TABLE registration_tokens (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires_at REAL NOT NULL, used_at REAL);
            CREATE INDEX idx_login_requests_user_id ON login_requests(user_id);
            INSERT INTO users (id, username, telegram_id, linked_at) VALUES (1, 'linked', 42, '2026-01-01T00:00:00+00:00'), (2, 'pending', NULL, NULL);
        """)
        connection.execute("INSERT INTO registration_tokens VALUES (?, 2, 9999999999, NULL)", (hashlib.sha256(b"tok").hexdigest(),))
        connection.execute("INSERT INTO login_requests (id, user_id, status, session_token, expires_at) VALUES ('legacy', 1, 'approved', 'legacy-jwt', 9999999999)")
    database = SQLiteDatabase(path)
    await database.init_db()
    await database.init_db()
    linked = await database.get_user_by_username("linked")
    assert linked.telegram_id == 42 and linked.linked_at == "2026-01-01T00:00:00+00:00"
    assert (await database.get_user_by_username("pending")).telegram_id is None
    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(login_requests)")}
        assert {"ip", "user_agent", "verification_code", "refresh_token"} <= columns
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='sessions'").fetchone()
    assert await database.take_login_status("legacy") == {"status": "approved", "session_token": "legacy-jwt", "refresh_token": None}
    await database.consume_and_link("tok", 43)
    assert (await database.get_user_by_username("pending")).telegram_id == 43


async def test_me_does_not_take_write_lock(db):
    import sqlite3
    from test_phase3 import issue
    from src.utils.crypto import verify_token
    await linked(db)
    tokens = await issue(db)
    blocker = sqlite3.connect(db.db_path, timeout=0)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        assert (await asyncio.wait_for(db.session(verify_token(tokens["session_token"])), 2))["username"] == "alice"
    finally:
        blocker.rollback()
        blocker.close()


async def test_account_commands_private_only():
    from src.bot import TeleLoginBot
    bot = TeleLoginBot.__new__(TeleLoginBot)
    bot.internal_request = AsyncMock()
    query = SimpleNamespace(answer=AsyncMock(), edit_message_text=AsyncMock())
    for data in ("unlink_confirm", "revoke_all"):
        query.data = data
        update = SimpleNamespace(callback_query=query, effective_chat=SimpleNamespace(type="group"), effective_user=SimpleNamespace(id=42))
        await bot.button_callback(update, None)
    bot.internal_request.assert_not_called()
    assert "private chat" in query.edit_message_text.call_args.args[0]
    message = SimpleNamespace(reply_text=AsyncMock())
    await bot.private_only_command(SimpleNamespace(message=message), None)
    assert "private chat" in message.reply_text.call_args.args[0]
