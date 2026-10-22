# TeleLogin

Telegram login confirmation using FastAPI, a Telegram bot and SQLite. Python 3.11+.

## Features

- Telegram deep-link registration and Confirm/Deny login buttons.
- SQLite persistence with atomic registration linking and login transitions.
- Expiring registration tokens and login requests, with one-time JWT delivery.
- Browser login page, JavaScript client and cURL integration examples.
- Protected internal endpoints, configurable rate limits and proxy trust.
- Docker deployment with shared storage, automatic permission migration and healthchecks.

## Project Structure

```text
telelogin/
├── src/
│   ├── app.py                    # FastAPI application and lifespan
│   ├── bot.py                    # Telegram bot and notification HTTP server
│   ├── config.py                 # Validated environment settings
│   ├── database/
│   │   ├── base.py               # Database interface
│   │   └── sqlite.py             # Schema, migrations and atomic operations
│   ├── models/user.py            # User model
│   ├── services/
│   │   ├── auth_service.py       # Login and background notifications
│   │   ├── token_service.py      # Persistent registration tokens
│   │   └── user_service.py       # User operations
│   ├── utils/crypto.py           # JWT signing and verification
│   └── web/
│       ├── dependencies.py       # Application-scoped dependency providers
│       ├── routes.py             # Authentication routes
│       ├── schemas.py            # Request/response validation
│       ├── security.py           # Internal key checks and rate limiter
│       └── templates/index.html  # Browser login page
├── tests/
│   ├── conftest.py               # Environment and temporary database fixtures
│   ├── test_security.py          # Phase 1 security regressions
│   └── test_phase2.py            # Architecture and integration checks
├── docker/
│   ├── Dockerfile
│   ├── entrypoint.sh             # Volume ownership migration and privilege drop
│   ├── docker-compose.yml
│   └── env.example
├── examples/
│   ├── curl_examples.md
│   └── js_client/                # JavaScript client and demo
├── .env.example
├── .gitattributes
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
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
| ACCESS_TOKEN_EXPIRE_MINUTES | 30 |
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
| FORWARDED_ALLOW_IPS | 127.0.0.1; trusted proxy addresses |

## Flow Overview

### Registration

1. A client posts a username to `/register` and receives a Telegram deep link.
2. The API persists a hash of the random registration token with its expiry.
3. The user opens the link and presses START in the bot.
4. The bot sends the token and the sender's Telegram ID to protected `/auth/link-telegram`.
5. The API consumes the token and links the account in one transaction. A failed
   link leaves the token valid; a Telegram ID can belong to only one account.

### Login

1. The client posts the username to `/auth/start-login` and receives a pending login ID.
2. For linked users the API schedules a Telegram notification after sending the response.
   Missing or unlinked users receive a dummy request that can only expire.
3. The owner chooses Confirm or Deny. The bot calls the protected confirm or deny
   endpoint with the sender's Telegram ID. Only pending, unexpired requests can change.
4. The client polls `POST /auth/status` sequentially with `{"login_id":"..."}`.
5. Confirmation produces `approved` with a JWT delivered once across POST and the
   deprecated GET endpoint. Later polls return `approved` without the token.
6. Deny produces `denied`; pending requests past the configured TTL become `expired`.
   Clients stop on a terminal state and enforce their own polling deadline.

## API

| Method and path | Behavior |
| --- | --- |
| GET / | JSON service information |
| GET /login | Browser login page |
| GET /health | 200 {"status":"ok"} after a database query |
| POST /register | {"username":"alice"}; returns Telegram registration link; duplicate username 400 |
| POST /auth/link-telegram | Internal: {"token":"...","telegram_id":42}; atomic single-use registration link |
| POST /auth/start-login | {"username":"alice"}; always returns pending login_id unless rate limited |
| POST /auth/confirm-login | Internal: {"login_id":"...","telegram_id":42}; owner approves pending unexpired login |
| POST /auth/deny-login | Internal: same body; owner denies pending unexpired login |
| POST /auth/status | {"login_id":"..."}; pending/approved/denied/expired, or 404 |
| GET /status/{login_id} | Deprecated compatibility polling endpoint |

Internal endpoints require X-Internal-Key; missing/invalid keys return 401. The bot's
POST /notify-login requires the same key. Bot GET /health returns 200 only while its
Telegram application is running. API and bot healthchecks are defined separately in Compose.
Poll sequentially every two seconds, stop on a terminal status and enforce a timeout.
An approved status includes the original JWT only once across both status endpoints.
See examples/curl_examples.md and examples/js_client/telelogin.js.

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
| session_token | TEXT JWT, cleared after delivery |
| created_at | DATETIME, creation timestamp |
| expires_at | REAL Unix timestamp, login deadline |
| token_delivered_at | REAL Unix timestamp, nullable until delivery |

`idx_login_requests_user_id` indexes the owner. Approval, denial and expiry use
conditional updates. One-time delivery uses a serialized transaction to read the
original token and clear it before releasing the lock.

### registration_tokens

| Column | Storage / purpose |
| --- | --- |
| token_hash | TEXT primary key, SHA-256 of the random token |
| user_id | INTEGER, target account |
| expires_at | REAL Unix timestamp |
| used_at | REAL Unix timestamp, NULL until consumed |

The raw token is returned in the registration link and is never stored in this table.
Token consumption and account linking share one transaction and roll back together.

## Security and deployment

Registration tokens are random, hashed in SQLite, expire and are consumed atomically
with linking. Telegram IDs are unique; approval/denial checks the owner atomically.
Missing and unlinked usernames receive dummy expiring requests. Notifications run after
the response. Registration still reveals duplicate usernames. Keep login IDs and tokens private.
Rate limits are in memory: run one worker; limits are not shared across instances.
Username limits allow an attacker to temporarily lock out a known username.

Terminate HTTPS at Caddy or Nginx. Set FORWARDED_ALLOW_IPS to the actual proxy IP(s)
so Uvicorn can use forwarded client addresses for IP limits. The loopback default trusts
only local proxies. Restrict network access to the API and notification service; do not
trust arbitrary forwarded headers or use '*' on an externally reachable API.

## Verification

```bash
.venv/bin/python -m pytest -q && .venv/bin/ruff check src tests && .venv/bin/python -W error::DeprecationWarning -m pytest -q
```

Host verification: build images, check that the main process (`/proc/1/status`) runs
as UID 10001 and API /health, inspect
both service healthchecks and verify writing an upgraded volume. Bot startup and the
real registration/Confirm/Deny flow require a valid Telegram token.

## License

TeleLogin is distributed under the Apache License, Version 2.0. See [LICENSE](LICENSE)
for the full terms.
