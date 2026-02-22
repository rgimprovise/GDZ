"""
Bot configuration using pydantic-settings.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Bot settings loaded from environment variables."""
    
    # Core
    env: str = "local"
    
    # Redis
    redis_url: str = "redis://localhost:6379/0"
    
    # Telegram
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    telegram_tma_bot_username: str = ""
    
    # API
    base_url: str = "http://localhost:8000"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
