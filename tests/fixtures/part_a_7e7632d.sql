-- Schema captured from SQLiteDatabase.init_db at 7e7632d (Part A).
CREATE TABLE app_users (app_id TEXT NOT NULL REFERENCES apps(id), user_id INTEGER NOT NULL REFERENCES users(id), PRIMARY KEY(app_id,user_id));

CREATE TABLE apps (id TEXT PRIMARY KEY, name TEXT NOT NULL, access_policy TEXT NOT NULL DEFAULT 'allowlist' CHECK(access_policy IN ('allowlist','all')), secret_hash TEXT, redirect_uris TEXT NOT NULL DEFAULT '[]', origins TEXT NOT NULL DEFAULT '[]', created_at REAL NOT NULL);

CREATE TABLE login_requests (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    status TEXT DEFAULT 'pending',
                    session_token TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP, expires_at REAL, token_delivered_at REAL, ip TEXT, user_agent TEXT, verification_code INTEGER, refresh_token TEXT, purpose TEXT NOT NULL DEFAULT 'api', app_id TEXT, return_to TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                );

CREATE TABLE registration_tokens (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires_at REAL NOT NULL, used_at REAL);

CREATE TABLE sessions (id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), refresh_hash TEXT UNIQUE NOT NULL, previous_refresh_hash TEXT, created_at REAL NOT NULL, expires_at REAL NOT NULL, last_used_at REAL, revoked_at REAL, ip TEXT, user_agent TEXT, kind TEXT NOT NULL DEFAULT 'api');

CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    telegram_id INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    linked_at DATETIME
                , public_id TEXT);

CREATE INDEX idx_login_requests_user_id ON login_requests(user_id);

CREATE INDEX idx_sessions_user ON sessions(user_id);

CREATE UNIQUE INDEX idx_users_public_id ON users(public_id);

CREATE UNIQUE INDEX idx_users_telegram_id ON users(telegram_id) WHERE telegram_id IS NOT NULL;

CREATE INDEX idx_users_username ON users(username);
