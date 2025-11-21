"""
Authentication service
Handles login logic and bot notifications
"""
from typing import Optional, Dict
from src.database.base import DatabaseInterface
from src.services.token_service import TokenService
from src.utils.crypto import create_access_token
import logging
import httpx
from src.config import settings

logger = logging.getLogger(__name__)

class AuthService:
    """Authentication service for login flow"""
    
    def __init__(self, db: DatabaseInterface):
        self.db = db
        self.token_service = TokenService()
        self.bot_notification_url = None  # Will be set if needed
    
    async def start_login(self, username: str) -> Optional[Dict[str, str]]:
        """
        Start login process for a user
        Returns login_id and status
        """
        user = await self.db.get_user_by_username(username)
        
        if not user:
            logger.warning(f"Login attempt for non-existent user: {username}")
            return None
        
        if not user.telegram_id:
            logger.warning(f"User {username} has not linked Telegram account")
            return None
        
        # Create login request
        login_id = await self.db.create_login_request(user.id)
        
        # Send Telegram notification to user
        try:
            await self.send_login_notification(user.telegram_id, login_id, username)
        except Exception as e:
            logger.error(f"Failed to send login notification: {e}")
        
        return {
            "login_id": login_id,
            "status": "pending"
        }
    
    async def send_login_notification(self, telegram_id: int, login_id: str, username: str):
        """
        Send login notification via bot HTTP endpoint
        """
        bot_url = f"http://bot:8001/notify-login"
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    bot_url,
                    json={
                        "telegram_id": telegram_id,
                        "login_id": login_id,
                        "username": username
                    },
                    timeout=5.0
                )
                
                if response.status_code == 200:
                    logger.info(f"Login notification sent successfully to telegram_id={telegram_id}")
                else:
                    logger.error(f"Failed to send notification: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Error sending login notification: {e}", exc_info=True)
    
    async def confirm_login(self, login_id: str, telegram_id: int) -> Optional[Dict[str, str]]:
        """
        Confirm login request
        Returns authentication token
        """
        login_request = await self.db.get_login_request(login_id)
        
        if not login_request:
            logger.warning(f"Invalid login request: {login_id}")
            return None
        
        if login_request["status"] != "pending":
            logger.warning(f"Login request {login_id} is not pending")
            return None
        
        # Verify telegram_id matches user
        user = await self.db.get_user_by_telegram_id(telegram_id)
        
        if not user or user.id != login_request["user_id"]:
            logger.warning(f"Telegram ID mismatch for login {login_id}")
            await self.db.update_login_status(login_id, "denied")
            return None
        
        # Update status to approved
        await self.db.update_login_status(login_id, "approved", access_token)
        
        # Generate session token
        access_token = create_access_token(
            data={"sub": user.username, "user_id": user.id}
        )
        
        return {
            "status": "authenticated",
            "session_token": access_token
        }
    
    async def get_login_status(self, login_id: str) -> Optional[Dict[str, str]]:
        """
        Get status of login request
        Returns status and session_token if approved
        """
        login_request = await self.db.get_login_request(login_id)
        
        if not login_request:
            return None
        
        result = {"status": login_request["status"]}
        
        # Include session token if login was approved
        if login_request["status"] == "approved" and login_request.get("session_token"):
            result["session_token"] = login_request["session_token"]
        
        return result
