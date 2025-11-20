"""
Configuration management
Loads environment variables and application settings
"""
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Bot configuration
    BOT_TOKEN: str
    BOT_USERNAME: str = "YourBot"  # Telegram bot username (without @)
    
    # Database configuration (SQLite only)
    DB_URL: str = "sqlite:///db.sqlite3"
    
    # Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Application
    DEBUG: bool = False
    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
