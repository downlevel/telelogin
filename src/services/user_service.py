"""
User service
Handles user profile operations
"""
from typing import Optional
from src.database.base import DatabaseInterface
from src.models.user import User
import logging

logger = logging.getLogger(__name__)

class UserService:
    """Service for user management"""
    
    def __init__(self, db: DatabaseInterface):
        self.db = db
    
    async def create_user(self, username: str) -> Optional[User]:
        """
        Create a new user
        """
        try:
            # Check if user already exists
            existing_user = await self.db.get_user_by_username(username)
            if existing_user:
                logger.warning(f"User already exists: {username}")
                return None
            
            user = await self.db.create_user(username)
            logger.info(f"Created new user: {username}")
            return user
        except Exception as e:
            logger.error(f"Error creating user {username}: {e}")
            return None
    
    async def get_user(self, username: str) -> Optional[User]:
        """
        Get user by username
        """
        return await self.db.get_user_by_username(username)
    
    async def get_user_by_telegram(self, telegram_id: int) -> Optional[User]:
        """
        Get user by Telegram ID
        """
        return await self.db.get_user_by_telegram_id(telegram_id)
    
    async def link_telegram(self, user_id: int, telegram_id: int) -> bool:
        """
        Link Telegram account to user
        """
        try:
            # Check if telegram_id is already linked
            existing_user = await self.db.get_user_by_telegram_id(telegram_id)
            if existing_user and existing_user.id != user_id:
                logger.warning(f"Telegram ID {telegram_id} already linked to another user")
                return False
            
            await self.db.link_telegram_id(user_id, telegram_id)
            logger.info(f"Linked Telegram ID {telegram_id} to user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error linking Telegram: {e}")
            return False
