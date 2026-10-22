"""Authentication and background bot notifications."""
import logging

import httpx

from src.config import settings
from src.utils.crypto import create_access_token

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(self, db):
        self.db = db

    async def start_login(self, username, background_tasks):
        user = await self.db.get_user_by_username(username)
        # Reserved ID 0 has no user and can never match a Telegram owner.
        linked = user is not None and user.telegram_id is not None
        login_id = await self.db.create_login_request(user.id if linked else 0)
        if linked:
            background_tasks.add_task(self.send_login_notification, user.telegram_id, login_id, username)
        return {"login_id": login_id, "status": "pending"}

    async def send_login_notification(self, telegram_id, login_id, username):
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(settings.BOT_NOTIFY_URL, headers={"X-Internal-Key": settings.INTERNAL_API_KEY}, json={"telegram_id": telegram_id, "login_id": login_id, "username": username})
                response.raise_for_status()
        except Exception:
            logger.warning("Login notification failed")

    async def confirm_login(self, login_id, telegram_id):
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if user is None:
            return None
        token = create_access_token({"sub": user.username, "user_id": user.id})
        if not await self.db.update_login_status(login_id, "approved", token, telegram_id):
            return None
        return {"status": "authenticated", "session_token": token}

    async def get_login_status(self, login_id):
        return await self.db.take_login_status(login_id)
