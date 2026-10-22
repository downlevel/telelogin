"""Persistent registration tokens; linking and consumption share a transaction."""
import secrets

from src.config import settings
from src.database.sqlite import SQLiteDatabase


class TokenService:
    def __init__(self, db=None):
        self.db = db if db is not None else SQLiteDatabase()

    async def generate_registration_token(self, user_id, expires_in_minutes=None):
        token = secrets.token_urlsafe(32)
        ttl = settings.REGISTRATION_TOKEN_TTL_SECONDS if expires_in_minutes is None else expires_in_minutes * 60
        await self.db.save_registration_token(token, user_id, ttl)
        return token

    def create_telegram_link(self, token, bot_username=None):
        return f"https://t.me/{bot_username or settings.BOT_USERNAME}?start={token}&startattach=reply"
