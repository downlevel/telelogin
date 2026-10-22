"""
Configuration management
Loads environment variables and application settings
"""
from pydantic import Field, model_validator
from urllib.parse import urlsplit, urlunsplit
import ipaddress
import tldextract
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_TTL_DAYS: int = Field(default=30, gt=0)
    LOGIN_HISTORY_RETENTION_DAYS: int = Field(default=30, gt=0)
    PURGE_INTERVAL_SECONDS: float = Field(default=3600, gt=0)

    PUBLIC_URL: str = "http://localhost:8000"
    SSO_COOKIE_NAME: str = "tl_sso"
    SSO_COOKIE_SECURE: bool = True
    SSO_COOKIE_DOMAIN: str = ""
    REGISTRATION_MODE: str = "open"

    @model_validator(mode="after")
    def validate_sso(self):
        url = urlsplit(self.PUBLIC_URL)
        if (url.scheme not in ("http", "https") or not url.hostname or url.username
                or url.password or url.query or url.fragment or "\\" in self.PUBLIC_URL):
            raise ValueError("PUBLIC_URL must be an absolute http(s) URL without credentials, query or fragment")
        url.port  # Reject invalid ports.
        self.PUBLIC_URL = urlunsplit((url.scheme, url.netloc.lower(), url.path.rstrip("/"), "", ""))
        if self.REGISTRATION_MODE not in ("open", "closed"):
            raise ValueError("REGISTRATION_MODE must be open or closed")
        domain = self.SSO_COOKIE_DOMAIN
        if domain:
            try:
                ipaddress.ip_address(domain)
                is_ip = True
            except ValueError:
                is_ip = False
            extract = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True)
            if (domain != domain.lower() or domain.startswith(".") or domain.endswith(".")
                    or "." not in domain or is_ip or not extract(domain).domain
                    or any(not part or not all(c.isascii() and (c.isalnum() or c == "-") for c in part) for part in domain.split("."))
                    or not (url.hostname == domain or url.hostname.endswith("." + domain))):
                raise ValueError("SSO_COOKIE_DOMAIN must be a non-public parent domain of PUBLIC_URL, without a leading dot or IP address")
        return self

    # Application
    DEBUG: bool = False

    API_PORT: int = 8000
    FORWARDED_ALLOW_IPS: str = "127.0.0.1"
    API_BASE_URL: str = "http://api:8000"
    BOT_NOTIFY_URL: str = "http://bot:8001/notify-login"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

settings = Settings()
