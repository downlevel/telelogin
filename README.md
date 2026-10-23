# TeleLogin

TeleLogin provides Telegram-confirmed login through a self-hosted bot. Protect apps with
forward auth through nginx, Traefik or Caddy, connect standard clients with OpenID Connect,
or build a custom UI with the raw API. Shared browser sessions and per-app access policies
let connected apps reuse one Telegram confirmation. Python 3.11+.

| I want to... | Read |
| --- | --- |
| Install the TeleLogin server | [Quick start](#quick-start) below |
| Protect an app or connect it to TeleLogin | **[Integration guide](docs/INTEGRATION.md)**: which mode to choose, proxy examples, OIDC |
| Manage users and apps | [Operator CLI](docs/INTEGRATION.md#operator-cli) |
| Build a custom login UI | [API](#api) and the [JavaScript client](examples/js_client/) |
| Upgrade from 1.x | [Upgrading from 1.x](#upgrading-from-1x) |

## Quick start

Run these commands from the root of this checkout with Docker Compose v2 installed.
They install the server; connecting your app is covered in the
[integration guide](docs/INTEGRATION.md).

1. Create a Telegram bot with **@BotFather** and dedicate it to TeleLogin: TeleLogin polls it
   for updates, so do not reuse a bot that another program reads. Save its token and
   username (without `@`).
2. Generate the two server secrets:

   ```bash
   docker run --rm ghcr.io/downlevel/telelogin:2.0.0 python -m src.admin gen-secrets
   cp deploy/.env.example deploy/.env
   ```

   Edit `deploy/.env`: fill `BOT_TOKEN`, `BOT_USERNAME`, `SECRET_KEY` and
   `INTERNAL_API_KEY` with your values. Set `PUBLIC_URL` to your external HTTPS URL,
   for example `https://auth.example.com` or `https://example.com/telelogin`.
   Keep `SSO_COOKIE_SECURE=true`. For sibling apps, set `SSO_COOKIE_DOMAIN=example.com`
   only if every subdomain is trusted. The domain must match your own deployment.
3. Start the services:

   ```bash
   docker compose -f deploy/docker-compose.yml up -d
   ```

   Configure your HTTPS proxy using the matching [integration example](docs/INTEGRATION.md).
   The API listens on host loopback port 8000; a Docker proxy instead needs a shared private
   network and no published API port (see the guide). Proxy the configured public URL to
   the API, stripping any path prefix, and block internal endpoints.
4. Invite yourself (works with both open and closed registration):

   ```bash
   docker compose -f deploy/docker-compose.yml exec --user 10001 api python -m src.admin user invite alice
   ```

   Admin commands run as the application user (`--user 10001`) so that SQLite files in the
   data volume stay owned by it. The hosted `/login` page signs in existing users; it has no registration control.
   The command sends no Telegram message: it prints a single-use `https://t.me/...` link,
   valid for 30 minutes. Open it in Telegram and press **Start** to link your account.
   `alice` is your TeleLogin username, used on the login page; it need not match your Telegram
   username. Replace it consistently in these commands. `user list` shows a numeric
   `telegram_id` once linked; if the link expired, run `user remove alice` and invite again.
5. Register and authorize the first app:

   ```bash
   docker compose -f deploy/docker-compose.yml exec --user 10001 api python -m src.admin app add myapp --name "My App"
   docker compose -f deploy/docker-compose.yml exec --user 10001 api python -m src.admin app allow myapp alice
   ```

   For a sibling app, register its actual origin too:

   ```bash
   docker compose -f deploy/docker-compose.yml exec --user 10001 api python -m src.admin app origin add myapp https://app.example.com
   ```

6. Paste the nginx, Traefik or Caddy protection snippet from
   [the integration guide](docs/INTEGRATION.md#forward-auth), using app id `myapp` and your actual
   hostnames/upstream. Host proxy → `127.0.0.1:8000` (replace `8000` with `API_PORT`); proxy in Docker → `telelogin:8000` after joining the TeleLogin Compose network (`deploy_telelogin_network` by default).
   For Docker, start with the [port-removal override and network setup](docs/INTEGRATION.md#docker-proxy-networking):

   ```bash
   docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.docker-proxy.yml up -d
   ```

   Keep the app reachable only through that proxy. Visit the app,
   sign in and select the displayed number in Telegram.

For an optional OIDC app, use `app add` with `--redirect-uri` and configure the printed
client secret, discovery URL and `openid profile` scopes as described in
[OpenID Connect](docs/INTEGRATION.md#openid-connect).

## Upgrading from 1.x

Read the [breaking changes and upgrade steps](CHANGELOG.md#upgrading-from-1x) before
starting 2.0.0, especially the existing volume mapping and proxy settings.

| Browser/SSO setting | Default | Purpose |
| --- | --- | --- |
| `PUBLIC_URL` | `http://localhost:8000` | External base URL, including any proxy-stripped prefix |
| `SSO_COOKIE_NAME` | `tl_sso` | Browser cookie name |
| `SSO_COOKIE_SECURE` | `true` | Set false only for plain HTTP local development |
| `SSO_COOKIE_DOMAIN` | empty | Host-only; set a validated trusted parent domain for sibling apps |
| `REGISTRATION_MODE` | `open` | `closed` requires CLI user invitations |

| Browser endpoint | Method | Purpose |
| --- | --- | --- |
| `/` | GET | Account page with sign-in/logout |
| `/login?app=ID&rd=URL` | GET | Hosted Telegram login |
| `/sso/start` | POST JSON | Begin browser login (username, optional app and rd) |
| `/sso/complete` | POST JSON | Poll login_id; deliver browser cookie once |
| `/sso/verify` | GET | Proxy forward-auth; app header/query, optional redirect=1 |
| `/logout?app=ID&rd=URL` | GET | Logout confirmation |
| `/sso/logout` | POST JSON/form | Revoke browser session, clear cookie, redirect |


## Features

- OpenID Connect discovery, RS256 ID tokens, opaque access tokens, and shared browser SSO.
- Telegram deep-link registration, number matching and Deny login buttons.
- SQLite persistence with atomic registration linking and login transitions.
- Expiring registration tokens and login requests, with one-time access/refresh token delivery.
- Session rotation and revocation, plus account management from Telegram.
- Browser login page, JavaScript client and cURL integration examples.
- Protected internal endpoints, configurable rate limits and proxy trust.
- Docker deployment with shared storage, automatic permission migration and healthchecks.

## Project Structure

```text
telelogin/
├── src/
│   ├── app.py                    # FastAPI application and lifespan
│   ├── admin.py                  # Operator CLI
│   ├── bot.py                    # Telegram bot and notification server
│   ├── config.py                 # Validated environment settings
│   ├── database/                 # Schema, migrations and atomic operations
│   ├── models/                   # User model
│   ├── services/                 # Authentication, registration and user operations
│   ├── utils/                    # API token signing and verification
│   └── web/
│       ├── routes.py             # Raw API
│       ├── sso.py                # Browser sessions and forward auth
│       ├── oidc.py               # OpenID Connect provider
│       ├── dependencies.py       # Application-scoped providers
│       ├── schemas.py            # Request/response validation
│       ├── security.py           # Internal key checks and rate limiter
│       └── templates/index.html  # Hosted login
├── deploy/
│   ├── docker-compose.yml        # Release images
│   ├── docker-compose.docker-proxy.yml # Remove published port for Docker proxies
│   └── .env.example              # Release configuration template
├── docker/                       # Development Compose, Dockerfile and entrypoint
├── docs/INTEGRATION.md            # Deployment and app integration guide
├── examples/
│   ├── nginx/                    # Forward auth configurations
│   ├── traefik/                  # Dynamic configuration and labels
│   ├── caddy/                    # Forward auth Caddyfiles
│   ├── oidc_fastapi/             # Authlib client
│   ├── js_client/                # Raw API JavaScript client and demo
│   └── curl_examples.md
├── tests/                        # Unit/integration tests and e2e/ proxy harness
├── .github/workflows/            # CI and tag-only image releases
├── .env.example                  # Local development configuration
├── .gitattributes
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
├── CHANGELOG.md
├── SECURITY.md
├── CONTRIBUTING.md
├── README.md
└── LICENSE
```

## Setup

Install `requirements.txt` (and `requirements-dev.txt` for tests) in a virtual environment.
For local development, copy `.env.example` to `.env`, configure it, then run
`uvicorn src.app:app` and `python -m src.bot`. The local template already points
API_BASE_URL and BOT_NOTIFY_URL to localhost; docker/env.example uses the service names.

For Docker, from the checkout root:

```bash
cp docker/env.example docker/.env
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "import secrets; print(secrets.token_urlsafe(48))"
# Put the two generated values in SECRET_KEY and INTERNAL_API_KEY; configure BOT_TOKEN/BOT_USERNAME.
docker compose -f docker/docker-compose.yml up -d --build
```

The shared volume remains at /app/data. The entrypoint starts as root, automatically
migrates the volume to ownership 10001:10001 whenever any entry is owned by someone else,
then drops privileges. API and bot application processes run as UID 10001. When the
container starts as a non-root user, the entrypoint runs the command directly.

Because the image user is root (needed for the automatic migration), `docker compose exec`
opens a root shell. For maintenance, use `docker compose exec --user 10001 api sh`; check
the application's identity with `docker compose exec api grep Uid /proc/1/status`.

## Configuration

Both templates declare all supported variables. Required secrets must be supplied.

| Variable | Default / purpose |
| --- | --- |
| BOT_TOKEN | Required Telegram token |
| BOT_USERNAME | YourBot, without @ |
| DB_URL | sqlite:///db.sqlite3; Docker sqlite:///data/db.sqlite3 |
| SECRET_KEY | Required, minimum 32 characters; JWT signing |
| INTERNAL_API_KEY | Required, minimum 32 characters; shared API/bot secret |
| ALGORITHM | HS256 |
| ACCESS_TOKEN_EXPIRE_MINUTES | 15; access JWT lifetime |
| REFRESH_TOKEN_TTL_DAYS | 30; fixed session lifetime from creation |
| LOGIN_HISTORY_RETENTION_DAYS | 30; login history and session metadata retention |
| PURGE_INTERVAL_SECONDS | 3600; cleanup interval, also run at startup |
| OIDC_KEY_FILE | data/oidc-signing-key.pem; persistent private RSA signing key |
| OIDC_CODE_TTL_SECONDS | 60; authorization code lifetime |
| OIDC_TOKEN_TTL_SECONDS | 600; access token and ID token lifetime |
| DEBUG | false |
| CORS_ORIGINS | [] (JSON list) |
| LOGIN_REQUEST_TTL_SECONDS | 120 |
| REGISTRATION_TOKEN_TTL_SECONDS | 1800 |
| RATE_LIMIT_WINDOW_SECONDS | 600 |
| RATE_LIMIT_USERNAME | 5 per operation/window |
| RATE_LIMIT_IP | 20 per operation/window |
| API_PORT | 8000; host published port in Compose (internal API stays 8000) |
| API_BASE_URL | http://api:8000 (Docker), http://localhost:8000 (local template); bot calls API |
| BOT_NOTIFY_URL | http://bot:8001/notify-login (Docker), localhost:8001 (local template); API calls bot |
| FORWARDED_ALLOW_IPS | Trusted proxy addresses. 127.0.0.1 when running uvicorn directly; the Docker Compose default is `*` because the port is published on 127.0.0.1 only |

## Flow Overview

### Registration

1. A client posts a username to `/register` and receives a Telegram deep link.
2. The API persists a hash of the random registration token with its expiry.
3. The user opens the link and presses START in the bot.
4. The bot sends the token and the sender's Telegram ID to protected `/auth/link-telegram`.
5. The API consumes the token and links the account in one transaction. A failed
   link leaves the token valid; a Telegram ID can belong to only one account.

### Login

1. The client posts the username to `/auth/start-login` and receives a pending login ID and a two-digit `verification_code`.
   Display the code prominently; selecting a wrong code in Telegram denies the request.
2. For linked users the API schedules a Telegram notification after sending the response.
   Missing or unlinked users receive a dummy request that can only expire.
3. The owner chooses the browser code or Deny. The bot calls the protected confirm or deny
   endpoint with the sender's Telegram ID (and code for confirmation). Only pending, unexpired requests can change.
4. The client polls `POST /auth/status` sequentially with `{"login_id":"..."}`.
5. Confirmation produces `approved` with access and refresh tokens delivered once across POST and the
   deprecated GET endpoint. Later polls return `approved` without either token.
6. Deny produces `denied`; pending requests past the configured TTL become `expired`.
   Clients stop on a terminal state and enforce their own polling deadline.

## API

| Method and path | Behavior |
| --- | --- |
| GET / | Browser account page (HTML) |
| GET /login | Hosted browser login; optional app and rd parameters |
| GET /health | 200 {"status":"ok","version":"2.0.0"} after a database query |
| POST /register | {"username":"alice"}; returns Telegram registration link; duplicate username 400 |
| GET /.well-known/openid-configuration | OIDC discovery |
| GET /jwks.json | Public RSA signing key |
| GET /authorize | Authorization code flow |
| POST /token | Form-encoded code redemption with client authentication |
| GET, POST /userinfo | Opaque Bearer token identity |
| POST /auth/link-telegram | Internal: {"token":"...","telegram_id":42}; atomic single-use registration link |
| POST /auth/start-login | {"username":"alice"}; always returns pending login_id and verification_code unless rate limited |
| POST /auth/confirm-login | Internal: {"login_id":"...","telegram_id":42,"verification_code":42}; owner approves pending unexpired login; returns only {"status":"authenticated"}, wrong code denies with 400 |
| POST /auth/deny-login | Internal: {"login_id":"...","telegram_id":42}; owner denies pending unexpired login |
| POST /auth/status | {"login_id":"..."}; pending/approved/denied/expired, or 404 |
| GET /status/{login_id} | Deprecated compatibility polling endpoint |
| GET /auth/me | Bearer access token; returns user_id, username, session_id and access expires_at (Unix seconds); invalid/revoked/expired token 401 |
| POST /auth/refresh | {"refresh_token":"..."}; rotates refresh and access tokens; invalid/expired/reused token 401; IP rate limited |
| POST /auth/logout | Bearer access token; revokes current session; idempotent for an already revoked session |
| POST /auth/logout-all | Active Bearer session required; revokes all user sessions; revoked token 401 |
| POST /internal/account | Internal: {"telegram_id":42}; account, active session count and last five real logins; missing account 404 |
| POST /internal/sessions | Internal: {"telegram_id":42}; active sessions with id, creation/last use, IP and user-agent |
| POST /internal/sessions/revoke | Internal: {"telegram_id":42,"session_id":"UUID"}; null means all; invalid UUID 422, unowned session 404 |
| POST /internal/account/delete | Internal: {"telegram_id":42}; atomically deletes account and associated rows; missing account 404 |

Internal endpoints require X-Internal-Key; missing/invalid keys return 401. The bot's
POST /notify-login requires the same key. Bot GET /health returns 200 only while its
Telegram application is running. API and bot healthchecks are defined separately in Compose.
Poll sequentially every two seconds, stop on a terminal status and enforce a timeout.
An approved status includes the original access and refresh tokens only once across both status endpoints.
See examples/curl_examples.md and examples/js_client/telelogin.js.

Tokens issued before this upgrade lack a session ID and are rejected: log in again.

Use `Authorization: Bearer <session_token>` with `GET /auth/me` to obtain
`user_id`, `username`, `session_id`, and the access token's `expires_at` (Unix seconds).
`POST /auth/refresh` accepts `{"refresh_token":"..."}` and returns both replacement
tokens. Refresh tokens are random secrets; only their SHA-256 hashes persist in
sessions. The original login delivery temporarily holds both plaintext tokens until
retrieval. Refresh expiry is fixed at session creation, not extended by rotation.
Reuse of the immediately previous refresh token revokes the session. Two concurrent
refreshes using the same token yield at most one success and revoke that session.
`POST /auth/logout` revokes the current session; `POST /auth/logout-all` revokes all
sessions of the user. Only logout accepts an otherwise valid token for an already revoked
session, making its retries idempotent. Logout-all requires an active session. Every protected request checks the database.

The JavaScript client stores both tokens and offers `me()`, `refresh()`, `logout()`,
and `logoutAll()`. `authenticatedRequest()` refreshes once after a 401 and retries
once. Concurrent requests share a refresh promise; storage is rechecked before
refresh. Where available, Web Locks serializes refreshes across browser tabs using
`telelogin-refresh`. Without Web Locks, simultaneous refreshes across tabs remain
possible and can trigger reuse revocation. `login(username, onStatusChange, onCode)`
exposes the browser code through `onCode`. The `/login` page uses the SSO cookie flow. The raw API and JavaScript client
are the option for storing tokens in the browser.

Telegram commands (private chat only — in groups the bot refuses them, so IPs and
browsers are never shown to other members): `/status` shows the linked account and last five login requests;
`/sessions` shows up to ten most recently used active sessions, reports any omitted
count, and offers individual/all revocation; `/unlink`
asks for confirmation then deletes the account, registration tokens, login history,
and sessions. Its username becomes available again.

## Database Structure

The API initializes SQLite and applies idempotent migrations without replacing existing data.

### users

| Column | Storage / purpose |
| --- | --- |
| id | INTEGER primary key |
| username | TEXT, unique and required |
| telegram_id | INTEGER, nullable until linked |
| created_at | DATETIME, creation timestamp |
| linked_at | UTC ISO 8601 string for new links |

`idx_users_username` indexes usernames. `idx_users_telegram_id` is a unique partial
index on `telegram_id WHERE telegram_id IS NOT NULL`. Migration retains the oldest
known link for each duplicate ID, disconnects the others and logs a warning for each.

### login_requests

| Column | Storage / purpose |
| --- | --- |
| id | TEXT primary key, random UUID |
| user_id | INTEGER, account owner; reserved 0 for dummy requests |
| status | TEXT: pending, approved, denied or expired |
| session_token | TEXT access JWT, cleared after delivery |
| refresh_token | TEXT refresh secret, cleared with the access token after delivery |
| verification_code | INTEGER 10–99, never included in status responses |
| ip | TEXT requesting IP, NULL for dummy requests |
| user_agent | TEXT browser header, truncated to 200 characters; NULL for dummy requests |
| created_at | DATETIME, creation timestamp |
| expires_at | REAL Unix timestamp, login deadline |
| token_delivered_at | REAL Unix timestamp, nullable until delivery |

`idx_login_requests_user_id` indexes the owner. Approval, denial and expiry use
conditional updates. One-time delivery uses a serialized transaction to read the
original token pair and clear both before releasing the lock.

### registration_tokens

| Column | Storage / purpose |
| --- | --- |
| token_hash | TEXT primary key, SHA-256 of the random token |
| user_id | INTEGER, target account |
| expires_at | REAL Unix timestamp |
| used_at | REAL Unix timestamp, NULL until consumed |

The raw token is returned in the registration link and is never stored in this table.
Token consumption and account linking share one transaction and roll back together.

### sessions

| Column | Storage / purpose |
| --- | --- |
| id | TEXT primary key, UUID; access token sid |
| user_id | INTEGER, account owner |
| refresh_hash | TEXT unique, SHA-256 of the current refresh secret |
| previous_refresh_hash | TEXT SHA-256 of the last rotated secret, for reuse detection |
| created_at | REAL Unix timestamp |
| expires_at | REAL Unix timestamp, fixed session deadline |
| last_used_at | REAL Unix timestamp, nullable until refresh |
| revoked_at | REAL Unix timestamp, NULL while not revoked |
| ip | TEXT requesting IP, removed after retention threshold |
| user_agent | TEXT truncated browser header, removed after retention threshold |

An index on user_id supports listing and revocation. Access JWTs include sub,
user_id, sid, jti (UUID), type="access", iat and exp. Only refresh hashes persist
in sessions. User/session operations and account deletion are serialized with
BEGIN IMMEDIATE; dummy requests use user_id=0 and SQLite foreign keys stay disabled.

## Security and deployment

Registration tokens are random, hashed in SQLite, expire and are consumed atomically
with linking. Telegram IDs are unique; approval/denial checks the owner atomically.
Missing and unlinked usernames receive dummy expiring requests. Notifications run after
the response. Registration still reveals duplicate usernames. Keep login IDs and tokens private.
Rate limits are in memory: run one worker; limits are not shared across instances.
Username limits allow an attacker to temporarily lock out a known username.

Terminate HTTPS at a reverse proxy (nginx, Traefik or Caddy). Uvicorn must trust the proxy so
that IP rate limits and the IP shown in Telegram confirmations are the real client address. A
proxy on the host reaches the container through the Docker gateway (e.g. 172.17.0.1), never
from 127.0.0.1, so the Compose default is `FORWARDED_ALLOW_IPS=*`, which is safe only because the
API port is published on 127.0.0.1. If you publish the port on another interface, set the proxy's
exact address instead. When running uvicorn directly on the host, 127.0.0.1 is correct. Restrict
network access to the API and notification service and never use '*' on an externally reachable
API.

Privacy: real linked login requests and sessions record the requesting IP and
user-agent (at most 200 characters; notifications show at most 100). Fictitious
requests store no IP or user-agent. No geolocation is performed. `/unlink` deletes
all account data immediately. `LOGIN_HISTORY_RETENTION_DAYS=30` controls login
history deletion, deletion of sessions closed beyond that period, and removal of
IP/user-agent from older sessions even while those sessions remain active.
`REFRESH_TOKEN_TTL_DAYS=30` controls fixed session lifetime.
`PURGE_INTERVAL_SECONDS=3600` controls periodic retention cleanup, also run at API
startup. Maximum normal deletion delay is the retention threshold plus this interval;
a failed pass is logged and retried at the next interval. These positive settings
are present in both environment templates and Docker Compose.

## Verification

GitHub Actions (`.github/workflows/ci.yml`) runs on every push to main and every pull
request: Ruff, the test suite on Python 3.11 and 3.12 (including the Node client
simulation and a warnings-as-errors pass), development and deploy Compose validation,
the image build and an API smoke test (`/health`, `/auth/me` → 401). A separate e2e job
runs the real nginx, Traefik and Caddy forward-auth checks. Actionlint is a host review
check and is not run in CI.

```bash
.venv/bin/python -m pytest -q && .venv/bin/ruff check src tests && .venv/bin/python -W error::DeprecationWarning -m pytest -q
```

Host verification: build images, check that the main process (`/proc/1/status`) runs
as UID 10001 and API /health, inspect
both service healthchecks and verify writing an upgraded volume. Bot startup and the
real registration/Confirm/Deny flow require a valid Telegram token.

The pytest suite also runs `node tests/client_refresh.cjs` when Node is available;
otherwise that simulation is skipped.

## License

TeleLogin is distributed under the Apache License, Version 2.0. See [LICENSE](LICENSE)
for the full terms.

## OpenID Connect integration

TeleLogin supports confidential OIDC clients with authorization code flow, PKCE S256, RS256 ID
tokens, and shared browser SSO. See [the integration guide](docs/INTEGRATION.md#openid-connect)
and [the Authlib example](examples/oidc_fastapi/app.py).
