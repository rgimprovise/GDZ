"""
Bot configuration using pydantic-settings.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    env: str = "local"

    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    telegram_tma_bot_username: str = ""

    base_url: str = "http://localhost:8000"
    api_internal_url: str = "http://api:8000"
    tma_url: str = "https://t.me/YourBotUsername/app"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
