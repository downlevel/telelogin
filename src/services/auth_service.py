"""Authentication and background bot notifications."""
import logging
from datetime import datetime, timezone
import httpx
from src.config import settings

logger = logging.getLogger(__name__)

class AuthService:
    def __init__(self, db):
        self.db = db

    async def start_login(self, username, background_tasks, ip="unknown", user_agent=""):
        login_id, code, user = await self.db.start_request(username, ip, user_agent)
        if user:
            background_tasks.add_task(self.send_login_notification, user['telegram_id'], login_id, username, code, datetime.now(timezone.utc).isoformat(), ip, user_agent[:200])
        return {'login_id':login_id,'status':'pending','verification_code':code}

    async def send_login_notification(self, telegram_id, login_id, username, verification_code, requested_at, ip, user_agent, app_name=None):
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(settings.BOT_NOTIFY_URL, headers={'X-Internal-Key':settings.INTERNAL_API_KEY}, json=dict(telegram_id=telegram_id,login_id=login_id,username=username,verification_code=verification_code,requested_at=requested_at,ip=ip,user_agent=user_agent,app_name=app_name))
                response.raise_for_status()
        except Exception:
            logger.warning('Login notification failed')

    async def confirm_login(self, login_id, telegram_id, verification_code):
        return await self.db.approve(login_id, telegram_id, verification_code)

    async def get_login_status(self, login_id):
        return await self.db.take_login_status(login_id)
