# Database Structure

## SQLite Schema

### Table `users`
| Field        | Type      | Notes                                  |
|--------------|-----------|----------------------------------------|
| id           | INTEGER   | Primary Key (auto-increment)           |
| username     | TEXT      | Unique, local application username     |
| telegram_id  | INTEGER   | Telegram user ID (nullable until linked)|
| created_at   | DATETIME  | User registration timestamp            |
| linked_at    | DATETIME  | Telegram account link timestamp        |

**Indexes:**
- `idx_users_username` on `username`
- `idx_users_telegram_id` on `telegram_id`

---

### Table `login_requests`
| Field         | Type      | Notes                                    |
|---------------|-----------|------------------------------------------|
| id            | TEXT      | Primary Key (UUID format)                |
| user_id       | INTEGER   | Foreign Key → users.id                   |
| status        | TEXT      | pending / approved / denied / expired    |
| session_token | TEXT      | JWT token (stored when approved)         |
| created_at    | DATETIME  | Login request creation timestamp         |

**Indexes:**
- `idx_login_requests_user_id` on `user_id`

**Status values:**
- `pending` - Waiting for user confirmation via Telegram
- `approved` - User confirmed login, session token generated
- `denied` - User explicitly denied the login request
- `expired` - Login request timed out (not yet implemented)

---

## Database Initialization

The database is automatically initialized on application startup via:
- **API service**: `src/app.py` lifespan event
- **Bot service**: `src/bot.py` start method

Tables and indexes are created if they don't exist using SQLite's `CREATE TABLE IF NOT EXISTS` syntax.

---

## Data Flow

### Registration Flow
1. User registers → `users` table entry created with `username`
2. User clicks Telegram link → Bot calls `/auth/link-telegram`
3. Backend updates `telegram_id` and `linked_at` in `users` table

### Login Flow
1. User starts login → `login_requests` entry created with status `pending`
2. User confirms in Telegram → Bot calls `/auth/confirm-login`
3. Backend updates `status` to `approved` and stores `session_token`
4. Client polls `/status/{login_id}` and retrieves the token