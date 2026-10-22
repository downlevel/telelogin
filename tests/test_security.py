import asyncio
import hashlib
import sqlite3
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import BackgroundTasks
from src.config import Settings, settings
from src.database.sqlite import SQLiteDatabase
from src.services.auth_service import AuthService
from src.services.token_service import TokenService
from src.web import routes
from src.app import app
from src.web.security import RateLimiter




async def linked(db, username="alice", telegram_id=42):
    user = await db.create_user(username)
    token = await TokenService(db).generate_registration_token(user.id)
    await db.consume_and_link(token, telegram_id)
    return user


async def test_tokens_persist_single_use_and_rollback(db):
    first = await linked(db)
    user = await db.create_user("bob")
    token = await TokenService(db).generate_registration_token(user.id)
    restarted = SQLiteDatabase(db.db_path)
    with pytest.raises(ValueError, match="already linked"):
        await restarted.consume_and_link(token, first.telegram_id or 42)
    results = await asyncio.gather(restarted.consume_and_link(token, 43), db.consume_and_link(token, 44), return_exceptions=True)
    assert sum(result is None for result in results) == 1
    with sqlite3.connect(db.db_path) as connection:
        assert connection.execute("SELECT token_hash FROM registration_tokens WHERE user_id=?", (user.id,)).fetchone()[0] == hashlib.sha256(token.encode()).hexdigest()
    expired = await TokenService(db).generate_registration_token(user.id, expires_in_minutes=-1)
    with pytest.raises(ValueError):
        await db.consume_and_link(expired, 45)


async def test_concurrent_links_keep_losing_token(db):
    users = [await db.create_user(name) for name in ("alice", "bob")]
    tokens = [await TokenService(db).generate_registration_token(user.id) for user in users]
    results = await asyncio.gather(*(db.consume_and_link(token, 99) for token in tokens), return_exceptions=True)
    assert sum(result is None for result in results) == 1
    loser = next(index for index, result in enumerate(results) if isinstance(result, Exception))
    await db.consume_and_link(tokens[loser], 100)


async def test_confirm_races_and_original_token_delivery(db):
    user = await linked(db)
    auth = AuthService(db)
    login = (await db.start_request(user.username, "127.0.0.1", "test"))[0]
    code = (await db.get_login_request(login))["verification_code"]
    results = await asyncio.gather(*(auth.confirm_login(login, 42, code) for _ in range(2)))
    winner = next(result for result in results if result)
    assert winner == {"status": "authenticated"}
    original = await db.get_login_request(login)
    assert sum(result is not None for result in results) == 1
    assert not await db.update_login_status(login, "denied", telegram_id=42)
    statuses = await asyncio.gather(*(auth.get_login_status(login) for _ in range(2)))
    assert [result["session_token"] for result in statuses if "session_token" in result] == [original["session_token"]]
    assert await auth.get_login_status(login) == {"status": "approved"}


async def test_confirm_deny_race_and_owner(db):
    user = await linked(db)
    login = (await db.start_request(user.username, "127.0.0.1", "test"))[0]
    assert not await db.update_login_status(login, "denied", telegram_id=999)
    confirm, deny = await asyncio.gather(AuthService(db).confirm_login(login, 42, (await db.get_login_request(login))["verification_code"]), db.update_login_status(login, "denied", telegram_id=42))
    assert bool(confirm) != deny
    assert (await db.get_login_request(login))["status"] == ("approved" if confirm else "denied")


async def test_expiry_real_and_dummy(db, monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_REQUEST_TTL_SECONDS", 0.01)
    await linked(db)
    auth = AuthService(db)
    tasks = BackgroundTasks()
    real = await auth.start_login("alice", tasks)
    dummy = await auth.start_login("missing", BackgroundTasks())
    unlinked = await db.create_user("unlinked")
    fake = await auth.start_login(unlinked.username, BackgroundTasks())
    assert len(tasks.tasks) == 1
    await asyncio.sleep(0.02)
    for request in (real, dummy, fake):
        assert await auth.confirm_login(request["login_id"], 42, request["verification_code"]) is None
        assert await auth.get_login_status(request["login_id"]) == {"status": "expired"}


async def test_internal_api_and_public_flow(db, monkeypatch):
    monkeypatch.setattr(app.state, "db", db, raising=False)
    monkeypatch.setattr(app.state, "limiter", RateLimiter(), raising=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for endpoint, payload in [("link-telegram", {"token": "x", "telegram_id": 42}), ("confirm-login", {"login_id": "x", "telegram_id": 42}), ("deny-login", {"login_id": "x", "telegram_id": 42})]:
            for headers in ({}, {"X-Internal-Key": "wrong"}):
                assert (await client.post(f"/auth/{endpoint}", json=payload, headers=headers)).status_code == 401
        response = await client.post("/register", json={"username": "alice"})
        token = response.json()["link"].split("start=")[1].split("&")[0]
        assert (await client.post("/register", json={"username": "alice"})).status_code == 400
        assert (await client.post("/auth/link-telegram", json={"token": token, "telegram_id": 42}, headers={"X-Internal-Key": settings.INTERNAL_API_KEY})).status_code == 200
        for _ in range(settings.RATE_LIMIT_USERNAME):
            assert (await client.post("/auth/start-login", json={"username": "missing"})).status_code == 200
        assert (await client.post("/auth/start-login", json={"username": "missing"})).status_code == 429
        assert (await client.options("/register", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})).status_code == 400


async def test_background_latency(db, monkeypatch):
    await linked(db)
    auth = AuthService(db)
    async def slow(*args):
        await asyncio.sleep(5)
    monkeypatch.setattr(auth, "send_login_notification", slow)
    tasks = BackgroundTasks()
    for username in ("alice", "missing"):
        start = time.monotonic()
        await auth.start_login(username, tasks)
        assert time.monotonic() - start < 1
    assert len(tasks.tasks) == 1


async def test_notification_header_and_failure(db, monkeypatch, caplog):
    post = AsyncMock(side_effect=RuntimeError("sensitive-token"))
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    await AuthService(db).send_login_notification(42, "id", "alice", 42, "now", "ip", "ua")
    assert post.call_args.kwargs["headers"]["X-Internal-Key"] == settings.INTERNAL_API_KEY
    assert "sensitive-token" not in caplog.text


def test_settings_and_paths(tmp_path, monkeypatch):
    for key in ("SECRET_KEY", "INTERNAL_API_KEY"):
        with pytest.raises(ValueError):
            Settings(**{key: "short"})
    for path in ("relative.db", str(tmp_path / "absolute.db")):
        monkeypatch.setattr(settings, "DB_URL", "sqlite:///" + path)
        assert SQLiteDatabase().db_path == path
    monkeypatch.setattr(settings, "DB_URL", "postgres://bad")
    with pytest.raises(ValueError):
        SQLiteDatabase()


async def test_baseline_migration(tmp_path, caplog):
    path = str(tmp_path / "old.db")
    with sqlite3.connect(path) as connection:
        connection.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, telegram_id INTEGER, created_at DATETIME, linked_at DATETIME); CREATE TABLE login_requests(id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, status TEXT DEFAULT 'pending', session_token TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP); CREATE INDEX idx_users_telegram_id ON users(telegram_id); INSERT INTO users VALUES(1,'old',42,NULL,'2020-01-01'), (2,'new',42,NULL,'2021-01-01'); INSERT INTO login_requests(id,user_id,created_at) VALUES('old',1,'2020-01-01');")
    database = SQLiteDatabase(path)
    await asyncio.gather(database.init_db(), database.init_db())
    assert (await database.get_user_by_username("old")).telegram_id == 42
    assert (await database.get_user_by_username("new")).telegram_id is None
    assert "Unlinked duplicate" in caplog.text
    assert await database.take_login_status("old") == {"status": "expired"}
    with sqlite3.connect(path) as connection:
        index = connection.execute("SELECT sql FROM sqlite_master WHERE name='idx_users_telegram_id'").fetchone()[0]
        assert "UNIQUE" in index and "WHERE telegram_id IS NOT NULL" in index


async def test_bot_auth_callbacks_and_errors(monkeypatch, caplog):
    from src.bot import TeleLoginBot
    bot = TeleLoginBot.__new__(TeleLoginBot)
    bot.api_base_url = "http://api:8000"
    bot.send_login_notification = AsyncMock()
    request = SimpleNamespace(headers={}, json=AsyncMock())
    assert (await bot.handle_login_notification(request)).status == 401
    bot.send_login_notification.assert_not_called()
    request.headers = {"X-Internal-Key": settings.INTERNAL_API_KEY}
    request.json.return_value = {"telegram_id": 42, "login_id": "secret-login-id", "username": "alice", "verification_code": 42, "requested_at": "now", "ip": "ip", "user_agent": "ua"}
    assert (await bot.handle_login_notification(request)).status == 200
    query = SimpleNamespace(data=None, answer=AsyncMock(), edit_message_text=AsyncMock())
    update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=42, username="alice", first_name="Alice"), message=SimpleNamespace(reply_text=AsyncMock()))
    for data in (None, "bad", "login_deny:", "login_deny:a:b", "unknown:123"):
        query.data = data
        await bot.button_callback(update, None)
    post = AsyncMock(side_effect=RuntimeError("secret-token"))
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    for action in ("login_confirm", "login_deny"):
        query.data = action + ":00000000-0000-0000-0000-000000000001" + (":42" if action == "login_confirm" else "")
        await bot.button_callback(update, None)
        assert post.call_args.kwargs["headers"]["X-Internal-Key"] == settings.INTERNAL_API_KEY
    for method in (bot.start_command, bot.link_command):
        await method(update, SimpleNamespace(args=["secret-token"]))
    assert "secret-token" not in caplog.text
    assert "secret-login-id" not in caplog.text
    assert "secret-token" not in str(update.message.reply_text.call_args_list)
    assert "secret-token" not in str(query.edit_message_text.call_args_list)


def test_rate_limits_ip_register_and_window(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(settings, "RATE_LIMIT_IP", 2)
    monkeypatch.setattr(settings, "RATE_LIMIT_USERNAME", 1)
    limiter = RateLimiter()
    for operation in ("register", "login"):
        limiter.check(operation, "alice", "ip")
        with pytest.raises(HTTPException) as error:
            limiter.check(operation, "alice", "other-ip")
        assert error.value.status_code == 429
        limiter.check(operation, "bob", "ip")
        with pytest.raises(HTTPException):
            limiter.check(operation, "carol", "ip")
    future = time.monotonic() + 601
    monkeypatch.setattr("src.web.security.time.monotonic", lambda: future)
    limiter.check("register", "alice", "ip")


async def test_response_sent_before_slow_background_notification(db, monkeypatch):
    import json
    await linked(db)
    auth = AuthService(db)
    notified = []

    async def slow(*args):
        await asyncio.sleep(5)
        notified.append(True)

    monkeypatch.setattr(auth, "send_login_notification", slow)
    monkeypatch.setitem(app.dependency_overrides, routes.get_auth_service, lambda: auth)
    monkeypatch.setattr(app.state, "limiter", RateLimiter(), raising=False)
    for username in ("alice", "missing"):
        started = time.monotonic()
        messages = []
        body = json.dumps({"username": username}).encode()

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            messages.append((time.monotonic() - started, message))

        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http", "path": "/auth/start-login", "raw_path": b"/auth/start-login", "query_string": b"", "headers": [(b"content-type", b"application/json")], "client": ("127.0.0.1", 1234), "server": ("test", 80), "root_path": ""}
        await app(scope, receive, send)
        assert next(message["status"] for _, message in messages if message["type"] == "http.response.start") == 200
        assert next(elapsed for elapsed, message in messages if message["type"] == "http.response.body") < 1
    assert notified == [True]


async def test_migration_prefers_real_linked_at_over_null(tmp_path):
    path = str(tmp_path / "nulls.db")
    with sqlite3.connect(path) as connection:
        connection.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, telegram_id INTEGER, created_at DATETIME, linked_at DATETIME); CREATE TABLE login_requests(id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, status TEXT DEFAULT 'pending', session_token TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP); INSERT INTO users VALUES(1,'nulllink',42,NULL,NULL), (2,'reallink',42,NULL,'2021-01-01');")
    database = SQLiteDatabase(path)
    await database.init_db()
    assert (await database.get_user_by_username("reallink")).telegram_id == 42
    assert (await database.get_user_by_username("nulllink")).telegram_id is None


def test_bot_registration_error_messages():
    from src.bot import TeleLoginBot
    def response(status, detail=None):
        return httpx.Response(status, json={"detail": detail} if detail else None)
    message = TeleLoginBot.registration_error_message
    assert "already linked" in message(response(400, "Telegram already linked to another account"))
    assert "invalid or expired" in message(response(400, "Invalid or expired token"))
    for other in (response(400, "<b>injected</b>"), response(500), response(400)):
        text = message(other)
        assert text.startswith("❌ Registration failed") and "injected" not in text


def test_compose_passes_tunables():
    import pathlib
    compose = pathlib.Path("docker/docker-compose.yml").read_text()
    api, bot = compose.split("\n  bot:\n")
    for name in ("CORS_ORIGINS", "LOGIN_REQUEST_TTL_SECONDS", "REGISTRATION_TOKEN_TTL_SECONDS", "RATE_LIMIT_WINDOW_SECONDS", "RATE_LIMIT_USERNAME", "RATE_LIMIT_IP", "INTERNAL_API_KEY"):
        assert f"- {name}=" in api
    for name in ("LOGIN_REQUEST_TTL_SECONDS", "INTERNAL_API_KEY", "DEBUG"):
        assert f"- {name}=" in bot


def test_telegram_library_debug_logging_disabled(monkeypatch):
    import importlib
    import logging
    import src.bot
    monkeypatch.setattr(settings, "DEBUG", True)
    importlib.reload(src.bot)
    assert logging.getLogger("telegram").getEffectiveLevel() >= logging.INFO
    assert not logging.getLogger("telegram.ext.Application").isEnabledFor(logging.DEBUG)


@pytest.mark.parametrize('key', ['SECRET_KEY', 'INTERNAL_API_KEY'])
@pytest.mark.parametrize('placeholder', [
    'your_secret_key_here_minimum_32_characters_long',
    'replace_with_shared_random_secret_at_least_32_characters',
])
def test_settings_reject_template_secrets(key, placeholder):
    with pytest.raises(ValueError, match='run gen-secrets'):
        Settings(_env_file=None, **{key: placeholder})
