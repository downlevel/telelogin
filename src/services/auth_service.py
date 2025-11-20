"""
Authentication service
Handles login logic and bot notifications
"""
from typing import Optional, Dict
from src.database.base import DatabaseInterface
from src.services.token_service import TokenService
from src.utils.crypto import create_access_token
import logging

logger = logging.getLogger(__name__)

class AuthService:
    """Authentication service for login flow"""
    
    def __init__(self, db: DatabaseInterface):
        self.db = db
        self.token_service = TokenService()
    
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
        
        # TODO: Send Telegram notification to user
        # await self.send_login_notification(user.telegram_id, login_id)
        
        return {
            "login_id": login_id,
            "status": "pending"
        }
    
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
        await self.db.update_login_status(login_id, "approved")
        
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
        """
        login_request = await self.db.get_login_request(login_id)
        
        if not login_request:
            return None
        
        return {"status": login_request["status"]}
