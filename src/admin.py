"""Operator CLI. Shell access is administrative access."""
import hashlib
import argparse
import asyncio
import json
import re
import secrets
import sys
import time
from urllib.parse import urlsplit


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='group', required=True)
    sub.add_parser('gen-secrets')
    apps = sub.add_parser('app').add_subparsers(dest='action', required=True)
    add = apps.add_parser('add')
    add.add_argument('id')
    add.add_argument('--name', required=True)
    add.add_argument('--policy', choices=['allowlist', 'all'], default='allowlist')
    add.add_argument('--redirect-uri', action='append', default=[])
    apps.add_parser('rotate-secret').add_argument('id')
    redirects = apps.add_parser('redirect-uri').add_subparsers(dest='operation', required=True)
    for action in ('add', 'remove'):
        a = redirects.add_parser(action)
        a.add_argument('id')
        a.add_argument('uri')
    apps.add_parser('list')
    for action in ('show', 'remove'):
        apps.add_parser(action).add_argument('id')
    policy = apps.add_parser('policy')
    policy.add_argument('id')
    policy.add_argument('policy', choices=['allowlist', 'all'])
    for action in ('allow', 'disallow'):
        a = apps.add_parser(action)
        a.add_argument('id')
        a.add_argument('username')
    origins = apps.add_parser('origin').add_subparsers(dest='operation', required=True)
    for action in ('add', 'remove'):
        a = origins.add_parser(action)
        a.add_argument('id')
        a.add_argument('origin')
    users = sub.add_parser('user').add_subparsers(dest='action', required=True)
    users.add_parser('list')
    for action in ('invite', 'remove'):
        users.add_parser(action).add_argument('username')
    return p


def validated_origin(value):
    from src.config import settings
    from src.web.sso import origin
    parsed = urlsplit(value)
    normalized = origin(value)
    if (parsed.path or parsed.query or parsed.fragment or '\\' in value
            or (parsed.scheme != 'https' and parsed.hostname not in ('localhost', '127.0.0.1'))):
        raise ValueError('Origin must be https://host[:port] (http allowed only for localhost/127.0.0.1)')
    host = parsed.hostname.lower()
    domain = settings.SSO_COOKIE_DOMAIN
    if host != urlsplit(settings.PUBLIC_URL).hostname and not (domain and (host == domain or host.endswith('.' + domain))):
        raise ValueError('Origin cannot receive the cookie; configure SSO_COOKIE_DOMAIN to a shared parent domain')
    return normalized


def validated_redirect(value):
    parsed = urlsplit(value)
    if (not parsed.hostname or parsed.username or parsed.password or parsed.fragment
            or "#" in value or "\\" in value or any(ord(c) <= 32 or ord(c) == 127 for c in value)
            or parsed.scheme not in ('https', 'http')
            or (parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1'))):
        raise ValueError('Redirect URI must be absolute HTTPS (HTTP only on localhost/127.0.0.1), without fragment or credentials')
    parsed.port
    return value


async def run(args):
    import aiosqlite
    from src.database.sqlite import SQLiteDatabase
    from src.services.token_service import TokenService
    if args.group == 'user' and args.action == 'invite':
        from src.web.schemas import RegisterRequest
        args.username = RegisterRequest(username=args.username).username
    db = SQLiteDatabase()
    await db.init_db()
    if args.group == 'user':
        if args.action == 'invite':
            try:
                user = await db.create_user(args.username)
            except aiosqlite.IntegrityError:
                raise ValueError('Username already exists') from None
            tokens = TokenService(db)
            print(tokens.create_telegram_link(await tokens.generate_registration_token(user.id)))
            return
        async with aiosqlite.connect(db.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            if args.action == 'list':
                rows = await (await conn.execute('SELECT username,telegram_id,public_id FROM users ORDER BY username')).fetchall()
                print(json.dumps([dict(r) for r in rows], ensure_ascii=False))
                return
            await conn.execute('BEGIN IMMEDIATE')
            user = await (await conn.execute('SELECT id FROM users WHERE username=?', (args.username,))).fetchone()
            if not user:
                raise ValueError('Unknown username')
            for table in ('oidc_tokens', 'oidc_codes', 'app_users', 'sessions', 'registration_tokens', 'login_requests'):
                await conn.execute(f'DELETE FROM {table} WHERE user_id=?', (user['id'],))
            await conn.execute('DELETE FROM users WHERE id=?', (user['id'],))
            await conn.commit()
        print('User removed')
        return
    secret = None
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute('BEGIN IMMEDIATE')
        if args.action == 'list':
            rows = await (await conn.execute('SELECT id,name,access_policy,origins FROM apps ORDER BY id')).fetchall()
            print(json.dumps([dict(r) for r in rows], ensure_ascii=False))
            return
        if args.action == 'add':
            if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,39}', args.id):
                raise ValueError('App id must match ^[a-z0-9][a-z0-9-]{0,39}$')
            uris = [validated_redirect(uri) for uri in args.redirect_uri]
            secret = secrets.token_urlsafe(32) if uris else None
            await conn.execute('INSERT INTO apps(id,name,access_policy,created_at,redirect_uris,secret_hash) VALUES (?,?,?,?,?,?)', (args.id, args.name, args.policy, time.time(), json.dumps(uris), hashlib.sha256(secret.encode()).hexdigest() if secret else None))
        else:
            app = await (await conn.execute('SELECT * FROM apps WHERE id=?', (args.id,))).fetchone()
            if not app:
                raise ValueError('Unknown app')
            if args.action == 'show':
                data = dict(app)
                data.pop('secret_hash')
                data['allowlist'] = [r[0] for r in await (await conn.execute('SELECT u.username FROM app_users a JOIN users u ON u.id=a.user_id WHERE a.app_id=? ORDER BY u.username', (args.id,))).fetchall()]
                print(json.dumps(data, ensure_ascii=False))
                return
            if args.action == 'remove':
                for table in ('oidc_tokens', 'oidc_codes', 'app_users'):
                    await conn.execute(f'DELETE FROM {table} WHERE app_id=?', (args.id,))
                await conn.execute('DELETE FROM apps WHERE id=?', (args.id,))
            elif args.action in ('rotate-secret', 'redirect-uri'):
                if args.action == 'redirect-uri':
                    value = validated_redirect(args.uri)
                    uris = json.loads(app['redirect_uris'])
                    if args.operation == 'add' and value not in uris:
                        uris.append(value)
                    if args.operation == 'remove' and value in uris:
                        uris.remove(value)
                    await conn.execute('UPDATE apps SET redirect_uris=? WHERE id=?', (json.dumps(uris), args.id))
                if args.action == 'rotate-secret' or (args.operation == 'add' and not app['secret_hash']):
                    secret = secrets.token_urlsafe(32)
                    await conn.execute('UPDATE apps SET secret_hash=? WHERE id=?', (hashlib.sha256(secret.encode()).hexdigest(), args.id))
            elif args.action == 'policy':
                await conn.execute('UPDATE apps SET access_policy=? WHERE id=?', (args.policy, args.id))
            elif args.action in ('allow', 'disallow'):
                user = await (await conn.execute('SELECT id,telegram_id FROM users WHERE username=?', (args.username,))).fetchone()
                if not user:
                    raise ValueError('Unknown username')
                if args.action == 'allow':
                    if user['telegram_id'] is None:
                        raise ValueError('user exists but has not linked Telegram yet')
                    await conn.execute('INSERT OR IGNORE INTO app_users VALUES (?,?)', (args.id, user[0]))
                else:
                    await conn.execute('DELETE FROM app_users WHERE app_id=? AND user_id=?', (args.id, user[0]))
            elif args.action == 'origin':
                from src.web.sso import origin
                value = validated_origin(args.origin) if args.operation == 'add' else origin(args.origin)
                origins = json.loads(app['origins'])
                if args.operation == 'add' and value not in origins:
                    origins.append(value)
                if args.operation == 'remove' and value in origins:
                    origins.remove(value)
                await conn.execute('UPDATE apps SET origins=? WHERE id=?', (json.dumps(origins), args.id))
        await conn.commit()
    print('Client secret: ' + secret if secret else 'OK')


def main():
    args = parser().parse_args()
    if args.group == 'gen-secrets':
        print('SECRET_KEY=' + secrets.token_urlsafe(32))
        print('INTERNAL_API_KEY=' + secrets.token_urlsafe(32))
        return
    try:
        asyncio.run(run(args))
    except Exception as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
