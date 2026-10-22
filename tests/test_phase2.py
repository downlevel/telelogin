from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from src.app import app
from src.config import Settings, settings
from src.services.auth_service import AuthService
from src.web.security import RateLimiter
from test_security import linked


@pytest.mark.parametrize('first', ['post', 'get'])
async def test_status_shared_delivery(db, monkeypatch, first):
    monkeypatch.setattr(app.state, 'db', db, raising=False)
    user = await linked(db)
    login_id = (await db.start_request(user.username, "127.0.0.1", "test"))[0]
    assert await AuthService(db).confirm_login(login_id, 42, (await db.get_login_request(login_id))["verification_code"]) == {"status": "authenticated"}
    original = await db.get_login_request(login_id)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        async def poll(method):
            if method == 'post':
                return await client.post('/auth/status', json={'login_id': login_id})
            return await client.get('/status/' + login_id)
        assert (await poll(first)).json()['session_token'] == original['session_token']
        assert (await poll('get' if first == 'post' else 'post')).json() == {'status': 'approved'}
        assert (await poll(first)).json() == {'status': 'approved'}
        assert (await client.post('/auth/status', json={'login_id': 'missing'})).status_code == 404
    assert app.openapi()['paths']['/status/{login_id}']['get']['deprecated']


async def test_lifespan_health_login(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'DB_URL', 'sqlite:///' + str(tmp_path / 'lifecycle.db'))
    previous_state = app.state._state.copy()
    try:
        async with app.router.lifespan_context(app):
            assert isinstance(app.state.limiter, RateLimiter)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                assert (await client.get('/health')).json() == {'status': 'ok'}
                response = await client.get('/login')
                assert response.status_code == 200 and 'text/html' in response.headers['content-type']
                assert "request('sso/complete'" in response.text and 'setInterval' not in response.text
                assert "request('/sso/" not in response.text
                assert 'Sign in' in (await client.get('/')).text
    finally:
        app.state._state.clear()
        app.state._state.update(previous_state)


@pytest.mark.parametrize('template', ['.env.example', 'docker/env.example'])
def test_settings_templates(template, monkeypatch):
    for name in ('BOT_TOKEN', 'SECRET_KEY', 'INTERNAL_API_KEY'):
        monkeypatch.delenv(name, raising=False)
    config = Settings(_env_file=Path(__file__).parents[1] / template)
    assert config.API_PORT == 8000
    assert len(config.SECRET_KEY) >= 32 and len(config.INTERNAL_API_KEY) >= 32


async def test_configured_urls_and_bot_health(db, monkeypatch):
    from src.bot import TeleLoginBot
    monkeypatch.setattr(settings, 'API_BASE_URL', 'http://custom-api:9000/')
    monkeypatch.setattr(settings, 'BOT_NOTIFY_URL', 'http://custom-bot:9001/notify-login')
    bot = TeleLoginBot()
    assert bot.api_base_url == 'http://custom-api:9000'
    post = AsyncMock(return_value=httpx.Response(200, request=httpx.Request('POST', settings.BOT_NOTIFY_URL)))
    monkeypatch.setattr(httpx.AsyncClient, 'post', post)
    await AuthService(db).send_login_notification(42, 'private', 'alice', 42, 'now', 'ip', 'ua')
    assert post.call_args.args[0] == settings.BOT_NOTIFY_URL
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=42, username='alice'),
        message=SimpleNamespace(reply_text=AsyncMock()),
    )
    await bot.link_account(update, 'registration-token')
    assert post.call_args.args[0] == f"{settings.API_BASE_URL.rstrip('/')}/auth/link-telegram"
    assert post.call_args.kwargs['json'] == {'token': 'registration-token', 'telegram_id': 42}
    assert post.call_args.kwargs['headers']['X-Internal-Key'] == settings.INTERNAL_API_KEY
    bot.app = SimpleNamespace(running=False)
    assert (await bot.health(None)).status == 503
    bot.app.running = True
    assert (await bot.health(None)).status == 200


def test_crlf_and_no_dead_code():
    for path in [*Path('src').rglob('*.py'), Path('src/web/templates/index.html')]:
        data = path.read_bytes()
        assert b'\n' not in data.replace(b'\r\n', b'')
    for path in Path('src').rglob('*.py'):
        text = path.read_text()
        for dead in ('utcnow', 'startattach', 'create_signed_token', 'TODO'):
            assert dead not in text
