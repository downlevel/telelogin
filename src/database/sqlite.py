"""
SQLite database implementation
"""
import hashlib
import logging
import secrets
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from src.config import settings
from src.database.base import DatabaseInterface
from src.models.user import User


class SQLiteDatabase(DatabaseInterface):
    """SQLite implementation of database interface"""

    def __init__(self, db_path: str = None):
        if db_path is None:
            if not settings.DB_URL.startswith("sqlite:///"):
                raise ValueError("DB_URL must use sqlite:///")
            db_path = settings.DB_URL[len("sqlite:///"):]
            if not db_path or db_path == ":memory:" or "?" in db_path:
                raise ValueError("DB_URL must identify a SQLite file")
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    async def ping(self):
        """Verify that the application schema is accessible."""
        async with aiosqlite.connect(self.db_path) as db:
            await (await db.execute("SELECT 1 FROM users LIMIT 1")).fetchone()

    async def init_db(self):
        """Initialize database tables"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    telegram_id INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    linked_at DATETIME
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS login_requests (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    status TEXT DEFAULT 'pending',
                    session_token TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """)

            await db.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
            # Serialize migrations when API and bot start together.
            await db.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in await (await db.execute("PRAGMA table_info(login_requests)")).fetchall()}
            for name, kind in (("expires_at", "REAL"), ("token_delivered_at", "REAL"), ("ip", "TEXT"), ("user_agent", "TEXT"), ("verification_code", "INTEGER"), ("refresh_token", "TEXT")):
                if name not in columns:
                    await db.execute(f"ALTER TABLE login_requests ADD COLUMN {name} {kind}")
            await db.execute("UPDATE login_requests SET expires_at = COALESCE(strftime('%s', created_at), ?) + ? WHERE expires_at IS NULL", (time.time(), settings.LOGIN_REQUEST_TTL_SECONDS))
            rows = await (await db.execute("SELECT id, telegram_id FROM users WHERE telegram_id IS NOT NULL ORDER BY linked_at IS NULL, linked_at, id")).fetchall()
            seen = set()
            for user_id, telegram_id in rows:
                if telegram_id in seen:
                    await db.execute("UPDATE users SET telegram_id=NULL, linked_at=NULL WHERE id=?", (user_id,))
                    logging.getLogger(__name__).warning("Unlinked duplicate Telegram account for user %s", user_id)
                seen.add(telegram_id)
            await db.execute("DROP INDEX IF EXISTS idx_users_telegram_id")
            await db.execute("CREATE UNIQUE INDEX idx_users_telegram_id ON users(telegram_id) WHERE telegram_id IS NOT NULL")
            await db.execute("CREATE TABLE IF NOT EXISTS registration_tokens (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires_at REAL NOT NULL, used_at REAL)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_login_requests_user_id ON login_requests(user_id)")

            await db.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), refresh_hash TEXT UNIQUE NOT NULL, previous_refresh_hash TEXT, created_at REAL NOT NULL, expires_at REAL NOT NULL, last_used_at REAL, revoked_at REAL, ip TEXT, user_agent TEXT)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")
            await db.commit()

    async def create_user(self, username: str) -> User:
        """Create a new user"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "INSERT INTO users (username) VALUES (?)",
                (username,)
            )
            await db.commit()
            user_id = cursor.lastrowid

            return User(id=user_id, username=username)

    async def get_user_by_username(self, username: str) -> User | None:
        """Get user by username"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM users WHERE username = ?",
                (username,)
            )
            row = await cursor.fetchone()

            if row:
                return User(**dict(row))
            return None

    async def get_user_by_telegram_id(self, telegram_id: int) -> User | None:
        """Get user by Telegram ID"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM users WHERE telegram_id = ?",
                (telegram_id,)
            )
            row = await cursor.fetchone()

            if row:
                return User(**dict(row))
            return None

    async def create_login_request(self, user_id: int) -> str:
        """Create a login request and return login_id"""
        login_id = str(uuid.uuid4())
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO login_requests (id, user_id, expires_at) VALUES (?, ?, ?)",
                (login_id, user_id, time.time() + settings.LOGIN_REQUEST_TTL_SECONDS)
            )
            await db.commit()
            return login_id

    async def get_login_request(self, login_id: str) -> dict | None:
        """Get login request by ID"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM login_requests WHERE id = ?",
                (login_id,)
            )
            row = await cursor.fetchone()

            if row:
                return dict(row)
            return None

    async def update_login_status(self, login_id, status, session_token=None, telegram_id=None):
        if status not in ("approved", "denied") or telegram_id is None:
            return False
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE login_requests SET status='expired' WHERE id=? AND status='pending' AND expires_at <= ?", (login_id, time.time()))
            cursor = await db.execute(
                "UPDATE login_requests SET status=?, session_token=? WHERE id=? AND status='pending' AND expires_at > ? AND user_id IN (SELECT id FROM users WHERE telegram_id=?)",
                (status, session_token, login_id, time.time(), telegram_id),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def take_login_status(self, login_id):
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            await db.execute("UPDATE login_requests SET status='expired' WHERE id=? AND status='pending' AND expires_at <= ?", (login_id, time.time()))
            row = await (await db.execute("SELECT * FROM login_requests WHERE id=?", (login_id,))).fetchone()
            if row is None:
                await db.commit()
                return None
            result = {"status": row["status"]}
            if row["status"] == "approved" and row["session_token"]:
                result["session_token"] = row["session_token"]
                result["refresh_token"] = row["refresh_token"]
                cursor = await db.execute("UPDATE login_requests SET session_token=NULL, refresh_token=NULL, token_delivered_at=? WHERE id=? AND status='approved' AND session_token IS NOT NULL", (time.time(), login_id))
                assert cursor.rowcount == 1
            await db.commit()
            return result

    async def save_registration_token(self, token, user_id, ttl):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("INSERT INTO registration_tokens VALUES (?, ?, ?, NULL)", (hashlib.sha256(token.encode()).hexdigest(), user_id, time.time() + ttl))
            await db.commit()

    async def consume_and_link(self, token, telegram_id):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            cursor = await db.execute("UPDATE registration_tokens SET used_at=? WHERE token_hash=? AND used_at IS NULL AND expires_at > ? RETURNING user_id", (time.time(), token_hash, time.time()))
            row = await cursor.fetchone()
            await cursor.close()
            if row is None:
                raise ValueError("Invalid or expired token")
            try:
                cursor = await db.execute("UPDATE users SET telegram_id=?, linked_at=? WHERE id=?", (telegram_id, datetime.now(timezone.utc).isoformat(), row[0]))
                if cursor.rowcount != 1:
                    raise ValueError("Invalid user")
                await db.commit()
            except aiosqlite.IntegrityError:
                await db.rollback()
                raise ValueError("Telegram already linked to another account") from None

    async def start_request(self, username, ip, user_agent):
        code = secrets.randbelow(90) + 10
        login_id = str(uuid.uuid4())
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            user = await (await db.execute("SELECT * FROM users WHERE username=? AND telegram_id IS NOT NULL", (username,))).fetchone()
            await db.execute("INSERT INTO login_requests (id,user_id,expires_at,verification_code,ip,user_agent) VALUES (?,?,?,?,?,?)", (login_id, user['id'] if user else 0, time.time()+settings.LOGIN_REQUEST_TTL_SECONDS, code, ip if user else None, user_agent[:200] if user else None))
            await db.commit()
        return login_id, code, dict(user) if user else None

    @staticmethod
    def access(user, sid):
        from src.utils.crypto import create_access_token
        return create_access_token({'sub': user['username'], 'user_id': user['id'], 'sid': sid, 'jti': str(uuid.uuid4()), 'type': 'access', 'iat': int(time.time())})

    async def approve(self, login_id, telegram_id, code):
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            row = await (await db.execute("SELECT l.*, u.username FROM login_requests l JOIN users u ON u.id=l.user_id WHERE l.id=? AND u.telegram_id=? AND l.status='pending' AND l.expires_at>?", (login_id, telegram_id, time.time()))).fetchone()
            if not row:
                return None
            if row['verification_code'] != code:
                await db.execute("UPDATE login_requests SET status='denied' WHERE id=?", (login_id,))
                await db.commit()
                return 'wrong'
            sid, refresh = str(uuid.uuid4()), secrets.token_urlsafe(32)
            token = self.access({'id': row['user_id'], 'username': row['username']}, sid)
            now = time.time()
            await db.execute("INSERT INTO sessions (id,user_id,refresh_hash,created_at,expires_at,ip,user_agent) VALUES (?,?,?,?,?,?,?)", (sid,row['user_id'],hashlib.sha256(refresh.encode()).hexdigest(),now,now+settings.REFRESH_TOKEN_TTL_DAYS*86400,row['ip'],row['user_agent']))
            await db.execute("UPDATE login_requests SET status='approved',session_token=?,refresh_token=? WHERE id=?", (token,refresh,login_id))
            await db.commit()
            return {'status': 'authenticated'}

    async def session(self, payload, allow_revoked=False, revoke=None):
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if revoke:
                # Read-only validation (/auth/me) needs no write lock: the single SELECT is atomic
                await db.execute("BEGIN IMMEDIATE")
            row = await (await db.execute("SELECT s.*,u.username FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.id=? AND s.user_id=? AND s.expires_at>?", (payload.get('sid'),payload.get('user_id'),time.time()))).fetchone()
            if not row or (row['revoked_at'] is not None and not allow_revoked):
                return None
            if revoke:
                await db.execute("UPDATE sessions SET revoked_at=COALESCE(revoked_at,?) WHERE " + ('user_id=?' if revoke == 'all' else 'id=?'), (time.time(), row['user_id'] if revoke == 'all' else row['id']))
            await db.commit()
            return {'user_id': row['user_id'], 'username': row['username'], 'session_id': row['id'], 'expires_at': payload['exp']}

    async def refresh(self, token):
        digest = hashlib.sha256(token.encode()).hexdigest()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            row = await (await db.execute("SELECT s.*,u.username FROM sessions s JOIN users u ON u.id=s.user_id WHERE (refresh_hash=? OR previous_refresh_hash=?) AND revoked_at IS NULL AND expires_at>?", (digest,digest,time.time()))).fetchone()
            if not row:
                return None
            if row['previous_refresh_hash'] == digest:
                await db.execute("UPDATE sessions SET revoked_at=? WHERE id=?", (time.time(),row['id']))
                await db.commit()
                return None
            refresh = secrets.token_urlsafe(32)
            await db.execute("UPDATE sessions SET previous_refresh_hash=refresh_hash,refresh_hash=?,last_used_at=? WHERE id=?", (hashlib.sha256(refresh.encode()).hexdigest(),time.time(),row['id']))
            token = self.access({'id':row['user_id'],'username':row['username']},row['id'])
            await db.commit()
            return {'session_token':token,'refresh_token':refresh}

    async def account_action(self, telegram_id, action, session_id=None):
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            user = await (await db.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,))).fetchone()
            if not user:
                return None
            uid, now = user['id'], time.time()
            sessions = [dict(r) for r in await (await db.execute("SELECT id,created_at,last_used_at,ip,user_agent FROM sessions WHERE user_id=? AND revoked_at IS NULL AND expires_at>? ORDER BY COALESCE(last_used_at,created_at) DESC, created_at DESC, id", (uid,now))).fetchall()]
            result = {'status':'ok'}
            if action == 'account':
                recent = [dict(r) for r in await (await db.execute("SELECT created_at,CASE WHEN status='pending' AND expires_at<=? THEN 'expired' ELSE status END AS status,ip,user_agent FROM login_requests WHERE user_id=? ORDER BY created_at DESC, rowid DESC LIMIT 5", (now,uid))).fetchall()]
                result = {'username':user['username'],'linked_at':user['linked_at'],'active_sessions':len(sessions),'recent_logins':recent}
            elif action == 'sessions':
                result = {'sessions':sessions}
            elif action == 'revoke':
                if session_id is not None and not await (await db.execute("SELECT id FROM sessions WHERE id=? AND user_id=?", (session_id,uid))).fetchone():
                    return None
                await db.execute("UPDATE sessions SET revoked_at=COALESCE(revoked_at,?) WHERE user_id=?" + (' AND id=?' if session_id is not None else ''), (now,uid,session_id) if session_id is not None else (now,uid))
            elif action == 'delete':
                for table in ('sessions','registration_tokens','login_requests'):
                    await db.execute(f"DELETE FROM {table} WHERE user_id=?", (uid,))
                await db.execute("DELETE FROM users WHERE id=?", (uid,))
            await db.commit()
            return result

    async def purge_old(self, retention_seconds):
        cutoff = time.time() - retention_seconds
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute("DELETE FROM login_requests WHERE CAST(strftime('%s',created_at) AS REAL)<?", (cutoff,))
            await db.execute("DELETE FROM sessions WHERE expires_at<? OR revoked_at<?", (cutoff,cutoff))
            await db.execute("UPDATE sessions SET ip=NULL,user_agent=NULL WHERE created_at<?", (cutoff,))
            await db.commit()
