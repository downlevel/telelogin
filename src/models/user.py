"""
User model definition
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class User:
    """User data model"""
    id: int
    username: str
    telegram_id: Optional[int] = None
    created_at: Optional[datetime] = None
    linked_at: Optional[datetime] = None
    
    def is_linked(self) -> bool:
        """Check if user has linked Telegram account"""
        return self.telegram_id is not None
