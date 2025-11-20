"""
Abstract database interface
Defines CRUD operations for users and login requests
"""
from abc import ABC, abstractmethod
from typing import Optional, List
from src.models.user import User

class DatabaseInterface(ABC):
    """Abstract base class for database operations"""
    
    @abstractmethod
    async def create_user(self, username: str) -> User:
        """Create a new user"""
        pass
    
    @abstractmethod
    async def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username"""
        pass
    
    @abstractmethod
    async def get_user_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        """Get user by Telegram ID"""
        pass
    
    @abstractmethod
    async def link_telegram_id(self, user_id: int, telegram_id: int) -> bool:
        """Link Telegram ID to user"""
        pass
    
    @abstractmethod
    async def create_login_request(self, user_id: int) -> str:
        """Create a login request and return login_id"""
        pass
    
    @abstractmethod
    async def get_login_request(self, login_id: str) -> Optional[dict]:
        """Get login request by ID"""
        pass
    
    @abstractmethod
    async def update_login_status(self, login_id: str, status: str) -> bool:
        """Update login request status"""
        pass
