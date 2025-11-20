-- Database schema for TeleLogin
-- SQLite

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    telegram_id INTEGER,  -- Use BIGINT for PostgreSQL
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    linked_at TIMESTAMP
);

-- Login requests table
CREATE TABLE IF NOT EXISTS login_requests (
    id TEXT PRIMARY KEY,  -- UUID format
    user_id INTEGER NOT NULL,
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'denied', 'expired')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Registration tokens table (optional, can be stored in Redis)
CREATE TABLE IF NOT EXISTS registration_tokens (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    used BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);
CREATE INDEX IF NOT EXISTS idx_login_requests_user_id ON login_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_login_requests_status ON login_requests(status);
CREATE INDEX IF NOT EXISTS idx_registration_tokens_user_id ON registration_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_registration_tokens_expires_at ON registration_tokens(expires_at);
