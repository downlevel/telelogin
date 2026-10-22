import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from src import admin
from src.config import settings
from src.services.token_service import TokenService


def args(*values):
    return admin.parser().parse_args(values)


def test_gen_secrets_without_settings(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in ('BOT_TOKEN', 'SECRET_KEY', 'INTERNAL_API_KEY')}
    env['PYTHONPATH'] = str(Path.cwd())
    result = subprocess.run([sys.executable, '-m', 'src.admin', 'gen-secrets'], cwd=tmp_path, env=env, text=True, capture_output=True, check=True)
    lines = dict(line.split('=', 1) for line in result.stdout.splitlines())
    assert set(lines) == {'SECRET_KEY', 'INTERNAL_API_KEY'}
    assert all(len(value) >= 43 for value in lines.values())


async def test_admin_app_lifecycle(db, monkeypatch, capsys):
    monkeypatch.setattr(settings, 'DB_URL', 'sqlite:///' + db.db_path)
    monkeypatch.setattr(settings, 'PUBLIC_URL', 'https://auth.example.com')
    monkeypatch.setattr(settings, 'SSO_COOKIE_DOMAIN', 'example.com')
    await admin.run(args('user', 'invite', 'alice'))
    link = capsys.readouterr().out.strip()
    assert link.startswith('https://t.me/')
    await db.consume_and_link(link.split('?start=')[1], 42)
    await admin.run(args('app', 'add', 'demo', '--name', 'Demo'))
    await admin.run(args('app', 'allow', 'demo', 'alice'))
    await admin.run(args('app', 'origin', 'add', 'demo', 'https://APP.example.com'))
    assert json.loads((await db.get_app('demo'))['origins']) == ['https://app.example.com']
    await admin.run(args('app', 'show', 'demo'))
    output = capsys.readouterr().out
    assert 'alice' in output and 'secret_hash' not in output
    for command in [('app', 'list'), ('user', 'list'), ('app', 'policy', 'demo', 'all'), ('app', 'disallow', 'demo', 'alice'), ('app', 'origin', 'remove', 'demo', 'https://app.example.com')]:
        await admin.run(args(*command))
    assert (await db.get_app('demo'))['access_policy'] == 'all'
    for command in [('app', 'add', 'BAD', '--name', 'Invalid'), ('app', 'show', 'missing'), ('app', 'allow', 'demo', 'missing'), ('app', 'origin', 'add', 'demo', 'https://evil.test')]:
        with pytest.raises(ValueError):
            await admin.run(args(*command))
    await admin.run(args('app', 'allow', 'demo', 'alice'))
    await admin.run(args('app', 'remove', 'demo'))
    assert await db.get_app('demo') is None
    await admin.run(args('user', 'remove', 'alice'))
    assert await db.get_user_by_username('alice') is None


@pytest.mark.parametrize('value', ['https://evil.test', 'https://app.example.com/path', 'https://app.example.com?q=1', 'http://app.example.com', 'https://auth.example.com#fragment', 'https://user@auth.example.com'])
def test_invalid_origins(value, monkeypatch):
    monkeypatch.setattr(settings, 'PUBLIC_URL', 'https://auth.example.com')
    monkeypatch.setattr(settings, 'SSO_COOKIE_DOMAIN', '')
    with pytest.raises(ValueError):
        admin.validated_origin(value)


async def test_invite_with_closed_registration(db, monkeypatch, capsys):
    monkeypatch.setattr(settings, 'DB_URL', 'sqlite:///' + db.db_path)
    monkeypatch.setattr(settings, 'REGISTRATION_MODE', 'closed')
    await admin.run(args('user', 'invite', 'alice'))
    token = capsys.readouterr().out.strip().split('?start=')[1]
    await db.consume_and_link(token, 42)
    assert (await db.get_user_by_telegram_id(42)).username == 'alice'
    with pytest.raises(ValueError):
        await db.consume_and_link(token, 43)
    with patch.object(TokenService, 'create_telegram_link', return_value='link'):
        await admin.run(args('user', 'invite', 'bob'))


@pytest.mark.parametrize('username', ['', 'ab', 'x' * 51])
def test_invite_invalid_username_exits_one(username, monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['admin', 'user', 'invite', username])
    with patch('src.database.sqlite.SQLiteDatabase') as database:
        with pytest.raises(SystemExit) as exc:
            admin.main()
        assert exc.value.code == 1
        database.assert_not_called()
    assert 'username' in capsys.readouterr().err.lower()


def test_invite_duplicate_exits_one(monkeypatch, capsys):
    import aiosqlite
    from unittest.mock import AsyncMock
    monkeypatch.setattr(sys, 'argv', ['admin', 'user', 'invite', 'alice'])
    with patch('src.database.sqlite.SQLiteDatabase') as database:
        database.return_value.init_db = AsyncMock()
        database.return_value.create_user = AsyncMock(side_effect=aiosqlite.IntegrityError('UNIQUE constraint failed: users.username'))
        with pytest.raises(SystemExit) as exc:
            admin.main()
        assert exc.value.code == 1
    assert 'Username already exists' in capsys.readouterr().err


async def test_allow_rejects_unlinked_user(db, monkeypatch):
    monkeypatch.setattr(settings, 'DB_URL', 'sqlite:///' + db.db_path)
    await db.create_user('alice')
    await admin.run(args('app', 'add', 'demo', '--name', 'Demo'))
    with pytest.raises(ValueError, match='user exists but has not linked Telegram yet'):
        await admin.run(args('app', 'allow', 'demo', 'alice'))
    import sqlite3
    with sqlite3.connect(db.db_path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM app_users').fetchone()[0] == 0
    tokens = TokenService(db)
    user = await db.get_user_by_username('alice')
    await db.consume_and_link(await tokens.generate_registration_token(user.id), 42)
    await admin.run(args('app', 'allow', 'demo', 'alice'))


async def test_oidc_client_commands(db, monkeypatch, capsys):
    import hashlib
    import sqlite3
    monkeypatch.setattr(settings, 'DB_URL', 'sqlite:///' + db.db_path)
    uri = 'https://client.example/callback'
    await admin.run(args('app', 'add', 'oidc', '--name', 'Client', '--redirect-uri', uri, '--redirect-uri', 'http://localhost:9000/callback'))
    secret = capsys.readouterr().out.strip().split('Client secret: ')[1]
    app = await db.get_app('oidc')
    assert app['secret_hash'] == hashlib.sha256(secret.encode()).hexdigest()
    assert json.loads(app['redirect_uris']) == [uri, 'http://localhost:9000/callback']
    for action in ('show', 'list'):
        await admin.run(args('app', action, *(['oidc'] if action == 'show' else [])))
        output = capsys.readouterr().out
        assert secret not in output and app['secret_hash'] not in output and 'secret_hash' not in output
    await admin.run(args('app', 'rotate-secret', 'oidc'))
    replacement = capsys.readouterr().out.strip().split('Client secret: ')[1]
    assert replacement != secret
    assert (await db.get_app('oidc'))['secret_hash'] == hashlib.sha256(replacement.encode()).hexdigest()
    await admin.run(args('app', 'redirect-uri', 'remove', 'oidc', uri))
    assert uri not in json.loads((await db.get_app('oidc'))['redirect_uris'])
    await admin.run(args('app', 'add', 'forward', '--name', 'Forward'))
    capsys.readouterr()
    await admin.run(args('app', 'redirect-uri', 'add', 'forward', uri))
    assert 'Client secret: ' in capsys.readouterr().out
    await admin.run(args('app', 'redirect-uri', 'add', 'forward', uri))
    assert capsys.readouterr().out.strip() == 'OK'
    with sqlite3.connect(db.db_path) as conn:
        conn.execute("INSERT INTO oidc_codes(code_hash,app_id) VALUES ('code','oidc')")
        conn.execute("INSERT INTO oidc_tokens(token_hash,app_id) VALUES ('token','oidc')")
    await admin.run(args('app', 'remove', 'oidc'))
    with sqlite3.connect(db.db_path) as conn:
        for table in ('oidc_codes', 'oidc_tokens'):
            assert conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0


@pytest.mark.parametrize('uri', ['https://client.example/cb#fragment', 'http://client.example/cb', '/callback', 'https://user@client.example/cb', 'javascript:alert(1)', 'https://client.example/\ncb', 'https://client.example/cb#'])
def test_invalid_redirect_uris(uri):
    with pytest.raises(ValueError):
        admin.validated_redirect(uri)


async def test_admin_user_remove_oidc_cascade(db, monkeypatch, capsys):
    import sqlite3
    monkeypatch.setattr(settings, 'DB_URL', 'sqlite:///' + db.db_path)
    user = await db.create_user('delete-me')
    with sqlite3.connect(db.db_path) as conn:
        conn.execute('INSERT INTO oidc_codes(code_hash,user_id) VALUES (?,?)', ('code', user.id))
        conn.execute('INSERT INTO oidc_tokens(token_hash,user_id) VALUES (?,?)', ('token', user.id))
    await admin.run(args('user', 'remove', 'delete-me'))
    with sqlite3.connect(db.db_path) as conn:
        for table in ('oidc_codes', 'oidc_tokens'):
            assert conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0
