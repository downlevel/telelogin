"""
Token model and management
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

@dataclass
class RegistrationToken:
    """Registration token for linking Telegram account"""
    token: str
    user_id: int
    created_at: datetime
    expires_at: datetime
    used: bool = False
    
    def is_valid(self) -> bool:
        """Check if token is still valid"""
        return not self.used and datetime.now() < self.expires_at
    
    def is_expired(self) -> bool:
        """Check if token has expired"""
        return datetime.now() >= self.expires_at

@dataclass
class LoginRequest:
    """Login request model"""
    id: str
    user_id: int
    status: str  # pending, approved, denied, expired
    created_at: datetime
    
    def is_pending(self) -> bool:
        """Check if login is pending"""
        return self.status == "pending"
