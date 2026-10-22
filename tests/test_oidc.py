"""OIDC interoperability, grant isolation and lifecycle tests."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import time
from threading import Barrier
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.oidc.core import CodeIDToken
from joserfc import jwt
from joserfc.jwk import KeySet
import httpx2
import pytest
from fastapi import FastAPI

from src.app import app
from src.config import settings
from src.web.oidc import digest, load_key
from src.web.security import RateLimiter
from test_security import linked

BASE = 'http://testserver/telelogin'
URI = 'https://client.example.com/callback?existing=1'
SECRET = 'client-secret'


@pytest.fixture
async def oidc(db, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, 'PUBLIC_URL', BASE)
    monkeypatch.setattr(settings, 'SSO_COOKIE_SECURE', False)
    monkeypatch.setattr(settings, 'SSO_COOKIE_DOMAIN', '')
    monkeypatch.setattr(app.state, 'db', db, raising=False)
    monkeypatch.setattr(app.state, 'oidc_key', load_key(tmp_path / 'key.pem'), raising=False)
    monkeypatch.setattr(app.state, 'limiter', RateLimiter(), raising=False)
    monkeypatch.setattr(app.state, 'login_html', Path('src/web/templates/index.html').read_text(), raising=False)
    monkeypatch.setattr('src.services.auth_service.AuthService.send_login_notification', AsyncMock())
    user = await linked(db)
    with sqlite3.connect(db.db_path) as conn:
        conn.execute('INSERT INTO apps VALUES (?,?,?,?,?,?,?)', ('demo', 'Demo', 'all', digest(SECRET), json.dumps([URI]), '[]', time.time()))
    mounted = FastAPI()
    mounted.mount('/telelogin', app)
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=mounted), base_url=BASE + '/') as client:
        yield client, mounted, user


async def browser(client):
    start = (await client.post('sso/start', json={'username': 'alice', 'app': 'demo'})).json()
    result = await client.post('auth/confirm-login', json=dict(login_id=start['login_id'], telegram_id=42, verification_code=start['verification_code']), headers={'X-Internal-Key': settings.INTERNAL_API_KEY})
    assert result.status_code == 200, result.text
    result = await client.post('sso/complete', json={'login_id': start['login_id']})
    assert result.json()['status'] == 'approved'


def params(**extra):
    return dict(client_id='demo', redirect_uri=URI, response_type='code', scope='openid profile', state='state', **extra)


async def code(client, **extra):
    response = await client.get('authorize', params=params(**extra))
    assert response.status_code == 302
    values = parse_qs(urlsplit(response.headers['location']).query)
    assert values['iss'] == [BASE]
    return values['code'][0]


async def redeem(client, value, **extra):
    body = dict(grant_type='authorization_code', client_id='demo', client_secret=SECRET, redirect_uri=URI, code=value)
    body.update(extra)
    return await client.post('token', data=body)


async def test_authlib_prefix_flow(oidc):
    client, mounted, user = oidc
    discovery = (await client.get('.well-known/openid-configuration')).json()
    assert discovery['issuer'] == BASE
    async with AsyncOAuth2Client('demo', SECRET, transport=httpx2.ASGITransport(app=mounted), code_challenge_method='S256') as oauth:
        verifier = 'v' * 64
        url, state = oauth.create_authorization_url(discovery['authorization_endpoint'], redirect_uri=URI, scope='openid profile', code_verifier=verifier, nonce='nonce')
        first = await client.get(url)
        login = first.headers['location']
        assert login.startswith(BASE + '/login?')
        continuation = parse_qs(urlsplit(login).query)['rd'][0]
        assert continuation.startswith(BASE + '/authorize?')
        await browser(client)
        result = await client.get(continuation)
        callback = result.headers['location']
        assert parse_qs(urlsplit(callback).query)['state'] == [state]
        token = await oauth.fetch_token(discovery['token_endpoint'], authorization_response=callback, state=state, redirect_uri=URI, code_verifier=verifier)
        keys = (await client.get(discovery['jwks_uri'])).json()
        decoded = jwt.decode(token['id_token'], KeySet.import_key_set(keys), algorithms=['RS256'])
        claims = CodeIDToken(decoded.claims, decoded.header, options={'iss': {'essential': True, 'value': BASE}, 'aud': {'essential': True, 'value': 'demo'}, 'nonce': {'essential': True, 'value': 'nonce'}}, params={'client_id': 'demo', 'nonce': 'nonce'})
        claims.validate()
        assert claims['sub'] == user.public_id
        info = await oauth.get(discovery['userinfo_endpoint'])
        assert info.json() == {'sub': user.public_id, 'name': 'alice', 'preferred_username': 'alice'}


async def test_authorization_errors(oidc, db):
    client, _, _ = oidc
    bad = params()
    bad['redirect_uri'] = 'https://evil.example/callback'
    result = await client.get('authorize', params=bad)
    assert result.status_code == 400 and 'location' not in result.headers
    result = await client.get('authorize', params=params(prompt='none'))
    assert 'error=login_required' in result.headers['location']
    await browser(client)
    result = await client.get('authorize', params=params(prompt='login'))
    assert 'force=1' in result.headers['location']
    login = await client.get(result.headers['location'])
    assert login.status_code == 200
    for key, value, expected in [('response_type', 'token', 'unsupported_response_type'), ('scope', 'profile', 'invalid_scope'), ('request_uri', 'https://evil', 'request_not_supported'), ('code_challenge_method', 'plain', 'invalid_request')]:
        query = params()
        query[key] = value
        result = await client.get('authorize', params=query)
        assert 'error=' + expected in result.headers['location']
    with sqlite3.connect(db.db_path) as conn:
        conn.execute("UPDATE apps SET access_policy='allowlist'")
    result = await client.get('authorize', params=params())
    assert 'error=access_denied' in result.headers['location']


@pytest.mark.parametrize('failure', ['wrong-secret', 'expired', 'revoked', 'missing-verifier', 'mismatch', 'unexpected-verifier', 'redirect', 'disallowed'])
async def test_invalid_grants(oidc, db, failure):
    client, _, _ = oidc
    await browser(client)
    pkce = failure in ('missing-verifier', 'mismatch')
    value = await code(client, **({'code_challenge': 'a'*43, 'code_challenge_method': 'S256'} if pkce else {}))
    extra = {}
    if failure == 'wrong-secret':
        extra['client_secret'] = 'wrong'
    if failure in ('mismatch', 'unexpected-verifier'):
        extra['code_verifier'] = 'b'*43
    if failure == 'redirect':
        extra['redirect_uri'] = 'https://other.example/'
    with sqlite3.connect(db.db_path) as conn:
        if failure == 'expired':
            conn.execute('UPDATE oidc_codes SET expires_at=0')
        if failure == 'revoked':
            conn.execute('UPDATE sessions SET revoked_at=1')
        if failure == 'disallowed':
            conn.execute("UPDATE apps SET access_policy='allowlist'")
    result = await redeem(client, value, **extra)
    assert result.status_code == (401 if failure == 'wrong-secret' else 400)
    assert result.json()['error'] == ('invalid_client' if failure == 'wrong-secret' else 'invalid_grant')


@pytest.mark.parametrize('purge', [False, True])
async def test_replay_revokes_tokens(oidc, db, purge):
    client, _, _ = oidc
    await browser(client)
    value = await code(client)
    result = await redeem(client, value)
    assert result.status_code == 200
    token = result.json()['access_token']
    assert (await client.get('userinfo', headers={'Authorization': 'Bearer '+token})).status_code == 200
    if purge:
        with sqlite3.connect(db.db_path) as conn:
            conn.execute('UPDATE oidc_codes SET expires_at=?', (time.time()-1,))
        await db.purge_old(86400)
        with sqlite3.connect(db.db_path) as conn:
            assert conn.execute('SELECT count(*) FROM oidc_codes').fetchone()[0] == 1
            # Even a missing code must retain replay protection through the tokens.
            conn.execute('DELETE FROM oidc_codes')
    assert (await redeem(client, value)).json()['error'] == 'invalid_grant'
    assert (await client.get('userinfo', headers={'Authorization': 'Bearer '+token})).status_code == 401


async def test_token_isolation_and_revocation(oidc, db):
    client, _, user = oidc
    await browser(client)
    value = await code(client)
    result = (await redeem(client, value)).json()
    assert (await client.get('auth/me', headers={'Authorization': 'Bearer '+result['access_token']})).status_code == 401
    api = db.access({'id': user.id, 'username': user.username}, 'sid')
    assert (await client.get('userinfo', headers={'Authorization': 'Bearer '+api})).status_code == 401
    await db.account_action(42, 'revoke')
    result = await client.get('authorize', params=params(prompt='none'))
    assert 'login_required' in result.headers['location']
    await db.account_action(42, 'delete')
    with sqlite3.connect(db.db_path) as conn:
        for table in ('oidc_codes', 'oidc_tokens'):
            assert conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0


def test_keys_concurrent_and_reused(tmp_path, monkeypatch):
    from src.web import oidc
    barrier = Barrier(2)
    original_generate = oidc.rsa.generate_private_key

    def generate(*args, **kwargs):
        barrier.wait(timeout=10)
        return original_generate(*args, **kwargs)

    monkeypatch.setattr(oidc.rsa, 'generate_private_key', generate)
    filename = tmp_path / 'key.pem'
    with ThreadPoolExecutor(2) as pool:
        keys = list(pool.map(load_key, [filename, filename]))
    on_disk = load_key(filename)
    assert keys[0][1] == keys[1][1] == on_disk[1]
    assert all(key[0].private_numbers() == on_disk[0].private_numbers() for key in keys)
    assert filename.stat().st_mode & 0o777 == 0o600
    jwk = keys[0][1]
    from src.web.oidc import b64
    canonical = json.dumps({k: jwk[k] for k in ('e', 'kty', 'n')}, sort_keys=True, separators=(',', ':'))
    assert jwk['kid'] == b64(hashlib.sha256(canonical.encode()).digest())
    assert list(tmp_path.iterdir()) == [filename]


def test_key_publication_failure_and_durability(tmp_path, monkeypatch):
    from src.web import oidc
    filename = tmp_path / 'key.pem'
    events = []
    original_fsync = oidc.os.fsync
    original_link = oidc.os.link

    def fsync(fd):
        events.append('fsync')
        return original_fsync(fd)

    def link(source, target):
        events.append('link')
        return original_link(source, target)

    monkeypatch.setattr(oidc.os, 'fsync', fsync)
    monkeypatch.setattr(oidc.os, 'link', link)
    load_key(filename)
    assert events == ['fsync', 'link', 'fsync']
    filename.unlink()

    def unsupported_link(source, target):
        raise OSError('unsupported filesystem')

    monkeypatch.setattr(oidc.os, 'link', unsupported_link)
    with pytest.raises(OSError, match='must support hard links, or pre-create') as error:
        load_key(filename)
    assert str(error.value.__cause__) == 'unsupported filesystem'
    assert list(tmp_path.iterdir()) == []


async def test_part_a_schema_migration(tmp_path):
    from src.database.sqlite import SQLiteDatabase
    database = SQLiteDatabase(str(tmp_path / 'part-a.db'))
    tables = ('users', 'sessions', 'login_requests', 'apps', 'app_users', 'registration_tokens')
    with sqlite3.connect(database.db_path) as conn:
        conn.executescript(Path('tests/fixtures/part_a_7e7632d.sql').read_text())
        conn.execute("INSERT INTO users(id,username,telegram_id,public_id) VALUES (1,'alice',42,'stable-public-id')")
        conn.execute("INSERT INTO apps(id,name,created_at) VALUES ('demo','Demo',100)")
        conn.execute("INSERT INTO app_users VALUES ('demo',1)")
        for kind in ('api', 'sso'):
            conn.execute('INSERT INTO sessions(id,user_id,refresh_hash,created_at,expires_at,kind) VALUES (?,1,?,100,200,?)', (kind, kind+'-hash', kind))
            conn.execute("INSERT INTO login_requests(id,user_id,status,expires_at,purpose,app_id) VALUES (?,1,'pending',200,?,'demo')", (kind, kind))
        conn.execute("INSERT INTO registration_tokens VALUES ('registration-hash',1,200,NULL)")
        before = {table: conn.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall() for table in tables}
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'oidc_%'").fetchall()
    await database.init_db()
    await database.init_db()
    with sqlite3.connect(database.db_path) as conn:
        for table in tables:
            assert conn.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall() == before[table]
        for table in ('oidc_codes', 'oidc_tokens'):
            assert conn.execute(f'SELECT * FROM {table}').fetchall() == []


def test_example_import(monkeypatch):
    monkeypatch.setenv('OIDC_CLIENT_ID', 'demo')
    monkeypatch.setenv('OIDC_CLIENT_SECRET', SECRET)
    monkeypatch.setenv('SESSION_SECRET', 's'*32)
    spec = importlib.util.spec_from_file_location('oidc_example', 'examples/oidc_fastapi/app.py')
    spec.loader.exec_module(importlib.util.module_from_spec(spec))


async def test_code_retention(db):
    with sqlite3.connect(db.db_path) as conn:
        for name, expiry in [('recent', time.time()-1), ('old', time.time()-settings.OIDC_TOKEN_TTL_SECONDS-10)]:
            conn.execute('INSERT INTO oidc_codes(code_hash,expires_at) VALUES (?,?)', (name, expiry))
            conn.execute('INSERT INTO oidc_tokens(token_hash,expires_at) VALUES (?,?)', (name, expiry))
    await db.purge_old(86400)
    with sqlite3.connect(db.db_path) as conn:
        assert conn.execute('SELECT code_hash FROM oidc_codes').fetchall() == [('recent',)]
        assert conn.execute('SELECT count(*) FROM oidc_tokens').fetchone()[0] == 0


async def test_client_authentication_and_profile_scope(oidc):
    import base64
    client, _, _ = oidc
    await browser(client)
    for auth, data in [(None, {}), ('Basic invalid!', {}), ('Basic '+base64.b64encode(b'demo:client-secret').decode(), {'client_id': 'demo', 'client_secret': SECRET})]:
        headers = {'Authorization': auth} if auth else {}
        response = await client.post('token', data=dict(grant_type='authorization_code', **data), headers=headers)
        assert response.status_code == 401
        if auth:
            assert response.headers['www-authenticate'] == 'Basic'
    response = await redeem(client, 'missing', grant_type='refresh_token')
    assert response.json()['error'] == 'unsupported_grant_type'
    query = params()
    query['scope'] = 'openid unknown'
    response = await client.get('authorize', params=query)
    value = parse_qs(urlsplit(response.headers['location']).query)['code'][0]
    response = await redeem(client, value)
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['pragma'] == 'no-cache'
    token = response.json()['access_token']
    result = await client.post('userinfo', headers={'Authorization': 'Bearer '+token})
    assert list(result.json()) == ['sub']
    assert (await client.get('userinfo', params={'access_token': token})).status_code == 401


async def test_expired_token_and_removed_access(oidc, db):
    client, _, _ = oidc
    await browser(client)
    token = (await redeem(client, await code(client))).json()['access_token']
    with sqlite3.connect(db.db_path) as conn:
        conn.execute('UPDATE oidc_tokens SET expires_at=0')
    assert (await client.get('userinfo', headers={'Authorization': 'Bearer '+token})).status_code == 401
    token = (await redeem(client, await code(client))).json()['access_token']
    with sqlite3.connect(db.db_path) as conn:
        conn.execute("UPDATE apps SET access_policy='allowlist'")
    assert (await client.get('userinfo', headers={'Authorization': 'Bearer '+token})).status_code == 401


@pytest.fixture
async def oidc_without_db(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(settings, 'PUBLIC_URL', BASE)
    fake = SimpleNamespace(get_app=AsyncMock(return_value={'id': 'demo', 'secret_hash': digest(SECRET), 'redirect_uris': json.dumps([URI]), 'origins': '[]'}), browser_session=AsyncMock(return_value=None))
    monkeypatch.setattr(app.state, 'db', fake, raising=False)
    from src.web.dependencies import get_db

    async def fake_db():
        return fake

    monkeypatch.setattr(app, 'dependency_overrides', {**app.dependency_overrides, get_db: fake_db})
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url='http://testserver') as client:
        yield client


async def test_continuation_rejected_before_login(oidc_without_db):
    query = params()
    query['state'] = 'x' * 2048
    response = await oidc_without_db.get('/authorize', params=query)
    assert response.status_code == 302
    target = urlsplit(response.headers['location'])
    assert target.netloc == 'client.example.com'
    values = parse_qs(target.query)
    assert values['error'] == ['invalid_request']
    assert values['error_description'] == ['authorization request too long or invalid']
    assert values['state'] == [query['state']]
    assert values['iss'] == [BASE]


@pytest.mark.parametrize('name', ['client_id', 'redirect_uri', 'state', 'scope', 'response_type', 'nonce', 'unknown'])
async def test_duplicate_authorization_parameters(oidc_without_db, name):
    query = list(params().items())
    # Identical duplicates are also invalid; unknown parameters cannot repeat either.
    query += [(name, params().get(name, 'value'))]
    if name not in params():
        query += [(name, 'value')]
    response = await oidc_without_db.get('/authorize', params=query)
    if name in ('client_id', 'redirect_uri'):
        assert response.status_code == 400
        assert 'location' not in response.headers
        assert response.headers['content-type'].startswith('text/html')
    else:
        assert response.status_code == 302
        values = parse_qs(urlsplit(response.headers['location']).query)
        assert values['error'] == ['invalid_request']
        assert values['state'] == ['state']
        assert values['iss'] == [BASE]


async def test_openapi_without_warnings(monkeypatch):
    import warnings
    monkeypatch.setattr(app, 'openapi_schema', None)
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url='http://testserver') as client:
            response = await client.get('/openapi.json')
    assert response.status_code == 200
    paths = response.json()['paths']['/userinfo']
    assert paths['get']['operationId'] != paths['post']['operationId']


def test_existing_key_permissions_warning(tmp_path, caplog):
    key = tmp_path / 'signing.pem'
    load_key(key)
    assert not caplog.records
    key.chmod(0o644)
    with caplog.at_level('WARNING', logger='src.web.oidc'):
        load_key(key)
    assert 'group/others' in caplog.text
    assert '0600' in caplog.text
    assert key.read_text() not in caplog.text


async def test_lifespan_key_outside_checkout(monkeypatch):
    from types import SimpleNamespace
    from src.app import lifespan
    root = Path(__file__).resolve().parents[1]
    key = Path(settings.OIDC_KEY_FILE).resolve()
    assert not key.is_relative_to(root)
    database = SimpleNamespace(init_db=AsyncMock(), purge_old=AsyncMock())
    monkeypatch.setattr('src.app.SQLiteDatabase', lambda: database)
    # Restore state on teardown even though lifespan assigns these attributes.
    for name in ('db', 'oidc_key', 'limiter', 'login_html'):
        monkeypatch.setattr(app.state, name, getattr(app.state, name, None), raising=False)
    async with lifespan(app):
        assert key.exists()
        assert not (root / 'data/oidc-signing-key.pem').exists()
    assert not (root / 'data/oidc-signing-key.pem').exists()


@pytest.mark.parametrize('body_auth', ['matching', 'mismatching', 'secret'])
async def test_basic_body_client_id_interop(oidc, body_auth):
    import base64
    client, _, _ = oidc
    await browser(client)
    value = await code(client)
    body = dict(grant_type='authorization_code', redirect_uri=URI, code=value, client_id='demo')
    if body_auth == 'mismatching':
        body['client_id'] = 'other'
    if body_auth == 'secret':
        body['client_secret'] = SECRET
    authorization = 'Basic ' + base64.b64encode(b'demo:client-secret').decode()
    response = await client.post('token', data=body, headers={'Authorization': authorization})
    if body_auth == 'matching':
        assert response.status_code == 200, response.text
        assert response.json()['token_type'] == 'Bearer'
    else:
        assert response.status_code == 401
        assert response.json()['error'] == 'invalid_client'
        assert response.headers['www-authenticate'] == 'Basic'


@pytest.mark.parametrize('configured', [False, True])
async def test_example_logout_origin_with_prefix(monkeypatch, configured):
    from starlette.requests import Request
    monkeypatch.setenv('OIDC_CLIENT_ID', 'demo')
    monkeypatch.setenv('OIDC_CLIENT_SECRET', SECRET)
    monkeypatch.setenv('SESSION_SECRET', 's'*32)
    if configured:
        monkeypatch.setenv('APP_ORIGIN', 'https://external.example.com')
    else:
        monkeypatch.delenv('APP_ORIGIN', raising=False)
    spec = importlib.util.spec_from_file_location('oidc_example', 'examples/oidc_fastapi/app.py')
    example = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(example)
    expected = 'https://external.example.com' if configured else 'https://app.example.com'
    for origin, status in [(expected, 303), ('https://evil.example.com', 403)]:
        session = {'user': {'sub': 'test'}}
        request = Request({'type': 'http', 'scheme': 'https', 'server': ('app.example.com', 443),
                           'path': '/prefix/logout', 'root_path': '/prefix', 'query_string': b'',
                           'headers': [(b'host', b'app.example.com'), (b'origin', origin.encode())],
                           'session': session})
        assert (await example.logout(request)).status_code == status
        assert bool(session) == (status == 403)
