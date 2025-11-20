"""
Token service
Manages registration and login tokens
"""
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict
from src.utils.crypto import create_signed_token, verify_signed_token
from src.config import settings
import logging

logger = logging.getLogger(__name__)

class TokenService:
    """Service for token management"""
    
    def __init__(self):
        self.tokens: Dict[str, dict] = {}  # In-memory storage, replace with Redis/DB in production
    
    def generate_registration_token(self, user_id: int, expires_in_minutes: int = 30) -> str:
        """
        Generate a signed registration token
        """
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now() + timedelta(minutes=expires_in_minutes)
        
        # Store token metadata
        self.tokens[token] = {
            "user_id": user_id,
            "type": "registration",
            "expires_at": expires_at,
            "used": False
        }
        
        # Create signed token
        signed_token = create_signed_token({
            "token": token,
            "user_id": user_id,
            "type": "registration"
        })
        
        return signed_token
    
    def verify_registration_token(self, signed_token: str) -> Optional[int]:
        """
        Verify registration token and return user_id
        """
        try:
            payload = verify_signed_token(signed_token)
            if not payload:
                return None
            
            token = payload.get("token")
            token_type = payload.get("type")
            
            if token_type != "registration":
                logger.warning("Invalid token type")
                return None
            
            # Check token metadata
            token_data = self.tokens.get(token)
            if not token_data:
                logger.warning("Token not found")
                return None
            
            if token_data["used"]:
                logger.warning("Token already used")
                return None
            
            if datetime.now() > token_data["expires_at"]:
                logger.warning("Token expired")
                return None
            
            # Mark as used
            token_data["used"] = True
            
            return token_data["user_id"]
        
        except Exception as e:
            logger.error(f"Error verifying token: {e}")
            return None
    
    def create_telegram_link(self, token: str, bot_username: str = "YourBot") -> str:
        """
        Create Telegram deep link with token
        """
        return f"https://t.me/{bot_username}?start={token}"
