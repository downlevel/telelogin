"""
SQLite database implementation
"""
import aiosqlite
import uuid
from datetime import datetime
from typing import Optional, List
from src.database.base import DatabaseInterface
from src.models.user import User
from src.config import settings

class SQLiteDatabase(DatabaseInterface):
    """SQLite implementation of database interface"""
    
    def __init__(self, db_path: str = "db.sqlite3"):
        self.db_path = db_path
    
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
            await db.execute("CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_login_requests_user_id ON login_requests(user_id)")
            
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
    
    async def get_user_by_username(self, username: str) -> Optional[User]:
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
    
    async def get_user_by_telegram_id(self, telegram_id: int) -> Optional[User]:
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
    
    async def link_telegram_id(self, user_id: int, telegram_id: int) -> bool:
        """Link Telegram ID to user"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE users SET telegram_id = ?, linked_at = ? WHERE id = ?",
                (telegram_id, datetime.now(), user_id)
            )
            await db.commit()
            return True
    
    async def create_login_request(self, user_id: int) -> str:
        """Create a login request and return login_id"""
        login_id = str(uuid.uuid4())
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO login_requests (id, user_id) VALUES (?, ?)",
                (login_id, user_id)
            )
            await db.commit()
            return login_id
    
    async def get_login_request(self, login_id: str) -> Optional[dict]:
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
    
    async def update_login_status(self, login_id: str, status: str, session_token: str = None) -> bool:
        """Update login request status and optionally session token"""
        async with aiosqlite.connect(self.db_path) as db:
            if session_token:
                await db.execute(
                    "UPDATE login_requests SET status = ?, session_token = ? WHERE id = ?",
                    (status, session_token, login_id)
                )
            else:
                await db.execute(
                    "UPDATE login_requests SET status = ? WHERE id = ?",
                    (status, login_id)
                )
            await db.commit()
            return True
