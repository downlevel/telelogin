"""
Configuration management
Loads environment variables and application settings
"""
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Bot configuration
    BOT_TOKEN: str
    BOT_USERNAME: str = "YourBot"  # Telegram bot username (without @)

    # Database configuration (SQLite only)
    DB_URL: str = "sqlite:///db.sqlite3"

    # Security
    SECRET_KEY: str = Field(min_length=32)
    INTERNAL_API_KEY: str = Field(min_length=32)
    CORS_ORIGINS: list[str] = []
    LOGIN_REQUEST_TTL_SECONDS: int = Field(default=120, gt=0)
    REGISTRATION_TOKEN_TTL_SECONDS: int = Field(default=1800, gt=0)
    RATE_LIMIT_WINDOW_SECONDS: int = Field(default=600, gt=0)
    RATE_LIMIT_USERNAME: int = Field(default=5, gt=0)
    RATE_LIMIT_IP: int = Field(default=20, gt=0)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Application
    DEBUG: bool = False

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
